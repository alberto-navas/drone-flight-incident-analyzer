"""
Deteccion de formato + parseo, compartido entre el CLI (src/cli.py) y la
interfaz web (src/web/app.py).

Antes de este modulo, esta logica vivia duplicada dentro de cli.py. Se
extrae aqui porque ahora hay dos consumidores reales, no como abstraccion
especulativa. Importante: este modulo NO debe lanzar SystemExit (a
diferencia del CLI) porque tambien lo usa un proceso de servidor web, donde
SystemExit terminaria el worker entero en vez de devolver un error HTTP
normal; los errores se señalizan con ValueError, y cada interfaz decide como
presentarlos (el CLI los convierte a SystemExit en su propio limite).
"""

from pathlib import Path

from .parsers.ardupilot import parse_ardupilot_log
from .parsers.base import FlightLog
from .parsers.betaflight import decode_bbl_to_csv, parse_betaflight_csv
from .parsers.px4 import parse_px4_log

# Mapea la extension del archivo al formato, para que el usuario no tenga
# que especificar el formato en el caso comun, ni siquiera al mezclar varios
# formatos en una misma tanda. El unico formato CSV que esta herramienta
# sabe leer es un Betaflight ya decodificado por blackbox_decode, asi que
# mapear ".csv" directamente a "betaflight" no es ambiguo en la practica.
EXTENSION_TO_FORMAT = {
    ".bin": "ardupilot",
    ".ulog": "px4",
    ".bbl": "betaflight",
    ".csv": "betaflight",
}


def parse_log(input_path: Path, forced_format: str | None = None) -> FlightLog:
    """
    Elige el parser correcto segun el formato (forzado o inferido por
    extension) y devuelve el FlightLog. Lanza ValueError si no se puede
    determinar el formato o no esta reconocido.
    """
    fmt = forced_format or EXTENSION_TO_FORMAT.get(input_path.suffix.lower())

    if fmt is None:
        raise ValueError(
            f"No se pudo inferir el formato a partir de la extension '{input_path.suffix}'. "
            "Especifica el formato explicitamente: ardupilot, px4 o betaflight."
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

    raise ValueError(f"Formato desconocido: {fmt}")
