"""Otomatik doğrulama (S14): klip klasörünü ver, her şeyi koştursun, rapor yazsın.

    python -m tracker.autotest                 # klipler\\ klasöründeki tüm videolar
    python -m tracker.autotest --clips D --quick

Klip başına (sırayla): eski izleyici temeli -> `sam-track` (hepsi açık) -> `sam-refine --plan` ->
`sam-refine --camera` -> `export` -> `export --stabilize`. Sonra ÜRETİLEN dosyalardan otomatik
denetimler (doluluk, zoom titremesi, durumlar, VRAM, dışa aktarma). Çıktı: `<out>/<zaman>/report.md`
+ `report.json` + her adımın günlüğü. Hata varsa çıkış kodu 1.

Klip yanına isteğe bağlı `X.mp4.test.json`:
  {"rect": [x1, y1, x2, y2], "start": 0.0,
   "expect": {"min_tracked": 0.7, "states_include": ["OUT_OF_FRAME"], "states_exclude": []}}
`rect` yoksa ilk karede person tespitinin alt yarısı alınır (önizleme PNG'si rapor klasöründe: bak).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIDEO_EXT = (".mp4", ".mkv", ".mov", ".avi", ".webm")
PASS, FAIL, INFO, SKIP = "GEÇTİ", "KALDI", "BİLGİ", "ATLANDI"

# Eşikler (ilk tahmin; gerçek kliplerden sonra ayarla)
MIN_TRACKED = 0.70
OCC_TOL = 0.10  # doluluk ortancası lower_fill ± bu
PUMP_STEP = 0.05  # log2: bundan küçük zoom adımı titreme sayılmaz
PUMP_PER_MIN = 4.0  # dakikada en çok bu kadar zoom yön değişimi
RATE_SLACK = 1.10  # en hızlı zoom değişimi <= lower_zoom_rate * 1.5 * bu
VRAM_LIMIT_MB = 5800  # 6 GB kartta pay bırak


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


@dataclass
class Step:
    name: str
    cmd: list[str]
    code: int | None = None
    seconds: float = 0.0
    log: str = ""
    tail: str = ""


@dataclass
class ClipResult:
    clip: str
    rect: list[float] | None = None
    rect_source: str = ""
    steps: list[Step] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    peak_vram_mb: float | None = None


# ---------------------------------------------------------------- saf denetimler (testlenir)

def auto_rect(box: tuple[float, float, float, float], size: tuple[int, int]) -> list[float]:
    """Person kutusunun alt yarısı (bacaklar + ayaklar), kare içinde."""
    x1, y1, x2, y2 = box
    w, h = size
    top = y1 + 0.5 * (y2 - y1)
    return [max(0.0, x1), max(0.0, top), min(float(w), x2), min(float(h), y2)]


def zoom_pumping(views: list[list[float]]) -> dict[str, float]:
    """Zoom anahtar karelerinden: yön değişimi sayısı (|adım| > PUMP_STEP), dakika başına oran, en hızlı değişim."""
    if len(views) < 2:
        return {"reversals": 0, "per_min": 0.0, "max_rate": 0.0}
    steps: list[float] = []
    max_rate = 0.0
    for a, b in zip(views, views[1:], strict=False):
        dz, dt = b[1] - a[1], b[0] - a[0]
        if dt > 1e-6:
            max_rate = max(max_rate, abs(dz) / dt)
        if abs(dz) > PUMP_STEP:
            steps.append(dz)
    rev = sum(1 for a, b in zip(steps, steps[1:], strict=False) if a * b < 0)
    dur = max(views[-1][0] - views[0][0], 1e-6)
    return {"reversals": rev, "per_min": rev / (dur / 60.0), "max_rate": max_rate}


def check_tracking(doc: dict[str, Any], expect: dict[str, Any]) -> list[Check]:
    c = doc.get("counts", {})
    n, tr = c.get("frames", 0), c.get("tracked", 0)
    need = float(expect.get("min_tracked", MIN_TRACKED))
    out = [Check("izlenen kare oranı", PASS if n and tr / n >= need else FAIL,
                 f"{tr}/{n} = {tr / n:.2f} (en az {need:.2f})" if n else "kare yok")]
    counts = (doc.get("state") or {}).get("counts", {})
    for s in expect.get("states_include", []):
        out.append(Check(f"durum görüldü: {s}", PASS if counts.get(s) else FAIL, f"{counts.get(s, 0)} kare"))
    for s in expect.get("states_exclude", []):
        out.append(Check(f"durum görülmedi: {s}", PASS if not counts.get(s) else FAIL, f"{counts.get(s, 0)} kare"))
    out.append(Check("durum sayıları", INFO, json.dumps(counts, ensure_ascii=False)))
    gate = doc.get("gate") or {}
    out.append(Check("kapı", INFO, f"reddedilen {gate.get('rejected', 0)}, temiz olmayan {gate.get('unclean', 0)}"))
    post = doc.get("posture")
    if post:
        f = post["fields"]
        di, pi = f.index("desk"), f.index("posture")
        rows = post["rows"]
        desk = sum(1 for r in rows if r[di])
        words: dict[str, int] = {}
        for r in rows:
            words[r[pi]] = words.get(r[pi], 0) + 1
        out.append(Check("duruş / masa", INFO, f"masa maskesi reddi {desk} kare; duruş {words}"))
    re = doc.get("reentry")
    if re:
        out.append(Check("Re-ID kararları", INFO, json.dumps(re.get("counts", {}), ensure_ascii=False)))
    return out


def check_camera(doc: dict[str, Any], cfg: Any | None = None) -> list[Check]:
    from . import camera
    from .config import Config

    cfg = cfg or Config()
    cam, src = camera.views_from_doc(doc, cfg)
    out: list[Check] = []
    occ = sorted(o for o, ok in zip(cam.occupancy, cam.zoom_ok, strict=False) if ok and o is not None)
    if occ:
        med = statistics.median(occ)
        ok = abs(med - cfg.lower_fill) <= OCC_TOL
        out.append(Check("doluluk (ortanca)", PASS if ok else FAIL,
                         f"{med:.2f}, hedef {cfg.lower_fill:.2f} ± {OCC_TOL:.2f} (bölge: {src})"))
    else:
        out.append(Check("doluluk (ortanca)", FAIL, "zoom'a girdi olan kare yok"))
    p = zoom_pumping(cam.views)
    out.append(Check("zoom titremesi", PASS if p["per_min"] <= PUMP_PER_MIN else FAIL,
                     f"{p['reversals']} yön değişimi, {p['per_min']:.1f}/dk (en çok {PUMP_PER_MIN:.0f})"))
    lim = cfg.lower_zoom_rate * 1.5 * RATE_SLACK
    out.append(Check("zoom hız sınırı", PASS if p["max_rate"] <= lim else FAIL,
                     f"en hızlı {p['max_rate']:.2f} log2/sn (sınır {lim:.2f})"))
    out.append(Check("kamera özeti", INFO, cam.summary()))
    return out


def check_refined(orig: dict[str, Any], refined: dict[str, Any]) -> list[Check]:
    n0, n1 = len(orig["records"]), len(refined["records"])
    out = [Check("iyileştirme kare sayısı", PASS if n0 == n1 else FAIL, f"{n0} -> {n1}")]
    t0 = orig["counts"]["tracked"]
    t1 = refined["counts"]["tracked"]
    out.append(Check("iyileştirme izlenen kare", PASS if t1 >= t0 else FAIL, f"{t0} -> {t1} (azalmamalı)"))
    rf = refined.get("refine") or {}
    out.append(Check("iyileştirme özeti", INFO, json.dumps(rf.get("summary", rf.get("counts", {})),
                                                            ensure_ascii=False)[:300]))
    return out


def check_export(step: Step, label: str) -> Check:
    ok = step.code == 0 and "doğrulama: tamam" in step.tail
    return Check(f"dışa aktarma {label}", PASS if ok else FAIL,
                 f"çıkış {step.code}; " + ("doğrulama tamam" if ok else "doğrulama tamam satırı yok (günlüğe bak)"))


# ---------------------------------------------------------------- GPU belleği

def gpu_used_mb() -> float | None:
    """nvidia-smi (NVIDIA) ya da Windows `typeperf` (DirectML dahil, bütün kartlar); yoksa None."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip().splitlines()[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    if os.name == "nt":
        try:
            r = subprocess.run(["typeperf", r"\GPU Adapter Memory(*)\Dedicated Usage", "-sc", "1"],
                               capture_output=True, text=True, timeout=10)
            vals = []
            for line in r.stdout.splitlines()[1:3]:
                for cell in line.split(","):
                    cell = cell.strip().strip('"')
                    try:
                        vals.append(float(cell))
                    except ValueError:
                        pass
            if vals:
                return max(vals) / 1048576.0
        except (OSError, subprocess.SubprocessError):
            pass
    return None


