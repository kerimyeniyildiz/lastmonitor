import { describe, expect, it } from "vitest";
import { buildInstagramMessage, validateInstagramPayload } from "../src/instagram";

const payload = {
  event_key: "instagram:rozmedyahaber:feed:ABC123",
  instagram_id: "ABC123",
  username: "rozmedyahaber",
  content_type: "reel" as const,
  caption: "Yeni haber",
  link: "https://www.instagram.com/reel/ABC123/",
  created_at: "2026-07-23T12:00:00+00:00",
};

describe("Instagram ingest helpers", () => {
  it("validates normalized Instagram events", () => {
    expect(validateInstagramPayload(payload)).toEqual(payload);
  });

  it("rejects non-Instagram links", () => {
    expect(() =>
      validateInstagramPayload({ ...payload, link: "https://example.com/ABC123" }),
    ).toThrow("instagram.com");
  });

  it("builds compact reel notifications without video data", () => {
    expect(buildInstagramMessage(payload)).toBe(
      "Instagram Reels\n" +
      "Hesap: @rozmedyahaber\n" +
      "Açıklama: Yeni haber\n" +
      "Bağlantı: https://www.instagram.com/reel/ABC123/",
    );
  });
});
