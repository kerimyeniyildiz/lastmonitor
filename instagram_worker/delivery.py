from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

import requests

from .config import Config


class CloudflareDelivery:
    def __init__(self, config: Config):
        self.base_url = config.ingest_url
        self.token = config.ingest_token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "authorization": f"Bearer {self.token}",
                "user-agent": "lastmonitor-instagram-worker/1.0",
            }
        )

    def send_event(
        self,
        payload: Mapping[str, str | None],
        preview_path: Path | None,
    ) -> dict:
        files: dict[str, tuple[str, object, str]] = {}
        preview_handle = None
        try:
            if preview_path and preview_path.exists():
                preview_handle = preview_path.open("rb")
                files["preview"] = (preview_path.name, preview_handle, "image/jpeg")
            response = self.session.post(
                f"{self.base_url}/events",
                data={"payload": json.dumps(payload, ensure_ascii=False)},
                files=files,
                timeout=90,
            )
            if not response.ok:
                raise requests.HTTPError(
                    f"Cloudflare ingest {response.status_code}: {response.text[:500]}",
                    response=response,
                )
            value = response.json()
            if value.get("telegram_status") != "sent":
                raise RuntimeError("Cloudflare did not confirm Telegram delivery")
            return value
        finally:
            if preview_handle:
                preview_handle.close()

    def report_run(self, payload: Mapping[str, object]) -> None:
        response = self.session.post(
            f"{self.base_url}/runs",
            json=payload,
            timeout=30,
        )
        if not response.ok:
            raise requests.HTTPError(
                f"Cloudflare run report {response.status_code}: {response.text[:500]}",
                response=response,
            )
