# Correção de expiração e estudo separado de parâmetros

## Correção operacional

Classificador `0.1.1-expiry`, política `reset_pending_v1`. Uma transição expirada
não pode reaparecer no candle seguinte por causa da faixa com `EXIT_ACCEPTED`.
Quando a confirmação não se completou, o motor descarta o contexto pendente e
retorna UNKNOWN, subtipo TRANSITION_EXPIRED. É necessário observar novas barras
para estabelecer outra classificação. Expiração não autoriza TREND nem ordens.

Transições dentro do prazo permanecem válidas. Uma faixa estabelecida que não
estava aguardando confirmação continua tendo seu próprio ciclo de vida.
Geometria sem categoria, confirmação pendente e expiração têm motivos explícitos
no campo `features.classification_reason`; falta de dados permanece em
`missing_data`.

Os limiares operacionais continuam eficiência 0,65 e três confirmações, com
direção H4+H1 obrigatória. Apenas a correção de ciclo de vida é operacional.
O hash do classificador separa memória e estatísticas das versões anteriores.
Registros antigos não são apagados nem relabelados. A memória histórica da nova
versão pode começar vazia até existirem amostras classificadas com seu hash.

## Experimentos isolados

`run_regime_study.py` compara quatro versões:

1. Legado `0.1.0-research`, apenas como referência de pesquisa.
2. Correção de expiração, eficiência 0,65 e três confirmações.
3. A mesma correção, alterando **somente** eficiência para 0,55.
4. A mesma correção, alterando **somente** confirmações para duas.

Não se combinam eficiência 0,55 e duas confirmações. Todas usam os mesmos candles,
lote, padrão de pullback, sessões, custos, posição única e limites do simulador.
Os resultados são separados para direção H4+H1 e H1, sem alterar a direção ativa.
Este é um estudo de elegibilidade técnica, sem reproduzir a seleção adaptativa
completa do robô nem treinar pesos do Timestral.

## Três conjuntos separados

- **Histórico:** catálogo congelado de 335 dias já consultado, com 30 de aquecimento.
  Somente candidatos previamente rotulados; avaliação retrospectiva.
- **Pós-catálogo exploratório:** novos candidatos construídos causalmente depois
  do fim desse catálogo, no histórico MT5 mais recente. Não é chamado de período
  virgem: dados e operações recentes podem já ter sido vistos no projeto.
- **Prospectivo:** somente entradas depois do registro imutável do protocolo no
  PostgreSQL. No início é INCONCLUSIVE. Exige no mínimo sete dias e 20 operações
  encerradas por braço principal H4+H1 para ficar READY_FOR_REVIEW_NOT_PROMOTED.
  Isso é prontidão para revisar, não comprovação de superioridade.

O acompanhamento automático termina após 30 dias; falta de amostra não é
aprovação. Não há busca automática de parâmetros nem promoção para produção.

## Falsos rompimentos

A medida descritiva considera a primeira ativação TREND de um rompimento de faixa
confirmado. Verifica se algum dos oito candles H1 fechados seguintes retorna
através do nível rompido. Falta de oito candles ou lacuna inesperada mantém a
observação pendente; não é contabilizada como sucesso.

Essa medida tem denominador próprio e não equivale à taxa de perdas de trades.
As confirmações de rompimento continuam exigindo as três barras de aceitação
originais; a variante de duas confirmações altera a persistência da geometria,
não todas as confirmações do sistema.

## Execução e persistência

- Windows, primeira captura: `python run_regime_study.py --capture`.
- Reavaliação do histórico novo no PostgreSQL:
  `python run_regime_study.py --forward-only`.
- VM: `agente-trader-regime-study.timer`, diariamente às 02:20 UTC, equivalente
  a 23:20 de Brasília, com pequena variação de até dois minutos.
- Serviço isolado com prioridade reduzida, limite de CPU/memória e lease no
  PostgreSQL para impedir duas pesquisas simultâneas.
- Protocolos: `agent_regime_study_protocol`; relatórios: `agent_regime_study_report`;
  arquivo local: `data/reports/regime-study.json`.

O serviço lê os candles que o agente importa para o PostgreSQL. Com o MT5/Windows
indisponível não inventa dados, e qualidade insuficiente impede concluir a rodada.
O timer não depende de o navegador estar aberto e não envia ordens ao MT5.

## Primeira execução — 22/10/2026

Resultado retrospectivo com direção H4+H1, lote 0,01 e custos do simulador:

| Versão | Sinais elegíveis | Operações encerradas | Ganhos / perdas | Líquido USD |
|---|---:|---:|---:|---:|
| Legado | 1 | 1 | 0 / 1 | -1,18 |
| Apenas correção de expiração | 1 | 1 | 0 / 1 | -1,18 |
| Correção + eficiência 0,55 | 10 | 7 | 2 / 5 | -3,97 |
| Correção + duas confirmações | 5 | 3 | 0 / 3 | -2,65 |

Sinais não equivalem a trades: exposição existente e limites de execução podem
impedir a entrada. No braço H1, respectivamente, foram 2, 2, 12 e 5 operações,
com resultados de -2,21, -2,21, -7,25 e -4,09 USD. Não há demonstração de melhora
econômica, e as amostras são muito pequenas.

No fluxo H1 completo, a incoerência TRANSITION + EXPIRED caiu de 1.724 observações
no legado para zero nas versões corrigidas. Parte dos estados passou a UNKNOWN;
a correção não foi feita para aumentar operações.

A medida de falsos rompimentos teve apenas uma ou duas ativações avaliáveis
nos braços corrigidos, com outras observações pendentes. Não permite concluir
que duas confirmações aumentem ou reduzam falsos rompimentos.

O período posterior ao catálogo disponível nessa captura não produziu operações
elegíveis em nenhum braço. O prospectivo continua INCONCLUSIVE: ausência de
trades não é acerto de 0%, nem validação da estratégia.

Protocolo registrado em **22/10/2026 às 11:21:45 de Brasília**, antes de calcular
os resultados novos. O piso de sete dias só se completa em 29/10/2026, mantendo
também a exigência de amostra suficiente. O resultado pode continuar inconclusivo.

Study ID: `032e1aff1ceb8567496d357847355e325958e0054bff451c91832ae5ab228ae8`.
Primeiro relatório: `cf096fc50844849767c6d07bb3a15cea552c577632f7b625176f3c152a3f49cc`.
