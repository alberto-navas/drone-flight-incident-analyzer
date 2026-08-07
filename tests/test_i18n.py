"""Tests del modulo central de traduccion (src/report/i18n.py)."""

from src.analysis.integrity import IntegrityFinding
from src.parsers.base import FlightEvent
from src.report.i18n import (
    SUPPORTED_LANGUAGES,
    normalize_lang,
    translate_assumptions,
    translate_event,
    translate_finding,
    translate_integrity_summary,
    ui,
)


def test_normalize_lang_falls_back_to_spanish_for_unknown_values():
    assert normalize_lang("fr") == "es"
    assert normalize_lang(None) == "es"
    assert normalize_lang("es") == "es"


def test_translate_event_renders_message_key_in_requested_language():
    event = FlightEvent(
        timestamp=1.0,
        category="possible_impact",
        severity="critical",
        description="Descenso de 12.0 m/s (umbral: 8.0 m/s); posible caida o perdida de control.",
        message_key="possible_impact",
        message_params={"rate": 12.0, "threshold": 8.0},
    )
    assert "Descenso de 12.0 m/s" in translate_event(event, "es")
    assert "Descent of 12.0 m/s" in translate_event(event, "en")
    assert "Sinkflug von 12.0 m/s" in translate_event(event, "de")


def test_translate_event_without_message_key_returns_raw_description():
    """
    Un logged_message de PX4 (texto libre citado del propio firmware) no
    tiene message_key: no hay nada que re-renderizar, se devuelve tal cual
    salga el idioma pedido.
    """
    event = FlightEvent(timestamp=1.0, category="firmware_message", severity="info", description="Estimator reset")
    assert translate_event(event, "de") == "Estimator reset"


def test_translate_event_appends_episode_suffix_in_requested_language():
    event = FlightEvent(
        timestamp=1.0,
        category="possible_impact",
        severity="critical",
        description="...",
        message_key="possible_impact",
        message_params={"rate": 12.0, "threshold": 8.0},
        episode_duration_s=4.0,
        episode_sample_count=9,
    )
    assert "sustained for 4.0s (9 samples)" in translate_event(event, "en")
    assert "anhaltend über 4.0s (9 Messungen)" in translate_event(event, "de")


def test_translate_finding_renders_integrity_message_key():
    finding = IntegrityFinding(
        kind="suspicious_gap",
        field=None,
        timestamp=5.0,
        severity="warning",
        description="...",
        message_key="suspicious_gap",
        message_params={"gap": 12.0, "a": 5.0, "b": 17.0, "median": 1.0},
    )
    assert "12.0s gap" in translate_finding(finding, "en")
    assert "12.0s Lücke" in translate_finding(finding, "de")


def test_translate_integrity_summary_clean_vs_dirty():
    assert "No signs of tampering" in translate_integrity_summary([], "en")

    finding = IntegrityFinding(kind="time_reversal", field="alt", timestamp=1.0, severity="critical", description="...")
    summary = translate_integrity_summary([finding], "en")
    assert "1 finding(s)" in summary
    assert "1 critical" in summary


def test_translate_assumptions_preserves_order():
    keys = ["terrain_flat", "no_mass"]
    translated = translate_assumptions(keys, "en")
    assert translated[0].startswith("Flat terrain")
    assert translated[1].startswith("Vehicle mass was not provided")


def test_ui_has_matching_keys_across_all_languages():
    """
    Regresion de coherencia: si se añade una clave a un idioma sin
    añadirla a los otros dos, una plantilla que la use romperia en
    silencio (KeyError) solo en ese idioma. Se comprueba una vez aqui en
    vez de confiar en descubrirlo a mano en cada idioma.
    """
    key_sets = {lang: set(ui(lang).keys()) for lang in SUPPORTED_LANGUAGES}
    reference = key_sets["es"]
    for lang, keys in key_sets.items():
        assert keys == reference, f"claves de UI distintas entre 'es' y '{lang}': {reference ^ keys}"
