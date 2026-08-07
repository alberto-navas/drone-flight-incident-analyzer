"""Utilidades geoespaciales compartidas entre la deteccion de anomalias y el informe."""

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..parsers.base import FlightRecord

# Radio de la Tierra en metros, usado por Haversine. Aproximacion esferica:
# suficiente para las distancias de un vuelo de dron (no hace falta el
# modelo elipsoidal WGS84 completo para este caso de uso).
_EARTH_RADIUS_M = 6_371_000


def extract_geo_points(records: "list[FlightRecord]") -> list[tuple[float, float]]:
    """
    (lat, lon) de los records que traen ambos campos, en el mismo orden.

    Centraliza un filtro que se repetia identico en varios modulos
    (trayectoria, mapa combinado de flota, resumen de distancia). De paso
    resuelve, para mypy, el "narrowing" de lat/lon de `float | None` a
    `float`: son Optional a nivel de tipo porque no todos los FlightRecord
    los traen (ver parsers/base.py), pero dentro de esta misma comprension
    mypy si sabe que el filtro garantiza que no son None.
    """
    return [(r.lat, r.lon) for r in records if r.lat is not None and r.lon is not None]


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en metros entre dos puntos GPS (lat/lon en grados decimales)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Rumbo inicial (0-360, 0=norte) para ir del punto 1 al punto 2 por el camino mas corto."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def destination_point(lat: float, lon: float, bearing: float, distance_m: float) -> tuple[float, float]:
    """
    Punto de destino al recorrer `distance_m` metros con rumbo `bearing` desde (lat, lon).

    Es la operacion inversa de haversine_distance_m + bearing_deg: en vez de
    medir la distancia/rumbo entre dos puntos conocidos, aqui se parte de un
    punto, una direccion y una distancia, y se calcula donde se termina.
    Se usa para proyectar la posicion de impacto en src/analysis/impact.py.
    """
    delta = distance_m / _EARTH_RADIUS_M
    theta = math.radians(bearing)
    phi1 = math.radians(lat)
    lambda1 = math.radians(lon)

    phi2 = math.asin(math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta))
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    return math.degrees(phi2), math.degrees(lambda2)
