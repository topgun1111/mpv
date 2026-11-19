"""S7: alt vücut bölgesi (görünen / anatomik / sol-sağ / tek kadraj). Saf Python; model ve GPU gerekmez."""
import json
from types import SimpleNamespace

import numpy as np
import pytest
from test_sam_track import _avi, _cli

from tracker import lowerbody as lb
from tracker import sam_preview as sp
from tracker import sam_track as st
from tracker.geometry import BBox
from tracker.main import main

W = H = 1000
SH_Y, HIP_Y = 0.25, 0.55  # gövde boyu L = 0.30 (300 px)
L = 0.30


def make_row(*, hips=True, lk=None, la=None, rk=None, ra=None, sh_y=SH_Y, hip_y=HIP_Y, conf=0.9):
    """Önden görünüm: kişinin SOLU görüntünün SAĞINDA (sol kalça x=.58). Eklem (x, y) ya da None (görünmüyor)."""
    row = [0.0] * 51

    def setj(j, p, c=conf):
        if p is not None:
            row[3 * j:3 * j + 3] = [p[0], p[1], c]

    setj(5, (0.58, sh_y))
    setj(6, (0.42, sh_y))
    if hips:
        setj(11, (0.58, hip_y))
        setj(12, (0.42, hip_y))
    setj(13, lk)
    setj(15, la)
    setj(14, rk)
    setj(16, ra)
    return row


def feed(model, rows, dt=0.1, **kw):
    return [model.update(i * dt, r, (W, H), **kw) for i, r in enumerate(rows)]


def contains(outer, inner, eps=1e-6):
    return (outer[0] <= inner[0] + eps and outer[1] <= inner[1] + eps
            and outer[2] >= inner[2] - eps and outer[3] >= inner[3] - eps)


# --- görünen vs anatomik ---

def test_seated_behind_desk_hips_only_gives_anatomical_thighs_and_no_visible():
    out = lb.LowerBodyModel().update(0.0, make_row(), (W, H))
    assert out.left.hidden and out.right.hidden and out.visible is None
    assert out.source == "pose"
    a = out.anatomical
    assert a[1] == pytest.approx(HIP_Y) and a[3] == pytest.approx(HIP_Y + lb.LEG_REACH * L)  # kalçadan 1 gövde boyu
    assert a[0] < 0.42 and a[2] > 0.58  # iki bacak da kapsanır
    assert out.framing == pytest.approx(out.anatomical)


def test_visible_region_is_contained_in_anatomical_and_follows_shins_and_feet():
    row = make_row(lk=(0.58, 0.72), la=(0.58, 0.85), rk=(0.42, 0.72), ra=(0.42, 0.85))
    out = lb.LowerBodyModel().update(0.0, row, (W, H))
    v, a = out.visible, out.anatomical
    assert not out.left.hidden and not out.right.hidden
    assert v[1] == pytest.approx(0.72 - lb.VIS_PAD * L) and v[3] == pytest.approx(0.85 + lb.VIS_PAD * L)
    assert contains(a, v) and a[1] == pytest.approx(HIP_Y)  # anatomik kalçadan başlar, görünen dizden
    assert out.left.evidence > 0.8 and out.right.evidence > 0.8


def test_invented_joints_behind_the_desk_are_not_visible_evidence():
    # diz/ayak bileği kalçadan çok uzakta (perde arkası uydurma): görünen bölgeye girmez, bacak gizli sayılır
    row = make_row(lk=(0.58, 1.40), la=(0.58, 1.90), conf=0.5)
    out = lb.LowerBodyModel().update(0.0, row, (W, H))
    assert out.left.hidden and out.left.visible is None
    assert out.anatomical[3] < 1.0


def test_missing_landmark_is_not_a_missing_limb_one_hidden_leg_does_not_collapse():
    m = lb.LowerBodyModel()
    both = make_row(lk=(0.58, 0.72), la=(0.58, 0.85), rk=(0.42, 0.72), ra=(0.42, 0.85))
    one = make_row(lk=(0.58, 0.72), la=(0.58, 0.85))  # sağ bacak masanın arkasında
    first, second = feed(m, [both, one])
    assert second.right.hidden and second.right.anatomical is not None and second.right.held is False
    assert second.right.anatomical[3] == pytest.approx(first.right.anatomical[3])  # son alt kenar tutulur
    assert second.anatomical[0] == pytest.approx(first.anatomical[0], abs=1e-9)
    assert second.anatomical[2] == pytest.approx(first.anatomical[2], abs=1e-9)  # genişlik küçülmedi
    assert second.framing is not None


