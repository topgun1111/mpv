"""Paket klasörünü hazırlar (mpv.exe'yi fetch_deps.ps1 ekler). İki varyant:
  main       (varsayılan) dist/TakipliOynat      — takip, modeller, offline (mevcut uygulama)
  recording  dist/TakipliOynatKayit — yalnız elle kamera (zoom+sürükle) + dışa aktarma; model YOK
Kullanım: python scripts/make_package.py [--variant main|recording] [--out DİZİN]

Çıktı yapısı (main):
  dist/TakipliOynat/
    mpv/portable_config/...   (mpv.conf, input.conf, scripts/track.lua)
    tracker/                  (Python paketi)
    models/                   (YOLO ONNX buraya konur; MODELLER.txt)
    Baslat.bat, Offline.bat   (başlatıcılar; python/ klasörünü build_embedded.py ekler)
    requirements.txt, README.md, VERSION, THIRD_PARTY_NOTICES.md (+ LICENSE varsa)
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist" / "TakipliOynat"
OUT_RECORDING = ROOT / "dist" / "TakipliOynatKayit"
VARIANTS = ("main", "recording")


def _copytree(src: Path, dst: Path) -> None:
    shutil.copytree(
        src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )


def _copy_launchers(src_dir: Path, out: Path) -> None:
    for bat in sorted(src_dir.glob("*.bat")):  # CRLF: cmd.exe için
        data = bat.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        (out / bat.name).write_bytes(data)


def _finish(out: Path, requirements: str) -> None:
    for name in ("README.md", "VERSION", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, out / name)
    shutil.copy2(ROOT / requirements, out / "requirements.txt")
    if (ROOT / "LICENSE").is_file():  # proje lisansı (sahibi ekler)
        shutil.copy2(ROOT / "LICENSE", out / "LICENSE")
    files = sum(1 for p in out.rglob("*") if p.is_file())
    print(f"Paket hazır: {out} ({files} dosya)")


def build_main(out: Path) -> None:
    _copytree(ROOT / "tracker", out / "tracker")
    _copytree(ROOT / "mpv" / "portable_config", out / "mpv" / "portable_config")
    (out / "models").mkdir()
    (out / "models" / ".gitkeep").touch()
    for name in ("MODELLER.txt", "manifest.json"):
        shutil.copy2(ROOT / "models" / name, out / "models" / name)
    _copy_launchers(ROOT / "launcher", out)
    _finish(out, "requirements.txt")


def build_recording(out: Path) -> None:
    """Kayıt varyantı: `recorder/` + kendi mpv ayarları; tracker/, models/, Offline.bat YOK."""
    _copytree(ROOT / "recorder", out / "recorder")
    _copytree(ROOT / "mpv" / "portable_config_recording", out / "mpv" / "portable_config")
    _copy_launchers(ROOT / "launcher_recording", out)
    _finish(out, "requirements-recording.txt")


def main(argv: list[str] | tuple[str, ...] = ()) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--variant", choices=VARIANTS, default="main")
    ap.add_argument("--out", help="çıktı klasörü (varsayılan: dist/TakipliOynat[Kayit])")
    a = ap.parse_args(list(argv))
    out = Path(a.out) if a.out else (OUT if a.variant == "main" else OUT_RECORDING)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (build_main if a.variant == "main" else build_recording)(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
