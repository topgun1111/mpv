"""Vücut parçası hazır ayarları ve grup kutuları (Android Part 10; PC ile aynı referans; B3 canlı).

Hazır ayar = COCO-17 eklem grubu. Kutu = güvenilir eklemlerin birleşimi + `part_margin`, en az
`kp_box` × kişi boyu (tek eklem de anlamlı kutu alır). Güvenilir eklem yoksa kişi kutusunun ilgili
bölgesi (alt kutu) kullanılır: kayıp zinciri eklem grubu → kişi alt kutusu → (offline_interp_s
dolgusu)
→ bekle/zoom-out (`offline._views_from_boxes`).
"""
from __future__ import annotations

import math

PART_MARGIN = 0.02  # kare yüksekliği oranı; Config'te `part_margin` varsa o kullanılır
PART_FIT = 0.70  # parça kutusu görünümün en az bu kadarını kaplar (büyük parçada zoom'un 1x'te kalmasını önler)

PRESETS: dict[str, tuple[int, ...]] = {
    "person": (),
    "head": (0, 1, 2, 3, 4),
    "torso": (5, 6, 11, 12),
    "left_arm": (5, 7, 9), "right_arm": (6, 8, 10),
    "left_leg": (11, 13, 15), "right_leg": (12, 14, 16), "legs": (11, 12, 13, 14, 15, 16),
    "left_foot": (15,), "right_foot": (16,), "feet": (15, 16),
    "hands": (9, 10),
}

# Güvenilir eklem yokken: kişi kutusunun (üst, alt) dikey oranları; yatayda kutunun tamamı.
REGION: dict[str, tuple[float, float]] = {
    "head": (0.0, 0.22), "torso": (0.18, 0.55),
    "left_arm": (0.15, 0.60), "right_arm": (0.15, 0.60),
    "left_leg": (0.50, 1.0), "right_leg": (0.50, 1.0), "legs": (0.50, 1.0),
    "left_foot": (0.88, 1.0), "right_foot": (0.88, 1.0), "feet": (0.88, 1.0),
    "hands": (0.35, 0.62),
}


# Android 10b: eksik uç eklem → (üst eklem, onun üstü, uzuv oranı). Uç = üst + (üst − onun üstü) × oran
# (bacakta baldır ≈ uyluk, kolda ön kol ≈ 0.8 × üst kol). İkisi de güvenilirse kestirilir; güveni
# min(üst, onun üstü) × INFER_CONF (gerçek eklemden her zaman düşük → kutu seçiminde sonra gelir).
INFER: dict[int, tuple[int, int, float]] = {
    15: (13, 11, 1.0), 16: (14, 12, 1.0), 9: (7, 5, 0.8), 10: (8, 6, 0.8),
}
INFER_CONF = 0.5


def infer_joint(row, j: int, w: int, h: int, min_conf: float):
    """Eksik eklem j'nin kare pikseli kestirimi (x, y, güven) ya da None (zincir güvenilir değil)."""
    if not row or j not in INFER:
        return None
    p, g, ratio = INFER[j]
    if row[3 * p + 2] < min_conf or row[3 * g + 2] < min_conf:
        return None
    px, py, gx, gy = row[3 * p] * w, row[3 * p + 1] * h, row[3 * g] * w, row[3 * g + 1] * h
    return (px + (px - gx) * ratio, py + (py - gy) * ratio,
            min(row[3 * p + 2], row[3 * g + 2]) * INFER_CONF)


