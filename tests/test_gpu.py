"""Ekran kartı seçimi: liste, kimlikler, ONNX Runtime `device_id`, canlı mesaj + yeniden başlatma."""
import json

from tracker import detector, gpu
from tracker.config import Config
from tracker.gpu import Adapter
from tracker.live import LiveController
from tracker.settings import panel_snapshot

DML, CUDA, CPU = "DmlExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"
CARDS = [Adapter(0, "NVIDIA GeForce RTX 3060", 0x10DE, 12288), Adapter(1, "Intel(R) UHD", 0x8086, 128),
         Adapter(2, "Microsoft Basic Render Driver", 0x1414, 0, True)]


def test_choices_dml_cuda_cpu_and_software_hidden():
    ids = [c.id for c in gpu.choices([DML, CUDA, CPU], CARDS)]
    assert ids == ["auto", "dml:0", "cuda:0", "dml:1", "cpu"]  # WARP (yazılım) listelenmez
    assert [c.id for c in gpu.choices([CPU], CARDS)] == ["auto", "cpu"]  # sağlayıcı yok: yalnız CPU
    lab = {c.id: c.label for c in gpu.choices([DML, CPU], CARDS)}
    assert "12 GB" in lab["dml:0"] and lab["dml:1"].endswith("128 MB · DirectML")


def test_choices_without_adapter_list_still_offers_generic():
    ids = [c.id for c in gpu.choices([DML, CPU], [])]
    assert ids == ["auto", "dml:-1", "cpu"]


def test_cuda_ordinal_counts_only_nvidia():
    two = [Adapter(0, "Intel", 0x8086), Adapter(1, "NVIDIA A", 0x10DE), Adapter(2, "NVIDIA B", 0x10DE)]
    ch = {c.id: c for c in gpu.choices([DML, CUDA, CPU], two)}
    assert ch["cuda:0"].label.startswith("NVIDIA A") and ch["cuda:1"].label.startswith("NVIDIA B")


def test_current_id_and_apply_choice():
    cfg = Config(ipc_path="x")
    assert gpu.current_id(cfg) == "auto"
    valid = gpu.choices([DML, CUDA, CPU], CARDS)
    assert gpu.apply_choice(cfg, "dml:1", valid) and (cfg.device, cfg.gpu) == ("dml", 1)
    assert gpu.current_id(cfg) == "dml:1"
    assert gpu.apply_choice(cfg, "cpu", valid) and gpu.current_id(cfg) == "cpu"
    assert not gpu.apply_choice(cfg, "dml:9", valid) and cfg.device == "cpu"
    assert gpu.apply_choice(cfg, "auto", valid) and (cfg.device, cfg.gpu) == ("auto", -1)


def test_ort_providers_device_id():
    try:
        detector.set_gpu(-1)
        assert detector.ort_providers([DML, CPU]) == [DML, CPU]  # seçim yok: eski davranış
        detector.set_gpu(1)
        assert detector.ort_providers([DML, CPU]) == [(DML, {"device_id": 1}), CPU]
        assert detector.ort_providers([CUDA, CPU])[0] == (CUDA, {"device_id": 1})
    finally:
        detector.set_gpu(-1)


def test_config_roundtrip_old_config_has_default(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"device": "dml"}), encoding="utf-8")
    assert Config.load(p).gpu == -1
    c = Config(ipc_path="x")
    c.gpu = 2
    c.save(p)
    assert Config.load(p).gpu == 2


def test_panel_snapshot_has_gpu(monkeypatch):
    monkeypatch.setattr(gpu, "adapters", lambda refresh=False: CARDS)
    snap = panel_snapshot(Config(ipc_path="x"))
    assert snap["gpu"]["cur"] == "auto" and snap["gpu"]["items"][0] == {
        "id": "auto", "label": "Otomatik (en iyi kullanılabilir)"}


def test_live_gpu_message_saves_config_and_requests_restart(tmp_path, monkeypatch):
    real = gpu.choices
    monkeypatch.setattr(gpu, "choices", lambda *a, **k: real([DML, CUDA, CPU], CARDS))
    path = tmp_path / "config.json"

    class P:
        def reset(self):
            pass

    c = LiveController(P(), Config(ipc_path="x"), cfg_path=str(path))
    out = c.handle_event({"event": "client-message", "args": ["track-gpu", "dml:1"]})
    assert c.restart_req and "Intel(R) UHD" in out.osd and c.cfg_dirty
    assert not path.exists()  # seçim yalnız bu oturum: dosyaya yazılmaz
    assert gpu.current_id(c.cfg) == "dml:1"
    out = c.handle_event({"event": "client-message", "args": ["track-gpu-default", "set"]})
    assert Config.load(path).default_gpu == "dml:1" and "dml:1" in out.osd
    c.handle_event({"event": "client-message", "args": ["track-gpu-default", "clear"]})
    assert Config.load(path).default_gpu == ""
    c.restart_req = False
    out = c.handle_event({"event": "client-message", "args": ["track-gpu", "dml:1"]})
    assert not c.restart_req and "zaten" in out.osd  # aynı seçim: yeniden başlatma yok
    out = c.handle_event({"event": "client-message", "args": ["track-gpu", "zzz"]})
    assert not c.restart_req and "Bilinmeyen" in out.osd


def test_live_gpu_message_works_without_cfg_path():
    class P:
        def reset(self):
            pass

    c = LiveController(P(), Config(ipc_path="x"))
    c.handle_event({"event": "client-message", "args": ["track-gpu", "cpu"]})
    assert c.restart_req  # oturum seçimi dosyaya yazılmaz, yol gerekmez


def test_resolve_startup_default_override_and_missing():
    valid = gpu.choices([DML, CPU], CARDS)
    cfg = Config(ipc_path="x")
    assert gpu.resolve_startup(cfg, None, valid) is None and cfg.device == "auto"  # varsayılan yok
    cfg.default_gpu = "dml:1"
    assert gpu.resolve_startup(cfg, None, valid) is None and gpu.current_id(cfg) == "dml:1"
    assert gpu.resolve_startup(cfg, "cpu", valid) is None and gpu.current_id(cfg) == "cpu"  # --gpu geçer
    cfg.default_gpu = "dml:7"  # kart artık yok
    warn = gpu.resolve_startup(cfg, None, valid)
    assert "dml:7" in warn and gpu.current_id(cfg) == "auto"
    assert gpu.snapshot(cfg)["default"] == "dml:7"
