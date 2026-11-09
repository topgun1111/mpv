"""Gömülü Python'u (python.org embeddable, amd64) hazırlar ve bağımlılıkları içine kurar.

Kullanım (Windows, CI): python scripts/build_embedded.py [--out dist/TakipliOynat] [--no-install]
Sonuç: <out>/python/python.exe (`python -m tracker`); pip ve test/önbellek dosyaları ayıklanır.
Saf mantık (`patch_pth`, `prune`) platformdan bağımsız testlidir; indirme/kurulum yalnız Windows'ta.
"""
from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_VERSION = "3.11.9"  # requirements: cp311 tekerlekleri (numpy/opencv/onnxruntime-directml)
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

# site-packages içinde çalışma zamanında gerekmeyen, boyut yapan kalemler
PRUNE_DIRS = {"__pycache__", "tests", "test", "testing", "_pyinstaller"}
PRUNE_TOP = ("pip", "setuptools", "wheel", "pkg_resources", "_distutils_hack")


def patch_pth(text: str) -> str:
    """`pythonXY._pth`: `import site` açılır (site-packages), uygulama kökü (`..`) yola eklenir
    (gömülü Python PYTHONPATH/cwd'yi yok sayar; `python -m tracker` kökten çalışsın)."""
    lines = [ln.rstrip("\r") for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln.strip().lstrip("#").strip() == "import site":
            ln = "import site"
        out.append(ln)
    if "import site" not in out:
        out.append("import site")
    if ".." not in out:
        idx = out.index("import site")
        out.insert(idx, "..")  # `import site` satırından önce: yol girdileri
    return "\n".join(out) + "\n"


def prune(site: Path) -> tuple[int, int]:
    """(silinen dizin, silinen dosya sayısı). numpy/opencv/onnxruntime çalışma zamanı etkilenmez."""
    dirs = files = 0
    if not site.is_dir():
        return 0, 0
    for p in sorted(site.rglob("*"), key=lambda q: len(q.parts), reverse=True):
        if p.is_dir() and p.name in PRUNE_DIRS and p.exists():
            shutil.rmtree(p)
            dirs += 1
        elif p.is_file() and p.suffix == ".pyc" and p.exists():
            p.unlink()
            files += 1
    for name in PRUNE_TOP:
        for p in list(site.glob(name)) + list(site.glob(f"{name}-*")):
            if p.is_dir():
                shutil.rmtree(p)
                dirs += 1
            else:
                p.unlink()
                files += 1
    return dirs, files


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "takipli-oynat-ci"})
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 (sabit https adresleri)
        return r.read()


def build(out: Path, install: bool = True) -> Path:
    py = out / "python"
    if py.exists():
        shutil.rmtree(py)
    py.mkdir(parents=True)
    print(f"Python {PY_VERSION} indiriliyor...")
    with zipfile.ZipFile(io.BytesIO(_download(PY_URL))) as z:
        z.extractall(py)
    pths = list(py.glob("python*._pth"))
    if len(pths) != 1:
        raise RuntimeError(f"_pth dosyası bulunamadı: {pths}")
    pths[0].write_text(patch_pth(pths[0].read_text(encoding="utf-8")), encoding="utf-8")
    if install:
        exe = py / "python.exe"
        gp = py / "get-pip.py"
        gp.write_bytes(_download(GET_PIP_URL))
        run = [str(exe), "-m", "pip", "install", "--no-warn-script-location",
               "--disable-pip-version-check"]
        subprocess.run([str(exe), str(gp), "--no-warn-script-location"], check=True)
        subprocess.run([*run, "-r", str(ROOT / "requirements.txt")], check=True)
        gp.unlink()
        dirs, files = prune(py / "Lib" / "site-packages")
        print(f"ayıklandı: {dirs} dizin, {files} dosya")
    mb = sum(p.stat().st_size for p in py.rglob("*") if p.is_file()) / 1e6
    print(f"gömülü Python hazır: {py} ({mb:.0f} MB)")
    return py


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist" / "TakipliOynat"))
    ap.add_argument("--no-install", action="store_true", help="yalnız Python'u aç (test)")
    a = ap.parse_args(argv)
    if sys.platform != "win32":
        print("Uyarı: gömülü Python yalnız Windows'ta çalışır; yine de dosyalar hazırlanır.")
    build(Path(a.out), install=not a.no_install)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
