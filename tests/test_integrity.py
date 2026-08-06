"""Tests del modulo de verificacion de integridad (src/analysis/integrity.py)."""

from src.analysis.integrity import check_integrity
from src.parsers.base import FlightLog, FlightRecord, Source


def test_clean_log_has_no_findings(synthetic_flight_log):
    report = check_integrity(synthetic_flight_log)
    assert report.looks_clean
    assert report.findings == []


def test_time_reversal_detected():
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    for i in range(20):
        log.records.append(FlightRecord(timestamp=float(i), alt=50.0))
    # Insertado "a mano" fuera de orden temporal dentro del mismo flujo de 'alt'.
    log.records.append(FlightRecord(timestamp=5.0, alt=999.0))

    report = check_integrity(log)

    assert not report.looks_clean
    assert any(f.kind == "time_reversal" and f.field == "alt" for f in report.findings)


def test_suspicious_gap_detected():
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    for i in range(20):
        log.records.append(FlightRecord(timestamp=i * 0.1, alt=50.0))
    log.records.append(FlightRecord(timestamp=50.0, alt=50.0))  # hueco enorme frente a la cadencia de 0.1s

    report = check_integrity(log)

    assert not report.looks_clean
    assert any(f.kind == "suspicious_gap" for f in report.findings)


def test_too_few_samples_produces_no_gap_findings():
    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    log.records.append(FlightRecord(timestamp=0.0, alt=50.0))
    log.records.append(FlightRecord(timestamp=100.0, alt=50.0))

    report = check_integrity(log)
    assert report.looks_clean  # con <3 muestras, "la mediana" no significa nada: no se marca nada
