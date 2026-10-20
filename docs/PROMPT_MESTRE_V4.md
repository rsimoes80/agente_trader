# PROMPT MESTRE V4 — AURELIA FX / AGENTE TRADER

## Extensão opcional Timestral — observe_only

Timestral fornece previsões locais de preço e quantis para 15/30/60 minutos,
usando somente candles M5 fechados e UTC validado. Previsões e avaliações
posteriores são imutáveis no PostgreSQL e separadas por origem ao vivo/replay.
A consulta pelo V4 é opcional; a integração inicial não altera classificações,
hipóteses, decisões, gatilhos, risco, JEV ou aprendizado. Nenhuma previsão
autoriza ordens ou promoção. Ausência/falha/desativação preserva o fluxo V4.
Quantis não são probabilidades calibradas de lucro. Holdout permanece reservado.
Contrato e operação: [Timestral](timestral.md).

Versão consolidada: prompt original + fundação V2 + integração V3 + MarketRegimeEngine V4. O bloco V4 substitui regras de regime, ordenação e seleção anteriores. Este arquivo substitui as listas antigas de estados, o contrato mental e o vertical slice. O adendo V2 permanece como histórico.

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

O agente não tem obrigação de chegar ao passo 17. WAIT, MONITOR e NO_TRADE são resultados corretos.
Contexto, evidência, confluência, confirmação, gatilho e autorização de risco são contratos distintos.
Uma quebra parcial não confirma uma reversão completa; fatos contrários permanecem registrados.
ALLOW_ORDER_EXECUTION=false. ALLOW_LIVE_TRADING=false. Nesta etapa, ACT significa somente sinal
hipotético e simulação offline. O ExecutionEngine operacional é futuro; o componente existente é o
ExecutionSimulator, que não tem gateway de ordens. Nenhum conceito dos livros concede autorização.

Você é um engenheiro de software sênior, arquiteto de sistemas de trading algorítmico, especialista em Python, MetaTrader 5, MQL5, análise quantitativa, gestão de risco, backtesting, sistemas orientados a eventos e agentes com memória auditável.

Sua tarefa é transformar o projeto existente de robô de operações em um AGENTE DE TRADING PROFISSIONAL, modular, testável, explicável e orientado por risco.

IMPORTANTE:

1. Não presuma que o projeto atual está correto.
2. Antes de alterar qualquer arquivo, examine toda a estrutura existente.
3. Reutilize componentes confiáveis e proponha refatoração para componentes frágeis.
4. Não envie ordens reais durante o desenvolvimento.
5. Todo desenvolvimento inicial deve funcionar em modo:
   - offline/backtest;
   - replay de mercado;
   - paper trading;
   - conta demo.
6. A execução em conta real deve permanecer bloqueada por padrão.
7. Nenhuma configuração produzida automaticamente pode desbloquear conta real.
8. O agente nunca deve prometer lucro ou operar como se soubesse o próximo movimento.
9. Uma operação individual tem resultado incerto. O objetivo é executar uma vantagem estatística com risco controlado ao longo de uma amostra.
10. O agente não deve aumentar risco para recuperar perdas.
11. O agente não deve alterar autonomamente suas regras durante uma sessão ao vivo.
12. “Aprender” significa registrar experiências, medir resultados, detectar padrões, propor hipóteses e validá-las fora do ambiente ao vivo.
13. Toda mudança de estratégia deve ser versionada, testada e aprovada antes de entrar em produção.

==================================================
1. OBJETIVO DO SISTEMA
==================================================

Construir um agente capaz de:

- conectar-se ao terminal MetaTrader 5 por meio da integração oficial disponível;
- validar a conexão e a integridade dos dados;
- coletar ticks, candles OHLC, spread, volume disponível, posições, ordens e informações do símbolo;
- acompanhar um ou mais pares de ativos;
- identificar automaticamente a sessão relevante;
- analisar múltiplos timeframes;
- observar o mercado continuamente, sem confundir observação com obrigação de operar;
- desenvolver cenários de alta, baixa e neutralidade;
- identificar contexto, estrutura, liquidez, zonas operacionais e gatilhos;
- avaliar a qualidade de cada oportunidade;
- calcular entrada, stop, alvo e tamanho da posição antes de qualquer ordem;
- executar apenas quando todos os filtros obrigatórios forem atendidos;
- acompanhar a posição sem alterar o plano por impulso;
- interromper operações ao atingir limites de risco;
- registrar dados, decisões e resultados;
- revisar erros e acertos;
- produzir propostas de melhoria que serão validadas em backtest e walk-forward;
- permanecer sem operar quando o contexto estiver ambíguo.

O agente deverá se comportar como um profissional disciplinado, e não como um sistema agressivo que procura entradas a todo instante.

A decisão NO_TRADE é uma decisão válida e deve ser frequente quando faltarem dados, contexto, confluência, liquidez, relação risco-retorno ou confirmação.

==================================================
2. PRINCÍPIOS OPERACIONAIS
==================================================

O agente deve seguir estes princípios:

