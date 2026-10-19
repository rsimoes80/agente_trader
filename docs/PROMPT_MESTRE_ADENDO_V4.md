# Adendo V4

## PROCESSO MENTAL OPERACIONAL DO AGENTE

1. **OBSERVE** — O que o preço está fazendo?
2. **CLASSIFY REGIME** — Estamos em TREND, RANGE, TRANSITION ou UNKNOWN?
3. **LOCATE** — Onde o preço está dentro desse regime?
4. **CLASSIFY TREND** — Se houver tendência relevante, como ela se organiza entre os timeframes?
5. **READ STRUCTURE** — Qual estrutura está efetivamente confirmada?
6. **READ PRICE ACTION** — Como o preço está se comportando barra a barra?
7. **MAP LEVELS** — Quais níveis estruturais são relevantes?
8. **COLLECT EVIDENCE** — Quais evidências são favoráveis, contrárias ou invalidantes?
9. **SELECT ELIGIBLE STRATEGIES** — Quais estratégias são compatíveis com o regime?
10. **REMEMBER** — Existem experiências realmente comparáveis neste mesmo regime?
11. **FORM HYPOTHESIS** — Qual hipótese falsificável explica o cenário?
12. **DEFINE EXPECTATION** — O que deve acontecer se a hipótese estiver correta?
13. **WAIT** — O comportamento esperado apareceu?
14. **CONFIRM** — A evidência confirmou a hipótese?
15. **TRIGGER** — O evento operacional definido ocorreu?
16. **VALIDATE RISK** — A operação ainda é aceitável?
17. **ACT OR WAIT** — BUY, SELL, WAIT ou NO_TRADE, conforme ambiente autorizado.
18. **MANAGE** — O regime e a hipótese continuam válidos?
19. **REVIEW** — O processo foi correto independentemente do P&L?
20. **LEARN** — Há evidência suficiente para uma nova hipótese de pesquisa?

## REGIME, ELEGIBILIDADE E MEMÓRIA — CONTRATO V4

Ordem normativa: MarketDataProvider → DataQuality → SessionEngine → MarketRegimeEngine
→ MarketLocation inicial → TrendHierarchyEngine → Structure → PriceAction → Levels/Liquidity
→ MarketLocation enriquecida → Evidence → StrategyMetadata/Eligibility → ExperienceMemory
→ Hypothesis → ExpectedVsObserved → Confirmation → Trigger → Risk → Execution ou NO_TRADE.
Nenhuma busca de setup deve ocorrer em regime incompatível ou UNKNOWN. Localização inicial usa
limites já observados; níveis estruturais posteriores enriquecem a localização sem reclassificar o passado.
Regimes são relativos ao timeframe. Por padrão o contexto é o timeframe de contexto da hierarquia;
direcionalidade menor não determina o regime maior. Registrar todos os horizontes disponíveis.
O journal compartilhado é PostgreSQL; SQLite só mediante seleção explícita offline.
Snapshots/experiências V4 acrescentam payloads aos registros existentes, preservando schema físico 3.
Registros V3 não recebem rótulos retroativos. Classificador e parâmetros possuem versão/hash próprios.
Parâmetros iniciais e conceitos novos ficam needs_review; taxonomia, estabilidade descritiva e gates
não demonstram vantagem estatística. TEST e PROMOTE continuam obrigatórios no pipeline offline,
com out-of-sample, walk-forward, robustez e aprovação; nenhuma promoção automática.
ALLOW_ORDER_EXECUTION=false; ALLOW_LIVE_TRADING=false.

==================================================
MARKET REGIME ENGINE
==================================================

Crie um componente central chamado MarketRegimeEngine.

O MarketRegimeEngine deverá executar antes do TrendHierarchyEngine e antes da seleção de qualquer estratégia.

Pergunta fundamental:

“EM QUE TIPO DE MERCADO ESTAMOS AGORA?”

O agente não poderá assumir que existe uma tendência simplesmente porque consegue identificar movimentos direcionais em um timeframe menor.

O MarketRegimeEngine deve distinguir contexto/regime antes de procurar setups.

Fluxo obrigatório:

MarketDataProvider
→ DataQuality
→ SessionEngine
→ MarketRegimeEngine
→ TrendHierarchyEngine
→ MarketStructureEngine
→ PriceActionReader
→ SupportResistanceEngine
→ LiquidityMap
→ EvidenceEngine
→ MarketSnapshot
→ ExperienceMemory
→ HypothesisBuilder
→ ExpectedVsObservedEngine
→ DecisionEngine
→ RiskManager
→ ExecutionEngine

