"""
Parser de subtitulos SRT de vuelo de DJI (telemetria embebida por fotograma).

Los drones DJI graban, junto al video, un archivo de subtitulos (.srt) con
la posicion GPS/altitud/parametros de camara de CADA fotograma. Es lo que
permite correlacionar imagen y datos: "en el segundo X del video, la
telemetria decia esto".

No existe una libreria oficial de DJI para este formato: es texto informal,
no documentado oficialmente, y ha cambiado entre generaciones de dron. Este
parser reconoce dos variantes conocidas (a traves de dos patrones de texto
distintos) y es tolerante a que falten campos, siguiendo el mismo enfoque
que el parser de Betaflight (ver src/parsers/betaflight.py) ante un formato
inestable entre versiones.

La estructura general del .srt (indice, rango de tiempo, texto) SI es un
estandar bien definido, y para esa parte se usa la libreria `srt` en vez de
parsearla a mano.
"""

import re
from dataclasses import dataclass
from datetime import datetime

import srt

# Variante moderna (series Mavic/Mini recientes), con corchetes tipo
# "[latitude: 47.376900] [longitude: 8.541700] [rel_alt: 10.000 abs_alt: 594.000]".
_MODERN_PATTERN = re.compile(
    r"latitude:\s*(?P<lat>-?\d+\.\d+).*?longitude:\s*(?P<lon>-?\d+\.\d+).*?rel_alt:\s*(?P<alt>-?\d+\.\d+)",
    re.DOTALL,
)

# Variante antigua (Phantom 4 / Mavic Pro), tipo "GPS (8.5417, 47.3769, 594)"
# — nota el orden longitud,latitud,altitud, al reves que la variante moderna.
_LEGACY_GPS_PATTERN = re.compile(
    r"GPS\s*\(\s*(?P<lon>-?\d+\.?\d*)\s*,\s*(?P<lat>-?\d+\.?\d*)\s*,\s*(?P<alt>-?\d+\.?\d*)\s*\)"
)

# Fecha/hora real de grabacion, cuando el SRT la incluye (variante moderna).
# Sirve para alinear automaticamente video y log si el log tambien expusiera
# una hora real (ver limitacion documentada en src/analysis/video_sync.py).
_ABSOLUTE_TIME_PATTERN = re.compile(r"(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:[.,]\d+)?)")


@dataclass
class VideoTelemetryFrame:
    """Telemetria asociada a un fotograma/subtitulo concreto del video."""

    video_timestamp_s: float  # segundos desde el INICIO DEL VIDEO (no del log de vuelo)
    absolute_time: datetime | None
    lat: float | None
    lon: float | None
    alt: float | None


def _extract_position(text: str) -> tuple[float | None, float | None, float | None]:
    """Prueba los patrones conocidos, en orden, y devuelve (lat, lon, alt) del primero que coincide."""
    match = _MODERN_PATTERN.search(text)
    if match:
        return float(match["lat"]), float(match["lon"]), float(match["alt"])

    match = _LEGACY_GPS_PATTERN.search(text)
    if match:
        return float(match["lat"]), float(match["lon"]), float(match["alt"])

    return None, None, None


def _extract_absolute_time(text: str) -> datetime | None:
    match = _ABSOLUTE_TIME_PATTERN.search(text)
    if not match:
        return None
    raw = match["dt"].replace(",", ".")
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f" if "." in raw else "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None  # texto con pinta de fecha pero que no lo es realmente; se ignora, no se rompe el parseo


def parse_dji_srt(file_path: str) -> list[VideoTelemetryFrame]:
    """Lee un archivo .srt de DJI y devuelve la telemetria de cada fotograma/subtitulo."""
    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    frames = []
    for subtitle in srt.parse(content):
        # El punto medio del rango de tiempo del subtitulo representa mejor
        # el instante del fotograma que el inicio o el final del intervalo.
        midpoint = (subtitle.start + subtitle.end) / 2
        lat, lon, alt = _extract_position(subtitle.content)
        frames.append(
            VideoTelemetryFrame(
                video_timestamp_s=midpoint.total_seconds(),
                absolute_time=_extract_absolute_time(subtitle.content),
                lat=lat,
                lon=lon,
                alt=alt,
            )
        )
    return frames
