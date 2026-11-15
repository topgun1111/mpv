"""Android record-only variant (android/rec): ayrı modül, AI/izleme yok, tam ekran + döndürme düğmeleri var."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANDROID = ROOT / "android"
REC = ANDROID / "rec"
SRC = REC / "src" / "main" / "kotlin" / "com" / "takipli" / "oynat" / "rec"


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _code(p: Path) -> str:
    """Dosya metni, // ve # açıklama satırları atılmış (açıklamada yasak sözcükler geçebilir)."""
    return "\n".join(l for l in _text(p).splitlines() if not l.strip().startswith(("//", "#")))


def test_rec_is_its_own_module_next_to_app():
    s = _text(ANDROID / "settings.gradle.kts")
    assert '":rec"' in s and '":app"' in s and '":core"' in s
    g = _text(REC / "build.gradle.kts")
    assert 'applicationId = "com.takipli.oynat.rec"' in g
    assert 'project(":core")' in g and 'project(":app")' not in g  # :app (pose/ONNX/OpenCV) is NOT a dependency


def test_rec_has_no_ai_tracking_or_network():
    g = _code(REC / "build.gradle.kts").lower()
    for banned in ("onnxruntime", "opencv", "qnn", "serialization"):
        assert banned not in g, banned
    m = _text(REC / "src" / "main" / "AndroidManifest.xml")
    for banned in ("INTERNET", "FOREGROUND_SERVICE", "REQUEST_INSTALL_PACKAGES", "ScanService"):
        assert banned not in m, banned
    for f in SRC.glob("*.kt"):
        t = _text(f)
        for banned in ("ai.onnxruntime", "org.opencv", "PoseRunner", "Scanner", "ScanService", "StabPlan", "TrackDoc"):
            assert banned not in t, (f.name, banned)


def test_rec_screen_has_fullscreen_overlay_and_rotation():
    t = _text(SRC / "RecScreen.kt")
    assert "fullscreen" in t and "WindowInsetsCompat.Type.systemBars()" in t  # sistem çubukları gizlenir
    assert "R.string.full_screen" in t  # normal önizlemede tam ekran düğmesi
    assert "rotate(-90)" in t and "rotate(90)" in t  # iki döndürme düğmesi
    assert t.count("rotate(-90)") >= 2 and t.count("rotate(90)") >= 2  # hem normal hem tam ekran düzeninde
    assert "detectTransformGestures" in t and "applyGestureAt" in t  # zoom + sürükleme aynı anda
    assert "BackHandler" in t  # geri tuşu tam ekrandan çıkar / kaydı durdurur
    e = _text(SRC / "RecExporter.kt")
    assert "rotationEffect(rot)" in e  # döndürme dışa aktarmaya da girer


def test_rec_strings_en_tr_match_and_formats_agree():
    res = REC / "src" / "main" / "res"
    en, tr = _text(res / "values" / "strings.xml"), _text(res / "values-tr" / "strings.xml")
    names = lambda s: set(re.findall(r'<string name="([^"]+)"', s))
    assert names(en) == names(tr)
    for n in names(en):
        pat = re.compile(r'<string name="%s">(.*?)</string>' % re.escape(n), re.S)
        fmt = lambda s: sorted(re.findall(r"%\d\$[sd]", pat.search(s).group(1)))
        assert fmt(en) == fmt(tr), n
    # her R.string.X kodda tanımlı
    used = set()
    for f in SRC.glob("*.kt"):
        used |= set(re.findall(r"R\.string\.([a-z_0-9]+)", _text(f)))
    assert used <= names(en), used - names(en)


def test_rec_workflow_is_separate_and_android_yml_untouched():
    w = _code(ROOT / ".github" / "workflows" / "android-rec.yml")
    assert ":rec:assembleRelease" in w and "export_pose" not in w and "export_sam2" not in w
    y = _text(ROOT / ".github" / "workflows" / "android.yml")
    assert ":rec" not in y
