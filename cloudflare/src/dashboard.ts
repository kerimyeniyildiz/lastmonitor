import type { Env } from "./types";

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};
const ISTANBUL_OFFSET_MS = 3 * 60 * 60 * 1000;

function normalizedTimestampSql(column: string): string {
  return `datetime(
    CASE
      WHEN trim(${column}) GLOB '*[+-][0-9][0-9]' THEN trim(${column}) || ':00'
      ELSE trim(${column})
    END
  )`;
}

function eventTimestampSql(createdColumn: string): string {
  return `COALESCE(
    ${normalizedTimestampSql(createdColumn)},
    ${normalizedTimestampSql("fetched_at")}
  )`;
}

interface FeedCursor {
  at: string;
  kind: string;
  id: number;
}

interface FeedRow extends Record<string, unknown> {
  item_id: number;
  kind: string;
  display_at: string;
  filter_reasons: string;
}

function json(value: unknown, cacheSeconds = 0): Response {
  const headers = new Headers(JSON_HEADERS);
  if (cacheSeconds > 0) {
    headers.set("cache-control", `public, max-age=${cacheSeconds}`);
  }
  return new Response(JSON.stringify(value), { headers });
}

function parseLimit(value: string | null, fallback = 30, maximum = 60): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) ? Math.min(maximum, Math.max(1, parsed)) : fallback;
}

export function encodeFeedCursor(cursor: FeedCursor): string {
  return `${cursor.at}|${cursor.kind}|${cursor.id}`;
}

export function decodeFeedCursor(value: string | null): FeedCursor | null {
  if (!value) return null;
  const parts = value.split("|");
  if (parts.length !== 3) return null;
  const id = Number.parseInt(parts[2], 10);
  if (!parts[0] || !parts[1] || !Number.isFinite(id)) return null;
  return { at: parts[0], kind: parts[1], id };
}

export function dashboardPeriodStarts(now = new Date()): {
  today: string;
  week: string;
  month: string;
  year: string;
} {
  const local = new Date(now.getTime() + ISTANBUL_OFFSET_MS);
  const year = local.getUTCFullYear();
  const month = local.getUTCMonth();
  const day = local.getUTCDate();
  const todayLocal = Date.UTC(year, month, day);
  const mondayOffset = (local.getUTCDay() + 6) % 7;
  const toDatabaseTime = (localMilliseconds: number) =>
    new Date(localMilliseconds - ISTANBUL_OFFSET_MS)
      .toISOString()
      .slice(0, 19)
      .replace("T", " ");
  return {
    today: toDatabaseTime(todayLocal),
    week: toDatabaseTime(todayLocal - mondayOffset * 24 * 60 * 60 * 1000),
    month: toDatabaseTime(Date.UTC(year, month, 1)),
    year: toDatabaseTime(Date.UTC(year, 0, 1)),
  };
}

function feedSource(view: string): string {
  const tweetEventAt = eventTimestampSql("tweet_created_at");
  const newsEventAt = eventTimestampSql("news_created_at");
  const instagramEventAt = eventTimestampSql("content_created_at");
  const tweets = (status: "sent" | "filtered") => `
    SELECT id AS item_id, 'tweet' AS kind, query, user_handle, user_name,
           text, link, NULL AS source, delivery_status, filter_reasons,
           NULL AS preview_url, NULL AS content_type,
           strftime('%Y-%m-%dT%H:%M:%fZ', ${tweetEventAt}) AS display_at
    FROM tweets
    WHERE delivery_status = '${status}'`;
  const news = `
    SELECT id AS item_id, 'news' AS kind, NULL AS query, NULL AS user_handle,
           NULL AS user_name, NULL AS text, link, source, delivery_status,
           '[]' AS filter_reasons,
           NULL AS preview_url, NULL AS content_type,
           strftime('%Y-%m-%dT%H:%M:%fZ', ${newsEventAt}) AS display_at
    FROM news
    WHERE delivery_status = 'sent'`;
  const instagram = `
    SELECT id AS item_id, 'instagram' AS kind, NULL AS query,
           username AS user_handle, username AS user_name, caption AS text,
           link, 'Instagram' AS source, delivery_status, '[]' AS filter_reasons,
           preview_url,
           content_type,
           strftime('%Y-%m-%dT%H:%M:%fZ', ${instagramEventAt}) AS display_at
    FROM instagram_events
    WHERE delivery_status = 'sent'`;
  if (view === "tweets") return tweets("sent");
  if (view === "news") return news;
  if (view === "instagram") return instagram;
  if (view === "filtered") return tweets("filtered");
  return `${tweets("sent")} UNION ALL ${news} UNION ALL ${instagram}`;
}

