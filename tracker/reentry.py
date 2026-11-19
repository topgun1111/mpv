"""S10: kayıptan/kare dışından dönüşte kimlik doğrulama (MEVCUT Re-ID ile; yeni Re-ID YOK).

SAM izleyici kayıptan sonra "bir şey" bulur; bu şey hedef mi, kareye giren BAŞKA kişi mi? `ReentryVerifier` bunu çözer,
`trackstate.TrackStateMachine` kararı uygular (ACCEPT → REACQUIRED, REJECT → kayıp sürer, UNCERTAIN → elle seçim).

Veri akışı (`sam-track --reid`, poz her karede çalışır):
  - Hedef TRACKED ve kare temizken `observe`: hedefin kişi kutusu (SAM kutusunu kapsayan poz) `reid.PartAppearance` galerisine
    girer (aynı kırpıntı uygunluğu `reid.crop_ok`, aynı hız sınırı `reid_every_s`) + kişi oranları (en/boy, kare boyuna oranı) EMA.
  - Kayıptan dönen her karede `check`: aday = SAM kutusunu kapsayan kişi. Kare kanıtı:
      * görünüm: galeriye kosinüs. `>= reid_thres` aday eşleşir; `< reid_thres - WEAK_BAND` eşleşmez; arası belirsiz;
      * başka kişiler: karedeki diğer kişiler de galeriyle puanlanır. Biri de eşik üstündeyse ve adayı `reid_margin` içinde
        yakalıyorsa AMBIGUOUS (iki benzer kişi); adaydan marjla iyiyse MISMATCH (SAM yanlış kişide);
      * oranlar: kişi kutusunun boyu/en-boy oranı hedefinkine uygun değilse MISMATCH;
      * hareket+zamanlama: aday son güvenilir kutudan, geçen süreye göre makul olandan çok uzaktaysa MISMATCH
        (`GEO_BASE + GEO_SPEED * yokluk_sn`);
      * kırpıntı kullanılamıyorsa (kenarda kesik, başkasıyla örtüşük, kişi yok) UNKNOWN: kanıt sayılmaz, beklenir.
  - Çevrimdışı gelecek kare doğrulaması: karar tek kareden verilmez. Yokluk başına bir pencere tutulur; ACCEPT için SON
    `accept_n` kare üst üste MATCH (aradaki tek bir MISMATCH/AMBIGUOUS/UNKNOWN sayacı sıfırlar), REJECT için son `reject_n`
    kare üst üste MISMATCH gerekir. Dönüşün ilk karesi bu yüzden "aday" kalır (kamera eski kırpımda bekler) ve karar sonraki
    karelerle verilir. `verify_s` içinde ikisi de olmadıysa UNCERTAIN → elle seçim (zayıf güvenle kimlik DEĞİŞMEZ).
  - Galeri boşsa (hiç temiz kırpıntı alınamadı) doğrulama YAPILAMAZ: `check` None döner ve makine S9 gibi davranır
    (sayaç `unverified`); aksi halde kareye hep dayanan bir oturanda her uzun kayıp elle seçime düşerdi.

Model yoksa `Embedder` kurulamaz; çağıran (`sam-track --reid`) bunu yazıp Re-ID'siz sürer.
Saf mantık; sahte `embedder` ile testlidir (`embed(frame, [BBox]) -> (N, D)`). Eşikler ilk tahmindir, gerçek klipte ayarlanmadı.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .config import Config
from .lowerbody import pick_pose
from .reid import PartAppearance, crop_ok
from .trackstate import ID_ACCEPT, ID_PENDING, ID_REJECT, ID_UNCERTAIN

MATCH, MISMATCH, AMBIGUOUS, UNKNOWN = "match", "mismatch", "ambiguous", "unknown"
VERDICTS = (MATCH, MISMATCH, AMBIGUOUS, UNKNOWN)
DECISIONS = (ID_ACCEPT, ID_REJECT, ID_UNCERTAIN, ID_PENDING)

WEAK_BAND = 0.10  # reid_thres'in bu kadar altı "kesin başka kişi"; arası belirsiz
GEO_BASE = 0.25  # kare boyunun oranı: yokluk süresinden bağımsız makul sıçrama
GEO_SPEED = 0.35  # kare boyu/sn: kayıp sırasında özne bu hızla yer değiştirmiş olabilir
HEIGHT_RANGE = (0.4, 2.5)  # kişi kutusu boyu / hedefin ortalama boyu
ASPECT_RANGE = (0.5, 2.0)  # kişi kutusu en/boy / hedefin ortalama oranı
PROP_KEEP = 0.9  # oran EMA'sında eski değerin payı

ROW_FIELDS = ("index", "t", "state", "decision", "verdict", "why", "score", "other", "gap")


@dataclass(frozen=True)
class Identity:
    """Bir kare için kimlik denetimi sonucu. `decision` makineye gider; kalanı kayıt/önizleme içindir."""

    decision: str  # accept | reject | uncertain | pending
    verdict: str  # bu karenin kanıtı: match | mismatch | ambiguous | unknown
    why: str  # kısa kod: ok, low_score, weak_score, other_better, two_similar, too_far, scale, proportions, no_person, crop, embed
    score: float | None = None  # adayın galeri benzerliği
    other: float | None = None  # en iyi diğer kişinin galeri benzerliği
    index: int = 0
    t: float = 0.0
    state: str = ""
    gap: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"decision": self.decision, "verdict": self.verdict, "why": self.why,
                "score": None if self.score is None else round(self.score, 3),
                "other": None if self.other is None else round(self.other, 3)}

    def row(self) -> list[Any]:
        """`.sam.json` `reentry.rows` satırı (alan sırası `ROW_FIELDS`)."""
        r = lambda v: None if v is None else round(float(v), 3)  # noqa: E731
        return [self.index, round(self.t, 4), self.state, self.decision, self.verdict, self.why,
                r(self.score), r(self.other), round(self.gap, 2)]


class _Box:
    """`reid.crop_ok` `.bbox` özniteliği bekler."""

    def __init__(self, bbox: Any) -> None:
        self.bbox = bbox


class ReentryVerifier:
    """Hedef görünürken galeri besler (`observe`), kayıptan dönüşte kimliği doğrular (`check`)."""

    def __init__(self, embedder: Any, cfg: Config | None = None, *, accept_n: int | None = None,
                 reject_n: int | None = None, verify_s: float | None = None) -> None:
        self.cfg = cfg or Config()
        self.app = PartAppearance(embedder, self.cfg)
        self.accept_n = max(accept_n if accept_n is not None else self.cfg.reid_accept_n, 1)
        self.reject_n = max(reject_n if reject_n is not None else self.cfg.reid_reject_n, 1)
        self.verify_s = verify_s if verify_s is not None else self.cfg.reid_verify_s
        self.center: tuple[float, float] | None = None  # hedef kişinin son merkezi (px): pick_pose sürekliliği
        self._aspect: float | None = None
        self._hfrac: float | None = None
        self._ep: float | None = None
        self._t0 = 0.0
        self._hist: list[str] = []
        self.rows: list[list[Any]] = []
        self.counts: Counter[str] = Counter()  # karar başına denetlenen kare
        self.unverified = 0  # galeri boşken doğrulanamayan kare

    # --- galeri ---

    def observe(self, frame: Any, rec: Any, poses: list[Any], size: tuple[int, int], t: float) -> None:
        """Hedef TRACKED + temiz kare iken çağrılır: galeri ve kişi oranları. Kişi yoksa hiçbir şey yapmaz."""
        owner = pick_pose(poses, tuple(rec.box) if rec.box else None, size, self.center)
        if owner is None:
            return
        bb = owner.bbox
        self.center = (bb.cx, bb.cy)
        fh = size[1]
        if bb.h > 0 and bb.w > 0:
            asp, hf = bb.w / bb.h, bb.h / max(fh, 1)
            self._aspect = asp if self._aspect is None else PROP_KEEP * self._aspect + (1 - PROP_KEEP) * asp
            self._hfrac = hf if self._hfrac is None else PROP_KEEP * self._hfrac + (1 - PROP_KEEP) * hf
        self.app.observe(frame, bb, [p.bbox for p in poses if p is not owner], t)

    @property
    def gallery_size(self) -> int:
        return len(self.app.gallery)

    # --- doğrulama ---

    def check(self, frame: Any, rec: Any, poses: list[Any], size: tuple[int, int], ctx: Any) -> Identity | None:
        """Dönen karenin kimliği. `ctx`: `trackstate.ReentryContext`. Galeri boşsa None (denetlenemiyor)."""
        if ctx.episode != self._ep:  # yeni yokluk: pencere sıfırlanır
            self._ep, self._t0, self._hist = ctx.episode, float(rec.t), []
        if self.gallery_size == 0:
            self.unverified += 1
            return None
        verdict, why, score, other = self._evidence(frame, rec, poses, size, ctx)
        self._hist.append(verdict)
        out = Identity(self._decide(float(rec.t)), verdict, why, score, other, int(rec.index), float(rec.t),
                       ctx.state, float(ctx.gap))
        self.counts[out.decision] += 1
        self.rows.append(out.row())
        return out

    def _decide(self, t: float) -> str:
        h = self._hist
        if len(h) >= self.accept_n and all(v == MATCH for v in h[-self.accept_n:]):
            return ID_ACCEPT
        if len(h) >= self.reject_n and all(v == MISMATCH for v in h[-self.reject_n:]):
            return ID_REJECT
        if t - self._t0 >= self.verify_s:
            return ID_UNCERTAIN
        return ID_PENDING

    def _evidence(self, frame: Any, rec: Any, poses: list[Any], size: tuple[int, int],
                  ctx: Any) -> tuple[str, str, float | None, float | None]:
        owner = pick_pose(poses, tuple(rec.box), size, self.center)
        if owner is None:
            return UNKNOWN, "no_person", None, None
        why = self._implausible(rec, owner, ctx, size)
        if why:  # hareket/zamanlama/oran: görünümden bağımsız, sağlam kanıt
            return MISMATCH, why, None, None
        fw, fh = size
        others = [p.bbox for p in poses if p is not owner]
        if not crop_ok(_Box(owner.bbox), [_Box(o) for o in others], fw, fh, self.cfg.reid_min_h, self.cfg.reid_max_iou):
            return UNKNOWN, "crop", None, None
        try:
            embs = self.app.emb.embed(frame, [owner.bbox, *others])
        except Exception:  # model/kare hatası: kanıt yok, takip sürer
            return UNKNOWN, "embed", None, None
        sc = [self.app.gallery.score(e) if float(e @ e) > 0.5 else None for e in embs]
        s = sc[0]
        if s is None:
            return UNKNOWN, "embed", None, None
        o = max((v for v in sc[1:] if v is not None), default=None)
        return (*self._appearance(s, o), s, o)

    def _appearance(self, s: float, o: float | None) -> tuple[str, str]:
        thr, mar = self.cfg.reid_thres, self.cfg.reid_margin
        if s < thr - WEAK_BAND:
            return MISMATCH, "low_score"
        if s < thr:
            return AMBIGUOUS, "weak_score"
        if o is not None and o >= thr:
            if o - s >= mar:
                return MISMATCH, "other_better"
            if s - o < mar:
                return AMBIGUOUS, "two_similar"
        return MATCH, "ok"

    def _implausible(self, rec: Any, owner: Any, ctx: Any, size: tuple[int, int]) -> str | None:
        """Hareket+zamanlama (son güvenilir kutuya uzaklık) ve kişi oranları; makulse None."""
        b, a = rec.box, ctx.anchor.box
        dist = math.hypot((b[0] + b[2] - a[0] - a[2]) / 2, (b[1] + b[3] - a[1] - a[3]) / 2)
        if dist > GEO_BASE + GEO_SPEED * max(ctx.gap, 0.0):
            return "too_far"
        bb = owner.bbox
        if self._hfrac and bb.h > 0 and not HEIGHT_RANGE[0] <= (bb.h / max(size[1], 1)) / self._hfrac <= HEIGHT_RANGE[1]:
            return "scale"
        if self._aspect and bb.h > 0 and not ASPECT_RANGE[0] <= (bb.w / bb.h) / self._aspect <= ASPECT_RANGE[1]:
            return "proportions"
        return None

    def summary(self) -> str:
        c = self.counts
        return (f"re-ID: kabul {c[ID_ACCEPT]}, ret {c[ID_REJECT]}, belirsiz {c[ID_UNCERTAIN]}, bekleyen {c[ID_PENDING]} "
                f"(kare) · doğrulanamadı {self.unverified} · galeri {self.gallery_size}")
