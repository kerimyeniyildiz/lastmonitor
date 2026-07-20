import os
import re
import threading
import time
import json
import random
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import psycopg2

try:
    from instagrapi import Client as InstagramClient
    from instagrapi.exceptions import (
        ChallengeRequired,
        ClientError as InstagramClientError,
        LoginRequired,
        PleaseWaitFewMinutes,
        TwoFactorRequired,
    )
except ImportError:  # pragma: no cover - optional dependency when Instagram is disabled.
    InstagramClient = None
    ChallengeRequired = InstagramClientError = LoginRequired = PleaseWaitFewMinutes = None
    TwoFactorRequired = None


IMAGE_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".avif",
    ".bmp",
    ".tiff",
    ".ico",
)

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
DEFAULT_SITEMAP_URLS = ("https://www.onadimgazetesi.com/sitemap.xml",)
DEFAULT_SITEMAP_MONTHLY_TEMPLATES = (
    "https://www.alternatifgazetesi.com/sitemap/sitemap-{YYYY}-{MM}.xml",
)
DEFAULT_BLOCKED_TWEET_TERMS = (
    "escort",
    "kırklarelibayan",
    "kırklarelieskort",
    "kırklareliesc",
)
DEFAULT_TWEET_FILTER_MODE = "drop"
DEFAULT_DROPPABLE_FILTER_REASONS = (
    "block_pattern:location_hashtags_link_only",
    "block_pattern:location_word_soup_link",
    "block_pattern:suspicious_location_link",
    "block_pattern:generated_location_link_campaign",
    "block_pattern:luleburgaz_short_link_campaign",
    "block_pattern:luleburgaz_ad_profile",
    "block_pattern:luleburgaz_location_dump",
)
DEFAULT_WATCH_TWEET_TERMS = (
    "ücret elden",
    "ucret elden",
    "ödeme elden",
    "odeme elden",
    "ev otel",
    "apart rezidans",
    "otel rezidans",
)
DEFAULT_LOCATION_HASHTAG_TERMS = (
    "kırklareli",
    "kirklareli",
    "lüleburgaz",
    "luleburgaz",
    "babaeski",
    "pınarhisar",
    "pinarhisar",
    "kofçaz",
    "kofcaz",
    "demirköy",
    "demirkoy",
    "pehlivanköy",
    "pehlivankoy",
    "kapaklı",
    "kapakli",
    "tekirdağ",
    "tekirdag",
    "edirne",
)
LULEBURGAZ_CAMPAIGN_LOCATION_TERMS = (
    "çorlu",
    "corlu",
    "çerkezköy",
    "cerkezkoy",
    "şarkköy",
    "sarkkoy",
    "malkara",
    "hayrabolu",
    "saray",
    "ergene",
    "muratlı",
    "muratli",
    "marmaraereğlisi",
    "marmaraereglisi",
)
LULEBURGAZ_CAMPAIGN_PROFILE_TERMS = ("bayan", "escort", "eskort")
DEFAULT_TWEET_FILTER_BYPASS_QUERIES = (
    "from:mustafaciftcitr",
    "Valikirklareli",
    "KirklareliEmn",
)


def log(message: str) -> None:
    ts = datetime.now(ISTANBUL_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} | {message}")


