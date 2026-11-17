"""S4: PC SAM bellek döngüsü (tracker/sam_track.py + SamEngine bellek yöntemleri). Model dosyası/GPU gerekmez: sahte grafikler.

Sahte grafikler değerleri taşır: encoder kare sırasını `image_feat`'e yazar, `sam-memenc` bunu bellek karesine
kopyalar, `sam-memattn` aldığı yuvaları kaydeder. Böylece yuva sırası doğrudan okunur.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tracker import cache
from tracker import sam_engine as se
from tracker import sam_track as st
from tracker import trackgate as tg
from tracker.main import main
from tracker.sam_engine import DEC, DEC_TRK, ENC, M, MEMATTN, MEMENC, SamEngine

ROOT = Path(__file__).resolve().parents[1]
CPU = "CPUExecutionProvider"
K, P = 4, 5  # sahte `sam-memattn` statik yuva sayıları


def logits(*regions):
    a = np.full((M, M), -10.0, np.float32)
    for x1, y1, x2, y2 in regions:
        a[y1:y2 + 1, x1:x2 + 1] = 5.0
    return a


class Inp:
    def __init__(self, name, shape):
        self.name, self.shape = name, shape


class FakeEnc:
    """`image_feat` = bu çağrının sırası (kare no) ile dolu."""

    def __init__(self):
        self.n = 0

    def get_providers(self):
        return [CPU]

    def run(self, names, feed):
        f = np.full((1, 2, 2, 2), self.n, np.float32)
        self.n += 1
        return [np.zeros((1, 2, 4, 4), np.float32), np.zeros((1, 3, 2, 2), np.float32),
                np.zeros((1, 4, 2, 2), np.float32), f]


class FakeDec:
    """İlk kare: 3 aday; iou en yüksek #1 (alan 64x64 piksel / 65536)."""

    def __init__(self):
        self.calls = []

    def get_providers(self):
        return [CPU]

    def run(self, names, feed):
        self.calls.append(feed)
        masks = np.stack([logits((10, 10, 20, 20)), logits((64, 32, 127, 95)), logits((0, 0, 255, 255))])[None]
        ptrs = np.stack([np.full(256, k + 1, np.float32) for k in range(3)])[None]
        return [masks, np.array([[0.5, 0.9, 0.7]], np.float32), ptrs, np.array([[3.0]], np.float32)]


class FakeDecTrk:
    """`script`: izleme çağrısı başına (bölge | None, iou, object_score[, işaretçi]). Varsayılan işaretçi = 100 + çağrı no."""

    def __init__(self, script):
        self.script, self.calls = list(script), []

    def get_providers(self):
        return [CPU]

    def run(self, names, feed):
        self.calls.append(feed)
        region, iou, score, *rest = self.script[len(self.calls) - 1]  # rest[0]: isteğe bağlı 256'lık işaretçi
        m = logits(region) if region else logits()
        ptr = rest[0] if rest else np.full(256, 100 + len(self.calls), np.float32)
        return [m[None, None], np.array([[iou]], np.float32),
                np.asarray(ptr, np.float32).reshape(1, 1, 256), np.array([[score]], np.float32)]


class FakeMemEnc:
    def __init__(self, size=3):
        self.calls, self.size = [], size

    def get_providers(self):
        return [CPU]

    def run(self, names, feed):
        self.calls.append({k: np.array(v) for k, v in feed.items()})
        return [np.full((1, self.size), float(feed["image_feat"].flat[0]), np.float32)]


class FakeMemAttn:
    def __init__(self, k=K, p=P):
        self.shapes = {"image_feat": (1, 2, 2, 2), "mem_feats": (k, 3), "ptrs": (p, 256)}
        self.calls = []

    def get_providers(self):
        return [CPU]

    def get_inputs(self):
        return [Inp(n, s) for n, s in self.shapes.items()]

    def run(self, names, feed):
        self.calls.append({"mem": feed["mem_feats"][:, 0].copy(), "ptr": feed["ptrs"][:, 0].copy(),
                           "shape": feed["mem_feats"].shape, "pshape": feed["ptrs"].shape})
        return [np.full((1, 4, 2, 2), float(feed["image_feat"].flat[0]), np.float32)]


