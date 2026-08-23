ALTER TABLE tweets ADD COLUMN delivered_at TEXT;
ALTER TABLE news ADD COLUMN delivered_at TEXT;

UPDATE tweets
SET delivered_at = fetched_at
WHERE delivery_status = 'sent' AND delivered_at IS NULL;

UPDATE news
SET delivered_at = fetched_at
WHERE delivery_status = 'sent' AND delivered_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_tweets_delivery_status_delivered_at
    ON tweets (delivery_status, delivered_at DESC);

CREATE INDEX IF NOT EXISTS idx_news_delivery_status_delivered_at
    ON news (delivery_status, delivered_at DESC);