def load_env_file(path: str = ".env") -> None:
    """Populate os.environ from a simple KEY=VALUE .env file without extra deps."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                cleaned = line.strip()
                if not cleaned or cleaned.startswith("#") or "=" not in cleaned:
                    continue
                key, value = cleaned.split("=", 1)
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError as exc:
        log(f"env read failed: {path} ({exc})")


def str_to_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def str_to_int(value: Optional[str], default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    normalized = value.replace("\n", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def parse_required_prefixes(value: Optional[str]) -> Dict[str, str]:
    prefixes: Dict[str, str] = {}
    for item in parse_list(value):
        if "=>" not in item:
            continue
        query, prefix = item.split("=>", 1)
        query = query.strip().lower()
        prefix = prefix.strip()
        if query and prefix:
            prefixes[query] = prefix
    return prefixes


def normalize_prefix_match(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return normalized.translate(str.maketrans({"I": "ı", "İ": "i"})).lower()


@dataclass
class QuerySchedule:
    query: str
    interval_seconds: int


@dataclass
class InstagramTarget:
    username: str
    interval_seconds: int


def parse_duration_seconds(text: Optional[str], default: int) -> int:
    """Parse durations like '30m', '5m', '60', '1h' into seconds."""
    if text is None:
        return default
    raw = str(text).strip().lower()
    if not raw:
        return default
    multiplier = 1
    if raw.endswith("h"):
        multiplier = 3600
        raw = raw[:-1]
    elif raw.endswith("m"):
        multiplier = 60
        raw = raw[:-1]
    elif raw.endswith("s"):
        multiplier = 1
        raw = raw[:-1]
    try:
        return max(1, int(raw) * multiplier)
    except ValueError:
        return default


def parse_query_schedule(
    raw: Optional[str], fallback_query: str, fallback_interval: int
) -> List[QuerySchedule]:
    """
    Parse a schedule definition like:
    QUERY_SCHEDULE="Kofcaz|30m,Kirklareli|1m,Babaeski|1800"
    Delimiters: comma between items, '|' or ':' between query and interval.
    """
    if fallback_interval <= 0:
        fallback_interval = 60
    schedule: List[QuerySchedule] = []
    text = (raw or "").strip()
    if text:
        for part in text.split(","):
            item = part.strip()
            if not item:
                continue
            query_text, interval_text = item, str(fallback_interval)
            if "|" in item:
                query_text, interval_text = item.split("|", 1)
            elif ":" in item:
                query_text, interval_text = item.split(":", 1)
            query_clean = query_text.strip()
            if not query_clean:
                continue
            if query_clean.lower() == "from:aliyerlikaya":
                query_clean = "from:mustafaciftcitr"
            interval_seconds = parse_duration_seconds(interval_text, fallback_interval)
            schedule.append(
                QuerySchedule(query=query_clean, interval_seconds=interval_seconds)
            )
    if not schedule and fallback_query:
        schedule.append(
            QuerySchedule(query=fallback_query, interval_seconds=fallback_interval)
        )
    return schedule


def parse_instagram_targets(raw: Optional[str], fallback_interval: int) -> List[InstagramTarget]:
    """
    Parse Instagram target definitions like:
    INSTAGRAM_TARGETS="rozmedyahaber|30m,kirklareli_gundem|45m"
    """
    if fallback_interval <= 0:
        fallback_interval = 1800
    targets: List[InstagramTarget] = []
    text = (raw or "").strip()
    if not text:
        return targets
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        username_text, interval_text = item, str(fallback_interval)
        if "|" in item:
            username_text, interval_text = item.split("|", 1)
        elif ":" in item:
            username_text, interval_text = item.split(":", 1)
        username = username_text.strip().lstrip("@")
        if not username:
            continue
        targets.append(
            InstagramTarget(
                username=username,
                interval_seconds=parse_duration_seconds(interval_text, fallback_interval),
            )
        )
    return targets


@dataclass
class Config:
    api_key: str
    query: str
    query_type: str
    tweet_limit: int
    poll_interval_seconds: int
    telegram_token: str
    telegram_chat_id: str
    sent_urls_file: str
    news_sent_file: str
    instagram_sent_file: str
    news_limit: int
    news_max_age_hours: int
    sitemap_urls: List[str]
    sitemap_monthly_templates: List[str]
    sitemap_month_lookback: int
    sitemap_list_url: str
    sitemap_list_file: str
    sitemap_check_seconds: int
    sitemap_refresh_seconds: int
    http_timeout_seconds: int
    http_max_retries: int
    http_retry_backoff: int
    s3_enable: bool
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_region: str
    s3_bucket: str
    s3_sent_urls_key: str
    s3_sent_news_key: str
    s3_sent_instagram_key: str
    tweet_filter_mode: str
    blocked_tweet_terms: List[str]
    watch_tweet_terms: List[str]
    location_hashtag_terms: List[str]
    tweet_filter_bypass_queries: List[str]
    tweet_required_prefixes: Dict[str, str]
    queries_schedule: List[QuerySchedule]
    db_url: str
    instagram_enable: bool
    instagram_username: str
    instagram_password: str
    instagram_session_file: str
    instagram_targets: List[InstagramTarget]
    instagram_limit: int
    instagram_interval_jitter_seconds: int
    instagram_send_existing: bool

    @classmethod
    def from_env(cls) -> "Config":
        default_query = os.environ.get("QUERY", "Kırklareli")
        default_interval = str_to_int(os.environ.get("POLL_INTERVAL_SECONDS"), 300)
        schedule_raw = os.environ.get("QUERY_SCHEDULE")
        return cls(
            api_key=os.environ.get("API_KEY", ""),
            query=default_query,
            query_type=os.environ.get("QUERY_TYPE", "Latest"),
            tweet_limit=str_to_int(os.environ.get("TWEET_LIMIT"), 20),
            poll_interval_seconds=default_interval,
            telegram_token=os.environ.get("TELEGRAM_TOKEN", ""),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
            sent_urls_file=os.environ.get("SENT_URLS_FILE", "sent_urls.txt"),
            news_sent_file=os.environ.get("NEWS_SENT_FILE", "sent_news.txt"),
            instagram_sent_file=os.environ.get(
                "INSTAGRAM_SENT_FILE", "sent_instagram.txt"
            ),
            news_limit=str_to_int(os.environ.get("NEWS_LIMIT"), 10),
            news_max_age_hours=str_to_int(os.environ.get("NEWS_MAX_AGE_HOURS"), 72),
            sitemap_urls=parse_list(
                os.environ.get("SITEMAP_URLS", ",".join(DEFAULT_SITEMAP_URLS))
            ),
            sitemap_monthly_templates=parse_list(
                os.environ.get(
                    "SITEMAP_MONTHLY_TEMPLATES",
                    ",".join(DEFAULT_SITEMAP_MONTHLY_TEMPLATES),
                )
            ),
            sitemap_month_lookback=max(
                0, str_to_int(os.environ.get("SITEMAP_MONTH_LOOKBACK"), 1)
            ),
            sitemap_list_url=os.environ.get("SITEMAP_LIST_URL", ""),
            sitemap_list_file=os.environ.get("SITEMAP_LIST_FILE", "sitemap.txt"),
            sitemap_check_seconds=str_to_int(
                os.environ.get("SITEMAP_CHECK_SECONDS"), 600
            ),
            sitemap_refresh_seconds=str_to_int(
                os.environ.get("SITEMAP_REFRESH_SECONDS"), 86400
            ),
            http_timeout_seconds=str_to_int(
                os.environ.get("HTTP_TIMEOUT_SECONDS"), 30
            ),
            http_max_retries=str_to_int(os.environ.get("HTTP_MAX_RETRIES"), 3),
            http_retry_backoff=str_to_int(os.environ.get("HTTP_RETRY_BACKOFF"), 2),
            s3_enable=str_to_bool(os.environ.get("S3_ENABLE"), True),
            s3_endpoint=os.environ.get("S3_ENDPOINT", ""),
            s3_access_key=os.environ.get("S3_ACCESS_KEY", ""),
            s3_secret_key=os.environ.get("S3_SECRET_KEY", ""),
            s3_region=os.environ.get("S3_REGION", "auto"),
            s3_bucket=os.environ.get("S3_BUCKET", ""),
            s3_sent_urls_key=os.environ.get("S3_SENT_URLS_KEY", "sent_urls.txt"),
            s3_sent_news_key=os.environ.get("S3_SENT_NEWS_KEY", "sent_news.txt"),
            s3_sent_instagram_key=os.environ.get(
                "S3_SENT_INSTAGRAM_KEY", "sent_instagram.txt"
            ),
            tweet_filter_mode=os.environ.get(
                "TWEET_FILTER_MODE", DEFAULT_TWEET_FILTER_MODE
            )
            .strip()
            .lower(),
            blocked_tweet_terms=parse_list(
                os.environ.get(
                    "BLOCKED_TWEET_TERMS", ",".join(DEFAULT_BLOCKED_TWEET_TERMS)
                )
            ),
            watch_tweet_terms=parse_list(
                os.environ.get("WATCH_TWEET_TERMS", ",".join(DEFAULT_WATCH_TWEET_TERMS))
            ),
            location_hashtag_terms=parse_list(
                os.environ.get(
                    "LOCATION_HASHTAG_TERMS",
                    ",".join(DEFAULT_LOCATION_HASHTAG_TERMS),
                )
            ),
            tweet_filter_bypass_queries=parse_list(
                os.environ.get(
                    "TWEET_FILTER_BYPASS_QUERIES",
                    ",".join(DEFAULT_TWEET_FILTER_BYPASS_QUERIES),
                )
            ),
            tweet_required_prefixes=parse_required_prefixes(
                os.environ.get("TWEET_REQUIRED_PREFIXES")
            ),
            queries_schedule=parse_query_schedule(
                schedule_raw, default_query, default_interval
            ),
            db_url=os.environ.get("DB_URL", ""),
            instagram_enable=str_to_bool(os.environ.get("INSTAGRAM_ENABLE"), False),
            instagram_username=os.environ.get("INSTAGRAM_USERNAME", ""),
            instagram_password=os.environ.get("INSTAGRAM_PASSWORD", ""),
            instagram_session_file=os.environ.get(
                "INSTAGRAM_SESSION_FILE", "instagram_session.json"
            ),
            instagram_targets=parse_instagram_targets(
                os.environ.get("INSTAGRAM_TARGETS"),
                parse_duration_seconds(os.environ.get("INSTAGRAM_INTERVAL"), 1800),
            ),
            instagram_limit=str_to_int(os.environ.get("INSTAGRAM_LIMIT"), 5),
            instagram_interval_jitter_seconds=max(
                0, parse_duration_seconds(os.environ.get("INSTAGRAM_JITTER"), 300)
            ),
            instagram_send_existing=str_to_bool(
                os.environ.get("INSTAGRAM_SEND_EXISTING"), False
            ),
        )


def build_http_session(config: Config) -> requests.Session:
    retry_strategy = Retry(
        total=config.http_max_retries,
        backoff_factor=config.http_retry_backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class DBClient:
    """Lightweight Postgres client for persisting tweets/news."""

    TWEET_INSERT_SQL = """
        INSERT INTO tweets (
            tweet_id, query, user_handle, user_name, text, link,
            tweet_created_at, delivery_status, filter_reasons
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (link) DO NOTHING;
    """
    NEWS_INSERT_SQL = """
        INSERT INTO news (link, source, news_created_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (link) DO NOTHING;
    """

    def __init__(
        self,
        db_url: str,
        retry_interval_seconds: int = 30,
        pending_limit: int = 50000,
    ):
        self.db_url = db_url
        self.conn = None
        self.enabled = bool(db_url)
        self.retry_interval_seconds = max(0, retry_interval_seconds)
        self.pending_limit = max(1, pending_limit)
        self.next_retry_at = 0.0
        self.tables_ready = False
        self.lock = threading.RLock()
        self.pending_tweets: Dict[str, Tuple] = {}
        self.pending_news: Dict[str, Tuple] = {}
        if not self.enabled:
            return
        self.ensure_tables()

    def _disconnect_locked(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:  # pylint: disable=broad-except
                pass
        self.conn = None
        self.tables_ready = False
        self.next_retry_at = time.monotonic() + self.retry_interval_seconds

    def _ensure_connection_locked(self) -> bool:
        if not self.enabled:
            return False
        if self.conn and not self.conn.closed:
            return True
        if time.monotonic() < self.next_retry_at:
            return False
        try:
            self.conn = psycopg2.connect(self.db_url, connect_timeout=5)
            self.conn.autocommit = True
            self.next_retry_at = 0.0
            log("db connected")
            return True
        except Exception as exc:  # pylint: disable=broad-except
            log(f"db connect failed: {exc}")
            self._disconnect_locked()
            return False

    def _ensure_tables_locked(self) -> bool:
        if not self._ensure_connection_locked():
            return False
        if self.tables_ready:
            return True
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tweets (
                        id SERIAL PRIMARY KEY,
                        tweet_id TEXT,
                        query TEXT,
                        user_handle TEXT,
                        user_name TEXT,
                        text TEXT,
                        link TEXT UNIQUE,
                        tweet_created_at TIMESTAMPTZ,
                        delivery_status TEXT NOT NULL DEFAULT 'sent',
                        filter_reasons TEXT[] NOT NULL DEFAULT '{}',
                        fetched_at TIMESTAMPTZ DEFAULT NOW()
                    );
                    ALTER TABLE tweets
                        ADD COLUMN IF NOT EXISTS delivery_status TEXT NOT NULL DEFAULT 'sent';
                    ALTER TABLE tweets
                        ADD COLUMN IF NOT EXISTS filter_reasons TEXT[] NOT NULL DEFAULT '{}';
                    CREATE INDEX IF NOT EXISTS idx_tweets_query_created_at
                        ON tweets (query, tweet_created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_tweets_delivery_status_created_at
                        ON tweets (delivery_status, tweet_created_at DESC);
                    CREATE TABLE IF NOT EXISTS news (
                        id SERIAL PRIMARY KEY,
                        link TEXT UNIQUE,
                        source TEXT,
                        news_created_at TIMESTAMPTZ,
                        fetched_at TIMESTAMPTZ DEFAULT NOW()
                    );
                    """
                )
            self.tables_ready = True
            return True
        except Exception as exc:  # pylint: disable=broad-except
            log(f"db ensure tables failed: {exc}")
            self._disconnect_locked()
            return False

    def ensure_tables(self) -> bool:
        if not self.enabled:
            return False
        with self.lock:
            return self._ensure_tables_locked()

    def _queue_locked(self, queue: Dict[str, Tuple], key: str, params: Tuple) -> None:
        if key in queue:
            return
        if len(queue) >= self.pending_limit:
            oldest_key = next(iter(queue))
            queue.pop(oldest_key)
            log(f"db pending queue full: dropped oldest key={oldest_key}")
        queue[key] = params

    def _execute_locked(self, sql: str, params: Tuple, label: str) -> bool:
        try:
            with self.conn.cursor() as cur:
                cur.execute(sql, params)
            return True
        except Exception as exc:  # pylint: disable=broad-except
            log(f"db insert {label} failed: {exc}")
            self._disconnect_locked()
            return False

    def _flush_pending_locked(self) -> bool:
        flushed_tweets = 0
        flushed_news = 0
        for key, params in list(self.pending_tweets.items()):
            if not self._execute_locked(self.TWEET_INSERT_SQL, params, "tweet"):
                return False
            self.pending_tweets.pop(key, None)
            flushed_tweets += 1
        for key, params in list(self.pending_news.items()):
            if not self._execute_locked(self.NEWS_INSERT_SQL, params, "news"):
                return False
            self.pending_news.pop(key, None)
            flushed_news += 1
        if flushed_tweets or flushed_news:
            log(
                f"db pending flushed tweets={flushed_tweets} news={flushed_news}"
            )
        return True

    def insert_tweet(
        self,
        tweet: Dict,
        query: str,
        delivery_status: str = "sent",
        filter_reasons: Optional[List[str]] = None,
    ) -> bool:
        if not self.enabled:
            return False
        link = str(tweet.get("link") or tweet.get("id") or "")
        params = (
            tweet.get("id"),
            query,
            tweet.get("user_handle"),
            tweet.get("user_name"),
            tweet.get("text"),
            tweet.get("link"),
            tweet.get("created_at_dt") or parse_datetime(tweet.get("created_at")),
            delivery_status,
            list(filter_reasons or []),
        )
        with self.lock:
            if not self._ensure_tables_locked():
                self._queue_locked(self.pending_tweets, link, params)
                return False
            if not self._flush_pending_locked():
                self._queue_locked(self.pending_tweets, link, params)
                return False
            if self._execute_locked(self.TWEET_INSERT_SQL, params, "tweet"):
                return True
            self._queue_locked(self.pending_tweets, link, params)
            return False

    def insert_news(self, entry: Dict) -> bool:
        if not self.enabled:
            return False
        link = str(entry.get("link") or "")
        params = (
            entry.get("link"),
            urlparse(entry.get("link", "")).netloc,
            entry.get("created_at_dt") or parse_datetime(entry.get("created_at")),
        )
        with self.lock:
            if not self._ensure_tables_locked():
                self._queue_locked(self.pending_news, link, params)
                return False
            if not self._flush_pending_locked():
                self._queue_locked(self.pending_news, link, params)
                return False
            if self._execute_locked(self.NEWS_INSERT_SQL, params, "news"):
                return True
            self._queue_locked(self.pending_news, link, params)
            return False


class R2Store:
    """Persist sent URL lists to Cloudflare R2 and local disk."""

    def __init__(self, config: Config):
        self.config = config
        self.lock = threading.Lock()
        self.enabled = bool(
            config.s3_enable
            and config.s3_endpoint
            and config.s3_access_key
            and config.s3_secret_key
            and config.s3_bucket
        )
        self.client = None
        if self.enabled:
            self.client = boto3.client(
                "s3",
                endpoint_url=config.s3_endpoint,
                region_name=config.s3_region,
                aws_access_key_id=config.s3_access_key,
                aws_secret_access_key=config.s3_secret_key,
                config=BotoConfig(signature_version="s3v4"),
            )

    def _read_local_lines(self, path: str) -> Set[str]:
        if not os.path.exists(path):
            return set()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return {line.strip() for line in handle if line.strip()}
        except OSError as exc:
            log(f"store read local failed: {path} ({exc})")
            return set()

    def _write_local(self, path: str, values: Set[str]) -> None:
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(sorted(values)))
        except OSError as exc:
            log(f"store write local failed: {path} ({exc})")

    def _get_remote_text(self, key: str) -> Optional[str]:
        if not self.enabled or not self.client:
            return None
        try:
            response = self.client.get_object(Bucket=self.config.s3_bucket, Key=key)
            body = response.get("Body")
            if not body:
                return None
            return body.read().decode("utf-8")
        except self.client.exceptions.NoSuchKey:
            return None
        except ClientError as exc:
            log(f"store download failed: {key} ({exc})")
            return None

    def _put_remote_text(self, key: str, text: str) -> None:
        if not self.enabled or not self.client:
            return
        try:
            self.client.put_object(
                Bucket=self.config.s3_bucket,
                Key=key,
                Body=text.encode("utf-8"),
                ContentType="text/plain",
            )
        except ClientError as exc:
            log(f"store upload failed: {key} ({exc})")

    def load_set(self, key: str, local_path: str) -> Set[str]:
        with self.lock:
            values = set()
            values.update(self._read_local_lines(local_path))
            remote_text = self._get_remote_text(key)
            if remote_text:
                values.update(
                    {line.strip() for line in remote_text.splitlines() if line.strip()}
                )
            return values

    def save_set(self, key: str, local_path: str, values: Set[str]) -> None:
        with self.lock:
            snapshot = set(values)
            self._write_local(local_path, snapshot)
            self._put_remote_text(key, "\n".join(sorted(snapshot)))


