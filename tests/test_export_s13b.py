"""S13b: çalışma anı NVENC yedeği, NVDEC okuyucu (sahte), sabitleme + doğrulama uçtan uca."""
import json
import shutil
import subprocess

import cv2
import numpy as np
import pytest

from tracker import export as ex
from tracker.config import Config
from tracker.main import main

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg yok")


def _video(path, n=20, w=320, h=180, shake=False, audio=False):
    rng = np.random.default_rng(1)
    g = cv2.GaussianBlur((rng.random((h + 40, w + 40)) * 255).astype(np.uint8), (0, 0), 2)
    raw = path.with_suffix(".raw.avi")
    vw = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (w, h))
    for k in range(n):
        dx, dy = (int(rng.integers(0, 12)), int(rng.integers(0, 12))) if shake else (20, 20)
        vw.write(cv2.cvtColor(g[dy:dy + h, dx:dx + w], cv2.COLOR_GRAY2BGR))
    vw.release()
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw)]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={n / 10}", "-c:a", "aac"]
    subprocess.run(cmd + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(path)],
                   check=True)
    raw.unlink()


@pytest.fixture(autouse=True)
def _clear_probe():
    ex._PROBE.clear()
    yield
    ex._PROBE.clear()


def _break_nvenc(monkeypatch):
    """NVENC 'seçilir' ama ffmpeg kodlama sırasında düşer (GPU makinesinde de deterministik)."""
    real = ex.ffmpeg_cmd
    monkeypatch.setattr(ex, "choose_encoder",
                        lambda ff, pref="auto", run=None: "libx264" if pref == "x264"
                        else "h264_nvenc")
    monkeypatch.setattr(ex, "ffmpeg_cmd", lambda *a, **k: [
        "no_such_encoder" if t == "h264_nvenc" else t for t in real(*a, **k)])


def test_runtime_nvenc_failure_falls_back_to_x264(tmp_path, monkeypatch, capsys):
    v, out = tmp_path / "a.mp4", tmp_path / "a.takipli.mp4"
    _video(v)
    _break_nvenc(monkeypatch)
    r = ex.export_video(str(v), [[0, 0.0, 0.0, 0.0]], str(out), Config())
    assert r["encoder"] == "libx264" and r["fallback"] == "h264_nvenc → libx264"
    assert r["frames"] == 20 and out.exists() and r["validation"]["ok"]
    assert "libx264 ile yeniden" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.partial*"))


def test_forced_nvenc_failure_raises_without_fallback(tmp_path, monkeypatch):
    v, out = tmp_path / "a.mp4", tmp_path / "o.mp4"
    _video(v)
    _break_nvenc(monkeypatch)
    with pytest.raises(ex.EncoderError) as e:
        ex.export_video(str(v), [[0, 0.0, 0.0, 0.0]], str(out), Config(), encoder="nvenc")
    assert e.value.encoder == "h264_nvenc" and not out.exists()
    assert json.loads((tmp_path / "o.mp4.export.json").read_text())["state"] == "error"


def test_x264_failure_is_not_retried(tmp_path, monkeypatch):
    v = tmp_path / "a.mp4"
    _video(v)
    calls = []
    monkeypatch.setattr(ex, "_export_once",
                        lambda *a, **k: calls.append(k["pref"]) or (_ for _ in ()).throw(
                            ex.EncoderError("x", "libx264")))
    with pytest.raises(ex.EncoderError):
        ex.export_video(str(v), [[0, 0.0, 0.0, 0.0]], str(tmp_path / "o.mp4"), Config())
    assert calls == ["auto"]


class _FakeNvdec:
    """cv2 ile çözen sahte NVDEC: arayüz (read/release/error) ve kare sırası aynı."""

    ok = True

    def __init__(self, ff, video, w, h):
        self.cap = cv2.VideoCapture(video)

    def read(self):
        return self.cap.read() if self.ok else (False, None)

    def error(self):
        return "CUDA yok"

    def release(self):
        self.cap.release()


def test_nvdec_reader_used_and_frames_match_cpu(tmp_path, monkeypatch):
    v = tmp_path / "a.mp4"
    _video(v)
    monkeypatch.setattr(ex, "NvdecReader", _FakeNvdec)
    a = ex.export_video(str(v), [[0, 1.0, 0.0, 0.0]], str(tmp_path / "n.mp4"), decode="nvdec")
    b = ex.export_video(str(v), [[0, 1.0, 0.0, 0.0]], str(tmp_path / "c.mp4"), decode="cpu")
    assert a["decoder"] == "nvdec" and b["decoder"] == "cpu" and a["frames"] == b["frames"] == 20
    assert a["validation"]["ok"] and b["validation"]["ok"]


