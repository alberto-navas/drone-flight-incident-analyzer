"""
Permite arrancar la interfaz web con `python -m src.web`.

Respeta la variable de entorno PORT (que plataformas como Render asignan
dinamicamente) si esta presente, pero por defecto sigue siendo 127.0.0.1:8000
para desarrollo local — no queremos que el servidor de desarrollo quede
expuesto en la red local por defecto solo por soportar despliegue.
"""

import os

import uvicorn

if __name__ == "__main__":  # pragma: no cover — punto de entrada trivial, arranca un servidor real
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("src.web.app:app", host="127.0.0.1", port=port, reload=False)
