"""kayit.lua (kayıt arayüzü) sahte `mp` ile çalıştırılır; Python `recorder` ile eşlik denetlenir."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from recorder import geometry as g
from recorder import keys as k

LUA = shutil.which("texlua") or shutil.which("lua") or shutil.which("luajit")
ROOT = Path(__file__).resolve().parent.parent
CONF = ROOT / "mpv" / "portable_config_recording"
KAYIT_LUA = CONF / "scripts" / "kayit.lua"
HARNESS = Path(__file__).with_name("lua_harness_kayit.lua")
# lua_harness_kayit.lua içindeki dizi ile AYNI olmalı (ax, ay, dx, dy, çarpan)
SEQ = [(0.5, 0.5, 0, 0, 1.5), (0.3, 0.6, 0.02, -0.01, 1.3), (0.8, 0.2, -0.05, 0.04, 1.0),
       (0.5, 0.5, 0, 0, 0.5), (0.1, 0.9, 0.1, -0.1, 3.0)]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    if LUA is None:
        pytest.skip("lua/texlua yok")
    tmp = tmp_path_factory.mktemp("kayit")
    video = tmp / "clip.mp4"
    video.write_bytes(b"x")
    env = {"KAYIT_LUA": str(KAYIT_LUA), "VIDEO": str(video)}
    r = subprocess.run([LUA, str(HARNESS)], env=env, capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    d: dict[str, list[str]] = {}
    for ln in r.stdout.splitlines():
        key, *rest = ln.split("\t")
        d.setdefault(key, []).append("\t".join(rest) if key in ("JSON", "SEG_JSON") else rest)
    return d, video


def fl(row):
    return [float(x) for x in row]


def test_lua_geometry_matches_python(run):
    d, _ = run
    assert fl(d["REF"][0]) == pytest.approx([1.0, -0.125, 0.125])  # Android referansı
    v = (0.0, 0.0, 0.0)
    for got, (ax, ay, dx, dy, f) in zip(d["SEQ"], SEQ):
        v = g.apply_gesture_at(v, ax, ay, dx, dy, f)
        assert fl(got) == pytest.approx(v, abs=1e-8)


def test_cursor_point_stays_under_cursor(run):
    d, _ = run
    zoom_only, zoom_and_drag = fl(d["INV"][0])
    assert zoom_only < 1e-9 and zoom_and_drag < 1e-9  # zoom + sürükleme: nokta imleçle kalır


def test_mouse_wheel_drag_and_keys(run):
    d, _ = run
    assert d["HUD0"][0] == ["true", "false"]  # zoom hep görünür; kayıt dışında KAYIT yok
    v = g.apply_gesture_at((0, 0, 0), 0.25, 0.25, 0, 0, 2 ** 0.25)
    assert fl(d["WHEEL1"][0]) == pytest.approx(v, abs=1e-8)
    z = (0.0, 0.0, 0.0)
    for i in range(8):  # 1 tekerlek @ (320,180) sonra 7 @ (640,360)
        a = 0.25 if i == 0 else 0.5
        z = g.apply_gesture_at(z, a, a, 0, 0, 2 ** 0.25)
    assert fl(d["ZOOM2"][0]) == pytest.approx(z, abs=1e-8) and z[0] == pytest.approx(2.0)
    # sürükleme: (640,360)→(700,380) piksel, 1280×720 pencere
    z = g.apply_gesture_at(z, 0.5, 0.5, 60 / 1280, 20 / 720, 1.0)
    assert fl(d["DRAG"][0]) == pytest.approx(z, abs=1e-8)
    # sürüklerken tekerlek: imleç (700,380) noktasında
    z = g.apply_gesture_at(z, 700 / 1280, 380 / 720, 0, 0, 2 ** 0.25)
    assert fl(d["DRAGWHEEL"][0]) == pytest.approx(z, abs=1e-8)
    z = g.apply_gesture_at(z, 700 / 1280, 380 / 720, -10 / 1280, -10 / 720, 1.0)
    assert fl(d["DRAGMORE"][0]) == pytest.approx(z, abs=1e-8)
    assert fl(d["NODRAG"][0]) == pytest.approx(z, abs=1e-8)  # tuş bırakılınca kayma yok
    zo = g.set_zoom_at(z, 0.5, 0.5, z[0] - 0.25)
    assert fl(d["KEYOUT"][0]) == pytest.approx(zo, abs=1e-8)
    zi = g.set_zoom_at(zo, 0.5, 0.5, zo[0] + 0.25)
    assert fl(d["KEYIN"][0]) == pytest.approx(zi, abs=1e-8)
    assert fl(d["RESET"][0][:3]) == [0.0, 0.0, 0.0] and d["RESET"][0][3] == "true"


def test_recording_writes_rec_json_readable_by_python(run):
    d, video = run
    assert d["PREARM"][0] == ["0"]  # seek bitmeden (playback-restart öncesi) anahtar yok
    before, after = d["NOKEY"][0]
    assert before == after  # duraklatma (saat ilerlemedi) anahtar üretmez
    assert d["HUDREC"][0] == ["true", "true"]  # ● KAYIT ... 1.2× (zoom göstergesi)
    assert d["ROT_REC"][0] == ["0", "true"]  # kayıt sırasında döndürme reddedilir
    assert d["STOP"][0] == ["false", "true"] and d["TMP"][0] == ["true"]

    doc = json.loads(d["JSON"][0])
    assert doc["version"] == 1 and doc["kind"] == "manual-camera" and doc["video"] == "clip.mp4"
    assert doc["rotate"] == 0 and doc["speed"] == 1.0 and "vsig" not in doc
    ks = doc["views"]
    assert ks[0][0] == 0.0 and len(ks) >= 30
    assert all(b[0] > a[0] for a, b in zip(ks, ks[1:])) and ks[-1][0] == pytest.approx(1.32)
    assert ks[10][1] == 0.0 and ks[-1][1] == pytest.approx(0.25)  # önce 1×, sonra 2^0.25
    # Python tarafı kaydı olduğu gibi kabul eder (vsig yok → imza denetimi atlanır)
    loaded = k.load_recording(video.with_name("clip.mp4.rec.json"), video=str(video))
    assert loaded["views"] == ks and loaded["rotate"] == 0


def test_rotate_speed_and_write_failure(run):
    d, _ = run
    assert d["ROT"][0] == ["90"]
    assert d["SPEED"][0] == ["1.5", "0.75"]  # 1.0 → 1.5; iki yavaşlatma: 1.0 → 0.75
    assert d["WRITEFAIL"][0] == ["true"]


def test_rewinds_are_recorded_as_repeated_segments(run):
    d, _ = run
    assert d["SEG_PRE"][0] == ["11"]  # seek bitmeden (playback-restart öncesi) anahtar yok
    doc = json.loads(d["SEG_JSON"][0])
    # 4 parça: 0→1.0, 0.5→1.0, 0.5→0.8, 0.2→0.3 (duraklıyken geri sarma dahil)
    assert doc["breaks"] == [11, 17, 21]
    ts = [r[0] for r in doc["views"]]
    assert ts[:11] == pytest.approx([i / 10 for i in range(11)]) and ts[11] == pytest.approx(0.5)
    assert ts[-2:] == pytest.approx([0.2, 0.3])
    assert d["SEG_T"][0] == ["1.90"]  # HUD: toplam kayıt süresi = parçaların toplamı
    segs = k.split_segments(doc["views"], doc["breaks"])
    assert [len(x) for x in segs] == [11, 6, 4, 2]


def test_rotate_buttons(run):
    d, _ = run
    # hazırken ► = +90°, ◄ = geri 0°; düğmeler HUD'da görünür
    assert d["ROT_BTN_READY"][0] == ["90", "0", "true"]
    # Space ile kayıt başlayınca düğmeler gizli, tık ve K döndürmez, K uyarı verir
    assert d["ROT_LOCK"][0] == ["0", "0", "false", "true"]


def test_export_flow_launches_recorder_and_reports(run):
    d, video = run
    out = str(video.with_name("clip.kamera.mp4"))
    assert d["EXP_NOREC"][0] == ["true", "true"]  # kayıt yok → uyarı, süreç başlamaz
    assert d["EXP_RECON"][0] == ["true", "true"]  # kayıt sürerken dışa aktarılamaz
    assert d["EXP_NOPY"][0] == ["true", "true"]  # python/ yok → anlaşılır uyarı
    assert d["EXP_PYFALLBACK"][0] == ["C:/app/python/python.exe"]  # pythonw yoksa python.exe
    args, playback_only, esc = d["EXP_ARGS"][0]
    assert args == f"C:/app/python/pythonw.exe|-m|recorder|export|{video}|--out|{out}"
    assert playback_only == "false" and esc == "true"  # duraklatınca durmaz; Esc bağı var
    assert d["EXP_BUSY"][0] == ["true"]  # ikinci E yeni süreç başlatmaz
    assert d["EXP_PROGRESS"][0] == ["true", "true"]  # %50 + Esc ipucu (.export.json'dan)
    assert d["EXP_CANCELFILE"][0] == ["true"]  # Esc → <çıktı>.export.cancel
    assert d["EXP_CANCELLED"][0] == ["true", "true"] and d["EXP_DONE"][0] == ["true", "true"]
    assert d["EXP_ERROR"][0] == ["true"] and d["EXP_NOJSON"][0] == ["true"]
    # Lua'nın çıktı adı Python'unkiyle aynı (bu dosya aynı kuralı iki yerden de türetir)
    assert out == k.default_out(str(video))


def test_ready_space_pause_resume_flow(run):
    d, _ = run
    # KAYDET/R: hazır — oynatma durur, kayıt henüz yok (HUD «HAZIR», ● yok)
    assert d["READY"][0] == ["yes", "true", "false", "true", "false"]
    # Space: geri sayım YOK — kayıt hemen başlar (video başa sarılır ve oynar)
    assert d["START"][0] == ["seek 0 absolute exact", "no", "true", "true"]
    # kayıtta Space = duraklat, anahtar yok
    assert d["PAUSED"][0] == ["false", "yes", "true", "true"]
    assert d["RESUMED"][0] == ["true", "no"]  # tekrar Space = sürdür


def test_screen_buttons_right_drag_and_s_export(run):
    d, video = run
    out = str(video.with_name("clip.kamera.mp4"))
    # sol tık: hız 1 → 1.5, düğmede görünür
    assert d["SPD_CLICK"][0] == ["1.5", "true"]
    # sağ tık yavaşlatır; 2× → 0.25× (döner)
    assert d["SPD_RIGHT"][0] == ["1.0"] and d["SPD_WRAP"][0] == ["0.25"]
    # KAYDET'siz Space: oynatma/kayıt başlamaz
    assert d["SPACE_IDLE"][0] == ["yes", "true", "false"]
    # düğme → hazır, DURDUR yazar
    assert d["BTN_READY"][0] == ["true", "false", "yes", "true", "true"]
    # sol tuş kaydırır; sağ tuş kaydırmaz; oynatma değişmez
    assert d["DRAG_BTN"][0] == ["true", "true", "yes"]
    assert d["BTN_STOP"][0] == ["false", "true", "true", "true"]  # durdu, otomatik dışa aktarma YOK
    assert d["S_EXPORT"][0] == [f"C:/app/python/pythonw.exe|-m|recorder|export|{video}|--out|{out}"]
    assert d["LOADED_ROTATION"][0] == ["0"]
    assert d["LOADED_PAUSED"][0] == ["yes"]  # video açılınca duraklı


def test_lua_has_screen_buttons():
    lua = KAYIT_LUA.read_text(encoding="utf-8")
    assert "KAYDET" in lua and "DURDUR" in lua and "HIZ" in lua and "modkeys" not in lua


def test_wiring_in_config_and_no_tracking_code():
    inp = (CONF / "input.conf").read_text(encoding="utf-8")
    lines = {ln.split(None, 1)[0]: ln for ln in inp.splitlines()
             if ln.strip() and not ln.startswith("#")}
    lua = KAYIT_LUA.read_text(encoding="utf-8")
    binds = {"MBTN_LEFT": "drag", "MBTN_RIGHT": "rclick", "WHEEL_UP": "wheel-in",
             "WHEEL_DOWN": "wheel-out", "SPACE": "space", "+": "zoom-in", "-": "zoom-out",
             "0": "reset", "r": "record", "[": "slower", "]": "faster", "k": "rotate",
             "s": "export"}
    for key, name in binds.items():
        assert lines[key].endswith(f"script-binding kayit/{name}"), key
        assert f'add_key_binding(nil, "{name}"' in lua
    # oynat/durdur YALNIZ alttaki düğmeyle: çift tık, P ve oynat/duraklat tuşları etkisiz
    for key in ("MBTN_LEFT_DBL", "p", "PAUSE", "PLAYPAUSE"):
        assert lines[key].endswith("ignore"), key
    conf = (CONF / "mpv.conf").read_text(encoding="utf-8")
    assert "pause=yes" in conf  # açılışta oynatma başlamaz
    assert 'require,"recordingmenu"' in lua
    low = lua.lower()
    assert not any(w in low for w in ("onnx", "yolo", "tracker", "track-point", "models"))


def test_responsive_hud_and_window_config(run):
    d, _ = run
    assert d["RESPONSIVE_HUD"][0] == ["true"]
    conf = (CONF / "mpv.conf").read_text(encoding="utf-8")
    for option in ("auto-window-resize=no", "keepaspect-window=no", "keepaspect=yes",
                   "force-window=yes", "idle=yes", "hidpi-window-scale=no"):
        assert option in conf


def test_gpu_playback_config_and_view_write_optimization(run):
    d, _ = run
    assert d["VIEW_WRITE_OPTIMIZATION"][0] == ["true"]
    conf = (CONF / "mpv.conf").read_text(encoding="utf-8")
    for option in ("vo=gpu", "gpu-api=d3d11", "gpu-context=d3d11", "hwdec=auto-copy",
                   "video-sync=display-resample", "interpolation=no", "framedrop=vo"):
        assert option in conf
