const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";
const API_TOKEN = import.meta.env.VITE_API_TOKEN || "";

type FetchOptions = {
  path: string;
  search?: Record<string, string | number | undefined>;
};

async function request<T>({ path, search }: FetchOptions): Promise<T> {
  if (!API_BASE_URL) {
    throw new Error("API base URL is not set (VITE_API_BASE_URL).");
  }
  const url = new URL(path, API_BASE_URL);
  if (search) {
    Object.entries(search).forEach(([k, v]) => {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    });
  }
  const res = await fetch(url.toString(), {
    headers: {
      Authorization: `Bearer ${API_TOKEN}`,
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

export type Tweet = {
  tweet_id: string;
  query: string;
  user_handle: string;
  user_name: string;
  text: string;
  link: string;
  tweet_created_at: string;
  fetched_at: string;
};

export type News = {
  link: string;
  source: string;
  news_created_at: string;
  fetched_at: string;
};

export type DailyStat = { day: string; tweets: number };
export type QueryStat = { query: string; total: number };

export function fetchTweets(params?: { q?: string; search?: string }) {
  return request<Tweet[]>({ path: "/tweets", search: params });
}

export function fetchNews() {
  return request<News[]>({ path: "/news" });
}

export function fetchDailyStats() {
  return request<DailyStat[]>({ path: "/stats/daily" });
}

export function fetchTopQueries(limit = 10) {
  return request<QueryStat[]>({ path: "/stats/top-queries", search: { limit } });
}
