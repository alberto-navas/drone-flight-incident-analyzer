"""
Deteccion de anomalias por aprendizaje no supervisado, complementaria a las
reglas explicitas de anomalies.py.

Las reglas de anomalies.py solo detectan lo que a alguien se le ocurrio
buscar de antemano (una caida de bateria, un salto de GPS...). Un modelo de
Isolation Forest, en cambio, aprende que combinacion de valores es "normal"
DENTRO DE ESTE VUELO CONCRETO, observando varias magnitudes a la vez, y
señala los instantes que se salen de ese patron aunque no encajen en
ninguna regla predefinida — por ejemplo, una combinacion rara de actitud y
velocidad que ninguna regla individual estaba mirando.

Dos decisiones de diseño importantes:

1. El modelo se entrena UNICAMENTE con los datos de este vuelo, no con un
   modelo pre-entrenado compartido entre vuelos. Lo que se busca es "que es
   raro PARA ESTE vuelo", no "que es raro en general", porque el rango
   normal de valores varia mucho segun el tipo de vehiculo y de mision. Es
   tambien la razon por la que se fija `random_state` explicitamente: en un
   contexto forense, dos analisis del mismo log deben dar el mismo
   resultado siempre, no uno distinto cada vez que se ejecuta.

2. Para no convertir esto en una caja negra (ver la filosofia de
   anomalies.py), cada hallazgo se acompaña de que magnitud concreta se
   desvio mas de lo habitual en ese instante (un z-score simple por
   variable). No es una atribucion causal rigurosa como SHAP, pero es una
   heuristica honesta sobre que "empujo" el punto fuera de lo normal, en
   vez de un opaco "esto es raro, confía en el modelo".
"""

from collections import defaultdict

import pandas as pd
from sklearn.ensemble import IsolationForest

from ..parsers.base import FlightEvent, FlightLog
from .anomalies import consolidate_episodes

# Magnitudes candidatas sobre las que se busca un patron conjunto. No todas
# estaran presentes en todos los formatos/vuelos (p.ej. Betaflight no trae
# roll/pitch/yaw absolutos); las ausentes se descartan en _build_feature_matrix.
_CANDIDATE_FEATURES = ["alt", "groundspeed", "battery_voltage", "rc_signal", "roll", "pitch", "yaw"]

# Fraccion esperada de instantes anomalos. Es un hiperparametro del modelo,
# no una medida objetiva: 3% es un valor conservador tipico para deteccion
# de anomalias exploratoria (deja pasar la gran mayoria del vuelo como
# "normal" y solo señala una minoria).
_CONTAMINATION = 0.03

# Cadencia (segundos) a la que se remuestrean los datos dispersos del log a
# una tabla comun antes de entrenar el modelo. Ver _build_feature_matrix.
_RESAMPLE_INTERVAL_S = 0.5

# Por debajo de este numero de muestras remuestreadas, un Isolation Forest
# no tiene suficiente contexto como para que "anomalo" signifique algo
# fiable; se prefiere no dar resultado a dar uno poco fiable.
_MIN_SAMPLES_REQUIRED = 20


