-- Observability schema additions

ALTER TABLE scanner_metrics ADD COLUMN IF NOT EXISTS s1_ms FLOAT8;
ALTER TABLE scanner_metrics ADD COLUMN IF NOT EXISTS s2_ms FLOAT8;
ALTER TABLE scanner_metrics ADD COLUMN IF NOT EXISTS s3_ms FLOAT8;
ALTER TABLE scanner_metrics ADD COLUMN IF NOT EXISTS s4_ms FLOAT8;
ALTER TABLE scanner_metrics ADD COLUMN IF NOT EXISTS s5_ms FLOAT8;
ALTER TABLE scanner_metrics ADD COLUMN IF NOT EXISTS cycle_success BOOLEAN;
ALTER TABLE scanner_metrics ADD COLUMN IF NOT EXISTS cycle_error TEXT;
ALTER TABLE scanner_metrics ADD COLUMN IF NOT EXISTS cycle_duration_ms FLOAT8;

CREATE TABLE IF NOT EXISTS error_log (
    ts          TIMESTAMPTZ NOT NULL,
    source      TEXT NOT NULL,
    error_type  TEXT NOT NULL,
    message     TEXT
);
SELECT create_hypertable('error_log', 'ts', if_not_exists => TRUE);
