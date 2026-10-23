# Entre rodadas: a recusa vira restrição na rodada seguinte, depois que quem
# recusou confirma, e a viagem fecha quando todos aceitam o plano recomendado.

CARLA_REASON = "Lençóis não, prefiro Paraty."


def generate(client, trip) -> dict:
    response = client.post(f"/trips/{trip.id}/plans", headers=trip.admin)
    assert response.status_code == 201, response.text
    return response.json()


def react(client, trip, plan_id: str, name: str, verdict: str, comment: str | None = None):
    body = {"invite_token": trip.tokens[name], "verdict": verdict, "comment": comment}
    return client.post(f"/plans/{plan_id}/reactions", json=body)


def confirm(client, trip, plan_id: str, name: str, draft: dict):
    body = {"invite_token": trip.tokens[name], "hard": draft["hard"], "soft": draft["soft"]}
    return client.post(f"/plans/{plan_id}/reactions/constraints", json=body)


def destinations(round_: dict) -> list[str]:
    return [plan["destination_id"] for plan in round_["plans"]]


def test_confirmed_rejection_changes_the_next_round(client, july):
    first = generate(client, july)
    recommended = first["recommended_plan_id"]
    assert first["plans"][0]["destination_id"] == "dest-lencois"

    rejected = react(client, july, recommended, "Carla", "rejected", CARLA_REASON)
    assert rejected.status_code == 201, rejected.text
    body = rejected.json()
    assert body["verdict"] == "rejected" and body["trip_status"] == "planned"
    draft = body["constraint_draft"]
    assert [(i["kind"], i["destination_ids"]) for i in draft["hard"]] == [
        ("exclude_destination", ["dest-lencois"])
    ]
    assert [(i["kind"], i["destination_ids"]) for i in draft["soft"]] == [
        ("prefer_destination", ["dest-paraty"])
    ]
    assert draft["member_limits"] == [
        {"constraint_id": "h1", "kind": "exclude_destination", "eliminated_destination_ids": ["dest-lencois"]}
    ]
    # O rascunho não é salvo: até a confirmação, Carla continua com a versão 1.
    invite = client.get(f"/invite/{july.tokens['Carla']}").json()
    assert invite["constraints"]["version"] == 1

    confirmed = confirm(client, july, recommended, "Carla", draft)
    assert confirmed.status_code == 201, confirmed.text
    saved = confirmed.json()
    assert saved["version"] == 2
    assert [item["id"] for item in saved["hard"]] == ["v2-h1"]
    assert saved["hard"][0]["summary"] == "Sem Lençóis Maranhenses"
    # A preferência de destino nova substitui a anterior; as outras ficam.
    assert [(item["id"], item["kind"]) for item in saved["soft"]] == [
        ("carla-s2", "prefer_tags"),
        ("carla-s3", "pace"),
        ("v2-s1", "prefer_destination"),
    ]
    assert saved["raw_text"].endswith(f"Ao recusar um plano: {CARLA_REASON}")

    # Confirmar de novo a mesma recusa não duplica a restrição.
    assert confirm(client, july, recommended, "Carla", draft).status_code == 409

    second = generate(client, july)
    assert second["round"] == 2
    assert "dest-lencois" not in destinations(second)
    assert second["plans"][0]["destination_id"] == "dest-paraty"
    lencois = next(
        item for item in second["excluded_destinations"] if item["destination_id"] == "dest-lencois"
    )
    assert lencois["reason"] == "limit"
    assert lencois["limits"] == [{"member_id": july.member_ids["Carla"], "kind": "exclude_destination"}]


def test_unconfirmed_rejection_does_not_change_the_next_round(client, july):
    first = generate(client, july)
    assert (
        react(client, july, first["recommended_plan_id"], "Carla", "rejected", CARLA_REASON).status_code
        == 201
    )
    second = generate(client, july)
    assert destinations(second) == destinations(first)


def test_only_who_rejected_confirms(client, july):
    first = generate(client, july)
    recommended = first["recommended_plan_id"]
    draft = react(client, july, recommended, "Carla", "rejected", CARLA_REASON).json()["constraint_draft"]
    assert react(client, july, recommended, "Ana", "accepted").json()["constraint_draft"] is None
    response = confirm(client, july, recommended, "Ana", draft)
    assert response.status_code == 409
    assert (
        response.json()["detail"] == "Só quem recusou este plano confirma uma restrição a partir do motivo."
    )

    # Depois de uma nova rodada, a recusa da rodada anterior não pode mais ser confirmada.
    generate(client, july)
    assert confirm(client, july, recommended, "Carla", draft).status_code == 409


def test_confirmation_needs_something_to_confirm(client, july):
    first = generate(client, july)
    recommended = first["recommended_plan_id"]
    draft = react(client, july, recommended, "Carla", "rejected", "Não gostei.").json()["constraint_draft"]
    assert draft == {"hard": [], "soft": [], "member_limits": []}
    assert confirm(client, july, recommended, "Carla", draft).status_code == 422


def test_trip_closes_when_everyone_accepts_the_recommended_plan(client, july):
    first = generate(client, july)
    recommended, other = first["plans"][0]["id"], first["plans"][1]["id"]

    assert react(client, july, recommended, "Ana", "accepted").json()["trip_status"] == "planned"
    # Aceitar outra alternativa não conta para o acordo.
    assert react(client, july, other, "Bruno", "accepted").json()["trip_status"] == "planned"
    assert (
        react(client, july, recommended, "Carla", "rejected", CARLA_REASON).json()["trip_status"] == "planned"
    )
    assert (
        react(client, july, recommended, "Bruno", "accepted_with_reservation", "Topo.").json()["trip_status"]
        == "planned"
    )
    # Carla troca a recusa por aceito: agora todos que responderam aceitaram.
    last = react(client, july, recommended, "Carla", "accepted")
    assert last.status_code == 201 and last.json()["trip_status"] == "agreed"
    assert client.get(f"/trips/{july.id}", headers=july.admin).json()["status"] == "agreed"
    assert client.get(f"/invite/{july.tokens['Eva']}").json()["trip"]["status"] == "agreed"

    # Fechada, nada muda.
    closed = "A viagem já fechou: todos aceitaram o plano final."
    for response in (
        react(client, july, recommended, "Ana", "rejected", "Mudei de ideia."),
        client.post(f"/trips/{july.id}/plans", headers=july.admin),
        client.put(
            f"/invite/{july.tokens['Eva']}/constraints", json={"raw_text": "", "hard": [], "soft": []}
        ),
        client.post(
            f"/invite/{july.tokens['Eva']}/constraints/parse",
            json={"raw_text": "Ritmo tranquilo, por favor."},
        ),
    ):
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == closed
    round_ = client.get(f"/trips/{july.id}/plans", params={"round": 1}, headers=july.admin).json()
    assert {r["verdict"] for r in round_["reactions"] if r["plan_id"] == recommended} == {
        "accepted",
        "accepted_with_reservation",
    }


def test_someone_who_responded_after_the_round_must_also_accept(client, july):
    first = generate(client, july)
    recommended = first["recommended_plan_id"]
    client.put(f"/invite/{july.tokens['Eva']}/constraints", json={"raw_text": "", "hard": [], "soft": []})
    for name in ("Ana", "Bruno", "Carla"):
        assert react(client, july, recommended, name, "accepted").json()["trip_status"] == "planned"
    assert react(client, july, recommended, "Eva", "accepted").json()["trip_status"] == "agreed"
    assert client.get(f"/trips/{july.id}", headers=july.admin).json()["status"] == "agreed"
