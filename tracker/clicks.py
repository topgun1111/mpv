"""track.lua'dan gelen `script-message track-click ...` olaylarını ayrıştırır."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CLICK_MSG = "track-click"
RESET_MSG = "track-reset"
TOGGLE_MSG = "track-toggle"


@dataclass(frozen=True)
class ClickEvent:
    nx: float  # video içinde normalize x (0..1)
    ny: float
    vw: int  # video piksel genişliği
    vh: int
    time_pos: float  # tıklama anındaki oynatma zamanı (sn)

    @property
    def px(self) -> float:
        return self.nx * self.vw

    @property
    def py(self) -> float:
        return self.ny * self.vh


def parse_click(event: dict[str, Any]) -> ClickEvent | None:
    """client-message olayı bir tıklama değilse veya bozuksa None döner."""
    if event.get("event") != "client-message":
        return None
    args = event.get("args") or []
    if len(args) != 6 or args[0] != CLICK_MSG:
        return None
    try:
        nx, ny = float(args[1]), float(args[2])
        vw, vh = int(float(args[3])), int(float(args[4]))
        t = float(args[5])
    except (TypeError, ValueError):
        return None
    if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0) or vw <= 0 or vh <= 0:
        return None
    return ClickEvent(nx, ny, vw, vh, t)


def message_name(event: dict[str, Any]) -> str | None:
    """client-message olayının ilk argümanı (track-reset vb.)."""
    if event.get("event") != "client-message":
        return None
    args = event.get("args") or []
    return args[0] if args else None
