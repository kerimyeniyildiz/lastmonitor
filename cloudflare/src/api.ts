import { parseBoolean } from "./config";
import { dashboardFeed, dashboardStats } from "./dashboard";
import { ingestInstagramEvent, ingestInstagramRun, serveInstagramMedia } from "./instagram";
import type { AppConfig, Env } from "./types";
import { runDueMonitors, sendTelegram } from "./monitor";

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "authorization, content-type",
  "access-control-allow-methods": "GET, POST, OPTIONS",
};

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: JSON_HEADERS });
}

function isAuthorized(request: Request, env: Env): boolean {
  const requireToken = parseBoolean(env.API_REQUIRE_TOKEN, true);
  if (!requireToken) return true;
  if (!env.API_TOKEN) return false;
  return request.headers.get("authorization") === `Bearer ${env.API_TOKEN}`;
}

function parseLimit(value: string | null, fallback = 50, maximum = 200): number {
  const parsed = Number.parseInt(value ?? "", 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(maximum, Math.max(1, parsed));
}

function parseOffset(value: string | null): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
}

async function listTweets(requestUrl: URL, env: Env): Promise<Response> {
  const filters: string[] = [];
  const values: unknown[] = [];
  const query = requestUrl.searchParams.get("q");
  const search = requestUrl.searchParams.get("search");
  const status = requestUrl.searchParams.get("status") || "sent";
  if (query) {
    filters.push("query = ?");
    values.push(query);
  }
  if (search) {
    filters.push("LOWER(text) LIKE LOWER(?)");
    values.push(`%${search}%`);
  }
  if (status !== "all") {
    filters.push("delivery_status = ?");
    values.push(status);
  }
  const where = filters.length ? `WHERE ${filters.join(" AND ")}` : "";
  const limit = parseLimit(requestUrl.searchParams.get("limit"));
  const offset = parseOffset(requestUrl.searchParams.get("offset"));
  const result = await env.DB
    .prepare(
      `SELECT tweet_id, query, user_handle, user_name, text, link,
              tweet_created_at, delivery_status, filter_reasons, fetched_at
       FROM tweets ${where}
       ORDER BY COALESCE(tweet_created_at, fetched_at) DESC
       LIMIT ? OFFSET ?`,
    )
    .bind(...values, limit, offset)
    .all<Record<string, unknown>>();
  const rows = result.results.map((row) => ({
    ...row,
    filter_reasons: JSON.parse(String(row.filter_reasons || "[]")),
  }));
  return json(rows);
}

async function listNews(requestUrl: URL, env: Env): Promise<Response> {
  const limit = parseLimit(requestUrl.searchParams.get("limit"));
  const offset = parseOffset(requestUrl.searchParams.get("offset"));
  const result = await env.DB
    .prepare(
      `SELECT link, source, news_created_at, delivery_status, fetched_at
       FROM news
       ORDER BY COALESCE(news_created_at, fetched_at) DESC
       LIMIT ? OFFSET ?`,
    )
    .bind(limit, offset)
    .all();
  return json(result.results);
}

async function status(env: Env, config: AppConfig): Promise<Response> {
  const [tweetCounts, newsCounts, recentRuns] = await env.DB.batch([
    env.DB.prepare("SELECT delivery_status, COUNT(*) AS total FROM tweets GROUP BY delivery_status"),
    env.DB.prepare("SELECT delivery_status, COUNT(*) AS total FROM news GROUP BY delivery_status"),
    env.DB.prepare(
      `SELECT kind, target, status, fetched_count, new_count, filtered_count,
              error, started_at, finished_at
       FROM monitor_runs ORDER BY finished_at DESC LIMIT 20`,
    ),
  ]);
  return json({
    status: "ok",
    delivery_mode: config.deliveryMode,
    tweet_counts: tweetCounts.results,
    news_counts: newsCounts.results,
    recent_runs: recentRuns.results,
  });
}

async function dailyStats(env: Env): Promise<Response> {
  const result = await env.DB
    .prepare(
      `SELECT date(COALESCE(tweet_created_at, fetched_at)) AS day,
              COUNT(*) AS tweets
       FROM tweets
       WHERE delivery_status IN ('sent', 'shadow')
       GROUP BY day
       ORDER BY day DESC
       LIMIT 90`,
    )
    .all();
  return json(result.results);
}

async function topQueries(requestUrl: URL, env: Env): Promise<Response> {
  const limit = parseLimit(requestUrl.searchParams.get("limit"), 20, 100);
  const result = await env.DB
    .prepare(
      `SELECT query, COUNT(*) AS total
       FROM tweets
       WHERE delivery_status IN ('sent', 'shadow')
       GROUP BY query
       ORDER BY total DESC
       LIMIT ?`,
    )
    .bind(limit)
    .all();
  return json(result.results);
}

export async function handleRequest(
  request: Request,
  env: Env,
  config: AppConfig,
): Promise<Response> {
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: JSON_HEADERS });
  const url = new URL(request.url);
  if (url.pathname === "/" || url.pathname === "/health") {
    try {
      await env.DB.prepare("SELECT 1").first();
      return json({ status: "ok", service: "lastmonitor-cloudflare", mode: config.deliveryMode });
    } catch (error) {
      return json({ status: "error", error: error instanceof Error ? error.message : String(error) }, 503);
    }
  }
  if (request.method === "GET" && url.pathname === "/api/dashboard/feed") {
    return dashboardFeed(url, env);
  }
  if (request.method === "GET" && url.pathname === "/api/dashboard/stats") {
    return dashboardStats(env);
  }
  if (request.method === "GET" && url.pathname.startsWith("/api/instagram/media/")) {
    return serveInstagramMedia(url, env);
  }
  if (request.method === "POST" && url.pathname === "/api/instagram/events") {
    return ingestInstagramEvent(request, env);
  }
  if (request.method === "POST" && url.pathname === "/api/instagram/runs") {
    return ingestInstagramRun(request, env);
  }
  if (!isAuthorized(request, env)) return json({ detail: "Unauthorized" }, 401);
  if (request.method === "GET" && url.pathname === "/status") return status(env, config);
  if (request.method === "GET" && url.pathname === "/tweets") return listTweets(url, env);
  if (request.method === "GET" && url.pathname === "/news") return listNews(url, env);
  if (request.method === "GET" && url.pathname === "/stats/daily") return dailyStats(env);
  if (request.method === "GET" && url.pathname === "/stats/top-queries") {
    return topQueries(url, env);
  }
  if (request.method === "POST" && url.pathname === "/admin/run") {
    const results = await runDueMonitors(env, config, true);
    return json({ results });
  }
  if (request.method === "POST" && url.pathname === "/admin/telegram/test") {
    await sendTelegram(
      env,
      "Lastmonitor Cloudflare gecis testi basarili.\n\nKaynak: Cloudflare Workers\nDurum: Telegram teslimati calisiyor.",
    );
    return json({ status: "ok" });
  }
  return json({ detail: "Not found" }, 404);
}
