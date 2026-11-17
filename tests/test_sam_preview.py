"""S6: SAM önizleme verisi (kontur + birleşik dikdörtgen + durum) ve CLI. Sahte motor; model/GPU gerekmez."""
import json
from types import SimpleNamespace

import numpy as np
import pytest
from test_sam_track import _avi, _cli, logits

from tracker import sam_engine as se
from tracker import sam_preview as sp
from tracker import sam_track as st
from tracker.main import main

pytest.importorskip("cv2")


def test_preview_path_sits_next_to_the_video():
    assert sp.preview_path("a/b/x.mp4").name == "x.mp4.sam.preview.json"


def test_outline_is_normalized_closed_and_bounded():
    pts = sp.outline(logits((16, 32, 47, 95)) > 0)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert 3 <= len(pts) <= sp.MAX_POINTS
    assert min(xs) == pytest.approx(16 / se.M, abs=0.01) and max(xs) == pytest.approx(48 / se.M, abs=0.01)
    assert min(ys) == pytest.approx(32 / se.M, abs=0.01) and max(ys) == pytest.approx(96 / se.M, abs=0.01)


def test_outline_takes_the_largest_blob_accepts_logits_and_handles_empty():
    pts = sp.outline(logits((2, 2, 5, 5), (100, 100, 200, 200)))  # logit girdi (> 0)
    assert min(p[0] for p in pts) > 0.2  # küçük leke değil, büyük olan
    assert sp.outline(np.zeros((se.M, se.M), bool)) == []


def test_outline_point_count_is_capped_for_ragged_masks():
    rng = np.random.default_rng(1)
    m = np.zeros((se.M, se.M), bool)
    m[20:100, 20:100] = True
    m[rng.random(m.shape) < 0.04] ^= True  # pürüzlü kenar
    assert len(sp.outline(m, max_points=40)) <= 40


def test_payload_clamps_rects_and_rounds():
    p = sp.make_payload("TRACKED", conf=0.123456, rect=(-0.2, 0.5, 1.4, 0.1), drawn=None, t=1.23456, index=3)
    assert p["rect"] == [0.0, 0.1, 1.0, 0.5] and p["drawn"] is None and p["conf"] == 0.123 and p["v"] == 1


def test_from_first_gives_confirm_state_with_mask_box_and_drawn_rect():
    res = SimpleNamespace(mask_logits=logits((16, 32, 47, 95)), box_norm=(0.1, 0.2, 0.3, 0.4), rect=(8, 8, 56, 40),
                          size=(64, 48), iou=0.9, object_score=3.0)
    p = sp.from_first(res, t=2.0)
    assert p["state"] == "CONFIRM" and p["rect"] == [0.1, 0.2, 0.3, 0.4] and p["drawn"] == [0.125, 0.1667, 0.875, 0.8333]
    assert p["conf"] == pytest.approx(0.9 * 0.9526, abs=0.01) and len(p["outline"]) >= 3 and p["t"] == 2.0


def test_no_mask_payload_keeps_the_drawn_rect_and_a_hint():
    p = sp.no_mask((0.1, 0.1, 0.5, 0.5))
    assert p["state"] == "NO_MASK" and p["outline"] == [] and p["rect"] is None and "yeniden" in p["note"]


def test_from_record_uses_state_conf_box_and_mask():
    rec = st.TrackRecord(index=4, t=0.4, state="LOST", accepted=False, box=(0.2, 0.3, 0.6, 0.9), area=0.1, iou=0.5,
                         object_score=1.0, conf=0.31, ratio=1.0, mask=logits((10, 10, 40, 40)) > 0)
    p = sp.from_record(rec, drawn=(0.1, 0.1, 0.5, 0.5))
    assert (p["state"], p["conf"], p["index"], p["rect"]) == ("LOST", 0.31, 4, [0.2, 0.3, 0.6, 0.9]) and p["outline"]
    rec.mask = None
    assert sp.from_record(rec)["outline"] == []


def test_save_is_atomic_and_valid_json(tmp_path):
    f = sp.save(tmp_path / "x.sam.preview.json", sp.make_payload("DONE"))
    assert json.loads(f.read_text(encoding="utf-8"))["state"] == "DONE" and not list(tmp_path.glob("*.tmp"))


