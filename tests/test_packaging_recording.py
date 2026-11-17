"""R3: kayıt varyantı dağıtımı — installer, workflow, başlatıcılar, belgeler, hata kanalı."""
import importlib.util
import re
import sys
from pathlib import Path

from recorder import main as rmain
from recorder.export import _write_state, state_path

ROOT = Path(__file__).resolve().parent.parent
ISS = ROOT / "installer-recording.iss"
WF = ROOT / ".github" / "workflows" / "build-recording.yml"
CONF = ROOT / "mpv" / "portable_config_recording"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _appid(text):
    return re.search(r"AppId=\{\{([0-9A-Fa-f-]+)\}", text).group(1).lower()


def test_installer_is_independent_and_model_free():
    iss = ISS.read_text(encoding="utf-8")
    main_iss = (ROOT / "installer.iss").read_text(encoding="utf-8")
    assert _appid(iss) != _appid(main_iss)  # ana uygulamayla yan yana kurulabilir
    assert "DefaultDirName={autopf}\\TakipliOynatKayit" in iss
    assert "OutputDir=dist\\installer-recording" in iss and "OutputDir=dist\\installer" in main_iss
    assert 'Source: "dist\\TakipliOynatKayit\\*"' in iss
    assert "10.0.18362" not in iss and "MinVersion=10.0" in iss  # DirectML gerekmiyor
    low = "\n".join(ln for ln in iss.splitlines() if not ln.startswith(";")).lower()  # yorumsuz
    assert "models" not in low and "onnx" not in low and "tracker" not in low
    for needed in ("{app}\\python", "{app}\\recorder", "{app}\\ffmpeg",
                   "{app}\\mpv\\portable_config\\scripts"):
        assert needed in iss  # güncellemede eski sürüm artığı silinir
    assert 'MessagesFile: "compiler:Languages\\Turkish.isl"' in iss
    for bat in re.findall(r"\{app\}\\(\w[\w-]*\.bat)", iss):
        assert (ROOT / "launcher_recording" / bat).is_file(), bat
    assert "Disa-Aktar.bat" in iss and "THIRD_PARTY_NOTICES.md" in iss
    assert "-Wait" not in iss and "skipifsilent" in iss


def test_workflow_orders_steps_and_forbids_models():
    wf = WF.read_text(encoding="utf-8")
    keys = ("pytest -q", "make_package.py --variant recording", "build_embedded.py",
            "fetch_deps.ps1", "fetch_ffmpeg.ps1", "recorder --version", "recorder export",
            "Compress-Archive", "iscc", "installer-recording.iss")
    order = [wf.index(k) for k in keys]
    assert order == sorted(order)
    assert "--requirements requirements-recording.txt" in wf
    assert "dist/TakipliOynatKayit" in wf and "dist/TakipliOynat/" not in wf
    for banned in ("fetch_model", "export_pose", "export_reid", "export_wholebody",
                   "DmlExecutionProvider", "requirements.txt", "pip install ultralytics"):
        assert banned not in wf, banned
    assert "find_spec('onnxruntime')" in wf and "*.onnx" in wf  # onnxruntime/model yok denetlenir
    all_wf = (ROOT / ".github" / "workflows" / "build-all.yml").read_text(encoding="utf-8")
    # ortak sürüm: tek `v*` etiketi her uygulamayı derler ve tek Release açar (kayit-v* kaldırıldı)
    assert 'tags: ["v*"]' in all_wf and "kayit-v" not in all_wf and "kayit-v" not in wf
    assert "workflow_dispatch" in wf and "windows-latest" in wf
    assert "TakipliOynatKayit-Setup" in wf and "TakipliOynatKayit-Portable" in wf


def test_main_variant_files_untouched_by_recording():
    wf = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    assert "recording" not in wf.lower() and "kayit" not in wf.lower()
    iss = (ROOT / "installer.iss").read_text(encoding="utf-8")
    assert "recorder" not in iss and "Kayit" not in iss
    assert "recorder" not in (ROOT / "mpv" / "portable_config" / "scripts" / "track.lua"
                              ).read_text(encoding="utf-8")


