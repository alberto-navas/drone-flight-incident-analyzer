"""Fixtures compartidas por toda la suite de tests."""

from pathlib import Path

import pytest

from src.parsers.base import FlightLog, FlightRecord, Source

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def synthetic_flight_log() -> FlightLog:
    """
    Vuelo sintetico "limpio" de referencia: 20 muestras, 1 segundo entre
    cada una, sin ninguna anomalia. Sirve de punto de partida para tests
    que necesitan un FlightLog valido sin tener que parsear un archivo real.
    """
    log = FlightLog(source=Source.ARDUPILOT, source_file="synthetic.bin")
    for i in range(20):
        log.records.append(
            FlightRecord(
                timestamp=float(i),
                lat=47.3769 + i * 0.00001,
                lon=8.5417 + i * 0.00001,
                alt=50.0,
                groundspeed=5.0,
                battery_voltage=12.6 - i * 0.01,
                rc_signal=95.0,
                roll=0.0,
                pitch=0.0,
                yaw=0.0,
            )
        )
    return log
