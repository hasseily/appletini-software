CREATE TABLE IF NOT EXISTS starfall_runs (
    run_id TEXT PRIMARY KEY CHECK(length(run_id) = 32),
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 12),
    version TEXT NOT NULL CHECK(length(version) BETWEEN 1 AND 24),
    platform TEXT NOT NULL CHECK(length(platform) BETWEEN 1 AND 24 AND platform NOT GLOB '*[^a-z0-9_-]*'),
    score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 9999999),
    sector INTEGER NOT NULL CHECK(sector BETWEEN 1 AND 256),
    kills INTEGER NOT NULL CHECK(kills BETWEEN 0 AND 999999),
    submitted_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS starfall_score_order ON starfall_runs(score DESC, submitted_at, run_id);
CREATE INDEX IF NOT EXISTS starfall_player ON starfall_runs(name, score DESC, submitted_at, run_id);
CREATE TABLE IF NOT EXISTS starfall_rate (
    rate_key TEXT NOT NULL,
    minute INTEGER NOT NULL,
    hits INTEGER NOT NULL,
    PRIMARY KEY(rate_key, minute)
);
