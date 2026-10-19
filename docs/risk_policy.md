# Política de risco inicial

## Estado de aprovação

Este documento descreve controles atuais e salvaguardas necessárias. Não constitui aprovação de operação real. `app.py` rejeita modos diferentes de `paper`, e o código ativo não chama `order_send`. Não altere esse bloqueio via configuração ou modelo.

## Controles existentes

- configuração valida faixas para risco percentual, drawdown, perda diária, operações/dia, spread, slippage e relação risco-retorno;
- backtest calcula budget percentual, stop estrutural, exposição nocional limitada e bloqueia novas entradas após limites diários/drawdown;
- sinal exige filtros e candle de confirmação configurados; pullback de baixa qualidade reduz budget simulado;
- custos aproximados e regra stop-primeiro em empate intrabar estão descritos.

## Limitações materiais

Os limites estão no simulador e não formam um RiskManager que proteja todos os modos. `units = budget / distância` assume linearidade, contrato padrão e moeda compatível. Não valida `volume_min/max/step`, `trade_tick_value`, moeda de conta diferente, conversão, margem, exposição correlacionada, ordens pendentes reais, partial fill ou reconciliação. Candle OHLC não revela a ordem intrabar; assumir stop primeiro é conservador, mas não modela gaps. Spread/slippage do feed podem não refletir execução.

## Regras obrigatórias para a próxima etapa

1. Política explícita por modo e símbolo, fail-closed; risco nunca pode ser elevado pelo modelo de aprendizado.
2. Estado e freshness válidos antes de analisar. Qualquer dado inválido/atrasado resulta em `NO_TRADE`.
3. Calcular exposição monetária pelo contrato/tick value e moeda da conta; verificar lote mínimo/máximo/passo e margem usando gateway.
4. Definir limites por trade, dia, drawdown, posições e exposição agregada; travar até intervenção após violação.
5. Uma decisão tem chave idempotente; executor futuro consulta risco e autorização imediatamente antes de enviar.
6. Kill switch independente, auditoria de mudança e reconciliação antes de qualquer modo demo com ordens.
7. `ALLOW_LIVE_TRADING` não pode ser ativado por configuração gerada, otimização ou hipótese aprendida. Live permanece desativado neste projeto.

Os valores do arquivo atual `data/default_config.json` são parâmetros de simulação, não limites recomendados nem aprovados para uma conta real.