export async function dashboardFeed(requestUrl: URL, env: Env): Promise<Response> {
  const requestedView = requestUrl.searchParams.get("view") || "all";
  const view = ["all", "tweets", "news", "instagram", "filtered"].includes(requestedView)
    ? requestedView
    : "all";
  const limit = parseLimit(requestUrl.searchParams.get("limit"));
  const cursor = decodeFeedCursor(requestUrl.searchParams.get("cursor"));
  const cursorWhere = cursor
    ? `WHERE display_at < ?
       OR (display_at = ? AND kind < ?)
       OR (display_at = ? AND kind = ? AND item_id < ?)`
    : "";
  const statement = env.DB.prepare(
    `WITH feed AS (${feedSource(view)})
     SELECT * FROM feed
     ${cursorWhere}
     ORDER BY display_at DESC, kind DESC, item_id DESC
     LIMIT ?`,
  );
  const bound = cursor
    ? statement.bind(
        cursor.at,
        cursor.at,
        cursor.kind,
        cursor.at,
        cursor.kind,
        cursor.id,
        limit + 1,
      )
    : statement.bind(limit + 1);
  const result = await bound.all<FeedRow>();
  const hasMore = result.results.length > limit;
  const items = result.results.slice(0, limit).map((row) => ({
    ...row,
    filter_reasons: JSON.parse(String(row.filter_reasons || "[]")),
  }));
  const last = items.at(-1);
  const nextCursor = hasMore && last
    ? encodeFeedCursor({
        at: String(last.display_at),
        kind: String(last.kind),
        id: Number(last.item_id),
      })
    : null;
  return json({ items, next_cursor: nextCursor });
}

function periodCountSql(table: "tweets" | "news" | "instagram_events", status: string): string {
  const createdColumn =
    table === "tweets"
      ? "tweet_created_at"
      : table === "news"
        ? "news_created_at"
        : "content_created_at";
  return `
    WITH records AS (
      SELECT ${eventTimestampSql(createdColumn)} AS event_at
      FROM ${table}
      WHERE delivery_status = '${status}'
    )
    SELECT
      SUM(CASE WHEN event_at >= ? THEN 1 ELSE 0 END) AS today,
      SUM(CASE WHEN event_at >= ? THEN 1 ELSE 0 END) AS week,
      SUM(CASE WHEN event_at >= ? THEN 1 ELSE 0 END) AS month,
      SUM(CASE WHEN event_at >= ? THEN 1 ELSE 0 END) AS year
    FROM records`;
}

function periodCounts(row: Record<string, unknown> | undefined): Record<string, number> {
  return {
    today: Number(row?.today || 0),
    week: Number(row?.week || 0),
    month: Number(row?.month || 0),
    year: Number(row?.year || 0),
  };
}

