from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Configuração por variáveis de ambiente (ou um arquivo .env na raiz). Os
# valores padrão servem para rodar localmente com o docker compose.


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://planner:planner@localhost:5433/planner"
    #: Endereço do front, para montar o link de administração devolvido ao criar a viagem.
    front_base_url: str = "http://localhost:5173"
    #: Origens do front aceitas pelo CORS, separadas por vírgula: a local e a de produção.
    cors_origins: str = "http://localhost:5173"
    #: Interpretação do texto livre: "rules" (por regras) ou "llm" (com retorno às regras se falhar).
    constraint_parser: str = "rules"
    #: Provedor do LLM. Por enquanto só "gemini".
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-flash"
    #: Tempo máximo de uma interpretação pelo LLM, em segundos; passou disso, valem as regras.
    llm_timeout_seconds: float = 5
    gemini_api_key: str = ""
    #: Por minuto e por convite, na interpretação do texto livre (parse e motivo da recusa). 0 desliga.
    parse_rate_limit: int = 20
    #: Requisições por minuto, por token de administração, na geração de planos. 0 desliga.
    plans_rate_limit: int = 10

    @property
    def cors_origin_list(self) -> list[str]:
        # O navegador manda a origem sem barra final; "https://site.app/" nunca casaria.
        return [origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