def make(script, memenc=None, enc=None, dec=None, memory=True):
    """(engine, parçalar). `script`: FakeDecTrk betiği."""
    parts = SimpleNamespace(enc=enc or FakeEnc(), dec=dec or FakeDec(), trk=FakeDecTrk(script),
                            memenc=memenc or FakeMemEnc(), memattn=FakeMemAttn())
    s = {ENC: parts.enc, DEC: parts.dec}
    if memory:
        s.update({DEC_TRK: parts.trk, MEMENC: parts.memenc, MEMATTN: parts.memattn})
    return SamEngine(sessions=s), parts


def frames(n, w=64, h=48):
    return [(i * 0.1, np.zeros((h, w, 3), np.uint8)) for i in range(n)]


GOOD = ((64, 32, 127, 95), 0.9, 3.0)  # ilk karedekiyle aynı alan -> oran 1


def run(eng, n, rect=(8, 8, 56, 40), **kw):
    return list(st.track_video(eng, frames(n), rect, **kw))


# --- yuva sırası ve banka ---

def test_first_frame_is_pushed_as_slot_zero_and_slots_fill_with_it_until_history_exists():
    eng, p = make([GOOD] * 3)
    recs = run(eng, 4)
    assert len(recs) == 4 and recs[0].index == 0 and recs[0].tracked
    c = p.memattn.calls
    assert c[0]["mem"].tolist() == [0, 0, 0, 0] and c[0]["ptr"].tolist() == [2.0] * P  # boş geçmiş: hepsi ilk kare
    assert c[1]["mem"].tolist() == [0, 1, 0, 0]  # kare 1 izlendi -> yuva 1
    assert c[1]["ptr"].tolist() == [2.0, 101.0, 2.0, 2.0, 2.0]
    assert c[2]["mem"].tolist() == [0, 2, 1, 0]


def test_slot_order_is_prompted_frame_then_frames_d_steps_back():
    eng, p = make([GOOD] * 5)
    run(eng, 6)
    last = p.memattn.calls[-1]  # kare 5; geçmiş: 1,2,3,4
    assert last["mem"].tolist() == [0, 4, 3, 2]  # K=4: istemli, 1 geri, 2 geri, 3 geri
    assert last["ptr"].tolist() == [2.0, 104.0, 103.0, 102.0, 101.0]  # P=5
    assert last["shape"] == (K, 3) and last["pshape"] == (P, 256)


def test_bank_stays_bounded_and_graph_inputs_keep_static_shapes_over_a_long_clip():
    eng, p = make([GOOD] * 59)
    stats = st.TrackStats()
    run(eng, 60, stats=stats)
    assert stats.frames == 60 and stats.tracked == 60 and stats.lost == 0
    assert stats.bank_size <= max(K, P) - 1  # MemoryBank sınırı
    assert {c["shape"] for c in p.memattn.calls} == {(K, 3)} and {c["pshape"] for c in p.memattn.calls} == {(P, 256)}
    assert len(p.memattn.calls) == 59 and len(p.memenc.calls) == 60  # ilk kare + 59 izlenen


def test_lost_frames_push_nothing_to_the_bank():
    lost_empty, lost_score = (None, 0.9, 3.0), ((64, 32, 127, 95), 0.9, -2.0)
    eng, p = make([GOOD, lost_empty, lost_score, GOOD, GOOD])
    recs = run(eng, 6)
    assert [r.state for r in recs] == ["tracked", "tracked", "lost", "lost", "tracked", "tracked"]
    assert len(p.memenc.calls) == 1 + 3  # ilk kare + 3 izlenen kare; kayıp kareler belleğe yazmaz
    mem = [c["mem"].tolist() for c in p.memattn.calls]
    assert mem[1] == mem[2] == mem[3] == [0, 1, 0, 0]  # kare 2 ve 3 kayıptı: yuva 1 hâlâ kare 1
    assert mem[4] == [0, 4, 1, 0]  # kare 4 izlendi
    assert p.memattn.calls[3]["ptr"].tolist() == [2.0, 101.0, 2.0, 2.0, 2.0]


