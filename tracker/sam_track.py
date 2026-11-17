"""S4: PC SAM bellek döngüsü (ileri takip). Android `SamEngine.kt::walkMemory` portu, KAPISIZ.

Akış (kare başına bir kez kodlanır):
  ilk kare   : encoder -> decoder (dikdörtgen) -> `sam-memenc` -> `MemoryBank.reset` (yuva 0 = istemli kare)
  sonraki    : encoder -> `sam-memattn` (bellek koşullu gömme) -> `sam-decoder-trk` (istemsiz maske)
               -> izlendiyse `sam-memenc` -> `MemoryBank.push`.
Kayıp kare belleğe HİÇBİR ŞEY eklemez (banka yalnız izlenen kareleri tutar). Banka sabit boyutludur
(`sam-memattn` statik K bellek + P işaretçi yuvası); kare başına tensörler bir sonraki turda atılır.

Karar (izlendi/kayıp), Android ile aynı: object_score > 0, maske boş değil ve
`conf = iou * sigmoid(object_score) * (oran 0.25-4 ise 1, değilse 0.5)` >= `MIN_CONF`.
`oran` = maske alanı / hedefin son temiz alanı (EMA 0.8/0.2 yalnız izlenen karelerde).

`accepted` alanı S5'teki TrackGate kararı içindir: kapı henüz yok, bu yüzden HER kayıtta True'dur
(izlendi/kayıp ayrımı `state`'tedir). Kayıtlar `<video>.sam.json` dosyasına yazılır; mevcut
`track.json` / `views.json` şeması DEĞİŞMEZ.
"""
from __future__ import annotations

import json
import math
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from . import cache
from .edgetam_bank import MemoryBank
from .sam_engine import SamEngine

MIN_CONF = 0.35  # Android MIN_CONF
RATIO_LO, RATIO_HI = 0.25, 4.0  # alan oranı bu aralıkta değilse güven yarıya iner
RATIO_PENALTY = 0.5
AREA_KEEP = 0.8  # referans alan EMA'sında eski değerin payı
SCHEMA_VERSION = 1
KIND = "sam-track"
FIELDS = ("t", "tracked", "accepted", "x1", "y1", "x2", "y2", "iou", "object_score", "conf", "area", "ratio")
TRACKED, LOST = "tracked", "lost"

Rect = tuple[float, float, float, float]


class NoInitialMask(ValueError):
    """İlk karede dikdörtgenden maske çıkmadı: kullanıcı dikdörtgeni yeniden çizmeli."""


# --- kayıt ---

@dataclass
class TrackRecord:
    index: int  # örneklenen kare sırası (0 = istemli kare)
    t: float  # video zamanı (sn)
    state: str  # TRACKED | LOST
    accepted: bool  # S5'e kadar hep True
    box: tuple[float, float, float, float] | None  # normalize (x1, y1, x2, y2); kayıpta da son aday varsa dolu olabilir
    area: float  # maske alanı / (M*M)
    iou: float
    object_score: float
    conf: float
    ratio: float  # alan / referans alan
    mask: np.ndarray | None = field(default=None, repr=False)  # (M, M) bool; yalnız keep_masks=True

    @property
    def tracked(self) -> bool:
        return self.state == TRACKED


@dataclass
class TrackStats:
    frames: int = 0
    tracked: int = 0
    lost: int = 0
    bank_size: int = 0  # bankadaki geçmiş girdi sayısı (sınırlı kalmalı: <= max(K, P) - 1)

    def add(self, rec: TrackRecord) -> None:
        self.frames += 1
        if rec.tracked:
            self.tracked += 1
        else:
            self.lost += 1


@dataclass
class Mem:
    """Banka girdisi: bir izlenen karenin bellek özniteliği ve nesne işaretçisi."""

    feat: np.ndarray  # (1, *frame_shape)
    ptr: np.ndarray  # (256,)


def confidence(iou: float, object_score: float, ratio: float) -> float:
    """Android `conf`: iou x sigmoid(object_score) x (oran makulse 1, değilse 0.5)."""
    sig = 1.0 / (1.0 + math.exp(-max(min(object_score, 60.0), -60.0)))
    return iou * sig * (1.0 if RATIO_LO <= ratio <= RATIO_HI else RATIO_PENALTY)