class GpuSampler:
    def __init__(self, every: float = 2.0) -> None:
        self.every, self.peak, self.base = every, None, gpu_used_mb()
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self.every):
            v = gpu_used_mb()
            if v is not None and (self.peak is None or v > self.peak):
                self.peak = v

    def __enter__(self) -> GpuSampler:
        if self.base is not None:
            self._t.start()
        return self

    def __exit__(self, *a: object) -> None:
        self._stop.set()

    @property
    def peak_mb(self) -> float | None:
        return self.peak


# ---------------------------------------------------------------- adım koşturma

def run_step(name: str, args: list[str], logdir: Path, timeout: float | None = None) -> Step:
    cmd = [sys.executable, "-m", "tracker", *args]
    st = Step(name, cmd, log=str(logdir / (name.replace(" ", "_").replace("/", "-") + ".log")))
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        st.code, text = r.returncode, (r.stdout or "") + ("\n--- stderr ---\n" + r.stderr if r.stderr else "")
    except subprocess.TimeoutExpired:
        st.code, text = 124, "ZAMAN AŞIMI"
    except OSError as e:
        st.code, text = 127, f"başlatılamadı: {e}"
    st.seconds = time.time() - t0
    Path(st.log).write_text(f"$ {' '.join(cmd)}\n\n{text}", encoding="utf-8")
    st.tail = text[-4000:]
    return st


