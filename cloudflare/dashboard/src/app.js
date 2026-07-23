import {
  Activity,
  BarChart3,
  Bird,
  Camera,
  CheckCircle2,
  Clock3,
  ExternalLink,
  Inbox,
  Newspaper,
  Radio,
  RefreshCw,
  Search,
  ShieldX,
  TriangleAlert,
  UsersRound,
  createIcons,
} from "lucide";
import "./styles.css";

const icons = {
  Activity,
  BarChart3,
  Bird,
  Camera,
  CheckCircle2,
  Clock3,
  ExternalLink,
  Inbox,
  Newspaper,
  Radio,
  RefreshCw,
  Search,
  ShieldX,
  TriangleAlert,
  UsersRound,
};

const state = {
  view: "all",
  items: [],
  pendingItems: [],
  cursor: null,
  autoFlow: true,
  loading: false,
  search: "",
};

const elements = {
  feedList: document.querySelector("#feedList"),
  feedEmpty: document.querySelector("#feedEmpty"),
  feedScroller: document.querySelector("#feedScroller"),
  feedSummary: document.querySelector("#feedSummary"),
  loadMore: document.querySelector("#loadMoreButton"),
  newItems: document.querySelector("#newItemsButton"),
  refresh: document.querySelector("#refreshButton"),
  autoFlow: document.querySelector("#autoFlowButton"),
  search: document.querySelector("#feedSearch"),
  lastUpdated: document.querySelector("#lastUpdated"),
  statsFreshness: document.querySelector("#statsFreshness"),
};

