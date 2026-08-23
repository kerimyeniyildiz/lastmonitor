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

`drop` modunda yüksek güvenli spamler Telegram'a gönderilmez ve D1'de `filtered` olarak saklanır. `BLOCKED_TWEET_TERMS` eşleşmeleri; üretilmiş hesapların kısa konum kampanyaları, yoğun Trakya reklam listeleri ve konumlu yetişkin ilanlarında birden fazla sinyalin beraber bulunduğu kalıplar düşürülür. `WATCH_TWEET_TERMS` ve telefon numarası gibi zayıf sinyaller tek başına engelleme yapmaz. Geçici gözlem için `TWEET_FILTER_MODE=log`, tamamen kapatmak için `TWEET_FILTER_MODE=off` kullanılabilir. `from:` sorguları varsayılan olarak filtreyi bypass eder; resmi/kurumsal kaynaklarda kritik kelime geçse bile bildirim kaçırmamak için bu bilinçli bir tercihtir.

Kesin spam olduğu doğrulanan hesaplar `BLOCKED_TWEET_HANDLES` ile kullanıcı adı bazında
engellenebilir. Ayrıca ad-soyadla eşleşen fakat sonu rastgele harf/rakamlarla bozulan
hesaplar; yalnızca kısa anlamsız metin, konum etiketi, emoji ve medya bağlantısı sinyallerinin
tamamı birlikteyse otomatik kampanya olarak düşürülür.
Kırklareli, Edirne, Havsa ve Kapıkule adlarını birlikte kullanan eski kampanya da ancak
üretilmiş profil, bağlantı ve emoji sinyalleri beraber olduğunda engellenir.

`TWEET_REQUIRED_PREFIXES`, `sorgu=>zorunlu başlangıç` biçimindedir. Bu kural genel spam filtresinden bağımsızdır; örneğin `from:bpthaber` için yalnızca `SON DAKİKA` ile başlayan tweetler teslim edilir.

Filtre nedenlerinde `blocked_term:*` ve `block_pattern:*` Telegram'a gönderilmeyen kesin kararları, `watch_term:*` ve `watch_pattern:phone_number` ise yalnızca ölçülen sinyalleri ifade eder.

Lüleburgaz sorgusunda gözlenen otomatik reklam kampanyası ayrıca birleşik sinyallerle süzülür. Uzun rakam dizili kullanıcı adı, konum, medya bağlantısı, tek kelimelik görünen ad ve kısa artık metin birlikteyse kısa kalıp düşürülür. `BİLGİ-PROFİLDE`, `İLETİŞİM-PROFİLDE` ve kısaltılmış yazımları gibi reklam profil adları URL bulunmasa da yoğun konum listesiyle beraber değerlendirilir. Yetişkin ilanlarında ise yalnızca yetişkin içerik sinyali ile `var mı`, `yazın`, `arıyorum`, `beklerim` gibi doğrudan çağrıların birleşimi engellenir; `aktif` gibi gündelik kullanımı olan sözcükler tek başına yeterli değildir.

Haber kaynakları varsayılan olarak iki sitemap kullanır:

```env
SITEMAP_URLS=https://www.onadimgazetesi.com/sitemap.xml
SITEMAP_MONTHLY_TEMPLATES=https://www.alternatifgazetesi.com/sitemap/sitemap-{YYYY}-{MM}.xml
SITEMAP_MONTH_LOOKBACK=1
```

`SITEMAP_MONTHLY_TEMPLATES` içindeki `{YYYY}` ve `{MM}` alanları otomatik doldurulur. `SITEMAP_MONTH_LOOKBACK=1` ay başlarında önceki ayın sitemap'ini de kontrol eder. Eski uzaktan liste dosyası akışı gerekiyorsa `SITEMAP_LIST_URL` tanımlanabilir; doğrudan sitemap ayarları varsa öncelik onlardadır.

## Cloudflare Instagram İzleyicisi

Üretimdeki Instagram izleyicisi Cloudflare Cron içinde çalışır ve FlashAPI üzerinden
yalnızca herkese açık hesapları kontrol eder. Varsayılan hedefler `rozmedyahaber` ile
`kirklareli_gundem`; gönderiler ve story'ler hedef başına 30 dakikada bir taranır.
Takip için Instagram kullanıcı adı, şifresi, session veya yerel bilgisayar gerekmez.

İzleyici `2026-08-24 08:00 Europe/Istanbul` başlangıcından itibaren 48 saatlik döngünün
ilk 18 saatinde çalışır. Böylece 24 Ağustos 08:00-25 Ağustos 02:00 çalışma penceresinden
sonra 30 saat bekler ve 26 Ağustos 08:00'de yeniden başlar. İlk başarılı kontrolde bulunan
mevcut içerikler `seeded` olarak D1'e kaydedilir ve Telegram'a topluca gönderilmez. Hesap
ve akış türü başına son içerik zamanı da saklanır; API'nin daha sonraki bir yanıtta gösterdiği
eski içerikler yeni sanılmaz. Sonraki kontrollerde yalnızca gerçekten daha yeni içerikler
ortak Instagram teslimat hattından Telegram'a ve dashboard canlı akışına eklenir.

