"""S10: kayıptan dönüşte Re-ID ile kimlik doğrulama (reentry.py) + durum makinesine bağlanması.
Sahte embedder/poz/SAM betiği; model, GPU ve gerçek OSNet gerekmez."""
import json
import random
from types import SimpleNamespace

import numpy as np
import pytest
from test_posture import _FakePoseEstimator
from test_sam_track import GOOD, _cli

from tracker import reentry as re_
from tracker import sam_track as st
from tracker import trackstate as ts
from tracker.config import Config
from tracker.geometry import BBox
from tracker.main import main
from tracker.reentry import AMBIGUOUS, MATCH, MISMATCH, UNKNOWN, Identity, ReentryVerifier

W, H = 200, 120
RED, BLUE = (0, 0, 255), (255, 0, 0)  # BGR; kosinüs 0
T, TL, OUT, CAND, RE, MAN = (ts.TRACKED, ts.TEMPORARILY_LOST, ts.OUT_OF_FRAME, ts.REACQUISITION_CANDIDATE,
                             ts.REACQUIRED, ts.MANUAL_RESELECT_REQUIRED)


class ColorEmbedder:
    """Kutudaki ortalama renk -> L2-normalize vektör; çağrı sayısı tutulur."""

    def __init__(self):
        self.calls = 0

    def embed(self, frame, boxes):
        self.calls += 1
        rows = []
        for b in boxes:
            c = frame[int(b.y1):int(b.y2), int(b.x1):int(b.x2)].reshape(-1, 3).mean(axis=0)
            n = float(np.linalg.norm(c))
            rows.append(c / n if n > 0 else np.zeros(3))
        return np.array(rows, np.float32)


def pose(x, h=80, w=40, y2=105):
    return SimpleNamespace(bbox=BBox(x - w / 2, y2 - h, x + w / 2, y2), score=0.9, kpts=None)


def scene(*people):
    """people: (pose, BGR renk). Kare + poz listesi."""
    f = np.zeros((H, W, 3), np.uint8)
    for p, col in people:
        b = p.bbox
        f[int(b.y1):int(b.y2), int(b.x1):int(b.x2)] = col
    return f, [p for p, _ in people]


def sam_box(x):
    return ((x - 15) / W, 50 / H, (x + 15) / W, 100 / H)


def rec(t, x=60, index=0):
    return SimpleNamespace(t=t, index=index, box=sam_box(x), tracked=True, clean=True, ratio=1.0, conf=0.9,
                           size=None, accepted=True)


def ctx(gap=2.0, episode=1.0, state=TL, anchor_x=60):
    a = ts.Anchor(3, 0.3, sam_box(anchor_x), (0.15, 0.42), 0.9, 1.0)
    return ts.ReentryContext(episode, gap, a, None, state)


def verifier(**kw):
    """Galerisi RED hedefle dolu doğrulayıcı (hedef x=60'ta durdu)."""
    emb = ColorEmbedder()
    v = ReentryVerifier(emb, Config(), **kw)
    f, ps = scene((pose(60), RED))
    v.observe(f, rec(0.0), ps, (W, H), 0.0)
    assert v.gallery_size == 1
    emb.calls = 0
    return v, emb


def check(v, people, t, x=60, c=None, **kw):
    f, ps = scene(*people)
    return v.check(f, rec(t, x), ps, (W, H), c or ctx(**kw))


def decisions(v, people, n, t0=2.0, dt=0.1, x=60, **kw):
    return [check(v, people, t0 + k * dt, x, **kw).decision for k in range(n)]


# --- galeri ---

def test_observe_adds_clean_crops_only_and_is_rate_limited():
    emb = ColorEmbedder()
    v = ReentryVerifier(emb, Config())
    f, ps = scene((pose(60), RED))
    v.observe(f, rec(0.0), ps, (W, H), 0.0)
    v.observe(f, rec(0.1), ps, (W, H), 0.1)  # reid_every_s = 0.3: atlanır
    assert emb.calls == 1 and v.gallery_size == 1
    f, ps = scene((pose(60), RED), (pose(70), BLUE))  # kişiler iç içe: kırpıntı kirlenir
    v.observe(f, rec(1.0), ps, (W, H), 1.0)
    assert v.gallery_size == 1 and emb.calls == 1
    v.observe(f, rec(2.0), [], (W, H), 2.0)  # kişi yok: sessiz
    assert v.gallery_size == 1


