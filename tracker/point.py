"""Sınıfsız nokta/nesne izleyici (Parça 18): sağ tıklanan nokta ne olursa olsun takip edilir.

YOLO/ByteTrack yalnız "person" bilir; burada nesnenin ne olduğu önemli değildir (top, araba, kuş,
tahtadaki bir şekil...). Tıklanan noktadan bir başlangıç kutusu çıkarılır, sonra her karede:

1. **Hareket**: kutunun çekirdeğindeki köşe noktaları Lucas-Kanade optik akışıyla izlenir
   (ileri-geri tutarlılık süzgeciyle); medyan kayma kutuyu taşır, noktaların merkeze uzaklık oranı ölçeği verir.
2. **Doğrulama**: kutunun içeriği, başlangıç görünümünden (yavaşça güncellenen) şablonla normalize
   çapraz ilinti (NCC) ile karşılaştırılır; düşükse akış yanlış şeyi (arka planı) izliyor demektir.
3. **Yeniden bulma**: akış tutmazsa (dokusuz nesne, hızlı hareket) ya da doğrulama düşerse son
   konumun çevresinde şablon eşleştirme yapılır; bulunamazsa nesne **kayıp** sayılır (`update` None
   döner) ve arama penceresi kayıp süresiyle büyür.

Yalnız OpenCV çekirdek işlevleri (`calcOpticalFlowPyrLK`, `matchTemplate`, `floodFill`) kullanılır:
`cv2.TrackerCSRT/KCF` OpenCV 5'te çekirdekten çıktı (contrib gerekir), o yüzden kullanılmadı.
Kareler en uzun kenarı `max_side` olacak şekilde küçültülerek işlenir.

Tek tıklamadan nesnenin kapladığı alan bilinemez; `refine_box` aynı renkteki bitişik bölgeyi
büyüterek (flood fill) kutuyu tahmin eder, uygun bir bölge çıkmazsa karenin `box_frac` oranında bir
kare kutu kullanılır. Zoom miktarı `+`/`-` ile (doluluk) ayarlanır.
"""
from __future__ import annotations

import numpy as np

from .geometry import BBox

_MIN_WORK_BOX = 20  # çalışma ölçeğinde kutunun en küçük kenarı (px)
_CORE = 0.6  # köşe noktaları kutunun ortadaki bu oranından seçilir (kenardaki arka planı ele)
_FB_ERR = 1.0  # ileri-geri akış hatası üst sınırı (px)
_MIN_PTS = 6  # akışın güvenilir sayılması için en az iyi nokta
_REFRESH_PTS = 12  # bunun altına inince yeni köşe noktaları aranır
_UPDATE_SCORE = 0.85  # bunun üstünde şablon yavaşça güncellenir
_MAX_SCALE_STEP = 1.1  # kare başına en çok ölçek değişimi


def default_box(fw: int, fh: int, px: float, py: float, frac: float) -> tuple[float, ...]:
    """(px, py) merkezli, kare yüksekliğinin `frac` oranında kare kutu; kare içinde kalır."""
    side = max(min(frac * fh, fw, fh), 8.0)
    x1 = min(max(px - side / 2, 0.0), fw - side)
    y1 = min(max(py - side / 2, 0.0), fh - side)
    return x1, y1, x1 + side, y1 + side


def refine_box(frame_bgr: np.ndarray, px: float, py: float, tol: int = 14,
               min_frac: float = 0.03, max_frac: float = 0.35) -> tuple[float, ...] | None:
    """Tıklanan noktayla aynı renkteki bitişik bölgenin kutusu (kenarlarına %30 pay).

    Bölge çok küçükse (gürültü/doku), kutu çerçevesini taşırıp arka planı kapsıyorsa
    ya da dolgu oranı düşükse (ince çizgi) None döner → çağıran varsayılan kutuyu kullanır.
    """
    import cv2

    fh, fw = frame_bgr.shape[:2]
    r = int(0.3 * fh)
    x0, y0 = max(int(px) - r, 0), max(int(py) - r, 0)
    x1, y1 = min(int(px) + r + 1, fw), min(int(py) + r + 1, fh)
    crop = frame_bgr[y0:y1, x0:x1]
    h, w = crop.shape[:2]
    sx, sy = int(px) - x0, int(py) - y0
    if h < 8 or w < 8 or not (0 <= sx < w and 0 <= sy < h):
        return None
    img = cv2.GaussianBlur(np.ascontiguousarray(crop), (5, 5), 0)
    mask = np.zeros((h + 2, w + 2), np.uint8)
    flags = 4 | cv2.FLOODFILL_FIXED_RANGE | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    cv2.floodFill(img, mask, (sx, sy), (0, 0, 0), (tol,) * 3, (tol,) * 3, flags)
    ys, xs = np.nonzero(mask[1:-1, 1:-1])
    if len(xs) < 25:
        return None
    bx1, bx2, by1, by2 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    bw, bh = bx2 - bx1, by2 - by1
    if max(bw, bh) > max_frac * fh or len(xs) / (bw * bh) < 0.35:
        return None
    cx, cy = x0 + (bx1 + bx2) / 2, y0 + (by1 + by2) / 2
    side_w = max(bw * 1.3, min_frac * fh)
    side_h = max(bh * 1.3, min_frac * fh)
    nx1 = min(max(cx - side_w / 2, 0.0), fw - side_w)
    ny1 = min(max(cy - side_h / 2, 0.0), fh - side_h)
    return nx1, ny1, nx1 + side_w, ny1 + side_h


