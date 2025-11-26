import os
import threading
import time
import json
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


@dataclass
class QuerySchedule:
    query: str
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
            interval_seconds = parse_duration_seconds(interval_text, fallback_interval)
            schedule.append(
                QuerySchedule(query=query_clean, interval_seconds=interval_seconds)
            )
    if not schedule and fallback_query:
        schedule.append(
            QuerySchedule(query=fallback_query, interval_seconds=fallback_interval)
        )
    return schedule


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
    news_limit: int
    news_max_age_hours: int
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
    queries_schedule: List[QuerySchedule]

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
            news_limit=str_to_int(os.environ.get("NEWS_LIMIT"), 10),
            news_max_age_hours=str_to_int(os.environ.get("NEWS_MAX_AGE_HOURS"), 72),
            sitemap_list_url=os.environ.get(
                "SITEMAP_LIST_URL", "https://cdn.resimx.com.tr/sitemap.txt"
            ),
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
            queries_schedule=parse_query_schedule(
                schedule_raw, default_query, default_interval
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


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
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
            return datetime.strptime(
                text.replace("Z", "+0000").replace("+00:00", "+0000"), fmt
            )
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


def send_telegram_message(
    session: requests.Session, token: str, chat_id: str, text: str
) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": False}
    response = session.post(url, json=payload, timeout=20)
    if not response.ok:
        log(f"telegram send failed: {response.status_code} {response.text}")
    else:
        log("telegram send ok")


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


def build_tweet_message(tweet: Dict) -> str:
    return (
        "🐦 Yeni Tweet\n\n"
        f"👤 Kullanıcı: {tweet['user_name']}\n"
        f"💬 Tweet: {tweet['text']}\n"
        f"🕒 Tarih: {tweet['created_at']}\n"
        f"🔗 Link: {tweet['link']}"
    )


def load_sitemap_list(
    config: Config, session: requests.Session, force_refresh: bool = False
) -> List[str]:
    should_download = force_refresh or not os.path.exists(config.sitemap_list_file)
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
    urls: List[str] = []
    if os.path.exists(config.sitemap_list_file):
        try:
            with open(config.sitemap_list_file, "r", encoding="utf-8") as handle:
                urls = [line.strip() for line in handle if line.strip()]
        except OSError as exc:
            log(f"sitemap list read failed: {exc}")
    return urls


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
                for tweet in tweets:
                    link = tweet["link"]
                    with lock:
                        if link in sent_links:
                            continue
                        sent_links.add(link)
                    send_telegram_message(
                        session,
                        config.telegram_token,
                        config.telegram_chat_id,
                        build_tweet_message(tweet),
                    )
                    log(f"tweet sent link={link}")
                    new_count += 1
                if new_count:
                    store.save_set(
                        config.s3_sent_urls_key, config.sent_urls_file, sent_links
                    )
                log(
                    f"tweets cycle query='{item.query}' fetched={len(tweets)} sent={new_count}"
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
                sent_news.add(link)
            send_telegram_message(
                session,
                config.telegram_token,
                config.telegram_chat_id,
                build_news_message(entry),
            )
            log(f"news sent link={link}")
            sent_now += 1
        if sent_now:
            store.save_set(config.s3_sent_news_key, config.news_sent_file, sent_news)
        log(
            f"news cycle sites={len(sitemap_urls)} latest_checked={len(latest_items)} sent={sent_now}"
        )
        stop_event.wait(config.sitemap_check_seconds)


def validate_config(config: Config) -> None:
    missing = []
    for key in ("api_key", "telegram_token", "telegram_chat_id"):
        if not getattr(config, key):
            missing.append(key)
    if missing:
        raise SystemExit(f"Missing required config values: {', '.join(missing)}")


def main() -> None:
    load_env_file()
    config = Config.from_env()
    validate_config(config)
    session = build_http_session(config)
    store = R2Store(config)
    sent_tweets = store.load_set(config.s3_sent_urls_key, config.sent_urls_file)
    sent_news = store.load_set(config.s3_sent_news_key, config.news_sent_file)
    tweet_lock = threading.Lock()
    news_lock = threading.Lock()
    stop_event = threading.Event()
    log("service start")
    tweet_thread = threading.Thread(
        target=tweet_loop,
        args=(config, session, store, sent_tweets, tweet_lock, stop_event),
        daemon=True,
    )
    news_thread = threading.Thread(
        target=news_loop,
        args=(config, session, store, sent_news, news_lock, stop_event),
        daemon=True,
    )
    tweet_thread.start()
    news_thread.start()
    try:
        while tweet_thread.is_alive() and news_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        log("shutdown requested")
        stop_event.set()
        tweet_thread.join()
        news_thread.join()
    log("service stop")


if __name__ == "__main__":
    main()