def _rec(i, state="TRACKED"):
    return st.TrackRecord(index=i, t=i / 10, state=state, accepted=True, box=(0.1, 0.1, 0.5, 0.5), area=0.1, iou=0.9,
                          object_score=3.0, conf=0.8, ratio=1.0, mask=logits((10, 10, 40, 40)) > 0)


def test_writer_throttles_but_writes_state_changes_and_finish(tmp_path):
    now = [0.0]
    w = sp.Writer(tmp_path / "p.json", (0.1, 0.1, 0.5, 0.5), every=0.5, clock=lambda: now[0])
    assert w.update(_rec(0)) is True
    now[0] = 0.2
    assert w.update(_rec(1)) is False  # aynı durum, erken
    assert w.update(_rec(2, "LOST")) is True  # durum değişti
    now[0] = 0.8
    assert w.update(_rec(3, "LOST")) is True  # süre doldu
    w.finish(_rec(4))
    d = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
    assert d["state"] == "DONE" and d["index"] == 4 and d["drawn"] == [0.1, 0.1, 0.5, 0.5] and w.writes == 3


# --- CLI ---

def test_cli_sam_preview_writes_confirm_payload(tmp_path, monkeypatch, capsys):
    v = _avi(tmp_path / "k.avi")
    fake_first = SimpleNamespace(mask_logits=logits((16, 32, 47, 95)), box_norm=(0.25, 0.3, 0.75, 0.9), box=(16, 14, 48, 43),
                                 rect=(8, 8, 56, 40), size=(64, 48), iou=0.9, object_score=3.0)

    class Eng:
        def first_mask(self, frame, rect):
            assert frame.shape == (48, 64, 3) and rect == (8, 8, 56, 40)
            return fake_first

    monkeypatch.setattr(se, "SamEngine", lambda md, dev, rule="best", memory=False: Eng())
    assert main(["sam-preview", str(tmp_path), str(v), "--rect", "8,8,56,40", "--device", "cpu"]) == 0
    d = json.loads(sp.preview_path(v).read_text(encoding="utf-8"))
    assert d["state"] == "CONFIRM" and d["rect"] == [0.25, 0.3, 0.75, 0.9] and d["outline"]
    assert "P tuşu" in capsys.readouterr().out


def test_cli_sam_preview_without_mask_exits_1_and_writes_no_mask(tmp_path, monkeypatch, capsys):
    v = _avi(tmp_path / "k.avi")

    class Eng:
        def first_mask(self, frame, rect):
            return None

    monkeypatch.setattr(se, "SamEngine", lambda md, dev, rule="best", memory=False: Eng())
    assert main(["sam-preview", str(tmp_path), str(v), "--rect", "0.1,0.1,0.9,0.9", "--norm"]) == 1
    d = json.loads(sp.preview_path(v).read_text(encoding="utf-8"))
    assert d["state"] == "NO_MASK" and d["drawn"] == [0.1, 0.1, 0.9, 0.9] and "yeniden" in capsys.readouterr().err


def test_cli_sam_preview_bad_rect_exits_1(tmp_path, monkeypatch):
    v, _ = _cli(tmp_path, monkeypatch)
    assert main(["sam-preview", str(tmp_path), str(v), "--rect", "5,5,5,5"]) == 1
    assert not sp.preview_path(v).exists()


def test_cli_sam_track_preview_flag_writes_done_file_and_keeps_json_maskless(tmp_path, monkeypatch):
    v, _ = _cli(tmp_path, monkeypatch)
    assert main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--max-seconds", "0.5", "--preview"]) == 0
    d = json.loads(sp.preview_path(v).read_text(encoding="utf-8"))
    assert d["v"] == 1 and d["state"] == "DONE" and d["drawn"] is not None
    assert "mask" not in (tmp_path / "klip.avi.sam.json").read_text(encoding="utf-8")


def test_cli_sam_track_without_preview_writes_no_preview_file(tmp_path, monkeypatch):
    v, _ = _cli(tmp_path, monkeypatch)
    assert main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--max-seconds", "0.3"]) == 0
    assert not sp.preview_path(v).exists()
