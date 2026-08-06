"""
Modelo de datos comun del proyecto.

ArduPilot, PX4 y Betaflight guardan telemetria en tres formatos binarios
completamente distintos (dataflash .bin, ULog .ulog, blackbox .BBL). En vez
de que el resto del programa (mapas, deteccion de anomalias, informe) tenga
que conocer los tres formatos, cada parser especifico traduce su log a las
clases de este archivo. A partir de aqui todo el pipeline es agnostico al
origen: solo ve FlightLog / FlightRecord / FlightEvent.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class Source(StrEnum):
    """Formato de origen del log. Se guarda en el FlightLog para citarlo en el informe."""

    ARDUPILOT = "ardupilot"
    PX4 = "px4"
    BETAFLIGHT = "betaflight"


@dataclass
class FlightRecord:
    """
    Una muestra de telemetria en un instante concreto, ya normalizada.

    Todos los campos salvo `timestamp` son Optional porque no todos los
    formatos reportan lo mismo (p.ej. Betaflight no suele traer GPS en drones
    de carreras/FPV sin modulo GPS instalado). El resto del codigo debe
    tratar cualquier campo como potencialmente ausente.
    """

    timestamp: float  # segundos desde el inicio del log (tiempo relativo, no epoch Unix)
    lat: float | None = None  # grados decimales (WGS84)
    lon: float | None = None  # grados decimales (WGS84)
    alt: float | None = None  # metros, relativo al punto de despegue/home
    groundspeed: float | None = None  # m/s
    battery_voltage: float | None = None  # voltios
    battery_current: float | None = None  # amperios
    rc_signal: float | None = None  # calidad/potencia del enlace de radiocontrol (escala depende del formato)
    flight_mode: str | None = None  # modo de vuelo tal cual lo reporta el firmware (STABILIZE, LOITER, ACRO...)
    roll: float | None = None  # grados
    pitch: float | None = None  # grados
    yaw: float | None = None  # grados


@dataclass
class FlightEvent:
    """
    Un suceso puntual del vuelo, distinto de una muestra continua de telemetria.

    Se generan en tres sitios: (1) durante el parseo, para eventos que el
    propio firmware marca explicitamente en el log (cambio de modo,
    failsafe armado por el autopiloto); (2) en src/analysis/anomalies.py,
    por reglas explicitas sobre la serie temporal (p.ej. caida brusca de
    altitud = posible impacto); y (3) en src/analysis/ml_anomalies.py, por
    un modelo estadistico (Isolation Forest) que aprende que es "normal"
    para este vuelo en concreto y señala lo que se sale de ese patron.
    """

    timestamp: float
    # "rc_loss" | "battery_critical" | "gps_glitch" | "mode_change" | "possible_impact" | "ml_anomaly_*" | ...
    category: str
    severity: str  # "info" | "warning" | "critical"
    description: str
    # "rule" (regla explicita, incluye los que vienen del propio firmware) o
    # "ml" (modelo estadistico). Sirve para que el informe distinga
    # visualmente un hallazgo justificable por una regla concreta de uno
    # detectado por patron estadistico, que merece mas escrutinio humano.
    method: str = "rule"


@dataclass
class FlightLog:
    """
    Resultado completo de parsear un log de vuelo.

    Es el "contrato" que conecta las tres fases del pipeline:
    parser -> analysis (trayectoria + anomalias) -> report (informe HTML).
    Ningun modulo aguas abajo del parser debe importar pymavlink ni pyulog
    directamente: todo pasa por FlightLog.
    """

    source: Source
    source_file: str
    records: list[FlightRecord] = field(default_factory=list)
    events: list[FlightEvent] = field(default_factory=list)
    # metadata libre: numero de serie del vehiculo, version de firmware, etc.
    # Se guarda como dict porque cada formato expone campos distintos y no
    # merece la pena forzar un esquema comun para datos que solo se muestran,
    # no se procesan.
    metadata: dict = field(default_factory=dict)

    def duration_seconds(self) -> float:
        """Duracion total cubierta por el log, usada en el resumen del informe."""
        if not self.records:
            return 0.0
        return self.records[-1].timestamp - self.records[0].timestamp

    def sorted_records(self) -> list[FlightRecord]:
        """
        Devuelve los records ordenados por tiempo.

        Los parsers deberian entregarlos ya ordenados, pero algunos formatos
        (sobre todo dataflash de ArduPilot, que interleaved distintos tipos
        de mensaje) pueden generar timestamps ligeramente fuera de orden al
        fusionar mensajes de distintos sensores. Ordenar aqui, en un solo
        punto, evita que cada consumidor tenga que acordarse de hacerlo.
        """
        return sorted(self.records, key=lambda r: r.timestamp)