def test_memenc_gets_the_mask_logits_and_object_score_of_the_tracked_frame():
    eng, p = make([((64, 32, 127, 95), 0.9, 4.5)])
    run(eng, 2)
    first, second = p.memenc.calls
    assert first["low_res_mask"].shape == (1, 1, M, M) and first["object_score"].tolist() == [[3.0]]
    assert (first["low_res_mask"][0, 0] > 0).sum() == 64 * 64
    assert second["object_score"].tolist() == [[pytest.approx(4.5)]] and second["image_feat"].flat[0] == 1


def test_decoder_trk_gets_the_conditioned_embedding_and_no_prompt():
    eng, p = make([GOOD])
    run(eng, 2)
    f = p.trk.calls[0]
    assert f["point_coords"].shape == (1, 1, 2) and f["point_labels"].tolist() == [[-1.0]]
    assert f["image_embed"].flat[0] == 1.0  # `sam-memattn` çıktısı (kare 1), encoder'ın ham gömmesi değil


# --- karar ---

def test_confidence_formula_matches_the_android_rule():
    assert st.confidence(0.8, 0.0, 1.0) == pytest.approx(0.4)
    assert st.confidence(0.8, 0.0, 5.0) == pytest.approx(0.2)  # oran dışı: yarım
    assert st.confidence(0.8, 0.0, 0.2) == pytest.approx(0.2)
    assert st.confidence(0.9, 100.0, 1.0) == pytest.approx(0.9)  # taşma yok
    assert st.confidence(0.9, -100.0, 1.0) == pytest.approx(0.0, abs=1e-9)


def test_size_ratio_outside_the_range_halves_confidence_and_can_make_the_frame_lost():
    huge = ((0, 0, 255, 255), 0.6, 3.0)  # alan 16x ilk karenin: 0.6 * 0.95 * 0.5 = 0.29 < 0.35
    ok = ((64, 32, 127, 95), 0.6, 3.0)  # aynı güven, oran 1: 0.57
    recs = run(make([ok, huge])[0], 3)
    assert [r.state for r in recs] == ["tracked", "tracked", "lost"]
    assert recs[2].ratio == pytest.approx(16.0) and recs[2].conf < st.MIN_CONF <= recs[1].conf


def test_object_score_not_positive_is_lost_even_with_a_confident_mask():
    rec = run(make([((64, 32, 127, 95), 0.99, 0.0)])[0], 2)[1]
    assert rec.state == "lost" and rec.box is not None and rec.object_score == 0.0


def test_empty_mask_is_lost_with_no_box_and_zero_area():
    rec = run(make([(None, 0.9, 5.0)])[0], 2)[1]
    assert rec.state == "lost" and rec.box is None and rec.area == 0.0 and rec.mask is None


def test_reference_area_follows_clean_frames_slowly():
    big = ((64, 32, 191, 95), 0.9, 3.0)  # 2x alan: oran 2, izlenir
    recs = run(make([big, big, big])[0], 4, use_gate=False)  # S4 davranışı: her izlenen kare referansı besler
    assert recs[1].ratio == pytest.approx(2.0)
    assert recs[2].ratio < recs[1].ratio  # referans 0.8/0.2 EMA ile büyüdü
    assert recs[3].ratio < recs[2].ratio


def test_frames_the_gate_never_judged_stay_accepted_even_when_lost():
    recs = run(make([GOOD, (None, 0.9, 3.0), GOOD])[0], 4)
    assert [r.tracked for r in recs] == [True, True, False, True]
    assert all(r.accepted for r in recs)  # kayıp ama kapı reddi değil: güven/boş maske elemesi


# --- kayıtlar ---

def test_record_fields_for_the_first_frame_and_normalized_box():
    rec = run(make([])[0], 1)[0]
    assert (rec.index, rec.t, rec.state, rec.ratio) == (0, 0.0, "tracked", 1.0)
    assert rec.box == (0.25, 0.125, 0.5, 0.375)  # (64, 32, 128, 96) / 256
    assert rec.area == pytest.approx(64 * 64 / (M * M)) and rec.iou == pytest.approx(0.9) and rec.conf == rec.iou
    assert rec.object_score == pytest.approx(3.0)


