export interface Env {
  DB: D1Database;
  RAPIDAPI_KEY: string;
  TELEGRAM_TOKEN?: string;
  TELEGRAM_CHAT_ID?: string;
  API_TOKEN?: string;
  DELIVERY_MODE?: string;
  QUERY_TYPE?: string;
  TWEET_LIMIT?: string;
  QUERY_SCHEDULE?: string;
  TWEET_FILTER_MODE?: string;
  BLOCKED_TWEET_TERMS?: string;
  WATCH_TWEET_TERMS?: string;
  LOCATION_HASHTAG_TERMS?: string;
  TWEET_FILTER_BYPASS_QUERIES?: string;
  TWEET_REQUIRED_PREFIXES?: string;
  NEWS_LIMIT?: string;
  NEWS_MAX_AGE_HOURS?: string;
  NEWS_INTERVAL_SECONDS?: string;
  SITEMAP_URLS?: string;
  SITEMAP_MONTHLY_TEMPLATES?: string;
  SITEMAP_MONTH_LOOKBACK?: string;
  API_REQUIRE_TOKEN?: string;
}

export interface QuerySchedule {
  query: string;
  intervalSeconds: number;
}

export interface AppConfig {
  deliveryMode: "shadow" | "live";
  queryType: string;
  tweetLimit: number;
  querySchedule: QuerySchedule[];
  tweetFilterMode: "off" | "log" | "drop";
  blockedTweetTerms: string[];
  watchTweetTerms: string[];
  locationHashtagTerms: string[];
  tweetFilterBypassQueries: string[];
  tweetRequiredPrefixes: Record<string, string>;
  newsLimit: number;
  newsMaxAgeHours: number;
  newsIntervalSeconds: number;
  sitemapUrls: string[];
  sitemapMonthlyTemplates: string[];
  sitemapMonthLookback: number;
}

export interface Tweet {
  id: string;
  userHandle: string;
  userName: string;
  text: string;
  createdAt: string | null;
  link: string;
  sortTimestamp: number;
}

export interface NewsEntry {
  link: string;
  source: string;
  createdAt: string | null;
  sortTimestamp: number;
}

export interface RunSummary {
  kind: "tweets" | "news";
  target: string;
  status: "ok" | "error" | "skipped";
  fetchedCount: number;
  newCount: number;
  filteredCount: number;
  error?: string;
  startedAt: string;
  finishedAt: string;
}
