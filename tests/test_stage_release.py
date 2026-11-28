"""Public staging verifies tracking packages and blocks restricted Android APKs."""
from pathlib import Path
from zipfile import ZipFile

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def stage_module(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import stage_release
    return stage_release


def _tracking_pair(tmp_path, version, *, forbidden=False):
    from public_tracking import REQUIRED

    exe = tmp_path / f"TakipliOynat-Setup-{version}.exe"
    zip_path = tmp_path / f"TakipliOynat-Portable-{version}.zip"
    exe.write_bytes(b"installer")
    with ZipFile(zip_path, "w") as z:
        for name in sorted(REQUIRED):
            z.writestr("TakipliOynat/" + name, b"test")
        if forbidden:
            z.writestr("TakipliOynat/models/yolov8s-pose.onnx", b"restricted")
    return exe, zip_path


def test_stage_filters_before_upload(tmp_path, stage_module, monkeypatch):
    rec = tmp_path / "TakipliOynatKayit-Setup-1.2.3-b4.exe"
    android = tmp_path / "TakipliOynat-Android-pose-1.2.3-b4.apk"
    rec.write_bytes(b"record")
    android.write_bytes(b"pose")
    calls = []
    monkeypatch.setattr(stage_module.subprocess, "check_output", lambda *a, **k: "true\n")
    monkeypatch.setattr(stage_module.subprocess, "run", lambda a, **k: calls.append(a))
    assert stage_module.stage([str(rec), str(android)], "v1.2.3-b4", False, False) == 0
    assert len(calls) == 1 and str(rec) in calls[0] and str(android) not in calls[0]
    assert stage_module.stage([str(android)], "v1.2.3-b4", False, False) == 0
    assert len(calls) == 1
    monkeypatch.setattr(stage_module.subprocess, "check_output", lambda *a, **k: "false\n")
    with pytest.raises(SystemExit, match="published"):
        stage_module.stage([str(rec)], "v1.2.3-b4", False, False)


def test_public_tracking_pair_is_verified_before_upload(tmp_path, stage_module, monkeypatch):
    exe, z = _tracking_pair(tmp_path, "1.2.3-b4")
    calls = []
    monkeypatch.setattr(stage_module.subprocess, "check_output", lambda *a, **k: "true\n")
    monkeypatch.setattr(stage_module.subprocess, "run", lambda a, **k: calls.append(a))
    with pytest.raises(ValueError, match="matching"):
        stage_module.stage([str(exe)], "v1.2.3-b4", False, False)
    assert stage_module.stage([str(exe), str(z)], "v1.2.3-b4", False, False) == 0
    assert len(calls) == 1 and str(exe) in calls[0] and str(z) in calls[0]
    _tracking_pair(tmp_path, "1.2.3-b4", forbidden=True)
    with pytest.raises(ValueError, match="extra="):
        stage_module.stage([str(exe), str(z)], "v1.2.3-b4", False, False)
    assert len(calls) == 1
    assert stage_module.stage([str(exe), str(z)], "v1.2.3-b4", True, False) == 0


def test_verify_rejects_wrong_version_and_forbidden_asset(tmp_path, stage_module):
    rec = tmp_path / "TakipliOynatKayit-Setup-1.2.3-b4.exe"
    rec.write_bytes(b"record")
    assert stage_module.verify(tmp_path, False, False, "1.2.3-b4") == 0
    with pytest.raises(SystemExit):
        stage_module.verify(tmp_path, False, False, "1.2.3-b5")
    _tracking_pair(tmp_path, "1.2.3-b4")
    assert stage_module.verify(tmp_path, False, False, "1.2.3-b4") == 0
    _tracking_pair(tmp_path, "1.2.3-b4", forbidden=True)
    with pytest.raises(ValueError, match="extra="):
        stage_module.verify(tmp_path, False, True, "1.2.3-b4")
    assert stage_module.verify(tmp_path, True, True, "1.2.3-b4") == 0


def test_complete_release_rejects_missing_variants(tmp_path, stage_module):
    version = "1.2.3-b4"
    _tracking_pair(tmp_path, version)
    with pytest.raises(SystemExit, match="Incomplete release"):
        stage_module.verify(tmp_path, False, False, version, complete=True)
    for name in (f"TakipliOynatKayit-Setup-{version}.exe",
                 f"TakipliOynatKayit-Portable-{version}.zip",
                 f"TakipliKayit-Android-{version}.apk"):
        (tmp_path / name).write_bytes(b"binary")
    assert stage_module.verify(tmp_path, False, False, version, complete=True) == 0
    with pytest.raises(SystemExit, match="Incomplete release"):
        stage_module.verify(tmp_path, True, False, version, complete=True)
    for flavor in ("pose", "sam"):
        (tmp_path / f"TakipliOynat-Android-{flavor}-{version}.apk").write_bytes(b"binary")
    assert stage_module.verify(tmp_path, True, False, version, complete=True) == 0
    (tmp_path / f"TakipliOynatKayit-Setup-{version}.exe").write_bytes(b"")
    with pytest.raises(SystemExit, match="Empty release asset"):
        stage_module.verify(tmp_path, True, False, version, complete=True)


def test_record_patch_is_validated_with_release_assets(tmp_path, stage_module):
    from hashlib import sha256

    from apk_delta import make_patch, reconstruct
    from release_assets import pick

    version = "1.2.3-b5"
    base_path = tmp_path.parent / "base.apk"
    target_path = tmp_path / f"TakipliKayit-Android-{version}.apk"
    for path, content in ((base_path, b"old"), (target_path, b"new")):
        with ZipFile(path, "w") as archive:
            archive.writestr("classes.dex", content)
            archive.writestr("assets/shared", bytes(range(256)) * 4096)
    base, target = base_path.read_bytes(), target_path.read_bytes()
    patch_name, patch = make_patch(base, target, target_path)
    assert len(patch) < len(target)
    assert reconstruct(base, patch) == target
    with pytest.raises(ValueError, match="base mismatch"):
        reconstruct(target, patch)
    with pytest.raises((ValueError, EOFError)):
        reconstruct(base, patch[:len(patch) // 2])
    patch_path = tmp_path / patch_name
    patch_path.write_bytes(patch)
    assert pick([patch_path], private=False, tag_release=False) == ([patch_path], [])
    _tracking_pair(tmp_path, version)
    for name in (f"TakipliOynatKayit-Setup-{version}.exe",
                 f"TakipliOynatKayit-Portable-{version}.zip"):
        (tmp_path / name).write_bytes(b"binary")
    assert stage_module.verify(tmp_path, False, False, version, complete=True) == 0
    target_path.write_bytes(target + b"tampered")
    assert sha256(target_path.read_bytes()).hexdigest() not in patch_name
    with pytest.raises(SystemExit, match="wrong recorder APK"):
        stage_module.verify(tmp_path, False, False, version, complete=True)