def test_normalized_rect_is_scaled_by_the_first_frame_size():
    eng, p = make([])
    run(eng, 1, rect=(0.1, 0.2, 0.9, 0.8), normalized=True)
    c = p.dec.calls[0]["point_coords"][0]  # 1024 uzayında: oran x 1024 (kare 64x48 olsa da)
    np.testing.assert_allclose(c[:2], [[102.4, 204.8], [921.6, 819.2]], atol=1e-3)
    assert p.dec.calls[0]["point_labels"].tolist() == [[2.0, 3.0, 1.0]]


def test_keep_masks_returns_a_bool_mask_only_when_asked():
    recs = run(make([GOOD])[0], 2, keep_masks=True)
    assert all(r.mask.shape == (M, M) and r.mask.dtype == bool for r in recs)
    assert int(recs[1].mask.sum()) == 64 * 64
    assert all(r.mask is None for r in run(make([GOOD])[0], 2))


def test_generator_is_lazy_one_frame_per_record():
    eng, p = make([GOOD] * 3)
    gen = st.track_video(eng, frames(4), (8, 8, 56, 40))
    next(gen)
    assert p.enc.n == 1 and not p.trk.calls
    next(gen)
    assert p.enc.n == 2 and len(p.trk.calls) == 1


def test_only_the_current_frame_tensors_are_kept_between_frames():
    # kayıt `Encoded` taşımaz; bellek yalnız banka (K/P sınırlı) + son kare
    rec = run(make([GOOD])[0], 2)[1]
    assert not any(isinstance(v, se.Encoded) for v in vars(rec).values())


# --- hatalar ---

def test_no_mask_on_the_first_frame_raises_before_any_memory_work():
    class Empty(FakeDec):
        def run(self, names, feed):
            return [np.stack([logits()] * 3)[None], np.array([[0.1, 0.2, 0.3]], np.float32),
                    np.zeros((1, 3, 256), np.float32), np.array([[-5.0]], np.float32)]

    eng, p = make([], dec=Empty())
    with pytest.raises(st.NoInitialMask):
        run(eng, 3)
    assert p.enc.n == 1 and not p.memenc.calls  # ikinci kare çözülmedi


def test_missing_memory_graphs_fail_on_the_first_next_with_a_clear_message():
    eng, p = make([], memory=False)
    assert not eng.has_memory
    with pytest.raises(RuntimeError, match="sam-decoder-trk.onnx.*sam-memenc.onnx.*sam-memattn.onnx"):
        next(st.track_video(eng, frames(2), (8, 8, 56, 40)))
    assert p.enc.n == 0


def test_memory_frame_size_mismatch_between_memenc_and_memattn_is_reported():
    eng, _ = make([], memenc=FakeMemEnc(size=7))
    with pytest.raises(RuntimeError, match="bellek karesi 7 sayı"):
        run(eng, 1)


def test_dynamic_memattn_shapes_are_rejected():
    eng, p = make([])
    p.memattn.shapes["mem_feats"] = ("K", 3)
    with pytest.raises(RuntimeError, match="statik değil"):
        eng.memory_layout()


def test_memory_graphs_need_to_be_asked_for_and_present_on_disk(tmp_path):
    for n in (ENC, DEC):
        (tmp_path / f"{n}.onnx").write_bytes(b"x")
    made = []
    SamEngine(tmp_path, "cpu", factory=lambda p, d: (made.append(p.name) or FakeEnc(), [CPU]))  # memory=False: 2 grafik
    assert sorted(made) == ["sam-decoder.onnx", "sam-encoder.onnx"]
    with pytest.raises(FileNotFoundError, match="sam-decoder-trk.onnx"):
        SamEngine(tmp_path, "cpu", memory=True, factory=lambda p, d: (FakeEnc(), [CPU]))


def test_memory_layout_is_read_from_the_memattn_inputs():
    lay = make([])[0].memory_layout()
    assert (lay.k, lay.p, lay.frame_shape, lay.frame_size) == (K, P, (3,), 3)


