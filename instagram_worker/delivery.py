from __future__ import annotations

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
    ) -> dict:
        response = self.session.post(
            f"{self.base_url}/events",
            json=payload,
            timeout=30,
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
