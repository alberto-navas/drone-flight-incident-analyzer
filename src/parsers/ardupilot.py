"""
Parser de logs ArduPilot ("dataflash", extension .bin).

ArduPilot no guarda un log como una tabla unica: guarda un flujo de mensajes
de tipos distintos (GPS, BAT, ATT, MODE...) intercalados, cada uno con su
propio timestamp y sus propios campos. pymavlink ya sabe leer el formato
binario y decodificar cada mensaje; nuestro trabajo aqui es solo recorrer
ese flujo y traducir los tipos de mensaje que nos interesan a FlightRecord /
FlightEvent.

Decision de diseno: en vez de fusionar GPS+BAT+ATT en una unica fila por
"instante" (lo cual requeriria interpolar o hacer resample, con perdida de
precision), generamos un FlightRecord por mensaje, con solo los campos que
ese mensaje trae. Los demas campos quedan a None. Es mas fiel a los datos
originales y el resto del pipeline (mapas, deteccion de anomalias) ya esta
preparado para trabajar con campos ausentes.
"""

import contextlib
import io
from pathlib import Path

from pymavlink import mavutil

from .base import FlightEvent, FlightLog, FlightRecord, Source

# Mensajes dataflash que nos interesa traducir a telemetria continua.
# Referencia de campos: https://ardupilot.org/plane/docs/logmessages.html
_TELEMETRY_MESSAGE_TYPES = {"GPS", "BAT", "ATT", "RSSI"}

# Mensajes que representan un suceso puntual, no una medida continua.
_EVENT_MESSAGE_TYPES = {"MODE", "ERR", "EV"}

# Codigos de severidad conocidos de los mensajes ERR de ArduPilot.
# (subsistema -> nombre legible, no exhaustivo, solo los mas relevantes para forense)
_ERR_SUBSYSTEMS = {
    1: "main",
    2: "radio",
    3: "compass",
    4: "optical_flow",
    5: "failsafe_radio",
    6: "failsafe_battery",
    7: "failsafe_gps",
    8: "failsafe_gcs",
    9: "failsafe_fence",
    10: "flight_mode",
    11: "gps",
    12: "crash_check",
}


def _message_timestamp_seconds(msg) -> float | None:
    """
    Obtiene el timestamp de un mensaje dataflash en segundos desde el inicio del log.

    Los mensajes dataflash traen normalmente `TimeUS` (microsegundos desde
    boot). Versiones antiguas de ArduPilot usaban `TimeMS`. Si el mensaje no
    trae ninguno de los dos (algunos mensajes de configuracion no llevan
    tiempo), lo descartamos devolviendo None.
    """
    if hasattr(msg, "TimeUS"):
        return msg.TimeUS / 1_000_000.0
    if hasattr(msg, "TimeMS"):
        return msg.TimeMS / 1_000.0
    return None


def parse_ardupilot_log(file_path: str) -> FlightLog:
    """
    Lee un log dataflash .bin de ArduPilot y lo normaliza a FlightLog.

    `mavutil.mavlink_connection` detecta automaticamente que esta leyendo un
    log binario (en vez de un stream MAVLink en vivo) y devuelve un
    DFReader, que expone la misma API `recv_match()` que se usaria para leer
    telemetria en tiempo real de un dron conectado.

    Ante un archivo corrupto, DFReader no lanza excepcion por cada byte que
    no reconoce: emite por stderr un `print()` de diagnostico
    ("bad header...") por cada uno, lo cual puede ser miles de lineas de
    ruido en los logs del servidor si alguien sube un archivo invalido a la
    interfaz web. Se silencia esa salida aqui; si el resultado final no
    tiene ninguna muestra, parse_log() (src/pipeline.py) ya lo convierte en
    un error claro para el usuario.
    """
    # Comprobacion previa deliberada para el caso de archivo vacio: sin
    # esto, mavutil.mavlink_connection() abre el archivo internamente y
    # LUEGO falla al hacer mmap sobre 0 bytes, dejando ese descriptor de
    # archivo abierto sin que lleguemos a tener una referencia con la que
    # cerrarlo (el error ocurre a mitad de la construccion del DFReader).
    # En Windows eso bloquea borrar el archivo despues (p.ej. limpiar el
    # directorio temporal de una peticion web) hasta que el recolector de
    # basura de Python decida liberarlo. Evitamos todo el problema
    # detectando el caso antes de llamar a pymavlink.
    if Path(file_path).stat().st_size == 0:
        raise ValueError("el archivo esta vacio")

    log = FlightLog(source=Source.ARDUPILOT, source_file=file_path)

    mlog = None
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            mlog = mavutil.mavlink_connection(file_path)
            _consume_messages(mlog, log)
    finally:
        # DFReader mantiene el archivo abierto internamente; cerrarlo
        # explicitamente evita fugas de descriptor de archivo. Es
        # especialmente importante en Windows, donde un archivo no se puede
        # borrar (p.ej. limpiar un directorio temporal) mientras siga
        # abierto por el proceso — a diferencia de Unix, que si lo permite.
        # `mlog` puede seguir siendo None si mavlink_connection() fallo antes
        # de devolver nada (p.ej. archivo vacio): no hay nada que cerrar.
        if mlog is not None:
            mlog.close()

    log.metadata["parsed_message_count"] = len(log.records) + len(log.events)
    return log