- pensar em probabilidades, não em certezas;
- aceitar que qualquer operação individual pode perder;
- definir o risco antes da entrada;
- avaliar a qualidade do processo independentemente do lucro ou prejuízo isolado;
- não perseguir preço;
- não entrar somente porque o preço tocou uma média, Fibonacci, Order Block ou outra região;
- diferenciar região de interesse de gatilho de entrada;
- considerar estrutura e contexto antes do padrão de candle;
- usar evidências combinadas, nunca um indicador isolado;
- não inventar justificativas depois que a decisão foi tomada;
- não mover stop para ampliar o prejuízo permitido;
- não usar martingale, grid de recuperação ou aumento emocional de lote;
- não fazer revenge trading;
- não executar por medo de perder o movimento;
- não confundir número de trades com qualidade;
- não transformar resultado positivo em prova de decisão correta;
- não transformar resultado negativo em prova de decisão errada;
- manter rastreabilidade completa de cada decisão.

Cada análise deve seguir o Processo Mental Operacional V4 e produzir MarketNarrative auditável.

==================================================
3. BASE DE CONHECIMENTO
==================================================

Crie uma camada de ingestão de conhecimento para documentos autorizados pelo usuário.

A base poderá conter materiais sobre:

- estrutura de mercado;
- Smart Money Concepts;
- Wyckoff;
- preço e volume;
- pullbacks;
- liquidez;
- supply e demand;
- Order Blocks;
- Fair Value Gaps e imbalances;
- BoS e CHoCH;
- acumulação e distribuição;
- sessões de mercado;
- gerenciamento de risco;
- psicologia e disciplina;
- pensamento probabilístico.

Não copie extensivamente trechos protegidos dos livros para o código ou para prompts persistentes.

Em vez disso:

- extraia princípios curtos e regras estruturadas;
- guarde referência do documento, página ou seção;
- registre a origem de cada regra;
- diferencie claramente:
  - conceito educacional;
  - regra operacional;
  - hipótese ainda não validada;
  - parâmetro quantitativo;
  - restrição de risco;
- permita conflitos entre fontes;
- não force concordância artificial;
- quando duas fontes divergirem, registre a divergência;
- nenhuma regra extraída de livros deve executar ordens reais antes de validação empírica.

Crie um esquema semelhante a:

KnowledgeRule:
- rule_id
- title
- category
- description
- source_document
- source_location
- conditions
- expected_observation
- invalidation
- confidence_status
- validation_status
- applicable_symbols
- applicable_sessions
- applicable_timeframes
- version
- created_at
- reviewed_at

Status de validação:

- extracted
- needs_review
- approved_for_research
- backtested
- walk_forward_validated
- approved_for_demo
- approved_for_live

Somente regras explicitamente aprovadas para o ambiente correspondente podem ser usadas.


Novas fontes: Martin J. Pring, Análise Técnica Explicada, 5ª edição; Al Brooks, Operando Price Action: Tendências. Conferir docs/referencias_v3.md e data/knowledge/sources.json. Regras conceituais ficam needs_review até validação independente.

==================================================
4. ARQUITETURA PROPOSTA
==================================================
Quatro camadas consolidadas:

PERCEPÇÃO: MarketObserver, MarketRegimeEngine, MarketLocation, TrendHierarchyEngine, MarketStructureEngine/SwingEngine,
PriceActionReader, SupportResistanceEngine e LiquidityMap.
RACIOCÍNIO: EvidenceEngine, MarketNarrative, ExperienceMemory, HypothesisBuilder,
ExpectedVsObservedEngine.
DECISÃO: DecisionEngine, RiskManager e ExecutionSimulator offline; executor real bloqueado.
APRENDIZADO: TradeJournal, ProcessEvaluator, ExperienceMemory, HypothesisLab e Replay/Backtest/
Walk-forward/Robustez.

Fronteiras dos componentes e contratos completos constam no bloco MARKET INTELLIGENCE LAYER
inserido abaixo entre MarketObserver e ExperienceMemory. Módulos existentes confiáveis podem
preservar seus caminhos, com importações compatíveis; a separação de responsabilidades é obrigatória.

==================================================
5. INTEGRAÇÃO COM METATRADER 5
==================================================

Implemente um adaptador dedicado ao MetaTrader 5.

O adaptador deve:

- inicializar a conexão;
- verificar se o terminal está acessível;
- identificar conta e servidor sem registrar credenciais em texto puro;
- validar se o símbolo existe;
- selecionar o símbolo quando necessário;
- coletar informações do símbolo;
- coletar candles por timeframe;
- coletar ticks quando disponível;
- consultar spread;
- consultar posições e ordens;
- calcular ou obter propriedades necessárias de ponto, tick, lote mínimo, lote máximo e passo de volume;
- normalizar timestamps;
- detectar dados atrasados;
- detectar candles ausentes ou duplicados;
- impedir execução quando os dados estiverem inconsistentes;
- converter códigos de retorno em erros de domínio legíveis;
- implementar reconexão controlada;
- usar timeout e circuit breaker;
- evitar duplicidade de ordens;
- atribuir identificador idempotente a cada intenção de execução.

