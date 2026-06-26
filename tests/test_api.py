import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from api import get_token_header


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


if __name__ == "__main__":
    unittest.main()
