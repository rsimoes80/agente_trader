CREATE TABLE timestral_model_registry (
    model_key TEXT PRIMARY KEY, model TEXT NOT NULL, revision TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL, sdk_revision TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status='observe_only'),
    config JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE timestral_predictions (
    prediction_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL CHECK (scope IN ('live','replay')),
    source_id TEXT NOT NULL, symbol TEXT NOT NULL CHECK(symbol='EURUSD'),
    timeframe TEXT NOT NULL CHECK(timeframe='M5'),
    reference_time TIMESTAMPTZ NOT NULL, as_of TIMESTAMPTZ NOT NULL,
    target_time TIMESTAMPTZ NOT NULL, horizon INTEGER NOT NULL CHECK(horizon IN(3,6,12)),
    model_key TEXT NOT NULL REFERENCES timestral_model_registry(model_key),
    config_hash TEXT NOT NULL, median DOUBLE PRECISION NOT NULL CHECK(median>0),
    expected_return DOUBLE PRECISION NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('UP','DOWN','FLAT')),
    latency_ms DOUBLE PRECISION NOT NULL CHECK(latency_ms>=0),
    regime TEXT NOT NULL, payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK(as_of>=reference_time+INTERVAL '5 minutes'),
    CHECK(target_time=reference_time+horizon*INTERVAL '5 minutes'),
    UNIQUE(scope,source_id,symbol,timeframe,reference_time,horizon,model_key,config_hash)
);
CREATE INDEX timestral_predictions_lookup ON timestral_predictions(scope,symbol,timeframe,reference_time DESC);
CREATE INDEX timestral_predictions_targets ON timestral_predictions(scope,source_id,target_time);
CREATE INDEX timestral_predictions_models ON timestral_predictions(model_key,horizon,regime);
CREATE TABLE timestral_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    prediction_id TEXT NOT NULL UNIQUE REFERENCES timestral_predictions(prediction_id),
    observed_time TIMESTAMPTZ NOT NULL, observed_at TIMESTAMPTZ NOT NULL,
    actual_price DOUBLE PRECISION NOT NULL CHECK(actual_price>0),
    absolute_error DOUBLE PRECISION NOT NULL CHECK(absolute_error>=0),
    return_error DOUBLE PRECISION NOT NULL,
    directional_hit BOOLEAN NOT NULL, interval_covered BOOLEAN NOT NULL,
    payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK(observed_at>=observed_time+INTERVAL '5 minutes')
);
CREATE FUNCTION timestral_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Timestral records are immutable'; END $$;
CREATE TRIGGER immutable_timestral_predictions BEFORE UPDATE OR DELETE OR TRUNCATE
ON timestral_predictions FOR EACH STATEMENT EXECUTE FUNCTION timestral_reject_mutation();
CREATE TRIGGER immutable_timestral_evaluations BEFORE UPDATE OR DELETE OR TRUNCATE
ON timestral_evaluations FOR EACH STATEMENT EXECUTE FUNCTION timestral_reject_mutation();
CREATE TRIGGER immutable_timestral_model_registry BEFORE UPDATE OR DELETE OR TRUNCATE
ON timestral_model_registry FOR EACH STATEMENT EXECUTE FUNCTION timestral_reject_mutation();
