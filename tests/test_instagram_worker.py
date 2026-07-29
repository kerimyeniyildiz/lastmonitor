from __future__ import annotations

import tempfile
import unittest
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from instagram_worker.client import build_client
from instagram_worker.errors import is_login_required, requires_manual_attention
from instagram_worker.models import normalize_item
from instagram_worker.service import InstagramService
from instagram_worker.storage import Storage


def media(**values):
    defaults = {
        "pk": "123_456",
        "code": "ABC123",
        "media_type": 1,
        "product_type": "",
        "caption_text": "Kırklareli gündemi",
        "thumbnail_url": "https://cdn.example/cover.jpg",
        "taken_at": datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
        "resources": [],
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


class InstagramNormalizationTests(unittest.TestCase):
    def test_reel_uses_cover_and_reel_link(self) -> None:
        event = normalize_item(
            media(media_type=2, product_type="clips"),
            "rozmedyahaber",
            "feed",
        )
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.content_type, "reel")
        self.assertEqual(event.preview_url, "https://cdn.example/cover.jpg")
        self.assertEqual(event.link, "https://www.instagram.com/reel/ABC123/")

    def test_story_video_is_still_a_cover_only_event(self) -> None:
        event = normalize_item(
            media(media_type=2, code=""),
            "kirklareli_gundem",
            "story",
        )
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.content_type, "story")
        self.assertEqual(event.preview_url, "https://cdn.example/cover.jpg")
        self.assertEqual(
            event.link,
            "https://www.instagram.com/stories/kirklareli_gundem/123/",
        )

    def test_regular_feed_video_keeps_post_link_and_cover(self) -> None:
        event = normalize_item(
            media(media_type=2, product_type="feed"),
            "rozmedyahaber",
            "feed",
        )
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.content_type, "post")
        self.assertEqual(event.preview_url, "https://cdn.example/cover.jpg")
        self.assertEqual(event.link, "https://www.instagram.com/p/ABC123/")

    def test_carousel_uses_only_first_resource_preview(self) -> None:
        resources = [
            SimpleNamespace(thumbnail_url="https://cdn.example/first.jpg"),
            SimpleNamespace(thumbnail_url="https://cdn.example/second.jpg"),
        ]
        event = normalize_item(
            media(media_type=8, resources=resources),
            "rozmedyahaber",
            "feed",
        )
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.content_type, "carousel")
        self.assertEqual(event.preview_url, "https://cdn.example/first.jpg")


class InstagramStorageTests(unittest.TestCase):
    def test_first_group_is_seeded_and_later_items_are_pending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "state.db")
            first = normalize_item(media(pk="1_1", code="ONE"), "target", "feed")
            second = normalize_item(media(pk="2_2", code="TWO"), "target", "feed")
            assert first is not None and second is not None

            new_count, seeded_count = storage.add_group(
                "target", "feed", [first], send_existing=False
            )
            self.assertEqual((new_count, seeded_count), (0, 1))
            self.assertEqual(storage.pending_count(), 0)

            new_count, seeded_count = storage.add_group(
                "target", "feed", [first, second], send_existing=False
            )
            self.assertEqual((new_count, seeded_count), (1, 0))
            self.assertEqual(storage.pending_count(), 1)
            storage.close()

    def test_empty_first_story_check_still_creates_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "state.db")
            self.assertEqual(storage.add_group("target", "story", [], False), (0, 0))
            story = normalize_item(media(pk="3_3", code=""), "target", "story")
            assert story is not None
            self.assertEqual(
                storage.add_group("target", "story", [story], False),
                (1, 0),
            )
            storage.close()


class InstagramScheduleTests(unittest.TestCase):
    def test_random_interval_stays_between_fifteen_and_fifty_minutes(self) -> None:
        service = object.__new__(InstagramService)
        service.config = SimpleNamespace(interval_jitter_seconds=1050)
        target = SimpleNamespace(interval_seconds=1950)

        with patch("instagram_worker.service.random.randint", return_value=-1050):
            self.assertEqual(service._next_interval(target), 900)
        with patch("instagram_worker.service.random.randint", return_value=1050):
            self.assertEqual(service._next_interval(target), 3000)


class LoginRequired(Exception):
    pass


class ClientGraphqlError(Exception):
    pass


def masked_login_error() -> ClientGraphqlError:
    try:
        raise LoginRequired("login_required")
    except LoginRequired:
        try:
            raise RuntimeError("fallback failed")
        except RuntimeError:
            try:
                raise ClientGraphqlError("invalid request")
            except ClientGraphqlError as error:
                return error


class FakeInstagramClient:
    def __init__(self) -> None:
        self.delay_range = []
        self.relogin_calls = 0
        self.dump_calls = 0

    def set_country(self, _value):
        pass

    def set_country_code(self, _value):
        pass

    def set_locale(self, _value):
        pass

    def set_timezone_offset(self, _value):
        pass

    def load_settings(self, _path):
        pass

    def login(self, _username, _password, relogin=False, verification_code=""):
        del verification_code
        if relogin:
            self.relogin_calls += 1

    def account_info(self):
        if self.relogin_calls == 0:
            raise LoginRequired("login_required")
        return SimpleNamespace(pk="1")

    def dump_settings(self, _path):
        self.dump_calls += 1


class InstagramSessionTests(unittest.TestCase):
    def config(self, directory: str):
        session_file = Path(directory) / "session.json"
        session_file.write_text("{}", encoding="utf-8")
        return SimpleNamespace(
            session_file=session_file,
            username="monitor",
            password="secret",
        )

    def fake_module(self, client: FakeInstagramClient) -> AbstractContextManager:
        return patch.dict(
            "sys.modules",
            {"instagrapi": SimpleNamespace(Client=lambda: client)},
        )

    def test_background_start_rejects_an_expired_saved_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeInstagramClient()
            with self.fake_module(client):
                with self.assertRaises(LoginRequired):
                    build_client(self.config(directory), interactive=False)
            self.assertEqual(client.relogin_calls, 0)
            self.assertEqual(client.dump_calls, 0)

    def test_manual_login_refreshes_an_expired_saved_session_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeInstagramClient()
            with self.fake_module(client):
                result = build_client(self.config(directory), interactive=True)
            self.assertIs(result, client)
            self.assertEqual(client.relogin_calls, 1)
            self.assertEqual(client.dump_calls, 1)

    def test_masked_login_error_still_requires_manual_attention(self) -> None:
        error = masked_login_error()
        self.assertTrue(is_login_required(error))
        self.assertTrue(requires_manual_attention(error))


if __name__ == "__main__":
    unittest.main()
