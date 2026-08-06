"""Tests de los detectores de anomalias por reglas (src/analysis/anomalies.py)."""

from src.analysis.anomalies import (
    consolidate_episodes,
    detect_battery_anomalies,
    detect_gps_glitches,
    detect_rapid_descents,
    detect_rc_signal_loss,
)
from src.parsers.base import FlightEvent, FlightLog, FlightRecord, Source


def test_clean_flight_triggers_no_anomalies(synthetic_flight_log):
    assert detect_gps_glitches(synthetic_flight_log) == []
    assert detect_rapid_descents(synthetic_flight_log) == []
    assert detect_battery_anomalies(synthetic_flight_log) == []
    assert detect_rc_signal_loss(synthetic_flight_log) == []


def test_gps_glitch_detected_on_implausible_jump():
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    log.records.append(FlightRecord(timestamp=0.0, lat=47.0, lon=8.0))
    # Salto de ~5.5 km en 1 segundo: muy por encima de cualquier velocidad plausible de dron.
    log.records.append(FlightRecord(timestamp=1.0, lat=47.05, lon=8.0))

    events = detect_gps_glitches(log)
    assert len(events) == 1
    assert events[0].category == "gps_glitch"


def test_rapid_descent_detected_above_threshold():
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    log.records.append(FlightRecord(timestamp=0.0, alt=50.0))
    log.records.append(FlightRecord(timestamp=1.0, alt=30.0))  # -20 m/s, por encima del umbral (8 m/s)

    events = detect_rapid_descents(log)
    assert len(events) == 1
    assert events[0].category == "possible_impact"
    assert events[0].severity == "critical"


def test_rapid_descent_not_triggered_for_normal_landing():
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    log.records.append(FlightRecord(timestamp=0.0, alt=2.0))
    log.records.append(FlightRecord(timestamp=1.0, alt=0.0))  # -2 m/s: descenso normal de aterrizaje

    assert detect_rapid_descents(log) == []


def test_battery_critical_drop_detected():
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    log.records.append(FlightRecord(timestamp=0.0, battery_voltage=12.6))
    log.records.append(FlightRecord(timestamp=1.0, battery_voltage=11.0))  # 1.6 V/s, por encima del umbral (0.5)

    events = detect_battery_anomalies(log)
    assert len(events) == 1
    assert events[0].category == "battery_critical"


def test_rc_signal_loss_detected_on_transition_to_low():
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    log.records.append(FlightRecord(timestamp=0.0, rc_signal=90.0))
    log.records.append(FlightRecord(timestamp=1.0, rc_signal=5.0))  # cruza el umbral (15.0)

    events = detect_rc_signal_loss(log)
    assert len(events) == 1
    assert events[0].category == "rc_loss"


def test_rc_signal_loss_ignores_negative_scale_values():
    """RSSI en dBm (negativo) no debe interpretarse con el umbral 0-100: ver docstring del detector."""
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    log.records.append(FlightRecord(timestamp=0.0, rc_signal=-40.0))
    log.records.append(FlightRecord(timestamp=1.0, rc_signal=-90.0))

    assert detect_rc_signal_loss(log) == []


def test_consolidate_episodes_merges_close_events_same_category():
    events = [
        FlightEvent(timestamp=0.0, category="gps_glitch", severity="warning", description="a"),
        FlightEvent(timestamp=0.5, category="gps_glitch", severity="warning", description="b"),
        FlightEvent(timestamp=0.9, category="gps_glitch", severity="warning", description="c"),
    ]
    merged = consolidate_episodes(events)
    assert len(merged) == 1
    assert merged[0].timestamp == 0.0
    assert "sostenido durante" in merged[0].description


def test_consolidate_episodes_keeps_worst_severity():
    """Un episodio que mezcla warning y critical debe quedar marcado critical, no con la severidad del primero."""
    events = [
        FlightEvent(timestamp=0.0, category="x", severity="warning", description="a"),
        FlightEvent(timestamp=0.3, category="x", severity="critical", description="b"),
        FlightEvent(timestamp=0.6, category="x", severity="warning", description="c"),
    ]
    merged = consolidate_episodes(events)
    assert len(merged) == 1
    assert merged[0].severity == "critical"


def test_consolidate_episodes_keeps_separate_when_gap_too_large():
    events = [
        FlightEvent(timestamp=0.0, category="x", severity="warning", description="a"),
        FlightEvent(timestamp=10.0, category="x", severity="warning", description="b"),
    ]
    merged = consolidate_episodes(events)
    assert len(merged) == 2
