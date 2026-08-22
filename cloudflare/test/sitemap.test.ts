import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import {
  buildNewsMessage,
  buildSitemapUrls,
  extractNewsTitle,
  isNewsArticleUrl,
  parseSitemapXml,
} from "../src/sitemap";
import type { Env } from "../src/types";

describe("sitemap support", () => {
  it("parses URL sets", () => {
    const parsed = parseSitemapXml(`<?xml version="1.0"?>
      <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://example.com/a</loc><lastmod>2026-07-19T10:00:00Z</lastmod></url>
      </urlset>`);
    expect(parsed.entries).toEqual([
      { link: "https://example.com/a", lastmod: "2026-07-19T10:00:00Z" },
    ]);
  });

  it("builds current and previous monthly sitemap URLs", () => {
    const config = loadConfig({} as Env);
    const urls = buildSitemapUrls(config, new Date("2026-07-19T00:00:00Z"));
    expect(urls).toContain("https://www.alternatifgazetesi.com/sitemap/sitemap-2026-07.xml");
    expect(urls).toContain("https://www.alternatifgazetesi.com/sitemap/sitemap-2026-06.xml");
  });

  it("keeps homepages and media files out of the article limit", () => {
    expect(isNewsArticleUrl(new URL("https://example.com/"))).toBe(false);
    expect(isNewsArticleUrl(new URL("https://example.com/uploads/photo.jpg"))).toBe(false);
    expect(isNewsArticleUrl(new URL("https://example.com/kirklarelide-yeni-haber"))).toBe(true);
  });

  it("extracts and decodes Turkish Open Graph titles", () => {
    const html = `<!doctype html><html><head>
      <meta content="Kırklareli&#39;nin Genç Hokeycileri Türkiye Şampiyonu!" property="og:title">
      <title>URL tabanlı yedek başlık</title>
    </head></html>`;
    expect(extractNewsTitle(html)).toBe("Kırklareli'nin Genç Hokeycileri Türkiye Şampiyonu!");
  });

  it("falls back to the document title", () => {
    expect(extractNewsTitle("<title>Pınarhisar’da Kartal Park Gün Sayıyor &amp; Açılıyor</title>"))
      .toBe("Pınarhisar’da Kartal Park Gün Sayıyor & Açılıyor");
  });

  it("includes the real title in Telegram news messages", () => {
    const message = buildNewsMessage({
      link: "https://example.com/kirklareli-haberi",
      source: "example.com",
      title: "Kırklareli'de Şampiyonluk Sevinci",
      createdAt: "2026-08-22T12:00:00.000Z",
      sortTimestamp: Date.parse("2026-08-22T12:00:00.000Z"),
    });
    expect(message).toContain("📝 Başlık: Kırklareli'de Şampiyonluk Sevinci");
    expect(message).toContain("🔗 Link: https://example.com/kirklareli-haberi");
  });
});
