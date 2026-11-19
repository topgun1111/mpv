"""OSNet x0.25 Re-ID modelini ONNX'e çevirip hedef klasöre koyar (CI'da; isteğe bağlı model).

Kullanım: python scripts/export_reid.py dist/TakipliOynat/models [osnet_x0_25]
Gerekli (yalnız derleme makinesinde, pakete girmez):
  pip install torch torchvision torchreid gdown onnx
Ağırlık: torchreid'in ImageNet ön eğitimli OSNet ağırlığı (Google Drive'dan gdown ile iner).
Erişilemezse betik hata verir; CI adımı sürüme engel olmaz (`reid_live=auto` yalnız dosya
varsa Re-ID açar).
NOT: ImageNet ağırlığı Re-ID verisiyle (Market-1501 vb.) eğitilmemiştir; benzerlik kaba çalışır,
`reid_thres` gerçek videoda ayarlanmalıdır. Girdi [N,3,256,128] (tracker/reid.py), çıktı [N,D].
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

MIN_BYTES = 500_000


def export_onnx(torch, model, dummy, out: Path) -> None:
    """TorchScript exporter first: recent torch defaults to the dynamo exporter, which needs
    onnxscript + onnx_ir (`No module named 'onnxscript'` broke this step on 2026-11-19).
    Last resort: the dynamo exporter itself (the workflow installs onnxscript and onnx-ir)."""
    kw = dict(input_names=["input"], output_names=["feat"],
              dynamic_axes={"input": {0: "batch"}, "feat": {0: "batch"}})
    try:
        torch.onnx.export(model, dummy, str(out), opset_version=12, dynamo=False, **kw)
        print("ONNX export: TorchScript exporter, opset 12", flush=True)
    except TypeError:  # torch < 2.5 has no `dynamo` argument and is TorchScript only
        torch.onnx.export(model, dummy, str(out), opset_version=12, **kw)
        print("ONNX export: default exporter (no `dynamo` argument), opset 12", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"TorchScript exporter failed ({type(exc).__name__}: {exc}); retrying with dynamo",
              file=sys.stderr, flush=True)
        torch.onnx.export(model, dummy, str(out), dynamo=True, **kw)
        print("ONNX export: dynamo exporter (default opset)", flush=True)


def main(argv: list[str]) -> int:
    target = Path(argv[1] if len(argv) > 1 else "dist/TakipliOynat/models")
    name = argv[2] if len(argv) > 2 else "osnet_x0_25"
    import torch
    import torchreid

    print(f"export environment: python {sys.version.split()[0]}, torch {torch.__version__}",
          flush=True)
    model = torchreid.models.build_model(name=name, num_classes=1000, pretrained=True)
    model.eval()
    dummy = torch.zeros(1, 3, 256, 128)
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / f"{name}.onnx"
        export_onnx(torch, model, dummy, out)
        if not out.is_file() or out.stat().st_size < MIN_BYTES:
            print(f"HATA: ONNX dışa aktarma başarısız/çok küçük: {out}", file=sys.stderr)
            return 1
        import numpy as np
        import onnxruntime as ort

        sess = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"])
        y = sess.run(None, {"input": np.zeros((2, 3, 256, 128), np.float32)})[0]
        if y.ndim != 2 or y.shape[0] != 2:
            print(f"HATA: beklenmeyen çıktı biçimi {y.shape} ([N,D] olmalı)", file=sys.stderr)
            return 1
        dst = target / f"{name}.onnx"
        shutil.copyfile(out, dst)
    print(f"Re-ID modeli hazır: {dst} ({dst.stat().st_size / 1e6:.1f} MB, çıktı {y.shape})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
