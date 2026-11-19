"""S12: çift yönlü iyileştirme (geri SAM geçişi). `<video>.sam.json` -> `<video>.sam.refined.json`.

İleri geçiş (S4-S10) zaten var; bu modül yalnız BELİRSİZ aralıkları onarır. Özgün kayıt asla değişmez.

Akış:
  1. Güvenilir kare = izlendi + kapı kabul etti + temiz + güven >= 0.6 + (varsa) durum TRACKED/REACQUIRED + masa değil +
     tek karelik sıçrama değil. Güvenilir olmayan kareler belirsiz aralık olur (kayıp, kapı reddi, yarı örtülü, aday, masa,
     sıçrama). İki belirsiz aralık arasındaki 3 kareden kısa güvenilir koşu çapa sayılmaz, aralıklar birleşir.
  2. Aralığın hemen SONRAKİ güvenilir karesi (q) çapadır. SAM, q karesinin ileri kutusuyla yeniden istemlenir ve zaman
     içinde GERİ yürütülür (`sam_track.track_video`, kareler ters sırada; yeni `MemoryBank` + yeni `TrackGate`). Pencere
     `max_window` kareyle sınırlıdır (RAM/VRAM sabit): kareler uzun kenarı `max_side`'a küçültülüp aralık başına bir kez
     çözülür, bitince atılır.
  3. İleri ve geri karşılaştırılır. Onarım YALNIZ iki yön uyuşunca ya da kanıt açıkça birini seçince yapılır:
       closed  : geri iz q'dan öncesindeki güvenilir kareye (p) kesintisiz ulaştı ve p'de ileri kutuyla uyuştu (IoU >= 0.5):
                 aralıktaki tüm kareler geri izden onarılır. En güçlü kanıt (iki ucu da güvenilir, yol sürekli).
       open    : iz p'ye ulaşmadan koptu (ya da pencere sınırı): yalnız q'dan kesintisiz giden VE geri izin kendi ölçütüyle
                 TEMİZ (güven >= 0.6, normal boyut) kareler onarılır; kopuştan ötesi çözülmedi kalır.
       mismatch: iz p'ye ulaştı ama p'deki güvenilir ileri kutuyla uyuşmadı -> geri iz kaymış sayılır, aralıkta HİÇBİR şey
                 onarılmaz.
     Kare başına: `confirmed` (ileri izlendi, geri aynı yeri gösterdi: IoU >= 0.5; ileri kutu kalır), `repaired` (ileri
     kayıp/reddedilmiş/masa/sıçrama idi, geri kutu alındı; kapalı aralıkta ileri izli ama güveni geri izden en az 0.15
     düşükse de), `unresolved` (bayraklı kalır, kayıt DEĞİŞMEZ).
  4. Kimlik: S9/S10 kararı (`other_person`, `ambiguous_reentry`; kayıp durumunda ama SAM'ın izlediği kare) bu modülde DEĞİŞMEZ. İki yön de
     SAM'dır, bağımsız kimlik kanıtı değildir; bu kareler her zaman `unresolved` (neden `identity`) kalır; geri iz böyle bir karenin üstünden geçtiyse (`identity_cut`) daha eski kareler için de kanıt sayılmaz. OUT_OF_FRAME ve zaman aşımıyla
     MANUAL_RESELECT_REQUIRED (`absent_open`) kareleri yalnız closed aralıkta onarılır.
  5. Güvenilir kareler dokunulmaz (satırlar bayt bayt aynı).

Onarılan karede: `tracked`=1, `accepted`=1, kutu = geri kutu, `clean`=0 (belleğe girmedi), `w`,`h` = çapanın boyutu. Durum
satırı (varsa) PARTIALLY_OCCLUDED + neden `refined` + `hold`=0 olur: kamera bekleme/zoom-out yerine kaydırmayı sürdürür AMA
zoom'u BU karelerden beslemez (S11 yalnız TRACKED/REACQUIRED'dan besler; duruş kadrajı onarılan karede yeniden hesaplanmaz).
Doğrulanan aday kareler de PARTIALLY_OCCLUDED olur (REACQUIRED yalnız Re-ID ile). `posture`/`lower`/`reentry` blokları
DEĞİŞMEZ. Çıktıya isteğe bağlı `refine` bloğu eklenir (aralıklar, kare başına karar, özgün değerler; geri alınabilir).

Eşikler ilk tahmindir, gerçek klipte ayarlanmadı.
"""
from __future__ import annotations

