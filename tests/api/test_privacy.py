import re
from dataclasses import dataclass, field

import pytest

from tests.api.conftest import ADMIN, DIEGO_TEXT, TripHandle, create_july_trip, respond_with_text

# Orçamento é confidencial: o valor e quem tem o limite. Cada cenário percorre
# todas as rotas, como organizador e como cada convidado, grava todas as
# respostas e confere as que não são da própria Eva (a dona do orçamento).
# Os valores são incomuns para não coincidir com nenhum custo do catálogo.

BUDGET_ID = "eva-orcamento"
EVA_DATES = {"id": "eva-datas", "kind": "date_range", "start": "2027-07-10", "end": "2027-07-20"}
EVA_NO_COLD = {"id": "eva-clima", "kind": "exclude_climate", "climates": ["cold"]}
EVA_RELAXED = {"id": "eva-ritmo", "kind": "pace", "pace": "relaxed", "weight": 0.6}

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

#: O único texto sobre orçamento que o grupo pode ler (mapa de tensões).
ANONYMOUS_BUDGET_TEXT = re.compile(r"^O orçamento de um participante elimina [^.]+\.$")


@dataclass(frozen=True)
class Scenario:
    budget: int
    other_limits: list[dict] = field(default_factory=list)
    diego_responds: bool = False


SCENARIOS = {
    # Com datas e clima: Eva é quem tem mais limites, mas pelos outros dois.
    "orçamento folgado": Scenario(1137, [EVA_DATES, EVA_NO_COLD]),
    # R$ 1.013 elimina Paraty até no roteiro curto (R$ 1.080): aparece no mapa, sem nome.
    "orçamento elimina Paraty": Scenario(1013),
    # Orçamento mais um limite: contar o orçamento destacaria Eva como quem tem mais limites.
    "orçamento e datas": Scenario(1013, [EVA_DATES]),
    # Nada cabe: o orçamento entra nos limites que bloqueiam.
    "orçamento inviabiliza tudo": Scenario(613, [EVA_DATES], diego_responds=True),
}


@dataclass
class Recorder:
    """Toda resposta da API, com quem a recebeu."""

    client: object
    responses: list[tuple[str, str, object]] = field(default_factory=list)

    def call(self, viewer: str, method: str, url: str, **kwargs):
        response = getattr(self.client, method)(url, **kwargs)
        assert response.status_code < 400, f"{method.upper()} {url}: {response.text}"
        self.responses.append((viewer, f"{method.upper()} {url}", response.json()))
        return response.json()


def walk(value, path="$"):
    """Cada valor da resposta, em qualquer nível, com o caminho até ele."""
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, f"{path}[{index}]")


def budget_leaks(body, budget: int, eva_id: str, eva_counted_limits: int) -> list[str]:
    # "1137", "1.137" ou "1137.0", sem outros dígitos colados.
    thousands, rest = divmod(budget, 1000)
    value_text = re.compile(rf"(?<!\d)(?:{budget}|{thousands}\.{rest:03d})(?!\d)")
    leaks = []
    for path, value in walk(body):
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float) and value == budget:
            leaks.append(f"{path}: valor do orçamento")
        if isinstance(value, str) and not UUID.match(value):
            if value_text.search(value):
                leaks.append(f"{path}: valor do orçamento em {value!r}")
            if BUDGET_ID in value:
                leaks.append(f"{path}: id do limite de orçamento")
            if "orçamento" in value.lower() and not ANONYMOUS_BUDGET_TEXT.match(value):
                leaks.append(f"{path}: texto sobre orçamento {value!r}")
        if isinstance(value, dict):
            if "max_per_person" in value:
                leaks.append(f"{path}: limite de orçamento de alguém")
            if value.get("kind") == "budget" and value.get("member_id") is not None:
                leaks.append(f"{path}: orçamento com dono")
            if value.get("most_restrictive_member_id") == eva_id and eva_counted_limits < 2:
                leaks.append(f"{path}: destaque de mais limites conta o orçamento")
    return leaks


