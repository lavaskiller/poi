import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("selector_ocr_override", ROOT / "tools" / "run_selector_ocr_override.py")
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runner)


def candidate(name, distance, category="restaurant", place_id=None):
    value = {"name": name, "distance_m": distance, "category": category}
    if place_id is not None:
        value["provider_place_id"] = place_id
    return value


def test_full_distinctive_ocr_name_overrides_bloggo_when_unique():
    raw = [candidate("Pristine Smiles", 10, place_id="a"), candidate("Paris Baguette", 20, place_id="b")]
    result = runner.decide(raw, "Mocha cake | PARIS BAGUETTE | cheesecake")
    assert result["prediction"] == "Paris Baguette"
    assert result["decision"] == "unique_ocr_name_override"
    assert result["evidence"][0]["strength"] == "full_name"


def test_ocr_for_bloggo_winner_confirms_without_changing_prediction():
    raw = [candidate("Paris Baguette", 10, place_id="a"), candidate("Pristine Smiles", 100, place_id="b")]
    result = runner.decide(raw, "PARIS BAGUETTE")
    assert result["prediction"] == "Paris Baguette"
    assert result["decision"] == "ocr_confirms_bloggo"


def test_generic_ocr_word_is_not_identity_evidence():
    raw = [candidate("Alpha Cafe", 10, place_id="a"), candidate("Bravo Cafe", 15, place_id="b")]
    result = runner.decide(raw, "A cafe is open")
    assert result["prediction"] == "Alpha Cafe"
    assert result["decision"] == "no_unique_ocr_name_support_bloggo_fallback"


def test_multiple_supported_candidates_never_override():
    raw = [candidate("Alpha Cafe", 10, place_id="a"), candidate("Bravo Bistro", 15, place_id="b")]
    result = runner.decide(raw, "ALPHA CAFE and BRAVO BISTRO")
    assert result["prediction"] == "Alpha Cafe"
    assert result["decision"] == "ambiguous_ocr_name_support_bloggo_fallback"


def test_no_usable_candidate_stays_blank_even_if_ocr_has_text():
    result = runner.decide([candidate("Parking", 10, "parking")], "PARIS BAGUETTE")
    assert result["prediction"] == ""
    assert result["decision"] == "no_usable_bloggo_candidate"
