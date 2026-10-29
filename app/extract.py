from __future__ import annotations

import base64
import html as html_module
import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

from lxml import html


MEDIA_RE = re.compile(
    r"https?:(?:\\/\\/|//)[^\s'\"<>]+?\.(?:m3u8|mp4)(?:\?[^\s'\"<>]*)?",
    re.I,
)
IFRAME_RE = re.compile(r"<iframe[^>]+src\s*=\s*['\"]([^'\"]+)", re.I)


@dataclass(frozen=True)
class ServerLink:
    label: str
    value: str


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def deescape_script(value: str) -> str:
    value = html_module.unescape(value)
    value = value.replace(r"\/", "/")
    try:
        value = re.sub(
            r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), value
        )
    except ValueError:
        pass
    return value


def parse_search_results(source: str, page_url: str) -> list[dict]:
    tree = html.fromstring(source or "<html></html>")
    items: list[dict] = []
    seen: set[str] = set()
    anchors = tree.xpath("//a[@href]")
    for anchor in anchors:
        href = urljoin(page_url, anchor.get("href") or "")
        path = urlsplit(href).path
        if not re.search(r"/\d+\.html$", path):
            continue
        if href in seen:
            continue
        image = next(iter(anchor.xpath(".//img")), None)
        title = clean_text(
            anchor.get("title")
            or (image.get("alt") if image is not None else "")
            or " ".join(anchor.itertext())
        )
        if not title:
            continue
        poster = ""
        if image is not None:
            for attr in ("data-original", "data-lazy-src", "data-src", "src"):
                if image.get(attr):
                    poster = urljoin(page_url, image.get(attr))
                    break
        parent = anchor
        for _ in range(4):
            if parent.getparent() is None:
                break
            parent = parent.getparent()
            classes = " ".join(parent.get("class", "").split()).lower()
            if any(word in classes for word in ("post", "item", "video", "card", "thumb")):
                break
        text = clean_text(" ".join(parent.itertext()))
        code = ""
        code_match = re.search(r"\b[A-Z]{2,12}[-_ ]?\d{2,7}[A-Z]{0,3}\b", f"{title} {text}", re.I)
        if code_match:
            code = code_match.group(0).replace("_", "-").replace(" ", "-").upper()
        labels = []
        for node in parent.xpath(".//*[self::span or self::a][contains(@class,'tag') or contains(@class,'cat')]"):
            label = clean_text(" ".join(node.itertext()))
            if label and label != title and label not in labels:
                labels.append(label)
        seen.add(href)
        items.append(
            {
                "id": path.rsplit("/", 1)[-1].removesuffix(".html"),
                "title": title,
                "code": code,
                "url": href,
                "poster": poster,
                "labels": labels[:8],
                "playable": True,
            }
        )
    return items


def extract_server_links(source: str, page_url: str) -> list[ServerLink]:
    tree = html.fromstring(source or "<html></html>")
    result: list[ServerLink] = []
    seen: set[tuple[str, str]] = set()
    selectors = tree.xpath(
        "//*[@data-link or @data-url or @data-src][contains(concat(' ', normalize-space(@class), ' '), ' btn-server ') or contains(@class,'server')]"
    )
    for index, node in enumerate(selectors):
        value = node.get("data-link") or node.get("data-url") or node.get("data-src") or ""
        label = clean_text(" ".join(node.itertext()) or node.get("title") or node.get("data-server"))
        label = (label or f"SERVER-{index + 1}").upper()
        key = (label, value)
        if value and key not in seen:
            seen.add(key)
            result.append(ServerLink(label, value))

    # Some versions render the server map in JavaScript and use its key in data-link.
    for body in re.findall(r"serverMap\s*=\s*\{(.*?)\}\s*;?", source, re.I | re.S):
        for key, value in re.findall(r"['\"]?([\w-]+)['\"]?\s*:\s*['\"]([^'\"]+)['\"]", body):
            pair = (key.upper(), value)
            if pair not in seen:
                seen.add(pair)
                result.append(ServerLink(*pair))
    if not result:
        # A single embedded player still counts as a usable route.
        for index, value in enumerate(extract_iframes(source, page_url)):
            result.append(ServerLink(f"ORIGINAL-{index + 1}", value))
    return result


