"""Utilidades geoespaciales compartidas entre la deteccion de anomalias y el informe."""

import math

# Radio de la Tierra en metros, usado por Haversine. Aproximacion esferica:
# suficiente para las distancias de un vuelo de dron (no hace falta el
# modelo elipsoidal WGS84 completo para este caso de uso).
_EARTH_RADIUS_M = 6_371_000


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en metros entre dos puntos GPS (lat/lon en grados decimales)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))
