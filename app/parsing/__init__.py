from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.schemas import ConstraintsInput
from engine.models import Destination

# Interpretação do texto livre do convidado (POST /invite/{token}/constraints/parse).
# A rota só conhece esta interface: trocar as regras por um LLM é trocar a
# implementação devolvida por get_parser(). A interpretação nunca é salva sem a
# confirmação da pessoa, e o motor nunca recebe texto livre.


@dataclass(frozen=True)
class ParseContext:
    window_start: date
    window_end: date
    nights: int
    #: Os destinos desta viagem, os únicos que a interpretação pode citar.
    destinations: tuple[Destination, ...]


class ConstraintParser(Protocol):
    def parse(self, raw_text: str, context: ParseContext) -> ConstraintsInput:
        """
        Limites e preferências estruturados, cada um com id único e resumo
        pronto para exibição. Devolve listas vazias quando não entende nada.
        """
        ...


def get_parser(name: str) -> ConstraintParser:
    from app.parsing.rules import RuleBasedParser

    parsers: dict[str, type[ConstraintParser]] = {"rules": RuleBasedParser}
    if name not in parsers:
        raise ValueError(f"CONSTRAINT_PARSER desconhecido: {name}. Opções: {', '.join(parsers)}.")
    return parsers[name]()