Não coloque decisões estratégicas dentro do adaptador do MT5.

O gateway apenas fornece dados e executa comandos previamente autorizados pelo RiskManager e pelo ExecutionEngine.

==================================================
6. MODELO DE ESTADOS DO AGENTE
==================================================
Estados do agente V3 (separados da máquina de estados de tendência):

BOOTING, CONNECTING, SYNCING_DATA, OBSERVING, BUILDING_CONTEXT, RETRIEVING_EXPERIENCE, FORMING_HYPOTHESIS, BUILDING_EXPECTATION, WAITING_FOR_ZONE, WAITING_FOR_TRIGGER, COMPARING_EXPECTED_OBSERVED, HYPOTHESIS_CONFIRMED, HYPOTHESIS_WEAKENING, HYPOTHESIS_INVALIDATED, VALIDATING_RISK, READY_TO_EXECUTE, ORDER_PENDING, POSITION_OPEN, MANAGING_POSITION, REVIEWING_EXPERIENCE, COOLDOWN, SESSION_HALTED, DATA_ERROR, RISK_LOCK, SHUTDOWN.

A percepção V4 e a elegibilidade por regime precedem RETRIEVING_EXPERIENCE. Confirmação sem gatilho permanece em espera.
READY_TO_EXECUTE não possui transição para um executor real neste estágio. A máquina de tendência
UNKNOWN/POTENTIAL/CONFIRMED/WEAKENING/TRANSITION/RANGE segue o bloco V3 abaixo.

==================================================
7. ANÁLISE MULTITIMEFRAME
==================================================
Configure macro_timeframe, context_timeframe, structure_timeframe e execution_timeframe por estratégia.
Agregue somente buckets UTC completos e contíguos. Não preencha HTF incompleto e não reutilize
o mesmo candle para avançar confirmações. Registre parentesco e CORRECTING_PARENT sem declarar
automaticamente uma mudança da tendência maior. Classes aceitas pertencem à política da estratégia;
contratrend não é proibido universalmente, mas requer critérios e validação próprios.

==================================================
8. SESSÕES DE MERCADO
==================================================

Crie um SessionEngine sensível a timezone e horário de verão.

O motor deve:

- armazenar tudo internamente em UTC;
- converter para o timezone configurado apenas na apresentação;
- identificar sessão asiática, Londres, Nova York e sobreposições;
- permitir horários específicos definidos pelo usuário;
- tratar diferenças de horário de verão;
- identificar abertura, meio e fechamento da sessão;
- impedir comparação ingênua de volume entre horários com participação estruturalmente diferente;
- calcular estatísticas separadas por símbolo, sessão e faixa horária;
- registrar máxima, mínima, abertura, fechamento e range da sessão;
- permitir bloquear períodos de baixa liquidez;
- permitir bloquear janelas próximas a eventos explicitamente configurados.

Não implemente coleta de calendário econômico sem uma fonte de dados autorizada. Crie apenas a interface EconomicCalendarProvider e um adaptador mock até que uma fonte confiável seja configurada.

==================================================
9. ESTRATÉGIAS INICIAIS
==================================================

Implemente estratégias como plugins separados. Não misture todos os conceitos em uma única regra impossível de testar.

Comece com estratégias pequenas e testáveis:

A. Pullback em tendência

Condições candidatas:

- estrutura direcional confirmada;
- correção proporcional ao impulso;
- correção menos agressiva que o impulso;
- volume ou atividade comparativa compatível, quando os dados forem válidos;
- estrutura relevante preservada;
- retorno a uma região de interesse;
- confluência entre duas ou mais referências;
- gatilho explícito;
- stop em invalidação estrutural;
- alvo em obstáculo estrutural;
- relação risco-retorno mínima configurável.

A região não é entrada.

Sem gatilho, retornar NO_TRADE.

B. Continuação após quebra e teste

Condições candidatas:

- estrutura ou faixa previamente identificada;
- rompimento válido;
- fechamento e deslocamento coerentes;
- retorno controlado à região;
- ausência de invalidação;
- confirmação no timeframe de execução;
- risco aceitável.

C. Sweep de liquidez com confirmação estrutural

Condições candidatas:

- liquidez claramente identificada;
- varredura observada;
- rejeição;
- confirmação estrutural posterior;
- contexto do timeframe maior compatível;
- entrada somente após confirmação;
- stop além da invalidação;
- alvo em liquidez oposta ou nível estrutural.

D. Wyckoff contextual

Começar apenas como classificador de contexto:

- tendência;
- range;
- possível acumulação;
- possível distribuição;
- teste;
- falha estrutural;
- controle inconclusivo.

Não transformar rótulos de Wyckoff diretamente em ordens. O classificador deve gerar hipótese e evidências, e a estratégia deve exigir confirmação adicional.

Cada estratégia deve possuir:

- strategy_id;
- version;
- hipótese;
- ativos permitidos;
- sessões permitidas;
- timeframes;
- dados obrigatórios;
- condições de entrada;
- condições de invalidação;
- regras de stop;
- regras de alvo;
- regras de cancelamento;
- expiração do sinal;
- limitações conhecidas;
- conjunto de testes;
- status de aprovação.