def test_no_gallery_means_no_check_and_the_machine_falls_back_to_s9():
    v = ReentryVerifier(ColorEmbedder(), Config())
    f, ps = scene((pose(60), RED))
    assert v.check(f, rec(2.0), ps, (W, H), ctx()) is None and v.unverified == 1 and not v.rows
    assert "doğrulanamadı 1" in v.summary()


# --- doğrulama: kare kanıtı ---

def test_the_target_coming_back_is_accepted_only_after_three_matching_frames():
    v, _ = verifier()
    out = decisions(v, [(pose(60), RED)], 5)
    assert out == ["pending", "pending", "accept", "accept", "accept"]
    assert {r[4] for r in v.rows} == {MATCH} and v.rows[0][5] == "ok" and v.rows[0][6] == pytest.approx(1.0)


def test_a_different_person_in_the_same_place_is_rejected_after_two_frames():
    v, _ = verifier()
    out = decisions(v, [(pose(60), BLUE)], 3)
    assert out == ["pending", "reject", "reject"]
    assert v.rows[0][4] == MISMATCH and v.rows[0][5] == "low_score"


def test_one_bad_frame_in_the_middle_restarts_the_acceptance_count():
    v, _ = verifier()
    good, bad = [(pose(60), RED)], [(pose(60), BLUE)]
    seq = [good, good, bad, good, good, good]
    out = [check(v, p, 2.0 + 0.1 * k).decision for k, p in enumerate(seq)]
    assert out == ["pending", "pending", "pending", "pending", "pending", "accept"]  # tek uyumsuzluk ret için yetmez


def test_two_similar_people_never_accept_and_end_uncertain_after_verify_s():
    v, _ = verifier(verify_s=1.0)
    near_red = (30, 0, 255)  # RED ile kosinüs ~0.99: aralarında marj yok
    people = [(pose(60), RED), (pose(140), near_red)]
    out = decisions(v, people, 14)
    assert set(out[:10]) == {"pending"} and set(out[10:]) == {"uncertain"}
    assert {r[4] for r in v.rows} == {AMBIGUOUS} and v.rows[0][5] == "two_similar"


def test_sam_on_the_wrong_person_while_the_target_is_visible_elsewhere_is_a_mismatch():
    v, _ = verifier()
    people = [(pose(60), (120, 0, 255)), (pose(140), RED)]  # SAM x=60'ta; hedef x=140'ta (cos 0.9 vs 1.0)
    out = check(v, people, 2.0)
    assert out.verdict == MISMATCH and out.why == "other_better" and out.other > out.score >= 0.6


def test_a_weak_but_not_hopeless_score_is_ambiguous_not_a_mismatch():
    v, _ = verifier()
    weak = (228, 0, 150)
    cos = 150 / float(np.hypot(228, 150))
    assert 0.5 <= cos < 0.6
    out = check(v, [(pose(60), weak)], 2.0)
    assert out.verdict == AMBIGUOUS and out.why == "weak_score" and out.decision == "pending"


def test_reappearing_far_from_the_last_crop_too_soon_is_a_mismatch_without_embedding():
    v, emb = verifier()
    far = check(v, [(pose(150), RED)], 0.5, x=150, gap=0.2)  # 0.45 kare genişliği, 0.2 sn
    assert far.verdict == MISMATCH and far.why == "too_far" and emb.calls == 0
    late = check(v, [(pose(150), RED)], 3.0, x=150, gap=5.0, episode=9.0)  # aynı yer 5 sn sonra makul
    assert late.verdict == MATCH


def test_person_size_and_proportions_must_fit_the_target():
    v, _ = verifier()
    small = check(v, [(pose(60, h=20, w=40), RED)], 2.0)  # boy 0.25x
    assert small.verdict == MISMATCH and small.why == "scale"
    wide = check(v, [(pose(60, h=60, w=110), RED)], 2.1, episode=2.0)  # en/boy 3x (boy oranı makul)
    assert wide.verdict == MISMATCH and wide.why == "proportions"