export async function dashboardStats(env: Env, now = new Date()): Promise<Response> {
  const starts = dashboardPeriodStarts(now);
  const periodBindings = [starts.today, starts.week, starts.month, starts.year];
  const activitySince = new Date(now.getTime() - 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 19)
    .replace("T", " ");
  const dailySince = new Date(now.getTime() - 13 * 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 19)
    .replace("T", " ");
  const [
    tweetCounts,
    newsCounts,
    instagramCounts,
    spamCounts,
    topAccounts,
    hourly,
    daily,
    lastSuccess,
    lastError,
  ] =
    await env.DB.batch([
      env.DB.prepare(periodCountSql("tweets", "sent")).bind(...periodBindings),
      env.DB.prepare(periodCountSql("news", "sent")).bind(...periodBindings),
      env.DB.prepare(periodCountSql("instagram_events", "sent")).bind(...periodBindings),
      env.DB.prepare(
        `WITH records AS (
           SELECT delivery_status, filter_reasons,
                  ${eventTimestampSql("tweet_created_at")} AS event_at
           FROM tweets
           WHERE delivery_status IN ('sent', 'filtered')
         )
         SELECT
           SUM(CASE WHEN delivery_status = 'filtered' AND filter_reasons NOT LIKE '%required_prefix_missing%' AND event_at >= ? THEN 1 ELSE 0 END) AS today,
           SUM(CASE WHEN delivery_status = 'filtered' AND filter_reasons NOT LIKE '%required_prefix_missing%' AND event_at >= ? THEN 1 ELSE 0 END) AS week,
           SUM(CASE WHEN delivery_status = 'filtered' AND filter_reasons NOT LIKE '%required_prefix_missing%' AND event_at >= ? THEN 1 ELSE 0 END) AS month,
           SUM(CASE WHEN delivery_status = 'filtered' AND filter_reasons NOT LIKE '%required_prefix_missing%' AND event_at >= ? THEN 1 ELSE 0 END) AS year,
           SUM(CASE WHEN event_at >= ? AND (delivery_status = 'sent' OR (delivery_status = 'filtered' AND filter_reasons NOT LIKE '%required_prefix_missing%')) THEN 1 ELSE 0 END) AS total_today
         FROM records`,
      ).bind(...periodBindings, starts.today),
      env.DB.prepare(
        `SELECT user_handle, MAX(user_name) AS user_name, COUNT(*) AS total
         FROM tweets
         WHERE query = 'Kırklareli'
           AND delivery_status = 'sent'
           AND ${eventTimestampSql("tweet_created_at")} >= ?
           AND COALESCE(user_handle, '') <> ''
         GROUP BY LOWER(user_handle)
         ORDER BY total DESC, user_handle ASC
         LIMIT 7`,
      ).bind(starts.year),
      env.DB.prepare(
        `WITH activity AS (
           SELECT 'tweet' AS kind, ${eventTimestampSql("tweet_created_at")} AS event_at
           FROM tweets WHERE delivery_status = 'sent'
           UNION ALL
           SELECT 'news' AS kind, ${eventTimestampSql("news_created_at")} AS event_at
           FROM news WHERE delivery_status = 'sent'
           UNION ALL
           SELECT 'instagram' AS kind, ${eventTimestampSql("content_created_at")} AS event_at
           FROM instagram_events WHERE delivery_status = 'sent'
         )
         SELECT strftime('%Y-%m-%d %H:00', event_at, '+3 hours') AS bucket,
                SUM(CASE WHEN kind = 'tweet' THEN 1 ELSE 0 END) AS tweets,
                SUM(CASE WHEN kind = 'news' THEN 1 ELSE 0 END) AS news,
                SUM(CASE WHEN kind = 'instagram' THEN 1 ELSE 0 END) AS instagram
         FROM activity
         WHERE event_at >= ?
         GROUP BY bucket
         ORDER BY bucket ASC`,
      ).bind(activitySince),
      env.DB.prepare(
        `WITH activity AS (
           SELECT 'tweet' AS kind, ${eventTimestampSql("tweet_created_at")} AS event_at
           FROM tweets WHERE delivery_status = 'sent'
           UNION ALL
           SELECT 'news' AS kind, ${eventTimestampSql("news_created_at")} AS event_at
           FROM news WHERE delivery_status = 'sent'
           UNION ALL
           SELECT 'instagram' AS kind, ${eventTimestampSql("content_created_at")} AS event_at
           FROM instagram_events WHERE delivery_status = 'sent'
         )
         SELECT date(event_at, '+3 hours') AS bucket,
                SUM(CASE WHEN kind = 'tweet' THEN 1 ELSE 0 END) AS tweets,
                SUM(CASE WHEN kind = 'news' THEN 1 ELSE 0 END) AS news,
                SUM(CASE WHEN kind = 'instagram' THEN 1 ELSE 0 END) AS instagram
         FROM activity
         WHERE event_at >= ?
         GROUP BY bucket
         ORDER BY bucket ASC`,
      ).bind(dailySince),
      env.DB.prepare(
        `SELECT kind, target, finished_at
         FROM monitor_runs WHERE status = 'ok'
         ORDER BY finished_at DESC LIMIT 1`,
      ),
      env.DB.prepare(
        `SELECT kind, target, error, finished_at
         FROM monitor_runs WHERE status = 'error'
         ORDER BY finished_at DESC LIMIT 1`,
      ),
    ]);

  const spam = (spamCounts.results[0] || {}) as Record<string, unknown>;
  const spamToday = Number(spam.today || 0);
  const totalToday = Number(spam.total_today || 0);
  return json({
    generated_at: now.toISOString(),
    tweets: periodCounts(tweetCounts.results[0] as Record<string, unknown> | undefined),
    news: periodCounts(newsCounts.results[0] as Record<string, unknown> | undefined),
    instagram: periodCounts(
      instagramCounts.results[0] as Record<string, unknown> | undefined,
    ),
    spam: {
      today: spamToday,
      week: Number(spam.week || 0),
      month: Number(spam.month || 0),
      year: Number(spam.year || 0),
      rate_today: totalToday > 0 ? Math.round((spamToday / totalToday) * 1000) / 10 : 0,
    },
    top_kirklareli_accounts: topAccounts.results,
    hourly_activity: hourly.results,
    daily_activity: daily.results,
    last_success: lastSuccess.results[0] || null,
    last_error: lastError.results[0] || null,
  }, 15);
}
