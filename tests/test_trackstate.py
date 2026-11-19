"""S9: izleme durum makinesi (7 durum): yalnız geçiş testleri. Sahte kayıtlar; model/GPU gerekmez, Re-ID eşleştirmesi yok."""
import json
import random

import pytest
from test_sam_track import GOOD, _cli, make, run

from tracker import sam_preview as sp
from tracker import sam_track as st
from tracker import trackstate as ts
from tracker.main import main

BOX = (0.3, 0.2, 0.6, 0.7)
T, P, TL, OUT, CAND, RE, MAN = (ts.TRACKED, ts.PARTIALLY_OCCLUDED, ts.TEMPORARILY_LOST, ts.OUT_OF_FRAME,
                                ts.REACQUISITION_CANDIDATE, ts.REACQUIRED, ts.MANUAL_RESELECT_REQUIRED)


def rec(i, kind="T", box=BOX, dt=0.1):
    """kind: T temiz izlenen · p kısmen örtülü (oran 0.4) · c düşük güven (oran normal) · b büyük oran ·
    L kayıp (maske yok) · G kayıp (TrackGate reddetti)."""
    tracked = kind in "Tpcb"
    ratio = {"p": 0.4, "b": 2.0}.get(kind, 1.0)
    return st.TrackRecord(index=i, t=round(i * dt, 4), state=st.TRACKED if tracked else st.LOST,
                          accepted=kind != "G", box=box if tracked else None, area=0.1, iou=0.9,
                          object_score=3.0, conf=0.4 if kind == "c" else 0.9, ratio=ratio, clean=kind == "T",
                          size=(box[2] - box[0], box[3] - box[1]) if tracked else None)


def feed(m, pattern, boxes=None, start=0, **kw):
    out = []
    for k, ch in enumerate(pattern):
        out.append(m.update(rec(start + k, ch, **({"box": boxes[k]} if boxes else {})), **kw))
    return out


def names(frames):
    return [f.state for f in frames]


def runs(frames):
    """Art arda tekrarları sıkıştırır: [(durum, adet), ...]."""
    out = []
    for f in frames:
        if out and out[-1][0] == f.state:
            out[-1][1] += 1
        else:
            out.append([f.state, 1])
    return [tuple(x) for x in out]


# --- TRACKED / PARTIALLY_OCCLUDED ---

def test_first_frame_starts_tracked_and_clean_frames_never_change_state():
    fr = feed(ts.TrackStateMachine(), "TTTTT")
    assert names(fr) == [T] * 5 and fr[0].prev is None and fr[0].reason == "start" and fr[1].reason == "ok"
    assert not any(f.changed or f.hold or f.lost_s for f in fr) and fr[0].crop == BOX


def test_first_frame_without_a_mask_starts_temporarily_lost_with_no_crop():
    f = feed(ts.TrackStateMachine(), "L")[0]
    assert (f.state, f.reason, f.crop, f.hold) == (TL, "no_mask", None, True)


def test_low_mask_ratio_is_partial_at_once_and_needs_two_clean_frames_to_come_back():
    fr = feed(ts.TrackStateMachine(), "TTpppTTT")
    assert names(fr) == [T, T, P, P, P, P, T, T]
    assert [f.reason for f in fr[2:6]] == ["low_ratio"] * 3 + ["recovering"] and fr[6].reason == "ok"


def test_one_unclean_frame_with_a_normal_ratio_is_a_blip_two_make_it_partial():
    fr = feed(ts.TrackStateMachine(), "TTcTT")
    assert names(fr) == [T] * 5 and fr[2].reason == "blip"
    fr = feed(ts.TrackStateMachine(), "TTccTT")
    assert names(fr) == [T, T, T, P, P, T] and fr[3].reason == "low_conf" and fr[4].reason == "recovering"


def test_oversized_mask_is_partial_with_its_own_reason():
    fr = feed(ts.TrackStateMachine(), "Tbb")
    assert names(fr) == [T, T, P] and fr[2].reason == "big_ratio"