def test_unusable_evidence_is_unknown_and_never_counts_for_either_side():
    v, emb = verifier()
    assert check(v, [], 2.0).why == "no_person" and check(v, [], 2.1).verdict == UNKNOWN
    edge = check(v, [(pose(60, y2=120), RED)], 2.2)  # kutu alt kenarda kesik
    assert edge.verdict == UNKNOWN and edge.why == "crop" and emb.calls == 0
    assert {r[3] for r in v.rows} == {"pending"}


def test_a_new_absence_resets_the_window_and_the_uncertain_clock():
    v, _ = verifier(verify_s=1.0)
    bad = [(pose(60), (228, 0, 150))]
    assert decisions(v, bad, 12, t0=2.0)[-1] == "uncertain"
    assert check(v, bad, 5.0, episode=7.0).decision == "pending"  # yeni yokluk: saat yeniden


def test_acceptance_can_still_come_after_an_uncertain_stretch():
    v, _ = verifier(verify_s=0.3)
    bad, good = [(pose(60), (228, 0, 150))], [(pose(60), RED)]
    assert decisions(v, bad, 5)[-1] == "uncertain"
    assert [check(v, good, 3.0 + 0.1 * k).decision for k in range(3)] == ["uncertain", "uncertain", "accept"]


def test_missing_embedder_output_is_unknown_not_a_crash():
    class Boom:
        def embed(self, frame, boxes):
            raise RuntimeError("x")

    v, _ = verifier()
    v.app.emb = Boom()
    assert check(v, [(pose(60), RED)], 2.0).why == "embed"


# --- durum makinesi ---

BOX = (0.3, 0.2, 0.6, 0.7)
OTHER = (0.62, 0.2, 0.92, 0.7)


def mrec(i, kind="T", box=BOX, dt=0.1):
    tracked = kind == "T"
    return st.TrackRecord(index=i, t=round(i * dt, 4), state=st.TRACKED if tracked else st.LOST, accepted=True,
                          box=box if tracked else None, area=0.1, iou=0.9, object_score=3.0, conf=0.9, ratio=1.0,
                          clean=tracked, size=(box[2] - box[0], box[3] - box[1]) if tracked else None)


def ident(decision, verdict=MATCH):
    return Identity(decision, verdict, "ok")


def drive(m, pattern, identities=None, boxes=None, start=0):
    """pattern: T/L; identities: kayıptan dönen izlenen kareler için karar sırası (ctx doluysa kullanılır)."""
    ids = iter(identities or [])
    out = []
    for k, ch in enumerate(pattern):
        r = mrec(start + k, ch, **({"box": boxes[k]} if boxes else {}))
        ident_ = next(ids, None) if m.reentry_context(r) is not None else None
        out.append(m.update(r, identity=ident_))
    return out


def test_context_exists_only_for_a_seen_frame_after_a_long_loss_with_a_known_anchor():
    m = ts.TrackStateMachine(hold_s=1.0)
    assert m.reentry_context(mrec(0, "T")) is None  # henüz durum yok
    drive(m, "TT")
    assert m.reentry_context(mrec(2, "T")) is None  # izlenirken
    drive(m, "LLL", start=2)
    assert m.reentry_context(mrec(5, "T")) is None  # kısa kayıp (<= hold_s): doğrudan sürer
    assert m.reentry_context(mrec(5, "L")) is None  # kayıp kare: denetlenecek şey yok
    drive(m, "L" * 10, start=5)
    c = m.reentry_context(mrec(15, "T"))
    assert c.state == TL and c.episode == pytest.approx(0.2) and c.gap == pytest.approx(1.3) and c.anchor.box == BOX
    assert ts.TrackStateMachine().update(mrec(0, "L")).state == TL
    m2 = ts.TrackStateMachine()
    m2.update(mrec(0, "L"))
    assert m2.reentry_context(mrec(40, "T")) is None  # hiç güvenilir kare yok: karşılaştırılacak kimlik yok


def test_a_rejected_return_keeps_the_loss_the_clock_the_crop_and_never_moves_the_anchor():
    m = ts.TrackStateMachine(hold_s=1.0, manual_s=8.0)
    drive(m, "TT" + "L" * 15)
    fr = drive(m, "TTTT", [ident(ts.ID_PENDING, MISMATCH), ident(ts.ID_REJECT, MISMATCH), ident(ts.ID_REJECT, MISMATCH),
                           ident(ts.ID_REJECT, MISMATCH)], boxes=[OTHER] * 4, start=17)
    assert [f.state for f in fr] == [CAND, TL, TL, TL] and [f.reason for f in fr] == ["back"] + ["other_person"] * 3
    assert fr[1].changed and fr[1].prev == CAND and fr[1].lost_s == pytest.approx(1.6) and not fr[1].hold
    assert all(f.crop == BOX for f in fr) and m.anchor.box == BOX  # yabancı kutu anchor olmadı
    assert fr[1].identity.decision == ts.ID_REJECT and fr[1].to_dict()["identity"]["decision"] == "reject"