def parse_datetime(value: Optional[object]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=ISTANBUL_TZ)
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S",
        "%a %b %d %H:%M:%S %z %Y",  # Twitter format
    ):
        try:
            parsed = datetime.strptime(
                text.replace("Z", "+0000").replace("+00:00", "+0000"), fmt
            )
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=ISTANBUL_TZ)
            return parsed
        except ValueError:
            continue
    try:
        return datetime.fromtimestamp(int(text), tz=timezone.utc)
    except (ValueError, OverflowError):
        return None


def format_datetime(dt: Optional[datetime]) -> str:
    if not dt:
        return "Bilinmiyor"
    return dt.astimezone(ISTANBUL_TZ).strftime("%Y-%m-%d %H:%M:%S")


def normalize_tweet(raw: Dict) -> Optional[Dict]:
    tweet_id = str(
        raw.get("tweet_id")
        or raw.get("id_str")
        or raw.get("id")
        or raw.get("tweetId")
        or raw.get("conversation_id")
        or ""
    ).strip()
    user_info = raw.get("user_info") or raw.get("user") or {}
    user_handle = (
        raw.get("screen_name")
        or raw.get("username")
        or raw.get("user_screen_name")
        or user_info.get("screen_name")
        or user_info.get("username")
    )
    user_name = raw.get("name") or user_info.get("name") or user_handle or "Bilinmiyor"
    text = raw.get("full_text") or raw.get("text") or raw.get("tweet") or raw.get("content")
    created_at_raw = raw.get("created_at") or raw.get("date") or raw.get("time")
    link = raw.get("link") or raw.get("url") or raw.get("tweet_url")
    if not link and tweet_id:
        if user_handle:
            link = f"https://x.com/{user_handle}/status/{tweet_id}"
        else:
            link = f"https://x.com/i/web/status/{tweet_id}"
    if not link or not text:
        return None
    dt = parse_datetime(created_at_raw)
    return {
        "id": tweet_id or link,
        "user_handle": (user_handle or "").strip(),
        "user_name": user_name,
        "text": text.strip(),
        "created_at": format_datetime(dt),
        "created_at_dt": dt,
        "sort_ts": dt.timestamp() if dt else 0,
        "link": link,
    }


