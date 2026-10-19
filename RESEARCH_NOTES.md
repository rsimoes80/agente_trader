# Caderno de pesquisa: regras extraídas dos PDFs

Os três documentos locais foram lidos e resumidos em regras que podem ser auditadas e testadas em candles históricos. As frases são sínteses; as operações não importam rótulos manuais dos livros nem presumem que os exemplos publicados tenham vantagem estatística fora da amostra.

## Manual do Pullback

O guia organiza a análise em tendência, qualidade da correção, região, gatilho, stop e tamanho. A qualidade do pullback considera quatro itens: profundidade em relação à perna anterior, correção mais lenta/estreita que o impulso, volume em contração quando a fonte oferece dados adequados e preservação do swing anterior. O próprio checklist sugere não operar com dois critérios ou menos; três recomenda reduzir tamanho; quatro permitem o tamanho normal definido no plano. A região (EMA, retração de Fibonacci ou congestão rompida) serve para observar, não para comprar por toque. O gatilho é confirmado depois da região, por exemplo fechamento de reversão e rompimento da máxima/mínima.

**Aplicação no motor:** score separado de 0–4 para a qualidade do pullback; sinal bloqueado com menos de 3 quando o filtro está ligado; budget de risco reduzido pela metade com 3 critérios; stop técnico do swing confirmado com buffer ATR. As faixas de retração, EMAs e gatilhos ficam configuráveis.

## Smart Money Concepts — Marraik

O material descreve pivôs/swing points, BOS e CHoCH, zonas de liquidez e sweeps. Também ressalta que um pavio que cruza nível pode ser captura de liquidez e não confirmação de rompimento; o fechamento do candle importa. O guia reconhece que os rótulos e algumas zonas são interpretativos.

**Aplicação no motor:** pivôs só entram após candles à direita confirmarem o swing; BOS usa fechamento além do swing; sweep exige passar um extremo recente e fechar de volta dentro da faixa. O filtro atual pede BOS ou sweep junto com gatilho de candle. Order blocks/CHoCH completos não são inferidos automaticamente, pois a leitura do material depende de contexto e a regra não foi validada para FX.

## Wyckoff 2.0

O livro trabalha leitura de contexto e relação entre preço e volume, mas alerta para padrões menos convencionais e para não forçar a identificação de eventos. Também discute limitações de dados de mercados OTC e a diferença entre o feed de um intermediário e o conjunto de negociações.

**Aplicação no motor:** o filtro de volume começa desligado, e os campos de feed Forex são tratados como volume tick do provedor, não volume consolidado do mercado mundial. O filtro Wyckoff é opcional e por enquanto só busca uma varredura com fechamento de retorno em range recente; isso é um proxy simples, não classificação de fases/causa e efeito.

## Controles adicionais adotados

- Exigir score configurável, candle de confirmação e risco/retorno mínimo antes de propor entrada.
- Calcular tamanho simulado como orçamento monetário de risco dividido pela distância até o stop; limitar a exposição nocional do backtest.
- Aplicar limite de perda diária, drawdown, operações por dia, custos de spread/slippage e saída temporal.
- No backtest, sinal fechado preenche na abertura seguinte; se stop e alvo caírem dentro da mesma barra, presume stop primeiro.
- Métricas passadas não são promessa de assertividade. Separar período de calibração do período de avaliação e testar custos/regimes antes de tirar conclusões.

## Arquivos-fonte

- `avulso/replica_robo_python/EBOOK-MANUAL-DO-PULLBACK.pdf` — critérios de correção, regiões, gatilhos e ficha de análise.
- `avulso/replica_robo_python/Smart Money Concepts - MARRAIK SMC 2 (1).pdf` — estrutura, liquidez, sweeps, confirmação e risco.
- `avulso/replica_robo_python/wyckoff-20-portugues-pr.pdf` — contexto, preço-volume, subjetividade dos rótulos e observações sobre OTC.
