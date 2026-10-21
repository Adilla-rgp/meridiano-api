from engine.scoring import Component

# Justificativa por regras, a partir dos mesmos termos da satisfação. Nunca
# cita o valor do orçamento de ninguém: ele é confidencial.
#
# Rascunho: os textos ainda vão ser revisados com as telas.

GAIN_THRESHOLD = 0.75
CONCESSION_THRESHOLD = 0.25
#: Máximo de itens em "Ganhou …" e em "Abriu mão …".
MAX_ITEMS = 2

PACE_LABEL = {"relaxed": "ritmo tranquilo", "balanced": "ritmo equilibrado", "intense": "ritmo agitado"}
CLIMATE_LABEL = {"hot": "clima quente", "mild": "clima ameno", "cold": "clima frio"}

FALLBACK_TEXT = "Dentro de todos os seus limites."


def join_pt(items: list[str]) -> str:
    """["a", "b", "c"] → "a, b e c"."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} e {items[-1]}"


def _gain(item: Component, labels: dict[str, str]) -> str | None:
    match item.kind:
        case "destination":
            return "o destino preferido"
        case "tags":
            return join_pt(list(item.matched_tags))
        case "climate" | "pace":
            return labels.get(item.source_id)
    return None


def _concession(item: Component, labels: dict[str, str]) -> str | None:
    match item.kind:
        case "destination":
            return "do destino preferido"
        case "tags":
            return f"de {join_pt(list(item.missing_tags))}"
        case "climate" | "pace":
            label = labels.get(item.source_id)
            return f"de {label}" if label else None
    return None


def _budget_sentence(item: Component) -> str:
    if item.match >= GAIN_THRESHOLD:
        return "Sobra folga no orçamento."
    if item.match <= CONCESSION_THRESHOLD:
        return "Dentro do orçamento, mas no limite."
    return "Dentro do orçamento, com pouca folga."


def explain(items: list[Component], labels: dict[str, str], nights_lost: int) -> str:
    """
    Monta o texto de uma pessoa. `labels` dá o rótulo das preferências de clima e
    ritmo pelo id (por exemplo, "ritmo tranquilo"); `nights_lost` é quantas
    noites o candidato tem a menos que o roteiro padrão.
    """
    declared = sorted(
        (item for item in items if item.kind not in ("budget", "duration")),
        key=lambda item: (-item.weight, item.source_id),
    )

    gains = [text for item in declared if item.match >= GAIN_THRESHOLD and (text := _gain(item, labels))]
    gains = gains[:MAX_ITEMS]

    concessions = [f"de {nights_lost} dias de viagem"] if nights_lost > 0 else []
    concessions += [
        text
        for item in declared
        if item.match <= CONCESSION_THRESHOLD and (text := _concession(item, labels))
    ]
    concessions = concessions[:MAX_ITEMS]

    sentences: list[str] = []
    if gains:
        sentences.append(f"Ganhou {join_pt(gains)}.")
    if concessions:
        sentences.append(f"Abriu mão {join_pt(concessions)}.")
    budget = next((item for item in items if item.kind == "budget"), None)
    if budget:
        sentences.append(_budget_sentence(budget))

    return " ".join(sentences) or FALLBACK_TEXT
