"""Android golden fixtures: Python reference → android/core/src/test/resources/golden/*.json.

Kotlin tests (`core`) must match these. `python scripts/gen_golden.py` rewrites them;
`tests/test_golden.py` fails when the committed files are stale.
"""
from __future__ import annotations

import json
import random
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tracker.bytetrack import ByteTracker, KalmanBox, linear_assignment  # noqa: E402
from tracker.config import Config  # noqa: E402
from tracker.export import crop_rect  # noqa: E402
from tracker.geometry import BBox  # noqa: E402
from tracker.offline import make_doc, save_views, view_at  # noqa: E402
from tracker.smooth import BoxFilter, Kalman1D, OneEuro  # noqa: E402

OUT = ROOT / "android" / "core" / "src" / "test" / "resources" / "golden"

# Config keys shared with Android (same names/defaults, handover-android.md §5).
SHARED_KEYS = (
    "det_conf det_iou det_size live_det_conf offline_fps offline_interp_s offline_alpha "
    "target_fill min_zoom max_zoom alpha_pos alpha_zoom dead_zone_pos dead_zone_zoom "
    "lost_hold_s lost_zoomout_s kf_accel kf_meas gmc gmc_side cut_detect cut_hist cut_diff "
    "pick_tol pose_conf kp_min_conf kp_box kp_hold_s kp_filter kp_world"
).split()

VIEWS = [[0.0, 0.0, 0.0, 0.0], [1.0, 1.0, 0.1, -0.05], [2.5, 2.0, -0.2, 0.15], [4.0, 0.5, 0.0, 0.0]]


def _view_at() -> dict:
    ts = [-1.0, 0.0, 0.25, 1.0, 1.7, 2.5, 3.0, 4.0, 9.0]
    return {"views": VIEWS, "cases": [{"t": t, "v": list(view_at(VIEWS, t))} for t in ts],
            "empty": list(view_at([], 1.0))}


def _crop_rect() -> dict:
    views = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.4, -0.4), (2.0, -0.3, 0.2),
             (-1.0, 0.2, 0.2), (0.5, 0.123, -0.077), (3.0, 0.0, 0.0), (0.01, 0.5, 0.5)]
    sizes = [(640, 360), (1920, 1080), (1281, 721)]
    return {"cases": [{"view": list(v), "w": w, "h": h, "rect": list(crop_rect(v, w, h))}
                      for v in views for w, h in sizes]}


def _one_euro() -> dict:
    xs = [0.50, 0.51, 0.49, 0.50, 0.60, 0.75, 0.80, 0.80, 0.79, 0.81]
    ts = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.5, 0.7, 0.8, 1.0]  # t=0.5 repeats (dt = 0 → hold)
    out = []
    for kw in ({}, {"min_cutoff": 0.5, "beta": 5.0, "d_cutoff": 2.0}):
        f = OneEuro(**kw)
        out.append({"params": kw, "t": ts, "x": xs, "y": [f.update(x, t) for x, t in zip(xs, ts)]})
    return {"runs": out}


def _config() -> dict:
    d = asdict(Config())
    return {k: d[k] for k in SHARED_KEYS}


def _f(a) -> list:
    return [float(v) for v in a]


class _Det:
    """Minimal stand-in for tracker.detector.Detection (ByteTracker reads bbox + score only)."""

    def __init__(self, box, score):
        self.bbox, self.score = BBox(*box), score


def _assignment() -> dict:
    rng = random.Random(11)
    cases = []
    for n, m in [(3, 3), (2, 5), (5, 2), (4, 4), (1, 3), (6, 6), (0, 3)]:
        c = [[round(rng.uniform(0, 1), 6) for _ in range(m)] for _ in range(n)]
        pairs = linear_assignment(np.array(c, float).reshape(n, m))
        cases.append({"cost": c, "n": n, "m": m, "pairs": sorted([i, j] for i, j in pairs)})
    return {"cases": cases}


def _kalman_box() -> dict:
    kb = KalmanBox(BBox(100, 50, 140, 150))
    ops = [{"op": "predict"}, {"op": "update", "box": [103, 52, 144, 151]}, {"op": "predict"},
           {"op": "predict"}, {"op": "update", "box": [110, 55, 150, 158]},
           {"op": "compensate", "m": [[1.02, 0.01, 5.0], [-0.01, 1.02, -3.0], [0, 0, 1]]},
           {"op": "predict"}, {"op": "update", "box": [120, 60, 163, 165]}]
    out = []
    for o in ops:
        if o["op"] == "predict":
            kb.predict()
        elif o["op"] == "update":
            kb.update(BBox(*o["box"]))
        else:
            kb.compensate(np.array(o["m"], float))
        out.append({"x": _f(kb.x), "p": _f(np.diag(kb.P))})
    return {"init": [100, 50, 140, 150], "ops": ops, "out": out}


def _kalman_1d() -> dict:
    steps = [(0.1, 1.0), (0.1, 1.2), (0.0, 1.3), (0.2, 1.9), (0.1, 2.0), (-0.1, 5.0), (0.1, 2.4)]
    k = Kalman1D(1.0, 0.01, 0.5, 0.5)
    out = []
    for dt, z in steps:
        k.predict(dt)
        k.update(z)
        out.append(_f([k.p, k.v, k.p00, k.p01, k.p11]))
    return {"args": [1.0, 0.01, 0.5, 0.5], "steps": [list(s) for s in steps], "out": out}