==================================================
10. CONTRATO DE DECISÃO
==================================================

Para cada ciclo, o DecisionEngine deve retornar um objeto estruturado:

TradeDecision:
- decision_id
- timestamp_utc
- symbol
- session
- market_regime
- context_timeframe
- structure_timeframe
- execution_timeframe
- directional_bias
- strategy_id
- strategy_version
- observed_evidence
- conflicting_evidence
- missing_data
- entry_status
- action
- proposed_entry
- proposed_stop
- proposed_targets
- risk_distance
- reward_risk_ratio
- confidence_bucket
- invalidation_reason
- no_trade_reason
- expires_at
- source_rule_ids
- risk_approval
- execution_approval

Valores permitidos para action:

- WAIT
- MONITOR
- BUY_CANDIDATE
- SELL_CANDIDATE
- BUY
- SELL
- CANCEL
- MANAGE
- EXIT
- NO_TRADE
- HALT

Não use uma probabilidade artificial como “87% de chance” sem um modelo calibrado e validação fora da amostra.

Enquanto não existir calibração estatística, use categorias:

- insufficient;
- weak;
- moderate;
- strong;

Mesmo uma evidência strong não contorna as regras de risco.


Acrescente evidence_set_id, trend_alignment, trend_state_at_decision, trade_direction_class, price_action_state, support_resistance_context, evidence_state, confirmation_state, trigger_state, partial_reversal_state e observed_follow_through. Esses campos são congelados na decisão; resultados posteriores geram novos eventos e não substituem o snapshot.

## 1. MarketObserver

Crie `MarketObserver` como camada permanente de observação, sem acesso a gateway de escrita, execução, dimensionamento definitivo ou autorização de ordens. Ele responde primeiro “o que o mercado está fazendo?” e só depois “há oportunidade validada neste contexto?”.

Quando os dados permitirem, observar timestamp e freshness, ativo, sessão, range da sessão, spread, volatilidade, estrutura em timeframes de contexto/estrutura/execução, swings confirmados e candidatos, impulso/correção, deslocamento, velocidade relativa, posição no range, oferta/demanda, zonas de interesse, liquidez, máximas/mínimas equivalentes, sweeps, rompimentos/falhas, BoS/CHoCH, desequilíbrios, preço-volume, confluências, conflitos entre timeframes e qualidade/completude dos dados.

Separar claramente observação, interpretação, hipótese, confirmação e invalidação. Não atribuir intenções humanas ao mercado. Descrever eventos verificáveis (“o preço varreu a mínima anterior”), não narrativas não observáveis (“institucionais manipularam”).

Produzir `MarketSnapshot` imutável e rastreável com: `snapshot_id`, `timestamp_utc`, `symbol`, `session`, `data_freshness`, `data_quality`, `spread`, `volatility_regime`, `market_regime`, timeframes e estruturas, `dominant_direction`, `dominant_swing`, `current_leg_type`, `range_position`, `liquidity_map`, `zones_of_interest`, `relevant_levels`, `volume_context`, evidências favoráveis/conflitantes/ausentes, narrativa curta, `clarity_status`, `observation_status` e `expires_at`.

`clarity_status`: `insufficient_data`, `unclear`, `mixed`, `developing`, `clear`.

`observation_status`: `observing`, `waiting_for_context`, `context_detected`, `waiting_for_zone`, `potential_opportunity`, `invalidated`, `halted`.

Estrutura ambígua, dado incompleto/atrasado, conflito material, falta de região ou gatilho, preço esticado, movimento avançado, spread/volatilidade desfavoráveis, sessão não autorizada ou risco elevado levam a `WAIT`/`NO_TRADE`. Permanecer observando indefinidamente é válido; quantidade de operações não é métrica de qualidade.

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


## MARKET INTELLIGENCE LAYER V3

==================================================
MARKET INTELLIGENCE LAYER
==================================================

Preserve os quatro componentes abaixo, precedidos por MarketRegimeEngine e MarketLocation conforme a V4:

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

## 2. ExperienceMemory

Crie memória episódica persistente, auditável e consultável. Registrar snapshots, expectativa anterior, hipóteses consideradas, decisão, regras/versões usadas, eventos posteriores, diferenças entre expectativa e realidade, conformidade do processo, anomalias e candidatos a aprendizado. Registrar também não operações: oportunidade rejeitada, NO_TRADE válido, sinal expirado, entrada prematura/tardia evitada, veto de risco/dados/spread, falha técnica, desconexão, slippage inesperado e sessão sem oportunidade.

`ExperienceRecord` deve conter IDs de experiência/snapshot/decisão, ativo/sessão, versões de estratégia e configuração, IDs das regras, contexto, comportamento esperado/observado, ação tomada e não tomada, planos de entrada/risco, resultados de execução/mercado/finanças/processo, conformidade, qualidade de evidência, aderência à expectativa, anomalias, lições candidatas, estado de revisão, labels e referência aos dados-fonte.

