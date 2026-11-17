"""S8: duruş (oturma/ayakta/geçiş), masa oklüzyonu, bacak durumu. Saf Python; model ve GPU gerekmez.

Geometri: 1000x1000 kare, omuz y=.10, kalça y=.30 -> gövde boyu L = .20 (200 px). Ayakta: diz kalçadan .85 L,
ayak bileği 1.7 L aşağıda. Önden oturan: uyluk kameraya baktığı için diz .25 L, ayak bileği 1.2 L aşağıda.
"""
import json
import random
from types import SimpleNamespace

import numpy as np
import pytest
from test_lowerbody import _pose, make_row
from test_sam_track import _avi, _cli

from tracker import lowerbody as lb
from tracker import posture as pm
from tracker import sam_preview as sp
from tracker import sam_track as st
from tracker.geometry import BBox
from tracker.main import main

W = H = 1000
SH, HIP, L = 0.10, 0.30, 0.20


def row_for(thigh, reach, *, dx=0.0, left=True, right=True):
    """thigh/reach: diz / ayak bileği kalçanın kaç L aşağısında. dx: tüm x'lere eklenir."""
    kw = {"sh_y": SH, "hip_y": HIP}
    ky, ay = HIP + thigh * L, HIP + reach * L
    r = make_row(**kw)
    # make_row x'leri sabit (sol .58, sağ .42): dx ile kaydır
    def setj(j, x, y):
        r[3 * j:3 * j + 3] = [x + dx, y, 0.9]
    if left:
        setj(13, 0.58, ky)
        setj(15, 0.58, ay)
    if right:
        setj(14, 0.42, ky)
        setj(16, 0.42, ay)
    for j in (5, 6, 11, 12):
        r[3 * j] += dx
    return r


SEATED = row_for(0.25, 1.2)
STAND = row_for(0.85, 1.7)
HIPS_ONLY = make_row(sh_y=SH, hip_y=HIP)


def mix(a, b, k):
    return row_for(a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)


def seq(model, rows, dt=0.1, t0=0.0, **kw):
    return [model.update(t0 + i * dt, r, (W, H), **kw) for i, r in enumerate(rows)]


def collapse(items):
    out = []
    for x in items:
        if not out or out[-1] != x:
            out.append(x)
    return out


# --- duruş ---

def test_seated_and_standing_rows_are_classified():
    o = seq(pm.PostureModel(), [SEATED] * 20)[-1]
    assert o.posture == pm.SEATED and o.score < pm.SIT_AT
    o = seq(pm.PostureModel(), [STAND] * 20)[-1]
    assert o.posture == pm.STANDING and o.score > pm.STAND_AT


def test_unknown_until_there_is_evidence():
    m = pm.PostureModel()
    o = m.update(0.0, None, (W, H))
    assert o.posture == pm.UNKNOWN and o.score is None and o.framing is None
    assert o.legs == {"left": pm.GONE, "right": pm.GONE}
    assert m.update(0.1, SEATED, (W, H)).posture == pm.SEATED


@pytest.mark.parametrize("base", [(0.25, 1.2), (0.85, 1.7)])
def test_noisy_keypoints_do_not_flicker(base):
    rng = random.Random(7)
    m = pm.PostureModel()
    rows = [row_for(base[0] + rng.gauss(0, 0.12), base[1] + rng.gauss(0, 0.15)) for _ in range(150)]
    states = {o.posture for o in seq(m, rows)}
    assert states == {pm.SEATED if base[0] < 0.5 else pm.STANDING}


def test_sit_down_goes_standing_transition_seated_once():
    rows = [STAND] * 15 + [mix((0.85, 1.7), (0.25, 1.2), k / 15) for k in range(1, 15)] + [SEATED] * 30
    outs = seq(pm.PostureModel(), rows)
    assert collapse(o.posture for o in outs) == [pm.STANDING, pm.TRANSITION, pm.SEATED]
    assert {o.direction for o in outs if o.posture == pm.TRANSITION} == {"sitting_down"}
    assert all(o.direction is None for o in outs if o.posture != pm.TRANSITION)


