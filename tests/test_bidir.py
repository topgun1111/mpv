"""S12: çift yönlü iyileştirme (tracker/bidir.py). Model, GPU ve gerçek video gerekmez.

Sentetik ileri kayıt + sentetik geri iz uyuşmazlıkları: 10 kare/sn, özne sabit kutuda. Gerçek `track_video` yalnız
uçtan uca testte (sahte grafikler, test_sam_track ile aynı) kullanılır; diğerlerinde geri iz doğrudan `BackFrame` olarak verilir.
"""
import json
from pathlib import Path

import numpy as np
import pytest
from test_sam_track import GOOD, make

from tracker import bidir as bd
from tracker import camera
from tracker import sam_track as st
from tracker import trackstate as ts
from tracker.bidir import BackFrame, Interval
from tracker.main import main

BOX = (0.30, 0.45, 0.60, 0.95)
FAR = (0.70, 0.05, 0.95, 0.30)  # BOX ile hiç örtüşmeyen kutu
OFF = (0.40, 0.50, 0.70, 1.00)  # BOX ile IoU ~0.43 (< 0.5), merkezi o kadar uzak değil: sıçrama sayılmaz
FPS = 10.0


def rec(i, *, tracked=True, accepted=True, clean=True, conf=0.9, box=BOX, ratio=1.0):
    ok = tracked and accepted  # kapı reddi gerçek döngüde de LOST + accepted=False
    return st.TrackRecord(index=i, t=i / FPS, state=st.TRACKED if ok else st.LOST, accepted=accepted,
                          box=box, area=0.15, iou=0.9, object_score=3.0, conf=conf, ratio=ratio, clean=clean and ok,
                          size=(box[2] - box[0], box[3] - box[1]) if ok and box else None)


def seq(n, bad=None):
    """n kare; `bad`: {kare: rec() argümanları} ya da {kare: None} (kayıp, kutu yok)."""
    out = []
    for i in range(n):
        o = (bad or {}).get(i, {})
        out.append(rec(i, tracked=False, box=None, clean=False) if o is None else rec(i, **o))
    return out


def lost(*idx):
    return {i: None for i in idx}


def make_doc(recs, *, posture=None, video="klip.avi", states=True):
    m = ts.TrackStateMachine()
    rows = [m.update(r).row() for r in recs] if states else None
    doc = st.make_doc(video, recs, size=(1280, 720), sample_fps=FPS, states=rows)
    if posture is not None:
        doc["posture"] = {"fields": ["desk"], "rows": [[int(i in posture)] for i in range(len(recs))]}
    return doc


def bf(box=BOX, conf=0.9, clean=True, tracked=True, accepted=True):
    return BackFrame(tracked, accepted, clean, conf, box if tracked else None, iou=0.9, object_score=3.0, area=0.15, ratio=1.0)


def run(doc, back, max_window=150):
    """`back`: {kare: BackFrame}; yalnız pencereye (lo <= kare < q) girenler verilir. Dönüş: (yeni belge, rapor, çağrılar)."""
    calls = []

    def fn(iv, lo):
        calls.append((iv, lo))
        return {i: b for i, b in back.items() if lo <= i < iv.q}

    new, rep = bd.refine(doc, fn, max_window=max_window)
    return new, rep, calls


def full(lo, hi, **kw):
    return {i: bf(**kw) for i in range(lo, hi + 1)}


def verdicts(rep):
    return {v.index: (v.verdict, v.why) for r in rep.results for v in r.verdicts}


def state_of(doc, i):
    s = doc["state"]
    row = s["rows"][i]
    c = {n: s["fields"].index(n) for n in ("state", "reason", "hold")}
    return row[c["state"]], row[c["reason"]], row[c["hold"]]


def set_state(doc, idx, state, reason):
    s = doc["state"]
    for i in idx:
        s["rows"][i][s["fields"].index("state")] = state
        s["rows"][i][s["fields"].index("reason")] = reason


# --- aralıkların bulunması ---

def test_all_reliable_clip_has_no_interval_and_backward_is_never_called():
    doc = make_doc(seq(30))
    new, rep, calls = run(doc, {})
    assert rep.results == [] and calls == []
    assert new["records"] == doc["records"] and new["refine"]["counts"]["suspect"] == 0
    assert "belirsiz aralık yok" in rep.summary()


def test_lost_run_becomes_one_interval_with_reliable_anchors_on_both_sides():
    rows = bd.forward_rows(make_doc(seq(40, lost(*range(15, 23)))))
    ivs = bd.plan(rows)
    assert [(v.a, v.b, v.p, v.q) for v in ivs] == [(15, 22, 14, 23)]


