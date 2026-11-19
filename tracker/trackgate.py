"""S5: SAM bellek takibinin tıkanma (occlusion) kapısı. Android `core/TrackGate.kt` portu (saf matematik, IO yok).

 1. `remember`: belleğe yalnız temiz, güvenli, normal boyutlu kareler girer (yarı örtülü özne ya da örten nesne
    — ör. masa — "özne" olmasın).
 2. `accept`: maske çok uzağa sıçradıysa ya da kayıptan sonra yeniden belirdiyse özneye benzemeli (nesne
    işaretçilerinin kosinüsü). Eşik bu taramanın KENDİ temiz karelerinden öğrenilir (sabit kalibrasyon yok);
    yeterli temiz kare görülene kadar her şey geçer.
 3. `size`: kısmen örtülü özne küçük maske verir; kamera görünen parçaya zoom yapmasın diye son temiz boyut tutulur.

Sabitler Kotlin ile AYNI (`tests/test_trackgate.py` kaynağı okuyup karşılaştırır).
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

REMEMBER_CONF = 0.6
REMEMBER_MIN_RATIO = 0.6
REMEMBER_MAX_RATIO = 1.6
PARTIAL_RATIO = 0.6
MIN_LEARN = 3
JUMP_K = 0.75
RESUME_K = 0.6
# Üst üste izlenen ama hiç "temiz" olmayan kareler (özne gerçekten boyut değiştirdi): yine de uyum sağla, kilitlenme.
FORCE_CLEAN_FRAMES = 12
# Uzun kayıp: özne başka poz/açı/ışıkta dönebilir. RELAX_FROM kayıp kareden sonra gereken benzerlik RELAX_SPAN
# karede doğrusal olarak değerinin RELAX_FLOOR'una iner → "kayıp"ta sonsuza dek kilitlenmez.
RELAX_FROM = 12
RELAX_SPAN = 24
RELAX_FLOOR = 0.5


def relax(lost: int) -> float:
    p = min(max(lost - RELAX_FROM, 0), RELAX_SPAN) / RELAX_SPAN
    return 1.0 - (1.0 - RELAX_FLOOR) * p


def remember(conf: float, ratio: float) -> bool:
    """Kare belleğe girebilir mi (güven yeterli, alan oranı normal)?"""
    return conf >= REMEMBER_CONF and REMEMBER_MIN_RATIO <= ratio <= REMEMBER_MAX_RATIO


def cosine(a: Sequence[float] | np.ndarray, b: Sequence[float] | np.ndarray) -> float:
    """Kosinüs benzerliği; boş, boyut uyuşmaz ya da sıfır vektörde 0."""
    x, y = np.asarray(a, np.float64).reshape(-1), np.asarray(b, np.float64).reshape(-1)
    if x.size == 0 or x.size != y.size:
        return 0.0
    na, nb = float(x @ x), float(y @ y)
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return float(x @ y) / (math.sqrt(na) * math.sqrt(nb))


def is_jump(dist: float, box_size: float, lost: int) -> bool:
    """Öznenin son yerinden uzak mı? Boyutu ve her kayıp kareyi hesaba katar (~8 kayıp karede hemen her yer serbest)."""
    return dist > max(box_size, 0.05) * (1.5 + 0.75 * min(lost, 8))


def size(ratio: float, w: float, h: float, stable_w: float, stable_h: float) -> tuple[float, float]:
    """Kısmen örtülü maskede (oran < PARTIAL_RATIO) son temiz boyut; bilinmiyorsa ham boyut."""
    if ratio < PARTIAL_RATIO and stable_w > 0.0 and stable_h > 0.0:
        return stable_w, stable_h
    return w, h


class TrackGate:
    """Durumlu kısım: temiz karelerden öğrenilen benzerlik referansı ve sayaçlar."""

    def __init__(self) -> None:
        self.ref = 0.0
        self.learned = 0
        self.accepted = 0
        self.rejected = 0

    def learn(self, sim: float) -> None:
        """Temiz, bozulmamış karenin benzerliği: koşan ortalama = bu videoda "aynı özne" neye benzer."""
        self.ref = sim if self.learned == 0 else 0.9 * self.ref + 0.1 * sim
        self.learned += 1

    def note(self) -> None:
        self.accepted += 1

    def needed(self, dist: float, box_size: float, lost: int) -> float:
        resume = RESUME_K * self.ref if lost > 0 else 0.0
        jump = JUMP_K * self.ref if is_jump(dist, box_size, lost) else 0.0
        return relax(lost) * max(resume, jump)

    def accept(self, dist: float, box_size: float, lost: int, sim: float) -> bool:
        ok = self.learned < MIN_LEARN or sim >= self.needed(dist, box_size, lost)
        if not ok:
            self.rejected += 1
        return ok

    def summary(self) -> str:
        return (f"kapı: {self.accepted} kabul, {self.rejected} ret "
                f"(benzerlik ref {self.ref:.2f}, {self.learned} temiz kare)")
