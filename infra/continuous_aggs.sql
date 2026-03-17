-- Continuous aggregates for Grafana dashboards

-- Hourly prediction accuracy
CREATE MATERIALIZED VIEW prediction_accuracy_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', ts) AS bucket,
    COUNT(*) as n_predictions,
    COUNT(*) FILTER (WHERE resolved) as n_resolved,
    AVG(CASE WHEN resolved THEN (p_est - outcome)^2 END) as brier_score,
    AVG(edge) as avg_edge,
    AVG(confidence) as avg_confidence
FROM predictions
GROUP BY bucket;

-- Hourly trade summary
CREATE MATERIALIZED VIEW trade_summary_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', ts) AS bucket,
    COUNT(*) as n_trades,
    SUM(size) as total_volume,
    AVG(kelly_frac) as avg_kelly,
    COUNT(*) FILTER (WHERE status = 'FILLED') as fills,
    COUNT(*) FILTER (WHERE status = 'PAPER') as paper
FROM trades
GROUP BY bucket;

-- Daily scanner funnel
CREATE MATERIALIZED VIEW scanner_funnel_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', ts) AS bucket,
    AVG(stage_1) as avg_stage_1,
    AVG(stage_2) as avg_stage_2,
    AVG(stage_3) as avg_stage_3,
    AVG(stage_4) as avg_stage_4,
    AVG(stage_5) as avg_stage_5,
    AVG(duration_ms) as avg_scan_ms,
    COUNT(*) as n_cycles
FROM scanner_metrics
GROUP BY bucket;
