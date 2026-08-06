"""
Parser de logs PX4 (formato ULog, extension .ulog).

A diferencia del dataflash de ArduPilot (un flujo de mensajes intercalados),
un ULog es mas parecido a una base de datos: cada "topico" (GPS, bateria,
actitud...) es una tabla independiente con su propia frecuencia de muestreo,
mas una lista aparte de mensajes de texto ("logged messages") que el
flight stack va emitiendo durante el vuelo. Por eso este parser recorre cada
topico por separado, en vez de iterar un unico flujo como en ArduPilot.
"""

import math
from pathlib import Path

from pyulog import ULog

from .base import FlightEvent, FlightLog, FlightRecord, Source

# Cabecera magica que todo archivo ULog valido empieza (ver pyulog.core.ULog.HEADER_BYTES).
# Se usa para validar el archivo ANTES de pasarselo a pyulog: ver el
# comentario en parse_px4_log sobre por que importa hacerlo asi.
_ULOG_MAGIC = b"\x55\x4c\x6f\x67\x01\x12\x35"

# Subconjunto del enum vehicle_status_s::nav_state de PX4. No es exhaustivo:
# solo cubrimos los modos mas comunes para que el informe sea legible: los
# valores no mapeados se muestran como "NAV_STATE_<n>" en vez de fallar.
# Referencia: PX4-Autopilot/msg/VehicleStatus.msg
_NAV_STATE_NAMES = {
    0: "MANUAL",
    1: "ALTCTL",
    2: "POSCTL",
    3: "AUTO_MISSION",
    4: "AUTO_LOITER",
    5: "AUTO_RTL",
    6: "ACRO",
    8: "STAB",
    10: "AUTO_LAND",
    12: "AUTO_TAKEOFF",
    13: "AUTO_PRECLAND",
    14: "ORBIT",
}

# syslog levels que PX4 usa en sus logged_messages (a menor numero, mas grave).
_SYSLOG_CRITICAL_MAX = 3  # EMERG..ERR
_SYSLOG_WARNING = 4


def _quaternion_to_euler_deg(q0: float, q1: float, q2: float, q3: float) -> tuple[float, float, float]:
    """
    Convierte un cuaternion PX4 (orden w,x,y,z) a angulos de Euler en grados.

    PX4 guarda la actitud como cuaternion (evita el gimbal lock), pero para
    un informe humano roll/pitch/yaw es mucho mas legible. Formula estandar
    de conversion cuaternion -> Euler (convencion aeroespacial ZYX).
    """
    sinr_cosp = 2 * (q0 * q1 + q2 * q3)
    cosr_cosp = 1 - 2 * (q1 * q1 + q2 * q2)
    roll = math.degrees(math.atan2(sinr_cosp, cosr_cosp))

    sinp = 2 * (q0 * q2 - q3 * q1)
    sinp = max(-1.0, min(1.0, sinp))  # evita domain error de asin por redondeo
    pitch = math.degrees(math.asin(sinp))

    siny_cosp = 2 * (q0 * q3 + q1 * q2)
    cosy_cosp = 1 - 2 * (q2 * q2 + q3 * q3)
    yaw = math.degrees(math.atan2(siny_cosp, cosy_cosp))

    return roll, pitch, yaw


def _primary_dataset(ulog: ULog, topic_name: str):
    """
    Devuelve la instancia primaria (multi_id == 0) de un topico dado.

    Algunos sensores (p.ej. dos GPS redundantes) generan varias instancias
    del mismo topico. Para el MVP nos quedamos solo con la primaria; usar
    todas las instancias es una mejora futura si hace falta comparar
    sensores redundantes entre si.
    """
    for dataset in ulog.data_list:
        if dataset.name == topic_name and dataset.multi_id == 0:
            return dataset
    return None


