"""S2: `sam-bench` (tracker/sam_bench.py). Model dosyası/GPU gerekmez: sahte oturumlar + elle yazılmış minik ONNX."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tracker import sam_bench
from tracker.main import build_parser, main
from tracker.sam_bench import (
    CHAIN,
    GRAPHS,
    VramSampler,
    bench_graph,
    make_fp16,
    markdown_rows,
    random_inputs,
    run_bench,
)

ROOT = Path(__file__).resolve().parents[1]
CPU, CUDA, DML = "CPUExecutionProvider", "CUDAExecutionProvider", "DmlExecutionProvider"
# Gerçek grafiklerin girdi adları/şekilleri (scripts/export_sam2.py başlığı); memenc/memattn K=7, P=16 örneği.
SHAPES = {
    "sam-encoder": {"image": [1, 3, 8, 8]},
    "sam-decoder": {"image_embed": [1, 4, 2, 2], "high_res_feats_0": [1, 2, 4, 4], "high_res_feats_1": [1, 2, 3, 3],
                    "point_coords": [1, 3, 2], "point_labels": [1, 3]},
    "sam-decoder-trk": {"image_embed": [1, 4, 2, 2], "high_res_feats_0": [1, 2, 4, 4], "high_res_feats_1": [1, 2, 3, 3],
                        "point_coords": [1, 1, 2], "point_labels": [1, 1]},
    "sam-memenc": {"image_feat": [1, 4, 2, 2], "low_res_mask": [1, 1, 4, 4], "object_score": [1, 1]},
    "sam-memattn": {"image_feat": [1, 4, 2, 2], "mem_feats": [7, 3, 2], "ptrs": [16, 4]},
}


class FakeSession:
    def __init__(self, inputs, providers=(CPU,), out=None, fail_run=False):
        self._in = [SimpleNamespace(name=n, shape=s, type=t) for n, s, t in inputs]
        self._prov = list(providers)
        self._out = out if out is not None else [np.ones((1, 2), np.float32)]
        self.fail_run, self.feeds = fail_run, []

    def get_inputs(self):
        return self._in

    def get_providers(self):
        return self._prov

    def run(self, names, feed):
        if self.fail_run:
            raise RuntimeError("boom")
        self.feeds.append(feed)
        return self._out


def _inputs(shapes=None, typ="tensor(float)"):
    return [(n, s, typ) for n, s in (shapes or SHAPES["sam-decoder"]).items()]


def _touch(d: Path, names=GRAPHS):
    for n in names:
        (d / f"{n}.onnx").write_bytes(b"x")


def _factory(sess, selected=(CPU,)):
    return lambda path, device: (sess, list(selected))


# --- sözleşme ---

def test_graph_list_matches_the_export_script_and_the_bank_contract():
    export = (ROOT / "scripts/export_sam2.py").read_text(encoding="utf-8")
    assert set(GRAPHS) == set(re.findall(r"(sam-[a-z-]+)\.onnx", export))
    assert set(CHAIN) <= set(GRAPHS) and "sam-decoder" not in CHAIN  # bellekli karede decoder-trk koşar


def test_export_workflow_is_manual_only_and_uploads_the_graphs():
    y = (ROOT / ".github/workflows/sam-export.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in y and "push:" not in y and "pull_request:" not in y and "workflow_call:" not in y
    assert "scripts/export_sam2.py" in y and "--no-memory" not in y  # beş grafiğin hepsi (geri düşüş yok)
    assert "upload-artifact" in y and "sam-models/*.onnx" in y
    assert all(v in y for v in ("edgetam", "small", "base_plus")) and "large" not in y.split("options:")[1]


# --- girdiler ---

def test_random_inputs_follow_shape_dtype_and_roles():
    s = FakeSession(_inputs() + [("object_score", [1, 1], "tensor(float)")])
    f = random_inputs(s)
    assert {n: tuple(a.shape) for n, a in f.items()}["point_coords"] == (1, 3, 2)
    assert (f["point_labels"] == -1).all() and (f["object_score"] == 5).all()
    assert f["point_coords"].min() >= 0 and f["point_coords"].max() < 1024
    assert all(a.dtype == np.float32 for a in f.values())
    assert all(np.array_equal(f[k], random_inputs(s)[k]) for k in f)  # aynı tohum: tekrarlanabilir


def test_random_inputs_fp16_and_dynamic_dims():
    f = random_inputs(FakeSession([("x", ["batch", 3], "tensor(float16)")]))
    assert f["x"].dtype == np.float16 and f["x"].shape == (1, 3)


# --- tek grafik ---

def test_bench_graph_counts_runs_and_reports_provider(tmp_path):
    _touch(tmp_path, ("sam-decoder",))
    sess = FakeSession(_inputs(), providers=(DML, CPU))
    row, outs = bench_graph("sam-decoder", tmp_path / "sam-decoder.onnx", device="dml", runs=5, warmup=2,
                            factory=_factory(sess, (DML, CPU)))
    assert len(sess.feeds) == 7 and row["runs"] == 5 and len(row["warmup_ms"]) == 2
    assert row["provider"] == DML and row["fell_back"] is False and row["finite"] is True
    assert row["peak_vram_mb"] is None  # DirectML: n/a
    assert set(row["stats"]) == {"mean", "p50", "p95", "min"} and len(outs) == 1


def test_bench_graph_flags_silent_cpu_fallback(tmp_path):
    _touch(tmp_path, ("sam-decoder",))
    sess = FakeSession(_inputs(), providers=(CPU,))
    row, _ = bench_graph("sam-decoder", tmp_path / "sam-decoder.onnx", device="cuda", runs=1, warmup=0,
                         factory=_factory(sess, (CUDA, CPU)))
    assert row["fell_back"] is True and row["provider"] == CPU


def test_bench_graph_missing_load_and_run_errors_do_not_raise(tmp_path):
    row, _ = bench_graph("sam-encoder", tmp_path / "nope.onnx", device="cpu", runs=1, warmup=0)
    assert "dosya yok" in row["error"]
    _touch(tmp_path, ("sam-encoder",))

    def bad(path, device):
        raise OSError("dll yok")
    row, _ = bench_graph("sam-encoder", tmp_path / "sam-encoder.onnx", device="cpu", runs=1, warmup=0, factory=bad)
    assert "yükleme" in row["error"] and "dll yok" in row["error"]
    row, _ = bench_graph("sam-encoder", tmp_path / "sam-encoder.onnx", device="cpu", runs=2, warmup=0,
                         factory=_factory(FakeSession(_inputs(), fail_run=True)))
    assert "çalıştırma" in row["error"] and "stats" not in row


def test_nonfinite_outputs_are_flagged(tmp_path):
    _touch(tmp_path, ("sam-decoder",))
    sess = FakeSession(_inputs(), out=[np.array([[1.0, np.nan]], np.float32)])
    row, _ = bench_graph("sam-decoder", tmp_path / "sam-decoder.onnx", device="cpu", runs=1, warmup=0,
                         factory=_factory(sess))
    assert row["finite"] is False


# --- VRAM ---

def test_vram_sampler_keeps_the_peak():
    vals = iter([100.0, 140.0, 120.0] + [110.0] * 1000)
    with VramSampler(lambda: next(vals), interval=0.001) as s:
        pass
    assert s.peak is not None and s.peak >= 100.0
    assert VramSampler(lambda: None).peak is None


def test_peak_vram_is_the_difference_to_the_pre_load_value_on_cuda_only(tmp_path):
    _touch(tmp_path, ("sam-decoder",))
    seq = iter([1000.0])  # yüklemeden önce
    state = {"v": 1000.0}

    def probe():
        v = next(seq, None)
        return state["v"] if v is None else v

    class Growing(FakeSession):
        def run(self, names, feed):
            state["v"] = 1850.0
            return super().run(names, feed)

    row, _ = bench_graph("sam-decoder", tmp_path / "sam-decoder.onnx", device="cuda", runs=2, warmup=1,
                         factory=_factory(Growing(_inputs(), providers=(CUDA, CPU)), (CUDA, CPU)), vram_probe=probe)
    assert row["peak_vram_mb"] == 850.0
    row, _ = bench_graph("sam-decoder", tmp_path / "sam-decoder.onnx", device="dml", runs=1, warmup=0,
                         factory=_factory(FakeSession(_inputs(), providers=(DML,)), (DML,)), vram_probe=probe)
    assert row["peak_vram_mb"] is None


def test_nvidia_smi_missing_returns_none(monkeypatch):
    def nope(*a, **k):
        raise FileNotFoundError("nvidia-smi")
    monkeypatch.setattr(sam_bench.subprocess, "run", nope)
    assert sam_bench.nvidia_smi_used_mb() is None
    monkeypatch.setattr(sam_bench.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="3812\n"))
    assert sam_bench.nvidia_smi_used_mb() == 3812.0


# --- klasör + fp16 ---

def _fake_ort():
    return SimpleNamespace(__version__="9.9", get_available_providers=lambda: [DML, CPU])


def test_run_bench_reports_missing_graphs_and_chain(tmp_path):
    _touch(tmp_path, ("sam-encoder", "sam-decoder-trk", "sam-memenc", "sam-memattn"))
    sess = FakeSession(_inputs())
    rep = run_bench(tmp_path, "cpu", runs=2, warmup=1, ort=_fake_ort(), factory=_factory(sess), vram_probe=None)
    by = {r["graph"]: r for r in rep["rows"]}
    assert "dosya yok" in by["sam-decoder"]["error"] and "stats" in by["sam-encoder"]
    assert set(rep["chain_ms"]) == {"fp32"} and rep["ort_version"] == "9.9"
    json.dumps(rep)  # JSON'a çevrilebilir


def test_run_bench_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_bench(tmp_path / "yok", "cpu", ort=_fake_ort())


def test_fp16_rows_use_the_converter_and_compare_outputs(tmp_path):
    _touch(tmp_path, ("sam-encoder",))
    calls = []

    def conv(src, dst):
        calls.append((src.name, dst.parent.name))
        dst.write_bytes(b"y")

    outs = iter([[np.full((1, 2), 1.0, np.float32)], [np.full((1, 2), 1.5, np.float32)]])

    class Seq(FakeSession):
        def run(self, names, feed):
            return self._out

    made = []

    def factory(path, device):
        s = Seq(_inputs(), out=next(outs))
        made.append(path.parent.name)
        return s, [CPU]

    rep = run_bench(tmp_path, "cpu", runs=1, warmup=0, fp16=True, ort=_fake_ort(), factory=factory,
                    vram_probe=None, converter=conv, graphs=("sam-encoder",))
    assert calls == [("sam-encoder.onnx", "fp16")] and made[1] == "fp16"
    r16 = rep["rows"][1]
    assert r16["precision"] == "fp16" and abs(r16["max_rel_diff"] - 0.5 / 1.0) < 1e-6


def test_fp16_without_converter_package_is_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "onnxconverter_common", None)  # import -> ImportError
    src, dst = tmp_path / "a.onnx", tmp_path / "fp16" / "a.onnx"
    src.write_bytes(b"x")
    assert "onnxconverter-common" in make_fp16(src, dst)

    def bad(s, d):
        d.write_bytes(b"partial")
        raise ValueError("kötü")
    assert make_fp16(src, dst, converter=bad).startswith("fp16 dönüşümü başarısız")
    assert not dst.exists()  # yarım dosya bırakılmaz


def test_existing_fp16_file_is_reused(tmp_path):
    src, dst = tmp_path / "a.onnx", tmp_path / "fp16" / "a.onnx"
    src.write_bytes(b"x")
    dst.parent.mkdir()
    dst.write_bytes(b"y")
    assert make_fp16(src, dst, converter=lambda s, d: pytest.fail("yeniden üretilmemeli")) is None


# --- çıktı ---

def test_markdown_rows_match_the_test_results_table(tmp_path):
    _touch(tmp_path, ("sam-encoder",))
    rep = run_bench(tmp_path, "cpu", runs=2, warmup=1, ort=_fake_ort(), factory=_factory(FakeSession(_inputs())),
                    vram_probe=None, graphs=("sam-encoder", "sam-memenc"))
    md = markdown_rows(rep, date="2026-11-18").splitlines()
    results = (ROOT / "docs/TEST_RESULTS.md").read_text(encoding="utf-8")
    assert md[0] in results  # başlık, TEST_RESULTS.md'deki tabloyla aynı
    assert md[2].startswith("| 2026-11-18 | " + tmp_path.name + "/sam-encoder | CPUExecutionProvider | fp32 |")
    assert "| n/a |" in md[2] and "ERROR dosya yok" in md[3]
    assert all(len(r.split("|")) == len(md[0].split("|")) for r in md if r.startswith("| 2"))


# --- CLI ---

def test_cli_arguments():
    a = build_parser().parse_args(["sam-bench", "models/sam", "--device", "cuda", "--runs", "5", "--fp16"])
    assert (a.cmd, a.model_dir, a.device, a.runs, a.warmup, a.fp16) == ("sam-bench", "models/sam", "cuda", 5, 3, True)


def test_cli_missing_dir_exits_1(tmp_path):
    assert main(["sam-bench", str(tmp_path / "yok")]) == 1


# --- gerçek ONNX Runtime, CPU, elle yazılmış minik grafikler ---

def _varint(n):
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _ld(num, data):
    data = data.encode() if isinstance(data, str) else data
    return _varint(num << 3 | 2) + _varint(len(data)) + data


def _vi(num, val):
    return _varint(num << 3) + _varint(val)


def _tiny_onnx(path, inputs):
    """Identity(ilk girdi) -> out0; başka girdiler kullanılmaz. Gerçek onnx paketi gerekmez."""
    def info(name, shape):
        dims = b"".join(_ld(1, _vi(1, d)) for d in shape)
        return _ld(1, name) + _ld(2, _ld(1, _vi(1, 1) + _ld(2, dims)))
    first = next(iter(inputs))
    graph = (_ld(1, _ld(1, first) + _ld(2, "out0") + _ld(4, "Identity")) + _ld(2, "g")
             + b"".join(_ld(11, info(n, s)) for n, s in inputs.items()) + _ld(12, info("out0", inputs[first])))
    path.write_bytes(_vi(1, 8) + _ld(7, graph) + _ld(8, _vi(2, 13)))


def test_real_onnxruntime_cpu_end_to_end(tmp_path):
    pytest.importorskip("onnxruntime")
    for g in GRAPHS:
        _tiny_onnx(tmp_path / f"{g}.onnx", SHAPES[g])
    out = tmp_path / "rapor.json"
    assert main(["sam-bench", str(tmp_path), "--device", "cpu", "--runs", "3", "--warmup", "1", "--out", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert [r["graph"] for r in rep["rows"]] == list(GRAPHS)
    assert all(r["provider"] == CPU and r["finite"] is True and r["runs"] == 3 and not r["fell_back"] for r in rep["rows"])
    assert set(rep["chain_ms"]) == {"fp32"}
    assert out.with_suffix(".md").read_text(encoding="utf-8").startswith("| Date |")