def test_a_rejected_stranger_that_stays_long_enough_ends_in_manual_reselect():
    m = ts.TrackStateMachine(hold_s=1.0, manual_s=3.0)
    drive(m, "TT" + "L" * 15)
    ids = [ident(ts.ID_REJECT, MISMATCH)] * 40
    fr = drive(m, "T" * 40, ids, boxes=[OTHER] * 40, start=17)
    first = next(f for f in fr if f.state == MAN)
    assert first.reason == "timeout" and first.lost_s == pytest.approx(3.0, abs=0.11)
    assert all(f.state == TL for f in fr[: fr.index(first)]) and fr[-1].state == MAN and fr[-1].reason == "other_person"


def test_out_of_frame_stays_out_while_a_stranger_walks_in_and_waits_its_longer_deadline():
    left = [(0.3 - 0.1 * k if k < 3 else 0.0, 0.2, 0.5 - 0.1 * k if k < 3 else 0.2, 0.8) for k in range(4)]
    m = ts.TrackStateMachine(hold_s=0.5)
    drive(m, "TTTT", boxes=left)
    drive(m, "LL", start=4)
    fr = drive(m, "TTTT", [ident(ts.ID_REJECT, MISMATCH)] * 4, boxes=[(0.0, 0.2, 0.15, 0.8)] * 4, start=6)
    assert [f.state for f in fr] == [OUT] * 4 and {f.edge for f in fr} == {"left"} and fr[0].reason == "other_person"


def test_pending_frames_hold_the_camera_and_never_confirm_even_after_enough_frames():
    m = ts.TrackStateMachine(hold_s=1.0)
    drive(m, "TT" + "L" * 15)
    fr = drive(m, "TTTTTT", [ident(ts.ID_PENDING, "unknown")] * 6, boxes=[OTHER] * 6, start=17)
    assert [f.state for f in fr] == [CAND] * 6 and [f.reason for f in fr] == ["back", "back", "verifying", "verifying", "verifying", "verifying"]
    assert all(f.hold and f.crop == BOX for f in fr) and m.anchor.box == BOX  # doğrulanmamış kare anchor'ı kirletmedi


def test_accept_confirms_the_candidate_and_only_then_the_anchor_follows_the_new_position():
    m = ts.TrackStateMachine(hold_s=1.0)
    drive(m, "TT" + "L" * 15)
    fr = drive(m, "TTTTTT", [ident(ts.ID_PENDING), ident(ts.ID_PENDING), ident(ts.ID_ACCEPT)], boxes=[OTHER] * 6, start=17)
    assert [f.state for f in fr] == [CAND, CAND, RE, RE, RE, T] and fr[2].reason == "confirmed"
    assert fr[0].crop == BOX and m.anchor.box == OTHER and fr[2].lost_s == pytest.approx(1.5)


def test_an_uncertain_return_asks_for_a_manual_reselect_and_a_later_accept_comes_back_through_a_candidate():
    m = ts.TrackStateMachine(hold_s=1.0, manual_s=8.0)
    drive(m, "TT" + "L" * 15)
    fr = drive(m, "TTT", [ident(ts.ID_PENDING, AMBIGUOUS), ident(ts.ID_UNCERTAIN, AMBIGUOUS), ident(ts.ID_UNCERTAIN, AMBIGUOUS)],
               boxes=[OTHER] * 3, start=17)
    assert [f.state for f in fr] == [CAND, MAN, MAN] and fr[1].reason == "ambiguous_reentry" and not fr[1].hold
    assert m.anchor.box == BOX
    fr2 = drive(m, "TTTT", [ident(ts.ID_ACCEPT)] * 4, boxes=[OTHER] * 4, start=20)
    assert [f.state for f in fr2] == [CAND, CAND, RE, RE] and fr2[0].prev == MAN  # confirm_frames=3 yine gerekir


