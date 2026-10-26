# CLAUDE.md

Contexto permanente para agentes de código neste repositório.

## O projeto

API e motor de decisão de um planejador de viagens em grupo. Cada participante informa limites e preferências; o motor calcula o plano mais justo e explica quem cedeu o quê. O front fica em outro repositório (meridiano).

- Regras do motor: `docs/motor.md`. Leia antes de mexer em `engine/`.
- Contrato da API: o formato de referência é `src/types/api.ts` do meridiano. Mudou o contrato aqui, registre a mudança no resumo final para o front acompanhar.

## Arquitetura

- `engine/`: Python puro e determinístico. Sem banco, sem web, sem LLM, sem I/O. Toda regra de negócio mora aqui (score, filtros, justificativas, tensões, resumos de restrições).
- `app/`: FastAPI. Só valida, converte, autentica, chama o motor e grava. Nenhuma regra de negócio.
- Interpretação de texto livre: atrás da interface `ConstraintParser`. A saída sempre é validada antes de chegar ao motor, e nunca é salva sem confirmação de quem respondeu.
- `fixtures/july-trip.json` é gerado pelo motor (`scripts/export_fixture.py`) e consumido pelos mocks do front. Mudou o motor, gere de novo; o teste de consistência acusa divergência.

## Regras invioláveis

- O LLM nunca decide: não escolhe plano, não pontua, não escreve justificativa com números.
- Privacidade do orçamento: nenhuma resposta que não seja da própria pessoa contém o valor do orçamento nem identifica de quem é um limite de orçamento. Isso vale para justificativas, tensões, destinos excluídos, limites bloqueantes e destaques. O teste de privacidade da API precisa continuar passando.
- Tokens (admin e convite) são aleatórios de 256 bits e só existem no banco como hash.
- O mesmo conjunto de entradas produz sempre a mesma saída, em qualquer ordem.

## Stack

Python 3.12, FastAPI, Pydantic 2, pydantic-settings, SQLAlchemy 2, Alembic, PostgreSQL 16, pytest com testcontainers, ruff. Ambiente local com docker compose.

## Qualidade

Antes de concluir qualquer tarefa: `ruff check`, `ruff format --check` e `pytest`, sem falhas. Mudança de modelo exige migração do Alembic conferida com `alembic check`.

## Textos

Textos que chegam à interface (justificativas, resumos, mensagens de erro) em português do Brasil, frases completas e sem supor gênero ("quem organiza", não "a organizadora"). Código, nomes e commits em inglês.

## Git

- Trabalhe em branch, nunca direto na `main`.
- Commits pequenos, Conventional Commits, em inglês.
- Mensagens de commit e de PR sem linhas de coautoria e sem referência a ferramentas de IA.
