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
  it("normalizes stylized Unicode blocked terms", () => {
    const reasons = evaluateTweetFilter(
      config,
      "Kırklareli",
      tweet("Aaaaadcnc", "Random", "#kırklareli 𝕰𝕾𝕮𝕺𝕽𝕿 serbestsin"),
    );

    expect(reasons).toContain("blocked_term:escort");
    expect(shouldDropTweet(reasons)).toBe(true);
  });

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

  it("drops the observed generated location-link campaign", () => {
    const samples = [
      tweet("Daryl1057822", "Daryl", "🙄 et sineği #kırklareli hayrat"),
      tweet("Sadie131026", "Sadie", "güzel ☹ #kırklareli yeğlik"),
      tweet("Dolores867030", "Dolores", "ön yönetebilmek ☹ #kırklareli gün"),
    ];
    for (const item of samples) {
      const reasons = evaluateTweetFilter(config, "Kırklareli", item);
      expect(reasons).toContain("watch_pattern:generated_location_link_campaign");
      expect(shouldDropTweet(reasons)).toBe(true);
    }
  });

  it("keeps Alitek as a normal user", () => {
    const item = tweet("Alitek3959", "Ali Tek", "Lüleburgaz şu an yeri olan");
    item.text = "Lüleburgaz şu an yeri olan";

    expect(shouldDropTweet(evaluateTweetFilter(config, "Lüleburgaz", item))).toBe(false);
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
