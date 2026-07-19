import os
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from api import get_token_header, list_tweets


class ApiAuthTests(unittest.TestCase):
    def test_token_required_by_default_when_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                get_token_header(None)

        self.assertEqual(ctx.exception.status_code, 500)

    def test_auth_can_be_disabled_for_local_development(self) -> None:
        with patch.dict(os.environ, {"API_REQUIRE_TOKEN": "false"}, clear=True):
            get_token_header(None)

    def test_rejects_missing_bearer_header_when_token_is_set(self) -> None:
        with patch.dict(os.environ, {"API_TOKEN": "secret"}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                get_token_header(None)

        self.assertEqual(ctx.exception.status_code, 401)

    def test_accepts_matching_bearer_token(self) -> None:
        with patch.dict(os.environ, {"API_TOKEN": "secret"}, clear=True):
            get_token_header("Bearer secret")


class TweetApiTests(unittest.TestCase):
    def test_filtered_status_is_applied_to_tweet_query(self) -> None:
        db = Mock()
        db.fetch_all.return_value = []

        list_tweets(
            q=None,
            search=None,
            status="filtered",
            limit=25,
            offset=0,
            db=db,
            _=None,
        )

        sql, params = db.fetch_all.call_args.args
        self.assertIn("delivery_status = %s", sql)
        self.assertIn("filter_reasons", sql)
        self.assertEqual(params, ("filtered", 25, 0))

    def test_all_status_does_not_filter_tweet_query(self) -> None:
        db = Mock()
        db.fetch_all.return_value = []

        list_tweets(
            q=None,
            search=None,
            status="all",
            limit=25,
            offset=0,
            db=db,
            _=None,
        )

        sql, params = db.fetch_all.call_args.args
        self.assertNotIn("delivery_status = %s", sql)
        self.assertEqual(params, (25, 0))


if __name__ == "__main__":
    unittest.main()
