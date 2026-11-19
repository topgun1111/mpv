"""S3: PC SAM motoru (tracker/sam_engine.py), yalnız ilk kare. Model dosyası/GPU gerekmez: sahte oturumlar."""
import re
from pathlib import Path

import numpy as np
import pytest

from tracker import sam_engine as se
from tracker.main import main
from tracker.sam_bench import GRAPHS
from tracker.sam_engine import (
    DEC,
    DEC_OUT,
    ENC,
    ENC_OUT,
    M,
    S,
    SamEngine,
    analyse,
    box_prompt,
    clamp_rect,
    parse_rect,
    pick_candidate,
    preprocess,
    to_frame_box,
    to_norm_box,
)

ROOT = Path(__file__).resolve().parents[1]
CPU, DML = "CPUExecutionProvider", "DmlExecutionProvider"


def logits(*regions):
    """(M, M) logit: her bölge (x1, y1, x2, y2; son piksel DAHİL) +5, kalanı -10."""
    a = np.full((M, M), -10.0, np.float32)
    for x1, y1, x2, y2 in regions:
        a[y1:y2 + 1, x1:x2 + 1] = 5.0
    return a


class FakeEnc:
    def __init__(self, providers=(CPU,)):
        self.calls, self._p = [], list(providers)

    def get_providers(self):
        return self._p

    def run(self, names, feed):
        self.calls.append((list(names), feed))
        return [np.full((1, 2, 4, 4), 1, np.float32), np.full((1, 3, 2, 2), 2, np.float32),
                np.full((1, 4, 2, 2), 3, np.float32), np.full((1, 4, 2, 2), 4, np.float32)]


class FakeDec:
    def __init__(self, masks, iou=(0.5, 0.9, 0.7), score=3.0, providers=(CPU,)):
        self.masks, self.iou, self.score = masks, iou, score
        self.calls, self._p = [], list(providers)

    def get_providers(self):
        return self._p

    def run(self, names, feed):
        self.calls.append((list(names), feed))
        ptrs = np.stack([np.full(256, k + 1, np.float32) for k in range(len(self.iou))])[None]
        return [np.stack(self.masks)[None].astype(np.float32), np.array([self.iou], np.float32), ptrs,
                np.array([[self.score]], np.float32)]


def _masks():
    return [logits((10, 10, 20, 20)), logits((64, 32, 127, 95)), logits((0, 0, 255, 255))]


def _engine(dec=None, enc=None, rule="best"):
    enc, dec = enc or FakeEnc(), dec or FakeDec(_masks())
    return SamEngine(sessions={ENC: enc, DEC: dec}, rule=rule), enc, dec


def _frame(w=640, h=480):
    return np.zeros((h, w, 3), np.uint8)


# --- sözleşme ---

def test_graph_names_and_tensor_names_match_the_export_script_and_kotlin():
    export = (ROOT / "scripts/export_sam2.py").read_text(encoding="utf-8")
    kotlin = (ROOT / "android/app/src/sam/kotlin/com/takipli/oynat/SamEngine.kt").read_text(encoding="utf-8")
    assert ENC in GRAPHS and DEC in GRAPHS
    for n in ENC_OUT + DEC_OUT + ("image", "image_embed", "point_coords", "point_labels"):
        assert n in export, n
        assert f'"{n}"' in kotlin, n


def test_prompt_labels_and_constants_match_the_kotlin_engine():
    kotlin = (ROOT / "android/app/src/sam/kotlin/com/takipli/oynat/SamEngine.kt").read_text(encoding="utf-8")
    assert "l[0] = 2f" in kotlin and "l[1] = 3f" in kotlin and "l[2] = 1f" in kotlin  # köşe, köşe, nokta
    assert "private const val S = 1024" in kotlin and "private const val M = 256" in kotlin
    assert (S, M) == (1024, 256)
    for v in ("0.485f, 0.456f, 0.406f", "0.229f, 0.224f, 0.225f"):
        assert v in kotlin
    assert se.MEAN == (0.485, 0.456, 0.406) and se.STD == (0.229, 0.224, 0.225)


# --- ön işleme ---

def test_preprocess_shape_dtype_and_rgb_normalisation():
    f = np.zeros((480, 640, 3), np.uint8)
    f[:, :, 0], f[:, :, 1], f[:, :, 2] = 0, 255, 51  # BGR: mavi 0, yeşil 255, kırmızı 51
    x = preprocess(f)
    assert x.shape == (1, 3, S, S) and x.dtype == np.float32 and x.flags["C_CONTIGUOUS"]
    # kanal 0 = KIRMIZI (51/255), 1 = yeşil (1.0), 2 = mavi (0)
    for c, v in enumerate((51 / 255, 1.0, 0.0)):
        want = (v - se.MEAN[c]) / se.STD[c]
        assert abs(float(x[0, c, 500, 500]) - want) < 1e-5


