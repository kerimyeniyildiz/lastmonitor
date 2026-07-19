import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import { buildSitemapUrls, parseSitemapXml } from "../src/sitemap";
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
});
