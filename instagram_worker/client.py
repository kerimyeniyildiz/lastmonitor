from __future__ import annotations

import getpass
import logging
import os
from pathlib import Path
from typing import Callable

from .config import Config

LOGGER = logging.getLogger(__name__)


def _challenge_code_handler(_username: str, choice: object) -> str:
    channel = "e-posta" if str(choice).lower().endswith("email") else "SMS"
    return getpass.getpass(f"Instagram {channel} doğrulama kodu: ").strip()


def build_client(
    config: Config,
    interactive: bool = False,
    verification_code: str = "",
):
    try:
        from instagrapi import Client
    except ImportError as exc:
        raise RuntimeError(
            "instagrapi is not installed; install requirements-instagram.txt"
        ) from exc

    client = Client()
    client.delay_range = [2, 5]
    client.set_country("TR")
    client.set_country_code(90)
    client.set_locale("tr_TR")
    client.set_timezone_offset(3 * 60 * 60)
    if interactive:
        client.challenge_code_handler = _challenge_code_handler

    if config.session_file.exists():
        client.load_settings(config.session_file)
        LOGGER.info("Saved Instagram session loaded")
    client.login(
        config.username,
        config.password,
        verification_code=verification_code,
    )
    config.session_file.parent.mkdir(parents=True, exist_ok=True)
    client.dump_settings(config.session_file)
    os.chmod(config.session_file, 0o600)
    return client


def login_interactively(
    config: Config,
    verification_code_reader: Callable[[], str] | None = None,
):
    try:
        return build_client(config, interactive=True)
    except Exception as exc:
        try:
            from instagrapi.exceptions import TwoFactorRequired
        except ImportError:
            raise
        if not isinstance(exc, TwoFactorRequired):
            raise
        reader = verification_code_reader or (
            lambda: getpass.getpass("Instagram Authenticator kodu: ").strip()
        )
        code = reader()
        if not code:
            raise RuntimeError("Two-factor verification code is required") from exc
        return build_client(config, interactive=True, verification_code=code)


def session_exists(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0
