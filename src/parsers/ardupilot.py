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
    """
    mlog = mavutil.mavlink_connection(file_path)

    log = FlightLog(source=Source.ARDUPILOT, source_file=file_path)
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
            log.records.append(
                FlightRecord(timestamp=ts, rc_signal=getattr(msg, "RXRSSI", None))
            )

        elif msg_type == "MODE":
            mode_name = getattr(msg, "Mode", None)
            log.events.append(
                FlightEvent(
                    timestamp=ts,
                    category="mode_change",
                    severity="info",
                    description=f"Cambio de modo de vuelo a {mode_name}",
                )
            )

        elif msg_type == "ERR":
            subsys = _ERR_SUBSYSTEMS.get(getattr(msg, "Subsys", -1), f"subsys_{getattr(msg, 'Subsys', '?')}")
            log.events.append(
                FlightEvent(
                    timestamp=ts,
                    category="firmware_error",
                    # Cualquier ERR con codigo != 0 se marca como critico: son
                    # los mensajes que el propio firmware reserva para fallos,
                    # no para informacion rutinaria.
                    severity="critical" if getattr(msg, "ECode", 0) != 0 else "info",
                    description=f"Error de firmware en subsistema '{subsys}' (codigo {getattr(msg, 'ECode', '?')})",
                )
            )

        elif msg_type == "EV":
            log.events.append(
                FlightEvent(
                    timestamp=ts,
                    category="firmware_event",
                    severity="info",
                    description=f"Evento de firmware id={getattr(msg, 'Id', '?')}",
                )
            )

    # Metadatos generales del vehiculo/firmware, si el log los trae en la
    # cabecera (mensaje MSG suele contener la version de firmware como texto).
    log.metadata["parsed_message_count"] = len(log.records) + len(log.events)

    return log