Nenhuma estratégia poderá ser avaliada antes da classificação de regime.

==================================================
1. RESPONSABILIDADE
==================================================

O MarketRegimeEngine deverá:

- identificar se o mercado apresenta características direcionais ou de equilíbrio;
- identificar lateralização;
- identificar possível transição entre lateralização e tendência;
- identificar possível transição entre tendência e lateralização;
- analisar a estabilidade do regime;
- identificar incerteza de classificação;
- fornecer contexto ao restante do agente;
- impedir estratégias incompatíveis com o regime observado.

O MarketRegimeEngine:

- não envia ordens;
- não calcula lotes;
- não define stop;
- não define alvo;
- não escolhe entrada;
- não promove estratégia;
- não modifica configuração;
- não contorna o RiskManager.

Ele apenas classifica contexto/regime com evidências observáveis.

==================================================
2. REGIMES PRIMÁRIOS
==================================================

Comece com três estados principais:

TREND
RANGE
TRANSITION

Permita também:

UNKNOWN

Não force classificação quando os dados não forem suficientes.

Estrutura inicial:

MarketRegime:

UNKNOWN

TREND
├── BULL
└── BEAR

RANGE
├── DEVELOPING
├── ESTABLISHED
└── BREAKOUT_ATTEMPT

TRANSITION
├── TREND_TO_RANGE
├── RANGE_TO_TREND
└── UNRESOLVED

Esses estados são abstrações do sistema e deverão ser validados empiricamente.

Não trate essa taxonomia como verdade universal do mercado.

==================================================
3. REGIME OBJECT
==================================================

Produza:

MarketRegimeState:
- regime_id
- snapshot_id
- timestamp_utc
- symbol
- timeframe
- session
- regime
- subtype
- direction
- previous_regime
- transition_status
- maturity
- stability
- directional_progress
- overlap_behavior
- breakout_behavior
- follow_through_behavior
- balance_state
- range_state
- trend_state
- evidence_ids
- conflicting_evidence_ids
- invalidating_evidence_ids
- missing_data
- classification_quality
- classification_status
- detected_at
- last_updated_at
- expires_at

Valores permitidos para regime:

- UNKNOWN
- TREND
- RANGE
- TRANSITION

Valores permitidos para direction:

- BULLISH
- BEARISH
- NEUTRAL
- UNDEFINED

Valores permitidos para classification_status:

- INSUFFICIENT_DATA
- DEVELOPING
- PROVISIONAL
- STABLE
- WEAKENING
- CHANGING
- INVALIDATED

==================================================
4. RANGE CONTEXT
==================================================

Crie uma estrutura dedicada:

RangeContext:
- range_id
- symbol
- timeframe
- detected_at
- upper_boundary
- lower_boundary
- midpoint
- range_width
- range_duration
- position_inside_range
- internal_structure
- boundary_test_count
- upper_break_attempts
- lower_break_attempts
- failed_breakouts
- accepted_breakouts
- volatility_state
- overlap_state
- directional_progress
- evidence_ids
- status

Valores de position_inside_range:

- UPPER_AREA
- MIDDLE_AREA
- LOWER_AREA
- OUTSIDE_ABOVE
- OUTSIDE_BELOW
- UNDEFINED

Os nomes acima são abstrações de software.

Não assuma qualquer vantagem operacional desses locais antes de validação.

==================================================
5. MARKET LOCATION
==================================================

Crie:

MarketLocation:
- regime
- timeframe
- relative_location
- nearest_support
- nearest_resistance
- nearest_range_boundary
- nearest_structural_level
- distance_to_boundary
- distance_to_structural_level
- location_quality

A interpretação da mesma evidência deve poder mudar conforme:

- regime;
- timeframe;
- localização;
- sessão;
- estrutura maior.

Nunca interprete um padrão de Price Action isoladamente do MarketLocation.

==================================================
6. DETECÇÃO DE RANGE
==================================================

O agente deverá procurar evidências observáveis de equilíbrio/lateralização.

Features candidatas:

