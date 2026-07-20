import { describe, expect, it } from "vitest";
import {
  TELEGRAM_MESSAGE_SAFE_LIMIT,
  buildTweetMessage,
  extractTweets,
  matchesQuery,
  normalizeTweet,
} from "../src/twitter";

describe("Twitter response normalization", () => {
  it("normalizes the RapidAPI shape and builds a link", () => {
    const result = normalizeTweet({
      tweet_id: "123",
      text: "Kırklareli gündemi",
      created_at: "2026-07-19T20:00:00+03:00",
      user_info: { screen_name: "haber", name: "Haber" },
    });
    expect(result?.link).toBe("https://x.com/haber/status/123");
    expect(result?.userName).toBe("Haber");
    expect(result?.createdAt).toBe("2026-07-19T17:00:00.000Z");
  });

  it("extracts and sorts timeline tweets", () => {
    const results = extractTweets({
      timeline: [
        { tweet_id: "1", text: "Kırklareli", created_at: "2026-07-19T10:00:00Z", username: "a" },
        { tweet_id: "2", text: "Kırklareli", created_at: "2026-07-19T11:00:00Z", username: "b" },
      ],
    });
    expect(results.map((item) => item.id)).toEqual(["2", "1"]);
  });

  it("matches account and keyword queries", () => {
    const item = normalizeTweet({
      tweet_id: "1",
      text: "Kırklareli gündemi",
      username: "mustafaciftcitr",
    });
    expect(item).not.toBeNull();
    expect(matchesQuery("Kırklareli", item!)).toBe(true);
    expect(matchesQuery("from:mustafaciftcitr", item!)).toBe(true);
    expect(matchesQuery("from:başkası", item!)).toBe(false);
  });

  it("truncates long Telegram messages while preserving metadata and link", () => {
    const item = normalizeTweet({
      tweet_id: "long",
      text: "A".repeat(5000),
      created_at: "2026-07-20T17:00:00Z",
      user_info: { screen_name: "haber", name: "Haber" },
    });

    const message = buildTweetMessage(item!);

    expect(Array.from(message).length).toBeLessThanOrEqual(TELEGRAM_MESSAGE_SAFE_LIMIT);
    expect(message).toContain("A…\n🕒 Tarih:");
    expect(message).toContain("👤 Kullanıcı: Haber");
    expect(message.endsWith("🔗 Link: https://x.com/haber/status/long")).toBe(true);
  });
});
