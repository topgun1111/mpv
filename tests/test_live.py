import base64
import json
import os
import queue
import socket
import threading

import numpy as np
import pytest

from tracker.bytetrack import Track
from tracker.config import Config
from tracker.frames import decode_raw, grab_frame
from tracker.geometry import BBox, View
from tracker.ipc import MpvCommandError, MpvIpc, MpvIpcError
from tracker.live import CLOSED, LiveController, pick_track, run_live

FRAME = np.zeros((100, 200, 3), np.uint8)


def _tr(i, x1, y1, x2, y2):
    return Track(i, BBox(x1, y1, x2, y2), 0.9, 5, 0)


def _click(px, py, w=200, h=100):
    return {"event": "client-message",
            "args": ["track-click", str(px / w), str(py / h), str(w), str(h), "1.0"]}


def _toggle(on):
    return {"event": "client-message", "args": ["track-toggle", "on" if on else "off"]}


class FakePipeline:
    def __init__(self, seq):
        self.seq, self.i, self.resets = seq, 0, 0

    def step(self, frame):
        out = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        return out

    def reset(self):
        self.resets += 1


def _cfg():
    return Config(ipc_path="x")


# --- frames ---
def _node(w=3, h=2, stride=16, fmt="bgr0", b64=True):
    raw = bytearray(stride * h)
    for y in range(h):
        for x in range(w):
            raw[y * stride + x * 4: y * stride + x * 4 + 4] = bytes([x, y, 7, 255])
    data = base64.b64encode(bytes(raw)).decode() if b64 else list(raw)
    return {"w": w, "h": h, "stride": stride, "format": fmt, "data": data}


def test_decode_raw_stride_and_channels():
    f = decode_raw(_node())
    assert f.shape == (2, 3, 3) and f.dtype == np.uint8 and f.flags["C_CONTIGUOUS"]
    assert tuple(f[1, 2]) == (2, 1, 7)  # padding (stride > w*4) atılır, alfa/0 kanalı düşer


def test_decode_raw_list_data_and_errors():
    assert decode_raw(_node(b64=False)).shape == (2, 3, 3)
    with pytest.raises(ValueError):
        decode_raw(_node(fmt="rgb24"))
    bad = _node()
    bad["data"] = base64.b64encode(b"short").decode()
    with pytest.raises(ValueError):
        decode_raw(bad)
    with pytest.raises(ValueError):
        decode_raw({"w": 1})


# --- seçim ---
def test_pick_track():
    a, b = _tr(1, 0, 0, 100, 100), _tr(2, 60, 0, 160, 100)
    assert pick_track([a, b], 20, 50).id == 1
    assert pick_track([a, b], 140, 50).id == 2
    assert pick_track([a, b], 100, 50).id == 2  # iki kutuda: merkezi yakın olan
    assert pick_track([a, b], 190, 50) is None


# --- denetleyici ---
def test_disabled_does_nothing():
    c = LiveController(FakePipeline([[]]), _cfg())
    assert not c.needs_frame(1.0)
    assert c.step(FRAME, 1.0).view is None


def test_click_selects_and_follows():
    c = LiveController(FakePipeline([[_tr(3, 85, 40, 95, 60)]]), _cfg())
    c.handle_event(_toggle(True))
    c.handle_event(_click(90, 50))
    out = c.step(FRAME, 1.0)
    assert c.target_id == 3 and out.osd == "Hedef: ID 3"
    assert out.view is not None and out.view.zoom > 0.5
    assert abs(out.view.pan_x) < 0.06  # hedef yatayda ortaya yakın


def test_click_on_empty_area():
    c = LiveController(FakePipeline([[_tr(3, 85, 40, 95, 60)]]), _cfg())
    c.handle_event(_click(5, 5))
    out = c.step(FRAME, 1.0)
    assert c.target_id is None and out.osd == "Burada kişi yok" and out.view is None


def test_target_lost_osd_once_and_view_held():
    t = _tr(3, 85, 40, 95, 60)
    c = LiveController(FakePipeline([[t], [], []]), _cfg())
    c.handle_event(_click(90, 50))
    c.step(FRAME, 1.0)
    o1, o2 = c.step(FRAME, 1.04), c.step(FRAME, 1.08)
    assert o1.osd == "Hedef kayboldu" and o1.view is None
    assert o2.osd is None and c.target_id == 3  # kayıp yönetimi Parça 8


