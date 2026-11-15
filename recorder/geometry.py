"""Elle kamera geometrisi — Android `Record.kt` ve `tracker/export.py` ile aynı formüller.

Görünüm = (zoom log2, pan_x, pan_y). Ölçek s = 2^zoom; görünen merkez = 0.5 − pan (kare oranı).
Pan, kırpma penceresi kare dışına taşmayacak şekilde ±(0.5 − 0.5/s) ile sınırlanır.
"""
from __future__ import annotations

import math

View = tuple[float, float, float]
MAX_ZOOM = 4.0  # log2 → 16×; Android ile aynı


def clamp_view(v: View, max_zoom: float = MAX_ZOOM) -> View:
    z = min(max(v[0], 0.0), max_zoom)
    lim = max(0.5 - 0.5 / 2.0 ** z, 0.0)
    return z, min(max(v[1], -lim), lim), min(max(v[2], -lim), lim)


def apply_gesture_at(v: View, ax: float, ay: float, dx_frac: float, dy_frac: float,
                     zoom_factor: float, max_zoom: float = MAX_ZOOM) -> View:
    """Zoom ve sürüklemeyi AYNI ANDA uygular (Android `applyGestureAt`).

    (ax, ay): imlecin görüntü alanındaki konumu (genişlik/yükseklik oranı), (dx_frac, dy_frac):
    aynı karede imleç kayması, zoom_factor: ölçek çarpanı (1 = değişmez). İmlecin altındaki
    kare noktası imlecle birlikte kalır: zoom imleç etrafında olur, kare ortası etrafında değil.
    """
    z0 = max(v[0], 0.0)
    z1 = min(max(z0 + (math.log2(zoom_factor) if zoom_factor > 0 else 0.0), 0.0), max_zoom)
    s0, s1 = 2.0 ** z0, 2.0 ** z1
    fx = (0.5 - v[1]) + (ax - 0.5) / s0  # imlecin altındaki kare noktası
    fy = (0.5 - v[2]) + (ay - 0.5) / s0
    cx = fx - (ax + dx_frac - 0.5) / s1
    cy = fy - (ay + dy_frac - 0.5) / s1
    return clamp_view((z1, 0.5 - cx, 0.5 - cy), max_zoom)


def set_zoom_at(v: View, ax: float, ay: float, zoom: float, max_zoom: float = MAX_ZOOM) -> View:
    """Zoom düzeyini (log2) doğrudan ayarla; (ax, ay) noktası yerinde kalır. Kaydırma yok."""
    z0 = max(v[0], 0.0)
    z1 = min(max(zoom, 0.0), max_zoom)
    return apply_gesture_at(v, ax, ay, 0.0, 0.0, 2.0 ** (z1 - z0), max_zoom)


def view_at(views: list[list[float]], t: float) -> View:
    """Anahtar kareler arası doğrusal (uçlarda sabit) — `track.lua::view_at` ile aynı."""
    if not views:
        return 0.0, 0.0, 0.0
    if t <= views[0][0]:
        return views[0][1], views[0][2], views[0][3]
    if t >= views[-1][0]:
        return views[-1][1], views[-1][2], views[-1][3]
    lo, hi = 0, len(views) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if views[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    a, b = views[lo], views[hi]
    f = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
    return a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f


def crop_rect(view: View, vw: int, vh: int) -> tuple[int, int, int, int]:
    """(zoom, pan_x, pan_y) → piksel kırpma (x, y, w, h); kare içinde, boyutlar ≥2."""
    z, px, py = view
    s = max(2.0 ** max(z, 0.0), 1.0)
    cw, ch = vw / s, vh / s
    cx = min(max((0.5 - px) * vw, cw / 2), vw - cw / 2)
    cy = min(max((0.5 - py) * vh, ch / 2), vh - ch / 2)
    w, h = max(int(round(cw)), 2), max(int(round(ch)), 2)
    x = min(max(int(round(cx - cw / 2)), 0), vw - w)
    y = min(max(int(round(cy - ch / 2)), 0), vh - h)
    return x, y, w, h
