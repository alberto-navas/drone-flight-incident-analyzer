"""
Traduccion del informe (ES/EN/DE): textos fijos de la interfaz y plantillas
de los mensajes dinamicos que genera el analisis.

Decision de diseno central: los eventos/hallazgos (FlightEvent,
IntegrityFinding) siguen guardando su descripcion en español en el campo
`description` de siempre (para no romper nada que dependa de ese valor por
defecto), pero ADEMAS guardan `message_key` + `message_params`: la clave de
la plantilla y los valores numericos/textuales que la rellenan. Este modulo
usa esas dos cosas para volver a renderizar el mismo mensaje en otro idioma
en el momento de generar el informe, sin tener que tocar cada detector cada
vez que se añade un idioma.

Los textos ESTATICOS de la plantilla (titulos de seccion, cabeceras de
tabla, etiquetas...) viven aparte, en UI_STRINGS, y se acceden con
`ui(lang)` para pasarlos al contexto de Jinja2 de una vez.
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..analysis.video_sync import SyncedEvent
    from ..parsers.base import FlightEvent

SUPPORTED_LANGUAGES = ("es", "en", "de")
DEFAULT_LANGUAGE = "es"


def normalize_lang(lang: str | None) -> str:
    """Devuelve `lang` si es uno de los soportados, o el idioma por defecto si no."""
    if lang in SUPPORTED_LANGUAGES:
        return lang
    return DEFAULT_LANGUAGE


# ---------------------------------------------------------------------------
# Plantillas de mensajes dinamicos (eventos de vuelo, hallazgos de integridad)
# ---------------------------------------------------------------------------
# Cada clave corresponde a un `message_key` guardado en el FlightEvent /
# IntegrityFinding en el momento de crearlo (ver src/analysis/*.py y
# src/parsers/*.py). Los placeholders {nombre} se rellenan con
# `message_params` via str.format().

EVENT_MESSAGES: dict[str, dict[str, str]] = {
    "gps_glitch": {
        "es": "Salto de posición GPS implica velocidad de {speed:.1f} m/s (umbral: {threshold} m/s); "
        "probable glitch de receptor, no movimiento real.",
        "en": "GPS position jump implies a speed of {speed:.1f} m/s (threshold: {threshold} m/s); "
        "likely a receiver glitch, not real movement.",
        "de": "Der GPS-Positionssprung impliziert eine Geschwindigkeit von {speed:.1f} m/s (Schwelle: "
        "{threshold} m/s); wahrscheinlich ein Empfängerfehler, keine echte Bewegung.",
    },
    "possible_impact": {
        "es": "Descenso de {rate:.1f} m/s (umbral: {threshold} m/s); posible caída o pérdida de control.",
        "en": "Descent of {rate:.1f} m/s (threshold: {threshold} m/s); possible crash or loss of control.",
        "de": "Sinkflug von {rate:.1f} m/s (Schwelle: {threshold} m/s); möglicher Absturz oder Kontrollverlust.",
    },
    "battery_critical": {
        "es": "Caída de voltaje de {rate:.2f} V/s (umbral: {threshold} V/s); posible fallo de celda o cortocircuito.",
        "en": "Voltage drop of {rate:.2f} V/s (threshold: {threshold} V/s); possible cell failure or short circuit.",
        "de": "Spannungsabfall von {rate:.2f} V/s (Schwelle: {threshold} V/s); "
        "möglicher Zellenfehler oder Kurzschluss.",
    },
    "rc_signal_low": {
        "es": "Señal RC cayó a {signal:.0f} (umbral: {threshold})",
        "en": "RC signal dropped to {signal:.0f} (threshold: {threshold})",
        "de": "RC-Signal fiel auf {signal:.0f} (Schwelle: {threshold})",
    },
    "ml_anomaly": {
        "es": "Patrón estadísticamente anómalo (Isolation Forest, entrenado solo con este vuelo); la "
        "magnitud que más se desvía de lo habitual es '{feature}' ({value:.2f}, {z_score:.1f} "
        "desviaciones estándar).",
        "en": "Statistically anomalous pattern (Isolation Forest, trained only on this flight); the metric "
        "that deviates most from normal is '{feature}' ({value:.2f}, {z_score:.1f} standard deviations).",
        "de": "Statistisch auffälliges Muster (Isolation Forest, nur mit diesem Flug trainiert); die Größe, "
        "die am stärksten vom Normalwert abweicht, ist „{feature}“ ({value:.2f}, {z_score:.1f} "
        "Standardabweichungen).",
    },
    "mode_change": {
        "es": "Cambio de modo de vuelo a {mode}",
        "en": "Flight mode changed to {mode}",
        "de": "Flugmodus geändert zu {mode}",
    },
    "firmware_error": {
        "es": "Error de firmware en subsistema '{subsys}' (código {code})",
        "en": "Firmware error in subsystem '{subsys}' (code {code})",
        "de": "Firmware-Fehler im Subsystem „{subsys}“ (Code {code})",
    },
    "firmware_event": {
        "es": "Evento de firmware id={event_id}",
        "en": "Firmware event id={event_id}",
        "de": "Firmware-Ereignis ID={event_id}",
    },
    "failsafe_activated": {
        "es": "Failsafe activado (fase {phase})",
        "en": "Failsafe activated (phase {phase})",
        "de": "Failsafe aktiviert (Phase {phase})",
    },
    "rc_signal_lost": {
        "es": "Se dejó de recibir señal de radiocontrol válida",
        "en": "Stopped receiving a valid radio control signal",
        "de": "Kein gültiges Fernsteuerungssignal mehr empfangen",
    },
    "time_reversal": {
        "es": "El tiempo retrocede en el flujo de '{field}': una muestra en t={ts:.2f}s llega después de "
        "otra en t={last_ts:.2f}s dentro del mismo archivo. Puede indicar un log editado/empalmado, "
        "o corrupción del archivo.",
        "en": "Time goes backwards in the '{field}' stream: a sample at t={ts:.2f}s arrives after one at "
        "t={last_ts:.2f}s within the same file. May indicate an edited/spliced log, or file corruption.",
        "de": "Die Zeit läuft im Datenstrom „{field}“ rückwärts: Eine Messung bei t={ts:.2f}s erscheint "
        "nach einer bei t={last_ts:.2f}s innerhalb derselben Datei. Das kann auf ein "
        "bearbeitetes/zusammengefügtes Log oder eine beschädigte Datei hindeuten.",
    },
    "suspicious_gap": {
        "es": "Hueco de {gap:.1f}s sin ninguna muestra de telemetría (de t={a:.2f}s a t={b:.2f}s), frente a "
        "una cadencia habitual de ~{median:.2f}s entre muestras. Puede ser una pérdida de señal real, "
        "o un tramo del log eliminado.",
        "en": "{gap:.1f}s gap with no telemetry samples (from t={a:.2f}s to t={b:.2f}s), versus a typical "
        "cadence of ~{median:.2f}s between samples. May be a real signal loss, or a deleted section "
        "of the log.",
        "de": "{gap:.1f}s Lücke ohne Telemetriedaten (von t={a:.2f}s bis t={b:.2f}s), gegenüber einer "
        "üblichen Taktung von ~{median:.2f}s zwischen den Messungen. Kann ein echter Signalverlust "
        "sein oder ein gelöschter Abschnitt des Logs.",
    },
}

# Sufijo que consolidate_episodes() añade cuando fusiona varias muestras
# consecutivas del mismo hallazgo en un unico episodio (ver anomalies.py).
EPISODE_SUFFIX: dict[str, str] = {
    "es": " — sostenido durante {duration:.1f}s ({count} muestras)",
    "en": " — sustained for {duration:.1f}s ({count} samples)",
    "de": " — anhaltend über {duration:.1f}s ({count} Messungen)",
}


def translate_event(event: "FlightEvent | SyncedEvent", lang: str) -> str:
    """
    Renderiza la descripcion de un FlightEvent (o un SyncedEvent, que lleva
    los mismos campos message_key/message_params, ver video_sync.py) en `lang`.

    Si el evento no tiene `message_key` (p.ej. un logged_message de PX4,
    que es texto libre que el propio firmware escribio en su idioma
    original) se devuelve `description` tal cual: no hay nada que traducir,
    esa cadena no es nuestra.
    """
    lang = normalize_lang(lang)
    if not event.message_key or event.message_key not in EVENT_MESSAGES:
        return event.description

    template = EVENT_MESSAGES[event.message_key][lang]
    text = template.format(**event.message_params)

    if event.episode_duration_s is not None and event.episode_sample_count is not None:
        text += EPISODE_SUFFIX[lang].format(duration=event.episode_duration_s, count=event.episode_sample_count)
    return text


def translate_finding(finding, lang: str) -> str:
    """Igual que translate_event() pero para IntegrityFinding (ver src/analysis/integrity.py)."""
    lang = normalize_lang(lang)
    if not finding.message_key or finding.message_key not in EVENT_MESSAGES:
        return finding.description
    return EVENT_MESSAGES[finding.message_key][lang].format(**finding.message_params)


# ---------------------------------------------------------------------------
# Resumen de integridad: se recalcula en el idioma pedido a partir de los
# propios hallazgos ya traducidos, en vez de guardar un resumen fijo en
# español dentro de IntegrityReport.
# ---------------------------------------------------------------------------

_INTEGRITY_SUMMARY_CLEAN: dict[str, str] = {
    "es": "No se encontraron indicios de manipulación o corrupción en este log.",
    "en": "No signs of tampering or corruption were found in this log.",
    "de": "Es wurden keine Hinweise auf Manipulation oder Beschädigung in diesem Log gefunden.",
}

_INTEGRITY_SUMMARY_DIRTY: dict[str, str] = {
    "es": "Se encontraron {n} indicio(s) ({critical} crítico(s), {warning} de advertencia). Esto no "
    "prueba manipulación por sí solo: cada hallazgo debe revisarse en su contexto.",
    "en": "{n} finding(s) were found ({critical} critical, {warning} warning). This alone doesn't prove "
    "tampering: each finding should be reviewed in context.",
    "de": "{n} Hinweis(e) gefunden ({critical} kritisch, {warning} Warnung). Das allein beweist keine "
    "Manipulation: jeder Fund sollte im Kontext geprüft werden.",
}


def translate_integrity_summary(findings: list, lang: str) -> str:
    """Recalcula el resumen de la verificacion de integridad en `lang` a partir de la lista de hallazgos."""
    lang = normalize_lang(lang)
    if not findings:
        return _INTEGRITY_SUMMARY_CLEAN[lang]
    n_critical = sum(1 for f in findings if f.severity == "critical")
    n_warning = sum(1 for f in findings if f.severity == "warning")
    return _INTEGRITY_SUMMARY_DIRTY[lang].format(n=len(findings), critical=n_critical, warning=n_warning)


# ---------------------------------------------------------------------------
# Asunciones de la estimacion de impacto (src/analysis/impact.py): son
# frases fijas, sin valores interpolados salvo la que depende de si se dio
# la masa del vehiculo, asi que basta con una clave simple por frase.
# ---------------------------------------------------------------------------

ASSUMPTION_MESSAGES: dict[str, dict[str, str]] = {
    "terrain_flat": {
        "es": "Terreno llano a la misma altitud que el punto de despegue: en terreno con desnivel "
        "(relevante en entornos alpinos) el punto real de impacto puede estar antes o después del "
        "estimado.",
        "en": "Flat terrain at the same altitude as the takeoff point: on sloped terrain (relevant in "
        "alpine environments) the real impact point may be before or after the estimate.",
        "de": "Ebenes Gelände auf gleicher Höhe wie der Startpunkt: bei geneigtem Gelände (relevant in "
        "alpinen Umgebungen) kann der tatsächliche Aufprallpunkt vor oder hinter der Schätzung liegen.",
    },
    "ballistic_simple": {
        "es": "Trayectoria balística simple (solo gravedad) desde la última muestra conocida: no se "
        "modela resistencia del aire ni posibles maniobras del piloto/autopiloto tras el corte del log.",
        "en": "Simple ballistic trajectory (gravity only) from the last known sample: air resistance and "
        "any pilot/autopilot maneuvers after the log cuts off are not modeled.",
        "de": "Einfache ballistische Flugbahn (nur Schwerkraft) ab der letzten bekannten Messung: "
        "Luftwiderstand und mögliche Piloten-/Autopilot-Manöver nach dem Abbruch des Logs werden "
        "nicht berücksichtigt.",
    },
    "constant_heading": {
        "es": "Velocidad horizontal y rumbo constantes desde la última muestra hasta el impacto.",
        "en": "Constant horizontal speed and heading from the last sample until impact.",
        "de": "Konstante horizontale Geschwindigkeit und Kurs von der letzten Messung bis zum Aufprall.",
    },
    "no_mass": {
        "es": "No se proporcionó la masa del vehículo: no se calcula energía de impacto.",
        "en": "Vehicle mass was not provided: impact energy is not calculated.",
        "de": "Die Fahrzeugmasse wurde nicht angegeben: Die Aufprallenergie wird nicht berechnet.",
    },
}


def translate_assumptions(assumption_keys: list[str], lang: str) -> list[str]:
    lang = normalize_lang(lang)
    return [ASSUMPTION_MESSAGES[key][lang] for key in assumption_keys if key in ASSUMPTION_MESSAGES]


# ---------------------------------------------------------------------------
# Etiquetas cortas (severidad, origen del hallazgo) — se pasan al contexto
# de Jinja2 como diccionarios planos para el idioma activo, y la plantilla
# hace `{{ severity_labels[event.severity] }}`.
# ---------------------------------------------------------------------------

SEVERITY_LABELS: dict[str, dict[str, str]] = {
    "critical": {"es": "crítico", "en": "critical", "de": "kritisch"},
    "warning": {"es": "advertencia", "en": "warning", "de": "Warnung"},
    "info": {"es": "información", "en": "info", "de": "Info"},
}

METHOD_LABELS: dict[str, dict[str, str]] = {
    "rule": {"es": "regla", "en": "rule", "de": "Regel"},
    "ml": {"es": "ML", "en": "ML", "de": "ML"},
}


def labels_for(dictionary: dict[str, dict[str, str]], lang: str) -> dict[str, str]:
    """Aplana SEVERITY_LABELS/METHOD_LABELS a un dict {clave: texto} para un idioma, listo para Jinja2."""
    lang = normalize_lang(lang)
    return {key: values[lang] for key, values in dictionary.items()}


# ---------------------------------------------------------------------------
# Textos fijos de la interfaz (informe individual, panel de flota, mapa,
# graficos). Un solo diccionario grande por idioma en vez de decenas de
# pequeños: mas facil de revisar que las 3 versiones de cada frase esten
# completas y sean coherentes entre si.
# ---------------------------------------------------------------------------

UI_STRINGS: dict[str, dict[str, str]] = {
    "es": {
        # Informe individual
        "report_title": "Informe de vuelo",
        "report_h1": "Informe de vuelo — análisis forense",
        "meta_generated": "Generado el {date} · Fuente: {source_format} · {source_file}",
        "status_critical": "Hallazgos críticos",
        "status_warning": "Advertencias",
        "status_clean": "Nominal",
        "stat_duration": "Duración",
        "stat_distance": "Distancia recorrida",
        "stat_max_altitude": "Altitud máxima",
        "stat_max_speed": "Velocidad máxima",
        "stat_critical_events": "Eventos críticos",
        "stat_warnings": "Advertencias",
        "sec_route": "Ruta de vuelo",
        "route_extrapolated_note": "La línea discontinua roja es el tramo EXTRAPOLADO tras el último dato "
        "real del log — ver «03 · Estimación de impacto».",
        "sec_telemetry": "Telemetría",
        "sec_impact": "Estimación de impacto",
        "impact_note": "El log termina en t={last_ts:.1f}s en pleno descenso, antes de tocar el suelo. Lo "
        "siguiente es una PROYECCIÓN física a partir de esa última trayectoria conocida, no un dato "
        "registrado por el dron.",
        "impact_time_to": "Tiempo hasta el impacto",
        "impact_position": "Posición estimada",
        "impact_vspeed": "Velocidad vertical al impacto",
        "impact_tspeed": "Velocidad total al impacto",
        "impact_energy": "Energía cinética estimada",
        "impact_assumptions_title": "Asunciones de esta estimación (léase antes de citar estos números):",
        "sec_video": "Sincronización con vídeo",
        "video_note": "Cada evento del log correlacionado con su fotograma de vídeo más cercano. La "
        "columna «GPS log vs. vídeo» compara la posición que dice el log del autopiloto con la que "
        "dice el archivo de subtítulos del vídeo en ese mismo instante — dos fuentes de GPS "
        "independientes que, si no coinciden, merece la pena revisar.",
        "th_time_log": "Tiempo log (s)",
        "th_time_video": "Tiempo vídeo (s)",
        "th_event": "Evento",
        "th_gps_cross_check": "GPS log vs. vídeo",
        "sec_events": "Línea de tiempo de eventos",
        "th_time": "Tiempo (s)",
        "th_severity": "Severidad",
        "th_origin": "Origen",
        "th_category": "Categoría",
        "th_description": "Descripción",
        "no_events": "No se detectaron eventos.",
        "events_legend": "«regla» = detectado por un umbral explicable (ver código); «ML» = patrón "
        "estadísticamente anómalo detectado por un modelo entrenado solo con este vuelo — merece más "
        "revisión humana antes de sacar conclusiones.",
        "sec_integrity": "Verificación de integridad",
        "integrity_clean_badge": "sin indicios",
        "th_type": "Tipo",
        # Panel de flota
        "fleet_title": "Panel de flota",
        "fleet_h1": "Panel de flota — análisis comparativo",
        "fleet_meta": "Generado el {date} · {n} vuelos analizados conjuntamente",
        "fleet_stat_flights": "Vuelos analizados",
        "fleet_stat_critical": "Eventos críticos (total)",
        "fleet_stat_warning": "Advertencias (total)",
        "fleet_stat_impact": "Vuelos con posible impacto",
        "fleet_stat_integrity": "Vuelos con indicios de integridad",
        "fleet_sec_routes": "Rutas combinadas",
        "fleet_sec_patterns": "Patrones de fallo en el conjunto",
        "fleet_sec_comparison": "Comparativa de vuelos",
        "th_file": "Archivo",
        "th_format": "Formato",
        "th_duration": "Duración",
        "th_distance": "Distancia",
        "th_critical": "Críticos",
        "th_warnings": "Advertencias",
        "th_impact_estimated": "Impacto estimado",
        "th_integrity": "Integridad",
        "tag_yes": "sí",
        "tag_no": "no",
        "tag_review": "revisar",
        "no_flights": "No se analizó ningún vuelo.",
        # Mapa (folium) y leyenda de flota
        "map_takeoff": "Despegue / inicio del log",
        "map_end": "Fin del log",
        "map_impact_marker": "Impacto estimado (proyección, no registrado por el log): {speed:.1f} m/s",
        "map_flight_start": "Inicio",
        "legend_title": "Vuelos",
        "legend_start_point": "● = punto de inicio del vuelo",
        "legend_no_gps": "Sin GPS en el log (no aparecen en el mapa): {names}",
        "legend_no_gps_at_all": "Ningún vuelo del conjunto trae GPS.",
        # Graficos (plotly)
        "chart_altitude_speed": "Altitud (m) y velocidad (m/s)",
        "chart_battery": "Batería",
        "chart_rc_signal": "Señal de radiocontrol",
        "chart_time_axis": "Tiempo desde el inicio del log (s)",
        "chart_telemetry_title": "Telemetría — {source}",
        "chart_altitude": "Altitud (m)",
        "chart_speed": "Velocidad (m/s)",
        "chart_voltage": "Voltaje (V)",
        "chart_rc": "Señal RC",
        "chart_fleet_categories_title": "Categorías de anomalía más frecuentes en el conjunto",
        "chart_category_axis": "Categoría",
        "chart_count_axis": "Nº de veces detectada",
    },
    "en": {
        "report_title": "Flight report",
        "report_h1": "Flight report — forensic analysis",
        "meta_generated": "Generated on {date} · Source: {source_format} · {source_file}",
        "status_critical": "Critical findings",
        "status_warning": "Warnings",
        "status_clean": "Nominal",
        "stat_duration": "Duration",
        "stat_distance": "Distance flown",
        "stat_max_altitude": "Max altitude",
        "stat_max_speed": "Max speed",
        "stat_critical_events": "Critical events",
        "stat_warnings": "Warnings",
        "sec_route": "Flight route",
        "route_extrapolated_note": "The dashed red line is the EXTRAPOLATED segment after the last real "
        "log data — see “03 · Impact estimate”.",
        "sec_telemetry": "Telemetry",
        "sec_impact": "Impact estimate",
        "impact_note": "The log ends at t={last_ts:.1f}s mid-descent, before touching the ground. The "
        "following is a physical PROJECTION from that last known trajectory, not data recorded by the "
        "drone.",
        "impact_time_to": "Time to impact",
        "impact_position": "Estimated position",
        "impact_vspeed": "Vertical speed at impact",
        "impact_tspeed": "Total speed at impact",
        "impact_energy": "Estimated kinetic energy",
        "impact_assumptions_title": "Assumptions behind this estimate (read before quoting these numbers):",
        "sec_video": "Video synchronization",
        "video_note": "Each log event correlated with its closest video frame. The “Log GPS vs. video” "
        "column compares the position reported by the autopilot log with the one reported by the "
        "video's subtitle file at that same instant — two independent GPS sources that, if they "
        "disagree, are worth a closer look.",
        "th_time_log": "Log time (s)",
        "th_time_video": "Video time (s)",
        "th_event": "Event",
        "th_gps_cross_check": "Log GPS vs. video",
        "sec_events": "Event timeline",
        "th_time": "Time (s)",
        "th_severity": "Severity",
        "th_origin": "Source",
        "th_category": "Category",
        "th_description": "Description",
        "no_events": "No events were detected.",
        "events_legend": "“rule” = detected by an explainable threshold (see code); “ML” = statistically "
        "anomalous pattern detected by a model trained only on this flight — deserves more human review "
        "before drawing conclusions.",
        "sec_integrity": "Integrity check",
        "integrity_clean_badge": "no findings",
        "th_type": "Type",
        "fleet_title": "Fleet dashboard",
        "fleet_h1": "Fleet dashboard — comparative analysis",
        "fleet_meta": "Generated on {date} · {n} flights analyzed together",
        "fleet_stat_flights": "Flights analyzed",
        "fleet_stat_critical": "Critical events (total)",
        "fleet_stat_warning": "Warnings (total)",
        "fleet_stat_impact": "Flights with possible impact",
        "fleet_stat_integrity": "Flights with integrity findings",
        "fleet_sec_routes": "Combined routes",
        "fleet_sec_patterns": "Failure patterns across the set",
        "fleet_sec_comparison": "Flight comparison",
        "th_file": "File",
        "th_format": "Format",
        "th_duration": "Duration",
        "th_distance": "Distance",
        "th_critical": "Critical",
        "th_warnings": "Warnings",
        "th_impact_estimated": "Impact estimated",
        "th_integrity": "Integrity",
        "tag_yes": "yes",
        "tag_no": "no",
        "tag_review": "review",
        "no_flights": "No flights were analyzed.",
        "map_takeoff": "Takeoff / start of log",
        "map_end": "End of log",
        "map_impact_marker": "Estimated impact (projection, not recorded by the log): {speed:.1f} m/s",
        "map_flight_start": "Start",
        "legend_title": "Flights",
        "legend_start_point": "● = flight start point",
        "legend_no_gps": "No GPS in the log (not shown on the map): {names}",
        "legend_no_gps_at_all": "None of the flights in this set have GPS.",
        "chart_altitude_speed": "Altitude (m) and speed (m/s)",
        "chart_battery": "Battery",
        "chart_rc_signal": "RC signal",
        "chart_time_axis": "Time since start of log (s)",
        "chart_telemetry_title": "Telemetry — {source}",
        "chart_altitude": "Altitude (m)",
        "chart_speed": "Speed (m/s)",
        "chart_voltage": "Voltage (V)",
        "chart_rc": "RC signal",
        "chart_fleet_categories_title": "Most frequent anomaly categories across the set",
        "chart_category_axis": "Category",
        "chart_count_axis": "Times detected",
    },
    "de": {
        "report_title": "Flugbericht",
        "report_h1": "Flugbericht — forensische Analyse",
        "meta_generated": "Erstellt am {date} · Quelle: {source_format} · {source_file}",
        "status_critical": "Kritische Befunde",
        "status_warning": "Warnungen",
        "status_clean": "Unauffällig",
        "stat_duration": "Dauer",
        "stat_distance": "Zurückgelegte Strecke",
        "stat_max_altitude": "Maximale Höhe",
        "stat_max_speed": "Maximale Geschwindigkeit",
        "stat_critical_events": "Kritische Ereignisse",
        "stat_warnings": "Warnungen",
        "sec_route": "Flugroute",
        "route_extrapolated_note": "Die rote gestrichelte Linie ist der EXTRAPOLIERTE Abschnitt nach den "
        "letzten echten Log-Daten — siehe „03 · Aufprallschätzung“.",
        "sec_telemetry": "Telemetrie",
        "sec_impact": "Aufprallschätzung",
        "impact_note": "Das Log endet bei t={last_ts:.1f}s mitten im Sinkflug, vor dem Bodenkontakt. Das "
        "Folgende ist eine physikalische PROJEKTION anhand der letzten bekannten Flugbahn, kein von der "
        "Drohne aufgezeichneter Wert.",
        "impact_time_to": "Zeit bis zum Aufprall",
        "impact_position": "Geschätzte Position",
        "impact_vspeed": "Vertikalgeschwindigkeit beim Aufprall",
        "impact_tspeed": "Gesamtgeschwindigkeit beim Aufprall",
        "impact_energy": "Geschätzte kinetische Energie",
        "impact_assumptions_title": "Annahmen dieser Schätzung (vor dem Zitieren dieser Werte lesen):",
        "sec_video": "Video-Synchronisation",
        "video_note": "Jedes Log-Ereignis, korreliert mit dem nächstgelegenen Videoframe. Die Spalte „GPS "
        "Log vs. Video“ vergleicht die vom Autopilot-Log gemeldete Position mit der von der "
        "Video-Untertiteldatei gemeldeten Position zum selben Zeitpunkt — zwei unabhängige GPS-Quellen, "
        "die bei Abweichung einen genaueren Blick lohnen.",
        "th_time_log": "Log-Zeit (s)",
        "th_time_video": "Video-Zeit (s)",
        "th_event": "Ereignis",
        "th_gps_cross_check": "GPS Log vs. Video",
        "sec_events": "Ereigniszeitleiste",
        "th_time": "Zeit (s)",
        "th_severity": "Schweregrad",
        "th_origin": "Quelle",
        "th_category": "Kategorie",
        "th_description": "Beschreibung",
        "no_events": "Es wurden keine Ereignisse erkannt.",
        "events_legend": "„Regel“ = erkannt durch einen nachvollziehbaren Schwellenwert (siehe Code); "
        "„ML“ = statistisch auffälliges Muster, erkannt durch ein nur mit diesem Flug trainiertes Modell "
        "— verdient vor Schlussfolgerungen mehr menschliche Prüfung.",
        "sec_integrity": "Integritätsprüfung",
        "integrity_clean_badge": "keine Hinweise",
        "th_type": "Typ",
        "fleet_title": "Flottenübersicht",
        "fleet_h1": "Flottenübersicht — Vergleichsanalyse",
        "fleet_meta": "Erstellt am {date} · {n} gemeinsam analysierte Flüge",
        "fleet_stat_flights": "Analysierte Flüge",
        "fleet_stat_critical": "Kritische Ereignisse (gesamt)",
        "fleet_stat_warning": "Warnungen (gesamt)",
        "fleet_stat_impact": "Flüge mit möglichem Aufprall",
        "fleet_stat_integrity": "Flüge mit Integritätsbefunden",
        "fleet_sec_routes": "Kombinierte Routen",
        "fleet_sec_patterns": "Fehlermuster im Datensatz",
        "fleet_sec_comparison": "Flugvergleich",
        "th_file": "Datei",
        "th_format": "Format",
        "th_duration": "Dauer",
        "th_distance": "Strecke",
        "th_critical": "Kritisch",
        "th_warnings": "Warnungen",
        "th_impact_estimated": "Aufprall geschätzt",
        "th_integrity": "Integrität",
        "tag_yes": "ja",
        "tag_no": "nein",
        "tag_review": "prüfen",
        "no_flights": "Es wurde kein Flug analysiert.",
        "map_takeoff": "Start / Beginn des Logs",
        "map_end": "Ende des Logs",
        "map_impact_marker": "Geschätzter Aufprall (Projektion, nicht vom Log aufgezeichnet): {speed:.1f} m/s",
        "map_flight_start": "Start",
        "legend_title": "Flüge",
        "legend_start_point": "● = Startpunkt des Flugs",
        "legend_no_gps": "Kein GPS im Log (nicht auf der Karte dargestellt): {names}",
        "legend_no_gps_at_all": "Keiner der Flüge in diesem Datensatz hat GPS.",
        "chart_altitude_speed": "Höhe (m) und Geschwindigkeit (m/s)",
        "chart_battery": "Akku",
        "chart_rc_signal": "RC-Signal",
        "chart_time_axis": "Zeit seit Log-Beginn (s)",
        "chart_telemetry_title": "Telemetrie — {source}",
        "chart_altitude": "Höhe (m)",
        "chart_speed": "Geschwindigkeit (m/s)",
        "chart_voltage": "Spannung (V)",
        "chart_rc": "RC-Signal",
        "chart_fleet_categories_title": "Häufigste Anomalie-Kategorien im Datensatz",
        "chart_category_axis": "Kategorie",
        "chart_count_axis": "Anzahl Erkennungen",
    },
}


def ui(lang: str) -> Mapping[str, str]:
    """Devuelve el diccionario de textos fijos de la interfaz para `lang`, listo para pasar a Jinja2."""
    return UI_STRINGS[normalize_lang(lang)]