def test_missing_hip_uses_the_other_hip_mirrored_and_marks_the_leg_as_held():
    m = lb.LowerBodyModel()
    full = make_row(la=(0.58, 0.85), ra=(0.42, 0.85))
    r = make_row(la=(0.58, 0.85), ra=(0.42, 0.85))
    r[3 * 12 + 2] = 0.0  # sağ kalça kayıp (oklüzyon)
    a, b = feed(m, [full, r])
    assert b.right.held and not a.right.held
    assert b.right.anatomical[0] == pytest.approx(a.right.anatomical[0], abs=1e-6)


def test_pose_loss_holds_the_last_region_then_gives_up():
    m = lb.LowerBodyModel(hold_s=1.0)
    first = m.update(0.0, make_row(), (W, H))
    held = m.update(0.5, None, (W, H))
    assert held.source == "held" and held.anatomical == pytest.approx(first.anatomical)
    assert held.framing == pytest.approx(first.framing)
    gone = m.update(2.5, None, (W, H))
    assert gone.source == "none" and gone.anatomical is None and gone.framing is None


# --- SAM maskesi ---

def test_mask_only_when_no_pose_ever():
    out = lb.LowerBodyModel().update(0.0, None, (W, H), mask_box=(0.3, 0.6, 0.7, 0.95), mask_conf=0.8)
    assert out.source == "mask" and out.visible == pytest.approx((0.3, 0.6, 0.7, 0.95))
    assert out.anatomical == pytest.approx(out.visible)


def test_low_confidence_or_lost_mask_is_not_evidence():
    m = lb.LowerBodyModel()
    a = m.update(0.0, make_row(), (W, H), mask_box=(0.0, 0.0, 1.0, 1.0), mask_conf=0.3)
    b = m.update(0.1, make_row(), (W, H), mask_box=(0.0, 0.0, 1.0, 1.0), mask_conf=0.9, tracked=False)
    assert a.source == b.source == "pose" and a.visible is None and b.visible is None


def test_mask_that_swallows_torso_and_desk_is_clipped_to_the_leg_zone():
    out = lb.LowerBodyModel().update(0.0, make_row(), (W, H), mask_box=(0.0, 0.05, 1.0, 1.0), mask_conf=0.9)
    assert out.source == "pose+mask"
    v = out.visible
    assert v[1] >= HIP_Y - lb.MASK_TOP_SLACK * L - 1e-9  # gövde dışarıda
    assert v[0] >= 0.42 - lb.LEG_HALF_W * L - lb.MASK_SIDE_SLACK * L - 1e-9  # masanın yanları dışarıda
    assert v[2] <= 0.58 + lb.LEG_HALF_W * L + lb.MASK_SIDE_SLACK * L + 1e-9
    assert v[3] <= HIP_Y + (lb.FULL_LEG + lb.FOOT_PAD) * L + 1e-9
    assert contains(out.anatomical, out.visible)
    assert out.left.mask_overlap is not None and 0 < out.left.mask_overlap <= 1


# --- kadraj: tek ayak hareketi bölgeyi sürüklemez ---

def _standing(la_y=0.50, ra_y=0.50, la_x=0.58, ra_x=0.42, hip_y=0.30, sh_y=0.10):
    # L = 0.20
    return make_row(hip_y=hip_y, sh_y=sh_y, lk=(0.58, 0.40), la=(la_x, la_y), rk=(0.42, 0.40), ra=(ra_x, ra_y))


def test_foot_wiggle_does_not_move_the_framing():
    rng = np.random.default_rng(3)
    rows = [_standing(la_y=0.50 + rng.uniform(-0.01, 0.01), ra_y=0.50 + rng.uniform(-0.01, 0.01),
                      la_x=0.58 + rng.uniform(-0.01, 0.01), ra_x=0.42 + rng.uniform(-0.01, 0.01)) for _ in range(40)]
    outs = feed(lb.LowerBodyModel(), rows)
    fr = np.array([o.framing for o in outs[1:]])
    an = np.array([o.anatomical for o in outs[1:]])
    moved, raw = (fr.max(axis=0) - fr.min(axis=0)).max(), (an.max(axis=0) - an.min(axis=0)).max()
    assert moved < 0.008 and moved < 0.5 * raw  # ham alt kenar titrer, kadraj en çok yarısı kadar kıpırdar


def test_one_extended_foot_does_not_pull_the_framing_bottom():
    m = lb.LowerBodyModel()
    out = m.update(0.0, _standing(la_y=0.50, ra_y=0.66), (W, H))  # sağ ayak öne uzandı: 0.8 L daha aşağıda
    assert out.anatomical[3] > out.framing[3] + 0.04  # anatomik gerçeği söyler, kadraj kovalamaz
    lo = out.left.anatomical[3]
    assert out.framing[3] == pytest.approx(lo + lb.FOOT_LEAD * 0.20, abs=1e-6)