def test_engine_timing_counts_every_graph_call():
    eng, _ = make([GOOD] * 2)
    run(eng, 3)
    n = {g: int(v[1]) for g, v in eng.timing.items()}
    assert n == {ENC: 3, DEC: 1, MEMENC: 3, MEMATTN: 2, DEC_TRK: 2}
    assert set(st.ms_per_call(eng)) == set(n) and all(v >= 0 for v in st.ms_per_call(eng).values())


# --- kayıt dosyası ---

def _docs(tmp_path, n=4, script=None):
    eng, _ = make(script or [GOOD, (None, 0.9, 3.0), GOOD])
    recs = run(eng, n)
    video = tmp_path / "klip.mp4"
    video.write_bytes(b"v")
    doc = st.make_doc(video, recs, size=(64, 48), sample_fps=10.0, start=0.0, rect=(0.1, 0.2, 0.8, 0.9),
                      providers=eng.providers(), layout=eng.memory_layout(), timing_ms=st.ms_per_call(eng))
    return video, recs, doc


def test_sam_path_sits_next_to_the_video_like_track_and_views(tmp_path):
    assert st.sam_path(tmp_path / "x.mp4").name == "x.mp4.sam.json"
    assert st.sam_path("a/b/ö ğ.mkv").name == "ö ğ.mkv.sam.json"


def test_document_round_trip_keeps_rows_counts_and_signature(tmp_path):
    video, recs, doc = _docs(tmp_path)
    assert doc["kind"] == "sam-track" and doc["version"] == 2 and doc["complete"] is True
    assert doc["counts"] == {"frames": 4, "tracked": 3, "lost": 1}
    assert doc["vsig"] == cache.file_sig(video) and doc["layout"] == {"k": K, "p": P, "frame_shape": [3]}
    assert doc["fields"][:3] == ["t", "tracked", "accepted"] and len(doc["records"][0]) == len(doc["fields"])
    path = st.save_doc(st.sam_path(video), doc)
    back = st.doc_records(st.load_doc(path))
    assert [r.state for r in back] == [r.state for r in recs] and back[2].box is None
    assert back[1].box == pytest.approx(recs[1].box, abs=1e-4) and all(r.accepted for r in back)
    assert not list(tmp_path.glob("*.tmp"))  # atomik yazım: geçici dosya kalmaz
    assert [r.clean for r in back] == [True, True, False, True] and back[0].size == pytest.approx((0.25, 0.25), abs=1e-4)
    assert back[2].size is None and back[1].size == pytest.approx((0.25, 0.25), abs=1e-4)
    assert doc["gate"] == {"enabled": True, "rejected": 0, "unclean": 0, "ref": None, "learned": None}


def test_save_does_not_touch_existing_track_or_views_files(tmp_path):
    video, _, doc = _docs(tmp_path)
    track, views = tmp_path / "klip.mp4.track.json", tmp_path / "klip.mp4.views.json"
    track.write_text('{"version": 1}', encoding="utf-8")
    views.write_text('{"version": 1, "views": []}', encoding="utf-8")
    st.save_doc(st.sam_path(video), doc)
    assert track.read_text(encoding="utf-8") == '{"version": 1}'
    assert views.read_text(encoding="utf-8") == '{"version": 1, "views": []}'


def test_load_rejects_other_json_files_and_changed_fields(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"version": 1, "samples": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="SAM kayıt"):
        st.load_doc(p)
    _, _, doc = _docs(tmp_path)
    doc["fields"] = doc["fields"][:-1]
    p.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="alanları"):
        st.load_doc(p)


def test_partial_document_is_marked_incomplete(tmp_path):
    eng, _ = make([GOOD])
    doc = st.make_doc(tmp_path / "yok.mp4", run(eng, 2), size=(64, 48), sample_fps=10.0, complete=False)
    assert doc["complete"] is False and doc["counts"]["frames"] == 2 and doc["rect"] is None


# --- video ---

def _avi(path, n=30):
    cv2 = pytest.importorskip("cv2")
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (64, 48))
    for k in range(n):
        vw.write(np.full((48, 64, 3), k * 8, np.uint8))
    vw.release()
    return path