# Oklüzyon dayanıklılığı (masa arkasında oturan kişi vb.): perde arkasındaki eklemler çoğu zaman düşük
# güvenle ama uzakta/yanlış yerde üretilir ve dev kutu yapar. Uzuv eklemi kök eklemine (kalça/omuz)
# gövde boyunun REACH katından uzaksa elenir; makul yerdeyse düşük güven (SOFT_CONF) de kabul edilir.
_ROOT = {7: 5, 8: 6, 9: 5, 10: 6, 13: 11, 14: 12, 15: 11, 16: 12}  # eklem -> kök (omuz/kalça)
REACH = {13: 1.3, 14: 1.3, 15: 2.2, 16: 2.2, 7: 0.9, 8: 0.9, 9: 1.5, 10: 1.5}  # kök eklemine en çok uzaklık (gövde boyu katı)
SOFT_CONF = 0.20  # kök güvenilir + makul konumdaysa bu güven de yeter (ağırlığı 0.8'e iner)
_LEG_PRESETS = ("left_leg", "right_leg", "legs", "left_foot", "right_foot", "feet")


def torso_len(row, w: int, h: int, min_conf: float, person_h_px: float = 0.0):
    """Omuz orta noktası - kalça orta noktası uzaklığı (piksel); eklem yoksa kişi boyunun 0.45'i
    (kutu yalnız görünen kısmı kapsayabilir); o da yoksa None."""
    if not row:
        return None
    sh = [(row[3 * j] * w, row[3 * j + 1] * h) for j in (5, 6) if row[3 * j + 2] >= min_conf]
    hp = [(row[3 * j] * w, row[3 * j + 1] * h) for j in (11, 12) if row[3 * j + 2] >= min_conf]
    if sh and hp:
        d = math.hypot(sum(p[0] for p in sh) / len(sh) - sum(p[0] for p in hp) / len(hp),
                       sum(p[1] for p in sh) / len(sh) - sum(p[1] for p in hp) / len(hp))
        if d >= 4.0:
            # güvenilmez omuz/kalça tahmini aşırı kısa/uzun gövde vermesin: kişi boyunun %25-70'i
            return min(max(d, 0.25 * person_h_px), 0.7 * person_h_px) if person_h_px > 0 else d
    return 0.45 * person_h_px if person_h_px > 0 else None


def _limb_point(row, j: int, w: int, h: int, min_conf: float, torso: float | None):
    """Eklem j için (x, y, güven) ya da None: güvenilir ve makul konumda, ya da (kök güvenilirse)
    düşük güvenli ama makul konumda. Kök güvenilir değilse klasik kural (yalnız `min_conf`)."""
    c = row[3 * j + 2]
    x, y = row[3 * j] * w, row[3 * j + 1] * h
    root = _ROOT.get(j)
    if root is None or not torso or row[3 * root + 2] < min_conf:
        return (x, y, c) if c >= min_conf else None
    d = math.hypot(x - row[3 * root] * w, y - row[3 * root + 1] * h)
    if d > REACH[j] * torso:
        return None  # perde arkası uydurma eklem
    if c >= min_conf:
        return x, y, c
    return (x, y, c * 0.8) if c >= SOFT_CONF else None


def sanitize_row(row, w: int, h: int, min_conf: float, person_h_px: float):
    """Satırın uzuv eklemlerini makullük kuralıyla temizler: uydurma eklem güveni 0 olur (kestirim de
    ona dayanmaz), makul düşük güvenli eklem `min_conf`'a çıkar. Kök yoksa satır aynen döner."""
    torso = torso_len(row, w, h, min_conf, person_h_px)
    if not torso:
        return row
    out = list(row)
    for j in _ROOT:
        lp = _limb_point(row, j, w, h, min_conf, torso)
        out[3 * j + 2] = 0.0 if lp is None else max(lp[2], min_conf) if row[3 * j + 2] < min_conf else row[3 * j + 2]
    return out


