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

## API çalıştırma

API'nin veri dönebilmesi için `DB_URL` tanımlı olmalıdır.

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

Endpointler:

- `GET /health`
- `GET /tweets`
- `GET /news`
- `GET /stats/daily`
- `GET /stats/top-queries`

Veri endpointleri varsayılan olarak token ister. `API_TOKEN` tanımlayın ve isteklerde `Authorization: Bearer <token>` başlığı gönderin. Sadece kapalı geliştirme ortamında korumayı kapatmak için `API_REQUIRE_TOKEN=false` kullanın.

## Runtime dosyaları

Worker aynı linkleri tekrar göndermemek için yerelde şu dosyaları oluşturabilir:

- `sent_urls.txt`
- `sent_news.txt`
- `sitemap.txt`

Bu dosyalar çalışma zamanı verisidir ve git'e eklenmez.

## Kontrol

```bash
python -m py_compile api.py main.py
python -m unittest discover -s tests -v
```