def extract_tweets(payload: Dict) -> List[Dict]:
    candidates: Iterable = []
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        for key in ("timeline", "data", "statuses", "result", "results"):
            if key in payload and isinstance(payload[key], list):
                candidates = payload[key]
                break
    tweets: List[Dict] = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        normalized = normalize_tweet(raw)
        if normalized:
            tweets.append(normalized)
    tweets.sort(key=lambda item: item.get("sort_ts", 0), reverse=True)
    return tweets


def matches_query(search_query: str, tweet: Dict) -> bool:
    q = (search_query or "").strip()
    if not q:
        return True
    q_lower = q.lower()
    text_lower = (tweet.get("text") or "").lower()
    link_lower = (tweet.get("link") or "").lower()
    handle_lower = (tweet.get("user_handle") or "").lower()

    if q_lower.startswith("from:"):
        handle = q_lower[5:].strip()
        return bool(handle) and handle_lower == handle
    if q_lower.startswith("to:"):
        handle = q_lower[3:].strip()
        return bool(handle) and (handle in text_lower or handle in link_lower)
    if q_lower.startswith("@"):
        handle = q_lower[1:].strip()
        return bool(handle) and (
            handle in text_lower or handle == handle_lower or handle in link_lower
        )

    terms = [term for term in q_lower.split() if term]
    if not terms:
        return True
    return all(term in text_lower for term in terms)


def compact_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").lower()
    return "".join(ch for ch in normalized if ch.isalnum())


def text_contains_term(haystack_lower: str, haystack_compact: str, term: str) -> bool:
    clean_term = term.strip().lower()
    if not clean_term:
        return False
    return clean_term in haystack_lower or compact_text(clean_term) in haystack_compact


def extract_hashtags(text: str) -> List[str]:
    return [match.lower() for match in re.findall(r"#([^\s#@/]+)", text or "")]


def meaningful_text_length(text: str) -> int:
    without_urls = re.sub(r"https?://\S+", " ", text or "", flags=re.IGNORECASE)
    without_mentions = re.sub(r"@\S+", " ", without_urls)
    without_hashtags = re.sub(r"#\S+", " ", without_mentions)
    return len(compact_text(without_hashtags))


def count_location_mentions(text: str, location_terms: Set[str]) -> int:
    text_lower = (text or "").lower()
    count = 0
    for term in location_terms:
        clean = term.strip().lower()
        if not clean:
            continue
        if re.search(rf"(?<!\w)#?{re.escape(clean)}(?!\w)", text_lower):
            count += 1
    return count


def looks_like_autogenerated_handle(handle: str) -> bool:
    cleaned = (handle or "").strip()
    if not cleaned or "_" in cleaned:
        return False
    return bool(re.fullmatch(r"[A-Za-z]{5,}[A-Za-z]*\d+[A-Za-z0-9]*", cleaned))


def is_luleburgaz_query(search_query: str) -> bool:
    return compact_text(search_query) in {"lüleburgaz", "luleburgaz"}


def looks_like_generated_numeric_handle(handle: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z]{3,}\d{6,}", (handle or "").strip()))


def contains_pictographic_symbol(text: str) -> bool:
    return any(unicodedata.category(character) == "So" for character in text or "")


def looks_like_simple_display_name(name: str) -> bool:
    cleaned = (name or "").strip()
    return len(cleaned) >= 3 and cleaned.isalpha()


def count_non_location_words(text: str, location_terms: Set[str]) -> int:
    remaining = re.sub(r"https?://\S+", " ", text or "", flags=re.IGNORECASE)
    remaining = re.sub(r"@\S+", " ", remaining)
    for term in sorted(location_terms, key=len, reverse=True):
        clean = term.strip().lower()
        if not clean:
            continue
        remaining = re.sub(
            rf"(?<!\w)#?{re.escape(clean)}(?!\w)",
            " ",
            remaining,
            flags=re.IGNORECASE,
        )
    return len(re.findall(r"[^\W\d_]+", remaining, flags=re.UNICODE))


def query_bypasses_tweet_filter(config: Config, search_query: str) -> bool:
    query = (search_query or "").strip().lower()
    if query.startswith("from:"):
        return True
    return query in {item.strip().lower() for item in config.tweet_filter_bypass_queries}


