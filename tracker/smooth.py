"""Yumuşatma: dead-zone + EMA. (Kalman ve lookahead Parça 7'de eklenecek.)"""
from __future__ import annotations

from .geometry import View


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