def test_partial_frame_does_not_move_the_last_reliable_crop():
    other = (0.1, 0.1, 0.3, 0.4)
    m = ts.TrackStateMachine()
    m.update(rec(0, "T"))
    f = m.update(rec(1, "p", other))
    assert f.state == P and f.crop == BOX and m.anchor.box == BOX and m.anchor.index == 0
    m.update(rec(2, "p", other))
    assert m.update(rec(3, "L")).crop == BOX  # kayıpta da son temiz kırpım


# --- kayıp ---

def test_short_loss_inside_the_hold_resumes_directly_without_a_candidate():
    fr = feed(ts.TrackStateMachine(hold_s=1.0), "TTLLLT")
    assert names(fr) == [T, T, TL, TL, TL, T] and fr[5].reason == "resumed"
    assert [f.lost_s for f in fr[2:5]] == pytest.approx([0.0, 0.1, 0.2]) and all(f.hold for f in fr[2:5])
    assert fr[5].lost_s == 0 and not fr[5].hold and [f.reason for f in fr[2:5]] == ["no_mask"] * 3


def test_a_resumed_frame_that_is_still_partly_covered_goes_straight_to_partial():
    fr = feed(ts.TrackStateMachine(hold_s=1.0), "TTLpp")
    assert names(fr) == [T, T, TL, P, P] and fr[3].reason == "low_ratio"


def test_long_loss_returns_through_candidate_then_reacquired_then_tracked():
    fr = feed(ts.TrackStateMachine(hold_s=1.0), "TT" + "L" * 15 + "T" * 7)
    assert runs(fr) == [(T, 2), (TL, 15), (CAND, 2), (RE, 3), (T, 2)]
    lost, cand, back = fr[2:17], fr[17:19], fr[19:22]
    assert lost[0].lost_s == 0 and lost[-1].lost_s == pytest.approx(1.4)
    assert [f.hold for f in lost[:11]] == [True] * 11 and not any(f.hold for f in lost[11:])  # 1.0 sn sonra kırpım bırakılır
    assert all(f.hold and f.lost_s == pytest.approx(1.5) and f.reason == "back" for f in cand)  # aday: eski kırpım, biten yokluk
    assert [f.reason for f in back] == ["confirmed", "settling", "settling"] and all(f.lost_s == pytest.approx(1.5) for f in back)
    assert not any(f.hold for f in back + fr[22:]) and all(f.crop == BOX for f in fr[2:])


def test_candidate_that_vanishes_again_returns_to_the_old_loss_and_keeps_its_clock():
    fr = feed(ts.TrackStateMachine(hold_s=1.0), "TT" + "L" * 15 + "T" + "L")
    assert fr[17].state == CAND and fr[18].state == TL and fr[18].lost_s == pytest.approx(1.6) and not fr[18].hold
    assert fr[18].changed and fr[18].prev == CAND


def test_loss_after_reacquired_starts_a_new_absence():
    m = ts.TrackStateMachine(hold_s=0.15)
    fr = feed(m, "TT" + "LLL" + "TTT" + "L")
    assert names(fr)[5:9] == [CAND, CAND, RE, TL] and fr[8].lost_s == 0.0  # yeni yokluk sıfırdan


def test_gate_rejection_is_a_loss_with_its_own_reason_and_a_desk_jump_never_counts_as_back():
    fr = feed(ts.TrackStateMachine(hold_s=0.15), "TTGGGG")
    assert names(fr) == [T, T, TL, TL, TL, TL] and {f.reason for f in fr[2:]} == {"gate"}
    fr = feed(ts.TrackStateMachine(hold_s=0.15), "TTLGGT")  # kayıp + reddedilen kare yokluğu sürdürür, ilk gerçek kare aday olur
    assert names(fr)[2:] == [TL, TL, TL, CAND] and fr[3].reason == "gate"


# --- kare dışı ---

def boxes_left(n=4):
    return [(0.3 - 0.1 * k if k < 3 else 0.0, 0.2, 0.5 - 0.1 * k if k < 3 else 0.2, 0.8) for k in range(n)]