def test_foot_far_to_the_side_is_clamped_in_x():
    out = lb.LowerBodyModel().update(0.0, _standing(ra_x=0.0), (W, H))  # sağ ayak çok yanda
    assert out.right.anatomical[0] >= 0.42 - (lb.SPREAD_MAX + lb.FOOT_HALF_W) * 0.20 - 1e-9


def test_framing_is_smoothed_not_jumping_after_a_real_change():
    m = lb.LowerBodyModel()
    first = m.update(0.0, _standing(), (W, H))
    moved = m.update(0.1, _standing(hip_y=0.40, sh_y=0.20), (W, H))  # kişi 0.1 aşağı indi
    target = lb.LowerBodyModel().update(0.1, _standing(hip_y=0.40, sh_y=0.20), (W, H)).framing
    assert first.framing[1] < moved.framing[1] < target[1]  # kare başına kısmi adım


# --- sol/sağ kimlik ---

def _walk(lx, rx):
    return make_row(hip_y=HIP_Y, la=(lx, 0.85), ra=(rx, 0.85))


def test_label_swap_at_crossing_is_repaired_by_continuity():
    m = lb.LowerBodyModel()
    # gerçek: sol ayak .58 -> .42, sağ ayak .42 -> .58 (adım .08, çaprazlama), son karede model etiketleri takas eder
    path = [(0.58, 0.42), (0.50, 0.50), (0.42, 0.58)]
    outs = feed(m, [_walk(*p) for p in path])
    assert not any(o.swapped for o in outs)  # düzgün çaprazlama: dokunulmaz
    swapped = m.update(0.3, _walk(0.58, 0.42), (W, H))  # etiketler takas: sol .58, sağ .42 (gerçekte tersi)
    assert swapped.swapped
    cx = lambda b: (b[0] + b[2]) / 2  # noqa: E731
    assert cx(swapped.left.visible) == pytest.approx(0.42, abs=0.01)  # sol bacak sürekliliği korudu
    assert cx(swapped.right.visible) == pytest.approx(0.58, abs=0.01)


def test_fast_single_foot_motion_is_not_mistaken_for_a_swap():
    m = lb.LowerBodyModel()
    a = m.update(0.0, _walk(0.58, 0.42), (W, H))
    r = make_row(la=(0.58, 0.60), ra=(0.42, 0.85))  # yalnız sol ayak hızla yukarı
    b = m.update(0.1, r, (W, H))
    assert not a.swapped and not b.swapped


def test_smooth_crossing_keeps_identity_every_frame():
    m = lb.LowerBodyModel()
    xs = np.linspace(0.58, 0.42, 9)
    outs = feed(m, [_walk(x, 1.0 - x) for x in xs])
    assert not any(o.swapped for o in outs)
    assert all(o.framing is not None for o in outs)


# --- biçim ---

def test_to_dict_is_json_and_row_matches_fields():
    out = lb.LowerBodyModel().update(0.0, make_row(la=(0.58, 0.85)), (W, H), mask_box=(0.4, 0.6, 0.7, 0.9),
                                     mask_conf=0.9)
    d = json.loads(json.dumps(out.to_dict()))
    assert set(d["legs"]) == {"left", "right"} and d["source"] == "pose+mask"
    assert len(out.row()) == len(lb.ROW_FIELDS)
    assert len(lb.LowerBodyModel().update(0.0, None, (W, H)).row()) == len(lb.ROW_FIELDS)


def test_no_pose_and_no_mask_is_none_not_a_crash():
    out = lb.LowerBodyModel().update(0.0, None, (W, H))
    assert out.source == "none" and out.framing is None and out.visible is None


def test_short_or_empty_rows_are_ignored():
    out = lb.LowerBodyModel().update(0.0, [0.0] * 10, (W, H))
    assert out.source == "none"


# --- poz seçimi ---

def _pose(x1, y1, x2, y2):
    return SimpleNamespace(bbox=BBox(x1, y1, x2, y2), kpts=np.zeros((17, 3), np.float32), score=0.9)


def test_pick_pose_matches_legs_below_the_seated_person_box():
    seated = _pose(300, 100, 700, 500)  # kişi kutusu yalnız üst gövde
    other = _pose(800, 100, 990, 600)
    legs = (0.35, 0.55, 0.65, 0.80)  # SAM kutusu kutunun ALTINDA (masa arkası bacaklar)
    assert lb.pick_pose([other, seated], legs, (W, H)) is seated


def test_pick_pose_none_without_overlap_and_keeps_continuity_when_mask_is_lost():
    a, b = _pose(100, 100, 300, 500), _pose(600, 100, 800, 500)
    assert lb.pick_pose([a, b], (0.9, 0.9, 0.95, 0.95), (W, H)) is None
    assert lb.pick_pose([a, b], None, (W, H), last_center=(700.0, 300.0)) is b  # maske yok: süreklilik
    assert lb.pick_pose([a, b], None, (W, H)) is None
    assert lb.pick_pose([], (0.1, 0.1, 0.5, 0.5), (W, H)) is None