def test_pause_skips_frames_until_click():
    c = LiveController(FakePipeline([[_tr(3, 85, 40, 95, 60)]]), _cfg())
    c.handle_event(_toggle(True))
    assert c.needs_frame(5.0)  # ilk kare
    c.step(FRAME, 5.0)
    assert not c.needs_frame(5.0)
    c.handle_event(_click(90, 50))
    assert c.needs_frame(5.0)  # duraklatılmışken tıklama yine işlenir


def test_seek_resets_target():
    p = FakePipeline([[_tr(3, 85, 40, 95, 60)]])
    c = LiveController(p, _cfg())
    c.handle_event(_click(90, 50))
    c.step(FRAME, 10.0)
    out = c.step(FRAME, 60.0)  # ileri atlama
    assert c.target_id is None and p.resets == 1
    assert out.view == View() and "Atlama" in out.osd
    c.handle_event(_click(90, 50))
    c.step(FRAME, 60.1)
    out = c.step(FRAME, 20.0)  # geri atlama
    assert c.target_id is None and p.resets == 2


def test_reset_and_toggle_off_restore_view():
    c = LiveController(FakePipeline([[_tr(3, 85, 40, 95, 60)]]), _cfg())
    c.handle_event(_click(90, 50))
    c.step(FRAME, 1.0)
    assert c.handle_event({"event": "client-message", "args": ["track-reset"]}).view == View()
    assert c.target_id is None and c.enabled
    assert c.handle_event(_toggle(False)).view == View() and not c.enabled


# --- döngü ---
class FakeMpv:
    def __init__(self, stop, frames):
        self.stop, self.frames, self.t, self.views, self.texts = stop, frames, 0.0, [], []
        self.grabs = 0

    def get_property(self, name):
        assert name == "time-pos"
        self.t += 0.1
        return self.t

    def command(self, *a):
        if a[0] == "show-text":
            self.texts.append(a[1])

    def set_view(self, v):
        self.views.append(v)


def test_run_live_end_to_end():
    stop = threading.Event()
    mpv = FakeMpv(stop, 4)

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
    assert mpv.texts == ["Hedef: ID 3"]
    assert mpv.views and mpv.views[-1].zoom > 0.5
    assert len(mpv.views) <= 4


def test_run_live_closed_event_and_command_error():
    ev = queue.Queue()
    ev.put(CLOSED)
    run_live(object(), ev, FakePipeline([[]]), _cfg(), log=lambda *_: None)

    class NoVideo(FakeMpv):
        def get_property(self, name):
            self.grabs += 1
            if self.grabs > 2:
                raise MpvIpcError("mpv bağlantısı kapandı")
            raise MpvCommandError("mpv hatası: property unavailable")

    ev = queue.Queue()
    ev.put(_toggle(True))
    logs = []
    run_live(NoVideo(None, 0), ev, FakePipeline([[]]), _cfg(), log=logs.append,
             sleep=lambda _s: None)
    assert "kesildi" in logs[-1]  # komut hatası döngüyü bozmaz; bağlantı hatası temiz çıkar


# --- gerçek soket: büyük satır ---
@pytest.mark.skipif(os.name == "nt", reason="Unix soketi gerekir")
def test_grab_frame_over_socket_large_payload(tmp_path):
    path = str(tmp_path / "m.sock")
    w, h = 1280, 720
    payload = {"w": w, "h": h, "stride": w * 4, "format": "bgr0",
               "data": base64.b64encode(bytes(w * h * 4)).decode()}
    ready = threading.Event()

    def serve():
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(path)
        srv.listen(1)
        ready.set()
        conn, _ = srv.accept()
        f = conn.makefile("rwb")
        for line in f:
            req = json.loads(line)
            f.write(json.dumps({"event": "noise"}).encode() + b"\n")
            f.write(json.dumps({"error": "success", "data": payload,
                                "request_id": req["request_id"]}).encode() + b"\n")
            f.flush()
        srv.close()

    threading.Thread(target=serve, daemon=True).start()
    ready.wait(2)
    with MpvIpc(path, timeout=10.0, keep_events=False) as mpv:
        frame = grab_frame(mpv)
        assert frame.shape == (h, w, 3)
        assert len(mpv._events) == 0
