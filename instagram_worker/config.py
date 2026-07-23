from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


DEFAULT_CONFIG_PATH = Path("~/.config/lastmonitor-instagram/config.env").expanduser()


@dataclass(frozen=True)
class Target:
    username: str
    interval_seconds: int


@dataclass(frozen=True)
class Config:
    username: str
    password: str
    targets: tuple[Target, ...]
    interval_jitter_seconds: int
    fetch_limit: int
    send_existing: bool
    ingest_url: str
    ingest_token: str
    runtime_dir: Path
    session_file: Path
    database_file: Path
    media_dir: Path
    log_file: Path
    config_file: Path


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _read_bool(value: str | None, fallback: bool = False) -> bool:
    if value is None:
        return fallback
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int(
    values: Mapping[str, str],
    key: str,
    fallback: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(values.get(key, str(fallback)))
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return parsed


def _parse_targets(raw: str) -> tuple[Target, ...]:
    targets: list[Target] = []
    seen: set[str] = set()
    for definition in raw.split(","):
        definition = definition.strip()
        if not definition:
            continue
        username, separator, interval_text = definition.partition("|")
        username = username.strip().lstrip("@").lower()
        if not username or not all(
            character.isalnum() or character in "._" for character in username
        ):
            raise ValueError(f"Invalid Instagram target: {username!r}")
        if username in seen:
            raise ValueError(f"Duplicate Instagram target: {username}")
        try:
            interval = int(interval_text) if separator else 1800
        except ValueError as exc:
            raise ValueError(f"Invalid interval for {username}") from exc
        if interval < 600:
            raise ValueError(f"Interval for {username} must be at least 600 seconds")
        targets.append(Target(username=username, interval_seconds=interval))
        seen.add(username)
    if not targets:
        raise ValueError("IG_TARGETS must contain at least one account")
    return tuple(targets)


def _assert_private_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {path}. Run `python -m instagram_worker configure`."
        )
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise PermissionError(f"Configuration file must use mode 600: {path}")


def keychain_get(service: str, account: str) -> str:
    result = subprocess.run(
        [
            "/usr/bin/security",
            "find-generic-password",
            "-s",
            service,
            "-a",
            account,
            "-w",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def keychain_set(service: str, account: str, secret: str) -> None:
    if not secret:
        raise ValueError("Secret cannot be empty")
    subprocess.run(
        [
            "/usr/bin/security",
            "add-generic-password",
            "-U",
            "-s",
            service,
            "-a",
            account,
            "-w",
            secret,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def load_config(path: Path | None = None, require_secrets: bool = True) -> Config:
    config_path = (
        path
        or Path(os.environ.get("LASTMONITOR_INSTAGRAM_CONFIG", DEFAULT_CONFIG_PATH))
    ).expanduser()
    _assert_private_file(config_path)
    values = _parse_env_file(config_path)
    values.update(
        {
            key: value
            for key, value in os.environ.items()
            if key.startswith(("IG_", "CF_"))
        }
    )

    runtime_dir = Path(
        values.get("IG_RUNTIME_DIR", "~/.local/share/lastmonitor-instagram")
    ).expanduser()
    username = values.get("IG_USERNAME", "").strip()
    password = values.get("IG_PASSWORD", "") or (
        keychain_get("lastmonitor-instagram-password", username) if username else ""
    )
    ingest_url = values.get(
        "CF_INGEST_URL",
        "https://lastmonitor-cloudflare.kerim-yeniyildiz.workers.dev/api/instagram",
    ).rstrip("/")
    ingest_token = values.get("CF_INGEST_TOKEN", "") or keychain_get(
        "lastmonitor-instagram-ingest",
        "cloudflare",
    )
    if require_secrets:
        missing = [
            key
            for key, value in (
                ("IG_USERNAME", username),
                ("IG_PASSWORD", password),
                ("CF_INGEST_TOKEN", ingest_token),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")
    if not ingest_url.startswith("https://"):
        raise ValueError("CF_INGEST_URL must use HTTPS")

    return Config(
        username=username,
        password=password,
        targets=_parse_targets(
            values.get("IG_TARGETS", "rozmedyahaber|1800,kirklareli_gundem|1800")
        ),
        interval_jitter_seconds=_read_int(
            values, "IG_INTERVAL_JITTER_SECONDS", 300, 0, 900
        ),
        fetch_limit=_read_int(values, "IG_FETCH_LIMIT", 12, 5, 30),
        send_existing=_read_bool(values.get("IG_SEND_EXISTING"), False),
        ingest_url=ingest_url,
        ingest_token=ingest_token,
        runtime_dir=runtime_dir,
        session_file=runtime_dir / "session.json",
        database_file=runtime_dir / "state.db",
        media_dir=runtime_dir / "media",
        log_file=runtime_dir / "worker.log",
        config_file=config_path,
    )
