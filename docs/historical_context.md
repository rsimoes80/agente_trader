# Premissa de análise: histórico mensal antes de considerar operação

A análise operacional começa por verificar histórico e estatísticas persistidas
do mesmo ativo, corretora/servidor e contrato UTC da fonte atual. O padrão é
**30 dias corridos de EURUSD**, nos períodos **M1, M5, M15, M30, H1, H4 e D1**.
Não equivale a 30 pregões. Períodos diários podem ter cerca de 21 candles;
isso fornece contexto, mas não amostra suficiente para validar uma estratégia D1.

O gráfico e a classificação continuam acessíveis sem histórico completo. No
observador V4 publicado, a falta dessa base produz `HISTORY_BASELINE_REQUIRED`,
`HISTORY_COVERAGE_INSUFFICIENT`, `HISTORY_SOURCE_MISMATCH` ou
`HISTORY_BASELINE_STALE`, preservando `NO_TRADE`. O sucesso desse requisito não
autoriza operação: os demais gates de regime, hipótese, confirmação, gatilho e
risco continuam necessários. O sistema permanece sem gateway de ordens.

## Coleta e PostgreSQL

```powershell
.venv/Scripts/python.exe run_history.py --full --study
.venv/Scripts/python.exe run_history.py --watch --study
.\install_history_startup.ps1
```

O primeiro comando captura o mês e executa um estudo pequeno de hipóteses.
`--watch` atualiza a janela a cada 15 minutos; após falhas, tenta novamente em
60 segundos. A tarefa `AgenteTrader-History` inicia no logon Windows, com
supervisor e lease exclusivo no PostgreSQL. MT5 deve estar aberto e conectado.
Não são instaladas outras instâncias de banco ou ferramentas de orquestração.

A captura reutiliza `mt5_provider.fetch_history`, que chama o SDK oficial e
exclui a posição zero, correspondente ao candle em formação. O volume pedido
é calculado pelo período e pela janela de calendário, com margem. A base também
filtra por timestamp de fechamento e pelo instante UTC congelado da captura.
O retorno depende do histórico disponível no terminal e do limite de barras.
Histórico insuficiente é informado, sem inventar ou preencher preços.

Depois da primeira importação válida, são solicitadas somente as barras desde
a última atualização, com sobreposição mínima de 100 barras por período para
detectar revisões. Mudança de servidor dispara uma captura completa para a nova
identidade. Capturas repetidas idênticas não duplicam registros.

O armazenamento **reutiliza `project_records`**, incluindo sua chave composta,
hashes e proteção append-only. Não foram criadas outras tabelas de candles nem
alteradas tabelas operacionais:

- `closed_candle`, chave `archive:<identidade>:EURUSD:<período>:<UTC>`: OHLC,
  volume de ticks, spread, timestamp UTC e original, offset, corretora e servidor.
- `historical_baseline`: janela, hashes por período, estatísticas, cobertura e
  referência de cada importação.
- `historical_collection_status`: sucesso, indisponibilidade e motivo.
- `historical_hypothesis_study`: plano e resultados exploratórios versionados.

Uma revisão do mesmo candle cria outra versão imutável; não sobrescreve o
original. Consultas `known_by` usam o instante de chegada ao PostgreSQL. O loader
de replay verifica o hash da revisão congelada pela baseline. Capturas feitas
hoje não permitem afirmar que aquela versão histórica já era conhecida no passado.

## Estatísticas e qualidade

São calculados contagem de barras, retornos contíguos, média e desvio padrão dos
retornos logarítmicos, fração de retornos positivos, amplitude média e percentil
95, spread médio e percentil 95 e volume médio de ticks. Há grupos por sessão
Londres/Nova York e hora UTC. O volume é específico da corretora.

Lacunas e timestamps originais ficam auditáveis. Retornos através de lacunas
não entram na distribuição de retornos contíguos. Não há normalização automática
de preços ausentes nem preenchimento de fins de semana.

