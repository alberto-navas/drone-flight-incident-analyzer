"""
Tests de la interfaz web (src/web/app.py), usando el TestClient de FastAPI
(no levanta un servidor real, invoca la app directamente en el mismo proceso).
"""

from fastapi.testclient import TestClient

from src.web.app import app

client = TestClient(app)


def test_upload_form_renders(fixtures_dir):
    response = client.get("/")
    assert response.status_code == 200
    assert "<form" in response.text


def test_analyze_single_ardupilot_file(fixtures_dir):
    with open(fixtures_dir / "mini_ardupilot.bin", "rb") as f:
        response = client.post("/analyze", files={"files": ("mini_ardupilot.bin", f, "application/octet-stream")})

    assert response.status_code == 200
    assert "Informe de vuelo" in response.text


def test_analyze_single_px4_file(fixtures_dir):
    with open(fixtures_dir / "mini_px4.ulog", "rb") as f:
        response = client.post("/analyze", files={"files": ("mini_px4.ulog", f, "application/octet-stream")})

    assert response.status_code == 200
    assert "Informe de vuelo" in response.text


def test_analyze_single_betaflight_csv(fixtures_dir):
    with open(fixtures_dir / "mini_betaflight.csv", "rb") as f:
        response = client.post("/analyze", files={"files": ("mini_betaflight.csv", f, "application/octet-stream")})

    assert response.status_code == 200
    assert "Informe de vuelo" in response.text


def test_analyze_multiple_files_generates_fleet_report(fixtures_dir):
    with open(fixtures_dir / "mini_ardupilot.bin", "rb") as f1, open(fixtures_dir / "mini_betaflight.csv", "rb") as f2:
        response = client.post(
            "/analyze",
            files=[
                ("files", ("mini_ardupilot.bin", f1, "application/octet-stream")),
                ("files", ("mini_betaflight.csv", f2, "application/octet-stream")),
            ],
        )

    assert response.status_code == 200
    assert "Panel de flota" in response.text


def test_analyze_with_mass_kg_computes_kinetic_energy():
    """
    mini_ardupilot.bin no tiene un descenso brusco, asi que no basta para
    probar la seccion de impacto end-to-end aqui (eso ya lo cubre
    tests/test_report_generation.py con un FlightLog sintetico). Este test
    solo comprueba que el formulario acepta y transmite mass_kg sin romperse.
    """
    with open("tests/fixtures/mini_ardupilot.bin", "rb") as f:
        response = client.post(
            "/analyze",
            files={"files": ("mini_ardupilot.bin", f, "application/octet-stream")},
            data={"mass_kg": "1.5"},
        )
    assert response.status_code == 200


def test_analyze_unsupported_extension_returns_400():
    response = client.post("/analyze", files={"files": ("archivo.xyz", b"contenido", "application/octet-stream")})
    assert response.status_code == 400
    assert "formato" in response.json()["detail"].lower()


def test_analyze_path_traversal_filename_is_sanitized():
    """
    Un nombre de archivo con componentes de ruta ("../../etc/passwd.bin")
    no debe escribirse fuera del directorio temporal de la peticion.
    El contenido no es un log real, asi que la peticion termina en 400 (ver
    tests/test_malformed_inputs.py); lo que importa aqui es que el nombre
    se trato como el simple "passwd.bin" (ver _safe_filename en app.py), no
    como una ruta que escriba fuera del directorio temporal — ni en el
    propio sistema de archivos ni reflejado tal cual en el mensaje de error.
    """
    malicious_name = "../../../../etc/passwd.bin"
    files = {"files": (malicious_name, b"no es un log real", "application/octet-stream")}
    response = client.post("/analyze", files=files)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "passwd.bin" in detail
    assert "etc/passwd" not in detail