def test_leaving_through_the_left_edge_is_out_of_frame_and_comes_back_as_a_candidate():
    m = ts.TrackStateMachine(hold_s=0.5)
    fr = feed(m, "TTTT", boxes_left())
    fr += feed(m, "LLL", start=4)
    assert names(fr)[4:] == [OUT] * 3 and fr[4].reason == "exit_left" and {f.edge for f in fr[4:]} == {"left"}
    assert [f.hold for f in fr[4:]] == [True, True, True]
    enter = (0.0, 0.2, 0.15, 0.8)
    fr2 = feed(m, "TTTTTT", [enter] * 6, start=7)
    assert runs(fr2) == [(CAND, 2), (RE, 3), (T, 1)] and fr2[0].edge == "left" and fr2[2].edge == "left"
    assert fr2[0].lost_s == pytest.approx(0.3) and fr2[0].hold  # kayıt: ilk lost 0.4, dönüş 0.7


def test_a_box_shrinking_at_the_right_edge_is_leaving_even_if_its_centre_barely_moves():
    boxes = [(0.60, 0.2, 1.0, 0.8), (0.65, 0.2, 1.0, 0.8), (0.75, 0.2, 1.0, 0.8), (0.85, 0.2, 1.0, 0.8)]
    fr = feed(ts.TrackStateMachine(), "TTTTL", boxes + [None])
    assert fr[4].state == OUT and fr[4].edge == "right" and fr[4].reason == "exit_right"


def test_leaving_through_the_top_and_bottom_edges():
    up = [(0.3, 0.30 - 0.15 * k, 0.6, 0.60 - 0.15 * k) for k in range(3)]
    assert feed(ts.TrackStateMachine(), "TTTL", up + [None])[3].edge == "top"
    down = [(0.3, 0.20 + 0.15 * k, 0.6, 0.70 + 0.15 * k) for k in range(3)]
    assert feed(ts.TrackStateMachine(), "TTTL", down + [None])[3].edge == "bottom"


def test_a_box_that_merely_rests_on_the_bottom_edge_is_a_temporary_loss_not_an_exit():
    seated = (0.3, 0.4, 0.7, 1.0)  # oturan kişi: kadraj bacağı kesiyor
    fr = feed(ts.TrackStateMachine(), "TTTTTTL", [seated] * 6 + [None])
    assert fr[6].state == TL and fr[6].edge is None and fr[6].reason == "no_mask"


def test_legs_left_hint_turns_a_loss_at_an_edge_into_an_exit_but_not_away_from_it():
    seated = (0.3, 0.4, 0.7, 1.0)
    m = ts.TrackStateMachine()
    feed(m, "TTT", [seated] * 3)
    f = m.update(rec(3, "L"), legs_left=True)
    assert f.state == OUT and f.edge == "bottom"
    m = ts.TrackStateMachine()
    feed(m, "TTT")  # ortada
    assert m.update(rec(3, "L"), legs_left=True).state == TL


def test_out_of_frame_never_resumes_directly_even_after_a_short_absence():
    m = ts.TrackStateMachine(hold_s=5.0)
    fr = feed(m, "TTTT", boxes_left()) + feed(m, "LT", start=4)
    assert names(fr)[4:] == [OUT, CAND]


# --- elle seçim ---

def test_temporary_loss_times_out_into_manual_reselect_and_a_later_mask_becomes_a_candidate():
    m = ts.TrackStateMachine(hold_s=1.0, manual_s=2.0)
    fr = feed(m, "TT" + "L" * 30)
    first = next(f for f in fr if f.state == MAN)
    assert first.index == 22 and first.reason == "timeout" and first.lost_s == pytest.approx(2.0) and not first.hold
    assert all(f.state == TL for f in fr[2:22]) and all(f.state == MAN for f in fr[22:])
    fr2 = feed(m, "TTTT", start=32)
    assert names(fr2) == [CAND, CAND, RE, RE] and fr2[0].prev == MAN and fr2[0].lost_s == pytest.approx(3.0)


def test_candidate_that_fails_after_the_deadline_goes_to_manual_not_back_to_temporary_loss():
    m = ts.TrackStateMachine(hold_s=0.5, manual_s=2.0)
    fr = feed(m, "TT" + "L" * 19 + "T" + "L")  # kayıp 0.2'de başladı, aday 2.1'de, tekrar kayıp 2.2'de (>= 2 sn)
    assert fr[21].state == CAND and fr[22].state == MAN and fr[22].reason == "timeout"


