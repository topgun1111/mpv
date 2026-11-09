"""CLI girişi: ping, view, listen (Parça 2), detect (3), live (5), offline/offline-view (9)."""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .clicks import RESET_MSG, message_name, parse_click
from .config import Config
from .geometry import View, pan_for_center
from .ipc import MpvIpc, MpvIpcError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tracker", description="Takipli Oynat")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config", help="Config JSON yolu")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping", help="mpv IPC bağlantısını dene")
    v = sub.add_parser("view", help="Elle zoom/pan uygula")
    v.add_argument("zoom", type=float)
    v.add_argument("pan_x", type=float, nargs="?", default=0.0)
    v.add_argument("pan_y", type=float, nargs="?", default=0.0)
    ls = sub.add_parser("listen", help="Lua tıklamalarını dinle ve yazdır")
    ls.add_argument("--follow-click", action="store_true", help="Tıklanan noktaya zoom yap (demo)")
    ls.add_argument("--zoom", type=float, default=1.5, help="--follow-click log2 zoom")
    d = sub.add_parser("detect", help="Görüntü dosyasında person tespiti (model testi)")
    d.add_argument("image")
    d.add_argument("--model", help="ONNX model yolu (varsayılan: config.model_path)")
    d.add_argument("--conf", type=float, help="Skor eşiği")
    d.add_argument("--device", choices=["auto", "dml", "cuda", "cpu"], help="Çalışma cihazı")
    d.add_argument("--out", help="Kutuları çizilmiş görüntüyü kaydet")
    lv = sub.add_parser("live", help="Canlı mod: mpv karelerini oku, takip et, zoom/pan uygula")
    lv.add_argument("--model", help="ONNX model yolu (varsayılan: config.model_path)")
    lv.add_argument("--device", choices=["auto", "dml", "cuda", "cpu"], help="Çalışma cihazı")
    lv.add_argument("--fps", type=float, help="En fazla işleme hızı (varsayılan: config.live_fps)")
    lv.add_argument("--stats", type=float, default=0.0, metavar="SN",
                    help="SN'de bir hız/gecikme yaz")
    of = sub.add_parser("offline", help="Videoyu işle → track.json (hedef verilirse görünüm de)")
    of.add_argument("video")
    of.add_argument("--out", help="Çıktı (varsayılan: <video>.track.json)")
    of.add_argument("--model", help="ONNX model yolu (varsayılan: config.model_path)")
    of.add_argument("--device", choices=["auto", "dml", "cuda", "cpu"], help="Çalışma cihazı")
    of.add_argument("--fps", type=float, help="İşlenen kare/sn (varsayılan: config.offline_fps)")
    _add_target_args(of)
    ov = sub.add_parser("offline-view", help="track.json'da hedefi seç/değiştir (tespit yok)")
    ov.add_argument("json")
    ov.add_argument("--out", help="Çıktı (varsayılan: girdinin üzerine yazar)")
    ov.add_argument("--list", action="store_true", help="İzleri (en uzun görünenden) listele")
    _add_target_args(ov)
    return p


