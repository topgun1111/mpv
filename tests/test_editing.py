"""Editing graph and real FFmpeg smoke test when tools are available."""
import os
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_editing_graph_and_ffmpeg():
    lua = shutil.which("texlua") or shutil.which("lua") or shutil.which("luajit")
    if not lua:
        pytest.skip("Lua interpreter unavailable")
    # Compile all new Lua modules, including the mpv-dependent entrypoint, without executing them.
    for rel in ("mpv/portable_config/script-modules/editingcore.lua",
                "mpv/portable_config/script-modules/editingui.lua"):
        assert (ROOT / rel).is_file()
    result = subprocess.run(
        [lua, "tests/lua_harness_editing.lua"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    )
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return
    graphs = result.stdout.strip().splitlines()
    assert len(graphs) == 4
    for graph in graphs:
        subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-filter_threads", "1",
             "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=5", "-t", "0.4",
             "-vf", graph, "-f", "null", "-"],
            check=True, capture_output=True, timeout=30,
        )


def test_editing_slider_interaction():
    lua = shutil.which("texlua") or shutil.which("lua") or shutil.which("luajit")
    if not lua:
        pytest.skip("Lua interpreter unavailable")
    result = subprocess.run(
        [lua, "tests/lua_harness_editing_ui.lua"], cwd=ROOT, check=False,
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "EDITING_UI_OK" in result.stdout


def test_editing_real_mpv(tmp_path):
    mpv = shutil.which("mpv")
    ffmpeg = shutil.which("ffmpeg")
    if not mpv or not ffmpeg:
        if os.environ.get("REQUIRE_EDITING_MPV") == "1":
            pytest.fail("MPV or FFmpeg missing in required integration test")
        pytest.skip("MPV or FFmpeg unavailable")
    clip = tmp_path / "source.mp4"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=size=160x120:rate=5", "-t", "1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
        check=True, capture_output=True, timeout=30,
    )
    env = dict(os.environ, EDITING_MODULES=str(ROOT / "mpv/portable_config/script-modules"))
    result = subprocess.run(
        [mpv, "--no-config", "--vo=null", "--ao=null", "--pause=yes",
         "--keep-open=yes", "--script=" + str(ROOT / "tests/editing_mpv_smoke.lua"), str(clip)],
        env=env, check=False, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "EDITING_MPV_SMOKE_OK" in result.stdout + result.stderr


def test_editing_cpu_export_quality_and_probe(tmp_path):
    lua = shutil.which("texlua") or shutil.which("lua") or shutil.which("luajit")
    ffmpeg = shutil.which("ffmpeg")
    if not lua or not ffmpeg:
        pytest.skip("Lua or FFmpeg unavailable")
    source = tmp_path / "input clip.mp4"
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=size=320x240:rate=10", "-f", "lavfi",
         "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)],
        check=True, capture_output=True, timeout=30,
    )
    script = "tests/lua_harness_editing_export_args.lua"
    for quality in (14, 26):
        dest = tmp_path / f"quality {quality}.mp4"
        for mode in ("probe", "export"):
            args = subprocess.run(
                [lua, script, ffmpeg, str(source), str(dest), str(quality), mode],
                cwd=ROOT, capture_output=True, text=True, check=True, timeout=20,
            ).stdout.splitlines()
            assert args[args.index("-crf") + 1] == str(quality)
            subprocess.run(args, check=True, capture_output=True, timeout=30)
        assert dest.is_file() and dest.stat().st_size > 0
        subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(dest),
             "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
            check=True, capture_output=True, timeout=30,
        )


def test_recording_topbar_actions():
    lua = shutil.which("texlua") or shutil.which("lua") or shutil.which("luajit")
    if not lua:
        pytest.skip("Lua interpreter unavailable")
    result = subprocess.run(
        [lua, "tests/lua_harness_recording_menu.lua"], cwd=ROOT,
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RECORDING_MENU_OK" in result.stdout
