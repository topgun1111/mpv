"""S2: EdgeTAM / SAM 2.1 grafikleri için PC kıyası (`python -m tracker sam-bench MODEL_DIR`).

Beş statik grafik (`scripts/export_sam2.py`): sam-encoder, sam-decoder, sam-decoder-trk, sam-memenc,
sam-memattn. Her biri için: yükleme süresi, ısınma, ortalama gecikme (N koşu), gerçekte kullanılan
sağlayıcı, hata ve (yalnız CUDA'da) tepe VRAM. Girdiler rastgele ama doğru şekil/tipte
(Android `SamEngine.randomInputs` ile aynı kural); gecikme, girdilerin host'tan aygıta kopyasını
içerir, ön/son işlemeyi içermez.

`--fp16`: her grafiğin fp16 ağırlıklı sürümünü de ölçer (G/Ç fp32 kalır). Sürüm `MODEL_DIR/fp16/`
altında aranır; yoksa `onnx` + `onnxconverter-common` kuruluysa üretilir. fp32 ile çıktı farkı ve
NaN/Inf denetimi satıra yazılır: hızlı ama bozuk bir fp16 sonuç sayılmaz.

`onnxruntime` yalnız burada (tembel) içe aktarılır; testler sahte oturum/yoklayıcı verir.
"""
from __future__ import annotations

import contextlib
import gc
import json
import statistics
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from . import tracklog
from .bench import _pct
from .detector import (
    _PROVIDER_NAMES,
    ort_providers,
    preload_cuda,
    resolve_model_path,
    select_providers,
)
from .providers import installed_ort_packages

GRAPHS = ("sam-encoder", "sam-decoder", "sam-decoder-trk", "sam-memenc", "sam-memattn")
# Bellekli takip karesinde sırayla çalışan grafikler (ilk kare: encoder + decoder + memenc).
CHAIN = ("sam-encoder", "sam-memattn", "sam-decoder-trk", "sam-memenc")
IMAGE_SIDE = 1024  # `point_coords` 1024 px uzayındadır
FP16_DIR = "fp16"
TABLE_HEADER = ("| Date | Model/graph | Provider | Precision | Load s | Warm-up ms | Avg ms "
                "| Peak VRAM MB | Notes |\n|---|---|---|---|---|---|---|---|---|")

VramProbe = Callable[[], float | None]
SessionFactory = Callable[[Path, str], tuple[Any, list[str]]]


# --- girdiler ---

def random_inputs(session: Any, seed: int = 1) -> dict[str, np.ndarray]:
    """Oturumun girdi şekil/tiplerine uyan rastgele girdiler (Kotlin `randomInputs` kuralı).

    `*labels` = -1 (kullanılmayan slot), `*coords` = [0, 1024) px, `object_score` = 5, kalanı N(0, 0.5).
    """
    rng = np.random.default_rng(seed)
    feed: dict[str, np.ndarray] = {}
    for inp in session.get_inputs():
        shape = [d if isinstance(d, int) and d > 0 else 1 for d in (inp.shape or [])]
        dtype = np.float16 if "float16" in str(getattr(inp, "type", "")) else np.float32
        n = inp.name
        if n.endswith("labels"):
            a = np.full(shape, -1.0)
        elif n.endswith("coords"):
            a = rng.random(shape) * IMAGE_SIDE
        elif n == "object_score":
            a = np.full(shape, 5.0)
        else:
            a = rng.standard_normal(shape) * 0.5
        feed[n] = a.astype(dtype)
    return feed


def stats(ms: list[float]) -> dict[str, float]:
    return {"mean": statistics.fmean(ms), "p50": _pct(ms, 0.5), "p95": _pct(ms, 0.95), "min": min(ms)}


# --- VRAM ---

