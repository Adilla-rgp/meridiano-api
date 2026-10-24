import json
from pathlib import Path

from scripts.export_fixture import DEFAULT_OUT, TENSIONS_FILE, build, build_tensions

ROOT = Path(__file__).resolve().parent.parent


def test_committed_fixture_matches_the_engine():
    """Se falhar, rode `python -m scripts.export_fixture` e copie o arquivo para o front."""
    committed = json.loads((ROOT / DEFAULT_OUT).read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(build()))


def test_committed_tensions_match_the_engine():
    """Se falhar, rode `python -m scripts.export_fixture` e copie os arquivos para o front."""
    committed = json.loads((ROOT / DEFAULT_OUT).with_name(TENSIONS_FILE).read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(build_tensions()))


def test_tensions_cover_the_same_rounds_and_never_link_by_budget():
    rounds = build_tensions()["rounds"]
    assert list(rounds) == [item["name"] for item in build()["rounds"]]
    for name, data in rounds.items():
        assert all(pair["criterion"] != "budget" for pair in data["pairs"]), name
        assert all("R$" not in item["summary"] for item in data["key_constraints"]), name


def test_fixture_rounds_never_tie_budget_to_a_member():
    for round_data in build()["rounds"]:
        refs = [
            *(limit for item in round_data["excluded_destinations"] for limit in item["limits"]),
            *round_data["blocking_limits"],
        ]
        assert all(ref["member_id"] is None for ref in refs if ref["kind"] == "budget"), round_data["name"]


def test_fixture_covers_the_demo_states():
    rounds = {item["name"]: item for item in build()["rounds"]}
    assert rounds["after_diego_response"]["plans"] == []
    assert rounds["after_diego_response"]["blocking_limits"][0]["member_id"] == "mem-diego"
    eva_scores = [
        score
        for plan in rounds["eva_limits_only"]["plans"]
        for score in plan["per_member_scores"]
        if score["member_id"] == "mem-eva"
    ]
    assert eva_scores and all(score["has_preferences"] is False for score in eva_scores)
