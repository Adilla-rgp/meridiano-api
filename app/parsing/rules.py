import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from app import schemas
from app.parsing import ParseContext
from app.parsing.output import to_schema
from engine import models as engine

# Interpretação por regras simples, sem IA: datas ("de 8 a 18 de julho",
# "12/07 a 15/07"), orçamento ("no máximo uns 800 conto", "R$ 1.100"), clima
# ("não curto frio"), ritmo ("tranquilo", "agito"), destinos da viagem pelo
# nome e tags dos destinos da viagem ("quero praia", "não quero praia"). Cobre
# o básico para a demonstração e para os testes; o LLM entra como outra
# implementação de ConstraintParser.
#
# Trabalha sobre o texto em minúsculas e sem acentos.

MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
MONTH = "(" + "|".join(MONTHS) + ")"
DAY = r"(\d{1,2})o?"
RANGE_SEPARATOR = r"\s*(?:a|ate|ao|e|-)\s*"

DATE_RANGE_WRITTEN = re.compile(rf"\b{DAY}(?:\s+de\s+{MONTH})?{RANGE_SEPARATOR}{DAY}\s+de\s+{MONTH}\b")
DATE_RANGE_NUMERIC = re.compile(rf"\b(\d{{1,2}})/(\d{{1,2}}){RANGE_SEPARATOR}(\d{{1,2}})/(\d{{1,2}})\b")

AMOUNT = re.compile(
    r"(?P<currency>r\$\s*)?(?P<number>\d{1,3}(?:\.\d{3})+|\d+)(?:,(?P<cents>\d{1,2}))?"
    r"(?P<thousand>\s*(?:mil|k)\b)?(?P<word>\s*(?:reais|real|contos?|pilas?)\b)?"
)
BUDGET_CUE = re.compile(r"\b(ate|maximo|orcamento|gastar|gasto|teto|limite|budget)\b")
NOT_MONEY_AFTER = re.compile(r"\s*(noites?|dias?|semanas?|pessoas?|horas?)\b")
#: Abaixo disso, um número sem "R$" nem "reais" não é tratado como dinheiro.
MIN_BUDGET = 50
ALL_INCLUSIVE = re.compile(r"\b(tudo inclu\w*|com tudo|incluindo tudo|all inclusive)\b")

NEGATION = re.compile(r"\b(nao|nada de|nada|sem|odeio|detesto|evito|evitar|menos|fora|nunca|jamais)\b")
#: Negação logo depois de um nome: "Chapada não", "Paraty nem pensar".
NEGATION_AFTER = re.compile(r"\s*(nao|nem pensar|jamais|nunca|(?:esta|ta) fora)\b")
LIKING = re.compile(r"\b(prefiro|preferencia|gosto|curto|quero|queria|adoro|amo|adoraria)\b")
INTENSIFIER = re.compile(r"\b(muito|bem|demais|super|por favor|mesmo|total)\b")
#: Fim de oração: uma negação antes dele não vale para o que vem depois.
CLAUSE_BREAK = re.compile(r"[.;!?,\n]|\bmas\b")
#: Quantos caracteres antes de uma menção ainda contam para negação e gosto.
CUE_WINDOW = 30

CLIMATE_WORDS: dict[engine.Climate, re.Pattern[str]] = {
    "cold": re.compile(r"\b(fri[oa]s?|friozinho|gelad[oa]s?)\b"),
    "hot": re.compile(r"\b(calor|calorao|quentes?)\b"),
    "mild": re.compile(r"\b(amenos?|fresquinho|fresco)\b"),
}
PACE_WORDS: dict[engine.Pace, re.Pattern[str]] = {
    "relaxed": re.compile(
        r"\b(tranquil\w*|sossegad\w*|calm[oa]|relax\w*|descans\w*|sem pressa|de boa|parad[oa])\b"
    ),
    "intense": re.compile(
        r"\b(agit\w*|balada\w*|festa\w*|noitada|intens\w*|aventura\w*|adrenalina|corrid[oa])\b"
    ),
    "balanced": re.compile(r"\b(equilibrad\w*|meio termo)\b"),
}
OPPOSITE_PACE: dict[engine.Pace, engine.Pace] = {
    "relaxed": "intense",
    "intense": "relaxed",
    "balanced": "balanced",
}