# --- video ---

class Clip:
    """`offline.VideoSource` ile `fps` hızında örneklenmiş kareler; `start` sn'den (dahil) başlar.

    `VideoSource(start=)` başlangıç karesini ATLAR; bu yüzden bir adım erken başlatılıp önceki kareler süzülür.
    `max_seconds > 0`: başlangıçtan itibaren bu kadar sn sonra durur.
    """

    def __init__(self, path: str | os.PathLike, fps: float = 10.0, start: float = 0.0,
                 max_seconds: float = 0.0) -> None:
        from .offline import VideoSource

        self.path, self.fps, self.start, self.max_seconds = str(path), fps, max(start, 0.0), max_seconds
        step = 1.0 / max(fps, 0.1)
        self._src = VideoSource(self.path, fps, max(self.start - step, 0.0))
        self.w, self.h, self.src_fps, self.duration = self._src.w, self._src.h, self._src.src_fps, self._src.duration

    def close(self) -> None:
        """Hiç yinelenmediyse (ör. dikdörtgen hatası) VideoCapture'ı bırakır."""
        self._src._cap.release()

    def __iter__(self) -> Iterator[tuple[float, np.ndarray]]:
        it = iter(self._src)
        try:
            for t, frame in it:
                if t + 1e-6 < self.start:
                    continue
                if self.max_seconds > 0 and t - self.start > self.max_seconds + 1e-6:
                    break
                yield t, frame
        finally:
            it.close()  # VideoCapture'ı hemen bırak (break ile erken çıkışta bile)


# --- döngü ---

def _record(i: int, t: float, tracked: bool, cand: Any, iou: float, score: float, conf: float,
            ratio: float, mask: np.ndarray | None) -> TrackRecord:
    return TrackRecord(index=i, t=t, state=TRACKED if tracked else LOST, accepted=True, box=cand.box,
                       area=cand.area, iou=iou, object_score=score, conf=conf, ratio=ratio, mask=mask)


def track_video(engine: SamEngine, frames: Iterable[tuple[float, np.ndarray]], rect: Rect, *,
                normalized: bool = False, keep_masks: bool = False,
                stats: TrackStats | None = None) -> Iterator[TrackRecord]:
    """`frames`: (t, BGR kare) dizisi (ör. `Clip`); ilk kare istemli karedir. Kare başına bir kayıt üretir.

    `rect` ilk karenin pikselinde (`normalized`: 0-1 oranı). İlk karede maske yoksa `NoInitialMask`.
    Tembel: bir kayıt tüketilene kadar sonraki kare çözülmez/işlenmez.
    """
    lay = engine.memory_layout()  # bellek grafikleri yoksa burada (ilk kareden önce) hata
    bank: MemoryBank[Mem] = MemoryBank(lay.k, lay.p)
    ref_area = 0.0
    for i, (t, frame) in enumerate(frames):
        enc = engine.encode(frame)
        if i == 0:
            w, h = enc.size
            r = (rect[0] * w, rect[1] * h, rect[2] * w, rect[3] * h) if normalized else rect
            first = engine.segment_rect(enc, r)
            if first is None:
                raise NoInitialMask("ilk karede maske bulunamadı: dikdörtgeni nesnenin çevresine yeniden çizin")
            bank.reset(Mem(engine.memorize(enc.feat, first.mask_logits, first.object_score), first.obj_ptr))
            cd = first.candidates[first.index]
            ref_area = cd.area
            rec = _record(i, t, True, cd, first.iou, first.object_score, first.iou, 1.0,
                          first.mask.copy() if keep_masks else None)
        else:
            mem_feats = np.concatenate([m.feat for m in bank.mem_slots()], axis=0)  # (K, *frame_shape)
            ptrs = np.stack([m.ptr for m in bank.ptr_slots()])  # (P, 256)
            d = engine.decode_track(enc, engine.condition(enc.feat, mem_feats, ptrs))
            ratio = d.cand.area / ref_area if ref_area > 0 else 1.0
            conf = confidence(d.iou, d.object_score, ratio)
            tracked = d.object_score > 0 and d.cand.area > 0 and conf >= MIN_CONF
            if tracked:  # yalnız izlenen kare belleğe girer
                bank.push(Mem(engine.memorize(enc.feat, d.mask_logits, d.object_score), d.obj_ptr))
                ref_area = AREA_KEEP * ref_area + (1 - AREA_KEEP) * d.cand.area
            rec = _record(i, t, tracked, d.cand, d.iou, d.object_score, conf, ratio,
                          (d.mask_logits > 0) if keep_masks else None)
        del enc  # kare tensörleri bir sonraki turda birikmesin
        if stats is not None:
            stats.add(rec)
            stats.bank_size = bank.size
        yield rec


