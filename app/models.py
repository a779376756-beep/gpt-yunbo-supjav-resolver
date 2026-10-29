from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any


@dataclass
class MediaRef:
    url: str
    referer: str
    label: str = ""


@dataclass
class PlaybackSession:
    token: str
    client: Any
    player_referer: str
    server: str
    title: str
    ttl: int
    created_at: float = field(default_factory=monotonic)
    refs: dict[str, MediaRef] = field(default_factory=dict)
    ref_index: dict[str, str] = field(default_factory=dict)

    @property
    def expired(self) -> bool:
        return monotonic() - self.created_at > self.ttl