def test_clip_starts_at_the_given_time_and_stops_after_max_seconds(tmp_path):
    v = _avi(tmp_path / "c.avi")
    ts = [t for t, _ in st.Clip(v, 10.0)]
    assert ts[0] == 0.0 and len(ts) == 30
    c = st.Clip(v, 10.0, start=1.0, max_seconds=0.5)
    ts = [t for t, _ in c]
    assert (c.w, c.h) == (64, 48)
    assert ts[0] == pytest.approx(1.0, abs=1e-6) and ts[-1] == pytest.approx(1.5, abs=1e-6) and len(ts) == 6
    assert [t for t, _ in st.Clip(v, 10.0, start=0.04)][0] == pytest.approx(0.1, abs=1e-6)  # ilk örnek >= start


def test_clip_missing_file_is_a_file_not_found(tmp_path):
    pytest.importorskip("cv2")
    with pytest.raises(FileNotFoundError):
        st.Clip(tmp_path / "yok.avi")


def test_track_video_runs_over_a_real_clip_and_stops_at_max_seconds(tmp_path):
    v = _avi(tmp_path / "c.avi")
    eng, p = make([GOOD] * 40)
    gen = st.track_video(eng, st.Clip(v, 10.0, max_seconds=1.0), (8, 8, 56, 40))
    recs = list(gen)
    assert len(recs) == 11 and recs[-1].t == pytest.approx(1.0, abs=1e-6)  # 0.0 .. 1.0 dahil


# --- CLI ---

def _cli(tmp_path, monkeypatch, script=None, dec=None):
    v = _avi(tmp_path / "klip.avi")
    made = []

    def fake(md, dev, rule="best", memory=False):
        eng, _ = make(script if script is not None else [GOOD] * 40, dec=dec)
        made.append((md, dev, rule, memory))
        return eng

    monkeypatch.setattr(se, "SamEngine", fake)
    return v, made


def test_cli_sam_track_writes_records_next_to_the_video_and_reports_timing(tmp_path, monkeypatch, capsys):
    v, made = _cli(tmp_path, monkeypatch)
    code = main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--max-seconds", "1.0", "--device", "cpu"])
    out = capsys.readouterr().out
    assert code == 0 and made == [(str(tmp_path), "cpu", "best", True)]  # bellek grafikleri istendi
    doc = st.load_doc(st.sam_path(v))
    assert doc["counts"] == {"frames": 11, "tracked": 11, "lost": 0} and doc["complete"] is True
    assert doc["video"]["w"] == 64 and doc["rect"] == [0.125, 0.16667, 0.875, 0.83333]
    for needle in ("kare 11", "izlenen 11", "kare/sn", "sam-encoder:", "sam-memattn:", "tepe VRAM: n/a", "Kayıt:"):
        assert needle in out, needle


def test_cli_sam_track_custom_out_no_save_and_norm(tmp_path, monkeypatch, capsys):
    v, _ = _cli(tmp_path, monkeypatch)
    o = tmp_path / "özel.json"
    assert main(["sam-track", str(tmp_path), str(v), "--rect", "0.1,0.1,0.9,0.9", "--norm", "--max-seconds", "0.3",
                 "--out", str(o)]) == 0 and o.is_file() and not st.sam_path(v).exists()
    assert "Kayıt:" in capsys.readouterr().out
    assert main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--max-seconds", "0.3", "--no-save"]) == 0
    assert not st.sam_path(v).exists() and "Kayıt:" not in capsys.readouterr().out


def test_cli_sam_track_start_offset_skips_the_earlier_frames(tmp_path, monkeypatch):
    v, _ = _cli(tmp_path, monkeypatch)
    assert main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--start", "2.0", "--max-seconds", "0.4"]) == 0
    doc = st.load_doc(st.sam_path(v))
    assert doc["start"] == 2.0 and doc["records"][0][0] == pytest.approx(2.0, abs=1e-4) and len(doc["records"]) == 5