def parse_px4_log(file_path: str) -> FlightLog:
    """
    Lee un log .ulog de PX4 y lo normaliza a FlightLog.

    Antes de instanciar `ULog`, se valida a mano que el archivo tiene la
    cabecera minima esperada. No es solo una comprobacion redundante: la
    propia libreria pyulog abre el archivo (`open(file_path, "rb")`) ANTES
    de validar su contenido, y si esa validacion falla no cierra el archivo
    (la excepcion aborta la construccion del objeto a mitad, sin dejarnos
    nunca una referencia con la que cerrarlo). En Windows eso bloquea borrar
    el archivo despues (p.ej. limpiar el directorio temporal de una
    peticion web) hasta que el recolector de basura lo libere — y con
    excepciones encadenadas (`raise ... from exc`) eso puede tardar hasta
    que el error termina de propagarse del todo. Validar antes evita entrar
    en ese camino para los casos mas comunes (archivo vacio o de otro formato).
    """
    header = Path(file_path).read_bytes()[:16]
    if len(header) < 16 or header[:7] != _ULOG_MAGIC:
        raise ValueError("el archivo no tiene una cabecera ULog valida")

    ulog = ULog(file_path)

    log = FlightLog(source=Source.PX4, source_file=file_path)

    # ULog ya trae timestamps absolutos en microsegundos desde el arranque
    # del sistema; igual que en el parser de ArduPilot, normalizamos para
    # que el FlightLog empiece en t=0.
    t0_us: int | None = None

    def to_relative_seconds(timestamp_us: int) -> float:
        nonlocal t0_us
        if t0_us is None:
            t0_us = timestamp_us
        return (timestamp_us - t0_us) / 1_000_000.0

    gps = _primary_dataset(ulog, "vehicle_gps_position")
    if gps is not None:
        data = gps.data
        for i in range(len(data["timestamp"])):
            # lat/lon vienen en grados * 1e7 y alt en milimetros: son enteros
            # para evitar errores de precision de coma flotante en el log.
            log.records.append(
                FlightRecord(
                    timestamp=to_relative_seconds(int(data["timestamp"][i])),
                    lat=data["lat"][i] / 1e7,
                    lon=data["lon"][i] / 1e7,
                    alt=data["alt"][i] / 1000.0,
                    groundspeed=data.get("vel_m_s", [None] * len(data["timestamp"]))[i],
                )
            )

    battery = _primary_dataset(ulog, "battery_status")
    if battery is not None:
        data = battery.data
        for i in range(len(data["timestamp"])):
            log.records.append(
                FlightRecord(
                    timestamp=to_relative_seconds(int(data["timestamp"][i])),
                    battery_voltage=data.get("voltage_v", [None] * len(data["timestamp"]))[i],
                    battery_current=data.get("current_a", [None] * len(data["timestamp"]))[i],
                )
            )

    attitude = _primary_dataset(ulog, "vehicle_attitude")
    if attitude is not None:
        data = attitude.data
        for i in range(len(data["timestamp"])):
            roll, pitch, yaw = _quaternion_to_euler_deg(
                data["q[0]"][i], data["q[1]"][i], data["q[2]"][i], data["q[3]"][i]
            )
            log.records.append(
                FlightRecord(
                    timestamp=to_relative_seconds(int(data["timestamp"][i])),
                    roll=roll,
                    pitch=pitch,
                    yaw=yaw,
                )
            )

    rc = _primary_dataset(ulog, "input_rc")
    if rc is not None:
        data = rc.data
        if "rssi" in data:
            for i in range(len(data["timestamp"])):
                log.records.append(
                    FlightRecord(
                        timestamp=to_relative_seconds(int(data["timestamp"][i])),
                        rc_signal=data["rssi"][i],
                    )
                )

    status = _primary_dataset(ulog, "vehicle_status")
    if status is not None:
        data = status.data
        prev_mode = None
        for i in range(len(data["timestamp"])):
            nav_state = int(data["nav_state"][i])
            mode_name = _NAV_STATE_NAMES.get(nav_state, f"NAV_STATE_{nav_state}")
            # vehicle_status se publica a alta frecuencia aunque el modo no
            # cambie; solo generamos un evento cuando el modo es distinto al
            # anterior, igual que hace el mensaje MODE de ArduPilot.
            if mode_name != prev_mode:
                log.events.append(
                    FlightEvent(
                        timestamp=to_relative_seconds(int(data["timestamp"][i])),
                        category="mode_change",
                        severity="info",
                        description=f"Cambio de modo de vuelo a {mode_name}",
                    )
                )
                prev_mode = mode_name

    # Los "logged messages" son el equivalente PX4 a los mensajes ERR/EV de
    # ArduPilot: texto libre que el flight stack emite ante eventos notables
    # (failsafes, cambios de estimador, fallos de sensor...).
    for lm in ulog.logged_messages:
        severity = (
            "critical"
            if lm.log_level <= _SYSLOG_CRITICAL_MAX
            else ("warning" if lm.log_level == _SYSLOG_WARNING else "info")
        )
        log.events.append(
            FlightEvent(
                timestamp=to_relative_seconds(lm.timestamp),
                category="firmware_message",
                severity=severity,
                description=lm.message,
            )
        )

    log.metadata["parsed_message_count"] = len(log.records) + len(log.events)

    return log
