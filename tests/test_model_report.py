"""scripts/model_report.py (CI report on exported ONNX models) and the export wiring in the workflows."""
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # @dataclass (postponed annotations) looks its module up in sys.modules
    spec.loader.exec_module(mod)
    return mod


mr = _load("model_report")


def _tiny_onnx(path: Path, in_name="images", out_name="output0", shape=(1, 56, 8)):
    onnx = pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    from onnx import TensorProto, helper

    x = helper.make_tensor_value_info(in_name, TensorProto.FLOAT, list(shape))
    y = helper.make_tensor_value_info(out_name, TensorProto.FLOAT, list(shape))
    graph = helper.make_graph([helper.make_node("Identity", [in_name], [out_name])], "g", [x], [y])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 12)])
    model.ir_version = 8
    onnx.save(model, str(path))


# --- needs neither onnx nor onnxruntime ---

def test_missing_required_fails_and_missing_optional_only_warns(tmp_path):
    req = mr.inspect_file(tmp_path, mr.Spec("a.onnx", 1))
    opt = mr.inspect_file(tmp_path, mr.Spec("b.onnx", 1, required=False))
    assert req.status == "FAIL" and "MISSING" in req.notes[0]
    assert opt.status == "WARN"


def test_too_small_file_fails_even_without_onnx(tmp_path):
    (tmp_path / "a.onnx").write_bytes(b"x" * 10)
    r = mr.inspect_file(tmp_path, mr.Spec("a.onnx", 1000))
    assert r.status == "FAIL" and r.size == 10 and "TOO SMALL" in r.notes[0] and len(r.sha256) == 64


def test_main_exit_codes_and_report_text(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mr, "preset", lambda name: [mr.Spec("need.onnx", 1),
                                                   mr.Spec("maybe.onnx", 1, required=False)])
    (tmp_path / "leftover.pt").write_bytes(b"x")  # would be packed into the APK
    assert mr.main(["x", str(tmp_path), "--preset", "android-pose"]) == 1
    out = capsys.readouterr().out
    assert "[FAIL] need.onnx" in out and "[WARN] maybe.onnx" in out
    assert "stray file would be packaged" in out and "leftover.pt" in out
    assert "SUMMARY android-pose: 0/2 ok, 1 failed" in out and "FAILED: need.onnx" in out


def test_missing_folder_is_reported_not_crashed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mr, "preset", lambda name: [mr.Spec("need.onnx", 1)])
    assert mr.main(["x", str(tmp_path / "nope"), "--preset", "android-pose"]) == 1
    assert "folder does not exist" in capsys.readouterr().out


def test_presets_list_exactly_what_the_apk_and_package_need():
    sam = {s.path for s in mr.preset("android-sam")}
    graphs = {"sam-encoder", "sam-decoder", "sam-decoder-trk", "sam-memenc", "sam-memattn"}
    assert sam == {"yolov8s-pose.onnx", "yolo26m-pose.onnx", "osnet-reid.onnx"} | {f"{v}/{g}.onnx" for v in ("edgetam", "small") for g in graphs}
    assert {s.path for s in mr.preset("android-pose")} == {"yolov8s-pose.onnx", "yolo11m-pose.onnx", "yolo26m-pose.onnx", "osnet-reid.onnx"}
    for flavor in ("android-pose", "android-sam"):
        reid = next(s for s in mr.preset(flavor) if s.path == "osnet-reid.onnx")
        assert reid.want_in == {"image"} and reid.want_out == {"embeddings"}
        strong = next(s for s in mr.preset(flavor) if s.path == "yolo26m-pose.onnx")
        assert strong.required and strong.kind == "pose" and strong.min_bytes >= 60_000_000
    pc = {s.path: s.required for s in mr.preset("pc")}
    assert pc["models/yolox_s.onnx"] and pc["models/yolov8s-pose.onnx"]
    assert not pc["models/osnet_x0_25.onnx"] and not pc["models/rtmpose-wholebody.onnx"]
    export = (ROOT / "scripts" / "export_sam2.py").read_text(encoding="utf-8")
    assert set(re.findall(r"(sam-[a-z-]+\.onnx)", export)) == set(mr.SAM_GRAPHS)  # same I/O contract source


# --- real ONNX files ---

def test_valid_pose_model_is_ok(tmp_path):
    _tiny_onnx(tmp_path / "p.onnx")
    r = mr.inspect_file(tmp_path, mr.Spec("p.onnx", 1, kind="pose"))
    assert r.status == "OK", r.notes
    assert r.inputs == ["images[1,56,8]"] and r.outputs == ["output0[1,56,8]"]
    assert r.ort.startswith("ok") and r.opset == "ai.onnx:12" and r.nodes == 1


