"""Package Qualcomm's MIT-licensed OSNet ReID ONNX asset as one Android model.

Usage: python scripts/prepare_osnet.py osnet-onnx-float.zip OUTPUT.onnx
The release URL/version and archive SHA are pinned so CI never silently changes
the identity model. A smoke run uses the same ORT version as Android.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import onnx
import onnxruntime as ort

OSNET_RELEASE_URL = (
    "https://qaihub-public-assets.s3.us-west-2.amazonaws.com/"
    "qai-hub-models/models/osnet/releases/v0.66.0/osnet-onnx-float.zip"
)
OSNET_ZIP_SHA256 = "c79139f9c143cc8457a548c0877988ee2355b2608707ac78c05f83c66443d673"
ONNX_FILE = "osnet-onnx-float/osnet.onnx"
DATA_FILE = "osnet-onnx-float/osnet.data"


def package(source: Path, destination: Path) -> None:
    if hashlib.sha256(source.read_bytes()).hexdigest() != OSNET_ZIP_SHA256:
        raise ValueError("OSNet release archive SHA256 mismatch")
    with tempfile.TemporaryDirectory(prefix="osnet-export-") as temp:
        root = Path(temp)
        with ZipFile(source) as archive:
            for name in (ONNX_FILE, DATA_FILE):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as src, target.open("wb") as dst:
                    import shutil

                    shutil.copyfileobj(src, dst)
        model = onnx.load(str(root / ONNX_FILE), load_external_data=True)
        if [v.name for v in model.graph.input] != ["image"]:
            raise ValueError("OSNet input contract changed")
        if [v.name for v in model.graph.output] != ["embeddings"]:
            raise ValueError("OSNet output contract changed")
        inp = [d.dim_value for d in model.graph.input[0].type.tensor_type.shape.dim]
        out = [d.dim_value for d in model.graph.output[0].type.tensor_type.shape.dim]
        if inp != [1, 3, 256, 128] or out != [1, 512]:
            raise ValueError(f"Unexpected OSNet shapes: {inp} -> {out}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        onnx.save_model(model, str(destination), save_as_external_data=False)
    onnx.checker.check_model(str(destination))
    session = ort.InferenceSession(str(destination), providers=["CPUExecutionProvider"])
    result = session.run(["embeddings"], {"image": np.zeros((1, 3, 256, 128), dtype=np.float32)})[0]
    if result.shape != (1, 512) or not np.isfinite(result).all():
        raise ValueError("OSNet inference produced invalid embeddings")
    length = float(np.linalg.norm(result))
    if not 0.98 <= length <= 1.02:
        raise ValueError(f"OSNet embedding is not normalized: norm={length}")
    print(f"OSNet ready: {destination} ({destination.stat().st_size} bytes, norm {length:.4f})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python scripts/prepare_osnet.py ZIP OUTPUT.onnx")
    package(Path(sys.argv[1]), Path(sys.argv[2]))
