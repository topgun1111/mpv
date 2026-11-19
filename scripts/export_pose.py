"""YOLO-pose ağırlığını ONNX'e çevirip hedef klasöre koyar (CI'da; kişisel kullanım, AGPL).

Kullanım: python scripts/export_pose.py dist/TakipliOynat/models [yolov8s-pose] [--fp16]
  --fp16: ayrıca `<ad>-fp16.onnx` yazar (iç hesap fp16, girdi/çıktı fp32; DirectML hızlanması için).
Gerekli: pip install ultralytics onnx [onnxconverter-common] (yalnız derleme makinesinde).
Örnek: ... models yolo11m-pose --fp16  (YOLO11-pose çıktısı da [1,56,N]; aynı çözücü)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

MIN_BYTES = 5_000_000
POSE_CHANNELS = 56  # 4 box + 1 score + 17 keypoints * 3 (tracker/pose.py decodes [1,56,N])


def log_versions() -> None:
    """One line with every version that decides whether the ONNX export works (CI diagnosis)."""
    import importlib

    parts = [f"python {sys.version.split()[0]}"]
    for mod in ("torch", "torchvision", "ultralytics", "onnx", "onnxruntime",
                "onnxscript", "onnx_ir"):
        try:
            parts.append(f"{mod} {getattr(importlib.import_module(mod), '__version__', '?')}")
        except Exception as exc:  # noqa: BLE001
            parts.append(f"{mod} MISSING ({type(exc).__name__})")
    print("export environment: " + ", ".join(parts), flush=True)


def verify_onnx(path: Path) -> None:
    """Structure check + (when onnxruntime is installed) a load and output-layout check."""
    import onnx

    onnx.checker.check_model(str(path))
    print(f"  structure valid: {path.name}", flush=True)
    try:
        import onnxruntime as ort
    except ImportError:
        print(f"  onnxruntime not installed: load check skipped for {path.name}", flush=True)
        return
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    shape = sess.get_outputs()[0].shape
    print(f"  onnxruntime loads {path.name}: output {shape}", flush=True)
    if len(shape) < 2 or shape[1] != POSE_CHANNELS:
        raise RuntimeError(f"{path.name}: pose output must be [1,{POSE_CHANNELS},N], got {shape}")


def to_fp16(src: Path, dst: Path) -> None:
    import onnx
    from onnxconverter_common import float16

    model = onnx.load(str(src))
    onnx.save(float16.convert_float_to_float16(model, keep_io_types=True), str(dst))


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    target = Path(args[0] if args else "dist/TakipliOynat/models")
    name = args[1] if len(args) > 1 else "yolov8s-pose"
    print(f"=== EXPORT {name} -> {target} ===", flush=True)
    log_versions()
    from ultralytics import YOLO

    target.mkdir(parents=True, exist_ok=True)
    try:
        exported = YOLO(f"{name}.pt").export(format="onnx", imgsz=640, opset=12, simplify=False)
        onnx_path = Path(exported)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {name}: export raised {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise
    if not onnx_path.is_file() or onnx_path.stat().st_size < MIN_BYTES:
        print(f"HATA: ONNX dışa aktarma başarısız/çok küçük: {onnx_path}", file=sys.stderr)
        return 1
    dst = target / f"{name}.onnx"
    shutil.copyfile(onnx_path, dst)
    print(f"Pose modeli hazır: {dst} ({dst.stat().st_size / 1e6:.1f} MB)")
    try:
        verify_onnx(dst)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ {dst.name} failed verification: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if "--fp16" in argv:
        d16 = target / f"{name}-fp16.onnx"
        to_fp16(dst, d16)
        if d16.stat().st_size < MIN_BYTES // 2:
            print(f"HATA: fp16 dönüşümü çok küçük: {d16}", file=sys.stderr)
            return 1
        print(f"fp16 hazır: {d16} ({d16.stat().st_size / 1e6:.1f} MB)")
        try:
            verify_onnx(d16)
        except Exception as exc:  # noqa: BLE001
            print(f"✗ {d16.name} failed verification: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    print(f"✓ MODEL READY: {name}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
