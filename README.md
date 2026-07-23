# lastmonitor

Kırklareli odaklı açık kaynak takip botu. Servis, belirlenen X/Twitter aramalarını ve haber sitemap kaynaklarını periyodik olarak kontrol eder. Yeni gördüğü tweet ve haber linklerini Telegram'a bildirir. İsteğe bağlı olarak verileri Postgres'e kaydeder ve FastAPI üzerinden okunabilir hale getirir.

## Bileşenler

- `main.py`: Ana worker. Tweet araması, sitemap haber taraması, Telegram bildirimi, tekrar kontrolü, R2/S3 durum saklama ve Postgres kayıtlarını yönetir.
- `api.py`: Postgres'te tutulan tweet, haber ve istatistik kayıtlarını dönen FastAPI uygulaması.
- `Dockerfile.worker`: Worker servisini çalıştırır.
- `Dockerfile.api`: API servisini çalıştırır.

Cloudflare sürümü canlı akış ve istatistik dashboard'ını da sunar:
https://onleme.kerimyeniyildiz.com.tr

## Cloudflare sürümü

`cloudflare/` dizini mevcut Dokploy servisinden bağımsız çalışan Workers + Cron + D1
sürümünü içerir. Canlı ortam `DELIVERY_MODE=live` ile Telegram teslimatı yapar;
D1'daki benzersiz bağlantılar daha önce gözlenen içeriklerin yeniden gönderilmesini
engeller. Dashboard statik dosyaları aynı Worker üzerinden sunulur.

```bash
cd cloudflare
npm install
npm test
npm run check
npx wrangler d1 migrations apply lastmonitor-shadow --remote
npm run deploy
```

Dashboard geliştirme sunucusu `npm run dev`, Worker geliştirme sunucusu ise
`npm run worker:dev` ile başlatılır. Üretim dağıtımı Vite arayüzünü derler ve Worker,
cron, D1 API'leri ile statik dosyaları birlikte yayınlar.

`RAPIDAPI_KEY`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` ve `API_TOKEN` değerleri
repoya yazılmaz; `wrangler secret put` ile Cloudflare Secrets içinde tutulur.

## Kurulum

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` içindeki değerleri gerçek anahtarlar ve servis bilgileriyle doldurun. Gizli değerleri repoya eklemeyin.

## Worker çalıştırma

```bash
python main.py
```

Gerekli minimum ortam değişkenleri:

```env
API_KEY=
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=
```

Birden fazla sorguyu farklı aralıklarla takip etmek için:

```env
QUERY_SCHEDULE=Kırklareli|5m,Lüleburgaz|10m,Babaeski|15m
```

Genel tweet sorgularında bariz gürültüleri önce loglamak için:

```env
TWEET_FILTER_MODE=drop
BLOCKED_TWEET_TERMS=escort,kırklarelibayan,kırklarelieskort,kırklareliesc
WATCH_TWEET_TERMS=ücret elden,ucret elden,ödeme elden,odeme elden,ev otel,apart rezidans,otel rezidans
LOCATION_HASHTAG_TERMS=kırklareli,kirklareli,lüleburgaz,luleburgaz,babaeski,pınarhisar,pinarhisar,kofçaz,kofcaz,demirköy,demirkoy,pehlivanköy,pehlivankoy,kapaklı,kapakli,tekirdağ,tekirdag,edirne
TWEET_FILTER_BYPASS_QUERIES=from:mustafaciftcitr,Valikirklareli,KirklareliEmn
TWEET_REQUIRED_PREFIXES=from:bpthaber=>SON DAKİKA
```

`drop` modunda güvenli görülen spamler Telegram'a gönderilmez. Şu an `BLOCKED_TWEET_TERMS` eşleşmeleri, sadece lokasyon hashtag'i + link içeren paylaşımlar ve rakam ekli üretilmiş hesapların kısa lokasyon-link kampanyaları düşürülür. `WATCH_TWEET_TERMS` ve telefon numarası gibi diğer sinyaller logda kalır; yanlış pozitif riskini ölçmeden bunlara göre susturma yapılmaz. Geçici gözlem için `TWEET_FILTER_MODE=log`, tamamen kapatmak için `TWEET_FILTER_MODE=off` kullanılabilir. `from:` sorguları varsayılan olarak filtreyi bypass eder; resmi/kurumsal kaynaklarda kritik kelime geçse bile bildirim kaçırmamak için bu bilinçli bir tercihtir.

`TWEET_REQUIRED_PREFIXES`, `sorgu=>zorunlu başlangıç` biçimindedir. Bu kural genel spam filtresinden bağımsızdır; örneğin `from:bpthaber` için yalnızca `SON DAKİKA` ile başlayan tweetler teslim edilir.

Filtre nedenlerinde `blocked_term:*` ve `block_pattern:*` Telegram'a gönderilmeyen kesin kararları, `watch_term:*` ve `watch_pattern:phone_number` ise yalnızca ölçülen sinyalleri ifade eder.