def test_each_kind_of_unreliable_frame_is_suspect():
    bad = {5: dict(clean=False, conf=0.5, ratio=0.5), 10: dict(accepted=False), 15: dict(conf=0.5), 20: None}
    iv = bd.plan(bd.forward_rows(make_doc(seq(30, bad))))
    assert [(v.a, v.b) for v in iv] == [(5, 6), (10, 10), (15, 15), (20, 20)]  # 6: S9 "recovering" (yarı örtülü durumda)


def test_short_interior_reliable_run_does_not_count_as_anchor_and_merges_intervals():
    ivs = bd.plan(bd.forward_rows(make_doc(seq(30, lost(10, 11, 12, 15, 16, 17)))))
    assert [(v.a, v.b, v.p, v.q) for v in ivs] == [(10, 17, 9, 18)]  # 13-14: iki güvenilir kare < 3


def test_run_of_exactly_three_reliable_frames_is_an_anchor():
    ivs = bd.plan(bd.forward_rows(make_doc(seq(30, lost(10, 11, 12, 16, 17, 18)))))
    assert [(v.a, v.b) for v in ivs] == [(10, 12), (16, 18)]


def test_clip_edge_runs_stay_anchors_even_when_short():
    ivs = bd.plan(bd.forward_rows(make_doc(seq(12, lost(2, 3, 4, 5, 6, 7, 8, 9)))))  # 0-1 ve 10-11 klip kenarı
    assert [(v.a, v.b, v.p, v.q) for v in ivs] == [(2, 9, 1, 10)]


def test_interval_running_to_the_clip_end_has_no_anchor():
    ivs = bd.plan(bd.forward_rows(make_doc(seq(30, lost(*range(20, 30))))))
    assert [(v.a, v.b, v.p, v.q) for v in ivs] == [(20, 29, 19, None)]


def test_desk_flagged_frames_are_suspect_even_if_tracked_and_clean():
    doc = make_doc(seq(30), posture={20, 21})
    assert [(v.a, v.b) for v in bd.plan(bd.forward_rows(doc))] == [(20, 21)]


def test_single_frame_mask_spike_is_suspect_but_a_real_move_is_not():
    far = {25: dict(box=(0.55, 0.05, 0.85, 0.55))}
    assert [(v.a, v.b) for v in bd.plan(bd.forward_rows(make_doc(seq(40, far))))] == [(25, 25)]
    walk = {i: dict(box=(0.30 + 0.01 * (i - 20), 0.45, 0.60 + 0.01 * (i - 20), 0.95)) for i in range(20, 40)}
    assert bd.plan(bd.forward_rows(make_doc(seq(40, walk)))) == []  # yavaş yürüyüş sıçrama değil


def test_state_machine_state_matters_when_the_state_block_exists():
    doc = make_doc(seq(30))
    set_state(doc, [12], ts.REACQUISITION_CANDIDATE, "verifying")
    assert [(v.a, v.b) for v in bd.plan(bd.forward_rows(doc))] == [(12, 12)]
    assert bd.plan(bd.forward_rows(make_doc(seq(30), states=False))) == []


# --- closed: iki yön uyuşur ---

def test_closed_interval_repairs_every_lost_frame_from_the_backward_track():
    doc = make_doc(seq(40, lost(*range(15, 23))))
    drift = {i: bf(box=(0.30 + 0.001 * (22 - i), 0.45, 0.60 + 0.001 * (22 - i), 0.95)) for i in range(14, 23)}
    new, rep, calls = run(doc, drift)
    assert calls[0][1] == 14  # pencere p'yi kapsar
    assert rep.results[0].closure == bd.CLOSED and rep.count(bd.REPAIRED) == 8
    row = dict(zip(new["fields"], new["records"][18], strict=True))
    assert row["tracked"] == 1 and row["accepted"] == 1 and row["clean"] == 0
    assert (row["x1"], row["y1"]) == (round(0.30 + 0.004, 4), 0.45) and row["w"] == round(BOX[2] - BOX[0], 4)
    assert state_of(new, 18) == (ts.PARTIALLY_OCCLUDED, "refined", 0)
    assert new["counts"]["lost"] == 0 and new["counts"]["tracked"] == 40


def test_high_confidence_frames_are_untouched_byte_for_byte():
    doc = make_doc(seq(40, lost(*range(15, 23))))
    new, _, _ = run(doc, full(14, 22))
    keep = [i for i in range(40) if i not in range(15, 23)]
    assert [new["records"][i] for i in keep] == [doc["records"][i] for i in keep]
    assert [new["state"]["rows"][i] for i in keep] == [doc["state"]["rows"][i] for i in keep]


def test_original_document_is_never_modified():
    doc = make_doc(seq(40, lost(*range(15, 23))))
    before = json.dumps(doc, sort_keys=True)
    run(doc, full(14, 22))
    assert json.dumps(doc, sort_keys=True) == before and "refine" not in doc


