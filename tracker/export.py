"""E1: takip kamerası dışa aktarma — `<video>.views.json` anahtar karelerinden kare başına
kırp + ölçekle, ffmpeg'e ham BGR ver (libx264), özgün sesi aynen ekle.

Geometri (mpv ile aynı): ölçek s = 2^zoom, görünen alan = karenin 1/s'i, merkez = 0.5 − pan
(normalize), kenar boşluğu görünmesin diye kıstırılır. Çıktı boyutu kaynakla aynıdır.
ffmpeg yoksa (PATH / `TAKIPLI_FFMPEG` / `ffmpeg\\ffmpeg.exe`) `cv2.VideoWriter` ile sessiz
yedek kullanılır (uyarı basılır).

S13b: çalışma anı NVENC hatasında (auto) x264'e yeniden dener; isteğe bağlı NVDEC çözme
(`decode`: cpu | auto | nvdec; sıralı kalır); isteğe bağlı sabitleme (`stabilize.py`, gmc.py
kestirimi); bitince `export_check.validate_files` (süre, kare, fps, ses, zaman damgası).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .config import Config
from .offline import view_at


class EncoderError(RuntimeError):
    """ffmpeg kodlama sırasında başarısız oldu; `encoder` hangi kodlayıcıyla."""

    def __init__(self, msg: str, encoder: str):
        super().__init__(msg)
        self.encoder = encoder


def crop_rect(view: tuple[float, float, float], vw: int, vh: int) -> tuple[int, int, int, int]:
    """(zoom log2, pan_x, pan_y) → piksel kırpma (x, y, w, h); kare içinde, boyutlar ≥2."""
    z, px, py = view
    s = max(2.0 ** max(z, 0.0), 1.0)  # 1x altına inilmez: kenar boşluğu gösterilmez
    cw, ch = vw / s, vh / s
    cx = min(max((0.5 - px) * vw, cw / 2), vw - cw / 2)
    cy = min(max((0.5 - py) * vh, ch / 2), vh - ch / 2)
    w, h = max(int(round(cw)), 2), max(int(round(ch)), 2)
    x = min(max(int(round(cx - cw / 2)), 0), vw - w)
    y = min(max(int(round(cy - ch / 2)), 0), vh - h)
    return x, y, w, h


def render_frame(cv2, frame, view, size: tuple[int, int]):
    """Karenin görünüme göre kırpılıp `size` (w, h) boyuna ölçeklenmiş hali."""
    h, w = frame.shape[:2]
    x, y, cw, ch = crop_rect(view, w, h)
    crop = frame[y:y + ch, x:x + cw]
    if (cw, ch) == size:
        return crop
    interp = cv2.INTER_CUBIC if cw < size[0] else cv2.INTER_AREA
    return cv2.resize(crop, size, interpolation=interp)


def find_ffmpeg(explicit: str | None = None) -> str | None:
    cands = [explicit, os.environ.get("TAKIPLI_FFMPEG")]
    exe = Path(sys.executable).resolve().parent
    cands += [str(exe.parent / "ffmpeg" / "ffmpeg.exe"), str(exe / "ffmpeg.exe")]
    for c in cands:
        if c and Path(c).is_file():
            return c
    return shutil.which("ffmpeg")


_PROBE: dict[tuple[str, str], bool] = {}


def encoder_available(ff: str, name: str = "h264_nvenc", run=subprocess.run) -> bool:
    """S13a: ffmpeg derlemesi `name` kodlayıcısını içeriyor VE küçük bir deneme kodlaması
    gerçekten çalışıyor mu (listede olması GPU/sürücü olduğunu kanıtlamaz). Önbelleğe alınır."""
    key = (ff, name)
    if key in _PROBE:
        return _PROBE[key]
    ok = False
    try:
        lst = run([ff, "-hide_banner", "-encoders"], capture_output=True, timeout=20)
        if name in (lst.stdout or b"").decode("utf-8", "replace"):
            t = run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                     "color=c=black:s=256x256:d=0.2", "-frames:v", "2", "-c:v", name,
                     "-f", "null", "-"], capture_output=True, timeout=30)
            ok = t.returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    _PROBE[key] = ok
    return ok


def choose_encoder(ff: str, pref: str = "auto", run=subprocess.run) -> str:
    """pref: auto (NVENC varsa o, yoksa libx264) | nvenc (zorla; yoksa hata) | x264 (zorla)."""
    pref = (pref or "auto").lower()
    if pref in ("x264", "libx264", "cpu"):
        return "libx264"
    if pref not in ("auto", "nvenc", "h264_nvenc"):
        raise ValueError(f"bilinmeyen kodlayıcı: {pref} (auto | nvenc | x264)")
    if encoder_available(ff, "h264_nvenc", run):
        return "h264_nvenc"
    if pref != "auto":
        raise RuntimeError("h264_nvenc bu ffmpeg derlemesinde/bu makinede çalışmıyor "
                           "(NVIDIA sürücüsü veya NVENC'li ffmpeg yok); --encoder x264 kullanın")
    return "libx264"


def ffmpeg_cmd(ff: str, size: tuple[int, int], fps: float, src: str, out: str,
               audio: bool = True, crf: int = 18, encoder: str = "libx264",
               audio_limit: float | None = None) -> list[str]:
    cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{size[0]}x{size[1]}", "-r", f"{fps:.6f}", "-i", "-"]
    if audio:
        # S13b: sesli çıktıda `-shortest` son 1-2 kareyi kırpıyordu (doğrulama yakaladı): süre
        # biliniyorsa video kısalmaz, ses yalnız giriş tarafında `-t` ile video süresine kısılır.
        # `audio_limit` yoksa eski komut aynen (recorder/export.py ile eşlik testi).
        lim = ["-t", f"{audio_limit:.6f}"] if audio_limit else []
        cmd += lim + ["-i", src, "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "copy"]
        if not audio_limit:
            cmd += ["-shortest"]
    if encoder == "h264_nvenc":  # crf ile aynı ölçekte sabit kalite (-cq), bit hızı sınırsız
        venc = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(crf), "-b:v", "0"]
    else:
        venc = ["-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast"]
    return cmd + venc + ["-pix_fmt", "yuv420p", "-movflags", "+faststart", out]


def load_views(path: str | Path, video: str | None = None) -> list[list[float]]:
    """`video` verilirse ve dosya başka bir videonun imzasını (`vsig`) taşıyorsa ValueError (A3)."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if video is not None:
        from .cache import views_match

        if not views_match(path, video):
            raise ValueError(f"{path}: bu görünüm başka bir videoya (ya da değişmiş dosyaya) ait; "
                             "yeniden tara (--rescan)")
    v = d.get("views") or []
    if not v:
        raise ValueError(f"{path}: görünüm anahtar karesi yok (önce hedef seçip tara)")
    return v