def _build_feature_matrix(flight_log: FlightLog) -> pd.DataFrame | None:
    """
    Convierte los FlightRecord (dispersos: un subconjunto de campos por
    mensaje, a instantes distintos) en una tabla con una fila por ventana de
    tiempo y una columna por magnitud, que es lo que necesita un modelo
    multivariante para comparar todas las señales a la vez.
    """
    records = flight_log.sorted_records()
    rows = [{"timestamp": r.timestamp, **{f: getattr(r, f) for f in _CANDIDATE_FEATURES}} for r in records]
    df = pd.DataFrame(rows)
    if df.empty:
        return None

    # Solo se usan columnas con datos reales en este vuelo: meter una
    # columna vacia forzaria una señal falsa (todo "normal" en esa
    # magnitud), lo que enmascararia anomalias reales en las demas.
    feature_cols = [c for c in _CANDIDATE_FEATURES if df[c].notna().sum() >= _MIN_SAMPLES_REQUIRED]
    if len(feature_cols) < 2:
        return None  # con una sola magnitud no hay "patron conjunto" que buscar

    # astype a nanosegundos explicito: pandas elige automaticamente la
    # resolucion mas "gruesa" que representa los valores de entrada sin
    # perdida (p.ej. timedelta64[s] si todos los timestamps son enteros), y
    # luego un resample a sub-segundo sobre un indice en segundos falla con
    # un ValueError de casting. Forzar nanosegundos evita ese problema pase
    # lo que pase con los valores de entrada.
    df["timestamp"] = pd.to_timedelta(df["timestamp"], unit="s").astype("timedelta64[ns]")
    df = df.set_index("timestamp")[feature_cols]

    # Remuestreo a cadencia fija (media por ventana) con relleno hacia
    # adelante para huecos cortos: un campo que solo llega cada pocos
    # segundos (p.ej. bateria) no debe dejar una fila vacia en cada ventana
    # intermedia en la que no llego una muestra nueva.
    resampled = df.resample(f"{_RESAMPLE_INTERVAL_S}s").mean().ffill()
    resampled = resampled.dropna()  # huecos que ffill no pudo rellenar (t=0, antes de la primera muestra real)

    if len(resampled) < _MIN_SAMPLES_REQUIRED:
        return None

    return resampled


def _group_by_category(events: list[FlightEvent]) -> list[FlightEvent]:
    """
    Aplica consolidate_episodes() por categoria en vez de al conjunto entero.

    consolidate_episodes() fusiona eventos consecutivos en el tiempo sin
    mirar su categoria (asume que la lista que recibe ya es homogenea, como
    ocurre en anomalies.py). Aqui la lista mezcla distintas categorias
    ("ml_anomaly_alt", "ml_anomaly_battery_voltage"...), asi que hay que
    agrupar primero para no fusionar por error dos anomalias de magnitudes
    distintas que solo coinciden en estar cerca en el tiempo.
    """
    grouped = defaultdict(list)
    for event in events:
        grouped[event.category].append(event)

    consolidated = [e for group in grouped.values() for e in consolidate_episodes(group)]
    return sorted(consolidated, key=lambda e: e.timestamp)


def detect_ml_anomalies(flight_log: FlightLog) -> list[FlightEvent]:
    """
    Entrena un Isolation Forest sobre este vuelo y devuelve los instantes
    marcados como estadisticamente anomalos.

    Devuelve una lista vacia (sin lanzar excepcion) cuando no hay datos
    suficientes o suficientemente variados para que el modelo tenga
    sentido, en vez de forzar un resultado sobre el que no se puede confiar.
    """
    features = _build_feature_matrix(flight_log)
    if features is None:
        return []

    model = IsolationForest(contamination=_CONTAMINATION, random_state=42)
    labels = model.fit_predict(features)  # -1 = anomalo, 1 = normal segun el modelo
    scores = model.decision_function(features)  # mas negativo = mas anomalo

    means = features.mean()
    stds = features.std().replace(0, 1)  # evita division por cero en una columna constante
    most_anomalous_idx = scores.argmin()  # el punto mas anomalo de TODO el vuelo

    events = []
    for i, ((timestamp, row), label) in enumerate(zip(features.iterrows(), labels, strict=True)):
        if label != -1:
            continue

        z_scores = ((row - means) / stds).abs()
        top_feature = z_scores.idxmax()

        # Solo el punto mas anomalo del vuelo entero se marca "critical": es
        # una escala relativa a este vuelo (no un umbral absoluto inventado),
        # consistente con el resto del hallazgo, que tambien se mide en
        # relacion al propio vuelo y no a un valor de referencia externo.
        severity = "critical" if i == most_anomalous_idx else "warning"

        events.append(
            FlightEvent(
                timestamp=timestamp.total_seconds(),
                category=f"ml_anomaly_{top_feature}",
                severity=severity,
                description=(
                    "Patrón estadísticamente anómalo (Isolation Forest, entrenado solo con este vuelo); "
                    f"la magnitud que más se desvía de lo habitual es '{top_feature}' "
                    f"({row[top_feature]:.2f}, {z_scores[top_feature]:.1f} desviaciones estándar)."
                ),
                method="ml",
            )
        )

    return _group_by_category(events)
