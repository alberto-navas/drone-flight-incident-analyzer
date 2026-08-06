"""
Reconstruccion visual del vuelo: mapa de la ruta + timeline de telemetria.

Este modulo solo lee FlightLog (nunca pymavlink/pyulog directamente), asi
que funciona igual sea cual sea el formato de origen del log.
"""

import folium
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ..parsers.base import FlightLog
from .impact import ImpactEstimate

# Colores fijos por severidad, reutilizados tanto en el mapa como en el
# timeline para que un mismo evento se reconozca visualmente en los dos sitios.
_SEVERITY_COLORS = {"info": "blue", "warning": "orange", "critical": "red"}


def build_route_map(flight_log: FlightLog, impact_estimate: ImpactEstimate | None = None) -> folium.Map:
    """
    Genera un mapa Leaflet con la ruta de vuelo y marcadores de despegue/aterrizaje/eventos.

    Se apoya solo en los FlightRecord que tienen lat/lon (muchos records de
    ArduPilot/PX4 no traen posicion, p.ej. los que solo llevan bateria o
    actitud), por eso se filtran explicitamente antes de dibujar la ruta.

    Si se pasa `impact_estimate` (ver src/analysis/impact.py), se dibuja
    ademas una linea discontinua desde el ultimo punto conocido hasta el
    punto de impacto proyectado, para distinguir visualmente "lo que el log
    registro de verdad" de "lo que se ha extrapolado".
    """
    records = flight_log.sorted_records()
    points = [(r.lat, r.lon) for r in records if r.lat is not None and r.lon is not None]

    if not points:
        # Sin GPS no hay mapa que dibujar (p.ej. un log Betaflight sin modulo
        # GPS instalado). Se devuelve un mapa vacio en vez de lanzar una
        # excepcion, para que el informe siga generandose con el resto de
        # graficos aunque falte esta pieza.
        return folium.Map(location=[0, 0], zoom_start=2)

    fmap = folium.Map(location=points[len(points) // 2], zoom_start=17)
    folium.PolyLine(points, color="#2b6cb0", weight=3, opacity=0.8).add_to(fmap)

    folium.Marker(points[0], tooltip="Despegue / inicio del log", icon=folium.Icon(color="green")).add_to(fmap)
    folium.Marker(points[-1], tooltip="Fin del log", icon=folium.Icon(color="black")).add_to(fmap)

    # Para ubicar cada evento en el mapa, buscamos el record con posicion
    # mas cercano en el tiempo (los eventos no siempre coinciden con una
    # muestra GPS exacta, sobre todo en ArduPilot donde GPS y ERR son
    # mensajes independientes con sus propios timestamps).
    geo_records = [r for r in records if r.lat is not None and r.lon is not None]
    for event in flight_log.events:
        if event.severity == "info":
            continue  # solo marcamos warnings/critical en el mapa para no saturarlo
        nearest = min(geo_records, key=lambda r: abs(r.timestamp - event.timestamp), default=None)
        if nearest is None:
            continue
        folium.Marker(
            (nearest.lat, nearest.lon),
            tooltip=f"[{event.severity}] {event.description}",
            icon=folium.Icon(color=_SEVERITY_COLORS[event.severity]),
        ).add_to(fmap)

    if impact_estimate is not None:
        # `points[-1]` es la ultima posicion GPS real conocida (el ancla que
        # usa impact.py para proyectar), asi que el segmento discontinuo
        # arranca exactamente donde termina la linea solida de la ruta real.
        last_point = points[-1]
        impact_point = (impact_estimate.lat, impact_estimate.lon)
        # Discontinua ("dash_array") para distinguir a simple vista un tramo
        # EXTRAPOLADO (no registrado por el log) de la ruta real, que se
        # dibuja arriba con linea solida.
        folium.PolyLine(
            [last_point, impact_point], color="#c53030", weight=3, opacity=0.9, dash_array="8"
        ).add_to(fmap)
        folium.Marker(
            impact_point,
            tooltip=(
                f"Impacto estimado (proyeccion, no registrado por el log): "
                f"{impact_estimate.total_speed_at_impact_ms:.1f} m/s"
            ),
            icon=folium.Icon(color="red", icon="warning-sign"),
        ).add_to(fmap)

    return fmap


def build_telemetry_timeline(flight_log: FlightLog) -> go.Figure:
    """
    Genera una figura Plotly con 3 sub-graficos apilados: altitud, velocidad/bateria y señal RC.

    Se usan subplots con eje X compartido para poder comparar visualmente,
    por ejemplo, una caida de voltaje de bateria con una caida de altitud en
    el mismo instante.
    """
    records = flight_log.sorted_records()

    def series(field: str):
        """Extrae (tiempos, valores) para un campo, descartando muestras donde ese campo es None."""
        xs, ys = [], []
        for r in records:
            value = getattr(r, field)
            if value is not None:
                xs.append(r.timestamp)
                ys.append(value)
        return xs, ys

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        subplot_titles=("Altitud (m) y velocidad (m/s)", "Bateria", "Señal de radiocontrol"),
        vertical_spacing=0.08,
    )

    alt_x, alt_y = series("alt")
    fig.add_trace(go.Scatter(x=alt_x, y=alt_y, name="Altitud (m)", line=dict(color="#2b6cb0")), row=1, col=1)
    speed_x, speed_y = series("groundspeed")
    fig.add_trace(
        go.Scatter(x=speed_x, y=speed_y, name="Velocidad (m/s)", line=dict(color="#38a169")), row=1, col=1
    )

    volt_x, volt_y = series("battery_voltage")
    fig.add_trace(go.Scatter(x=volt_x, y=volt_y, name="Voltaje (V)", line=dict(color="#d69e2e")), row=2, col=1)

    rssi_x, rssi_y = series("rc_signal")
    fig.add_trace(go.Scatter(x=rssi_x, y=rssi_y, name="Señal RC", line=dict(color="#805ad5")), row=3, col=1)

    # Las lineas verticales marcan cuando ocurrio cada evento no-informativo,
    # superpuestas a los tres sub-graficos a la vez (annotation en el eje X
    # compartido) para poder correlacionar telemetria y sucesos de un vistazo.
    for event in flight_log.events:
        if event.severity == "info":
            continue
        fig.add_vline(
            x=event.timestamp,
            line_dash="dot",
            line_color=_SEVERITY_COLORS[event.severity],
            annotation_text=event.category,
            annotation_position="top",
        )

    fig.update_xaxes(title_text="Tiempo desde el inicio del log (s)", row=3, col=1)
    fig.update_layout(height=800, showlegend=True, title_text=f"Telemetria — {flight_log.source.value}")

    return fig
