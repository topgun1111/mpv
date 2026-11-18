"""S13a: NVENC algılama + yedek, ffmpeg komutu (sahte ffmpeg çıktısıyla)."""
from types import SimpleNamespace as NS

import pytest

from tracker import export as ex


def fake_run(listed=True, probe_rc=0):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if "-encoders" in cmd:
            return NS(returncode=0, stdout=b" V....D h264_nvenc NVIDIA\n" if listed else b" V libx264\n")
        return NS(returncode=probe_rc, stdout=b"")
    run.calls = calls
    return run


@pytest.fixture(autouse=True)
def clear():
    ex._PROBE.clear()


def test_available_needs_listing_and_working_probe():
    assert ex.encoder_available("ff", run=fake_run()) is True
    ex._PROBE.clear()
    assert ex.encoder_available("ff", run=fake_run(listed=False)) is False
    ex._PROBE.clear()
    assert ex.encoder_available("ff", run=fake_run(probe_rc=1)) is False  # listede var, GPU yok


def test_probe_is_cached():
    r = fake_run()
    ex.encoder_available("ff", run=r)
    n = len(r.calls)
    ex.encoder_available("ff", run=r)
    assert len(r.calls) == n


def test_choose_auto_falls_back_and_forced_modes():
    assert ex.choose_encoder("ff", "auto", fake_run()) == "h264_nvenc"
    ex._PROBE.clear()
    assert ex.choose_encoder("ff", "auto", fake_run(listed=False)) == "libx264"
    assert ex.choose_encoder("ff", "x264", fake_run()) == "libx264"
    ex._PROBE.clear()
    with pytest.raises(RuntimeError, match="nvenc"):
        ex.choose_encoder("ff", "nvenc", fake_run(listed=False))
    with pytest.raises(ValueError):
        ex.choose_encoder("ff", "foo", fake_run())


def test_cmd_default_unchanged_and_nvenc_variant():
    base = ex.ffmpeg_cmd("ff", (64, 64), 25.0, "i", "o")
    assert "libx264" in base and "-crf" in base and "h264_nvenc" not in base
    nv = ex.ffmpeg_cmd("ff", (64, 64), 25.0, "i", "o", crf=20, encoder="h264_nvenc")
    assert nv[nv.index("-c:v") + 1] == "h264_nvenc" and nv[nv.index("-cq") + 1] == "20"
    assert "-crf" not in nv and "-c:a" in nv and "copy" in nv
    assert "-shortest" in nv  # süre verilmediyse eski komut (recorder ile eşlik)
    assert ex.ffmpeg_cmd("ff", (64, 64), 25.0, "i", "o", audio=False, encoder="h264_nvenc")[-1] == "o"
