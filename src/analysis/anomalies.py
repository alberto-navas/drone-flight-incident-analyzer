"""
Deteccion de anomalias por reglas sobre la serie temporal ya normalizada.

A diferencia de los eventos que los propios parsers extraen directamente del
log (p.ej. un MODE de ArduPilot o un logged_message de PX4), estos son
eventos DERIVADOS: los calculamos nosotros a partir de la telemetria
continua. Por eso viven en su propio modulo, agnostico de formato, y se
ejecutan siempre despues del parseo, sobre un FlightLog ya construido.

Cada detector es deliberadamente una regla simple y explicable (no una caja
negra de ML) porque en un contexto forense/de incidentes lo que importa es
poder justificar *por que* se marco un evento, no solo que se marco.
"""

from ..parsers.base import FlightEvent, FlightLog
from .geo import haversine_distance_m

# --- Umbrales por defecto -----------------------------------------------
# Se exponen como constantes (no hardcodeados dentro de las funciones) para
# que se puedan ajustar sin tocar la logica, y para documentar en un solo
# sitio de donde sale cada uno.

# Velocidad horizontal maxima plausible entre dos muestras GPS consecutivas.
# Un salto que implique una velocidad mayor es casi con certeza un glitch de
# GPS, no un movimiento real del vehiculo. 60 m/s (~216 km/h) es generoso
# incluso para un dron rapido, precisamente para minimizar falsos positivos.
_MAX_PLAUSIBLE_SPEED_MS = 60.0

# Velocidad vertical de descenso a partir de la cual consideramos que puede
# tratarse de una caida/impacto en vez de un descenso controlado normal.
_IMPACT_DESCENT_RATE_MS = 8.0

# Caida de voltaje de bateria (voltios por segundo) que consideramos
# anormalmente rapida, indicativa de fallo de celda o cortocircuito en vez
# de descarga normal por consumo.
_CRITICAL_VOLTAGE_DROP_RATE = 0.5

# Umbral de señal RC por debajo del cual, si el formato reporta 0-100,
# consideramos que el enlace esta en riesgo. No aplica a formatos que
# reportan RSSI en dBm (valores negativos): ver comentario en la funcion.
_LOW_RC_SIGNAL_THRESHOLD = 15.0

# Separacion temporal por debajo de la cual dos eventos consecutivos de la
# misma categoria se consideran parte del MISMO episodio en vez de sucesos
# independientes. Necesario porque los detectores de condicion sostenida
# (descenso brusco, glitch de GPS) evaluan cada par de muestras, y mientras
# la condicion se mantiene generarian un evento casi identico por muestra.
_EPISODE_MERGE_GAP_SECONDS = 1.0

# Orden de severidad, usado para quedarse con la PEOR severidad presente al
# fusionar un episodio (ver consolidate_episodes). En los detectores de
# anomalies.py todos los miembros de un episodio comparten severidad, asi
# que esto no cambia nada ahi; pero en ml_anomalies.py un mismo episodio
# puede mezclar puntos "warning" y un unico punto "critical" (el mas
# anomalo del vuelo), y descartar ese matiz seria perder informacion.
_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


def consolidate_episodes(events: list[FlightEvent]) -> list[FlightEvent]:
    """
    Fusiona eventos consecutivos de la misma categoria en un unico episodio.

    Sin esto, un descenso brusco sostenido 3 segundos generaria una fila por
    cada par de muestras en el informe (repetitivo e ilegible). Con esto,
    ese mismo descenso se muestra como un unico evento que cubre todo el
    episodio, con su duracion y numero de muestras afectadas.
    """
    if not events:
        return []

    events = sorted(events, key=lambda e: e.timestamp)
    episodes = [[events[0]]]
    for event in events[1:]:
        if event.timestamp - episodes[-1][-1].timestamp <= _EPISODE_MERGE_GAP_SECONDS:
            episodes[-1].append(event)
        else:
            episodes.append([event])

    merged = []
    for episode in episodes:
        first, last = episode[0], episode[-1]
        if len(episode) == 1:
            merged.append(first)
            continue
        worst_severity = max((e.severity for e in episode), key=lambda s: _SEVERITY_RANK[s])
        merged.append(
            FlightEvent(
                timestamp=first.timestamp,
                category=first.category,
                severity=worst_severity,
                description=(
                    f"{first.description} — sostenido durante "
                    f"{last.timestamp - first.timestamp:.1f}s ({len(episode)} muestras)"
                ),
                method=first.method,
            )
        )
    return merged


def detect_gps_glitches(flight_log: FlightLog) -> list[FlightEvent]:
    """
    Marca saltos de posicion GPS fisicamente implausibles entre muestras consecutivas.

    No mira la posicion absoluta (podria estar bien) sino la velocidad
    IMPLICADA por el salto entre dos puntos consecutivos: si para llegar de
    un punto a otro en el tiempo transcurrido habria que ir a mas de
    _MAX_PLAUSIBLE_SPEED_MS, es mas probable que sea ruido del receptor GPS
    que un movimiento real.
    """
    events = []
    geo_records = [r for r in flight_log.sorted_records() if r.lat is not None and r.lon is not None]

    for prev, curr in zip(geo_records, geo_records[1:], strict=False):
        dt = curr.timestamp - prev.timestamp
        if dt <= 0:
            continue
        # geo_records ya esta filtrada por lat/lon is not None; el assert
        # solo lo declara para mypy (los campos son Optional a nivel de
        # tipo porque no TODOS los FlightRecord los traen, ver base.py).
        assert prev.lat is not None and prev.lon is not None
        assert curr.lat is not None and curr.lon is not None
        distance = haversine_distance_m(prev.lat, prev.lon, curr.lat, curr.lon)
        implied_speed = distance / dt
        if implied_speed > _MAX_PLAUSIBLE_SPEED_MS:
            events.append(
                FlightEvent(
                    timestamp=curr.timestamp,
                    category="gps_glitch",
                    severity="warning",
                    description=(
                        f"Salto de posicion GPS implica velocidad de {implied_speed:.1f} m/s "
                        f"(umbral: {_MAX_PLAUSIBLE_SPEED_MS} m/s); probable glitch de receptor, no movimiento real."
                    ),
                )
            )
    return consolidate_episodes(events)


