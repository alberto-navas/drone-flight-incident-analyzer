"""
Interfaz web: subir uno o varios logs de vuelo desde el navegador y ver el
informe directamente, sin usar la terminal.

Es una capa fina sobre el mismo pipeline que usa el CLI (src/cli.py):
src/pipeline.py para el parseo, src/analysis/* para el analisis,
src/report/* para el informe. Esta app no reimplementa nada de eso, solo
adapta la entrada (archivos subidos por HTTP en vez de rutas de archivo) y
la salida (HTML servido directamente en vez de escrito a disco).

Alcance deliberadamente reducido respecto al CLI: no expone la
sincronizacion con video aqui (necesita dos archivos correlacionados y un
offset calibrado a mano, demasiada complejidad de formulario para una
primera version) — eso sigue siendo solo-CLI por ahora.
"""

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from ..analysis.anomalies import detect_anomalies
from ..analysis.ml_anomalies import detect_ml_anomalies
from ..parsers.base import FlightLog
from ..pipeline import parse_log
from ..report.fleet import generate_fleet_report
from ..report.generator import generate_report

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Limite de tamaño por archivo subido. No es un numero magico: los logs de
# vuelo reales de este proyecto van de decenas de KB a unos pocos MB: 50 MB
# es generoso para eso sin dejar la subida completamente sin limite (una
# subida sin limite es una superficie de abuso trivial en cualquier server
# que acepte archivos).
_MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024

# Limite de peticiones por IP a /analyze: es el endpoint caro (entrena un
# modelo de ML por peticion), y esta app corre en el plan gratuito de
# Render — sin limite, cualquiera podria dejarlo sin recursos con un bucle
# de peticiones. 20/minuto es generoso para un uso normal (probar varios
# archivos seguidos) pero corta un abuso automatizado.
_ANALYZE_RATE_LIMIT = "20/minute"

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Drone Flight Incident Analyzer")
app.state.limiter = limiter
# El handler de slowapi tiene una firma mas especifica (RateLimitExceeded en
# vez de Exception generico) de la que espera el stub de Starlette; es el
# patron oficial de slowapi (ver su documentacion), no un error real.
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _safe_filename(original_name: str | None) -> str:
    """
    Se queda solo con el nombre de archivo, descartando cualquier ruta.

    Un nombre de archivo subido por un cliente HTTP no es de fiar: algo
    como "../../etc/cron.d/algo" en el campo filename podria, sin esto,
    hacer que el archivo se escriba fuera del directorio temporal
    pensado. Path(...).name se queda solo con el ultimo componente.

    `original_name` es Optional porque el propio protocolo multipart no
    obliga a que una parte traiga nombre de archivo (UploadFile.filename de
    FastAPI lo tipa como `str | None`); si falta, se usa un nombre generico.
    """
    if not original_name:
        return "archivo"
    return Path(original_name).name or "archivo"


async def _save_upload(upload: UploadFile, dest_dir: Path) -> Path:
    content = await upload.read()
    if len(content) > _MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"'{upload.filename}' supera el limite de {_MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB.",
        )
    dest = dest_dir / _safe_filename(upload.filename)
    dest.write_bytes(content)
    return dest


def _parse_and_analyze(path: Path) -> FlightLog:
    """Mismo pipeline que usa el CLI (ver src/cli.py): parseo + reglas + ML, sin la parte de impresion por consola."""
    flight_log = parse_log(path)
    detect_anomalies(flight_log)
    ml_events = detect_ml_anomalies(flight_log)
    flight_log.events.extend(ml_events)
    return flight_log


@app.get("/", response_class=HTMLResponse)
async def upload_form(request: Request):
    return _templates.TemplateResponse(request, "upload.html", {})


@app.post("/analyze", response_class=HTMLResponse)
@limiter.limit(_ANALYZE_RATE_LIMIT)
async def analyze(
    request: Request,  # requerido por @limiter.limit para identificar al cliente (IP), no se usa directamente aqui
    files: list[UploadFile] = File(...),  # noqa: B008 — patron estandar de FastAPI, no una llamada real en cada request
    mass_kg: float | None = Form(None),
):
    if not files:
        raise HTTPException(status_code=400, detail="No se subio ningun archivo.")

    with tempfile.TemporaryDirectory() as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)

        try:
            saved_paths = [await _save_upload(upload, tmp_dir) for upload in files]
            flight_logs = [_parse_and_analyze(path) for path in saved_paths]
        except ValueError as exc:
            # Formato no reconocido u otro problema de parseo esperable:
            # se traduce a un error HTTP legible, no a un traceback de 500.
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        output_path = tmp_dir / "report.html"
        if len(flight_logs) == 1:
            generate_report(flight_logs[0], str(output_path), mass_kg=mass_kg)
        else:
            generate_fleet_report(flight_logs, str(output_path))

        # Se lee el HTML a memoria ANTES de que el directorio temporal se
        # borre al salir del "with": el archivo en si no necesita
        # persistir, solo su contenido para esta respuesta.
        html_content = output_path.read_text(encoding="utf-8")

    return HTMLResponse(html_content)
