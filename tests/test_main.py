import os
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import requests
from main import (
    Config,
    ISTANBUL_TZ,
    build_configured_sitemap_urls,
    evaluate_tweet_filter,
    filter_news_entries,
    normalize_tweet,
    parse_datetime,
    parse_duration_seconds,
    parse_instagram_targets,
    parse_query_schedule,
    parse_sitemap_xml,
    send_telegram_message,
    should_drop_filtered_tweet,
)


class ConfigParsingTests(unittest.TestCase):
    def test_parse_duration_seconds_supports_units(self) -> None:
        self.assertEqual(parse_duration_seconds("5m", 60), 300)
        self.assertEqual(parse_duration_seconds("2h", 60), 7200)
        self.assertEqual(parse_duration_seconds("45s", 60), 45)
        self.assertEqual(parse_duration_seconds("bad", 60), 60)

    def test_parse_query_schedule_uses_per_query_intervals(self) -> None:
        schedule = parse_query_schedule("Kırklareli|5m,Lüleburgaz:10m", "", 60)

        self.assertEqual([item.query for item in schedule], ["Kırklareli", "Lüleburgaz"])
        self.assertEqual([item.interval_seconds for item in schedule], [300, 600])

    def test_parse_query_schedule_replaces_old_minister_account(self) -> None:
        schedule = parse_query_schedule("from:Aliyerlikaya|10m", "", 60)

        self.assertEqual(schedule[0].query, "from:mustafaciftcitr")

    def test_parse_instagram_targets_supports_per_account_intervals(self) -> None:
        targets = parse_instagram_targets(
            "@rozmedyahaber|30m,kirklareli_gundem:1h", 1800
        )

        self.assertEqual(
            [(item.username, item.interval_seconds) for item in targets],
            [("rozmedyahaber", 1800), ("kirklareli_gundem", 3600)],
        )


class DateParsingTests(unittest.TestCase):
    def test_parse_datetime_keeps_timezone_when_present(self) -> None:
        parsed = parse_datetime("2026-06-27T12:30:00+03:00")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.utcoffset().total_seconds(), 10800)

    def test_parse_datetime_assumes_istanbul_for_naive_local_format(self) -> None:
        parsed = parse_datetime("2026-06-27 12:30:00")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.tzinfo, ISTANBUL_TZ)

    def test_parse_datetime_accepts_datetime_objects(self) -> None:
        parsed = parse_datetime(datetime(2026, 6, 27, 12, 30, 0))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.tzinfo, ISTANBUL_TZ)


class TweetParsingTests(unittest.TestCase):
    def test_normalize_tweet_builds_link_and_preserves_datetime(self) -> None:
        tweet = normalize_tweet(
            {
                "id": "123",
                "username": "kirklareli",
                "name": "Kırklareli",
                "text": "Kırklareli gündemi",
                "created_at": "2026-06-27T12:30:00+03:00",
            }
        )

        self.assertIsNotNone(tweet)
        self.assertEqual(tweet["link"], "https://x.com/kirklareli/status/123")
        self.assertEqual(tweet["created_at"], "2026-06-27 12:30:00")
        self.assertIsNotNone(tweet["created_at_dt"])

    def test_tweet_filter_matches_blocked_terms_in_mentions(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Lüleburgaz",
            {
                "user_handle": "normal_user",
                "user_name": "Normal User",
                "text": "ayrılmalıyız #lüleburgaz @乂esCort乂 https://t.co/x",
                "link": "https://x.com/normal_user/status/1",
            },
        )

        self.assertEqual(reasons, ["blocked_term:escort"])

    def test_tweet_filter_matches_blocked_terms_in_obfuscated_text(self) -> None:
        with patch.dict(
            os.environ,
            {"BLOCKED_TWEET_TERMS": "e s c o r t"},
            clear=True,
        ):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Kırklareli",
            {
                "user_handle": "random",
                "user_name": "Random",
                "text": "kirklareli escort ilanı",
                "link": "https://x.com/random/status/1",
            },
        )

        self.assertEqual(reasons, ["blocked_term:e s c o r t"])

    def test_tweet_filter_watches_ad_terms_without_marking_them_droppable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Lüleburgaz",
            {
                "user_handle": "random",
                "user_name": "Random",
                "text": "#lüleburgaz ödeme elden https://t.co/x",
                "link": "https://x.com/random/status/1",
            },
        )

        self.assertIn("watch_term:ödeme elden", reasons)
        self.assertFalse(should_drop_filtered_tweet(reasons))

    def test_tweet_filter_drops_location_hashtag_link_only_posts(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Lüleburgaz",
            {
                "user_handle": "CoxerQ37286",
                "user_name": "Coxer QUXEFET",
                "text": "👍 #kapaklı #lüleburgaz https://t.co/aMqpzw0pxj",
                "link": "https://x.com/CoxerQ37286/status/1",
            },
        )

        self.assertIn("watch_pattern:location_hashtags_link_only", reasons)
        self.assertTrue(should_drop_filtered_tweet(reasons))

    def test_tweet_filter_watches_phone_numbers(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Lüleburgaz",
            {
                "user_handle": "random",
                "user_name": "Random",
                "text": "#lüleburgaz 0530 011 29 40 https://t.co/x",
                "link": "https://x.com/random/status/1",
            },
        )

        self.assertIn("watch_pattern:phone_number", reasons)
        self.assertFalse(should_drop_filtered_tweet(reasons))

    def test_tweet_filter_blocked_terms_are_droppable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Lüleburgaz",
            {
                "user_handle": "random",
                "user_name": "Random",
                "text": "lüleburgaz escort",
                "link": "https://x.com/random/status/1",
            },
        )

        self.assertTrue(should_drop_filtered_tweet(reasons))

    def test_tweet_filter_bypasses_official_source_queries(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "from:mustafaciftcitr",
            {
                "user_handle": "mustafaciftcitr",
                "user_name": "Mustafa Çiftçi",
                "text": "escort operasyonu hakkında açıklama",
                "link": "https://x.com/mustafaciftcitr/status/1",
            },
        )

        self.assertEqual(reasons, [])

    def test_tweet_filter_can_be_turned_off(self) -> None:
        with patch.dict(os.environ, {"TWEET_FILTER_MODE": "off"}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Lüleburgaz",
            {
                "user_handle": "random",
                "user_name": "Random",
                "text": "lüleburgaz escort",
                "link": "https://x.com/random/status/1",
            },
        )

        self.assertEqual(reasons, [])


