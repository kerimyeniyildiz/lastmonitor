# lastmonitor

Kırklareli odaklı açık kaynak takip botu. Servis, belirlenen X/Twitter aramalarını ve haber sitemap kaynaklarını periyodik olarak kontrol eder. Yeni gördüğü tweet ve haber linklerini Telegram'a bildirir. İsteğe bağlı olarak verileri Postgres'e kaydeder ve FastAPI üzerinden okunabilir hale getirir.

## Bileşenler

- `main.py`: Ana worker. Tweet araması, sitemap haber taraması, Telegram bildirimi, tekrar kontrolü, R2/S3 durum saklama ve Postgres kayıtlarını yönetir.
- `api.py`: Postgres'te tutulan tweet, haber ve istatistik kayıtlarını dönen FastAPI uygulaması.
- `Dockerfile.worker`: Worker servisini çalıştırır.
- `Dockerfile.api`: API servisini çalıştırır.

Dashboard bu aşamada kaldırıldı. Arayüz daha sonra ihtiyaçlara göre sıfırdan hazırlanacak.

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
```

`drop` modunda güvenli görülen spamler Telegram'a gönderilmez. Şu an `BLOCKED_TWEET_TERMS` eşleşmeleri ve sadece lokasyon hashtag'i + link içeren paylaşımlar düşürülür. `WATCH_TWEET_TERMS` ve telefon numarası gibi diğer sinyaller logda kalır; yanlış pozitif riskini ölçmeden bunlara göre susturma yapılmaz. Geçici gözlem için `TWEET_FILTER_MODE=log`, tamamen kapatmak için `TWEET_FILTER_MODE=off` kullanılabilir. `from:` sorguları varsayılan olarak filtreyi bypass eder; resmi/kurumsal kaynaklarda kritik kelime geçse bile bildirim kaçırmamak için bu bilinçli bir tercihtir.

Haber kaynakları varsayılan olarak iki sitemap kullanır:

```env
SITEMAP_URLS=https://www.onadimgazetesi.com/sitemap.xml
SITEMAP_MONTHLY_TEMPLATES=https://www.alternatifgazetesi.com/sitemap/sitemap-{YYYY}-{MM}.xml
SITEMAP_MONTH_LOOKBACK=1
```

`SITEMAP_MONTHLY_TEMPLATES` içindeki `{YYYY}` ve `{MM}` alanları otomatik doldurulur. `SITEMAP_MONTH_LOOKBACK=1` ay başlarında önceki ayın sitemap'ini de kontrol eder. Eski uzaktan liste dosyası akışı gerekiyorsa `SITEMAP_LIST_URL` tanımlanabilir; doğrudan sitemap ayarları varsa öncelik onlardadır.

Instagram takibi isteğe bağlıdır ve `instagrapi` ile ayrı bir Instagram oturumu kullanır. İlk çalıştırmada mevcut içerikler varsayılan olarak sadece işaretlenir, Telegram'a gönderilmez; bundan sonraki yeni story/gönderi/reels içerikleri bildirilir.

```env
INSTAGRAM_ENABLE=true
INSTAGRAM_USERNAME=
INSTAGRAM_PASSWORD=
INSTAGRAM_TARGETS=rozmedyahaber|30m,kirklareli_gundem|30m
INSTAGRAM_INTERVAL=30m
INSTAGRAM_JITTER=5m
INSTAGRAM_LIMIT=5
INSTAGRAM_SESSION_FILE=instagram_session.json
INSTAGRAM_SENT_FILE=sent_instagram.txt
INSTAGRAM_SEND_EXISTING=false
```

Instagram döngüsü her hedef için story, gönderi ve reels verisini tarihe göre sıralar. Telegram medya URL'yi doğrudan alamazsa dosyayı indirip yüklemeyi dener; video çok büyükse kapak görseli ve link gönderir. Instagram challenge, iki aşamalı doğrulama veya bekleme hatası isterse döngü kendini durdurur ve Telegram'a müdahale gerektiğini bildirir.

## API çalıştırma

API'nin veri dönebilmesi için `DB_URL` tanımlı olmalıdır.

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

Endpointler:

- `GET /health`
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
