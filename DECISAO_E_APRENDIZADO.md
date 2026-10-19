# Decisão e aprendizado — V3

## Atualização V4

O fluxo vigente começa por regime e localização antes de selecionar estratégias. [Prompt Mestre V4](docs/PROMPT_MESTRE_V4.md) e [implementação/referência](docs/market_regime_v4.md). As versões anteriores abaixo são históricas.

O contrato mental atual é o processo OBSERVE → CONTEXTUALIZE → CLASSIFY TREND → READ PRICE ACTION → MAP LEVELS → COLLECT EVIDENCE → IDENTIFY CONFLICTS → REMEMBER → FORM HYPOTHESIS → DEFINE EXPECTATION → WAIT → CONFIRM → TRIGGER → VALIDATE RISK → ACT OR WAIT → MANAGE → REVIEW → LEARN → TEST → PROMOTE.

O [Prompt Mestre V3](docs/PROMPT_MESTRE_V3.md) é a referência consolidada. A [camada V3](docs/market_intelligence_v3.md) separa contexto, confluência, confirmação, gatilho e autorização de risco. O monitor Dukascopy permanece em observação; o replay implementa o ciclo com memória SQLite, custos e resultados simulados. Experiências congelam o contexto da entrada e recebem resultados por novos eventos. Jev e o learner legado não podem substituir esses contratos ou promover uma estratégia.

## Histórico do fluxo legado de pesquisa

As seções abaixo documentam o comportamento anterior do caderno de pesquisa e do learner experimental; não são o contrato operacional V3. Os limiares numéricos do parecer Jev não representam probabilidade calibrada de mercado nem autorização de risco. A implementação atual já possui feed somente leitura, percepção V3 e simulador offline.

## Como uma decisão é avaliada

1. O motor técnico calcula contexto apenas com candles fechados: tendência pelas EMAs, RSI, MACD, ADX, ATR, volume do provedor, estrutura, pullback, gatilho, stop e relação risco/retorno.
2. Se os filtros locais não formarem um candidato, o sistema espera e não chama o Jev.
3. Quando solicitado, o Jev recebe um resumo numérico do último candle do CSV e escolhe entre aprovar ou esperar. Ele não pode inverter a direção, recalcular o tamanho da posição nem alterar os limites.
4. Uma aprovação só passa se a opção for `approve`, a probabilidade dessa opção for pelo menos 0.82 e a confiança do Jev for pelo menos 0.75. Resposta inválida, falha de rede, chave recusada ou resultado ambíguo bloqueiam a entrada.
5. A revisão não envia ordens. Ainda não existe feed ao vivo nem adaptador de execução conectado.

Esses limiares são salvaguardas iniciais, não estimativas de lucro. Precisam ser avaliados em dados fora da amostra. Uma probabilidade de escolha ou confiança do modelo não e garantia de acerto.

## O que aprende com resultados

O Jev e um modelo de decisão chamado por requisição; ele não treina nem memoriza os resultados deste aplicativo entre chamadas. O aprendizado fica no projeto e usa resultados de trades fechados em backtests anteriores para estimar quais condições tecnicas foram mais uteis.

O modelo local e uma regressão logistica regularizada. Aprende pesos relativos para as confirmacoes de tendência, pullback, estrutura, gatilho, regiao, RSI, MACD, ADX, ATR, Wyckoff, intensidade de RSI/ADX/ATR, qualidade do pullback, BOS, sweep, volume relativo do provedor, expansao de faixa, posição do fechamento no candle, tamanho do corpo e distancia entre EMAs. Esses pesos podem vetar um candidato; nunca aumentam o risco monetario.

Para evitar que ajuste e avaliacao usem a mesma epoca, os registros são ordenados por data: os primeiros 80% treinam o modelo e os 20% finais ficam como validação cronologica. O filtro só liga se houver pelo menos 100 trades, pelo menos 10 vitórias e 10 perdas nos dois trechos, e o Brier score no trecho não visto superar a previsão-base em pelo menos 5%. Ativo, o filtro descarta candidatos com probabilidade aprendida de vitória abaixo de 55%. Se os requisitos não forem atendidos, a estrategia tecnica original continua valendo sem pesos aprendidos.

Resultados fechados de cada backtest são registrados em `data/decision_history.json`, separados por par e período. Repetir o mesmo candle não aumenta a contagem de amostras. Como backtests repetidos podem compartilhar dados, use períodos posteriores e independentes para validar qualquer ajuste; dados duplicados ou correlacionados podem inflar a aparente qualidade.

O ajuste atual aprende a importância das condições e indicadores, não muda automaticamente os períodos numericos das EMAs/RSI/ATR. A escolha de períodos fica configuravel para evitar uma busca grande que se ajuste demais a um unico histórico.

## Jev: configuração e custo

Na pagina **Caderno de pesquisa**, salve uma chave de API TypeSafe. Ela fica cifrada com DPAPI do Windows em `data/typesafe.dpapi`; o servidor nunca a devolve ao navegador nem a inclui nos logs. Depois importe um CSV e use **Revisar cenário com Jev**. Cada clique que chega a um candidato envia uma requisição para `api.typesafe.ai`; pode consumir a cota da conta TypeSafe. Se não existir candidato, nenhuma requisição externa e feita.

A chave e opcional. O backtest local e o filtro aprendido não dependem de chamadas ao Jev.

## CSV atual

O arquivo `EUR-USD_5Minute_BID_2026-10-16_23_59-23_59_Etc_UTC.csv` tem 219 candles M5 entre 00:00 e 18:10 UTC de 16/10/2026. O cabecalho `Etc/UTC` foi incluido entre os nomes aceitos para a coluna de tempo. Com as configuracoes atuais, o backtest produziu zero operações; portanto não ha resultados fechados para treinar o filtro nem candidato para enviar ao Jev. Um unico trecho inferior a um dia tambem não permite conclusoes estatísticas sobre assertividade.

Para ativar o aprendizado, importe histórico mais longo do mesmo par e período, com spreads/custos representativos e trades fechados suficientes. Prefira meses de diferentes regimes e valide sempre numa janela cronologicamente posterior. Volume Forex continua sendo especifico do provedor, não volume consolidado do mercado mundial.