def anchored_leg_box(preset: str, row, w: int, h: int, min_conf: float, person_h_px: float):
    """Bacak/ayak eklemi hiç yokken kalçadan türetilen kutu ([cx, cy, bw, bh] normalize) ya da None.
    Kişi kutusunun alt dilimi yerine (oturan kişide kutu yalnız üst gövdedir) gövde boyu `L` ölçülür:
    bacak = kalçadan L aşağı, ayak = 0.6L..1.3L; sol/sağ yan kalçaya, çiftli ayarlar orta noktaya."""
    if preset not in _LEG_PRESETS or not row:
        return None
    side = {"left_leg": (11,), "left_foot": (11,), "right_leg": (12,), "right_foot": (12,)}.get(preset, (11, 12))
    hips = [(row[3 * j] * w, row[3 * j + 1] * h) for j in side if row[3 * j + 2] >= min_conf]
    if not hips:
        hips = [(row[3 * j] * w, row[3 * j + 1] * h) for j in (11, 12) if row[3 * j + 2] >= min_conf]
    L = torso_len(row, w, h, min_conf, person_h_px)
    if not hips or not L:
        return None
    hx, hy = sum(p[0] for p in hips) / len(hips), sum(p[1] for p in hips) / len(hips)
    top, bot = (0.6, 1.3) if "foot" in preset or preset == "feet" else (0.0, 1.0)
    bw = (1.4 if len(side) == 2 else 0.9) * L
    return [hx / w, (hy + (top + bot) / 2 * L) / h, bw / w, (bot - top) * L / h]


# B3: menü/kısayol sırası ("auto" = parça ayarı yok: tıklanan eklem izlenir) ve Türkçe adlar.
CYCLE: tuple[str, ...] = ("auto", "person", "head", "torso", "left_arm", "right_arm", "left_leg",
                          "right_leg", "legs", "left_foot", "right_foot", "feet", "hands")
LABELS_TR: dict[str, str] = {
    "auto": "Serbest (tıklanan eklem)", "person": "Tüm kişi", "head": "Baş", "torso": "Gövde",
    "left_arm": "Sol kol", "right_arm": "Sağ kol", "left_leg": "Sol bacak",
    "right_leg": "Sağ bacak", "legs": "Bacaklar", "left_foot": "Sol ayak",
    "right_foot": "Sağ ayak", "feet": "Ayaklar", "hands": "Eller",
}


def next_preset(cur: str, step: int = 1) -> str:
    """Kısayolla döngü: CYCLE sırasında bir sonraki (step=-1: önceki)."""
    i = CYCLE.index(cur) if cur in CYCLE else 0
    return CYCLE[(i + step) % len(CYCLE)]


def check_preset(name: str) -> str:
    if name not in PRESETS:
        raise ValueError(f"bilinmeyen parça ayarı: {name!r} (olabilir: {', '.join(PRESETS)})")
    return name


def group_box(joints, row, w: int, h: int, person_h_px: float, kp_min_conf: float,
              kp_box: float, margin: float = PART_MARGIN, infer: bool = False,
              robust: bool = False):
    """([cx, cy, bw, bh] normalize, ort. güven) ya da None (güvenilir eklem yok).
    `infer` (10b): grubun güvenilir olmayan ayak bileği/bileği üst eklemlerinden kestirilir
    (`infer_joint`) ve birleşime katılır; zincir de güvenilir değilse yine None."""
    if not row:
        return None
    pts = []
    if robust:
        row = sanitize_row(row, w, h, kp_min_conf, person_h_px)
    distal = False  # uzuv ucuna doğru (diz/ayak bileği, dirsek/bilek) en az bir eklem var mı
    for j in joints:
        if row[3 * j + 2] >= kp_min_conf:
            pts.append((row[3 * j] * w, row[3 * j + 1] * h, row[3 * j + 2]))
            distal = distal or j in _ROOT
        elif infer:
            e = infer_joint(row, j, w, h, kp_min_conf)
            if e is not None:
                pts.append(e)
                distal = distal or j in _ROOT
    if not pts or (robust and not distal and any(j in _ROOT for j in joints)):
        return None  # yalnız kök eklem (kalça/omuz) kaldı: uzuv görünmüyor → türetilmiş kutu/dilim
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    m = margin * h
    side = max(kp_box * person_h_px, 8.0)
    bw = max(max(xs) - min(xs) + 2 * m, side)
    bh = max(max(ys) - min(ys) + 2 * m, side)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return [cx / w, cy / h, bw / w, bh / h], sum(p[2] for p in pts) / len(pts)