def test_cli_sam_track_reports_no_initial_mask_and_bad_input_with_exit_code_1(tmp_path, monkeypatch, capsys):
    class Empty(FakeDec):
        def run(self, names, feed):
            return [np.stack([logits()] * 3)[None], np.array([[0.1, 0.2, 0.3]], np.float32),
                    np.zeros((1, 3, 256), np.float32), np.array([[-5.0]], np.float32)]

    v, _ = _cli(tmp_path, monkeypatch, dec=Empty())
    assert main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40"]) == 1
    assert "maske bulunamadı" in capsys.readouterr().err and not st.sam_path(v).exists()
    assert main(["sam-track", str(tmp_path), str(v), "--rect", "1,2,3"]) == 1
    assert "HATA" in capsys.readouterr().err
    assert main(["sam-track", str(tmp_path), str(tmp_path / "yok.avi"), "--rect", "1,2,30,40"]) == 1


def test_cli_sam_track_saves_a_partial_file_on_interrupt(tmp_path, monkeypatch, capsys):
    v, _ = _cli(tmp_path, monkeypatch)
    real = st.track_video

    def boom(*a, **k):
        for i, rec in enumerate(real(*a, **k)):
            if i == 3:
                raise KeyboardInterrupt
            yield rec

    monkeypatch.setattr(st, "track_video", boom)
    assert main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40"]) == 130
    doc = st.load_doc(st.sam_path(v))
    assert doc["complete"] is False and doc["counts"]["frames"] == 3
    assert "Durduruldu" in capsys.readouterr().err


# --- sözleşme / belgeler ---

def test_graph_tensor_names_used_by_the_loop_match_the_export_script_and_kotlin():
    export = (ROOT / "scripts/export_sam2.py").read_text(encoding="utf-8")
    kotlin = (ROOT / "android/app/src/sam/kotlin/com/takipli/oynat/SamEngine.kt").read_text(encoding="utf-8")
    for n in ("image_feat", "low_res_mask", "object_score", "mem_feat", "mem_feats", "ptrs", "image_embed"):
        assert n in export and f'"{n}"' in kotlin, n
    assert (st.MIN_CONF, st.RATIO_LO, st.RATIO_HI) == (0.35, 0.25, 4.0)
    assert "MIN_CONF = 0.35" in kotlin and "ratio in 0.25..4.0" in kotlin and "0.8 * area + 0.2 * cd.area" in kotlin
    assert re.search(r"d\.score > 0f && cd\.area > 0 && conf >= MIN_CONF", kotlin)


def test_docs_name_the_new_command_and_the_decisions():
    d = (ROOT / "docs/DECISIONS.md").read_text(encoding="utf-8")
    assert "sam-track" in d and "SAM memory loop" in d
    assert ".sam.json" in (ROOT / "handover.md").read_text(encoding="utf-8")


# --- S5: TrackGate ---

OTHER = np.where(np.arange(256) % 2 == 0, 1.0, -1.0)  # ilk karedeki sabit işaretçiyle kosinüs tam 0
DESK = ((150, 150, 250, 250), 0.9, 3.0, OTHER)  # uzakta, özneye benzemeyen işaretçi; alan oranı ~2.5 (makul), güven yüksek
HALF = ((64, 32, 103, 71), 0.9, 3.0)  # GOOD'un 40x40'ı: oran 0.39 -> izlenir ama temiz değil


def test_mask_jumping_onto_a_desk_is_rejected_and_never_enters_memory():
    eng, p = make([GOOD, GOOD, GOOD, DESK, GOOD, GOOD])
    stats = st.TrackStats()
    recs = run(eng, 7, stats=stats)
    assert [r.state for r in recs] == ["tracked"] * 4 + ["lost", "tracked", "tracked"]
    assert recs[4].accepted is False and recs[4].box is not None and not recs[4].clean and recs[4].size is None
    assert all(r.accepted for i, r in enumerate(recs) if i != 4)
    assert (stats.rejected, stats.lost, stats.unclean) == (1, 1, 0)
    assert len(p.memenc.calls) == 1 + 3 + 2  # masa kareden bellek yazılmadı
    mem = [c["mem"].tolist() for c in p.memattn.calls]
    assert mem[3] == mem[4] == [0, 3, 2, 1]  # masa karesi (4) ve sonrası: geçmiş hâlâ 1,2,3
    assert mem[5] == [0, 5, 3, 2]  # kare 4 hiçbir yuvada yok
    assert p.memattn.calls[4]["ptr"][1:4].tolist() == [103.0, 102.0, 101.0]


