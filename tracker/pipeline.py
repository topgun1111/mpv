"""Detector + ByteTracker birleşimi: kare başına step(frame)."""
from __future__ import annotations

from .bytetrack import ByteTracker, Track


class Pipeline:
    """`gmc` (gmc.CameraMotion) verilirse ByteTrack tahmini kamera hareketiyle telafi edilir."""

    def __init__(self, detector, tracker: ByteTracker | None = None, gmc=None):
        self.detector = detector
        self.tracker = tracker or ByteTracker()
        self.gmc = gmc

    def step(self, frame_bgr) -> list[Track]:
        motion = None
        if self.gmc is not None:
            try:
                motion = self.gmc.step(frame_bgr, self.tracker.boxes)
            except Exception:  # kamera kestirimi asla izlemeyi düşürmesin
                motion = None
        return self.tracker.update(self.detector.detect(frame_bgr), motion)

    def reset(self) -> None:
        self.tracker.reset()
        if self.gmc is not None:
            self.gmc.reset()


def make_gmc(cfg):
    """Config.gmc açıksa ve OpenCV varsa CameraMotion, yoksa None."""
    if not getattr(cfg, "gmc", False):
        return None
    try:
        from .gmc import CameraMotion

        return CameraMotion(cam_side=cfg.gmc_side)
    except Exception:
        return None


class NullPipeline:
    """Person modeli yokken: iz üretmez. Yalnız sağ tık nesne takibi (point.py) çalışır."""

    def step(self, frame_bgr) -> list[Track]:
        return []

    def reset(self) -> None:
        pass