# --- kayıt dosyası ---

def sam_path(video: str | os.PathLike) -> Path:
    """`x.mp4` -> `x.mp4.sam.json` (yanındaki `.track.json` / `.views.json` ile aynı düzen)."""
    p = Path(video)
    return p.with_name(p.name + ".sam.json")


def _r(v: float | None, n: int) -> float | None:
    return None if v is None else round(float(v), n)


def _row(rec: TrackRecord) -> list[Any]:
    b = rec.box or (None, None, None, None)
    return [_r(rec.t, 4), int(rec.tracked), int(rec.accepted), _r(b[0], 4), _r(b[1], 4), _r(b[2], 4), _r(b[3], 4),
            _r(rec.iou, 3), _r(rec.object_score, 2), _r(rec.conf, 3), _r(rec.area, 4), _r(rec.ratio, 3)]


def make_doc(video: str | os.PathLike, records: list[TrackRecord], *, size: tuple[int, int],
             sample_fps: float, start: float = 0.0, rect: Rect | None = None, rule: str = "best",
             providers: dict[str, Any] | None = None, layout: Any = None,
             timing_ms: dict[str, float] | None = None, complete: bool = True) -> dict[str, Any]:
    """Kayıt belgesi (`track.json` şemasından BAĞIMSIZ). `rect`: ilk karede normalize dikdörtgen."""
    w, h = size
    n_tr = sum(r.tracked for r in records)
    return {
        "version": SCHEMA_VERSION, "kind": KIND, "complete": complete,
        "video": {"path": str(video), "w": w, "h": h}, "vsig": cache.file_sig(video),
        "sample_fps": sample_fps, "start": round(start, 4),
        "rect": [round(v, 5) for v in rect] if rect else None, "rule": rule,
        "providers": providers or {},
        "layout": {"k": layout.k, "p": layout.p, "frame_shape": list(layout.frame_shape)} if layout else None,
        "timing_ms": {k: round(v, 2) for k, v in (timing_ms or {}).items()},
        "counts": {"frames": len(records), "tracked": n_tr, "lost": len(records) - n_tr},
        "fields": list(FIELDS), "records": [_row(r) for r in records],
    }


def save_doc(path: str | os.PathLike, doc: dict[str, Any]) -> Path:
    """Atomik yazım (yarım dosya kalmaz)."""
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, p)
    return p


def load_doc(path: str | os.PathLike) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("kind") != KIND or doc.get("version") != SCHEMA_VERSION:
        raise ValueError(f"SAM kayıt dosyası değil ya da sürüm uyumsuz: {path}")
    if doc.get("fields") != list(FIELDS):
        raise ValueError(f"SAM kayıt alanları beklenenden farklı: {path}")
    return doc


def doc_records(doc: dict[str, Any]) -> list[TrackRecord]:
    """Belgedeki satırları `TrackRecord`'a çevirir (maske yok)."""
    out = []
    for i, row in enumerate(doc["records"]):
        t, tr, acc, x1, y1, x2, y2, iou, score, conf, area, ratio = row
        box = None if x1 is None else (x1, y1, x2, y2)
        out.append(TrackRecord(i, t, TRACKED if tr else LOST, bool(acc), box, area, iou, score, conf, ratio))
    return out


def ms_per_call(engine: SamEngine) -> dict[str, float]:
    """Grafik başına ortalama ms/çağrı (`engine.timing`)."""
    return {n: tot / cnt for n, (tot, cnt) in engine.timing.items() if cnt}
