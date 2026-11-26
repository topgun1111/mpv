"""Test the public-payload preparation step."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_public_preparation_preserves_models_and_removes_optional_weights(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import public_tracking as pub

    models = tmp_path / "models"
    models.mkdir()
    files = [
        {"path": "models/yolox_s.onnx", "min_bytes": 1, "license": "Apache-2.0",
         "license_file": "models/YOLOX_LICENSE.txt", "sha256": None},
        {"path": "models/yolov8s-pose.onnx", "min_bytes": 1, "license": "AGPL-3.0"},
    ]
    (models / "manifest.json").write_text(json.dumps({"version": 1, "files": files}))
    for name in ("yolox_s.onnx", "YOLOX_LICENSE.txt", "MODELLER.txt",
                 "yolov8s-pose.onnx", "yolo11m-pose.onnx", "osnet_x0_25.onnx",
                 "rtmpose-wholebody.onnx"):
        (models / name).write_bytes(b"x")
    for name in pub.SAM_FILES - {"sam-models/APACHE_LICENSE.txt", "sam-models/NOTICE.txt"}:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    pub.prepare(tmp_path)
    assert (models / "yolox_s.onnx").is_file()
    assert not (models / "yolov8s-pose.onnx").exists()
    assert not (models / "osnet_x0_25.onnx").exists()
    assert not (models / "rtmpose-wholebody.onnx").exists()
    assert not (models / "yolo11m-pose.onnx").exists()
    assert "yolov8s-pose" not in (models / "manifest.json").read_text(encoding="utf-8")
    assert "yolov8s-pose" not in (models / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert (tmp_path / "sam-models/APACHE_LICENSE.txt").is_file()
    pub.verify_model_paths(set(pub.REQUIRED))
    with pytest.raises(ValueError, match="extra="):
        pub.verify_model_paths(set(pub.REQUIRED) | {"models/unknown.onnx"})


def test_public_pruning_happens_after_model_smoke_tests_before_both_packages():
    wf = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
    order = [wf.index(x) for x in (
        "EDITING_MPV_SMOKE_OK", "scripts/public_tracking.py dist/TakipliOynat",
        "Compress-Archive", "Installer derle", "scripts/stage_release.py upload",
    )]
    assert order == sorted(order)
    assert "if: ${{ !github.event.repository.private }}" in wf
    iss = (ROOT / "installer.iss").read_text(encoding="utf-8")
    section = iss.split("[InstallDelete]", 1)[1].split("\n[", 1)[0]
    assert r'Name: "{app}\models"' not in section
