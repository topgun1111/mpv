"""Kayıt varyantı (Parça R1): geometri, anahtar kareler, dosya, dışa aktarma, CLI, paketleme."""
import ast
import importlib.util
import json
import math
from pathlib import Path

import cv2
import numpy as np
import pytest

import recorder.export as rex
from recorder import geometry as g
from recorder import keys as k
from recorder.main import main

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _frame_point(v, ax, ay):
    """İmlecin (ax, ay) altındaki kare noktası (görünüm v)."""
    s = 2.0 ** v[0]
    return (0.5 - v[1]) + (ax - 0.5) / s, (0.5 - v[2]) + (ay - 0.5) / s


# ---- geometri ----

def test_clamp_view_limits_zoom_and_pan():
    assert g.clamp_view((-1, 0.3, 0.3)) == (0.0, 0.0, 0.0)  # 1× altı yok, pan sıfır
    z, px, py = g.clamp_view((9, 5, -5))
    assert z == g.MAX_ZOOM and px == pytest.approx(0.5 - 0.5 / 16) and py == pytest.approx(-px)


def test_zoom_and_drag_happen_at_the_same_time():
    """Zoom + sürükleme tek adımda: imlecin altındaki nokta imleçle birlikte kayar."""
    v = (1.0, 0.1, -0.05)
    ax, ay, dx, dy = 0.6, 0.4, 0.05, -0.03
    nv = g.apply_gesture_at(v, ax, ay, dx, dy, 1.5)
    assert nv[0] == pytest.approx(1.0 + math.log2(1.5))
    before = _frame_point(v, ax, ay)
    after = _frame_point(nv, ax + dx, ay + dy)
    assert after == pytest.approx(before, abs=1e-9)


def test_zoom_is_anchored_at_cursor_not_center():
    v = (0.0, 0.0, 0.0)
    nv = g.apply_gesture_at(v, 0.8, 0.5, 0.0, 0.0, 2.0)
    assert _frame_point(nv, 0.8, 0.5) == pytest.approx(_frame_point(v, 0.8, 0.5))
    assert nv[1] < 0  # sağdaki nokta tutuldu → görünüm sağa kaydı (pan negatif)
    assert g.apply_gesture_at(v, 0.5, 0.5, 0, 0, 2.0) == (1.0, 0.0, 0.0)  # merkez: pan yok


def test_zoom_factor_zero_or_negative_keeps_zoom_and_pure_drag_pans():
    v = (2.0, 0.0, 0.0)
    assert g.apply_gesture_at(v, 0.5, 0.5, 0, 0, 0.0)[0] == 2.0
    nv = g.apply_gesture_at(v, 0.5, 0.5, 0.1, 0.0, 1.0)  # içerik sağa sürüklendi
    assert nv[0] == 2.0 and nv[1] == pytest.approx(0.1 / 4)
    assert g.apply_gesture_at(v, 0.5, 0.5, 5.0, 0.0, 1.0)[1] == pytest.approx(0.5 - 0.5 / 4)


def test_set_zoom_at_sets_level_without_panning_anchor():
    v = (1.0, 0.1, 0.0)
    nv = g.set_zoom_at(v, 0.3, 0.7, 3.0)
    assert nv[0] == 3.0
    assert _frame_point(nv, 0.3, 0.7) == pytest.approx(_frame_point(v, 0.3, 0.7), abs=1e-9)
    assert g.set_zoom_at(v, 0.5, 0.5, 99)[0] == g.MAX_ZOOM
    assert g.set_zoom_at(v, 0.5, 0.5, -3)[0] == 0.0


def test_parity_with_main_variant_export_and_view_at():
    """Ana varyantın `tracker.export` / `tracker.offline` formülleriyle birebir aynı."""
    from tracker.export import crop_rect as main_crop
    from tracker.offline import view_at as main_view_at

    rng = np.random.default_rng(1)
    for _ in range(200):
        v = (float(rng.uniform(-1, 4.5)), float(rng.uniform(-0.6, 0.6)),
             float(rng.uniform(-0.6, 0.6)))
        assert g.crop_rect(v, 1280, 720) == main_crop(v, 1280, 720)
    views = [[0.0, 0.0, 0.0, 0.0], [1.0, 2.0, 0.1, -0.1], [3.0, 1.0, 0.2, 0.0]]
    for t in (-1, 0, 0.5, 1, 2.2, 3, 9):
        assert g.view_at(views, t) == pytest.approx(main_view_at(views, t))
    assert g.view_at([], 1.0) == (0.0, 0.0, 0.0)