def _add_target_args(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument("--target-id", type=int, help="Hedef iz kimliği")
    g.add_argument("--click", nargs=3, type=float, metavar=("SN", "NX", "NY"),
                   help="Hedef: SN anında (0..1 normalize) NX,NY noktasındaki kişi")


def _resolve_target(doc: dict, cfg: Config, args: argparse.Namespace) -> int | None:
    from .offline import pick_target_id

    if args.target_id is not None:
        return args.target_id
    if args.click:
        t, nx, ny = args.click
        tid = pick_target_id(doc, t, nx, ny, cfg.pick_tol)
        if tid is None:
            raise ValueError(f"{t:g} sn'de ({nx:g}, {ny:g}) noktasında kişi yok")
        return tid
    return None


def _print_tracks(doc: dict, top: int = 10) -> None:
    from .offline import list_tracks

    print("En uzun görünen izler (--target-id ile seç):")
    for e in list_tracks(doc)[:top]:
        print(f"  ID {e['id']}: {e['first']:.1f}–{e['last']:.1f} sn, {e['n']} örnek")


def _finish_doc(doc: dict, cfg: Config, args: argparse.Namespace, out: str) -> None:
    from .offline import apply_target, save_doc, save_views, views_path

    tid = _resolve_target(doc, cfg, args)
    if tid is not None:
        apply_target(doc, tid, cfg)
        print(f"hedef ID {tid}: {len(doc['views'])} görünüm anahtar karesi")
    elif not doc.get("target"):
        _print_tracks(doc)
    save_doc(doc, out)
    print(f"kaydedildi: {out}")
    if doc.get("views"):
        vp = views_path(out)
        save_views(doc, vp)
        print(f"oynatma dosyası: {vp}  (mpv'de videonun yanında dursun; o tuşu)")


def run_offline_cmd(cfg: Config, args: argparse.Namespace) -> int:
    """Ağır bağımlılıklar yalnızca bu komutta içe aktarılır."""
    import time

    from .bytetrack import ByteTracker
    from .detector import Detector
    from .offline import VideoSource, make_doc, run_detection
    from .pipeline import Pipeline

    fps = args.fps or cfg.offline_fps
    src = VideoSource(args.video, fps)
    det = Detector(args.model or cfg.model_path, conf_thres=cfg.live_det_conf,
                   iou_thres=cfg.det_iou, input_size=cfg.det_size,
                   device=args.device or cfg.device)
    print(f"detector: provider={det.providers[0]}, girdi={det.size}; video {src.w}x{src.h}, "
          f"{src.duration:.0f} sn, {fps:g} örnek/sn")
    total = int(src.duration * fps) or None
    t0, last = time.monotonic(), [0.0]

    def progress(n: int, tot: int | None) -> None:
        if time.monotonic() - last[0] >= 5.0:
            last[0] = time.monotonic()
            pct = f"%{100 * n / tot:.0f}" if tot else ""
            print(f"  {n} örnek {pct} ({n / (last[0] - t0):.1f}/sn)")

    pipe = Pipeline(det, ByteTracker(low_thr=cfg.live_det_conf))
    samples, size = run_detection(src, pipe, progress, total)
    doc = make_doc(args.video, size, src.src_fps, src.duration, fps, samples)
    _finish_doc(doc, cfg, args, args.out or f"{args.video}.track.json")
    return 0


def run_offline_view_cmd(cfg: Config, args: argparse.Namespace) -> int:
    from .offline import load_doc

    doc = load_doc(args.json)
    if args.list:
        _print_tracks(doc, 30)
        return 0
    _finish_doc(doc, cfg, args, args.out or args.json)
    return 0


def run_live_cmd(cfg: Config, args: argparse.Namespace) -> int:
    """Ağır bağımlılıklar yalnızca bu komutta içe aktarılır."""
    import queue

    from .bytetrack import ByteTracker
    from .detector import Detector
    from .live import EventListener, run_live
    from .pipeline import Pipeline

    if args.fps:
        cfg.live_fps = args.fps
    det = Detector(
        args.model or cfg.model_path,
        conf_thres=cfg.live_det_conf,
        iou_thres=cfg.det_iou,
        input_size=cfg.det_size,
        device=args.device or cfg.device,
    )
    print(f"detector: provider={det.providers[0]}, girdi={det.size}")
    pipeline = Pipeline(det, ByteTracker(low_thr=cfg.live_det_conf))
    events: queue.Queue = queue.Queue()
    listener = EventListener(cfg.ipc_path, events)
    listener.start()
    try:
        with MpvIpc(cfg.ipc_path, keep_events=False) as mpv:  # komut bağlantısı olay biriktirmez
            run_live(mpv, events, pipeline, cfg, stats_every=args.stats)
    finally:
        listener.stop()
    return 0


def detect_image(cfg: Config, args: argparse.Namespace) -> int:
    """Ağır bağımlılıklar (numpy/cv2/onnxruntime) yalnızca bu komutta içe aktarılır."""
    import time

    import cv2
    import numpy as np

    from .detector import Detector

    data = np.fromfile(args.image, dtype=np.uint8)  # Unicode yollarda imread sorunlu
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if frame is None:
        print(f"HATA: görüntü okunamadı: {args.image}", file=sys.stderr)
        return 1
    det = Detector(
        args.model or cfg.model_path,
        conf_thres=args.conf if args.conf is not None else cfg.det_conf,
        iou_thres=cfg.det_iou,
        input_size=cfg.det_size,
        device=args.device or cfg.device,
    )
    det.detect(frame)  # ısınma (DirectML ilk çalıştırma yavaş)
    t0 = time.perf_counter()
    dets = det.detect(frame)
    ms = (time.perf_counter() - t0) * 1000
    print(f"{len(dets)} person, {ms:.0f} ms, provider={det.providers[0]}, girdi={det.size}")
    for d in dets:
        b = d.bbox
        print(f"  skor={d.score:.2f} x1={b.x1:.0f} y1={b.y1:.0f} x2={b.x2:.0f} y2={b.y2:.0f}")
    if args.out:
        for d in dets:
            b = d.bbox
            cv2.rectangle(frame, (int(b.x1), int(b.y1)), (int(b.x2), int(b.y2)), (0, 255, 0), 2)
            cv2.putText(frame, f"{d.score:.2f}", (int(b.x1), max(int(b.y1) - 4, 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        ok, buf = cv2.imencode(".jpg", frame)
        if ok:
            buf.tofile(args.out)
            print(f"kaydedildi: {args.out}")
    return 0


def listen(mpv: MpvIpc, follow: bool, zoom: float) -> None:
    print("Dinleniyor (Ctrl+C ile çık). mpv'de t tuşu ile takibi aç, videoya sol tıkla.")
    while True:
        ev = mpv.poll_event(1.0)
        if ev is None:
            continue
        click = parse_click(ev)
        if click:
            print(f"tıklama: nx={click.nx:.3f} ny={click.ny:.3f} "
                  f"px=({click.px:.0f},{click.py:.0f}) t={click.time_pos:.2f}s")
            if follow:
                pan_x, pan_y = pan_for_center(click.nx, click.ny, zoom)
                mpv.set_view(View(zoom, pan_x, pan_y))
        elif message_name(ev) == RESET_MSG:
            print("sıfırlandı")


def _utf8_console() -> None:
    """Windows'ta cp1252/cp857 konsolu ve yönlendirmede Türkçe çıktı hata vermesin."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    args = build_parser().parse_args(argv)
    cfg = Config.load(args.config) if args.config else Config()
    if args.cmd == "detect":  # mpv bağlantısı gerekmez
        try:
            return detect_image(cfg, args)
        except (FileNotFoundError, ValueError, ImportError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            return 1
    if args.cmd in ("offline", "offline-view"):
        try:
            fn = run_offline_cmd if args.cmd == "offline" else run_offline_view_cmd
            return fn(cfg, args)
        except KeyboardInterrupt:
            return 130
        except (FileNotFoundError, ValueError, ImportError, OSError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            return 1
    if args.cmd == "live":
        try:
            return run_live_cmd(cfg, args)
        except KeyboardInterrupt:
            return 0
        except (FileNotFoundError, ValueError, ImportError, MpvIpcError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            return 1
    try:
        with MpvIpc(cfg.ipc_path) as mpv:
            if args.cmd == "ping":
                print("mpv", mpv.get_property("mpv-version"))
            elif args.cmd == "view":
                mpv.set_view(View(args.zoom, args.pan_x, args.pan_y))
            elif args.cmd == "listen":
                listen(mpv, args.follow_click, args.zoom)
    except KeyboardInterrupt:
        return 0
    except MpvIpcError as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