- perda de progresso direcional;
- aumento de overlap;
- alternância frequente de direção;
- ausência de sequência estrutural clara;
- repetidas interações com uma mesma região;
- falha de continuação;
- rompimentos sem confirmação;
- contração relativa do deslocamento;
- estabilização dentro de limites observáveis;
- redução de clareza direcional.

Essas features são candidatas de engenharia.

Elas não devem ser consideradas regras lucrativas até serem validadas pelo HypothesisLab.

Não crie:

if overlap > valor_arbitrario:
    regime = RANGE

Todos os thresholds deverão ser:

- configuráveis;
- versionados;
- testados;
- específicos quando necessário por símbolo/timeframe;
- aprovados via pipeline de pesquisa.

==================================================
7. DETECÇÃO DE TREND
==================================================

TREND deverá depender de evidências observáveis de desequilíbrio direcional.

Features candidatas:

- progressão estrutural persistente;
- deslocamento direcional;
- novos extremos;
- continuidade após rompimentos;
- correções que não invalidam estrutura;
- redução do overlap;
- expansão direcional;
- follow-through consistente;
- alinhamento com estrutura superior.

TrendHierarchyEngine continua responsável por determinar:

- direção;
- hierarquia;
- relação entre timeframes.

MarketRegimeEngine responde apenas:

“Esse ambiente apresenta características suficientes de regime TREND?”

TrendHierarchyEngine responde:

“Caso apresente, qual direção e como as tendências se relacionam?”

==================================================
8. TRANSITION REGIME
==================================================

TRANSITION é um regime de primeira classe.

Não trate transição como erro de classificação.

Exemplos conceituais:

TREND
→ perda de continuidade
→ aumento de overlap
→ falhas sequenciais
→ TRANSITION
→ RANGE

e:

RANGE
→ breakout attempt
→ confirmação
→ follow-through
→ aceitação fora do range
→ TRANSITION
→ TREND

Crie:

RegimeTransition:
- transition_id
- from_regime
- candidate_regime
- started_at
- trigger_observation
- confirming_evidence
- conflicting_evidence
- confirmation_requirements
- invalidation_requirements
- status

Valores de status:

- SUSPECTED
- DEVELOPING
- PARTIALLY_CONFIRMED
- CONFIRMED
- FAILED
- EXPIRED

==================================================
9. REGIME TRANSITION DETECTOR
==================================================

Crie um componente interno:

RegimeTransitionDetector

Responsável por detectar:

TREND_TO_RANGE
RANGE_TO_TREND
FAILED_RANGE_BREAKOUT
FAILED_TREND_CONTINUATION

Não converta automaticamente:

BREAKOUT
→ TREND

Fluxo obrigatório:

breakout
→ observe follow-through
→ compare expected vs observed
→ evaluate acceptance/rejection
→ classify transition

Breakout sem confirmação pode permanecer:

RANGE / BREAKOUT_ATTEMPT

ou:

TRANSITION / UNRESOLVED

==================================================
10. BREAKOUT CONTRACT
==================================================

Quando o preço deixar uma faixa, crie:

BreakoutObservation:
- breakout_id
- range_id
- direction
- breakout_level
- breakout_timestamp
- displacement
- close_location
- follow_through
- retest_status
- return_inside_range
- evidence_ids
- current_status

Valores de current_status:

- ATTEMPT
- DEVELOPING
- CONFIRMED
- FAILED
- RETURNED_TO_RANGE
- EXPIRED

Um breakout não é automaticamente oportunidade de trade.

==================================================
11. EVIDENCE ENGINE + REGIME
==================================================

Toda Evidence deverá carregar:

- regime_id
- regime
- regime_subtype
- market_location
- regime_stability

A mesma observação poderá possuir interpretação diferente em regimes diferentes.

Portanto:

PATTERN
≠
EVIDENCE BY ITSELF

O correto é:

PATTERN
+
REGIME
+
LOCATION
+
STRUCTURE
+
TIMEFRAME
=
CONTEXTUALIZED EVIDENCE

Mesmo assim:

CONTEXTUALIZED EVIDENCE
≠
TRADE

==================================================
12. REGIME-AWARE STRATEGIES
==================================================

Toda estratégia deverá declarar:

StrategyMetadata:
- strategy_id
- version
- allowed_regimes
- prohibited_regimes
- allowed_transitions
- direction_requirements
- confirmation_requirements
- location_requirements
- data_requirements

Exemplo conceitual:

pullback_trend:
    allowed_regimes:
      - TREND

