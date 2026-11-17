"""S6: SAM maske konturu + birleşik dikdörtgen önizleme verisi (saf Python; Lua yalnız çizer).

Dosya: `<video>.sam.preview.json` (`preview_path`). Koordinatlar videonun 0-1 oranıdır.
`sam-preview` (dikdörtgen çizildikten sonra onay) ve `sam-track --preview` (işlem sırasında) yazar;
`track.lua` `P` tuşuyla okuyup çizer. Durum etiketi S9'a kadar yer tutucudur (CONFIRM/TRACKED/LOST/NO_MASK/DONE).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

VERSION = 1
MAX_POINTS = 96  # kontur nokta üst sınırı (dosya ve ASS yolu küçük kalsın)
SUFFIX = ".sam.preview.json"


def preview_path(video: str | os.PathLike) -> Path:
    """`x.mp4` -> `x.mp4.sam.preview.json`."""
    p = Path(video)
    return p.with_name(p.name + SUFFIX)


def outline(mask: np.ndarray, max_points: int = MAX_POINTS) -> list[list[float]]:
    """(M, M) bool/logit maskenin en büyük dış konturu -> normalize [[x, y], ...] (boşsa [])."""
    import cv2

    m = np.asarray(mask)
    if m.ndim != 2 or not m.any():
        return []
    h, w = m.shape
    bin_ = (m > 0).astype(np.uint8)  # bool ve logit için aynı: > 0
    cnts, _ = cv2.findContours(bin_, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return []
    c = max(cnts, key=cv2.contourArea)
    eps = 0.5
    while len(c) > max_points and eps < 20:  # nokta sayısı sınırın altına inene dek sadeleştir
        c = cv2.approxPolyDP(c, eps, True)
        eps *= 1.6
    return [[round(float(x) / w, 4), round(float(y) / h, 4)] for x, y in c.reshape(-1, 2)]


def clamp_rect(r: tuple[float, float, float, float] | list[float] | None) -> list[float] | None:
    if r is None:
        return None
    x1, y1, x2, y2 = (min(max(float(v), 0.0), 1.0) for v in r)
    return [round(min(x1, x2), 4), round(min(y1, y2), 4), round(max(x1, x2), 4), round(max(y1, y2), 4)]


def make_payload(state: str, *, conf: float | None = None, pts: list[list[float]] | None = None,
                 rect: Any = None, drawn: Any = None, t: float = 0.0, index: int = 0,
                 note: str = "", lower: Any = None) -> dict[str, Any]:
    """`rect` = birleşik dikdörtgen (maske kutusu; `lower` varsa S7 kadrajı: bacak+ayak bölgesi),
    `drawn` = kullanıcının çizdiği dikdörtgen (yeniden çizim karşılaştırması için).
    `lower` (S7 `LowerBody`): `rect` kadraja döner, `lower` alanı görünen/anatomik bölge ve sol/sağ kanıtı taşır."""
    if lower is not None and lower.framing is not None:
        rect = lower.framing
    d = {"v": VERSION, "state": state, "conf": None if conf is None else round(float(conf), 3),
         "outline": pts or [], "rect": clamp_rect(rect), "drawn": clamp_rect(drawn),
         "t": round(float(t), 3), "index": int(index), "note": note}
    if lower is not None:
        d["lower"] = lower.to_dict()
    return d


def from_first(res: Any, *, t: float = 0.0, lower: Any = None) -> dict[str, Any]:
    """`FirstMask` -> onay önizlemesi (CONFIRM). `res`: mask_logits, box_norm, rect, size, iou, object_score."""
    from .sam_track import confidence

    w, h = res.size
    drawn = (res.rect[0] / w, res.rect[1] / h, res.rect[2] / w, res.rect[3] / h)
    return make_payload("CONFIRM", conf=confidence(res.iou, res.object_score, 1.0), pts=outline(res.mask_logits),
                        rect=res.box_norm, drawn=drawn, t=t, lower=lower)


def no_mask(drawn: Any, *, t: float = 0.0) -> dict[str, Any]:
    return make_payload("NO_MASK", drawn=drawn, t=t, note="maske yok: dikdörtgeni nesnenin çevresine yeniden çiz")


def from_record(rec: Any, drawn: Any = None, lower: Any = None) -> dict[str, Any]:
    """`TrackRecord` (keep_masks=True) -> işlem önizlemesi; durum = kaydın durumu (S9'a kadar yer tutucu)."""
    pts = outline(rec.mask) if rec.mask is not None else []
    return make_payload(rec.state, conf=rec.conf, pts=pts, rect=rec.box, drawn=drawn, t=rec.t, index=rec.index,
                        lower=lower)


def save(path: str | os.PathLike, payload: dict[str, Any]) -> Path:
    """Atomik yazım: Lua yarım dosya okumasın."""
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, p)
    return p


class Writer:
    """İşlem sırasında önizlemeyi en fazla `every` sn'de bir yazar; durum değişince hemen."""

    def __init__(self, path: str | os.PathLike, drawn: Any = None, every: float = 0.5, clock=time.monotonic) -> None:
        self.path, self.drawn, self.every, self._clock = Path(path), clamp_rect(drawn), every, clock
        self._last = -1e9
        self._state: str | None = None
        self.writes = 0

    def update(self, rec: Any, lower: Any = None) -> bool:
        now = self._clock()
        if rec.state == self._state and now - self._last < self.every:
            return False
        self._state, self._last = rec.state, now
        save(self.path, from_record(rec, self.drawn, lower))
        self.writes += 1
        return True

    def finish(self, last: Any = None, lower: Any = None) -> None:
        """Bitiş: son çerçeve + `DONE` durumu."""
        pay = (from_record(last, self.drawn, lower) if last is not None
               else make_payload("DONE", drawn=self.drawn, lower=lower))
        pay["state"] = "DONE"
        save(self.path, pay)
