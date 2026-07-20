import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "selector_bloggo_vlm_conditioned", ROOT / "tools" / "run_selector_bloggo_vlm_conditioned.py"
)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runner)


def candidate(name, distance, category="restaurant", place_id=None):
    value = {"name": name, "distance_m": distance, "category": category}
    if place_id is not None:
        value["provider_place_id"] = place_id
    return value


def test_choice_prompt_names_only_the_top_three_candidates():
    prompt = runner.selection_prompt([
        candidate("Alpha", 1), candidate("Bravo", 2), candidate("Charlie", 3)
    ])
    assert "1. Alpha" in prompt and "2. Bravo" in prompt and "3. Charlie" in prompt
    assert "Reply with exactly one character" in prompt


def test_choice_parser_accepts_only_one_exact_candidate_digit():
    assert runner.parse_choice("1", 3) == 0
    assert runner.parse_choice("3", 3) == 2
    assert runner.parse_choice("0", 3) is None
    assert runner.parse_choice("2 because of the logo", 3) is None
    assert runner.parse_choice("4", 3) is None
    assert runner.parse_choice("", 3) is None


def test_yes_parser_does_not_accept_an_explanation_as_confirmation():
    assert runner.exact_yes("YES")
    assert runner.exact_yes(" yes ")
    assert not runner.exact_yes("YES, likely")
    assert not runner.exact_yes("NO")


def test_only_bloggo_ambiguous_sets_are_vlm_eligible():
    ambiguous = runner.decide_without_model([candidate("Alpha", 10), candidate("Bravo", 20)])
    clear = runner.decide_without_model([candidate("Alpha", 10), candidate("Bravo", 100)])
    assert ambiguous["decision"] == "bloggo_ambiguous_vlm_eligible"
    assert clear["decision"] == "bloggo_clear_winner_vlm_skipped"


def test_cache_key_changes_with_candidate_ordering_metadata_and_prompt_contract():
    case = {"_dataset": "d", "_photo": "p.jpg"}
    first = [candidate("Alpha", 10, place_id="a"), candidate("Bravo", 20, place_id="b")]
    second = [candidate("Alpha", 11, place_id="a"), candidate("Bravo", 20, place_id="b")]
    first_ranked = runner.decide_without_model(first)["ranked"]
    second_ranked = runner.decide_without_model(second)["ranked"]
    checkpoint = Path("/model/checkpoint")
    assert runner.cache_key(case, first, first_ranked, checkpoint) != runner.cache_key(case, second, second_ranked, checkpoint)
