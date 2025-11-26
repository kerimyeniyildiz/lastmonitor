import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchDailyStats,
  fetchNews,
  fetchTopQueries,
  fetchTweets,
  News,
  QueryStat,
  Tweet,
} from "./api";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  PieChart,
  Pie,
  Cell,
  AreaChart,
  Area,
} from "recharts";

const COLORS = ["#2563eb", "#ea580c", "#16a34a", "#9333ea", "#0891b2", "#f59e0b"];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="card">
      <div className="card-head">
        <h2>{title}</h2>
      </div>
      {children}
    </section>
  );
}

function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="stat-card">
      <p className="muted">{label}</p>
      <h3>{value}</h3>
      {hint && <span className="muted small">{hint}</span>}
    </div>
  );
}

function TweetList({ tweets }: { tweets: Tweet[] }) {
  return (
    <div className="list">
      {tweets.map((tweet) => (
        <article key={tweet.link} className="item">
          <div className="meta">
            <span className="pill">{tweet.query}</span>
            <span>{tweet.tweet_created_at || tweet.fetched_at}</span>
          </div>
          <h3>{tweet.user_name}</h3>
          <p>{tweet.text}</p>
          <div className="links">
            <a href={tweet.link} target="_blank" rel="noreferrer">
              Tweeti aç
            </a>
            {tweet.user_handle && (
              <span className="muted">@{tweet.user_handle}</span>
            )}
          </div>
        </article>
      ))}
    </div>
  );
}

function NewsList({ items }: { items: News[] }) {
  return (
    <div className="list">
      {items.map((entry) => (
        <article key={entry.link} className="item">
          <div className="meta">
            <span className="pill">Haber</span>
            <span>{entry.news_created_at || entry.fetched_at}</span>
          </div>
          <p className="truncate">{entry.link}</p>
          <div className="links">
            <a href={entry.link} target="_blank" rel="noreferrer">
              Haberi aç
            </a>
            <span className="muted">{entry.source}</span>
          </div>
        </article>
      ))}
    </div>
  );
}

