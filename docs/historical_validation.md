# Validação da base histórica — 20/10/2026

## Coleta real

Fonte: terminal MT5 Windows conectado ao servidor ThinkMarkets-Demo, EURUSD.
Contrato `mt5-utc-v1`, perfil verificado e timestamps originais preservados.
Janela solicitada: 30 dias corridos, de 20/09 a 20/10/2026. Primeiro candle
disponível da janela em 20/09 às 21h UTC, após o fechamento semanal.

Snapshot das 12:49 UTC:

| Período | Candles fechados na janela |
|---|---:|
| M1 | 31.139 |
| M5 | 6.233 |
| M15 | 2.079 |
| M30 | 1.039 |
| H1 | 519 |
| H4 | 129 |
| D1 | 21 |
| **Total** | **41.159** |

Baseline `b3dca21d9f9104f6ae3de2e1a1d1803cb1df027c62446bc1d06688df8b160391`,
estado `ready`, sem bloqueio de cobertura. Os números mudam na atualização
móvel. Uma atualização incremental reutilizou todas as 100 barras consultadas
em M5/H1/H4 e todas as 21 em D1, inserindo somente as novas barras M1 naquele
instante. Não houve duplicação do conteúdo idêntico.

O PostgreSQL existente foi reutilizado, sem DDL ou migração de tabelas
operacionais. O namespace `archive:` separa a coleta histórica dos registros
originais do monitor e replay. Revisões ficam como novos hashes imutáveis.

## Hipóteses exploratórias

Duas hipóteses fixas, continuação/reversão da direção do corpo do candle M5,
foram avaliadas nos horizontes 3/6/12. Na versão 2 do estudo, com janela atualizada:

| Horizonte | Amostras por hipótese | Continuação | Reversão |
|---|---:|---:|---:|
| 15 min | 404 | 48,5% | 48,5% |
| 30 min | 202 | 44,6% | 53,5% |
| 60 min | 99 | 49,5% | 50,5% |

Estudo v2: `635c84a810833b599797107711009565d5d30c82dc31621575cc1a9a426e9c5d`.
Resultados futuros neutros permanecem no denominador (12, 4 e 0 por horizonte).
A versão 1 exploratória, que os excluía, foi preservada como histórico e não
deve ser usada para inferir desempenho operacional. A correção evita seleção
retrospectiva de resultados; não alterou uma estratégia ou limiar em produção.

Estudo persistido em `historical_hypothesis_study`, com critério, partições,
hashes e baseline direcional congelado no desenvolvimento. Não há custos,
inferência de significância ou validação econômica nesses percentuais.
`RESEARCH_ONLY_CANDIDATE` não aprova uma estratégia. O estudo é exploratório,
com dependência temporal e possível sobreposição de períodos já vistos.

## Replay mensal do V4 diretamente do PostgreSQL

Comando: `python run_replay.py --postgres-history --validate-temporal`.
Plano: `validation-30aa0c24-984c-4dde-b8d9-d310280016ba`.

| Partição | Barras | Operações simuladas fechadas |
|---|---:|---:|
| Desenvolvimento | 3.739 | 0 |
| Validação | 1.247 | 0 |
| Holdout | 1.247 | Reservado, não avaliado |

Desenvolvimento: `9a6236d4-bd62-445a-8900-c6bf71e10c80`.
Validação: `81b45cf9-23b1-4c8c-8e70-c1942ae7493f`.

Todas as 4.986 decisões foram `NO_TRADE`. Os principais bloqueios foram
regime incompatível, sessão não autorizada e regime desconhecido. Não foram
relaxados filtros para produzir entradas. O replay conserva o modelo existente
de spreads, comissões e slippage; sem operações, não há demonstração de retorno
ou aprendizado sobre resultados financeiros de trades nesta execução.

O dataset foi congelado por baseline, hash e instante de chegada. A preparação
do arquivo ocorreu após os dados históricos; não se declara que essas revisões
já estavam disponíveis no passado nem que o holdout é globalmente inédito.

## Operação e interface

- Tarefa Windows `AgenteTrader-History` registrada e em execução.
- Atualização incremental a cada 15 minutos, com retry após falha de fonte.
- Gate mensal ligado no observador V4 publicado; leitura histórica consultada
  antes do preparo inicial e registrada por referência nas decisões seguintes.
- API `/api/diagnostics/history` retornou baseline válida e sete períodos.
- Chrome headless verificou o quadro no gráfico e no diagnóstico, inclusive
  viewport móvel de 390 × 844, sem exceções JavaScript.
- Backups PostgreSQL concluídos durante a entrega.

## Verificação automatizada

A suíte completa passou com **135 testes**, incluindo o modelo Timestral real,
PostgreSQL e as regressões anteriores, sem falhas ou testes ignorados.

Testes incluem dados incompletos/futuros, duplicatas, fonte e relógio,
captura incremental, qualidade mensal, bloqueio do motor sem histórico,
isolamento do holdout, idempotência e revisão temporal no PostgreSQL.
O schema de teste é isolado e descartado por rollback.

Os resultados são persistência e evidência para pesquisa. Não houve promoção,
fine-tuning ou autorização de ordens.
