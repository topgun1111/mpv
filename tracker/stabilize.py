"""S13b: isteğe bağlı sabitleme (dışa aktarma). Kamera kestirimi `gmc.CameraMotion`'dan gelir
(burada yeniden yazılmadı): ardışık karelerden kare → dünya dönüşümü `W_t` birikir, yol
(tx, ty, açı, log ölçek) hareketli ortalamayla yumuşatılır, düzeltme `inv(Ws_t) @ W_t` olur.
Yalnız titreme (yüksek frekans) alınır; yavaş kaydırma korunur. Düzeltme sınırlıdır ve kenar
boşluğu sabit bir büyütmeyle (`margin`) gizlenir. Önce sıralı bir analiz geçişi, sonra render.
"""
from __future__ import annotations

import math

import numpy as np

from .gmc import CameraMotion

MAX_SHIFT = 0.06  # düzeltme çevirisi üst sınırı (kare boyutu oranı)
MAX_ROT = math.radians(2.5)  # düzeltme dönüşü üst sınırı
MAX_MARGIN = 1.20  # kenar boşluğunu gizleyen büyütme üst sınırı


def decompose(W: np.ndarray) -> tuple[float, float, float, float]:
    """3x3 benzerlik → (tx, ty, açı, log ölçek)."""
    a, b = float(W[0, 0]), float(W[1, 0])
    s = math.hypot(a, b) or 1.0
    return float(W[0, 2]), float(W[1, 2]), math.atan2(b, a), math.log(s)


def compose(tx: float, ty: float, ang: float, ls: float) -> np.ndarray:
    s = math.exp(ls)
    c, n = s * math.cos(ang), s * math.sin(ang)
    return np.array([[c, -n, tx], [n, c, ty], [0.0, 0.0, 1.0]])


def moving_average(x: np.ndarray, radius: int) -> np.ndarray:
    """Ortalaması kenarlarda daralan pencereyle (kayma yok, uçlar yönlenmez)."""
    n = len(x)
    if radius <= 0 or n < 2:
        return x.astype(float).copy()
    c = np.concatenate([[0.0], np.cumsum(x, dtype=float)])
    idx = np.arange(n)
    lo, hi = np.maximum(idx - radius, 0), np.minimum(idx + radius + 1, n)
    return (c[hi] - c[lo]) / (hi - lo)


def corrections(paths: list[np.ndarray], fps: float, size: tuple[int, int],
                window_s: float = 1.0) -> tuple[list[np.ndarray], float]:
    """`paths`: kare başına W_t (kare → ilk kare). → (kare başına 3x3 düzeltme, margin ölçeği).

    Düzeltme M_t kare t pikselini sabitlenmiş görüntüye taşır; sınırlıdır, margin hepsini gizler."""
    n = len(paths)
    if n == 0:
        return [], 1.0
    P = np.array([decompose(w) for w in paths])
    P[:, 2] = np.unwrap(P[:, 2])
    radius = max(int(round(window_s * fps / 2)), 1)
    S = np.stack([moving_average(P[:, k], radius) for k in range(4)], axis=1)
    w, h = size
    lim = np.array([MAX_SHIFT * w, MAX_SHIFT * h, MAX_ROT, math.log(1.05)])
    out: list[np.ndarray] = []
    worst = 0.0
    for k in range(n):
        M = np.linalg.inv(compose(*S[k])) @ compose(*P[k])
        tx, ty, ang, ls = decompose(M)
        tx, ty, ang, ls = (float(np.clip(v, -m, m)) for v, m in zip((tx, ty, ang, ls), lim))
        M = compose(tx, ty, ang, ls)
        out.append(M)
        worst = max(worst, _border_need(M, w, h))
    return out, min(max(worst, 1.0), MAX_MARGIN)


def _border_need(M: np.ndarray, w: int, h: int) -> float:
    """M ile taşınan kare, merkez çevresinde kaç kat büyütülürse çıktıyı tamamen kaplar."""
    cx, cy = w / 2, h / 2
    T = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1.0]])
    Mc = T @ M @ np.linalg.inv(T)  # merkez orijinde; çıktı köşeleri ±(cx, cy)
    inv = np.linalg.inv(Mc)
    need = 1.0
    for sx, sy in ((-cx, -cy), (cx, -cy), (cx, cy), (-cx, cy)):
        u, v, _ = inv @ np.array([sx, sy, 1.0])  # çıktı köşesinin kaynak karedeki yeri
        need = max(need, abs(u) / cx, abs(v) / cy)
    return need


def margin_matrix(margin: float, size: tuple[int, int]) -> np.ndarray:
    """Merkez çevresinde `margin` kat büyütme (3x3)."""
    cx, cy = size[0] / 2, size[1] / 2
    return np.array([[margin, 0, cx - margin * cx], [0, margin, cy - margin * cy], [0, 0, 1.0]])


def analyse(frames, progress=None) -> tuple[list[np.ndarray], tuple[int, int]]:
    """Kare yineleyicisi (BGR) → kare başına W_t listesi ve (w, h). Sıralı; `CameraMotion` kullanır.
    Kestirilemeyen/kesme adımları kimlik sayılır (yol sıçramaz)."""
    cm = CameraMotion()
    paths: list[np.ndarray] = []
    size = (0, 0)
    for i, fr in enumerate(frames):
        if i == 0:
            size = (fr.shape[1], fr.shape[0])
        cm.step(fr)
        paths.append(cm.W.copy())
        if progress and i % 25 == 0:
            progress(i)
    return paths, size


def plan(frames, fps: float, window_s: float = 1.0, progress=None):
    """analyse + corrections → (düzeltmeler, margin, (w, h))."""
    paths, size = analyse(frames, progress)
    cors, margin = corrections(paths, fps, size, window_s)
    return cors, margin, size


def render_matrix(cors_t: np.ndarray, margin: float, size: tuple[int, int]) -> np.ndarray:
    """Kare t için kaynak → sabitlenmiş (büyütülmüş) görüntü, 3x3."""
    return margin_matrix(margin, size) @ cors_t
