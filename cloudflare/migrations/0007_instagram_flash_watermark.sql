ALTER TABLE instagram_flash_groups
ADD COLUMN latest_content_at INTEGER NOT NULL DEFAULT 0;

UPDATE instagram_flash_groups
SET latest_content_at = COALESCE((
    SELECT MAX(CAST(strftime('%s', events.content_created_at) AS INTEGER) * 1000)
    FROM instagram_events AS events
    WHERE events.username = instagram_flash_groups.username
      AND events.content_created_at IS NOT NULL
      AND (
        (instagram_flash_groups.group_name = 'story' AND events.content_type = 'story')
        OR
        (instagram_flash_groups.group_name = 'feed' AND events.content_type <> 'story')
      )
), 0);