def test_a_decision_is_ignored_when_the_frame_is_not_a_return_and_without_identity_nothing_changes():
    m = ts.TrackStateMachine(hold_s=1.0)
    f = m.update(mrec(0, "T"), identity=ident(ts.ID_REJECT, MISMATCH))
    f2 = m.update(mrec(1, "T"), identity=ident(ts.ID_REJECT, MISMATCH))
    assert (f.state, f2.state, f2.identity) == (T, T, None)
    fr = drive(ts.TrackStateMachine(hold_s=1.0), "TT" + "L" * 15 + "TTTT")  # kimlik yok: S9 yolu
    assert [f.state for f in fr[17:]] == [CAND, CAND, RE, RE]


def test_state_machine_with_random_identity_decisions_keeps_the_transition_table():
    boxes = [BOX, OTHER, (0.0, 0.2, 0.3, 0.8), (0.3, 0.6, 0.6, 1.0)]
    for seed in range(40):
        rng = random.Random(seed)
        m = ts.TrackStateMachine(hold_s=rng.choice([0.0, 0.5, 1.0]), manual_s=rng.choice([1.0, 3.0]), out_max_s=rng.choice([2.0, 6.0]))
        prev = None
        for i in range(400):
            kind = rng.choices("TL", weights=[10, 6])[0]
            r = mrec(i, kind, rng.choice(boxes))
            c = m.reentry_context(r)
            idn = ident(rng.choice([ts.ID_PENDING, ts.ID_ACCEPT, ts.ID_REJECT, ts.ID_UNCERTAIN])) if c else None
            f = m.update(r, identity=idn)
            if prev is not None and prev != f.state:
                assert f.state in ts.ALLOWED[prev], (seed, i, prev, f.state)
            if idn is not None and idn.decision in (ts.ID_REJECT, ts.ID_UNCERTAIN):
                assert f.state in ts.LOST_STATES  # başka kişi / belirsiz: asla izlenen duruma geçmez
            if f.state == RE and prev == CAND and idn is not None:
                assert idn.decision == ts.ID_ACCEPT  # kabul olmadan REACQUIRED yok
            assert (f.crop is None) == (m.anchor is None)
            prev = f.state


# --- uçtan uca: iki benzer kişi, uzun kayıp, yabancı dönüşü ---

def test_verifier_and_machine_together_never_attach_to_the_next_person_who_appears():
    emb = ColorEmbedder()
    v = ReentryVerifier(emb, Config())
    m = ts.TrackStateMachine(hold_s=1.0, manual_s=8.0)
    x_t = 60
    for i in range(3):  # hedef görünür: galeri dolar
        f, ps = scene((pose(x_t), RED))
        r = mrec(i, "T", sam_box(x_t))
        m.update(r)
        v.observe(f, r, ps, (W, H), r.t)
    for i in range(3, 18):
        m.update(mrec(i, "L"))
    states = []
    for k in range(12):  # yabancı (mavi) aynı yere gelir
        i = 18 + k
        f, ps = scene((pose(x_t), BLUE))
        r = mrec(i, "T", sam_box(x_t))
        c = m.reentry_context(r)
        states.append(m.update(r, identity=v.check(f, r, ps, (W, H), c) if c else None).state)
    assert RE not in states and T not in states and states[-1] == TL
    # hedef geri dönünce kabul
    out = []
    for k in range(5):
        i = 30 + k
        f, ps = scene((pose(x_t), RED))
        r = mrec(i, "T", sam_box(x_t))
        c = m.reentry_context(r)
        out.append(m.update(r, identity=v.check(f, r, ps, (W, H), c) if c else None).state)
    assert out[:3] == [CAND, CAND, RE]


# --- kayıt / CLI ---

def test_make_doc_writes_an_optional_reentry_block(tmp_path):
    v, _ = verifier()
    decisions(v, [(pose(60), RED)], 3)
    video = tmp_path / "klip.mp4"
    video.write_bytes(b"v")
    recs = [st.TrackRecord(index=0, t=0.0, state="tracked", accepted=True, box=BOX, area=0.1, iou=0.9, object_score=3.0,
                           conf=0.9, ratio=1.0, clean=True)]
    doc = st.make_doc(video, recs, size=(64, 48), sample_fps=10.0, reentry=v.rows)
    assert doc["reentry"]["fields"] == list(re_.ROW_FIELDS) and len(doc["reentry"]["rows"]) == 3
    assert doc["reentry"]["counts"] == {"pending": 2, "accept": 1} and doc["version"] == 2
    assert "reentry" not in st.make_doc(video, recs, size=(64, 48), sample_fps=10.0)
    json.dumps(doc)
    assert len(v.rows[0]) == len(re_.ROW_FIELDS)


