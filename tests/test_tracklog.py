"""Video başına takip günlüğü (tracklog) + canlı mod bağlantısı."""
import queue
import threading

import numpy as np

from tracker import errlog, tracklog
from tracker.bytetrack import Track
from tracker.config import Config
from tracker.geometry import BBox
from tracker.live import LiveController, run_live
from tracker.tracklog import TrackLog, log_name

FRAME = np.zeros((100, 200, 3), np.uint8)


def _text(tl):
    return (tl.path or tl.last_path).read_text(encoding="utf-8")


def _tl(tmp_path, **kw):
    return TrackLog(directory=tmp_path / "TakipLog", proc="canlı", version="9.9", **kw)


def test_log_name_safe_and_distinct():
    a, b = log_name(r"C:\x\maç: 1?.mp4"), log_name(r"D:\y\maç: 1?.mp4")
    assert a != b and a.startswith("maç_ 1-") and a.endswith(".log")
    assert not any(c in a for c in '<>:"/\\|?*')
    assert log_name("") .startswith("video-")


def test_header_startup_and_feature_transitions(tmp_path):
    tl = _tl(tmp_path)

    class S:  # CPU'ya düşmüş oturum
        def get_providers(self):
            return ["CPUExecutionProvider"]

    tl.model_opened("models/a.onnx", ["DmlExecutionProvider", "CPUExecutionProvider"], S())
    tl.fail("poz modeli yükleme", ValueError("bozuk"))  # video yok: açılış satırı
    tl.open_video("/v/x.mp4", {"Genişlik": 1920, "Boş": None})
    t = _text(tl)
    assert "Video: /v/x.mp4" in t and "Genişlik: 1920" in t and "Boş" not in t
    assert "UYARI" in t and "DmlExecutionProvider istendi ama CPUExecutionProvider" in t
    assert "HATA   poz modeli yükleme: ValueError: bozuk" in t
    for _ in range(5):
        tl.ok("kare alma")
    tl.fail("kare alma", RuntimeError("x"))
    tl.fail("kare alma", RuntimeError("x"))
    tl.ok("kare alma")
    t = _text(tl)
    assert t.count("OK     kare alma") == 1  # yalnız ilk başarı satırı
    assert t.count("HATA   kare alma") == 1  # ardışık hatalar tek satır
    assert "DÜZELDİ kare alma" in t
    f = tl.feat["kare alma"]
    assert (f.ok, f.fail) == (6, 2) and tl.verdict(f).startswith("KISMEN")


def test_target_accounting_and_summary(tmp_path):
    tl = _tl(tmp_path)
    tl.open_video("/v/y.mp4")
    tl.target_start("nesne takibi: nesne", 1.0)
    for i in range(8):
        tl.tracked(1.0 + i * 0.1)
    tl.lost(1.9)
    tl.lost(2.0)
    tl.tracked(2.5)
    tl.idle("kişi tespiti")
    tl.ok("görünüm uygulama (zoom/kaydırma)")
    tl.close_video("test")
    t = _text(tl)
    assert "hedef kayboldu" in t and "geri bulundu" in t
    assert "izlenen 9 kare, kayıp 2 kare" in t and "takip oranı %82" in t
    assert "---- ÖZET" in t and "kişi tespiti" in t and "SONUÇ SONUÇ" not in t
    assert "SONUÇ: tüm özellikler çalıştı" in t  # idle tek başına hata değil
    assert tl.video is None


def test_summary_reports_failures(tmp_path):
    tl = _tl(tmp_path)
    tl.open_video("/v/z.mp4")
    tl.fail("eklem/parça takibi", ValueError("boom"))
    tl.close_video()
    t = _text(tl)
    assert "ÇALIŞMADI" in t and "son hata: ValueError: boom" in t
    assert "SONUÇ: sorun var: eklem/parça takibi" in t


def test_second_video_switches_file_and_never_raises(tmp_path):
    tl = _tl(tmp_path)
    tl.open_video("/v/a.mp4")
    p1 = tl.path
    tl.open_video("/v/b.mp4")  # önceki kapanır (özet yazılır)
    assert tl.path != p1 and "ÖZET" in p1.read_text(encoding="utf-8")
    tl.close_video()
    bad = TrackLog(directory="/proc/nope/TakipLog")  # yazılamaz dizin: sessiz
    bad.open_video("/v/c.mp4")
    bad.fail("x", "y")
    bad.close_video()