def evaluate_tweet_filter(config: Config, search_query: str, tweet: Dict) -> List[str]:
    reasons: List[str] = []
    required_prefix = config.tweet_required_prefixes.get(
        (search_query or "").strip().lower()
    )
    if required_prefix:
        text = unicodedata.normalize("NFKC", str(tweet.get("text") or "")).lstrip()
        prefix = unicodedata.normalize("NFKC", required_prefix)
        if not normalize_prefix_match(text).startswith(normalize_prefix_match(prefix)):
            reasons.append("required_prefix_missing")
    if config.tweet_filter_mode == "off" or query_bypasses_tweet_filter(
        config, search_query
    ):
        return reasons

    haystack = " ".join(
        str(tweet.get(key) or "") for key in ("text", "user_handle", "user_name", "link")
    )
    haystack_lower = haystack.lower()
    haystack_compact = compact_text(haystack)
    for term in config.blocked_tweet_terms:
        clean_term = term.strip().lower()
        if not clean_term:
            continue
        if text_contains_term(haystack_lower, haystack_compact, clean_term):
            reasons.append(f"blocked_term:{clean_term}")

    for term in config.watch_tweet_terms:
        clean_term = term.strip().lower()
        if not clean_term:
            continue
        if text_contains_term(haystack_lower, haystack_compact, clean_term):
            reasons.append(f"watch_term:{clean_term}")

    text = str(tweet.get("text") or "")
    hashtags = extract_hashtags(text)
    location_terms = {term.lower() for term in config.location_hashtag_terms}
    location_hashtags = [tag for tag in hashtags if tag in location_terms]
    has_link = "http" in text.lower()
    meaningful_length = meaningful_text_length(text)
    if (
        has_link
        and len(hashtags) >= 2
        and len(location_hashtags) >= 1
        and meaningful_length <= 4
    ):
        reasons.append("block_pattern:location_hashtags_link_only")

    location_mentions = count_location_mentions(text, location_terms)
    if has_link and location_mentions >= 3 and meaningful_length <= 45:
        reasons.append("block_pattern:location_word_soup_link")

    if (
        has_link
        and location_mentions >= 2
        and meaningful_length <= 90
        and looks_like_autogenerated_handle(str(tweet.get("user_handle") or ""))
    ):
        reasons.append("block_pattern:suspicious_location_link")

    if (
        has_link
        and location_mentions >= 1
        and looks_like_generated_numeric_handle(
            str(tweet.get("user_handle") or "")
        )
        and looks_like_simple_display_name(str(tweet.get("user_name") or ""))
        and count_non_location_words(text, location_terms) <= 5
        and contains_pictographic_symbol(text)
    ):
        reasons.append("block_pattern:generated_location_link_campaign")

    if is_luleburgaz_query(search_query) and has_link:
        handle = str(tweet.get("user_handle") or "")
        user_name = str(tweet.get("user_name") or "")
        short_campaign_handle = looks_like_generated_numeric_handle(handle)
        profile_campaign_handle = short_campaign_handle or looks_like_autogenerated_handle(
            handle
        )
        campaign_location_terms = location_terms | {
            term.lower() for term in LULEBURGAZ_CAMPAIGN_LOCATION_TERMS
        }
        campaign_location_mentions = count_location_mentions(
            text, campaign_location_terms
        )
        remaining_words = count_non_location_words(text, campaign_location_terms)
        if (
            short_campaign_handle
            and campaign_location_mentions >= 1
            and remaining_words <= 3
            and looks_like_simple_display_name(user_name)
        ):
            reasons.append("block_pattern:luleburgaz_short_link_campaign")

        profile_lower = f"{handle} {user_name}".lower()
        if (
            profile_campaign_handle
            and campaign_location_mentions >= 1
            and any(term in profile_lower for term in LULEBURGAZ_CAMPAIGN_PROFILE_TERMS)
        ):
            reasons.append("block_pattern:luleburgaz_ad_profile")
        if (
            profile_campaign_handle
            and campaign_location_mentions >= 3
            and text.count(",") >= 5
        ):
            reasons.append("block_pattern:luleburgaz_location_dump")

    if re.search(r"(?:\+?90\s*)?0?5\d{2}[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}", text):
        reasons.append("watch_pattern:phone_number")

    return reasons


def should_drop_filtered_tweet(reasons: List[str]) -> bool:
    droppable_reasons = set(DEFAULT_DROPPABLE_FILTER_REASONS)
    return any(
        reason.startswith("blocked_term:")
        or reason == "required_prefix_missing"
        or reason in droppable_reasons
        for reason in reasons
    )


def send_telegram_message(
    session: requests.Session, token: str, chat_id: str, text: str
) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": False}
    try:
        response = session.post(url, json=payload, timeout=20)
    except requests.RequestException as exc:
        log(f"telegram send error: {exc}")
        return False
    if not response.ok:
        log(f"telegram send failed: {response.status_code} {response.text}")
        return False
    log("telegram send ok")
    return True


def send_telegram_media(
    session: requests.Session,
    token: str,
    chat_id: str,
    media_kind: Optional[str],
    media_url: Optional[str],
    caption: str,
    fallback_cover_url: Optional[str] = None,
    max_upload_bytes: int = 45 * 1024 * 1024,
) -> bool:
    caption = caption[:997] + "..." if len(caption) > 1000 else caption
    if not media_kind or not media_url:
        return send_telegram_message(session, token, chat_id, caption)

    method = "sendVideo" if media_kind == "video" else "sendPhoto"
    field = "video" if media_kind == "video" else "photo"
    payload = {"chat_id": chat_id, field: media_url, "caption": caption}
    if media_kind == "video":
        payload["supports_streaming"] = "true"

    try:
        response = session.post(
            f"https://api.telegram.org/bot{token}/{method}",
            data=payload,
            timeout=90,
        )
        if response.ok:
            log(f"telegram {method} ok url")
            return True
        log(f"telegram {method} url failed: {response.status_code} {response.text}")
    except requests.RequestException as exc:
        log(f"telegram {method} url error: {exc}")

    try:
        media_response = session.get(media_url, timeout=90)
        media_response.raise_for_status()
        content = media_response.content
    except requests.RequestException as exc:
        log(f"telegram media download failed: {exc}")
        content = b""

    if content and len(content) <= max_upload_bytes:
        suffix = ".mp4" if media_kind == "video" else ".jpg"
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
                handle.write(content)
                handle.flush()
                upload_payload = {"chat_id": chat_id, "caption": caption}
                if media_kind == "video":
                    upload_payload["supports_streaming"] = "true"
                with open(handle.name, "rb") as media_file:
                    response = session.post(
                        f"https://api.telegram.org/bot{token}/{method}",
                        data=upload_payload,
                        files={field: media_file},
                        timeout=180,
                    )
            if response.ok:
                log(f"telegram {method} ok upload")
                return True
            log(
                f"telegram {method} upload failed: "
                f"{response.status_code} {response.text}"
            )
        except OSError as exc:
            log(f"telegram media temp file failed: {exc}")
    elif content:
        log(f"telegram media too large: {len(content)} bytes")

    if fallback_cover_url and media_kind == "video":
        fallback_caption = (
            caption
            + "\n\nVideo büyük veya Telegram tarafından alınamadı; kapak görseli gönderildi."
        )
        payload = {
            "chat_id": chat_id,
            "photo": fallback_cover_url,
            "caption": fallback_caption[:1000],
        }
        try:
            response = session.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data=payload,
                timeout=90,
            )
            if response.ok:
                log("telegram sendPhoto ok cover")
                return True
            log(f"telegram cover failed: {response.status_code} {response.text}")
        except requests.RequestException as exc:
            log(f"telegram cover error: {exc}")

    return send_telegram_message(session, token, chat_id, caption)


