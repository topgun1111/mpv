"""GPU sağlayıcı tanılaması (S1): hangi ONNX Runtime sağlayıcısı var, hangisi seçilir, gerçekte hangisi yüklendi.

`python -m tracker providers [--device cuda] [--model models/yolox_s.onnx] [--json]`

Neden: `onnxruntime-directml` paketinde CUDA sağlayıcısı YOKTUR (CUDA için `onnxruntime-gpu` gerekir) ve
CUDA DLL'leri yüklenemezse ONNX Runtime çoğu zaman sessizce CPU'ya düşer. Bu komut ikisini de gösterir.
Gerçek yükleme denetimi için `--model` ver (oturum açılır, `session.get_providers()` yazılır).
`onnxruntime` yalnızca burada içe aktarılır; testler sahte modül verir.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .detector import (
    _PROVIDER_NAMES,
    auto_order,
    ort_providers,
    preload_cuda,
    resolve_model_path,
    select_providers,
)

# Aynı anda kurulu olmaması gereken ONNX Runtime dağıtımları (aynı `onnxruntime` klasörünü paylaşırlar).
ORT_PACKAGES = ("onnxruntime", "onnxruntime-directml", "onnxruntime-gpu", "onnxruntime-openvino",
                "onnxruntime-qnn", "onnxruntime-training")


def installed_ort_packages() -> dict[str, str]:
    """Kurulu ONNX Runtime pip paketleri: ad -> sürüm."""
    from importlib import metadata

    found: dict[str, str] = {}
    for name in ORT_PACKAGES:
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    return found


def _hints(report: dict[str, Any]) -> list[str]:
    avail = report["available"]
    dev = report["device"]
    out: list[str] = []
    pk = report["packages"]
    if len(pk) > 1:
        out.append("Birden çok ONNX Runtime paketi kurulu (" + ", ".join(sorted(pk)) + "): aynı klasörü "
                   "paylaşırlar, sağlayıcılar bozulabilir. Birini kaldır (ayrı bir venv kullan).")
    if dev in ("cuda", "auto") and _PROVIDER_NAMES["cuda"] not in avail:
        out.append("CUDA sağlayıcısı yok: `onnxruntime-directml` CUDA içermez. CUDA için ayrı bir venv'de "
                   "`onnxruntime-gpu` kur (bkz. docs/DECISIONS.md).")
    if dev in ("dml", "auto") and _PROVIDER_NAMES["dml"] not in avail:
        out.append("DirectML sağlayıcısı yok: Windows'ta `onnxruntime-directml` kurulu olmalı.")
    if report.get("session_error"):
        out.append("Model yüklenemedi: " + report["session_error"])
    elif report.get("fell_back"):
        out.append(f"{report['selected'][0]} istendi ama oturum {report['session_providers']} ile açıldı: "
                   "sağlayıcı yüklenemedi (CUDA/cuDNN DLL eksik ya da sürüm uyumsuz olabilir).")
    return out


def diagnose(device: str = "auto", model: str | Path | None = None, ort: Any = None,
             packages: dict[str, str] | None = None) -> dict[str, Any]:
    """Tanı sözlüğü. `ort`/`packages` testler için enjekte edilebilir."""
    if ort is None:
        import onnxruntime as ort  # ImportError çağırana gider
    avail = list(ort.get_available_providers())
    rep: dict[str, Any] = {
        "ort_version": getattr(ort, "__version__", "?"),
        "ort_device": ort.get_device() if hasattr(ort, "get_device") else "?",
        "packages": installed_ort_packages() if packages is None else packages,
        "available": avail,
        "device": device,
        "auto_order": list(auto_order()),
        "selection": {d: select_providers(avail, d) for d in ("auto", "dml", "cuda", "cpu")},
        "selected": select_providers(avail, device),
    }
    if model is not None:
        _try_session(rep, ort, resolve_model_path(model))
    rep["hints"] = _hints(rep)
    return rep


def _try_session(rep: dict[str, Any], ort: Any, path: Path) -> None:
    sel = rep["selected"]
    if not path.is_file():
        rep["session_error"] = f"model dosyası yok: {path}"
        return
    if _PROVIDER_NAMES["cuda"] in sel:
        rep["preload_cuda"] = preload_cuda(ort)
    opts = ort.SessionOptions()
    if _PROVIDER_NAMES["dml"] in sel:  # Detector ile aynı DirectML ayarları
        opts.enable_mem_pattern = False
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    t0 = time.perf_counter()
    try:
        sess = ort.InferenceSession(str(path), sess_options=opts, providers=ort_providers(sel))
    except Exception as e:
        rep["session_error"] = f"{type(e).__name__}: {e}"
        return
    rep["load_s"] = round(time.perf_counter() - t0, 3)
    used = list(sess.get_providers())
    rep["session_providers"] = used
    rep["fell_back"] = bool(used) and used[0] != sel[0]


def format_report(rep: dict[str, Any]) -> str:
    L = [f"ONNX Runtime {rep['ort_version']}  (get_device: {rep['ort_device']})"]
    pk = rep["packages"]
    L.append("Kurulu paketler: " + (", ".join(f"{k} {v}" for k, v in sorted(pk.items())) or "(bulunamadı)"))
    L.append("Kullanılabilir sağlayıcılar: " + ", ".join(rep["available"]))
    L.append("auto sırası: " + " > ".join(rep["auto_order"]) + " > cpu")
    for d in ("auto", "dml", "cuda", "cpu"):
        L.append(f"  --device {d:<4} -> {', '.join(rep['selection'][d])}")
    L.append(f"Seçilen (--device {rep['device']}): {', '.join(rep['selected'])}")
    if "preload_cuda" in rep:
        L.append(f"CUDA DLL ön yükleme: {rep['preload_cuda']}")
    if "session_providers" in rep:
        L.append(f"Model yüklendi ({rep['load_s']} sn); gerçek sağlayıcılar: {', '.join(rep['session_providers'])}")
    for h in rep["hints"]:
        L.append("UYARI: " + h)
    return "\n".join(L)


def to_json(rep: dict[str, Any]) -> str:
    return json.dumps(rep, ensure_ascii=False, indent=2)