function DailyChart({ data }: { data: { day: string; tweets: number }[] }) {
  const mapped = data
    .map((d) => ({ day: d.day, tweets: d.tweets }))
    .reverse()
    .slice(-14);
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={mapped}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="day" />
        <YAxis allowDecimals={false} />
        <Tooltip />
        <Bar dataKey="tweets" fill="#2563eb" radius={4} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function QueryPie({ data }: { data: QueryStat[] }) {
  const trimmed = data.slice(0, 8);
  return (
    <ResponsiveContainer width="100%" height={240}>
      <PieChart>
        <Pie dataKey="total" data={trimmed} nameKey="query" outerRadius={90}>
          {trimmed.map((_, idx) => (
            <Cell key={idx} fill={COLORS[idx % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip />
      </PieChart>
    </ResponsiveContainer>
  );
}

export default function App() {
  const [queryFilter, setQueryFilter] = useState<string>("");
  const [search, setSearch] = useState<string>("");

  const tweetsQuery = useQuery({
    queryKey: ["tweets", queryFilter, search],
    queryFn: () => fetchTweets({ q: queryFilter || undefined, search: search || undefined }),
  });
  const newsQuery = useQuery({ queryKey: ["news"], queryFn: fetchNews });
  const dailyQuery = useQuery({ queryKey: ["daily"], queryFn: fetchDailyStats });
  const topQueries = useQuery({ queryKey: ["top-queries"], queryFn: () => fetchTopQueries(12) });

  const recentTweets = useMemo(() => {
    if (!tweetsQuery.data) return [];
    return tweetsQuery.data.slice(0, 20);
  }, [tweetsQuery.data]);

  const recentNews = useMemo(() => {
    if (!newsQuery.data) return [];
    return newsQuery.data.slice(0, 15);
  }, [newsQuery.data]);

  const queries = useMemo(() => {
    if (!tweetsQuery.data) return [];
    const set = new Set<string>();
    tweetsQuery.data.forEach((t) => set.add(t.query));
    return Array.from(set);
  }, [tweetsQuery.data]);

  const stats = useMemo(() => {
    const totalTweets = tweetsQuery.data?.length || 0;
    const uniqueQueries = new Set((tweetsQuery.data || []).map((t) => t.query)).size;
    const lastFetched = tweetsQuery.data?.[0]?.fetched_at || tweetsQuery.data?.[0]?.tweet_created_at;
    const lastNews = newsQuery.data?.[0]?.fetched_at || newsQuery.data?.[0]?.news_created_at;
    return { totalTweets, uniqueQueries, lastFetched, lastNews };
  }, [tweetsQuery.data, newsQuery.data]);

  const timeline = useMemo(() => {
    if (!tweetsQuery.data) return [];
    return tweetsQuery.data
      .map((t) => ({
        ts: t.tweet_created_at || t.fetched_at,
        query: t.query,
      }))
      .slice(0, 50);
  }, [tweetsQuery.data]);

  return (
    <div className="page">
      <header className="header">
        <div>
          <p className="muted">lastmonitor</p>
          <h1>Dashboard</h1>
        </div>
        <div className="filters">
          <select
            value={queryFilter}
            onChange={(e) => setQueryFilter(e.target.value)}
            className="input"
          >
            <option value="">Tüm sorgular</option>
            {queries.map((q) => (
              <option key={q} value={q}>
                {q}
              </option>
            ))}
          </select>
          <input
            className="input"
            placeholder="Metinde ara"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button className="btn ghost" onClick={() => tweetsQuery.refetch()}>
            Yenile
          </button>
        </div>
      </header>

      <div className="stats-row">
        <StatCard label="Toplam Tweet" value={stats.totalTweets} hint="Son sorgu seti" />
        <StatCard label="Sorgu Çeşidi" value={stats.uniqueQueries} />
        <StatCard label="Son Tweet" value={stats.lastFetched || "-"} />
        <StatCard label="Son Haber" value={stats.lastNews || "-"} />
      </div>

      <div className="grid">
        <Section title="Günlük Tweet Adedi (14g)">
          {dailyQuery.isLoading ? (
            <p className="muted">Yükleniyor...</p>
          ) : (
            <DailyChart data={dailyQuery.data || []} />
          )}
        </Section>

        <Section title="Sorgu Dağılımı">
          {topQueries.isLoading ? (
            <p className="muted">Yükleniyor...</p>
          ) : (
            <QueryPie data={topQueries.data || []} />
          )}
        </Section>
      </div>

      <div className="grid">
        <Section title="Son 50 Tweet Zaman Çizelgesi">
          {timeline.length === 0 ? (
            <p className="muted">Veri yok</p>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart
                data={timeline.map((t, i) => ({ name: i + 1, query: t.query, value: 1 }))}
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Area type="monotone" dataKey="value" stroke="#2563eb" fill="#2563eb33" />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </Section>
      </div>

      <div className="grid">
        <Section title="Son Tweetler">
          {tweetsQuery.isLoading && <p className="muted">Yükleniyor...</p>}
          {tweetsQuery.error && (
            <p className="error">Hata: {(tweetsQuery.error as Error).message}</p>
          )}
          {recentTweets.length === 0 && !tweetsQuery.isLoading ? (
            <p className="muted">Kayıt yok</p>
          ) : (
            <TweetList tweets={recentTweets} />
          )}
        </Section>

        <Section title="Son Haberler">
          {newsQuery.isLoading && <p className="muted">Yükleniyor...</p>}
          {newsQuery.error && <p className="error">Hata: {(newsQuery.error as Error).message}</p>}
          {recentNews.length === 0 && !newsQuery.isLoading ? (
            <p className="muted">Kayıt yok</p>
          ) : (
            <NewsList items={recentNews} />
          )}
        </Section>
      </div>

      <footer className="footer">
        <p className="muted">API: {import.meta.env.VITE_API_BASE_URL || "tanımlanmadı"}</p>
      </footer>
    </div>
  );
}