def test_stand_up_goes_seated_transition_standing_once():
    rows = [SEATED] * 15 + [mix((0.25, 1.2), (0.85, 1.7), k / 15) for k in range(1, 15)] + [STAND] * 30
    outs = seq(pm.PostureModel(), rows)
    assert collapse(o.posture for o in outs) == [pm.SEATED, pm.TRANSITION, pm.STANDING]
    assert {o.direction for o in outs if o.posture == pm.TRANSITION} == {"standing_up"}


def test_legs_hidden_behind_the_desk_read_as_seated_and_stay_seated():
    outs = seq(pm.PostureModel(), [HIPS_ONLY] * 40)
    assert {o.posture for o in outs} == {pm.SEATED}
    assert outs[-1].legs == {"left": pm.HIDDEN, "right": pm.HIDDEN}


def test_frame_cut_legs_are_not_evidence_and_the_posture_is_held():
    low = make_row(sh_y=0.70, hip_y=0.90)  # anatomik bölge kadraj altını aşar: kadraj kesiyor, masa değil
    o = pm.PostureModel().update(0.0, low, (W, H))
    assert o.posture == pm.UNKNOWN and o.score is None
    m = pm.PostureModel()
    seq(m, [STAND] * 15)
    outs = seq(m, [low] * 20, t0=1.5)
    assert {o.posture for o in outs} == {pm.STANDING}
    assert outs[-1].legs["left"] == pm.LEFT_FRAME


def test_one_hidden_leg_does_not_change_the_posture_or_the_other_leg():
    m = pm.PostureModel()
    seq(m, [STAND] * 10)
    outs = seq(m, [row_for(0.85, 1.7, right=False)] * 10, t0=1.0)
    assert {o.posture for o in outs} == {pm.STANDING}
    assert outs[-1].legs == {"left": pm.VISIBLE, "right": pm.HIDDEN}


def test_foot_wiggle_while_seated_keeps_posture_and_framing():
    rng = random.Random(3)
    m = pm.PostureModel()
    seq(m, [SEATED] * 15)
    base = m.update(1.5, SEATED, (W, H)).framing
    rows = [row_for(0.25 + rng.uniform(-0.1, 0.1), 1.2 + rng.uniform(-0.15, 0.15)) for _ in range(40)]
    outs = seq(m, rows, t0=1.6)
    assert {o.posture for o in outs} == {pm.SEATED}
    assert abs(outs[-1].framing[3] - base[3]) < 0.03


def test_lifted_foot_while_walking_keeps_posture_and_does_not_pump_the_framing():
    m = pm.PostureModel()
    seq(m, [STAND] * 15)
    base = m.update(1.5, STAND, (W, H)).framing
    lifted = row_for(0.85, 1.7)
    lifted[3 * 15 + 1] -= 0.09  # sol ayak yukarı
    outs = seq(m, [lifted] * 15, t0=1.6)
    assert {o.posture for o in outs} == {pm.STANDING}
    assert abs(outs[-1].framing[3] - base[3]) < 0.03


# --- bacak durumu ---

def test_leg_moved_then_visible_again():
    m = pm.PostureModel()
    seq(m, [SEATED] * 3)
    jump = row_for(0.25, 1.2)
    jump[3 * 15:3 * 15 + 2] = [0.70, HIP + 1.2 * L]  # sol ayak bileği 120 px yana
    a = m.update(0.3, jump, (W, H))
    b = m.update(0.4, jump, (W, H))
    assert a.legs == {"left": pm.MOVED, "right": pm.VISIBLE} and b.legs["left"] == pm.VISIBLE


def test_leg_hidden_when_joints_vanish_mid_frame_with_the_person_still_there():
    m = pm.PostureModel()
    seq(m, [SEATED] * 3)
    o = m.update(0.3, row_for(0.25, 1.2, right=False), (W, H))
    assert o.legs == {"left": pm.VISIBLE, "right": pm.HIDDEN}


