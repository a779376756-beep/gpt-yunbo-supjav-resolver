from __future__ import annotations

import ipaddress
import socket
from functools import lru_cache
from urllib.parse import urlsplit


class UnsafeUrl(ValueError):
    pass


@lru_cache(maxsize=1024)
def _public_host(hostname: str) -> bool:
    try:
        addresses = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrl(f"host lookup failed: {hostname}") from exc
    if not addresses:
        raise UnsafeUrl(f"host lookup failed: {hostname}")
    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if not ip.is_global:
            raise UnsafeUrl("private or reserved address is not allowed")
    return True


def ensure_public_url(url: str, resolve_dns: bool = True) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeUrl("only public HTTP(S) URLs are allowed")
    host = parsed.hostname.strip("[]").lower()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if not ip.is_global:
            raise UnsafeUrl("private or reserved address is not allowed")
    else:
        if host == "localhost" or host.endswith(".localhost") or "." not in host:
            raise UnsafeUrl("local hosts are not allowed")
        if resolve_dns:
            _public_host(host)
    return url


def is_supjav_url(url: str, base_urls: tuple[str, ...]) -> bool:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    allowed = {(urlsplit(base).hostname or "").lower() for base in base_urls}
    return any(host == item or host.endswith("." + item) for item in allowed if item)

