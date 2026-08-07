"""
Estimacion del punto y velocidad de impacto cuando el log se corta en pleno vuelo.

Escenario real que motiva este modulo: cuando un dron choca, normalmente
pierde alimentacion (y por tanto deja de grabar) EN EL MOMENTO del impacto o
un instante antes, no despues. Eso significa que el log casi nunca contiene
la muestra del propio impacto: contiene la trayectoria hasta justo antes.
Este modulo coge esa ultima trayectoria conocida y la proyecta hacia
adelante con cinematica basica (velocidad + gravedad) para estimar donde y
como termino el vuelo.

Es, deliberadamente, una estimacion simple y explicable (las mismas
matematicas de caida libre que se enseñan en un curso de fisica de
bachillerato), no un modelo aerodinamico completo. Cada resultado se
acompaña de una lista de asunciones explicitas para que quien lea el
informe sepa exactamente cuanto puede fiarse del numero.
"""

import math
from dataclasses import dataclass

from ..parsers.base import FlightLog
from .geo import bearing_deg, destination_point, haversine_distance_m

# Aceleracion de la gravedad, m/s^2.
_G = 9.81

# Velocidad de descenso minima (m/s) en la ultima muestra para considerar
# que tiene sentido proyectar un impacto. Es mas permisivo que el umbral de
# "possible_impact" de anomalies.py (8 m/s) porque aqui no se esta
# clasificando el vuelo entero como anomalo, solo decidiendo si el ultimo
# tramo conocido describe una caida en vez de un vuelo nivelado o un
# aterrizaje controlado.
_MIN_DESCENT_FOR_EXTRAPOLATION_MS = 3.0

# Altura minima (m, relativa al punto de despegue) que debe tener la ultima
# muestra para intentar la extrapolacion. Si el log termina ya casi a nivel
# de despegue, lo mas probable es un aterrizaje normal, no un corte abrupto.
_MIN_ALTITUDE_FOR_EXTRAPOLATION_M = 2.0


@dataclass
class ImpactEstimate:
    """
    Resultado de proyectar el ultimo tramo de vuelo conocido hasta nivel del suelo.

    Todos los campos numericos son una PROYECCION fisica, no una medida
    directa del log (el log no llega a registrar el impacto). `assumptions`
    documenta bajo que condiciones es valida esta proyeccion.
    """

    last_known_timestamp: float
    time_to_impact_s: float
    impact_timestamp: float
    lat: float
    lon: float
    horizontal_distance_m: float
    vertical_speed_at_impact_ms: float
    horizontal_speed_ms: float
    total_speed_at_impact_ms: float
    kinetic_energy_j: float | None
    assumptions: list[str]
    # Claves de src/report/i18n.py:ASSUMPTION_MESSAGES equivalentes a `assumptions`, en el mismo
    # orden, para poder re-renderizar la lista en otro idioma al generar el informe.
    assumption_keys: list[str]