def test_leg_left_frame_when_it_goes_out_through_the_edge():
    m = pm.PostureModel()
    rows = [row_for(0.85, 1.7, dx=0.30)] * 3
    outs = seq(m, rows)
    assert outs[-1].legs["left"] == pm.VISIBLE
    for i, x in enumerate((0.93, 0.97, 0.99)):  # sol ayak sağ kenara doğru gider
        r = row_for(0.85, 1.7, dx=0.30)
        r[3 * 15:3 * 15 + 2] = [x, HIP + 1.7 * L]
        o = m.update(0.3 + 0.1 * i, r, (W, H))
    gone = row_for(0.85, 1.7, dx=0.30, left=False)
    o = m.update(0.6, gone, (W, H))
    assert o.legs == {"left": pm.LEFT_FRAME, "right": pm.VISIBLE}


def test_no_person_is_unknown_not_hidden():
    m = pm.PostureModel()
    seq(m, [SEATED] * 3)
    o = m.update(0.3, None, (W, H))
    assert o.legs == {"left": pm.GONE, "right": pm.GONE}


def test_crossing_legs_keep_identity_and_are_not_reported_as_moved():
    m = pm.PostureModel()
    seq(m, [SEATED] * 10)
    cross = row_for(0.25, 1.2)
    cross[3 * 15:3 * 15 + 2], cross[3 * 16:3 * 16 + 2] = [0.42, HIP + 1.2 * L], [0.58, HIP + 1.2 * L]  # etiket takası
    o = m.update(1.0, cross, (W, H))
    assert o.lower.swapped and o.legs == {"left": pm.VISIBLE, "right": pm.VISIBLE}
    assert o.posture == pm.SEATED


# --- masa ---

def test_desk_like_uses_overlap_and_width_not_a_desk_height():
    ref = (0.4, 0.3, 0.6, 0.6)
    desk = (0.1, 0.3, 0.9, 0.5)
    assert pm.desk_like(desk, ref, 200.0, W, H)[0]
    assert not pm.desk_like((0.38, 0.35, 0.62, 0.58), ref, 200.0, W, H)[0]  # bacak maskesi: bölgeyle örtüşür
    assert pm.desk_like((0.0, 0.3, 1.0, 0.5), None, 200.0, W, H)[0]  # bölge yokken yalnız mutlak genişlik
    assert not pm.desk_like(desk, None, 600.0, W, H)[0]  # L büyükse (yakın kişi) aynı genişlik normal
    mid = (0.2, 0.3, 0.8, 0.6)  # örtüşme .33: oturanda masa, ayaktayken (adım açıklığı) kabul
    assert pm.desk_like(mid, ref, 200.0, W, H)[0]
    assert not pm.desk_like(mid, ref, 200.0, W, H, standing=True)[0]


def test_desk_mask_is_rejected_and_never_widens_the_region():
    with_mask, without = pm.PostureModel(), pm.PostureModel()
    seq(with_mask, [SEATED] * 10)
    seq(without, [SEATED] * 10)
    desk = (0.15, 0.28, 0.85, 0.42)
    a = with_mask.update(1.0, SEATED, (W, H), mask_box=desk, mask_conf=0.9)
    b = without.update(1.0, SEATED, (W, H))
    assert a.desk_mask and not b.desk_mask and a.lower.source == "pose" and a.notes
    assert a.framing == pytest.approx(b.framing) and a.anatomical == pytest.approx(b.anatomical)


def test_leg_mask_is_still_used_as_evidence():
    m = pm.PostureModel()
    seq(m, [SEATED] * 5)
    o = m.update(0.5, SEATED, (W, H), mask_box=(0.38, 0.35, 0.62, 0.58), mask_conf=0.9)
    assert not o.desk_mask and o.lower.source == "pose+mask"


def test_lost_track_mask_is_not_checked_as_desk():
    m = pm.PostureModel()
    seq(m, [SEATED] * 5)
    o = m.update(0.5, SEATED, (W, H), mask_box=(0.0, 0.3, 1.0, 0.5), mask_conf=0.9, tracked=False)
    assert not o.desk_mask


# --- oturma bölgesi ---

