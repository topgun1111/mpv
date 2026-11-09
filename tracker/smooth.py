"""Yumuşatma: dead-zone + EMA (görünüm) ve Kalman + hız yönünde lookahead (hedef kutusu)."""
from __future__ import annotations

from .geometry import BBox, View


class Ema:
    def __init__(self, alpha: float):
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha (0, 1] aralığında olmalı")
        self.alpha = alpha
        self.value: float | None = None

    def update(self, v: float) -> float:
        self.value = v if self.value is None else self.value + self.alpha * (v - self.value)
        return self.value

    def reset(self) -> None:
        self.value = None


class DeadZone:
    """Girdi, mevcut değerden `radius` kadar uzaklaşmadıkça çıktı sabit kalır."""

    def __init__(self, radius: float):
        self.radius = radius
        self.value: float | None = None

    def update(self, v: float) -> float:
        if self.value is None:
            self.value = v
        else:
            d = v - self.value
            if abs(d) > self.radius:
                self.value += d - self.radius * (1 if d > 0 else -1)
        return self.value

    def reset(self) -> None:
        self.value = None


class ViewSmoother:
    def __init__(
        self,
        alpha_pos: float = 0.15,
        alpha_zoom: float = 0.08,
        dead_zone_pos: float = 0.01,
        dead_zone_zoom: float = 0.05,
    ):
        self._dz = [DeadZone(dead_zone_zoom), DeadZone(dead_zone_pos), DeadZone(dead_zone_pos)]
        self._ema = [Ema(alpha_zoom), Ema(alpha_pos), Ema(alpha_pos)]

    def update(self, view: View) -> View:
        raw = (view.zoom, view.pan_x, view.pan_y)
        out = [e.update(d.update(v)) for d, e, v in zip(self._dz, self._ema, raw, strict=True)]
        return View(*out)

    def reset(self) -> None:
        for s in (*self._dz, *self._ema):
            s.reset()


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class Kalman1D:
    """Tek eksen sabit hız Kalman süzgeci (durum: konum, hız). Zaman tabanlı: `predict(dt)` sn.

    Süreç gürültüsü beyaz ivme modeli (`accel` = ivme std, birim/sn²); `meas` ölçüm std.
    """

    def __init__(self, x0: float, meas: float, accel: float, v_std0: float = 0.5):
        self.p, self.v = x0, 0.0
        self.r = meas * meas
        self.q = accel * accel
        self.p00, self.p01, self.p11 = self.r, 0.0, v_std0 * v_std0

    def predict(self, dt: float) -> None:
        if dt <= 0.0:
            return
        self.p += self.v * dt
        p00 = self.p00 + dt * (2 * self.p01) + dt * dt * self.p11 + self.q * dt**4 / 4
        p01 = self.p01 + dt * self.p11 + self.q * dt**3 / 2
        self.p11 += self.q * dt * dt
        self.p00, self.p01 = p00, p01

    def update(self, z: float) -> None:
        s = self.p00 + self.r
        k0, k1 = self.p00 / s, self.p01 / s
        y = z - self.p
        self.p += k0 * y
        self.v += k1 * y
        p00 = self.p00 - k0 * self.p00
        p01 = self.p01 - k0 * self.p01
        p11 = self.p11 - k1 * self.p01
        self.p00, self.p01, self.p11 = p00, p01, p11


class BoxFilter:
    """Hedef kutusunu (cx, cy, w, h) Kalman ile süzer ve hız yönünde ileri öteler (lookahead).

    Birimler çağıranın seçimidir (denetleyici kareye göre normalize 0..1 kutu verir); `accel` ve
    `meas` aynı birimdedir. Boyut (w, h) kanalları daha az ivme gürültüsüyle (`size_ratio`)
    daha yumuşak tutulur. `update` zaman damgası (sn) ister: geri atlama veya `max_gap`'ten uzun
    boşlukta süzgeç ölçümden yeniden başlar (eski hız geçersizdir).
    """

    def __init__(
        self,
        accel: float = 0.5,
        meas: float = 0.01,
        size_ratio: float = 0.2,
        max_gap: float = 1.0,
    ):
        self.accel, self.meas = accel, meas
        self.size_ratio, self.max_gap = size_ratio, max_gap
        self._f: list[Kalman1D] | None = None
        self._t: float | None = None

    def reset(self) -> None:
        self._f, self._t = None, None

    @property
    def active(self) -> bool:
        return self._f is not None

    @property
    def velocity(self) -> tuple[float, float]:
        """Merkez hızı (birim/sn); süzgeç yokken (0, 0)."""
        return (self._f[0].v, self._f[1].v) if self._f else (0.0, 0.0)

    def update(self, box: BBox, t: float) -> BBox:
        vals = (box.cx, box.cy, box.w, box.h)
        restart = (
            self._f is None
            or self._t is None
            or t < self._t - 1e-6
            or t - self._t > self.max_gap
        )
        if restart:
            acc = (self.accel, self.accel, self.accel * self.size_ratio,
                   self.accel * self.size_ratio)
            self._f = [Kalman1D(v, self.meas, a) for v, a in zip(vals, acc, strict=True)]
        else:
            assert self._f is not None and self._t is not None
            dt = t - self._t
            for f, v in zip(self._f, vals, strict=True):
                f.predict(dt)
                f.update(v)
        self._t = t
        return self._box(0.0, 0.0)

    def lookahead(self, ahead_s: float, max_lead: float) -> BBox:
        """Süzülmüş kutu, merkez hızı * `ahead_s` kadar ileri ötelenmiş (her eksen ±max_lead)."""
        if self._f is None:
            raise ValueError("lookahead için önce update çağrılmalı")
        if ahead_s <= 0.0:
            return self._box(0.0, 0.0)
        dx = _clamp(self._f[0].v * ahead_s, -max_lead, max_lead)
        dy = _clamp(self._f[1].v * ahead_s, -max_lead, max_lead)
        return self._box(dx, dy)

    def _box(self, dx: float, dy: float) -> BBox:
        assert self._f is not None
        cx, cy = self._f[0].p + dx, self._f[1].p + dy
        w, h = max(self._f[2].p, 0.0), max(self._f[3].p, 0.0)
        return BBox(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