def load_json(p: Path) -> dict[str, Any] | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def first_frame_rect(video: Path, start: float, logdir: Path) -> tuple[list[float] | None, str]:
    import cv2

    from .config import Config
    from .detector import Detector

    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None, "kare okunamadı"
    try:
        dets = Detector(Config().model_path, device="auto").detect(frame)
    except Exception as e:  # model yok vb.
        return None, f"tespit çalışmadı: {e}"
    if not dets:
        return None, "ilk karede kişi bulunamadı (X.mp4.test.json ile rect ver)"
    best = max(dets, key=lambda d: (d.bbox[2] - d.bbox[0]) * (d.bbox[3] - d.bbox[1]))
    h, w = frame.shape[:2]
    rect = auto_rect(tuple(best.bbox), (w, h))
    prev = frame.copy()
    cv2.rectangle(prev, (int(rect[0]), int(rect[1])), (int(rect[2]), int(rect[3])), (0, 255, 255), 3)
    cv2.imwrite(str(logdir / f"{video.stem}.rect.png"), prev)
    return rect, "otomatik (kişi kutusunun alt yarısı)"


# ---------------------------------------------------------------- klip akışı

def process_clip(video: Path, a: argparse.Namespace, logdir: Path) -> ClipResult:
    res = ClipResult(video.name)
    side = load_json(video.with_name(video.name + ".test.json")) or {}
    start = float(side.get("start", 0.0))
    expect = side.get("expect", {})
    clog = logdir / video.stem
    clog.mkdir(parents=True, exist_ok=True)
    if side.get("rect"):
        res.rect, res.rect_source = [float(v) for v in side["rect"]], "test.json"
    else:
        res.rect, res.rect_source = first_frame_rect(video, start, clog)
    if not res.rect:
        res.checks.append(Check("seçim dikdörtgeni", FAIL, res.rect_source))
        return res
    res.checks.append(Check("seçim dikdörtgeni", INFO, f"{[round(v) for v in res.rect]} · {res.rect_source}"))
    v = str(video)
    rect = ",".join(f"{x:.0f}" for x in res.rect)
    dev = ["--device", a.device]

    def go(name: str, args: list[str]) -> Step:
        s = run_step(name, args, clog)
        res.steps.append(s)
        print(f"  [{'ok' if s.code == 0 else 'HATA'}] {video.name}: {name} ({s.seconds:.0f} sn)", flush=True)
        return s

    if not a.no_baseline:
        import cv2

        cap = cv2.VideoCapture(v)
        W, H = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        cap.release()
        nx = [res.rect[0] / W, res.rect[1] / H, res.rect[2] / W, res.rect[3] / H]
        s = go("0 eski izleyici", ["offline", v, "--pose", *dev, "--select-rect", f"{start:.3f}",
                                    *[f"{x:.4f}" for x in nx]])
        if s.code == 0:
            go("0 eski izleyici dışa aktarma", ["export", v, "--out", str(clog / "base.mp4")])

    with GpuSampler() as g:
        s = go("1 sam-track", ["sam-track", a.model_dir, v, "--rect", rect, "--start", f"{start}",
                               "--max-seconds", str(a.max_seconds), *dev, "--preview", "--posture",
                               "--reid", "--camera"])
        res.peak_vram_mb = g.peak_mb
        if s.code != 0:
            res.checks.append(Check("sam-track", FAIL, f"çıkış {s.code}; günlük: {s.log}"))
            return res
        doc = load_json(Path(v + ".sam.json"))
        if not doc:
            res.checks.append(Check("sam-track kaydı", FAIL, "<video>.sam.json okunamadı"))
            return res
        res.checks += check_tracking(doc, expect)
        res.checks += check_camera(doc)
        go("2 sam-refine --plan", ["sam-refine", a.model_dir, v + ".sam.json", "--plan"])
        s = go("3 sam-refine", ["sam-refine", a.model_dir, v + ".sam.json", *dev, "--camera"])
        if g.peak_mb is not None or res.peak_vram_mb is not None:
            res.peak_vram_mb = max(x for x in (g.peak_mb, res.peak_vram_mb) if x is not None)
    ref = load_json(Path(v + ".sam.refined.json"))
    if s.code == 0 and ref:
        res.checks += check_refined(doc, ref)
        res.checks += check_camera(ref)
    else:
        res.checks.append(Check("sam-refine", FAIL, f"çıkış {s.code}; günlük: {s.log}"))
    if res.peak_vram_mb is None:
        res.checks.append(Check("GPU belleği", SKIP, "ölçülemedi (nvidia-smi / typeperf yok)"))
    else:
        res.checks.append(Check("GPU belleği (tepe, tüm kart)", PASS if res.peak_vram_mb <= VRAM_LIMIT_MB else FAIL,
                                f"{res.peak_vram_mb:.0f} MB, sınır {VRAM_LIMIT_MB} MB"))
    res.checks.append(check_export(go("4 export", ["export", v, "--out", str(clog / "sam.mp4")]), "(düz)"))
    if not a.quick:
        res.checks.append(check_export(
            go("5 export --stabilize", ["export", v, "--stabilize", "--decode", "auto",
                                        "--out", str(clog / "sam_stab.mp4")]), "(sabitlemeli)"))
    return res


