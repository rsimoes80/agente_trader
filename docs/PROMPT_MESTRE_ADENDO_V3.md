# Integração V3 ao prompt mestre

## PROCESSO MENTAL OPERACIONAL DO AGENTE

1. **OBSERVE** — O que o mercado está fazendo?
2. **CONTEXTUALIZE** — Em que sessão, regime e estrutura isso ocorre?
3. **CLASSIFY TREND** — Qual é a tendência relevante em cada timeframe?
4. **READ PRICE ACTION** — Como o preço está se comportando?
5. **MAP LEVELS** — Onde estão os níveis estruturais relevantes?
6. **COLLECT EVIDENCE** — Quais fatos favorecem alta, baixa ou neutralidade?
7. **IDENTIFY CONFLICTS** — Quais fatos contradizem a narrativa predominante?
8. **REMEMBER** — Já ocorreram situações verdadeiramente comparáveis?
9. **FORM HYPOTHESIS** — Qual cenário falsificável pode ser formulado a partir dos dados?
10. **DEFINE EXPECTATION** — O que precisa acontecer para confirmar a hipótese?
11. **WAIT** — O comportamento esperado realmente apareceu?
12. **CONFIRM** — A hipótese ganhou confirmação suficiente?
13. **TRIGGER** — O gatilho definido ocorreu?
14. **VALIDATE RISK** — A operação continua aceitável depois de custos e risco?
15. **ACT OR WAIT** — BUY, SELL ou NO_TRADE, conforme ambiente autorizado.
16. **MANAGE** — A hipótese permanece válida após a entrada?
17. **REVIEW** — Quais foram o resultado financeiro e a qualidade do processo?
18. **LEARN** — Existe evidência suficiente para formular uma hipótese de melhoria?
19. **TEST** — A hipótese sobrevive a backtest, out-of-sample, walk-forward e robustez?
20. **PROMOTE** — Somente uma versão validada e aprovada pode substituir a anterior.

O agente não tem obrigação de chegar ao passo 15. WAIT, MONITOR e NO_TRADE são resultados corretos.
Contexto, evidência, confluência, confirmação, gatilho e autorização de risco são contratos distintos.
Uma quebra parcial não confirma uma reversão completa; fatos contrários permanecem registrados.
ALLOW_ORDER_EXECUTION=false. ALLOW_LIVE_TRADING=false. Nesta etapa, ACT significa somente sinal
hipotético e simulação offline. O ExecutionEngine operacional é futuro; o componente existente é o
ExecutionSimulator, que não tem gateway de ordens. Nenhum conceito dos livros concede autorização.

Insira o bloco abaixo depois de MarketObserver e antes de ExperienceMemory. A versão integral já consolidada está em PROMPT_MESTRE_V3.md.

==================================================
MARKET INTELLIGENCE LAYER
==================================================

Expanda o MarketObserver criando quatro componentes independentes:

1. TrendHierarchyEngine
2. PriceActionReader
3. SupportResistanceEngine
4. EvidenceEngine

Esses componentes formam a camada analítica do agente.

Nenhum desses componentes poderá:

- enviar ordens;
- aumentar exposição;
- alterar stop;
- calcular autorização final de lote;
- modificar estratégia em produção;
- contornar o RiskManager;
- promover hipóteses;
- interpretar uma evidência isolada como autorização de trade.

Fluxo obrigatório:

MarketData
→ MarketObserver
→ TrendHierarchyEngine
→ PriceActionReader
→ SupportResistanceEngine
→ EvidenceEngine
→ MarketNarrative
→ ExperienceMemory
→ HypothesisBuilder
→ ExpectedVsObservedEngine
→ DecisionEngine
→ RiskManager
→ ExecutionEngine

Os quatro novos componentes devem produzir dados estruturados e auditáveis.

==================================================
A. TREND HIERARCHY ENGINE
==================================================

Crie um componente chamado TrendHierarchyEngine.

Objetivo:

determinar como as tendências existentes em diferentes timeframes se relacionam, evitando que um movimento de curto prazo seja confundido automaticamente com uma mudança da tendência maior.

O componente deve trabalhar com timeframes configuráveis.

Nunca fixe universalmente H4, H1, M15 ou M5 no código.

Permita configurar:

- macro_timeframe;
- context_timeframe;
- structure_timeframe;
- execution_timeframe.

