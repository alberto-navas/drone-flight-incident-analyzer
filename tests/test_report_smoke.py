"""
Prueba de humo end-to-end con datos sinteticos.

No sustituye probar contra logs reales (eso lo hace el CLI con las muestras
descargadas en data/samples), pero sirve para verificar que el pipeline
completo (analysis + report) funciona sin tener que esperar a tener logs
reales descargados, y sin depender de pymavlink/pyulog para este test en
concreto.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analysis.anomalies import detect_anomalies
from src.parsers.base import FlightLog, FlightRecord, Source
from src.report.generator import generate_report


def build_synthetic_log() -> FlightLog:
    """Genera un vuelo sintetico de 60s con un glitch de GPS y una caida de bateria simulados."""
    log = FlightLog(source=Source.ARDUPILOT, source_file="synthetic_test.bin")

    base_lat, base_lon = 47.3769, 8.5417  # Zurich, punto de referencia arbitrario
    for i in range(60):
        lat = base_lat + i * 0.00003
        lon = base_lon + i * 0.00003
        if i == 30:
            # Salto de posicion artificial: simula un glitch de GPS.
            lat += 0.05
        log.records.append(
            FlightRecord(
                timestamp=float(i),
                lat=lat,
                lon=lon,
                alt=50.0 - (0 if i < 45 else (i - 45) * 6.0),  # caida brusca a partir de i=45
                groundspeed=5.0,
                battery_voltage=12.6 - (i * 0.01) - (0.6 if i > 50 else 0),
                rc_signal=90.0 if i < 55 else 5.0,
            )
        )

    return log


def main():
    log = build_synthetic_log()
    detect_anomalies(log)
    output_path = str(Path(__file__).parent.parent / "output" / "smoke_test_report.html")
    generate_report(log, output_path)
    print(f"OK: informe generado en {output_path}")
    print(f"Eventos detectados: {len(log.events)}")
    for event in sorted(log.events, key=lambda e: e.timestamp):
        print(f"  [{event.severity}] t={event.timestamp:.1f}s {event.category}: {event.description}")


if __name__ == "__main__":
    main()
