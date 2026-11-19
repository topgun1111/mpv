"""S1: sağlayıcı sırası (provider_order / ortam değişkeni) ve `providers` tanı komutu. Model/GPU gerekmez."""
from types import SimpleNamespace

import pytest

from tracker import detector, providers
from tracker.config import Config
from tracker.detector import (
    AUTO_ORDER_ENV,
    auto_order,
    parse_order,
    preload_cuda,
    select_providers,
    set_auto_order,
)

DML, CUDA, CPU = "DmlExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(AUTO_ORDER_ENV, raising=False)
    monkeypatch.setattr(detector, "_AUTO_ORDER", ("dml", "cuda"))  # test sonrası geri yüklenir


# --- sıra ---

def test_default_order_unchanged():
    assert Config().provider_order == "dml,cuda"
    assert auto_order() == ("dml", "cuda")
    assert select_providers([DML, CUDA, CPU], "auto") == [DML, CUDA, CPU]


def test_cuda_first_when_configured():
    assert set_auto_order("cuda,dml") == ("cuda", "dml")
    assert select_providers([DML, CUDA, CPU], "auto") == [CUDA, DML, CPU]
    assert select_providers([DML, CPU], "auto") == [DML, CPU]  # CUDA yoksa atlanır
    assert select_providers([CPU], "auto") == [CPU]


def test_explicit_device_ignores_order():
    set_auto_order("cuda,dml")
    assert select_providers([DML, CUDA, CPU], "dml") == [DML, CPU]
    assert select_providers([DML, CUDA, CPU], "cpu") == [CPU]


def test_parse_order_rules():
    assert parse_order(" CUDA , dml ,cuda") == ("cuda", "dml")  # küçük harf, boşluk, yinelenen
    assert parse_order("cuda,cpu") == ("cuda",)  # cpu yok sayılır (hep son)
    assert parse_order("") == ("dml", "cuda")  # boş -> varsayılan
    assert parse_order(["cuda"]) == ("cuda",)
    with pytest.raises(ValueError):
        parse_order("tpu")


def test_env_overrides_config(monkeypatch):
    set_auto_order("dml,cuda")
    monkeypatch.setenv(AUTO_ORDER_ENV, "cuda")
    assert auto_order() == ("cuda",)
    assert select_providers([DML, CUDA, CPU], "auto") == [CUDA, CPU]
    monkeypatch.setenv(AUTO_ORDER_ENV, "  ")  # boş ortam değişkeni yok sayılır
    assert auto_order() == ("dml", "cuda")


def test_bad_config_order_raises():
    with pytest.raises(ValueError):
        set_auto_order("cuda,tpu")


# --- preload ---

def test_preload_cuda_variants():
    assert preload_cuda(SimpleNamespace()) == "yok"  # onnxruntime-directml: preload_dlls yok
    assert preload_cuda(SimpleNamespace(preload_dlls=lambda: None)) == "ok"

    def boom():
        raise OSError("cudnn64_9.dll bulunamadı")

    assert preload_cuda(SimpleNamespace(preload_dlls=boom)).startswith("hata: ")


# --- tanı ---

class FakeSession:
    def __init__(self, providers_used):
        self._p = providers_used

    def get_providers(self):
        return list(self._p)


def fake_ort(available, session_providers=None, fail=None, preload=None):
    calls = []

    def make(path, sess_options=None, providers=None):
        calls.append((path, providers))
        if fail:
            raise RuntimeError(fail)
        return FakeSession(session_providers if session_providers is not None else providers)

    ns = SimpleNamespace(
        __version__="9.9.9",
        get_available_providers=lambda: list(available),
        get_device=lambda: "GPU",
        SessionOptions=lambda: SimpleNamespace(),
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="seq"),
        InferenceSession=make,
        calls=calls,
    )
    if preload is not None:
        ns.preload_dlls = preload
    return ns


def test_diagnose_directml_only_warns_about_cuda():
    rep = providers.diagnose("cuda", ort=fake_ort([DML, CPU]), packages={"onnxruntime-directml": "1.20.0"})
    assert rep["selected"] == [CPU]  # CUDA yok -> sessizce CPU
    assert rep["selection"]["auto"] == [DML, CPU]
    assert any("CUDA sağlayıcısı yok" in h for h in rep["hints"])
    assert "session_providers" not in rep  # --model verilmedi


def test_diagnose_flags_conflicting_packages():
    rep = providers.diagnose("auto", ort=fake_ort([DML, CPU]),
                             packages={"onnxruntime-directml": "1.20.0", "onnxruntime-gpu": "1.22.0"})
    assert any("Birden çok ONNX Runtime paketi" in h for h in rep["hints"])


def test_diagnose_real_session_detects_silent_fallback(tmp_path):
    model = tmp_path / "m.onnx"
    model.write_bytes(b"x")
    ort = fake_ort([CUDA, CPU], session_providers=[CPU], preload=lambda: None)  # CUDA yüklenemedi
    rep = providers.diagnose("cuda", model, ort=ort, packages={"onnxruntime-gpu": "1.22.0"})
    assert rep["preload_cuda"] == "ok"
    assert rep["session_providers"] == [CPU] and rep["fell_back"] is True
    assert ort.calls[0][1] == [CUDA, CPU]
    assert any("sağlayıcı yüklenemedi" in h for h in rep["hints"])


def test_diagnose_real_session_ok(tmp_path):
    model = tmp_path / "m.onnx"
    model.write_bytes(b"x")
    rep = providers.diagnose("dml", model, ort=fake_ort([DML, CPU]), packages={"onnxruntime-directml": "1"})
    assert rep["session_providers"] == [DML, CPU] and rep["fell_back"] is False
    assert not rep["hints"]
    assert "gerçek sağlayıcılar: DmlExecutionProvider" in providers.format_report(rep)


def test_diagnose_session_errors(tmp_path):
    rep = providers.diagnose("cpu", tmp_path / "yok.onnx", ort=fake_ort([CPU]), packages={})
    assert "model dosyası yok" in rep["session_error"]
    model = tmp_path / "m.onnx"
    model.write_bytes(b"x")
    rep = providers.diagnose("cpu", model, ort=fake_ort([CPU], fail="bozuk model"), packages={})
    assert rep["session_error"].startswith("RuntimeError: bozuk model")
    assert any("Model yüklenemedi" in h for h in rep["hints"])


def test_format_and_json_roundtrip():
    import json

    rep = providers.diagnose("auto", ort=fake_ort([DML, CPU]), packages={"onnxruntime-directml": "1.20.0"})
    text = providers.format_report(rep)
    assert "ONNX Runtime 9.9.9" in text and "auto sırası: dml > cuda > cpu" in text
    assert json.loads(providers.to_json(rep))["selected"] == [DML, CPU]


def test_cli_providers_command(monkeypatch, capsys, tmp_path):
    from tracker import main as tmain

    fake = fake_ort([DML, CPU])
    monkeypatch.setattr(providers, "installed_ort_packages", lambda: {"onnxruntime-directml": "1"})
    import sys

    monkeypatch.setitem(sys.modules, "onnxruntime", fake)
    assert tmain.main(["providers", "--device", "dml"]) == 0
    out = capsys.readouterr().out
    assert "Seçilen (--device dml): DmlExecutionProvider, CPUExecutionProvider" in out
    # geçersiz config sırası -> hata
    cfgp = tmp_path / "c.json"
    cfgp.write_text('{"provider_order": "tpu"}', encoding="utf-8")
    assert tmain.main(["--config", str(cfgp), "providers"]) == 1
