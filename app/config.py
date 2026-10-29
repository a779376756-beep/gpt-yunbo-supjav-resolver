from __future__ import annotations

import os
from dataclasses import dataclass


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(value.strip().rstrip("/") for value in os.getenv(name, default).split(",") if value.strip())


@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv("RESOLVER_API_KEY", "")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    site_origin: str = os.getenv("SITE_ORIGIN", "https://quiet-stream-91.a779376756.chatgpt.site").rstrip("/")
    base_urls: tuple[str, ...] = _csv(
        "SUPJAV_BASE_URLS", "https://supjav.com,https://supjav.net,https://supjav.org"
    )
    browser_enabled: bool = os.getenv("ENABLE_BROWSER", "1").lower() not in {"0", "false", "no"}
    session_ttl: int = int(os.getenv("SESSION_TTL_SECONDS", "2700"))
    html_timeout: int = int(os.getenv("HTML_TIMEOUT_SECONDS", "18"))
    media_timeout: int = int(os.getenv("MEDIA_TIMEOUT_SECONDS", "28"))


settings = Settings()

