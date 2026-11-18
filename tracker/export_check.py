"""S13b: dışa aktarma doğrulaması (süre, kare sayısı, fps, ses, zaman damgası) + ffmpeg raporu.

`python -m tracker.export_check [--ffmpeg yol]`: bu ffmpeg derlemesinin hangi kodlayıcıları /
donanım çözücüleri listelediğini ve NVENC deneme kodlamasının çalışıp çalışmadığını yazar
(listede olması çalıştığını göstermez; yalnız deneme kodlaması "çalışıyor" der).
ffprobe yoksa cv2 ile sınırlı doğrulama yapılır (ses bilinmez; uyarı verilir).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def find_ffprobe(ffmpeg: str | None) -> str | None:
    if ffmpeg:
        p = Path(ffmpeg)
        for name in ("ffprobe.exe", "ffprobe"):
            c = p.with_name(name)
            if c.is_file():
                return str(c)
    return shutil.which("ffprobe")


def _rate(s: str | None) -> float:
    try:
        if s and "/" in s:
            a, b = s.split("/")
            return float(a) / float(b) if float(b) else 0.0
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def probe_media(fprobe: str, path: str, *, packets: bool = False, run=subprocess.run) -> dict:
    """ffprobe → {video, audio, format_duration, pts}. `packets`: video zaman damgalarını da oku."""
    r = run([fprobe, "-v", "error", "-count_packets", "-show_streams", "-show_format",
             "-of", "json", path], capture_output=True, timeout=120)
    if r.returncode != 0:
        msg = (r.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"ffprobe başarısız ({path}): {msg or r.returncode}")
    d = json.loads((r.stdout or b"{}").decode("utf-8", "replace") or "{}")
    info: dict = {"video": None, "audio": None, "audio_known": True,
                  "format_duration": _f((d.get("format") or {}).get("duration")), "pts": None}
    for s in d.get("streams") or []:
        kind = s.get("codec_type")
        if kind == "video" and info["video"] is None:
            info["video"] = {
                "codec": s.get("codec_name"), "width": int(s.get("width") or 0),
                "height": int(s.get("height") or 0), "fps": _rate(s.get("r_frame_rate")),
                "avg_fps": _rate(s.get("avg_frame_rate")),
                "frames": int(s.get("nb_read_packets") or s.get("nb_frames") or 0),
                "duration": _f(s.get("duration")), "start": _f(s.get("start_time")) or 0.0}
        elif kind == "audio" and info["audio"] is None:
            info["audio"] = {"codec": s.get("codec_name"), "duration": _f(s.get("duration")),
                             "start": _f(s.get("start_time")) or 0.0}
    if packets and info["video"]:
        t = run([fprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "packet=pts_time,dts_time", "-of", "csv=p=0", path],
                capture_output=True, timeout=300)
        pts, dts = [], []
        for ln in (t.stdout or b"").decode("utf-8", "replace").splitlines():
            a = ln.strip().split(",")
            if len(a) >= 2 and _f(a[0]) is not None:
                pts.append(_f(a[0]))
                dts.append(_f(a[1]) if _f(a[1]) is not None else _f(a[0]))
        info["pts"], info["dts"] = pts, dts
    return info


def probe_cv2(cv2, path: str) -> dict:
    """ffprobe yokken yedek: yalnız video; ses bilinmez."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"video açılamadı: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    v = {"codec": None, "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
         "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), "fps": fps, "avg_fps": fps,
         "frames": n, "duration": n / fps if fps and n else None, "start": 0.0}
    cap.release()
    return {"video": v, "audio": None, "audio_known": False,
            "format_duration": v["duration"], "pts": None}