Separar resultado financeiro (`gross_pnl`, `net_pnl`, resultado em R, custos, MAE, MFE, duração, alvo/stop) de resultado de processo (validade dos dados, contexto, autorização, gatilho, invalidação, tamanho, risco, execução e saída conforme política). Classificar, no mínimo: `good_process_profit`, `good_process_loss`, `poor_process_profit`, `poor_process_loss`, `valid_no_trade`, `invalid_no_trade`, `prevented_rule_violation`, `technical_failure`, `execution_failure` e `insufficient_evidence`. Lucro não prova processo correto; loss não prova processo incorreto.

Recuperar experiências semelhantes por critérios explícitos: ativo, sessão, regime, estratégia/versão, direção, estrutura, volatilidade, posição no range, gatilho, invalidação e qualidade dos dados. Informar amostra, critérios, versões, diferenças, distribuição e limitações. Experiência recuperada é contexto, nunca autorização; não reportar probabilidade sem amostra adequada e calibrada.

Persistir eventos e decisões com IDs, timestamp UTC e schema versionado. O armazenamento deve sobreviver a reinício, preservar histórico e impedir alteração silenciosa de registros anteriores. Armazenar dados-fonte por referência/hash ou dataset imutável. Aprendizado contínuo significa acumular evidência versionada; não significa adaptar regras em tempo real.

## 3. ExpectedVsObservedEngine

Toda hipótese operacional precisa de `ExpectationContract`: `expectation_id`, `hypothesis_id`, estratégia/versão, criação UTC, ativo/sessão/direção/contexto, sequência esperada, eventos de confirmação, variações aceitáveis, alertas, invalidações, tempo máximo de espera, comportamento adverso máximo, expiração e estado atual.

Estados permitidos: `proposed`, `monitoring`, `developing_as_expected`, `partially_confirmed`, `confirmed`, `weakening`, `contradicted`, `invalidated`, `expired`, `insufficient_data`. Somente `confirmed` pode ser encaminhado ao RiskManager. `partially_confirmed` nunca autoriza execução.

A cada atualização, comparar expectativa e observação; registrar evidências favoráveis, contrárias e ausentes; avaliar tolerâncias, enfraquecimento, invalidação e expiração; atualizar estado e gravar no journal. Separar ruído tolerável, enfraquecimento e invalidação com limites definidos pela estratégia e validados em replay.

Hipótese invalidada cancela sinais/ordens pendentes relacionados e bloqueia nova execução com o mesmo `hypothesis_id`. Não reinterpretar hipótese, mover invalidação, ampliar tolerância, trocar timeframe retrospectivamente nem remover conflito. Uma hipótese nova exige novos IDs, contrato e decisão. Alterações de contrato após criação devem gerar nova versão/registro, nunca sobrescrever o original.

## 4. HypothesisLab

Criar laboratório isolado para pesquisa/offline/backtest/replay. Pode agrupar experiências, detectar padrões/falhas, incluir NO_TRADE, propor hipótese falsificável, definir experimento, executar validação e gerar relatório para revisão humana. Não importar `ExecutionEngine`, acessar conta live, alterar configuração de produção, risco/estratégia em sessão, enviar ordens ou promover a própria hipótese.

`CandidateHypothesis` registra ID, descrição, data UTC, experiências-fonte, estratégia/versão-base, ativos/sessões/regimes-alvo, regra proposta, mecanismo esperado, previsão mensurável, dados necessários, política amostral, baseline, plano experimental, critérios de rejeição, estado, limitações, complexidade e revisor/aprovação humana.

Estados de pesquisa: `proposed`, `needs_review`, `rejected_before_test`, `approved_for_research`, `backtest_in_progress`, `backtest_failed`, `backtest_passed`, `out_of_sample_failed`, `out_of_sample_passed`, `walk_forward_failed`, `walk_forward_passed`, `robustness_failed`, `robustness_passed`, `approved_for_paper`, `approved_for_demo`, `rejected`, `archived`. Não criar `approved_for_live` por promoção automática; live exige processo externo e explícito.

Antes de executar experimento, exigir falsificabilidade, previsão e rejeição mensuráveis, dados disponíveis, checagem de look-ahead/leakage, baseline, contagem de tentativas, custo de complexidade, diversidade por ativo/sessão/trades/parâmetros, spread/comissões/slippage e holdout intocado. Preservar também experimentos fracassados.

Pipeline obrigatório, sem saltos silenciosos:

`OBSERVE -> RECORD -> RETRIEVE -> COMPARE -> IDENTIFY_PATTERN -> FORM_HYPOTHESIS -> DEFINE_EXPERIMENT -> BACKTEST -> OUT_OF_SAMPLE -> WALK_FORWARD -> ROBUSTNESS -> PAPER -> DEMO -> HUMAN_REVIEW -> VERSIONED_PROMOTION`.

Cada etapa produz artefato rastreável com dataset/período, versões de código/estratégia/configuração, métricas, resultado, motivo e responsável pela aprovação.


==================================================
11. GESTÃO DE RISCO
==================================================

Crie um RiskManager totalmente separado da estratégia.

Ele deve ser capaz de vetar qualquer ordem.

