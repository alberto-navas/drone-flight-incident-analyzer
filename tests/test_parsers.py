"""
Tests de los cuatro parsers contra fixtures reales/realistas (tests/fixtures/).

Se comprueban propiedades estructurales (cuenta de registros, presencia de
campos esperados) en vez de valores exactos, porque los fixtures son datos
de vuelo reales (ArduPilot/PX4) cuyo contenido exacto no es el objeto de
prueba — lo que se quiere validar es que el parser los interpreta sin
romperse y produce un FlightLog coherente con el modelo comun.
"""

from src.parsers.ardupilot import parse_ardupilot_log
from src.parsers.base import Source
from src.parsers.betaflight import parse_betaflight_csv
from src.parsers.dji_srt import parse_dji_srt
from src.parsers.px4 import parse_px4_log


def test_parse_ardupilot_produces_records_and_events(fixtures_dir):
    log = parse_ardupilot_log(str(fixtures_dir / "mini_ardupilot.bin"))

    assert log.source == Source.ARDUPILOT
    assert len(log.records) > 0
    assert any(r.lat is not None for r in log.records)
    assert any(r.battery_voltage is not None for r in log.records)
    # El tiempo debe normalizarse a partir de 0, no quedar en microsegundos absolutos.
    assert log.records[0].timestamp == 0.0


def test_parse_ardupilot_gps_only_keeps_valid_fix(fixtures_dir):
    """GPS con Status < 3 (sin fix 3D) se descarta; los que quedan deben tener coordenadas plausibles."""
    log = parse_ardupilot_log(str(fixtures_dir / "mini_ardupilot.bin"))
    geo_records = [r for r in log.records if r.lat is not None]
    assert all(-90 <= r.lat <= 90 and -180 <= r.lon <= 180 for r in geo_records)


def test_parse_px4_produces_records_and_events(fixtures_dir):
    log = parse_px4_log(str(fixtures_dir / "mini_px4.ulog"))

    assert log.source == Source.PX4
    assert len(log.records) > 0
    assert any(r.roll is not None for r in log.records)
    assert log.records[0].timestamp == 0.0


def test_parse_betaflight_csv(fixtures_dir):
    log = parse_betaflight_csv(str(fixtures_dir / "mini_betaflight.csv"))

    assert log.source == Source.BETAFLIGHT
    assert len(log.records) == 30
    # El fixture tiene GPS_coord en grados*1e7; el parser debe convertirlo a grados decimales.
    first = log.records[0]
    assert first.lat == 47.3769
    assert first.lon == 8.5417


def test_parse_betaflight_csv_detects_failsafe(fixtures_dir):
    """El fixture fuerza failsafePhase=1 a partir de la muestra 25; debe generar un evento rc_loss."""
    log = parse_betaflight_csv(str(fixtures_dir / "mini_betaflight.csv"))
    assert any(e.category == "rc_loss" for e in log.events)


def test_parse_dji_srt(fixtures_dir):
    frames = parse_dji_srt(str(fixtures_dir / "mini_dji.srt"))

    assert len(frames) == 4
    assert all(f.lat is not None and f.lon is not None for f in frames)
    assert all(f.absolute_time is not None for f in frames)
    # Los timestamps de video deben ser crecientes (subtitulos en orden).
    timestamps = [f.video_timestamp_s for f in frames]
    assert timestamps == sorted(timestamps)
