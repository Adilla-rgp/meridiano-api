# planner-api

API e motor de decisão do planejador de viagens em grupo. O front-end fica no repositório `planner-vite`, que também guarda a especificação (`docs/especificacao.md`) e o contrato da API (`src/types/api.ts`).

## Estrutura

| Pasta | O que tem |
| --- | --- |
| `engine/` | Motor: funções puras em Python, sem banco nem rede. Toda regra de negócio fica aqui. |
| `app/` | API em FastAPI. Valida o formato, converte para os modelos do motor, chama o motor e grava. Não decide nada. |
| `migrations/` | Migrações do banco (Alembic). |
| `app/seed/` | Catálogo de destinos e a Viagem de julho de demonstração. |
| `tests/` | Testes do motor e, em `tests/api/`, testes da API contra PostgreSQL. |
| `scripts/` | Exportação do fixture do front e análise de satisfação. |

## Rodar com docker compose

```sh
docker compose up --build
```

Sobe o PostgreSQL (porta 5433 no computador) e a API em http://localhost:8000, com a documentação interativa em http://localhost:8000/docs. Ao iniciar, a API aplica as migrações e cria ou atualiza o catálogo.

Para criar a Viagem de julho de demonstração e ver os links:

```sh
docker compose exec api python -m app.cli create-demo-trip
```

O comando mostra o token de administração, o link de administração e o link de convite de cada pessoa. Os tokens só aparecem nessa hora: o banco guarda apenas o hash.

## Desenvolvimento

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # no Linux ou macOS: .venv/bin/python
cp .env.example .env
docker compose up -d db                            # só o banco
.venv/Scripts/alembic upgrade head
.venv/Scripts/python -m app.cli seed-catalog
.venv/Scripts/uvicorn app.main:create_app --factory --reload
```

A configuração vem de variáveis de ambiente ou do `.env` (veja `.env.example`): `DATABASE_URL`, `FRONT_BASE_URL`, `CORS_ORIGINS` e `CONSTRAINT_PARSER`.

### Testes e verificação

```sh
.venv/Scripts/python -m pytest
.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .
```

Os testes de `tests/api/` sobem um PostgreSQL 16 num container (testcontainers) e aplicam as migrações e o catálogo. Precisam do Docker rodando; sem ele, são pulados com aviso. Para usar um banco já existente, defina `TEST_DATABASE_URL` (as viagens dele são apagadas a cada teste).

Ao mudar `app/models.py`, gere a migração com um banco no ar:

```sh
.venv/Scripts/alembic revision --autogenerate -m "describe the change"
.venv/Scripts/alembic check
```

## Autenticação do MVP

Sem login por e-mail por enquanto (`POST /auth/magic-link` não existe).

- `POST /trips` cria a viagem e quem organiza (o primeiro participante) e devolve, uma única vez, o `admin_token`, o `admin_url` e o `invite_token` de quem organiza.
- Rotas do organizador exigem o cabeçalho `X-Admin-Token`.
- Convidados usam o `invite_token`: no caminho de `/invite/{token}`, no corpo de `POST /plans/{id}/reactions` e no cabeçalho `X-Invite-Token` de `GET /trips/{id}/plans`.
- Os tokens têm 256 bits aleatórios e o banco guarda só o SHA-256. Por isso o token de convite só é devolvido ao criar o convite. Para reenviar um link perdido, `POST /trips/{id}/members/{member_id}/invite` gera um novo e invalida o anterior.
- O `admin_url` leva o token no fragmento (`#admin=…`), que o navegador não envia a servidores.

## Rotas

| Método | Rota | Quem |
| --- | --- | --- |
| GET | /destinations | todos |
| POST | /trips | organizador (cria e recebe os tokens) |
| GET | /trips/{id} | organizador |
| POST | /trips/{id}/members | organizador |
| POST | /trips/{id}/members/{member_id}/invite | organizador |
| GET | /trips/{id}/tensions | organizador |
| POST | /trips/{id}/plans | organizador (roda o motor de forma síncrona) |
| GET | /trips/{id}/plans?round=n | organizador ou convidado |
| GET | /invite/{token} | convidado |
| POST | /invite/{token}/constraints/parse | convidado |
| PUT | /invite/{token}/constraints | convidado |
| POST | /plans/{id}/reactions | convidado |

Os formatos seguem `planner-vite/src/types/api.ts`. Erros de regra vêm como `{"detail": "mensagem em português"}`; erros de formato, no padrão do FastAPI (`detail` com a lista de campos).

## Interpretação do texto livre

`POST /invite/{token}/constraints/parse` usa um `ConstraintParser` (`app/parsing/`). Hoje a implementação é por regras simples (`rules.py`): datas, orçamento, clima, ritmo, destinos da viagem e tags. A implementação com LLM entra como outra classe com o mesmo método `parse`, escolhida por `CONSTRAINT_PARSER`. Nada é salvo sem a confirmação da pessoa, e o motor nunca recebe texto livre.

## Privacidade do orçamento

As respostas para o grupo passam pelas regras do motor (`engine/privacy.py` e `engine/tensions.py`): o orçamento aparece sem participante e sem valor, as justificativas não falam dele e ele não conta para destacar quem tem mais limites. Cada pessoa vê os próprios limites em `GET /invite/{token}` e no parse. `tests/api/test_privacy.py` percorre todas as rotas, como organizador e como cada convidado, e procura o valor ou o dono do orçamento em toda resposta que não é da própria pessoa.

## Motor

1. **Candidatos:** destino × variante (roteiro padrão e roteiro curto) × dia de ida dentro da janela (`engine/candidates.py`).
2. **Filtro:** descarta os candidatos que ferem algum limite. Se nada sobrar, devolve `plans` vazio e os limites que bloqueiam (`blocking_limits`).
3. **Satisfação** de cada pessoa e **score** do plano pelo critério de equilíbrio (`engine/scoring.py`).
4. **Justificativas** por regras, sem falar de orçamento (`engine/explain.py`).
5. **Privacidade:** orçamento sem identificar ninguém nas saídas do grupo; cada pessoa vê os próprios limites (`engine/privacy.py`).
6. **Mapa de tensões** e **resumos das restrições** (`engine/tensions.py` e `engine/summaries.py`).

As regras, os pesos e as limitações estão em `docs/motor.md`. Os testes do motor usam a "Viagem de julho", o mesmo grupo dos dados de exemplo do front.

Para atualizar os dados de exemplo do front depois de mudar o motor:

```sh
.venv/Scripts/python -m scripts.export_fixture
cp fixtures/july-trip.json ../planner-vite/src/mocks/fixtures/
```
