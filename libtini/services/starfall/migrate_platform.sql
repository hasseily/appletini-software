-- Apply only when an older starfall_runs table has no platform column.
ALTER TABLE starfall_runs ADD COLUMN platform TEXT NOT NULL DEFAULT 'unknown'
    CHECK(length(platform) BETWEEN 1 AND 24 AND platform NOT GLOB '*[^a-z0-9_-]*');
