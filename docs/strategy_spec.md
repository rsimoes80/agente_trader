# Especificação inicial de estratégia

## Escopo

O plugin implementado é `research_breakout_retest`, versão `2.0-v3`. Sua política aceita WITH_TREND, exige contexto/estrutura confirmados e usa [Market Intelligence V3](market_intelligence_v3.md) antes de formar hipótese. A confirmação é o retorno à zona congelada; o gatilho é um fechamento posterior além do extremo do candle de retorno. Contrato, gatilho e risco são gates distintos. Transições, evidência insuficiente/conflitante/invalidante e obstáculos estruturais ao alvo podem resultar em NO_TRADE. Essa política é de pesquisa e não demonstra vantagem estatística.

O primeiro plugin de pesquisa proposto é pullback em tendência. Ainda não está aprovado como vantagem estatística nem para execução. Todas as análises usam candles fechados; o candle 0 pode ser exibido no gráfico, mas não deve confirmar um sinal.

## Hipótese de pesquisa

Em um regime direcional confirmado, uma correção moderada e menos agressiva que o impulso, preservando o swing relevante e retornando a uma região previamente definida, pode oferecer uma entrada de melhor relação risco-retorno depois de um gatilho de fechamento. Isso é hipótese testável, não previsão.

## Evidências candidatas

- swing/pivô confirmado sem usar barras futuras na decisão;
- direção e estrutura observáveis no timeframe de contexto configurado;
- profundidade do pullback dentro de faixa configurada;
- range/velocidade da correção comparado ao impulso;
- volume tick somente quando a fonte e o significado forem conhecidos;
- preservação do swing de invalidação;
- região de interesse apenas como contexto, nunca gatilho por toque;
- candle fechado que confirme retomada;
- spread, freshness, custos e espaço até obstáculo aceitos pelo RiskManager.

## Saída

Retornar `NO_TRADE` como padrão. Para candidato, guardar direção, candle de referência, evidências favoráveis/contrárias, preço hipotético de entrada, nível estrutural de invalidação, alvo bruto, custo estimado, validade temporal e versões. A estratégia não escolhe volume/lote nem transmite ordens.

## Validação

Comparar com baseline simples; separar treino, validação e teste cronologicamente; incluir warm-up, spread, slippage, comissões e conversão; walk-forward por regime/sessão; relatar número de trades, expectativa em R, payoff, fator de lucro, drawdown e duração, custos, MAE/MFE e estabilidade. Registrar todas as tentativas. Não promover por lucro ou win rate isolados. Limites ainda dependem de política de risco aprovada.

## Situação herdada

`analysis.py` já contém EMA/RSI/MACD/ADX/ATR, pivôs com barras à direita, proxy BOS/sweep, regiões EMA/Fibonacci e score de pullback. Essa implementação calcula sinal na mesma função e não implementa contexto multi-timeframe ou sessões. Reaproveitamento exige teste causal e separação de feature, estratégia e plano de risco.