import copy
import math
import os
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import cache, sam_track
from .trackstate import (
    LOST_STATES,
    MANUAL_RESELECT_REQUIRED,
    OUT_OF_FRAME,
    PARTIALLY_OCCLUDED,
    REACQUIRED,
    REACQUISITION_CANDIDATE,
    TRACKED,
)

Box = tuple[float, float, float, float]

HIGH_CONF = 0.6  # güvenilir kare: trackgate.REMEMBER_CONF ile aynı
ANCHOR_RUN = 3  # iki belirsiz aralık arasındaki güvenilir koşu bundan kısaysa çapa sayılmaz (birleşir)
AGREE_IOU = 0.5  # ileri ve geri kutu bu IoU'dan çoksa "aynı yeri gösteriyor"
CONF_MARGIN = 0.15  # closed aralıkta ileri izli kareyi geri izle değiştirmek için gereken güven farkı
SPIKE_FRAC = 0.6  # tek kare sıçrama: iki komşuya da kutu boyutunun bu kadarından uzak, komşular birbirine yakın
SPIKE_GAP = 3  # sıçrama komşuları en çok bu kadar kare uzakta
MAX_WINDOW = 150  # geri geçiş penceresi (kare); 10/sn'de 15 sn
MAX_SIDE = 1024  # bellekte tutulan karenin uzun kenarı (SAM zaten 1024'e sıkıştırır)
DECODE_TOL = 0.6  # çözülen kare zamanı istenenden en çok bu kadar örnekleme adımı sapabilir
MIN_ANCHOR_SIDE = 0.01  # çapa kutusu normalize en az bu kadar geniş/yüksek olmalı
IDENTITY_REASONS = ("other_person", "ambiguous_reentry")
REFINED = "refined"
CONFIRMED, REPAIRED, UNRESOLVED = "confirmed", "repaired", "unresolved"
CLOSED, OPEN, MISMATCH = "closed", "open", "mismatch"
SCHEMA = 1
REFINE_FIELDS = ("index", "t", "verdict", "why", "iou", "bconf", "otracked", "oaccepted", "ox1", "oy1", "ox2", "oy2")


class WindowError(Exception):
    """Geri geçiş penceresi hazırlanamadı (kare çözülemedi, çapa kutusu bozuk, çapada maske yok). `code` kısa neden."""

    def __init__(self, code: str, msg: str = "") -> None:
        super().__init__(msg or code)
        self.code = code


# --- ileri kayıt görünümü ---

@dataclass(frozen=True)
class Fwd:
    """Bir ileri kare: kayıt + (varsa) durum + masa bayrağı. Saf veri."""

    index: int
    t: float
    tracked: bool
    accepted: bool
    clean: bool
    conf: float
    box: Box | None
    size: tuple[float, float] | None
    state: str | None = None
    reason: str = ""
    desk: bool = False
    spike: bool = False


def _col(block: dict[str, Any] | None, name: str) -> int | None:
    return block["fields"].index(name) if block and name in block.get("fields", []) else None


def _wh(box: Box) -> tuple[float, float]:
    return box[2] - box[0], box[3] - box[1]


def _center(box: Box) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def iou(a: Box | None, b: Box | None) -> float:
    if a is None or b is None:
        return 0.0
    iw, ih = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def forward_rows(doc: dict[str, Any]) -> list[Fwd]:
    """`.sam.json` -> `Fwd` listesi. `state`/`posture` blokları yalnız kayıtla aynı uzunluktaysa okunur."""
    recs = sam_track.doc_records(doc)
    n = len(recs)
    stt, post = doc.get("state"), doc.get("posture")
    use_state = bool(stt) and len(stt["rows"]) == n
    use_post = bool(post) and len(post["rows"]) == n and _col(post, "desk") is not None
    out = []
    for i, r in enumerate(recs):
        state, reason, desk = None, "", False
        if use_state:
            row = stt["rows"][i]
            state, reason = row[_col(stt, "state")], row[_col(stt, "reason")]
        if use_post:
            desk = bool(post["rows"][i][_col(post, "desk")])
        out.append(Fwd(i, r.t, r.tracked, r.accepted, r.clean, r.conf, r.box, r.size, state, reason, desk))
    spikes = _spikes(out)
    return [replace(f, spike=True) if f.index in spikes else f for f in out]


