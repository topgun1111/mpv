"""Tracker paneli (L tuşu / «Tracker» sekmesi): trackpanel.lua + track.lua bağlama + mod kapıları."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

LUA = shutil.which("texlua") or shutil.which("lua") or shutil.which("luajit")
ROOT = Path(__file__).resolve().parent.parent
PC = ROOT / "mpv" / "portable_config"
TRACK_LUA = PC / "scripts" / "track.lua"
MODULES = PC / "script-modules"
HARNESS = Path(__file__).with_name("lua_harness_tracker.lua")

CFG = ("return { fill={0.3,0.1,0.8,'%30'}, speed={0.15,0.03,0.6,'0.15'}, lead={0.15,0,0.6,'0.15 sn'},"
       " hold={1,0,5,'1.00 sn'}, zoomout={2,0,6,'2.0 sn'}, memory={1.5,0,5,'1.5 sn'}, pbox={0.06,0.02,0.2,'%6'},"
       " pscore={0.45,0.2,0.9,'0.45'}, kpconf={0.35,0.1,0.8,'0.35'}, flags={kp_filter=true} }")


@pytest.mark.skipif(LUA is None, reason="lua/texlua yok")
def test_tracker_panel_flow(tmp_path):
    data = tmp_path / "d.lua"
    data.write_text(CFG, encoding="utf-8")
    env = {"TRACK_LUA": str(TRACK_LUA), "TRACK_MODULES": str(MODULES), "VIDEO": "", "DATA_LUA": str(data)}
    r = subprocess.run([LUA, str(HARNESS)], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    d = {ln.split("\t")[0]: ln.split("\t")[1:] for ln in r.stdout.splitlines() if "\t" in ln}
    assert d["OPEN"] == ["true", "true", "true"]  # panel çizildi, ayar özeti istendi, Esc bağlı
    assert d["NOCFG"] == ["true"] and d["CFG"] == ["true", "true"]  # özet yokken «—», gelince değerler
    assert d["BODY"] == ["true", "true"] and d["POINT"] == ["true"] and d["CHIP"] == ["true"]
    assert d["STEP1"] == ["script-message track-setting fill 1"]  # temel ayar: Ctrl+ tuşlarıyla aynı yol
    assert d["STEP2"] == ["script-message track-option pbox -1"]  # ek ayar: yeni mesaj
    assert d["FLAG"] == ["script-message track-option kp_filter toggle"]
    assert d["SAVE"] == ["script-message track-save"] and d["DEF"] == ["script-message track-setting all 0"]
    assert d["ARROWS"] == ["true"] and d["ARROWOFF"] == ["true", "true"]  # oklar yalnız panel üstündeyken
    assert d["RECTGATE"] == ["true", "true"] and d["POINTGATE"] == ["true", "true"]
    assert d["HUDMODE"] == ["true"]
    assert d["ESC"] == ["true", "true"] and d["TAB"] == ["true"] and d["TABOFF"] == ["true"]


def test_panel_parts_match_track_lua():
    """Panel parça listesi (sıra + id) track.lua PARTS ile aynı olmalı («auto» panelde ayrı: Otomatik/Nokta modları)."""
    lua = TRACK_LUA.read_text(encoding="utf-8")
    parts = re.findall(r'"(\w+)"', re.search(r"local PARTS = \{(.*?)\}", lua, re.S).group(1))
    panel = (MODULES / "trackpanel.lua").read_text(encoding="utf-8")
    ids = re.findall(r'\{ "(\w+)", "[^"]+" \}', re.search(r"M\.PARTS = \{(.*?)\n\}", panel, re.S).group(1))
    assert ids == [p for p in parts if p != "auto"]
