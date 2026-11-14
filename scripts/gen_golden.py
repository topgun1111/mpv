"""Android golden fixtures: Python reference → android/core/src/test/resources/golden/*.json.

Kotlin tests (`core`) must match these. `python scripts/gen_golden.py` rewrites them;
`tests/test_golden.py` fails when the committed files are stale.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tracker.config import Config  # noqa: E402
from tracker.export import crop_rect  # noqa: E402
from tracker.offline import make_doc, save_views, view_at  # noqa: E402
from tracker.smooth import OneEuro  # noqa: E402

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
             "config": _config(), **_docs()}
    return {f"{k}.json": json.dumps(v, indent=1, sort_keys=True) + "\n" for k, v in parts.items()}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in build().items():
        (OUT / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"{len(build())} fixtures → {OUT}")


if __name__ == "__main__":
    main()
