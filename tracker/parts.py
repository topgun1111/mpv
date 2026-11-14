"""Android Part 10: vücut parçası hazır ayarları ve grup kutuları (PC ve Android aynı referansı paylaşır).

Hazır ayar = COCO-17 eklem grubu. Kutu = güvenilir eklemlerin birleşimi + `part_margin`, en az
`kp_box` × kişi boyu (tek eklem de anlamlı kutu alır). Güvenilir eklem yoksa kişi kutusunun ilgili
bölgesi (alt kutu) kullanılır: kayıp zinciri eklem grubu → kişi alt kutusu → (offline_interp_s dolgusu)
→ bekle/zoom-out (`offline._views_from_boxes`).
"""
from __future__ import annotations

PART_MARGIN = 0.02  # kare yüksekliği oranı; Config'te `part_margin` varsa o kullanılır

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


def check_preset(name: str) -> str:
    if name not in PRESETS:
        raise ValueError(f"bilinmeyen parça ayarı: {name!r} (olabilir: {', '.join(PRESETS)})")
    return name


def group_box(joints, row, w: int, h: int, person_h_px: float, kp_min_conf: float,
              kp_box: float, margin: float = PART_MARGIN):
    """([cx, cy, bw, bh] normalize, ort. güven) ya da None (güvenilir eklem yok)."""
    if not row:
        return None
    pts = [(row[3 * j] * w, row[3 * j + 1] * h, row[3 * j + 2]) for j in joints
           if row[3 * j + 2] >= kp_min_conf]
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    m = margin * h
    side = max(kp_box * person_h_px, 8.0)
    bw = max(max(xs) - min(xs) + 2 * m, side)
    bh = max(max(ys) - min(ys) + 2 * m, side)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return [cx / w, cy / h, bw / w, bh / h], sum(p[2] for p in pts) / len(pts)


def preset_boxes(doc: dict, ids: set[int], preset: str, cfg) -> dict[int, list[float]]:
    """Örnek başına [cx, cy, w, h] (normalize). Birden çok kimlikte en iyi aday: eklem tabanlı
    kutular (ort. güven) her zaman alt kutudan (−1 + skor) ve eşitlikte sonraki kimlik kazanır."""
    check_preset(preset)
    w, h = doc["video"]["w"] or 1, doc["video"]["h"] or 1
    margin = getattr(cfg, "part_margin", PART_MARGIN)
    joints = PRESETS[preset]
    boxes: dict[int, list[float]] = {}
    best: dict[int, float] = {}
    for i, s in enumerate(doc["samples"]):
        kps = s.get("kp") or {}
        for d in s["d"]:
            if d[0] not in ids:
                continue
            x1, y1, x2, y2, score = d[1], d[2], d[3], d[4], d[5]
            if preset == "person":
                box, q = [(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1], score
            else:
                g = group_box(joints, kps.get(str(d[0])), w, h, (y2 - y1) * h,
                              cfg.kp_min_conf, cfg.kp_box, margin)
                if g is not None:
                    box, q = g
                else:
                    top, bot = REGION[preset]
                    ry1, ry2 = y1 + (y2 - y1) * top, y1 + (y2 - y1) * bot
                    box, q = [(x1 + x2) / 2, (ry1 + ry2) / 2, x2 - x1, ry2 - ry1], -1.0 + score
            if q >= best.get(i, -2.0):
                boxes[i], best[i] = box, q
    return boxes
