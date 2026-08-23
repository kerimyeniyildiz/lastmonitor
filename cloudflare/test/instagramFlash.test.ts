import { describe, expect, it } from "vitest";
import {
  extractFlashUserId,
  isInstagramShiftActive,
  normalizeFlashInstagram,
  parseFlashJson,
  shouldSeedFlashEvent,
} from "../src/instagramFlash";
import type { AppConfig } from "../src/types";

const shiftConfig = {
  instagramShiftAnchor: "2026-08-24T08:00:00+03:00",
  instagramShiftWorkHours: 18,
  instagramShiftCycleHours: 48,
} as AppConfig;

describe("FlashAPI Instagram support", () => {
  it("follows the 18-hour work and 30-hour off rotation", () => {
    expect(isInstagramShiftActive(new Date("2026-08-23T09:00:00+03:00"), shiftConfig))
      .toBe(false);
    expect(isInstagramShiftActive(new Date("2026-08-24T07:59:59+03:00"), shiftConfig))
      .toBe(false);
    expect(isInstagramShiftActive(new Date("2026-08-24T08:00:00+03:00"), shiftConfig))
      .toBe(true);
    expect(isInstagramShiftActive(new Date("2026-08-25T01:59:59+03:00"), shiftConfig))
      .toBe(true);
    expect(isInstagramShiftActive(new Date("2026-08-25T02:00:00+03:00"), shiftConfig))
      .toBe(false);
    expect(isInstagramShiftActive(new Date("2026-08-26T08:00:00+03:00"), shiftConfig))
      .toBe(true);
  });

  it("extracts a cached numeric user id from common response envelopes", () => {
    expect(extractFlashUserId({ data: { user_id: "123456789" } }, "rozmedyahaber"))
      .toBe("123456789");
    expect(extractFlashUserId({ user: { username: "kirklareli_gundem", pk: 987654 } }, "kirklareli_gundem"))
      .toBe("987654");
  });

  it("normalizes posts, reels and carousel covers", () => {
    const result = normalizeFlashInstagram(
      {
        items: [
          {
            pk: "111_99",
            code: "CAROUSEL1",
            media_type: 8,
            caption: { text: "Kırklareli'den yeni haber" },
            taken_at: 1_787_400_000,
            carousel_media: [
              {
                image_versions2: {
                  candidates: [{ url: "https://scontent.cdninstagram.com/first.jpg" }],
                },
              },
            ],
          },
          {
            pk: "222_99",
            code: "REEL2",
            media_type: 2,
            product_type: "clips",
            caption_text: "Yeni video",
            taken_at: 1_787_400_100,
            thumbnail_url: "https://scontent.fbcdn.net/reel.jpg",
          },
        ],
      },
      "rozmedyahaber",
      "feed",
    );

    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({
      event_key: "instagram:rozmedyahaber:feed:CAROUSEL1",
      content_type: "carousel",
      caption: "Kırklareli'den yeni haber",
      link: "https://www.instagram.com/p/CAROUSEL1/",
      preview_url: "https://scontent.cdninstagram.com/first.jpg",
    });
    expect(result[1]).toMatchObject({
      event_key: "instagram:rozmedyahaber:feed:REEL2",
      content_type: "reel",
      link: "https://www.instagram.com/p/REEL2/",
    });
  });

  it("preserves story ids beyond JavaScript's safe integer range", () => {
    const value = parseFlashJson(
      '{"items":[{"pk":3969497835019712179,"media_type":1,"taken_at":1787400200}]}',
    );
    const result = normalizeFlashInstagram(value, "rozmedyahaber", "story");

    expect(result[0]).toMatchObject({
      event_key: "instagram:rozmedyahaber:story:3969497835019712179",
      instagram_id: "3969497835019712179",
      link: "https://www.instagram.com/stories/rozmedyahaber/3969497835019712179/",
    });
  });

  it("silently stores old media that appears after the initial snapshot", () => {
    const watermark = Date.parse("2026-08-22T12:00:00.000Z");

    expect(shouldSeedFlashEvent(false, 0, "2026-08-22T12:00:00.000Z")).toBe(true);
    expect(shouldSeedFlashEvent(true, watermark, "2026-08-21T12:00:00.000Z")).toBe(true);
    expect(shouldSeedFlashEvent(true, watermark, "2026-08-22T12:00:01.000Z")).toBe(false);
  });

  it("normalizes nested story responses as cover-only events", () => {
    const result = normalizeFlashInstagram(
      {
        reels: {
          "123": {
            items: [
              {
                pk: "333_123",
                media_type: 2,
                taken_at: 1_787_400_200,
                image_versions2: {
                  candidates: [{ url: "https://scontent.cdninstagram.com/story.jpg" }],
                },
              },
            ],
          },
        },
      },
      "kirklareli_gundem",
      "story",
    );

    expect(result).toEqual([
      expect.objectContaining({
        event_key: "instagram:kirklareli_gundem:story:333",
        instagram_id: "333",
        content_type: "story",
        link: "https://www.instagram.com/stories/kirklareli_gundem/333/",
        preview_url: "https://scontent.cdninstagram.com/story.jpg",
      }),
    ]);
  });
});
