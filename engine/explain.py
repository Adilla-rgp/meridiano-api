from engine.models import Member, PreferClimate, PreferDestination, PreferPace, SoftConstraint
from engine.scoring import DESTINATION_FIRST, NEUTRAL, Breakdown, Component

# Justificativa por regras, a partir dos mesmos termos da satisfação. Nunca
# cita o valor do orçamento de ninguém: ele é confidencial. Frases completas e
# sem supor gênero: falam do destino, do ritmo e do orçamento, não da pessoa.
#
# - Ganho: preferência declarada com valor a partir de GAIN_THRESHOLD.
# - Concessão: preferência declarada abaixo do neutro. O que a pessoa não
#   mencionou não aparece.
#
# Exemplos:
#   "Ganhou o destino que indicou, com praia."
#   "Ganhou o ritmo tranquilo que pediu. Abriu mão do destino que indicou e de um destino de serra."
#   "Abriu mão de 2 dias de viagem. O plano cabe no orçamento com folga."

GAIN_THRESHOLD = 0.75
#: Máximo de itens em "Ganhou …" e em "Abriu mão …".
MAX_ITEMS = 2

PACE_LABEL = {"relaxed": "ritmo tranquilo", "balanced": "ritmo equilibrado", "intense": "ritmo agitado"}
CLIMATE_LABEL = {"hot": "clima quente", "mild": "clima ameno", "cold": "clima frio"}
CLIMATE_SEQUENCE = ("hot", "mild", "cold")

#: Folga no orçamento (valor do termo, de 0,5 a 1) a partir da qual o texto diz "com folga".
BUDGET_COMFORTABLE = 0.875
#: Até aqui o texto diz "no limite".
BUDGET_TIGHT = 0.625

NO_PREFERENCES_TEXT = "Não indicou preferências."
PARTIAL_TEXT = "O plano atende em parte ao que pediu."

#: Lugar reservado, na lista de ganhos ou de concessões, para os atributos do destino (tags e clima).
_ATTRIBUTES = object()


def join_pt(items: list[str]) -> str:
    """["a", "b", "c"] → "a, b e c"."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} e {items[-1]}"


def _climates(climates: frozenset[str]) -> list[str]:
    return [CLIMATE_LABEL[c] for c in CLIMATE_SEQUENCE if c in climates]


def _destination_gain(pref: PreferDestination, match: float) -> str:
    if match < DESTINATION_FIRST:
        return "um dos destinos que indicou"
    return "o destino que indicou" if len(pref.destination_ids) == 1 else "o destino que indicou primeiro"


def _destination_concession(pref: PreferDestination) -> str:
    return "do destino que indicou" if len(pref.destination_ids) == 1 else "dos destinos que indicou"


def _place_attributes(items: list, attributes: list[str], phrase: str) -> list[str]:
    """Troca o lugar reservado pela frase dos atributos, ou remove se não houver nenhum."""
    return [
        phrase if item is _ATTRIBUTES else item for item in items if item is not _ATTRIBUTES or attributes
    ]


def _budget_sentence(item: Component) -> str:
    if item.match >= BUDGET_COMFORTABLE:
        return "O plano cabe no orçamento com folga."
    if item.match <= BUDGET_TIGHT:
        return "O plano cabe no orçamento, mas no limite."
    return "O plano cabe no orçamento, com pouca folga."


def explain(member: Member, scores: Breakdown, nights_lost: int, destination_climate: str) -> str:
    """Texto de uma pessoa; `nights_lost` é quantas noites o candidato tem a menos que o roteiro padrão."""
    prefs: dict[str, SoftConstraint] = {pref.id: pref for pref in member.soft}
    declared = sorted(
        (item for item in scores.components if item.kind != "budget"),
        key=lambda item: (-item.weight, item.source_id),
    )

    gains: list = []
    concessions: list = [f"de {nights_lost} dias de viagem"] if nights_lost > 0 else []
    gained_attributes: list[str] = []
    lost_attributes: list[str] = []
    destination_gain: str | None = None

    for item in declared:
        pref = prefs[item.source_id]
        if item.match >= GAIN_THRESHOLD:
            match pref:
                case PreferDestination():
                    destination_gain = _destination_gain(pref, item.match)
                    gains.append(destination_gain)
                case PreferPace(pace=pace):
                    gains.append(f"o {PACE_LABEL[pace]} que pediu")
                case _:
                    if _ATTRIBUTES not in gains:
                        gains.append(_ATTRIBUTES)
                    gained_attributes += item.matched_tags or [CLIMATE_LABEL[destination_climate]]
        elif item.match < NEUTRAL:
            match pref:
                case PreferDestination():
                    concessions.append(_destination_concession(pref))
                case PreferPace(pace=pace):
                    concessions.append(f"do {PACE_LABEL[pace]} que pediu")
                case PreferClimate(climates=climates):
                    if _ATTRIBUTES not in concessions:
                        concessions.append(_ATTRIBUTES)
                    lost_attributes += _climates(climates)
                case _:
                    if _ATTRIBUTES not in concessions:
                        concessions.append(_ATTRIBUTES)
                    lost_attributes += item.missing_tags

    # Com o destino indicado, os atributos viram complemento dele ("o destino
    # que indicou, com praia"), para não parecer que são dois destinos.
    if destination_gain and gained_attributes:
        gains = [item for item in gains if item is not _ATTRIBUTES]
        gains[gains.index(destination_gain)] = f"{destination_gain}, com {join_pt(gained_attributes)}"
    else:
        gains = _place_attributes(gains, gained_attributes, f"um destino de {join_pt(gained_attributes)}")
    concessions = _place_attributes(
        concessions, lost_attributes, f"de um destino de {join_pt(lost_attributes)}"
    )

    sentences: list[str] = []
    if gains:
        sentences.append(f"Ganhou {join_pt(gains[:MAX_ITEMS])}.")
    if concessions:
        sentences.append(f"Abriu mão {join_pt(concessions[:MAX_ITEMS])}.")
    budget = next((item for item in scores.components if item.kind == "budget"), None)
    if budget:
        sentences.append(_budget_sentence(budget))

    if sentences:
        return " ".join(sentences)
    return NO_PREFERENCES_TEXT if not member.soft else PARTIAL_TEXT
