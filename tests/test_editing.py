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
        [lua, "tests/lua_harness_editing_ui.lua"], cwd=ROOT, check=True,
        capture_output=True, text=True, timeout=20,
    )
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