def validate(src: dict, out: dict, *, frames_written: int, size: tuple[int, int], fps: float,
             audio_expected: bool, pts_tol_frames: float = 1.5) -> dict:
    """Saf denetim (ffprobe/cv2 çıktısı sözlükleriyle). → {ok, errors, warnings, info}.
    errors = dosya kullanılamaz/yanlış; warnings = dikkat (kayma, ses süresi, kaynak VFR)."""
    err: list[str] = []
    warn: list[str] = []
    ov, sv = out.get("video"), src.get("video")
    if not ov:
        return {"ok": False, "errors": ["çıktıda video akışı yok"], "warnings": [], "info": {}}
    spf = 1.0 / fps if fps else 0.04
    if (ov["width"], ov["height"]) != tuple(size):
        err.append(f"çıktı boyutu {ov['width']}x{ov['height']}, beklenen {size[0]}x{size[1]}")
    if ov["frames"] and ov["frames"] != frames_written:
        err.append(f"kare sayısı {ov['frames']}, yazılan {frames_written}")
    if sv and sv["frames"] and abs(sv["frames"] - frames_written) > 1:
        warn.append(f"kaynakta {sv['frames']} kare var, {frames_written} yazıldı")
    if ov["fps"] and fps and abs(ov["fps"] - fps) > 0.01 * fps:
        err.append(f"çıktı fps {ov['fps']:.3f}, kaynak {fps:.3f}")
    if sv and sv["fps"] and sv["avg_fps"] and abs(sv["fps"] - sv["avg_fps"]) > 0.02 * sv["fps"]:
        warn.append("kaynak değişken kare hızlı (VFR); çıktı sabit kare hızı, zamanlama "
                    "kaynağa göre kayabilir")
    vdur = ov.get("duration") or out.get("format_duration")
    want = frames_written * spf
    if vdur is not None and abs(vdur - want) > 2 * spf:
        err.append(f"video süresi {vdur:.2f} sn, beklenen {want:.2f} sn ({frames_written} kare)")
    sdur = (sv or {}).get("duration") or src.get("format_duration")
    if vdur is not None and sdur and abs(vdur - sdur) > max(0.25, 2 * spf):
        warn.append(f"çıktı süresi {vdur:.2f} sn, kaynak {sdur:.2f} sn")
    pts = out.get("pts")
    if pts:
        dts = out.get("dts") or pts
        if any(b < a for a, b in zip(dts, dts[1:])):
            err.append("zaman damgaları geriye gidiyor (dts sıralı değil)")
        ordered = sorted(pts)
        gap = max((b - a for a, b in zip(ordered, ordered[1:])), default=0.0)
        if gap > pts_tol_frames * spf:
            err.append(f"zaman damgalarında {gap:.3f} sn boşluk (kare aralığı {spf:.3f} sn)")
        first = ordered[0]
        s0 = (sv or {}).get("start") or 0.0
        if abs(first - s0) > pts_tol_frames * spf and abs(first) > pts_tol_frames * spf:
            warn.append(f"ilk kare zamanı {first:.3f} sn, kaynak {s0:.3f} sn")
    a_src, a_out = src.get("audio"), out.get("audio")
    if audio_expected:
        if not out.get("audio_known", True):
            warn.append("ffprobe yok: ses doğrulanamadı")
        elif src.get("audio_known", True) and a_src and not a_out:
            err.append("kaynakta ses var, çıktıda ses akışı yok")
        elif a_src and a_out:
            if a_src.get("codec") != a_out.get("codec"):
                warn.append(f"ses kodeği değişti ({a_src.get('codec')} → {a_out.get('codec')})")
            ad = a_out.get("duration")
            if ad is not None and vdur is not None and abs(ad - vdur) > 0.5:
                warn.append(f"ses {ad:.2f} sn, video {vdur:.2f} sn")
            if abs((a_out.get("start") or 0.0) - (a_src.get("start") or 0.0)) > 0.1:
                warn.append("ses başlangıcı kaynaktan farklı (A/V kayması olabilir)")
    elif a_out:
        warn.append("ses istenmedi ama çıktıda ses akışı var")
    info = {"frames": ov["frames"], "fps": ov["fps"], "duration": vdur,
            "audio": bool(a_out), "codec": ov.get("codec"), "size": [ov["width"], ov["height"]]}
    return {"ok": not err, "errors": err, "warnings": warn, "info": info}


def validate_files(src: str, out: str, *, ffmpeg: str | None, frames_written: int,
                   size: tuple[int, int], fps: float, audio_expected: bool,
                   run=subprocess.run) -> dict:
    """Dosyaları araştır (ffprobe, yoksa cv2) ve `validate` çalıştır."""
    if not Path(out).is_file() or Path(out).stat().st_size == 0:
        return {"ok": False, "errors": [f"çıktı dosyası yok ya da boş: {out}"],
                "warnings": [], "info": {}}
    fp = find_ffprobe(ffmpeg)
    try:
        if fp:
            s = probe_media(fp, src, run=run)
            o = probe_media(fp, out, packets=True, run=run)
        else:
            import cv2

            s, o = probe_cv2(cv2, src), probe_cv2(cv2, out)
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as e:
        return {"ok": False, "errors": [f"doğrulama yapılamadı: {e}"], "warnings": [],
                "info": {}}
    r = validate(s, o, frames_written=frames_written, size=size, fps=fps,
                 audio_expected=audio_expected)
    if not fp:
        r["warnings"].insert(0, "ffprobe bulunamadı: yalnız cv2 ile sınırlı doğrulama")
    return r


def ffmpeg_report(ff: str, run=subprocess.run) -> dict:
    """Bu ffmpeg derlemesi: listelenen kodlayıcılar, NVENC deneme sonucu, hwaccel'ler, ffprobe."""
    from .export import encoder_available

    def out(args):
        try:
            r = run([ff, "-hide_banner", *args], capture_output=True, timeout=30)
            return (r.stdout or b"").decode("utf-8", "replace")
        except (OSError, subprocess.SubprocessError):
            return ""

    enc = out(["-encoders"])
    names = ("libx264", "h264_nvenc", "hevc_nvenc", "av1_nvenc", "h264_qsv", "h264_amf")
    hw = [ln.strip() for ln in out(["-hwaccels"]).splitlines()[1:] if ln.strip()]
    return {"ffmpeg": ff, "listed": {n: n in enc for n in names},
            "nvenc_works": encoder_available(ff, "h264_nvenc", run),
            "hwaccels": hw, "ffprobe": find_ffprobe(ff)}


def main(argv: list[str] | None = None) -> int:
    import argparse

    from .export import find_ffmpeg

    ap = argparse.ArgumentParser(prog="tracker.export_check")
    ap.add_argument("--ffmpeg")
    a = ap.parse_args(argv)
    ff = find_ffmpeg(a.ffmpeg)
    if not ff:
        print("ffmpeg bulunamadı", file=sys.stderr)
        return 2
    print(json.dumps(ffmpeg_report(ff), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
