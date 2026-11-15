"""build-all.yml: tek tetikleyici; diğer iş akışları yeniden kullanılabilir (workflow_call), böylece hiçbir şey iki kez çalışmaz."""
from pathlib import Path

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows"
CALLED = ["ci.yml", "build.yml", "build-recording.yml", "android.yml", "android-rec.yml"]


def test_build_all_calls_every_build():
    t = (WF / "build-all.yml").read_text(encoding="utf-8")
    for name in CALLED:
        assert f"uses: ./.github/workflows/{name}" in t, name
    assert "pull_request" in t and "workflow_dispatch" in t


def test_called_workflows_have_no_own_push_trigger():
    for name in CALLED:
        t = (WF / name).read_text(encoding="utf-8")
        assert "workflow_call:" in t, name
        assert "push:" not in t and "pull_request:" not in t, name
        assert "concurrency:" not in t, name  # tek grup build-all.yml'de


def test_build_all_collects_one_error_log():
    t = (WF / "build-all.yml").read_text(encoding="utf-8")
    assert "error-log:" in t and "name: error-log" in t and "actions: read" in t
    assert "if: ${{ !cancelled() }}" in t  # başarısız iş olsa da çalışır