def test_forward_tracked_frame_that_backward_confirms_keeps_its_forward_box():
    bad = {i: dict(clean=False, conf=0.5, ratio=0.5, box=(0.31, 0.46, 0.59, 0.94)) for i in range(15, 20)}
    doc = make_doc(seq(40, bad))
    new, rep, _ = run(doc, full(14, 20))  # 20: S9 "recovering" kare, durum hâlâ yarı örtülü
    assert {v for v in verdicts(rep).values()} == {(bd.CONFIRMED, "agree")} and len(verdicts(rep)) == 6
    assert new["records"][15:21] == doc["records"][15:21]  # kutu ve bayraklar değişmedi
    assert all(state_of(new, i)[0] == ts.PARTIALLY_OCCLUDED for i in range(15, 21))  # zaten yarı örtülüydü


def test_confirmed_candidate_frame_releases_the_camera_hold_but_never_becomes_reacquired():
    doc = make_doc(seq(40))
    set_state(doc, [20, 21], ts.REACQUISITION_CANDIDATE, "verifying")
    doc["state"]["rows"][20][doc["state"]["fields"].index("hold")] = 1
    new, rep, _ = run(doc, full(19, 21))
    assert {k: v[0] for k, v in verdicts(rep).items()} == {20: bd.CONFIRMED, 21: bd.CONFIRMED}
    assert state_of(new, 20) == (ts.PARTIALLY_OCCLUDED, "refined", 0)


def test_confirmed_tracked_state_is_not_downgraded():
    doc = make_doc(seq(40, {20: dict(clean=False, conf=0.5)}))
    assert state_of(doc, 20)[0] == ts.TRACKED  # tek yarı örtülü kare S9'da TRACKED kalır
    new, rep, _ = run(doc, full(19, 20))
    assert verdicts(rep)[20] == (bd.CONFIRMED, "agree") and state_of(new, 20)[0] == ts.TRACKED


def test_forward_and_backward_disagree_without_clear_evidence_stays_flagged_and_unchanged():
    bad = {i: dict(clean=False, conf=0.5, ratio=0.5) for i in (16, 17)}
    doc = make_doc(seq(40, bad))
    back = full(15, 18)  # 18: "recovering"
    back[16] = bf(box=FAR, conf=0.5)  # ileri güvenle eşit, kutu uyuşmuyor
    new, rep, _ = run(doc, back)
    assert verdicts(rep)[16] == (bd.UNRESOLVED, "disagree") and verdicts(rep)[17][0] == bd.CONFIRMED
    assert new["records"][16] == doc["records"][16]


def test_closed_interval_prefers_backward_only_when_its_confidence_is_clearly_higher():
    bad = {16: dict(clean=False, conf=0.4, ratio=0.5, box=OFF)}
    doc = make_doc(seq(40, bad))
    new, rep, _ = run(doc, {**full(15, 17), 16: bf(box=BOX, conf=0.9)})
    assert rep.results[0].closure == bd.CLOSED and verdicts(rep)[16] == (bd.REPAIRED, "closed_better")
    assert new["records"][16][new["fields"].index("x1")] == BOX[0]
    new2, rep2, _ = run(doc, {**full(15, 17), 16: bf(box=BOX, conf=0.45)})  # fark 0.05 < 0.15
    assert verdicts(rep2)[16] == (bd.UNRESOLVED, "disagree") and new2["records"][16] == doc["records"][16]


def test_open_interval_never_overrides_a_forward_tracked_frame_even_with_higher_backward_confidence():
    bad = {16: dict(clean=False, conf=0.4, ratio=0.5, box=OFF)}
    doc = make_doc(seq(40, bad))
    new, rep, _ = run(doc, {16: bf(box=BOX, conf=0.95), 17: bf()})  # iz 15'e ulaşmıyor: open
    assert rep.results[0].closure == bd.OPEN and verdicts(rep)[16] == (bd.UNRESOLVED, "disagree")
    assert new["records"][16] == doc["records"][16]


def test_rejected_gate_frames_are_repaired_like_lost_ones():
    doc = make_doc(seq(40, {i: dict(accepted=False, box=FAR) for i in (20, 21)}))
    new, rep, _ = run(doc, full(19, 21))
    assert {verdicts(rep)[i] for i in (20, 21)} == {(bd.REPAIRED, "closed")}
    assert new["gate"]["rejected"] == 0 and new["records"][20][new["fields"].index("x1")] == BOX[0]


def test_desk_flagged_and_spike_frames_are_repaired_from_the_backward_track():
    doc = make_doc(seq(40, {30: dict(box=(0.55, 0.05, 0.85, 0.55))}), posture={20, 21})
    new, rep, _ = run(doc, {**full(19, 21), **full(29, 31)})
    assert {verdicts(rep)[i] for i in (20, 21, 30)} == {(bd.REPAIRED, "closed")}
    assert new["records"][30][new["fields"].index("x1")] == BOX[0]


