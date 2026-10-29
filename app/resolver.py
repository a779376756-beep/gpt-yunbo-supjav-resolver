from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import quote_plus, urlsplit

from .browser import browser_resolver, client_from_browser
from .client import FetchError, fetch_html, new_client
from .config import settings
from .extract import (
    ServerLink,
    candidate_server_urls,
    detail_metadata,
    document_title,
    extract_iframes,
    extract_media_urls,
    extract_server_links,
    parse_search_results,
)
from .security import ensure_public_url, is_supjav_url


SERVER_ORDER = ("EVS", "FST", "VOE", "VAS", "LUC", "ORIGINAL")


@dataclass
class ResolvedMedia:
    routes: list[dict]
    title: str
    client: object
    metadata: dict


async def _fetch_html(client, url: str, referer: str = "") -> tuple[str, str]:
    ensure_public_url(url)
    return await asyncio.to_thread(fetch_html, client, url, referer)


async def search(query: str, page: int) -> tuple[list[dict], str]:
    errors = []
    for base in settings.base_urls:
        client = new_client()
        paths = [
            f"/?s={quote_plus(query)}" if page == 1 else f"/page/{page}/?s={quote_plus(query)}",
            f"/zh/?s={quote_plus(query)}" if page == 1 else f"/zh/page/{page}/?s={quote_plus(query)}",
        ]
        for path in paths:
            url = base + path
            try:
                source, final_url = await _fetch_html(client, url)
                items = parse_search_results(source, final_url)
                if items:
                    return items, final_url
            except Exception as exc:
                errors.append(f"{base}: {exc}")
    raise FetchError("all SupJav mirrors failed: " + "; ".join(errors[-3:]))


def _sort_links(links: list[ServerLink]) -> list[ServerLink]:
    def rank(item: ServerLink) -> tuple[int, str]:
        label = item.label.upper()
        if label == "ST" or "ST" == label.split()[0]:
            return (999, label)
        for index, preferred in enumerate(SERVER_ORDER):
            if preferred in label:
                return (index, label)
        return (100, label)

    return sorted(links, key=rank)


async def _follow_candidate(client, start_url: str, detail_url: str, max_depth: int = 5):
    queue = [(start_url, detail_url, 0)]
    visited = set()
    while queue:
        url, referer, depth = queue.pop(0)
        if url in visited or depth > max_depth:
            continue
        visited.add(url)
        try:
            source, final_url = await _fetch_html(client, url, referer)
        except Exception:
            continue
        media = extract_media_urls(source, final_url)
        if media:
            return media[0], final_url
        for iframe in extract_iframes(source, final_url):
            if iframe not in visited:
                queue.append((iframe, final_url, depth + 1))
    return None


async def resolve(detail_url: str) -> ResolvedMedia:
    if not is_supjav_url(detail_url, settings.base_urls):
        raise ValueError("only configured SupJav detail URLs are accepted")
    client = new_client()
    source = final_url = ""
    path = urlsplit(detail_url).path
    page_errors = []
    page_candidates = [detail_url, *(base + path for base in settings.base_urls)]
    for candidate in dict.fromkeys(page_candidates):
        try:
            source, final_url = await _fetch_html(client, candidate)
            break
        except Exception as exc:
            page_errors.append(str(exc))
    if not source:
        raise FetchError("all SupJav detail mirrors failed: " + "; ".join(page_errors[-3:]))
    title = document_title(source)
    metadata = detail_metadata(source, final_url)
    links = _sort_links(extract_server_links(source, final_url))
    errors = []
    routes: list[dict] = []
    for link in links:
        if link.label.upper().strip() == "ST":
            continue
        for candidate in candidate_server_urls(link, final_url):
            result = await _follow_candidate(client, candidate, final_url)
            if result:
                media_url, player_url = result
                ensure_public_url(media_url)
                routes.append({"url": media_url, "player_url": player_url, "server": link.label})
                break
        errors.append(link.label)

    if routes:
        return ResolvedMedia(routes, title, client, metadata)

    if settings.browser_enabled:
        for link in links or [ServerLink("ORIGINAL", final_url)]:
            if link.label.upper().strip() == "ST":
                continue
            try:
                result = await browser_resolver.resolve(final_url, link.label)
                if result:
                    client = client_from_browser(result.cookies)
                    return ResolvedMedia(
                        [{"url": result.media_url, "player_url": result.player_url, "server": link.label}],
                        title,
                        client,
                        metadata,
                    )
            except Exception as exc:
                errors.append(f"{link.label}:{type(exc).__name__}")
    raise FetchError("no playable SupJav route found; tried " + ", ".join(errors or ["page"]))

