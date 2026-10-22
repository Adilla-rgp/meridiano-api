import json

from tests.api.conftest import ADMIN, DIEGO_TEXT, EVA_TEXT, ROOT, respond_with_text

# Ciclo completo pela API: criar viagem → convidar → responder → gerar planos →
# reagir. Os planos têm de ser os mesmos que o motor exportou para o front
# (fixtures/july-trip.json), porque é o mesmo grupo com as mesmas respostas.

FIXTURE = json.loads((ROOT / "fixtures" / "july-trip.json").read_text(encoding="utf-8"))
ENGINE_ROUNDS = {item["name"]: item for item in FIXTURE["rounds"]}


def with_api_ids(value, member_ids: dict[str, str]):
    """Troca, em qualquer nível, os ids do fixture (mem-eva) pelos que a API criou."""
    by_fixture_id = {f"mem-{name.lower()}": member_id for name, member_id in member_ids.items()}
    if isinstance(value, dict):
        return {key: with_api_ids(item, member_ids) for key, item in value.items()}
    if isinstance(value, list):
        return [with_api_ids(item, member_ids) for item in value]
    return by_fixture_id.get(value, value) if isinstance(value, str) else value


def plan_keys(plans: list[dict]) -> list[tuple]:
    return [
        (p["destination_id"], p["variant_label"], p["start_date"], p["end_date"], p["score"]) for p in plans
    ]


