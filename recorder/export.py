"""Kayıt dışa aktarma: anahtar karelerden kare başına kırp + ölçekle → ffmpeg (libx264) → mp4.

Ana varyanttaki `tracker/export.py` ile aynı geometri ve çıktı kuralları (çıktı boyutu kaynakla
aynı; özgün ses aynen eklenir); bağımsız kopyadır, çünkü kayıt paketi `tracker/` içermez.
ffmpeg yoksa (PATH / `TAKIPLI_FFMPEG` / `ffmpeg\\ffmpeg.exe`) cv2.VideoWriter ile sessiz yedek.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .geometry import View, crop_rect, view_at


def render_frame(cv2, frame, view: View, size: tuple[int, int]):
    """Karenin görünüme göre kırpılıp `size` (w, h) boyuna ölçeklenmiş hali."""
    h, w = frame.shape[:2]
    x, y, cw, ch = crop_rect(view, w, h)
    crop = frame[y:y + ch, x:x + cw]
    if (cw, ch) == size:
        return crop
    interp = cv2.INTER_CUBIC if cw < size[0] else cv2.INTER_AREA
    return cv2.resize(crop, size, interpolation=interp)


def rotate_frame(cv2, frame, rotate: int):
    """mpv `video-rotate` ile aynı yön (saat yönü); zoom/pan döndürülmüş kareye göredir."""
    code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
            270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(rotate)
    return frame if code is None else cv2.rotate(frame, code)


def find_ffmpeg(explicit: str | None = None) -> str | None:
    cands = [explicit, os.environ.get("TAKIPLI_FFMPEG")]
    exe = Path(sys.executable).resolve().parent
    cands += [str(exe.parent / "ffmpeg" / "ffmpeg.exe"), str(exe / "ffmpeg.exe")]
    for c in cands:
        if c and Path(c).is_file():
            return c
    return shutil.which("ffmpeg")


def ffmpeg_cmd(ff: str, size: tuple[int, int], fps: float, src: str, out: str,
               audio: bool = True, crf: int = 18, preset: str = "veryfast") -> list[str]:
    cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{size[0]}x{size[1]}", "-r", f"{fps:.6f}", "-i", "-"]
    if audio:
        cmd += ["-i", src, "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "copy", "-shortest"]
    return cmd + ["-c:v", "libx264", "-crf", str(crf), "-preset", preset,
                  "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]


def has_audio(ff: str, src: str) -> bool:
    """Kaynakta ses akışı var mı (ffmpeg -i çıktısındaki «Audio:» satırı)."""
    try:
        r = subprocess.run([ff, "-hide_banner", "-i", src], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return b"Audio:" in r.stderr


def segment_plan(segments, fps: float, total: int = 0) -> list[tuple[int, int, list]]:
    """Parçalar → [(ilk_kare, son_kare_hariç, anahtarlar)]; videonun dışına taşmaz."""
    plan = []
    for keys in segments:
        f0 = max(int(round(keys[0][0] * fps)), 0)
        f1 = max(int(round(keys[-1][0] * fps)) + 1, f0 + 1)
        if total:
            f1 = min(f1, total)
            if f0 >= f1:
                continue
        plan.append((f0, f1, keys))
    return plan


def audio_filter(plan, fps: float) -> str:
    """Her parçanın sesini kare hizasında keser, kaydedilen sırayla art arda ekler."""
    n = len(plan)
    head = "[1:a]asplit=%d%s;" % (n, "".join(f"[s{i}]" for i in range(n))) if n > 1 else ""
    parts = [f"[s{i}]" if n > 1 else "[1:a]" for i in range(n)]
    cuts = [f"{parts[i]}atrim=start={f0 / fps:.6f}:end={f1 / fps:.6f},asetpts=PTS-STARTPTS[a{i}]"
            for i, (f0, f1, _k) in enumerate(plan)]
    cat = "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[aout]"
    return head + ";".join(cuts + [cat])


def ffmpeg_cmd_segments(ff: str, size: tuple[int, int], fps: float, src: str, out: str, plan,
                        audio: bool = True, crf: int = 18, preset: str = "veryfast") -> list[str]:
    cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{size[0]}x{size[1]}", "-r", f"{fps:.6f}", "-i", "-"]
    if audio:
        cmd += ["-i", src, "-filter_complex", audio_filter(plan, fps), "-map", "0:v:0",
                "-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    return cmd + ["-c:v", "libx264", "-crf", str(crf), "-preset", preset,
                  "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]


def _iter_frames(cv2, cap, plan):
    """Planın parçalarını sırayla okur (geri sarma → yeniden konumlanıp aynı kareleri tekrar okur)."""
    pos = 0
    for f0, f1, keys in plan:
        if f0 != pos:
            cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
            pos = f0
        fr = f0
        while f1 is None or fr < f1:
            ok, frame = cap.read()
            if not ok:
                break
            yield frame, fr, keys
            fr += 1
        pos = fr


def out_size(w: int, h: int, rotate: int = 0) -> tuple[int, int]:
    """Çıktı boyutu: döndürmede w/h yer değiştirir; libx264/yuv420p çift boyut ister."""
    if rotate in (90, 270):
        w, h = h, w
    return w - w % 2, h - h % 2


def state_path(out: str | os.PathLike) -> Path:
    """İlerleme/hata dosyası: `<çıktı>.export.json` (kayit.lua bunu okur)."""
    p = Path(out)
    return p.with_name(p.name + ".export.json")


def _write_state(path: Path, state: str, n: int, total: int, error: str | None = None) -> None:
    tmp = path.with_name(path.name + ".tmp")
    pct = round(100 * n / total) if total else None
    tmp.write_text(json.dumps({"state": state, "n": n, "total": total, "pct": pct,
                               "error": error}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def export_video(video: str, views: list[list[float]], out: str, *, rotate: int = 0,
                 ffmpeg: str | None = None, audio: bool = True, crf: int = 18,
                 preset: str = "veryfast", progress=None, clock=time.monotonic,
                 segments: list | None = None) -> dict:
    """Videoyu anahtar karelerle dışa aktar → {frames, ffmpeg, audio, size, out}.
    `segments` (kayıt parçaları) verilirse çıktı = parçalar KAYDEDİLDİĞİ SIRAYLA art arda
    (geri sarıp tekrar oynatılan yer tekrar eder; ses de aynı kesim/sırayla); yoksa tüm video.
    `<out>.export.json` ilerleme, `<out>.export.cancel` varsa iptal (yarım çıktı silinir)."""
    import cv2

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise FileNotFoundError(f"video açılamadı: {video}")
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    size = out_size(w, h, rotate)
    outp = Path(out)
    tmp = outp.with_name(outp.stem + ".partial" + outp.suffix)
    st = outp.with_name(outp.name + ".export.json")
    cancel = outp.with_name(outp.name + ".export.cancel")
    cancel.unlink(missing_ok=True)
    ff = find_ffmpeg(ffmpeg)
    plan = segment_plan(segments, fps, total) if segments else [(0, None, views)]
    if segments:
        if not plan:
            raise ValueError("kayıt videonun dışında: dışa aktarılacak kare yok")
        total = sum(f1 - f0 for f0, f1, _k in plan)
    proc = writer = None
    if ff:
        if segments:
            audio = audio and has_audio(ff, video)
            cmd = ffmpeg_cmd_segments(ff, size, fps, video, str(tmp), plan, audio, crf, preset)
        else:
            cmd = ffmpeg_cmd(ff, size, fps, video, str(tmp), audio, crf, preset)
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        print("UYARI: ffmpeg bulunamadı; sessiz yedek yazıcı (mp4v) kullanılıyor",
              file=sys.stderr)
        audio = False
        writer = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    n, last, stopped, err = 0, -1e9, False, None
    try:
        for frame, fr, keys in _iter_frames(cv2, cap, plan):
            frame = rotate_frame(cv2, frame, rotate)
            img = render_frame(cv2, frame[:size[1], :size[0]], view_at(keys, fr / fps), size)
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
            raise RuntimeError(f"dışa aktarma başarısız: {err}")
        return {"frames": n, "cancelled": True, "out": str(outp)}
    os.replace(tmp, outp)
    _write_state(st, "done", n, n or total)
    return {"frames": n, "ffmpeg": bool(ff), "audio": audio, "size": size, "out": str(outp)}
