# Contrato de decisão

Cada avaliação deve produzir um registro serializável, versionado e baseado somente nos dados disponíveis no instante da decisão.

```json
{
  "schema_version": 3,
  "decision_id": "uuid",
  "run_id": "uuid",
  "created_at_utc": "timestamp ISO-8601 com Z/offset",
  "symbol": "EURUSD",
  "timeframe": "M5",
  "data_source": "csv|replay|mt5|fix",
  "data_timestamp_utc": "timestamp do último candle fechado",
  "action": "NO_TRADE|HYPOTHETICAL_SIGNAL",
  "state": "estado explícito de AgentState",
  "strategy_id": "research_breakout_retest",
  "strategy_version": "versionada",
  "config_hash": "sha256",
  "evidence": [],
  "contradictions": [],
  "missing_data": [],
  "risk": {"approved": false, "reasons": [], "risk_budget": null},
  "candidate": null,
  "snapshot_id": "identificador do snapshot V3",
  "hypothesis_id": null,
  "intelligence_context": {
    "trend_state_at_decision": "UNKNOWN",
    "trend_alignment": {},
    "trade_direction_class": "UNDEFINED",
    "price_action_state": {},
    "support_resistance_context": [],
    "evidence_set_id": "identificador auditável",
    "evidence_available": [],
    "evidence_missing": [],
    "conflicting_evidence": [],
    "evidence_state": "INSUFFICIENT",
    "confirmation_state": "not_evaluated",
    "trigger_state": "not_evaluated",
    "partial_reversal_state": "none",
    "observed_follow_through": "insufficient_data"
  },
  "reason_code": "NO_TRIGGER",
  "knowledge_rule_ids": []
}
```

`NO_TRADE` é o default. Campos de hipótese permanecem nulos quando faltarem dados ou regras. Candidato não significa autorização de ordem. Os estados incluem saídas para DATA_ERROR, RISK_LOCK, SESSION_HALTED e SHUTDOWN; nenhum salto direto de observação para execução é permitido.

Na V3, a percepção precede a recuperação de memória. A sequência completa passa por RETRIEVING_EXPERIENCE, FORMING_HYPOTHESIS, BUILDING_EXPECTATION e COMPARING_EXPECTED_OBSERVED. Confirmação sem gatilho permanece em WAITING_FOR_TRIGGER; apenas um gatilho válido e contexto aceito podem chegar a VALIDATING_RISK. READY_TO_EXECUTE é utilizado somente para sinal hipotético/simulador, sem transição para ordens reais. O instante `created_at_utc` é o fechamento que tornou os dados disponíveis; `data_timestamp_utc` identifica a abertura do candle de referência. Eventos posteriores não substituem a decisão.

Registrar entradas e resultados de regras, não cadeia privada de raciocínio. O registro append-only deve incluir IDs, versões, timestamps, origem, qualidade dos dados e erros para reproduzir a decisão.
