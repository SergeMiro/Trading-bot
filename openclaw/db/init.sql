-- ═══════════════════════════════════════════════════════════════
-- Trading Bot v2 — PostgreSQL Schema Initialization
-- This script runs automatically on first Docker Compose startup
-- ═══════════════════════════════════════════════════════════════

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─── Earnings Calendar ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS earnings_calendar (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    earnings_date VARCHAR(20) NOT NULL,
    is_confirmed BOOLEAN DEFAULT FALSE,
    source VARCHAR(50),
    market_cap FLOAT,
    sector VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    scan_date VARCHAR(20) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_earnings_ticker ON earnings_calendar(ticker);
CREATE INDEX IF NOT EXISTS ix_earnings_ticker_date ON earnings_calendar(ticker, earnings_date);
CREATE INDEX IF NOT EXISTS ix_earnings_scan_date ON earnings_calendar(scan_date);

-- ─── SEC Events ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sec_events (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    description TEXT,
    weight INTEGER DEFAULT 0,
    red_flag BOOLEAN DEFAULT FALSE,
    filing_date VARCHAR(20),
    total_score INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    scan_date VARCHAR(20) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sec_events_ticker ON sec_events(ticker);
CREATE INDEX IF NOT EXISTS ix_sec_events_scan_date ON sec_events(scan_date);

-- ─── Monitoring List ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS monitoring_list (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    rank INTEGER NOT NULL,
    sec_score INTEGER DEFAULT 0,
    source VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    scan_date VARCHAR(20) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_monitoring_ticker ON monitoring_list(ticker);

-- ─── Pre-Market Data ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS premarket_data (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    premarket_price FLOAT,
    premarket_volume FLOAT,
    avg_volume_14d FLOAT,
    volume_ratio FLOAT,
    atr_5d FLOAT,
    sector VARCHAR(100),
    sector_etf_change FLOAT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    scan_date VARCHAR(20) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_premarket_ticker ON premarket_data(ticker);
CREATE INDEX IF NOT EXISTS ix_premarket_scan_date ON premarket_data(scan_date);

-- ─── Scoring Results ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scoring_results (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    final_score INTEGER NOT NULL,
    recommendation VARCHAR(10) NOT NULL,
    breakdown JSONB,
    entry_price FLOAT,
    target_price FLOAT,
    stop_price FLOAT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    scan_date VARCHAR(20) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_scoring_ticker ON scoring_results(ticker);
CREATE INDEX IF NOT EXISTS ix_scoring_scan_date ON scoring_results(scan_date);
CREATE INDEX IF NOT EXISTS ix_scoring_recommendation ON scoring_results(recommendation);

-- ─── Open Positions ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS open_positions (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    entry_price FLOAT NOT NULL,
    quantity INTEGER NOT NULL,
    entry_time TIMESTAMP WITH TIME ZONE NOT NULL,
    target_price FLOAT NOT NULL,
    stop_price FLOAT NOT NULL,
    max_hold_until TIMESTAMP WITH TIME ZONE NOT NULL,
    scoring_id INTEGER REFERENCES scoring_results(id),
    status VARCHAR(20) DEFAULT 'open',
    predicted_gain_pct FLOAT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_positions_ticker ON open_positions(ticker);
CREATE INDEX IF NOT EXISTS ix_positions_status ON open_positions(status);

-- ─── Trade History ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trade_history (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    entry_price FLOAT NOT NULL,
    exit_price FLOAT NOT NULL,
    quantity INTEGER NOT NULL,
    entry_time TIMESTAMP WITH TIME ZONE NOT NULL,
    exit_time TIMESTAMP WITH TIME ZONE NOT NULL,
    pnl_amount FLOAT NOT NULL,
    pnl_percent FLOAT NOT NULL,
    exit_reason VARCHAR(50),
    scoring_id INTEGER REFERENCES scoring_results(id),
    predicted_gain_pct FLOAT,
    actual_gain_pct FLOAT,
    prediction_accuracy FLOAT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_history_ticker ON trade_history(ticker);
CREATE INDEX IF NOT EXISTS ix_history_exit_time ON trade_history(exit_time);
CREATE INDEX IF NOT EXISTS ix_history_exit_reason ON trade_history(exit_reason);

-- ─── Agent Logs ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_logs (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    message TEXT,
    input_data JSONB,
    output_data JSONB,
    execution_time_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_agent_logs_name ON agent_logs(agent_name);
CREATE INDEX IF NOT EXISTS ix_agent_logs_created ON agent_logs(created_at);

-- ─── Self-Learning Logs ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS self_learning_logs (
    id SERIAL PRIMARY KEY,
    trade_id INTEGER REFERENCES trade_history(id) NOT NULL,
    ticker VARCHAR(10) NOT NULL,
    predicted_gain_pct FLOAT,
    actual_gain_pct FLOAT,
    prediction_error FLOAT,
    chain_analysis JSONB,
    improvement_suggestions JSONB,
    suggested_skill_code TEXT,
    user_approved BOOLEAN,
    applied_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_self_learning_trade ON self_learning_logs(trade_id);
CREATE INDEX IF NOT EXISTS ix_self_learning_ticker ON self_learning_logs(ticker);

-- ─── Scoring Parameter History (for self-tuning) ────────────
CREATE TABLE IF NOT EXISTS scoring_param_history (
    id SERIAL PRIMARY KEY,
    param_name VARCHAR(100) NOT NULL,
    old_value FLOAT,
    new_value FLOAT,
    reason TEXT,
    approved_by VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ─── Useful Views ───────────────────────────────────────────

-- Win rate by week
CREATE OR REPLACE VIEW v_weekly_performance AS
SELECT
    date_trunc('week', exit_time) AS week,
    COUNT(*) AS total_trades,
    COUNT(*) FILTER (WHERE pnl_percent > 0) AS wins,
    COUNT(*) FILTER (WHERE pnl_percent <= 0) AS losses,
    ROUND(AVG(pnl_percent)::numeric, 2) AS avg_pnl_pct,
    ROUND(SUM(pnl_amount)::numeric, 2) AS total_pnl,
    ROUND(
        (COUNT(*) FILTER (WHERE pnl_percent > 0)::float / NULLIF(COUNT(*), 0) * 100)::numeric, 1
    ) AS win_rate
FROM trade_history
GROUP BY date_trunc('week', exit_time)
ORDER BY week DESC;

-- Prediction accuracy by week
CREATE OR REPLACE VIEW v_prediction_accuracy AS
SELECT
    date_trunc('week', exit_time) AS week,
    COUNT(*) AS total_trades,
    ROUND(AVG(prediction_accuracy)::numeric, 4) AS avg_accuracy,
    ROUND(AVG(ABS(predicted_gain_pct - actual_gain_pct))::numeric, 2) AS avg_error_pct,
    ROUND(AVG(predicted_gain_pct)::numeric, 2) AS avg_predicted,
    ROUND(AVG(actual_gain_pct)::numeric, 2) AS avg_actual
FROM trade_history
WHERE predicted_gain_pct IS NOT NULL
GROUP BY date_trunc('week', exit_time)
ORDER BY week DESC;

-- Exit reason distribution
CREATE OR REPLACE VIEW v_exit_reasons AS
SELECT
    exit_reason,
    COUNT(*) AS count,
    ROUND(AVG(pnl_percent)::numeric, 2) AS avg_pnl_pct,
    ROUND(SUM(pnl_amount)::numeric, 2) AS total_pnl
FROM trade_history
GROUP BY exit_reason
ORDER BY count DESC;

-- Grant access notice
-- In production, create a read-only user for Grafana:
-- CREATE USER grafana_reader WITH PASSWORD 'grafana_pass';
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_reader;
-- GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO grafana_reader;
