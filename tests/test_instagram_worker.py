from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from instagram_worker.models import normalize_item
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


if __name__ == "__main__":
    unittest.main()