def preset_boxes(doc: dict, ids: set[int], preset: str, cfg,
                 kps: list[dict] | None = None) -> dict[int, list[float]]:
    """Örnek başına [cx, cy, w, h] (normalize). Birden çok kimlikte en iyi aday: eklem tabanlı
    kutular (ort. güven) her zaman alt kutudan (−1 + skor) ve eşitlikte sonraki kimlik kazanır.
    `kps` (10b): örnek başına {kimlik: satır} (`offscreen.smooth_keypoints`); yoksa `s["kp"]`."""
    check_preset(preset)
    w, h = doc["video"]["w"] or 1, doc["video"]["h"] or 1
    margin = getattr(cfg, "part_margin", PART_MARGIN)
    joints = PRESETS[preset]
    infer = bool(getattr(cfg, "kp_infer", False))
    robust = bool(getattr(cfg, "kp_robust", False))
    boxes: dict[int, list[float]] = {}
    best: dict[int, float] = {}
    for i, s in enumerate(doc["samples"]):
        rows = kps[i] if kps is not None else (s.get("kp") or {})
        for d in s["d"]:
            if d[0] not in ids:
                continue
            x1, y1, x2, y2, score = d[1], d[2], d[3], d[4], d[5]
            if preset == "person":
                box, q = [(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1], score
            else:
                g = group_box(joints, rows.get(str(d[0])), w, h, (y2 - y1) * h,
                              cfg.kp_min_conf, cfg.kp_box, margin, infer, robust)
                a = (anchored_leg_box(preset, rows.get(str(d[0])), w, h, cfg.kp_min_conf, (y2 - y1) * h)
                     if g is None and robust else None)
                if g is not None:
                    box, q = g
                elif a is not None:
                    box, q = a, -0.5 + score
                else:
                    top, bot = REGION[preset]
                    ry1, ry2 = y1 + (y2 - y1) * top, y1 + (y2 - y1) * bot
                    box, q = [(x1 + x2) / 2, (ry1 + ry2) / 2, x2 - x1, ry2 - ry1], -1.0 + score
            if q >= best.get(i, -2.0):
                boxes[i], best[i] = box, q
    return boxes


def group_extent(kpts, preset: str, person, min_conf: float, kp_box: float,
                 margin: float = PART_MARGIN):
    """Tek karedeki poz için parça kutusu, KARE PİKSELİ: (cx, cy, bw, bh).

    `kpts` [17,3] (x, y, güven); `person` kişi kutusu (`geometry.BBox`). Güvenilir eklem varsa
    onların birleşimi + `margin`×kişi boyu, en az `kp_box`×kişi boyu; yoksa kişi kutusunun ilgili
    bölgesi (`REGION`); "person" kişi kutusunun kendisi. `group_box` (offline) ile aynı mantık.
    """
    check_preset(preset)
    ph = max(person.y2 - person.y1, 1.0)
    if preset == "person":
        return person.cx, person.cy, person.x2 - person.x1, ph
    pts = [(float(kpts[j][0]), float(kpts[j][1])) for j in PRESETS[preset]
           if j < len(kpts) and kpts[j][2] >= min_conf]
    if pts:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        side = max(kp_box * ph, 8.0)
        bw = max(max(xs) - min(xs) + 2 * margin * ph, side)
        bh = max(max(ys) - min(ys) + 2 * margin * ph, side)
        return (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, bw, bh
    top, bot = REGION[preset]
    y1, y2 = person.y1 + ph * top, person.y1 + ph * bot
    return person.cx, (y1 + y2) / 2, person.x2 - person.x1, y2 - y1
