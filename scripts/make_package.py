"""dist/TakipliOynat/ klasörünü hazırlar (mpv.exe hariç; onu fetch_deps.ps1 ekler)."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist" / "TakipliOynat"


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "tracker", OUT / "tracker", ignore=ignore)
    shutil.copytree(ROOT / "mpv" / "portable_config", OUT / "mpv" / "portable_config")
    (OUT / "models").mkdir(parents=True)
    for name in ("README.md", "VERSION", "requirements.txt"):
        shutil.copy2(ROOT / name, OUT / name)
    print(f"Paket hazir: {OUT}")


if __name__ == "__main__":
    main()