Lüleburgaz sorgusunda gözlenen otomatik reklam kampanyası ayrıca birleşik sinyallerle süzülür. Yalnızca uzun rakam dizili kullanıcı adı, konum, link, tek kelimelik görünen ad ve en fazla üç artık kelime birlikteyse kısa kalıp düşürülür. Aynı kapsamda reklam ifadeli profil adları ve virgülle oluşturulmuş uzun konum listeleri de engellenir; bu kurallar diğer sorgulara uygulanmaz.

Haber kaynakları varsayılan olarak iki sitemap kullanır:

```env
SITEMAP_URLS=https://www.onadimgazetesi.com/sitemap.xml
SITEMAP_MONTHLY_TEMPLATES=https://www.alternatifgazetesi.com/sitemap/sitemap-{YYYY}-{MM}.xml
SITEMAP_MONTH_LOOKBACK=1
```

`SITEMAP_MONTHLY_TEMPLATES` içindeki `{YYYY}` ve `{MM}` alanları otomatik doldurulur. `SITEMAP_MONTH_LOOKBACK=1` ay başlarında önceki ayın sitemap'ini de kontrol eder. Eski uzaktan liste dosyası akışı gerekiyorsa `SITEMAP_LIST_URL` tanımlanabilir; doğrudan sitemap ayarları varsa öncelik onlardadır.

## Yerel Instagram Worker

Yeni Instagram izleyicisi Cloudflare cron içinde çalışmaz. Instagram oturumu ve Android
cihaz kimliği yalnızca Mac'te tutulur; normalize edilen yeni içerikler kimlik doğrulamalı
Cloudflare ingest endpointine gönderilir. Cloudflare içeriği D1/R2'ye kaydeder, Telegram
bildirimini gönderir ve dashboard akışına ekler.

Bildirim medya kuralları:

- Normal gönderi: görsel, açıklama ve bağlantı
- Carousel: yalnızca ilk görsel, açıklama ve bağlantı
- Reels: yalnızca kapak görseli, açıklama ve bağlantı
- Fotoğraf veya video story: yalnızca kapak/önizleme ve bağlantı

Kurulum:

```bash
/Users/seo/.local/bin/python3.11 -m venv .venv-instagram
.venv-instagram/bin/pip install -r requirements-instagram.txt
.venv-instagram/bin/python -m instagram_worker configure
.venv-instagram/bin/python -m instagram_worker check-config
.venv-instagram/bin/python -m instagram_worker login
.venv-instagram/bin/python -m instagram_worker run-once
.venv-instagram/bin/python -m instagram_worker install-launchd
```

Varsayılan güvenli yapılandırma dosyası
`~/.config/lastmonitor-instagram/config.env`, çalışma verileri ise
`~/.local/share/lastmonitor-instagram` altındadır. Her iki konum da Git dışında kalır.
Instagram şifresi ve Cloudflare ingest anahtarı macOS Keychain'de saklanır; yapılandırma
dosyasına yazılmaz.
`launchd` servisi Mac prize bağlıyken sistem uykusunu engeller; ekranın uyumasına izin
verir.

## API çalıştırma

API'nin veri dönebilmesi için `DB_URL` tanımlı olmalıdır.

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

Endpointler:

- `GET /health`
- `GET /api/dashboard/feed` (public, cursor tabanlı canlı akış)
- `GET /api/dashboard/stats` (public dashboard istatistikleri)
- `GET /tweets` (varsayılan `status=sent`; ayrıca `status=filtered` ve `status=all`)
- `GET /news`
- `GET /stats/daily`
- `GET /stats/top-queries`

Veri endpointleri varsayılan olarak token ister. `API_TOKEN` tanımlayın ve isteklerde `Authorization: Bearer <token>` başlığı gönderin. Sadece kapalı geliştirme ortamında korumayı kapatmak için `API_REQUIRE_TOKEN=false` kullanın.

Worker geçici bir PostgreSQL bağlantı hatasında kayıtları bellekte sıraya alır ve bağlantıyı düzenli olarak yeniden dener. Tweet kayıtlarında `delivery_status` alanı Telegram'a gönderilenler için `sent`, spam filtresinin düşürdükleri için `filtered` değerini taşır; eşleşen sinyaller `filter_reasons` alanında saklanır. Gerekli tablo alanları mevcut veritabanına otomatik eklenir.

## Runtime dosyaları

Worker aynı linkleri tekrar göndermemek için yerelde şu dosyaları oluşturabilir:

- `sent_urls.txt`
- `sent_news.txt`
- `sent_instagram.txt`
- `instagram_session.json`
- `sitemap.txt`

Bu dosyalar çalışma zamanı verisidir ve git'e eklenmez.

## Kontrol

```bash
python -m py_compile api.py main.py
python -m unittest discover -s tests -v
```
