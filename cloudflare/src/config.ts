import type { AppConfig, Env, QuerySchedule } from "./types";

export const DEFAULT_BLOCKED_TWEET_TERMS = [
  "escort",
  "kırklarelibayan",
  "kırklarelieskort",
  "kırklareliesc",
];

export const DEFAULT_BLOCKED_TWEET_HANDLES = [
  "AddisonMorzsl",
  "GuzinKarad9jh",
  "dishugaharwar",
  "MariaBurnsv9yj",
  "EdwardHalldv",
  "QuintinAyaj8dx",
  "SophiaFreeyne",
  "KatharinaBbn",
  "SinanEmirofi",
  "GracaFragohqc",
  "CamdenHayegz6",
  "HelenRamirt9ur",
  "PolatAkyilwj",
  "EslemKayhax9",
  "AvelinaSoamma",
  "HulyaAksu69dv",
  "PatrickJenffpg",
  "TolgaOzcel5sz",
  "BeatrizBoo28653",
];

export const DEFAULT_WATCH_TWEET_TERMS = [
  "ücret elden",
  "ucret elden",
  "ödeme elden",
  "odeme elden",
  "ev otel",
  "apart rezidans",
  "otel rezidans",
];

export const DEFAULT_LOCATION_HASHTAG_TERMS = [
  "kırklareli",
  "kirklareli",
  "lüleburgaz",
  "luleburgaz",
  "babaeski",
  "pınarhisar",
  "pinarhisar",
  "kofçaz",
  "kofcaz",
  "demirköy",
  "demirkoy",
  "pehlivanköy",
  "pehlivankoy",
  "kapaklı",
  "kapakli",
  "tekirdağ",
  "tekirdag",
  "edirne",
];

const DEFAULT_BYPASS_QUERIES = [
  "from:mustafaciftcitr",
  "Valikirklareli",
  "KirklareliEmn",
];

export function parseList(value: string | undefined, fallback: string[] = []): string[] {
  if (!value) return [...fallback];
  return value
    .replaceAll("\n", ",")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function parseRequiredPrefixes(value: string | undefined): Record<string, string> {
  const prefixes: Record<string, string> = {};
  for (const item of parseList(value)) {
    const separator = item.indexOf("=>");
    if (separator <= 0) continue;
    const query = item.slice(0, separator).trim().toLowerCase();
    const prefix = item.slice(separator + 2).trim();
    if (query && prefix) prefixes[query] = prefix;
  }
  return prefixes;
}

export function parseInteger(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function parseBoolean(value: string | undefined, fallback = false): boolean {
  if (value === undefined) return fallback;
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
}

export function parseDurationSeconds(value: string | undefined, fallback: number): number {
  const raw = (value ?? "").trim().toLowerCase();
  if (!raw) return fallback;
  const match = raw.match(/^(\d+)\s*([hms]?)$/);
  if (!match) return fallback;
  const amount = Number.parseInt(match[1], 10);
  const multiplier = match[2] === "h" ? 3600 : match[2] === "m" ? 60 : 1;
  return Math.max(1, amount * multiplier);
}

export function parseQuerySchedule(value: string | undefined): QuerySchedule[] {
  const raw = value?.trim() || "Kırklareli|5m";
  return raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const separator = item.includes("|") ? "|" : ":";
      const [rawQuery, rawInterval] = item.split(separator, 2);
      const query =
        rawQuery.trim().toLowerCase() === "from:aliyerlikaya"
          ? "from:mustafaciftcitr"
          : rawQuery.trim();
      return {
        query,
        intervalSeconds: parseDurationSeconds(rawInterval, 300),
      };
    })
    .filter((item) => item.query.length > 0);
}

export function loadConfig(env: Env): AppConfig {
  const rawDeliveryMode = (env.DELIVERY_MODE || "shadow").toLowerCase();
  const rawFilterMode = (env.TWEET_FILTER_MODE || "drop").toLowerCase();
  return {
    deliveryMode: rawDeliveryMode === "live" ? "live" : "shadow",
    queryType: env.QUERY_TYPE || "Latest",
    tweetLimit: Math.max(1, parseInteger(env.TWEET_LIMIT, 20)),
    querySchedule: parseQuerySchedule(env.QUERY_SCHEDULE),
    tweetFilterMode:
      rawFilterMode === "off" || rawFilterMode === "log" ? rawFilterMode : "drop",
    blockedTweetTerms: parseList(env.BLOCKED_TWEET_TERMS, DEFAULT_BLOCKED_TWEET_TERMS),
    blockedTweetHandles: parseList(
      env.BLOCKED_TWEET_HANDLES,
      DEFAULT_BLOCKED_TWEET_HANDLES,
    ).map((handle) => handle.replace(/^@/, "").toLowerCase()),
    watchTweetTerms: parseList(env.WATCH_TWEET_TERMS, DEFAULT_WATCH_TWEET_TERMS),
    locationHashtagTerms: parseList(
      env.LOCATION_HASHTAG_TERMS,
      DEFAULT_LOCATION_HASHTAG_TERMS,
    ),
    tweetFilterBypassQueries: parseList(
      env.TWEET_FILTER_BYPASS_QUERIES,
      DEFAULT_BYPASS_QUERIES,
    ),
    tweetRequiredPrefixes: parseRequiredPrefixes(env.TWEET_REQUIRED_PREFIXES),
    newsLimit: Math.max(1, parseInteger(env.NEWS_LIMIT, 10)),
    newsMaxAgeHours: Math.max(0, parseInteger(env.NEWS_MAX_AGE_HOURS, 72)),
    newsIntervalSeconds: Math.max(60, parseInteger(env.NEWS_INTERVAL_SECONDS, 600)),
    sitemapUrls: parseList(env.SITEMAP_URLS, [
      "https://www.onadimgazetesi.com/sitemap.xml",
    ]),
    sitemapMonthlyTemplates: parseList(env.SITEMAP_MONTHLY_TEMPLATES, [
      "https://www.alternatifgazetesi.com/sitemap/sitemap-{YYYY}-{MM}.xml",
    ]),
    sitemapMonthLookback: Math.max(0, parseInteger(env.SITEMAP_MONTH_LOOKBACK, 1)),
  };
}