--------------------------------------------------
A.1 Trend State
--------------------------------------------------

Para cada timeframe produza:

TrendState:
- timeframe
- timestamp_utc
- direction
- state
- structure
- last_confirmed_high
- last_confirmed_low
- dominant_swing
- impulse_direction
- correction_direction
- structure_break_status
- reversal_status
- maturity_status
- evidence_status
- parent_timeframe
- relationship_with_parent
- data_quality

Valores permitidos para direction:

- bullish
- bearish
- neutral
- undefined

Valores permitidos para state:

- UNKNOWN
- POTENTIAL_BULL
- BULL_CONFIRMED
- BULL_WEAKENING
- TRANSITION
- POTENTIAL_BEAR
- BEAR_CONFIRMED
- BEAR_WEAKENING
- RANGE

Valores permitidos para reversal_status:

- none
- early_warning
- partial_reversal
- confirmed_reversal
- failed_reversal

Nunca transforme automaticamente uma única quebra de swing em confirmação completa de reversão.

--------------------------------------------------
A.2 Relação entre tendências
--------------------------------------------------

Classifique a relação entre cada timeframe:

- ALIGNED;
- CORRECTING_PARENT;
- COUNTER_TREND;
- TRANSITIONING;
- RANGE_INSIDE_TREND;
- CONFLICTING;
- INSUFFICIENT_DATA.

Exemplo:

context_timeframe:
  direction: bullish

structure_timeframe:
  direction: bullish
  relationship: ALIGNED

execution_timeframe:
  direction: bearish
  relationship: CORRECTING_PARENT

Isso não deve ser classificado simplesmente como:

BEARISH MARKET.

O agente deverá entender que movimentos menores podem representar correções dentro de estruturas maiores.

--------------------------------------------------
A.3 Mudança de tendência
--------------------------------------------------

Utilize progressão estrutural para analisar:

Bullish:
- higher highs;
- higher lows.

Bearish:
- lower highs;
- lower lows.

Transição:
- falha em continuar a estrutura anterior;
- quebra parcial;
- conflito entre topos e fundos;
- mudança ainda não confirmada.

Uma quebra parcial deve gerar:

EARLY_WARNING

ou:

PARTIAL_REVERSAL

e não:

CONFIRMED_REVERSAL

sem evidência adicional exigida pela estratégia.

--------------------------------------------------
A.4 Trend Alignment Matrix
--------------------------------------------------

Produza uma matriz:

TrendAlignment:
- macro_direction
- context_direction
- structure_direction
- execution_direction
- alignment_status
- dominant_direction
- countertrend_risk
- transition_risk
- trade_direction_class

Valores de trade_direction_class:

- WITH_TREND
- COUNTER_TREND
- RANGE
- TRANSITION
- UNDEFINED

Cada estratégia deverá declarar explicitamente quais classes aceita.

Exemplo:

pullback:
  allowed_direction_classes:
    - WITH_TREND

reversal:
  allowed_direction_classes:
    - TRANSITION

range_strategy:
  allowed_direction_classes:
    - RANGE

Estratégias COUNTER_TREND deverão exigir critérios adicionais configuráveis e validados por backtest.

Não invente uma penalidade fixa para contratrend.

==================================================
B. PRICE ACTION READER
==================================================

Crie um componente chamado PriceActionReader.

Objetivo:

converter OHLC, ticks disponíveis, estrutura e sequência de candles em observações objetivas sobre o comportamento do preço.

O PriceActionReader não deve prever o próximo candle.

Ele deve descrever o que efetivamente aconteceu.

--------------------------------------------------
B.1 Observações
--------------------------------------------------

Analise:

- OHLC;
- tamanho absoluto das barras;
- tamanho relativo;
- range;
- corpo;
- pavios;
- fechamento dentro do range;
- sequência de candles;
- expansão;
- contração;
- impulso;
- correção;
- overlap;
- rompimento;
- reteste;
- falha de rompimento;
- gaps;
- velocidade;
- progressão;
- desaceleração;
- aceleração;
- distância percorrida;
- distância entre swings;
- continuidade;
- falta de continuidade.

Quando houver volume válido, permita associação posterior pelo EvidenceEngine.

--------------------------------------------------
B.2 PriceActionObservation
--------------------------------------------------

Produza:

