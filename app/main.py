from __future__ import annotations

import hmac
import re
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .client import FetchError, fetch_media, new_client
from .config import settings
from .extract import rewrite_m3u8
from .resolver import resolve, search
from .security import UnsafeUrl, ensure_public_url
from .store import store


def require_key(x_resolver_key: str = Header(default="")) -> None:
    if not settings.api_key:
        raise HTTPException(503, "RESOLVER_API_KEY is not configured")
    if not hmac.compare_digest(x_resolver_key, settings.api_key):
        raise HTTPException(401, "invalid resolver key")


class ResolveBody(BaseModel):
    url: str = Field(min_length=10, max_length=2000)


app = FastAPI(title="SupJav resolver", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.site_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS", "HEAD"],
    allow_headers=["Content-Type", "X-Resolver-Key", "Range"],
    expose_headers=["Content-Length", "Content-Range", "Accept-Ranges"],
)


@app.exception_handler(FetchError)
async def fetch_error_handler(_request: Request, exc: FetchError):
    return JSONResponse({"error": str(exc)}, status_code=502)


@app.exception_handler(UnsafeUrl)
async def unsafe_url_handler(_request: Request, exc: UnsafeUrl):
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "supjav-resolver",
        "browser": settings.browser_enabled,
        "configured": bool(settings.api_key),
    }


@app.get("/v1/search", dependencies=[Depends(require_key)])
async def search_route(q: str = Query(min_length=1, max_length=120), page: int = Query(1, ge=1, le=50)):
    items, upstream = await search(q.strip(), page)
    return {"source": "supjav", "page": page, "items": items, "upstream": upstream}


def public_base(request: Request) -> str:
    return settings.public_base_url or str(request.base_url).rstrip("/")


@app.post("/v1/resolve", dependencies=[Depends(require_key)])
async def resolve_route(body: ResolveBody, request: Request):
    result = await resolve(body.url)
    primary = result.routes[0]
    item = store.create(
        result.client,
        player_referer=primary["player_url"],
        server=primary["server"],
        title=result.title,
        ttl=settings.session_ttl,
    )
    qualities = []
    for route in result.routes:
        ref_id = store.register(item, route["url"], route["player_url"], route["server"])
        media_url = f"{public_base(request)}/v1/media/{item.token}/{ref_id}"
        qualities.append(
            {
                "server": route["server"],
                "label": f"{route['server']} · 自动线路",
                "format": "hls" if ".m3u8" in urlsplit(route["url"]).path.lower() else "mp4",
                "url": media_url,
            }
        )
    return {
        "title": result.title,
        "server": primary["server"],
        "format": qualities[0]["format"],
        "url": qualities[0]["url"],
        "qualities": qualities,
        "expiresIn": settings.session_ttl,
        "fallback": "automatic",
        **result.metadata,
    }


@app.get("/v1/image", dependencies=[Depends(require_key)])
async def image_route(url: str = Query(min_length=10, max_length=2000)):
    ensure_public_url(url)
    client = new_client()
    upstream = client.get(
        url,
        headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8", "Referer": "https://supjav.com/"},
        timeout=settings.media_timeout,
        allow_redirects=True,
    )
    content_type = upstream.headers.get("content-type", "").split(";", 1)[0].lower()
    if upstream.status_code >= 400 or not content_type.startswith("image/"):
        raise HTTPException(502, "image upstream unavailable")
    if len(upstream.content) > 15 * 1024 * 1024:
        raise HTTPException(502, "image is too large")
    return Response(
        upstream.content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )


@app.api_route("/v1/media/{token}/{ref_id}", methods=["GET", "HEAD"])
async def media_route(token: str, ref_id: str, request: Request):
    item = store.get(token)
    if not item or ref_id not in item.refs:
        raise HTTPException(410, "playback session expired; resolve the video again")
    ref = item.refs[ref_id]
    ensure_public_url(ref.url)
    incoming = {name.lower(): value for name, value in request.headers.items()}
    upstream = fetch_media(item.client, ref.url, ref.referer, incoming)
    if upstream.status_code >= 400:
        upstream.close()
        raise HTTPException(502, f"media upstream returned {upstream.status_code}")

    content_type = upstream.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
    is_playlist = "mpegurl" in content_type.lower() or re.search(r"\.m3u8(?:$|[?#])", ref.url, re.I)
    common_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() in {"content-length", "content-range", "accept-ranges", "etag", "last-modified", "cache-control"}
    }
    common_headers["Access-Control-Allow-Origin"] = settings.site_origin
    common_headers["Vary"] = "Origin"
    if request.method == "HEAD":
        upstream.close()
        return Response(status_code=upstream.status_code, media_type=content_type, headers=common_headers)

    if is_playlist:
        data = upstream.content
        upstream.close()
        if len(data) > 2 * 1024 * 1024:
            raise HTTPException(502, "playlist is too large")
        text = data.decode("utf-8", "replace")

        def register(url: str) -> str:
            ensure_public_url(url)
            child_id = store.register(item, url, ref.referer)
            return f"{public_base(request)}/v1/media/{token}/{child_id}"

        rewritten = rewrite_m3u8(text, ref.url, register)
        common_headers.pop("content-length", None)
        common_headers["Cache-Control"] = "no-store"
        return Response(rewritten, media_type="application/vnd.apple.mpegurl", headers=common_headers)

    def stream():
        try:
            for chunk in upstream.iter_content(chunk_size=128 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(stream(), status_code=upstream.status_code, media_type=content_type, headers=common_headers)

