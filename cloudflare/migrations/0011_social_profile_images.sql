CREATE TABLE IF NOT EXISTS twitter_profiles (
    user_handle TEXT PRIMARY KEY COLLATE NOCASE,
    profile_image_url TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE instagram_flash_profiles ADD COLUMN profile_image_url TEXT;
ALTER TABLE instagram_flash_profiles ADD COLUMN profile_image_fetched_at TEXT;