O gate exige sete períodos, ao menos 30 dias solicitados, cobertura mínima de
95% e barras recentes. A cobertura usa a convenção semanal Forex de sexta às
17h de Nova York até domingo às 17h, com timezone dinâmico. Não é calendário
oficial de feriados da corretora; H4/D1 usam duração negociável, porque suas
fronteiras podem não coincidir com meia-noite UTC. Cobertura é indicador de
qualidade, não prova de ausência de todo problema no feed.

A baseline deve ter menos de seis horas. A atualidade das barras é verificada
na captura, com tolerância proporcional ao período. O gate também rejeita fonte
diferente, versão incompatível e baseline posterior à análise. A API de consulta
não usa uma baseline registrada depois do instante avaliado. A fonte ao vivo
continua sujeita à validação de ticks e relógios já existente.

## Pesquisa e aprendizado persistente

O estudo inicial formula duas hipóteses fixas: continuação ou reversão da direção
do corpo do último candle para 3, 6 e 12 barras M5. Os sinais só usam dados
fechados; rótulos vêm dos candles posteriores da mesma partição. Amostras de cada
horizonte não se sobrepõem e janelas atravessando lacunas são rejeitadas.

O protocolo usa 60% desenvolvimento, 20% validação e 20% final reservado. O
baseline direcional majoritário é calculado no desenvolvimento e congelado para
a validação. O critério inicial compara acerto com esse baseline, exigindo ao
menos 30 amostras. `RESEARCH_ONLY_CANDIDATE` significa somente proposta para
pesquisa adicional, sem aprovação estatística, econômica ou operacional.

O resultado registra direção e movimento bruto, **sem custos de negociação**.
Não é backtest de rentabilidade. A amostra pode compartilhar dias e horizontes
correlacionados. Estudos móveis podem se sobrepor a dados vistos anteriormente;
o segmento reservado não se torna um holdout independente por mudar de nome.
Não há fine-tuning, alteração automática de limiares ou promoção de estratégia.

Os dados aumentam a memória auditável e permitem testar novas hipóteses em
períodos posteriores. Não são importados como experiências de trades lucrativos
nem usados para modificar impulsivamente o learner existente.

## Replay a partir do banco

```powershell
.venv/Scripts/python.exe run_replay.py --postgres-history --validate-temporal
```

Esse comando carrega a versão mensal M5 congelada no PostgreSQL, verifica hashes
e utiliza o replay existente com spreads, slippage e comissões configurados.
O holdout permanece reservado. O modelo Timestral pode ser solicitado com
`--timestral`, mantendo suas previsões separadas das decisões V4.

No replay offline, o aquecimento e as partições continuam explícitos; o histórico
mensal posterior a uma barra não é convertido em conhecimento disponível naquela
barra. O gate mensal operacional é aplicado no observador ao vivo; o replay de
pesquisa não autoriza operações reais e não reutiliza a baseline futura para
liberar decisões históricas.

## Painel e testes

O quadro expansível **Histórico antes da análise** aparece no gráfico e no
diagnóstico. Mostra a janela, cobertura, candles, amplitude, spread e status.
`GET /api/diagnostics/history` consulta a baseline e o estudo mais recentes.
Isso não muda o timeframe de entrada do Timestral, que continua M5 nesta versão.

Testes cobrem exclusão de candles abertos/futuros, duplicatas, integridade de
preços, qualidade mensal, sessões, atualidade, fonte, dados futuros, bloqueio
prévio do motor, isolamento do holdout, idempotência e revisões no PostgreSQL.
Os testes PostgreSQL usam schema transacional desfeito por rollback, na instância
existente, sem banco paralelo. Para habilitá-los: `TIMESTRAL_TEST_POSTGRES=1`.

Referência oficial: [copy_rates_from_pos](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py).
O conector preserva a [normalização UTC validada](mt5_clock.md).
