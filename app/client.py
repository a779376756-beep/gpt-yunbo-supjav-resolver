from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urlsplit

from curl_cffi import requests

from .config import settings


USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1"
)


class FetchError(RuntimeError):
    pass


def new_client() -> requests.Session:
    client = requests.Session(impersonate="safari_ios")
    client.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "DNT": "1",
        }
    )
    return client


def origin_for(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def fetch_html(client: requests.Session, url: str, referer: str = "") -> tuple[str, str]:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site" if referer else "none",
    }
    if referer:
        headers["Referer"] = referer
    response = client.get(url, headers=headers, timeout=settings.html_timeout, allow_redirects=True)
    if response.status_code >= 400:
        raise FetchError(f"upstream returned {response.status_code}")
    if len(response.content) > 5 * 1024 * 1024:
        raise FetchError("upstream page is too large")
    return response.text, str(response.url)


def media_headers(referer: str, incoming: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "Accept": "*/*",
        "Referer": referer,
        "Origin": origin_for(referer),
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
    }
    incoming = incoming or {}
    for name in ("range", "if-none-match", "if-modified-since"):
        if incoming.get(name):
            headers[name.title()] = incoming[name]
    return headers


def fetch_media(client: requests.Session, url: str, referer: str, incoming: dict[str, str]):
    return client.get(
        url,
        headers=media_headers(referer, incoming),
        timeout=settings.media_timeout,
        allow_redirects=True,
        stream=True,
    )

