# Drone Flight Incident Analyzer

Herramienta de análisis forense de logs de vuelo de drones. Ingiere logs de
telemetría en los tres formatos abiertos más usados en autopilotos reales
(**ArduPilot** `.bin`, **PX4** `.ulog`, **Betaflight** blackbox `.BBL`/CSV),
reconstruye la trayectoria de vuelo, detecta anomalías, estima dónde y cómo
impactó un vuelo cuyo log se cortó en pleno descenso, verifica indicios de
manipulación del propio log, cruza el vuelo con el vídeo grabado (DJI SRT),
y compara varios vuelos a la vez en un panel de flota — todo en informes
HTML autocontenidos.

## Motivación

Con el aumento de drones derribados/estrellados (uso civil y militar), la
extracción y el análisis de sus logs de vuelo se hace hoy en gran medida a
mano, caso por caso. No existe apenas tooling abierto que automatice
"log crudo → informe de incidente". Este proyecto es una exploración de ese
problema: no pretende ser una herramienta forense certificada, sino
demostrar cómo se diseñaría el pipeline de un analizador de incidentes real.

## Capacidades

- **Parseo multi-formato**: ArduPilot, PX4, Betaflight → un modelo de datos común.
- **Detección de anomalías por reglas explicables**: glitches de GPS, descensos
  bruscos, caídas de batería, pérdida de señal RC (`src/analysis/anomalies.py`).
- **Estimación de impacto**: cuando el log se corta en pleno descenso (el caso
  típico: el dron pierde alimentación al chocar), proyecta con cinemática
  básica dónde y a qué velocidad probablemente impactó, con sus asunciones
  explícitas (`src/analysis/impact.py`).
- **Verificación de integridad**: indicios heurísticos de log manipulado o
  corrupto — retrocesos de tiempo por sensor, huecos anormalmente grandes
  (`src/analysis/integrity.py`). No es una prueba criptográfica, es una señal.
- **Sincronización con vídeo**: cruza los subtítulos SRT de un vídeo DJI (que
  llevan GPS/altitud por fotograma) con el log de vuelo, incluyendo una
  verificación cruzada de GPS entre las dos fuentes independientes
  (`src/parsers/dji_srt.py`, `src/analysis/video_sync.py`).
- **Panel de flota**: analiza varios logs a la vez — mapa con todas las rutas
  superpuestas, histograma de qué anomalía es más frecuente en el conjunto,
  tabla comparativa (`src/report/fleet.py`).

## Arquitectura

```
log (.bin / .ulog / .BBL)
        │
        ▼
   src/parsers/*  ──►  FlightLog (modelo de datos común)
        │                 │
        │                 ▼
        │          src/analysis/anomalies.py   (detección de eventos por reglas)
        │          src/analysis/impact.py       (estimación de impacto)
        │          src/analysis/integrity.py    (indicios de manipulación)
        │          src/analysis/video_sync.py   (cruce con vídeo DJI, opcional)
        │                 │
        ▼                 ▼
   src/analysis/trajectory.py  (mapa + timeline)
        │
        ▼
   src/report/generator.py  ──►  informe HTML autocontenido (1 vuelo)
   src/report/fleet.py       ──►  panel comparativo (varios vuelos)
```

La pieza central del diseño es `FlightLog` / `FlightRecord` / `FlightEvent`
(`src/parsers/base.py`): cada parser traduce su formato binario a estas
clases, y todo lo que viene después (mapas, anomalías, impacto, integridad,
informe) es completamente agnóstico del formato de origen.

## Formatos soportados y sus limitaciones

| Formato | Librería usada | Limitación conocida |
|---|---|---|
| ArduPilot (`.bin`) | `pymavlink` (oficial) | El campo `Mode` en logs antiguos puede venir como número sin decodificar a nombre (depende de la versión/tipo de vehículo) |
| PX4 (`.ulog`) | `pyulog` (oficial) | Logs sin GPS/batería habilitados en la simulación no generan esos campos (el informe se degrada con gracia, sin mapa) |
| Betaflight (`.BBL`) | `blackbox_decode` (externo) + parser CSV propio | No hay librería Python oficial; requiere tener `blackbox_decode` instalado. Betaflight no registra actitud absoluta por defecto, así que roll/pitch/yaw no están disponibles para este formato |
| DJI SRT (vídeo) | `srt` + parser propio | Formato no documentado oficialmente por DJI y distinto entre generaciones; solo se reconocen dos variantes conocidas. La sincronización con el log requiere un offset manual salvo que se aporte la hora UTC real de inicio del log |

**Modo flota**: `--format` fuerza el mismo formato para todos los logs a la
vez; para mezclar formatos en una sola tanda, todos deben ser
auto-detectables por extensión (`.bin`/`.ulog`/`.BBL`) — un `.csv` de
Betaflight ya decodificado no se puede mezclar con otros formatos en el
mismo comando porque no hay forma de distinguirlo solo por la extensión.

## Uso

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt

# Informe individual
python -m src.cli data/samples/ardupilot/vuelo.bin
python -m src.cli data/samples/px4/vuelo.ulog
python -m src.cli data/samples/betaflight/vuelo.BBL          # requiere blackbox_decode en el PATH
python -m src.cli data/samples/betaflight/vuelo.csv --format betaflight

# Con masa del vehiculo, para calcular energia cinetica de impacto
python -m src.cli data/samples/ardupilot/vuelo.bin --mass-kg 1.5

# Cruzando con video DJI (offset calibrado a mano, en segundos)
python -m src.cli data/samples/betaflight/vuelo.csv --format betaflight --video-srt vuelo.srt --video-offset 2.3

# Panel de flota (varios logs a la vez)
python -m src.cli data/samples/ardupilot/*.bin --output output/flota.html
```

El informe se genera en `output/<nombre_del_log>.html` (o `output/fleet_report.html` en modo flota).

## Datos de prueba

Los logs de ejemplo no se versionan en git (ver `data/samples/README.md`
para las fuentes públicas de donde descargarlos). El pipeline ha sido
probado contra:
- Un log real de ArduPilot (`ArduPilot/pymavlink` test fixtures)
- Un log real de PX4 (`PX4/pyulog` test fixtures)
- Un CSV sintético con el esquema de columnas real de `blackbox_decode`
  (no se encontró un `.BBL`/CSV real descargable públicamente sin el
  binario `blackbox_decode`)
- Un `.srt` sintético con el formato real de subtítulos DJI (no se disponía
  de un vídeo/vuelo DJI real para pruebas)

## Qué NO hace este proyecto

Deliberadamente no incluye nada relacionado con targeting, guiado o control
de vuelo: es una herramienta de análisis posterior al vuelo (post-incident),
no de operación en tiempo real. La estimación de impacto es física básica
(cinemática de caída libre), no un modelo de daño ni de letalidad.

## Posibles extensiones

- Detección de anomalías por ML (p. ej. Isolation Forest) en vez de reglas
  fijas, para hallazgos que no encajan en ningún patrón predefinido.
- Interfaz web (subir log → descargar informe) sobre el mismo `src/cli.py`.
- Capturar la hora UTC real de inicio del log en los parsers (ArduPilot y
  PX4 la tienen disponible internamente) para poder alinear automáticamente
  el vídeo sin offset manual.
- Terreno real (modelo de elevación) en vez de "terreno llano" en la
  estimación de impacto — muy relevante en entornos alpinos.