def candidate_server_urls(link: ServerLink, page_url: str) -> list[str]:
    raw = deescape_script(unquote(link.value.strip()))
    values = [raw]
    if raw:
        values.append(raw[::-1])
        padded = raw + "=" * (-len(raw) % 4)
        for decoder in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                decoded = decoder(padded).decode("utf-8", "ignore")
                if decoded:
                    values.append(decoded)
            except Exception:
                pass
    urls: list[str] = []
    for value in values:
        value = value.strip()
        if value.startswith("//"):
            value = "https:" + value
        if value.startswith(("http://", "https://", "/")):
            urls.append(urljoin(page_url, value))

    token = raw
    if token and not any(char in token for char in "<>\"'"):
        query_token = quote(token, safe="")
        reverse_token = quote(token[::-1], safe="")
        urls.extend(
            [
                f"https://lk1.supremejav.com/supjav.php?c={query_token}",
                f"https://lk1.supremejav.com/supjav.php?c={reverse_token}",
            ]
        )
    return list(dict.fromkeys(urls))


def extract_iframes(source: str, page_url: str) -> list[str]:
    values: list[str] = []
    try:
        tree = html.fromstring(source or "<html></html>")
        values.extend(tree.xpath("//iframe/@src"))
    except Exception:
        pass
    values.extend(IFRAME_RE.findall(source))
    result = []
    for value in values:
        value = deescape_script(value.strip())
        if value.startswith("//"):
            value = "https:" + value
        url = urljoin(page_url, value)
        if url.startswith(("http://", "https://")) and url not in result:
            result.append(url)
    return result


def extract_media_urls(source: str, page_url: str) -> list[str]:
    decoded = deescape_script(source)
    values = MEDIA_RE.findall(decoded)
    patterns = [
        r"(?:file|hls|src|source|urlPlay)\s*[:=]\s*['\"]([^'\"]+)",
        r"['\"](https?://[^'\"]+\.(?:m3u8|mp4)(?:\?[^'\"]*)?)['\"]",
    ]
    for pattern in patterns:
        values.extend(re.findall(pattern, decoded, re.I))
    result: list[str] = []
    for value in values:
        value = deescape_script(value).strip().rstrip("\\")
        if value.startswith("//"):
            value = "https:" + value
        value = urljoin(page_url, value)
        if re.search(r"\.(?:m3u8|mp4)(?:$|[?#])", value, re.I) and value not in result:
            result.append(value)
    return result


def document_title(source: str) -> str:
    try:
        tree = html.fromstring(source)
        og = tree.xpath("//meta[@property='og:title']/@content")
        if og:
            return clean_text(og[0])
        titles = tree.xpath("//title/text() | //h1[1]//text()")
        return clean_text(" ".join(titles))
    except Exception:
        return ""


def detail_metadata(source: str, page_url: str) -> dict:
    try:
        tree = html.fromstring(source or "<html></html>")
    except Exception:
        return {"poster": "", "actors": [], "genres": [], "hasChineseSubtitles": False}
    posters = tree.xpath("//meta[@property='og:image']/@content | //video/@poster")
    poster = urljoin(page_url, posters[0]) if posters else ""
    actors: list[dict] = []
    genres: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for anchor in tree.xpath("//a[@href]"):
        href = urljoin(page_url, anchor.get("href") or "")
        path = urlsplit(href).path.lower()
        name = clean_text(" ".join(anchor.itertext()) or anchor.get("title"))
        if not name or len(name) > 80:
            continue
        target = None
        kind = ""
        if re.search(r"/(?:actor|actress|pornstar|star)/", path):
            target, kind = actors, "sup-actor"
        elif re.search(r"/(?:genre|tag|category|studio|maker)/", path):
            target, kind = genres, "sup-genre"
        if target is None:
            continue
        slug = unquote(path.rstrip("/").rsplit("/", 1)[-1])
        key = (kind, slug or name)
        if key in seen:
            continue
        seen.add(key)
        target.append({"id": slug or name, "name": name, "type": kind})
    text = clean_text(" ".join(tree.itertext()))
    has_subtitles = bool(re.search(r"中文字幕|中文翻译|Chinese\s*Sub", text, re.I))
    return {
        "poster": poster,
        "actors": actors[:12],
        "genres": genres[:24],
        "hasChineseSubtitles": has_subtitles,
    }


URI_ATTRIBUTE_RE = re.compile(r'URI=("|\')(.*?)(\1)', re.I)


def rewrite_m3u8(source: str, playlist_url: str, register) -> str:
    output: list[str] = []
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line:
            output.append(raw_line)
            continue
        if line.startswith("#"):
            def replace_uri(match: re.Match) -> str:
                absolute = urljoin(playlist_url, match.group(2))
                return f'URI={match.group(1)}{register(absolute)}{match.group(1)}'

            output.append(URI_ATTRIBUTE_RE.sub(replace_uri, raw_line))
        else:
            output.append(register(urljoin(playlist_url, line)))
    return "\n".join(output) + "\n"

