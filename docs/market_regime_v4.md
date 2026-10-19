# MarketRegimeEngine V4

Regime precede tendência, consulta de experiências e busca de setup. O motor observa
TREND, RANGE, TRANSITION ou UNKNOWN por timeframe, com versão `0.1.0-research`.
São categorias de engenharia, não estados universais nem vantagem comprovada.
O regime principal vem do timeframe **context** da hierarquia configurada. Todos os
timeframes disponíveis são classificados separadamente; uma tendência M1 não preenche
dados M30 ausentes. A localização inicial usa a faixa congelada e depois recebe os níveis
estruturais do mesmo timeframe. Price action só vira evidência junto desse contexto.

## Dados e parâmetros

O motor aceita candles fechados, em ordem, alinhados ao timeframe. Dados insuficientes,
atrasados, lacunas e inconsistências resultam em UNKNOWN, sem inventar RANGE.
Estado repetido no mesmo candle não avança confirmação; alteração de candle já fechado
é rejeitada. Os limites da faixa são fixados no instante em que ela é detectada, sem
usar observações posteriores. Cada snapshot preserva estado, features, versão e hash.

`RegimeConfig` concentra todos os parâmetros: janela, persistência, aceitação e expiração,
progresso direcional, sobreposição, alternância, novos extremos, testes nas bordas,
localização, buffer e largura mínima. Os valores iniciais estão em código versionado,
visíveis na configuração/hash de cada replay (`--regime-config arquivo.json`) e em `needs_review`. São hipóteses de pesquisa;
os testes sintéticos verificam funcionamento e causalidade, não calibram limiares para EUR/USD.
O campo STABLE significa persistência descritiva, não aprovação do modelo.

## Eventos e transições

- Range exige múltiplos fatos de negociação bilateral; falta de tendência isolada não basta.
- Tendência exige progresso e novos extremos persistentes em candles distintos.
- Faixa tem estágios DEVELOPING, ESTABLISHED e BREAKOUT_ATTEMPT.
- Sair da faixa cria uma tentativa. Continuidade e fechamentos posteriores fora dela são
  necessários para aceitação; a passagem inicial é TRANSITION, antes de TREND.
- Retorno aos limites congelados registra falha e invalida a transição; aceitação também
  pode falhar posteriormente. Prazos expiram observações não confirmadas.
- Perda de direção produz transição; equilíbrio persistente pode confirmar RANGE.

`MarketRegimeState`, `RangeContext`, `MarketLocation`, `RegimeTransition` e
`BreakoutObservation` são imutáveis nos snapshots. O estado interno avança apenas em nova
barra fechada; não altera payloads anteriores nem utiliza o resultado financeiro.

## Estratégias, memória e pesquisa

`StrategyMetadata` declara regimes permitidos/proibidos, transições, direção, confirmação,
localização e dados. A estratégia experimental `research_breakout_retest`, versão `3.0-v4`,
continua restrita a TREND. RANGE gera REGIME_MISMATCH; UNKNOWN gera espera. Uma hipótese
pendente incompatível é cancelada antes de confirmação ou risco. Não foram criadas
estratégias operacionais de faixa, reversão ou transição por essa alteração.

Snapshots e decisões usam contrato 4; o journal físico PostgreSQL continua schema 3,
pois a extensão está nos payloads. Experiências e resultados herdam o contexto congelado
na decisão. Recuperação compara regime, versão/hash do classificador, estratégia e corte
temporal. Dados antigos não são relabelados. O catálogo sincroniza versões ao PostgreSQL.

`regime_performance.json` mantém coortes separadas por estratégia, regime, símbolo,
timeframe, sessão e versão/hash. Expectativa, taxa de acerto, payoff e profit factor
são descritivos, com piso amostral; MAE/MFE e custos só aparecem quando atribuídos.
Drawdown da conta por coorte e estabilidade estatística permanecem não estabelecidos.
O HypothesisLab enumera perguntas sobre redundância, limiares, transições, classificação
e degradação da estratégia. Nenhuma matriz autoriza promoção automática.

## Referência conferida

*Operando Price Action: Lateralidades*, Al Brooks, é um PDF digitalizado de 688 páginas.
Foram conferidos trechos selecionados, não o livro inteiro:

| Trecho | Aprendizado aplicado |
| --- | --- |
| Parte I, p. 41 / PDF 81; cap. 3, p. 97 / PDF 137 | Saída e continuidade são observações diferentes. |
| Cap. 5, p. 111 / PDF 151 | Falha, retorno e teste do rompimento precisam de sequência temporal. |
| Parte III, p. 205 / PDF 245 | Correção/lateralidade dependem do horizonte observado. |
| Parte IV, pp. 365–366 / PDF 405–406 | Negociação bilateral, alternância e incerteza distinguem contexto de faixa. |
| Cap. 22, p. 421 / PDF 461 | Faixas estreitas merecem critérios próprios e atenção aos custos. |

As probabilidades e interpretações sobre participantes do livro não foram transportadas
para o código. O motor registra fatos OHLC e hipóteses descritivas. Quatro conceitos novos
ficam needs_review; catálogo total: 21. Proveniência e hash em `data/knowledge/sources.json`.

Veja [Prompt Mestre V4](PROMPT_MESTRE_V4.md) e [PostgreSQL](postgresql.md).
