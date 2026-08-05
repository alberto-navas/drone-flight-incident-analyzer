# Drone Flight Incident Analyzer

Herramienta de análisis forense de logs de vuelo de drones. Ingiere logs de
telemetría en los tres formatos abiertos más usados en autopilotos reales
(**ArduPilot** `.bin`, **PX4** `.ulog`, **Betaflight** blackbox `.BBL`/CSV),
reconstruye la trayectoria de vuelo, detecta anomalías (glitches de GPS,
descensos bruscos, caídas de batería, pérdida de señal RC) y genera un
informe HTML autocontenido con mapa, gráficos y línea de tiempo de eventos.

## Motivación

Con el aumento de drones derribados/estrellados (uso civil y militar), la
extracción y el análisis de sus logs de vuelo se hace hoy en gran medida a
mano, caso por caso. No existe apenas tooling abierto que automatice
"log crudo → informe de incidente". Este proyecto es una exploración de ese
problema: no pretende ser una herramienta forense certificada, sino
demostrar cómo se diseñaría el pipeline de un analizador de incidentes real.

## Arquitectura

```
log (.bin / .ulog / .BBL)
        │
        ▼
   src/parsers/*  ──►  FlightLog (modelo de datos común)
        │                 │
        │                 ▼
        │          src/analysis/anomalies.py  (detección de eventos por reglas)
        │                 │
        ▼                 ▼
   src/analysis/trajectory.py  (mapa + timeline)
        │
        ▼
   src/report/generator.py  ──►  informe HTML autocontenido
```

La pieza central del diseño es `FlightLog` / `FlightRecord` / `FlightEvent`
(`src/parsers/base.py`): cada parser traduce su formato binario a estas
clases, y todo lo que viene después (mapas, detección de anomalías,
informe) es completamente agnóstico del formato de origen.

## Formatos soportados y sus limitaciones

| Formato | Librería usada | Limitación conocida |
|---|---|---|
| ArduPilot (`.bin`) | `pymavlink` (oficial) | El campo `Mode` en logs antiguos puede venir como número sin decodificar a nombre (depende de la versión/tipo de vehículo) |
| PX4 (`.ulog`) | `pyulog` (oficial) | Logs sin GPS/batería habilitados en la simulación no generan esos campos (el informe se degrada con gracia, sin mapa) |
| Betaflight (`.BBL`) | `blackbox_decode` (externo) + parser CSV propio | No hay librería Python oficial; requiere tener `blackbox_decode` instalado. Betaflight no registra actitud absoluta por defecto (solo velocidades angulares), así que roll/pitch/yaw no están disponibles para este formato |

## Uso

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt

python -m src.cli data/samples/ardupilot/vuelo.bin
python -m src.cli data/samples/px4/vuelo.ulog
python -m src.cli data/samples/betaflight/vuelo.BBL   # requiere blackbox_decode en el PATH
python -m src.cli data/samples/betaflight/vuelo.csv --format betaflight  # si ya está decodificado
```

El informe se genera en `output/<nombre_del_log>.html`.

## Datos de prueba

Los logs de ejemplo no se versionan en git (ver `data/samples/README.md`
para las fuentes públicas de donde descargarlos). El pipeline ha sido
probado contra:
- Un log real de ArduPilot (`ArduPilot/pymavlink` test fixtures)
- Un log real de PX4 (`PX4/pyulog` test fixtures)
- Un CSV sintético con el esquema de columnas real de `blackbox_decode`
  (no se encontró un `.BBL`/CSV real descargable públicamente sin el
  binario `blackbox_decode`)

## Qué NO hace este proyecto

Deliberadamente no incluye nada relacionado con targeting, guiado o control
de vuelo: es una herramienta de análisis posterior al vuelo (post-incident),
no de operación en tiempo real.

## Posibles extensiones

- Parsear subtítulos SRT de vídeos DJI (llevan telemetría por frame) para
  correlacionar imagen y datos de vuelo.
- Detección de anomalías por ML (p. ej. Isolation Forest) en vez de reglas
  fijas, para hallazgos que no encajan en ningún patrón predefinido.
- Interfaz web (subir log → descargar informe) sobre el mismo `src/cli.py`.
