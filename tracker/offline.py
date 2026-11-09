"""Offline mod (Parça 9): videoyu baştan sona işle → `track.json`.

Aşamalar (hepsi IO'suz, testli; yalnız `VideoSource` cv2 kullanır):
  1. `run_detection`: kareler → Pipeline → örnek başına normalize izler.
  2. `pick_target_id`: hedef kimliği (ID ya da zaman+nokta ile).
  3. `build_views`: hedefin izinden zoom/pan anahtar kareleri. Canlı moddan farkı **nedensel
     olmamasıdır**: sıfır-faz yumuşatma (gecikme yok), kısa kayıplar ileri-geri doğrusal
     doldurulur, uzun kayıplarda bekle → zoom-out (Parça 8) ve hedef dönmeden önce zoom-in.

Şema (sürüm 1), tüm koordinatlar kare boyutuna göre normalize (0..1), zaman sn (video zamanı):
  {"version": 1, "video": {"path", "w", "h", "fps", "duration"}, "sample_fps": 10.0,
   "samples": [{"t": 0.1, "d": [[id, x1, y1, x2, y2, skor], ...]}, ...],
   "target": {"id": 7} | null,
   "views": [[t, zoom, pan_x, pan_y], ...]}   # target yoksa []
Hedef seçilince ayrıca küçük bir `<video>.views.json` yazılır (`save_views`): yalnız
{"version", "video": {"path"}, "target", "views"}; Lua (Parça 10) bunu okur, büyük `samples`'ı
ayrıştırmaz. `views` doğrudan mpv `video-zoom`/`video-pan-x/y` değerleridir (Parça 10 Lua bunları
`time-pos`'a göre interpole eder); `samples` hedefi sonradan değiştirmek içindir.
"""
from __future__ import annotations

import json
from pathlib import Path

from .bytetrack import Track
from .config import Config
from .geometry import BBox, View, compute_view
from .live import pick_track
from .smooth import ease_view, smooth_zero_phase

SCHEMA_VERSION = 1


class VideoSource:
    """cv2.VideoCapture ile `fps` hızında örneklenmiş (t, BGR kare); sabit kare hızı varsayılır."""

    def __init__(self, path: str, fps: float = 10.0):
        import cv2

        self.path, self.fps = path, fps
        self._cv2 = cv2
        self._cap = cv2.VideoCapture(path)
        if not self._cap.isOpened():
            raise FileNotFoundError(f"video açılamadı: {path}")
        self.w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.src_fps = self._cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.n_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration = self.n_frames / self.src_fps if self.n_frames > 0 else 0.0

    def __iter__(self):
        idx, next_t, step = 0, 0.0, 1.0 / max(self.fps, 0.1)
        try:
            while self._cap.grab():  # grab ucuzdur; yalnızca örneklenen kare çözülür (retrieve)
                t = idx / self.src_fps
                idx += 1
                if t + 1e-9 < next_t:
                    continue
                ok, frame = self._cap.retrieve()
                if not ok:
                    break
                next_t += step
                yield t, frame
        finally:
            self._cap.release()


def run_detection(frames, pipeline, progress=None, total: int | None = None):
    """`frames`: (t, kare) üreteci → (örnekler, (w, h)). Kare boyutu ilk kareden alınır."""
    samples, size = [], None
    for n, (t, frame) in enumerate(frames, 1):
        h, w = frame.shape[:2]
        size = size or (w, h)
        d = []
        for tr in pipeline.step(frame):
            b = tr.bbox
            d.append([tr.id, round(b.x1 / w, 4), round(b.y1 / h, 4),
                      round(b.x2 / w, 4), round(b.y2 / h, 4), round(tr.score, 3)])
        samples.append({"t": round(t, 3), "d": d})
        if progress:
            progress(n, total)
    return samples, size or (0, 0)


def make_doc(path: str, size, fps_src: float, duration: float, sample_fps: float,
             samples: list) -> dict:
    return {"version": SCHEMA_VERSION,
            "video": {"path": path, "w": size[0], "h": size[1], "fps": round(fps_src, 3),
                      "duration": round(duration, 3)},
            "sample_fps": sample_fps, "samples": samples, "target": None, "views": []}


def save_doc(doc: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False),
                          encoding="utf-8")


def views_path(track_path: str | Path) -> Path:
    """`x.mp4.track.json` → `x.mp4.views.json` (Lua `<video>.views.json` arar); diğer adlarda
    `<ad>.views.json`."""
    p = Path(track_path)
    if p.name.endswith(".track.json"):
        return p.with_name(p.name[: -len(".track.json")] + ".views.json")
    return p.with_name(p.stem + ".views.json")


def save_views(doc: dict, path: str | Path) -> None:
    """Oynatma için küçük dosya: `samples` olmadan yalnız hedef + görünüm anahtar kareleri."""
    small = {"version": SCHEMA_VERSION, "video": {"path": doc["video"].get("path", "")},
             "target": doc.get("target"), "views": doc.get("views", [])}
    Path(path).write_text(json.dumps(small, separators=(",", ":"), ensure_ascii=False),
                          encoding="utf-8")