def _spikes(rows: list[Fwd]) -> set[int]:
    """Tek karelik maske sıçraması: iki komşuya da uzak, komşular birbirine yakın (kapı bunu yakalamamış olabilir)."""
    ok = [r for r in rows if r.tracked and r.accepted and r.box is not None]
    out: set[int] = set()
    for j in range(1, len(ok) - 1):
        a, b, c = ok[j - 1], ok[j], ok[j + 1]
        if b.index - a.index > SPIKE_GAP or c.index - b.index > SPIKE_GAP:
            continue
        s = max(max(_wh(x.box)) for x in (a, b, c))  # type: ignore[arg-type]

        def d(p: Fwd, q: Fwd) -> float:
            (px, py), (qx, qy) = _center(p.box), _center(q.box)  # type: ignore[arg-type]
            return math.hypot(px - qx, py - qy)

        if d(a, b) > SPIKE_FRAC * s and d(b, c) > SPIKE_FRAC * s and d(a, c) <= 0.5 * SPIKE_FRAC * s:
            out.add(b.index)
    return out


def is_reliable(f: Fwd) -> bool:
    """Dokunulmayacak, çapa olabilecek kare."""
    return (f.tracked and f.accepted and f.clean and f.conf >= HIGH_CONF and f.box is not None and not f.desk
            and not f.spike and (f.state is None or f.state in (TRACKED, REACQUIRED)))


def identity_hold(f: Fwd) -> bool:
    """S9/S10 durum makinesi bu kareyi KİMLİK yüzünden reddetti: SAM-SAM uyuşması kimlik kanıtı değildir.

    İki belirti: (a) neden `other_person` / `ambiguous_reentry`; (b) durum kayıp ailesinden (TEMPORARILY_LOST, OUT_OF_FRAME,
    MANUAL_RESELECT_REQUIRED) ama SAM kaydı izlenmiş + kabul edilmiş: makine görülen kişiyi hedef saymadı (zaman aşımı
    nedeni `other_person`'ın üstüne yazsa bile)."""
    return f.reason in IDENTITY_REASONS or (f.state in LOST_STATES and f.tracked and f.accepted)


def needs_closed(f: Fwd) -> bool:
    """Öznenin uzun süre yok olduğu kareler (kare dışı, elle seçim zaman aşımı): yalnız kapalı aralıkta onarılır."""
    return f.state in (OUT_OF_FRAME, MANUAL_RESELECT_REQUIRED)


# --- aralıklar ---

@dataclass
class Interval:
    a: int  # ilk belirsiz kare
    b: int  # son belirsiz kare
    p: int | None  # a-1 (güvenilir) ya da None
    q: int | None  # b+1 (güvenilir, çapa) ya da None (klip belirsiz biter)

    @property
    def n(self) -> int:
        return self.b - self.a + 1


