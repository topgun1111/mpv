"""Açılışta sessiz güncelleme denetimi (track.lua → `tracker update check`), sahte `mp` ve sahte alt süreçle."""
import shutil
import subprocess
from pathlib import Path

import pytest

LUA = shutil.which("texlua") or shutil.which("lua") or shutil.which("luajit")
ROOT = Path(__file__).resolve().parent.parent
PC = ROOT / "mpv" / "portable_config"
HARNESS = Path(__file__).with_name("lua_harness_autoupdate.lua")


@pytest.mark.skipif(LUA is None, reason="lua/texlua yok")
def test_startup_update_check(tmp_path):
    data = tmp_path / "d.lua"
    data.write_text("return {}", encoding="utf-8")
    state = tmp_path / "appdata"
    (state / "TakipliOynat").mkdir(parents=True)
    env = {"TRACK_LUA": str(PC / "scripts" / "track.lua"), "TRACK_MODULES": str(PC / "script-modules"),
           "VIDEO": "", "TRACK_PYTHON": "/fake/python.exe", "DATA_LUA": str(data),
           "TRACK_STATE_DIR": str(state)}
    r = subprocess.run([LUA, str(HARNESS)], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    d = {ln.split("\t")[0]: ln.split("\t")[1:] for ln in r.stdout.splitlines()}

    assert d["SCHEDULED"] == ["true", "true"]  # açılışta zamanlayıcı kurulur, hemen denetlemez
    assert d["CHECK_ARGS"] == ["check", "update"]  # `tracker update check`
    assert d["QUIET_UPTODATE"] == ["true", "true"]  # güncel: ekrana bir şey yazmaz
    assert d["QUIET_ERROR"] == ["true", "true"]  # ağ hatası: sessiz
    assert d["ASK"] == ["powershell.exe", "true"]  # yeni sürüm: Evet/Hayır penceresi
    assert d["ASKED_FILE"] == ["9.9.9"]  # sorulan sürüm kaydedilir
    assert d["INSTALL"] == ["update", "install", "--progress"]  # Evet → `tracker update install`
    assert d["NO_REPEAT"] == ["true", "true"]  # aynı sürüm için tekrar sormaz