def _consume_messages(mlog, log: FlightLog) -> None:
    """Recorre el flujo de mensajes del DFReader y rellena log.records / log.events."""
    # t0 se fija con el primer timestamp valido que encontramos, para que el
    # FlightLog resultante empiece siempre en tiempo relativo 0, sea cual sea
    # el instante de boot real del vehiculo.
    t0: float | None = None

    while True:
        msg = mlog.recv_match(type=_TELEMETRY_MESSAGE_TYPES | _EVENT_MESSAGE_TYPES, blocking=False)
        if msg is None:
            break  # fin del archivo

        raw_ts = _message_timestamp_seconds(msg)
        if raw_ts is None:
            continue

        if t0 is None:
            t0 = raw_ts
        ts = raw_ts - t0

        msg_type = msg.get_type()

        if msg_type == "GPS":
            # Status < 3 significa que el receptor GPS todavia no tiene fix
            # 3D; publicar esas posiciones ensuciaria el mapa con saltos
            # falsos, asi que se descartan.
            if getattr(msg, "Status", 3) < 3:
                continue
            log.records.append(
                FlightRecord(
                    timestamp=ts,
                    lat=msg.Lat,
                    lon=msg.Lng,
                    alt=getattr(msg, "Alt", None),
                    groundspeed=getattr(msg, "Spd", None),
                )
            )

        elif msg_type == "BAT":
            log.records.append(
                FlightRecord(
                    timestamp=ts,
                    battery_voltage=getattr(msg, "Volt", None),
                    battery_current=getattr(msg, "Curr", None),
                )
            )

        elif msg_type == "ATT":
            log.records.append(
                FlightRecord(
                    timestamp=ts,
                    roll=getattr(msg, "Roll", None),
                    pitch=getattr(msg, "Pitch", None),
                    yaw=getattr(msg, "Yaw", None),
                )
            )

        elif msg_type == "RSSI":
            log.records.append(FlightRecord(timestamp=ts, rc_signal=getattr(msg, "RXRSSI", None)))

        elif msg_type == "MODE":
            mode_name = getattr(msg, "Mode", None)
            log.events.append(
                FlightEvent(
                    timestamp=ts,
                    category="mode_change",
                    severity="info",
                    description=f"Cambio de modo de vuelo a {mode_name}",
                    message_key="mode_change",
                    message_params={"mode": mode_name},
                )
            )

        elif msg_type == "ERR":
            subsys = _ERR_SUBSYSTEMS.get(getattr(msg, "Subsys", -1), f"subsys_{getattr(msg, 'Subsys', '?')}")
            ecode = getattr(msg, "ECode", "?")
            log.events.append(
                FlightEvent(
                    timestamp=ts,
                    category="firmware_error",
                    # Cualquier ERR con codigo != 0 se marca como critico: son
                    # los mensajes que el propio firmware reserva para fallos,
                    # no para informacion rutinaria.
                    severity="critical" if getattr(msg, "ECode", 0) != 0 else "info",
                    description=f"Error de firmware en subsistema '{subsys}' (codigo {ecode})",
                    message_key="firmware_error",
                    message_params={"subsys": subsys, "code": ecode},
                )
            )

        elif msg_type == "EV":
            event_id = getattr(msg, "Id", "?")
            log.events.append(
                FlightEvent(
                    timestamp=ts,
                    category="firmware_event",
                    severity="info",
                    description=f"Evento de firmware id={event_id}",
                    message_key="firmware_event",
                    message_params={"event_id": event_id},
                )
            )
