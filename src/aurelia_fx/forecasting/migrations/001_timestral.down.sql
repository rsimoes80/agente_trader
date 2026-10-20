-- Development rollback only: preserve every historical forecast/evaluation.
DO $$ BEGIN
IF EXISTS(SELECT 1 FROM timestral_predictions) OR EXISTS(SELECT 1 FROM timestral_evaluations)
THEN RAISE EXCEPTION 'Cannot roll back Timestral with historical predictions'; END IF;
END $$;
DROP TABLE timestral_evaluations;
DROP TABLE timestral_predictions;
DROP TABLE timestral_model_registry;
DROP FUNCTION timestral_reject_mutation();
DROP TABLE timestral_schema_migrations;