def test_errlog_forward_and_null(tmp_path):
    tracklog.NULL.ok("x")
    tracklog.forward("x", "y")  # etkin günlük yok: sessiz
    tl = _tl(tmp_path)
    tl.open_video("/v/e.mp4")
    tracklog.activate(tl)
    try:
        errlog.record("poz tahmini", RuntimeError("oops"))
    finally:
        tracklog.activate(None)
    assert tl.feat["poz tahmini"].fail == 1 and "HATA   poz tahmini: RuntimeError: oops" in _text(tl)


def test_operation_logs_success_and_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(tracklog, "log_dir", lambda: tmp_path / "TakipLog")
    # operation, TrackLog()'u varsayılan klasörle kurar: log_dir yamalandı
    with tracklog.operation("/v/o.mp4", "tarama") as tl:
        tl.ok("tarama")
    t = (tmp_path / "TakipLog" / log_name("/v/o.mp4")).read_text(encoding="utf-8")
    assert "tarama başladı" in t and "SONUÇ: tüm özellikler çalıştı" in t
    try:
        with tracklog.operation("/v/o.mp4", "dışa aktarma"):
            raise FileNotFoundError("ffmpeg yok")
    except FileNotFoundError:
        pass
    t = (tmp_path / "TakipLog" / log_name("/v/o.mp4")).read_text(encoding="utf-8")
    assert "HATA   dışa aktarma: FileNotFoundError: ffmpeg yok" in t
    assert tracklog.active() is tracklog.NULL


# --- canlı mod ---
class _Pipe:
    def __init__(self, seq):
        self.seq, self.i, self.detector = seq, 0, object()

    def step(self, frame):
        out = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        return out

    def reset(self):
        pass


def _tr(i, x1, y1, x2, y2):
    return Track(i, BBox(x1, y1, x2, y2), 0.9, 5, 0)


def _click(px, py):
    return {"event": "client-message",
            "args": ["track-click", str(px / 200), str(py / 100), "200", "100", "1.0"]}


def test_controller_logs_person_target_and_loss(tmp_path):
    tl = _tl(tmp_path)
    tl.open_video("/v/p.mp4")
    c = LiveController(_Pipe([[_tr(3, 85, 40, 95, 60)], [_tr(3, 85, 40, 95, 60)], []]),
                       Config(ipc_path="x"), tlog=tl)
    c.handle_event({"event": "client-message", "args": ["track-toggle", "on"]})
    c.handle_event(_click(90, 50))
    c.step(FRAME, 1.0)
    c.step(FRAME, 1.1)
    c.step(FRAME, 1.2)  # hedef yok
    c.handle_event({"event": "client-message", "args": ["track-release"]})
    t = _text(tl)
    assert "başladı: kişi ID 3" in t and "hedef kayboldu: kişi ID 3" in t
    assert "bitti: kişi ID 3 | sebep: bırakıldı" in t and "izlenen 2 kare, kayıp 1 kare" in t
    assert tl.feat["kişi tespiti"].ok == 2 and tl.feat["kişi tespiti"].idle == 1


def test_run_live_opens_log_per_video_and_closes(tmp_path):
    stop = threading.Event()
    path = {"v": "/v/live.mp4"}

    class Mpv:
        def __init__(self):
            self.t, self.grabs, self.texts = 0.0, 0, []

        def get_property(self, name):
            if name == "time-pos":
                self.t += 0.1
                return self.t
            if name == "path":
                return path["v"]
            if name == "video-params/w":
                return 200
            raise RuntimeError("yok")

        def command(self, *a):
            if a[0] == "show-text":
                self.texts.append(a[1])

        def set_view(self, v):
            pass

    mpv = Mpv()

    def grab(m):
        m.grabs += 1
        if m.grabs == 3:
            path["v"] = "/v/other.mp4"  # video değişti
        if m.grabs >= 6:
            stop.set()
        return FRAME

    tl = _tl(tmp_path)
    ev = queue.Queue()
    ev.put({"event": "client-message", "args": ["track-toggle", "on"]})
    ev.put(_click(90, 50))
    cfg = Config(ipc_path="x")
    cfg.live_fps = 1000.0
    clock = iter(range(0, 10_000, 2))  # her çağrı 2 sn: video denetimi her turda
    run_live(mpv, ev, _Pipe([[_tr(3, 85, 40, 95, 60)]]), cfg, grab=grab, stop=stop,
             log=lambda *_: None, sleep=lambda _s: None, tlog=tl, clock=lambda: next(clock))
    first = (tmp_path / "TakipLog" / log_name("/v/live.mp4")).read_text(encoding="utf-8")
    assert "Genişlik: 200" in first and "kişi ID 3" in first and "video değişti" in first
    assert (tmp_path / "TakipLog" / log_name("/v/other.mp4")).exists()
    assert "Hedef: ID 3" in "\n".join(mpv.texts)
    assert tl.video is None  # çıkışta kapandı