# --- open: yalnız temiz ve kesintisiz ---

def test_open_interval_repairs_only_clean_frames_contiguous_from_the_anchor():
    doc = make_doc(seq(40, lost(*range(15, 23))))
    back = {**full(19, 22), 18: bf(tracked=False), 21: bf(clean=False), **full(15, 17)}
    new, rep, _ = run(doc, back)
    v = verdicts(rep)
    assert rep.results[0].closure == bd.OPEN
    assert v[22] == (bd.REPAIRED, "back_clean") and v[20] == (bd.REPAIRED, "back_clean") and v[19][0] == bd.REPAIRED
    assert v[21] == (bd.UNRESOLVED, "back_unclean")
    assert all(v[i] == (bd.UNRESOLVED, "no_backward") for i in range(15, 19))  # 18'de iz koptu: ötesi sayılmaz
    assert new["records"][16] == doc["records"][16]


def test_mismatch_at_the_reliable_anchor_means_backward_drifted_and_nothing_is_repaired():
    doc = make_doc(seq(40, lost(*range(15, 23))))
    new, rep, _ = run(doc, {**full(15, 22), 14: bf(box=FAR)})
    assert rep.results[0].closure == bd.MISMATCH
    assert {v[1] for v in verdicts(rep).values()} == {"closure_mismatch"}
    assert new["records"] == doc["records"]


def test_window_cap_limits_the_backward_pass_and_blocks_closing():
    doc = make_doc(seq(80, lost(*range(10, 50))))  # 10-49 kayıp, 50-51 aday, q = 52
    new, rep, calls = run(doc, full(0, 51), max_window=10)
    assert calls[0][1] == 52 - 10 + 1 and rep.results[0].closure == bd.OPEN
    v = verdicts(rep)
    assert all(v[i] == (bd.REPAIRED, "back_clean") for i in range(43, 50))
    assert all(v[i] == (bd.CONFIRMED, "agree") for i in (50, 51))
    assert all(v[i] == (bd.UNRESOLVED, "window_cap") for i in range(10, 43))
    assert new["records"][10] == doc["records"][10]


def test_interval_without_a_later_anchor_is_never_repaired_and_backward_is_not_called():
    doc = make_doc(seq(30, lost(*range(20, 30))))
    new, rep, calls = run(doc, full(0, 29))
    assert calls == [] and {v[1] for v in verdicts(rep).values()} == {"no_anchor"}
    assert new["records"] == doc["records"]


def test_failed_window_leaves_the_interval_unresolved_with_the_reason():
    doc = make_doc(seq(40, lost(*range(15, 23))))

    def fn(iv, lo):
        raise bd.WindowError("decode_failed")

    new, rep = bd.refine(doc, fn)
    assert {v[1] for v in verdicts(rep).values()} == {"decode_failed"} and new["records"] == doc["records"]


# --- kimlik ve kare dışı ---

def test_identity_frames_are_never_touched_even_when_both_directions_agree():
    doc = make_doc(seq(40, lost(*range(15, 23))))
    set_state(doc, range(15, 19), ts.TEMPORARILY_LOST, "other_person")
    set_state(doc, [19], ts.MANUAL_RESELECT_REQUIRED, "ambiguous_reentry")
    new, rep, _ = run(doc, full(14, 22))
    v = verdicts(rep)
    assert all(v[i] == (bd.UNRESOLVED, "identity") for i in range(15, 20))
    assert all(v[i][0] == bd.REPAIRED for i in range(20, 23))
    assert new["records"][16] == doc["records"][16] and state_of(new, 16)[1] == "other_person"


def test_backward_track_through_an_identity_frame_is_no_evidence_for_older_frames():
    doc = make_doc(seq(50, lost(*range(10, 30))))
    set_state(doc, range(18, 22), ts.TEMPORARILY_LOST, "other_person")
    new, rep, _ = run(doc, full(9, 31))  # 30-31: aday kareler
    v = verdicts(rep)
    assert rep.results[0].closure == bd.OPEN  # zincir kimlik karesinde kesilir: p'ye ulaşılamaz
    assert all(v[i] == (bd.UNRESOLVED, "identity_cut") for i in range(10, 18))
    assert all(v[i] == (bd.UNRESOLVED, "identity") for i in range(18, 22))
    assert all(v[i] == (bd.REPAIRED, "back_clean") for i in range(22, 30))
    assert all(v[i][0] == bd.CONFIRMED for i in (30, 31))
    assert new["records"][12] == doc["records"][12]


