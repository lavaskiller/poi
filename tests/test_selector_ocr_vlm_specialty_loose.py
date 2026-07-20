import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "selector_ocr_vlm_specialty_loose", ROOT / "tools" / "run_selector_ocr_vlm_specialty_loose.py"
)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runner)


def candidate(name, distance=10, category="restaurant", place_id=None):
    result = {"name": name, "distance_m": distance, "category": category}
    if place_id:
        result["provider_place_id"] = place_id
    return result


def test_specialty_detection_requires_exact_candidate_name_word():
    assert runner.candidate_specialty_terms(candidate("Empty Quiver Archery")) == ["archery"]
    assert runner.candidate_specialty_terms(candidate("Arc Abatement")) == []
    assert runner.candidate_specialty_terms(candidate("Golfing Supply")) == []


def test_generic_venue_names_cannot_open_semantic_gate():
    assert runner.candidate_specialty_terms(candidate("Paris Baguette")) == []
    assert runner.candidate_specialty_terms(candidate("Downtown Cafe")) == []


def test_specialty_verifier_accepts_affirmative_format_variants_only():
    assert runner.permissive_specialty_yes("1")
    assert runner.permissive_specialty_yes("YES")
    assert runner.permissive_specialty_yes("yes, bows and targets are visible")
    assert runner.permissive_specialty_yes("true")
    assert not runner.permissive_specialty_yes("0")
    assert not runner.permissive_specialty_yes("NO")
    assert not runner.permissive_specialty_yes("uncertain")


def test_unique_direct_ocr_candidate_requires_one_supported_name():
    ranked = [candidate("Pristine Smiles"), candidate("Paris Baguette")]
    assert runner.unique_ocr_candidate(ranked, "cakes | PARIS BAGUETTE | mango")["name"] == "Paris Baguette"
    assert runner.unique_ocr_candidate(ranked, "cakes | mango") is None