PriceActionObservation:
- observation_id
- timestamp_utc
- symbol
- timeframe
- bar_count
- directional_pressure
- impulse_state
- correction_state
- expansion_state
- overlap_state
- breakout_status
- retest_status
- failure_status
- swing_progression
- momentum_behavior
- volatility_behavior
- candle_sequence_features
- continuation_evidence
- exhaustion_evidence
- reversal_evidence
- conflicting_evidence
- data_quality

Não atribua intenções psicológicas não observáveis.

Não use:

“os bancos querem comprar”.

Use:

“houve rompimento seguido por deslocamento comprador”.

Não use:

“market makers estão caçando stops”.

Use:

“o preço ultrapassou a mínima anterior e retornou posteriormente para dentro da faixa”.

--------------------------------------------------
B.3 Price action não é gatilho automaticamente
--------------------------------------------------

Um padrão de candle nunca deve produzir diretamente:

BUY
SELL

A sequência deve ser:

PriceActionObservation
→ Context
→ EvidenceEngine
→ Hypothesis
→ ExpectedVsObserved
→ Trigger Validation
→ RiskManager

Price Action fora de contexto deve ser classificada apenas como observação.

--------------------------------------------------
B.4 Falhas e ausência de continuidade
--------------------------------------------------

Dê atenção especial às situações:

expected_continuation
→ continuation_failed

breakout
→ no_follow_through

impulse
→ decreasing_progress

new_extreme
→ immediate_rejection

strong_context
→ weak_response

Armazene essas situações para comparação posterior pelo ExpectedVsObservedEngine.

==================================================
C. SUPPORT RESISTANCE ENGINE
==================================================

Crie um componente chamado SupportResistanceEngine.

Objetivo:

identificar zonas historicamente relevantes onde o comportamento do mercado tenha produzido interações observáveis.

Não trate suporte e resistência como preços matemáticos exatos por padrão.

Modele-os como zonas quando apropriado.

--------------------------------------------------
C.1 Fontes de nível
--------------------------------------------------

O componente poderá considerar:

- swing highs confirmados;
- swing lows confirmados;
- máximas e mínimas de sessão;
- máximas e mínimas anteriores;
- áreas repetidamente testadas;
- congestões;
- rompimentos anteriores;
- regiões rompidas e posteriormente testadas;
- extremos de ranges;
- zonas estruturais;
- níveis derivados de estratégias autorizadas.

Cada nível deve registrar a origem.

--------------------------------------------------
C.2 PriceLevel
--------------------------------------------------

Crie:

PriceLevel:
- level_id
- symbol
- timeframe
- level_type
- lower_bound
- upper_bound
- origin
- created_at_utc
- first_touch
- last_touch
- test_count
- breakout_status
- retest_status
- role
- parent_structure
- source_rule_ids
- status

Valores de role:

- support
- resistance
- structural_high
- structural_low
- range_high
- range_low
- breakout_level
- retest_zone
- liquidity_reference
- neutral_reference

Não atribua força probabilística baseada somente no número de toques sem validação empírica.

--------------------------------------------------
C.3 Contexto do nível
--------------------------------------------------

O nível não é sinal.

A saída deve responder:

- onde está o preço;
- qual nível está próximo;
- de qual timeframe veio;
- qual a função histórica;
- se houve rompimento;
- se houve reteste;
- se o nível conflita com outro timeframe;
- qual é a distância até o nível;
- se o nível interfere no alvo;
- se o nível interfere na relação risco-retorno.

==================================================
D. EVIDENCE ENGINE
==================================================

Crie um componente chamado EvidenceEngine.

Este componente é crítico.

Sua responsabilidade será agregar evidências independentes do mercado sem permitir que um único indicador, padrão ou conceito autorize a operação.

Princípio:

INDICADOR ≠ DECISÃO

PADRÃO ≠ DECISÃO

ZONA ≠ DECISÃO

CONFLUÊNCIA ≠ GATILHO

GATILHO ≠ AUTORIZAÇÃO DE RISCO

--------------------------------------------------
D.1 Evidence Object
--------------------------------------------------

Toda evidência deve tornar-se:

Evidence:
- evidence_id
- timestamp_utc
- symbol
- timeframe
- category
- source_component
- source_rule_id
- direction
- observation
- status
- quality
- relevance
- conflicts_with
- expires_at
- data_reference

Categorias:

- trend;
- structure;
- price_action;
- support_resistance;
- liquidity;
- volume;
- momentum;
- volatility;
- session;
- location;
- confirmation;
- execution;
- expected_vs_observed;
- risk_environment.

Valores de direction:

- bullish
- bearish
- neutral

Valores de status:

- supportive
- conflicting
- warning
- invalidating
- insufficient

Não gere probabilidades artificiais.

--------------------------------------------------
D.2 Evidence Set
--------------------------------------------------

Agrupe:

EvidenceSet:
- evidence_set_id
- snapshot_id
- symbol
- timestamp_utc
- bullish_evidence
- bearish_evidence
- neutral_evidence
- warnings
- invalidations
- missing_evidence
- conflicts
- dominant_evidence
- confluence_status
- confirmation_status
- evidence_quality
- valid_until

O mecanismo deve preservar evidências contrárias.

Nunca remova evidência contrária simplesmente porque a hipótese predominante é bullish ou bearish.

--------------------------------------------------
D.3 Confluência
--------------------------------------------------

Defina confluência como:

múltiplas evidências independentes coerentes com a mesma hipótese.

Não conte duas derivações do mesmo dado como evidências independentes.

Exemplo:

HH/HL detectado pelo StructureEngine

e

“bullish structure” calculado novamente com os mesmos HH/HL

não devem valer como duas evidências independentes.

Evite double counting.

--------------------------------------------------
D.4 Confluência, confirmação e gatilho
--------------------------------------------------

Implemente três conceitos diferentes:

CONFLUENCE:
o cenário possui múltiplas evidências coerentes.

CONFIRMATION:
o comportamento esperado começou a ocorrer.

TRIGGER:
um evento operacional específico e previamente definido ocorreu.

Fluxo:

CONTEXT
→ CONFLUENCE
→ HYPOTHESIS
→ EXPECTATION
→ CONFIRMATION
→ TRIGGER
→ RISK VALIDATION
→ EXECUTION

Nenhuma etapa substitui a seguinte.

--------------------------------------------------
D.5 Weight of Evidence
--------------------------------------------------

Inicialmente, implemente Weight of Evidence de forma categórica e explicável.

Estados:

- INSUFFICIENT;
- CONFLICTED;
- WEAK;
- DEVELOPING;
- SUPPORTIVE;
- STRONG_BUT_UNCONFIRMED;
- CONFIRMED;
- INVALIDATED.

Não invente pesos numéricos.

Não atribua:

“82% bullish”

sem modelo estatístico calibrado fora da amostra.

Qualquer sistema futuro de pesos deverá passar pelo HypothesisLab.

--------------------------------------------------
D.6 Evidence veto
--------------------------------------------------

Algumas evidências podem ser configuradas como invalidantes.

Exemplo:

- dados atrasados;
- estrutura principal invalidada;
- hipótese expirada;
- spread incompatível;
- invalidação estrutural;
- símbolo indisponível;
- discrepância de posição;
- regime incompatível com a estratégia.

Uma evidência invalidante deve impedir o envio da hipótese ao RiskManager enquanto permanecer ativa.

==================================================
E. INTEGRAÇÃO COM MARKET OBSERVER
==================================================

Atualize MarketObserver para conter:

MarketObserver
│
├── SessionEngine
├── TrendHierarchyEngine
├── MarketStructureEngine
├── PriceActionReader
├── SwingEngine
├── LiquidityMap
├── SupportResistanceEngine
├── VolumeContext
├── MomentumContext
├── VolatilityRegime
├── EvidenceEngine
└── MarketNarrative

MarketObserver continua sem permissão de execução.

--------------------------------------------------
E.1 MarketSnapshot V3
--------------------------------------------------

Expanda MarketSnapshot:

MarketSnapshot:
- snapshot_id
- timestamp_utc
- symbol
- session
- data_freshness
- data_quality

- macro_trend
- context_trend
- structure_trend
- execution_trend
- trend_alignment
- trend_state
- reversal_status

- market_structure
- swing_structure
- dominant_swing

- price_action
- impulse_state
- correction_state
- follow_through_status

- support_levels
- resistance_levels
- nearby_structural_levels

- liquidity_map

- volume_context
- momentum_context
- volatility_regime

- evidence_set_id
- evidence_status
- bullish_evidence
- bearish_evidence
- conflicting_evidence
- invalidating_evidence
- missing_evidence