def test_android_parity_apply_gesture_at_reference_values():
    """Kotlin `applyGestureAt` ile elle hesaplanmış referans (z=0→1, imleç (0.75, 0.25))."""
    nv = g.apply_gesture_at((0.0, 0.0, 0.0), 0.75, 0.25, 0.0, 0.0, 2.0)
    assert nv == pytest.approx((1.0, -0.125, 0.125))


# ---- hız / anahtar kareler ----

def test_speed_clamp_and_key_dt():
    assert k.clamp_speed(float("nan")) == 1.0
    assert k.clamp_speed(0.01) == 0.25 and k.clamp_speed(9) == 2.0
    assert k.clamp_speed(0.8 + 1e-12) == 0.8 and k.clamp_speed(0.52) == 0.5
    assert all(k.clamp_speed(p) == p for p in k.SPEED_PRESETS)
    assert k.key_dt(1.0) == pytest.approx(0.033)
    assert k.key_dt(0.25) == 0.012 and k.key_dt(2.0) == pytest.approx(0.066)


def test_append_key_skips_rewind_and_pause():
    ks = k.append_key([], 1.0, (1.0, 0.1, 0.2))
    assert ks == [[1.0, 1.0, 0.1, 0.2]]
    assert k.append_key(ks, 1.01, (2, 0, 0)) is ks  # çok yakın
    assert k.append_key(ks, 0.5, (2, 0, 0)) is ks  # geri sarma
    assert len(k.append_key(ks, 1.05, (2, 0, 0))) == 2
    assert len(k.append_key(ks, 1.01, (2, 0, 0), min_dt=0.005)) == 2


def test_normalize_keys_sorts_dedups_and_pads_single():
    out = k.normalize_keys([[2, 1, 0, 0], [1, 0, 0, 0], [2, 3, 0, 0]])
    assert out == [[1, 0, 0, 0], [2, 3, 0, 0]]
    one = k.normalize_keys([[5, 2, 0.1, 0.1]])
    assert len(one) == 2 and one[1] == [5.04, 2, 0.1, 0.1]
    assert k.normalize_keys([]) == []


def test_recording_roundtrip_signature_and_validation(tmp_path):
    vid = tmp_path / "a.mp4"
    vid.write_bytes(b"x" * 10)
    rp = tmp_path / k.rec_path("a.mp4")
    k.save_recording(rp, str(vid), [[0, 0, 0, 0], [1, 1, 0.1, 0.0]], rotate=90, speed=0.5)
    d = k.load_recording(rp, video=str(vid))
    assert d["rotate"] == 90 and d["speed"] == 0.5 and d["kind"] == "manual-camera"
    assert not list(tmp_path.glob("*.tmp"))
    vid.write_bytes(b"y" * 11)  # video değişti → imza uyuşmaz
    with pytest.raises(ValueError, match="başka bir video"):
        k.load_recording(rp, video=str(vid))
    assert k.load_recording(rp)["views"]  # video verilmezse denetim yok
    with pytest.raises(ValueError):
        k.save_recording(rp, str(vid), [])
    with pytest.raises(ValueError):
        k.save_recording(rp, str(vid), [[0, 0, 0, 0]], rotate=45)
    rp.write_text(json.dumps({"version": 1, "views": [[0, 1, 2]]}))
    with pytest.raises(ValueError, match="bozuk"):
        k.load_recording(rp)
    rp.write_text(json.dumps({"version": 9, "views": []}))
    with pytest.raises(ValueError, match="sürüm"):
        k.load_recording(rp)
    rp.write_text(json.dumps({"version": 1, "views": []}))
    with pytest.raises(ValueError, match="anahtar karesi yok"):
        k.load_recording(rp)


def test_signature_matches_main_variant_cache(tmp_path):
    from tracker.cache import file_sig

    v = tmp_path / "v.mp4"
    v.write_bytes(b"abc")
    assert k.file_sig(v) == file_sig(v)


# ---- dışa aktarma ----