range_strategy:
    allowed_regimes:
      - RANGE

breakout_strategy:
    allowed_regimes:
      - TRANSITION

reversal_strategy:
    allowed_regimes:
      - TRANSITION

Não presuma que essas estratégias possuem vantagem.

São categorias para organização e testes.

==================================================
13. REGIME MISMATCH
==================================================

Se uma estratégia não for compatível com o regime:

StrategyEvaluation:
    status = REJECTED
    reason = REGIME_MISMATCH

Registre no ExperienceMemory.

Exemplo:

strategy = TREND_PULLBACK
regime = RANGE

Resultado:

NO_TRADE
reason = REGIME_MISMATCH

O agente não deve tentar reinterpretar o RANGE como TREND para habilitar a estratégia.

==================================================
14. REGIME UNKNOWN
==================================================

UNKNOWN é válido.

Se:

- evidências insuficientes;
- dados conflitantes;
- timeframe inadequado;
- range ainda não definido;
- tendência ainda não estabelecida;
- transição ambígua;

retorne:

regime = UNKNOWN

action = WAIT

UNKNOWN nunca deverá ser convertido arbitrariamente em RANGE.

UNKNOWN também nunca deverá ser convertido arbitrariamente em TREND.

==================================================
15. RANGE NÃO SIGNIFICA TRADE
==================================================

Detectar RANGE não autoriza nenhuma operação.

RANGE apenas permite que estratégias de RANGE aprovadas sejam avaliadas.

A sequência continuará:

RANGE
→ MarketLocation
→ PriceAction
→ Structure
→ Evidence
→ Hypothesis
→ ExpectedVsObserved
→ Trigger
→ RiskManager

Somente depois:

BUY / SELL / NO_TRADE

==================================================
16. RANGE E NO_TRADE
==================================================

Crie motivos explícitos de NO_TRADE:

- RANGE_NOT_ESTABLISHED
- RANGE_TOO_NARROW
- RANGE_TOO_UNSTABLE
- RANGE_LOCATION_UNFAVORABLE
- BREAKOUT_ATTEMPT_UNCONFIRMED
- FAILED_BREAKOUT_UNRESOLVED
- TRANSITION_UNCLEAR
- REGIME_MISMATCH
- REGIME_UNKNOWN
- INSUFFICIENT_EVIDENCE
- RISK_REJECTED

Os critérios quantitativos relacionados aos motivos acima devem permanecer configuráveis e pesquisáveis.

==================================================
17. MARKET SNAPSHOT V4
==================================================

Atualize MarketSnapshot:

MarketSnapshot:
- snapshot_id
- timestamp_utc
- symbol
- session

- data_quality
- data_freshness

# REGIME

- market_regime_id
- regime
- regime_subtype
- regime_maturity
- regime_stability
- previous_regime
- transition_status

# LOCATION

- market_location
- range_id
- range_position
- upper_boundary
- lower_boundary
- nearest_structural_level

# TREND

- macro_trend
- context_trend
- structure_trend
- execution_trend
- trend_alignment
- reversal_status

# STRUCTURE

- market_structure
- swing_structure
- dominant_swing

# PRICE ACTION

- price_action
- impulse_state
- correction_state
- overlap_state
- follow_through_status
- breakout_status

# CONTEXT

- support_levels
- resistance_levels
- liquidity_map
- volume_context
- momentum_context
- volatility_regime

# EVIDENCE

- evidence_set_id
- evidence_status
- favorable_evidence
- conflicting_evidence
- invalidating_evidence
- missing_evidence

# OUTPUT

- market_narrative
- clarity_status
- observation_status
- expires_at

==================================================
18. EXPERIENCE MEMORY V4
==================================================

Acrescente ao ExperienceRecord:

- regime_id
- regime
- regime_subtype
- regime_maturity
- regime_stability
- previous_regime
- market_location
- range_id
- range_position
- transition_status
- breakout_status
- regime_match
- strategy_regime_compatibility

Isso permitirá posteriormente pesquisar:

- performance da estratégia em TREND;
- performance em RANGE;
- performance em TRANSITION;
- trades executados durante UNKNOWN;
- sinais rejeitados por REGIME_MISMATCH;
- oportunidades após transições;
- failed breakouts;
- breakouts confirmados;
- NO_TRADE por regime inadequado.

==================================================
19. HYPOTHESIS LAB V4
==================================================

Permita ao HypothesisLab investigar:

- quais features realmente distinguem TREND de RANGE?
- quais features são redundantes?
- quais thresholds são estáveis?
- a classificação varia por símbolo?
- a classificação varia por timeframe?
- a classificação varia por sessão?
- quanto tempo normalmente dura cada regime?
- quais transições são mais difíceis de classificar?
- breakout + follow-through possui informação adicional?
- retorno para dentro do range após breakout possui utilidade?
- RANGE DEVELOPING deve ser tratado diferente de RANGE ESTABLISHED?
- quais estratégias degradam ao mudar de regime?
- REGIME_MISMATCH reduz trades ruins?
- UNKNOWN frequente significa falta de dados ou classificador conservador?

Todas essas perguntas são hipóteses.

Não codifique suas respostas como fatos.

==================================================
20. REGIME PERFORMANCE MATRIX
==================================================

Após backtests suficientes, produza:

StrategyRegimePerformance:
- strategy_id
- strategy_version
- regime
- symbol
- timeframe
- session
- sample_size
- expectancy_r
- win_rate
- payoff
- profit_factor
- max_drawdown
- mae
- mfe
- costs
- stability
- validation_status

Não use essas métricas para promoção automática.

Não confunda correlação entre regime e resultado com causalidade.

==================================================
21. NOVAS PROIBIÇÕES
==================================================

Proibido:

- assumir que mercado está sempre em tendência;
- assumir que mercado está sempre em range;
- operar antes de classificar regime;
- forçar classificação para habilitar estratégia;
- considerar breakout como tendência automaticamente;
- considerar CHoCH isoladamente como mudança completa de regime;
- considerar um candle direcional como tendência;
- considerar ausência de tendência automaticamente como range;
- criar thresholds arbitrários escondidos no código;
- usar classificação futura para corrigir regime passado;
- alterar retrospectivamente regime em backtests;
- usar candles futuros para definir limites atuais da faixa;
- usar look-ahead na confirmação do breakout;
- selecionar estratégia antes da classificação do regime;
- permitir que ExperienceMemory altere regime;
- permitir que HypothesisLab altere classificador live durante sessão.

==================================================
22. TESTES
==================================================

MarketRegimeEngine:

- detecta candidato TREND;
- detecta candidato RANGE;
- retorna UNKNOWN quando necessário;
- detecta TREND_TO_RANGE;
- detecta RANGE_TO_TREND;
- diferencia breakout attempt de breakout confirmado;
- identifica failed breakout;
- não usa candles futuros;
- classifica deterministicamente;
- respeita timeframe;
- respeita dados ausentes.

RegimeTransitionDetector:

- RANGE → breakout attempt;
- breakout → failed;
- breakout → confirmed;
- confirmed breakout → TREND candidate;
- TREND → weakening;
- TREND → TRANSITION;
- TRANSITION → RANGE.

Strategy compatibility:

- TREND strategy + TREND → evaluate;
- TREND strategy + RANGE → reject;
- RANGE strategy + RANGE → evaluate;
- RANGE strategy + TREND → reject;
- UNKNOWN → WAIT;
- TRANSITION strategy não autorizada → reject.

Experience:

- registra regime correto no momento da decisão;
- não altera regime depois de conhecer o resultado;
- preserva versão do classificador;
- registra REGIME_MISMATCH.

==================================================
23. VERSIONAMENTO
==================================================

MarketRegimeEngine deverá possuir versão independente:

regime_model_version

Exemplo:

regime_model_version = "0.1.0-research"

Cada MarketSnapshot deverá registrar essa versão.

Cada backtest deverá registrar essa versão.

Cada ExperienceRecord deverá registrar essa versão.

Nunca compare resultados de versões diferentes sem identificá-las explicitamente.

==================================================
24. ARQUITETURA V4
==================================================

src/
  market_data/
  mt5_gateway/

  observation/
    market_observer.py
    market_snapshot.py
    market_narrative.py

  sessions/
    session_engine.py

  regime/
    market_regime_engine.py
    market_regime_state.py
    regime_transition_detector.py
    range_context.py
    breakout_observation.py
    market_location.py

  trend/
    trend_hierarchy_engine.py
    trend_state.py
    trend_alignment.py

  structure/
    market_structure_engine.py
    swing_engine.py

  price_action/
    price_action_reader.py
    price_action_observation.py

  levels/
    support_resistance_engine.py