def test_preprocess_squashes_without_letterbox():
    f = np.zeros((100, 400, 3), np.uint8)
    f[:, 200:] = 255  # sağ yarı beyaz
    x = preprocess(f)
    assert x[0, 0, 10, 100] < 0 < x[0, 0, 10, 900]  # sol yarı siyah, sağ yarı beyaz: üstte/altta dolgu yok
    assert x[0, 0, 0, 900] > 0 and x[0, 0, S - 1, 900] > 0


def test_preprocess_rejects_gray_frames():
    with pytest.raises(ValueError):
        preprocess(np.zeros((10, 10), np.uint8))


# --- istem ---

def test_box_prompt_encodes_corners_then_centre_point_in_1024_space():
    coords, labels = box_prompt((512, 256, 1024, 768), w=2048, h=1024)
    assert coords.shape == (1, 3, 2) and labels.shape == (1, 3)
    assert coords.dtype == labels.dtype == np.float32
    np.testing.assert_allclose(coords[0], [[256, 256], [512, 768], [384, 512]])
    assert labels.tolist() == [[2.0, 3.0, 1.0]]


def test_clamp_rect_sorts_clips_and_rejects_tiny_rects():
    assert clamp_rect((300, 200, -50, 900), w=640, h=480) == (0.0, 200.0, 300.0, 480.0)
    for bad in ((10, 10, 11, 200), (700, 10, 900, 200), (0, 0, float("nan"), 5)):
        with pytest.raises(ValueError):
            clamp_rect(bad, w=640, h=480)


def test_parse_rect_pixels_normalised_and_errors():
    assert parse_rect("10, 20,110,220", 640, 480) == (10.0, 20.0, 110.0, 220.0)
    assert parse_rect("0.25,0.5,0.5,1", 640, 480, normalized=True) == (160.0, 240.0, 320.0, 480.0)
    for bad in ("1,2,3", "a,b,c,d"):
        with pytest.raises(ValueError):
            parse_rect(bad, 640, 480)


# --- adaylar ---

def test_analyse_box_centroid_area_and_empty_mask():
    c = analyse(logits((64, 32, 127, 95)), 1, 0.9)
    assert c.box == (0.25, 0.125, 0.5, 0.375)
    assert c.area == 64 * 64 / (M * M) and c.iou == pytest.approx(0.9)
    assert c.centroid == (pytest.approx(95.5 / M), pytest.approx(63.5 / M))  # Kotlin: sx / n / M (+0.5 yok)
    e = analyse(logits(), 0, 0.4)
    assert e.area == 0.0 and e.box is None and e.centroid is None


def test_pick_candidate_best_smallest_and_empty():
    cs = [analyse(m, k, i) for k, (m, i) in enumerate(zip(_masks(), (0.5, 0.9, 0.95)))]
    assert pick_candidate(cs, "best") == 2
    assert pick_candidate(cs, "smallest") == 1  # 0.95 * 0.85 = 0.81: #0 (0.5) elenir, #1 (0.9) en küçük kalan
    assert pick_candidate([analyse(logits(), 0, 0.9)]) == -1
    assert pick_candidate([]) == -1
    with pytest.raises(ValueError):
        pick_candidate(cs, "nope")


def test_empty_candidates_are_never_picked_even_with_top_iou():
    cs = [analyse(logits(), 0, 0.99), analyse(logits((5, 5, 9, 9)), 1, 0.2)]
    assert pick_candidate(cs, "best") == 1 and pick_candidate(cs, "smallest") == 1


# --- koordinatlar ---

def test_mask_box_maps_to_frame_pixels_and_round_trips():
    # maske (64..127, 32..95) -> normalize (0.25, 0.125, 0.5, 0.375) -> 1280x720 karede
    eng, _, _ = _engine()
    res = eng.first_mask(_frame(1280, 720), (100, 100, 900, 600))
    assert res.box_norm == (0.25, 0.125, 0.5, 0.375)
    assert res.box == (320.0, 90.0, 640.0, 270.0)
    assert to_norm_box(res.box, 1280, 720) == res.box_norm
    assert to_frame_box(to_norm_box((13.0, 7.0, 913.0, 451.0), 1280, 720), 1280, 720) == pytest.approx((13.0, 7.0, 913.0, 451.0))


def test_upscale_mask_has_frame_size_and_keeps_the_region():
    m = se.upscale_mask(logits((64, 32, 127, 95)), 1280, 720)
    assert m.shape == (720, 1280) and m.dtype == bool
    assert m[180, 480] and not m[600, 1200] and not m[10, 10]