def fetch_latest_tweets(
    config: Config, session: requests.Session, search_query: str
) -> List[Dict]:
    url = "https://twitter-api45.p.rapidapi.com/search.php"
    params = {"query": search_query, "search_type": config.query_type}
    headers = {
        "x-rapidapi-key": config.api_key,
        "x-rapidapi-host": "twitter-api45.p.rapidapi.com",
    }
    response = session.get(url, headers=headers, params=params, timeout=config.http_timeout_seconds)
    if not response.ok:
        log(f"tweets api error: {response.status_code} {response.text}")
        return []
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        log(f"tweets json parse failed: {exc}")
        return []
    tweets = extract_tweets(payload)
    filtered = [tweet for tweet in tweets if matches_query(search_query, tweet)]
    if config.tweet_limit and len(filtered) > config.tweet_limit:
        filtered = filtered[: config.tweet_limit]
    log(
        f"tweets fetched={len(filtered)} query='{search_query}' raw={len(tweets)}"
    )
    return filtered


TELEGRAM_MESSAGE_SAFE_LIMIT = 4000


def build_tweet_message(tweet: Dict) -> str:
    header = (
        "🐦 Yeni Tweet\n\n"
        f"👤 Kullanıcı: {tweet['user_name']}\n"
        "💬 Tweet: "
    )
    footer = f"🕒 Tarih: {tweet['created_at']}\n🔗 Link: {tweet['link']}"
    available_text_length = max(
        1, TELEGRAM_MESSAGE_SAFE_LIMIT - len(header) - len(footer) - 1
    )
    text = str(tweet["text"])
    if len(text) > available_text_length:
        text = text[: available_text_length - 1].rstrip() + "…"
    return f"{header}{text}\n{footer}"


def month_offset(dt: datetime, offset: int) -> datetime:
    month_index = dt.year * 12 + (dt.month - 1) + offset
    year = month_index // 12
    month = month_index % 12 + 1
    return dt.replace(year=year, month=month, day=1)


def render_sitemap_template(template: str, dt: datetime) -> str:
    return template.format(
        YYYY=f"{dt.year:04d}",
        YY=f"{dt.year % 100:02d}",
        MM=f"{dt.month:02d}",
        M=str(dt.month),
    )


def unique_in_order(values: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def build_configured_sitemap_urls(
    config: Config, now: Optional[datetime] = None
) -> List[str]:
    current = (now or datetime.now(ISTANBUL_TZ)).astimezone(ISTANBUL_TZ)
    urls: List[str] = list(config.sitemap_urls)
    for template in config.sitemap_monthly_templates:
        for offset in range(0, -config.sitemap_month_lookback - 1, -1):
            urls.append(render_sitemap_template(template, month_offset(current, offset)))
    return unique_in_order(urls)


def load_sitemap_list(
    config: Config, session: requests.Session, force_refresh: bool = False
) -> List[str]:
    urls = build_configured_sitemap_urls(config)
    if urls:
        return urls

    should_download = bool(config.sitemap_list_url) and (
        force_refresh or not os.path.exists(config.sitemap_list_file)
    )
    if should_download:
        try:
            response = session.get(
                config.sitemap_list_url, timeout=config.http_timeout_seconds
            )
            if response.ok:
                with open(config.sitemap_list_file, "w", encoding="utf-8") as handle:
                    handle.write(response.text)
                log("sitemap list downloaded")
            else:
                log(f"sitemap list download failed: {response.status_code} (using cache)")
        except requests.RequestException as exc:
            log(f"sitemap list error: {exc}")
    if os.path.exists(config.sitemap_list_file):
        try:
            with open(config.sitemap_list_file, "r", encoding="utf-8") as handle:
                urls = [line.strip() for line in handle if line.strip()]
        except OSError as exc:
            log(f"sitemap list read failed: {exc}")
    return unique_in_order(urls)


def parse_sitemap_xml(content: str) -> Tuple[List[str], List[Tuple[str, Optional[str]]]]:
    sitemap_links: List[str] = []
    entries: List[Tuple[str, Optional[str]]] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return sitemap_links, entries
    tag = root.tag.lower()
    if tag.endswith("sitemapindex"):
        for node in root.findall(".//{*}loc"):
            if node.text:
                sitemap_links.append(node.text.strip())
    else:
        for url_node in root.findall(".//{*}url"):
            loc_node = url_node.find(".//{*}loc")
            if loc_node is None or not loc_node.text:
                continue
            loc = loc_node.text.strip()
            lastmod_node = url_node.find(".//{*}lastmod")
            lastmod = lastmod_node.text.strip() if lastmod_node is not None and lastmod_node.text else None
            entries.append((loc, lastmod))
    return sitemap_links, entries


def fetch_sitemap_entries(
    sitemap_urls: List[str],
    session: requests.Session,
    timeout: int,
    max_depth: int = 1,
) -> List[Tuple[str, Optional[str]]]:
    collected: List[Tuple[str, Optional[str]]] = []
    visited: Set[str] = set()
    queue: List[Tuple[str, int]] = [(url, 0) for url in sitemap_urls]
    while queue:
        url, depth = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            response = session.get(url, timeout=timeout)
            if not response.ok:
                log(f"sitemap fetch failed: {response.status_code} {url}")
                continue
            sitemap_links, entries = parse_sitemap_xml(response.text)
            collected.extend(entries)
            if depth < max_depth:
                for child in sitemap_links:
                    queue.append((child, depth + 1))
        except requests.RequestException as exc:
            log(f"sitemap fetch error: {url} ({exc})")
    return collected


def filter_news_entries(
    entries: List[Tuple[str, Optional[str]]], max_age_hours: int
) -> List[Dict]:
    filtered: List[Dict] = []
    now = datetime.now(ISTANBUL_TZ)
    for link, lastmod in entries:
        parsed = urlparse(link)
        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in IMAGE_EXTENSIONS):
            continue
        dt = parse_datetime(lastmod) if lastmod else None
        if dt and max_age_hours and (now - dt).total_seconds() > max_age_hours * 3600:
            continue
        filtered.append(
            {
                "link": link,
                "created_at": format_datetime(dt),
                "created_at_dt": dt,
                "sort_ts": dt.timestamp() if dt else 0,
            }
        )
    filtered.sort(key=lambda item: item.get("sort_ts", 0), reverse=True)
    return filtered


def build_news_message(entry: Dict) -> str:
    domain = urlparse(entry["link"]).netloc
    if domain.startswith("www."):
        domain = domain[4:]
    return (
        "📰 Yeni Haber\n\n"
        f"🌐 Kaynak: {domain or 'Bilinmiyor'}\n"
        f"🕒 Tarih: {entry['created_at']}\n"
        f"🔗 Link: {entry['link']}"
    )


