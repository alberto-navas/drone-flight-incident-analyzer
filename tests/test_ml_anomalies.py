"""Tests del detector de anomalias por Isolation Forest (src/analysis/ml_anomalies.py)."""

import random

from src.analysis.ml_anomalies import detect_ml_anomalies
from src.parsers.base import FlightLog, FlightRecord, Source


def _build_flight_with_outlier(outlier_start: int, outlier_end: int) -> FlightLog:
    """
    Vuelo de 300s a 2 Hz con ruido gaussiano pequeño alrededor de valores
    normales, y un tramo con un valor de roll claramente fuera de rango.
    Semilla fija: el test debe ser determinista.
    """
    rng = random.Random(42)
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    for i in range(600):
        t = i * 0.5
        alt = 50 + rng.gauss(0, 1)
        battery = 12.0 - t * 0.005 + rng.gauss(0, 0.05)
        roll = rng.gauss(0, 2)
        pitch = rng.gauss(0, 2)
        if outlier_start <= i <= outlier_end:
            roll = 60.0  # muy fuera del rango normal (~N(0, 2))
        log.records.append(FlightRecord(timestamp=t, alt=alt, battery_voltage=battery, roll=roll, pitch=pitch))
    return log


def test_deliberate_outlier_is_detected():
    log = _build_flight_with_outlier(400, 405)
    events = detect_ml_anomalies(log)

    assert len(events) > 0
    assert all(e.method == "ml" for e in events)
    # El tramo forzado (t=200-202.5s) debe caer dentro de alguno de los eventos detectados.
    assert any(abs(e.timestamp - 200.0) < 3.0 and "roll" in e.category for e in events)


def test_most_anomalous_point_is_marked_critical():
    log = _build_flight_with_outlier(400, 405)
    events = detect_ml_anomalies(log)

    critical_events = [e for e in events if e.severity == "critical"]
    assert len(critical_events) == 1  # solo el punto mas anomalo de TODO el vuelo
    assert "roll" in critical_events[0].category


def test_returns_empty_with_too_few_resampled_rows():
    """
    Un vuelo muy corto (pocos segundos) da menos de _MIN_SAMPLES_REQUIRED
    filas tras remuestrear, aunque tenga varias magnitudes disponibles.
    """
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    for i in range(8):
        log.records.append(FlightRecord(timestamp=float(i), alt=50.0, battery_voltage=12.0 - i * 0.01))

    assert detect_ml_anomalies(log) == []


def test_clean_flight_may_flag_a_small_fraction_but_never_crashes(synthetic_flight_log):
    """
    Isolation Forest con `contamination` fijo SIEMPRE marca ~ese porcentaje
    de puntos como anomalos, incluso en datos limpios (es una propiedad del
    algoritmo, no un bug): no hay garantia de "cero falsos positivos" en
    vuelos cortos. Lo unico que se puede afirmar es que no revienta y que,
    si marca algo, es una fraccion pequeña, consistente con `_CONTAMINATION`.
    """
    events = detect_ml_anomalies(synthetic_flight_log)
    assert len(events) <= max(1, round(len(synthetic_flight_log.records) * 0.05))


def test_returns_empty_with_single_feature():
    """Con una sola magnitud numerica no hay 'patron conjunto' que buscar."""
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    for i in range(100):
        log.records.append(FlightRecord(timestamp=i * 0.5, alt=50.0 + i * 0.01))
    assert detect_ml_anomalies(log) == []
