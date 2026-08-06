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

Contrato de errores: SIEMPRE ValueError. Los tres parsers subyacentes son
tres librerias de terceros distintas (pymavlink, pyulog, subprocess+CSV) que
lanzan tipos de excepcion distintos e inconsistentes ante un archivo vacio o
corrupto (ValueError, TypeError, CalledProcessError...). En vez de que cada
interfaz tenga que conocer y capturar los tres tipos, se normalizan aqui a
un unico tipo con un mensaje en español pensado para un usuario final, no
para depurar la libreria interna.
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


def _parse_by_format(input_path: Path, fmt: str) -> FlightLog:
    """
    Despacha al parser concreto. Puede lanzar cualquier excepcion de la
    libreria subyacente; parse_log() la normaliza.
    """
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


def parse_log(input_path: Path, forced_format: str | None = None) -> FlightLog:
    """
    Elige el parser correcto segun el formato (forzado o inferido por
    extension), lo ejecuta y devuelve el FlightLog resultante.

    Lanza ValueError (y solo ValueError, ver docstring del modulo) si:
    - no se puede determinar el formato,
    - el archivo esta vacio, corrupto, o no es realmente de ese formato
      (cada libreria subyacente lo detecta a su manera; aqui se homogeniza),
    - el archivo se parsea sin errores pero no contiene ninguna muestra de
      telemetria (un informe sin datos no le sirve a nadie, mejor avisar
      claramente que generar un informe vacio).
    """
    fmt = forced_format or EXTENSION_TO_FORMAT.get(input_path.suffix.lower())

    if fmt is None:
        raise ValueError(
            f"No se pudo inferir el formato a partir de la extension '{input_path.suffix}'. "
            "Especifica el formato explicitamente: ardupilot, px4 o betaflight."
        )

    try:
        flight_log = _parse_by_format(input_path, fmt)
    except Exception as exc:
        # Se envuelve SIEMPRE, incluso si `exc` ya es un ValueError: un
        # ValueError puede venir tanto de un mensaje pensado por nosotros
        # (betaflight.py) como de una libreria de terceros con un mensaje
        # tecnico poco util (p.ej. "cannot mmap an empty file" de mmap.mmap
        # al leer un ArduPilot .bin vacio). Envolver de forma uniforme,
        # siempre con el mismo formato, es mas fiable que intentar
        # distinguir "mensajes ya buenos" por tipo de excepcion.
        detail = str(exc).rstrip(".")
        raise ValueError(
            f"No se pudo leer '{input_path.name}' como log de {fmt}: {detail}. "
            "¿Seguro que el archivo no esta vacio, truncado, o corresponde a otro formato?"
        ) from exc

    if not flight_log.records and not flight_log.events:
        raise ValueError(
            f"'{input_path.name}' se parseo sin errores como {fmt}, pero no contiene ninguna "
            "muestra de telemetria ni evento reconocible. Puede que el archivo este vacio, "
            "truncado, o que en realidad no sea un log de este formato."
        )

    return flight_log
