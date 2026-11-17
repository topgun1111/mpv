"""S7: alt vücut bölgesi: görünen (visible) ve anatomik (anatomical) bölge, sol/sağ bacak kanıtı, tek kadraj.

Saf Python (model/GPU yok). Girdi kare başına: COCO-17 satırı (51 sayı, 0-1 oranı; `parts.py` ile aynı),
SAM maske kutusu (normalize) ve güveni. Çıktı `LowerBody`:
- görünen bölge: şu an görünen bacak/ayak (güvenilir diz/ayak bileği + SAM maskesi, kalça çizgisinin altı);
- anatomik bölge: tahmini TÜM alt vücut (masa arkasındaki uyluklar dahil); her zaman görünen bölgeyi kapsar;
- sol/sağ bacak: ayrı kanıt (`Leg`); yalnız destek, hedef tek birleşik kadraj;
- kadraj (`framing`): anatomik bölgeden türeyen, ölü bölgeli ve yumuşatılmış tek dikdörtgen.
Sabit masa yüksekliği YOK: eksik eklem "uzuv yok" demek değildir; kalçadan gövde boyu `L` ile kestirilir,
son gözlem `hold_s` sn tutulur. Zoom/kamera bu modülde YOK (S11).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from . import parts

Box = tuple[float, float, float, float]  # normalize (x1, y1, x2, y2)

# Boyutlar gövde boyu `L` (omuz ortası - kalça ortası) katıdır.
LEG_REACH = 1.0  # bacak ucu bilinmiyorsa kalçadan en az bu kadar aşağı (`parts.anchored_leg_box` ile aynı)
FULL_LEG = 2.0  # kalça -> ayak bileği üst sınırı (ayaktaki tam bacak)
FOOT_PAD = 0.15  # son görünen eklemin altına payı
LEG_HALF_W = 0.30  # kalça çevresinde bacak yarı genişliği
FOOT_HALF_W = 0.20  # ayak/diz noktasının yarı genişliği
SPREAD_MAX = 0.9  # ayak/diz x'i kalça x'inden en çok bu kadar uzakta sayılır (yana uzanan ayak kadrajı sürüklemesin)
VIS_PAD = 0.20  # görünen kutunun eklemler etrafındaki payı
FOOT_LEAD = 0.4  # iki ayak da görünürken kadraj altı, yüksek ayağın en çok bu kadar altına iner
SHOULDER_TO_TORSO = 1.2  # yalnız omuzlar görünüyorsa gövde boyu ≈ omuz genişliği × bu
MASK_MIN_CONF = 0.5  # bunun altındaki SAM maskesi kanıt sayılmaz
MASK_TOP_SLACK = 0.1  # maske üstü kalça çizgisinin en çok bu kadar üstünde (gövde maskeye girmesin)
MASK_SIDE_SLACK = 1.0  # maske yanları anatomik bölgenin en çok bu kadar dışında
HOLD_S = 1.5  # eksik kalça / bacak ucu / bölge için son gözlemin ömrü (sn)
TORSO_HOLD_S = 10.0  # ölçülen gövde boyunun ömrü
SWAP_RATIO = 0.6  # sol/sağ yer değişimi: takas maliyeti doğrudan maliyetin bu oranından az
SWAP_MIN = 0.5  # ... ve doğrudan sıçrama en az bu kadar (L); küçük oynamalar etiket sayılmaz
DEAD = 0.06  # kadraj kenarı: hedef bölge boyutunun bu oranından az oynarsa kıpırdamaz
ALPHA = 0.35  # kadraj kenarı hedefe yaklaşma oranı (kare başına)
W_HIP, W_KNEE, W_ANKLE = 0.2, 0.3, 0.5  # bacak kanıtı ağırlıkları

_SIDES = {"left": (11, 13, 15, 5), "right": (12, 14, 16, 6)}  # kalça, diz, ayak bileği, omuz


# --- kutu yardımcıları ---

def union(boxes: list[Box | None]) -> Box | None:
    bs = [b for b in boxes if b is not None]
    if not bs:
        return None
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


def area(b: Box | None) -> float:
    return 0.0 if b is None else max(b[2] - b[0], 0.0) * max(b[3] - b[1], 0.0)


def intersect(a: Box, b: Box) -> Box | None:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None


def clamp_box(b: Box | None) -> Box | None:
    if b is None:
        return None
    x1, y1, x2, y2 = (min(max(v, 0.0), 1.0) for v in b)
    return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None


def _r(b: Box | None) -> list[float] | None:
    return None if b is None else [round(v, 4) for v in b]


# --- sonuç ---

@dataclass
class Leg:
    side: str  # "left" | "right" (kişinin kendi sol/sağı; COCO etiketi + süreklilik)
    visible: Box | None = None  # görünen diz/ayak bileği çevresi
    anatomical: Box | None = None  # kalçadan tahmini ayağa
    evidence: float = 0.0  # 0-1: görünen eklemlerin ağırlıklı güveni (kalça .2, diz .3, ayak bileği .5)
    joints: tuple[str, ...] = ()  # güvenilir görünen eklemler: hip/knee/ankle
    hidden: bool = False  # diz ve ayak bileği görünmüyor (masa/oklüzyon); bacak YOK demek değildir
    held: bool = False  # bölge son gözleme dayanıyor (bu karede yeni eklem yok)
    mask_overlap: float | None = None  # SAM maske kutusunun bu bacağın anatomik kutusuna oranı

    def to_dict(self) -> dict[str, Any]:
        return {"visible": _r(self.visible), "anatomical": _r(self.anatomical), "evidence": round(self.evidence, 3),
                "joints": list(self.joints), "hidden": self.hidden, "held": self.held,
                "mask_overlap": None if self.mask_overlap is None else round(self.mask_overlap, 3)}


@dataclass
class LowerBody:
    t: float
    left: Leg
    right: Leg
    visible: Box | None = None
    anatomical: Box | None = None
    framing: Box | None = None  # tek birleşik kadraj dikdörtgeni (yumuşatılmış, kareye kırpılmış)
    source: str = "none"  # pose | pose+mask | mask | held | none
    conf: float = 0.0
    torso_px: float | None = None
    swapped: bool = False  # bu karede sol/sağ süreklilik düzeltmesi yapıldı
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"t": round(self.t, 3), "visible": _r(self.visible), "anatomical": _r(self.anatomical),
                "framing": _r(self.framing), "source": self.source, "conf": round(self.conf, 3),
                "legs": {"left": self.left.to_dict(), "right": self.right.to_dict()},
                "swapped": self.swapped}

    def row(self) -> list[Any]:
        """`.sam.json` `lower.rows` satırı (alan sırası `ROW_FIELDS`)."""
        f = self.framing or (None,) * 4
        v = self.visible or (None,) * 4
        a = self.anatomical or (None,) * 4
        return [round(self.t, 4), *[None if x is None else round(x, 4) for x in (*v, *a, *f)],
                self.source, round(self.conf, 3), round(self.left.evidence, 3), round(self.right.evidence, 3),
                int(self.left.hidden), int(self.right.hidden)]


ROW_FIELDS = ("t", "vx1", "vy1", "vx2", "vy2", "ax1", "ay1", "ax2", "ay2", "fx1", "fy1", "fx2", "fy2",
              "source", "conf", "left_ev", "right_ev", "left_hidden", "right_hidden")


# --- model ---

class LowerBodyModel:
    """Durumlu model: kare kare `update`. Kesme/yeni klipte `reset()`."""

    def __init__(self, *, min_conf: float = 0.35, hold_s: float = HOLD_S, dead: float = DEAD,
                 alpha: float = ALPHA) -> None:
        self.min_conf, self.hold_s, self.dead, self.alpha = min_conf, hold_s, dead, alpha
        self.reset()

    def reset(self) -> None:
        self._L: tuple[float, float] | None = None  # (gövde boyu px, ölçüldüğü an)
        self._hip: dict[str, tuple[float, float, float]] = {}  # taraf -> (x, y, an) px
        self._sep: float | None = None  # işaretli kalça ayrımı (sol.x - sağ.x), px
        self._dist: dict[str, tuple[float, float, float]] = {}  # taraf -> son uç nokta (kimlik sürekliliği)
        self._drop: dict[str, tuple[float, float]] = {}  # taraf -> (alt kenar kalçadan L katı, an)
        self._anat: tuple[Box, float] | None = None
        self._frame: Box | None = None
        self._frame_t = -1e9

    # -- yardımcılar --
    def _pt(self, row, j: int, w: int, h: int):
        if row[3 * j + 2] >= self.min_conf:
            return row[3 * j] * w, row[3 * j + 1] * h, row[3 * j + 2]
        return None

    def _torso(self, row, w: int, h: int, person_h_px: float, t: float) -> float | None:
        """Gövde boyu (px): iki omuz + iki kalça varsa `parts.torso_len`; tek kalçada aynı taraf omuzla uzaklık
        (tek kalça + omuz ortası yanal kaymayı gövdeye katardı); yoksa tutulan; omuz genişliği; kişi boyu."""
        if row:
            sh = {s: self._pt(row, _SIDES[s][3], w, h) for s in _SIDES}
            hp = {s: self._pt(row, _SIDES[s][0], w, h) for s in _SIDES}
            d = None
            if all(sh.values()) and all(hp.values()):
                d = parts.torso_len(row, w, h, self.min_conf, person_h_px)
            else:
                ds = [math.hypot(sh[s][0] - hp[s][0], sh[s][1] - hp[s][1]) for s in _SIDES if sh[s] and hp[s]]
                if ds:
                    d = sum(ds) / len(ds)
                    if person_h_px > 0:
                        d = min(max(d, 0.25 * person_h_px), 0.7 * person_h_px)
            if d and d >= 4.0:
                self._L = (d, t)
                return d
        if self._L and t - self._L[1] <= TORSO_HOLD_S:
            return self._L[0]
        if row:
            s = [self._pt(row, j, w, h) for j in (5, 6)]
            if all(s):
                return max(abs(s[0][0] - s[1][0]), 4.0) * SHOULDER_TO_TORSO
        return 0.45 * person_h_px if person_h_px > 0 else None

    def _hip_xy(self, side: str, row, w: int, h: int, hips: dict, L: float, t: float):
        """(x, y, ölçüldü_mü) ya da None: kendi kalçası, aynalanmış karşı kalça, tutulan, omuz altı."""
        if hips.get(side):
            x, y, _ = hips[side]
            return x, y, True
        other = "right" if side == "left" else "left"
        if hips.get(other):
            ox, oy, _ = hips[other]
            sep = self._sep
            if sep is None and row:
                ls, rs = self._pt(row, 5, w, h), self._pt(row, 6, w, h)
                if ls and rs:
                    sep = (ls[0] - rs[0]) * 0.8
            if sep:
                return (ox + sep if side == "left" else ox - sep), oy, False
        held = self._hip.get(side)
        if held and t - held[2] <= self.hold_s:
            return held[0], held[1], False
        if row:
            sh = self._pt(row, _SIDES[side][3], w, h)
            if sh:
                return sh[0], sh[1] + L, False
        return None

    def _untangle(self, obs: dict[str, dict], t: float, L: float) -> bool:
        """İki bacağın uç noktaları süreklilikle ters eşleşiyorsa (etiket takası, bacak çaprazlama) yer değiştirir."""
        pts = {}
        for s in ("left", "right"):
            p = obs[s].get("ankle") or obs[s].get("knee")
            last = self._dist.get(s)
            if p is None or last is None or t - last[2] > self.hold_s:
                return False
            pts[s] = (p, last)
        (pl, ll), (pr, lr) = pts["left"], pts["right"]
        direct = math.hypot(pl[0] - ll[0], pl[1] - ll[1]) + math.hypot(pr[0] - lr[0], pr[1] - lr[1])
        swap = math.hypot(pl[0] - lr[0], pl[1] - lr[1]) + math.hypot(pr[0] - ll[0], pr[1] - ll[1])
        if direct > SWAP_MIN * L and swap < SWAP_RATIO * direct:
            for k in ("knee", "ankle"):
                a, b = obs["left"].pop(k, None), obs["right"].pop(k, None)
                if b is not None:
                    obs["left"][k] = b
                if a is not None:
                    obs["right"][k] = a
            return True
        return False

    # -- ana adım --
    def update(self, t: float, row, size: tuple[int, int], *, person_h_px: float = 0.0,
               mask_box: Box | None = None, mask_conf: float = 0.0, tracked: bool = True) -> LowerBody:
        """`row`: 51 sayı (0-1 oranı) ya da None (poz yok). `mask_box`: SAM maske kutusu (normalize)."""
        w, h = max(int(size[0]), 1), max(int(size[1]), 1)
        row = list(row) if row and len(row) >= 51 else None
        L = self._torso(row, w, h, person_h_px, t)
        out = LowerBody(t, Leg("left"), Leg("right"), torso_px=L)

        obs: dict[str, dict] = {"left": {}, "right": {}}
        hips: dict[str, tuple[float, float, float]] = {}
        if row and L:
            for s, (hj, kj, aj, _sj) in _SIDES.items():
                hp = self._pt(row, hj, w, h)
                if hp:
                    hips[s] = hp
                    obs[s]["hip"] = hp
                for name, j in (("knee", kj), ("ankle", aj)):
                    p = parts._limb_point(row, j, w, h, self.min_conf, L)  # uydurma (perde arkası) eklem elenir
                    if p:
                        obs[s][name] = p
            if len(hips) == 2:
                self._sep = hips["left"][0] - hips["right"][0]
            out.swapped = self._untangle(obs, t, L)
            if out.swapped:
                out.notes.append("sol/sağ süreklilik düzeltildi")

        for s in ("left", "right"):
            leg = out.left if s == "left" else out.right
            o = obs[s]
            leg.joints = tuple(n for n in ("hip", "knee", "ankle") if n in o)
            leg.evidence = min(sum(wt * min(o[n][2], 1.0) for n, wt in
                                   (("hip", W_HIP), ("knee", W_KNEE), ("ankle", W_ANKLE)) if n in o), 1.0)
            leg.hidden = "knee" not in o and "ankle" not in o
            if not (row and L):
                continue
            far = o.get("ankle") or o.get("knee")
            if far:
                self._dist[s] = (far[0], far[1], t)
            hxy = self._hip_xy(s, row, w, h, hips, L, t)
            if hxy:
                hx, hy, measured = hxy
                if measured:
                    self._hip[s] = (hx, hy, t)
                leg.held = not measured
            # görünen kutu: güvenilir diz/ayak bileği + pay (kalça görünen bölgeye girmez: masa arkasında olabilir)
            pts = [(o[n][0], o[n][1]) for n in ("knee", "ankle") if n in o]
            if pts:
                pad = VIS_PAD * L
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                leg.visible = ((min(xs) - pad) / w, (min(ys) - pad) / h, (max(xs) + pad) / w, (max(ys) + pad) / h)
            if not hxy:
                leg.anatomical = leg.visible  # kalça kestirilemiyor: yalnız görünen
                continue
            leg.anatomical = self._leg_anat(s, o, hx, hy, L, t, w, h)

        left_a, right_a = out.left.anatomical, out.right.anatomical
        vis = union([out.left.visible, out.right.visible])
        anat = union([left_a, right_a])
        has_pose = anat is not None
        hip_y = None
        ys = [p[1] for p in hips.values()] or [self._hip[s][1] for s in self._hip if t - self._hip[s][2] <= self.hold_s]
        if ys:
            hip_y = sum(ys) / len(ys)

        # SAM maske kanıtı: kalça çizgisinin altı ve bacak bölgesine yakın kısım
        used_mask = False
        if mask_box is not None and tracked and mask_conf >= MASK_MIN_CONF:
            mb = self._clip_mask(mask_box, anat, hip_y, L, w, h)
            if mb is not None:
                used_mask = True
                vis, anat = union([vis, mb]), union([anat, mb])
                for leg in (out.left, out.right):
                    if leg.anatomical is not None:
                        inter = intersect(mb, leg.anatomical)
                        leg.mask_overlap = area(inter) / max(area(leg.anatomical), 1e-9)
        anat = union([anat, vis])  # anatomik bölge görüneni her zaman kapsar

        if anat is None and self._anat and t - self._anat[1] <= self.hold_s:
            anat, out.source = self._anat[0], "held"  # eksik gözlem "uzuv yok" demek değil: son bölge tutulur
        elif anat is None:
            out.source = "none"
        else:
            out.source = ("pose+mask" if used_mask else "pose") if has_pose else "mask"
            self._anat = (anat, t)
        out.visible, out.anatomical = clamp_box(vis), clamp_box(anat)
        evid = (out.left.evidence + out.right.evidence) / 2
        out.conf = max(evid, mask_conf if used_mask else 0.0)
        out.framing = self._frame_step(t, anat, out, L, w, h)
        return out

    def _leg_anat(self, s: str, o: dict, hx: float, hy: float, L: float, t: float, w: int, h: int) -> Box:
        far = o.get("ankle") or o.get("knee")
        off = LEG_REACH
        if far:
            off = (far[1] - hy) / L + FOOT_PAD
            if "ankle" in o:
                self._drop[s] = (min(max(off, LEG_REACH), FULL_LEG), t)
        elif s in self._drop and t - self._drop[s][1] <= self.hold_s:
            off = self._drop[s][0]  # ayak bileği geçici kayıp: son alt kenar tutulur
        off = min(max(off, LEG_REACH), FULL_LEG)
        x1, x2 = hx - LEG_HALF_W * L, hx + LEG_HALF_W * L
        for n in ("knee", "ankle"):
            if n in o:  # yana uzanan ayak: kalça x'inden SPREAD_MAX * L'den uzağa sayılmaz
                px = min(max(o[n][0], hx - SPREAD_MAX * L), hx + SPREAD_MAX * L)
                x1, x2 = min(x1, px - FOOT_HALF_W * L), max(x2, px + FOOT_HALF_W * L)
        return (x1 / w, hy / h, x2 / w, (hy + off * L) / h)

    def _clip_mask(self, mb: Box, anat: Box | None, hip_y: float | None, L: float | None, w: int, h: int):
        x1, y1, x2, y2 = mb
        if L and hip_y is not None:
            y1 = max(y1, (hip_y - MASK_TOP_SLACK * L) / h)  # gövde/üst vücut alt vücut bölgesine girmesin
            y2 = min(y2, (hip_y + (FULL_LEG + FOOT_PAD) * L) / h)
        if L and anat is not None:
            x1, x2 = max(x1, anat[0] - MASK_SIDE_SLACK * L / w), min(x2, anat[2] + MASK_SIDE_SLACK * L / w)
        return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None

    def _frame_step(self, t: float, anat: Box | None, out: LowerBody, L: float | None, w: int, h: int) -> Box | None:
        """Anatomik bölgeden tek kadraj: tek ayak hareketi alt kenarı sürüklemez; ölü bölge + yumuşatma."""
        tgt = anat
        a, b = out.left, out.right
        if tgt is not None and L and a.anatomical and b.anatomical and "ankle" in a.joints and "ankle" in b.joints:
            lo, hi = sorted((a.anatomical[3], b.anatomical[3]))
            tgt = (tgt[0], tgt[1], tgt[2], min(tgt[3], hi, lo + FOOT_LEAD * L / h))
        tgt = clamp_box(tgt)
        if tgt is None:
            if self._frame is not None and t - self._frame_t > self.hold_s:
                self._frame = None
            return self._frame
        self._frame_t = t
        if self._frame is None:
            self._frame = tgt
            return tgt
        cur = self._frame
        dims = (max(cur[2] - cur[0], 0.05), max(cur[3] - cur[1], 0.05))
        new = []
        for i in range(4):
            d = dims[i % 2]
            delta = tgt[i] - cur[i]
            new.append(cur[i] + self.alpha * delta if abs(delta) > self.dead * d else cur[i])
        nb = clamp_box((new[0], new[1], new[2], new[3]))
        self._frame = nb or cur
        return self._frame


# --- poz seçimi (SAM hedefiyle eşleştirme) ---

def pose_row(pose, w: int, h: int) -> list[float]:
    """`pose.Pose` (kare pikseli) -> 51 sayılık 0-1 satırı (`parts.py` biçimi)."""
    row: list[float] = []
    for j in range(17):
        x, y, c = pose.kpts[j]
        row += [float(x) / w, float(y) / h, float(c)]
    return row


def pick_pose(poses, box: Box | None, size: tuple[int, int], last_center: tuple[float, float] | None = None,
              min_overlap: float = 0.3):
    """SAM hedef kutusunu (normalize) en çok kapsayan kişi pozu; ya da None.

    Oturan kişide kişi kutusu yalnız üst gövdedir, bacaklar altındadır: kişi kutusu boyunun 1.2 katı kadar
    aşağı uzatılır. Eşitlikte `last_center` (px) en yakın olan kazanır; kutu yoksa yalnız süreklilik (yakınlık)."""
    if not poses:
        return None
    w, h = size
    best, best_s = None, -1e9
    for p in poses:
        bb = p.bbox
        cx, cy = (bb.x1 + bb.x2) / 2, (bb.y1 + bb.y2) / 2
        near = 0.0
        if last_center is not None:
            near = -math.hypot(cx - last_center[0], cy - last_center[1]) / max(w, h)
        if box is not None:
            tb = (box[0] * w, box[1] * h, box[2] * w, box[3] * h)
            ext = (bb.x1, bb.y1, bb.x2, bb.y2 + 1.2 * (bb.y2 - bb.y1))
            inter = intersect(tb, ext)
            ov = area(inter) / max(area(tb), 1e-9)
            if ov < min_overlap:
                continue
            s = ov + 0.1 * near
        elif last_center is not None and -near < 0.15:
            s = near
        else:
            continue
        if s > best_s:
            best, best_s = p, s
    return best


class Follower:
    """Poz + SAM kaydı -> `LowerBody`: hedef kişiyi SAM kutusuyla eşler (`pick_pose`), modeli besler.

    `sam-track --pose` kullanır. Poz yoksa model yalnız SAM maskesiyle (ve tutulan son bölgeyle) çalışır."""

    def __init__(self, model: LowerBodyModel | None = None) -> None:
        self.model = model or LowerBodyModel()
        self.center: tuple[float, float] | None = None

    def step(self, rec, poses, size: tuple[int, int]) -> LowerBody:
        """`rec`: `sam_track.TrackRecord` (t, box, conf, tracked); `poses`: o karenin `pose.Pose` listesi."""
        w, h = size
        box = tuple(rec.box) if rec.tracked and rec.box else None
        pose = pick_pose(poses, box, size, self.center)
        row, ph = None, 0.0
        if pose is not None:
            row, ph = pose_row(pose, w, h), float(pose.bbox.y2 - pose.bbox.y1)
            self.center = ((pose.bbox.x1 + pose.bbox.x2) / 2, (pose.bbox.y1 + pose.bbox.y2) / 2)
        return self.model.update(rec.t, row, size, person_h_px=ph, mask_box=box, mask_conf=rec.conf,
                                 tracked=rec.tracked)
