"""
Punto de entrada de linea de comandos: log de vuelo -> informe HTML.

Ejemplo de uso:
    python -m src.cli data/samples/ardupilot/vuelo1.bin
    python -m src.cli data/samples/px4/vuelo2.ulog --output output/vuelo2.html
    python -m src.cli data/samples/betaflight/vuelo3.BBL   # requiere blackbox_decode en el PATH
    python -m src.cli data/samples/betaflight/vuelo3.csv --format betaflight  # si ya esta decodificado
"""

import argparse
import sys
from pathlib import Path

from .analysis.anomalies import detect_anomalies
from .parsers.ardupilot import parse_ardupilot_log
from .parsers.betaflight import decode_bbl_to_csv, parse_betaflight_csv
from .parsers.base import FlightLog
from .parsers.px4 import parse_px4_log
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera un informe forense a partir de un log de vuelo de dron.")
    parser.add_argument("input", type=Path, help="Ruta al log de vuelo (.bin / .ulog / .BBL / .csv)")
    parser.add_argument(
        "--format",
        choices=["ardupilot", "px4", "betaflight"],
        default=None,
        help="Fuerza el formato del log en vez de inferirlo por la extension del archivo.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Ruta del informe HTML de salida. Por defecto: output/<nombre_del_log>.html",
    )
    parser.add_argument(
        "--mass-kg",
        type=float,
        default=None,
        help="Masa estimada del vehiculo en kg, usada solo para calcular la energia cinetica de impacto (opcional).",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        raise SystemExit(f"No existe el archivo: {args.input}")

    output_path = args.output or (Path("output") / f"{args.input.stem}.html")

    print(f"Parseando {args.input}...")
    flight_log = _parse_log(args.input, args.format)
    print(f"  {len(flight_log.records)} muestras de telemetria, {len(flight_log.events)} eventos del firmware.")

    print("Ejecutando deteccion de anomalias...")
    new_events = detect_anomalies(flight_log)
    print(f"  {len(new_events)} anomalias adicionales detectadas.")

    print(f"Generando informe en {output_path}...")
    generate_report(flight_log, str(output_path), mass_kg=args.mass_kg)

    print("Listo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
