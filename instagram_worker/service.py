from __future__ import annotations

import logging
import random
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from .client import build_client
from .config import Config, Target
from .delivery import CloudflareDelivery
from .media import prepare_preview
from .models import normalize_items
from .storage import Storage

LOGGER = logging.getLogger(__name__)
ATTENTION_ERRORS = {
    "ChallengeRequired",
    "TwoFactorRequired",
    "FeedbackRequired",
    "PleaseWaitFewMinutes",
    "LoginRequired",
    "BadPassword",
}


class InstagramService:
    def __init__(self, config: Config, client=None):
        self.config = config
        self.client = client
        self.storage = Storage(config.database_file)
        self.delivery = CloudflareDelivery(config)
        self.stop_event = threading.Event()
        self.targets = {target.username: target for target in config.targets}
        for username in self.targets:
            self.storage.ensure_target(username)

    def close(self) -> None:
        self.storage.close()

    def stop(self, *_args: object) -> None:
        self.stop_event.set()

    def _client(self):
        if self.client is None:
            self.client = build_client(self.config)
            LOGGER.info("Instagram session ready")
        return self.client

    def _user_id(self, username: str) -> str:
        cached = self.storage.get_user_id(username)
        if cached:
            return cached
        value = str(self._client().user_id_from_username(username))
        self.storage.set_user_id(username, value)
        return value

    def _next_interval(self, target: Target) -> int:
        jitter = self.config.interval_jitter_seconds
        return max(600, target.interval_seconds + random.randint(-jitter, jitter))

    def _report_run(
        self,
        target: str,
        status: str,
        started_at: str,
        fetched_count: int,
        new_count: int,
        error: str = "",
    ) -> None:
        payload = {
            "target": target,
            "status": status,
            "fetched_count": fetched_count,
            "new_count": new_count,
            "error": error[:1000] or None,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.delivery.report_run(payload)
        except Exception as exc:  # Run telemetry must not stop monitoring.
            LOGGER.warning("Instagram run report failed: %s", exc)

    def check_target(self, target: Target) -> tuple[int, int, int]:
        started_at = datetime.now(timezone.utc).isoformat()
        fetched_count = 0
        new_count = 0
        seeded_count = 0
        try:
            user_id = self._user_id(target.username)
            client = self._client()
            stories = normalize_items(
                list(client.user_stories(user_id)),
                target.username,
                "story",
            )
            feed = normalize_items(
                list(client.user_medias(user_id, amount=self.config.fetch_limit)),
                target.username,
                "feed",
            )
            fetched_count = len(stories) + len(feed)
            for group_name, events in (("story", stories), ("feed", feed)):
                new, seeded = self.storage.add_group(
                    target.username,
                    group_name,
                    events,
                    self.config.send_existing,
                )
                new_count += new
                seeded_count += seeded
            self._report_run(
                target.username,
                "ok",
                started_at,
                fetched_count,
                new_count,
            )
            LOGGER.info(
                "Instagram check complete username=%s fetched=%d new=%d seeded=%d",
                target.username,
                fetched_count,
                new_count,
                seeded_count,
            )
            return fetched_count, new_count, seeded_count
        except Exception as exc:
            error_name = type(exc).__name__
            self._report_run(
                target.username,
                "error",
                started_at,
                fetched_count,
                new_count,
                f"{error_name}: {exc}",
            )
            if error_name in ATTENTION_ERRORS:
                LOGGER.error("Instagram requires manual attention: %s", error_name)
                self.stop_event.set()
            raise
        finally:
            self.storage.schedule_target(
                target.username,
                time.time() + self._next_interval(target),
            )

    def deliver_due(self) -> int:
        delivered = 0
        for row in self.storage.due_items(time.time()):
            event_key = str(row["event_key"])
            preview_path = (
                Path(str(row["preview_path"])) if row["preview_path"] else None
            )
            try:
                if preview_path is None or not preview_path.exists():
                    preview_path = prepare_preview(
                        event_key,
                        str(row["preview_url"]) if row["preview_url"] else None,
                        self.config.media_dir,
                    )
                    self.storage.set_preview_path(
                        event_key,
                        str(preview_path) if preview_path else None,
                    )
                self.delivery.send_event(
                    {
                        "event_key": event_key,
                        "instagram_id": str(row["instagram_id"]),
                        "username": str(row["username"]),
                        "content_type": str(row["content_type"]),
                        "caption": str(row["caption"] or ""),
                        "link": str(row["link"]),
                        "created_at": str(row["created_at"])
                        if row["created_at"]
                        else None,
                    },
                    preview_path,
                )
                self.storage.mark_delivered(event_key)
                delivered += 1
                LOGGER.info("Instagram event delivered event_key=%s", event_key)
            except (
                requests.RequestException,
                OSError,
                RuntimeError,
                ValueError,
            ) as exc:
                attempts = int(row["attempts"] or 0) + 1
                retry_delay = min(6 * 3600, 60 * (2 ** min(attempts, 8)))
                self.storage.mark_failed(event_key, str(exc), time.time() + retry_delay)
                LOGGER.warning(
                    "Instagram delivery failed event_key=%s retry_seconds=%d error=%s",
                    event_key,
                    retry_delay,
                    exc,
                )
        return delivered

    def run_once(self) -> None:
        for target in self.config.targets:
            if self.stop_event.is_set():
                break
            try:
                self.check_target(target)
            except Exception:
                LOGGER.exception(
                    "Instagram target check failed username=%s", target.username
                )
            self.deliver_due()
        self.storage.prune_delivered()

    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        LOGGER.info("Instagram worker started targets=%s", ",".join(self.targets))
        while not self.stop_event.is_set():
            due = self.storage.due_targets(time.time())
            for username in due:
                if self.stop_event.is_set():
                    break
                try:
                    self.check_target(self.targets[username])
                except Exception:
                    LOGGER.exception(
                        "Instagram target check failed username=%s", username
                    )
                self.deliver_due()
            self.deliver_due()
            next_run = self.storage.next_target_time()
            sleep_for = (
                60.0
                if next_run is None
                else max(5.0, min(60.0, next_run - time.time()))
            )
            self.stop_event.wait(sleep_for)
        LOGGER.info("Instagram worker stopped")