def _make_clip(path, n=30, w=320, h=180, fps=10.0):
    wr = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    assert wr.isOpened()
    for i in range(n):
        f = np.zeros((h, w, 3), np.uint8)
        f[:, : w // 2] = (0, 0, 255)  # sol yarı kırmızı (BGR), sağ yarı siyah
        cv2.putText(f, str(i), (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        wr.write(f)
    wr.release()


def test_ffmpeg_cmd_matches_main_variant():
    from tracker.export import ffmpeg_cmd as main_cmd

    assert rex.ffmpeg_cmd("ff", (1280, 720), 29.97, "i.mp4", "o.mp4") == \
        main_cmd("ff", (1280, 720), 29.97, "i.mp4", "o.mp4")
    assert rex.ffmpeg_cmd("ff", (640, 360), 25.0, "i", "o", audio=False, crf=23) == \
        main_cmd("ff", (640, 360), 25.0, "i", "o", audio=False, crf=23)


def test_out_size_even_and_rotation_swaps():
    assert rex.out_size(321, 181) == (320, 180)
    assert rex.out_size(320, 180, 90) == (180, 320) and rex.out_size(320, 180, 180) == (320, 180)


def test_rotate_frame_matches_mpv_clockwise():
    f = np.zeros((2, 4, 3), np.uint8)
    f[0, 0] = 255  # sol üst
    r = rex.rotate_frame(cv2, f, 90)  # saat yönü: sol üst → sağ üst
    assert r.shape[:2] == (4, 2) and r[0, 1].min() == 255
    assert rex.rotate_frame(cv2, f, 0) is f
    assert rex.rotate_frame(cv2, f, 180)[1, 3].min() == 255


def test_export_applies_manual_camera_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(rex, "find_ffmpeg", lambda explicit=None: None)  # cv2 yedeği
    vid, out = tmp_path / "c.mp4", tmp_path / "o.mp4"
    _make_clip(vid)
    # 2× zoom, görünüm sağ üste kaydırılmış → yalnız siyah bölge; sol yarı görünmez
    z = 1.0
    views = [[0.0, z, -0.25, 0.0], [10.0, z, -0.25, 0.0]]
    r = rex.export_video(str(vid), views, str(out))
    assert r["frames"] == 30 and r["size"] == (320, 180) and r["audio"] is False
    assert not list(tmp_path.glob("*.partial*"))
    st = json.loads((tmp_path / "o.mp4.export.json").read_text())
    assert st["state"] == "done"
    cap = cv2.VideoCapture(str(out))
    ok, img = cap.read()
    cap.release()
    assert ok and img.shape[:2] == (180, 320) and img[:, :, 2].mean() < 40  # kırmızı yok
    # aynı klip, sol tarafa bakan kamera → kırmızı baskın
    left = [[0.0, z, 0.25, 0.0], [10.0, z, 0.25, 0.0]]
    rex.export_video(str(vid), left, str(out))
    cap = cv2.VideoCapture(str(out))
    ok, img = cap.read()
    cap.release()
    assert ok and img[:, :, 2].mean() > 200


def test_export_rotation_swaps_output_size(tmp_path, monkeypatch):
    monkeypatch.setattr(rex, "find_ffmpeg", lambda explicit=None: None)
    vid, out = tmp_path / "c.mp4", tmp_path / "o.mp4"
    _make_clip(vid, n=5)
    r = rex.export_video(str(vid), [[0, 0, 0, 0], [1, 0, 0, 0]], str(out), rotate=90)
    assert r["size"] == (180, 320)


def test_export_missing_video_and_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(rex, "find_ffmpeg", lambda explicit=None: None)
    with pytest.raises(FileNotFoundError):
        rex.export_video(str(tmp_path / "yok.mp4"), [[0, 0, 0, 0]], str(tmp_path / "o.mp4"))
    vid, out = tmp_path / "c.mp4", tmp_path / "o.mp4"
    _make_clip(vid, n=20)
    (tmp_path / "o.mp4.export.cancel").write_text("")
    # export başında iptal dosyası silinir; ilerleme geri çağrısında oluşturup iptal ettir
    def prog(n, total):
        (tmp_path / "o.mp4.export.cancel").write_text("")
    r = rex.export_video(str(vid), [[0, 0, 0, 0], [1, 0, 0, 0]], str(out), progress=prog)
    assert r.get("cancelled") and not out.exists()
    assert not list(tmp_path.glob("*.partial*"))
    assert json.loads((tmp_path / "o.mp4.export.json").read_text())["state"] == "cancelled"


def test_split_segments_by_breaks_and_backward_time():
    ks = [[0.0, 0, 0, 0], [0.1, 0, 0, 0], [0.5, 1, 0, 0], [0.6, 1, 0, 0], [0.2, 2, 0, 0]]
    assert [len(x) for x in k.split_segments(ks, [2])] == [2, 2, 2]  # 0.6→0.2 otomatik bölünür
    assert [len(x) for x in k.split_segments(ks[:4], [])] == [4]
    one = k.split_segments([[1.0, 0, 0, 0], [0.5, 0, 0, 0], [0.6, 0, 0, 0]], [1])
    assert one[0] == [[1.0, 0, 0, 0], [1.04, 0, 0, 0]]  # tek anahtarlı parça +40 ms


def test_segmented_recording_roundtrip_keeps_order(tmp_path):
    vid = tmp_path / "c.mp4"
    vid.write_bytes(b"x")
    ks = [[0, 0, 0, 0], [1, 1, 0, 0], [0.5, 2, 0, 0], [1, 2, 0, 0]]
    k.save_recording(k.rec_path(vid), str(vid), ks, breaks=[2])
    d = k.load_recording(k.rec_path(vid), video=str(vid))
    assert d["views"] == ks and [len(x) for x in d["segments"]] == [2, 2]  # sıra korunur
    old = tmp_path / "old.rec.json"
    k.save_recording(old, str(vid), [[1, 0, 0, 0], [0, 1, 0, 0]])  # eski biçim: sıralanır, tüm video
    assert k.load_recording(old)["segments"] is None


def _make_gray_clip(path, n=15, w=64, h=36, fps=10.0):
    wr = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    assert wr.isOpened()
    for i in range(n):
        wr.write(np.full((h, w, 3), 16 * i + 8, np.uint8))  # parlaklık = indeks (sıkıştırmaya dayanıklı adım)
    wr.release()


def test_export_segments_repeat_rewound_parts_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr(rex, "find_ffmpeg", lambda explicit=None: None)  # cv2 yedeği
    vid, out = tmp_path / "c.mp4", tmp_path / "o.mp4"
    _make_gray_clip(vid)
    v = [0.0, 0.0, 0.0]
    # 0→0.9 sn, geri 0.5→0.9, geri 0.5→0.7 (fps 10 → kare 0..9, 5..9, 5..7)
    segs = [[[0.0, *v], [0.9, *v]], [[0.5, *v], [0.9, *v]], [[0.5, *v], [0.7, *v]]]
    r = rex.export_video(str(vid), [], str(out), segments=segs)
    assert r["frames"] == 10 + 5 + 3
    cap = cv2.VideoCapture(str(out))
    levels = []
    while True:
        ok, img = cap.read()
        if not ok:
            break
        levels.append(int(img.mean()))
    cap.release()
    idx = [round((x - 8) / 16) for x in levels]
    assert idx == list(range(10)) + list(range(5, 10)) + [5, 6, 7]


def test_export_segments_with_audio_concatenates_in_recorded_order(tmp_path):
    ff = rex.find_ffmpeg()
    if not ff:
        pytest.skip("ffmpeg yok")
    import subprocess

    vid, out = tmp_path / "c.mp4", tmp_path / "o.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=64x36:rate=10:duration=3", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(vid)], check=True)
    v = [0.0, 0.0, 0.0]
    segs = [[[0.0, *v], [1.0, *v]], [[0.5, *v], [1.5, *v]]]  # 1. parça + geri sarıp 2. parça
    r = rex.export_video(str(vid), [], str(out), segments=segs)
    assert r["audio"] is True and r["frames"] == 11 + 11
    probe = subprocess.run([ff, "-hide_banner", "-i", str(out)], capture_output=True)
    assert b"Audio:" in probe.stderr and b"Video:" in probe.stderr
    assert b"Duration: 00:00:02.2" in probe.stderr or b"Duration: 00:00:02.1" in probe.stderr


def test_audio_filter_splits_and_concats_segments():
    plan = [(0, 11, []), (5, 16, [])]
    f = rex.audio_filter(plan, 10.0)
    assert f.startswith("[1:a]asplit=2[s0][s1];") and "concat=n=2:v=0:a=1[aout]" in f
    assert "atrim=start=0.500000:end=1.600000" in f
    assert rex.audio_filter(plan[:1], 10.0).startswith("[1:a]atrim=")  # tek parça: split yok


def test_segment_plan_clamps_to_video_length():
    segs = [[[2.8, 0, 0, 0], [9.0, 0, 0, 0]], [[50.0, 0, 0, 0], [51.0, 0, 0, 0]]]
    plan = rex.segment_plan(segs, 10.0, total=30)
    assert [(a, b) for a, b, _k in plan] == [(28, 30)]  # video dışındaki parça atlanır


# ---- CLI ----

def test_cli_info_export_and_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rex, "find_ffmpeg", lambda explicit=None: None)
    vid = tmp_path / "c.mp4"
    _make_clip(vid, n=8)
    assert main(["export", str(vid)]) == 1  # kayıt yok
    assert "HATA" in capsys.readouterr().err
    k.save_recording(k.rec_path(vid), str(vid), [[0, 0, 0, 0], [0.8, 1.0, 0.1, 0.0]])
    assert main(["info", k.rec_path(vid)]) == 0
    assert "2 anahtar kare" in capsys.readouterr().out
    assert main(["export", str(vid)]) == 0
    assert (tmp_path / "c.kamera.mp4").is_file()
    assert "kaydedildi" in capsys.readouterr().out
    assert main([]) == 2
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0 and "takipli-oynat-kayit" in capsys.readouterr().out


