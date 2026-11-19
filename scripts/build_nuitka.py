"""Build the Windows tracker as a Nuitka one-file executable.

Run from the repository root on Windows after installing requirements.txt:
    python scripts/build_nuitka.py --out dist/TakipliOynat
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build(out: Path) -> Path:
    if sys.platform != "win32":
        raise SystemExit("Nuitka Windows executable build must run on Windows.")
    python = Path(sys.executable)
    # Compile against the same environment that owns the runtime dependencies.
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "Nuitka"], check=True)
    exe = out / "tracker.exe"
    out.mkdir(parents=True, exist_ok=True)
    if exe.exists():
        exe.unlink()
    command = [
        str(python), "-m", "nuitka",
        "--onefile",
        "--assume-yes-for-downloads",
        "--windows-console-mode=force",
        f"--output-dir={out}",
        "--output-filename=tracker.exe",
        "--enable-plugin=numpy",
        # Yalnız kendi paketimiz C'ye derlenir; numpy/cv2/onnxruntime import'lardan bulunur.
        # (--include-package ile üçüncü taraf paket derlemek derlemeyi saatlere uzatıyordu.)
        "--include-package=tracker",
        "--include-package-data=onnxruntime",
        "--include-package-data=cv2",
        "--nofollow-import-to=numpy.tests,numpy.f2py,matplotlib,scipy,tkinter,pytest",
        f"--jobs={os.cpu_count() or 2}",
        "--lto=no",
        "--show-scons",
        str(ROOT / "scripts" / "tracker_entry.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    if not exe.is_file() or exe.stat().st_size < 1_000_000:
        raise RuntimeError(f"Nuitka did not produce a valid tracker.exe: {exe}")
    print(f"Standalone tracker ready: {exe} ({exe.stat().st_size / 1e6:.1f} MB)")
    return exe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "dist" / "TakipliOynat"))
    args = parser.parse_args(argv)
    build(Path(args.out).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