def test_seated_keeps_the_shin_region_while_the_legs_are_hidden_behind_the_desk():
    m, plain = pm.PostureModel(), lb.LowerBodyModel()
    seq(m, [SEATED] * 20)
    base = m.update(2.0, SEATED, (W, H)).framing
    outs = seq(m, [HIPS_ONLY] * 80, t0=2.1)  # 8 sn masa arkası
    for i in range(20):
        plain.update(i * 0.1, SEATED, (W, H))
    for i in range(80):
        s7 = plain.update(2.1 + i * 0.1, HIPS_ONLY, (W, H))
    assert s7.anatomical[3] == pytest.approx(HIP + lb.LEG_REACH * L)  # S7 tek başına: 1 L'ye çöker
    assert outs[-1].framing[3] >= base[3] - 0.01 and outs[-1].posture == pm.SEATED  # S8: baldır bölgesi tutulur


def test_seated_region_is_held_through_a_pose_dropout_and_then_expires():
    m = pm.PostureModel()
    seq(m, [SEATED] * 20)
    base = m.update(2.0, SEATED, (W, H)).framing
    o = m.update(7.0, None, (W, H))
    assert o.framing == pytest.approx(base, abs=0.02)
    assert m.update(2.0 + pm.SEATED_HOLD_S + 1.0, None, (W, H)).framing is None


def test_standing_region_is_held_only_briefly():
    m = pm.PostureModel()
    seq(m, [STAND] * 15)
    assert m.update(2.0, None, (W, H)).framing is not None
    assert m.update(4.0, None, (W, H)).framing is None


def test_thigh_region_follows_visible_knees_and_is_held_when_they_vanish():
    m = pm.PostureModel()
    o = seq(m, [HIPS_ONLY])[0]
    assert o.thigh[3] - o.thigh[1] == pytest.approx(pm.THIGH_SEATED * L)  # hiç diz görülmedi: varsayılan
    outs = seq(m, [SEATED] * 30, t0=0.1)
    th = outs[-1].thigh
    assert th[1] == pytest.approx(HIP) and th[3] - th[1] == pytest.approx(0.25 * L, abs=0.01)
    held = seq(m, [HIPS_ONLY] * 10, t0=3.2)[-1].thigh
    assert held[3] - held[1] == pytest.approx(th[3] - th[1], abs=1e-6)


def test_framing_moves_smoothly_between_seated_and_standing():
    rows = [SEATED] * 15 + [mix((0.25, 1.2), (0.85, 1.7), k / 12) for k in range(1, 13)] + [STAND] * 40
    outs = seq(pm.PostureModel(), rows)
    bottoms = [o.framing[3] for o in outs]
    total = bottoms[-1] - bottoms[0]
    assert total > 0.05 and outs[-1].framing[3] > outs[14].framing[3]
    assert max(abs(b - a) for a, b in zip(bottoms, bottoms[1:])) < 0.5 * total
    assert all(0.0 <= o.blend <= 1.0 for o in outs) and outs[-1].blend == pytest.approx(1.0)


def test_blend_rate_is_limited():
    m = pm.PostureModel()
    seq(m, [SEATED] * 10)
    blends = [o.blend for o in seq(m, [STAND] * 30, t0=1.0)]
    steps = [abs(b - a) for a, b in zip(blends, blends[1:])]
    assert max(steps) <= pm.BLEND_RATE * 0.1 + 1e-9 and blends[-1] == pytest.approx(1.0)


def test_s7_regions_are_unchanged_by_the_posture_layer():
    rows = [STAND] * 10 + [mix((0.85, 1.7), (0.25, 1.2), k / 10) for k in range(1, 11)] + [SEATED] * 10
    a = seq(pm.PostureModel(), rows)
    b = seq(lb.LowerBodyModel(), rows)
    for x, y in zip(a, b):
        assert x.anatomical == y.anatomical and x.visible == y.visible and x.lower.source == y.source


# --- biçim, önizleme, kayıt, CLI ---

def test_to_dict_is_json_and_row_matches_fields():
    m = pm.PostureModel()
    o = seq(m, [SEATED] * 3)[-1]
    d = json.loads(json.dumps(o.to_dict()))
    assert d["posture"] == pm.SEATED and set(d["leg_status"]) == {"left", "right"} and d["desk_mask"] is False
    assert set(d) >= {"visible", "anatomical", "framing", "legs", "thigh", "blend"}  # S7 + S8 alanları
    assert len(o.row()) == len(pm.ROW_FIELDS)
    assert len(pm.PostureModel().update(0.0, None, (W, H)).row()) == len(pm.ROW_FIELDS)