- market_narrative
- clarity_status
- observation_status
- expires_at

==================================================
F. TREND STATE MACHINE
==================================================

Adicione uma máquina de estados específica de tendência:

UNKNOWN
→ POTENTIAL_BULL
→ BULL_CONFIRMED
→ BULL_WEAKENING
→ TRANSITION
→ POTENTIAL_BEAR
→ BEAR_CONFIRMED

e:

BEAR_CONFIRMED
→ BEAR_WEAKENING
→ TRANSITION
→ POTENTIAL_BULL
→ BULL_CONFIRMED

RANGE pode aparecer a partir de:

- UNKNOWN;
- BULL_WEAKENING;
- BEAR_WEAKENING;
- TRANSITION.

Não permita mudança:

BULL_CONFIRMED
→ BEAR_CONFIRMED

a partir de uma observação isolada sem satisfazer as regras de confirmação configuradas.

--------------------------------------------------
F.1 Estado TRANSITION
--------------------------------------------------

TRANSITION deve ser tratado com cautela especial.

Por padrão:

TRANSITION
→ WAIT ou NO_TRADE

Estratégias de reversão poderão operar TRANSITION somente quando:

- forem explicitamente autorizadas;
- possuírem expectativa definida;
- possuírem gatilho definido;
- tenham validação histórica;
- tenham aprovação para o ambiente atual.

==================================================
G. ATUALIZAÇÃO DO EXPECTED VS OBSERVED ENGINE
==================================================

Integre EvidenceEngine ao ExpectedVsObservedEngine.

Novo fluxo:

Hypothesis
→ ExpectationContract
→ MarketObservation
→ EvidenceSet
→ ExpectedVsObserved
→ hypothesis_status

Compare:

expected_trend_behavior
vs
observed_trend_behavior

expected_structure
vs
observed_structure

expected_price_action
vs
observed_price_action

expected_level_reaction
vs
observed_level_reaction

expected_momentum
vs
observed_momentum

expected_follow_through
vs
observed_follow_through

Estados:

- proposed
- monitoring
- developing_as_expected
- partially_confirmed
- confirmed
- weakening
- contradicted
- invalidated
- expired
- insufficient_data

--------------------------------------------------
G.1 Partial reversal
--------------------------------------------------

Implemente tratamento específico:

reversal_warning
→ partial_reversal
→ confirmation_required

Partial reversal nunca deve ser automaticamente promovida para confirmed reversal.

Exemplo conceitual:

bullish context
+
último HL rompido
+
ainda sem estrutura bearish confirmada

Resultado:

trend_state = TRANSITION
reversal_status = PARTIAL_REVERSAL

Não:

trend_state = BEAR_CONFIRMED

==================================================
H. ATUALIZAÇÃO DO EXPERIENCE MEMORY
==================================================

Registre também:

- trend_state_at_decision;
- trend_alignment;
- trade_direction_class;
- price_action_state;
- support_resistance_context;
- evidence_set_id;
- evidence_available;
- evidence_missing;
- conflicting_evidence;
- evidence_state;
- confirmation_state;
- trigger_state;
- partial_reversal_state;
- observed_follow_through.

Isso permitirá estudar posteriormente:

- trades a favor da tendência;
- trades contratrend;
- trades em transição;
- trades em range;
- trades com evidência conflitante;
- operações executadas antes de confirmação;
- sinais corretamente ignorados;
- falsos rompimentos;
- follow-through ausente.

==================================================
I. ATUALIZAÇÃO DO HYPOTHESIS LAB
==================================================

Permita que HypothesisLab teste hipóteses como:

- determinada estratégia funciona melhor quando macro e context trend estão alinhados?
- operações contratrend precisam de confirmação adicional?
- quais evidências são redundantes?
- quais tipos de evidência acrescentam informação independente?
- quais sinais aparecem frequentemente juntos?
- quais sinais produzem double counting?
- partial reversal possui valor preditivo?
- ausência de follow-through melhora critérios de invalidação?
- proximidade de suporte ou resistência altera expectativa?
- determinada sequência de price action é útil em determinado regime?
- resultado muda entre sessões?
- resultado muda entre regimes de volatilidade?

Essas perguntas são hipóteses de pesquisa.

Nunca assuma que são verdadeiras antes dos testes.

==================================================
J. PROIBIÇÕES NOVAS
==================================================

