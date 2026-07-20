import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import requests
from main import (
    Config,
    DBClient,
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
    tweet_loop,
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

    def test_tweet_filter_matches_stylized_unicode_blocked_term(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Kırklareli",
            {
                "user_handle": "Aaaaadcnc",
                "user_name": "Random",
                "text": "#kırklareli 𝕰𝕾𝕮𝕺𝕽𝕿 serbestsin https://t.co/x",
                "link": "https://x.com/Aaaaadcnc/status/1",
            },
        )

        self.assertIn("blocked_term:escort", reasons)
        self.assertTrue(should_drop_filtered_tweet(reasons))

    def test_tweet_filter_matches_kirklareli_ad_terms_case_insensitive(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Kırklareli",
            {
                "user_handle": "random",
                "user_name": "Random",
                "text": "kırklarelibaYan ilanı",
                "link": "https://x.com/random/status/1",
            },
        )

        self.assertIn("blocked_term:kırklarelibayan", reasons)
        self.assertTrue(should_drop_filtered_tweet(reasons))

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

        self.assertIn("block_pattern:location_hashtags_link_only", reasons)
        self.assertTrue(should_drop_filtered_tweet(reasons))

    def test_tweet_filter_drops_one_location_hashtag_plus_empty_hashtag_link(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Kırklareli",
            {
                "user_handle": "JanaNunez5k",
                "user_name": "Jana Nunez",
                "text": "📙 #kırklareli #kepez https://t.co/BAkEppO8Xk",
                "link": "https://x.com/JanaNunez5k/status/1",
            },
        )

        self.assertIn("block_pattern:location_hashtags_link_only", reasons)
        self.assertTrue(should_drop_filtered_tweet(reasons))

    def test_tweet_filter_drops_location_word_soup_links(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Lüleburgaz",
            {
                "user_handle": "MelissaEll9o",
                "user_name": "Melissa Ellis",
                "text": "#tekirdAğ lüleburgaz edirne görundu  saçlarımdan https://t.co/UZj01WG5J1",
                "link": "https://x.com/MelissaEll9o/status/1",
            },
        )

        self.assertIn("block_pattern:location_word_soup_link", reasons)
        self.assertTrue(should_drop_filtered_tweet(reasons))

    def test_tweet_filter_drops_suspicious_generated_handle_location_links(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Kırklareli",
            {
                "user_handle": "ParkerJeff61162",
                "user_name": "Jefferson Parker",
                "text": "ikizkenar #edirNe üçgen şahsiyat kapıkule havsa hayvanca #kırklareli 🪁 sermayecilik https://t.co/CpewGGrLuw",
                "link": "https://x.com/ParkerJeff61162/status/1",
            },
        )

        self.assertIn("block_pattern:suspicious_location_link", reasons)
        self.assertTrue(should_drop_filtered_tweet(reasons))

    def test_tweet_filter_drops_luleburgaz_short_link_campaign(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        samples = [
            ("Richard78459041", "Richard", "#lüleburgaz Verilerin dolup"),
            ("Olga1071492", "Olga", "ödemeli lüleburgaz ön öncelemek #çorlu"),
            ("Lorraine1645970", "Lorraine", "#lüleburgaz Her bir"),
            ("Mary141509", "Mary", "#lüleburgaz gördüm karanlık"),
            ("Ami1960541", "Ami", "#lüleburgaz etrafımızda seni"),
            ("Jason4858240311", "Jason", "benim #lüleburgaz yüzden"),
            ("Jason8883368957", "Jason", "#lüleburgaz için bir"),
            ("Mildred1066551", "Mildred", "#lüleburgaz yazıldığı sen"),
            ("Henry094129372", "Henry", "#lüleburgaz inanışmışsın Gözlerin"),
            ("Joan70019329190", "Joan", "#lüleburgaz uygun ve"),
            ("Jonas448468", "Jonas", "Gözlerin olacak #lüleburgaz"),
        ]
        reason = "block_pattern:luleburgaz_short_link_campaign"

        for index, (handle, name, text) in enumerate(samples):
            with self.subTest(handle=handle):
                reasons = evaluate_tweet_filter(
                    config,
                    "Lüleburgaz",
                    {
                        "user_handle": handle,
                        "user_name": name,
                        "text": f"{text} https://t.co/{index}",
                        "link": f"https://x.com/{handle}/status/{index}",
                    },
                )

                self.assertIn(reason, reasons)
                self.assertTrue(should_drop_filtered_tweet(reasons))

    def test_tweet_filter_drops_generated_location_link_campaign(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        samples = [
            (
                "Daryl1057822",
                "Daryl",
                "🙄 et sineği #kırklareli hayrat https://t.co/a",
            ),
            (
                "Sadie131026",
                "Sadie",
                "güzel ☹ #kırklareli yeğlik https://t.co/b",
            ),
            (
                "Dolores867030",
                "Dolores",
                "ön yönetebilmek ☹ #kırklareli gün https://t.co/c",
            ),
        ]

        for index, (handle, name, text) in enumerate(samples):
            with self.subTest(handle=handle):
                reasons = evaluate_tweet_filter(
                    config,
                    "Kırklareli",
                    {
                        "user_handle": handle,
                        "user_name": name,
                        "text": text,
                        "link": f"https://x.com/{handle}/status/{index}",
                    },
                )

                self.assertIn(
                    "block_pattern:generated_location_link_campaign", reasons
                )
                self.assertTrue(should_drop_filtered_tweet(reasons))

    def test_tweet_filter_keeps_alitek(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Lüleburgaz",
            {
                "user_handle": "Alitek3959",
                "user_name": "Ali Tek",
                "text": "Lüleburgaz şu an yeri olan",
                "link": "https://x.com/Alitek3959/status/1",
            },
        )

        self.assertFalse(should_drop_filtered_tweet(reasons))

    def test_tweet_filter_drops_luleburgaz_ad_profile_location_dump(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Lüleburgaz",
            {
                "user_handle": "DonaldBaco49691",
                "user_name": "GÜZEL BAYAN",
                "text": (
                    "Huzur en büyük servettir çorlu,çerkezköy,kapaklı,"
                    "tekirdağ,lüleburgaz,şarkköy,malkara,hayrabolu,saray,"
                    "ergene,muratlı,marmaraereğlisi,bayan https://t.co/x"
                ),
                "link": "https://x.com/DonaldBaco49691/status/1",
            },
        )

        self.assertIn("block_pattern:luleburgaz_ad_profile", reasons)
        self.assertIn("block_pattern:luleburgaz_location_dump", reasons)
        self.assertTrue(should_drop_filtered_tweet(reasons))

    def test_tweet_filter_keeps_normal_luleburgaz_posts(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        samples = [
            {
                "user_handle": "Ahmet1987",
                "user_name": "Ahmet",
                "text": "#lüleburgaz deprem oldu https://t.co/x",
            },
            {
                "user_handle": "Ahmet12345",
                "user_name": "Ahmet",
                "text": "#lüleburgaz deprem oldu https://t.co/x",
            },
            {
                "user_handle": "Ahmet123456",
                "user_name": "Ahmet",
                "text": (
                    "#lüleburgaz belediyesi yaz konserleri programını "
                    "bu akşam kamuoyuyla paylaştı https://t.co/x"
                ),
            },
            {
                "user_handle": "Trakya_Duyuru",
                "user_name": "Trakya Duyuru",
                "text": (
                    "Çorlu, Çerkezköy, Kapaklı, Tekirdağ ve Lüleburgaz "
                    "ilçelerinde sağanak yağış bekleniyor https://t.co/x"
                ),
            },
        ]

        for index, tweet in enumerate(samples):
            with self.subTest(index=index):
                tweet["link"] = f"https://x.com/test/status/{index}"
                reasons = evaluate_tweet_filter(config, "Lüleburgaz", tweet)

                self.assertFalse(should_drop_filtered_tweet(reasons))

    def test_luleburgaz_campaign_rule_does_not_apply_to_other_queries(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Babaeski",
            {
                "user_handle": "sinan1050001",
                "user_name": "sinan",
                "text": "Hayırlı akşamlar BABAESKİ DEN https://t.co/x",
                "link": "https://x.com/sinan1050001/status/1",
            },
        )

        self.assertFalse(should_drop_filtered_tweet(reasons))

    def test_tweet_filter_keeps_natural_reply_without_link(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Kırklareli",
            {
                "user_handle": "rtgunduz",
                "user_name": "Ramazan Gündüz",
                "text": "@arsmaxx @cuneytozdemir Trakya şivesinde gerekli gereksiz herkese Ağa derler. Konum Kırklareli",
                "link": "https://x.com/rtgunduz/status/1",
            },
        )

        self.assertEqual(reasons, [])

    def test_tweet_filter_keeps_long_location_announcement_links(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()

        reasons = evaluate_tweet_filter(
            config,
            "Babaeski",
            {
                "user_handle": "tmotobblidas",
                "user_name": "TMO-TOBB LİDAŞ",
                "text": "🔴Ülkemizin ilk lisanslı depo şirketi; TMO-TOBB Tarım Ürünleri Lis. Dep. San. ve Tic. A.Ş. #Babaeski, #Çorum, #Hayrabolu, #Keskin şubeleri ile hizmet veriyor https://t.co/x",
                "link": "https://x.com/tmotobblidas/status/1",
            },
        )

        self.assertFalse(should_drop_filtered_tweet(reasons))

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

    def test_tweet_filter_requires_configured_prefix_for_account_query(self) -> None:
        with patch.dict(
            os.environ,
            {"TWEET_REQUIRED_PREFIXES": "from:bpthaber=>SON DAKİKA"},
            clear=True,
        ):
            config = Config.from_env()

        matching = {
            "user_handle": "bpthaber",
            "user_name": "BPT",
            "text": "  son dakika | Örnek gelişme",
            "link": "https://x.com/bpthaber/status/1",
        }
        unrelated = {
            **matching,
            "text": "Günün öne çıkan haberleri",
            "link": "https://x.com/bpthaber/status/2",
        }

        self.assertEqual(evaluate_tweet_filter(config, "from:bpthaber", matching), [])
        reasons = evaluate_tweet_filter(config, "from:bpthaber", unrelated)
        self.assertIn("required_prefix_missing", reasons)
        self.assertTrue(should_drop_filtered_tweet(reasons))
        self.assertEqual(
            evaluate_tweet_filter(config, "from:mustafaciftcitr", unrelated), []
        )

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


class DBClientTests(unittest.TestCase):
    def test_reconnects_and_flushes_tweets_queued_during_startup_outage(self) -> None:
        clock = {"value": 100.0}
        connection = MagicMock()
        connection.closed = 0
        cursor = connection.cursor.return_value.__enter__.return_value
        first_tweet = {
            "id": "1",
            "user_handle": "spam_account",
            "user_name": "Spam Account",
            "text": "kırklarelibayan",
            "link": "https://x.com/spam_account/status/1",
            "created_at": "2026-07-19T12:00:00+03:00",
        }
        second_tweet = {
            "id": "2",
            "user_handle": "news_account",
            "user_name": "News Account",
            "text": "Kırklareli haberi",
            "link": "https://x.com/news_account/status/2",
            "created_at": "2026-07-19T12:01:00+03:00",
        }

        with patch("main.time.monotonic", side_effect=lambda: clock["value"]):
            with patch(
                "main.psycopg2.connect",
                side_effect=[Exception("temporary dns failure"), connection],
            ) as connect:
                db = DBClient("postgresql://db", retry_interval_seconds=30)
                queued = db.insert_tweet(
                    first_tweet,
                    "Kırklareli",
                    delivery_status="filtered",
                    filter_reasons=["blocked_term:kırklarelibayan"],
                )
                clock["value"] = 131.0
                inserted = db.insert_tweet(second_tweet, "Kırklareli")

        self.assertFalse(queued)
        self.assertTrue(inserted)
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(db.pending_tweets, {})
        insert_params = [
            call.args[1]
            for call in cursor.execute.call_args_list
            if "INSERT INTO tweets" in call.args[0]
        ]
        self.assertEqual(len(insert_params), 2)
        self.assertEqual(insert_params[0][7], "filtered")
        self.assertEqual(
            insert_params[0][8], ["blocked_term:kırklarelibayan"]
        )
        self.assertEqual(insert_params[1][7], "sent")

    def test_missing_db_url_disables_persistence_without_connecting(self) -> None:
        with patch("main.psycopg2.connect") as connect:
            db = DBClient("")

        self.assertFalse(db.enabled)
        self.assertFalse(db.insert_tweet({}, "Kırklareli"))
        connect.assert_not_called()


class TweetLoopTests(unittest.TestCase):
    def test_dropped_tweet_is_persisted_without_telegram_delivery(self) -> None:
        with patch.dict(
            os.environ, {"QUERY_SCHEDULE": "Kırklareli|1s"}, clear=True
        ):
            config = Config.from_env()
        tweet = {
            "id": "1",
            "user_handle": "spam_account",
            "user_name": "Spam Account",
            "text": "kırklarelibayan ilanı",
            "link": "https://x.com/spam_account/status/1",
            "created_at": "2026-07-19T12:00:00+03:00",
        }
        store = Mock()
        db = Mock()
        stop_event = Mock()
        stop_event.is_set.side_effect = [False, True]

        with patch("main.fetch_latest_tweets", return_value=[tweet]):
            with patch("main.send_telegram_message") as send:
                tweet_loop(
                    config,
                    Mock(),
                    store,
                    db,
                    set(),
                    MagicMock(),
                    stop_event,
                )

        send.assert_not_called()
        db.insert_tweet.assert_called_once_with(
            tweet,
            "Kırklareli",
            delivery_status="filtered",
            filter_reasons=["blocked_term:kırklarelibayan"],
        )
        store.save_set.assert_called_once()


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
