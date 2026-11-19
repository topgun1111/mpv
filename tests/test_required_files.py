"""Push eksik kaldıysa CI'da anlamsız ImportError/KeyError yerine net hata ver."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED = [
    "tracker/providers.py",
    "tracker/sam_bench.py",
    "mpv/portable_config_recording/input.conf",
    "android/core/src/main/kotlin/com/takipli/oynat/core/Tracking.kt",
]


def test_required_files_exist_and_not_empty():
    for rel in REQUIRED:
        p = ROOT / rel
        assert p.is_file(), f"eksik dosya (commit/push edilmemis?): {rel}"
        assert p.stat().st_size > 0, f"bos dosya: {rel}"


def test_providers_exports_installed_ort_packages():
    src = (ROOT / "tracker" / "providers.py").read_text(encoding="utf-8")
    assert "def installed_ort_packages(" in src