```env
INSTAGRAM_FLASH_ENABLED=true
INSTAGRAM_FLASH_TARGET_SCHEDULE=rozmedyahaber|30m,kirklareli_gundem|30m,kirklareli_bugun|60m
INSTAGRAM_FLASH_TARGETS=rozmedyahaber,kirklareli_gundem
INSTAGRAM_FLASH_INTERVAL_SECONDS=1800
INSTAGRAM_SHIFT_ANCHOR=2026-08-24T08:00:00+03:00
INSTAGRAM_SHIFT_WORK_HOURS=18
INSTAGRAM_SHIFT_CYCLE_HOURS=48
```

`INSTAGRAM_FLASH_TARGET_SCHEDULE` tanımlandığında hesap başına aralıkları kullanır ve
eski `INSTAGRAM_FLASH_TARGETS` / `INSTAGRAM_FLASH_INTERVAL_SECONDS` ayarlarının önüne
geçer. En kısa aralık 10 dakikadır.

FlashAPI aynı RapidAPI hesabındaki `RAPIDAPI_KEY` secret'ını kullanır. Kullanıcı kimlikleri
D1'de önbelleğe alındıktan sonra her hedef ve kontrol için bir gönderi, bir story isteği
yapılır. Görseller indirilmez veya R2'ye kopyalanmaz; Instagram CDN önizleme bağlantıları
doğrudan kullanıldığı için süresi dolan eski dashboard görselleri artık açılmayabilir.

Bildirim medya kuralları:

- Normal gönderi: görsel, açıklama ve bağlantı
- Carousel: yalnızca ilk görsel, açıklama ve bağlantı
- Reels: yalnızca kapak görseli, açıklama ve bağlantı
- Fotoğraf veya video story: yalnızca kapak/önizleme ve bağlantı

## Eski Yerel Instagram Worker

`instagram_worker/` dizini önceki `instagrapi` tabanlı Mac uygulamasını korur ancak
üretimde kullanılmaz ve otomatik başlamaz. Aşağıdaki bilgiler yalnızca yedek yöntemin
yeniden denenmesi gerekirse geçerlidir. Yerel worker normalize ettiği içerikleri
kimlik doğrulamalı Cloudflare ingest endpointine gönderir; ortak teslimat hattı D1,
Telegram ve dashboard işlemlerini yapar.

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

Worker otomatik başlamaz ve hata sonrasında kendiliğinden yeniden açılmaz. Çalışma
durumunu görmek, başlatmak, durdurmak ve logu izlemek için:

```bash
.venv-instagram/bin/python -m instagram_worker status
.venv-instagram/bin/python -m instagram_worker start
.venv-instagram/bin/python -m instagram_worker stop
tail -f ~/.local/share/lastmonitor-instagram/worker.log
```

Uzun bir kesintiden sonra güncel story ve gönderileri Telegram'a topluca yollamadan
başlangıç noktası yapmak için worker kapalıyken aşağıdaki komut kullanılabilir. Bu işlem
mevcut kayıtları silmez; yalnız daha önce görülmemiş güncel snapshot'ı `seeded` olarak
kaydeder:

```bash
.venv-instagram/bin/python -m instagram_worker seed-current
```

Worker aynı süreç içinde tek Instagram istemcisi kullanır. Yeniden başlatıldığında
`session.json` içindeki cihaz kimliği, çerezler ve oturum ayarları yüklenir; oturum geçerli
olduğu sürece yeni parola girişi yapılmaz. `state.db` görülen içerik kimliklerini ve hedef
başlangıçlarını korur. `IG_SEND_EXISTING=false` olduğu için yeni eklenen hedefin ilk
taraması sessizce başlangıç noktası oluşturur; normal yeniden başlatmalarda daha önce
görülen içerikler yeniden gönderilmez.

Yüklenen session, worker başlarken Instagram özel API'sindeki hesap bilgisiyle doğrulanır.
Session geçersizse arka plan worker'ı kendiliğinden tekrar giriş denemez ve durur. Resmi
Instagram uygulaması veya web sitesindeki olası güvenlik uyarısı tamamlandıktan sonra
`login` komutu bir defalık temiz giriş yapar; ardından worker ayrıca `start` komutuyla
başlatılır. Challenge, `login_required` ve benzeri hatalar başka bir exception içinde
maskelense bile aynı güvenli durdurma davranışı uygulanır.

İki hedef de her başarılı kontrolden sonra bağımsız olarak 15–50 dakika arasında
rastgele bir sonraki kontrol zamanı seçer. Bu aralık ortalama istek sayısını sabit yarım
saatlik düzene yakın tutarken kontrollerin düzenli aralıklarla tekrarlanmasını önler.

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
