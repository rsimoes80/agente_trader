# Adendo V2 ao prompt mestre — observação, memória e validação

**Incorporação:** inserir este bloco imediatamente antes da seção `GESTÃO DE RISCO` do prompt mestre. Em seguida, substituir a máquina de estados antiga e o primeiro vertical slice pelas versões deste adendo. As regras de risco, segurança e bloqueio de ordens do prompt mestre continuam prevalecendo.

## Objetivo do ciclo de aprendizado

O agente deve executar um ciclo auditável:

`observar -> recordar -> comparar -> formular hipótese -> validar -> agir`

Aprender significa registrar observações e resultados, comparar experiências, propor hipóteses falsificáveis e validá-las em pesquisa/replay/backtest. Experiências recentes nunca podem alterar estratégia, risco ou configuração de produção durante uma sessão. A execução real continua bloqueada.

Use como referências conceituais os materiais autorizados pelo usuário: *Reminiscências de Um Especulador Financeiro* (Jesse Livermore e Edward Lefèvre), Wyckoff 2.0, Smart Money Concepts de Marraik, Manual do Pullback e *Trading in the Zone*. Registre paráfrases curtas e a seção/página de cada regra. Se a localização ou o texto não tiver sido conferido, marque `needs_review`; não atribua ao livro uma regra que veio da especificação do usuário. Conflitos entre fontes permanecem explícitos. Nenhuma regra de leitura autoriza uma operação.

## 1. MarketObserver

Crie `MarketObserver` como camada permanente de observação, sem acesso a gateway de escrita, execução, dimensionamento definitivo ou autorização de ordens. Ele responde primeiro “o que o mercado está fazendo?” e só depois “há oportunidade validada neste contexto?”.

Quando os dados permitirem, observar timestamp e freshness, ativo, sessão, range da sessão, spread, volatilidade, estrutura em timeframes de contexto/estrutura/execução, swings confirmados e candidatos, impulso/correção, deslocamento, velocidade relativa, posição no range, oferta/demanda, zonas de interesse, liquidez, máximas/mínimas equivalentes, sweeps, rompimentos/falhas, BoS/CHoCH, desequilíbrios, preço-volume, confluências, conflitos entre timeframes e qualidade/completude dos dados.

Separar claramente observação, interpretação, hipótese, confirmação e invalidação. Não atribuir intenções humanas ao mercado. Descrever eventos verificáveis (“o preço varreu a mínima anterior”), não narrativas não observáveis (“institucionais manipularam”).

Produzir `MarketSnapshot` imutável e rastreável com: `snapshot_id`, `timestamp_utc`, `symbol`, `session`, `data_freshness`, `data_quality`, `spread`, `volatility_regime`, `market_regime`, timeframes e estruturas, `dominant_direction`, `dominant_swing`, `current_leg_type`, `range_position`, `liquidity_map`, `zones_of_interest`, `relevant_levels`, `volume_context`, evidências favoráveis/conflitantes/ausentes, narrativa curta, `clarity_status`, `observation_status` e `expires_at`.

`clarity_status`: `insufficient_data`, `unclear`, `mixed`, `developing`, `clear`.

`observation_status`: `observing`, `waiting_for_context`, `context_detected`, `waiting_for_zone`, `potential_opportunity`, `invalidated`, `halted`.

Estrutura ambígua, dado incompleto/atrasado, conflito material, falta de região ou gatilho, preço esticado, movimento avançado, spread/volatilidade desfavoráveis, sessão não autorizada ou risco elevado levam a `WAIT`/`NO_TRADE`. Permanecer observando indefinidamente é válido; quantidade de operações não é métrica de qualidade.

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

## Coordenação e fronteiras

`MarketDataProvider -> MarketObserver -> MarketSnapshot -> ExperienceMemory.retrieve_similar -> OpportunityDetector -> HypothesisBuilder -> ExpectationContract -> ExpectedVsObservedEngine -> DecisionEngine -> RiskManager -> (execução futura autorizada) -> ExperienceMemory.record -> HypothesisLab`.

- MarketObserver observa; ExperienceMemory recorda; ExpectedVsObservedEngine compara; HypothesisLab pesquisa.
- DecisionEngine propõe; RiskManager tem veto absoluto; um executor futuro só aceita decisão autorizada.
- Componentes de aprendizagem não alteram produção durante a sessão.
- Toda mensagem entre componentes carrega IDs/versões para auditoria.