# --- motor ---

def test_first_mask_runs_encoder_then_decoder_with_the_contract_names():
    eng, enc, dec = _engine()
    eng.first_mask(_frame(), (100, 100, 400, 300))
    (en, ef), (dn, df) = enc.calls[0], dec.calls[0]
    assert en == list(ENC_OUT) and set(ef) == {"image"} and ef["image"].shape == (1, 3, S, S)
    assert dn == list(DEC_OUT)
    assert set(df) == {"image_embed", "high_res_feats_0", "high_res_feats_1", "point_coords", "point_labels"}
    assert (df["image_embed"] == 3).all() and (df["high_res_feats_0"] == 1).all() and (df["high_res_feats_1"] == 2).all()
    assert df["point_coords"].shape == (1, 3, 2) and df["point_labels"].tolist() == [[2.0, 3.0, 1.0]]
    np.testing.assert_allclose(df["point_coords"][0, 0], [100 * S / 640, 100 * S / 480])
    assert len(enc.calls) == len(dec.calls) == 1


def test_first_mask_returns_best_candidate_and_its_scores():
    eng, _, _ = _engine()
    res = eng.first_mask(_frame(), (100, 100, 400, 300))
    assert res.index == 1 and res.iou == pytest.approx(0.9) and res.object_score == pytest.approx(3.0)
    assert res.mask.shape == res.mask_logits.shape == (M, M) and res.mask.sum() == 64 * 64
    assert (res.obj_ptr == 2).all() and res.obj_ptr.shape == (256,)  # 2. adayın işaretçisi
    assert (res.image_feat == 4).all() and res.size == (640, 480) and len(res.candidates) == 3
    assert res.rect == (100.0, 100.0, 400.0, 300.0) and 0.95 < res.object_prob < 0.96  # sigmoid(3)


def test_smallest_rule_is_available_on_the_engine():
    eng, _, _ = _engine(FakeDec(_masks(), iou=(0.88, 0.9, 0.92)), rule="smallest")
    assert eng.first_mask(_frame(), (10, 10, 200, 200)).index == 0  # hepsi >= 0.85*0.92; en küçük alan #0
    with pytest.raises(ValueError):
        SamEngine(sessions={ENC: FakeEnc(), DEC: FakeDec(_masks())}, rule="x")


def test_one_encoding_serves_several_rectangles():
    eng, enc, dec = _engine()
    e = eng.encode(_frame())
    a = eng.segment_rect(e, (10, 10, 200, 200))
    b = eng.segment_rect(e, (50, 50, 300, 300))
    assert len(enc.calls) == 1 and len(dec.calls) == 2 and a and b
    assert not np.array_equal(dec.calls[0][1]["point_coords"], dec.calls[1][1]["point_coords"])


def test_rect_is_clipped_to_the_frame_before_prompting():
    eng, _, dec = _engine()
    res = eng.first_mask(_frame(), (-100, -100, 5000, 5000))
    assert res.rect == (0.0, 0.0, 640.0, 480.0)
    assert dec.calls[0][1]["point_coords"].max() <= S


def test_returns_none_when_no_candidate_has_a_mask():
    eng, _, _ = _engine(FakeDec([logits(), logits(), logits()]))
    assert eng.first_mask(_frame(), (10, 10, 100, 100)) is None


def test_unexpected_decoder_shapes_raise_clear_errors():
    bad = FakeDec([np.zeros((64, 64), np.float32)] * 3)
    eng, _, _ = _engine(bad)
    with pytest.raises(RuntimeError, match="maske boyutu"):
        eng.first_mask(_frame(), (10, 10, 100, 100))

    class Short(FakeDec):
        def run(self, names, feed):
            return super().run(names, feed)[:3]
    eng, _, _ = _engine(Short(_masks()))
    with pytest.raises(RuntimeError, match="çıktı beklenirdi"):
        eng.first_mask(_frame(), (10, 10, 100, 100))


def test_tiny_rect_is_rejected_before_any_graph_runs():
    eng, enc, dec = _engine()
    with pytest.raises(ValueError):
        eng.segment_rect(eng.encode(_frame()), (10, 10, 11, 11))
    assert not dec.calls


# --- yükleme ---

def test_missing_directory_and_graph_files_are_named(tmp_path):
    with pytest.raises(FileNotFoundError, match="model klasörü yok"):
        SamEngine(tmp_path / "yok")
    (tmp_path / "sam-encoder.onnx").write_bytes(b"x")
    with pytest.raises(FileNotFoundError, match="sam-decoder.onnx"):
        SamEngine(tmp_path)
    with pytest.raises(ValueError):
        SamEngine()


