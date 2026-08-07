"""
Tests de extremo a extremo del pipeline de generacion de informes.

No comprueban el contenido visual (eso se valido a mano durante el
desarrollo), sino que el pipeline completo no se rompe y que el HTML
resultante contiene las piezas que se esperan segun el escenario.
"""

from pathlib import Path

from src.analysis.anomalies import detect_anomalies
from src.parsers.base import FlightEvent, FlightLog, FlightRecord, Source
from src.report.fleet import generate_fleet_report
from src.report.generator import generate_report


def test_generate_report_for_clean_flight(tmp_path, synthetic_flight_log):
    detect_anomalies(synthetic_flight_log)
    output_path = tmp_path / "report.html"

    result_path = generate_report(synthetic_flight_log, str(output_path))

    html = Path(result_path).read_text(encoding="utf-8")
    assert "Informe de vuelo" in html
    assert "tag-clean" in html  # sin indicios de integridad, log limpio
    assert "Estimación de impacto" not in html  # vuelo nivelado: no deberia proyectarse impacto


def test_generate_report_includes_impact_section_for_crash_scenario(tmp_path):
    log = FlightLog(source=Source.ARDUPILOT, source_file="crash.bin")
    log.records.append(FlightRecord(timestamp=0.0, lat=47.0, lon=8.0, alt=51.0))
    log.records.append(FlightRecord(timestamp=0.1, lat=47.000004, lon=8.0, alt=50.0))
    output_path = tmp_path / "crash_report.html"

    generate_report(log, str(output_path), mass_kg=1.5)

    html = output_path.read_text(encoding="utf-8")
    assert "Estimación de impacto" in html
    assert "Energía cinética estimada" in html


def test_generate_report_flags_integrity_findings(tmp_path):
    log = FlightLog(source=Source.ARDUPILOT, source_file="tampered.bin")
    for i in range(20):
        log.records.append(FlightRecord(timestamp=float(i), alt=50.0))
    log.records.append(FlightRecord(timestamp=5.0, alt=999.0))  # retroceso de tiempo deliberado
    output_path = tmp_path / "tampered_report.html"

    generate_report(log, str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "tag-critical" in html


def test_generate_fleet_report_combines_multiple_flights(tmp_path, synthetic_flight_log):
    second_log = FlightLog(source=Source.PX4, source_file="second.ulog")
    second_log.records.append(FlightRecord(timestamp=0.0, roll=0.0, pitch=0.0, yaw=0.0))

    output_path = tmp_path / "fleet.html"
    generate_fleet_report([synthetic_flight_log, second_log], str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "Panel de flota" in html
    assert "synthetic.bin" in html
    assert "second.ulog" in html


def test_generate_report_translates_structure_and_dynamic_findings(tmp_path):
    """
    Cubre el caso que motivo el modulo de i18n: no basta con traducir la
    estructura fija de la plantilla, la descripcion de cada hallazgo
    concreto (generada dinamicamente en anomalies.py a partir de un
    message_key) tambien debe salir en el idioma pedido.
    """
    log = FlightLog(source=Source.ARDUPILOT, source_file="crash.bin")
    log.records.append(FlightRecord(timestamp=0.0, lat=47.0, lon=8.0, alt=51.0))
    log.records.append(FlightRecord(timestamp=0.1, lat=47.000004, lon=8.0, alt=50.0))
    detect_anomalies(log)
    output_path = tmp_path / "crash_report_en.html"

    generate_report(log, str(output_path), mass_kg=1.5, lang="en")

    html = output_path.read_text(encoding="utf-8")
    assert "Flight report" in html  # estructura fija de la plantilla
    assert "Impact estimate" in html
    assert "Estimated kinetic energy" in html
    assert "possible crash or loss of control" in html  # hallazgo dinamico (message_key="possible_impact")
    assert "Descenso de" not in html  # no debe quedar nada en español


def test_generate_fleet_report_translates_to_german(tmp_path, synthetic_flight_log):
    second_log = FlightLog(source=Source.PX4, source_file="second.ulog")
    second_log.records.append(FlightRecord(timestamp=0.0, roll=0.0, pitch=0.0, yaw=0.0))
    output_path = tmp_path / "fleet_de.html"

    generate_fleet_report([synthetic_flight_log, second_log], str(output_path), lang="de")

    html = output_path.read_text(encoding="utf-8")
    assert "Flottenübersicht" in html
    assert "Panel de flota" not in html


def test_generate_report_shows_ml_badge_for_ml_events(tmp_path, synthetic_flight_log):
    synthetic_flight_log.events.append(
        FlightEvent(
            timestamp=5.0,
            category="ml_anomaly_alt",
            severity="warning",
            description="anomalia de prueba",
            method="ml",
        )
    )
    output_path = tmp_path / "ml_report.html"

    generate_report(synthetic_flight_log, str(output_path))

    html = output_path.read_text(encoding="utf-8")
    assert "tag-ml" in html