def _seated_pose():
    p = _pose(300, 100, 700, 500)
    p.kpts = np.array([[SEATED[3 * j] * W, SEATED[3 * j + 1] * H, SEATED[3 * j + 2]] for j in range(17)], np.float32)
    return p


def test_follower_with_posture_model_and_preview_payload():
    f = pm.follower()
    rec = SimpleNamespace(t=0.0, box=(0.4, 0.3, 0.6, 0.6), conf=0.9, tracked=True)
    out = f.step(rec, [_seated_pose()], (W, H))
    assert isinstance(out, pm.PostureFrame) and out.posture == pm.SEATED
    pay = sp.make_payload("TRACKED", conf=0.9, rect=(0.0, 0.0, 0.1, 0.1), lower=out)
    assert pay["rect"] == pytest.approx(sp.clamp_rect(out.framing))  # kadraj = duruşa duyarlı kadraj
    assert pay["lower"]["posture"] == pm.SEATED and pay["lower"]["anatomical"] is not None
    json.dumps(pay)


def test_reset_clears_posture_and_regions():
    m = pm.PostureModel()
    seq(m, [STAND] * 20)
    m.reset()
    o = m.update(0.0, None, (W, H))
    assert o.posture == pm.UNKNOWN and o.framing is None


def test_make_doc_writes_posture_block_only_when_given(tmp_path):
    v = _avi(tmp_path / "k.avi", 3)
    rec = st.TrackRecord(0, 0.0, st.TRACKED, True, (0.1, 0.1, 0.5, 0.5), 0.1, 0.9, 3.0, 0.9, 1.0)
    assert "posture" not in st.make_doc(v, [rec], size=(64, 48), sample_fps=10.0)
    doc = st.make_doc(v, [rec], size=(64, 48), sample_fps=10.0, posture=[[0.0] * len(pm.ROW_FIELDS)])
    assert doc["posture"]["fields"] == list(pm.ROW_FIELDS) and len(doc["posture"]["rows"]) == 1


class _FakePoseEstimator:
    def __init__(self, *a, **k):
        pass

    def estimate(self, frame):
        h, w = frame.shape[:2]
        k = np.array([[SEATED[3 * j] * w, SEATED[3 * j + 1] * h, SEATED[3 * j + 2]] for j in range(17)], np.float32)
        return [SimpleNamespace(bbox=BBox(0.3 * w, 0.1 * h, 0.7 * w, 0.6 * h), score=0.9, kpts=k)]


def test_cli_sam_track_posture_writes_posture_and_lower_rows_and_preview(tmp_path, monkeypatch):
    import tracker.pose as pose_mod

    monkeypatch.setattr(pose_mod, "PoseEstimator", _FakePoseEstimator)
    v, _ = _cli(tmp_path, monkeypatch)
    assert main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--max-seconds", "0.5", "--preview",
                 "--posture"]) == 0
    doc = json.loads((tmp_path / "klip.avi.sam.json").read_text(encoding="utf-8"))
    n = len(doc["records"])
    assert n > 1 and len(doc["posture"]["rows"]) == n and doc["posture"]["fields"] == list(pm.ROW_FIELDS)
    assert len(doc["lower"]["rows"]) == n and doc["lower"]["fields"] == list(lb.ROW_FIELDS)
    pv = json.loads(sp.preview_path(v).read_text(encoding="utf-8"))
    assert pv["state"] == "DONE" and pv["lower"]["posture"] == pm.SEATED


def test_cli_sam_track_pose_alone_has_no_posture_block(tmp_path, monkeypatch):
    import tracker.pose as pose_mod

    monkeypatch.setattr(pose_mod, "PoseEstimator", _FakePoseEstimator)
    v, _ = _cli(tmp_path, monkeypatch)
    assert main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--max-seconds", "0.3", "--pose"]) == 0
    doc = json.loads((tmp_path / "klip.avi.sam.json").read_text(encoding="utf-8"))
    assert "lower" in doc and "posture" not in doc