function renderIcons() {
  createIcons({ icons });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatNumber(value) {
  return new Intl.NumberFormat("tr-TR").format(Number(value || 0));
}

function formatDate(value, withSeconds = false) {
  if (!value) return "Kayıt yok";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Bilinmiyor";
  return new Intl.DateTimeFormat("tr-TR", {
    timeZone: "Europe/Istanbul",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" } : {}),
  }).format(date);
}

function relativeTime(value) {
  const milliseconds = Date.now() - new Date(value).getTime();
  const minutes = Math.floor(milliseconds / 60000);
  if (minutes < 1) return "şimdi";
  if (minutes < 60) return `${minutes} dk önce`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} sa önce`;
  return formatDate(value);
}

function itemKey(item) {
  return `${item.kind}:${item.item_id}`;
}

function titleFromUrl(link) {
  try {
    const url = new URL(link);
    const segments = url.pathname.split("/").filter(Boolean);
    const lastSegment = segments.at(-1) || "Yeni haber";
    const segment = decodeURIComponent(/^\d+$/.test(lastSegment) && segments.length > 1 ? segments.at(-2) : lastSegment);
    return segment
      .replace(/\.html?$/i, "")
      .replace(/[-_]+/g, " ")
      .replace(/\b\w/g, (character) => character.toLocaleUpperCase("tr-TR"));
  } catch {
    return "Yeni haber";
  }
}

function reasonLabel(reasons) {
  const labels = {
    required_prefix_missing: "Zorunlu başlık eşleşmedi",
    "block_pattern:location_hashtags_link_only": "Yalnızca konum etiketi ve bağlantı",
    "block_pattern:location_word_soup_link": "Otomatik konum kelime dizisi",
    "block_pattern:suspicious_location_link": "Şüpheli konum bağlantısı",
    "block_pattern:generated_location_link_campaign": "Otomatik oluşturulan kampanya",
    "block_pattern:generated_name_location_link_campaign": "Üretilmiş ad hesabı kampanyası",
    "block_pattern:trakya_location_word_campaign": "Toplu Trakya konum kampanyası",
    "block_pattern:trakya_location_dump_ad_campaign": "Toplu Trakya reklam konum listesi",
    "block_pattern:luleburgaz_short_link_campaign": "Kısa reklam kalıbı",
    "block_pattern:luleburgaz_ad_profile": "Reklam profili kalıbı",
    "block_pattern:luleburgaz_location_dump": "Toplu konum listesi",
  };
  return (reasons || [])
    .map((reason) =>
      labels[reason] ||
      (reason.startsWith("blocked_term:")
        ? `Engelli kelime: ${reason.split(":").slice(1).join(":")}`
        : reason.startsWith("blocked_handle:")
          ? `Engelli hesap: @${reason.split(":").slice(1).join(":")}`
          : reason)
    )
    .join(" · ");
}

function feedItemMarkup(item) {
  const filtered = item.delivery_status === "filtered";
  const isNews = item.kind === "news";
  const isInstagram = item.kind === "instagram";
  const itemClass = filtered
    ? "filtered-item"
    : isNews
      ? "news-item"
      : isInstagram
        ? "instagram-item"
        : "tweet-item";
  const icon = filtered ? "shield-x" : isNews ? "newspaper" : isInstagram ? "camera" : "bird";
  const identity = isNews
    ? item.source || "Haber kaynağı"
    : item.user_name || item.user_handle || (isInstagram ? "Instagram hesabı" : "X kullanıcısı");
  const instagramLabels = {
    post: "Gönderi",
    carousel: "Çoklu gönderi",
    reel: "Reels",
    story: "Story",
  };
  const subline = isNews
    ? "Haber"
    : isInstagram
      ? `@${item.user_handle} · ${instagramLabels[item.content_type] || "Instagram"}`
      : `${item.user_handle ? `@${item.user_handle}` : "X"}${item.query ? ` · ${item.query}` : ""}`;
  const copy = isNews ? titleFromUrl(item.link) : item.text || (isInstagram ? "Yeni Instagram içeriği" : "");
  const longCopy = copy.length > 360;
  const badge = filtered
    ? reasonLabel(item.filter_reasons) || "Filtrelendi"
    : isNews
      ? item.source
      : isInstagram
        ? instagramLabels[item.content_type] || "Instagram"
        : item.query;
  return `
    <article class="feed-item ${itemClass}" data-key="${escapeHtml(itemKey(item))}">
      <span class="feed-type-icon"><i data-lucide="${icon}"></i></span>
      <div class="feed-item-body">
        <div class="feed-item-head">
          <div class="feed-identity"><strong>${escapeHtml(identity)}</strong><span>${escapeHtml(subline)}</span></div>
          <time class="feed-time" datetime="${escapeHtml(item.display_at)}" title="${escapeHtml(formatDate(item.display_at, true))}">${escapeHtml(relativeTime(item.display_at))}</time>
        </div>
        ${isInstagram && item.preview_url ? `<img class="instagram-preview" src="${escapeHtml(item.preview_url)}" alt="@${escapeHtml(item.user_handle)} Instagram önizlemesi" loading="lazy" />` : ""}
        <p class="feed-copy${longCopy ? " is-collapsed" : ""}">${escapeHtml(copy)}</p>
        ${longCopy ? '<button class="expand-button" type="button">Devamını göster</button>' : ""}
        <div class="feed-item-footer">
          <span class="source-badge${filtered ? " danger-badge" : ""}">${escapeHtml(badge || (isNews ? "Haber" : "Tweet"))}</span>
          <a class="external-link" href="${escapeHtml(item.link)}" target="_blank" rel="noopener noreferrer">
            ${isNews ? "Haberi aç" : isInstagram ? "Instagram'da aç" : "X'te aç"}<i data-lucide="external-link"></i>
          </a>
        </div>
      </div>
    </article>`;
}

function filteredItems() {
  const needle = state.search.trim().toLocaleLowerCase("tr-TR");
  if (!needle) return state.items;
  return state.items.filter((item) =>
    [item.text, item.user_name, item.user_handle, item.query, item.source, item.content_type, item.link]
      .join(" ")
      .toLocaleLowerCase("tr-TR")
      .includes(needle),
  );
}

function renderFeed() {
  const items = filteredItems();
  elements.feedList.innerHTML = items.map(feedItemMarkup).join("");
  elements.feedEmpty.hidden = items.length > 0;
  elements.feedSummary.textContent = `${formatNumber(state.items.length)} kayıt gösteriliyor`;
  elements.loadMore.hidden = !state.cursor;
  elements.loadMore.disabled = state.loading;
  elements.loadMore.textContent = state.loading ? "Yükleniyor" : "Daha fazla göster";
  renderIcons();
}

async function fetchFeed({ append = false, poll = false } = {}) {
  if (state.loading && !poll) return;
  if (!poll) state.loading = true;
  const params = new URLSearchParams({ view: state.view, limit: "30" });
  if (append && state.cursor) params.set("cursor", state.cursor);
  try {
    const response = await fetch(`/api/dashboard/feed?${params}`);
    if (!response.ok) throw new Error(`Akış isteği başarısız: ${response.status}`);
    const data = await response.json();
    if (poll) {
      const known = new Set(state.items.map(itemKey));
      const incoming = data.items.filter((item) => !known.has(itemKey(item)));
      if (!incoming.length) return;
      if (state.autoFlow && elements.feedScroller.scrollTop < 80) {
        state.items = [...incoming, ...state.items];
        renderFeed();
        elements.feedScroller.scrollTo({ top: 0, behavior: "smooth" });
      } else {
        const pendingKnown = new Set(state.pendingItems.map(itemKey));
        state.pendingItems = [...incoming.filter((item) => !pendingKnown.has(itemKey(item))), ...state.pendingItems];
        elements.newItems.hidden = false;
        elements.newItems.textContent = `${state.pendingItems.length} yeni bildirim`;
      }
      return;
    }
    state.items = append ? [...state.items, ...data.items] : data.items;
    state.cursor = data.next_cursor;
  } catch (error) {
    elements.feedSummary.textContent = error instanceof Error ? error.message : "Akış alınamadı";
  } finally {
    if (!poll) state.loading = false;
    renderFeed();
  }
}

function readPath(object, path) {
  return path.split(".").reduce((value, key) => value?.[key], object);
}

function renderMetricValues(stats) {
  document.querySelectorAll("[data-stat]").forEach((element) => {
    const value = readPath(stats, element.dataset.stat);
    element.textContent = `${formatNumber(value)}${element.dataset.suffix || ""}`;
  });
}

function completeBuckets(rows, count, type) {
  const byBucket = new Map((rows || []).map((row) => [row.bucket, row]));
  const buckets = [];
  const now = new Date();
  for (let offset = count - 1; offset >= 0; offset -= 1) {
    const date = new Date(now.getTime() - offset * (type === "hour" ? 3600000 : 86400000));
    const parts = new Intl.DateTimeFormat("sv-SE", {
      timeZone: "Europe/Istanbul",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      ...(type === "hour" ? { hour: "2-digit", hour12: false } : {}),
    }).formatToParts(date).reduce((result, part) => ({ ...result, [part.type]: part.value }), {});
    const key = type === "hour"
      ? `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:00`
      : `${parts.year}-${parts.month}-${parts.day}`;
    buckets.push(byBucket.get(key) || { bucket: key, tweets: 0, news: 0, instagram: 0 });
  }
  return buckets;
}

function renderChart(element, rows, type) {
  const count = type === "hour" ? 24 : 14;
  const buckets = completeBuckets(rows, count, type);
  const maximum = Math.max(
    1,
    ...buckets.map(
      (row) => Number(row.tweets || 0) + Number(row.news || 0) + Number(row.instagram || 0),
    ),
  );
  element.innerHTML = buckets.map((row, index) => {
    const tweets = Number(row.tweets || 0);
    const news = Number(row.news || 0);
    const instagram = Number(row.instagram || 0);
    const total = tweets + news + instagram;
    const totalHeight = (total / maximum) * 100;
    const tweetHeight = total > 0 ? (tweets / total) * 100 : 0;
    const newsHeight = total > 0 ? (news / total) * 100 : 0;
    const instagramHeight = total > 0 ? (instagram / total) * 100 : 0;
    const showLabel = type === "hour" ? index % 6 === 0 || index === count - 1 : index % 3 === 0 || index === count - 1;
    const label = type === "hour" ? row.bucket.slice(11, 13) : row.bucket.slice(5).replace("-", "/");
    return `<div class="chart-column" title="${escapeHtml(label)} · ${tweets} tweet · ${news} haber · ${instagram} Instagram">
      <div class="chart-bars" style="height:${Math.max(totalHeight, total > 0 ? 3 : 1)}%">
        <span class="instagram-bar" style="height:${instagramHeight}%"></span>
        <span class="news-bar" style="height:${newsHeight}%"></span>
        <span class="tweet-bar" style="height:${tweetHeight}%"></span>
      </div>
      ${showLabel ? `<span class="chart-label">${escapeHtml(label)}</span>` : ""}
    </div>`;
  }).join("");
}

function renderAccounts(accounts) {
  const container = document.querySelector("#topAccounts");
  if (!accounts?.length) {
    container.innerHTML = '<div class="accounts-empty">Bu yıl için kayıt bulunmuyor.</div>';
    return;
  }
  const max = Math.max(...accounts.map((account) => Number(account.total || 0)), 1);
  container.innerHTML = accounts.map((account) => `
    <div class="account-row">
      <div class="account-info"><strong>${escapeHtml(account.user_name || account.user_handle)}</strong><span>@${escapeHtml(account.user_handle)}</span></div>
      <div class="account-track"><div class="account-bar" style="width:${(Number(account.total || 0) / max) * 100}%"></div></div>
      <span class="account-count">${formatNumber(account.total)}</span>
    </div>`).join("");
}

function renderSystem(stats) {
  const success = stats.last_success;
  const error = stats.last_error;
  document.querySelector("#lastSuccess").textContent = success ? formatDate(success.finished_at, true) : "Kayıt yok";
  document.querySelector("#lastSuccessTarget").textContent = success ? success.target : "";
  document.querySelector("#lastError").textContent = error ? `${error.target} · ${formatDate(error.finished_at, true)}` : "Hata yok";
  document.querySelector("#lastErrorMessage").textContent = error?.error || "Son hata kaydı bulunmuyor";
}

async function fetchStats() {
  const response = await fetch("/api/dashboard/stats");
  if (!response.ok) throw new Error(`İstatistik isteği başarısız: ${response.status}`);
  const stats = await response.json();
  renderMetricValues(stats);
  renderChart(document.querySelector("#hourlyChart"), stats.hourly_activity, "hour");
  renderChart(document.querySelector("#dailyChart"), stats.daily_activity, "day");
  renderAccounts(stats.top_kirklareli_accounts);
  renderSystem(stats);
  elements.statsFreshness.textContent = `${formatDate(stats.generated_at, true)} itibarıyla`;
  return stats;
}

async function refreshAll() {
  elements.refresh.classList.add("is-loading");
  elements.refresh.disabled = true;
  try {
    await Promise.all([fetchFeed(), fetchStats()]);
    elements.lastUpdated.textContent = `Son yenileme ${formatDate(new Date().toISOString(), true)}`;
  } catch (error) {
    elements.lastUpdated.textContent = error instanceof Error ? error.message : "Yenileme başarısız";
  } finally {
    elements.refresh.classList.remove("is-loading");
    elements.refresh.disabled = false;
    renderIcons();
  }
}

document.querySelector("#feedTabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-view]");
  if (!button || button.dataset.view === state.view) return;
  state.view = button.dataset.view;
  state.items = [];
  state.pendingItems = [];
  state.cursor = null;
  document.querySelectorAll("[data-view]").forEach((item) => item.classList.toggle("is-active", item === button));
  elements.newItems.hidden = true;
  fetchFeed();
});

elements.search.addEventListener("input", () => {
  state.search = elements.search.value;
  renderFeed();
});

elements.loadMore.addEventListener("click", () => fetchFeed({ append: true }));
elements.refresh.addEventListener("click", refreshAll);
elements.autoFlow.addEventListener("click", () => {
  state.autoFlow = !state.autoFlow;
  elements.autoFlow.classList.toggle("is-active", state.autoFlow);
  elements.autoFlow.setAttribute("aria-pressed", String(state.autoFlow));
});

elements.newItems.addEventListener("click", () => {
  state.items = [...state.pendingItems, ...state.items];
  state.pendingItems = [];
  elements.newItems.hidden = true;
  renderFeed();
  elements.feedScroller.scrollTo({ top: 0, behavior: "smooth" });
});

elements.feedList.addEventListener("click", (event) => {
  const button = event.target.closest(".expand-button");
  if (!button) return;
  const copy = button.previousElementSibling;
  copy.classList.toggle("is-collapsed");
  button.textContent = copy.classList.contains("is-collapsed") ? "Devamını göster" : "Daha az göster";
});

document.querySelectorAll("[data-mobile-view]").forEach((button) => {
  button.addEventListener("click", () => {
    const view = button.dataset.mobileView;
    document.querySelectorAll("[data-mobile-view]").forEach((item) => item.classList.toggle("is-active", item === button));
    document.querySelector("#feedPanel").classList.toggle("mobile-panel-active", view === "feed");
    document.querySelector("#statsPanel").classList.toggle("mobile-panel-active", view === "stats");
  });
});

renderIcons();
refreshAll();
setInterval(() => fetchFeed({ poll: true }), 15000);
setInterval(fetchStats, 60000);