## Máquina de estados V2

Use estados explícitos:

`BOOTING`, `CONNECTING`, `SYNCING_DATA`, `OBSERVING`, `BUILDING_CONTEXT`, `RETRIEVING_EXPERIENCE`, `FORMING_HYPOTHESIS`, `BUILDING_EXPECTATION`, `WAITING_FOR_ZONE`, `WAITING_FOR_TRIGGER`, `COMPARING_EXPECTED_OBSERVED`, `HYPOTHESIS_CONFIRMED`, `HYPOTHESIS_WEAKENING`, `HYPOTHESIS_INVALIDATED`, `VALIDATING_RISK`, `READY_TO_EXECUTE`, `ORDER_PENDING`, `POSITION_OPEN`, `MANAGING_POSITION`, `REVIEWING_EXPERIENCE`, `COOLDOWN`, `SESSION_HALTED`, `DATA_ERROR`, `RISK_LOCK`, `SHUTDOWN`.

Antes de qualquer execução futura, exigir a sequência `OBSERVING -> BUILDING_CONTEXT -> RETRIEVING_EXPERIENCE -> FORMING_HYPOTHESIS -> BUILDING_EXPECTATION -> WAITING_FOR_ZONE -> WAITING_FOR_TRIGGER -> COMPARING_EXPECTED_OBSERVED -> HYPOTHESIS_CONFIRMED -> VALIDATING_RISK -> READY_TO_EXECUTE`. Enfraquecimento volta a observar/esperar ou cancela. Invalidação cancela a hipótese, registra experiência e volta a observar. Nenhum estado habilita envio de ordens neste estágio.

## Métricas e testes adicionais

Medir ciclos/tempo de observação e espera, hipóteses por estado, NO_TRADE válido/inválido, oportunidades vetadas, entradas prematuras/tardias evitadas, sinais expirados, violações, aderência à expectativa, desvios do plano, qualidade do processo por estratégia/sessão/regime e P&L separado por classe de processo. Mais trades não é necessariamente melhor.

Testar que: MarketObserver não acessa escrita; a memória registra trade e não trade e preserva versões; similaridade informa amostra insuficiente; resultado financeiro e de processo são independentes; expectativa enfraquece/invalida/expira sem mutação retroativa; HypothesisLab não importa execução, não promove automaticamente e detecta leakage/look-ahead; custos e holdout são aplicados; replay é determinístico; hipótese invalidada bloqueia entrada; risco pode vetar hipótese confirmada; NO_TRADE é resultado normal; falha/atraso de dados cancela sinal; nenhuma ordem real é transmitida.

## Primeiro vertical slice V2

`MT5 ou replay -> validação de dados -> MarketObserver/Snapshot -> sessão -> estrutura -> recuperação de experiências -> hipótese -> ExpectationContract -> comparação esperado/observado -> decisão estruturada -> RiskManager -> NO_TRADE ou sinal hipotético -> ExperienceMemory persistente -> relatório`.

Começar por replay/histórico e manter execução real bloqueada. HypothesisLab usa somente dados históricos e experimentos isolados.

## Atualizações no prompt mestre anterior

1. Substituir a lista de estados da seção “Modelo de estados” pela “Máquina de estados V2” acima.
2. Na seção de aprendizado, acrescentar memória de experiências, resultados de processo, retrieval e pipeline do laboratório; preservar validação temporal e proibição de promoção automática.
3. Na arquitetura, acrescentar MarketObserver, ExperienceMemory, ExpectedVsObservedEngine e HypothesisLab como módulos separados, com fronteiras descritas acima.
4. Substituir o primeiro vertical slice pelo “Primeiro vertical slice V2”.
5. Acrescentar os testes e critérios deste adendo à seção de testes. Em caso de conflito, manter o bloqueio de risco/execução do prompt mestre e deixar a alternativa mais segura documentada.

## Referência Livermore

The local Livermore PDF in `Aprendizado/` was reviewed (216 pages; translation and technical review are identified on its front matter). Chapter I, pp. 5-6, describes tracking and comparing price behavior and keeping a notebook of forecasts and outcomes. Chapter II, p. 15, describes waiting to confirm a trend. Chapter V, pp. 48-49, distinguishes individual fluctuations from major moves and emphasizes waiting. These passages support the three educational concepts recorded in the knowledge catalog. They do not establish a statistical edge in Forex and are not entry rules; keep each rule at `needs_review` pending independent research validation.
