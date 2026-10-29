from __future__ import annotations

import secrets
import threading

from .models import MediaRef, PlaybackSession


class SessionStore:
    def __init__(self) -> None:
        self._items: dict[str, PlaybackSession] = {}
        self._lock = threading.RLock()

    def create(self, client, player_referer: str, server: str, title: str, ttl: int) -> PlaybackSession:
        self.cleanup()
        token = secrets.token_urlsafe(32)
        item = PlaybackSession(token, client, player_referer, server, title, ttl)
        with self._lock:
            self._items[token] = item
        return item

    def get(self, token: str) -> PlaybackSession | None:
        with self._lock:
            item = self._items.get(token)
            if item and item.expired:
                self._items.pop(token, None)
                return None
            return item

    def register(self, item: PlaybackSession, url: str, referer: str = "", label: str = "") -> str:
        with self._lock:
            if url in item.ref_index:
                return item.ref_index[url]
            ref_id = secrets.token_urlsafe(12)
            item.refs[ref_id] = MediaRef(url=url, referer=referer or item.player_referer, label=label)
            item.ref_index[url] = ref_id
            return ref_id

    def cleanup(self) -> None:
        with self._lock:
            expired = [token for token, item in self._items.items() if item.expired]
            for token in expired:
                self._items.pop(token, None)


store = SessionStore()

