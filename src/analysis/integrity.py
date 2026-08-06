"""
Verificacion de integridad del log: indicios heuristicos de manipulacion o corrupcion.

Aviso importante, para no vender esto como algo que no es: NO es una prueba
criptografica de autenticidad. Los formatos de log de dron soportados aqui
no llevan firma digital ni hash de todo el archivo. Lo que hace este modulo
es buscar patrones que un log genuino, grabado sin interrupciones por el
propio autopiloto, no deberia presentar. Cuantos mas indicios aparecen,
menos deberia confiarse en el log sin mas contexto — pero ni un log "limpio"
segun estos chequeos esta garantizado autentico, ni un indicio aislado
prueba manipulacion (podria ser, por ejemplo, una perdida de señal real).
"""

from dataclasses import dataclass

from ..parsers.base import FlightLog

# Cuantas veces mayor que la mediana debe ser un hueco entre muestras para
# considerarlo sospechoso. Se usa un umbral RELATIVO (no un numero fijo de
# segundos) porque cada log tiene una cadencia de muestreo distinta: lo que
# es un hueco enorme en un log muy denso es normal en uno mas disperso.
_GAP_SUSPICION_FACTOR = 10.0

# Huecos mas cortos que esto (segundos) nunca se marcan, aunque superen el
# factor anterior: en un log muy corto la mediana puede ser tan pequeña que
# hasta un hueco irrelevante de medio segundo parezca "10x la mediana".
_MIN_GAP_TO_FLAG_SECONDS = 1.0

# Campos sobre los que se comprueba monotonicidad temporal de forma
# INDEPENDIENTE unos de otros. Se hace por campo, no sobre el flujo entero
# del archivo, porque distintos tipos de mensaje (GPS, bateria, actitud...)
# se intercalan de forma normal y esperada en el archivo crudo; lo anormal
# es que el MISMO sensor/magnitud retroceda en el tiempo respecto a si mismo.
_MONOTONICITY_FIELDS = ["lat", "alt", "battery_voltage", "rc_signal", "roll"]


@dataclass
class IntegrityFinding:
    """Un indicio individual encontrado durante la verificacion."""

    kind: str  # "time_reversal" | "suspicious_gap"
    field: str | None
    timestamp: float
    severity: str  # "warning" | "critical"
    description: str


@dataclass
class IntegrityReport:
    """Resultado completo de la verificacion, con un resumen en texto plano para el informe."""

    findings: list[IntegrityFinding]
    summary: str

    @property
    def looks_clean(self) -> bool:
        return len(self.findings) == 0


def _check_monotonicity(flight_log: FlightLog) -> list[IntegrityFinding]:
    """
    Busca retrocesos de tiempo dentro del flujo de un mismo campo.

    Se recorre `flight_log.records` en su orden de insercion ORIGINAL (el
    orden en que el parser leyo el archivo), no el orden ya ordenado por
    tiempo que da `sorted_records()`: ordenar por tiempo escondería
    exactamente la anomalia que se quiere detectar aqui.
    """
    findings = []
    for field_name in _MONOTONICITY_FIELDS:
        last_ts = None
        for record in flight_log.records:
            value = getattr(record, field_name)
            if value is None:
                continue
            if last_ts is not None and record.timestamp < last_ts:
                findings.append(
                    IntegrityFinding(
                        kind="time_reversal",
                        field=field_name,
                        timestamp=record.timestamp,
                        severity="critical",
                        description=(
                            f"El tiempo retrocede en el flujo de '{field_name}': una muestra en "
                            f"t={record.timestamp:.2f}s llega despues de otra en t={last_ts:.2f}s dentro del "
                            "mismo archivo. Puede indicar un log editado/empalmado, o corrupcion del archivo."
                        ),
                    )
                )
            last_ts = record.timestamp
    return findings


def _check_gaps(flight_log: FlightLog) -> list[IntegrityFinding]:
    """Busca huecos de tiempo anormalmente grandes sin ninguna muestra de telemetria."""
    findings = []
    timestamps = sorted(r.timestamp for r in flight_log.records)
    if len(timestamps) < 3:
        return findings  # muy pocas muestras para que "la mediana" signifique algo

    gaps = [b - a for a, b in zip(timestamps, timestamps[1:], strict=False) if b > a]
    if not gaps:
        return findings

    gaps_sorted = sorted(gaps)
    median_gap = gaps_sorted[len(gaps_sorted) // 2]
    if median_gap <= 0:
        return findings

    for a, b in zip(timestamps, timestamps[1:], strict=False):
        gap = b - a
        if gap >= _MIN_GAP_TO_FLAG_SECONDS and gap > median_gap * _GAP_SUSPICION_FACTOR:
            findings.append(
                IntegrityFinding(
                    kind="suspicious_gap",
                    field=None,
                    timestamp=a,
                    severity="warning",
                    description=(
                        f"Hueco de {gap:.1f}s sin ninguna muestra de telemetria (de t={a:.2f}s a t={b:.2f}s), "
                        f"frente a una cadencia habitual de ~{median_gap:.2f}s entre muestras. Puede ser una "
                        "perdida de señal real, o un tramo del log eliminado."
                    ),
                )
            )
    return findings


def check_integrity(flight_log: FlightLog) -> IntegrityReport:
    """Punto de entrada unico del modulo: ejecuta todos los chequeos y devuelve un IntegrityReport."""
    findings = _check_monotonicity(flight_log) + _check_gaps(flight_log)
    findings.sort(key=lambda f: f.timestamp)

    if not findings:
        summary = "No se encontraron indicios de manipulacion o corrupcion en este log."
    else:
        n_critical = sum(1 for f in findings if f.severity == "critical")
        n_warning = sum(1 for f in findings if f.severity == "warning")
        summary = (
            f"Se encontraron {len(findings)} indicio(s) ({n_critical} critico(s), {n_warning} de advertencia). "
            "Esto no prueba manipulacion por si solo: cada hallazgo debe revisarse en su contexto."
        )

    return IntegrityReport(findings=findings, summary=summary)
