"""
Tests del modulo de estimacion de impacto (src/analysis/impact.py).

Los valores esperados de fisica (tiempo/velocidad de impacto) se validaron
primero a mano resolviendo la ecuacion de caida libre; aqui se fijan como
regresion para detectar si un cambio futuro rompe la cinematica.
"""

import pytest

from src.analysis.impact import estimate_impact
from src.parsers.base import FlightLog, FlightRecord, Source


def test_impact_estimated_for_steep_descent():
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    # 51m -> 50m en 0.1s cayendo (vz0=-10 m/s), moviendose ligeramente hacia el norte.
    log.records.append(FlightRecord(timestamp=0.0, lat=47.0, lon=8.0, alt=51.0))
    log.records.append(FlightRecord(timestamp=0.1, lat=47.000004, lon=8.0, alt=50.0))

    estimate = estimate_impact(log)

    assert estimate is not None
    # t = [-vz0 + sqrt(vz0^2 + 2*g*alt0)] / g, resuelto a mano: ~2.33s
    assert estimate.time_to_impact_s == pytest.approx(2.332, abs=0.01)
    assert estimate.vertical_speed_at_impact_ms == pytest.approx(32.88, abs=0.05)


def test_no_impact_estimated_for_normal_landing():
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    log.records.append(FlightRecord(timestamp=0.0, lat=47.0, lon=8.0, alt=1.5))
    log.records.append(FlightRecord(timestamp=0.5, lat=47.0, lon=8.0, alt=0.2))

    assert estimate_impact(log) is None


def test_no_impact_estimated_for_level_flight():
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    log.records.append(FlightRecord(timestamp=0.0, lat=47.0, lon=8.0, alt=50.0))
    log.records.append(FlightRecord(timestamp=0.5, lat=47.0001, lon=8.0, alt=50.1))

    assert estimate_impact(log) is None


def test_no_impact_estimated_with_insufficient_data():
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    log.records.append(FlightRecord(timestamp=0.0, lat=47.0, lon=8.0, alt=51.0))

    assert estimate_impact(log) is None


def test_kinetic_energy_only_computed_when_mass_given():
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    log.records.append(FlightRecord(timestamp=0.0, lat=47.0, lon=8.0, alt=51.0))
    log.records.append(FlightRecord(timestamp=0.1, lat=47.000004, lon=8.0, alt=50.0))

    without_mass = estimate_impact(log)
    assert without_mass.kinetic_energy_j is None

    with_mass = estimate_impact(log, mass_kg=1.5)
    expected_energy = 0.5 * 1.5 * with_mass.total_speed_at_impact_ms**2
    assert with_mass.kinetic_energy_j == pytest.approx(expected_energy, rel=1e-6)
