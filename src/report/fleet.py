"""
Panel multi-vuelo: analiza varios logs a la vez y genera un unico informe comparativo.

Un informe individual (src/report/generator.py) responde "¿que paso en ESTE
vuelo?". Este modulo responde una pregunta distinta: "¿hay un patron que se
repite en varios incidentes?", "¿que vuelos tienen indicios de integridad
cuestionable?", "¿cual fue el mas grave?". Es la diferencia entre mirar un
informe de accidente aislado y mirar las estadisticas de una flota entera.

Deliberadamente NO repite el detalle completo (mapa+timeline interactivos a
tamaño completo) de cada vuelo dentro de este archivo: con varios vuelos, la
libreria plotly.js embebida por cada uno multiplicaria el tamaño del archivo
sin necesidad. Para el detalle de un vuelo concreto se sigue usando
generate_report() sobre ese log de forma individual.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import folium
import plotly.graph_objects as go
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..analysis.geo import haversine_distance_m
from ..analysis.impact import estimate_impact
from ..analysis.integrity import check_integrity
from ..parsers.base import FlightLog

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Paleta fija (no generada al azar) para que el color de cada vuelo sea
# reproducible entre ejecuciones y se pueda citar ("el vuelo azul") sin
# ambiguedad. Si hay mas vuelos que colores, el ciclo se repite.
_ROUTE_COLORS = ["#2b6cb0", "#38a169", "#d69e2e", "#805ad5", "#dd6b20", "#c53030", "#319795", "#b83280"]


@dataclass
class FlightSummary:
    """Una fila de la tabla comparativa: resumen ligero de un vuelo, no el FlightLog completo."""

    source_file: str
    source_format: str
    duration_seconds: float
    total_distance_m: float
    critical_events: int
    warning_events: int
    has_impact_estimate: bool
    integrity_clean: bool
    color: str


def _summarize_flight(flight_log: FlightLog, color: str) -> FlightSummary:
    """Reduce un FlightLog completo a los datos que interesan en la tabla comparativa."""
    records = flight_log.sorted_records()
    geo_records = [r for r in records if r.lat is not None and r.lon is not None]
    total_distance_m = sum(
        haversine_distance_m(a.lat, a.lon, b.lat, b.lon) for a, b in zip(geo_records, geo_records[1:])
    )
    critical = sum(1 for e in flight_log.events if e.severity == "critical")
    warning = sum(1 for e in flight_log.events if e.severity == "warning")

    return FlightSummary(
        source_file=Path(flight_log.source_file).name,
        source_format=flight_log.source.value,
        duration_seconds=flight_log.duration_seconds(),
        total_distance_m=total_distance_m,
        critical_events=critical,
        warning_events=warning,
        has_impact_estimate=estimate_impact(flight_log) is not None,
        integrity_clean=check_integrity(flight_log).looks_clean,
        color=color,
    )


def _build_combined_map(flight_logs: list[FlightLog], colors: list[str]) -> folium.Map:
    """Superpone la ruta de cada vuelo en un unico mapa, un color fijo por vuelo."""
    all_points = []
    for flight_log in flight_logs:
        records = flight_log.sorted_records()
        all_points.extend((r.lat, r.lon) for r in records if r.lat is not None and r.lon is not None)

    if not all_points:
        return folium.Map(location=[0, 0], zoom_start=2)

    fmap = folium.Map(location=all_points[len(all_points) // 2], zoom_start=12)
    for flight_log, color in zip(flight_logs, colors):
        records = flight_log.sorted_records()
        points = [(r.lat, r.lon) for r in records if r.lat is not None and r.lon is not None]
        if not points:
            continue  # este vuelo en concreto no tiene GPS (p.ej. Betaflight sin modulo GPS)
        name = Path(flight_log.source_file).name
        folium.PolyLine(points, color=color, weight=3, opacity=0.8, tooltip=name).add_to(fmap)
        folium.CircleMarker(points[0], radius=6, color=color, fill=True, fill_opacity=1, tooltip=f"Inicio — {name}").add_to(fmap)

    return fmap


def _build_anomaly_histogram(flight_logs: list[FlightLog]) -> go.Figure:
    """
    Cuenta cuantas veces aparece cada categoria de anomalia en TODO el conjunto de vuelos.

    Es el grafico que responde "¿que suele fallar en esta flota?" en vez de
    "¿que fallo en este vuelo?" — la pregunta que solo tiene sentido cuando
    se analizan varios vuelos juntos.
    """
    counter: Counter[str] = Counter()
    for flight_log in flight_logs:
        for event in flight_log.events:
            if event.severity != "info":
                counter[event.category] += 1

    categories = list(counter.keys())
    counts = [counter[c] for c in categories]

    fig = go.Figure(go.Bar(x=categories, y=counts, marker_color="#2b6cb0"))
    fig.update_layout(
        title_text="Categorías de anomalía más frecuentes en el conjunto",
        xaxis_title="Categoría",
        yaxis_title="Nº de veces detectada",
        height=400,
    )
    return fig


def generate_fleet_report(flight_logs: list[FlightLog], output_path: str) -> str:
    """
    Genera el informe comparativo a partir de varios FlightLog ya parseados.

    Igual que generate_report(), no ejecuta detect_anomalies aqui: se asume
    que el llamador ya lo hizo sobre cada FlightLog antes de pasarlo.
    """
    colors = [_ROUTE_COLORS[i % len(_ROUTE_COLORS)] for i in range(len(flight_logs))]
    summaries = [_summarize_flight(fl, color) for fl, color in zip(flight_logs, colors)]

    map_html = _build_combined_map(flight_logs, colors)._repr_html_()
    histogram_html = _build_anomaly_histogram(flight_logs).to_html(full_html=False, include_plotlyjs=True)

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=select_autoescape(["html"]))
    template = env.get_template("fleet_report.html")

    rendered = template.render(
        flights=summaries,
        flight_count=len(flight_logs),
        total_critical=sum(s.critical_events for s in summaries),
        total_warning=sum(s.warning_events for s in summaries),
        flights_with_integrity_issues=sum(1 for s in summaries if not s.integrity_clean),
        flights_with_impact=sum(1 for s in summaries if s.has_impact_estimate),
        map_html=map_html,
        histogram_html=histogram_html,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(rendered, encoding="utf-8")
    return str(output_file)
