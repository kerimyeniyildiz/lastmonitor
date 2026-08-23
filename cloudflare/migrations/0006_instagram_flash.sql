CREATE TABLE IF NOT EXISTS instagram_flash_profiles (
    username TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS instagram_flash_groups (
    username TEXT NOT NULL,
    group_name TEXT NOT NULL,
    initialized_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (username, group_name)
);