# ---- bağımsızlık + paketleme ----

def test_recorder_never_imports_main_variant_or_ai_libs():
    """Kayıt varyantı: tracker/ ve model kütüphaneleri hiçbir yerde içe aktarılmaz."""
    banned = {"tracker", "onnxruntime", "onnx", "torch", "ultralytics"}
    for f in (ROOT / "recorder").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            assert not {n.split(".")[0] for n in names} & banned, (f.name, names)


def test_recording_requirements_have_no_onnxruntime():
    req = (ROOT / "requirements-recording.txt").read_text(encoding="utf-8")
    lines = [ln for ln in req.splitlines() if ln.strip() and not ln.startswith("#")]
    assert any(ln.startswith("numpy") for ln in lines)
    assert any(ln.startswith("opencv-python-headless") for ln in lines)
    assert not any("onnx" in ln for ln in lines)


def test_make_package_recording_variant_has_no_models_or_tracker(tmp_path):
    pkg = _load("make_package")
    out = tmp_path / "Kayit"
    assert pkg.main(["--variant", "recording", "--out", str(out)]) == 0
    for name in ("recorder/main.py", "recorder/export.py", "mpv/portable_config/mpv.conf",
                 "mpv/portable_config/input.conf", "Kayit.bat", "VERSION", "README.md",
                 "requirements.txt", "THIRD_PARTY_NOTICES.md"):
        assert (out / name).is_file(), name
    assert not (out / "tracker").exists() and not (out / "models").exists()
    assert not (out / "Offline.bat").exists() and not (out / "Baslat.bat").exists()
    assert "onnx" not in (out / "requirements.txt").read_text(encoding="utf-8")
    raw = (out / "Kayit.bat").read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    assert not list(out.rglob("__pycache__"))
    cfg = (out / "mpv/portable_config/mpv.conf").read_text(encoding="utf-8")
    assert "input-ipc-server=\\\\.\\pipe\\mpv-kayit" in cfg  # ana varyantın borusundan ayrı


def test_make_package_main_variant_unchanged_and_isolated(tmp_path):
    pkg = _load("make_package")
    out = tmp_path / "Ana"
    assert pkg.main(["--out", str(out)]) == 0  # varsayılan varyant = main
    assert (out / "tracker/main.py").is_file() and (out / "Offline.bat").is_file()
    assert (out / "models/MODELLER.txt").is_file()
    assert not (out / "recorder").exists() and not (out / "Kayit.bat").exists()
    assert "onnxruntime-directml" in (out / "requirements.txt").read_text(encoding="utf-8")


def test_variant_versions_stay_in_sync():
    import recorder
    import tracker

    assert recorder.__version__ == tracker.__version__ == (ROOT / "VERSION").read_text().strip()


def test_build_embedded_accepts_requirements_file():
    emb = _load("build_embedded")
    import inspect

    assert inspect.signature(emb.build).parameters["requirements"].default == "requirements.txt"
    assert "--requirements" in (ROOT / "scripts" / "build_embedded.py").read_text(encoding="utf-8")
