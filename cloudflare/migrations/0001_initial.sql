CREATE TABLE IF NOT EXISTS tweets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id TEXT,
    query TEXT NOT NULL,
    user_handle TEXT,
    user_name TEXT,
    text TEXT NOT NULL,
    link TEXT NOT NULL UNIQUE,
    tweet_created_at TEXT,
    delivery_status TEXT NOT NULL,
    filter_reasons TEXT NOT NULL DEFAULT '[]',
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tweets_query_created_at
    ON tweets (query, tweet_created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tweets_delivery_status_created_at
    ON tweets (delivery_status, tweet_created_at DESC);

CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    link TEXT NOT NULL UNIQUE,
    source TEXT,
    news_created_at TEXT,
    delivery_status TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_news_created_at
    ON news (news_created_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_delivery_status
    ON news (delivery_status, news_created_at DESC);

CREATE TABLE IF NOT EXISTS schedules (
    key TEXT PRIMARY KEY,
    next_run_at INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS monitor_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    status TEXT NOT NULL,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    new_count INTEGER NOT NULL DEFAULT 0,
    filtered_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_monitor_runs_finished_at
    ON monitor_runs (finished_at DESC);
