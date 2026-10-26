from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol

from app.schemas import ConstraintsInput
from engine.models import Destination

if TYPE_CHECKING:
    from app.settings import Settings

# Interpretação do texto livre do convidado (POST /invite/{token}/constraints/parse).
# A rota só conhece esta interface: CONSTRAINT_PARSER escolhe entre as regras
# (rules.py) e o LLM (llm.py), devolvidos por get_parser(). A interpretação nunca é salva sem a
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


PARSERS = ("rules", "llm")
PROVIDERS = ("gemini",)


def get_parser(name: str, settings: "Settings | None" = None, fallback: bool = True) -> ConstraintParser:
    """
    O parser pelo nome. "llm" usa o provedor de settings e, com fallback, cai
    nas regras quando o modelo falha.
    """
    from app.parsing.rules import RuleBasedParser

    if name == "rules":
        return RuleBasedParser()
    if name != "llm":
        raise ValueError(f"CONSTRAINT_PARSER desconhecido: {name}. Opções: {', '.join(PARSERS)}.")
    if settings is None:
        raise ValueError("CONSTRAINT_PARSER=llm precisa das configurações do provedor.")

    from app.parsing.llm import LLMParser

    return LLMParser(_llm_client(settings), RuleBasedParser() if fallback else None)


def _llm_client(settings: "Settings"):
    if settings.llm_provider not in PROVIDERS:
        raise ValueError(
            f"LLM_PROVIDER desconhecido: {settings.llm_provider}. Opções: {', '.join(PROVIDERS)}."
        )
    if not settings.gemini_api_key:
        raise ValueError("CONSTRAINT_PARSER=llm com o Gemini precisa de GEMINI_API_KEY.")
    return _gemini_client(settings.gemini_api_key, settings.llm_model, settings.llm_timeout_seconds)


@lru_cache
def _gemini_client(api_key: str, model: str, timeout_seconds: float):
    from app.parsing.gemini import GeminiClient

    return GeminiClient(api_key, model, timeout_seconds)
