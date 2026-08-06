"""
Tests de robustez: que pasa cuando se sube un archivo vacio, corrupto, o de
otro formato con la extension equivocada.

Motivacion: durante el desarrollo se descubrio que, sin manejo explicito,
estos casos no fallaban de forma limpia: unos lanzaban excepciones sin
capturar (TypeError de pyulog, ValueError crudo de mmap...), y ademas dos
de ellos dejaban un archivo bloqueado en Windows porque pymavlink/pyulog
abren el archivo ANTES de validar su contenido y no lo cierran si esa
validacion falla a mitad de construir su objeto lector. Estos tests fijan
el comportamiento correcto como regresion: siempre ValueError, con un
mensaje legible, sin importar el tipo de corrupcion.
"""

import pytest

from src.pipeline import parse_log


@pytest.mark.parametrize(
    "filename",
    ["empty.bin", "garbage.bin", "empty.ulog", "garbage.ulog", "empty.csv", "garbage.csv"],
)
def test_malformed_file_raises_value_error(fixtures_dir, filename):
    with pytest.raises(ValueError):
        parse_log(fixtures_dir / "malformed" / filename)


def test_malformed_file_error_message_is_helpful(fixtures_dir):
    """El mensaje debe mencionar el nombre del archivo, no ser solo un traceback tecnico crudo."""
    with pytest.raises(ValueError) as exc_info:
        parse_log(fixtures_dir / "malformed" / "empty.bin")
    assert "empty.bin" in str(exc_info.value)


def test_wrong_extension_still_produces_clean_error(tmp_path):
    """Un .csv que en realidad es basura (no un export de blackbox_decode) debe fallar limpio, no con un error crudo."""
    fake_csv = tmp_path / "fake.csv"
    fake_csv.write_text("esto,no,es,un,csv,de,verdad\n1,2,3,4,5,6", encoding="utf-8")

    with pytest.raises(ValueError):
        parse_log(fake_csv)