def estimate_impact(flight_log: FlightLog, mass_kg: float | None = None) -> ImpactEstimate | None:
    """
    Intenta estimar el punto de impacto a partir del final del log.

    Devuelve None cuando no hay datos suficientes o cuando el patron final
    del vuelo no sugiere una caida (p.ej. el log termina con el dron ya
    parado en el suelo, un aterrizaje normal). No forzamos una estimacion
    en esos casos: es preferible no dar un numero a dar uno que no
    corresponde a un incidente real.
    """
    # Se necesitan muestras con posicion Y altitud a la vez: en los tres
    # formatos soportados, ambas vienen del mismo mensaje GPS, asi que en la
    # practica esto no descarta datos que si tendrian altitud por separado.
    geo_alt_records = [
        r for r in flight_log.sorted_records() if r.lat is not None and r.lon is not None and r.alt is not None
    ]
    if len(geo_alt_records) < 2:
        return None

    anchor = geo_alt_records[-1]
    prev = geo_alt_records[-2]

    dt = anchor.timestamp - prev.timestamp
    if dt <= 0:
        return None

    # geo_alt_records ya esta filtrada por lat/lon/alt is not None; el
    # assert solo lo declara para mypy (son Optional a nivel de tipo porque
    # no todos los FlightRecord los traen, ver parsers/base.py).
    assert anchor.lat is not None and anchor.lon is not None and anchor.alt is not None
    assert prev.lat is not None and prev.lon is not None and prev.alt is not None

    vertical_speed = (anchor.alt - prev.alt) / dt  # negativo = descendiendo
    horizontal_distance_between = haversine_distance_m(prev.lat, prev.lon, anchor.lat, anchor.lon)
    horizontal_speed = horizontal_distance_between / dt
    heading = bearing_deg(prev.lat, prev.lon, anchor.lat, anchor.lon)

    if anchor.alt < _MIN_ALTITUDE_FOR_EXTRAPOLATION_M:
        return None
    if vertical_speed > -_MIN_DESCENT_FOR_EXTRAPOLATION_MS:
        return None

    # Cinematica de caida libre: altura(t) = alt0 + vz0*t - 0.5*g*t^2
    # Se busca el primer instante t>0 en que altura(t) vuelve a 0 (nivel del
    # punto de despegue, ver asuncion de terreno llano mas abajo).
    a_coef, b_coef, c_coef = -0.5 * _G, vertical_speed, anchor.alt
    discriminant = b_coef * b_coef - 4 * a_coef * c_coef
    if discriminant < 0:
        return None  # no deberia ocurrir con c_coef > 0, pero se comprueba por seguridad numerica

    sqrt_disc = math.sqrt(discriminant)
    roots = [(-b_coef + sqrt_disc) / (2 * a_coef), (-b_coef - sqrt_disc) / (2 * a_coef)]
    positive_roots = [t for t in roots if t > 0]
    if not positive_roots:
        return None
    time_to_impact = min(positive_roots)  # la primera vez que cruza el nivel del suelo

    vertical_speed_at_impact = vertical_speed - _G * time_to_impact
    horizontal_distance_to_impact = horizontal_speed * time_to_impact
    impact_lat, impact_lon = destination_point(anchor.lat, anchor.lon, heading, horizontal_distance_to_impact)
    total_speed = math.hypot(horizontal_speed, vertical_speed_at_impact)

    assumptions = [
        "Terreno llano a la misma altitud que el punto de despegue: en terreno con desnivel "
        "(relevante en entornos alpinos) el punto real de impacto puede estar antes o despues del estimado.",
        "Trayectoria balistica simple (solo gravedad) desde la ultima muestra conocida: no se modela "
        "resistencia del aire ni posibles maniobras del piloto/autopiloto tras el corte del log.",
        "Velocidad horizontal y rumbo constantes desde la ultima muestra hasta el impacto.",
    ]
    assumption_keys = ["terrain_flat", "ballistic_simple", "constant_heading"]
    kinetic_energy = None
    if mass_kg is not None:
        kinetic_energy = 0.5 * mass_kg * total_speed**2
    else:
        assumptions.append("No se proporciono la masa del vehiculo: no se calcula energia de impacto.")
        assumption_keys.append("no_mass")

    return ImpactEstimate(
        last_known_timestamp=anchor.timestamp,
        time_to_impact_s=time_to_impact,
        impact_timestamp=anchor.timestamp + time_to_impact,
        lat=impact_lat,
        lon=impact_lon,
        horizontal_distance_m=horizontal_distance_to_impact,
        vertical_speed_at_impact_ms=abs(vertical_speed_at_impact),
        horizontal_speed_ms=horizontal_speed,
        total_speed_at_impact_ms=total_speed,
        kinetic_energy_j=kinetic_energy,
        assumptions=assumptions,
        assumption_keys=assumption_keys,
    )