#: Palavras do nome de um destino que não o identificam sozinhas.
GENERIC_NAME_WORDS = {"praia", "praias", "serra", "ilha", "lagoa", "cidade", "porto", "morro", "parque"}
MIN_ALIAS_LENGTH = 5

DEFAULT_WEIGHT = 0.6
STRONG_WEIGHT = 0.8
DESTINATION_WEIGHT = 0.8


def normalize(text: str) -> str:
    """Minúsculas e sem acentos, com o mesmo comprimento para português ("ç" → "c", "º" → "o")."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


@dataclass
class _Text:
    value: str

    def clause_before(self, start: int) -> str:
        """O trecho da mesma oração antes da posição, até CUE_WINDOW caracteres."""
        window = self.value[max(0, start - CUE_WINDOW) : start]
        breaks = list(CLAUSE_BREAK.finditer(window))
        return window[breaks[-1].end() :] if breaks else window

    def negated(self, start: int) -> bool:
        return bool(NEGATION.search(self.clause_before(start)))

    def negated_after(self, end: int) -> bool:
        return bool(NEGATION_AFTER.match(self.value, end))

    def liked(self, start: int) -> bool:
        return bool(LIKING.search(self.clause_before(start)))

    def blank(self, start: int, end: int) -> None:
        """Apaga um trecho já interpretado, para outra regra não ler de novo."""
        self.value = self.value[:start] + " " * (end - start) + self.value[end:]


class RuleBasedParser:
    def parse(self, raw_text: str, context: ParseContext) -> schemas.ConstraintsInput:
        text = _Text(normalize(raw_text))
        hard: list[engine.HardConstraint] = []
        soft: list[engine.SoftConstraint] = []

        def hard_id() -> str:
            return f"h{len(hard) + 1}"

        def soft_id() -> str:
            return f"s{len(soft) + 1}"

        if found := _date_range(text, context):
            hard.append(engine.DateRange(hard_id(), *found))
        if (budget := _budget(text)) is not None:
            hard.append(engine.Budget(hard_id(), budget, bool(ALL_INCLUSIVE.search(text.value))))

        excluded_climates, preferred_climates = _climates(text)
        if excluded_climates:
            hard.append(engine.ExcludeClimate(hard_id(), frozenset(excluded_climates)))

        excluded_ids, preferred_ids = _destinations(text, context.destinations)
        if excluded_ids:
            hard.append(engine.ExcludeDestination(hard_id(), frozenset(excluded_ids)))
        excluded_tags, preferred_tags = _tags(text, context.destinations)
        if excluded_tags:
            hard.append(engine.ExcludeTags(hard_id(), frozenset(excluded_tags)))
        if preferred_ids:
            soft.append(engine.PreferDestination(soft_id(), tuple(preferred_ids), DESTINATION_WEIGHT))
        if preferred_tags:
            soft.append(engine.PreferTags(soft_id(), tuple(preferred_tags), DEFAULT_WEIGHT))
        if preferred_climates:
            soft.append(engine.PreferClimate(soft_id(), frozenset(preferred_climates), DEFAULT_WEIGHT))
        if pace := _pace(text):
            soft.append(engine.PreferPace(soft_id(), *pace))

        return to_schema(raw_text, hard, soft, context)


def _year(month: int, context: ParseContext) -> int:
    """O ano em que esse mês cai dentro da janela da viagem."""
    if context.window_start.year == context.window_end.year or month >= context.window_start.month:
        return context.window_start.year
    return context.window_end.year


def _make_date(day: str, month: int, context: ParseContext) -> date | None:
    try:
        return date(_year(month, context), month, int(day))
    except ValueError:
        return None


def _date_range(text: _Text, context: ParseContext) -> tuple[date, date] | None:
    for match in DATE_RANGE_WRITTEN.finditer(text.value):
        start_day, start_month, end_day, end_month = match.groups()
        start = _make_date(start_day, MONTHS[start_month or end_month], context)
        end = _make_date(end_day, MONTHS[end_month], context)
        if start and end and start <= end:
            text.blank(*match.span())
            return start, end
    for match in DATE_RANGE_NUMERIC.finditer(text.value):
        start_day, start_month, end_day, end_month = match.groups()
        if not (1 <= int(start_month) <= 12 and 1 <= int(end_month) <= 12):
            continue
        start = _make_date(start_day, int(start_month), context)
        end = _make_date(end_day, int(end_month), context)
        if start and end and start <= end:
            text.blank(*match.span())
            return start, end
    return None


def _budget(text: _Text) -> float | None:
    for match in AMOUNT.finditer(text.value):
        if NOT_MONEY_AFTER.match(text.value, match.end()):
            continue
        value = float(match["number"].replace(".", "")) + (
            float(f"0.{match['cents']}") if match["cents"] else 0
        )
        if match["thousand"]:
            value *= 1000
        explicit = match["currency"] or match["word"] or match["thousand"]
        if explicit or (value >= MIN_BUDGET and BUDGET_CUE.search(text.clause_before(match.start()))):
            text.blank(*match.span())
            return round(value, 2)
    return None


def _climates(text: _Text) -> tuple[list[engine.Climate], list[engine.Climate]]:
    excluded: list[engine.Climate] = []
    preferred: list[engine.Climate] = []
    for climate, pattern in CLIMATE_WORDS.items():
        for match in pattern.finditer(text.value):
            if text.negated(match.start()):
                excluded.append(climate)
            elif text.liked(match.start()):
                preferred.append(climate)
    return sorted(set(excluded)), sorted(set(preferred) - set(excluded))


def _pace(text: _Text) -> tuple[engine.Pace, float] | None:
    mentions = [
        (match.start(), pace)
        for pace, pattern in PACE_WORDS.items()
        for match in pattern.finditer(text.value)
    ]
    if not mentions:
        return None
    start, pace = min(mentions)
    if text.negated(start):
        pace = OPPOSITE_PACE[pace]
    clause = text.clause_before(start) + text.value[start : start + CUE_WINDOW]
    return pace, STRONG_WEIGHT if INTENSIFIER.search(clause) else DEFAULT_WEIGHT


def _aliases(destinations: tuple[engine.Destination, ...]) -> dict[str, str]:
    """Nome completo e cada palavra distintiva do nome, sem acento, para o id do destino."""
    found: dict[str, set[str]] = {}
    for destination in destinations:
        name = normalize(destination.name)
        words = [w for w in name.split() if len(w) >= MIN_ALIAS_LENGTH and w not in GENERIC_NAME_WORDS]
        for alias in {name, *words}:
            found.setdefault(alias, set()).add(destination.id)
    return {alias: ids.pop() for alias, ids in found.items() if len(ids) == 1}


def _destinations(text: _Text, destinations: tuple[engine.Destination, ...]) -> tuple[list[str], list[str]]:
    mentions: list[tuple[int, str, bool]] = []
    for alias, destination_id in _aliases(destinations).items():
        for match in re.finditer(rf"\b{re.escape(alias)}\b", text.value):
            negated = text.negated(match.start()) or text.negated_after(match.end())
            mentions.append((match.start(), destination_id, negated))
    excluded = sorted({destination_id for _, destination_id, negated in mentions if negated})
    preferred: list[str] = []
    for _, destination_id, _ in sorted(mentions):
        if destination_id not in excluded and destination_id not in preferred:
            preferred.append(destination_id)
    return excluded, preferred


def _tags(text: _Text, destinations: tuple[engine.Destination, ...]) -> tuple[list[str], list[str]]:
    """Tags dos destinos da viagem citadas com negação e sem negação, estas na ordem do texto."""
    vocabulary = sorted({tag for destination in destinations for tag in destination.tags})
    excluded: list[str] = []
    mentions: list[tuple[int, str]] = []
    for tag in vocabulary:
        stem = normalize(tag)
        stem = stem[:-1] if stem.endswith("s") and len(stem) > 4 else stem
        match = re.search(rf"\b{re.escape(stem)}s?\b", text.value)
        if not match:
            continue
        if text.negated(match.start()):
            excluded.append(tag)
        else:
            mentions.append((match.start(), tag))
    return excluded, [tag for _, tag in sorted(mentions)]
