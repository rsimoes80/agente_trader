# Contrato de decisão

Cada avaliação deve produzir um registro serializável, versionado e baseado somente nos dados disponíveis no instante da decisão.

```json
{
  "schema_version": 1,
  "decision_id": "uuid",
  "run_id": "uuid",
  "created_at_utc": "timestamp ISO-8601 com Z/offset",
  "symbol": "EURUSD",
  "timeframe": "M5",
  "data_source": "csv|replay|mt5|fix",
  "data_timestamp_utc": "timestamp do último candle fechado",
  "state": "NO_TRADE|CANDIDATE|RISK_REJECTED|HYPOTHETICAL_SIGNAL",
  "strategy_id": "pullback_trend",
  "strategy_version": "versionada",
  "config_hash": "sha256",
  "evidence": {"supporting": [], "contradicting": [], "missing": []},
  "risk": {"approved": false, "reasons": [], "budget": null},
  "hypothesis": {"side": null, "entry": null, "stop": null, "target": null},
  "reason_code": "NO_TRIGGER",
  "knowledge_rule_ids": []
}
```

`NO_TRADE` é o default. Campos de hipótese permanecem nulos quando faltarem dados ou regras. Candidato não significa autorização de ordem. Transições seguem BOOTING -> CONNECTING -> SYNCING_DATA -> OBSERVING -> BUILDING_CONTEXT -> WAITING_FOR_ZONE -> WAITING_FOR_TRIGGER -> VALIDATING_RISK -> READY_TO_EXECUTE (inexistente no escopo atual), com saídas possíveis para DATA_ERROR, RISK_LOCK, SESSION_HALTED e SHUTDOWN. Não permitir salto direto de observação para execução.

Registrar entradas e resultados de regras, não cadeia privada de raciocínio. O registro append-only deve incluir IDs, versões, timestamps, origem, qualidade dos dados e erros para reproduzir a decisão.
