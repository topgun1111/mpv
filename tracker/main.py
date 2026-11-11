"""CLI girişi: ping, view, listen (Parça 2), detect (3), live (5), offline/offline-view (9)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
    lv.add_argument("--reid", action="store_true",
                    help="Re-ID: hedef ID değişirse görünüme göre yeniden bağla (OSNet gerekir)")
    lv.add_argument("--reid-model", help="OSNet ONNX yolu (varsayılan: config.reid_model)")
    lv.add_argument("--team", action="store_true",
                    help="Re-ID adaylarını takım rengine göre ele (--reid gerekir)")
    lv.add_argument("--number", action="store_true",
                    help="Re-ID adaylarını forma numarasına göre ele (--reid + numara modeli)")
    lv.add_argument("--wait", type=float, default=0.0, metavar="SN",
                    help="mpv IPC kanalı açılana kadar en çok SN saniye bekle (başlatıcı kullanır)")
    lv.add_argument("--stats", type=float, default=0.0, metavar="SN",
                    help="SN'de bir hız/gecikme yaz")
    of = sub.add_parser("offline", help="Videoyu işle → track.json (hedef verilirse görünüm de)")
    of.add_argument("video")
    of.add_argument("--out", help="Çıktı (varsayılan: <video>.track.json)")
    of.add_argument("--model", help="ONNX model yolu (varsayılan: config.model_path)")
    of.add_argument("--device", choices=["auto", "dml", "cuda", "cpu"], help="Çalışma cihazı")
    of.add_argument("--fps", type=float, help="İşlenen kare/sn (varsayılan: config.offline_fps)")
    of.add_argument("--reid", action="store_true",
                    help="İzlerin embedding'ini de kaydet (ID değişimini zincirlemek için)")
    of.add_argument("--reid-model", help="OSNet ONNX yolu (varsayılan: config.reid_model)")
    of.add_argument("--team", action="store_true",
                    help="İzlerin takım rengini kaydet (ID zincirlemede farklı takım elenir)")
    of.add_argument("--pose", action="store_true",
                    help="Eklemleri de kaydet (track.json sürüm 2; --part için gerekir)")
    of.add_argument("--pose-model", help="Poz ONNX yolu (varsayılan: config.pose_model)")
    _add_target_args(of)
    bn = sub.add_parser("bench", help="Kıyasla: izleme/görünüm kalitesi + hız")
    bn.add_argument("video", help="Video ya da .track.json (json: tespit yapılmaz)")
    bn.add_argument("--model")
    bn.add_argument("--device", choices=["auto", "dml", "cuda", "cpu"])
    bn.add_argument("--fps", type=float, help="İşlenen kare/sn (varsayılan: config.offline_fps)")
    bn.add_argument("--max-seconds", type=float, default=0.0, help="Yalnız ilk N sn (0: hepsi)")
    bn.add_argument("--target-id", type=int, help="Hedef iz (varsayılan: en uzun iz)")
    bn.add_argument("--out", help="JSON rapor yolu")
    ov = sub.add_parser("offline-view", help="track.json'da hedefi seç/değiştir (tespit yok)")
    ov.add_argument("json")
    ov.add_argument("--out", help="Çıktı (varsayılan: girdinin üzerine yazar)")
    ov.add_argument("--list", action="store_true", help="İzleri (en uzun görünenden) listele")
    ov.add_argument("--no-link", action="store_true",
                    help="Kayıtlı Re-ID embedding'leri varsa bile ID zincirleme yapma")
    _add_target_args(ov)
    return p


def _add_target_args(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument("--target-id", type=int, help="Hedef iz kimliği")
    g.add_argument("--click", nargs=3, type=float, metavar=("SN", "NX", "NY"),
                   help="Hedef: SN anında (0..1 normalize) NX,NY noktasındaki kişi")
    p.add_argument("--part", metavar="EKLEM",
                   help="Kişi yerine eklemi izle: indeks 0-16 ya da ad (örn. \"sol ayak bileği\"); "
                        "--target-id/--click ile; track.json'da eklem verisi gerekir")


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
    if getattr(args, "part", None) and doc.get("target"):  # yalnız --part: mevcut hedefin eklemi
        return doc["target"]["id"]
    return None


def _parse_part(value: str | None) -> int | None:
    from .pose import KEYPOINT_NAMES

    if value is None:
        return None
    v = value.strip().lower()
    if v.isdigit() and int(v) < len(KEYPOINT_NAMES):
        return int(v)
    if v in KEYPOINT_NAMES:
        return KEYPOINT_NAMES.index(v)
    raise ValueError(f"bilinmeyen eklem: {value!r} (0-{len(KEYPOINT_NAMES) - 1} ya da "
                     + ", ".join(KEYPOINT_NAMES) + ")")


def _print_tracks(doc: dict, top: int = 10) -> None:
    from .offline import list_tracks

    print("En uzun görünen izler (--target-id ile seç):")
    for e in list_tracks(doc)[:top]:
        print(f"  ID {e['id']}: {e['first']:.1f}–{e['last']:.1f} sn, {e['n']} örnek")


def _finish_doc(doc: dict, cfg: Config, args: argparse.Namespace, out: str) -> None:
    from .offline import apply_target, save_doc, save_views, views_path

    tid = _resolve_target(doc, cfg, args)
    if tid is not None:
        part = _parse_part(getattr(args, "part", None))
        apply_target(doc, tid, cfg, link=not getattr(args, "no_link", False), part=part)
        linked = doc["target"].get("linked", [])
        from .pose import KEYPOINT_NAMES

        print(f"hedef ID {tid}" + (f", eklem: {KEYPOINT_NAMES[part]}" if part is not None else "")
              + (f" (+ Re-ID ile bağlanan: {linked})" if linked else "")
              + f": {len(doc['views'])} görünüm anahtar karesi")
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
                   device=args.device or cfg.device, model_type=cfg.model_type,
                   yolox_decoded=cfg.yolox_decoded)
    print(f"detector: provider={det.providers[0]}, girdi={det.size}; video {src.w}x{src.h}, "
          f"{src.duration:.0f} sn, {fps:g} örnek/sn")
    total = int(src.duration * fps) or None
    t0, last = time.monotonic(), [0.0]

    def progress(n: int, tot: int | None) -> None:
        if time.monotonic() - last[0] >= 5.0:
            last[0] = time.monotonic()
            pct = f"%{100 * n / tot:.0f}" if tot else ""
            print(f"  {n} örnek {pct} ({n / (last[0] - t0):.1f}/sn)")

    bank = None
    if args.reid:
        from .reid import Embedder, TrackletBank

        emb = Embedder(args.reid_model or cfg.reid_model, device=args.device or cfg.device)
        bank = TrackletBank(emb, cfg)
    tbank = None
    if args.team:
        from .team import TeamBank

        tbank = TeamBank(cfg)
    pest = None
    if args.pose:
        from .pose import PoseEstimator

        pest = PoseEstimator(args.pose_model or cfg.pose_model, conf_thres=cfg.pose_conf,
                             device=args.device or cfg.device)
    pipe = Pipeline(det, ByteTracker(low_thr=cfg.live_det_conf))
    samples, size = run_detection(src, pipe, progress, total, bank=bank, team=tbank, pose=pest)
    doc = make_doc(args.video, size, src.src_fps, src.duration, fps, samples,
                   emb=bank.result() if bank else None,
                   team=tbank.result() if tbank else None, pose=pest is not None)
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
    import threading

    from .bytetrack import ByteTracker
    from .detector import Detector
    from .live import EventListener, model_line, run_live
    from .pipeline import NullPipeline, Pipeline
    from .single import SingleInstance

    if (args.team or args.number) and not args.reid:
        print("--team/--number için --reid de gerekir")
        return 2
    if args.fps:
        cfg.live_fps = args.fps
    if args.wait > 0:
        from .ipc import wait_for_ipc

        print(f"mpv bekleniyor (en çok {args.wait:g} sn)...")
        if not wait_for_ipc(cfg.ipc_path, args.wait):
            print("HATA: mpv IPC kanalı açılmadı (mpv çalışıyor mu?)", file=sys.stderr)
            return 1
    try:
        det = Detector(
            args.model or cfg.model_path,
            conf_thres=cfg.live_det_conf,
            iou_thres=cfg.det_iou,
            input_size=cfg.det_size,
            device=args.device or cfg.device,
            model_type=cfg.model_type,
            yolox_decoded=cfg.yolox_decoded,
        )
    except Exception as e:  # model yok/bozuk: sağ tık nesne takibi modelsiz de çalışır
        print(f"UYARI: person modeli yüklenemedi ({e}); yalnız sağ tık nesne takibi çalışır "
              "(oyuncu kimliği/Re-ID yok).", file=sys.stderr)
        if args.reid:
            print("--reid için person modeli gerekir", file=sys.stderr)
            return 2
        pipeline = NullPipeline()
        info = ["Model: yok (yalnız nesne takibi)"]
    else:
        print(f"detector: provider={det.providers[0]}, girdi={det.size}")
        info = [model_line("Model", args.model or cfg.model_path, det.session,
                           f"{det.model_type}, {det.size[1]}x{det.size[0]}")]
        pipeline = Pipeline(det, ByteTracker(low_thr=cfg.live_det_conf))
    reid = None
    if args.reid:
        from .reid import Embedder, ReIdManager

        emb = Embedder(args.reid_model or cfg.reid_model, device=args.device or cfg.device)
        team = numbers = None
        if args.team:
            from .team import TeamClassifier

            team = TeamClassifier(cfg)
        if args.number:
            from .number import NumberReader

            numbers = NumberReader(cfg.number_model, device=args.device or cfg.device,
                                   conf=cfg.number_conf)
        reid = ReIdManager(emb, cfg, team=team, numbers=numbers)
        print(f"Re-ID açık: provider={emb.session.get_providers()[0]}")
        extra = ", ".join(n for n, on in (("takım", args.team), ("numara", args.number)) if on)
        info.append(model_line("Re-ID", args.reid_model or cfg.reid_model, emb.session, extra))
    pose = None
    try:
        from .detector import resolve_model_path
        from .pose import PoseEstimator

        if resolve_model_path(cfg.pose_model).is_file():
            pose = PoseEstimator(cfg.pose_model, conf_thres=cfg.pose_conf,
                                 device=args.device or cfg.device)
            print(f"Vücut parçası takibi açık: provider={pose.session.get_providers()[0]}")
            info.append(model_line("Poz", cfg.pose_model, pose.session))
    except Exception as e:  # eklem takibi isteğe bağlı: yoksa/bozuksa eski davranış
        print(f"UYARI: pose modeli yüklenemedi ({e}); eklem takibi kapalı.", file=sys.stderr)
    events: queue.Queue = queue.Queue()
    # Aynı mpv'yi birden çok takip programı sürmesin (her mpv açılışı yeni süreç başlatır)
    inst = SingleInstance(Path(args.cfg_path).resolve().parent / "tracker.lock")
    stop = threading.Event()
    if inst.claim():
        inst.watch(stop)
    # Konsolsuz (pythonw) çalışırken log'a 5 sn'de bir hız/gecikme/hedef satırı yaz
    stats = args.stats or (5.0 if getattr(args, "headless", False) else 0.0)
    listener = EventListener(cfg.ipc_path, events)
    listener.start()
    try:
        with MpvIpc(cfg.ipc_path, keep_events=False) as mpv:  # komut bağlantısı olay biriktirmez
            run_live(mpv, events, pipeline, cfg, stats_every=stats, reid=reid,
                     cfg_path=args.cfg_path, pose=pose, info=info, stop=stop)
    finally:
        stop.set()
        listener.stop()
        inst.release()
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
        model_type=cfg.model_type,
        yolox_decoded=cfg.yolox_decoded,
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
    print("Dinleniyor (Ctrl+C ile çık). mpv'de videoya sağ tıkla: takip kendiliğinden açılır.")
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


def _log_dir(cfg_path: str) -> Path:
    """Log klasörü: kullanıcının masaüstü (OneDrive'a taşınmış olabilir); yoksa config klasörü."""
    home = Path.home()
    for d in (home / "Desktop", home / "OneDrive" / "Desktop", home / "Masaüstü"):
        if d.is_dir():
            return d
    return Path(cfg_path).resolve().parent


def _log_if_headless(cfg_path: str) -> Path | None:
    """`pythonw.exe` (mpv'nin otomatik başlattığı gizli süreç) konsolsuzdur: sys.stdout/stderr None
    olur ve her hata sessizce kaybolur. Bu durumda çıktıyı masaüstündeki
    `takipli-oynat-log.txt`'ye yaz (her başlangıçta sıfırlanır): takip çalışmıyorsa neden orada."""
    if sys.stdout is not None and sys.stderr is not None:
        return None
    try:
        path = _log_dir(cfg_path) / "takipli-oynat-log.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        f = open(path, "w", encoding="utf-8", buffering=1)  # noqa: SIM115 (süreç boyunca açık)
    except OSError:
        return None
    sys.stdout = sys.stderr = f
    import platform
    import time

    print(f"Takipli Oynat takip programı başladı {time.strftime('%Y-%m-%d %H:%M:%S')} | "
          f"Python {platform.python_version()} | config: {cfg_path}")
    return path


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    args = build_parser().parse_args(argv)
    cfg = Config.load(args.config) if args.config and Path(args.config).is_file() else Config()
    args.cfg_path = args.config or "tracker_config.json"  # canlı `track-save` hedefi
    if args.cmd == "detect":  # mpv bağlantısı gerekmez
        try:
            return detect_image(cfg, args)
        except (FileNotFoundError, ValueError, ImportError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            return 1
    if args.cmd == "bench":
        from .bench import format_report, run_bench, save_report

        try:
            rep = run_bench(args, cfg)
        except KeyboardInterrupt:
            return 130
        except (FileNotFoundError, ValueError, ImportError, OSError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            return 1
        print(format_report(rep))
        if args.out:
            save_report(rep, args.out)
            print(f"kaydedildi: {args.out}")
        return 0
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
        args.headless = _log_if_headless(args.cfg_path) is not None
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