def test_out_of_frame_frames_are_repaired_only_when_the_interval_is_closed():
    doc = make_doc(seq(40, lost(*range(15, 23))))
    set_state(doc, range(15, 23), ts.OUT_OF_FRAME, "exit_left")
    _, rep, _ = run(doc, full(18, 22))  # p'ye ulaşmıyor -> open
    assert {v[1] for k, v in verdicts(rep).items() if k >= 18} == {"absent_open"}
    _, rep2, _ = run(doc, full(14, 22))
    assert rep2.results[0].closure == bd.CLOSED and rep2.count(bd.REPAIRED) == 8


def test_long_loss_timeout_frames_need_a_closed_interval_too():
    doc = make_doc(seq(200, lost(*range(20, 120))))  # 10 sn: 100'den sonra MANUAL_RESELECT_REQUIRED ("timeout")
    assert state_of(doc, 110)[0] == ts.MANUAL_RESELECT_REQUIRED
    _, rep, _ = run(doc, full(100, 121))  # p'ye ulaşmıyor
    v = verdicts(rep)
    assert all(v[i] == (bd.UNRESOLVED, "absent_open") for i in range(100, 120))
    _, rep2, _ = run(doc, full(19, 121))
    assert rep2.results[0].closure == bd.CLOSED and rep2.count(bd.REPAIRED) == 100 and rep2.count(bd.UNRESOLVED) == 0


def test_tracked_frame_in_a_lost_state_means_the_machine_refused_it_and_counts_as_identity():
    doc = make_doc(seq(40))
    set_state(doc, [16], ts.TEMPORARILY_LOST, "timeout")  # SAM izlemiş ama makine hedef saymamış (zaman aşımı nedeni ezmiş)
    new, rep, _ = run(doc, full(15, 17))
    assert verdicts(rep)[16] == (bd.UNRESOLVED, "identity") and new["records"][16] == doc["records"][16]


def test_backward_pass_failure_still_reports_identity_frames_as_identity():
    doc = make_doc(seq(40, lost(*range(15, 23))))
    set_state(doc, [15], ts.TEMPORARILY_LOST, "other_person")

    def fn(iv, lo):
        raise bd.WindowError("bad_anchor")

    _, rep = bd.refine(doc, fn)
    assert verdicts(rep)[15] == (bd.UNRESOLVED, "identity") and verdicts(rep)[16] == (bd.UNRESOLVED, "bad_anchor")


def test_unexpected_backward_error_leaves_only_that_interval_unresolved_and_the_others_still_run():
    doc = make_doc(seq(80, lost(*range(15, 22), *range(50, 57))))
    calls = []

    def fn(iv, lo):
        calls.append(iv.a)
        if iv.a == 15:
            raise RuntimeError("DmlExecutionProvider: out of memory")
        return full(lo, iv.q - 1)

    new, rep = bd.refine(doc, fn)
    assert calls == [15, 50] and len(rep.errors) == 1 and "RuntimeError" in rep.errors[0] and "kare 15-" in rep.errors[0]
    v = verdicts(rep)
    assert {v[i][1] for i in range(15, 22)} == {"backward_error"} and all(v[i][0] == bd.REPAIRED for i in range(50, 57))
    assert new["records"][16] == doc["records"][16] and "1 aralıkta HATA" in rep.summary()


def test_keyboard_interrupt_is_not_swallowed():
    doc = make_doc(seq(40, lost(*range(15, 23))))

    def fn(iv, lo):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        bd.refine(doc, fn)


# --- çıktı belgesi ---

def test_refine_block_keeps_original_values_and_counts_and_derived_counters_are_consistent():
    doc = make_doc(seq(40, lost(*range(15, 23))))
    new, rep, _ = run(doc, {**full(20, 22), **full(14, 18), 19: bf(tracked=False)})  # 19'da iz koptu: 15-19 çözülemez
    blk = new["refine"]
    assert blk["fields"] == list(bd.REFINE_FIELDS) and len(blk["rows"]) == 8
    r = {n: v for n, v in zip(blk["fields"], blk["rows"][0], strict=True)}
    assert r["index"] == 15 and r["verdict"] == bd.UNRESOLVED and r["why"] == "no_backward"
    assert r["otracked"] == 0 and r["ox1"] is None
    r = {n: v for n, v in zip(blk["fields"], blk["rows"][7], strict=True)}
    assert r["index"] == 22 and r["verdict"] == bd.REPAIRED and r["bconf"] == 0.9
    assert blk["counts"] == {"suspect": 8, "repaired": rep.count(bd.REPAIRED), "confirmed": 0,
                             "unresolved": rep.count(bd.UNRESOLVED)}
    assert blk["intervals"][0]["closure"] in (bd.OPEN, bd.CLOSED)
    n_tr = sum(1 for x in new["records"] if x[1])
    assert new["counts"] == {"frames": 40, "tracked": n_tr, "lost": 40 - n_tr}
    assert new["state"]["counts"] == {s: sum(1 for x in new["state"]["rows"] if x[1] == s) for s in new["state"]["counts"]}


