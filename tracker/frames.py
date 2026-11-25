"""Capture mpv video frames as BGR arrays for live tracking."""
from __future__ import annotations

import base64
import os
import tempfile
from typing import Any

import numpy as np


def decode_raw(node: dict[str, Any]) -> np.ndarray:
    """`{w,h,stride,format,data}` → (h, w, 3) uint8 BGR.

    Accept base64 or byte sequences from adapters that can transport binary nodes.
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
    """`screenshot-to-file` ile kareyi geçici dosyadan okur (büyük JSON satırına gerek yok)."""
    import cv2

    from .ipc import MpvCommandError

    path = os.path.join(tempfile.gettempdir(), f"takipli_kare_{os.getpid()}.jpg")
    try:
        mpv.command("screenshot-to-file", path, "video")
        data = np.fromfile(path, dtype=np.uint8)
        frame = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    except (OSError, cv2.error) as e:
        raise MpvCommandError(f"kare dosyası okunamadı: {e}") from e
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if frame is None:
        raise MpvCommandError("kare dosyası okunamadı")  # geçici hata: döngü yeniden dener
    return np.ascontiguousarray(frame)
