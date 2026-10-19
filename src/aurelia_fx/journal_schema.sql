CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    created_at_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    session TEXT NOT NULL,
                    market_regime TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    data_reference TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    session TEXT NOT NULL,
                    market_regime TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiences (
                    experience_id TEXT PRIMARY KEY,
                    created_at_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    session TEXT NOT NULL,
                    market_regime TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    decision_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    config_version TEXT NOT NULL,
                    direction TEXT,
                    action_taken TEXT NOT NULL,
                    process_classification TEXT NOT NULL,
                    result_in_r REAL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    FOREIGN KEY(snapshot_id) REFERENCES market_snapshots(snapshot_id),
                    FOREIGN KEY(decision_id) REFERENCES decisions(decision_id)
                );
                CREATE INDEX IF NOT EXISTS ix_experiences_context
                    ON experiences(symbol, session, market_regime, strategy_id, strategy_version, direction);
                CREATE TABLE IF NOT EXISTS hypothesis_events (
                    event_id TEXT PRIMARY KEY,
                    hypothesis_id TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS expectation_events (
                    event_id TEXT PRIMARY KEY,
                    expectation_id TEXT NOT NULL,
                    hypothesis_id TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiment_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    created_at_utc TEXT NOT NULL,
                    dataset_reference TEXT NOT NULL,
                    code_version TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS simulated_execution_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    decision_id TEXT NOT NULL,
                    observed_at_utc TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    FOREIGN KEY(decision_id) REFERENCES decisions(decision_id)
                );
                CREATE INDEX IF NOT EXISTS ix_execution_run ON simulated_execution_events(run_id, observed_at_utc);
                CREATE TABLE IF NOT EXISTS market_intelligence (
                    evidence_set_id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL,
                    observed_at_utc TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    FOREIGN KEY(snapshot_id) REFERENCES market_snapshots(snapshot_id)
                );