class SitemapParsingTests(unittest.TestCase):
    def test_build_configured_sitemap_urls_adds_current_and_previous_month(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        urls = build_configured_sitemap_urls(
            config, datetime(2026, 6, 27, 12, 0, tzinfo=ISTANBUL_TZ)
        )

        self.assertEqual(
            urls,
            [
                "https://www.onadimgazetesi.com/sitemap.xml",
                "https://www.alternatifgazetesi.com/sitemap/sitemap-2026-06.xml",
                "https://www.alternatifgazetesi.com/sitemap/sitemap-2026-05.xml",
            ],
        )

    def test_build_configured_sitemap_urls_supports_custom_templates(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SITEMAP_URLS": "https://example.com/sitemap.xml",
                "SITEMAP_MONTHLY_TEMPLATES": "https://example.com/{YYYY}/{M}.xml",
                "SITEMAP_MONTH_LOOKBACK": "0",
            },
            clear=True,
        ):
            config = Config.from_env()

        urls = build_configured_sitemap_urls(
            config, datetime(2026, 6, 27, 12, 0, tzinfo=ISTANBUL_TZ)
        )

        self.assertEqual(
            urls,
            [
                "https://example.com/sitemap.xml",
                "https://example.com/2026/6.xml",
            ],
        )

    def test_parse_sitemap_xml_extracts_url_entries(self) -> None:
        _, entries = parse_sitemap_xml(
            """<?xml version="1.0"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url>
                <loc>https://example.com/haber</loc>
                <lastmod>2026-06-27T12:30:00+03:00</lastmod>
              </url>
            </urlset>
            """
        )

        self.assertEqual(entries, [("https://example.com/haber", "2026-06-27T12:30:00+03:00")])

    def test_filter_news_entries_skips_images_and_keeps_datetime(self) -> None:
        entries = filter_news_entries(
            [
                ("https://example.com/haber", "2026-06-27T12:30:00+03:00"),
                ("https://example.com/image.jpg", "2026-06-27T12:30:00+03:00"),
            ],
            max_age_hours=0,
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["link"], "https://example.com/haber")
        self.assertIsNotNone(entries[0]["created_at_dt"])


class TelegramTests(unittest.TestCase):
    def test_send_telegram_message_returns_true_on_success(self) -> None:
        session = Mock()
        session.post.return_value = Mock(ok=True)

        result = send_telegram_message(session, "token", "chat", "message")

        self.assertTrue(result)

    def test_send_telegram_message_returns_false_on_http_failure(self) -> None:
        session = Mock()
        session.post.return_value = Mock(ok=False, status_code=500, text="error")

        result = send_telegram_message(session, "token", "chat", "message")

        self.assertFalse(result)

    def test_send_telegram_message_returns_false_on_request_error(self) -> None:
        session = Mock()
        session.post.side_effect = requests.RequestException("network")

        result = send_telegram_message(session, "token", "chat", "message")

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