def detect_rapid_descents(flight_log: FlightLog) -> list[FlightEvent]:
    """
    Marca descensos de altitud anormalmente rapidos, candidatos a caida/impacto.

    Se calcula la velocidad vertical entre muestras de altitud consecutivas
    (que ya vienen del mismo sensor/topico, para no mezclar ruido de fuentes
    distintas). Un descenso sostenido por encima del umbral es la señal mas
    directa disponible de un posible impacto sin necesitar acelerometro.
    """
    events = []
    alt_records = [r for r in flight_log.sorted_records() if r.alt is not None]

    for prev, curr in zip(alt_records, alt_records[1:], strict=False):
        dt = curr.timestamp - prev.timestamp
        if dt <= 0:
            continue
        assert prev.alt is not None and curr.alt is not None  # ver comentario equivalente en detect_gps_glitches
        vertical_rate = (curr.alt - prev.alt) / dt  # negativo = descendiendo
        if vertical_rate < -_IMPACT_DESCENT_RATE_MS:
            events.append(
                FlightEvent(
                    timestamp=curr.timestamp,
                    category="possible_impact",
                    severity="critical",
                    description=(
                        f"Descenso de {abs(vertical_rate):.1f} m/s "
                        f"(umbral: {_IMPACT_DESCENT_RATE_MS} m/s); posible caida o perdida de control."
                    ),
                )
            )
    return consolidate_episodes(events)


def detect_battery_anomalies(flight_log: FlightLog) -> list[FlightEvent]:
    """
    Marca caidas de voltaje de bateria anormalmente rapidas.

    Se usa la TASA de caida (V/s) en vez de un voltaje absoluto minimo a
    proposito: el voltaje "normal" depende del numero de celdas de la
    bateria, que el log no siempre declara explicitamente, mientras que una
    caida brusca es anormal sea cual sea la quimica/tamaño de la bateria.
    """
    events = []
    batt_records = [r for r in flight_log.sorted_records() if r.battery_voltage is not None]

    for prev, curr in zip(batt_records, batt_records[1:], strict=False):
        dt = curr.timestamp - prev.timestamp
        if dt <= 0:
            continue
        # ver comentario equivalente en detect_gps_glitches
        assert prev.battery_voltage is not None and curr.battery_voltage is not None
        drop_rate = (prev.battery_voltage - curr.battery_voltage) / dt
        if drop_rate > _CRITICAL_VOLTAGE_DROP_RATE:
            events.append(
                FlightEvent(
                    timestamp=curr.timestamp,
                    category="battery_critical",
                    severity="critical",
                    description=(
                        f"Caida de voltaje de {drop_rate:.2f} V/s "
                        f"(umbral: {_CRITICAL_VOLTAGE_DROP_RATE} V/s); posible fallo de celda o cortocircuito."
                    ),
                )
            )
    return events


def detect_rc_signal_loss(flight_log: FlightLog) -> list[FlightEvent]:
    """
    Marca la transicion a señal de radiocontrol baja, cuando el formato la reporta en escala 0-100.

    Nota de diseño: algunos formatos (RSSI de ArduPilot en dBm) usan una
    escala distinta donde "bajo" significa un numero muy negativo, no
    cercano a 0. Para no generar falsos positivos por asumir la escala
    equivocada, esta regla solo actua sobre valores no negativos (0-100),
    que es la convencion mas comun (Betaflight rssi, PX4 input_rc.rssi).
    Los eventos de failsafe explicito de ArduPilot/Betaflight ya cubren la
    perdida de señal en las demas escalas, generados en el propio parser.
    """
    events = []
    rc_records = [r for r in flight_log.sorted_records() if r.rc_signal is not None and r.rc_signal >= 0]

    was_low = False
    for r in rc_records:
        assert r.rc_signal is not None  # ver comentario en detect_gps_glitches
        is_low = r.rc_signal < _LOW_RC_SIGNAL_THRESHOLD
        if is_low and not was_low:
            events.append(
                FlightEvent(
                    timestamp=r.timestamp,
                    category="rc_loss",
                    severity="warning",
                    description=f"Señal RC cayo a {r.rc_signal:.0f} (umbral: {_LOW_RC_SIGNAL_THRESHOLD})",
                )
            )
        was_low = is_low
    return events


def detect_anomalies(flight_log: FlightLog) -> list[FlightEvent]:
    """
    Ejecuta todos los detectores y añade sus hallazgos a flight_log.events.

    Punto de entrada unico del modulo: el CLI/report solo necesitan llamar a
    esta funcion despues de parsear el log, sin conocer los detectores
    individuales.
    """
    new_events = (
        detect_gps_glitches(flight_log)
        + detect_rapid_descents(flight_log)
        + detect_battery_anomalies(flight_log)
        + detect_rc_signal_loss(flight_log)
    )
    flight_log.events.extend(new_events)
    return new_events
