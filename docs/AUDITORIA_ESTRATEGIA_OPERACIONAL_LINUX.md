# Auditoria da estratégia operacional — 28/10/2026

A camada de propostas da estratégia operacional não autorizou entradas nas
janelas congeladas. O motivo principal é o filtro de regime H1, seguido da
confirmação obrigatória em H4. A falta de contexto diário não explica a ausência
de propostas nesta execução. Nenhuma regra, modelo, risco ou sessão foi alterado.

## Escopo e reprodução

A auditoria reutiliza `agent_research.intelligence_session` e
`agent_strategy.propose_pullback` com `research=False`: H4/H1/M15/M5, contexto
D1 e as mesmas regras estritas da camada de propostas do worker operacional.
Os candles anteriores à janela são processados pelo caminho `warmup_only`
utilizado pelo worker. Não há fallback de direção ou flexibilização de regime.

```bash
.venv/bin/python run_operational_audit.py \
  --plan data/replays/validation-b40c0837-50cc-4af5-9d28-27a34fac865f/plan.json \
  --warmup data/provisioning/verification/warmup-60days.json
```

Os argumentos são artefatos privados locais, não arquivos publicados no Git.
O coletor já havia preparado 60 dias M5. Para esta avaliação, a consulta ao
PostgreSQL foi limitada a candles anteriores à reserva, iniciada em
2026-10-22 03:05 UTC. Os hashes de desenvolvimento e validação conferem com
os do plano original. O runner também rejeita revisões de preço ou contagem
antes de futuras avaliações. Cada partição recebe contexto exclusivamente
passado e uma sessão de análise nova; não usa resultados financeiros anteriores.

O plano, código-fonte executado, hashes, decisões agregadas e resultados ficam
em `data/reports/operational-audit-660e7eca-6911-48a2-952a-fc92292f0b6c/`.
O registro também foi persistido no PostgreSQL como `operational_proposal_audit`.

## Resultado das regras estritas

| Verificação | Desenvolvimento | Validação |
| --- | ---: | ---: |
| Candles avaliados | 3.798 | 1.266 |
| Contexto M5 suficiente | 3.798 | 1.266 |
| Contexto diário suficiente | 3.798 | 1.266 |
| Mínimo de candles D1 disponíveis | 25 | 40 |
| Regime H1 classificado como TREND | 12 | 0 |
| Confirmação conjunta H4/H1 aprovada após regime | 0 | 0 |
| Propostas operacionais | 0 | 0 |

Primeiro bloqueio retornado por `propose_pullback`:

| Motivo | Desenvolvimento | Validação |
| --- | ---: | ---: |
| TREND_REGIME_REQUIRED | 3.786 | 1.266 |
| TREND_CONFIRMATION_REQUIRED | 12 | 0 |

Essas contagens são decisões M5, não observações H1 independentes. Não se pode
atribuir a rejeição a filtros posteriores, como spread ou gatilho de pullback:
nenhuma decisão chegou até eles após passar pelos gates anteriores.

## Investigação do regime e da confirmação

Na janela de desenvolvimento, 3.449 decisões viram UNKNOWN, 181 RANGE, 156
TRANSITION e 12 TREND. Na validação: 172 UNKNOWN, 1.034 RANGE e 60 TRANSITION.
Não houve lacuna inesperada M5 segundo o calendário da corretora na fonte usada.

Uma sondagem separada, somente de contexto, contou fechamentos H1 distintos.
Das 318 observações no desenvolvimento, 278 tinham geometria não classificada.
Entre as 316 com features disponíveis, 307 não atingiam a eficiência direcional
mínima de 0,65; 229 não atingiam a fração de extremos direcionais de 0,50.
Os critérios se sobrepõem e não devem ser somados como causas independentes.
Na validação, nenhuma das 105 observações com features atingia a eficiência
mínima. RANGE ou TRANSITION também não autorizam a política atual, mesmo quando
há oscilação de preço visível no gráfico.

O único estado H1 TREND observado na sondagem de desenvolvimento foi conhecido
em 2026-10-07 13:00 UTC. H1 estava `BEAR_CONFIRMED`, mas H4 estava `TRANSITION`,
com direção neutra. Isso explica as 12 decisões M5 seguintes recusadas pela
confirmação; não havia confirmação conjunta H4/H1 para abrir a posição.

Houve ainda três observações H1 distintas com `REGIME_DATA_STALE` na sondagem.
Não eram lacunas M5 inesperadas e não explicam a maior parte das rejeições.
Não foi demonstrado um defeito que justifique alterar os limiares: a geometria
observada simplesmente não satisfez os critérios publicados nesta amostra.

## Simulação financeira e limites

Foram simuladas carteiras hipotéticas das propostas em cada partição, com
0,01 lote padrão (1.000 unidades), conta sintética de US$ 10.000, holding de
12 candles M5 e exclusão de entradas na última hora de cada janela. As carteiras
normais usam spread histórico, slippage de 0,2 pip e comissão hipotética de
US$ 35 por milhão por lado. O estresse multiplica o spread por 1,5 e usa
slippage de 0,4 pip. A comissão não representa tarifa confirmada da conta.

Todas as quatro carteiras terminaram com zero operações e P&L zero. Não houve
posição censurada, exposição pendente ou resultado financeiro para comparar.
A análise de custos fica sem amostra; zero drawdown não é evidência de segurança.

Este é um teste das propostas e de sua execução hipotética, não uma validação
integral do agente. Como nenhuma proposta passou, previsão Timestral, filtro
aprendido, escolha de hipótese pelo aprendizado contínuo, cotação ao vivo e
execução demo não foram exercitados por esta avaliação. Não foram fabricadas
probabilidades ou propostas para atravessar esses bloqueios. Não houve treino,
promoção de modelo, acesso de desempenho à reserva final ou envio de ordens.

Os 18 testes de causalidade, reserva, revisão de preços, estratégia, tendência
e agregação passaram. A próxima etapa de pesquisa pode ampliar a amostra
histórica para verificar esses critérios em mais regimes, mantendo o protocolo
congelado; não há evidência suficiente para promover a estratégia ou relaxar
filtros apenas para forçar operações.