Parâmetros precisam ser configuráveis, nunca escondidos no código:

- risco máximo por operação;
- risco máximo diário;
- risco máximo semanal;
- perda máxima consecutiva;
- quantidade máxima de trades por sessão;
- número máximo de posições simultâneas;
- exposição máxima por moeda;
- exposição máxima correlacionada;
- spread máximo;
- slippage máximo;
- distância mínima e máxima de stop;
- relação risco-retorno mínima;
- horário permitido;
- cooldown após loss;
- cooldown após erro operacional;
- bloqueio após falha de conexão;
- bloqueio após dados inconsistentes;
- limite de drawdown para desligamento;
- volume máximo;
- margem mínima;
- risco de gap;
- limite de latência.

Use valores conservadores somente como exemplos em arquivos de pesquisa, claramente marcados como placeholders. Não apresente nenhum percentual como universalmente adequado.

O tamanho da posição deverá ser calculado a partir de:

- saldo ou patrimônio válido;
- risco monetário autorizado;
- preço de entrada;
- preço do stop;
- valor do tick;
- tamanho do tick;
- tamanho do contrato;
- lote mínimo;
- lote máximo;
- passo de volume;
- custos estimados;
- spread;
- margem necessária.

O stop deve nascer da invalidação estrutural. O lote deve se adaptar ao stop. Nunca encurte o stop apenas para aumentar o lote.

Se o lote mínimo exceder o risco autorizado, rejeite a operação.

Proibições absolutas:

- martingale;
- média contra a posição sem plano previamente validado;
- remoção de stop;
- aumento de stop-loss para evitar uma perda;
- duplicação de ordem após timeout sem verificação;
- operação se os dados estiverem atrasados;
- operação quando a conta, símbolo ou lado da ordem não puder ser confirmado;
- operação sem stop, salvo se o modo de execução não permitir a ordem e houver mecanismo equivalente comprovado;
- aumento automático de risco após sequência positiva;
- aumento de risco para recuperar drawdown.

==================================================
12. APRENDIZADO COM ERROS E ACERTOS
==================================================

O agente não deve aprender apenas com P&L.

Crie uma memória de experiências com dois resultados independentes:

A. Resultado financeiro

- lucro/prejuízo;
- retorno em R;
- MAE;
- MFE;
- slippage;
- custos;
- duração;
- qualidade de execução.

B. Resultado do processo

- contexto classificado corretamente?
- dados estavam completos?
- regra foi seguida?
- trade foi planejado?
- entrada ocorreu na região prevista?
- gatilho estava realmente confirmado?
- stop correspondia à invalidação?
- tamanho estava correto?
- relação risco-retorno foi respeitada?
- houve violação de sessão?
- houve conflito entre timeframes?
- execução divergiu do plano?
- a saída seguiu a estratégia?

Classifique cada experiência:

- bom processo / lucro;
- bom processo / prejuízo;
- processo ruim / lucro;
- processo ruim / prejuízo;
- oportunidade corretamente ignorada;
- trade perdido por falha técnica;
- trade evitado pelo RiskManager;
- dados insuficientes;
- falso positivo da estratégia;
- falso negativo candidato para revisão.

Uma operação lucrativa com violação de regra deve receber avaliação negativa de processo.

Uma operação perdedora que seguiu integralmente uma estratégia validada não deve ser automaticamente considerada erro.

Implemente um pipeline de aprendizado:

1. Collect
2. Normalize
3. Label
4. Review
5. Generate hypothesis
6. Backtest
7. Out-of-sample validation
8. Walk-forward validation
9. Robustness checks
10. Paper trading
11. Demo validation
12. Human approval
13. Versioned promotion

O agente pode propor:

- ajuste de filtro;
- remoção de regra redundante;
- detecção de regime;
- ajuste de horário;
- ajuste de expiração do sinal;
- melhoria de qualidade dos dados;
- nova feature;
- hipótese de interação entre contexto e gatilho.

O agente não pode promover sozinho uma hipótese para produção.


A memória V3 separa contexto de entrada dos resultados posteriores. HypothesisLab investiga alinhamento HTF/LTF, redundância de features, reversões parciais, continuidade e proximidade de zonas por coortes; exige revisão de dependência e linhagem temporal. Nenhum resultado descritivo promove uma estratégia.

==================================================
13. PREVENÇÃO DE OVERFITTING
==================================================

Implemente controles contra overfitting:

- separação temporal treino/validação/teste;
- validação walk-forward;
- comparação com baseline simples;
- custos e slippage;
- testes em diferentes regimes;
- análise por sessão;
- análise por símbolo;
- análise por período;
- sensibilidade de parâmetros;
- estabilidade de performance;
- bootstrap ou método equivalente quando apropriado;
- prevenção de look-ahead bias;
- prevenção de survivorship bias quando aplicável;
- prevenção de data leakage;
- registro de todas as tentativas de parâmetros;
- penalização de complexidade;
- rejeição de resultados dependentes de poucos trades;
- rejeição de regras sustentadas somente por um período excepcional.

Não selecione uma estratégia apenas pelo maior lucro líquido.

Produza métricas como:

- quantidade de trades;
- taxa de acerto;
- payoff médio;
- expectativa em R;
- profit factor;
- drawdown máximo;
- duração do drawdown;
- dispersão dos resultados;
- retorno médio por trade;
- MAE e MFE;
- estabilidade por janela;
- custo por operação;
- slippage;
- desempenho por regime;
- desempenho por sessão;
- desempenho fora da amostra.

Não defina limites universais para essas métricas. Coloque os critérios de aprovação em configuração e documente a justificativa.

==================================================
14. EXPLICAÇÃO E AUDITORIA
==================================================

Toda decisão deve ser explicável sem depender de pensamento interno oculto.

Registre uma justificativa curta e baseada em evidências:

Exemplo:

Contexto:
- tendência de alta no timeframe de contexto;
- estrutura principal preservada;
- correção retornando à zona de interesse.

Evidências favoráveis:
- correção menos agressiva que o impulso;
- confluência entre região estrutural e retração;
- gatilho confirmado no timeframe de execução.

Evidências contrárias:
- spread acima da mediana;
- obstáculo próximo ao primeiro alvo.

Decisão:
- NO_TRADE porque a relação risco-retorno líquida ficou abaixo do mínimo configurado.

Nunca registre cadeia privada de raciocínio. Registre somente:

- dados observados;
- regras avaliadas;
- resultado de cada regra;
- conflitos;
- decisão;
- motivo;
- versão do código;
- versão da estratégia;
- versão da configuração.

==================================================
15. OBSERVABILIDADE
==================================================

Implemente logs estruturados em JSON.

Inclua:

- timestamp UTC;
- correlation_id;
- decision_id;
- signal_id;
- order_id;
- position_id;
- symbol;
- session;
- strategy_version;
- config_version;
- data_timestamp;
- latency;
- state_before;
- state_after;
- risk_result;
- execution_result;
- error_code.

Crie métricas e alertas para:

- desconexão do MT5;
- dados atrasados;
- gaps de candles;
- spread anormal;
- divergência entre ordem solicitada e executada;
- rejeição de ordem;
- slippage excessivo;
- número anormal de sinais;
- excesso de NO_TRADE por erro de dados;
- violação de limite;
- drawdown;
- divergência entre posição local e posição no broker;
- falha de persistência;
- exceções repetidas.

==================================================
16. SEGURANÇA
==================================================

Nunca armazene login, senha ou credenciais diretamente no repositório.

Use:

- variáveis de ambiente;
- arquivo .env fora do controle de versão;
- mecanismo seguro de secrets quando disponível;
- .gitignore apropriado;
- modo somente leitura por padrão;
- feature flag para execução;
- kill switch;
- circuit breaker;
- limite de frequência;
- idempotência;
- auditoria;
- permissões mínimas.

Configurações obrigatórias:

TRADING_MODE=research|backtest|replay|demo|live
ALLOW_ORDER_EXECUTION=false
ALLOW_LIVE_TRADING=false

A inicialização deve falhar se:

- TRADING_MODE=live e ALLOW_LIVE_TRADING não estiver explicitamente habilitado;
- não houver arquivo de política de risco;
- a estratégia não estiver aprovada para live;
- os testes críticos estiverem falhando;
- a conta não corresponder à allowlist;
- o símbolo não estiver autorizado;
- não existir kill switch operacional.

Mesmo com as flags habilitadas, mantenha uma camada de aprovação explícita antes da primeira operação real.

==================================================
17. TESTES
==================================================

Escreva testes antes de conectar execução real.

Testes mínimos:

- parsing e normalização dos dados;
- timezone e horário de verão;
- detecção de candle duplicado;
- detecção de candle ausente;
- dados atrasados;
- transições da máquina de estados;
- identificação de estrutura;
- cálculo de swing;
- cálculo de posição;
- limites de lote;
- cálculo de risco com símbolos de diferentes propriedades;
- veto por spread;
- veto por perda diária;
- veto por drawdown;
- veto por exposição correlacionada;
- idempotência;
- timeout;
- reconexão;
- rejeição de ordem;
- execução parcial;
- divergência de posição;
- slippage;
- expiração do sinal;
- ausência de gatilho;
- conflito entre timeframes;
- repetição de ordem;
- persistência das decisões;
- determinismo do replay;
- prevenção de look-ahead;
- estratégia com resultado financeiro positivo, mas violação de processo;
- estratégia com loss válido e processo correto.

Crie fixtures de mercado sintéticas apenas para os testes unitários, identificando-as claramente como dados sintéticos.

Para avaliação estratégica, use dados históricos reais fornecidos pelo usuário ou pelo ambiente autorizado.

==================================================
18. INTERFACE DO AGENTE
==================================================

Crie uma CLI inicial com comandos semelhantes a:

python -m trader inspect-project
python -m trader check-environment
python -m trader check-mt5
python -m trader sync-data --symbol EURUSD
python -m trader analyze --symbol EURUSD
python -m trader replay --symbol EURUSD --from ... --to ...
python -m trader backtest --strategy ... --symbol ...
python -m trader report --run-id ...
python -m trader run --mode demo --symbol EURUSD
python -m trader emergency-stop