def render_frame_stab(cv2, frame, view, size: tuple[int, int], M):
    """Sabitlenmiş render: kare önce `M` (3x3, margin dahil) ile taşınır, kırpma görünüm merkezinin
    `M` ile taşınmış yerine yapılır; tek `warpAffine` (kaynak → çıktı)."""
    import numpy as np

    h, w = frame.shape[:2]
    z, px, py = view
    c = M @ np.array([(0.5 - px) * w, (0.5 - py) * h, 1.0])
    x, y, cw, ch = crop_rect((z, 0.5 - c[0] / w, 0.5 - c[1] / h), w, h)
    T = np.array([[size[0] / cw, 0, -x * size[0] / cw], [0, size[1] / ch, -y * size[1] / ch],
                  [0, 0, 1.0]])
    A = (T @ M)[:2]
    interp = cv2.INTER_CUBIC if cw < size[0] else cv2.INTER_LINEAR
    return cv2.warpAffine(frame, A, size, flags=interp, borderMode=cv2.BORDER_REPLICATE)


class NvdecReader:
    """`cv2.VideoCapture` arayüzü (read/release) ile ffmpeg `-hwaccel cuda` çözümü. Kareler sıralı,
    atlama/tekrarlama yok (`-fps_mode passthrough`). Çalışmıyorsa ilk `read` False döner."""

    def __init__(self, ff: str, video: str, w: int, h: int, run=subprocess.Popen):
        self.w, self.h = w, h
        self.proc = run([ff, "-hide_banner", "-loglevel", "error", "-hwaccel", "cuda", "-i", video,
                         "-an", "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "bgr24",
                         "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def read(self):
        import numpy as np

        n = self.w * self.h * 3
        buf = self.proc.stdout.read(n)
        if len(buf) < n:
            return False, None
        return True, np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 3)

    def error(self) -> str:
        try:
            self.proc.wait(timeout=5)
            return self.proc.stderr.read().decode("utf-8", "replace").strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    def release(self) -> None:
        try:
            self.proc.kill()
        except OSError:
            pass
        for p in (self.proc.stdout, self.proc.stderr):
            try:
                p.close()
            except OSError:
                pass


def open_source(cv2, video: str, ff: str | None, decode: str, w: int, h: int):
    """→ (okuyucu, çözücü adı, ilk kare ya da None). decode: cpu | auto (NVDEC dene, olmazsa cpu) |
    nvdec (zorla; çalışmazsa hata). NVDEC çalıştığı gerçek GPU'da denenmeden iddia edilmez."""
    decode = (decode or "cpu").lower()
    if decode not in ("cpu", "auto", "nvdec"):
        raise ValueError(f"bilinmeyen çözücü: {decode} (cpu | auto | nvdec)")
    if decode != "cpu" and ff:
        rd = NvdecReader(ff, video, w, h)
        ok, first = rd.read()
        if ok:
            return rd, "nvdec", first
        why = rd.error() or "çözülemedi"
        rd.release()
        if decode == "nvdec":
            raise RuntimeError(f"NVDEC çalışmıyor: {why}; --decode cpu kullanın")
        print(f"UYARI: NVDEC kullanılamadı ({why}); cpu çözme", file=sys.stderr)
    elif decode == "nvdec":
        raise RuntimeError("NVDEC için ffmpeg gerekli (bulunamadı); --decode cpu kullanın")
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise FileNotFoundError(f"video açılamadı: {video}")
    return cap, "cpu", None


def _write_state(path: Path, state: str, n: int, total: int, error: str | None = None,
                 extra: dict | None = None) -> None:
    tmp = path.with_name(path.name + ".tmp")
    pct = round(100 * n / total) if total else None
    d = {"state": state, "n": n, "total": total, "pct": pct, "error": error}
    d.update(extra or {})
    tmp.write_text(json.dumps(d), encoding="utf-8")
    os.replace(tmp, path)


def _stab_plan(cv2, video: str, fps: float, cfg: Config | None, st: Path, total: int):
    """Sıralı analiz geçişi (cv2) → (düzeltmeler, margin); kestirim gmc.py'den."""
    from . import stabilize

    cap = cv2.VideoCapture(video)

    def frames():
        while True:
            ok, f = cap.read()
            if not ok:
                return
            yield f

    last = [-1e9]

    def prog(i):
        now = time.monotonic()
        if now - last[0] >= 1.0:
            last[0] = now
            _write_state(st, "analysing", i, total)

    try:
        cors, margin, _ = stabilize.plan(frames(), fps, getattr(cfg, "stabilize_s", 1.0), prog)
    finally:
        cap.release()
    return cors, margin


def _export_once(video: str, views, out: str, cfg: Config | None, *, ffmpeg, audio, crf,
                 progress, clock, pref: str, decode: str, stabilize: bool,
                 validate: bool) -> dict:
    import cv2

    probe = cv2.VideoCapture(video)
    if not probe.isOpened():
        raise FileNotFoundError(f"video açılamadı: {video}")
    w, h = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH)), int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = probe.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(probe.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    probe.release()
    size = (w - w % 2, h - h % 2)  # libx264/yuv420p çift boyut ister
    outp = Path(out)
    tmp = outp.with_name(outp.stem + ".partial" + outp.suffix)
    st = outp.with_name(outp.name + ".export.json")
    cancel = outp.with_name(outp.name + ".export.cancel")
    cancel.unlink(missing_ok=True)
    ff = find_ffmpeg(ffmpeg)
    cors, margin = None, 1.0
    if stabilize:
        cors, margin = _stab_plan(cv2, video, fps, cfg, st, total)
    cap, dec, first = open_source(cv2, video, ff, decode, w, h)
    proc = writer = None
    enc = "mp4v"
    try:
        if ff:
            enc = choose_encoder(ff, pref)
            lim = total / fps if total > 0 else None
            proc = subprocess.Popen(ffmpeg_cmd(ff, size, fps, video, str(tmp), audio, crf, enc,
                                               lim),
                                    stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            print("UYARI: ffmpeg bulunamadı; sessiz yedek yazıcı (mp4v) kullanılıyor",
                  file=sys.stderr)
            audio = False
            writer = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    except BaseException:
        cap.release()
        raise
    n, last, stopped, err = 0, -1e9, False, None
    try:
        while True:
            if first is not None:
                ok, frame, first = True, first, None
            else:
                ok, frame = cap.read()
            if not ok:
                break
            view = view_at(views, n / fps)
            if cors is not None:
                from .stabilize import render_matrix

                M = render_matrix(cors[min(n, len(cors) - 1)], margin, (frame.shape[1],
                                                                          frame.shape[0]))
                img = render_frame_stab(cv2, frame, view, size, M)
            else:
                img = render_frame(cv2, frame[:size[1], :size[0]], view, size)
            if proc:
                try:
                    proc.stdin.write(img.tobytes())
                except (BrokenPipeError, OSError):
                    err = proc.stderr.read().decode("utf-8", "replace").strip() or "ffmpeg kapandı"
                    break
            else:
                writer.write(img)
            n += 1
            now = clock()
            if now - last >= 1.0:
                last = now
                _write_state(st, "running", n, total)
                if progress:
                    progress(n, total)
                if cancel.exists():
                    stopped = True
                    break
    finally:
        cap.release()
        if proc:
            try:
                proc.stdin.close()
            except OSError:
                pass
            rc = proc.wait()
            if rc != 0 and not stopped and err is None:
                err = proc.stderr.read().decode("utf-8", "replace").strip() or f"ffmpeg kodu {rc}"
        if writer:
            writer.release()
    if stopped or err:
        tmp.unlink(missing_ok=True)
        _write_state(st, "cancelled" if stopped else "error", n, total, err)
        cancel.unlink(missing_ok=True)
        if err:
            raise EncoderError(f"dışa aktarma başarısız: {err}", enc)
        return {"frames": n, "cancelled": True, "out": str(outp)}
    os.replace(tmp, outp)
    res = {"frames": n, "ffmpeg": bool(ff), "audio": audio, "size": size, "out": str(outp),
           "encoder": enc, "decoder": dec, "stabilized": bool(stabilize)}
    if validate:
        from .export_check import validate_files

        res["validation"] = validate_files(video, str(outp), ffmpeg=ff, frames_written=n,
                                           size=size, fps=fps, audio_expected=audio)
    _write_state(st, "done", n, n or total, None,
                 {"valid": res["validation"]["ok"]} if validate else None)
    return res


def export_video(video: str, views: list[list[float]], out: str, cfg: Config | None = None, *,
                 ffmpeg: str | None = None, audio: bool = True, crf: int = 18,
                 progress=None, clock=time.monotonic, encoder: str | None = None,
                 decode: str | None = None, stabilize: bool | None = None,
                 validate: bool | None = None) -> dict:
    """Videoyu görünümlerle dışa aktar → {frames, ffmpeg, audio, size, out, encoder, decoder,
    stabilized, validation?, fallback?}. `<out>.export.json` ilerleme, `<out>.export.cancel` varsa
    iptal (yarım çıktı silinir). `auto` kodlayıcıda NVENC çalışma anında başarısız olursa bir kez
    libx264 ile baştan yeniden denenir (`fallback`); `nvenc` zorlanmışsa hata verilir."""
    pref = encoder or getattr(cfg, "export_encoder", "auto")
    kw = {"ffmpeg": ffmpeg, "audio": audio, "crf": crf, "progress": progress, "clock": clock,
          "decode": decode or getattr(cfg, "export_decode", "cpu"),
          "stabilize": getattr(cfg, "stabilize", False) if stabilize is None else stabilize,
          "validate": getattr(cfg, "export_validate", True) if validate is None else validate}
    try:
        return _export_once(video, views, out, cfg, pref=pref, **kw)
    except EncoderError as e:
        if (pref or "auto").lower() != "auto" or e.encoder != "h264_nvenc":
            raise
        print(f"UYARI: NVENC kodlaması başarısız ({e}); libx264 ile yeniden deneniyor",
              file=sys.stderr)
        res = _export_once(video, views, out, cfg, pref="x264", **kw)
        res["fallback"] = "h264_nvenc → libx264"
        return res


def default_out(video: str) -> str:
    p = Path(video)
    return str(p.with_name(p.stem + ".takipli.mp4"))
