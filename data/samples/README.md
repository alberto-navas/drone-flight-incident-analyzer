# Datos de ejemplo

Los logs binarios reales no se versionan en git (ver `.gitignore`) porque pesan
demasiado y no son código nuestro. Aquí van las fuentes públicas de donde
descargarlos para probar cada parser:

- **ArduPilot** (`ardupilot/`): logs `.bin` de ejemplo en
  https://github.com/ArduPilot/SITL_Models o en el propio "Log Browser" de
  Mission Planner. También hay logs de incidentes reales analizados por la
  comunidad en el foro de ArduPilot (categoría "Log Analysis").
- **PX4** (`px4/`): logs `.ulog` públicos en https://review.px4.io/browse
  (cada vuelo subido por la comunidad PX4 es descargable en formato `.ulog`).
- **Betaflight** (`betaflight/`): logs `.BBL` de ejemplo en el repo de
  Betaflight (`src/test/unit/blackbox_test_data`) o exportados desde el
  Blackbox Explorer oficial.

Coloca los archivos descargados en la subcarpeta correspondiente antes de
ejecutar el CLI.
