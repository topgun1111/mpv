"""Vücut parçası takibi: YOLOv8-pose (ONNX) çıktısından 17 COCO eklem noktası.

Sağ tık bir eklemin (ayak bileği, diz, bilek...) yakınına yapılırsa o eklem izlenir; uzaktaysa
eski nesne takibi (point.py) çalışır. Model: `models/yolov8s-pose.onnx` (Ultralytics, AGPL-3.0:
yalnız kişisel kullanım). Çıktı `[1, 56, N]`: cx, cy, w, h, skor + 17 x (x, y, güven).
Saf fonksiyonlar (`decode_yolo_pose`, `nearest_keypoint`) model olmadan test edilir.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .detector import (
    _MAX_CANDIDATES,
    Detector,
    LetterboxInfo,
    nms,
    preprocess,
    resolve_model_path,
)
from .geometry import BBox

KEYPOINT_NAMES = (
    "burun", "sol göz", "sağ göz", "sol kulak", "sağ kulak", "sol omuz", "sağ omuz",
    "sol dirsek", "sağ dirsek", "sol bilek", "sağ bilek", "sol kalça", "sağ kalça",
    "sol diz", "sağ diz", "sol ayak bileği", "sağ ayak bileği",
)
N_KPT = len(KEYPOINT_NAMES)


@dataclass(frozen=True)
class Pose:
    bbox: BBox
    score: float
    kpts: np.ndarray  # [17, 3]: x, y (kare pikseli), güven


def decode_yolo_pose(
    output: np.ndarray,
    info: LetterboxInfo,
    frame_w: int,
    frame_h: int,
    conf_thres: float = 0.25,
    iou_thres: float = 0.45,
    max_det: int = 20,
) -> list[Pose]:
    """YOLOv8-pose ham çıktısı (`[1,56,N]` ya da `[1,N,56]`) -> `Pose` listesi (kare pikseli)."""
    out = np.asarray(output)
    if out.ndim == 3:
        if out.shape[0] != 1:
            raise ValueError(f"Yalnızca batch=1 desteklenir, çıktı şekli {out.shape}")
        out = out[0]
    if out.ndim != 2:
        raise ValueError(f"Beklenmeyen çıktı şekli: {np.asarray(output).shape}")
    if out.shape[0] == 5 + 3 * N_KPT and out.shape[1] != out.shape[0]:  # [56, N] -> [N, 56]
        out = out.T
    if out.shape[1] != 5 + 3 * N_KPT:
        raise ValueError(f"Pose çıktısı [N, {5 + 3 * N_KPT}] bekleniyor, şekil {out.shape}")
    out = out.astype(np.float32, copy=False)
    scores = out[:, 4]
    idx = np.flatnonzero(scores >= conf_thres)
    if idx.size == 0:
        return []
    if idx.size > _MAX_CANDIDATES:
        idx = idx[np.argsort(-scores[idx])[:_MAX_CANDIDATES]]
    rows, scores = out[idx], scores[idx]

    cx, cy, w, h = rows[:, 0], rows[:, 1], rows[:, 2], rows[:, 3]
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    boxes[:, [0, 2]] = np.clip((boxes[:, [0, 2]] - info.pad_x) / info.scale, 0, frame_w)
    boxes[:, [1, 3]] = np.clip((boxes[:, [1, 3]] - info.pad_y) / info.scale, 0, frame_h)
    kp = rows[:, 5:].reshape(-1, N_KPT, 3).copy()
    kp[:, :, 0] = (kp[:, :, 0] - info.pad_x) / info.scale
    kp[:, :, 1] = (kp[:, :, 1] - info.pad_y) / info.scale

    valid = ((boxes[:, 2] - boxes[:, 0]) >= 1.0) & ((boxes[:, 3] - boxes[:, 1]) >= 1.0)
    boxes, scores, kp = boxes[valid], scores[valid], kp[valid]
    keep = nms(boxes, scores, iou_thres)[:max_det]
    return [Pose(BBox(*(float(v) for v in boxes[i])), float(scores[i]), kp[i]) for i in keep]


def nearest_keypoint(
    poses: list[Pose], px: float, py: float, tol: float = 0.12, min_conf: float = 0.35
) -> tuple[int, int] | None:
    """(px, py) noktasına en yakın güvenilir eklem: (poz indeksi, eklem indeksi).

    Uzaklık sınırı kişi boyunun `tol` oranıdır; hiçbiri yeterince yakın değilse None.
    """
    best: tuple[float, int, int] | None = None
    for i, p in enumerate(poses):
        limit = tol * max(p.bbox.y2 - p.bbox.y1, 1.0)
        for k in range(N_KPT):
            x, y, c = p.kpts[k]
            if c < min_conf:
                continue
            d = float(np.hypot(x - px, y - py))
            if d <= limit and (best is None or d < best[0]):
                best = (d, i, k)
    return None if best is None else (best[1], best[2])


def _iou(a: BBox, b: BBox) -> float:
    iw = min(a.x2, b.x2) - max(a.x1, b.x1)
    ih = min(a.y2, b.y2) - max(a.y1, b.y1)
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    ua = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
    return inter / max(ua, 1e-9)


class PoseEstimator:
    """ONNX Runtime ile YOLOv8-pose. `session` verilirse model yüklenmez (test)."""

    def __init__(self, model_path: str | Path = "models/yolov8s-pose.onnx", conf_thres: float = 0.3,
                 iou_thres: float = 0.45, input_size: int = 640, device: str = "auto",
                 session: Any = None) -> None:
        self.conf_thres, self.iou_thres = conf_thres, iou_thres
        if session is None:
            session = Detector._open_session(resolve_model_path(model_path), device)
        self.session = session
        inp = session.get_inputs()[0]
        self.input_name: str = inp.name
        self.fp16 = "float16" in str(getattr(inp, "type", ""))
        shape = list(getattr(inp, "shape", []) or [])
        h = shape[2] if len(shape) == 4 and isinstance(shape[2], int) else input_size
        w = shape[3] if len(shape) == 4 and isinstance(shape[3], int) else input_size
        self.size: tuple[int, int] = (int(h), int(w))

    def estimate(self, frame_bgr: np.ndarray) -> list[Pose]:
        h, w = frame_bgr.shape[:2]
        x, info = preprocess(frame_bgr, self.size, self.fp16)
        out = self.session.run(None, {self.input_name: x})[0]
        return decode_yolo_pose(out, info, w, h, self.conf_thres, self.iou_thres)


class KeypointTracker:
    """Seçilen kişinin seçilen eklemini her karede pozdan okur (point.py ile aynı arayüz).

    Kişi, önceki kutuya en çok benzeyen (IoU / merkez yakınlığı) pozla eşlenir. Eklem güveni
    düşükse ya da kişi bulunamazsa `update` None döner (denetleyici "hedef kayıp" akışına girer).
    """

    visible = True

    def __init__(self, estimator: PoseEstimator, pose: Pose, kp: int, box_frac: float = 0.10,
                 min_conf: float = 0.35) -> None:
        self.est, self.kp, self.box_frac, self.min_conf = estimator, kp, box_frac, min_conf
        self.label = KEYPOINT_NAMES[kp]
        self._person = pose.bbox
        self._pos = (float(pose.kpts[kp][0]), float(pose.kpts[kp][1]))

    @property
    def bbox(self) -> BBox:
        half = max(self.box_frac * (self._person.y2 - self._person.y1), 8.0) / 2
        return BBox(self._pos[0] - half, self._pos[1] - half,
                    self._pos[0] + half, self._pos[1] + half)

    def update(self, frame_bgr: np.ndarray) -> BBox | None:
        prev = self._person
        ph = max(prev.y2 - prev.y1, 1.0)
        best, best_s = None, 0.0
        for p in self.est.estimate(frame_bgr):
            d = float(np.hypot(p.bbox.cx - prev.cx, p.bbox.cy - prev.cy)) / ph
            s = _iou(prev, p.bbox) + max(0.0, 1.0 - d)  # yakın + örtüşen
            if (_iou(prev, p.bbox) > 0.1 or d < 0.6) and s > best_s:
                best, best_s = p, s
        if best is None or best.kpts[self.kp][2] < self.min_conf:
            return None
        self._person = best.bbox
        self._pos = (float(best.kpts[self.kp][0]), float(best.kpts[self.kp][1]))
        return self.bbox
