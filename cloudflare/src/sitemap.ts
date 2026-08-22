import { XMLParser } from "fast-xml-parser";
import type { AppConfig, NewsEntry } from "./types";
import { parseDate } from "./twitter";

const IMAGE_EXTENSIONS = [
  ".jpg",
  ".jpeg",
  ".png",
  ".gif",
  ".webp",
  ".svg",
  ".avif",
  ".bmp",
  ".tiff",
  ".ico",
];

const parser = new XMLParser({
  ignoreAttributes: true,
  processEntities: false,
  trimValues: true,
});

const HTML_ENTITIES: Record<string, string> = {
  amp: "&",
  apos: "'",
  gt: ">",
  hellip: "...",
  laquo: "\u00ab",
  ldquo: "\u201c",
  lsquo: "\u2018",
  lt: "<",
  mdash: "\u2014",
  nbsp: " ",
  ndash: "\u2013",
  quot: '"',
  raquo: "\u00bb",
  rdquo: "\u201d",
  rsquo: "\u2019",
};

function toArray<T>(value: T | T[] | undefined): T[] {
  if (value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

function textValue(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return String(value);
  return "";
}

function decodeHtmlEntities(value: string): string {
  return value.replace(/&(#(?:x[\da-f]+|\d+)|[a-z][\w]+);/giu, (entity, name: string) => {
    if (name.startsWith("#")) {
      const hexadecimal = name[1]?.toLowerCase() === "x";
      const codePoint = Number.parseInt(name.slice(hexadecimal ? 2 : 1), hexadecimal ? 16 : 10);
      if (Number.isInteger(codePoint) && codePoint >= 0 && codePoint <= 0x10ffff) {
        return String.fromCodePoint(codePoint);
      }
      return entity;
    }
    return HTML_ENTITIES[name.toLowerCase()] ?? entity;
  });
}

function cleanTitle(value: string): string | null {
  const title = decodeHtmlEntities(value)
    .replace(/<[^>]*>/gu, " ")
    .replace(/\s+/gu, " ")
    .trim();
  return title ? title.slice(0, 500) : null;
}

function tagAttributes(tag: string): Record<string, string> {
  const attributes: Record<string, string> = {};
  const pattern = /([^\s=/>]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>]+))/gu;
  for (const match of tag.matchAll(pattern)) {
    attributes[match[1].toLowerCase()] = match[2] ?? match[3] ?? match[4] ?? "";
  }
  return attributes;
}

export function extractNewsTitle(html: string): string | null {
  const candidates = new Map<string, string>();
  for (const tag of html.match(/<meta\b[^>]*>/giu) ?? []) {
    const attributes = tagAttributes(tag);
    const key = (attributes.property || attributes.name || "").toLowerCase();
    if ((key === "og:title" || key === "twitter:title") && attributes.content) {
      candidates.set(key, attributes.content);
    }
  }
  for (const key of ["og:title", "twitter:title"]) {
    const title = cleanTitle(candidates.get(key) ?? "");
    if (title) return title;
  }
  const documentTitle = html.match(/<title\b[^>]*>([\s\S]*?)<\/title>/iu)?.[1] ?? "";
  return cleanTitle(documentTitle);
}

export async function fetchNewsTitle(link: string): Promise<string | null> {
  const response = await fetch(link, {
    headers: {
      accept: "text/html,application/xhtml+xml",
      "user-agent": "lastmonitor-cloudflare/0.1",
    },
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new Error(`News page ${response.status}: ${link}`);
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  if (contentType && !contentType.includes("text/html") && !contentType.includes("xhtml")) {
    return null;
  }
  return extractNewsTitle(await response.text());
}

interface ParsedSitemap {
  children: string[];
  entries: Array<{ link: string; lastmod: string | null }>;
}

export function parseSitemapXml(content: string): ParsedSitemap {
  const parsed = parser.parse(content) as Record<string, unknown>;
  const sitemapIndex = parsed.sitemapindex as Record<string, unknown> | undefined;
  if (sitemapIndex) {
    return {
      children: toArray(sitemapIndex.sitemap as Record<string, unknown> | Record<string, unknown>[])
        .map((item) => textValue(item.loc))
        .filter(Boolean),
      entries: [],
    };
  }
  const urlset = parsed.urlset as Record<string, unknown> | undefined;
  const entries = toArray(urlset?.url as Record<string, unknown> | Record<string, unknown>[])
    .map((item) => ({
      link: textValue(item.loc),
      lastmod: textValue(item.lastmod) || null,
    }))
    .filter((item) => item.link.length > 0);
  return { children: [], entries };
}

function monthAtOffset(now: Date, offset: number): { year: number; month: number } {
  const date = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + offset, 1));
  return { year: date.getUTCFullYear(), month: date.getUTCMonth() + 1 };
}

