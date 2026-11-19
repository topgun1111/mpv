"""S13b: dışa aktarma doğrulaması (saf denetim + sahte ffprobe + gerçek ffmpeg varsa uçtan uca)."""
import json
import shutil
import subprocess
from types import SimpleNamespace as NS

import pytest

from tracker import export_check as ec


def _v(**k):
    d = {"codec": "h264", "width": 320, "height": 180, "fps": 10.0, "avg_fps": 10.0,
         "frames": 30, "duration": 3.0, "start": 0.0}
    d.update(k)
    return d


def _m(video=None, audio="auto", pts="auto", **k):
    a = {"codec": "aac", "duration": 3.0, "start": 0.0} if audio == "auto" else audio
    ts = [i / 10 for i in range(30)] if pts == "auto" else pts
    d = {"video": video or _v(), "audio": a, "audio_known": True, "format_duration": 3.0,
         "pts": ts, "dts": ts}
    d.update(k)
    return d


def _val(src=None, out=None, **k):
    kw = {"frames_written": 30, "size": (320, 180), "fps": 10.0, "audio_expected": True}
    kw.update(k)
    return ec.validate(src or _m(pts=None), out or _m(), **kw)


def test_valid_export_passes_clean():
    r = _val()
    assert r["ok"] and not r["errors"] and not r["warnings"]
    assert r["info"]["frames"] == 30 and r["info"]["audio"] is True


@pytest.mark.parametrize("out,needle", [
    (_m(video=_v(frames=29)), "kare sayısı"),
    (_m(video=_v(width=318)), "boyutu"),
    (_m(video=_v(fps=12.0)), "fps"),
    (_m(video=_v(duration=4.5)), "video süresi"),
    (_m(audio=None), "ses akışı yok"),
    (_m(pts=[i / 10 for i in range(15)] + [i / 10 + 1.0 for i in range(15, 30)]), "boşluk"),
    (_m(pts=[i / 10 for i in range(30)], dts=[0.0, 0.2, 0.1] + [i / 10 for i in range(3, 30)]),
     "geriye"),
])
def test_each_error_is_reported(out, needle):
    r = _val(out=out)
    assert not r["ok"] and any(needle in e for e in r["errors"])


def test_no_video_stream_is_error():
    r = ec.validate(_m(), {"video": None}, frames_written=1, size=(2, 2), fps=10.0,
                    audio_expected=False)
    assert not r["ok"] and "video akışı yok" in r["errors"][0]


def test_warnings_vfr_audio_codec_and_source_mismatch():
    src = _m(video=_v(fps=30.0, avg_fps=24.0, frames=40, duration=4.5), pts=None)
    out = _m(audio={"codec": "mp3", "duration": 4.2, "start": 0.3})
    r = _val(src=src, out=out)
    w = " | ".join(r["warnings"])
    assert r["ok"] and "VFR" in w and "ses kodeği" in w and "kaynakta 40 kare" in w
    assert "ses 4.20" in w and "A/V" in w and "kaynak 4.50" in w


def test_audio_cases():
    src_no_audio = _m(audio=None, pts=None)
    assert _val(src=src_no_audio, out=_m(audio=None))["ok"]  # kaynakta ses yok: sorun değil
    r = _val(out=_m(), audio_expected=False)
    assert r["ok"] and any("ses istenmedi" in w for w in r["warnings"])
    cv_out = _m(audio=None, audio_known=False, pts=None)
    r = _val(out=cv_out)
    assert r["ok"] and any("doğrulanamadı" in w for w in r["warnings"])


def test_probe_media_parses_json_and_packets():
    js = {"streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 320, "height": 180,
         "r_frame_rate": "30000/1001", "avg_frame_rate": "30000/1001", "nb_read_packets": "12",
         "duration": "0.4", "start_time": "0.000000"},
        {"codec_type": "audio", "codec_name": "aac", "duration": "0.41", "start_time": "0.0"}],
        "format": {"duration": "0.41"}}

    def run(cmd, **k):
        if "-select_streams" in cmd:
            return NS(returncode=0, stdout=b"0.0,0.0\n0.033,0.033\n0.066,\n", stderr=b"")
        return NS(returncode=0, stdout=json.dumps(js).encode(), stderr=b"")

    m = ec.probe_media("ffprobe", "x.mp4", packets=True, run=run)
    assert m["video"]["frames"] == 12 and abs(m["video"]["fps"] - 29.97) < 0.01
    assert m["audio"]["codec"] == "aac" and m["format_duration"] == 0.41
    assert m["pts"] == [0.0, 0.033, 0.066] and m["dts"][-1] == 0.066


def test_probe_media_failure_message():
    run = lambda cmd, **k: NS(returncode=1, stdout=b"", stderr=b"Invalid data found")  # noqa: E731
    with pytest.raises(RuntimeError, match="Invalid data"):
        ec.probe_media("ffprobe", "bad.mp4", run=run)


def test_validate_files_missing_or_empty(tmp_path):
    r = ec.validate_files("s", str(tmp_path / "yok.mp4"), ffmpeg=None, frames_written=1,
                          size=(2, 2), fps=10.0, audio_expected=False)
    assert not r["ok"] and "yok ya da boş" in r["errors"][0]
    (tmp_path / "e.mp4").write_bytes(b"")
    assert not ec.validate_files("s", str(tmp_path / "e.mp4"), ffmpeg=None, frames_written=1,
                                 size=(2, 2), fps=10.0, audio_expected=False)["ok"]


def test_ffmpeg_report_with_fake_run():
    from tracker import export as ex

    ex._PROBE.clear()

    def run(cmd, **k):
        if "-encoders" in cmd:
            return NS(returncode=0, stdout=b" V libx264\n V h264_nvenc\n", stderr=b"")
        if "-hwaccels" in cmd:
            return NS(returncode=0, stdout=b"Hardware acceleration methods:\ncuda\ndxva2\n",
                      stderr=b"")
        return NS(returncode=1, stdout=b"", stderr=b"no device")  # deneme kodlaması başarısız

    r = ec.ffmpeg_report("ff-fake", run)
    assert r["listed"]["libx264"] and r["listed"]["h264_nvenc"] and not r["listed"]["hevc_nvenc"]
    assert r["nvenc_works"] is False and r["hwaccels"] == ["cuda", "dxva2"]
    ex._PROBE.clear()


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                    reason="ffmpeg/ffprobe yok")
def test_validate_files_real_ffmpeg_ok_and_truncated(tmp_path):
    src = tmp_path / "s.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=320x180:rate=10:duration=3", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    ff = shutil.which("ffmpeg")
    ok = ec.validate_files(str(src), str(src), ffmpeg=ff, frames_written=30, size=(320, 180),
                           fps=10.0, audio_expected=True)
    assert ok["ok"], ok
    cut = tmp_path / "c.mp4"  # 1 sn'de kesilmiş: kare sayısı/süre hatası verir
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-t", "1", "-c", "copy",
                    str(cut)], check=True)
    bad = ec.validate_files(str(src), str(cut), ffmpeg=ff, frames_written=30, size=(320, 180),
                            fps=10.0, audio_expected=True)
    assert not bad["ok"] and any("kare sayısı" in e or "süresi" in e for e in bad["errors"])
