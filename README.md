# planner-api

[![CI](https://github.com/Adilla-rgp/meridiano-api/actions/workflows/ci.yml/badge.svg)](https://github.com/Adilla-rgp/meridiano-api/actions/workflows/ci.yml)

API e motor de decisão de um planejador de viagens em grupo. Cada pessoa informa, em particular, o que não abre mão (datas, orçamento, clima, destinos ou tipos de lugar vetados) e o que prefere. O motor calcula o plano mais justo para o grupo e explica, com regras, quem cedeu o quê. O orçamento de cada pessoa nunca é mostrado ao grupo.

Front-end (React + TypeScript): [Adilla-rgp/meridiano](https://github.com/Adilla-rgp/meridiano). Ele também guarda a especificação do produto (`docs/especificacao.md`) e o contrato da API (`src/types/api.ts`). Sem API configurada, o front roda com dados de exemplo gerados por este motor.

Projeto de portfólio. Stack: Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 16, pytest com testcontainers, ruff e GitHub Actions.

## Arquitetura: motor puro × aplicação

```
engine/   Python puro e determinístico: sem banco, sem rede, sem LLM, sem I/O.
          Toda regra de negócio: candidatos, filtros, satisfação, score,
          justificativas, privacidade, mapa de tensões e rodadas.
app/      FastAPI: valida o formato, autentica, converte para os modelos do
          motor, chama o motor e grava no PostgreSQL. Não decide nada.
```

| Pasta | O que tem |
| --- | --- |
| `engine/` | O motor. Recebe uma viagem e devolve planos, justificativas e tensões. |
| `app/` | Rotas, autenticação por token, persistência e `app/parsing/` (interpretação do texto livre). |
| `migrations/` | Migrações do banco (Alembic). |
| `app/seed/` | Catálogo de destinos e a Viagem de julho de demonstração. |
| `tests/` | Testes do motor e, em `tests/api/`, testes da API contra PostgreSQL. |
| `evals/` | Casos e avaliação dos parsers de texto livre. |
| `scripts/` | Exportação dos dados de exemplo do front e análise de satisfação. |

A separação permite testar o motor como funções comuns, sem banco nem servidor, e garante que nenhuma regra fique escondida numa rota. Os dados de exemplo do front (`fixtures/`) saem do próprio motor, e um teste falha se ficarem diferentes da saída atual.

## Regras do motor

1. **Candidatos:** destino × variante (roteiro com as noites fixadas por quem organiza e um roteiro curto, com 2 noites a menos) × dia de ida dentro da janela. Custo por pessoa: `fixed_cost + noites × nightly_cost`.
2. **Filtro:** um candidato que fere qualquer limite de alguém (datas, orçamento, clima vetado, destino vetado, tag vetada) é descartado. Se nada sobra, a rodada devolve os limites que bloqueiam, do que mais elimina para o que menos.
3. **Satisfação** de cada pessoa `i` no plano `p`, só com as preferências que ela declarou:

   ```
   s_i(p) = (Σ w_k · m_k / Σ w_k) · fator de duração
   ```

   `w_k` é o peso da preferência e `m_k`, quanto o plano a atende, de 0 a 1 (destino preferido, tags, clima, ritmo e folga no orçamento). O que a pessoa não mencionou é neutro e nunca aparece como concessão. O roteiro curto reduz a satisfação de todos pelo fator de duração.

4. **Score** pelo critério de equilíbrio, com α escolhido por quem organiza (padrão 0,5):

   ```
   score(p) = (1 − α) · média(s_i(p)) + α · min(s_i(p))
   ```

   Com α = 0, vale só a média (o melhor para a maioria); com α = 1, vale só quem sai pior. No empate, vem o roteiro padrão, depois o menor custo e depois o id do destino. O motor devolve até 3 alternativas, e a primeira é a recomendada.

5. **Justificativas** geradas por regras, com a satisfação de cada pessoa ao lado da melhor que ela teria em algum plano viável (`best_possible`): é isso que mostra quem cedeu e quanto.
6. **Rodadas:** quem recusa um plano diz o motivo; o motivo vira restrição só depois de a pessoa confirmar e entra na próxima rodada. A viagem fecha quando todos que responderam aceitam o plano recomendado.

Os pesos, as tabelas de `m_k`, o mapa de tensões e as limitações conhecidas estão em [`docs/motor.md`](docs/motor.md).

## Garantias testadas

| Garantia | Teste |
| --- | --- |
| **Determinismo:** a mesma viagem, com participantes e destinos embaralhados, dá exatamente o mesmo resultado. | `tests/test_engine.py::test_is_deterministic_regardless_of_input_order` |
| **Nenhum limite violado:** todo plano devolvido respeita todos os limites de todos. | `tests/test_engine.py::test_returned_plans_never_violate_limits` |
| **Privacidade do orçamento no motor:** as justificativas não falam de orçamento; nas saídas do grupo, um limite de orçamento não tem dono; o mapa de tensões nunca liga duas pessoas pelo orçamento nem o conta para destacar quem tem mais limites. | `tests/test_engine.py`, `tests/test_tensions.py` |
| **Privacidade do orçamento na API:** em quatro cenários (orçamento folgado, que elimina um destino, somado a outro limite e que inviabiliza tudo), o teste percorre todas as rotas como organizador e como cada convidado, grava todas as respostas e procura o valor do orçamento ou quem tem esse limite em toda resposta que não seja da própria pessoa. Como controle, confere que a busca encontra o valor nas respostas dela. | `tests/api/test_privacy.py` |
| **Tokens seguros:** os tokens de administração e de convite têm 256 bits aleatórios e só existem no banco como hash. | `tests/api/test_auth.py` |

O CI roda `ruff check`, `ruff format --check` e `pytest` (com um PostgreSQL 16 de verdade) em todo push e pull request.

## Interpretação do texto livre

A pessoa pode escrever do jeito dela ("só posso de 10 a 20 de julho, no máximo R$ 1.100 tudo incluso, não curto frio"). Um `ConstraintParser` (`app/parsing/`) transforma o texto num rascunho de limites e preferências, que a pessoa revisa e confirma antes de salvar. O motor nunca recebe texto livre.

- `rules` (padrão): regras simples, sem IA.
- `llm`: um LLM extrai os campos num JSON de formato fixo; o código valida tudo, descarta o que não é da viagem, aplica os pesos e gera os resumos pelo motor. O LLM não escolhe plano, não pontua e não escreve justificativa. Qualquer falha cai nas regras.

`GET /trips/{id}` e `GET /invite/{token}` informam em `constraint_parser` qual dos dois está configurado. Com `llm`, o front avisa que o texto passa por um serviço de IA externo.

Os parsers são medidos em `evals/` com um conjunto de desenvolvimento (49 casos) e um de teste (20 casos, nunca usado em ajuste), em sete categorias: apelidos de destino, dinheiro, negação, datas, texto vazio, tentativa de injeção de instruções e textos mistos.

Linha de base do `rules`:

| Campo | Desenvolvimento | Teste |
| --- | --- | --- |
| destinos | 84% | 80% |
| datas | 84% | 90% |
| orçamento | 88% | 90% |
| clima | 96% | 100% |
| ritmo | 96% | 95% |
| tags | 98% | 95% |
| **casos inteiramente certos** | **25/49** | **10/20** |

A avaliação do `llm` está pronta (`python -m evals.run --parser llm`), mas não foi executada: o projeto não usa chave de um provedor de LLM, então não há números dele e o padrão continua `CONSTRAINT_PARSER=rules`. Os resultados por categoria e o método de comparação estão em [`docs/motor.md`](docs/motor.md#interpretação-do-texto-livre).

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

Para usar com o front, rode-o com `VITE_API_URL=http://localhost:8000`. Para liberar outra origem do front, defina `CORS_ORIGINS` antes de subir: `CORS_ORIGINS=http://localhost:5173,https://seu-front.vercel.app docker compose up`.

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
.venv/Scripts/python -m evals.run --parser rules
```

Os testes de `tests/api/` sobem um PostgreSQL 16 num container (testcontainers) e aplicam as migrações e o catálogo. Precisam do Docker rodando; sem ele, são pulados com aviso. Para usar um banco já existente, defina `TEST_DATABASE_URL` (as viagens dele são apagadas a cada teste); é assim que o CI roda.

Ao mudar `app/models.py`, gere a migração com um banco no ar:

```sh
.venv/Scripts/alembic revision --autogenerate -m "describe the change"
.venv/Scripts/alembic check
```

Para atualizar os dados de exemplo do front depois de mudar o motor:

```sh
.venv/Scripts/python -m scripts.export_fixture --out ../planner-vite/src/mocks/fixtures/july-trip.json
```

## Referência da API

### Autenticação

Sem login por e-mail por enquanto.

- `POST /trips` cria a viagem e quem organiza (o primeiro participante) e devolve, uma única vez, o `admin_token`, o `admin_url` e o `invite_token` de quem organiza.
- Rotas do organizador exigem o cabeçalho `X-Admin-Token`.
- Convidados usam o `invite_token`: no caminho de `/invite/{token}`, no corpo de `POST /plans/{id}/reactions` e no cabeçalho `X-Invite-Token` de `GET /trips/{id}/plans`.
- O banco guarda só o SHA-256 dos tokens. Para reenviar um link perdido, `POST /trips/{id}/members/{member_id}/invite` gera um novo e invalida o anterior.
- O `admin_url` leva o token no fragmento (`#admin=…`), que o navegador não envia a servidores.

### Rotas

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
| POST | /plans/{id}/reactions/constraints | convidado que recusou |

Os formatos seguem `src/types/api.ts` do front. Erros de regra vêm como `{"detail": "mensagem em português"}`; erros de formato, no padrão do FastAPI (`detail` com a lista de campos).

### Rodadas, recusas e acordo

- **Reagir:** só ao plano da rodada mais recente; um plano de rodada anterior responde 409.
- **Recusa vira restrição:** a resposta de uma recusa traz `constraint_draft`, o motivo interpretado pelo `ConstraintParser`. Nada é salvo até a pessoa confirmar em `POST /plans/{id}/reactions/constraints`, com `invite_token`, `hard` e `soft` (pode tirar itens do rascunho). A confirmação grava uma nova versão das restrições, que entra na próxima rodada: limites novos se somam aos anteriores e uma preferência nova substitui a do mesmo tipo. Cada recusa é confirmada uma vez.
- **Acordo:** a viagem passa a `agreed` quando todos que responderam aceitaram o plano recomendado da rodada mais recente e ninguém o recusou. Depois disso, respostas, reações e novas rodadas respondem 409.

### Limite de requisições

A interpretação do texto livre e a geração de planos têm um limite por token, numa janela de 60 segundos: `PARSE_RATE_LIMIT` (padrão 20, por convite) e `PLANS_RATE_LIMIT` (padrão 10, por token de administração). Passou do limite, a API responde 429 com `Retry-After`. O contador fica na memória do processo; com mais de um processo, troque por um compartilhado.
