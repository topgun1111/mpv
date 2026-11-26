"""Editing graph and real FFmpeg smoke test when tools are available."""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_editing_graph_and_ffmpeg():
    lua = shutil.which("texlua") or shutil.which("lua") or shutil.which("luajit")
    if not lua:
        pytest.skip("Lua interpreter unavailable")
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