def test_loads_both_graphs_through_the_factory_and_reports_fallback(tmp_path):
    for n in (ENC, DEC):
        (tmp_path / f"{n}.onnx").write_bytes(b"x")
    seen = []

    def factory(path, device):
        seen.append((path.name, device))
        return (FakeEnc((CPU,)) if path.stem == ENC else FakeDec(_masks(), providers=(DML, CPU))), [DML, CPU]

    eng = SamEngine(tmp_path, "dml", factory=factory)
    assert seen == [("sam-encoder.onnx", "dml"), ("sam-decoder.onnx", "dml")]
    p = eng.providers()
    assert p[ENC] == {"provider": CPU, "fell_back": True}  # DML istendi, CPU'da açıldı: gizli düşüş görünür
    assert p[DEC] == {"provider": DML, "fell_back": False}


# --- görüntü yardımcıları ve CLI ---

def test_overlay_draws_the_contour_without_touching_the_input_and_png_round_trips_unicode(tmp_path):
    eng, _, _ = _engine()
    frame = _frame(640, 480)
    res = eng.first_mask(frame, (100, 100, 400, 300))
    out = se.draw_overlay(frame, res)
    assert frame.sum() == 0 and out.shape == frame.shape  # girdi değişmez
    green = (out[:, :, 1] == 255) & (out[:, :, 0] == 0) & (out[:, :, 2] == 0)
    ys, xs = np.nonzero(green)
    assert green.any() and 150 <= xs.min() <= 170 and 90 <= xs.max() <= 330  # x: 160..320 çevresi
    d = tmp_path / "çalışma klasörü"
    d.mkdir()
    se.save_png(d / "maske.png", out)
    assert np.array_equal(se.read_image(d / "maske.png"), out)
    with pytest.raises(FileNotFoundError):
        se.read_image(d / "yok.png")
    (d / "bozuk.png").write_bytes(b"degil")
    with pytest.raises(ValueError):
        se.read_image(d / "bozuk.png")


def test_format_result_lists_providers_candidates_and_box():
    eng, _, _ = _engine()
    res = eng.first_mask(_frame(1280, 720), (100, 100, 900, 600))
    txt = se.format_result(res, {ENC: {"provider": DML, "fell_back": False}, DEC: {"provider": CPU, "fell_back": True}},
                           {ENC: 12.34, DEC: 1.5})
    assert "sam-encoder: DmlExecutionProvider · 12.3 ms" in txt and "FELL BACK" in txt
    assert "#1 iou 0.900" in txt and "(seçildi)" in txt and "320,90,640,270" in txt


def _cli_setup(tmp_path, monkeypatch, dec=None):
    img = tmp_path / "kare.png"
    se.save_png(img, np.full((480, 640, 3), 80, np.uint8))
    real = SamEngine
    monkeypatch.setattr(se, "SamEngine", lambda md, dev, rule="best": real(
        sessions={ENC: FakeEnc(), DEC: dec or FakeDec(_masks())}, rule=rule))
    return img


def test_cli_sam_first_writes_the_outline_png(tmp_path, monkeypatch, capsys):
    img = _cli_setup(tmp_path, monkeypatch)
    out = tmp_path / "çıktı.png"
    code = main(["sam-first", str(tmp_path), str(img), "--rect", "100,100,400,300", "--out", str(out)])
    text = capsys.readouterr().out
    assert code == 0 and out.is_file() and "Kontur PNG" in text and "(seçildi)" in text
    assert se.read_image(out).shape == (480, 640, 3)
    code = main(["sam-first", str(tmp_path), str(img), "--rect", "0.1,0.1,0.6,0.6", "--norm"])
    assert code == 0 and (tmp_path / "kare_maske.png").is_file()  # varsayılan çıktı yolu


def test_cli_sam_first_reports_no_mask_and_bad_input_with_exit_code_1(tmp_path, monkeypatch, capsys):
    img = _cli_setup(tmp_path, monkeypatch, FakeDec([logits(), logits(), logits()]))
    assert main(["sam-first", str(tmp_path), str(img), "--rect", "10,10,200,200"]) == 1
    assert "Maske bulunamadı" in capsys.readouterr().err
    assert main(["sam-first", str(tmp_path), str(img), "--rect", "1,2,3"]) == 1
    assert "HATA" in capsys.readouterr().err
    assert main(["sam-first", str(tmp_path), str(tmp_path / "yok.png"), "--rect", "1,2,30,40"]) == 1
    assert "görüntü yok" in capsys.readouterr().err


def test_docs_name_the_new_command():
    d = (ROOT / "docs/DECISIONS.md").read_text(encoding="utf-8")
    assert "sam-first" in d and re.search(r"SAM engine", d)