def test_pose_row_is_normalized_51_values():
    k = np.zeros((17, 3), np.float32)
    k[15] = (500.0, 250.0, 0.8)
    row = lb.pose_row(SimpleNamespace(kpts=k), 1000, 500)
    assert len(row) == 51 and row[45:48] == pytest.approx([0.5, 0.5, 0.8])


def test_follower_lost_record_does_not_use_the_stale_mask_box():
    f = lb.Follower()
    seated = _pose(300, 100, 700, 500)
    row = make_row()
    seated.kpts = np.array([[row[3 * j] * W, row[3 * j + 1] * H, row[3 * j + 2]] for j in range(17)], np.float32)
    ok = SimpleNamespace(t=0.0, box=(0.4, 0.6, 0.6, 0.8), conf=0.9, tracked=True)
    lost = SimpleNamespace(t=0.1, box=(0.4, 0.6, 0.6, 0.8), conf=0.9, tracked=False)
    a = f.step(ok, [seated], (W, H))
    b = f.step(lost, [seated], (W, H))  # poz yine süreklilikle seçilir; maske kanıt sayılmaz
    assert a.source == "pose+mask" and b.source == "pose"


# --- önizleme + kayıt + CLI ---

def test_preview_payload_carries_lower_fields_and_framing_becomes_the_combined_rect():
    out = lb.LowerBodyModel().update(0.0, make_row(la=(0.58, 0.85), ra=(0.42, 0.85)), (W, H))
    pay = sp.make_payload("TRACKED", conf=0.9, rect=(0.0, 0.0, 0.1, 0.1), lower=out)
    assert pay["v"] == sp.VERSION and pay["rect"] == pytest.approx(sp.clamp_rect(out.framing))
    assert set(pay["lower"]) >= {"visible", "anatomical", "framing", "legs", "source"}
    plain = sp.make_payload("TRACKED", rect=(0.1, 0.1, 0.2, 0.2))
    assert "lower" not in plain and plain["rect"] == [0.1, 0.1, 0.2, 0.2]  # S6 davranışı bozulmadı


def test_make_doc_writes_lower_block_only_when_given(tmp_path):
    v = _avi(tmp_path / "k.avi", 3)
    rec = st.TrackRecord(0, 0.0, st.TRACKED, True, (0.1, 0.1, 0.5, 0.5), 0.1, 0.9, 3.0, 0.9, 1.0)
    base = st.make_doc(v, [rec], size=(64, 48), sample_fps=10.0)
    assert "lower" not in base
    doc = st.make_doc(v, [rec], size=(64, 48), sample_fps=10.0, lower=[[0.0] * len(lb.ROW_FIELDS)])
    assert doc["lower"]["fields"] == list(lb.ROW_FIELDS) and len(doc["lower"]["rows"]) == 1
    p = st.save_doc(tmp_path / "d.json", doc)
    assert st.load_doc(p)["records"] == base["records"]  # kayıt şeması ve yükleyici değişmedi


class _FakePoseEstimator:
    """Her karede kare ortasında oturan bir kişi: omuz/kalça var, bacaklar masa arkasında."""

    def __init__(self, *a, **k):
        pass

    def estimate(self, frame):
        h, w = frame.shape[:2]
        row = make_row()
        k = np.array([[row[3 * j] * w, row[3 * j + 1] * h, row[3 * j + 2]] for j in range(17)], np.float32)
        return [SimpleNamespace(bbox=BBox(0.3 * w, 0.1 * h, 0.7 * w, 0.6 * h), score=0.9, kpts=k)]


def test_cli_sam_track_pose_writes_lower_rows_and_preview_fields(tmp_path, monkeypatch):
    import tracker.pose as pose_mod

    monkeypatch.setattr(pose_mod, "PoseEstimator", _FakePoseEstimator)
    v, _ = _cli(tmp_path, monkeypatch)
    code = main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--max-seconds", "0.5", "--preview", "--pose"])
    assert code == 0
    doc = json.loads((tmp_path / "klip.avi.sam.json").read_text(encoding="utf-8"))
    n = len(doc["records"])
    assert n > 1 and len(doc["lower"]["rows"]) == n and doc["lower"]["fields"] == list(lb.ROW_FIELDS)
    pv = json.loads(sp.preview_path(v).read_text(encoding="utf-8"))
    assert pv["state"] == "DONE" and "lower" in pv and pv["lower"]["anatomical"] is not None


def test_cli_sam_track_without_pose_has_no_lower_block(tmp_path, monkeypatch):
    v, _ = _cli(tmp_path, monkeypatch)
    assert main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--max-seconds", "0.3"]) == 0
    assert "lower" not in json.loads((tmp_path / "klip.avi.sam.json").read_text(encoding="utf-8"))