def test_out_of_frame_waits_much_longer_before_asking_for_a_reselect():
    m = ts.TrackStateMachine(hold_s=1.0, manual_s=2.0, out_max_s=5.0)
    fr = feed(m, "TTTT", boxes_left()) + feed(m, "L" * 60, start=4)
    assert fr[4].state == OUT and fr[4 + 49].state == OUT  # 4.9 sn
    first = next(f for f in fr if f.state == MAN)
    assert first.lost_s == pytest.approx(5.0) and first.reason == "timeout"


def test_reset_after_the_user_picks_again_forgets_the_loss_and_the_old_crop():
    m = ts.TrackStateMachine(hold_s=1.0, manual_s=2.0)
    fr = feed(m, "TT" + "L" * 30)
    assert fr[-1].state == MAN
    m.reset(3.2)
    assert m.state == T and m.anchor is None and m.transitions[-1][1:] == (MAN, T, "reset")
    new = (0.5, 0.5, 0.9, 0.9)
    f = m.update(rec(32, "T", new))
    assert (f.state, f.prev, f.lost_s, f.crop) == (T, T, 0.0, new)


# --- tutarlılık ---

def test_every_transition_is_in_the_table_and_invariants_hold_on_random_sequences():
    edge_boxes = [BOX, (0.0, 0.2, 0.3, 0.8), (0.7, 0.2, 1.0, 0.8), (0.3, 0.0, 0.6, 0.4), (0.3, 0.6, 0.6, 1.0)]
    for seed in range(40):
        rng = random.Random(seed)
        m = ts.TrackStateMachine(hold_s=rng.choice([0.0, 0.5, 1.0]), manual_s=rng.choice([1.0, 3.0]),
                                 out_max_s=rng.choice([2.0, 6.0]))
        prev = None
        for i in range(400):
            kind = rng.choices("TpcbLG", weights=[10, 3, 2, 1, 6, 2])[0]
            f = m.update(rec(i, kind, rng.choice(edge_boxes)), legs_left=rng.random() < 0.05)
            assert f.state in ts.STATES and f.prev == prev and f.lost_s >= 0
            if prev is not None and prev != f.state:
                assert f.state in ts.ALLOWED[prev], (seed, i, prev, f.state)
            if f.hold:
                assert f.state in (TL, OUT, CAND)
            assert (f.edge is not None) <= (f.state in (OUT, CAND, RE))
            assert f.lost == (f.state in ts.LOST_STATES) and (f.crop is None) == (m.anchor is None)
            if kind in "LG":
                assert f.state in ts.LOST_STATES  # kayıp kare asla izlenen durumda görünmez
            else:
                assert f.state not in ts.LOST_STATES  # izlenen kare asla kayıp durumunda görünmez
            prev = f.state


def test_summary_counts_frames_per_state_and_transitions():
    m = ts.TrackStateMachine(hold_s=1.0)
    feed(m, "TTLLLTTpp")
    assert m.counts[T] == 4 + 0 and m.counts[TL] == 3 and m.counts[P] == 2
    s = m.summary()
    assert "TRACKED 4" in s and "TEMPORARILY_LOST 3" in s and "PARTIALLY_OCCLUDED 2" in s and "geçiş 3" in s
    assert ts.TrackStateMachine().summary().startswith("durum: kare yok")


# --- kayıt / önizleme / CLI ---

def test_row_and_dict_carry_state_reason_loss_edge_hold_and_crop():
    m = ts.TrackStateMachine(hold_s=1.0)
    fr = feed(m, "TL")
    row = fr[1].row()
    assert len(row) == len(ts.ROW_FIELDS) and row[:6] == [0.1, TL, "no_mask", 0.0, None, 1] and row[6:] == list(BOX)
    d = fr[1].to_dict()
    assert d["state"] == TL and d["prev"] == T and d["crop"] == list(BOX) and d["hold"] is True
    assert feed(ts.TrackStateMachine(), "L")[0].row()[6:] == [None] * 4