Acrescente:

- não transformar indicador em ordem;
- não transformar candle isolado em ordem;
- não transformar suporte/resistência em ordem;
- não transformar liquidez em ordem;
- não confundir confluência com confirmação;
- não confundir confirmação com gatilho;
- não confundir gatilho com autorização de risco;
- não declarar reversão total a partir de quebra parcial;
- não ignorar a tendência do timeframe maior;
- não exigir alinhamento perfeito universal entre timeframes;
- não proibir contratrend universalmente;
- não atribuir pesos arbitrários às evidências;
- não contar evidências derivadas do mesmo dado várias vezes;
- não descartar evidências contrárias;
- não reclassificar evidência após conhecer o resultado do trade;
- não mudar TrendState retrospectivamente para melhorar backtest;
- não utilizar dados futuros na classificação dos swings.

==================================================
K. TESTES NOVOS
==================================================

TrendHierarchyEngine:

- identifica estruturas bullish;
- identifica estruturas bearish;
- diferencia correção de timeframe menor;
- detecta conflito entre timeframes;
- detecta transição;
- produz partial reversal;
- não confirma reversão precocemente;
- preserva timeframe pai;
- funciona com timeframes configuráveis.

PriceActionReader:

- mede candles corretamente;
- detecta expansão;
- detecta contração;
- registra overlap;
- registra rompimento;
- registra ausência de follow-through;
- detecta desaceleração sem prever reversão;
- não gera decisão de trade;
- não atribui intenção humana.

SupportResistanceEngine:

- cria níveis com origem rastreável;
- não duplica zonas equivalentes;
- registra rompimento;
- registra reteste;
- expira níveis conforme política;
- não transforma nível em ordem;
- calcula distância corretamente;
- preserva timeframe de origem.

EvidenceEngine:

- agrega evidências;
- preserva evidências contrárias;
- evita double counting;
- separa confluence/confirmation/trigger;
- reconhece missing evidence;
- reconhece invalidating evidence;
- não gera probabilidade artificial;
- produz resultado determinístico;
- bloqueia hipótese invalidada.

Integração:

- bullish HTF + bearish correction LTF;
- bearish HTF + bullish correction LTF;
- partial reversal;
- failed breakout;
- missing follow-through;
- conflicting evidence;
- strong confluence without trigger;
- valid trigger vetoed by risk;
- transition resulting in NO_TRADE.

==================================================
L. VERTICAL SLICE V3
==================================================

Atualize o primeiro vertical slice para:

MT5 ou Replay
        ↓
MarketDataProvider
        ↓
DataQuality
        ↓
SessionEngine
        ↓
TrendHierarchyEngine
        ↓
MarketStructureEngine
        ↓
PriceActionReader
        ↓
SupportResistanceEngine
        ↓
LiquidityMap
        ↓
Volume/Momentum/Volatility
        ↓
EvidenceEngine
        ↓
MarketSnapshot V3
        ↓
ExperienceMemory.retrieve_similar()
        ↓
HypothesisBuilder
        ↓
ExpectationContract
        ↓
ExpectedVsObservedEngine
        ↓
DecisionEngine
        ↓
RiskManager
        ↓
NO_TRADE ou sinal hipotético
        ↓
ExperienceMemory.record()
        ↓
HypothesisLab offline
        ↓
Report

Na implementação desse vertical slice:

ALLOW_ORDER_EXECUTION=false
ALLOW_LIVE_TRADING=false

Nenhuma ordem deverá ser enviada.

==================================================
M. ARQUITETURA FINAL V3
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
    price_level.py

  liquidity/
    liquidity_map.py

  evidence/
    evidence.py
    evidence_set.py
    evidence_engine.py

  expectations/
    expectation_contract.py
    expected_vs_observed.py
    hypothesis_tracker.py

  memory/
    experience_memory.py
    experience_record.py
    experience_retriever.py
    process_evaluator.py

  strategy/
  decision_engine/
  risk/
  execution/

  learning/
    hypothesis_lab/
      candidate_hypothesis.py
      experiment_runner.py
      quality_gates.py
      promotion_report.py

  backtesting/
  replay/
  monitoring/
  reporting/
  persistence/
  safeguards/

tests/
  architecture/
  trend/
  structure/
  price_action/
  levels/
  evidence/
  expectations/
  memory/
  hypothesis_lab/
  integration/