def tweet_loop(
    config: Config,
    session: requests.Session,
    store: R2Store,
    db: DBClient,
    sent_links: Set[str],
    lock: threading.Lock,
    stop_event: threading.Event,
) -> None:
    schedule = config.queries_schedule or [
        QuerySchedule(config.query, config.poll_interval_seconds)
    ]
    next_run: Dict[str, float] = {item.query: 0.0 for item in schedule}
    while not stop_event.is_set():
        try:
            now = time.time()
            for item in schedule:
                due_at = next_run.get(item.query, 0)
                if now < due_at:
                    continue
                tweets = fetch_latest_tweets(config, session, item.query)
                new_count = 0
                filtered_count = 0
                for tweet in tweets:
                    link = tweet["link"]
                    with lock:
                        if link in sent_links:
                            continue
                    filter_reasons = evaluate_tweet_filter(config, item.query, tweet)
                    if filter_reasons:
                        should_drop = (
                            "required_prefix_missing" in filter_reasons
                            or (
                                config.tweet_filter_mode == "drop"
                                and should_drop_filtered_tweet(filter_reasons)
                            )
                        )
                        log(
                            "tweet filter match "
                            f"mode={config.tweet_filter_mode} "
                            f"decision={'drop' if should_drop else 'observe'} "
                            f"query='{item.query}' "
                            f"reasons={','.join(filter_reasons)} link={link}"
                        )
                        if should_drop:
                            db.insert_tweet(
                                tweet,
                                item.query,
                                delivery_status="filtered",
                                filter_reasons=filter_reasons,
                            )
                            with lock:
                                sent_links.add(link)
                            filtered_count += 1
                            continue
                    sent = send_telegram_message(
                        session,
                        config.telegram_token,
                        config.telegram_chat_id,
                        build_tweet_message(tweet),
                    )
                    if not sent:
                        log(f"tweet send skipped link={link}")
                        continue
                    with lock:
                        sent_links.add(link)
                    log(f"tweet sent link={link}")
                    db.insert_tweet(
                        tweet,
                        item.query,
                        delivery_status="sent",
                        filter_reasons=filter_reasons,
                    )
                    new_count += 1
                if new_count or filtered_count:
                    store.save_set(
                        config.s3_sent_urls_key, config.sent_urls_file, sent_links
                    )
                log(
                    f"tweets cycle query='{item.query}' fetched={len(tweets)} "
                    f"sent={new_count} filtered={filtered_count}"
                )
                next_run[item.query] = time.time() + max(1, item.interval_seconds)
        except Exception as exc:  # pylint: disable=broad-except
            log(f"tweets unexpected error: {exc}")
        # Sleep until the soonest next run, but wake periodically to allow shutdown.
        if next_run:
            sleep_for = max(1.0, min(next_run.values()) - time.time())
        else:
            sleep_for = max(1.0, config.poll_interval_seconds)
        stop_event.wait(sleep_for)


def news_loop(
    config: Config,
    session: requests.Session,
    store: R2Store,
    db: DBClient,
    sent_news: Set[str],
    lock: threading.Lock,
    stop_event: threading.Event,
) -> None:
    last_refresh = 0.0
    sitemap_urls: List[str] = []
    while not stop_event.is_set():
        now = time.time()
        if not sitemap_urls or now - last_refresh > config.sitemap_refresh_seconds:
            sitemap_urls = load_sitemap_list(config, session, force_refresh=True)
            last_refresh = now
        entries = fetch_sitemap_entries(
            sitemap_urls, session, timeout=config.http_timeout_seconds
        )
        news_items = filter_news_entries(entries, config.news_max_age_hours)
        latest_items = (
            news_items[: config.news_limit] if config.news_limit else news_items
        )
        sent_now = 0
        for entry in latest_items:
            link = entry["link"]
            with lock:
                if link in sent_news:
                    continue
            sent = send_telegram_message(
                session,
                config.telegram_token,
                config.telegram_chat_id,
                build_news_message(entry),
            )
            if not sent:
                log(f"news send skipped link={link}")
                continue
            with lock:
                sent_news.add(link)
            log(f"news sent link={link}")
            db.insert_news(entry)
            sent_now += 1
        if sent_now:
            store.save_set(config.s3_sent_news_key, config.news_sent_file, sent_news)
        log(
            f"news cycle sites={len(sitemap_urls)} latest_checked={len(latest_items)} sent={sent_now}"
        )
        stop_event.wait(config.sitemap_check_seconds)


