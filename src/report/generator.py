"""
Generador del informe final: combina mapa + timeline + hallazgos en un unico HTML.

El informe se genera como un unico archivo HTML autocontenido (el mapa y los
graficos se incrustan como HTML/JS embebido, no como archivos separados)
para que sea facil de compartir o archivar como evidencia: un solo fichero,
sin dependencias externas ni conexion a internet para visualizarlo.
"""

from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..analysis.geo import extract_geo_points, haversine_distance_m
from ..analysis.impact import estimate_impact
from ..analysis.integrity import check_integrity
from ..analysis.trajectory import build_route_map, build_telemetry_timeline
from ..analysis.video_sync import SyncedEvent
from ..parsers.base import FlightLog
from .i18n import (
    METHOD_LABELS,
    SEVERITY_LABELS,
    labels_for,
    normalize_lang,
    translate_assumptions,
    translate_event,
    translate_finding,
    translate_integrity_summary,
    ui,
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _compute_summary(flight_log: FlightLog) -> dict:
    """
    Calcula las metricas de resumen que encabezan el informe.

    Se separa en su propia funcion (en vez de calcularlo inline en la
    plantilla Jinja2) porque son calculos, no presentacion: Jinja2 deberia
    limitarse a formatear datos ya calculados, no a hacer logica de negocio.
    """
    records = flight_log.sorted_records()
    geo_points = extract_geo_points(records)

    total_distance_m = sum(
        (
            haversine_distance_m(lat1, lon1, lat2, lon2)
            for (lat1, lon1), (lat2, lon2) in zip(geo_points, geo_points[1:], strict=False)
        ),
        start=0.0,
    )

    altitudes = [r.alt for r in records if r.alt is not None]
    speeds = [r.groundspeed for r in records if r.groundspeed is not None]

    events_by_severity = {"critical": 0, "warning": 0, "info": 0}
    for event in flight_log.events:
        events_by_severity[event.severity] = events_by_severity.get(event.severity, 0) + 1

    return {
        "source_format": flight_log.source.value,
        "source_file": Path(flight_log.source_file).name,
        "duration_seconds": flight_log.duration_seconds(),
        "total_distance_m": total_distance_m,
        "max_altitude_m": max(altitudes, default=None),
        "max_speed_ms": max(speeds, default=None),
        "record_count": len(records),
        "events_by_severity": events_by_severity,
    }


def generate_report(
    flight_log: FlightLog,
    output_path: str,
    mass_kg: float | None = None,
    synced_events: list[SyncedEvent] | None = None,
    lang: str = "es",
) -> str:
    """
    Genera el informe HTML de un FlightLog ya parseado (y, idealmente, ya pasado por detect_anomalies).

    Devuelve la ruta del archivo generado. No llama a detect_anomalies aqui
    a proposito: el CLI decide explicitamente cuando correr la deteccion de
    anomalias, para que este modulo se limite a presentar lo que ya se
    calculo, sin efectos secundarios ocultos.

    `mass_kg` es opcional y solo se usa para estimar la energia cinetica de
    impacto (ver src/analysis/impact.py): sin ella, la estimacion de impacto
    se sigue calculando (posicion, velocidad) pero sin energia.

    `synced_events` es opcional: si se aporta (ver src/analysis/video_sync.py),
    el informe incluye una seccion cruzando cada evento con su fotograma de
    video correspondiente y la verificacion cruzada de GPS log-vs-video.

    `lang` ("es"/"en"/"de") controla en que idioma se renderiza TODO el texto
    del informe: tanto la estructura fija de la plantilla como la descripcion
    de cada hallazgo concreto, reconstruida en el momento a partir de su
    message_key (ver src/report/i18n.py). El campo `description` original de
    cada FlightEvent/IntegrityFinding no se toca (sigue en español, ver
    parsers/base.py); esta funcion solo decide que texto ENSEÑAR.
    """
    lang = normalize_lang(lang)
    strings = ui(lang)

    impact = estimate_impact(flight_log, mass_kg=mass_kg)
    integrity = check_integrity(flight_log)

    route_map = build_route_map(flight_log, impact_estimate=impact, lang=lang)
    timeline_fig = build_telemetry_timeline(flight_log, lang=lang)

    # _repr_html_() de folium ya devuelve un <iframe srcdoc="..."> autonomo,
    # lo que evita colisiones de CSS/JS entre el mapa (Leaflet) y el resto
    # de la pagina del informe.
    map_html = route_map._repr_html_()

    # include_plotlyjs=True incrusta la libreria plotly.js completa dentro
    # del propio HTML (en vez de cargarla desde un CDN), para que el informe
    # se pueda abrir sin conexion a internet.
    timeline_html = timeline_fig.to_html(full_html=False, include_plotlyjs=True)

    events = [
        {
            "timestamp": event.timestamp,
            "category": event.category,
            "severity": event.severity,
            "description": translate_event(event, lang),
            "method": event.method,
        }
        for event in sorted(flight_log.events, key=lambda e: e.timestamp)
    ]

    impact_view = None
    if impact is not None:
        impact_view = {
            **impact.__dict__,
            "assumptions": translate_assumptions(impact.assumption_keys, lang),
        }

    integrity_view = {
        "looks_clean": integrity.looks_clean,
        "summary": translate_integrity_summary(integrity.findings, lang),
        "findings": [
            {
                "kind": finding.kind,
                "field": finding.field,
                "timestamp": finding.timestamp,
                "severity": finding.severity,
                "description": translate_finding(finding, lang),
            }
            for finding in integrity.findings
        ],
    }

    synced_events_view = None
    if synced_events is not None:
        synced_events_view = [
            {
                "flight_event_timestamp": se.flight_event_timestamp,
                "video_timestamp_s": se.video_timestamp_s,
                "description": translate_event(se, lang),
                "gps_cross_check_distance_m": se.gps_cross_check_distance_m,
            }
            for se in synced_events
        ]

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html")

    rendered = template.render(
        t=strings,
        lang=lang,
        severity_labels=labels_for(SEVERITY_LABELS, lang),
        method_labels=labels_for(METHOD_LABELS, lang),
        summary=_compute_summary(flight_log),
        events=events,
        map_html=map_html,
        timeline_html=timeline_html,
        impact=impact_view,
        integrity=integrity_view,
        synced_events=synced_events_view,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    )

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(rendered, encoding="utf-8")
    return str(output_file)