def preflight(a: argparse.Namespace, logdir: Path) -> list[Check]:
    out: list[Check] = []
    for name, args in (("providers", ["providers", "--device", a.device]),):
        s = run_step(name, args, logdir)
        out.append(Check(name, PASS if s.code == 0 else FAIL, f"çıkış {s.code}"))
    r = subprocess.run([sys.executable, "-m", "tracker.export_check"], cwd=ROOT, capture_output=True, text=True)
    try:
        rep = json.loads(r.stdout)
        out.append(Check("ffmpeg kodlayıcıları", INFO,
                         f"NVENC listede {rep['listed'].get('h264_nvenc')}, NVENC çalışıyor {rep['nvenc_works']}"))
    except (ValueError, KeyError):
        out.append(Check("ffmpeg kodlayıcıları", FAIL, "export_check çıktısı okunamadı"))
    if not a.skip_bench:
        s = run_step("sam-bench", ["sam-bench", a.model_dir, "--device", a.device, "--out",
                                   str(logdir / "sam-bench.json")], logdir)
        out.append(Check("sam-bench (5 grafik)", PASS if s.code == 0 else FAIL,
                         f"çıkış {s.code}; günlük: {s.log}"))
    return out


# ---------------------------------------------------------------- masaüstü

def desktop_dir() -> Path:
    """Masaüstü klasörü (OneDrive yönlendirmesi dahil: Windows'ta Bilinen Klasör API'si); bulunamazsa ~/Desktop."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            guid = ctypes.c_byte * 16
            fid = guid(*bytes.fromhex("3accbfb42cdb4c42b0297fe99a87c641"))  # FOLDERID_Desktop
            buf = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, wintypes.HANDLE(0),
                                                          ctypes.byref(buf)) == 0 and buf.value:
                return Path(buf.value)
        except Exception:
            pass
    d = Path.home() / "Desktop"
    return d if d.is_dir() else Path.home()


# ---------------------------------------------------------------- rapor

def write_report(logdir: Path, pre: list[Check], clips: list[ClipResult]) -> bool:
    fails = [c for c in pre if c.status == FAIL] + [c for r in clips for c in r.checks if c.status == FAIL]
    md = ["# Otomatik doğrulama raporu", "", f"Sonuç: **{'KALDI' if fails else 'GEÇTİ'}** ({len(fails)} başarısız denetim)", "",
          "## Ön koşullar", "", "| Denetim | Sonuç | Ayrıntı |", "|---|---|---|"]
    md += [f"| {c.name} | {c.status} | {c.detail} |" for c in pre]
    for r in clips:
        md += ["", f"## {r.clip}", "", "| Denetim | Sonuç | Ayrıntı |", "|---|---|---|"]
        md += [f"| {c.name} | {c.status} | {c.detail.replace('|', '/')} |" for c in r.checks]
        md += ["", "| Adım | Çıkış | Süre sn | Günlük |", "|---|---|---|---|"]
        md += [f"| {s.name} | {s.code} | {s.seconds:.0f} | {s.log} |" for s in r.steps]
    (logdir / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (logdir / "report.json").write_text(json.dumps(
        {"pre": [c.__dict__ for c in pre],
         "clips": [{"clip": r.clip, "rect": r.rect, "peak_vram_mb": r.peak_vram_mb,
                    "checks": [c.__dict__ for c in r.checks],
                    "steps": [{"name": s.name, "code": s.code, "seconds": s.seconds, "log": s.log} for s in r.steps]}
                   for r in clips]}, ensure_ascii=False, indent=1), encoding="utf-8")
    return not fails


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="autotest", description="Otomatik doğrulama (S14)")
    p.add_argument("--clips", default="klipler", help="video klasörü (varsayılan: klipler)")
    p.add_argument("--file", help="yalnız bu video; günlük MASAÜSTÜNE yazılır (--out verilmezse)")
    p.add_argument("--model-dir", default="models/sam-edgetam")
    p.add_argument("--device", default="auto", choices=("auto", "dml", "cuda", "cpu"))
    p.add_argument("--max-seconds", type=int, default=90)
    p.add_argument("--out", default=None, help="günlük klasörü (varsayılan: validation; --file ile masaüstü)")
    p.add_argument("--quick", action="store_true", help="sabitlemeli dışa aktarmayı atla")
    p.add_argument("--no-baseline", action="store_true", help="eski izleyici temelini atla")
    p.add_argument("--skip-bench", action="store_true", help="sam-bench'i atla")
    a = p.parse_args(argv)
    if a.file:
        f = Path(a.file)
        if not f.is_file():
            print(f"HATA: dosya yok: {f}")
            return 2
        vids, label = [f], f"Takipli-Test-{f.stem}"
        a.out = a.out or str(desktop_dir())
    else:
        src = Path(a.clips)
        vids = sorted(f for f in src.iterdir() if f.suffix.lower() in VIDEO_EXT) if src.is_dir() else []
        if not vids:
            print(f"HATA: {src} klasöründe video yok. Klipleri oraya koy ({', '.join(VIDEO_EXT)}).")
            return 2
        label = ""
        a.out = a.out or "validation"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    logdir = Path(a.out) / (f"{label}-{stamp}" if label else stamp)
    logdir.mkdir(parents=True, exist_ok=True)
    print(f"{len(vids)} klip, günlükler: {logdir}", flush=True)
    pre = preflight(a, logdir)
    clips: list[ClipResult] = []
    if any(c.status == FAIL for c in pre if c.name.startswith("sam-bench")):
        print("sam-bench başarısız: klipler atlandı (önce grafik sorununu çöz).")
    else:
        for v in vids:
            print(f"> {v.name}", flush=True)
            clips.append(process_clip(v, a, logdir))
    ok = write_report(logdir, pre, clips)
    if label:  # masaüstünde tek dosya olarak da dursun
        try:
            (logdir.parent / f"{logdir.name}.md").write_text((logdir / "report.md").read_text(encoding="utf-8"),
                                                              encoding="utf-8")
        except OSError:
            pass
    print(f"\nRapor: {logdir / 'report.md'}\nSonuç: {'GEÇTİ' if ok else 'KALDI'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