def test_make_doc_writes_an_optional_state_block_aligned_with_the_records(tmp_path):
    eng, _ = make([GOOD, (None, 0.9, 3.0), GOOD])
    recs = run(eng, 4)
    m = ts.TrackStateMachine()
    rows = [m.update(r).row() for r in recs]
    video = tmp_path / "klip.mp4"
    video.write_bytes(b"v")
    doc = st.make_doc(video, recs, size=(64, 48), sample_fps=10.0, states=rows)
    assert doc["state"]["fields"] == list(ts.ROW_FIELDS) and doc["state"]["rows"] == rows and len(rows) == len(doc["records"])
    assert doc["state"]["counts"] == {T: 3, TL: 1} and doc["version"] == 2  # şema sürümü değişmedi
    assert "state" not in st.make_doc(video, recs, size=(64, 48), sample_fps=10.0)
    json.dumps(doc)


def test_preview_payload_takes_the_machine_state_and_the_reason_as_note():
    m = ts.TrackStateMachine(hold_s=1.0)
    ok = m.update(rec(0, "T"))
    lost = m.update(rec(1, "L"))
    base = st.TrackRecord(index=1, t=0.1, state="lost", accepted=True, box=None, area=0, iou=0, object_score=0, conf=0.0, ratio=0)
    p = sp.from_record(base, track=lost)
    assert p["state"] == TL and p["note"] == "no_mask" and p["track"]["lost_s"] == 0.0 and p["track"]["hold"] is True
    assert sp.from_record(base, track=ok)["note"] == "" and sp.from_record(base)["state"] == "lost" and "track" not in sp.from_record(base)


def test_writer_writes_at_once_when_only_the_machine_state_changes(tmp_path):
    now = [0.0]
    w = sp.Writer(tmp_path / "p.json", every=10.0, clock=lambda: now[0])
    m = ts.TrackStateMachine(hold_s=1.0)
    a, b, c = m.update(rec(0, "T")), m.update(rec(1, "p")), m.update(rec(2, "p"))
    assert w.update(rec(0, "T"), track=a) and not w.update(rec(1, "T"), track=a)  # aynı durum, erken
    assert w.update(rec(1, "p"), track=b) is True  # kaydın durumu hep "tracked"; makine durumu değişti
    assert w.update(rec(2, "p"), track=c) is False
    w.finish(rec(3, "p"), track=c)
    d = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
    assert d["state"] == "DONE" and d["track"]["state"] == P


def test_track_video_records_drive_the_machine_through_a_real_loss_and_return():
    eng, _ = make([GOOD, GOOD] + [(None, 0.9, 3.0)] * 3 + [GOOD] * 6)
    m = ts.TrackStateMachine(hold_s=0.15)  # 3 kayıp kare = 0.3 sn > 0.15: aday + doğrulama
    fr = [m.update(r) for r in run(eng, 12)]
    assert runs(fr) == [(T, 3), (TL, 3), (CAND, 2), (RE, 3), (T, 1)]  # kare 0 istemli kare + betikte 2 iyi kare


def test_cli_sam_track_prints_the_state_summary_and_writes_the_state_block_and_preview(tmp_path, monkeypatch, capsys):
    v, _ = _cli(tmp_path, monkeypatch, script=[GOOD] * 3 + [(None, 0.9, 3.0)] * 12 + [GOOD] * 20)
    code = main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--device", "cpu", "--preview"])
    out = capsys.readouterr().out
    assert code == 0 and "durum: TRACKED" in out and "TEMPORARILY_LOST 12" in out and "REACQUIRED" in out
    doc = st.load_doc(st.sam_path(v))
    assert doc["state"]["fields"] == list(ts.ROW_FIELDS) and len(doc["state"]["rows"]) == len(doc["records"]) == 30
    assert doc["state"]["counts"][TL] == 12 and doc["state"]["counts"][CAND] == 2
    pre = json.loads(sp.preview_path(v).read_text(encoding="utf-8"))
    assert pre["state"] == "DONE" and pre["track"]["state"] in ts.STATES


def test_cli_hold_comes_from_the_config(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"lost_hold_s": 5.0}), encoding="utf-8")
    v, _ = _cli(tmp_path, monkeypatch, script=[GOOD] * 3 + [(None, 0.9, 3.0)] * 12 + [GOOD] * 20)
    main(["--config", str(cfg), "sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--device", "cpu"])
    out = capsys.readouterr().out
    assert "TEMPORARILY_LOST 12" in out and "REACQUIRED" not in out and "REACQUISITION_CANDIDATE" not in out  # 1.2 sn < 5 sn: doğrudan sürdü
