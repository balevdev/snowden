-- Snowden TimescaleDB Schema

-- Market tick data (price snapshots)
CREATE TABLE market_ticks (
    ts          TIMESTAMPTZ NOT NULL,
    token_id    TEXT        NOT NULL,
    market_id   TEXT        NOT NULL,
    mid         FLOAT8,
    spread      FLOAT8,
    vol_24h     FLOAT8,
    bid_depth   FLOAT8,
    ask_depth   FLOAT8
);
SELECT create_hypertable('market_ticks', 'ts');
CREATE INDEX idx_ticks_market ON market_ticks (market_id, ts DESC);

-- Predictions (every Analyst estimate)
CREATE TABLE predictions (
    ts          TIMESTAMPTZ NOT NULL,
    market_id   TEXT        NOT NULL,
    question    TEXT,
    p_market    FLOAT8,
    p_est       FLOAT8,
    p_est_raw   FLOAT8,
    confidence  FLOAT8,
    regime      TEXT,
    strategy    TEXT,
    edge        FLOAT8,
    reasoning   TEXT,
    data_quality FLOAT8     DEFAULT 0.5,
    resolved    BOOLEAN     DEFAULT FALSE,
    outcome     SMALLINT
);
SELECT create_hypertable('predictions', 'ts');
CREATE INDEX idx_pred_market ON predictions (market_id, ts DESC);
CREATE INDEX idx_pred_resolved ON predictions (resolved) WHERE resolved = true;

-- Trades (paper + live)
CREATE TABLE trades (
    ts          TIMESTAMPTZ NOT NULL,
    market_id   TEXT        NOT NULL,
    token_id    TEXT        NOT NULL,
    side        TEXT        NOT NULL,
    direction   TEXT        NOT NULL,
    size        FLOAT8,
    price       FLOAT8,
    order_id    TEXT,
    status      TEXT,
    strategy    TEXT,
    paper       BOOLEAN     DEFAULT TRUE,
    kelly_frac  FLOAT8,
    edge        FLOAT8
);
SELECT create_hypertable('trades', 'ts');
CREATE INDEX idx_trades_market ON trades (market_id, ts DESC);

-- Portfolio snapshots (one per cycle)
CREATE TABLE portfolio_snapshots (
    ts              TIMESTAMPTZ NOT NULL,
    bankroll        FLOAT8,
    total_equity    FLOAT8,
    heat            FLOAT8,
    daily_pnl       FLOAT8,
    daily_drawdown  FLOAT8,
    position_count  INT,
    cycle_number    INT
);
SELECT create_hypertable('portfolio_snapshots', 'ts');

-- Scanner metrics (one per cycle)
CREATE TABLE scanner_metrics (
    ts          TIMESTAMPTZ NOT NULL,
    stage_1     INT,
    stage_2     INT,
    stage_3     INT,
    stage_4     INT,
    stage_5     INT,
    duration_ms FLOAT8
);
SELECT create_hypertable('scanner_metrics', 'ts');

-- Market metadata cache
CREATE TABLE market_metadata (
    market_id       TEXT PRIMARY KEY,
    question        TEXT,
    description     TEXT,
    category        TEXT,
    end_date        TIMESTAMPTZ,
    resolution_source TEXT,
    yes_token_id    TEXT,
    no_token_id     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