def nvidia_smi_used_mb() -> float | None:
    """İlk GPU'nun kullanılan belleği (MB) `nvidia-smi` ile; yoksa/başarısızsa None.

    Tüm GPU'yu ölçer (başka uygulamalar da sayılır); bu yüzden satır, yüklemeden ÖNCEki değerden
    farkı verir.
    """
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        return float(r.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


class VramSampler:
    """Koşu boyunca VRAM'i yoklar; `peak` en büyük görülen değerdir (hiç ölçülemezse None)."""

    def __init__(self, probe: VramProbe, interval: float = 0.1) -> None:
        self.probe, self.interval = probe, interval
        self.peak: float | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _sample(self) -> None:
        v = self.probe()
        if v is not None:
            self.peak = v if self.peak is None else max(self.peak, v)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self._sample()

    def __enter__(self) -> VramSampler:
        self._sample()
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()
        self._sample()


# --- oturum ---

def open_session(path: Path, device: str, ort: Any = None) -> tuple[Any, list[str]]:
    """Detector ile aynı sağlayıcı seçimi ve DirectML ayarları; (oturum, istenen sağlayıcılar)."""
    if ort is None:
        import onnxruntime as ort
    sel = select_providers(ort.get_available_providers(), device)
    if _PROVIDER_NAMES["cuda"] in sel:
        preload_cuda(ort)
    opts = ort.SessionOptions()
    if _PROVIDER_NAMES["dml"] in sel:
        opts.enable_mem_pattern = False
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    sess = ort.InferenceSession(str(path), sess_options=opts, providers=ort_providers(sel))
    tracklog.model_opened(path, sel, sess)
    return sess, sel


def _onnx_fp16(src: Path, dst: Path) -> None:
    import onnx
    from onnxconverter_common import float16

    onnx.save(float16.convert_float_to_float16(onnx.load(str(src)), keep_io_types=True), str(dst))


def make_fp16(src: Path, dst: Path, converter: Callable[[Path, Path], None] | None = None) -> str | None:
    """`src` grafiğinin fp16 ağırlıklı kopyasını `dst`'ye yazar (G/Ç fp32). None = hazır; yoksa neden."""
    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
        return None
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        (converter or _onnx_fp16)(src, dst)
    except ImportError:
        return "fp16 üretilemedi: `pip install onnx onnxconverter-common` gerekir"
    except Exception as e:  # dönüştürücü kütüphane çeşitli hatalar verebilir
        dst.unlink(missing_ok=True)
        return f"fp16 dönüşümü başarısız: {type(e).__name__}: {e}"
    return None


# --- ölçüm ---

def bench_graph(name: str, path: Path, *, device: str, runs: int, warmup: int, precision: str = "fp32",
                factory: SessionFactory | None = None, vram_probe: VramProbe | None = None,
                ref_outputs: list[np.ndarray] | None = None) -> tuple[dict[str, Any], list[np.ndarray]]:
    """Tek grafiği ölçer. Döner: (satır sözlüğü, son çıktılar). Hata satıra yazılır, fırlatılmaz."""
    row: dict[str, Any] = {"graph": name, "file": path.name, "precision": precision}
    if not path.is_file():
        row["error"] = f"dosya yok: {path}"
        return row, []
    factory = factory or open_session
    base = vram_probe() if vram_probe else None  # yüklemeden önce: fark alınacak
    t0 = time.perf_counter()
    try:
        sess, sel = factory(path, device)
    except Exception as e:  # yükleme hatası (DLL, desteklenmeyen op...) raporlanır
        row["error"] = f"yükleme: {type(e).__name__}: {e}"
        return row, []
    row["load_s"] = round(time.perf_counter() - t0, 3)
    used = list(sess.get_providers())
    row["provider"] = used[0] if used else "?"
    row["fell_back"] = bool(used) and used[0] != sel[0]
    cuda = row["provider"] == _PROVIDER_NAMES["cuda"]
    feed = random_inputs(sess)
    outs: list[np.ndarray] = []
    warm: list[float] = []
    times: list[float] = []
    sampler = VramSampler(vram_probe) if (vram_probe and cuda) else None
    try:
        with sampler or contextlib.nullcontext():
            for i in range(warmup + runs):
                t = time.perf_counter()
                res = sess.run(None, feed)
                ms = (time.perf_counter() - t) * 1000
                (warm if i < warmup else times).append(ms)
                outs = [np.asarray(r) for r in res]
    except Exception as e:
        row["error"] = f"çalıştırma: {type(e).__name__}: {e}"
    row["warmup_ms"] = [round(w, 2) for w in warm]
    if times:
        row["stats"] = {k: round(v, 2) for k, v in stats(times).items()}
        row["runs"] = len(times)
    row["finite"] = all(bool(np.isfinite(o.astype(np.float32)).all()) for o in outs) if outs else None
    row["peak_vram_mb"] = (round(sampler.peak - base, 1) if sampler and sampler.peak is not None
                           and base is not None else None)
    if ref_outputs and outs and len(ref_outputs) == len(outs):
        row["max_rel_diff"] = float(max(
            float(np.abs(a.astype(np.float32) - b.astype(np.float32)).max()) / max(1.0, float(np.abs(b).max()))
            for a, b in zip(outs, ref_outputs)))
    del sess
    gc.collect()
    return row, outs


def run_bench(model_dir: str | Path, device: str = "auto", runs: int = 20, warmup: int = 3,
              fp16: bool = False, *, ort: Any = None, factory: SessionFactory | None = None,
              vram_probe: VramProbe | None = nvidia_smi_used_mb,
              converter: Callable[[Path, Path], None] | None = None,
              graphs: tuple[str, ...] = GRAPHS) -> dict[str, Any]:
    """Klasördeki grafikleri ölçer (yoksa satırda hata). `ort`/`factory`/`vram_probe` testler içindir."""
    d = resolve_model_path(model_dir)
    if not d.is_dir():
        raise FileNotFoundError(f"model klasörü yok: {d}")
    if ort is None and factory is None:
        import onnxruntime as ort
    make: SessionFactory = factory or (lambda p, dev: open_session(p, dev, ort))
    avail = list(ort.get_available_providers()) if ort is not None else []
    rep: dict[str, Any] = {
        "model": d.name, "model_dir": str(d), "device": device, "runs": runs, "warmup": warmup,
        "ort_version": getattr(ort, "__version__", "?"), "packages": installed_ort_packages(),
        "available": avail, "selected": select_providers(avail, device) if avail else [],
        "rows": [],
    }
    for g in graphs:
        row, ref = bench_graph(g, d / f"{g}.onnx", device=device, runs=runs, warmup=warmup,
                               factory=make, vram_probe=vram_probe)
        rep["rows"].append(row)
        if not fp16 or "stats" not in row:
            continue
        src = d / f"{g}.onnx"
        dst = d / FP16_DIR / f"{g}.onnx"
        why = make_fp16(src, dst, converter)
        if why:
            rep["rows"].append({"graph": g, "file": dst.name, "precision": "fp16", "error": why})
            continue
        row16, _ = bench_graph(g, dst, device=device, runs=runs, warmup=warmup, precision="fp16",
                               factory=make, vram_probe=vram_probe, ref_outputs=ref)
        rep["rows"].append(row16)
    rep["chain_ms"] = _chain(rep["rows"])
    rep["hints"] = _hints(rep)
    return rep


def _chain(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Bir takip karesinin ölçülen ortalamalarının toplamı (her duyarlık için, hepsi varsa)."""
    out: dict[str, float] = {}
    for prec in ("fp32", "fp16"):
        m = {r["graph"]: r["stats"]["mean"] for r in rows
             if r["precision"] == prec and "error" not in r and "stats" in r}
        if all(g in m for g in CHAIN):
            out[prec] = round(sum(m[g] for g in CHAIN), 2)
    return out


def _hints(rep: dict[str, Any]) -> list[str]:
    out: list[str] = []
    rows = [r for r in rep["rows"] if "provider" in r]
    if any(r.get("fell_back") for r in rows):
        out.append("En az bir grafik istenen sağlayıcıyla açılamadı ve düştü: o satırların süreleri GPU "
                   "değildir. `python -m tracker providers --model <graf>` ile bakın.")
    if rep["device"] in ("dml", "cuda") and any(r["provider"] == "CPUExecutionProvider" for r in rows):
        out.append(f"--device {rep['device']} istendi ama bazı satırlar CPU'da koştu.")
    if any(r.get("finite") is False for r in rows):
        out.append("Bazı çıktılarda NaN/Inf var: o satırın hızı geçerli sayılmaz.")
    return out


# --- çıktı ---

def _cell(v: Any, fmt: str = "{}") -> str:
    return "—" if v is None else fmt.format(v)


def markdown_rows(rep: dict[str, Any], date: str | None = None) -> str:
    """`docs/TEST_RESULTS.md` GPU tablosuna yapıştırılacak satırlar (başlık dahil)."""
    date = date or time.strftime("%Y-%m-%d")
    lines = [TABLE_HEADER]
    for r in rep["rows"]:
        label = f"{rep['model']}/{r['graph']}"
        notes: list[str] = []
        st = r.get("stats")
        if st:
            notes.append(f"p50 {st['p50']} · p95 {st['p95']} · {r['runs']} runs")
        if r.get("fell_back"):
            notes.append("FELL BACK")
        if r.get("finite") is False:
            notes.append("NaN/Inf")
        if "max_rel_diff" in r:
            notes.append(f"max rel diff vs fp32 {r['max_rel_diff']:.3g}")
        if "error" in r:
            notes.append("ERROR " + r["error"])
        vram = r.get("peak_vram_mb")
        lines.append(
            f"| {date} | {label} | {r.get('provider', '—')} | {r['precision']} | {_cell(r.get('load_s'))} "
            f"| {_cell((r.get('warmup_ms') or [None])[0])} | {_cell(st and st['mean'])} "
            f"| {_cell(vram, '{:.0f}') if vram is not None else 'n/a'} | {' · '.join(notes)} |")
    return "\n".join(lines)


def format_report(rep: dict[str, Any]) -> str:
    L = [f"ONNX Runtime {rep['ort_version']} · model: {rep['model']} · --device {rep['device']} -> "
         f"{', '.join(rep['selected']) or '?'} · {rep['runs']} koşu, {rep['warmup']} ısınma"]
    for r in rep["rows"]:
        head = f"{r['graph']} [{r['precision']}]"
        if "error" in r and "provider" not in r:
            L.append(f"{head}: HATA {r['error']}")
            continue
        st = r.get("stats")
        speed = f"{st['mean']:.1f} ms ort · p50 {st['p50']:.1f} · p95 {st['p95']:.1f}" if st else "ölçülemedi"
        extra = f" · fark {r['max_rel_diff']:.3g}" if "max_rel_diff" in r else ""
        err = f" · HATA {r['error']}" if "error" in r else ""
        L.append(f"{head}: {speed} · yükleme {r.get('load_s')} sn · {r['provider']}{extra}{err}")
    for prec, ms in rep["chain_ms"].items():
        L.append(f"Bir takip karesi ({prec}): {ms} ms = encoder + memattn + decoder-trk + memenc "
                 "ölçülen ortalamalarının toplamı (ön/son işleme hariç)")
    for h in rep["hints"]:
        L.append("UYARI: " + h)
    return "\n".join(L)


def to_json(rep: dict[str, Any]) -> str:
    return json.dumps(rep, ensure_ascii=False, indent=2)


def save_report(rep: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(to_json(rep), encoding="utf-8")