def test_nvdec_auto_falls_back_forced_raises(tmp_path, monkeypatch, capsys):
    v = tmp_path / "a.mp4"
    _video(v)
    monkeypatch.setattr(ex, "NvdecReader", _FakeNvdec)
    monkeypatch.setattr(_FakeNvdec, "ok", False)
    r = ex.export_video(str(v), [[0, 0.0, 0.0, 0.0]], str(tmp_path / "o.mp4"), decode="auto")
    assert r["decoder"] == "cpu" and r["frames"] == 20 and "NVDEC kullanılamadı" in \
        capsys.readouterr().err
    with pytest.raises(RuntimeError, match="NVDEC çalışmıyor"):
        ex.export_video(str(v), [[0, 0.0, 0.0, 0.0]], str(tmp_path / "p.mp4"), decode="nvdec")
    with pytest.raises(ValueError, match="bilinmeyen çözücü"):
        ex.export_video(str(v), [[0, 0.0, 0.0, 0.0]], str(tmp_path / "q.mp4"), decode="gpu")


def test_default_export_is_unchanged_cpu_no_stab(tmp_path):
    v = tmp_path / "a.mp4"
    _video(v)
    r = ex.export_video(str(v), [[0, 0.0, 0.0, 0.0]], str(tmp_path / "o.mp4"))
    assert r["decoder"] == "cpu" and r["stabilized"] is False and r["validation"]["ok"]


def test_stabilize_end_to_end_reduces_shake_and_keeps_timing(tmp_path):
    v = tmp_path / "s.mp4"
    _video(v, n=30, shake=True, audio=True)
    views = [[0, 0.0, 0.0, 0.0]]
    plain = ex.export_video(str(v), views, str(tmp_path / "p.mp4"), stabilize=False)
    stab = ex.export_video(str(v), views, str(tmp_path / "st.mp4"), stabilize=True)
    assert stab["stabilized"] and stab["frames"] == plain["frames"] == 30
    assert stab["validation"]["ok"], stab["validation"]
    assert stab["audio"] and stab["validation"]["info"]["audio"]

    def shake_amount(p):
        cap = cv2.VideoCapture(str(p))
        gs = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            gs.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32))
        cap.release()
        sh = np.array([cv2.phaseCorrelate(a, b)[0] for a, b in zip(gs, gs[1:])])
        return float(sh.std(axis=0).sum())

    assert shake_amount(tmp_path / "st.mp4") < 0.7 * shake_amount(tmp_path / "p.mp4")


def test_validation_can_be_disabled_and_cfg_flags_apply(tmp_path):
    v = tmp_path / "a.mp4"
    _video(v)
    r = ex.export_video(str(v), [[0, 0.0, 0.0, 0.0]], str(tmp_path / "o.mp4"), validate=False)
    assert "validation" not in r
    assert json.loads((tmp_path / "o.mp4.export.json").read_text())["state"] == "done"
    cfg = Config(stabilize=True, export_validate=False)
    r = ex.export_video(str(v), [[0, 0.0, 0.0, 0.0]], str(tmp_path / "p.mp4"), cfg)
    assert r["stabilized"] and "validation" not in r


def test_cli_prints_validation_and_exit_code(tmp_path, capsys, monkeypatch):
    v = tmp_path / "a.mp4"
    _video(v, audio=True)
    (tmp_path / "a.mp4.views.json").write_text(json.dumps({"version": 1, "views": [[0, 0, 0, 0]]}))
    assert main(["export", str(v), "--stabilize", "--decode", "cpu"]) == 0
    assert "doğrulama: tamam" in capsys.readouterr().out
    monkeypatch.setattr("tracker.export_check.validate_files", lambda *a, **k: {
        "ok": False, "errors": ["kare sayısı 3, yazılan 20"], "warnings": ["x"], "info": {}})
    assert main(["export", str(v), "--out", str(tmp_path / "z.mp4")]) == 4
    cap = capsys.readouterr()
    assert "doğrulama HATA: kare sayısı" in cap.err and "BAŞARISIZ" in cap.out


def test_ffmpeg_cmd_limits_audio_on_input_side_instead_of_shortest():
    c = ex.ffmpeg_cmd("ff", (64, 64), 25.0, "src.mp4", "o.mp4", audio_limit=2.0)
    assert "-shortest" not in c
    i = c.index("src.mp4")
    assert c[i - 3:i] == ["-t", "2.000000", "-i"]  # yalnız ses girişine uygulanır
    d = ex.ffmpeg_cmd("ff", (64, 64), 25.0, "src.mp4", "o.mp4")  # süre bilinmiyorsa eski komut
    assert "-t" not in d and "-shortest" in d


def test_audio_export_keeps_every_video_frame(tmp_path):
    """Regresyon: `-shortest` sesli çıktıda son 1-2 kareyi kırpıyordu (20 → 18)."""
    v = tmp_path / "a.mp4"
    _video(v, n=20, audio=True)
    r = ex.export_video(str(v), [[0, 0.0, 0.0, 0.0]], str(tmp_path / "o.mp4"))
    assert r["frames"] == 20 and r["audio"]
    assert r["validation"]["ok"] and r["validation"]["info"]["frames"] == 20
