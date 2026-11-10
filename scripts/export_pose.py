"""YOLOv8-pose ağırlığını ONNX'e çevirip hedef klasöre koyar (CI'da; kişisel kullanım, AGPL).

Kullanım: python scripts/export_pose.py dist/TakipliOynat/models [yolov8s-pose]
Gerekli: pip install ultralytics onnx (yalnız derleme makinesinde; pakete girmez).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

MIN_BYTES = 5_000_000


def main(argv: list[str]) -> int:
    target = Path(argv[1] if len(argv) > 1 else "dist/TakipliOynat/models")
    name = argv[2] if len(argv) > 2 else "yolov8s-pose"
    from ultralytics import YOLO

    target.mkdir(parents=True, exist_ok=True)
    onnx = Path(YOLO(f"{name}.pt").export(format="onnx", imgsz=640, opset=12, simplify=False))
    if not onnx.is_file() or onnx.stat().st_size < MIN_BYTES:
        print(f"HATA: ONNX dışa aktarma başarısız/çok küçük: {onnx}", file=sys.stderr)
        return 1
    dst = target / f"{name}.onnx"
    shutil.copyfile(onnx, dst)
    print(f"Pose modeli hazır: {dst} ({dst.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
