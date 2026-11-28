"""Android record-only variant (android/rec): ayrı modül, AI/izleme yok, tam ekran + döndürme."""
import re
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
ANDROID = ROOT / "android"
REC = ANDROID / "rec"
SRC = REC / "src" / "main" / "kotlin" / "com" / "takipli" / "oynat" / "rec"


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _code(p: Path) -> str:
    """Dosya metni; // ve # açıklama satırları atılmış (açıklamada yasak sözcükler geçebilir)."""
    lines = _text(p).splitlines()
    return "\n".join(x for x in lines if not x.strip().startswith(("//", "#")))


def _strings(xml: str) -> dict[str, list[str]]:
    return {
        entry.attrib["name"]: sorted(re.findall(r"%\d+\$(?:\.\d+)?[sdf]", entry.text or ""))
        for entry in ElementTree.fromstring(xml).findall("string")
    }


def test_rec_is_its_own_module_next_to_app():
    s = _text(ANDROID / "settings.gradle.kts")
    assert '":rec"' in s and '":app"' in s and '":core"' in s
    g = _text(REC / "build.gradle.kts")
    assert 'applicationId = "com.takipli.oynat.rec"' in g
    # :app (pose/ONNX/OpenCV) bağımlılık DEĞİL
    assert 'project(":core")' in g and 'project(":app")' not in g


def test_rec_has_no_ai_tracking_and_only_updater_permissions():
    g = _code(REC / "build.gradle.kts").lower()
    for banned in ("onnxruntime", "opencv", "qnn", "serialization"):
        assert banned not in g, banned
    m = _text(REC / "src" / "main" / "AndroidManifest.xml")
    assert set(re.findall(r'<uses-permission android:name="([^"]+)"', m)) == {
        "android.permission.INTERNET",
        "android.permission.REQUEST_INSTALL_PACKAGES",
    }
    assert 'android:exported="false"' in m
    for banned in ("FOREGROUND_SERVICE", "ScanService"):
        assert banned not in m, banned
    for f in SRC.glob("*.kt"):
        t = _text(f)
        banned_code = (
            "ai.onnxruntime", "org.opencv", "PoseRunner", "Scanner",
            "ScanService", "StabPlan", "TrackDoc",
        )
        for banned in banned_code:
            assert banned not in t, (f.name, banned)


def test_rec_screen_has_fullscreen_overlay_and_rotation():
    t = _text(SRC / "RecScreen.kt")
    assert "fullscreen" in t and "WindowInsetsCompat.Type.systemBars()" in t  # sistem çubukları
    assert "R.string.full_screen" in t  # normal önizlemede tam ekran düğmesi
    # iki döndürme düğmesi, hem normal hem tam ekran düzeninde
    assert t.count("rotate(-90)") >= 2 and t.count("rotate(90)") >= 2
    assert "detectTransformGestures" in t and "applyGestureAt" in t  # zoom + sürükleme birlikte
    assert "BackHandler" in t  # geri tuşu tam ekrandan çıkar / kaydı durdurur
    e = _text(SRC / "RecExporter.kt")
    assert "rotationEffect(info.userRot)" in e  # döndürme dışa aktarmaya da girer
    assert "outputBitrate >= sourceBitrate" in e
    assert "extractor.sampleSize" in _text(SRC / "RecVideo.kt")
    for screen in ("RecScreen.kt", "RecEditingScreen.kt"):
        code = _text(SRC / screen)
        assert "RecExportOptions(" in code
        assert code.index("RecExporter.verifyQuality(") < code.index("RecExporter.saveToMovies(")


def test_rec_strings_en_tr_match_and_formats_agree():
    res = REC / "src" / "main" / "res"
    en = _strings(_text(res / "values" / "strings.xml"))
    tr = _strings(_text(res / "values-tr" / "strings.xml"))
    assert en == tr
    used = set()  # kodda kullanılan her R.string.X tanımlı olmalı
    for f in SRC.glob("*.kt"):
        used |= set(re.findall(r"(?<!android\.)\bR\.string\.([a-z_0-9]+)", _text(f)))
    assert used <= en.keys(), used - en.keys()


def test_rec_workflow_is_separate_and_android_yml_untouched():
    w = _code(ROOT / ".github" / "workflows" / "android-rec.yml")
    assert ":rec:assembleRelease" in w and "export_pose" not in w and "export_sam2" not in w
    y = _text(ROOT / ".github" / "workflows" / "android.yml")
    assert ":rec" not in y
