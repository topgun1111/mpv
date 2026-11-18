"""Tracker paneli ek ayarları (settings.EXTRA/FLAGS) ve `track-option` işleyicisi."""
from tracker.config import Config
from tracker.settings import EXTRA, FLAGS, SETTINGS, adjust, panel_snapshot, reset_all, toggle_flag


def test_extra_settings_step_clamp_and_reset():
    c = Config()
    assert adjust(c, "hold", 1).startswith("Kayıp bekleme") and c.lost_hold_s == 1.25
    for _ in range(40):
        adjust(c, "hold", -1)
    assert c.lost_hold_s == 0.0 and "alt sınır" in adjust(c, "hold", -1)
    adjust(c, "pbox", 1)
    assert c.point_box == 0.07
    reset_all(c)
    assert c.lost_hold_s == Config().lost_hold_s and c.point_box == Config().point_box


def test_flags_toggle_and_reset():
    c = Config()
    assert toggle_flag(c, "kp_filter") == "Eklem süzgeci (titreme azaltır): kapalı" and c.kp_filter is False
    assert toggle_flag(c, "yok") is None
    reset_all(c)
    assert c.kp_filter is True


def test_snapshot_has_every_panel_key():
    s = panel_snapshot(Config())
    assert set(SETTINGS) | set(EXTRA) <= set(s) and set(s["flags"]) == set(FLAGS)
    v, lo, hi, txt = s["fill"]
    assert lo <= v <= hi and txt == "%30"


def _ctl():
    from tracker.live import LiveController

    class P:  # boş boru hattı: yalnız mesaj işleme denenir
        def process(self, *_a, **_k):
            return []

    return LiveController(P(), Config())


def _msg(name, *args):
    return {"event": "client-message", "args": [name, *args]}


def test_controller_option_message_updates_cfg_and_queues_snapshot():
    import json

    c = _ctl()
    assert c.cfg_message() is None  # değişiklik yok → gönderme
    out = c.handle_event(_msg("track-option", "zoomout", "1"))
    assert c.cfg.lost_zoomout_s == 2.5 and "Zoom-out" in out.osd
    snap = json.loads(c.cfg_message())
    assert snap["zoomout"][0] == 2.5 and c.cfg_message() is None  # bir kez verilir
    c.handle_event(_msg("track-option", "kp_world", "toggle"))
    assert c.cfg.kp_world is False and json.loads(c.cfg_message())["flags"]["kp_world"] is False
    assert c.handle_event(_msg("track-option", "yok", "1")).osd is None  # bilinmeyen anahtar: sessiz
    c.handle_event(_msg("track-cfg-get"))  # panel açıldı: özet istendi
    assert c.cfg_message() is not None
    c.handle_event(_msg("track-setting", "fill", "1"))  # Ctrl+ ayarları da paneli günceller
    assert c.cfg_message() is not None
