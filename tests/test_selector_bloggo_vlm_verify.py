import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "selector_bloggo_vlm_verify", ROOT / "tools" / "run_selector_bloggo_vlm_verify.py"
)
hybrid = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(hybrid)


def candidate(name, distance, category="restaurant", place_id=None):
    result = {"name": name, "distance_m": distance, "category": category}
    if place_id is not None:
        result["provider_place_id"] = place_id
    return result


def test_evidence_requires_a_strict_json_object_and_visible_text():
    assert hybrid.parse_evidence('{"visible_text":"Da Vien Coffee"}') == {
        "visible_text": "Da Vien Coffee", "place_type": "unknown", "view": "unknown"
    }
    assert hybrid.parse_evidence('```json\n{"visible_text":"Da Vien Coffee"}\n```') is None
    assert hybrid.parse_evidence('{"place_type":"cafe"}') is None
    assert hybrid.parse_evidence('not json') is None


def test_unique_full_distinctive_name_match_rejects_generic_and_partial_text():
    candidates = [candidate("Da Vien Coffee", 10), candidate("Tea House", 15)]
    assert hybrid.unique_strong_name_match("Sign reads DA VIEN COFFEE", candidates)["name"] == "Da Vien Coffee"
    assert hybrid.unique_strong_name_match("Sign reads Da Vien", candidates) is None
    assert hybrid.unique_strong_name_match("Cafe Restaurant", candidates) is None


def test_multiple_or_duplicate_name_matches_never_override():
    candidates = [candidate("Blue Bottle Coffee", 10, place_id="a"), candidate("Blue Bottle Coffee", 12, place_id="b")]
    assert hybrid.unique_strong_name_match("BLUE BOTTLE COFFEE", candidates) is None


def test_exact_yes_is_not_a_best_effort_parser():
    assert hybrid.exact_yes("YES")
    assert hybrid.exact_yes(" yes ")
    assert not hybrid.exact_yes("YES, the sign is visible")
    assert not hybrid.exact_yes("NO")


def test_bloggo_clear_winner_skips_vlm_and_retains_bloggo_not_raw_nearest():
    # Bloggo excludes the raw-nearest infrastructure POI, leaving the museum.
    raw = [candidate("Parking", 10, "parking"), candidate("Museum", 30, "museum")]
    result = hybrid.decide_without_model(raw)
    assert result["decision"] == "bloggo_clear_winner_vlm_skipped"
    assert result["base"]["name"] == "Museum"


def test_bloggo_ambiguous_case_is_the_only_vlm_eligible_policy():
    raw = [candidate("Alpha Bistro", 10), candidate("Bravo Bistro", 20)]
    result = hybrid.decide_without_model(raw)
    assert result["decision"] == "bloggo_ambiguous_vlm_eligible"
    assert result["base"]["name"] == "Alpha Bistro"


def test_cache_key_changes_when_policy_or_prompt_relevant_candidate_metadata_changes():
    case = {"_dataset": "d", "_photo": "p.jpg"}
    first = [candidate("Alpha Bistro", 10, place_id="a"), candidate("Bravo Bistro", 20, place_id="b")]
    second = [candidate("Alpha Bistro", 11, place_id="a"), candidate("Bravo Bistro", 20, place_id="b")]
    first_ranked = hybrid.decide_without_model(first)["ranked"]
    second_ranked = hybrid.decide_without_model(second)["ranked"]
    model = Path("/model/checkpoint")
    assert hybrid.cache_key(case, first, first_ranked, model) != hybrid.cache_key(case, second, second_ranked, model)
