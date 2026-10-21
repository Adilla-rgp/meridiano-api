# planner-api

API e motor de decisão do planejador de viagens em grupo. O front-end fica no repositório `planner-vite`, que também guarda a especificação (`docs/especificacao.md`).

Por enquanto este repositório só tem o motor (`engine/`): funções puras em Python, sem banco nem rede. A API em FastAPI vai converter os modelos dela para os de `engine/models.py` e chamar `engine.run()`.

## Motor

1. **Candidatos:** destino × variante (roteiro padrão e roteiro curto) × dia de ida dentro da janela (`engine/candidates.py`).
2. **Filtro:** descarta os candidatos que ferem algum limite. Se nada sobrar, devolve `plans` vazio e os limites que bloqueiam (`blocking_limits`).
3. **Satisfação** de cada pessoa e **score** do plano pelo critério de equilíbrio (`engine/scoring.py`).
4. **Justificativas** por regras, sem falar de orçamento (`engine/explain.py`).
5. **Privacidade:** orçamento sem identificar ninguém nas saídas do grupo; cada pessoa vê os próprios limites (`engine/privacy.py`).

As regras, os pesos e as limitações estão em `docs/motor.md`.

## Desenvolvimento

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # no Linux ou macOS: .venv/bin/python
.venv/Scripts/python -m pytest
.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .
```

Os testes usam a "Viagem de julho", o mesmo grupo dos dados de exemplo do front.

Para atualizar os dados de exemplo do front depois de mudar o motor:

```sh
.venv/Scripts/python -m scripts.export_fixture
cp fixtures/july-trip.json ../planner-vite/src/mocks/fixtures/
```