def attr_value(obj: object, name: str, default: Optional[object] = None) -> Optional[object]:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def url_to_string(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def instagram_media_urls(item: object) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    video_url = url_to_string(attr_value(item, "video_url"))
    thumbnail_url = url_to_string(attr_value(item, "thumbnail_url"))
    if video_url:
        return "video", video_url, thumbnail_url
    if thumbnail_url:
        return "photo", thumbnail_url, thumbnail_url
    resources = attr_value(item, "resources") or []
    for resource in resources:
        media_kind, media_url, cover_url = instagram_media_urls(resource)
        if media_url:
            return media_kind, media_url, cover_url
    return None, None, thumbnail_url


def normalize_instagram_item(item: object, username: str, kind: str) -> Optional[Dict]:
    pk = str(attr_value(item, "pk") or attr_value(item, "id") or "").strip()
    code = str(attr_value(item, "code") or "").strip()
    taken_at = parse_datetime(attr_value(item, "taken_at"))
    media_type = attr_value(item, "media_type")
    media_kind, media_url, cover_url = instagram_media_urls(item)
    caption = str(attr_value(item, "caption_text") or "").strip()

    if kind == "story":
        item_id = pk
        story_id = pk.split("_", 1)[0]
        link = f"https://www.instagram.com/stories/{username}/{story_id}/" if story_id else ""
    else:
        item_id = code or pk
        link = f"https://www.instagram.com/p/{code}/" if code else ""
    if not item_id:
        return None

    if kind == "story":
        label = "Story"
    elif media_type == 8:
        label = "Çoklu Gönderi"
    elif kind == "clip" or media_type == 2 or media_kind == "video":
        label = "Video/Reels"
    else:
        label = "Gönderi"

    return {
        "id": item_id,
        "username": username,
        "kind": kind,
        "label": label,
        "caption": caption,
        "created_at": format_datetime(taken_at),
        "created_at_dt": taken_at,
        "sort_ts": taken_at.timestamp() if taken_at else 0,
        "link": link,
        "media_kind": media_kind,
        "media_url": media_url,
        "cover_url": cover_url,
    }


def unique_instagram_items(items: Iterable[Dict]) -> List[Dict]:
    seen: Set[str] = set()
    unique: List[Dict] = []
    for item in sorted(items, key=lambda value: value.get("sort_ts", 0), reverse=True):
        key = item.get("id") or item.get("link")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def build_instagram_message(item: Dict, index: Optional[int] = None) -> str:
    suffix = f" ({index})" if index else ""
    if item["kind"] == "story":
        return (
            f"📲 Instagram Story{suffix}\n"
            f"👤 Hesap: @{item['username']}\n"
            f"🕒 Paylaşım: {item['created_at']}\n"
            f"🔗 Story: {item['link'] or '-'}"
        )
    caption = item.get("caption") or ""
    return (
        f"🆕 Instagram {item['label']}{suffix}\n"
        f"👤 Hesap: @{item['username']}\n"
        f"🕒 Tarih: {item['created_at']}\n"
        f"🔗 Link: {item['link'] or '-'}\n"
        f"💬 Açıklama: {caption[:650]}"
    )


def instagram_sent_key(item: Dict) -> str:
    return f"instagram:{item['username']}:{item['kind']}:{item['id']}"


def instagram_prefix(username: str, kind: str) -> str:
    return f"instagram:{username}:{kind}:"


def has_instagram_sent_prefix(sent_items: Set[str], username: str, kind: str) -> bool:
    prefix = instagram_prefix(username, kind)
    return any(item.startswith(prefix) for item in sent_items)


def build_instagram_client(config: Config):
    if InstagramClient is None:
        raise RuntimeError("instagrapi is not installed")
    client = InstagramClient()
    client.delay_range = [1, 3]
    if os.path.exists(config.instagram_session_file):
        try:
            client.load_settings(config.instagram_session_file)
        except Exception as exc:  # pylint: disable=broad-except
            log(f"instagram session load failed: {exc}")
    client.login(config.instagram_username, config.instagram_password)
    try:
        client.dump_settings(config.instagram_session_file)
    except Exception as exc:  # pylint: disable=broad-except
        log(f"instagram session save failed: {exc}")
    return client


def fetch_instagram_items(config: Config, client, username: str) -> Tuple[List[Dict], List[Dict]]:
    user_id = client.user_id_from_username(username)
    story_items = [
        normalized
        for normalized in (
            normalize_instagram_item(item, username, "story")
            for item in client.user_stories(user_id)
        )
        if normalized
    ]
    media_items = [
        normalized
        for normalized in (
            normalize_instagram_item(item, username, "media")
            for item in client.user_medias(user_id, amount=max(config.instagram_limit * 2, 10))
        )
        if normalized
    ]
    clip_items = [
        normalized
        for normalized in (
            normalize_instagram_item(item, username, "clip")
            for item in client.user_clips(user_id, amount=max(config.instagram_limit, 5))
        )
        if normalized
    ]
    feed_items = unique_instagram_items(media_items + clip_items)
    for item in feed_items:
        item["kind"] = "feed"
    story_items = sorted(story_items, key=lambda item: item.get("sort_ts", 0), reverse=True)
    return story_items[: config.instagram_limit], feed_items[: config.instagram_limit]


def next_instagram_interval(config: Config, target: InstagramTarget) -> int:
    jitter = config.instagram_interval_jitter_seconds
    base = max(1, target.interval_seconds)
    if not jitter:
        return base
    return max(60, base + random.randint(-jitter, jitter))


def process_instagram_group(
    config: Config,
    session: requests.Session,
    store: R2Store,
    sent_items: Set[str],
    lock: threading.Lock,
    username: str,
    kind: str,
    items: List[Dict],
) -> Tuple[int, int]:
    sent_count = 0
    seeded_count = 0
    with lock:
        first_run_for_group = not has_instagram_sent_prefix(sent_items, username, kind)
        if first_run_for_group and not config.instagram_send_existing:
            for item in items:
                sent_items.add(instagram_sent_key(item))
            seeded_count = len(items)
            if seeded_count:
                store.save_set(
                    config.s3_sent_instagram_key,
                    config.instagram_sent_file,
                    sent_items,
                )
            return sent_count, seeded_count

    for item in sorted(items, key=lambda value: value.get("sort_ts", 0)):
        key = instagram_sent_key(item)
        with lock:
            if key in sent_items:
                continue
        sent = send_telegram_media(
            session,
            config.telegram_token,
            config.telegram_chat_id,
            item.get("media_kind"),
            item.get("media_url"),
            build_instagram_message(item),
            item.get("cover_url"),
        )
        if not sent:
            log(f"instagram send skipped link={item.get('link')}")
            continue
        with lock:
            sent_items.add(key)
        sent_count += 1
        log(f"instagram sent username={username} kind={kind} link={item.get('link')}")

    if sent_count:
        store.save_set(
            config.s3_sent_instagram_key, config.instagram_sent_file, sent_items
        )
    return sent_count, seeded_count


def instagram_loop(
    config: Config,
    session: requests.Session,
    store: R2Store,
    sent_items: Set[str],
    lock: threading.Lock,
    stop_event: threading.Event,
) -> None:
    if not config.instagram_enable:
        log("instagram disabled")
        return
    if not config.instagram_targets:
        log("instagram disabled: no targets")
        return

    client = None
    next_run: Dict[str, float] = {item.username: 0.0 for item in config.instagram_targets}
    while not stop_event.is_set():
        try:
            if client is None:
                client = build_instagram_client(config)
                log("instagram login ok")

            now = time.time()
            for target in config.instagram_targets:
                due_at = next_run.get(target.username, 0.0)
                if now < due_at:
                    continue

                stories, feed_items = fetch_instagram_items(
                    config, client, target.username
                )
                story_sent, story_seeded = process_instagram_group(
                    config,
                    session,
                    store,
                    sent_items,
                    lock,
                    target.username,
                    "story",
                    stories,
                )
                feed_sent, feed_seeded = process_instagram_group(
                    config,
                    session,
                    store,
                    sent_items,
                    lock,
                    target.username,
                    "feed",
                    feed_items,
                )
                log(
                    "instagram cycle "
                    f"username={target.username} stories={len(stories)} "
                    f"feed={len(feed_items)} sent={story_sent + feed_sent} "
                    f"seeded={story_seeded + feed_seeded}"
                )
                next_run[target.username] = (
                    time.time() + next_instagram_interval(config, target)
                )
        except (ChallengeRequired, TwoFactorRequired, PleaseWaitFewMinutes, LoginRequired) as exc:
            log(f"instagram requires attention: {type(exc).__name__} {exc}")
            send_telegram_message(
                session,
                config.telegram_token,
                config.telegram_chat_id,
                f"Instagram oturumu müdahale istiyor: {type(exc).__name__}",
            )
            return
        except (InstagramClientError, requests.RequestException) as exc:
            log(f"instagram recoverable error: {type(exc).__name__} {exc}")
            client = None
            stop_event.wait(300)
        except Exception as exc:  # pylint: disable=broad-except
            log(f"instagram unexpected error: {type(exc).__name__} {exc}")
            client = None
            stop_event.wait(300)

        if next_run:
            sleep_for = max(1.0, min(next_run.values()) - time.time())
        else:
            sleep_for = 300
        stop_event.wait(sleep_for)


def validate_config(config: Config) -> None:
    missing = []
    for key in ("api_key", "telegram_token", "telegram_chat_id"):
        if not getattr(config, key):
            missing.append(key)
    if config.instagram_enable:
        for key in ("instagram_username", "instagram_password"):
            if not getattr(config, key):
                missing.append(key)
        if InstagramClient is None:
            missing.append("instagrapi dependency")
    if missing:
        raise SystemExit(f"Missing required config values: {', '.join(missing)}")


def main() -> None:
    load_env_file()
    config = Config.from_env()
    validate_config(config)
    session = build_http_session(config)
    store = R2Store(config)
    db = DBClient(config.db_url)
    sent_tweets = store.load_set(config.s3_sent_urls_key, config.sent_urls_file)
    sent_news = store.load_set(config.s3_sent_news_key, config.news_sent_file)
    sent_instagram = store.load_set(
        config.s3_sent_instagram_key, config.instagram_sent_file
    )
    tweet_lock = threading.Lock()
    news_lock = threading.Lock()
    instagram_lock = threading.Lock()
    stop_event = threading.Event()
    log("service start")
    tweet_thread = threading.Thread(
        target=tweet_loop,
        args=(config, session, store, db, sent_tweets, tweet_lock, stop_event),
        daemon=True,
    )
    news_thread = threading.Thread(
        target=news_loop,
        args=(config, session, store, db, sent_news, news_lock, stop_event),
        daemon=True,
    )
    threads = [tweet_thread, news_thread]
    if config.instagram_enable:
        instagram_thread = threading.Thread(
            target=instagram_loop,
            args=(
                config,
                session,
                store,
                sent_instagram,
                instagram_lock,
                stop_event,
            ),
            daemon=True,
        )
        threads.append(instagram_thread)
    tweet_thread.start()
    news_thread.start()
    for thread in threads[2:]:
        thread.start()
    try:
        while tweet_thread.is_alive() and news_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        log("shutdown requested")
        stop_event.set()
        for thread in threads:
            thread.join()
    log("service stop")


if __name__ == "__main__":
    main()
