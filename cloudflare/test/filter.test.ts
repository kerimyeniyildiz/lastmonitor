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
  it("only keeps tweets with the configured query-specific prefix", () => {
    const prefixConfig = loadConfig({
      TWEET_REQUIRED_PREFIXES: "from:bpthaber=>SON DAKİKA",
    } as Env);
    const matching = tweet(
      "bpthaber",
      "BPT",
      "  son dakika | Örnek gelişme",
    );
    const unrelated = tweet("bpthaber", "BPT", "Günün öne çıkan haberleri");

    expect(evaluateTweetFilter(prefixConfig, "from:bpthaber", matching)).toEqual([]);
    const reasons = evaluateTweetFilter(prefixConfig, "from:bpthaber", unrelated);
    expect(reasons).toContain("required_prefix_missing");
    expect(shouldDropTweet(reasons)).toBe(true);
    expect(evaluateTweetFilter(prefixConfig, "from:mustafaciftcitr", unrelated)).toEqual([]);
  });

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
      expect(reasons).toContain("block_pattern:luleburgaz_short_link_campaign");
      expect(shouldDropTweet(reasons)).toBe(true);
    }
  });

  it("drops dense Luleburgaz location ads without relying on handle shape", () => {
    const item = tweet(
      "janagama_ravi",
      "ÇITIR KIZLAR",
      "Her şey güzel olacak 💞 çorlu,çerkezköy,kapaklı,tekirdağ,lüleburgaz,şarkköy,malkara,hayrabolu,saray,ergene,muratlı,marmaraereğlisi,bayan,",
    );

    const reasons = evaluateTweetFilter(config, "Lüleburgaz", item);

    expect(reasons).toContain("block_pattern:luleburgaz_location_dump");
    expect(shouldDropTweet(reasons)).toBe(true);
  });

  it("keeps ordinary Luleburgaz tweets that use the word bayan", () => {
    const item = tweet(
      "yerelhaber",
      "Yerel Haber",
      "Lüleburgaz'da kayıp bayan için arama çalışması başlatıldı",
    );

    expect(shouldDropTweet(evaluateTweetFilter(config, "Lüleburgaz", item))).toBe(false);
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
      expect(reasons).toContain("block_pattern:generated_location_link_campaign");
      expect(shouldDropTweet(reasons)).toBe(true);
    }
  });

  it("blocks explicitly confirmed spam handles case-insensitively", () => {
    const item = tweet(
      "BeatrizBoo28653",
      "Beatriz Booth",
      "havsa kapıkule #edirne #kırklareli anlamsız kelimeler",
    );
    const reasons = evaluateTweetFilter(config, "Kırklareli", item);

    expect(reasons).toContain("blocked_handle:beatrizboo28653");
    expect(shouldDropTweet(reasons)).toBe(true);
  });

  it("drops generated name handles only with the full short campaign pattern", () => {
    const samples = [
      tweet("GuzinKarad9jh", "Guzin Karadeniz", "haberi 😏 #kırklareli tekmil"),
      tweet("MariaBurnsv9yj", "Maria Burns", "☹ gömüverme asitölçer #kırklareli"),
      tweet("EdwardHalldv", "Edward Hall", "🤨 gravürcülük #kırklareli oyunluk"),
      tweet("SophiaFreeyne", "Sophia Freeman", "#kırklareli 🙋 avuçlatmak ha"),
      tweet("HulyaAksu69dv", "Hulya Aksu", "sertleşebilme 🤨 cüruf #kırklareli"),
      tweet("JaniceGranok", "Janice Grant", "indinde ☹ lüleburgaz"),
    ];
    for (const item of samples) {
      const reasons = evaluateTweetFilter(
        { ...config, blockedTweetHandles: [] },
        "Kırklareli",
        item,
      );
      expect(reasons).toContain("block_pattern:generated_name_location_link_campaign");
      expect(shouldDropTweet(reasons)).toBe(true);
    }
  });

  it("keeps normal name handles and natural location posts", () => {
    const numericHandle = tweet(
      "AhmetYilmaz1987",
      "Ahmet Yilmaz",
      "🙂 #kırklareli deprem oldu",
    );
    const naturalPost = tweet(
      "AyseDemirxq",
      "Ayse Demir",
      "🙂 #kırklareli belediyenin konser programı bu akşam meydanda başlayacak",
    );
    const testConfig = { ...config, blockedTweetHandles: [] };

    expect(shouldDropTweet(evaluateTweetFilter(testConfig, "Kırklareli", numericHandle))).toBe(false);
    expect(shouldDropTweet(evaluateTweetFilter(testConfig, "Kırklareli", naturalPost))).toBe(false);
  });

  it("drops the repeated Trakya location word campaign", () => {
    const samples = [
      tweet(
        "MauriceHer18287",
        "Maurice Hernandez",
        "havsa kapıkule cep görgülüce 💖 #kırklareli faresi #edirne izolatör",
      ),
      tweet(
        "lula_chloe27018",
        "Lula Chloe",
        "#kırklareli #edirne havsa 🎀 kapıkule rastgele kelimeler",
      ),
      tweet(
        "PhilippJacpjrf",
        "Philipp Jacob",
        "kapıkule havsa #edirne anlamsız ❤️ #kırklareli sözcükler",
      ),
    ];
    for (const item of samples) {
      const reasons = evaluateTweetFilter(
        { ...config, blockedTweetHandles: [] },
        "Kırklareli",
        item,
      );
      expect(reasons).toContain("block_pattern:trakya_location_word_campaign");
      expect(shouldDropTweet(reasons)).toBe(true);
    }
  });

  it("keeps a natural regional news post without a generated profile", () => {
    const item = tweet(
      "TrakyaHaber",
      "Trakya Haber",
      "Kırklareli, Edirne, Havsa ve Kapıkule güzergahında yoğunluk yaşanıyor 🚗",
    );

    expect(shouldDropTweet(evaluateTweetFilter(config, "Kırklareli", item))).toBe(false);
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
