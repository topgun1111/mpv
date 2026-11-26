"""Ortak sürüm: tek VERSION, her yerde aynı; CI etiketi/önsürüm kuralı; Release dosya seçimi (AGPL kuralı)."""
import importlib.util
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_pinned_version_matches_VERSION():
    v = _load("version")
    assert v.problems() == []
    assert re.fullmatch(r"\d+\.\d+\.\d+", v.read_version())


def test_bump_rules():
    v = _load("version")
    assert v.bump("1.2.3", "patch") == "1.2.4"
    assert v.bump("1.2.3", "minor") == "1.3.0"
    assert v.bump("1.2.3", "major") == "2.0.0"
    assert v.bump("1.2.3", "4.5.6") == "4.5.6"
    with pytest.raises(SystemExit):
        v.bump("1.2.3", "huge")


def test_bump_updates_tracker_recorder_and_license_test(tmp_path, monkeypatch):
    v = _load("version")
    for rel in ("VERSION", "tracker/__init__.py", "recorder/__init__.py", "tests/test_license.py",
                "android/app/build.gradle.kts", "android/rec/build.gradle.kts"):
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, dst)
    monkeypatch.setattr(v, "ROOT", tmp_path)
    cur = v.read_version()
    assert v.problems(tmp_path) == []
    v.apply("9.8.7", cur)
    assert (tmp_path / "VERSION").read_text().strip() == "9.8.7"
    assert v.problems(tmp_path) == []  # recorder dahil hiçbiri geride kalmadı
    (tmp_path / "recorder/__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    assert any("recorder" in p for p in v.problems(tmp_path))


def test_release_info_main_is_prerelease_and_tag_is_release():
    v = _load("version")
    main = v.release_info("refs/heads/main", 45, "1.2.0")
    assert main == {"version": "1.2.0", "build": "45", "full": "1.2.0-b45", "tag": "v1.2.0-b45", "prerelease": "true"}
    rel = v.release_info("refs/tags/v1.2.0", 46, "1.2.0")
    assert rel["tag"] == "v1.2.0" and rel["prerelease"] == "false" and rel["full"] == "1.2.0-b46"
    with pytest.raises(SystemExit):  # etiket VERSION ile aynı olmalı
        v.release_info("refs/tags/v1.3.0", 46, "1.2.0")
    with pytest.raises(SystemExit):  # eski kayit-v* gibi etiketler kabul edilmez
        v.release_info("refs/tags/kayit-v1.2.0", 46, "1.2.0")


def test_android_version_code_matches_release_file_names():
    """Android sürüm kodu = (X*10000+Y*100+Z)*1000 + yapı no; dosya adı X.Y.Z-b<no> (Updater.kt ikisini birlikte okur)."""
    g = (ROOT / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert "* 1000 + buildNumber" in g and "coerceIn(0, 999)" in g
    assert _load("version").MAX_BUILD == 999


def _touch(d, names):
    for n in names:
        (d / n).write_bytes(n.encode())


ALL = ["TakipliOynat-Setup-1.2.0-b5.exe", "TakipliOynat-Portable-1.2.0-b5.zip",
       "TakipliOynatKayit-Setup-1.2.0-b5.exe", "TakipliOynatKayit-Portable-1.2.0-b5.zip",
       "TakipliOynat-Android-pose-1.2.0-b5.apk", "TakipliOynat-Android-sam-1.2.0-b5.apk",
       "TakipliKayit-Android-1.2.0-b5.apk"]


@pytest.mark.parametrize("private,tag,expected_missing", [
    (True, False, set()),
    (True, True, set()),
    (False, False, {ALL[0], ALL[1], ALL[4], ALL[5]}),  # genel depo, main: AGPL modelli her şey dışarıda
    (False, True, {ALL[4], ALL[5]}),                   # genel depo, v* etiketi: PC ana eskisi gibi eklenir, Android hayır
])
def test_release_assets_follow_the_agpl_rule(tmp_path, private, tag, expected_missing):
    ra = _load("release_assets")
    d = tmp_path / "files"
    d.mkdir()
    _touch(d, [*ALL, "TakipliOynat-Android-pose-1.2.0-debug.apk"])
    chosen, _ = ra.pick(list(d.iterdir()), private, tag)
    assert {p.name for p in chosen} == set(ALL) - expected_missing


def test_release_assets_main_writes_list_notes_and_checksums(tmp_path):
    ra = _load("release_assets")
    d = tmp_path / "files"
    d.mkdir()
    _touch(d, ALL)
    lst, notes = tmp_path / "assets.txt", tmp_path / "notes.md"
    argv = [str(d), "--private", "false", "--tag-release", "false", "--list", str(lst), "--notes", str(notes)]
    assert ra.main(argv) == 0
    listed = [Path(x) for x in lst.read_text().splitlines()]  # Windows'ta ters eğik çizgi: Path ile karşılaştır
    assert d / "SHA256SUMS.txt" in listed and len(listed) == 4  # 3 kayıt dosyası + SHA256SUMS
    assert "AGPL" in notes.read_text() and "TakipliKayit-Android" in notes.read_text()
    assert "TakipliOynatKayit-Setup-1.2.0-b5.exe" in (d / "SHA256SUMS.txt").read_text()
    empty = tmp_path / "empty"
    empty.mkdir()
    assert ra.main([str(empty), "--private", "true", "--tag-release", "false", "--list", str(lst), "--notes", str(notes)]) == 1


def test_workflows_name_every_file_with_the_shared_version():
    for wf in ("build.yml", "build-recording.yml"):
        t = (WF / wf).read_text(encoding="utf-8")
        assert '$full = "$v-b${{ github.run_number }}"' in t, wf
        assert "softprops" not in t and "Release" not in t.split("Dosyaları adlandır")[1], wf
    a = (WF / "android.yml").read_text(encoding="utf-8")
    assert "gh release" not in a and "$v-b${{ github.run_number }}.apk" in a
    r = (WF / "android-rec.yml").read_text(encoding="utf-8")
    assert "$v-b${{ github.run_number }}.apk" in r


def test_no_debug_builds_or_artifacts():
    for name in ("android.yml", "android-rec.yml"):
        t = (WF / name).read_text(encoding="utf-8")
        assert "Debug" not in t and "-debug" not in t, name
        assert "upload-artifact" not in t and "scripts/stage_release.py upload" in t, name