class PointTracker:
    """Tek nesne izleyici. `update(frame)` → BBox (tam çözünürlük pikseli) ya da None (kayıp)."""

    def __init__(self, frame_bgr: np.ndarray, px: float, py: float, *,
                 box_frac: float = 0.06, refine: bool = True, max_side: int = 640,
                 min_score: float = 0.55):
        import cv2

        self._cv2 = cv2
        self.fh, self.fw = frame_bgr.shape[:2]
        self.min_score = min_score
        box = refine_box(frame_bgr, px, py) if refine else None
        if box is None:
            box = default_box(self.fw, self.fh, px, py, box_frac)
        x1, y1, x2, y2 = box
        s = min(1.0, max_side / max(self.fw, self.fh))
        small = max(min(x2 - x1, y2 - y1), 1.0)
        if small * s < _MIN_WORK_BOX:
            s = min(1.0, _MIN_WORK_BOX / small)
        self.s = s
        gray = self._prep(frame_bgr)
        self.gh, self.gw = gray.shape
        self.cx, self.cy = (x1 + x2) / 2 * s, (y1 + y2) / 2 * s
        self.bw, self.bh = (x2 - x1) * s, (y2 - y1) * s
        self.tmpl = self._crop(gray, self.cx, self.cy, self.bw, self.bh)
        self.prev = gray
        self.pts = self._detect(gray)
        self.lost = 0  # ardışık kayıp kare sayısı

    # --- dış arayüz ---
    @property
    def bbox(self) -> BBox:
        s, hw, hh = self.s, self.bw / 2, self.bh / 2
        return BBox(max((self.cx - hw) / s, 0.0), max((self.cy - hh) / s, 0.0),
                    min((self.cx + hw) / s, float(self.fw)),
                    min((self.cy + hh) / s, float(self.fh)))

    def update(self, frame_bgr: np.ndarray) -> BBox | None:
        cur = self._prep(frame_bgr)
        res = None  # (cx, cy, bw, bh, skor, noktalar)
        if self.lost == 0:
            lk = self._lk(cur)
            if lk is not None:
                score = self._score(cur, *lk[:4])
                if score >= self.min_score:
                    res = (*lk[:4], score, lk[4])
        if res is None:
            found = self._search(cur)
            if found is None:
                self.lost += 1
                self.prev, self.pts = cur, None
                return None
            res = (found[0], found[1], self.bw, self.bh, found[2], None)
        cx, cy, bw, bh, score, pts = res
        self.cx = min(max(cx, 0.0), self.gw - 1.0)
        self.cy = min(max(cy, 0.0), self.gh - 1.0)
        self.bw, self.bh = bw, bh
        self.lost = 0
        if score >= _UPDATE_SCORE:
            self._blend(cur)
        self.pts = pts
        if self.pts is None or len(self.pts) < _REFRESH_PTS:
            fresh = self._detect(cur)
            if fresh is not None:
                self.pts = fresh if self.pts is None else np.concatenate([self.pts, fresh])
        self.prev = cur
        return self.bbox

    # --- iç işlemler ---
    def _prep(self, frame_bgr: np.ndarray) -> np.ndarray:
        cv2 = self._cv2
        g = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        if self.s < 1.0:
            g = cv2.resize(g, (max(round(self.fw * self.s), 1), max(round(self.fh * self.s), 1)),
                           interpolation=cv2.INTER_AREA)
        return g

    def _rect(self, cx: float, cy: float, bw: float, bh: float) -> tuple[int, int, int, int]:
        """Görüntü içine kıstırılmış (x1, y1, x2, y2) tamsayı dikdörtgen; en az 4x4."""
        x1, y1 = int(round(cx - bw / 2)), int(round(cy - bh / 2))
        x2, y2 = max(x1 + 4, int(round(cx + bw / 2))), max(y1 + 4, int(round(cy + bh / 2)))
        x1, x2 = max(min(x1, self.gw - 4), 0), min(max(x2, 4), self.gw)
        y1, y2 = max(min(y1, self.gh - 4), 0), min(max(y2, 4), self.gh)
        return x1, y1, x2, y2

    def _crop(self, gray: np.ndarray, cx: float, cy: float, bw: float, bh: float) -> np.ndarray:
        x1, y1, x2, y2 = self._rect(cx, cy, bw, bh)
        return gray[y1:y2, x1:x2].copy()

    def _detect(self, gray: np.ndarray) -> np.ndarray | None:
        cv2 = self._cv2
        hw, hh = max(self.bw * _CORE / 2, 4.0), max(self.bh * _CORE / 2, 4.0)
        x1, y1, x2, y2 = self._rect(self.cx, self.cy, 2 * hw, 2 * hh)
        mask = np.zeros_like(gray)
        mask[y1:y2, x1:x2] = 255
        pts = cv2.goodFeaturesToTrack(gray, 40, 0.01, 3, mask=mask)
        return pts if pts is not None and len(pts) >= _MIN_PTS else None

    def _lk(self, cur: np.ndarray):
        """Optik akışla (cx, cy, bw, bh, pts) önerisi; güvenilir değilse None."""
        cv2 = self._cv2
        pts = self.pts if self.pts is not None else self._detect(self.prev)
        if pts is None or len(pts) < _MIN_PTS:
            return None
        lk = {"winSize": (21, 21), "maxLevel": 3,
              "criteria": (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.03)}
        p1, st, _ = cv2.calcOpticalFlowPyrLK(self.prev, cur, pts, None, **lk)
        p0r, st2, _ = cv2.calcOpticalFlowPyrLK(cur, self.prev, p1, None, **lk)
        fb = np.linalg.norm((pts - p0r).reshape(-1, 2), axis=1)
        good = (st.ravel() == 1) & (st2.ravel() == 1) & (fb < _FB_ERR)
        if int(good.sum()) < _MIN_PTS:
            return None
        a, b = pts[good].reshape(-1, 2), p1[good].reshape(-1, 2)
        dx, dy = np.median(b - a, axis=0)
        bw, bh = self.bw, self.bh
        if len(a) >= 8:  # ölçek: merkeze uzaklıkların oranı
            d0 = np.linalg.norm(a - a.mean(axis=0), axis=1)
            d1 = np.linalg.norm(b - b.mean(axis=0), axis=1)
            ok = d0 > 2.0
            if int(ok.sum()) >= 6:
                k = float(np.median(d1[ok] / d0[ok])) ** 0.5  # yarıya vurup yumuşat
                k = min(max(k, 1 / _MAX_SCALE_STEP), _MAX_SCALE_STEP)
                bw, bh = bw * k, bh * k
        return self.cx + float(dx), self.cy + float(dy), bw, bh, b.reshape(-1, 1, 2)

    def _tmpl_for(self, w: int, h: int) -> np.ndarray:
        t = self.tmpl
        if t.shape[1] == w and t.shape[0] == h:
            return t
        return self._cv2.resize(t, (w, h), interpolation=self._cv2.INTER_AREA)

    def _score(self, cur: np.ndarray, cx: float, cy: float, bw: float, bh: float) -> float:
        cv2 = self._cv2
        patch = self._crop(cur, cx, cy, bw, bh)
        t = self._tmpl_for(patch.shape[1], patch.shape[0])
        if t.std() < 2.0 or patch.std() < 2.0:  # düz bölge: NCC tanımsız → ortalama farkı
            return float(max(0.0, 1.0 - abs(float(t.mean()) - float(patch.mean())) / 64.0))
        v = float(cv2.matchTemplate(patch, t, cv2.TM_CCOEFF_NORMED)[0, 0])
        return v if np.isfinite(v) else 0.0

    def _search(self, cur: np.ndarray) -> tuple[float, float, float] | None:
        """Son konum çevresinde şablon eşleştirme → (cx, cy, skor); eşik altıysa None."""
        cv2 = self._cv2
        t = self._tmpl_for(max(int(round(self.bw)), 4), max(int(round(self.bh)), 4))
        th, tw = t.shape[:2]
        grow = min(1.5 + 0.25 * self.lost, 4.0)
        rx, ry = tw * grow, th * grow
        x1, y1 = max(int(self.cx - tw / 2 - rx), 0), max(int(self.cy - th / 2 - ry), 0)
        x2, y2 = min(int(self.cx + tw / 2 + rx), self.gw), min(int(self.cy + th / 2 + ry), self.gh)
        region = cur[y1:y2, x1:x2]
        if region.shape[0] < th or region.shape[1] < tw or t.std() < 2.0:
            return None
        res = np.nan_to_num(cv2.matchTemplate(region, t, cv2.TM_CCOEFF_NORMED), nan=0.0)
        _, score, _, loc = cv2.minMaxLoc(res)
        thr = self.min_score + (0.1 if self.lost else 0.0)
        if score < thr:
            return None
        return x1 + loc[0] + tw / 2, y1 + loc[1] + th / 2, float(score)

    def _blend(self, cur: np.ndarray) -> None:
        """Şablonu yeni görünümle yavaşça karıştır (ışık/poz değişimine uyum; kayma riskine karşı
        yalnız yüksek skorda)."""
        cv2 = self._cv2
        patch = self._crop(cur, self.cx, self.cy, self.bw, self.bh)
        t = self._tmpl_for(patch.shape[1], patch.shape[0])
        self.tmpl = cv2.addWeighted(t, 0.85, patch, 0.15, 0)
