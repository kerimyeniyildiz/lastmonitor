import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config";
import { evaluateTweetFilter, shouldDropTweet } from "../src/filter";
import type { Env, Tweet } from "../src/types";

const config = loadConfig({} as Env);

function tweet(handle: string, name: string, text: string): Tweet {
  return {
    id: "1",
    userHandle: handle,
    userName: name,
    text: `${text} https://t.co/example`,
    createdAt: "2026-07-19T17:00:00.000Z",
    sortTimestamp: 1,
    link: `https://x.com/${handle}/status/1`,
  };
}

describe("tweet filtering parity", () => {
  it("drops the observed Luleburgaz short-link campaign", () => {
    const samples = [
      ["Richard78459041", "Richard", "#lüleburgaz Verilerin dolup"],
      ["Olga1071492", "Olga", "ödemeli lüleburgaz ön öncelemek #çorlu"],
      ["Mildred1066551", "Mildred", "#lüleburgaz yazıldığı sen"],
      ["Henry094129372", "Henry", "#lüleburgaz inanışmışsın Gözlerin"],
      ["Joan70019329190", "Joan", "#lüleburgaz uygun ve"],
      ["Jonas448468", "Jonas", "Gözlerin olacak #lüleburgaz"],
    ];
    for (const [handle, name, text] of samples) {
      const reasons = evaluateTweetFilter(config, "Lüleburgaz", tweet(handle, name, text));
      expect(reasons).toContain("watch_pattern:luleburgaz_short_link_campaign");
      expect(shouldDropTweet(reasons)).toBe(true);
    }
  });

  it("keeps normal Luleburgaz announcements", () => {
    const samples = [
      tweet("Ahmet1987", "Ahmet", "#lüleburgaz deprem oldu"),
      tweet(
        "Ahmet123456",
        "Ahmet",
        "#lüleburgaz belediyesi yaz konserleri programını bu akşam kamuoyuyla paylaştı",
      ),
      tweet(
        "Trakya_Duyuru",
        "Trakya Duyuru",
        "Çorlu, Çerkezköy, Kapaklı, Tekirdağ ve Lüleburgaz ilçelerinde sağanak yağış bekleniyor",
      ),
    ];
    for (const item of samples) {
      expect(shouldDropTweet(evaluateTweetFilter(config, "Lüleburgaz", item))).toBe(false);
    }
  });

  it("does not apply the Luleburgaz campaign rule to other queries", () => {
    const reasons = evaluateTweetFilter(
      config,
      "Babaeski",
      tweet("sinan1050001", "sinan", "Hayırlı akşamlar BABAESKİ DEN"),
    );
    expect(shouldDropTweet(reasons)).toBe(false);
  });
});
