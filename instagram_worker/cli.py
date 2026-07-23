from __future__ import annotations

import argparse
import getpass
import logging
import logging.handlers
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path

from .client import login_interactively, session_exists
from .config import (
    DEFAULT_CONFIG_PATH,
    Config,
    keychain_get,
    keychain_set,
    load_config,
)
from .service import InstagramService

LAUNCHD_LABEL = "com.kerimyeniyildiz.lastmonitor-instagram"


def configure_logging(config: Config) -> None:
    config.runtime_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler = logging.handlers.RotatingFileHandler(
        config.log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[handler, console])
    logging.getLogger("instagrapi").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _prompt(label: str, fallback: str = "") -> str:
    suffix = f" [{fallback}]" if fallback else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or fallback


def configure(path: Path) -> None:
    path = path.expanduser()
    username = _prompt("Instagram kullanıcı adı")
    password = getpass.getpass("Instagram şifresi: ")
    targets = _prompt(
        "Hedefler (hesap|saniye,...)",
        "rozmedyahaber|1950,kirklareli_gundem|1950",
    )
    endpoint = _prompt(
        "Cloudflare ingest adresi",
        "https://lastmonitor-cloudflare.kerim-yeniyildiz.workers.dev/api/instagram",
    )
    token = keychain_get("lastmonitor-instagram-ingest", "cloudflare")
    if not token:
        token = getpass.getpass("Cloudflare Instagram ingest tokenı: ")
    runtime_dir = _prompt(
        "Runtime klasörü",
        "~/.local/share/lastmonitor-instagram",
    )
    if not all((username, password, token)):
        raise ValueError("Username, password and ingest token are required")
    keychain_set("lastmonitor-instagram-password", username, password)
    keychain_set("lastmonitor-instagram-ingest", "cloudflare", token)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        (
            f"IG_USERNAME={username}",
            f"IG_TARGETS={targets}",
            "IG_INTERVAL_JITTER_SECONDS=1050",
            "IG_FETCH_LIMIT=12",
            "IG_SEND_EXISTING=false",
            f"CF_INGEST_URL={endpoint}",
            f"IG_RUNTIME_DIR={runtime_dir}",
            "",
        )
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.chmod(path, 0o600)
    print(f"Configuration saved securely: {path}")


def install_launchd(config: Config) -> Path:
    plist_path = Path("~/Library/LaunchAgents").expanduser() / f"{LAUNCHD_LABEL}.plist"
    project_root = Path(__file__).resolve().parents[1]
    config.runtime_dir.mkdir(parents=True, exist_ok=True)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [
            "/usr/bin/caffeinate",
            "-s",
            sys.executable,
            "-m",
            "instagram_worker",
            "--config",
            str(config.config_file),
            "run",
        ],
        "WorkingDirectory": str(project_root),
        "RunAtLoad": False,
        "ProcessType": "Background",
        "ThrottleInterval": 30,
        "StandardOutPath": str(config.runtime_dir / "launchd.out.log"),
        "StandardErrorPath": str(config.runtime_dir / "launchd.err.log"),
    }
    with plist_path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)
    os.chmod(plist_path, 0o600)
    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", domain, str(plist_path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist_path)],
        check=True,
    )
    return plist_path


def launchd_plist_path() -> Path:
    return Path("~/Library/LaunchAgents").expanduser() / f"{LAUNCHD_LABEL}.plist"


def launchd_domain() -> str:
    return f"gui/{os.getuid()}"


def launchd_target() -> str:
    return f"{launchd_domain()}/{LAUNCHD_LABEL}"


def launchd_state() -> tuple[str, str, bool]:
    result = subprocess.run(
        ["launchctl", "print", launchd_target()],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return "stopped", "", False
    state_match = re.search(r"^\s*state = (.+?)\s*$", result.stdout, re.MULTILINE)
    pid_match = re.search(r"^\s*pid = (\d+)", result.stdout, re.MULTILINE)
    state = state_match.group(1) if state_match else "loaded"
    if state == "not running":
        state = "stopped"
    return (
        state,
        pid_match.group(1) if pid_match else "",
        True,
    )


def start_launchd() -> None:
    state, pid, loaded = launchd_state()
    if state == "running":
        print(f"Instagram worker already running (pid={pid})")
        return
    plist_path = launchd_plist_path()
    if not plist_path.exists():
        raise FileNotFoundError("LaunchAgent is not installed; run install-launchd first")
    if not loaded:
        subprocess.run(
            ["launchctl", "bootstrap", launchd_domain(), str(plist_path)],
            check=True,
        )
    subprocess.run(["launchctl", "kickstart", launchd_target()], check=True)
    print("Instagram worker started")


def stop_launchd() -> None:
    _state, _pid, loaded = launchd_state()
    if not loaded:
        print("Instagram worker already stopped")
        return
    subprocess.run(
        ["launchctl", "bootout", launchd_domain(), str(launchd_plist_path())],
        check=True,
    )
    print("Instagram worker stopped")


def print_launchd_status() -> None:
    state, pid, _loaded = launchd_state()
    suffix = f" (pid={pid})" if pid else ""
    print(f"Instagram worker: {state}{suffix}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lastmonitor local Instagram worker")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("configure")
    subparsers.add_parser("check-config")
    subparsers.add_parser("login")
    subparsers.add_parser("run-once")
    subparsers.add_parser("run")
    subparsers.add_parser("install-launchd")
    subparsers.add_parser("start")
    subparsers.add_parser("stop")
    subparsers.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "configure":
        configure(args.config)
        return 0

    config = load_config(args.config)
    configure_logging(config)
    if args.command == "check-config":
        print(
            f"Configuration valid: {len(config.targets)} targets; "
            f"session={'ready' if session_exists(config.session_file) else 'not created'}"
        )
        return 0
    if args.command == "login":
        login_interactively(config)
        print(f"Instagram session created: {config.session_file}")
        return 0
    if args.command == "install-launchd":
        if not session_exists(config.session_file):
            raise RuntimeError("Run the login command before installing launchd")
        path = install_launchd(config)
        print(f"LaunchAgent installed: {path}")
        return 0
    if args.command == "start":
        start_launchd()
        return 0
    if args.command == "stop":
        stop_launchd()
        return 0
    if args.command == "status":
        print_launchd_status()
        return 0

    service = InstagramService(config)
    try:
        if args.command == "run-once":
            service.run_once()
        else:
            service.run_forever()
    finally:
        service.close()
    return 0
