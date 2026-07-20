UPDATE tweets
SET tweet_created_at = tweet_created_at || ':00'
WHERE tweet_created_at GLOB '*[+-][0-9][0-9]';

UPDATE tweets
SET fetched_at = fetched_at || ':00'
WHERE fetched_at GLOB '*[+-][0-9][0-9]';

UPDATE news
SET news_created_at = news_created_at || ':00'
WHERE news_created_at GLOB '*[+-][0-9][0-9]';

UPDATE news
SET fetched_at = fetched_at || ':00'
WHERE fetched_at GLOB '*[+-][0-9][0-9]';
