"""Kayıt varyantı komut satırı: `python -m recorder export|info|--version`."""
from __future__ import annotations

import argparse
import sys
import time

from . import __version__
from .keys import default_out, load_recording, rec_path


def _utf8_stdio() -> None:
    """Windows konsolu/borusu cp125x: Türkçe harfli çıktı UnicodeEncodeError vermesin."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):  # pythonw: akış yok
            pass


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="recorder", description="Takipli Oynat Kayıt")
    ap.add_argument("--version", action="version", version=f"takipli-oynat-kayit {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    ex = sub.add_parser("export", help="Kayıtlı kamera hareketini uygula → mp4 (ffmpeg)")
    ex.add_argument("video")
    ex.add_argument("--rec", help="kayıt dosyası (varsayılan: <video>.rec.json)")
    ex.add_argument("--out", help="çıktı (varsayılan: <video>.kamera.mp4)")
    ex.add_argument("--ffmpeg", help="ffmpeg yolu")
    ex.add_argument("--no-audio", action="store_true")
    ex.add_argument("--crf", type=int, default=14, help="kalite (düşük = daha iyi; 14 = yüksek)")
    ex.add_argument("--preset", default="medium",
                    help="x264 hazır ayarı (yavaş = daha küçük dosya)")
    inf = sub.add_parser("info", help="Kayıt dosyasının özeti")
    inf.add_argument("rec")
    return ap


def _report_failure(out: str, msg: str) -> None:
    """Konsolsuz (pythonw) çalışırken hata yine de görünsün: kayit.lua `.export.json`'u okur."""
    from .export import _write_state, state_path

    try:
        _write_state(state_path(out), "error", 0, 0, msg)
    except OSError:
        pass


def run_export(args: argparse.Namespace) -> int:
    from .export import export_video

    out = args.out or default_out(args.video)
    t0 = time.monotonic()
    try:
        rec = load_recording(args.rec or rec_path(args.video), video=args.video)
        r = export_video(args.video, rec["views"], out, rotate=rec["rotate"], ffmpeg=args.ffmpeg,
                         audio=not args.no_audio, crf=args.crf, preset=args.preset)
    except (OSError, ValueError, RuntimeError) as e:
        _report_failure(out, str(e))
        raise
    if r.get("cancelled"):
        print("dışa aktarma iptal edildi")
        return 3
    print(f"kaydedildi: {r['out']} ({r['frames']} kare, {r['size'][0]}x{r['size'][1]}, "
          f"{'ses dahil' if r['audio'] else 'sessiz'}, {time.monotonic() - t0:.0f} sn)")
    return 0


def run_info(args: argparse.Namespace) -> int:
    rec = load_recording(args.rec)
    v = rec["views"]
    zmax = max(k[1] for k in v)
    print(f"{len(v)} anahtar kare, {v[0][0]:.2f}–{v[-1][0]:.2f} sn, en çok {2 ** zmax:.1f}×, "
          f"döndürme {rec['rotate']}°")
    return 0


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        if args.cmd == "export":
            return run_export(args)
        if args.cmd == "info":
            return run_info(args)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 1
    ap.print_help()
    return 2
