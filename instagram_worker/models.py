from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class InstagramEvent:
    event_key: str
    instagram_id: str
    username: str
    content_type: str
    group_name: str
    caption: str
    link: str
    created_at: str | None
    sort_timestamp: float
    preview_url: str | None

    def payload(self) -> dict[str, str | None]:
        return {
            "event_key": self.event_key,
            "instagram_id": self.instagram_id,
            "username": self.username,
            "content_type": self.content_type,
            "caption": self.caption,
            "link": self.link,
            "created_at": self.created_at,
        }


def attr_value(item: object, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _timestamp(value: object) -> tuple[str | None, float]:
    if not value:
        return None, 0.0
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None, 0.0
        if not parsed.tzinfo:
            parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(), parsed.timestamp()


def _preview_url(item: object, content_type: str) -> str | None:
    if content_type == "carousel":
        resources = attr_value(item, "resources") or []
        if resources:
            return str(attr_value(resources[0], "thumbnail_url") or "") or None
    return str(attr_value(item, "thumbnail_url") or "") or None


def normalize_item(
    item: object, username: str, group_name: str
) -> InstagramEvent | None:
    primary_key = str(attr_value(item, "pk") or attr_value(item, "id") or "").strip()
    code = str(attr_value(item, "code") or "").strip()
    if not primary_key and not code:
        return None

    media_type = int(attr_value(item, "media_type") or 0)
    product_type = str(attr_value(item, "product_type") or "").lower()
    caption = str(attr_value(item, "caption_text") or "").strip()
    created_at, sort_timestamp = _timestamp(attr_value(item, "taken_at"))

    if group_name == "story":
        content_type = "story"
        instagram_id = primary_key.split("_", 1)[0]
        link = f"https://www.instagram.com/stories/{username}/{instagram_id}/"
    else:
        instagram_id = code or primary_key
        if media_type == 8:
            content_type = "carousel"
        elif product_type in {"clips", "reels"}:
            content_type = "reel"
        else:
            content_type = "post"
        route = "reel" if content_type == "reel" else "p"
        link = (
            f"https://www.instagram.com/{route}/{code}/"
            if code
            else f"https://www.instagram.com/{username}/"
        )

    if not instagram_id:
        return None
    event_key = f"instagram:{username}:{group_name}:{instagram_id}"
    return InstagramEvent(
        event_key=event_key,
        instagram_id=instagram_id,
        username=username,
        content_type=content_type,
        group_name=group_name,
        caption=caption,
        link=link,
        created_at=created_at,
        sort_timestamp=sort_timestamp,
        preview_url=_preview_url(item, content_type),
    )


def normalize_items(
    items: list[object], username: str, group_name: str
) -> list[InstagramEvent]:
    unique: dict[str, InstagramEvent] = {}
    for item in items:
        event = normalize_item(item, username, group_name)
        if event:
            unique[event.event_key] = event
    return sorted(unique.values(), key=lambda event: event.sort_timestamp)
