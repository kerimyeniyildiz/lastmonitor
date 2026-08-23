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
    profileImageUrl: null,
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

  it("drops the observed synthetic-profile Luleburgaz campaign", () => {
    const samples = [
      tweet(
        "boya_amrutha_33",
        "🖤",
        "#edirNe kalem 💗 siyah #lüleburgAz",
      ),
      tweet(
        "BharajBalbeer",
        "🌸",
        "oturuş 💌 #lüleburgAz sandalye #edirNe",
      ),
      tweet(
        "MarioManhazr",
        "Mario Manha",
        "❤️‍🩹 Buz lüleburgaz #edirne kırkalerli gibi soğuk",
      ),
      tweet(
        "sksivakumarcv",
        "Sivakumar C V",
        "BELLETMEN İP #çorlu ☹ İSKELESİ YIRTTIRMAK lüleburgaz",
      ),
    ];

    for (const item of samples) {
      const reasons = evaluateTweetFilter(config, "Lüleburgaz", item);
      expect(reasons).toContain("block_pattern:luleburgaz_synthetic_profile_campaign");
      expect(shouldDropTweet(reasons)).toBe(true);
    }
  });

  it("drops concatenated ad hashtags and explicit Luleburgaz ad profiles", () => {
    const concatenated = tweet(
      "Verkhatii",
      "IRMAK",
      "Ballı Ballı. #lüleburgaztrAvesti",
    );
    const explicitProfiles = [
      tweet(
        "KrklareTekBayan",
        "Kırklareli Tek Bayan Asel",
        "Lüleburgaz güvenilir ciddi düşünen Tek var mı.",
      ),
      tweet(
        "KirklrelZeynep_",
        "Kırklareli Dul Bayan Zeynep",
        "Lüleburgaz Bu ne kııızzz",
      ),
    ];

    const concatenatedReasons = evaluateTweetFilter(config, "Lüleburgaz", concatenated);
    expect(concatenatedReasons).toContain(
      "block_pattern:luleburgaz_concatenated_ad_hashtag",
    );
    expect(shouldDropTweet(concatenatedReasons)).toBe(true);

    for (const item of explicitProfiles) {
      const reasons = evaluateTweetFilter(config, "Lüleburgaz", item);
      expect(reasons).toContain("block_pattern:luleburgaz_ad_profile");
      expect(shouldDropTweet(reasons)).toBe(true);
    }

    const profileOnlyAd = tweet(
      "DelbertNgum4fg",
      "BİLGİ-PROFİLDE-👈RÜYA",
      "Gerçekler acıtır ama öğretir. çorlu,çerkezköy,lüleburgaz,bayan,",
    );
    profileOnlyAd.text = profileOnlyAd.text.replace(" https://t.co/example", "");
    const profileOnlyReasons = evaluateTweetFilter(config, "Lüleburgaz", profileOnlyAd);
    expect(profileOnlyReasons).toContain("block_pattern:luleburgaz_ad_profile");
    expect(shouldDropTweet(profileOnlyReasons)).toBe(true);
  });

  it("drops repeated normalized locations hidden in generated text", () => {
    const samples = [
      tweet(
        "John82133296370",
        "John",
        "☹ öfkelenmişti. Bütün süper kahramanlar tekirdağ tekirdag lüleburgaz sehpasıydı. Demirden.",
      ),
      tweet(
        "John82133296370",
        "John",
        "Üç, tekirdağ tekirdag lüleburgaz ☹ ulusal kanallarda cihazını kapattı, ardından",
      ),
    ];

    for (const item of samples) {
      const reasons = evaluateTweetFilter(config, "Lüleburgaz", item);
      expect(reasons).toContain("block_pattern:luleburgaz_repeated_location_campaign");
      expect(shouldDropTweet(reasons)).toBe(true);
    }
  });

  it("drops explicit solicitation only when paired with several locations", () => {
    const solicitation = tweet(
      "muratk687288",
      "Efsane",
      "@kırklareli @lüleburgaz @babaeski @edirne dil masajı yaptırmak isteyen varmi sevişmek istiyorum",
    );
    solicitation.text = solicitation.text.replace(" https://t.co/example", "");

    const reasons = evaluateTweetFilter(config, "Kırklareli", solicitation);
    expect(reasons).toContain("block_pattern:multi_location_explicit_solicitation");
    expect(shouldDropTweet(reasons)).toBe(true);

    const quotedNews = tweet(
      "yerelhaber",
      "Yerel Haber",
      "Kırklareli'de duvara 'sevişmek istiyorum' yazan kişi hakkında işlem başlatıldı",
    );
    expect(shouldDropTweet(evaluateTweetFilter(config, "Kırklareli", quotedNews))).toBe(false);
  });

  it("drops linkless dense location ads with abbreviated contact profiles", () => {
    const samples = [
      tweet(
        "SamObrienluwd",
        "İLTŞM-PROFİLDE-👈RÜYA",
        "Karanlık ışığın değerini. çorlu,çerkezköy,bayan,kapaklı,malkara,tekirdağ,lüleburgaz,muratlı,hayrabolu,şarkköy,ergene,saray,marmaraereğlisi,",
      ),
      tweet(
        "ThelmaWhipavyq",
        "İLTİŞİM PROFİLDE SİBEL",
        "Hayat küçük anlarda gizlidir. çorlu,çerkezköy,kapaklı,malkara,tekirdağ,lüleburgaz,bayan,",
      ),
    ];

    for (const item of samples) {
      item.text = item.text.replace(" https://t.co/example", "");
      const reasons = evaluateTweetFilter(config, "Lüleburgaz", item);
      expect(reasons).toContain("block_pattern:trakya_location_dump_ad_campaign");
      expect(reasons).toContain("block_pattern:luleburgaz_ad_profile");
      expect(shouldDropTweet(reasons)).toBe(true);
    }
  });

  it("drops the expanded generated-name word-salad campaign", () => {
    const samples: Array<[string, Tweet]> = [
      ["Kırklareli", tweet(
        "Alexandriaqm5j",
        "Alexandria Fleming",
        "tuz ekmek hakkı 💐 keyfetme #kırklareli nite",
      )],
      ["Kırklareli", tweet(
        "LillianAndqww7",
        "Lillian Andrews",
        "lambası ikaz #kırklareli ☹ hırslanış başmakçı",
      )],
      ["Kırklareli", tweet(
        "Earnestinewfov",
        "Earnestine Dubray",
        "kravatlıca #kırklareli 🤨 nedeniyle soyluluk",
      )],
      ["Lüleburgaz", tweet(
        "SherylWeavt71z",
        "Sheryl Weaver",
        "yağ lüleburgaz yüreği tahripkâr ☹ katı çorlu ana",
      )],
    ];

    for (const [query, item] of samples) {
      const reasons = evaluateTweetFilter(config, query, item);
      expect(reasons, item.userHandle).toContain(
        "block_pattern:generated_name_location_link_campaign",
      );
      expect(shouldDropTweet(reasons)).toBe(true);
    }
  });

  it("drops location-based adult solicitations but keeps ordinary uses of active", () => {
    const solicitations = [
      tweet(
        "soekdprlfp",
        "j",
        "lüleburgaz aktifler hemen yazsın, genç pasifim #gay #aktif #pasif #seks #sakso",
      ),
      tweet(
        "HakanGonzales",
        "Mario Gonzales",
        "Lüleburgaz'da yeri olan aktif var mı? 30 yaşında pasifim #aktif #pasif",
      ),
      tweet("Vajinalorg60030", "vajinal orgazm yaşatırım", "#lüleburgaz uyumuş"),
    ];
    for (const item of solicitations) {
      const reasons = evaluateTweetFilter(config, "Lüleburgaz", item);
      expect(reasons).toContain("block_pattern:location_personal_solicitation");
      expect(shouldDropTweet(reasons)).toBe(true);
    }

    const announcement = tweet(
      "AnahtarParti39",
      "Anahtar Parti Kırklareli",
      "Kırklareli'nde en aktif il başkanı araştırmasının sonuçları açıklandı",
    );
    expect(shouldDropTweet(evaluateTweetFilter(config, "Kırklareli", announcement))).toBe(false);
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

  it("drops dense Trakya location ads regardless of the search query", () => {
    const samples = [
      tweet(
        "naik_ravinaik",
        "ÜNİVERSİTELİ KIZLAR",
        "Sevgi varsa yol bulunur 🛤️📷 edirne,kırklareli,kapaklı,tekirdağ,lüleburgaz,şarkköy,malkara,hayrabolu,saray,ergene,muratlı,marmaraereğlisi,bayan,",
      ),
      tweet(
        "Omer57205569",
        "ÇITIR KIZLAR",
        "Hayat sevdikçe güzel dostum💗kapaklı,saray,kırklareli,lüleburgaz, çorlu,çerkezköy,tekirdağ,bayan,",
      ),
      tweet(
        "NataliaHoprqak",
        "Suzan",
        "Huzur, en büyük servettir ☯️ çorlu,çerkezköy,lüleburgaz,bayan,",
      ),
    ];

    for (const item of samples) {
      const reasons = evaluateTweetFilter(
        { ...config, blockedTweetHandles: [] },
        "Kırklareli",
        item,
      );

      expect(reasons).toContain("block_pattern:trakya_location_dump_ad_campaign");
      expect(shouldDropTweet(reasons)).toBe(true);
    }
  });

  it("keeps natural multi-location regional reports", () => {
    const item = tweet(
      "TrakyaHaber",
      "Trakya Haber",
      "Edirne, Kırklareli, Kapaklı, Tekirdağ, Lüleburgaz, Şarkköy, Malkara ve Saray hattında kuvvetli yağış bekleniyor 🌧️",
    );

    expect(shouldDropTweet(evaluateTweetFilter(config, "Kırklareli", item))).toBe(false);
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
      tweet(
        "TrakyaHaber",
        "Trakya Haber",
        "#Edirne Lüleburgaz yolunda kaza meydana geldi 🚨",
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

  it("drops the synthetic single-name location word-salad campaign", () => {
    const samples = [
      tweet("wgvut", "علي المجيدي", "yarım #kırklareli 🐢 seren hışım mahşerleşmek"),
      tweet("qb6del", "فؤاد ناصر أحمد الخلقي", "☹ mediyasten #kırklareli mut Balkar"),
      tweet("HUDAwtva", "HUDA", "defnolunma doldurtabilme #kırklareli buyrukluk 🤬 başına"),
      tweet("Aaa9bf", "Aa", "ballanma #kırklareli önemseyiş ☹ fıskiye"),
      tweet("taahrzdeh", "taahr", "tanker pitsikato destursuz 🍉 #kırklareli"),
      tweet("ABDALLH27zy", "ABDALLH", "öfkeli muta 💖 #kırklareli çöğünme"),
      tweet("Amjad1th9", "Amjad", "türap menopoz 🐆 #kırklareli işçilik"),
      tweet("A7slce", "A", "#kırklareli çatallanma 🌾 onkolojik ensest"),
      tweet("xzgszm", "العباد", "rubaimsi 🕊 hidrobiyolojik #kırklareli etimoloji"),
    ];

    for (const item of samples) {
      const reasons = evaluateTweetFilter(
        { ...config, blockedTweetHandles: [] },
        "Kırklareli",
        item,
      );
      expect(reasons, item.userHandle).toContain("block_pattern:synthetic_location_word_salad");
      expect(shouldDropTweet(reasons)).toBe(true);
    }
  });

  it("keeps coherent short posts from generated-looking profiles", () => {
    const samples = [
      tweet("Selin123", "Selin", "Bugün #kırklareli hava çok güzel 🥰"),
      tweet("wgvut", "علي المجيدي", "Bugün #kırklareli hava çok güzel 🥰"),
      tweet("Aaa9bf", "Aa", "Bu akşam #kırklareli konseri var 🎶"),
    ];

    for (const item of samples) {
      const reasons = evaluateTweetFilter(
        { ...config, blockedTweetHandles: [] },
        "Kırklareli",
        item,
      );
      expect(reasons).not.toContain("block_pattern:synthetic_location_word_salad");
      expect(shouldDropTweet(reasons)).toBe(false);
    }
  });

  it("drops explicit location solicitations without blocking active-life posts", () => {
    const solicitation = tweet(
      "kedy543716",
      "cen",
      "Lüleburgaz aktifler yazsın azgınım büyük sikli yok mu yalayabileceğim 😏😋 #lüleburgaz #kırklareli #çorlu",
    );
    solicitation.text = solicitation.text.replace(/ https:\/\/t\.co\/example$/, "");
    const activeLife = tweet(
      "KirklareliSpor",
      "Kırklareli Spor",
      "Kırklareli'de aktif yaşam için spor etkinliği düzenlendi 🏃",
    );

    const solicitationReasons = evaluateTweetFilter(config, "Kırklareli", solicitation);
    expect(solicitationReasons).toContain("block_pattern:location_personal_solicitation");
    expect(shouldDropTweet(solicitationReasons)).toBe(true);
    expect(shouldDropTweet(evaluateTweetFilter(config, "Kırklareli", activeLife))).toBe(false);
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

  it("blocks the latest confirmed spam handles without relying on content", () => {
    const handles = [
      "wgvut",
      "HUDAwtva",
      "Aaa9bf",
      "taahrzdeh",
      "ABDALLH27zy",
      "Amjad1th9",
      "A7slce",
      "xzgszm",
      "kedy543716",
      "qb6del",
      "Zeynep1041817",
      "editorerdemir",
    ];

    for (const handle of handles) {
      const reasons = evaluateTweetFilter(
        config,
        "Kırklareli",
        tweet(handle.toUpperCase(), "Normal görünen ad", "Kırklareli hakkında sıradan metin"),
      );
      expect(reasons, handle).toContain(`blocked_handle:${handle.toLowerCase()}`);
      expect(shouldDropTweet(reasons)).toBe(true);
    }
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
