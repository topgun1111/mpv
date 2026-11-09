"""YOLO (ONNX) person detector: ön işleme, çıktı çözümleme, NMS.

Akış: BGR kare -> letterbox -> [1,3,H,W] float tensör -> ONNX Runtime -> `decode_yolo`
(YOLOv8/YOLO11 çıktısı `[1, 4+nc, N]`) -> skor eşiği -> NMS -> orijinal kare koordinatında
`Detection` listesi.

Saf fonksiyonlar (`letterbox`, `preprocess`, `decode_yolo`, `nms`, `select_providers`) gerçek model
olmadan test edilebilir. `onnxruntime` yalnızca `Detector` gerçek bir model yüklerken içe aktarılır.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .geometry import BBox

PERSON_CLASS = 0  # COCO

_PROVIDER_NAMES = {
    "dml": "DmlExecutionProvider",
    "cuda": "CUDAExecutionProvider",
    "cpu": "CPUExecutionProvider",
}
_CPU = _PROVIDER_NAMES["cpu"]
_MAX_CANDIDATES = 300  # NMS öncesi en yüksek skorlu aday sayısı


@dataclass(frozen=True)
class Detection:
    bbox: BBox  # orijinal kare pikseli
    score: float
    cls: int = PERSON_CLASS


@dataclass(frozen=True)
class LetterboxInfo:
    scale: float  # orijinal -> letterbox ölçeği
    pad_x: int  # sol boşluk (px)
    pad_y: int  # üst boşluk (px)


def letterbox(
    frame: np.ndarray, size: tuple[int, int] = (640, 640), color: int = 114
) -> tuple[np.ndarray, LetterboxInfo]:
    """En-boy oranını koruyarak `size=(H, W)` içine yerleştirir, kalanı gri doldurur."""
    import cv2

    th, tw = size
    h, w = frame.shape[:2]
    r = min(th / h, tw / w)
    nw, nh = max(1, round(w * r)), max(1, round(h * r))
    img = frame
    if (nw, nh) != (w, h):
        img = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
    left, top = (tw - nw) // 2, (th - nh) // 2
    img = cv2.copyMakeBorder(
        img, top, th - nh - top, left, tw - nw - left, cv2.BORDER_CONSTANT, value=(color,) * 3
    )
    return img, LetterboxInfo(r, left, top)


def preprocess(
    frame_bgr: np.ndarray, size: tuple[int, int] = (640, 640), fp16: bool = False
) -> tuple[np.ndarray, LetterboxInfo]:
    """BGR uint8 HxWx3 -> RGB float [1,3,H,W] (0..1) + letterbox bilgisi."""
    img, info = letterbox(frame_bgr, size)
    x = img[:, :, ::-1].transpose(2, 0, 1)[None]  # BGR->RGB, HWC->NCHW
    x = np.ascontiguousarray(x, dtype=np.float16 if fp16 else np.float32)
    x /= 255.0
    return x, info


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thres: float) -> list[int]:
    """Klasik NMS. boxes: [N,4] (x1,y1,x2,y2). Seçilen indeksleri skor sırasıyla döndürür."""
    if len(boxes) == 0:
        return []
    areas = np.maximum(boxes[:, 2] - boxes[:, 0], 0) * np.maximum(boxes[:, 3] - boxes[:, 1], 0)
    order = np.argsort(-scores, kind="stable")
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        rest = order[1:]
        if rest.size == 0:
            break
        xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.maximum(xx2 - xx1, 0) * np.maximum(yy2 - yy1, 0)
        iou = inter / np.maximum(areas[i] + areas[rest] - inter, 1e-9)
        order = rest[iou <= iou_thres]
    return keep


def decode_yolo(
    output: np.ndarray,
    info: LetterboxInfo,
    frame_w: int,
    frame_h: int,
    conf_thres: float = 0.25,
    iou_thres: float = 0.45,
    person_class: int = PERSON_CLASS,
    max_det: int = 100,
) -> list[Detection]:
    """YOLOv8/YOLO11 ham çıktısını (`[1,4+nc,N]` veya `[1,N,4+nc]`) `Detection` listesine çevirir.

    Satır biçimi: cx, cy, w, h (letterbox pikseli) + sınıf skorları (objectness yok).
    Yalnızca `person_class` skoru kullanılır.
    """
    out = np.asarray(output)
    if out.ndim == 3:
        if out.shape[0] != 1:
            raise ValueError(f"Yalnızca batch=1 desteklenir, çıktı şekli {out.shape}")
        out = out[0]
    if out.ndim != 2:
        raise ValueError(f"Beklenmeyen çıktı şekli: {np.asarray(output).shape}")
    if out.shape[0] < out.shape[1]:  # [4+nc, N] -> [N, 4+nc]
        out = out.T
    if out.shape[1] <= 4 + person_class:
        raise ValueError(f"Çıktıda person sınıfı yok, şekil {out.shape}")
    out = out.astype(np.float32, copy=False)

    scores = out[:, 4 + person_class]
    idx = np.flatnonzero(scores >= conf_thres)
    if idx.size == 0:
        return []
    if idx.size > _MAX_CANDIDATES:
        idx = idx[np.argsort(-scores[idx])[:_MAX_CANDIDATES]]
    rows, scores = out[idx], scores[idx]

    cx, cy, w, h = rows[:, 0], rows[:, 1], rows[:, 2], rows[:, 3]
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] - info.pad_x) / info.scale
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] - info.pad_y) / info.scale
    boxes[:, [0, 2]] = np.clip(boxes[:, [0, 2]], 0, frame_w)
    boxes[:, [1, 3]] = np.clip(boxes[:, [1, 3]], 0, frame_h)

    valid = ((boxes[:, 2] - boxes[:, 0]) >= 1.0) & ((boxes[:, 3] - boxes[:, 1]) >= 1.0)
    boxes, scores = boxes[valid], scores[valid]
    keep = nms(boxes, scores, iou_thres)[:max_det]
    return [
        Detection(BBox(*(float(v) for v in boxes[i])), float(scores[i]), person_class)
        for i in keep
    ]


def select_providers(available: list[str], device: str = "auto") -> list[str]:
    """Cihaz tercihine göre ONNX Runtime provider sırası. CPU her zaman son çare olarak kalır.

    auto: DirectML -> CUDA -> CPU. İstenen cihaz yoksa sessizce CPU'ya düşer.
    """
    device = device.lower()
    if device == "auto":
        order = [_PROVIDER_NAMES["dml"], _PROVIDER_NAMES["cuda"], _CPU]
    elif device in _PROVIDER_NAMES:
        order = [_PROVIDER_NAMES[device], _CPU]
    else:
        raise ValueError(f"Bilinmeyen cihaz '{device}' (auto, dml, cuda, cpu)")
    chosen = [p for p in dict.fromkeys(order) if p in available]
    return chosen or [_CPU]


def resolve_model_path(path: str | Path) -> Path:
    """Göreli yol önce çalışma klasöründe, sonra proje kökünde (tracker/ üstü) aranır."""
    p = Path(path)
    if p.is_absolute() or p.exists():
        return p
    alt = Path(__file__).resolve().parent.parent / p
    return alt if alt.exists() else p


class Detector:
    """ONNX Runtime ile YOLO person tespiti.

    `session` verilirse (test/özel kullanım) model yüklenmez; `get_inputs/run/get_providers`
    arayüzü yeterlidir.
    """

    def __init__(
        self,
        model_path: str | Path = "models/yolov8n.onnx",
        conf_thres: float = 0.25,
        iou_thres: float = 0.45,
        input_size: int = 640,
        device: str = "auto",
        person_class: int = PERSON_CLASS,
        max_det: int = 100,
        session: Any = None,
    ) -> None:
        self.conf_thres = conf_thres
        self.iou_thres = iou_thres
        self.person_class = person_class
        self.max_det = max_det
        if session is None:
            session = self._open_session(resolve_model_path(model_path), device)
        self.session = session
        inp = session.get_inputs()[0]
        self.input_name: str = inp.name
        self.fp16 = "float16" in str(getattr(inp, "type", ""))
        shape = list(getattr(inp, "shape", []) or [])
        h = shape[2] if len(shape) == 4 and isinstance(shape[2], int) else input_size
        w = shape[3] if len(shape) == 4 and isinstance(shape[3], int) else input_size
        self.size: tuple[int, int] = (int(h), int(w))

    @staticmethod
    def _open_session(path: Path, device: str) -> Any:
        if not path.is_file():
            raise FileNotFoundError(
                f"Model bulunamadı: {path}\n"
                "YOLOv8/YOLO11 person modelini ONNX olarak 'models/' klasörüne koy "
                "(ör. yolov8n.onnx; dışa aktarma: yolo export model=yolov8n.pt format=onnx)."
            )
        import onnxruntime as ort

        providers = select_providers(ort.get_available_providers(), device)
        opts = ort.SessionOptions()
        if _PROVIDER_NAMES["dml"] in providers:  # DirectML önerisi
            opts.enable_mem_pattern = False
            opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        return ort.InferenceSession(str(path), sess_options=opts, providers=providers)

    @property
    def providers(self) -> list[str]:
        return list(self.session.get_providers())

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        """BGR uint8 HxWx3 kare -> skora göre sıralı person tespitleri (kare pikseli)."""
        if frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
            raise ValueError(f"BGR HxWx3 kare bekleniyor, şekil {frame_bgr.shape}")
        h, w = frame_bgr.shape[:2]
        x, info = preprocess(frame_bgr, self.size, self.fp16)
        out = self.session.run(None, {self.input_name: x})[0]
        return decode_yolo(
            out, info, w, h, self.conf_thres, self.iou_thres, self.person_class, self.max_det
        )