def test_create_trip_returns_tokens_once(client):
    response = client.post(
        "/trips",
        json={
            "title": "Feriado",
            "organizer_name": "Ana",
            "destination_ids": ["dest-paraty", "dest-lencois"],
            "date_window_start": "2027-07-05",
            "date_window_end": "2027-07-26",
            "nights": 5,
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert created["status"] == "collecting"
    assert created["nights"] == 5 and created["alpha"] == 0.5
    assert (
        created["admin_url"]
        == f"http://front.test/viagens/{created['id']}/tensoes#admin={created['admin_token']}"
    )
    assert len(created["admin_token"]) >= 40
    [organizer] = created["members"]
    assert organizer["is_organizer"] and organizer["invite_token"]
    assert created["organizer_id"] == organizer["id"]
    # Destinos na ordem escolhida, com o custo das noites da viagem.
    assert [d["id"] for d in created["destinations"]] == ["dest-paraty", "dest-lencois"]
    assert created["destinations"][0]["est_cost_per_person"] == 480 + 5 * 150

    detail = client.get(f"/trips/{created['id']}", headers={ADMIN: created["admin_token"]}).json()
    assert detail["members"][0]["invite_token"] is None
    assert detail["latest_round"] is None


def test_full_cycle(client, july):
    # Estado inicial: 3 de 5 respostas, sem planos.
    detail = client.get(f"/trips/{july.id}", headers=july.admin).json()
    assert [m["display_name"] for m in detail["members"]] == ["Ana", "Bruno", "Carla", "Eva", "Diego"]
    assert [m["responded_at"] is not None for m in detail["members"]] == [True, True, True, False, False]

    tensions = client.get(f"/trips/{july.id}/tensions", headers=july.admin).json()
    assert tensions["responded_count"] == 3 and tensions["member_count"] == 5
    assert all(pair["status"] == "compatible" for pair in tensions["pairs"])

    first = client.post(f"/trips/{july.id}/plans", headers=july.admin)
    assert first.status_code == 201
    assert plan_keys(first.json()["plans"]) == plan_keys(ENGINE_ROUNDS["before_eva_response"]["plans"])

    # Eva responde em texto livre e confirma a interpretação.
    invite = client.get(f"/invite/{july.tokens['Eva']}").json()
    assert invite["organizer_name"] == "Ana" and invite["member_count"] == 5
    assert invite["latest_round"] == 1 and invite["constraints"] is None
    saved = respond_with_text(client, july, "Eva", EVA_TEXT)
    assert [item["kind"] for item in saved["hard"]] == ["date_range", "budget", "exclude_climate"]
    assert saved["hard"][1]["summary"] == "Até R$ 1.100 por pessoa, tudo incluso"
    assert saved["version"] == 1

    tensions = client.get(f"/trips/{july.id}/tensions", headers=july.admin).json()
    assert {
        "member_a_id": july.member_ids["Carla"],
        "member_b_id": july.member_ids["Eva"],
        "status": "conflict",
        "criterion": "climate",
    } in tensions["pairs"]
    assert "O limite de clima de Eva elimina Chapada Diamantina, que Carla prefere." in [
        item["summary"] for item in tensions["key_constraints"]
    ]

    second = client.post(f"/trips/{july.id}/plans", headers=july.admin).json()
    engine_round = ENGINE_ROUNDS["after_eva_response"]
    assert second["round"] == 2
    assert plan_keys(second["plans"]) == plan_keys(engine_round["plans"])
    assert second["excluded_destinations"] == with_api_ids(
        engine_round["excluded_destinations"], july.member_ids
    )
    assert second["alternatives_evaluated"] == engine_round["alternatives_evaluated"]
    assert second["recommended_plan_id"] == second["plans"][0]["id"]
    assert all(plan["violated_limits"] == 0 and plan["round"] == 2 for plan in second["plans"])
    assert client.get(f"/trips/{july.id}", headers=july.admin).json()["status"] == "planned"

    # Reações: cada um pelo próprio convite.
    recommended = second["recommended_plan_id"]

    def react(name: str, verdict: str, comment: str | None = None):
        body = {"invite_token": july.tokens[name], "verdict": verdict, "comment": comment}
        return client.post(f"/plans/{recommended}/reactions", json=body)

    assert react("Ana", "accepted").status_code == 201
    assert react("Bruno", "rejected").status_code == 422  # recusa sem motivo
    assert react("Bruno", "rejected", "Queria praia com agito.").status_code == 201
    assert react("Bruno", "accepted_with_reservation", "Topo se tiver passeio de buggy.").status_code == 201

    as_admin = client.get(f"/trips/{july.id}/plans", params={"round": 2}, headers=july.admin).json()
    by_member = {r["member_id"]: r["verdict"] for r in as_admin["reactions"]}
    assert by_member == {
        july.member_ids["Ana"]: "accepted",
        july.member_ids["Bruno"]: "accepted_with_reservation",
    }

    as_bruno = client.get(f"/trips/{july.id}/plans", params={"round": 2}, headers=july.invite("Bruno")).json()
    assert [r["member_id"] for r in as_bruno["reactions"]] == [july.member_ids["Bruno"]]
    assert as_bruno["plans"] == as_admin["plans"]

    # Diego responde e nada cabe: a rodada existe, sem planos.
    respond_with_text(client, july, "Diego", DIEGO_TEXT)
    third = client.post(f"/trips/{july.id}/plans", headers=july.admin).json()
    engine_round = ENGINE_ROUNDS["after_diego_response"]
    assert third["round"] == 3 and third["plans"] == [] and third["recommended_plan_id"] is None
    # No empate de eliminated_candidates, o motor ordena pelo id do participante,
    # que aqui é um UUID: compara sem depender dessa ordem.
    expected = with_api_ids(engine_round["blocking_limits"], july.member_ids)
    assert sorted(third["blocking_limits"], key=str) == sorted(expected, key=str)
    counts = [limit["eliminated_candidates"] for limit in third["blocking_limits"]]
    assert counts == sorted(counts, reverse=True)
    assert client.get(f"/trips/{july.id}", headers=july.admin).json()["status"] == "collecting"

    # Reagir a um plano de rodada anterior não vale.
    assert react("Carla", "accepted").status_code == 409
    assert client.get(f"/trips/{july.id}/plans", params={"round": 9}, headers=july.admin).status_code == 404


def test_saving_again_creates_a_new_version(client, july):
    first = respond_with_text(client, july, "Eva", EVA_TEXT)
    second = respond_with_text(client, july, "Eva", "Agora topo de 10 a 20 de julho, sem limite de gasto.")
    assert (first["version"], second["version"]) == (1, 2)
    invite = client.get(f"/invite/{july.tokens['Eva']}").json()
    assert invite["constraints"]["version"] == 2
    assert [item["kind"] for item in invite["constraints"]["hard"]] == ["date_range"]


def test_generate_plans_needs_two_responses(client):
    created = client.post(
        "/trips",
        json={
            "title": "Feriado",
            "organizer_name": "Ana",
            "destination_ids": ["dest-paraty", "dest-lencois"],
            "date_window_start": "2027-07-05",
            "date_window_end": "2027-07-26",
        },
    ).json()
    response = client.post(f"/trips/{created['id']}/plans", headers={ADMIN: created["admin_token"]})
    assert response.status_code == 422
    assert response.json()["detail"] == "São necessárias pelo menos 2 respostas para gerar planos."
