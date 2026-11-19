"""S8: duruş (SEATED / STANDING / TRANSITION), masa oklüzyonu, otur↔kalk, kadraj bölgesi.

Saf Python (model/GPU yok). `LowerBodyModel` (S7) üstüne oturur; aynı `update(...)` imzasıyla `Follower`'a takılır.
Yaptıkları:
- Duruş: kalça-diz-ayak bileği geometrisi (gövde boyu `L` biriminde) + görünen/anatomik bölge oranı; üstel yumuşatma,
  histerezis ve bekleme süresi ile titremez. Kanıt yoksa (poz yok, bacak kadraj dışına kesik) son duruş tutulur.
- Bacak durumu: `visible` / `moved` (görünüyor ama oynadı) / `hidden` (masa, oklüzyon) / `left_frame` (kadraj
  kenarından çıktı) / `unknown` (kişi yok). Sol/sağ kimliği S7'den gelir (`swapped`), burada bozulmaz.
- Masa: SAM maskesi, önceki anatomik bölgeye göre ENİNE geniş ve bölgeyle az örtüşüyorsa masa sayılır ve S7'ye
  verilmez (sabit masa yüksekliği YOK: yalnız maske-bölge örtüşmesi ve gövde boyuna oranlı genişlik).
- Oturma kipi: masa arkasındaki üst bacak bölgesi tutulur; görünen baldır/ayak bölgesi son görüldüğü yerden
  kalçaya göre `SEATED_HOLD_S` sn tutulur (masa kalıcı örter, kayıp değildir).
- Yürüme/ayakta: tam görünen tahmin, kısa tutma; oturma↔ayakta geçişi `blend` ile hız sınırlı karışır.
Zoom/kamera bu modülde YOK (S11).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from . import parts
from .lowerbody import (
    _SIDES,
    ALPHA,
    DEAD,
    FOOT_LEAD,
    HOLD_S,
    Box,
    LowerBody,
    LowerBodyModel,
    area,
    clamp_box,
    intersect,
    union,
)

SEATED, STANDING, TRANSITION, UNKNOWN = "seated", "standing", "transition", "unknown"
VISIBLE, MOVED, HIDDEN, LEFT_FRAME, GONE = "visible", "moved", "hidden", "left_frame", "unknown"

# --- duruş puanı: 0 = oturuyor, 1 = ayakta. Birimler: gövde boyu L (omuz-kalça) ---
THIGH_LO, THIGH_HI = 0.45, 0.75  # (diz.y - kalça.y) / L; önden oturanda uyluk kameraya bakar, kısalır
REACH_LO, REACH_HI = 1.30, 1.60  # (ayak bileği.y - kalça.y) / L
COV_LO, COV_HI = 0.30, 0.65  # görünen / anatomik bölge boyu (masa baldırı örtünce küçük)
W_THIGH, W_REACH, W_COV = 0.5, 0.3, 0.1  # oran en zayıf kanıt: önden oturanda uyluk kısa, görünen≈anatomik olabilir
OBS_FULL = 0.5  # toplam ağırlık bu değere ulaşınca gözlem tam güvenilir
NO_HIP_PENALTY = 0.7  # kalça görünmüyorsa (masa) omuz+L ile kestirilir: güven çarpanı
HIDDEN_SCORE, HIDDEN_WEIGHT = 0.15, 0.25  # kalça var, bacaklar yok, kadraj kesmiyor: zayıf "masa arkası oturuyor"
TAU_S = 0.35  # puan yumuşatma zaman sabiti
DT_MAX = 1.0
# --- durum makinesi (histerezis) ---
ENTER_UP, ENTER_DOWN = 0.45, 0.55  # SEATED'den / STANDING'den TRANSITION'a çıkış eşikleri
STAND_AT, SIT_AT = 0.72, 0.28  # TRANSITION'dan STANDING / SEATED'e yerleşme eşikleri
SETTLE_S = 0.4  # eşiğin ötesinde en az bu kadar kalmalı
BLEND_RATE = 1.5  # oturma↔ayakta bölge karışımı en çok bu hızla (1/sn) değişir
# --- bölgeler ---
SEATED_HOLD_S = 20.0  # oturanda bacak/bölge örtük kalma ömrü
STAND_HOLD_S = HOLD_S  # ayakta/yürürken kısa tutma
THIGH_SEATED = 0.45  # oturan üst bacak (kalça→diz) varsayılan düşüşü, L katı
THIGH_MIN, THIGH_MAX = 0.10, 1.00
THIGH_ALPHA = 0.3
EDGE = 0.04  # kadraj kenarına yakınlık (oran)
EDGE_BOTTOM = 0.99  # anatomik alt kenar bundan aşağıdaysa kadraj kesiyor
MOVE_L = 0.35  # iki gözlem arası bu kadar (L) kayan ayak "oynadı" sayılır
# --- masa maskesi ---
DESK_WIDTH_RATIO = 2.0  # maske genişliği / önceki anatomik genişlik
DESK_PRECISION = 0.45  # maskenin bölgeyle örtüşen payı bunun altında
DESK_PRECISION_STANDING = 0.25  # ayaktayken daha gevşek (adım açıklığı maskeyi genişletir)
DESK_ABS_W = 4.5  # maske genişliği (L) bundan fazlaysa bir insan olamaz
DESK_FLAT = 0.25  # yükseklik / genişlik bunun altı = yassı


def _ramp(v: float, lo: float, hi: float) -> float:
    return min(max((v - lo) / (hi - lo), 0.0), 1.0)


def _lerp_box(a: Box, b: Box, k: float) -> Box:
    return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k, a[3] + (b[3] - a[3]) * k)


def _r(b: Box | None) -> list[float] | None:
    return None if b is None else [round(v, 4) for v in b]


def desk_like(mask_box: Box, ref: Box | None, L: float | None, w: int, h: int,
              *, standing: bool = False) -> tuple[bool, float | None, float | None]:
    """(masa_mı, bölge_örtüşme_payı, genişlik_oranı). `ref`: önceki anatomik bölge (normalize).

    Masa geniş ve yassıdır, bacak bölgesinin çoğu dışındadır. Sabit yükseklik yok: yalnız maske ile bölge
    arasındaki örtüşme ve gövde boyu `L` kullanılır. `ref` yoksa yalnız mutlak genişlik kuralı çalışır."""
    mw, mh = (mask_box[2] - mask_box[0]) * w, (mask_box[3] - mask_box[1]) * h
    if L and mw >= DESK_ABS_W * L:
        return True, None, None
    if ref is None:
        return False, None, None
    aw = max((ref[2] - ref[0]) * w, 1.0)
    prec = area(intersect(mask_box, ref)) / max(area(mask_box), 1e-9)
    ratio = mw / aw
    limit = DESK_PRECISION_STANDING if standing else DESK_PRECISION
    flat = mw > 0 and mh < DESK_FLAT * mw and ratio >= 1.5
    return (ratio >= DESK_WIDTH_RATIO or flat) and prec < limit, prec, ratio


@dataclass
class PostureFrame:
    t: float
    posture: str = UNKNOWN
    score: float | None = None  # yumuşatılmış ayakta puanı (0-1); henüz kanıt yoksa None
    blend: float = 0.0  # 0 = oturma bölgesi, 1 = ayakta bölgesi
    direction: str | None = None  # TRANSITION'da: standing_up | sitting_down
    framing: Box | None = None  # duruşa duyarlı tek kadraj (S7 `lower.framing` yerine)
    thigh: Box | None = None  # oturanda masa arkasındaki tahmini üst bacak bölgesi
    visible_top: float | None = None  # en yüksek güvenilir diz/ayak bileği y'si (üstü örtülü olabilir)
    legs: dict[str, str] = field(default_factory=lambda: {"left": GONE, "right": GONE})
    desk_mask: bool = False  # bu karede maske masa sayıldı ve kanıt olarak kullanılmadı
    lower: LowerBody | None = None  # S7 çıktısı (görünen/anatomik/sol-sağ kanıtı)
    notes: list[str] = field(default_factory=list)

    @property
    def visible(self) -> Box | None:
        return self.lower.visible if self.lower else None

    @property
    def anatomical(self) -> Box | None:
        return self.lower.anatomical if self.lower else None

    def to_dict(self) -> dict[str, Any]:
        """S7 sözlüğü + duruş alanları (Lua `p.lower.anatomical/visible` okumaya devam eder)."""
        d = self.lower.to_dict() if self.lower else {"t": round(self.t, 3)}
        d.update({"framing": _r(self.framing), "posture": self.posture,
                  "score": None if self.score is None else round(self.score, 3), "blend": round(self.blend, 3),
                  "direction": self.direction, "thigh": _r(self.thigh),
                  "visible_top": None if self.visible_top is None else round(self.visible_top, 4),
                  "leg_status": dict(self.legs), "desk_mask": self.desk_mask})
        return d

    def row(self) -> list[Any]:
        f = self.framing or (None,) * 4
        k = self.thigh or (None,) * 4
        return [round(self.t, 4), self.posture, None if self.score is None else round(self.score, 3),
                round(self.blend, 3), *[None if x is None else round(x, 4) for x in (*f, *k)],
                self.legs["left"], self.legs["right"], int(self.desk_mask), self.direction]


ROW_FIELDS = ("t", "posture", "score", "blend", "fx1", "fy1", "fx2", "fy2", "tx1", "ty1", "tx2", "ty2",
              "left", "right", "desk", "direction")


class PostureModel:
    """Durumlu model: kare kare `update`; imza `LowerBodyModel.update` ile aynı, çıktı `PostureFrame`."""

    def __init__(self, lower: LowerBodyModel | None = None) -> None:
        self.lower = lower or LowerBodyModel()
        self.reset()

    def reset(self) -> None:
        self.lower.reset()
        self._state: str | None = None
        self._s: float | None = None
        self._from: str | None = None
        self._pend: str | None = None
        self._since = 0.0
        self._t_prev: float | None = None
        self._blend = 0.5
        self._ref: Box | None = None  # önceki anatomik bölge (masa denetimi için)
        self._thigh = THIGH_SEATED
        self._shin: tuple[tuple[float, float, float, float], float] | None = None  # kalçaya göre göreli, an
        self._seated_last: tuple[Box, float] | None = None
        self._last: dict[str, tuple[float, float, float, float, float]] = {}  # taraf -> x, y, an, vx, vy (px)
        self._frame: Box | None = None
        self._frame_t = -1e9

    # -- geometri --
    def _points(self, row, w: int, h: int, L: float) -> dict[str, dict[str, tuple[float, float]]]:
        mc = self.lower.min_conf
        out: dict[str, dict[str, tuple[float, float]]] = {}
        for s, (hj, kj, aj, _sj) in _SIDES.items():
            d: dict[str, tuple[float, float]] = {}
            if row[3 * hj + 2] >= mc:
                d["hip"] = (row[3 * hj] * w, row[3 * hj + 1] * h)
            for name, j in (("knee", kj), ("ankle", aj)):
                p = parts._limb_point(row, j, w, h, mc, L)  # perde arkası uydurma eklem elenir
                if p:
                    d[name] = (p[0], p[1])
            out[s] = d
        return out

    def _hip_y(self, row, pts, w: int, h: int, L: float) -> tuple[float | None, float]:
        """(kalça y px, güven çarpanı): ölçülen kalçalar; yoksa omuz + L (masa kalçayı örter)."""
        ys = [p["hip"][1] for p in pts.values() if "hip" in p]
        if ys:
            return sum(ys) / len(ys), 1.0
        sh = [row[3 * j + 1] * h for j in (5, 6) if row[3 * j + 2] >= self.lower.min_conf]
        if sh:
            return sum(sh) / len(sh) + L, NO_HIP_PENALTY
        return None, 0.0

    # -- duruş --
    def _observe(self, row, pts, hip_y, hip_k, L, lb: LowerBody, h: int) -> tuple[float, float] | None:
        """(ayakta puanı, ağırlık 0-1) ya da None (kanıt yok: duruş tutulur)."""
        terms: list[tuple[float, float]] = []
        if hip_y is not None:
            knees = [(p["knee"][1] - hip_y) / L for p in pts.values() if "knee" in p]
            ankles = [(p["ankle"][1] - hip_y) / L for p in pts.values() if "ankle" in p]
            if knees:
                terms.append((_ramp(sum(knees) / len(knees), THIGH_LO, THIGH_HI), W_THIGH))
            if ankles:
                terms.append((_ramp(sum(ankles) / len(ankles), REACH_LO, REACH_HI), W_REACH))
        a, v = lb.anatomical, lb.visible
        cut = a is not None and a[3] >= EDGE_BOTTOM
        if terms and a is not None and v is not None and not cut:
            terms.append((_ramp((v[3] - v[1]) / max(a[3] - a[1], 1e-9), COV_LO, COV_HI), W_COV))
        if terms:
            sw = sum(wt for _, wt in terms)
            return sum(sc * wt for sc, wt in terms) / sw, min(sw / OBS_FULL, 1.0) * hip_k
        present = any(row[3 * j + 2] >= self.lower.min_conf for j in (5, 6, 11, 12))
        if present and a is not None and not cut:
            return HIDDEN_SCORE, HIDDEN_WEIGHT  # bacaklar yok ama kadraj kesmiyor: masa arkası oturma ipucu
        return None

    def _advance(self, t: float, dt: float, obs: tuple[float, float] | None) -> None:
        if obs is None:
            return
        x, wgt = obs
        if self._s is None:
            self._s = x
            self._state = STANDING if x >= STAND_AT else SEATED if x <= SIT_AT else TRANSITION
            return
        self._s += (1.0 - math.exp(-dt * wgt / TAU_S)) * (x - self._s)
        s, st = self._s, self._state
        if st == SEATED and s >= ENTER_UP:
            self._state, self._from, self._pend = TRANSITION, SEATED, None
        elif st == STANDING and s <= ENTER_DOWN:
            self._state, self._from, self._pend = TRANSITION, STANDING, None
        elif st == TRANSITION:
            tgt = STANDING if s >= STAND_AT else SEATED if s <= SIT_AT else None
            if tgt is None:
                self._pend = None
            else:
                if self._pend != tgt:
                    self._pend, self._since = tgt, t
                if t - self._since >= SETTLE_S:
                    self._state, self._pend = tgt, None

    # -- bacak durumu --
    def _leg_status(self, side: str, pts_side, lleg, present: bool, t: float, L: float, w: int, h: int) -> str:
        far = pts_side.get("ankle") or pts_side.get("knee")
        last = self._last.get(side)
        if far:
            status, vx, vy = VISIBLE, 0.0, 0.0
            if last and 0.0 < t - last[2] <= HOLD_S:
                dt = t - last[2]
                vx, vy = (far[0] - last[0]) / dt, (far[1] - last[1]) / dt
                if math.hypot(far[0] - last[0], far[1] - last[1]) >= MOVE_L * L:
                    status = MOVED
            self._last[side] = (far[0], far[1], t, vx, vy)
            return status
        leaving = False
        if last:
            dt = min(t - last[2], DT_MAX)
            lx, ly = last[0] / w, last[1] / h
            ex, ey = (last[0] + last[3] * dt) / w, (last[1] + last[4] * dt) / h
            out = ex < 0.0 or ex > 1.0 or ey > 1.0
            near = (lx < EDGE and last[3] <= 0) or (lx > 1.0 - EDGE and last[3] >= 0) or (ly > 1.0 - EDGE and last[4] >= 0)
            leaving = out or near
        if not present:
            return LEFT_FRAME if leaving else GONE
        cut = lleg.anatomical is not None and lleg.anatomical[3] >= EDGE_BOTTOM
        return LEFT_FRAME if leaving or cut else HIDDEN

    # -- bölgeler --
    def _seated_region(self, t: float, lb: LowerBody, pts, hip_y, L, w: int, h: int,
                       out: PostureFrame) -> tuple[Box | None, bool]:
        """(bölge, taze_mi): taze değil = gözlem yok, son bölge tutuluyor (ömrü `SEATED_HOLD_S`)."""
        a = lb.anatomical
        if a is None or not L:
            if self._state == SEATED and self._seated_last and t - self._seated_last[1] <= SEATED_HOLD_S:
                return self._seated_last[0], False  # poz/maske yok: oturan kişi yerinde varsayılır (tutma)
            return None, False
        hy = hip_y if hip_y is not None else a[1] * h
        cx, half = (a[0] + a[2]) / 2 * w, (a[2] - a[0]) / 2 * w
        knees = [(p["knee"][1] - hy) / L for p in pts.values() if "knee" in p]
        if knees:
            m = min(max(sum(knees) / len(knees), THIGH_MIN), THIGH_MAX)
            self._thigh += THIGH_ALPHA * (m - self._thigh)
        out.thigh = clamp_box(((cx - half) / w, hy / h, (cx + half) / w, (hy + self._thigh * L) / h))
        v = lb.visible
        shin = None
        if v is not None:
            rel = ((v[0] * w - cx) / L, (v[1] * h - hy) / L, (v[2] * w - cx) / L, (v[3] * h - hy) / L)
            self._shin = (rel, t)
            shin = v
        elif self._shin and t - self._shin[1] <= SEATED_HOLD_S:
            r = self._shin[0]
            shin = ((cx + r[0] * L) / w, (hy + r[1] * L) / h, (cx + r[2] * L) / w, (hy + r[3] * L) / h)
        reg = clamp_box(union([a, out.thigh, shin]))
        if reg is not None:
            self._seated_last = (reg, t)
        return reg, True

    def _cap_feet(self, tgt: Box, lb: LowerBody, L: float | None, h: int) -> Box:
        a, b = lb.left, lb.right
        if L and a.anatomical and b.anatomical and "ankle" in a.joints and "ankle" in b.joints:
            lo, hi = sorted((a.anatomical[3], b.anatomical[3]))
            return (tgt[0], tgt[1], tgt[2], min(tgt[3], hi, lo + FOOT_LEAD * L / h))
        return tgt

    def _smooth(self, t: float, tgt: Box | None, fresh: bool = True) -> Box | None:
        hold = SEATED_HOLD_S if self._state == SEATED else STAND_HOLD_S
        tgt = clamp_box(tgt)
        if tgt is None:
            if self._frame is not None and t - self._frame_t > hold:
                self._frame = None
            return self._frame
        if fresh:
            self._frame_t = t
        if self._frame is None:
            self._frame = tgt
            return tgt
        cur = self._frame
        dims = (max(cur[2] - cur[0], 0.05), max(cur[3] - cur[1], 0.05))
        new = [cur[i] + ALPHA * (tgt[i] - cur[i]) if abs(tgt[i] - cur[i]) > DEAD * dims[i % 2] else cur[i]
               for i in range(4)]
        self._frame = clamp_box((new[0], new[1], new[2], new[3])) or cur
        return self._frame

    # -- ana adım --
    def update(self, t: float, row, size: tuple[int, int], *, person_h_px: float = 0.0,
               mask_box: Box | None = None, mask_conf: float = 0.0, tracked: bool = True) -> PostureFrame:
        w, h = max(int(size[0]), 1), max(int(size[1]), 1)
        row = list(row) if row and len(row) >= 51 else None
        out = PostureFrame(t)
        prev_L = self.lower._L[0] if self.lower._L else None
        if mask_box is not None and tracked and mask_conf >= 0.5:
            bad, prec, ratio = desk_like(mask_box, self._ref, prev_L, w, h, standing=self._state == STANDING)
            if bad:
                out.desk_mask, mask_box = True, None
                out.notes.append(f"maske masa sayıldı (örtüşme {prec if prec is None else round(prec, 2)}, "
                                 f"genişlik oranı {ratio if ratio is None else round(ratio, 2)})")
        lb = self.lower.update(t, row, (w, h), person_h_px=person_h_px, mask_box=mask_box, mask_conf=mask_conf,
                               tracked=tracked)
        out.lower, L = lb, lb.torso_px
        pts = self._points(row, w, h, L) if row and L else {"left": {}, "right": {}}
        if lb.swapped:  # S7 sol/sağ takasını düzeltti: kimlik bozulmasın, bizim noktaları da aynı yap
            for k in ("knee", "ankle"):
                a, b = pts["left"].pop(k, None), pts["right"].pop(k, None)
                if b is not None:
                    pts["left"][k] = b
                if a is not None:
                    pts["right"][k] = a
        hip_y, hip_k = self._hip_y(row, pts, w, h, L) if row and L else (None, 0.0)
        obs = self._observe(row, pts, hip_y, hip_k, L, lb, h) if row and L else None
        dt = 0.0 if self._t_prev is None else min(max(t - self._t_prev, 0.0), DT_MAX)
        self._t_prev = t
        first = self._state is None
        self._advance(t, dt, obs)
        out.posture, out.score, out.direction = self._state or UNKNOWN, self._s, None
        if self._state == TRANSITION and self._from:
            out.direction = "standing_up" if self._from == SEATED else "sitting_down"
        present = bool(row) and any(row[3 * j + 2] >= self.lower.min_conf for j in (5, 6, 11, 12))
        for s, leg in (("left", lb.left), ("right", lb.right)):
            out.legs[s] = self._leg_status(s, pts[s], leg, present, t, L or 1.0, w, h)
        ys = [p[1] for d in pts.values() for n, p in d.items() if n in ("knee", "ankle")]
        out.visible_top = min(ys) / h if ys else None

        # karışım: oturma bölgesi <-> ayakta bölgesi (hız sınırlı; geçiş ani sıçramaz)
        st = self._state
        goal = (0.5 if st is None else 0.0 if st == SEATED else 1.0 if st == STANDING
                else _ramp(self._s or 0.0, SIT_AT, STAND_AT))
        step = BLEND_RATE * dt
        if first and st is not None:
            self._blend = goal  # ilk kanıt: karışım doğrudan duruşa oturur
        else:
            self._blend += min(max(goal - self._blend, -step), step)
        out.blend = self._blend
        seated_r, fresh = self._seated_region(t, lb, pts, hip_y, L, w, h, out)
        stand_r = clamp_box(union([lb.anatomical, lb.visible]))
        if seated_r is not None and stand_r is not None:
            reg = _lerp_box(seated_r, stand_r, self._blend)
        else:
            reg = seated_r if stand_r is None else stand_r
        if reg is not None:
            reg = self._cap_feet(reg, lb, L, h)
        out.framing = self._smooth(t, reg, fresh or stand_r is not None)
        if lb.anatomical is not None:
            self._ref = lb.anatomical
        return out


def follower(min_conf: float = 0.35):
    """`sam-track --posture`: `Follower` + `PostureModel` (poz seçimi S7'deki gibi)."""
    from .lowerbody import Follower

    return Follower(PostureModel(LowerBodyModel(min_conf=min_conf)))
