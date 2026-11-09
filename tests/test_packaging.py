"""Parça 14: paketleme (gömülü Python yardımcıları, başlatıcılar, installer, IPC bekleme)."""
import importlib.util
import re
from pathlib import Path

from tracker.ipc import MpvIpcError, wait_for_ipc

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


emb = _load("build_embedded")
pkg = _load("make_package")

PTH = "python311.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n"


def test_patch_pth_enables_site_and_adds_app_root():
    out = emb.patch_pth(PTH)
    lines = out.splitlines()
    assert "import site" in lines and ".." in lines and "#import site" not in out
    assert lines.index("..") < lines.index("import site")  # yol girdileri önce
    assert emb.patch_pth(out) == out  # idempotent
    assert emb.patch_pth("python311.zip\r\n.\r\n").splitlines()[-1] == "import site"
    assert emb.patch_pth("import site\n").count("import site") == 1


def test_prune_removes_caches_tests_and_pip_only(tmp_path):
    sp = tmp_path / "site-packages"
    for d in ("numpy/core", "numpy/tests", "numpy/core/tests", "cv2/__pycache__", "pip",
              "pip-24.0.dist-info", "setuptools", "onnxruntime/capi"):
        (sp / d).mkdir(parents=True)
        (sp / d / "x.py").write_text("1")
    (sp / "numpy/core/m.cpython-311.pyc").write_bytes(b"")
    (sp / "onnxruntime/capi/onnxruntime.dll").write_bytes(b"MZ")
    dirs, files = emb.prune(sp)
    assert dirs >= 5 and files >= 1
    for gone in ("numpy/tests", "numpy/core/tests", "cv2/__pycache__", "pip", "setuptools",
                 "pip-24.0.dist-info"):
        assert not (sp / gone).exists(), gone
    assert (sp / "numpy/core/x.py").exists() and (sp / "onnxruntime/capi/onnxruntime.dll").exists()
    assert not (sp / "numpy/core/m.cpython-311.pyc").exists()
    assert emb.prune(tmp_path / "yok") == (0, 0)


def test_python_pin_matches_requirements_markers():
    assert re.fullmatch(r"3\.11\.\d+", emb.PY_VERSION)  # requirements cp311 tekerlekleri
    assert emb.PY_URL.endswith(f"python-{emb.PY_VERSION}-embed-amd64.zip")
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "onnxruntime-directml" in req and 'sys_platform == "win32"' in req  # DirectML varsayılan


def test_make_package_copies_launchers_with_crlf(tmp_path, monkeypatch):
    monkeypatch.setattr(pkg, "OUT", tmp_path / "TakipliOynat")
    assert pkg.main() == 0
    out = tmp_path / "TakipliOynat"
    for name in ("Baslat.bat", "Offline.bat", "VERSION", "README.md", "requirements.txt",
                 "models/MODELLER.txt", "tracker/main.py", "mpv/portable_config/input.conf"):
        assert (out / name).is_file(), name
    raw = (out / "Baslat.bat").read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")  # tüm satır sonları CRLF
    assert not list(out.rglob("__pycache__"))


def test_launchers_use_embedded_python_and_wait_for_mpv():
    live = (ROOT / "launcher" / "Baslat.bat").read_text(encoding="utf-8")
    assert r"python\python.exe" in live and "-m tracker" in live
    assert "live --wait" in live and "mpv\\mpv.exe" in live
    assert "--reid --team" in live and "osnet_x0_25.onnx" in live and "--number" in live
    assert "%APPDATA%" in live  # Program Files'a yazma sorunu: config kullanıcı klasöründe
    off = (ROOT / "launcher" / "Offline.bat").read_text(encoding="utf-8")
    assert "offline-view" in off and "--target-id" in off and "%~1.track.json" in off
    for t in (live, off):
        assert t.isascii() or "chcp 65001" in t  # UTF-8 kod sayfası ya da ASCII
        assert "yolox_s" in t and "yolov8n" in t and "HASMODEL" in t  # model eksikse anlaşılır hata
        msg = t.split("HASMODEL")[-1].split("echo HATA")[1].split("\n")[0]
        assert "(" not in msg  # echo içindeki parantez if bloğunu bozar


def test_installer_references_existing_files_and_win10_directml():
    iss = (ROOT / "installer.iss").read_text(encoding="utf-8")
    assert "MinVersion=10.0.18362" in iss and "ArchitecturesAllowed=x64compatible" in iss
    for bat in re.findall(r'\{app\}\\(\w+\.bat)', iss):
        assert (ROOT / "launcher" / bat).is_file(), bat
    assert 'Excludes: "models\\*.onnx"' in iss  # AGPL/lisans: model kurulumla dağıtılmaz
    assert "uninsneveruninstall" in iss
    assert 'MessagesFile: "compiler:Languages\\Turkish.isl"' in iss


def test_build_workflow_orders_steps_and_checks_directml():
    wf = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
    order = [wf.index(k) for k in ("make_package.py", "build_embedded.py", "fetch_deps.ps1",
                                   "DmlExecutionProvider", "Compress-Archive", "iscc")]
    assert order == sorted(order)


def test_wait_for_ipc_retries_until_open_then_gives_up():
    calls, slept = [], []
    now = [0.0]

    def connect_ok_on_3rd():
        calls.append(1)
        if len(calls) < 3:
            raise MpvIpcError("yok")

    assert wait_for_ipc("p", 10, connect=connect_ok_on_3rd, sleep=lambda s: slept.append(s) or
                        now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    assert len(calls) == 3 and slept == [0.5, 0.5]

    now[0], calls.clear()

    def never():
        calls.append(1)
        raise MpvIpcError("yok")

    assert not wait_for_ipc("p", 1.0, connect=never,
                            sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    assert len(calls) == 3  # t=0, 0.5, 1.0 → süre doldu
    assert wait_for_ipc("p", 0, connect=lambda: None)


def test_cli_missing_config_uses_defaults_and_live_wait_failure(tmp_path, monkeypatch, capsys):
    import tracker.ipc as ipc
    from tracker.main import main

    monkeypatch.setattr(ipc, "wait_for_ipc", lambda path, timeout, **kw: False)
    missing = tmp_path / "yeni" / "config.json"
    assert main(["--config", str(missing), "live", "--wait", "5"]) == 1  # config yok → hata değil
    assert "IPC kanalı açılmadı" in capsys.readouterr().err
    from tracker.config import Config

    Config(ipc_path="x").save(missing)  # üst klasör yoksa oluşturulur
    assert missing.is_file()


def test_config_save_creates_parent_dirs(tmp_path):
    from tracker.config import Config

    p = tmp_path / "a" / "b" / "c.json"
    Config(ipc_path="x", target_fill=0.4).save(p)
    assert Config.load(p).target_fill == 0.4