def view_at(views: list[list[float]], t: float) -> tuple[float, float, float]:
    """Anahtar kareler arası doğrusal (uçlarda sabit) — `track.lua::view_at` ile aynı formül."""
    if not views:
        return 0.0, 0.0, 0.0
    if t <= views[0][0]:
        return tuple(views[0][1:4])  # type: ignore[return-value]
    if t >= views[-1][0]:
        return tuple(views[-1][1:4])  # type: ignore[return-value]
    lo, hi = 0, len(views) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if views[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    a, b = views[lo], views[hi]
    f = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
    return tuple(a[k] + (b[k] - a[k]) * f for k in (1, 2, 3))  # type: ignore[return-value]


def load_doc(path: str | Path) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    ver = doc.get("version") if isinstance(doc, dict) else None
    if ver != SCHEMA_VERSION:
        raise ValueError(f"desteklenmeyen track.json sürümü: {ver}")
    for k in ("video", "samples"):
        if k not in doc:
            raise ValueError(f"track.json'da '{k}' yok")
    doc.setdefault("target", None)
    doc.setdefault("views", [])
    return doc


def list_tracks(doc: dict) -> list[dict]:
    """Kimlik başına {id, first, last, n}; en çok görünenden aza."""
    info: dict[int, dict] = {}
    for s in doc["samples"]:
        for d in s["d"]:
            e = info.setdefault(d[0], {"id": d[0], "first": s["t"], "last": s["t"], "n": 0})
            e["last"], e["n"] = s["t"], e["n"] + 1
    return sorted(info.values(), key=lambda e: -e["n"])


def pick_target_id(doc: dict, t: float, nx: float, ny: float, tol: float = 0.03) -> int | None:
    """`t` anına en yakın örnekte (nx, ny) noktasındaki kişinin kimliği; yoksa None."""
    samples = doc["samples"]
    if not samples:
        return None
    s = min(samples, key=lambda x: abs(x["t"] - t))
    w, h = doc["video"]["w"] or 1, doc["video"]["h"] or 1
    tracks = [Track(d[0], BBox(d[1] * w, d[2] * h, d[3] * w, d[4] * h), d[5], 0, 0)
              for d in s["d"]]
    tr = pick_track(tracks, nx * w, ny * h, tol * h)
    return tr.id if tr else None


def _runs(idx: list[int]) -> list[list[int]]:
    """Ardışık tam sayı dizilerine böl."""
    out: list[list[int]] = []
    for i in idx:
        if out and out[-1][-1] == i - 1:
            out[-1].append(i)
        else:
            out.append([i])
    return out


def build_views(doc: dict, target_id: int, cfg: Config) -> list[list[float]]:
    """Hedefin izinden [t, zoom, pan_x, pan_y] anahtar kareleri (sabit duranlar seyreltilir)."""
    samples = doc["samples"]
    n = len(samples)
    ts = [s["t"] for s in samples]
    if n == 0:
        return []
    boxes: dict[int, list[float]] = {}  # örnek → [cx, cy, w, h] (normalize)
    for i, s in enumerate(samples):
        for d in s["d"]:
            if d[0] == target_id:
                b = BBox(d[1], d[2], d[3], d[4])
                boxes[i] = [b.cx, b.cy, b.w, b.h]
    vis = sorted(boxes)
    # 1) kısa kayıpları doğrusal doldur (ileri-geri bilgi: non-causal)
    for a, b in zip(vis, vis[1:], strict=False):
        if b - a > 1 and ts[b] - ts[a] <= cfg.offline_interp_s:
            for i in range(a + 1, b):
                f = (ts[i] - ts[a]) / max(ts[b] - ts[a], 1e-9)
                boxes[i] = [boxes[a][k] + (boxes[b][k] - boxes[a][k]) * f for k in range(4)]
    present = sorted(boxes)
    views: dict[int, View] = {}
    # 2) görünür parçalarda sıfır-faz yumuşatma → compute_view
    for run in _runs(present):
        sm = []
        for k in range(4):
            a = cfg.offline_alpha * (1.0 if k < 2 else 0.4)
            sm.append(smooth_zero_phase([boxes[i][k] for i in run], a))
        for j, i in enumerate(run):
            cx, cy, w, h = sm[0][j], sm[1][j], sm[2][j], sm[3][j]
            bb = BBox(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            views[i] = compute_view(bb, 1.0, 1.0, cfg.target_fill, cfg.min_zoom, cfg.max_zoom)
    # 3) uzun kayıplar: bekle → zoom-out, hedef dönmeden önce zoom-in
    hold, dur = max(cfg.lost_hold_s, 0.0), cfg.lost_zoomout_s
    i = 0
    while i < n:
        if i in views:
            i += 1
            continue
        j = i
        while j < n and j not in views:
            j += 1
        prev, nxt = (views[i - 1] if i > 0 else None), (views[j] if j < n else None)
        t0, t1 = ts[i], (ts[j] if j < n else None)
        for k in range(i, j):
            t = ts[k]
            if prev is None:
                v = View()
            else:
                el = t - t0 - hold
                v = ease_view(prev, View(), (el / dur) if dur > 0 else (1.0 if el >= 0 else 0.0))
            if nxt is not None:
                q = (t - (t1 - dur)) / dur if dur > 0 else 0.0
                v = ease_view(v, nxt, q)
            views[k] = v
        i = j
    # 4) çıktı: sabit duran yinelenen anahtar kareleri at
    out: list[list[float]] = []
    keys = [[ts[k], round(views[k].zoom, 4), round(views[k].pan_x, 4), round(views[k].pan_y, 4)]
            for k in range(n)]
    for k, kf in enumerate(keys):
        if 0 < k < n - 1 and keys[k - 1][1:] == kf[1:] == keys[k + 1][1:]:
            continue
        out.append(kf)
    return out


def apply_target(doc: dict, target_id: int, cfg: Config) -> dict:
    doc["target"] = {"id": target_id}
    doc["views"] = build_views(doc, target_id, cfg)
    return doc
