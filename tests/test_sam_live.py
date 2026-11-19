"""F2: mpv dikdörtgeni -> canlı SAM izleyici.

Sahte grafikler (test_sam_track) kullanılır; model/GPU gerekmez.
"""
from types import SimpleNamespace

import numpy as np
import pytest
from test_sam_track import GOOD, FakeDec, logits, make

from tracker import errlog, sam_live
from tracker.geometry import BBox
from tracker.live import LiveController
from tracker.sam_engine import to_frame_box
from tracker.sam_track import NoInitialMask

RECT = (8.0, 8.0, 56.0, 40.0)
W, H = 64, 48


def frame():
    return np.zeros((H, W, 3), np.uint8)


def tracker(script, **kw):
    eng, parts = make(script, **kw)
    return sam_live.SamPointTracker(eng, frame(), RECT), parts


def test_first_frame_gives_the_mask_box_in_frame_pixels():
    tr, _ = tracker([GOOD])
    x1, y1, x2, y2 = to_frame_box((64 / 256, 32 / 256, 128 / 256, 96 / 256), W, H)
    assert tr.bbox == BBox(x1, y1, x2, y2)
    assert tr.label == "SAM" and tr.visible


def test_each_update_consumes_exactly_one_frame_and_returns_a_box():
    tr, parts = tracker([GOOD, GOOD])
    box = tr.update(frame())
    assert isinstance(box, BBox) and box.w > 0
    assert len(parts.trk.calls) == 1
    tr.update(frame())
    assert len(parts.trk.calls) == 2


def test_lost_frame_returns_none_then_tracking_resumes_from_memory():
    tr, _ = tracker([(None, 0.9, -5.0), GOOD])
    assert tr.update(frame()) is None and tr.visible is False
    assert tr.bbox.w > 0  # son bilinen kutu korunur
    assert tr.update(frame()) is not None and tr.visible is True


def test_frame_size_change_kills_the_tracker_and_logs(monkeypatch):
    seen = []
    monkeypatch.setattr(errlog, "record", lambda w, e=None: seen.append(w))
    tr, _ = tracker([GOOD])
    assert tr.update(np.zeros((H + 8, W, 3), np.uint8)) is None
    assert tr.dead and seen == ["SAM canlı takip"]
    assert tr.update(frame()) is None


def test_engine_error_is_contained(monkeypatch):
    monkeypatch.setattr(errlog, "record", lambda *a, **k: None)
    tr, _ = tracker([])  # betikte izleme çağrısı yok -> IndexError
    assert tr.update(frame()) is None and tr.dead


def test_no_initial_mask_raises():
    eng, _ = make([GOOD], dec=type("D", (FakeDec,), {"run": lambda s, n, f: [
        np.stack([logits(), logits(), logits()])[None], np.array([[0.5, 0.9, 0.7]], np.float32),
        np.zeros((1, 3, 256), np.float32), np.array([[3.0]], np.float32)]})())
    with pytest.raises(NoInitialMask):
        sam_live.SamPointTracker(eng, frame(), RECT)


def _fallbacks():
    calls = []
    return calls, lambda f, px, py, cfg, box=None: calls.append(box) or "old"


def test_factory_uses_sam_only_for_rectangles():
    calls, fb = _fallbacks()
    eng, _ = make([GOOD])
    f = sam_live.make_factory(fb, engine_factory=lambda cfg: eng)
    cfg = SimpleNamespace(sam_live=True)
    assert isinstance(f(frame(), 10, 10, cfg, box=RECT), sam_live.SamPointTracker)
    assert f(frame(), 10, 10, cfg) == "old" and calls == [None]  # tek tık: eski izleyici


def test_factory_falls_back_when_disabled_or_engine_missing():
    calls, fb = _fallbacks()
    f = sam_live.make_factory(fb, engine_factory=lambda cfg: None)
    assert f(frame(), 1, 1, SimpleNamespace(sam_live=True), box=RECT) == "old"
    eng, _ = make([GOOD])
    g = sam_live.make_factory(fb, engine_factory=lambda cfg: eng)
    assert g(frame(), 1, 1, SimpleNamespace(sam_live=False), box=RECT) == "old"
    assert len(calls) == 2


def test_factory_falls_back_on_unexpected_start_error(monkeypatch):
    monkeypatch.setattr(errlog, "record", lambda *a, **k: None)
    calls, fb = _fallbacks()
    eng, _ = make([GOOD], memory=False)  # bellek grafikleri yok -> ValueError/FileNotFound
    f = sam_live.make_factory(fb, engine_factory=lambda cfg: eng)
    assert f(frame(), 1, 1, SimpleNamespace(sam_live=True), box=RECT) == "old"


def test_factory_reraises_no_initial_mask_so_the_user_redraws():
    _, fb = _fallbacks()

    class Empty:
        def __getattr__(self, n):
            raise NoInitialMask("x")

    f = sam_live.make_factory(fb, engine_factory=lambda cfg: Empty())
    with pytest.raises(Exception):
        f(frame(), 1, 1, SimpleNamespace(sam_live=True), box=RECT)


def test_models_ready_needs_all_five_graphs(tmp_path):
    assert not sam_live.models_ready(tmp_path)
    for n in ("sam-encoder", "sam-decoder", "sam-decoder-trk", "sam-memenc", "sam-memattn"):
        (tmp_path / f"{n}.onnx").write_bytes(b"x")
    assert sam_live.models_ready(tmp_path)


def test_model_dir_follows_the_panel_selection():
    assert sam_live.model_dir(SimpleNamespace(sam_model_variant="sam2_small")).name == "small"
    assert sam_live.model_dir(SimpleNamespace(sam_model_variant="edgetam")).name == "edgetam"


def test_default_controller_wires_the_sam_factory():
    from tracker.config import Config

    ctl = LiveController(object(), Config())
    assert ctl._point_factory.__name__ == "factory"
    assert Config().sam_live is True