def _box_filter() -> dict:
    ts = [0.0, 0.1, 0.2, 0.3, 0.2, 0.4, 2.0, 2.1, 2.2]  # 0.2 = backward jump, 2.0 = gap > max_gap
    boxes = [[0.40 + 0.02 * i, 0.30, 0.50 + 0.02 * i, 0.60] for i in range(len(ts))]
    runs = []
    for kw in ({}, {"accel": 1.0, "meas": 0.02, "size_ratio": 0.5, "max_gap": 0.25}):
        f = BoxFilter(**kw)
        rows = []
        for t, b in zip(ts, boxes, strict=True):
            fb = f.update(BBox(*b), t)
            rows.append({"box": _f([fb.x1, fb.y1, fb.x2, fb.y2]), "vel": _f(f.velocity),
                         "look": _f([getattr(f.lookahead(0.15, 0.15), a)
                                     for a in ("x1", "y1", "x2", "y2")])})
        runs.append({"params": kw, "rows": rows})
    return {"t": ts, "boxes": boxes, "runs": runs}


def _scenario() -> list[dict]:
    rng = random.Random(5)
    # (x0, y0, vx, vy, w, h, first, last, score)
    objs = [(50, 100, 4, 0, 40, 100, 0, 44, 0.9), (400, 120, -4, 0, 42, 98, 0, 44, 0.85),
            (200, 300, 1, -1, 36, 90, 10, 44, 0.8), (600, 50, 0, 3, 30, 80, 0, 20, 0.95)]
    frames = []
    for i in range(45):
        dets = []
        for k, (x0, y0, vx, vy, w, h, a, b, sc) in enumerate(objs):
            if not a <= i <= b or (k == 1 and 25 <= i <= 28):  # object 1 vanishes 4 frames
                continue
            s = 0.3 if (k == 1 and 15 <= i <= 19) else sc  # object 1 low score (2nd stage)
            x, y = x0 + vx * i + rng.uniform(-1.5, 1.5), y0 + vy * i + rng.uniform(-1.5, 1.5)
            dets.append([round(v, 4) for v in (x, y, x + w, y + h)] + [s])
        dets.append([5.0, 5.0, 25.0, 45.0, 0.05])  # below low_thr: ignored
        m = None
        if 30 <= i <= 34:
            m = [[1, 0, -6.0], [0, 1, 2.0], [0, 0, 1]]
        elif i == 35:
            m = [[1.02, 0.01, 4.0], [-0.01, 1.02, -3.0], [0, 0, 1]]
        frames.append({"dets": dets, "motion": m, "clear": i == 38})
    return frames


def _bytetrack() -> dict:
    frames = _scenario()
    runs = []
    for kw in ({}, {"min_hits": 2, "max_lost": 4, "new_thr": 0.6, "second_iou": 0.4}):
        tr = ByteTracker(**kw)
        tr.set_next_id(5)
        out = []
        for f in frames:
            if f["clear"]:
                tr.clear()
            m = None if f["motion"] is None else np.array(f["motion"], float)
            res = tr.update([_Det(d[:4], d[4]) for d in f["dets"]], m)
            out.append({"tracks": [[t.id, *_f([t.bbox.x1, t.bbox.y1, t.bbox.x2, t.bbox.y2]),
                                    t.score, t.age, t.lost] for t in res],
                        "lost": [t.id for t in tr.lost_tracks], "n_boxes": len(tr.boxes)})
        runs.append({"params": kw, "next_id": 5, "out": out})
    return {"frames": frames, "runs": runs}


def _docs() -> dict:
    kp = [round(0.01 * i, 4) if j < 2 else 0.9 for i in range(17) for j in range(3)]
    samples = [
        {"t": 0.0, "d": [[1, 0.1, 0.2, 0.3, 0.8, 0.91]]},
        {"t": 0.1, "d": [[1, 0.11, 0.2, 0.31, 0.8, 0.9], [2, 0.5, 0.2, 0.6, 0.7, 0.4]],
         "kp": {"1": kp}, "cut": 1},
    ]
    doc = make_doc("clip.mp4", (1280, 720), 29.97, 12.5, 10.0, samples, pose=True)
    doc["target"] = {"id": 1, "part": 15}
    doc["views"] = [[0.0, 1.0, 0.1, 0.2], [0.1, 1.2, 0.12, 0.2]]
    v1 = make_doc("clip.mp4", (1280, 720), 29.97, 12.5, 10.0, samples[:1])
    v1["target"] = {"id": 1}
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "v.json"
        save_views(doc, p)
        views_doc = json.loads(p.read_text(encoding="utf-8"))
    return {"track_v2": doc, "track_v1": v1, "views": views_doc}


def build() -> dict[str, str]:
    parts = {"view_at": _view_at(), "crop_rect": _crop_rect(), "one_euro": _one_euro(),
             "config": _config(), "assignment": _assignment(), "kalman_box": _kalman_box(),
             "kalman_1d": _kalman_1d(), "box_filter": _box_filter(), "bytetrack": _bytetrack(),
             **_docs()}
    return {f"{k}.json": json.dumps(v, indent=1, sort_keys=True) + "\n" for k, v in parts.items()}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in build().items():
        (OUT / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"{len(build())} fixtures → {OUT}")


if __name__ == "__main__":
    main()