class _ByFrame:
    """Sahte Re-ID: gri düzeyinden kare sırası k çıkarılır; `target_until` sonrası kare mavi (yabancı), önce kırmızı."""

    def __init__(self, target_until=None):
        self.until = target_until

    def __call__(self, *a, **k):
        return self

    def embed(self, frame, boxes):
        k = round(float(frame.mean()) / 8)
        stranger = self.until is not None and k >= 16
        return np.array([[0.0, 1.0] if stranger else [1.0, 0.0] for _ in boxes], np.float32)


def _reid_cli(tmp_path, monkeypatch, stranger):
    import tracker.pose as pose_mod
    import tracker.reid as reid_mod

    monkeypatch.setattr(pose_mod, "PoseEstimator", _FakePoseEstimator)
    monkeypatch.setattr(reid_mod, "Embedder", _ByFrame(16 if stranger else None))
    v, _ = _cli(tmp_path, monkeypatch, script=[GOOD] * 3 + [(None, 0.9, 3.0)] * 12 + [GOOD] * 20)
    return v


def test_cli_reid_stranger_after_a_long_loss_is_rejected_and_the_loss_continues(tmp_path, monkeypatch, capsys):
    v = _reid_cli(tmp_path, monkeypatch, stranger=True)
    assert main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--device", "cpu", "--reid"]) == 0
    out = capsys.readouterr().out
    assert "REACQUIRED" not in out and "re-ID: kabul 0, ret " in out and "galeri " in out
    doc = st.load_doc(st.sam_path(v))
    assert doc["lower"]["rows"]  # --reid poz ister: --pose'u içerir
    assert doc["reentry"]["fields"] == list(re_.ROW_FIELDS) and doc["reentry"]["counts"].get("reject", 0) >= 10
    assert doc["state"]["counts"].get(ts.REACQUIRED) is None and doc["state"]["counts"][TL] > 12
    reasons = {r[2] for r in doc["state"]["rows"]}
    assert "other_person" in reasons


def test_cli_reid_the_target_returning_is_verified_and_reacquired(tmp_path, monkeypatch, capsys):
    v = _reid_cli(tmp_path, monkeypatch, stranger=False)
    assert main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--device", "cpu", "--reid", "--preview"]) == 0
    out = capsys.readouterr().out
    assert "REACQUIRED" in out and "kabul " in out and "ret 0" in out
    doc = st.load_doc(st.sam_path(v))
    assert doc["reentry"]["counts"]["accept"] >= 1 and doc["state"]["counts"][ts.REACQUIRED] == 3
    pv = json.loads(st.sam_path(v).with_name("klip.avi.sam.preview.json").read_text(encoding="utf-8"))
    assert pv["state"] == "DONE"


def test_cli_reid_without_the_model_warns_and_runs_like_s9(tmp_path, monkeypatch, capsys):
    v, _ = _cli(tmp_path, monkeypatch, script=[GOOD] * 3 + [(None, 0.9, 3.0)] * 12 + [GOOD] * 20)
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"reid_model": str(tmp_path / "yok.onnx")}), encoding="utf-8")
    code = main(["--config", str(cfg), "sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--device", "cpu", "--reid"])
    cap = capsys.readouterr()
    assert code == 0 and "Re-ID kapalı" in cap.err and "REACQUIRED" in cap.out and "re-ID:" not in cap.out
    doc = st.load_doc(st.sam_path(v))
    assert "reentry" not in doc and "lower" not in doc  # poz da açılmadı


def test_config_has_the_new_defaults_and_loads_overrides(tmp_path):
    c = Config()
    assert (c.reid_accept_n, c.reid_reject_n, c.reid_verify_s) == (3, 2, 3.0)
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"reid_accept_n": 5}), encoding="utf-8")
    assert Config.load(p).reid_accept_n == 5
