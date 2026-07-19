import type { AppConfig, Env, Tweet } from "./types";

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : null;
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number") return String(value);
  }
  return "";
}

export function parseDate(value: unknown): Date | null {
  if (value instanceof Date && !Number.isNaN(value.getTime())) return value;
  if (typeof value === "number") {
    const milliseconds = value > 10_000_000_000 ? value : value * 1000;
    const parsed = new Date(milliseconds);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
  if (typeof value !== "string" || !value.trim()) return null;
  const direct = new Date(value);
  if (!Number.isNaN(direct.getTime())) return direct;
  const epoch = Number.parseInt(value, 10);
  if (!Number.isFinite(epoch)) return null;
  const parsed = new Date(epoch * 1000);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function normalizeTweet(rawValue: unknown): Tweet | null {
  const raw = asRecord(rawValue);
  if (!raw) return null;
  const user = asRecord(raw.user_info) ?? asRecord(raw.user) ?? {};
  const id = firstString(
    raw.tweet_id,
    raw.id_str,
    raw.id,
    raw.tweetId,
    raw.conversation_id,
  );
  const userHandle = firstString(
    raw.screen_name,
    raw.username,
    raw.user_screen_name,
    user.screen_name,
    user.username,
  );
  const userName = firstString(raw.name, user.name, userHandle) || "Bilinmiyor";
  const text = firstString(raw.full_text, raw.text, raw.tweet, raw.content);
  const created = parseDate(raw.created_at ?? raw.date ?? raw.time);
  const link =
    firstString(raw.link, raw.url, raw.tweet_url) ||
    (id ? `https://x.com/${userHandle || "i/web"}/status/${id}` : "");
  if (!link || !text) return null;
  return {
    id: id || link,
    userHandle,
    userName,
    text,
    createdAt: created?.toISOString() ?? null,
    sortTimestamp: created?.getTime() ?? 0,
    link,
  };
}

export function extractTweets(payload: unknown): Tweet[] {
  let candidates: unknown[] = [];
  if (Array.isArray(payload)) {
    candidates = payload;
  } else {
    const record = asRecord(payload);
    for (const key of ["timeline", "data", "statuses", "result", "results"]) {
      if (record && Array.isArray(record[key])) {
        candidates = record[key] as unknown[];
        break;
      }
    }
  }
  return candidates
    .map(normalizeTweet)
    .filter((tweet): tweet is Tweet => tweet !== null)
    .sort((left, right) => right.sortTimestamp - left.sortTimestamp);
}

export function matchesQuery(query: string, tweet: Tweet): boolean {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return true;
  const text = tweet.text.toLowerCase();
  const link = tweet.link.toLowerCase();
  const handle = tweet.userHandle.toLowerCase();
  if (normalized.startsWith("from:")) return handle === normalized.slice(5).trim();
  if (normalized.startsWith("to:")) {
    const target = normalized.slice(3).trim();
    return Boolean(target) && (text.includes(target) || link.includes(target));
  }
  if (normalized.startsWith("@")) {
    const target = normalized.slice(1).trim();
    return Boolean(target) &&
      (text.includes(target) || handle === target || link.includes(target));
  }
  return normalized
    .split(/\s+/u)
    .filter(Boolean)
    .every((term) => text.includes(term));
}

async function fetchWithRetry(url: URL, init: RequestInit, attempts = 3): Promise<Response> {
  let lastResponse: Response | null = null;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const response = await fetch(url, init);
      if (response.ok || ![429, 500, 502, 503, 504].includes(response.status)) return response;
      lastResponse = response;
    } catch (error) {
      if (attempt === attempts - 1) throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250 * 2 ** attempt));
  }
  if (lastResponse) return lastResponse;
  throw new Error("Twitter API request failed without a response");
}

export async function fetchLatestTweets(
  env: Env,
  config: AppConfig,
  query: string,
): Promise<Tweet[]> {
  if (!env.RAPIDAPI_KEY) throw new Error("RAPIDAPI_KEY missing");
  const url = new URL("https://twitter-api45.p.rapidapi.com/search.php");
  url.searchParams.set("query", query);
  url.searchParams.set("search_type", config.queryType);
  const response = await fetchWithRetry(url, {
    headers: {
      "x-rapidapi-key": env.RAPIDAPI_KEY,
      "x-rapidapi-host": "twitter-api45.p.rapidapi.com",
    },
  });
  if (!response.ok) {
    throw new Error(`Twitter API error ${response.status}: ${(await response.text()).slice(0, 300)}`);
  }
  const tweets = extractTweets(await response.json()).filter((tweet) => matchesQuery(query, tweet));
  return tweets.slice(0, config.tweetLimit);
}

export function buildTweetMessage(tweet: Tweet): string {
  const createdAt = tweet.createdAt
    ? new Intl.DateTimeFormat("tr-TR", {
        timeZone: "Europe/Istanbul",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(new Date(tweet.createdAt))
    : "Bilinmiyor";
  return [
    "🐦 Yeni Tweet",
    "",
    `👤 Kullanıcı: ${tweet.userName}`,
    `💬 Tweet: ${tweet.text}`,
    `🕒 Tarih: ${createdAt}`,
    `🔗 Link: ${tweet.link}`,
  ].join("\n");
}
