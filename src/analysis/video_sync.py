"""
Cruce entre el vídeo (subtítulos SRT de DJI) y el log de vuelo.

El SRT mide el tiempo desde el inicio de la GRABACIÓN de vídeo; el log de
vuelo mide el tiempo desde el inicio del LOG. No son el mismo instante
salvo coincidencia, así que no se pueden comparar sus timestamps
directamente sin alinear antes los dos relojes. Este módulo ofrece dos
formas de alinear:

1. **Offset manual**: el usuario indica cuántos segundos después del inicio
   del log empezó a grabar el vídeo (calibrado a mano, p.ej. viendo un
   evento reconocible en ambos — un despegue, un giro brusco). Es el método
   más simple y siempre disponible.
2. **Alineación automática por hora absoluta**: si el SRT trae fecha/hora
   real (variante moderna de DJI) Y se conoce la hora real UTC de inicio
   del log, el offset se puede calcular solo. Los parsers de log de este
   proyecto normalizan el tiempo a relativo desde el primer registro (ver
   docstrings de src/parsers/ardupilot.py y src/parsers/px4.py) y no
   exponen la hora real, así que esta vía queda preparada en el código pero
   requiere que quien la use aporte esa hora real por otro medio.

Además de correlacionar timestamps, este módulo hace algo más interesante:
compara la posición GPS que dice el LOG con la que dice el VÍDEO para el
mismo instante. Son dos fuentes de GPS independientes (el receptor del
autopiloto y el receptor de la cámara/gimbal); si no coinciden, es otra
señal de que algo no cuadra — la misma lógica de fondo que
src/analysis/integrity.py, aplicada a una fuente de datos externa al log.
"""

import dataclasses
from dataclasses import dataclass
from datetime import datetime

from ..parsers.base import FlightLog
from ..parsers.dji_srt import VideoTelemetryFrame
from .geo import haversine_distance_m


@dataclass
class SyncedEvent:
    """Un evento del log de vuelo con su fotograma de vídeo correlacionado (si se pudo alinear)."""

    flight_event_timestamp: float
    video_timestamp_s: float | None
    description: str  # siempre en español; ver message_key para re-renderizar en otro idioma
    gps_cross_check_distance_m: float | None
    message_key: str | None = None
    message_params: dict = dataclasses.field(default_factory=dict)
    # Presentes solo para que translate_event() (src/report/i18n.py) pueda tratar un
    # SyncedEvent igual que un FlightEvent sin distinguir tipos; un SyncedEvent nunca
    # representa un episodio fusionado, asi que siempre quedan a None.
    episode_duration_s: float | None = None
    episode_sample_count: int | None = None


def resolve_offset(video_frames: list[VideoTelemetryFrame], flight_log_start_utc: datetime | None) -> float | None:
    """
    Calcula el offset (segundos a sumar al timestamp del log para obtener el
    timestamp de vídeo equivalente), si hay información suficiente.

    Devuelve None si no se puede resolver automáticamente (no se dio la
    hora de inicio del log, o el SRT no trae hora absoluta en ningún
    fotograma) — en ese caso, quien llame debe usar un offset manual.
    """
    if flight_log_start_utc is None:
        return None

    frame_with_time = next((f for f in video_frames if f.absolute_time is not None), None)
    if frame_with_time is None:
        return None
    # El filtro del generador de arriba garantiza esto en tiempo de
    # ejecucion, pero mypy no propaga esa narrowing de "f" a "frame_with_time".
    assert frame_with_time.absolute_time is not None

    seconds_into_log_when_frame_was_recorded = (frame_with_time.absolute_time - flight_log_start_utc).total_seconds()
    return frame_with_time.video_timestamp_s - seconds_into_log_when_frame_was_recorded


def _nearest_frame(video_frames: list[VideoTelemetryFrame], target_video_ts: float) -> VideoTelemetryFrame | None:
    if not video_frames:
        return None
    return min(video_frames, key=lambda f: abs(f.video_timestamp_s - target_video_ts))


def _cross_check_gps(
    flight_log: FlightLog, event_timestamp: float, video_frame: VideoTelemetryFrame | None
) -> float | None:
    """Distancia entre el GPS del log y el GPS del vídeo en el instante correlacionado, o None si falta algún dato."""
    if video_frame is None or video_frame.lat is None or video_frame.lon is None:
        return None
    geo_records = [r for r in flight_log.sorted_records() if r.lat is not None and r.lon is not None]
    if not geo_records:
        return None
    nearest_log_record = min(geo_records, key=lambda r: abs(r.timestamp - event_timestamp))
    assert nearest_log_record.lat is not None and nearest_log_record.lon is not None  # geo_records ya filtrada
    return haversine_distance_m(nearest_log_record.lat, nearest_log_record.lon, video_frame.lat, video_frame.lon)


def sync_events_with_video(
    flight_log: FlightLog, video_frames: list[VideoTelemetryFrame], offset_s: float
) -> list[SyncedEvent]:
    """
    Para cada evento no-informativo del log, busca el fotograma de vídeo más
    cercano en el tiempo (tras aplicar el offset) y devuelve la correlación.

    `offset_s`: segundos que hay que SUMAR al timestamp del log para obtener
    el timestamp equivalente en el vídeo. Se calcula con resolve_offset() si
    hay hora absoluta disponible, o se aporta a mano.
    """
    synced = []
    for event in flight_log.events:
        if event.severity == "info":
            continue
        target_video_ts = event.timestamp + offset_s
        nearest_frame = _nearest_frame(video_frames, target_video_ts)

        synced.append(
            SyncedEvent(
                flight_event_timestamp=event.timestamp,
                video_timestamp_s=nearest_frame.video_timestamp_s if nearest_frame else None,
                description=event.description,
                gps_cross_check_distance_m=_cross_check_gps(flight_log, event.timestamp, nearest_frame),
                message_key=event.message_key,
                message_params=event.message_params,
            )
        )
    return synced
