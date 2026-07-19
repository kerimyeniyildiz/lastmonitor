import type { NewsEntry, RunSummary, Tweet } from "./types";

export async function claimSchedule(
  db: D1Database,
  key: string,
  nowSeconds: number,
  intervalSeconds: number,
): Promise<boolean> {
  const result = await db
    .prepare(
      `INSERT INTO schedules (key, next_run_at, updated_at)
       VALUES (?, ?, CURRENT_TIMESTAMP)
       ON CONFLICT(key) DO UPDATE SET
         next_run_at = excluded.next_run_at,
         updated_at = CURRENT_TIMESTAMP
       WHERE schedules.next_run_at <= ?`,
    )
    .bind(key, nowSeconds + intervalSeconds, nowSeconds)
    .run();
  return (result.meta.changes ?? 0) > 0;
}

export async function reserveTweet(
  db: D1Database,
  tweet: Tweet,
  query: string,
  status: string,
  filterReasons: string[],
): Promise<boolean> {
  const result = await db
    .prepare(
      `INSERT INTO tweets (
         tweet_id, query, user_handle, user_name, text, link,
         tweet_created_at, delivery_status, filter_reasons, fetched_at
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
       ON CONFLICT(link) DO UPDATE SET
         delivery_status = excluded.delivery_status,
         filter_reasons = excluded.filter_reasons,
         fetched_at = CURRENT_TIMESTAMP
       WHERE tweets.delivery_status = 'send_failed'
         AND tweets.fetched_at <= datetime('now', '-2 minutes')`,
    )
    .bind(
      tweet.id,
      query,
      tweet.userHandle,
      tweet.userName,
      tweet.text,
      tweet.link,
      tweet.createdAt,
      status,
      JSON.stringify(filterReasons),
    )
    .run();
  return (result.meta.changes ?? 0) > 0;
}

export async function updateTweetStatus(
  db: D1Database,
  link: string,
  status: string,
): Promise<void> {
  await db
    .prepare("UPDATE tweets SET delivery_status = ?, fetched_at = CURRENT_TIMESTAMP WHERE link = ?")
    .bind(status, link)
    .run();
}

export async function reserveNews(
  db: D1Database,
  entry: NewsEntry,
  status: string,
): Promise<boolean> {
  const result = await db
    .prepare(
      `INSERT INTO news (
         link, source, news_created_at, delivery_status, fetched_at
       ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
       ON CONFLICT(link) DO UPDATE SET
         delivery_status = excluded.delivery_status,
         fetched_at = CURRENT_TIMESTAMP
       WHERE news.delivery_status = 'send_failed'
         AND news.fetched_at <= datetime('now', '-2 minutes')`,
    )
    .bind(entry.link, entry.source, entry.createdAt, status)
    .run();
  return (result.meta.changes ?? 0) > 0;
}

export async function updateNewsStatus(
  db: D1Database,
  link: string,
  status: string,
): Promise<void> {
  await db
    .prepare("UPDATE news SET delivery_status = ?, fetched_at = CURRENT_TIMESTAMP WHERE link = ?")
    .bind(status, link)
    .run();
}

export async function recordRun(db: D1Database, summary: RunSummary): Promise<void> {
  await db
    .prepare(
      `INSERT INTO monitor_runs (
         kind, target, status, fetched_count, new_count, filtered_count,
         error, started_at, finished_at
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .bind(
      summary.kind,
      summary.target,
      summary.status,
      summary.fetchedCount,
      summary.newCount,
      summary.filteredCount,
      summary.error?.slice(0, 1000) ?? null,
      summary.startedAt,
      summary.finishedAt,
    )
    .run();
}