export function buildSitemapUrls(config: AppConfig, now = new Date()): string[] {
  const urls = [...config.sitemapUrls];
  for (const template of config.sitemapMonthlyTemplates) {
    for (let offset = 0; offset >= -config.sitemapMonthLookback; offset -= 1) {
      const { year, month } = monthAtOffset(now, offset);
      urls.push(
        template
          .replaceAll("{YYYY}", String(year).padStart(4, "0"))
          .replaceAll("{YY}", String(year % 100).padStart(2, "0"))
          .replaceAll("{MM}", String(month).padStart(2, "0"))
          .replaceAll("{M}", String(month)),
      );
    }
  }
  return [...new Set(urls)];
}

export function isNewsArticleUrl(url: URL): boolean {
  if (url.pathname === "/" || url.pathname === "") return false;
  return !IMAGE_EXTENSIONS.some((extension) => url.pathname.toLowerCase().endsWith(extension));
}

async function fetchSitemap(url: string): Promise<ParsedSitemap> {
  const response = await fetch(url, {
    headers: { "user-agent": "lastmonitor-cloudflare/0.1" },
  });
  if (!response.ok) throw new Error(`Sitemap ${response.status}: ${url}`);
  return parseSitemapXml(await response.text());
}

export async function fetchNewsEntries(config: AppConfig): Promise<NewsEntry[]> {
  const roots = buildSitemapUrls(config);
  const settledRoots = await Promise.allSettled(roots.map(fetchSitemap));
  const rootResults = settledRoots
    .filter((item): item is PromiseFulfilledResult<ParsedSitemap> => item.status === "fulfilled")
    .map((item) => item.value);
  const children = [...new Set(rootResults.flatMap((item) => item.children))].slice(0, 20);
  const settledChildren = await Promise.allSettled(children.map(fetchSitemap));
  const allEntries = [
    ...rootResults.flatMap((item) => item.entries),
    ...settledChildren
      .filter((item): item is PromiseFulfilledResult<ParsedSitemap> => item.status === "fulfilled")
      .flatMap((item) => item.value.entries),
  ];
  const cutoff = Date.now() - config.newsMaxAgeHours * 3_600_000;
  const unique = new Map<string, NewsEntry>();
  for (const item of allEntries) {
    let parsedUrl: URL;
    try {
      parsedUrl = new URL(item.link);
    } catch {
      continue;
    }
    if (!isNewsArticleUrl(parsedUrl)) continue;
    const created = parseDate(item.lastmod);
    if (created && config.newsMaxAgeHours && created.getTime() < cutoff) continue;
    unique.set(item.link, {
      link: item.link,
      source: parsedUrl.hostname.replace(/^www\./u, ""),
      title: null,
      createdAt: created?.toISOString() ?? null,
      sortTimestamp: created?.getTime() ?? 0,
    });
  }
  return [...unique.values()]
    .sort((left, right) => right.sortTimestamp - left.sortTimestamp)
    .slice(0, config.newsLimit);
}

export function buildNewsMessage(entry: NewsEntry): string {
  const createdAt = entry.createdAt
    ? new Intl.DateTimeFormat("tr-TR", {
        timeZone: "Europe/Istanbul",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(new Date(entry.createdAt))
    : "Bilinmiyor";
  return [
    "📰 Yeni Haber",
    "",
    ...(entry.title ? [`📝 Başlık: ${entry.title}`, ""] : []),
    `🌐 Kaynak: ${entry.source || "Bilinmiyor"}`,
    `🕒 Tarih: ${createdAt}`,
    `🔗 Link: ${entry.link}`,
  ].join("\n");
}