def test_without_the_gate_the_desk_frame_is_remembered_like_in_s4():
    eng, p = make([GOOD, GOOD, GOOD, DESK, GOOD, GOOD])
    recs = run(eng, 7, use_gate=False)
    assert all(r.tracked and r.accepted and r.clean for r in recs)
    assert p.memattn.calls[5]["mem"].tolist() == [0, 5, 4, 3]  # masa karesi belleğe girdi


def test_everything_passes_until_three_clean_frames_were_learned():
    recs = run(make([GOOD, DESK])[0], 3)  # yalnız 1 temiz kare öğrenildi
    assert recs[2].tracked and recs[2].accepted


def test_lookalike_after_a_loss_is_rejected_but_the_subject_resumes():
    eng, p = make([GOOD, GOOD, GOOD, (None, 0.9, 3.0), DESK, GOOD])
    recs = run(eng, 7)
    assert [r.state for r in recs] == ["tracked"] * 4 + ["lost", "lost", "tracked"]
    assert [r.accepted for r in recs] == [True] * 5 + [False, True]  # 4: boş maske (kapı görmedi), 5: kapı reddi
    assert len(p.memenc.calls) == 1 + 3 + 1


def test_half_covered_frame_is_tracked_but_not_remembered_and_keeps_the_clean_size():
    eng, p = make([GOOD, HALF, GOOD])
    stats = st.TrackStats()
    recs = run(eng, 4, stats=stats)
    assert recs[0].clean and recs[0].size == (0.25, 0.25)
    half = recs[2]
    assert half.tracked and half.accepted and not half.clean
    assert half.box == pytest.approx((0.25, 0.125, 0.40625, 0.28125))  # ham kutu küçük
    assert half.size == pytest.approx((0.25, 0.25))  # kamera boyutu son temiz boyutta kalır (zoom pompalanmaz)
    assert len(p.memenc.calls) == 1 + 2 and stats.unclean == 1 and stats.lost == 0
    assert p.memattn.calls[2]["mem"].tolist() == [0, 1, 0, 0]  # örtülü kare (2) bellekte yok
    assert recs[3].ratio == pytest.approx(1.0)  # referans alan örtülü kareyle küçülmedi


def test_frames_that_never_become_clean_are_forced_into_memory_so_it_never_deadlocks():
    n = tg.FORCE_CLEAN_FRAMES
    eng, p = make([HALF] * (n + 2))
    recs = run(eng, n + 3)
    assert [r.clean for r in recs[1:]] == [False] * n + [True, False]
    assert len(p.memenc.calls) == 1 + 1  # yalnız ilk kare ve zorlanan kare


def test_a_clean_frame_after_a_covered_one_does_not_count_as_a_learning_frame():
    eng, _ = make([GOOD, HALF, GOOD, GOOD, GOOD, DESK])
    gate = tg.TrackGate()
    recs = run(eng, 7, gate=gate)
    assert gate.learned == 3  # kare 1, 4, 5; kare 3 örtülü kareden hemen sonra geldiği için öğretmez
    assert recs[6].state == "lost" and recs[6].accepted is False  # 3 temiz kare tamam: masa artık reddedilir


def test_gate_counters_are_exposed_to_the_caller():
    gate = tg.TrackGate()
    eng, _ = make([GOOD, GOOD, GOOD, DESK, GOOD])
    run(eng, 6, gate=gate)
    assert (gate.accepted, gate.rejected, gate.learned) == (4, 1, 3) and gate.ref == pytest.approx(1.0)
    assert "4 kabul, 1 ret" in gate.summary()


def test_cli_sam_track_prints_the_gate_summary_and_no_gate_turns_it_off(tmp_path, monkeypatch, capsys):
    v, _ = _cli(tmp_path, monkeypatch)
    base = ["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--max-seconds", "0.5", "--device", "cpu"]
    assert main(base) == 0
    assert "kapı: 5 kabul, 0 ret" in capsys.readouterr().out
    assert st.load_doc(st.sam_path(v))["gate"]["enabled"] is True
    assert main(base + ["--no-gate"]) == 0
    assert "kapı: kapalı" in capsys.readouterr().out
    assert st.load_doc(st.sam_path(v))["gate"]["enabled"] is False
