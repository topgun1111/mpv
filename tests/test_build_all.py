"""build-all.yml: tek tetikleyici; diğerleri yeniden kullanılabilir (workflow_call).

Böylece hiçbir şey iki kez çalışmaz.
"""

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
    assert "error-log:" in t and "error-log.txt" in t and "actions: read" in t
    assert "if: ${{ !cancelled() }}" in t  # başarısız iş olsa da çalışır


def test_build_all_has_one_version_job_and_one_release_job():
    t = (WF / "build-all.yml").read_text(encoding="utf-8")
    assert "scripts/version.py check" in t and "release-info" in t  # sürüm tutarlılığı + etiket
    assert t.count("gh release create") == 2 and "--prerelease" in t and "--verify-tag" in t  # main = önsürüm, v* = Release
    assert "scripts/release_assets.py" in t and "SHA256SUMS" in t
    assert 'tags: ["v*"]' in t and "github.event_name == 'push'" in t  # PR / elle çalıştırma Release açmaz
    assert "release]" in t  # error-log Release işini de bekler
    for name in CALLED:  # her yapı önce sürüm denetimini bekler
        job = t.split(f"uses: ./.github/workflows/{name}")[0].rsplit("\n\n", 1)[-1]
        assert "needs: version" in job or "needs: [version, prepare]" in job, name


def test_only_build_all_publishes_releases():
    for name in CALLED:
        t = (WF / name).read_text(encoding="utf-8")
        assert "gh release create" not in t and "gh release edit" not in t and "softprops" not in t, name
        if name != "ci.yml":
            assert "scripts/stage_release.py upload" in t and "inputs.release_tag" in t
    for p in WF.glob("*.yml"):
        assert "actions/upload-artifact" not in p.read_text(encoding="utf-8"), p.name
        assert "actions/download-artifact" not in p.read_text(encoding="utf-8"), p.name
    all_wf = (WF / "build-all.yml").read_text(encoding="utf-8")
    assert "--draft" in all_wf and "--draft=false" in all_wf
    assert "gh release download" in all_wf and "scripts/stage_release.py verify" in all_wf
    assert "GH_REPO: ${{ github.repository }}" in all_wf
    assert "enableCrossOsArchive: true" in (WF / "build.yml").read_text(encoding="utf-8")
