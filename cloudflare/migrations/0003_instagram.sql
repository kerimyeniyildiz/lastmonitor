CREATE TABLE IF NOT EXISTS instagram_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    instagram_id TEXT NOT NULL,
    username TEXT NOT NULL,
    content_type TEXT NOT NULL,
    caption TEXT,
    link TEXT NOT NULL,
    preview_key TEXT,
    content_created_at TEXT,
    delivery_status TEXT NOT NULL DEFAULT 'pending',
    telegram_status TEXT NOT NULL DEFAULT 'pending',
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_instagram_events_created_at
    ON instagram_events (content_created_at DESC);
CREATE INDEX IF NOT EXISTS idx_instagram_events_delivery_status
    ON instagram_events (delivery_status, content_created_at DESC);
CREATE INDEX IF NOT EXISTS idx_instagram_events_username
    ON instagram_events (username, content_created_at DESC);