def walk_every_route(recorder: Recorder, trip: TripHandle, client) -> None:
    """Todas as leituras e escritas do contrato, como organizador e como cada convidado."""
    names = list(trip.tokens)
    recorder.call("organizador", "get", f"/trips/{trip.id}", headers=trip.admin)
    recorder.call("organizador", "get", f"/trips/{trip.id}/tensions", headers=trip.admin)
    created = recorder.call("organizador", "post", f"/trips/{trip.id}/plans", headers=trip.admin)
    round_number = created["round"]
    recorder.call(
        "organizador", "get", f"/trips/{trip.id}/plans", params={"round": round_number}, headers=trip.admin
    )
    for name in names:
        recorder.call(name, "get", f"/invite/{trip.tokens[name]}")
        recorder.call(
            name, "get", f"/trips/{trip.id}/plans", params={"round": round_number}, headers=trip.invite(name)
        )
        recorder.call(
            name,
            "post",
            f"/invite/{trip.tokens[name]}/constraints/parse",
            json={"raw_text": "Quero praia e ritmo tranquilo, de 10 a 20 de julho."},
        )
    for plan in created["plans"][:1]:
        # Quem organiza recusa e confirma o motivo. A recusa também evita que a viagem feche no meio.
        rejecter, *accepting = names
        rejection = {
            "invite_token": trip.tokens[rejecter],
            "verdict": "rejected",
            "comment": "Prefiro Paraty.",
        }
        draft = recorder.call(rejecter, "post", f"/plans/{plan['id']}/reactions", json=rejection)
        recorder.call(
            rejecter,
            "post",
            f"/plans/{plan['id']}/reactions/constraints",
            json={
                "invite_token": trip.tokens[rejecter],
                "hard": draft["constraint_draft"]["hard"],
                "soft": draft["constraint_draft"]["soft"],
            },
        )
        for name in accepting:
            verdict = {"invite_token": trip.tokens[name], "verdict": "accepted"}
            recorder.call(name, "post", f"/plans/{plan['id']}/reactions", json=verdict)
        recorder.call(
            "organizador",
            "get",
            f"/trips/{trip.id}/plans",
            params={"round": round_number},
            headers=trip.admin,
        )
    recorder.call("organizador", "get", "/destinations")


@pytest.mark.parametrize("scenario", SCENARIOS.values(), ids=SCENARIOS.keys())
def test_group_responses_never_reveal_budget_value_or_owner(client, scenario):
    trip = create_july_trip(client)
    recorder = Recorder(client)
    budget = {"id": BUDGET_ID, "kind": "budget", "max_per_person": scenario.budget, "all_inclusive": True}
    eva_body = {"raw_text": "texto de Eva", "hard": [*scenario.other_limits, budget], "soft": [EVA_RELAXED]}
    recorder.call("Eva", "put", f"/invite/{trip.tokens['Eva']}/constraints", json=eva_body)
    if scenario.diego_responds:
        respond_with_text(client, trip, "Diego", DIEGO_TEXT)

    walk_every_route(recorder, trip, client)

    eva_id = trip.member_ids["Eva"]
    counted = len(scenario.other_limits)
    others = [(viewer, route, body) for viewer, route, body in recorder.responses if viewer != "Eva"]
    # 4 do organizador, 3 de cada um dos 4 outros convidados e o catálogo; com planos, mais as reações.
    assert len(others) >= 17
    leaks = [
        f"{viewer} · {route} · {leak}"
        for viewer, route, body in others
        for leak in budget_leaks(body, scenario.budget, eva_id, counted)
    ]
    assert leaks == []

    # Controle: a própria Eva vê o próprio orçamento, então a busca acharia um vazamento.
    own = [body for viewer, _, body in recorder.responses if viewer == "Eva"]
    assert any(budget_leaks(body, scenario.budget, eva_id, counted) for body in own)


def test_scenarios_reach_the_budget_paths(client):
    """Os cenários de fato passam pelo orçamento no mapa e nos limites que bloqueiam."""
    trip = create_july_trip(client)
    budget = {"id": BUDGET_ID, "kind": "budget", "max_per_person": 613, "all_inclusive": True}
    client.put(
        f"/invite/{trip.tokens['Eva']}/constraints", json={"raw_text": "x", "hard": [budget], "soft": []}
    )
    tensions = client.get(f"/trips/{trip.id}/tensions", headers=trip.admin).json()
    assert any(ANONYMOUS_BUDGET_TEXT.match(item["summary"]) for item in tensions["key_constraints"])
    round_ = client.post(f"/trips/{trip.id}/plans", headers={ADMIN: trip.admin[ADMIN]}).json()
    assert {"member_id": None, "kind": "budget"} in [
        {"member_id": limit["member_id"], "kind": limit["kind"]} for limit in round_["blocking_limits"]
    ]