def test_export_launcher_bat():
    bat = (ROOT / "launcher_recording" / "Disa-Aktar.bat").read_text(encoding="utf-8")
    assert "-m recorder export" in bat and 'python\\python.exe' in bat
    assert '%~1.rec.json' in bat  # kayıt yoksa anlaşılır hata (Python'a gitmeden)
    assert bat.isascii() or "chcp 65001" in bat
    assert "PYTHONUTF8=1" in bat
    assert not any(ln.rstrip().endswith("(") for ln in bat.splitlines())  # if bloğu yok:
    # echo içindeki parantez/özel karakter blok bozmasın
    for label in (":usage", ":norec", ":nopy", ":fail"):
        assert label in bat
    assert bat.count("pause") >= 4  # pencere hatayı okumadan kapanmaz


def test_make_package_recording_ships_export_flow(tmp_path):
    pkg = _load("make_package")
    out = tmp_path / "Kayit"
    assert pkg.main(["--variant", "recording", "--out", str(out)]) == 0
    for name in ("Disa-Aktar.bat", "Kayit.bat", "mpv/portable_config/scripts/kayit.lua",
                 "mpv/portable_config/input.conf", "recorder/export.py"):
        assert (out / name).is_file(), name
    for bat in ("Disa-Aktar.bat", "Kayit.bat"):
        raw = (out / bat).read_bytes()
        assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    assert not list(out.rglob("*.onnx")) and not (out / "tracker").exists()
    assert not (out / "models").exists()
    assert (out / "THIRD_PARTY_NOTICES.md").is_file()


def test_lua_and_python_agree_on_export_command_and_state_file():
    lua = (CONF / "scripts" / "kayit.lua").read_text(encoding="utf-8")
    assert '"-m", "recorder", "export"' in lua and "pythonw.exe" in lua and "python.exe" in lua
    assert '".kamera.mp4"' in lua and '".export.json"' in lua and '".export.cancel"' in lua
    assert "~~exe_dir/" in lua  # <mpv klasörünün üstü>/python/ (build_embedded.py yerleşimi)
    # Python'un yazdığı durum dosyası Lua'nın alan okuyucusuyla (aynı desenler) okunur
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.mp4.export.json"
        _write_state(p, "running", 5, 10)
        t = p.read_text(encoding="utf-8")
        assert re.search(r'"state"\s*:\s*"([^"]*)"', t).group(1) == "running"
        assert re.search(r'"pct"\s*:\s*(\d+)', t).group(1) == "50"
        _write_state(p, "error", 0, 0, "video açılamadı")
        t = p.read_text(encoding="utf-8")
        err = re.search(r'"error"\s*:\s*"([^"]*)"', t).group(1)
        assert err == "video açılamadı"  # ASCII dışı harfler kaçışsız yazılır


def test_cli_failure_is_reported_in_state_file(tmp_path, capsys):
    video = tmp_path / "yok.mp4"
    out = tmp_path / "cikti.mp4"
    assert rmain.main(["export", str(video), "--out", str(out)]) == 1  # kayıt dosyası yok
    st = state_path(out).read_text(encoding="utf-8")
    assert '"state": "error"' in st and "yok.mp4" in st  # pythonw'da konsol yok: dosyadan okunur
    assert "HATA" in capsys.readouterr().err


def test_utf8_stdio_never_crashes_without_streams(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    rmain._utf8_stdio()  # pythonw: akış yok → sessizce geç


def test_docs_cover_recording_variant():
    notes = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    sec = notes.split("## 3c.")[1].split("## 4.")[0]
    assert "onnx runtime" in sec.lower() and "UYGULANMAZ" in sec
    assert "ffmpeg" in sec and "mpv" in sec
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Kayıt varyantı (R1–R3)" in readme and "<video>.kamera.mp4" in readme
    assert "Disa-Aktar.bat" in readme and "kayit-v" not in readme
    assert "`S`" in (ROOT / "README.md").read_text(encoding="utf-8")
    inp = (CONF / "input.conf").read_text(encoding="utf-8")
    assert re.search(r"^s script-binding kayit/export$", inp, re.M)
