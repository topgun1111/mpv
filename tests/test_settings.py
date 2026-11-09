"""Parça 13: canlı ayarlar, HUD etiketi, kaydetme, Lua tuşları."""
import queue
import shutil
import subprocess
import threading
from pathlib import Path

import numpy as np
import pytest
from test_live import FakeMpv, FakePipeline, _click, _msg, _toggle
from test_reid import _tr

from tracker.config import Config
from tracker.live import LiveController, run_live
from tracker.settings import SETTINGS, adjust, reset_all, status_text

FRAME = np.zeros((100, 200, 3), np.uint8)
LUA = shutil.which("texlua") or shutil.which("lua") or shutil.which("luajit")
ROOT = Path(__file__).resolve().parent.parent


def _cfg(**kw):
    return Config(ipc_path="x", **kw)


def test_adjust_fill_steps_clamps_and_resets():
    c = _cfg()
    assert adjust(c, "fill", 1) == "Doluluk: %35" and c.target_fill == pytest.approx(0.35)
    adjust(c, "fill", -1)
    adjust(c, "fill", -1)
    assert c.target_fill == pytest.approx(0.25)
    for _ in range(30):
        adjust(c, "fill", -1)
    assert c.target_fill == 0.10 and "alt sınır" in adjust(c, "fill", -1)
    for _ in range(30):
        adjust(c, "fill", 1)
    assert c.target_fill == 0.80 and "üst sınır" in adjust(c, "fill", 1)
    assert "varsayılan" in adjust(c, "fill", 0) and c.target_fill == Config().target_fill


def test_adjust_speed_scales_both_alphas_and_lead_and_unknown():
    c = _cfg()
    pos0, zoom0 = c.alpha_pos, c.alpha_zoom
    adjust(c, "speed", 1)
    assert c.alpha_pos == pytest.approx(pos0 * 1.25, abs=1e-4)
    assert c.alpha_zoom == pytest.approx(zoom0 * 1.25, abs=1e-3)
    for _ in range(40):
        adjust(c, "speed", 1)
    assert c.alpha_pos == 0.60 and c.alpha_zoom <= 1.0
    for _ in range(80):
        adjust(c, "speed", -1)
    assert c.alpha_pos == 0.03 and c.alpha_zoom > 0
    assert adjust(c, "lead", 1) == "Öngörü: 0.20 sn"
    for _ in range(40):
        adjust(c, "lead", -1)
    assert c.lookahead_s == 0.0
    assert adjust(c, "yok", 1) is None and adjust(c, "all", 1) is None
    c.target_fill = 0.5
    assert reset_all(c) and c.target_fill == Config().target_fill
    assert c.alpha_pos == Config().alpha_pos and c.lookahead_s == Config().lookahead_s
    assert set(SETTINGS) == {"fill", "speed", "lead"}


def test_status_text_lists_all_and_target():
    t = status_text(_cfg(), 7)
    assert "Doluluk: %30" in t and "Tepki hızı: 0.15" in t and t.endswith("Hedef: ID 7")
    assert status_text(_cfg(), None).endswith("Hedef: yok")


def _ctl(**kw):
    return LiveController(FakePipeline([[_tr(3, 85, 40, 95, 60)]]), _cfg(**kw))


def _setting(key, d):
    return {"event": "client-message", "args": ["track-setting", key, str(d)]}


def test_controller_setting_updates_smoother_and_osd():
    c = _ctl()
    out = c.handle_event(_setting("speed", 1))
    assert out.osd.startswith("Tepki hızı") and c.smoother._ema[1].alpha == c.cfg.alpha_pos
    assert c.smoother._ema[0].alpha == c.cfg.alpha_zoom and c.cfg.alpha_pos > 0.15
    assert c.handle_event(_setting("fill", 1)).osd == "Doluluk: %35"
    assert c.handle_event(_setting("all", 0)).osd == "Ayarlar varsayılana döndü"
    assert c.smoother._ema[1].alpha == Config().alpha_pos
    for bad in ({"event": "client-message", "args": ["track-setting"]},
                {"event": "client-message", "args": ["track-setting", "fill", "x"]},
                _setting("yok", 1)):
        assert c.handle_event(bad).osd is None
    assert c.handle_event(_setting("fill", 99)).osd  # yön ±1'e kırpılır
    assert c.cfg.target_fill == pytest.approx(0.35)
    assert "Hedef: yok" in c.handle_event(_msg("track-status")).osd


