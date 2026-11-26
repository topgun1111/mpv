"""Draft staging never uploads files excluded by the existing release policy."""
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def stage_module(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import stage_release
    return stage_release


def test_stage_filters_before_upload(tmp_path, stage_module, monkeypatch):
    full = tmp_path / "TakipliOynat-Setup-1.2.3-b4.exe"
    rec = tmp_path / "TakipliOynatKayit-Setup-1.2.3-b4.exe"
    full.write_bytes(b"full")
    rec.write_bytes(b"record")
    calls = []
    monkeypatch.setattr(stage_module.subprocess, "check_output", lambda *a, **k: "true\n")
    monkeypatch.setattr(stage_module.subprocess, "run", lambda a, **k: calls.append(a))
    assert stage_module.stage([str(tmp_path / "*.exe")], "v1.2.3-b4", False, False) == 0
    assert len(calls) == 1 and str(rec) in calls[0] and str(full) not in calls[0]
    assert stage_module.stage([str(full)], "v1.2.3-b4", False, False) == 0
    assert len(calls) == 1
    monkeypatch.setattr(stage_module.subprocess, "check_output", lambda *a, **k: "false\n")
    with pytest.raises(SystemExit, match="published"):
        stage_module.stage([str(rec)], "v1.2.3-b4", False, False)


def test_verify_rejects_wrong_version_and_forbidden_asset(tmp_path, stage_module):
    rec = tmp_path / "TakipliOynatKayit-Setup-1.2.3-b4.exe"
    rec.write_bytes(b"record")
    assert stage_module.verify(tmp_path, False, False, "1.2.3-b4") == 0
    with pytest.raises(SystemExit):
        stage_module.verify(tmp_path, False, False, "1.2.3-b5")
    (tmp_path / "TakipliOynat-Setup-1.2.3-b4.exe").write_bytes(b"full")
    with pytest.raises(SystemExit):
        stage_module.verify(tmp_path, False, False, "1.2.3-b4")
    assert stage_module.verify(tmp_path, False, True, "1.2.3-b4") == 0
