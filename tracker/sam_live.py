"""F2: mpv'de çizilen dikdörtgen -> canlı SAM takibi.

`LiveController` nesne izleyiciden `bbox`, `update(kare) -> BBox | None`, `label` ve `visible`
bekler. `SamPointTracker` bunu `sam_track.track_video` üzerinden sağlar: üreteç tembeldir, bu
yüzden canlı kareler bir `_Feed` ile içeri itilir (her `update` = bir kare itilir + üretecin bir
kaydı çekilir). Böylece S4/S5 bellek döngüsü ve kapı ÇEVRİMDIŞI ile BİREBİR aynı kodla koşar
(kopya yok).

`make_factory`: dikdörtgen + SAM modelleri hazırsa SAM, değilse (tek tık, model yok,
`sam_live=False`, yükleme hatası) eski `WorldPointTracker`. Motor ilk dikdörtgende tembel
yüklenir ve (varyant, cihaz) için saklanır.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import errlog
from .geometry import BBox
from .sam_engine import DEC, ENC, MEMORY_GRAPHS, SamEngine, to_frame_box
from .sam_track import NoInitialMask, track_video

LABEL = "SAM"
_VARIANT_DIRS = {"edgetam": "edgetam", "sam2_small": "small"}


def model_dir(cfg) -> Path:
    """Panelde seçili SAM ailesinin klasörü (`sam-models/<edgetam|small>`)."""
    name = _VARIANT_DIRS.get(getattr(cfg, "sam_model_variant", "edgetam"), "edgetam")
    return Path(__file__).resolve().parents[1] / "sam-models" / name


def models_ready(folder: Path) -> bool:
    return all((folder / f"{n}.onnx").is_file() for n in (ENC, DEC, *MEMORY_GRAPHS))


class _Feed:
    """Tek kareli kuyruk: `push` bir kare bırakır, üretecin bir sonraki `next`'i onu alır."""

    def __init__(self) -> None:
        self._item: tuple[float, np.ndarray] | None = None

    def push(self, t: float, frame: np.ndarray) -> None:
        self._item = (t, frame)

    def __iter__(self):
        return self

    def __next__(self) -> tuple[float, np.ndarray]:
        item, self._item = self._item, None
        if item is None:
            raise StopIteration
        return item


class SamPointTracker:
    """Dikdörtgenle başlayan, kare kare SAM belleğiyle izlenen nesne. Kayıpta `update` None döner;
    bellek korunur, nesne geri gelirse (kapıdan geçerse) takip sürer."""

    label = LABEL

    def __init__(self, engine: SamEngine, frame: np.ndarray,
                 rect: tuple[float, float, float, float],
                 t: float = 0.0, *, use_gate: bool = True) -> None:
        self._h, self._w = frame.shape[:2]
        self._feed = _Feed()
        self._gen = track_video(engine, self._feed, rect, use_gate=use_gate)
        self.visible = True
        self.dead = False
        self.last = None  # son TrackRecord (önizleme/günlük için)
        self._box = BBox(*rect)
        box = self._step(frame, t)  # ilk kare: dikdörtgenden maske; yoksa NoInitialMask fırlar
        if box is not None:
            self._box = box

    @property
    def bbox(self) -> BBox:
        return self._box

    def _step(self, frame: np.ndarray, t: float) -> BBox | None:
        self._feed.push(t, frame)
        rec = next(self._gen)
        self.last = rec
        if not rec.tracked or rec.box is None:
            return None
        x1, y1, x2, y2 = to_frame_box(rec.box, self._w, self._h)
        return BBox(x1, y1, x2, y2)

    def update(self, frame: np.ndarray, t: float | None = None) -> BBox | None:
        if self.dead:
            return None
        if frame.shape[:2] != (self._h, self._w):  # çözünürlük değişti: bellek geçersiz
            self.dead = True
            errlog.record("SAM canlı takip", "kare boyutu değişti; nesneyi yeniden seçin")
            return None
        try:
            box = self._step(frame, 0.0 if t is None else t)
        except Exception as e:  # noqa: BLE001 - takip döngüsü düşmemeli
            self.dead = True
            errlog.record("SAM canlı takip", e)
            return None
        self.visible = box is not None
        if box is not None:
            self._box = box
        return box

    def close(self) -> None:
        self._gen.close()


def make_factory(fallback, engine_factory=None):
    """`LiveController(point_factory=)` imzası: (kare, px, py, cfg, box=None) -> izleyici.

    `fallback`: eski fabrika. `engine_factory(cfg) -> SamEngine | None` testte sahte motor verir."""
    cache: dict[tuple[str, str], SamEngine | None] = {}

    def load(cfg):
        if engine_factory is not None:
            return engine_factory(cfg)
        key = (getattr(cfg, "sam_model_variant", "edgetam"), getattr(cfg, "device", "auto"))
        if key not in cache:
            folder = model_dir(cfg)
            if not models_ready(folder):
                cache[key] = None
            else:
                try:
                    cache[key] = SamEngine(folder, cfg.device, memory=True)
                except Exception as e:  # noqa: BLE001 - model bozuk/GPU yok: eski izleyici
                    errlog.record("SAM modeli yükleme", e)
                    cache[key] = None
        return cache[key]

    def factory(frame, px: float, py: float, cfg, box=None):
        if box is None or not getattr(cfg, "sam_live", True):
            return fallback(frame, px, py, cfg, box=box)
        engine = load(cfg)
        if engine is None:
            return fallback(frame, px, py, cfg, box=box)
        try:
            return SamPointTracker(engine, frame, tuple(float(v) for v in box))
        except NoInitialMask:
            raise  # LiveController "başlatılamadı" der; kullanıcı dikdörtgeni yeniden çizer
        except Exception as e:  # noqa: BLE001
            errlog.record("SAM canlı takip başlatma", e)
            return fallback(frame, px, py, cfg, box=box)

    return factory
