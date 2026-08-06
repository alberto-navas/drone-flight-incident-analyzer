"""Tests de extremo a extremo del CLI (src/cli.py)."""

from src.cli import main


def test_single_file_generates_individual_report(tmp_path, fixtures_dir):
    output_path = tmp_path / "report.html"
    exit_code = main([str(fixtures_dir / "mini_ardupilot.bin"), "--output", str(output_path)])

    assert exit_code == 0
    assert output_path.exists()
    assert "Informe de vuelo" in output_path.read_text(encoding="utf-8")


def test_mixed_format_fleet_without_explicit_format(tmp_path, fixtures_dir):
    """
    Regresion: el modo flota debe poder mezclar formatos distintos (.bin +
    .csv) en la misma tanda sin necesitar --format, porque cada archivo se
    auto-detecta por su propia extension de forma independiente.
    """
    output_path = tmp_path / "fleet.html"
    exit_code = main(
        [
            str(fixtures_dir / "mini_ardupilot.bin"),
            str(fixtures_dir / "mini_betaflight.csv"),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    html = output_path.read_text(encoding="utf-8")
    assert "Panel de flota" in html
    assert "mini_ardupilot.bin" in html
    assert "mini_betaflight.csv" in html


def test_missing_input_file_exits_with_error(tmp_path):
    try:
        main([str(tmp_path / "no_existe.bin")])
        assert False, "deberia haber lanzado SystemExit"
    except SystemExit as exc:
        assert exc.code != 0