def plan(rows: list[Fwd]) -> list[Interval]:
    """Belirsiz aralıkları bul. İç kısa güvenilir koşular birleştirir; baş/son koşular (klip kenarı) çapa kalır."""
    n = len(rows)
    rel = [is_reliable(r) for r in rows]
    i = 0
    while i < n:
        if not rel[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and rel[j + 1]:
            j += 1
        if i > 0 and j < n - 1 and j - i + 1 < ANCHOR_RUN:
            for k in range(i, j + 1):
                rel[k] = False
        i = j + 1
    out, i = [], 0
    while i < n:
        if rel[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and not rel[j + 1]:
            j += 1
        out.append(Interval(i, j, i - 1 if i > 0 else None, j + 1 if j < n - 1 else None))
        i = j + 1
    return out


def window_low(iv: Interval, max_window: int) -> int | None:
    """Geri geçişin ulaşacağı en düşük kare (p'yi kapsamaya çalışır; pencere sınırı q'ya yakın olanı korur)."""
    if iv.q is None:
        return None
    base = iv.p if iv.p is not None else iv.a
    return max(base, iv.q - max(max_window, 2) + 1)


# --- geri geçiş sonucu ---

@dataclass(frozen=True)
class BackFrame:
    tracked: bool
    accepted: bool
    clean: bool
    conf: float
    box: Box | None
    iou: float = 0.0
    object_score: float = 0.0
    area: float = 0.0
    ratio: float = 1.0

    @property
    def valid(self) -> bool:
        return self.tracked and self.accepted and self.box is not None

    @classmethod
    def from_record(cls, rec: Any) -> BackFrame:
        return cls(bool(rec.tracked), bool(rec.accepted), bool(rec.clean), float(rec.conf), rec.box, float(rec.iou),
                   float(rec.object_score), float(rec.area), float(rec.ratio))


@dataclass
class Verdict:
    index: int
    verdict: str  # confirmed | repaired | unresolved
    why: str
    iou: float | None = None
    back: BackFrame | None = None  # repaired: alınan geri kare


def _chain(back: dict[int, BackFrame], q: int, lo: int, rows: list[Fwd]) -> set[int]:
    """q-1'den aşağı kesintisiz geçerli geri kareler. Kopuştan ve S10 kimlik karesinden (`identity_hold`) ötesi zincire
    girmez: geri iz, Re-ID'nin reddettiği bir kişinin üstünden geçtiyse daha eski kareler için kanıt sayılmaz."""
    out: set[int] = set()
    i = q - 1
    while i >= lo and (b := back.get(i)) is not None and b.valid and not identity_hold(rows[i]):
        out.add(i)
        i -= 1
    return out


def closure(iv: Interval, rows: list[Fwd], back: dict[int, BackFrame], lo: int | None) -> str:
    """closed | mismatch | open (modül açıklaması, madde 3)."""
    if iv.q is None or lo is None or iv.p is None or lo > iv.p:
        return OPEN
    chain = _chain(back, iv.q, lo, rows)
    if iv.p not in chain:
        return OPEN
    return CLOSED if iou(back[iv.p].box, rows[iv.p].box) >= AGREE_IOU else MISMATCH


def solve(iv: Interval, rows: list[Fwd], back: dict[int, BackFrame], lo: int | None,
          error: str | None = None) -> tuple[str, list[Verdict]]:
    """Aralığın kare kararları (saf). `error`: geri geçiş hiç yapılamadı (neden kodu) -> hepsi unresolved."""
    if iv.q is None:
        return OPEN, [Verdict(i, UNRESOLVED, "no_anchor") for i in range(iv.a, iv.b + 1)]
    if error is not None or lo is None:
        return OPEN, [Verdict(i, UNRESOLVED, "identity" if identity_hold(rows[i]) else (error or "no_backward"))
                      for i in range(iv.a, iv.b + 1)]
    clo = closure(iv, rows, back, lo)
    chain = _chain(back, iv.q, lo, rows)
    cut = max((i for i in range(iv.a, iv.q) if identity_hold(rows[i])), default=None)  # en yakın kimlik karesi
    out: list[Verdict] = []
    for i in range(iv.a, iv.b + 1):
        f, b = rows[i], back.get(i)
        if identity_hold(f):
            out.append(Verdict(i, UNRESOLVED, "identity"))
        elif cut is not None and i < cut:
            out.append(Verdict(i, UNRESOLVED, "identity_cut"))
        elif i < lo:
            out.append(Verdict(i, UNRESOLVED, "window_cap"))
        elif clo == MISMATCH:
            out.append(Verdict(i, UNRESOLVED, "closure_mismatch"))
        elif i not in chain or b is None:
            out.append(Verdict(i, UNRESOLVED, "no_backward"))
        elif f.tracked and f.accepted and f.box is not None and not f.desk and not f.spike:
            v = iou(f.box, b.box)
            if v >= AGREE_IOU:
                out.append(Verdict(i, CONFIRMED, "agree", v))
            elif clo == CLOSED and b.conf >= f.conf + CONF_MARGIN:
                out.append(Verdict(i, REPAIRED, "closed_better", v, b))
            else:
                out.append(Verdict(i, UNRESOLVED, "disagree", v))
        elif needs_closed(f) and clo != CLOSED:
            out.append(Verdict(i, UNRESOLVED, "absent_open"))
        elif clo == CLOSED:
            out.append(Verdict(i, REPAIRED, "closed", None, b))
        elif b.clean:
            out.append(Verdict(i, REPAIRED, "back_clean", None, b))
        else:
            out.append(Verdict(i, UNRESOLVED, "back_unclean"))
    return clo, out


# --- gerçek geri geçiş (I/O) ---

def _shrink(frame: Any, max_side: int) -> Any:
    import cv2

    h, w = frame.shape[:2]
    s = max_side / max(h, w)
    if s >= 1.0:
        return frame
    return cv2.resize(frame, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)


def load_window(video: str | os.PathLike, times: list[float], fps: float, max_side: int = MAX_SIDE,
                clip_factory: Callable[..., Any] | None = None) -> list[Any]:
    """`times` (artan) her biri için örneklenmiş en yakın kare; uzun kenarı `max_side`'a küçültülür. Kare bulunamazsa `WindowError`."""
    clip = (clip_factory or sam_track.Clip)(video, fps=fps, start=times[0], max_seconds=times[-1] - times[0])
    tol = DECODE_TOL / max(fps, 0.1)
    out: list[Any] = []
    try:
        for t, frame in clip:
            k = len(out)
            if k >= len(times):
                break
            if abs(t - times[k]) <= tol:
                out.append(_shrink(frame, max_side))
            elif t > times[k] + tol:
                break  # istenen kare atlandı
    finally:
        close = getattr(clip, "close", None)
        if close:
            close()
    if len(out) != len(times):
        raise WindowError("decode_failed", f"{len(times)} kareden {len(out)} tanesi çözüldü")
    return out


def backward_pass(engine: Any, video: str | os.PathLike, rows: list[Fwd], iv: Interval, lo: int, fps: float, *,
                  max_side: int = MAX_SIDE, loader: Callable[..., list[Any]] | None = None,
                  track: Callable[..., Any] | None = None) -> dict[int, BackFrame]:
    """q çapasından lo'ya kadar GERİ SAM: {kare sırası: BackFrame}. Kareler yalnız bu çağrı boyunca bellekte durur."""
    assert iv.q is not None
    q = iv.q
    box = rows[q].box
    if box is None or _wh(box)[0] < MIN_ANCHOR_SIDE or _wh(box)[1] < MIN_ANCHOR_SIDE:
        raise WindowError("bad_anchor")
    frames = (loader or load_window)(video, [rows[i].t for i in range(lo, q + 1)], fps, max_side)
    seq = ((rows[i].t, frames[i - lo]) for i in range(q, lo - 1, -1))
    out: dict[int, BackFrame] = {}
    try:
        for rec in (track or sam_track.track_video)(engine, seq, box, normalized=True):
            if rec.index > 0:
                out[q - rec.index] = BackFrame.from_record(rec)
    except sam_track.NoInitialMask as e:
        raise WindowError("no_anchor_mask", str(e)) from e
    finally:
        del frames, seq  # pencere kareleri bir sonraki aralığa taşınmasın
    return out


# --- rapor ---

@dataclass
class IntervalResult:
    iv: Interval
    t0: float
    t1: float
    lo: int | None
    closure: str
    verdicts: list[Verdict]

    def count(self, kind: str) -> int:
        return sum(v.verdict == kind for v in self.verdicts)


@dataclass
class Report:
    results: list[IntervalResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # geri geçişte beklenmeyen hata (GPU/ORT): aralık çözülmedi kalır, diğerleri sürer

    def count(self, kind: str) -> int:
        return sum(r.count(kind) for r in self.results)

    @property
    def suspect(self) -> int:
        return sum(r.iv.n for r in self.results)

    def why(self) -> Counter[str]:
        c: Counter[str] = Counter()
        for r in self.results:
            for v in r.verdicts:
                if v.verdict == UNRESOLVED:
                    c[v.why] += 1
        return c

    def summary(self) -> str:
        if not self.results:
            return "iyileştirme: belirsiz aralık yok (tüm kareler güvenilir); kayıt değişmedi"
        why = ", ".join(f"{k} {v}" for k, v in sorted(self.why().items())) or "yok"
        err = f" · {len(self.errors)} aralıkta HATA" if self.errors else ""
        return (f"iyileştirme: {len(self.results)} belirsiz aralık · {self.suspect} belirsiz kare → "
                f"{self.count(REPAIRED)} onarıldı, {self.count(CONFIRMED)} doğrulandı, {self.count(UNRESOLVED)} çözülmedi "
                f"(neden: {why}){err}")

    def lines(self) -> list[str]:
        out = []
        for k, r in enumerate(self.results, 1):
            q = f"q={r.iv.q}" if r.iv.q is not None else "çapa yok"
            out.append(f"  aralık {k}: kare {r.iv.a}-{r.iv.b} ({r.t0:.1f}-{r.t1:.1f} sn, {r.iv.n} kare) {q} · "
                       f"{r.closure} · onarıldı {r.count(REPAIRED)} doğrulandı {r.count(CONFIRMED)} "
                       f"çözülmedi {r.count(UNRESOLVED)}")
        return out


BackwardFn = Callable[[Interval, int], dict[int, BackFrame]]


def refine(doc: dict[str, Any], backward: BackwardFn, *, max_window: int = MAX_WINDOW,
           progress: Callable[[str], None] | None = None) -> tuple[dict[str, Any], Report]:
    """Belgeyi iyileştir. `backward(iv, lo)` geri kareleri verir ya da `WindowError` atar (aralık çözülmedi kalır).
    Yeni belge döner; `doc` DEĞİŞMEZ."""
    if doc.get("refine"):
        raise ValueError("kayıt zaten iyileştirilmiş: özgün <video>.sam.json'u verin")
    rows = forward_rows(doc)
    rep = Report()
    for iv in plan(rows):
        lo = window_low(iv, max_window)
        back: dict[int, BackFrame] = {}
        err: str | None = None
        if iv.q is not None and lo is not None:
            try:
                back = backward(iv, lo)
            except WindowError as e:
                err = e.code
            except Exception as e:  # noqa: BLE001 - GPU/ORT hatası bir aralığı çözülmedi bırakır; uzun koşu boşa gitmesin
                err = "backward_error"
                rep.errors.append(f"kare {iv.a}-{iv.b}: {type(e).__name__}: {e}")
        clo, verdicts = solve(iv, rows, back, lo, err)
        rep.results.append(IntervalResult(iv, rows[iv.a].t, rows[iv.b].t, lo, clo, verdicts))
        if progress:
            progress(rep.lines()[-1])
    return apply(doc, rows, rep, max_window), rep


def apply(doc: dict[str, Any], rows: list[Fwd], rep: Report, max_window: int = MAX_WINDOW) -> dict[str, Any]:
    """Kararları yeni belgeye yaz (kopya). Güvenilir kareler ve `unresolved` kareler olduğu gibi kalır."""
    new = copy.deepcopy(doc)
    names = new["fields"]
    ix = {n: names.index(n) for n in names}
    stt = new.get("state")
    use_state = bool(stt) and len(stt["rows"]) == len(new["records"])
    sc = {n: _col(stt, n) for n in ("state", "reason", "lost_s", "edge", "hold")} if use_state else {}
    ref_rows: list[list[Any]] = []
    for r in rep.results:
        for v in r.verdicts:
            old = doc["records"][v.index]
            ref_rows.append([v.index, old[ix["t"]], v.verdict, v.why, None if v.iou is None else round(v.iou, 3),
                             None if v.back is None else round(v.back.conf, 3), old[ix["tracked"]], old[ix["accepted"]],
                             old[ix["x1"]], old[ix["y1"]], old[ix["x2"]], old[ix["y2"]]])
            if v.verdict == UNRESOLVED:
                continue
            if v.verdict == REPAIRED:
                _write_repaired(new, rows, r.iv, v, ix)
            if use_state:
                row = stt["rows"][v.index]
                if v.verdict == REPAIRED or row[sc["state"]] == REACQUISITION_CANDIDATE:  # doğrulanan TRACKED/PARTIAL durum KALIR
                    row[sc["state"]], row[sc["reason"]], row[sc["hold"]] = PARTIALLY_OCCLUDED, REFINED, 0
                    if v.verdict == REPAIRED:
                        row[sc["lost_s"]], row[sc["edge"]] = 0.0, None
    _recount(new)
    new["refine"] = {
        "version": SCHEMA, "kind": "bidirectional",
        "params": {"max_window": max_window, "agree_iou": AGREE_IOU, "high_conf": HIGH_CONF,
                   "conf_margin": CONF_MARGIN, "anchor_run": ANCHOR_RUN},
        "fields": list(REFINE_FIELDS), "rows": ref_rows,
        "intervals": [{"a": r.iv.a, "b": r.iv.b, "p": r.iv.p, "q": r.iv.q, "lo": r.lo, "closure": r.closure,
                       "repaired": r.count(REPAIRED), "confirmed": r.count(CONFIRMED),
                       "unresolved": r.count(UNRESOLVED)} for r in rep.results],
        "counts": {"suspect": rep.suspect, "repaired": rep.count(REPAIRED), "confirmed": rep.count(CONFIRMED),
                   "unresolved": rep.count(UNRESOLVED)},
    }
    return new


def _write_repaired(new: dict[str, Any], rows: list[Fwd], iv: Interval, v: Verdict, ix: dict[str, int]) -> None:
    b = v.back
    assert b is not None and b.box is not None and iv.q is not None
    anchor = rows[iv.q]
    sw, sh = anchor.size if anchor.size else _wh(anchor.box)  # type: ignore[arg-type]
    row = new["records"][v.index]
    row[ix["tracked"]], row[ix["accepted"]], row[ix["clean"]] = 1, 1, 0
    for k, val in zip(("x1", "y1", "x2", "y2"), b.box, strict=True):
        row[ix[k]] = round(val, 4)
    row[ix["iou"]], row[ix["object_score"]], row[ix["conf"]] = round(b.iou, 3), round(b.object_score, 2), round(b.conf, 3)
    row[ix["area"]], row[ix["ratio"]] = round(b.area, 4), round(b.ratio, 3)
    row[ix["w"]], row[ix["h"]] = round(sw, 4), round(sh, 4)


def _recount(doc: dict[str, Any]) -> None:
    """Onarımdan sonra türev sayaçlar (`counts`, `gate`, `state.counts`) kayıtla tutarlı kalsın."""
    names = doc["fields"]
    tr, ac, cl = (names.index(n) for n in ("tracked", "accepted", "clean"))
    recs = doc["records"]
    n_tr = sum(1 for r in recs if r[tr])
    doc["counts"] = {"frames": len(recs), "tracked": n_tr, "lost": len(recs) - n_tr}
    if isinstance(doc.get("gate"), dict):
        doc["gate"]["rejected"] = sum(1 for r in recs if not r[ac])
        doc["gate"]["unclean"] = sum(1 for r in recs if r[tr] and not r[cl])
    stt = doc.get("state")
    if stt and len(stt["rows"]) == len(recs):
        c = Counter(row[_col(stt, "state")] for row in stt["rows"])
        stt["counts"] = {k: v for k, v in c.items() if v}


# --- video ile çalıştır ---

def refine_video(doc: dict[str, Any], video: str | os.PathLike, engine: Any, *, max_window: int = MAX_WINDOW,
                 max_side: int = MAX_SIDE, progress: Callable[[str], None] | None = None,
                 loader: Callable[..., list[Any]] | None = None,
                 track: Callable[..., Any] | None = None) -> tuple[dict[str, Any], Report]:
    """`refine` + gerçek geri SAM. Video imzası kayıttakiyle uyuşmalı (başka video/değişmiş dosya -> ValueError)."""
    sig = doc.get("vsig")
    if sig and sig != cache.file_sig(video):
        raise ValueError(f"video kayıttakiyle aynı değil (imza uyuşmuyor): {video}")
    rows = forward_rows(doc)
    fps = float(doc["sample_fps"])

    def backward(iv: Interval, lo: int) -> dict[int, BackFrame]:
        return backward_pass(engine, video, rows, iv, lo, fps, max_side=max_side, loader=loader, track=track)

    return refine(doc, backward, max_window=max_window, progress=progress)


def refined_path(sam_json: str | os.PathLike) -> Path:
    """`x.mp4.sam.json` -> `x.mp4.sam.refined.json` (özgün kayıt ezilmez)."""
    p = Path(sam_json)
    if p.name.endswith(".sam.json"):
        return p.with_name(p.name[: -len(".sam.json")] + ".sam.refined.json")
    return p.with_name(p.stem + ".refined.json")


def plan_lines(doc: dict[str, Any], max_window: int = MAX_WINDOW) -> list[str]:
    """Model/GPU gerekmeden: hangi aralıklar geri geçişe girer, pencere kaç kare (`--plan`)."""
    rows = forward_rows(doc)
    out = []
    for k, iv in enumerate(plan(rows), 1):
        lo = window_low(iv, max_window)
        if iv.q is None or lo is None:
            tail = "çapa yok (klip belirsiz bitiyor): çözülmeyecek"
        else:
            cap = " (pencere sınırı: p'ye ulaşılamaz)" if iv.p is None or lo > iv.p else ""
            tail = f"çapa q={iv.q}, geri pencere {iv.q - lo + 1} kare{cap}"
        out.append(f"  aralık {k}: kare {iv.a}-{iv.b} ({rows[iv.a].t:.1f}-{rows[iv.b].t:.1f} sn, {iv.n} kare) · {tail}")
    return out
