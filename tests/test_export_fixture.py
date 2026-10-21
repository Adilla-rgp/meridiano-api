import json
from pathlib import Path

from scripts.export_fixture import DEFAULT_OUT, build

ROOT = Path(__file__).resolve().parent.parent


def test_committed_fixture_matches_the_engine():
    """Se falhar, rode `python -m scripts.export_fixture` e copie o arquivo para o front."""
    committed = json.loads((ROOT / DEFAULT_OUT).read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(build()))


def test_fixture_rounds_never_tie_budget_to_a_member():
    text = json.dumps(build()["rounds"])
    data = json.loads(text)
    refs = [
        ref
        for round_data in data.values()
        for ref in [
            *(limit for item in round_data["excluded_destinations"] for limit in item["limits"]),
            *round_data["blocking_limits"],
        ]
    ]
    assert all(ref["member_id"] is None for ref in refs if ref["kind"] == "budget")
