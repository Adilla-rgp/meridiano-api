# Motor de plano

Regras do motor de decisão (`engine/`). O motor é determinístico: a mesma entrada, em qualquer ordem de destinos ou participantes, dá o mesmo resultado. Cada regra abaixo tem teste em `tests/`.

A especificação do produto fica no repositório do front (`planner-vite/docs/especificacao.md`).

## Candidatos

- **Duração:** o organizador fixa as noites da viagem (`nights`, padrão 6). Para cada destino, o motor testa o roteiro padrão e um "roteiro curto" com 2 noites a menos (no mínimo 2). O dia da volta é o dia da ida mais as noites.
- **Custo:** `fixed_cost + noites × nightly_cost`, por pessoa.
- **Candidato:** destino × variante × dia de ida dentro da janela. `alternatives_evaluated` é quantos foram gerados.
- **Filtro:** um candidato que fere qualquer limite (datas, orçamento, clima vetado, destino vetado) é descartado. O limite de orçamento é comparado com o custo total.

## Satisfação

Para cada pessoa e candidato:

```
s_i = (Σ w_k · m_k / Σ w_k) · fator de duração
```

A média só considera as preferências declaradas. O que a pessoa não mencionou é neutro (0,5), fica fora da média e nunca aparece como concessão.

| Termo | Peso | `m` |
| --- | --- | --- |
| `prefer_destination` | o declarado | 1 para o primeiro da lista, 0,75 para outro listado, 0,4 para não listado |
| `prefer_tags` | o declarado | fração das tags pedidas que o destino tem |
| `prefer_climate` | o declarado | `1 − \|preferência − destino\|`, com quente 0, ameno 0,5, frio 1 |
| `pace` | o declarado | `1 − \|preferência − destino\|`, com tranquilo 0, equilibrado 0,5, agitado 1 |
| folga no orçamento (só para quem tem limite) | 0,5 | de 0,5, quando o plano cabe no limite, a 1, com folga de 20% ou mais |

O **fator de duração** é 1 no roteiro padrão. No curto, vale `1 − 0,3 · noites perdidas / nights` e se aplica a todos.

Quem não declarou nenhuma preferência fica com 0,5, fora do score e com `has_preferences = false`. O termo de orçamento não conta como preferência.

## Score e alternativas

```
score(p) = (1 − α) · média(s_i) + α · min(s_i)
```

O score só considera quem tem preferências; se ninguém tiver, ele é 0. Para cada destino e variante, o motor usa o primeiro dia viável. A ordem é a do score, arredondado em 4 casas. No empate, vem primeiro o roteiro padrão, depois o menor custo e depois o id do destino. O motor devolve até 3 alternativas, e a primeira é a recomendada.

Cada satisfação vem com `best_possible`: a maior satisfação da pessoa em qualquer candidato que respeita os limites do grupo.

## Destinos excluídos

`excluded_destinations` traz cada destino da viagem que não aparece nas alternativas:

- `limit`: nenhum candidato do destino é viável. Lista os limites que ferem todos os candidatos do destino. Se o destino cai por combinação de limites, lista os que, retirados sozinhos, liberariam algum candidato; senão, todos os envolvidos.
- `lower_score`: viável, com score menor. Traz `best_score`.

## Sem plano viável

Quando nenhum candidato respeita todos os limites, a rodada devolve:

- `plans: []`;
- `excluded_destinations`, com todos os destinos e motivo `limit`;
- `blocking_limits`: cada limite que elimina algum candidato, com `kind`, `member_id` (nulo no orçamento) e `eliminated_candidates`, do que mais elimina para o que menos. No empate, vale a ordem de participante e de limite.

Exemplo: com 6 noites fixadas, quem só pode viajar 3 noites elimina todos os candidatos, inclusive o roteiro curto, de 4 noites. Esse limite aparece em primeiro, com `eliminated_candidates` igual a `alternatives_evaluated`. A tela pode sugerir reduzir as noites da viagem.

Em uma rodada viável, `blocking_limits` é vazio.

## Privacidade do orçamento

O valor do orçamento é confidencial, e quem tem limite de orçamento também não é identificado para o grupo:

- Nas saídas para o grupo (`plans`, `excluded_destinations`, `blocking_limits`), um limite de orçamento aparece só como `kind: "budget"`, com `member_id` nulo. Vários orçamentos que eliminam o mesmo candidato contam uma vez, num único item.
- As justificativas não falam de orçamento. Ao lado do custo do plano, "cabe, mas no limite" revelaria quase o valor.
- `limits_for_member(trip, member_id)` devolve só os limites daquela pessoa, cada um com os destinos da viagem que ele elimina sozinho (nenhum roteiro do destino o respeita). É para a tela da própria pessoa, nunca para o grupo.
- Um teste percorre todas as saídas de grupo em vários cenários e falha se encontrar `kind: "budget"` junto com um `member_id`.

Limitação: num grupo em que só uma pessoa declarou orçamento, quem souber disso por fora sabe de quem é o "budget". As satisfações dessa pessoa também variam com a folga, o que permite inferir algo comparando planos de custos diferentes.

## Limitações conhecidas

- **Duração:** só existem duas durações, as noites fixadas e o roteiro curto com 2 a menos. O motor não testa roteiros mais longos nem durações intermediárias, e ninguém informa a duração que prefere.
- **Custo** linear por noite, sem variação por data nem por tamanho do grupo.
- **Datas** não afetam a satisfação: vale sempre o primeiro dia viável.

## Dados de exemplo do front

`python -m scripts.export_fixture` roda o motor nos cenários da demonstração da Viagem de julho e grava `fixtures/july-trip.json` no formato do contrato do front:

| Cenário | Quem respondeu | Para mostrar |
| --- | --- | --- |
| `before_eva_response` | Ana, Bruno, Carla | planos antes da convidada da demonstração |
| `after_eva_response` | mais Eva | o plano recomendado da demonstração |
| `eva_limits_only` | Eva remove a preferência de ritmo | `has_preferences = false` |
| `after_diego_response` | mais Diego, só 3 noites | rodada sem plano viável |

Cada rodada traz as restrições de quem respondeu. O mock do front usa a rodada cujas restrições batem com as respostas salvas. O arquivo também traz o catálogo e os limites de cada pessoa (`member_limits`). Os mocks do front leem uma cópia dele, e um teste falha se o arquivo gravado ficar diferente da saída atual do motor.
