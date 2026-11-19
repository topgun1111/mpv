"""Reports, file by file, whether the exported ONNX models really exist and are usable (CI).

Usage:
  python scripts/model_report.py DIR --preset NAME [--json out.json] [--summary]

Presets (what must exist below DIR):
  android-pose  DIR = android/app/src/pose/assets/models
  android-sam   DIR = android/app/src/sam/assets/models
  pc            DIR = dist/TakipliOynat           (files below DIR/models)

For every expected file it prints: present or missing, size, sha256, ONNX structure check, opset,
node count, input/output names with shapes and whether ONNX Runtime opens it. Missing optional files
are only warnings; everything else fails the run (exit code 1) after the whole table is printed, so
one CI run shows the full picture. Stray checkpoints (*.pt, *.pth, *.part) below DIR are flagged,
because anything below an assets folder is packed into the APK.
--summary additionally appends a markdown table to $GITHUB_STEP_SUMMARY.
onnx / onnxruntime missing: those checks are reported as SKIPPED (size and presence still count).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

MB = 1_000_000
STRAY = (".pt", ".pth", ".part", ".ckpt")
_DEC_IN = {"image_embed", "high_res_feats_0", "high_res_feats_1", "point_coords", "point_labels"}
_DEC_OUT = {"low_res_masks", "iou_predictions", "obj_ptrs", "object_score"}
SAM_GRAPHS = {  # same I/O contract as scripts/export_sam2.py
    "sam-encoder.onnx": (
        {"image"}, {"high_res_feats_0", "high_res_feats_1", "image_embed", "image_feat"}),
    "sam-decoder.onnx": (_DEC_IN, _DEC_OUT),
    "sam-decoder-trk.onnx": (_DEC_IN, _DEC_OUT),
    "sam-memenc.onnx": ({"image_feat", "low_res_mask", "object_score"}, {"mem_feat"}),
    "sam-memattn.onnx": ({"image_feat", "mem_feats", "ptrs"}, {"image_embed"}),
}


@dataclass
class Spec:
    path: str                      # relative to the scanned root
    min_bytes: int
    required: bool = True
    kind: str = "generic"          # pose | sam | generic
    want_in: set[str] | None = None
    want_out: set[str] | None = None


@dataclass
class Result:
    path: str
    required: bool
    status: str = "FAIL"           # OK | FAIL | WARN
    size: int = 0
    sha256: str = ""
    opset: str = "-"
    nodes: int = 0
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    ort: str = "skipped"
    notes: list[str] = field(default_factory=list)


def preset(name: str) -> list[Spec]:
    if name == "android-pose":
        return [Spec("yolov8s-pose.onnx", 5 * MB, kind="pose"),
                Spec("yolo11m-pose.onnx", 30 * MB, kind="pose")]
    if name == "android-sam":
        specs = [Spec("yolov8s-pose.onnx", 5 * MB, kind="pose")]
        for variant in ("edgetam", "small"):
            for graph, (ins, outs) in SAM_GRAPHS.items():
                specs.append(Spec(f"{variant}/{graph}", MB, kind="sam", want_in=ins, want_out=outs))
        return specs
    if name == "pc":
        return [Spec("models/yolox_s.onnx", 10 * MB),
                Spec("models/yolov8s-pose.onnx", 5 * MB, kind="pose"),
                Spec("models/yolo11m-pose.onnx", 30 * MB, False, "pose"),
                Spec("models/yolo11m-pose-fp16.onnx", 15 * MB, False, "pose"),
                Spec("models/osnet_x0_25.onnx", 500_000, False),
                Spec("models/rtmpose-wholebody.onnx", 20 * MB, False)]
    raise SystemExit(f"unknown preset: {name} (android-pose | android-sam | pc)")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _shape(value_info) -> str:
    dims = []
    for d in value_info.type.tensor_type.shape.dim:
        dims.append(str(d.dim_value) if d.HasField("dim_value") else (d.dim_param or "?"))
    return f"{value_info.name}[{','.join(dims)}]"


def inspect_file(root: Path, spec: Spec) -> Result:
    res = Result(spec.path, spec.required)
    p = root / spec.path
    if not p.is_file():
        res.status = "FAIL" if spec.required else "WARN"
        res.notes.append("MISSING" if spec.required else "missing (optional)")
        return res
    res.size = p.stat().st_size
    res.sha256 = _sha256(p)
    if res.size < spec.min_bytes:
        res.notes.append(f"TOO SMALL: {res.size} < {spec.min_bytes} bytes")
        return res
    ok = True
    try:
        import onnx
    except ImportError:
        res.notes.append("onnx not installed: structure check SKIPPED")
        onnx = None
    if onnx is not None:
        try:
            model = onnx.load(str(p), load_external_data=False)
            onnx.checker.check_model(str(p))
            res.opset = ",".join(f"{o.domain or 'ai.onnx'}:{o.version}" for o in model.opset_import)
            res.nodes = len(model.graph.node)
            inits = {i.name for i in model.graph.initializer}
            real_in = [i for i in model.graph.input if i.name not in inits]
            res.inputs = [_shape(i) for i in real_in]
            res.outputs = [_shape(o) for o in model.graph.output]
            names_in = {i.name for i in real_in}
            names_out = {o.name for o in model.graph.output}
            if spec.want_in is not None and names_in != spec.want_in:
                res.notes.append(f"INPUT NAMES {sorted(names_in)} != {sorted(spec.want_in)}")
                ok = False
            if spec.want_out is not None and names_out != spec.want_out:
                res.notes.append(f"OUTPUT NAMES {sorted(names_out)} != {sorted(spec.want_out)}")
                ok = False
            if spec.kind == "pose":
                dims = [d.dim_value for d in model.graph.output[0].type.tensor_type.shape.dim]
                if len(dims) < 2 or dims[1] != 56:
                    res.notes.append(f"pose output must be [1,56,N], got {dims}")
                    ok = False
        except Exception as exc:  # noqa: BLE001 - report everything, never stop the table
            res.notes.append(f"ONNX INVALID: {type(exc).__name__}: {str(exc)[:200]}")
            ok = False
    try:
        import onnxruntime as ort
    except ImportError:
        res.notes.append("onnxruntime not installed: load check SKIPPED")
    else:
        try:
            ort.set_default_logger_severity(3)  # errors only: no warning noise in the CI log
            sess = ort.InferenceSession(str(p), providers=["CPUExecutionProvider"])
            res.ort = "ok (" + ", ".join(
                f"{o.name}{list(o.shape)}" for o in sess.get_outputs()) + ")"
        except Exception as exc:  # noqa: BLE001
            res.ort = "FAILED"
            res.notes.append(f"ONNX RUNTIME CANNOT LOAD: {type(exc).__name__}: {str(exc)[:200]}")
            ok = False
    res.status = "OK" if ok else "FAIL"
    return res


def scan_dir(root: Path, name: str) -> Path:
    """Folder that is listed and searched for stray files (the PC package also holds Python/mpv)."""
    return root / "models" if name == "pc" else root


def stray_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in STRAY)


def render(root: Path, name: str, results: list[Result], strays: list[Path]) -> str:
    lines = [f"=== MODEL EXPORT REPORT: {name}  (dir: {root}) ==="]
    if not root.is_dir():
        lines.append(f"[FAIL] folder does not exist: {root}")
    for r in results:
        tag = {"OK": "[ OK ]", "FAIL": "[FAIL]", "WARN": "[WARN]"}[r.status]
        if r.size:
            lines.append(f"{tag} {r.path}  {r.size / MB:.1f} MB  sha256={r.sha256[:16]}...")
            lines.append(f"       opset={r.opset} nodes={r.nodes} ort={r.ort}")
            lines.append(f"       in : {' '.join(r.inputs) or '-'}")
            lines.append(f"       out: {' '.join(r.outputs) or '-'}")
        else:
            lines.append(f"{tag} {r.path}")
        lines.extend(f"       ! {n}" for n in r.notes)
    for s in strays:
        lines.append(f"[WARN] stray file would be packaged: {s} ({s.stat().st_size / MB:.1f} MB)")
    where = scan_dir(root, name)
    if where.is_dir():
        lines.append(f"--- listing of {where}")
        for p in sorted(where.rglob("*")):
            if p.is_file():
                lines.append(f"    {p.relative_to(where)}  {p.stat().st_size / MB:.2f} MB")
    ok = sum(r.status == "OK" for r in results)
    bad = [r.path for r in results if r.status == "FAIL"]
    warn = sum(r.status == "WARN" for r in results) + len(strays)
    lines.append(f"SUMMARY {name}: {ok}/{len(results)} ok, {len(bad)} failed, {warn} warning(s)")
    if bad:
        lines.append("FAILED: " + ", ".join(bad))
    return "\n".join(lines)


def markdown(name: str, results: list[Result], strays: list[Path]) -> str:
    rows = [f"### Model export: {name}", "",
            "| status | file | size | opset | nodes | ORT | notes |",
            "|---|---|---|---|---|---|---|"]
    for r in results:
        icon = {"OK": "✅", "FAIL": "❌", "WARN": "⚠️"}[r.status]
        ort = r.ort.split(" ")[0]
        rows.append(f"| {icon} | `{r.path}` | {r.size / MB:.1f} MB | {r.opset} | {r.nodes} | {ort} "
                    f"| {'; '.join(r.notes).replace('|', '/')} |")
    rows.extend(f"| ⚠️ | `{s.name}` | stray checkpoint, would be packaged | | | | |" for s in strays)
    return "\n".join(rows) + "\n"


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Report on exported ONNX models (CI).")
    ap.add_argument("root", help="folder that holds the models")
    ap.add_argument("--preset", required=True, choices=("android-pose", "android-sam", "pc"))
    ap.add_argument("--json", help="also write the results as JSON")
    ap.add_argument("--summary", action="store_true", help="append a table to $GITHUB_STEP_SUMMARY")
    ns = ap.parse_args(argv[1:])
    root = Path(ns.root)
    results = [inspect_file(root, s) for s in preset(ns.preset)]
    strays = stray_files(scan_dir(root, ns.preset))
    print(render(root, ns.preset, results, strays), flush=True)
    if ns.json:
        Path(ns.json).parent.mkdir(parents=True, exist_ok=True)
        Path(ns.json).write_text(json.dumps([asdict(r) for r in results], indent=2),
                                 encoding="utf-8")
    if ns.summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(markdown(ns.preset, results, strays) + "\n")
    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
