"""Detector + ByteTracker birleşimi: kare başına step(frame)."""
from __future__ import annotations

from .bytetrack import ByteTracker, Track


class Pipeline:
    def __init__(self, detector, tracker: ByteTracker | None = None):
        self.detector = detector
        self.tracker = tracker or ByteTracker()

    def step(self, frame_bgr) -> list[Track]:
        return self.tracker.update(self.detector.detect(frame_bgr))

    def reset(self) -> None:
        self.tracker.reset()


class NullPipeline:
    """Person modeli yokken: iz üretmez. Yalnız sağ tık nesne takibi (point.py) çalışır."""

    def step(self, frame_bgr) -> list[Track]:
        return []

    def reset(self) -> None:
        pass
