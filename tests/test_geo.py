"""Tests de las utilidades geoespaciales compartidas (src/analysis/geo.py)."""

import pytest

from src.analysis.geo import bearing_deg, destination_point, haversine_distance_m


def test_haversine_distance_same_point_is_zero():
    assert haversine_distance_m(47.3769, 8.5417, 47.3769, 8.5417) == 0.0


def test_haversine_distance_known_value():
    # 1 grado de latitud equivale a ~111.32 km en meridianos; se usa una
    # tolerancia amplia porque la formula es esferica, no exacta (WGS84 real).
    distance = haversine_distance_m(0.0, 0.0, 1.0, 0.0)
    assert 110_000 < distance < 112_000


def test_bearing_north_is_zero():
    # Moverse solo en latitud (misma longitud) hacia el norte = rumbo 0.
    assert bearing_deg(47.0, 8.0, 48.0, 8.0) == pytest.approx(0.0, abs=0.5)


def test_bearing_east_is_90():
    assert bearing_deg(47.0, 8.0, 47.0, 9.0) == pytest.approx(90.0, abs=1.0)


def test_destination_point_round_trip():
    """Ir de A a B y luego proyectar desde A con la distancia/rumbo reales debe devolver B."""
    lat1, lon1 = 47.3769, 8.5417
    lat2, lon2 = 47.3800, 8.5500

    distance = haversine_distance_m(lat1, lon1, lat2, lon2)
    bearing = bearing_deg(lat1, lon1, lat2, lon2)

    result_lat, result_lon = destination_point(lat1, lon1, bearing, distance)

    assert result_lat == pytest.approx(lat2, abs=1e-4)
    assert result_lon == pytest.approx(lon2, abs=1e-4)