def test_refined_document_loads_and_feeds_the_existing_camera(tmp_path):
    recs = seq(80, lost(*range(15, 55)))
    doc = make_doc(recs)
    new, rep, _ = run(doc, full(14, 56))  # 55-56: aday kareler
    assert rep.results[0].closure == bd.CLOSED
    p = st.save_doc(tmp_path / "x.avi.sam.refined.json", new)
    back = st.load_doc(p)  # tür/sürüm/alanlar S4-S11 ile uyumlu
    old_cam, _ = camera.views_from_doc(doc)
    new_cam, _ = camera.views_from_doc(back)
    assert old_cam.held > 0 and new_cam.held == 0  # 4 sn'lik kayıp: önce bekleme + zoom-out vardı, onarımla yok
    assert min(v.zoom for v in new_cam.per_frame) >= min(v.zoom for v in old_cam.per_frame)


def test_refining_a_refined_document_is_refused():
    doc = make_doc(seq(40, lost(*range(15, 23))))
    new, _, _ = run(doc, full(14, 22))
    with pytest.raises(ValueError, match="zaten"):
        bd.refine(new, lambda iv, lo: {})


def test_document_without_state_block_is_refined_from_records_alone():
    doc = make_doc(seq(40, lost(*range(15, 23))), states=False)
    new, rep, _ = run(doc, full(14, 22))
    assert rep.count(bd.REPAIRED) == 8 and "state" not in new
    assert camera.views_from_doc(new)[0].held == 0  # kamera durumu kayıttan türetir: clean=0 -> yarı örtülü


def test_summary_and_lines_report_counts_and_reasons():
    doc = make_doc(seq(40, lost(*range(15, 23))))
    _, rep, _ = run(doc, {**full(19, 22)})
    s = rep.summary()
    assert "1 belirsiz aralık" in s and "4 onarıldı" in s and "4 çözülmedi" in s and "no_backward 4" in s
    assert "kare 15-22" in rep.lines()[0] and "open" in rep.lines()[0]


# --- gerçek geri geçiş (sahte grafikler, sahte video) ---

def fake_loader(calls):
    def load(video, times, fps, max_side):
        calls.append((video, list(times), fps, max_side))
        return [("kare", t) for t in times]
    return load


def stub_track(log, box_for=lambda k: BOX):
    def track(engine, frames, rect, **kw):
        fr = list(frames)
        log.append({"rect": rect, "kw": kw, "frames": fr})
        for k, (t, _) in enumerate(fr):
            yield rec(k, box=box_for(k))
    return track


def test_backward_pass_prompts_with_the_anchor_box_and_walks_time_in_reverse():
    rows = bd.forward_rows(make_doc(seq(40, lost(*range(15, 23)))))
    loads, log = [], []
    iv = Interval(15, 22, 14, 23)
    out = bd.backward_pass("eng", "v.mp4", rows, iv, 14, FPS, loader=fake_loader(loads), track=stub_track(log))
    assert loads[0][1] == [i / FPS for i in range(14, 24)]  # çözülen kareler ileri sırada
    call = log[0]
    assert call["rect"] == rows[23].box and call["kw"] == {"normalized": True}
    assert [t for t, _ in call["frames"]] == [i / FPS for i in range(23, 13, -1)]  # çapa önce, geri sırada
    assert call["frames"][0][1] == ("kare", 23 / FPS) and call["frames"][-1][1] == ("kare", 14 / FPS)
    assert sorted(out) == list(range(14, 23)) and all(isinstance(b, BackFrame) for b in out.values())


def test_backward_pass_maps_record_index_back_to_the_original_frame():
    rows = bd.forward_rows(make_doc(seq(40, lost(*range(15, 23)))))
    out = bd.backward_pass("e", "v", rows, Interval(15, 22, 14, 23), 14, FPS, loader=fake_loader([]),
                           track=stub_track([], box_for=lambda k: (0.3, 0.4 + 0.001 * k, 0.6, 0.9)))
    assert out[22].box[1] == 0.401 and out[14].box[1] == pytest.approx(0.409)


def test_bad_anchor_box_or_missing_anchor_mask_raise_window_error_not_a_crash():
    rows = bd.forward_rows(make_doc(seq(40, lost(*range(15, 23)))))
    tiny = bd.Fwd(**{**rows[23].__dict__, "box": (0.5, 0.5, 0.505, 0.505)})
    with pytest.raises(bd.WindowError) as e:
        bd.backward_pass("e", "v", [*rows[:23], tiny, *rows[24:]], Interval(15, 22, 14, 23), 14, FPS,
                         loader=fake_loader([]), track=stub_track([]))
    assert e.value.code == "bad_anchor"

    def no_mask(engine, frames, rect, **kw):
        raise st.NoInitialMask("maske yok")
        yield  # pragma: no cover

    with pytest.raises(bd.WindowError) as e2:
        bd.backward_pass("e", "v", rows, Interval(15, 22, 14, 23), 14, FPS, loader=fake_loader([]), track=no_mask)
    assert e2.value.code == "no_anchor_mask"


