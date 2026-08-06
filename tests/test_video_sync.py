"""Tests del cruce log-video (src/analysis/video_sync.py)."""

from datetime import datetime

from src.analysis.video_sync import resolve_offset, sync_events_with_video
from src.parsers.base import FlightEvent, FlightLog, FlightRecord, Source
from src.parsers.dji_srt import parse_dji_srt


def test_resolve_offset_from_absolute_time(fixtures_dir):
    frames = parse_dji_srt(str(fixtures_dir / "mini_dji.srt"))
    # El fixture usa 2024-01-01 12:00:10 como hora absoluta del primer fotograma (t=0.5s de video).
    offset = resolve_offset(frames, datetime(2024, 1, 1, 12, 0, 0))
    assert offset == -9.5


def test_resolve_offset_without_absolute_time_reference_returns_none(fixtures_dir):
    frames = parse_dji_srt(str(fixtures_dir / "mini_dji.srt"))
    assert resolve_offset(frames, None) is None


def test_gps_cross_check_matches_when_positions_agree(fixtures_dir):
    frames = parse_dji_srt(str(fixtures_dir / "mini_dji.srt"))

    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    # Coincide a proposito con la posicion del segundo fotograma del SRT (t=11:00 -> video t=1.5s).
    log.records.append(FlightRecord(timestamp=11.0, lat=47.376950, lon=8.541750, alt=12.0))
    log.events.append(FlightEvent(timestamp=11.0, category="mode_change", severity="warning", description="evento de prueba"))

    synced = sync_events_with_video(log, frames, offset_s=-9.5)

    assert len(synced) == 1
    assert synced[0].gps_cross_check_distance_m == 0.0


def test_gps_cross_check_flags_mismatch(fixtures_dir):
    frames = parse_dji_srt(str(fixtures_dir / "mini_dji.srt"))

    log = FlightLog(source=Source.ARDUPILOT, source_file="test.bin")
    # Posicion deliberadamente distinta a la que dice el SRT en el mismo instante.
    log.records.append(FlightRecord(timestamp=13.0, lat=47.381000, lon=8.541950, alt=5.0))
    log.events.append(FlightEvent(timestamp=13.0, category="rc_loss", severity="critical", description="evento con GPS discrepante"))

    synced = sync_events_with_video(log, frames, offset_s=-9.5)

    assert len(synced) == 1
    assert synced[0].gps_cross_check_distance_m > 100  # discrepancia clara, no ruido de precision GPS
