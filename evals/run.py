"""
Avaliação de um ConstraintParser nos casos de evals/*.jsonl.

    python -m evals.run --parser rules
    python -m evals.run --parser llm --cases evals/parse_cases_test.jsonl

Para cada caso e campo (destinos, datas, orçamento, clima, ritmo, tags), o
campo está certo quando o parser gera exatamente o esperado, ignorando id,
resumo, peso e a ordem das listas. Um item em "optional" não conta como erro se
faltar nem como invenção se aparecer. Falso positivo é cada item gerado que não
está no esperado nem no opcional: um orçamento ou uma data com valor errado
também é restrição inventada.

Imprime as tabelas em Markdown e, com --out, grava o resultado em JSON.
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app.parsing import ConstraintParser, ParseContext, get_parser
from app.seed.catalog import CATALOG
from app.seed.july_trip import TRIP
from app.settings import get_settings
from engine.models import Destination

FIELDS = ("destinations", "dates", "budget", "climate", "pace", "tags")
FIELD_LABEL = {
    "destinations": "destinos",
    "dates": "datas",
    "budget": "orçamento",
    "climate": "clima",
    "pace": "ritmo",
    "tags": "tags",
}
CATEGORIES = ("apelido", "dinheiro", "negacao", "data", "vazio", "injecao", "misto")
CATEGORY_LABEL = {"negacao": "negação", "injecao": "injeção"}
DEFAULT_CASES = Path(__file__).parent / "parse_cases.jsonl"

#: Átomo comparável de uma restrição: (campo, valor). O orçamento é comparado à parte.
Atom = tuple[str, tuple]


def july_context() -> ParseContext:
    """A Viagem de julho da demonstração: os mesmos destinos e janela dos casos."""
    by_id = {item["id"]: item for item in CATALOG}
    return ParseContext(
        window_start=TRIP["date_window_start"],
        window_end=TRIP["date_window_end"],
        nights=TRIP["nights"],
        destinations=tuple(
            Destination(
                id=row["id"],
                name=row["name"],
                climate=row["climate"],
                pace=row["pace"],
                tags=tuple(row["tags"]),
                fixed_cost=row["fixed_cost"],
                nightly_cost=row["nightly_cost"],
            )
            for row in (by_id[i] for i in TRIP["destination_ids"])
        ),
    )


def atoms(item: dict) -> list[Atom]:
    """Os átomos de um item, fora o orçamento."""
    match item["kind"]:
        case "exclude_destination":
            return [("destinations", ("exclude", i)) for i in item["destination_ids"]]
        case "prefer_destination":
            return [("destinations", ("prefer", i)) for i in item["destination_ids"]]
        case "date_range":
            return [("dates", (str(item["start"]), str(item["end"])))]
        case "exclude_climate":
            return [("climate", ("exclude", c)) for c in item["climates"]]
        case "prefer_climate":
            return [("climate", ("prefer", c)) for c in item["climates"]]
        case "pace":
            return [("pace", (item["pace"],))]
        case "exclude_tags":
            return [("tags", ("exclude", t)) for t in item["tags"]]
        case "prefer_tags":
            return [("tags", ("prefer", t)) for t in item["tags"]]
    raise ValueError(f"Tipo desconhecido: {item['kind']}")


def budget_matches(spec: dict, item: dict) -> bool:
    """Orçamento esperado como faixa [mín, máx] aceita qualquer valor dentro dela."""
    expected = spec["max_per_person"]
    low, high = expected if isinstance(expected, list) else (expected, expected)
    if not low <= item["max_per_person"] <= high:
        return False
    return spec.get("all_inclusive") is None or spec["all_inclusive"] == item["all_inclusive"]


@dataclass
class CaseResult:
    id: str
    category: str
    correct: dict[str, bool]
    false_positives: list[str]
    error: str | None = None

    @property
    def all_correct(self) -> bool:
        return all(self.correct.values())


def score_case(case: dict, predicted: list[dict]) -> tuple[dict[str, bool], list[str]]:
    """Acerto por campo e itens inventados de um caso."""
    expected = case["hard"] + case["soft"]
    optional = case.get("optional", [])

    def split(items: list[dict]) -> tuple[set[Atom], list[dict]]:
        found = {atom for item in items if item["kind"] != "budget" for atom in atoms(item)}
        return found, [item for item in items if item["kind"] == "budget"]

    expected_atoms, expected_budgets = split(expected)
    optional_atoms, optional_budgets = split(optional)
    predicted_atoms, predicted_budgets = split(predicted)

    correct = {
        name: {a for a in predicted_atoms - optional_atoms if a[0] == name}
        == {a for a in expected_atoms - optional_atoms if a[0] == name}
        for name in FIELDS
        if name != "budget"
    }
    invented = [
        f"{name}: {value}" for name, value in sorted(predicted_atoms - expected_atoms - optional_atoms)
    ]

    unmatched = list(expected_budgets)
    extra_budgets = 0
    for item in predicted_budgets:
        match = next((spec for spec in unmatched if budget_matches(spec, item)), None)
        if match is not None:
            unmatched.remove(match)
        elif not any(budget_matches(spec, item) for spec in optional_budgets):
            extra_budgets += 1
            invented.append(f"budget: {item['max_per_person']}, tudo incluso={item['all_inclusive']}")
    correct["budget"] = not unmatched and not extra_budgets
    return {name: correct[name] for name in FIELDS}, invented


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate(parser: ConstraintParser, cases: list[dict], context: ParseContext) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        error = None
        try:
            output = parser.parse(case["text"], context).model_dump(mode="json")
            predicted = output["hard"] + output["soft"]
        except Exception as exc:  # um parser que quebra num caso não para a avaliação
            error, predicted = f"{type(exc).__name__}: {exc}", []
        correct, invented = score_case(case, predicted)
        results.append(CaseResult(case["id"], case["category"], correct, invented, error))
    return results


@dataclass
class Summary:
    cases: int
    field_accuracy: dict[str, float]
    category_accuracy: dict[str, tuple[int, int]]
    all_correct: int
    false_positives: int
    cases_with_false_positives: int
    errors: int
    details: list[dict] = field(default_factory=list)


def summarize(results: list[CaseResult]) -> Summary:
    by_category: dict[str, list[CaseResult]] = defaultdict(list)
    for item in results:
        by_category[item.category].append(item)
    return Summary(
        cases=len(results),
        field_accuracy={name: sum(item.correct[name] for item in results) / len(results) for name in FIELDS},
        category_accuracy={
            name: (sum(item.all_correct for item in by_category[name]), len(by_category[name]))
            for name in CATEGORIES
            if by_category[name]
        },
        all_correct=sum(item.all_correct for item in results),
        false_positives=sum(len(item.false_positives) for item in results),
        cases_with_false_positives=sum(bool(item.false_positives) for item in results),
        errors=sum(item.error is not None for item in results),
        details=[
            {
                "id": item.id,
                "wrong_fields": [name for name in FIELDS if not item.correct[name]],
                "false_positives": item.false_positives,
                "error": item.error,
            }
            for item in results
            if not item.all_correct or item.false_positives or item.error
        ],
    )


def percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def markdown(summary: Summary) -> str:
    lines = ["| Campo | Acerto |", "| --- | --- |"]
    lines += [f"| {FIELD_LABEL[name]} | {percent(value)} |" for name, value in summary.field_accuracy.items()]
    lines += ["", "| Categoria | Casos certos |", "| --- | --- |"]
    lines += [
        f"| {CATEGORY_LABEL.get(name, name)} | {right}/{total} |"
        for name, (right, total) in summary.category_accuracy.items()
    ]
    lines += [
        "",
        f"Casos inteiramente certos: {summary.all_correct}/{summary.cases}. "
        f"Restrições inventadas: {summary.false_positives}, em {summary.cases_with_false_positives} casos. "
        f"Erros: {summary.errors}.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    args.add_argument("--parser", default="rules", help="nome aceito por get_parser (rules, llm)")
    args.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    args.add_argument("--out", type=Path, help="arquivo JSON para gravar o resultado")
    options = args.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    started = time.perf_counter()
    # Sem retorno às regras: um erro do LLM conta como erro, não como acerto das regras.
    parser = get_parser(options.parser, get_settings(), fallback=False)
    results = evaluate(parser, load_cases(options.cases), july_context())
    summary = summarize(results)
    print(markdown(summary))
    print(
        f"\n{options.parser} em {options.cases.name}: {time.perf_counter() - started:.1f} s", file=sys.stderr
    )
    if options.out:
        options.out.parent.mkdir(parents=True, exist_ok=True)
        payload = {"parser": options.parser, "cases_file": options.cases.name, **summary.__dict__}
        options.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