def test_window_size_is_bounded_by_max_window_in_the_real_flow():
    doc = make_doc(seq(100, lost(*range(20, 80))))  # 6 sn kayıp (TEMPORARILY_LOST), 80-81 aday, q = 82
    loads, log = [], []
    new, rep = bd.refine_video(doc, "klip.avi", "eng", max_window=12, loader=fake_loader(loads), track=stub_track(log))
    assert len(loads) == 1 and len(loads[0][1]) == 12 and len(log[0]["frames"]) == 12
    assert loads[0][3] == bd.MAX_SIDE
    assert rep.results[0].iv.n == 62  # 20-79 kayıp + 80-81 aday
    assert rep.count(bd.REPAIRED) == 9 and rep.count(bd.CONFIRMED) == 2 and rep.count(bd.UNRESOLVED) == 62 - 11


def test_video_signature_mismatch_is_refused():
    doc = make_doc(seq(40, lost(*range(15, 23))))
    doc["vsig"] = "0123456789abcdef"
    with pytest.raises(ValueError, match="imza"):
        bd.refine_video(doc, "klip.avi", "eng", loader=fake_loader([]), track=stub_track([]))


def test_end_to_end_with_the_real_track_video_and_fake_graphs():
    """Gerçek `track_video` + sahte grafikler: geri iz çapadan başlar, kutu = sahte maskenin kutusu."""
    eng, _ = make([GOOD] * 12)
    box = (0.25, 0.125, 0.50, 0.375)  # sahte maske (64,32)-(127,95)/256
    recs = seq(40, {**lost(*range(15, 23)), **{i: dict(box=box) for i in range(0, 15)}, **{i: dict(box=box) for i in range(23, 40)}})
    doc = make_doc(recs)
    frames_ = lambda video, times, fps, max_side: [np.zeros((48, 64, 3), np.uint8) for _ in times]  # noqa: E731
    new, rep = bd.refine_video(doc, "klip.avi", eng, loader=frames_)
    assert rep.results[0].closure == bd.CLOSED and rep.count(bd.REPAIRED) == 8
    row = dict(zip(new["fields"], new["records"][18], strict=True))
    assert row["x1"] == pytest.approx(0.25, abs=0.01) and row["y2"] == pytest.approx(0.375, abs=0.01)
    assert row["clean"] == 0 and row["tracked"] == 1


# --- kare yükleme ---

class FakeClip:
    def __init__(self, ts_, shape=(1080, 1920, 3)):
        self.ts, self.shape, self.closed, self.args = ts_, shape, False, None

    def __iter__(self):
        for t in self.ts:
            yield t, np.zeros(self.shape, np.uint8)

    def close(self):
        self.closed = True


def factory(clip):
    def make_clip(video, fps, start, max_seconds):
        clip.args = (video, fps, start, max_seconds)
        return clip
    return make_clip


def test_load_window_shrinks_frames_matches_times_and_closes_the_clip():
    clip = FakeClip([1.0, 1.1, 1.2, 1.3])
    out = bd.load_window("v.mp4", [1.0, 1.1, 1.2], FPS, 1024, clip_factory=factory(clip))
    cv2 = pytest.importorskip("cv2")  # noqa: F841
    assert len(out) == 3 and out[0].shape == (576, 1024, 3)
    assert clip.args == ("v.mp4", FPS, 1.0, pytest.approx(0.2)) and clip.closed


def test_load_window_keeps_small_frames_and_tolerates_a_one_source_frame_drift():
    clip = FakeClip([1.02, 1.11, 1.18], shape=(48, 64, 3))
    out = bd.load_window("v", [1.0, 1.1, 1.2], FPS, 1024, clip_factory=factory(clip))
    assert [o.shape for o in out] == [(48, 64, 3)] * 3


def test_load_window_missing_frame_raises_decode_failed():
    for ts_ in ([1.0, 1.2], [1.0, 1.1], [1.1, 1.2]):  # ortada, sonda, başta eksik
        with pytest.raises(bd.WindowError) as e:
            bd.load_window("v", [1.0, 1.1, 1.2], FPS, 1024, clip_factory=factory(FakeClip(ts_, (48, 64, 3))))
        assert e.value.code == "decode_failed"


# --- CLI ---

def _files(tmp_path, recs=None, **kw):
    video = tmp_path / "klip.avi"
    video.write_bytes(b"fake")
    doc = make_doc(recs or seq(60, lost(*range(15, 45))), video=str(video), **kw)
    return video, st.save_doc(tmp_path / "klip.avi.sam.json", doc)