def test_wrong_pose_layout_and_wrong_io_names_fail(tmp_path):
    _tiny_onnx(tmp_path / "bad.onnx", shape=(1, 17, 8))
    assert mr.inspect_file(tmp_path, mr.Spec("bad.onnx", 1, kind="pose")).status == "FAIL"
    _tiny_onnx(tmp_path / "enc.onnx", in_name="x", out_name="y")
    r = mr.inspect_file(tmp_path, mr.Spec("enc.onnx", 1, want_in={"image"}, want_out={"image_embed"}))
    assert r.status == "FAIL" and any("INPUT NAMES" in n for n in r.notes)


def test_garbage_onnx_is_invalid(tmp_path):
    pytest.importorskip("onnx")
    (tmp_path / "g.onnx").write_bytes(b"not an onnx file at all" * 10)
    r = mr.inspect_file(tmp_path, mr.Spec("g.onnx", 1))
    assert r.status == "FAIL" and any("INVALID" in n or "CANNOT LOAD" in n for n in r.notes)


def test_json_and_github_summary_are_written(tmp_path, monkeypatch):
    _tiny_onnx(tmp_path / "p.onnx")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(mr, "preset", lambda name: [mr.Spec("p.onnx", 1, kind="pose")])
    out_json = tmp_path / "out" / "report.json"
    assert mr.main(["x", str(tmp_path), "--preset", "android-pose", "--summary", "--json", str(out_json)]) == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data[0]["path"] == "p.onnx" and data[0]["status"] == "OK"
    assert "| `p.onnx` |" in summary.read_text(encoding="utf-8")


# --- workflow / script wiring (text level) ---

def test_android_workflow_pins_torch_and_reports_models():
    y = (WF / "android.yml").read_text(encoding="utf-8")
    assert "pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu" in y
    assert "pip install torch torchvision" not in y  # unpinned torch pulled the dynamo exporter (onnx_ir crash)
    assert "onnxscript==0.2.1" not in y
    assert 'scripts/model_report.py' in y and '--preset "android-${{ matrix.flavor }}"' in y
    assert y.index("scripts/export_pose.py") < y.index("scripts/export_sam2.py") < y.index("scripts/model_report.py")
    assert y.index("scripts/model_report.py") < y.index("assemble${{ matrix.gradle_task }}Release")
    assert "MODEL_CKPT_DIR" in y and "model-logs" in y
    assert "ultralytics==8.4.216" in y and 'scripts/export_pose.py "$d" yolo26m-pose' in y
    assert "upload-artifact" not in y and "download-artifact" not in y
    stage = y[y.index("- name: Stage permitted release files directly"):]
    assert "scripts/stage_release.py upload" in stage and "inputs.release_tag" in stage
    diagnostics = y[y.index("- name: Model diagnostics in job logs"):]
    assert "if: always()" in diagnostics
    assert "model-logs/*.json" in diagnostics and 'tail -n 100 "$f"' in diagnostics


def test_apk_check_is_per_flavor():
    y = (WF / "android.yml").read_text(encoding="utf-8")
    sec = y[y.index("- name: Models are inside the APK"):y.index("- name: Name the APK")]
    assert 'if [ "${{ matrix.flavor }}" = "pose" ]; then' in sec and "need yolo11m-pose.onnx" in sec
    assert 'for variant in edgetam small' in sec  # SAM graphs only in the sam branch
    pose_at = sec.index("need yolo11m-pose.onnx")
    assert pose_at < sec.index("\n          else\n", pose_at) < sec.index("for variant in edgetam small")
    assert "unzip -l \"$apk\" | grep -q" not in sec  # SIGPIPE under pipefail gives false misses


def test_pc_workflow_reports_models_before_verifying_them():
    y = (WF / "build.yml").read_text(encoding="utf-8")
    assert "onnxscript onnx-ir" in y
    assert y.index("export_reid.py") < y.index("model_report.py") < y.index("verify_models.py")
    assert "--preset pc" in y


def test_export_scripts_use_the_stable_paths():
    reid = (ROOT / "scripts" / "export_reid.py").read_text(encoding="utf-8")
    assert "dynamo=False" in reid and "dynamo=True" in reid and "dynamic_axes" in reid
    sam = (ROOT / "scripts" / "export_sam2.py").read_text(encoding="utf-8")
    assert 'ckpt = out / f"{size}.pt"' not in sam and "MODEL_CKPT_DIR" in sam  # no checkpoint in assets
    pose = (ROOT / "scripts" / "export_pose.py").read_text(encoding="utf-8")
    assert "verify_onnx" in pose and "POSE_CHANNELS = 56" in pose