def test_setting_changes_next_view():
    def view_zoom(fill):
        c = _ctl(target_fill=fill)
        c.handle_event(_toggle(True))
        c.handle_event(_click(90, 50))
        return c.step(FRAME, 0.1).view.zoom

    c = _ctl()
    c.handle_event(_toggle(True))
    c.handle_event(_click(90, 50))
    for _ in range(4):
        c.handle_event(_setting("fill", 1))  # %30 → %50
    assert c.step(FRAME, 0.1).view.zoom == pytest.approx(view_zoom(0.5))
    assert view_zoom(0.5) > view_zoom(0.3)  # hedef kareyi daha çok doldurunca zoom artar


def test_save_writes_config_and_reports_errors(tmp_path):
    p = tmp_path / "c.json"
    c = LiveController(FakePipeline([[]]), _cfg(), cfg_path=str(p))
    c.handle_event(_setting("fill", 1))
    assert "kaydedildi" in c.handle_event(_msg("track-save")).osd
    assert Config.load(p).target_fill == pytest.approx(0.35)
    assert "config yolu yok" in _ctl().handle_event(_msg("track-save")).osd
    bad = LiveController(FakePipeline([[]]), _cfg(), cfg_path=str(tmp_path))  # klasör
    assert "Kaydedilemedi" in bad.handle_event(_msg("track-save")).osd


def test_hud_text_states():
    c = _ctl(lost_hold_s=0.2, lost_zoomout_s=1.0)
    assert c.hud_text() == ""  # takip kapalı
    c.handle_event(_toggle(True))
    assert "hedef seç" in c.hud_text()
    c.handle_event(_click(90, 50))
    c.step(FRAME, 0.1)
    assert c.hud_text() == "Takip: ID 3"
    c.pipeline.seq, c.pipeline.i = [[]], 0  # hedef kayboldu
    c.step(FRAME, 0.2)
    assert c.hud_text() == "Takip: hedef kayıp"
    c.step(FRAME, 0.6)
    assert c.hud_text().endswith("(uzaklaşıyor)")
    c.cfg.hud = False
    assert c.hud_text() == ""


def test_run_live_sends_hud_only_on_change():
    stop = threading.Event()
    sent = []

    class Mpv(FakeMpv):
        def command(self, *a):
            if a[0] == "script-message-to" and a[2] == "track-hud":  # nokta mesajları ayrı
                sent.append(a)
            super().command(*a)

    mpv = Mpv(stop, 4)

    def grab(m):
        m.grabs += 1
        if m.grabs >= 4:
            stop.set()
        return FRAME

    ev = queue.Queue()
    ev.put(_toggle(True))
    ev.put(_click(90, 50))
    cfg = _cfg()
    cfg.live_fps = 1000.0
    run_live(mpv, ev, FakePipeline([[_tr(3, 85, 40, 95, 60)]]), cfg, grab=grab, stop=stop,
             log=lambda *_: None, sleep=lambda _s: None)
    assert [a[3] for a in sent] == ["Takip: hedef seç (tıkla)", "Takip: ID 3"]
    assert all(a[1:3] == ("track", "track-hud") for a in sent)
    assert [a[4] for a in sent] == ["0", "1"]  # 2. argüman: hedef kilitli mi (zoom +/- için)


@pytest.mark.skipif(LUA is None, reason="lua/texlua yok")
def test_lua_hud_and_setting_keys(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"")
    (tmp_path / "v.mp4.views.json").write_text("{}", encoding="utf-8")
    data = tmp_path / "d.lua"
    data.write_text("return {version=1,target={id=3},views={{0,0,0,0},{1,1,0,0}}}",
                    encoding="utf-8")
    env = {"TRACK_LUA": str(ROOT / "mpv/portable_config/scripts/track.lua"),
           "VIDEO": str(video), "DATA_LUA": str(data), "PATH": ""}
    r = subprocess.run([LUA, str(Path(__file__).with_name("lua_harness_hud.lua"))], env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    rows = [ln.split("\t") for ln in r.stdout.splitlines()]
    by = {x[0]: x for x in rows if x[0] != "KEY"}
    assert by["HUD"][1].endswith("Takip: ID 5") and by["HUD"][1].startswith("{\\an9")
    assert by["ESC"][1].endswith("a b  c")  # ASS kaçışları ({ } \) temizlenir
    assert by["EMPTY"][1] == "" and by["HIDDEN"][1] == ""  # gizleme tuşu
    assert by["SHOWN"][1].endswith("Takip: ID 5")
    keys = {x[1]: x[2] for x in rows if x[0] == "KEY"}
    assert keys["fill-up"] == "script-message track-setting fill 1"
    assert keys["lead-down"] == "script-message track-setting lead -1"
    assert keys["settings-reset"] == "script-message track-setting all 0"
    assert keys["settings-save"] == "script-message track-save"
    assert by["TOGGLE_OFF"][1] == ""  # canlı kapanınca etiket silinir
    assert by["OFFLINE"][1].endswith("Takip: offline ID 3")