def test_cli_plan_lists_intervals_and_needs_no_model(tmp_path, monkeypatch, capsys):
    from tracker import sam_engine as se

    monkeypatch.setattr(se, "SamEngine", lambda *a, **k: pytest.fail("--plan model yüklememeli"))
    _, p = _files(tmp_path)
    assert main(["sam-refine", "models", str(p), "--plan"]) == 0
    out = capsys.readouterr().out
    assert "1 belirsiz aralık" in out and "kare 15-46" in out and "q=47" in out and "geri pencere 34 kare" in out
    assert not (tmp_path / "klip.avi.sam.refined.json").exists()


def test_cli_plan_reports_a_clean_clip(tmp_path, capsys):
    _, p = _files(tmp_path, seq(30))
    assert main(["sam-refine", "models", str(p), "--plan"]) == 0
    assert "hepsi güvenilir" in capsys.readouterr().out


def test_cli_refine_writes_a_separate_file_keeps_the_original_and_can_write_the_camera(tmp_path, monkeypatch, capsys):
    from tracker import sam_engine as se

    made = []
    monkeypatch.setattr(se, "SamEngine", lambda md, dev, rule="best", memory=False: made.append((md, dev, memory)) or "eng")
    monkeypatch.setattr(bd, "load_window", lambda video, times, fps, max_side: [None] * len(times))
    monkeypatch.setattr(st, "track_video", stub_track([]))
    video, p = _files(tmp_path)
    before = p.read_bytes()
    assert main(["sam-refine", "models", str(p), "--camera", "--max-window", "40"]) == 0
    out = capsys.readouterr().out
    assert len(made) == 1 and made[0][0] == "models" and made[0][2] is True  # bellek grafikleri açık
    assert "32 belirsiz kare → 30 onarıldı, 2 doğrulandı, 0 çözülmedi" in out and "özgün kayıt değişmedi" in out
    assert p.read_bytes() == before
    refined = st.load_doc(tmp_path / "klip.avi.sam.refined.json")
    assert refined["refine"]["counts"]["repaired"] == 30 and refined["counts"]["lost"] == 0
    views = json.loads((tmp_path / "klip.avi.views.json").read_text(encoding="utf-8"))
    assert views["target"]["kind"] == "sam-lower" and views["views"]


def test_cli_backward_crash_still_writes_the_file_and_exits_1(tmp_path, monkeypatch, capsys):
    from tracker import sam_engine as se

    def boom(engine, frames, rect, **kw):
        raise RuntimeError("onnx çöktü")
        yield  # pragma: no cover

    monkeypatch.setattr(se, "SamEngine", lambda *a, **k: "eng")
    monkeypatch.setattr(bd, "load_window", lambda video, times, fps, max_side: [None] * len(times))
    monkeypatch.setattr(st, "track_video", boom)
    _, p = _files(tmp_path)
    assert main(["sam-refine", "models", str(p)]) == 1
    cap = capsys.readouterr()
    assert "1 aralıkta HATA" in cap.out and "onnx çöktü" in cap.err
    refined = st.load_doc(tmp_path / "klip.avi.sam.refined.json")
    assert refined["refine"]["counts"]["repaired"] == 0 and refined["records"] == st.load_doc(p)["records"]


def test_cli_out_option_and_errors_exit_with_code_1(tmp_path, monkeypatch, capsys):
    from tracker import sam_engine as se

    monkeypatch.setattr(se, "SamEngine", lambda *a, **k: "eng")
    monkeypatch.setattr(bd, "load_window", lambda video, times, fps, max_side: [None] * len(times))
    monkeypatch.setattr(st, "track_video", stub_track([]))
    video, p = _files(tmp_path)
    out = tmp_path / "baska.json"
    assert main(["sam-refine", "models", str(p), "--out", str(out)]) == 0 and out.is_file()
    assert main(["sam-refine", "models", str(out)]) == 1  # zaten iyileştirilmiş
    assert "zaten" in capsys.readouterr().err
    video.unlink()
    assert main(["sam-refine", "models", str(p)]) == 1
    assert "video bulunamadı" in capsys.readouterr().err
    assert main(["sam-refine", "models", str(p), "--plan", "--max-window", "1"]) == 1


def test_refined_path_naming():
    assert bd.refined_path(Path("a/x.mp4.sam.json")) == Path("a/x.mp4.sam.refined.json")
    assert bd.refined_path(Path("a/x.json")) == Path("a/x.refined.json")


def test_module_imports_no_model_runtime():
    import ast

    src = Path(bd.__file__).read_text(encoding="utf-8")
    mods = {n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom) and n.module}
    names = {a.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import) for a in n.names}
    assert not ({"onnxruntime", "numpy"} & names) and not any(m.startswith(("onnxruntime", "tracker.reid", "tracker.pose")) for m in mods)
