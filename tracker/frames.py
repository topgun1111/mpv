"""mpv `screenshot-raw` yanıtını BGR numpy karesine çevirir (Parça 5)."""
from __future__ import annotations

import base64
from typing import Any

import numpy as np


def decode_raw(node: dict[str, Any]) -> np.ndarray:
    """`{w,h,stride,format,data}` → (h, w, 3) uint8 BGR.

    JSON IPC bayt dizilerini base64 metni olarak verir; eski sürümler için sayı listesi de kabul.
    """
    try:
        w, h, stride = int(node["w"]), int(node["h"]), int(node["stride"])
        fmt, data = node["format"], node["data"]
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"screenshot-raw yanıtı bozuk: {e}") from e
    if fmt not in ("bgr0", "bgra"):
        raise ValueError(f"desteklenmeyen kare formatı: {fmt}")
    buf = base64.b64decode(data) if isinstance(data, str) else bytes(data)
    if w <= 0 or h <= 0 or stride < w * 4 or len(buf) < stride * h:
        raise ValueError(f"kare verisi eksik: {w}x{h} stride={stride} bayt={len(buf)}")
    arr = np.frombuffer(buf, dtype=np.uint8, count=stride * h).reshape(h, stride)
    return np.ascontiguousarray(arr[:, : w * 4].reshape(h, w, 4)[:, :, :3])


def grab_frame(mpv) -> np.ndarray:
    """O anki video karesini (altyazı/OSD'siz, zoom'suz, tam çözünürlük) BGR olarak alır."""
    return decode_raw(mpv.command("screenshot-raw", "video", "bgr0"))
