"""
Punto de entrada de linea de comandos: log de vuelo -> informe HTML.

Ejemplo de uso:
    python -m src.cli data/samples/ardupilot/vuelo1.bin
    python -m src.cli data/samples/px4/vuelo2.ulog --output output/vuelo2.html
    python -m src.cli data/samples/betaflight/vuelo3.BBL   # requiere blackbox_decode en el PATH
    python -m src.cli data/samples/betaflight/vuelo3.csv --format betaflight  # si ya esta decodificado

Con varios archivos a la vez se genera un panel comparativo de flota en vez
de un informe individual:
    python -m src.cli data/samples/ardupilot/*.bin --output output/flota.html
"""

import argparse
import sys
from pathlib import Path

from .analysis.anomalies import detect_anomalies
from .analysis.ml_anomalies import detect_ml_anomalies
from .analysis.video_sync import sync_events_with_video
from .parsers.ardupilot import parse_ardupilot_log
from .parsers.betaflight import decode_bbl_to_csv, parse_betaflight_csv
from .parsers.base import FlightLog
from .parsers.dji_srt import parse_dji_srt
from .parsers.px4 import parse_px4_log
from .report.fleet import generate_fleet_report
from .report.generator import generate_report

# Mapea la extension del archivo al formato, para que el usuario no tenga
# que especificar --format en el caso comun. Se puede forzar con --format
# de todas formas (por ejemplo, un .csv de Betaflight ya decodificado no
# tiene forma de distinguirse de cualquier otro CSV solo por la extension).
_EXTENSION_TO_FORMAT = {
    ".bin": "ardupilot",
    ".ulog": "px4",
    ".bbl": "betaflight",
}


def _parse_log(input_path: Path, forced_format: str | None) -> FlightLog:
    """Elige el parser correcto segun el formato (forzado o inferido por extension) y devuelve el FlightLog."""
    fmt = forced_format or _EXTENSION_TO_FORMAT.get(input_path.suffix.lower())

    if fmt is None:
        raise SystemExit(
            f"No se pudo inferir el formato a partir de la extension '{input_path.suffix}'. "
            "Especifica --format {ardupilot|px4|betaflight} explicitamente."
        )

    if fmt == "ardupilot":
        return parse_ardupilot_log(str(input_path))

    if fmt == "px4":
        return parse_px4_log(str(input_path))

    if fmt == "betaflight":
        if input_path.suffix.lower() == ".csv":
            # El usuario ya nos da el CSV decodificado (p.ej. exportado a
            # mano desde Blackbox Explorer): nos ahorramos depender de que
            # blackbox_decode este instalado.
            return parse_betaflight_csv(str(input_path))
        csv_path = decode_bbl_to_csv(str(input_path), output_dir=str(input_path.parent))
        return parse_betaflight_csv(csv_path, source_bbl_path=str(input_path))

    raise SystemExit(f"Formato desconocido: {fmt}")


def _parse_and_analyze(input_path: Path, forced_format: str | None) -> FlightLog:
    """Parsea un log y le corre encima la deteccion de anomalias (reglas + ML). Comun a los modos individual y flota."""
    print(f"Parseando {input_path}...")
    flight_log = _parse_log(input_path, forced_format)
    print(f"  {len(flight_log.records)} muestras de telemetria, {len(flight_log.events)} eventos del firmware.")

    new_events = detect_anomalies(flight_log)
    print(f"  {len(new_events)} anomalias adicionales detectadas por reglas.")

    ml_events = detect_ml_anomalies(flight_log)
    flight_log.events.extend(ml_events)
    if ml_events:
        print(f"  {len(ml_events)} anomalias adicionales detectadas por Isolation Forest (ML).")
    else:
        print("  Sin anomalias ML: datos insuficientes para este vuelo, o ninguna encontrada.")

    return flight_log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera un informe forense a partir de uno o varios logs de vuelo de dron.")
    parser.add_argument(
        "inputs",
        type=Path,
        nargs="+",
        help="Ruta a uno o varios logs de vuelo (.bin / .ulog / .BBL / .csv). Con varios, genera un panel de flota.",
    )
    parser.add_argument(
        "--format",
        choices=["ardupilot", "px4", "betaflight"],
        default=None,
        help="Fuerza el formato de TODOS los logs en vez de inferirlo por extension (util con un solo formato mezclado).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Ruta del informe HTML de salida. Por defecto: output/<nombre>.html (individual) u output/fleet_report.html (flota).",
    )
    parser.add_argument(
        "--mass-kg",
        type=float,
        default=None,
        help="Masa estimada del vehiculo en kg, usada solo para calcular la energia cinetica de impacto (solo modo individual).",
    )
    parser.add_argument(
        "--video-srt",
        type=Path,
        default=None,
        help="Archivo .srt de un vuelo DJI para cruzar eventos del log con fotogramas de video (solo modo individual).",
    )
    parser.add_argument(
        "--video-offset",
        type=float,
        default=0.0,
        help="Segundos a sumar al tiempo del log para obtener el tiempo de video equivalente (calibrado a mano). Requiere --video-srt.",
    )
    args = parser.parse_args(argv)

    if args.video_srt is not None and len(args.inputs) != 1:
        raise SystemExit("--video-srt solo esta soportado en modo de un solo vuelo.")

    for input_path in args.inputs:
        if not input_path.exists():
            raise SystemExit(f"No existe el archivo: {input_path}")

    if len(args.inputs) == 1:
        input_path = args.inputs[0]
        output_path = args.output or (Path("output") / f"{input_path.stem}.html")

        flight_log = _parse_and_analyze(input_path, args.format)

        synced_events = None
        if args.video_srt is not None:
            print(f"Cruzando con video: {args.video_srt} (offset {args.video_offset:+.1f}s)...")
            video_frames = parse_dji_srt(str(args.video_srt))
            synced_events = sync_events_with_video(flight_log, video_frames, offset_s=args.video_offset)

        print(f"Generando informe en {output_path}...")
        generate_report(flight_log, str(output_path), mass_kg=args.mass_kg, synced_events=synced_events)
    else:
        output_path = args.output or (Path("output") / "fleet_report.html")

        flight_logs = [_parse_and_analyze(input_path, args.format) for input_path in args.inputs]

        print(f"Generando panel de flota ({len(flight_logs)} vuelos) en {output_path}...")
        generate_fleet_report(flight_logs, str(output_path))

    print("Listo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