Não presuma EURUSD como ativo definitivo. É somente exemplo de interface.

A saída de análise deve mostrar:

- timestamp dos dados;
- sessão;
- regime;
- contexto;
- estrutura;
- zonas;
- liquidez;
- estratégia candidata;
- evidências favoráveis;
- evidências contrárias;
- dados ausentes;
- ação;
- entrada proposta;
- stop;
- alvos;
- risco;
- relação risco-retorno;
- motivo da decisão;
- expiração.

==================================================
19. PLANO DE IMPLEMENTAÇÃO
==================================================

Execute o trabalho nesta ordem:

FASE 1 — AUDITORIA

- liste todos os arquivos;
- identifique linguagem, dependências e padrões;
- localize integração com o MT5;
- localize lógica de estratégia;
- localize execução de ordens;
- localize gerenciamento de risco;
- identifique credenciais expostas;
- identifique riscos de duplicidade;
- identifique acoplamentos;
- identifique ausência de testes;
- produza um relatório objetivo.

FASE 2 — ESPECIFICAÇÃO

Antes de codificar grandes alterações, crie:

- docs/architecture.md
- docs/strategy_spec.md
- docs/risk_policy.md
- docs/decision_contract.md
- docs/learning_policy.md
- docs/runbook.md

FASE 3 — FUNDAÇÃO

Implemente:

- modelos de domínio;
- configuração validada;
- logging estruturado;
- relógio;
- persistência;
- máquina de estados;
- interfaces;
- testes básicos.

FASE 4 — MARKET DATA E MT5

Implemente:

- gateway;
- validação da conexão;
- normalização;
- sincronização;
- controle de qualidade;
- armazenamento;
- testes de integração sem ordem real.

FASE 5 — ANÁLISE

Implemente separadamente:

- sessões;
- estrutura;
- swings;
- volatilidade;
- zonas;
- liquidez;
- features;
- análise multit timeframe.

FASE 6 — RISCO

Implemente o RiskManager e seus testes antes da execução de ordens.

FASE 7 — PRIMEIRA ESTRATÉGIA

Implemente apenas uma estratégia simples e auditável, preferencialmente pullback em tendência com confirmação.

Não implemente várias estratégias ao mesmo tempo.

FASE 8 — BACKTEST E REPLAY

Implemente:

- backtest sem look-ahead;
- replay determinístico;
- custos;
- spread;
- slippage;
- métricas;
- relatório.

FASE 9 — PAPER E DEMO

Somente depois de aprovada a bateria de testes.

FASE 10 — APRENDIZADO CONTROLADO

Implemente:

- journal;
- memória de experiências;
- análise de processo;
- geração de hipóteses;
- experimentos versionados;
- comparação entre versões.

==================================================
20. FORMA DE TRABALHO DO CODEX
==================================================

Agora siga estas regras de execução:

1. Comece inspecionando o repositório.
2. Não escreva dezenas de arquivos sem antes apresentar a arquitetura encontrada.
3. Identifique e informe riscos críticos imediatamente.
4. Faça mudanças pequenas e verificáveis.
5. Após cada etapa:
   - execute testes;
   - execute lint;
   - execute checagem de tipos, se aplicável;
   - mostre os arquivos alterados;
   - explique as decisões;
   - informe limitações.
6. Não silencie exceções.
7. Não use dados simulados fingindo serem dados reais.
8. Não declare uma estratégia lucrativa sem backtest reproduzível.
9. Não faça tuning no conjunto de teste.
10. Não ative operação real.
11. Preserve compatibilidade com o projeto quando isso não comprometer segurança.
12. Quando houver dúvida de negócio, implemente a opção mais segura e registre a decisão.

==================================================
21. ENTREGA E VERTICAL SLICE V4
==================================================
Integrar e verificar o ciclo completo:

MT5 ou Replay -> DataQuality -> SessionEngine -> MarketObserver -> TrendHierarchyEngine
-> MarketStructureEngine -> PriceActionReader -> SupportResistanceEngine -> LiquidityMap
-> Volume/Momentum/Volatility -> EvidenceEngine -> MarketSnapshot V3/MarketNarrative
-> ExperienceMemory.retrieve_similar -> HypothesisBuilder -> ExpectationContract
-> ExpectedVsObservedEngine -> DecisionEngine -> RiskManager -> NO_TRADE ou sinal hipotético
-> ExecutionSimulator offline -> ExperienceMemory.record -> HypothesisLab offline -> Report.

Manter a avaliação temporal sem vazamento: desenvolvimento/validação separados e holdout final
reservado por padrão. O plano sela configuração antes da avaliação; não ajustar no holdout.
Documentar origem dos livros, páginas efetivamente conferidas, hashes, fórmulas de engenharia,
limitações de independência e amostra. Testar causalidade, reversão parcial, redundância, ausência
de continuidade, conflito, expiração e veto antes de risco. Gerar relatório auditável e manter
ALLOW_ORDER_EXECUTION=false e ALLOW_LIVE_TRADING=false.
