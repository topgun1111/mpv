"""CLI girişi: ping, view, listen (Parça 2), detect (3), live (5), offline/offline-view (9)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, errlog
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
    lv.add_argument("--single-pose", action="store_true",
                    help="Tek model: poz modeli kişi tespitini de yapar (person modeli yüklenmez)")
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
    of.add_argument("--single-pose", action="store_true",
                    help="Tek model: poz modeli kişi tespitini de yapar (--pose: 1 çıkarım/kare)")
    of.add_argument("--select-point", nargs=3, type=float, metavar=("SN", "NX", "NY"),
                    help="Hedef: SN anında NX,NY noktası (kişi ya da yakın eklem); tarama o ana "
                         "varınca çözülür; ilerleme <çıktı>.scan.json'a yazılır")
    of.add_argument("--select-rect", nargs=5, type=float,
                    metavar=("SN", "NX1", "NY1", "NX2", "NY2"),
                    help="Hedef: SN anında dikdörtgen (kişi ya da küçükse içindeki eklem)")
    of.add_argument("--resume", action="store_true",
                    help="Kesilen taramayı <çıktı>.partial.json'dan sürdür")
    of.add_argument("--rescan", action="store_true",
                    help="A3: önbelleği ve kesinti noktasını yok say, baştan tara")
    of.add_argument("--progress", action="store_true",
                    help="İlerleme/kesinti dosyalarını yaz (--select-* ile otomatik)")
    _add_target_args(of)
    bn = sub.add_parser("bench", help="Kıyasla: izleme/görünüm kalitesi + hız")
    bn.add_argument("video", help="Video ya da .track.json (json: tespit yapılmaz)")
    bn.add_argument("--model")
    bn.add_argument("--device", choices=["auto", "dml", "cuda", "cpu"])
    bn.add_argument("--fps", type=float, help="İşlenen kare/sn (varsayılan: config.offline_fps)")
    bn.add_argument("--max-seconds", type=float, default=0.0, help="Yalnız ilk N sn (0: hepsi)")
    bn.add_argument("--target-id", type=int, help="Hedef iz (varsayılan: en uzun iz)")
    bn.add_argument("--out", help="JSON rapor yolu")
    pb = sub.add_parser("pose-bench", help="Poz modellerini kıyasla: ms/kare, sağlayıcı, fp16 (G2)")
    pb.add_argument("source", help="Video ya da görüntü dosyası")
    pb.add_argument("--model", action="append", help="Poz ONNX (birden çok kez verilebilir)")
    pb.add_argument("--device", choices=["auto", "dml", "cuda", "cpu"])
    pb.add_argument("--frames", type=int, default=60, help="Ölçülecek kare sayısı (60)")
    sb = sub.add_parser("sam-bench", help="EdgeTAM/SAM 2.1 grafiklerini ölç: yükleme, ms, sağlayıcı, VRAM (S2)")
    sb.add_argument("model_dir", help="sam-*.onnx dosyalarının klasörü (scripts/export_sam2.py çıktısı)")
    sb.add_argument("--device", choices=["auto", "dml", "cuda", "cpu"])
    sb.add_argument("--runs", type=int, default=20, help="Ölçülecek koşu sayısı (20)")
    sb.add_argument("--warmup", type=int, default=3, help="Isınma koşuları, ölçüme girmez (3)")
    sb.add_argument("--fp16", action="store_true", help="fp16 sürümlerini de ölç (gerekirse üret)")
    sb.add_argument("--out", help="JSON rapor yolu; yanına .md tablo satırları da yazılır")
    sf = sub.add_parser("sam-first", help="Bir görüntü + dikdörtgen -> ilk maske, kontur PNG (S3)")
    sf.add_argument("model_dir", help="sam-encoder.onnx ve sam-decoder.onnx klasörü")
    sf.add_argument("image", help="Görüntü dosyası (png/jpg)")
    sf.add_argument("--rect", required=True, help="x1,y1,x2,y2 (piksel; --norm ile 0-1 oranı)")
    sf.add_argument("--norm", action="store_true", help="--rect değerleri 0-1 oranı")
    sf.add_argument("--device", choices=["auto", "dml", "cuda", "cpu"])
    sf.add_argument("--rule", choices=["best", "smallest"], default="best",
                    help="Aday kuralı: en yüksek iou (best) ya da en küçük güvenilir (smallest)")
    sf.add_argument("--out", help="Kontur PNG yolu (varsayılan: <görüntü>_maske.png)")
    st = sub.add_parser("sam-track", help="Video + ilk kare dikdörtgeni -> SAM bellek takibi, kare kayıtları (S4)")
    st.add_argument("model_dir", help="5 sam-*.onnx dosyasının klasörü")
    st.add_argument("video", help="Video dosyası")
    st.add_argument("--rect", required=True, help="İlk karede x1,y1,x2,y2 (piksel; --norm ile 0-1 oranı)")
    st.add_argument("--norm", action="store_true", help="--rect değerleri 0-1 oranı")
    st.add_argument("--start", type=float, default=0.0, help="Dikdörtgenin çizildiği an, sn (0)")
    st.add_argument("--fps", type=float, default=10.0, help="Örnekleme hızı (10)")
    st.add_argument("--max-seconds", type=float, default=0.0, help="Başlangıçtan itibaren yalnız N sn (0: hepsi)")
    st.add_argument("--device", choices=["auto", "dml", "cuda", "cpu"])
    st.add_argument("--rule", choices=["best", "smallest"], default="best", help="İlk kare aday kuralı")
    st.add_argument("--out", help="Kayıt dosyası (varsayılan: <video>.sam.json)")
    st.add_argument("--no-save", action="store_true", help="Kayıt dosyası yazma")
    st.add_argument("--no-gate", action="store_true", help="TrackGate kapalı: her izlenen kare belleğe girer (S4)")
    st.add_argument("--preview", action="store_true",
                    help="Maske konturu + birleşik dikdörtgeni <video>.sam.preview.json'a yaz (mpv'de P tuşu, S6)")
    st.add_argument("--pose", action="store_true",
                    help="Poz ile alt vücut bölgesi: görünen/anatomik, sol/sağ, tek kadraj (S7); "
                         "kayda `lower` bloğu yazar")
    st.add_argument("--pose-model", help="Poz ONNX yolu (varsayılan: config.pose_model)")
    st.add_argument("--posture", action="store_true",
                    help="--pose + duruş (oturma/ayakta/geçiş), masa maskesi reddi, bacak durumu, duruşa duyarlı kadraj (S8); "
                         "kayda `posture` bloğu yazar")
    st.add_argument("--reid", action="store_true",
                    help="Uzun kayıp/kare dışından dönüşte kişiyi mevcut Re-ID (OSNet) ile doğrula, başka kişiye bağlanma "
                         "(S10); --pose'u içerir, kayda `reentry` bloğu yazar. Model yoksa uyarıp Re-ID'siz sürer")
    st.add_argument("--camera", action="store_true",
                    help="Kayıttan sonra alt vücut kamerasını (%%70 doluluk, S11) <video>.views.json'a yaz; "
                         "`sam-camera` ile aynı")
    sc = sub.add_parser("sam-camera", help="<video>.sam.json -> alt vücut kamerası: <video>.views.json (S11)")
    sc.add_argument("sam_json", help="sam-track kaydı (<video>.sam.json)")
    sc.add_argument("--fill", type=float, help="Doluluk 0-1 (varsayılan: config.lower_fill = 0.70)")
    sc.add_argument("--out", help="Görünüm dosyası (varsayılan: <video>.views.json; VAROLANI EZER)")
    sp = sub.add_parser("sam-preview", help="Dikdörtgen -> ilk maske konturu + birleşik dikdörtgen, onay önizlemesi (S6)")
    sp.add_argument("model_dir", help="sam-encoder.onnx ve sam-decoder.onnx klasörü")
    sp.add_argument("video", help="Video dosyası")
    sp.add_argument("--rect", required=True, help="x1,y1,x2,y2 (piksel; --norm ile 0-1 oranı). Yeniden çizmek = yeni --rect")
    sp.add_argument("--norm", action="store_true", help="--rect değerleri 0-1 oranı")
    sp.add_argument("--start", type=float, default=0.0, help="Dikdörtgenin çizildiği an, sn (0)")
    sp.add_argument("--device", choices=["auto", "dml", "cuda", "cpu"])
    sp.add_argument("--rule", choices=["best", "smallest"], default="best", help="İlk kare aday kuralı")
    sp.add_argument("--out", help="Önizleme dosyası (varsayılan: <video>.sam.preview.json)")
    sp.add_argument("--pose", action="store_true",
                    help="Birleşik dikdörtgen = poz + maske alt vücut kadrajı (S7)")
    sp.add_argument("--pose-model", help="Poz ONNX yolu (varsayılan: config.pose_model)")
    pv = sub.add_parser("providers", help="GPU sağlayıcı tanılaması (DirectML/CUDA) (S1)")
    pv.add_argument("--device", choices=["auto", "dml", "cuda", "cpu"],
                    help="Denenecek cihaz (varsayılan: config.device)")
    pv.add_argument("--model", help="Gerçek yükleme denetimi için ONNX model (oturum açılır)")
    pv.add_argument("--json", action="store_true", help="JSON çıktı (TEST_RESULTS.md için)")
    ex = sub.add_parser("export", help="Takip kamerası videosu: görünümleri uygula → mp4 (ffmpeg)")
    ex.add_argument("video")
    ex.add_argument("--views", help="Görünüm dosyası (varsayılan: <video>.views.json)")
    ex.add_argument("--out", help="Çıktı (varsayılan: <video>.takipli.mp4)")
    ex.add_argument("--ffmpeg", help="ffmpeg yolu (varsayılan: TAKIPLI_FFMPEG, ffmpeg\\, PATH)")
    ex.add_argument("--no-audio", action="store_true", help="Sesi ekleme")
    ex.add_argument("--crf", type=int, default=18, help="x264 kalitesi (düşük = iyi; 18)")
    up = sub.add_parser("update", help="Güncelleme: check (JSON yazdırır) | install (indir + kur)")
    up.add_argument("action", choices=["check", "install"])
    up.add_argument("--progress", help="install: ilerleme JSON dosyası")
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
    from .cache import cached_doc, scan_sig
    from .detector import Detector, resolve_model_path
    from .offline import VideoSource, make_doc, run_detection
    from .pipeline import Pipeline, make_cuts, make_gmc
    from .scan import finish_cached, selection_from_args

    fps = args.fps or cfg.offline_fps
    src = VideoSource(args.video, fps)
    out = args.out or f"{args.video}.track.json"
    sel = selection_from_args(args)
    if sel and (args.target_id is not None or args.click):
        print("--select-* ile --target-id/--click birlikte verilemez", file=sys.stderr)
        return 2
    if sel and not args.pose:  # parça seçimi için model varsa eklem de tara
        args.pose = resolve_model_path(args.pose_model or cfg.pose_model).is_file()
    sig = scan_sig(args.video, fps, resolve_model_path(args.model or cfg.model_path),
                   resolve_model_path(args.pose_model or cfg.pose_model) if args.pose else None,
                   "reid" if args.reid else None, "team" if args.team else None)
    if not args.rescan:  # A3: aynı video+fps+model → tarama atlanır
        doc = cached_doc(out, sig, need_pose=args.pose)
        if doc is not None and (not args.reid or "emb" in doc) and (not args.team or "team" in doc):
            print(f"önbellekten: {out} (tarama atlandı; baştan taramak için --rescan)")
            sc = finish_cached(out, doc, cfg, sel, fps, sig)
            if sc.target:
                args.target_id = sc.target["id"]
                if "part" in sc.target:
                    args.part = str(sc.target["part"])
            elif sel:
                print(f"UYARI: {sc.error or 'hedef çözülemedi'}; izler listeleniyor",
                      file=sys.stderr)
            _finish_doc(doc, cfg, args, out)
            return 0
    else:
        args.resume = False
        for suffix in (".partial.json", ".scan.cancel"):
            Path(out + suffix).unlink(missing_ok=True)
    single = args.single_pose or cfg.single_pose
    pest = None
    if single:
        from .pose import PoseDetector

        pest = det = PoseDetector(args.pose_model or cfg.pose_model, cfg.live_det_conf,
                                  cfg.pose_conf, cfg.det_iou, device=args.device or cfg.device)
    else:
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
    if args.pose and pest is None:
        from .pose import PoseEstimator

        pest = PoseEstimator(args.pose_model or cfg.pose_model, conf_thres=cfg.pose_conf,
                             device=args.device or cfg.device)
    pipe = Pipeline(det, ByteTracker(low_thr=cfg.live_det_conf), gmc=make_gmc(cfg),
                    cuts=make_cuts(cfg))
    if sel or args.resume or args.progress:
        from .scan import run_scan

        samples, size, sc = run_scan(src, pipe, cfg, out, sel, fps, total, resume=args.resume,
                                     pose=pest, progress=progress, sig=sig)
        if sc.cancelled:
            print(f"tarama durduruldu ({len(samples)} örnek); --resume ile sürdür")
            return 3
        if sc.target:
            args.target_id = sc.target["id"]
            if "part" in sc.target:
                args.part = str(sc.target["part"])
        elif sel:
            print(f"UYARI: {sc.error or 'hedef çözülemedi'}; izler listeleniyor", file=sys.stderr)
    else:
        samples, size = run_detection(src, pipe, progress, total, bank=bank, team=tbank,
                                      pose=pest)
    doc = make_doc(args.video, size, src.src_fps, src.duration, fps, samples,
                   emb=bank.result() if bank else None,
                   team=tbank.result() if tbank else None, pose=pest is not None, sig=sig)
    _finish_doc(doc, cfg, args, out)
    return 0


def run_export_cmd(cfg: Config, args: argparse.Namespace) -> int:
    import time

    from .export import default_out, export_video, load_views

    views = load_views(args.views or f"{args.video}.views.json", video=args.video)
    out = args.out or default_out(args.video)
    t0 = time.monotonic()
    r = export_video(args.video, views, out, cfg, ffmpeg=args.ffmpeg, audio=not args.no_audio,
                     crf=args.crf)
    if r.get("cancelled"):
        print("dışa aktarma iptal edildi")
        return 3
    dt = time.monotonic() - t0
    print(f"kaydedildi: {r['out']} ({r['frames']} kare, {r['size'][0]}x{r['size'][1]}, "
          f"{'ses dahil' if r['audio'] else 'sessiz'}, {dt:.0f} sn)")
    return 0


def run_offline_view_cmd(cfg: Config, args: argparse.Namespace) -> int:
    from .offline import load_doc

    doc = load_doc(args.json)
    if args.list:
        _print_tracks(doc, 30)
        return 0
    _finish_doc(doc, cfg, args, args.out or args.json)
    return 0


def live_reid_plan(cfg: Config, args, reid_file: bool,
                   number_file: bool) -> tuple[bool, bool, bool]:
    """(reid, team, number): bayrak ya da config'ten. `--reid` açıkça verilmediyse Re-ID yalnız
    `reid_live` on, ya da auto + model dosyası varsa açılır; takım/numara yalnız Re-ID açıkken."""
    mode = (cfg.reid_live or "auto").lower()
    reid = bool(args.reid) or mode == "on" or (mode == "auto" and reid_file)
    if mode == "off" and not args.reid:
        reid = False
    team = reid and (bool(args.team) or cfg.team_live)
    number = reid and (bool(args.number) or (cfg.number_live and number_file))
    return reid, team, number


def run_update_cmd(cfg: Config, args: argparse.Namespace) -> int:
    """`update check`: tek satır JSON (Lua okur). `update install`: indir + kurulumu başlat."""
    import json

    from . import update

    info = update.check(update.resolve_repo(cfg.update_repo), __version__)
    if args.action == "check":
        print(json.dumps(info, ensure_ascii=False))
        return 0
    if info["state"] != "available":
        print(json.dumps(info, ensure_ascii=False))
        return 1
    res = update.install(info, Path(args.progress) if args.progress else None)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res["state"] == "launched" else 1


def _notify_loading(ipc_path: str, on: bool) -> None:
    """Lua'ya "modeller yükleniyor"/"hazır" bildir (en iyi çaba; hata izlemeyi etkilemez)."""
    from .clicks import LOADING_MSG

    try:
        with MpvIpc(ipc_path, keep_events=False) as m:
            m.command("script-message-to", "track", LOADING_MSG, "1" if on else "0")
    except Exception:  # noqa: BLE001 - bildirim isteğe bağlı
        pass


def run_live_cmd(cfg: Config, args: argparse.Namespace) -> int:
    """Ağır bağımlılıklar yalnızca bu komutta içe aktarılır."""
    import queue
    import threading

    from .bytetrack import ByteTracker
    from .detector import Detector
    from .live import EventListener, model_line, run_live
    from .pipeline import NullPipeline, Pipeline, make_cuts, make_gmc
    from .single import SingleInstance

    if (args.team or args.number) and not args.reid:
        print("--team/--number için --reid de gerekir")
        return 2
    from .detector import resolve_model_path

    explicit_reid = bool(args.reid)
    do_reid, do_team, do_number = live_reid_plan(
        cfg, args, resolve_model_path(args.reid_model or cfg.reid_model).is_file(),
        resolve_model_path(cfg.number_model).is_file())
    args.reid, args.team, args.number = do_reid, do_team, do_number
    if args.fps:
        cfg.live_fps = args.fps
    if args.wait > 0:
        from .ipc import wait_for_ipc

        print(f"mpv bekleniyor (en çok {args.wait:g} sn)...")
        if not wait_for_ipc(cfg.ipc_path, args.wait):
            print("HATA: mpv IPC kanalı açılmadı (mpv çalışıyor mu?)", file=sys.stderr)
            return 1
    # Olay dinleyicisi modellerden ÖNCE bağlanır: modeller (YOLOX, poz, Re-ID, tüm-vücut) exe'de
    # paketlenince yükleme sn–dakika sürüyor; mpv `script-message`'i biriktirmez, dinleyici yokken
    # gelen sağ tık kaybolurdu (artı sarı kalır, takip hiç başlamaz). Şimdi kuyruğa girer, modeller
    # hazır olunca `run_live` işler.
    events: queue.Queue = queue.Queue()
    listener = EventListener(cfg.ipc_path, events)
    listener.start()
    _notify_loading(cfg.ipc_path, True)
    pose_det = None
    if args.single_pose or cfg.single_pose:  # G2: tek model (poz) hem kişi hem eklem
        from .pose import PoseDetector

        try:
            pose_det = PoseDetector(cfg.pose_model, cfg.live_det_conf, cfg.pose_conf, cfg.det_iou,
                                    device=args.device or cfg.device)
        except Exception as e:
            errlog.record("tek-model (poz) yükleme", e)
            print(f"UYARI: tek-model (poz) açılamadı ({e}); ayrı person modeline dönülüyor.",
                  file=sys.stderr)
    try:
        det = pose_det or Detector(
            args.model or cfg.model_path,
            conf_thres=cfg.live_det_conf,
            iou_thres=cfg.det_iou,
            input_size=cfg.det_size,
            device=args.device or cfg.device,
            model_type=cfg.model_type,
            yolox_decoded=cfg.yolox_decoded,
        )
    except Exception as e:  # model yok/bozuk: sağ tık nesne takibi modelsiz de çalışır
        errlog.record("person modeli yükleme", e)
        print(f"UYARI: person modeli yüklenemedi ({e}); yalnız sağ tık nesne takibi çalışır "
              "(oyuncu kimliği/Re-ID yok).", file=sys.stderr)
        if explicit_reid:
            print("--reid için person modeli gerekir", file=sys.stderr)
            return 2
        pipeline = NullPipeline()
        info = ["Model: yok (yalnız nesne takibi)"]
    else:
        print(f"detector: provider={det.providers[0]}, girdi={det.size}")
        info = [model_line("Model", cfg.pose_model if pose_det else args.model or cfg.model_path,
                           det.session, f"{det.model_type}, {det.size[1]}x{det.size[0]}")]
        pipeline = Pipeline(det, ByteTracker(low_thr=cfg.live_det_conf), gmc=make_gmc(cfg))
    reid = None
    if args.reid and not explicit_reid and isinstance(pipeline, NullPipeline):
        args.reid = args.team = args.number = False  # otomatik Re-ID: person modeli yoksa kapalı
    if args.reid:
        from .reid import Embedder, ReIdManager

        try:
            emb = Embedder(args.reid_model or cfg.reid_model, device=args.device or cfg.device)
        except Exception as e:
            errlog.record("Re-ID modeli yükleme", e)
            if explicit_reid:
                raise
            print(f"UYARI: Re-ID modeli yüklenemedi ({e}); Re-ID kapalı.", file=sys.stderr)
            args.reid = args.team = args.number = False
    if args.reid:
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
    pose = pose_det  # tek model: poz çıkarımı kişi tespitiyle paylaşılır
    try:
        from .detector import resolve_model_path
        from .pose import PoseEstimator

        if pose is None and resolve_model_path(cfg.pose_model).is_file():
            pose = PoseEstimator(cfg.pose_model, conf_thres=cfg.pose_conf,
                                 device=args.device or cfg.device)
            print(f"Vücut parçası takibi açık: provider={pose.session.get_providers()[0]}")
            info.append(model_line("Poz", cfg.pose_model, pose.session))
    except Exception as e:  # eklem takibi isteğe bağlı: yoksa/bozuksa eski davranış
        errlog.record("pose modeli yükleme", e)
        print(f"UYARI: pose modeli yüklenemedi ({e}); eklem takibi kapalı.", file=sys.stderr)
    wb = None
    if pose is not None and cfg.wholebody != "off":  # O2: tüm-vücut (el/yüz/ayak parmağı)
        try:
            from .detector import resolve_model_path
            from .wholebody import WholeBodyEstimator

            wb_path = resolve_model_path(cfg.wholebody_model)
            if wb_path.is_file():
                wb = WholeBodyEstimator(wb_path, device=args.device or cfg.device)
                print(f"Tüm-vücut poz açık: provider={wb.session.get_providers()[0]}")
                info.append(model_line("Tüm vücut", cfg.wholebody_model, wb.session))
            elif cfg.wholebody == "on":
                print(f"UYARI: {cfg.wholebody_model} yok; el/yüz/ayak parmağı takibi kapalı.",
                      file=sys.stderr)
        except Exception as e:  # isteğe bağlı: yoksa/bozuksa 17 noktalı davranış
            errlog.record("tüm-vücut modeli yükleme", e)
            print(f"UYARI: tüm-vücut modeli yüklenemedi ({e}); yalnız 17 nokta.", file=sys.stderr)
    # Aynı mpv'yi birden çok takip programı sürmesin (her mpv açılışı yeni süreç başlatır)
    inst = SingleInstance(Path(args.cfg_path).resolve().parent / "tracker.lock")
    stop = threading.Event()
    if inst.claim():
        inst.watch(stop)
    # Konsolsuz (pythonw) çalışırken log'a 5 sn'de bir hız/gecikme/hedef satırı yaz
    stats = args.stats or (5.0 if getattr(args, "headless", False) else 0.0)
    _notify_loading(cfg.ipc_path, False)
    try:
        with MpvIpc(cfg.ipc_path, keep_events=False) as mpv:  # komut bağlantısı olay biriktirmez
            run_live(mpv, events, pipeline, cfg, stats_every=stats, reid=reid,
                     cfg_path=args.cfg_path, pose=pose, info=info, stop=stop, wholebody=wb,
                     cuts=make_cuts(cfg))
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


def _log_if_headless(cfg_path: str, name: str = "takipli-oynat-log.txt") -> Path | None:
    """`pythonw.exe` (mpv'nin otomatik başlattığı gizli süreç) konsolsuzdur: sys.stdout/stderr None
    olur ve her hata sessizce kaybolur. Bu durumda çıktıyı masaüstündeki
    `takipli-oynat-log.txt`'ye yaz (her başlangıçta sıfırlanır): takip çalışmıyorsa neden orada."""
    if sys.stdout is not None and sys.stderr is not None:
        return None
    try:
        path = _log_dir(cfg_path) / name
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


def providers_cmd(cfg: Config, args: argparse.Namespace) -> int:
    """GPU sağlayıcı tanılaması. Çıkış kodu 0: tanı yazıldı; 1: onnxruntime yok / hata."""
    from . import providers

    try:
        rep = providers.diagnose(args.device or cfg.device, args.model)
    except (ImportError, ValueError) as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 1
    print(providers.to_json(rep) if args.json else providers.format_report(rep))
    return 1 if rep.get("session_error") else 0


def sam_bench_cmd(cfg: Config, args: argparse.Namespace) -> int:
    """SAM grafik kıyası. Çıkış kodu 0: en az bir grafik ölçüldü; 1: hiçbiri ölçülemedi."""
    from . import sam_bench

    rep = sam_bench.run_bench(args.model_dir, args.device or cfg.device, max(args.runs, 1),
                              max(args.warmup, 0), args.fp16)
    print(sam_bench.format_report(rep))
    table = sam_bench.markdown_rows(rep)
    print("\n" + table)
    if args.out:
        sam_bench.save_report(rep, args.out)
        Path(args.out).with_suffix(".md").write_text(table + "\n", encoding="utf-8")
        print(f"\nRapor: {args.out} (+ {Path(args.out).with_suffix('.md').name})")
    return 0 if any("stats" in r for r in rep["rows"]) else 1


def sam_first_cmd(cfg: Config, args: argparse.Namespace) -> int:
    """Bir görüntü + dikdörtgen -> ilk maske. Çıkış kodu 0: maske bulundu ve PNG yazıldı; 1: bulunamadı."""
    import time

    from . import sam_engine as se

    img = se.read_image(args.image)
    h, w = img.shape[:2]
    rect = se.parse_rect(args.rect, w, h, args.norm)
    eng = se.SamEngine(args.model_dir, args.device or cfg.device, rule=args.rule)
    ms: dict[str, float] = {}
    t0 = time.perf_counter()
    enc = eng.encode(img)
    ms[se.ENC] = (time.perf_counter() - t0) * 1000
    t1 = time.perf_counter()
    res = eng.segment_rect(enc, rect)
    ms[se.DEC] = (time.perf_counter() - t1) * 1000
    if res is None:
        print("Maske bulunamadı: dikdörtgeni nesnenin çevresine yeniden çizin.", file=sys.stderr)
        return 1
    print(se.format_result(res, eng.providers(), ms))
    out = Path(args.out) if args.out else Path(args.image).with_name(Path(args.image).stem + "_maske.png")
    se.save_png(out, se.draw_overlay(img, res))
    print(f"Kontur PNG: {out}")
    return 0


def sam_preview_cmd(cfg: Config, args: argparse.Namespace) -> int:
    """Çizilen dikdörtgen -> ilk maske -> önizleme dosyası (S6). 0: maske var (CONFIRM); 1: maske yok (NO_MASK)."""
    from . import sam_engine as se
    from . import sam_preview, sam_track

    clip = sam_track.Clip(args.video, fps=10.0, start=args.start)
    try:
        rect = se.parse_rect(args.rect, clip.w, clip.h, args.norm)
        it = iter(clip)
        try:
            t, frame = next(it)
        except StopIteration:
            raise ValueError("videodan kare okunamadı") from None
        finally:
            it.close()
    finally:
        clip.close()
    out = args.out or sam_preview.preview_path(args.video)
    res = se.SamEngine(args.model_dir, args.device or cfg.device, rule=args.rule).first_mask(frame, rect)
    if res is None:
        sam_preview.save(out, sam_preview.no_mask(se.to_norm_box(rect, clip.w, clip.h), t=t))
        print("Maske bulunamadı: dikdörtgeni nesnenin çevresine yeniden çizin (aynı komut, yeni --rect).", file=sys.stderr)
        return 1
    lower = None
    if args.pose:
        from types import SimpleNamespace

        from . import lowerbody
        from .pose import PoseEstimator

        est = PoseEstimator(args.pose_model or cfg.pose_model, conf_thres=cfg.pose_conf,
                            device=args.device or cfg.device)
        first = sam_preview.from_first(res, t=t)
        rec = SimpleNamespace(t=t, box=tuple(res.box_norm), conf=first["conf"], tracked=True)
        lower = lowerbody.Follower(lowerbody.LowerBodyModel(min_conf=cfg.kp_min_conf)).step(
            rec, est.estimate(frame), (clip.w, clip.h))
    pay = sam_preview.from_first(res, t=t, lower=lower)
    sam_preview.save(out, pay)
    print(f"Önizleme: {out} · güven {pay['conf']:.2f} · kontur {len(pay['outline'])} nokta · mpv'de P tuşu. "
          "Uygunsa aynı --rect ile `sam-track --preview`; değilse yeni --rect ile bu komutu yeniden çalıştır.")
    return 0


def sam_camera_cmd(cfg: Config, args: argparse.Namespace) -> int:
    """`.sam.json` -> `.views.json` (S11). Model/GPU gerekmez. Kayıtta durum/duruş yoksa kayıttan türetilir."""
    from dataclasses import replace

    from . import camera, sam_track

    if args.fill is not None:
        if not 0.05 <= args.fill <= 1.0:
            raise ValueError("--fill 0.05-1.0 aralığında olmalı")
        cfg = replace(cfg, lower_fill=args.fill)
    doc = sam_track.load_doc(args.sam_json)
    cam, src = camera.views_from_doc(doc, cfg)
    out = camera.save_views(doc, cam, args.out or camera.views_path_for(args.sam_json), src)
    print(f"bölge kaynağı: {src} · hedef doluluk {cfg.lower_fill:.2f}")
    print("  " + cam.summary())
    print(f"Görünümler: {out}")
    return 0 if cam.views else 1


def sam_track_cmd(cfg: Config, args: argparse.Namespace) -> int:
    """Video boyunca SAM bellek takibi (S4). Çıkış kodu 0: kayıt üretildi; 1: ilk karede maske yok / hata."""
    import time

    from . import sam_bench, sam_preview, sam_track
    from . import sam_engine as se
    from .detector import _PROVIDER_NAMES
    from .posture import LEFT_FRAME
    from .trackgate import TrackGate
    from .trackstate import TRACKED as TRACKED_STATE
    from .trackstate import TrackStateMachine

    clip = sam_track.Clip(args.video, fps=args.fps, start=args.start, max_seconds=args.max_seconds)
    try:
        rect = se.parse_rect(args.rect, clip.w, clip.h, args.norm)
    except ValueError:
        clip.close()
        raise
    base_mb = sam_bench.nvidia_smi_used_mb()  # modeller yüklenmeden önce: VRAM farkı için
    eng = se.SamEngine(args.model_dir, args.device or cfg.device, rule=args.rule, memory=True)
    prov = eng.providers()
    cuda = any(p["provider"] == _PROVIDER_NAMES["cuda"] for p in prov.values())
    vram = sam_bench.VramSampler(sam_bench.nvidia_smi_used_mb) if cuda else None
    stats, records = sam_track.TrackStats(), []
    pw = (sam_preview.Writer(sam_preview.preview_path(args.video), se.to_norm_box(rect, clip.w, clip.h))
          if args.preview else None)
    use_gate = not args.no_gate
    gate = TrackGate() if use_gate else None
    frames = clip
    follower, now_poses, lower_rows, posture_rows = None, [], [], []
    lower, now_frame, verifier = None, [None], None
    machine = TrackStateMachine(hold_s=cfg.lost_hold_s)  # S9: 7 durumlu makine
    state_rows, track = [], None
    if args.reid:  # S10: Re-ID modeli (isteğe bağlı dosya); yoksa uyar, Re-ID'siz sür
        from .reentry import ReentryVerifier

        try:
            from .reid import Embedder

            verifier = ReentryVerifier(Embedder(cfg.reid_model, device=args.device or cfg.device), cfg)
        except Exception as e:  # model dosyası yok / açılamadı
            print(f"Re-ID kapalı (kayıptan dönüş yalnız S9 kurallarıyla doğrulanır): {e}", file=sys.stderr)
    if args.pose or args.posture or verifier is not None:  # S7: her karede poz; track_video tembel: kayıt i, i. karenin pozuyla eşleşir
        from . import lowerbody
        from .pose import PoseEstimator

        est = PoseEstimator(args.pose_model or cfg.pose_model, conf_thres=cfg.pose_conf,
                            device=args.device or cfg.device)
        if args.posture:  # S8: duruş katmanı S7 modelinin üstünde; --pose çıktısı değişmez
            from . import posture

            follower = posture.follower(cfg.kp_min_conf)
        else:
            follower = lowerbody.Follower(lowerbody.LowerBodyModel(min_conf=cfg.kp_min_conf))

        def frames_with_pose():
            for tt, fr in clip:
                now_poses[:] = est.estimate(fr)
                now_frame[0] = fr  # S10: Re-ID aynı kareyi kırpar
                yield tt, fr

        frames = frames_with_pose()
    t0 = time.perf_counter()
    complete = False
    try:
        if vram:
            vram.__enter__()
        for rec in sam_track.track_video(eng, frames, rect, stats=stats, use_gate=use_gate, gate=gate,
                                         keep_masks=pw is not None):
            if follower is not None:
                lower = follower.step(rec, now_poses, (clip.w, clip.h))
                if args.posture:
                    posture_rows.append(lower.row())
                    lower_rows.append(lower.lower.row())
                else:
                    lower_rows.append(lower.row())
            # S8: iki bacak da kareden çıktıysa ipucu
            legs = getattr(lower, "legs", None) if args.posture else None
            gone = bool(legs) and all(v == LEFT_FRAME for v in legs.values())
            ident, ctx = None, (machine.reentry_context(rec) if verifier is not None else None)
            if ctx is not None:  # S10: kayıptan dönen kare: kişi hedef mi?
                ident = verifier.check(now_frame[0], rec, now_poses, (clip.w, clip.h), ctx)
            track = machine.update(rec, legs_left=gone, identity=ident)
            if verifier is not None and track.state == TRACKED_STATE and rec.clean:
                verifier.observe(now_frame[0], rec, now_poses, (clip.w, clip.h), rec.t)  # hedef görünür: galeri
            state_rows.append(track.row())
            if pw is not None:
                pw.update(rec, lower, track)
                rec.mask = None  # önizleme yazıldı; maskeler bellekte birikmesin
            records.append(rec)
            if rec.index % 30 == 0:
                fps = stats.frames / max(time.perf_counter() - t0, 1e-9)
                print(f"kare {rec.index} t={rec.t:.1f}s {rec.state} conf {rec.conf:.2f} · "
                      f"izlenen {stats.tracked} kayıp {stats.lost} (kapı reddi {stats.rejected}) · {fps:.1f} kare/sn", flush=True)
        complete = True
    except KeyboardInterrupt:
        print("Durduruldu: şimdiye kadarki kayıtlar yazılıyor.", file=sys.stderr)
    finally:
        if vram:
            vram.__exit__(None, None, None)
        if pw is not None and records:
            pw.finish(lower=lower, track=track)
        wall = time.perf_counter() - t0
        out = None
        if records and not args.no_save:
            doc = sam_track.make_doc(
                args.video, records, size=(clip.w, clip.h), sample_fps=args.fps, start=args.start,
                rect=se.to_norm_box(rect, clip.w, clip.h), rule=args.rule, providers=prov,
                layout=eng.memory_layout(), timing_ms=sam_track.ms_per_call(eng), complete=complete,
                gate=gate, use_gate=use_gate, lower=lower_rows or None,
                posture=posture_rows or None, states=state_rows or None,
                reentry=verifier.rows if verifier is not None else None)
            out = sam_track.save_doc(args.out or sam_track.sam_path(args.video), doc)
            if args.camera:
                from . import camera

                cam, cam_src = camera.views_from_doc(doc, cfg)
                vout = camera.save_views(doc, cam, camera.views_path_for(out), cam_src)
                print(f"  {cam.summary()}\n  Görünümler: {vout} (bölge kaynağı: {cam_src})")
        if records:
            print(f"\nkare {stats.frames} · izlenen {stats.tracked} · kayıp {stats.lost} · {wall:.1f} sn · "
                  f"{stats.frames / max(wall, 1e-9):.2f} kare/sn")
            print("  " + (gate.summary() if gate else "kapı: kapalı (--no-gate)")
                  + f" · belleğe girmeyen (temiz değil) {stats.unclean}")
            print("  " + machine.summary())
            if verifier is not None:
                print("  " + verifier.summary())
            for n, ms in sam_track.ms_per_call(eng).items():
                p = prov.get(n, {})
                print(f"  {n}: {p.get('provider', '?')}{' (FELL BACK)' if p.get('fell_back') else ''} · "
                      f"{ms:.1f} ms/çağrı ({int(eng.timing[n][1])} çağrı)")
            if cuda:
                peak = vram.peak if vram and vram.peak is not None and base_mb is not None else None
                print("  tepe VRAM: " + (f"{peak - base_mb:.0f} MB (yükleme öncesine göre)" if peak is not None else "ölçülemedi"))
            else:
                print("  tepe VRAM: n/a (yalnız CUDA'da ölçülür)")
            if out:
                print(f"Kayıt: {out}")
    if not complete:
        return 130
    return 0 if records else 1


def pose_bench_cmd(cfg: Config, args: argparse.Namespace) -> int:
    """Her poz modelini aynı karelerde ölçer (ısınma hariç): ms, fps, sağlayıcı, fp16."""
    import time

    from .bench import _pct
    from .pose import PoseEstimator

    frames = _bench_frames(args.source, max(args.frames, 1))
    models = args.model or [cfg.pose_model]
    rows = []
    for m in models:
        est = PoseEstimator(m, conf_thres=cfg.pose_conf, device=args.device or cfg.device)
        est.estimate(frames[0])  # ısınma (DirectML ilk derleme)
        ms, persons = [], 0
        for f in frames:
            t0 = time.perf_counter()
            persons += len(est.estimate(f))
            ms.append((time.perf_counter() - t0) * 1000)
        st = {"mean": sum(ms) / len(ms), "p50": _pct(ms, 0.5), "p95": _pct(ms, 0.95)}
        rows.append((m, est.session.get_providers()[0], est.fp16, est.size, st, persons / len(ms)))
    print(f"{len(frames)} kare, {frames[0].shape[1]}x{frames[0].shape[0]}")
    for m, prov, fp16, size, st, per in rows:
        print(f"{Path(m).name}: {st['mean']:.1f} ms ort · p50 {st['p50']:.1f} · "
              f"p95 {st['p95']:.1f} · "
              f"{1000 / max(st['mean'], 1e-6):.1f} fps · {prov} · "
              f"{'fp16' if fp16 else 'fp32'} girdi · {size[1]}x{size[0]} · {per:.1f} kişi/kare")
    return 0


def _bench_frames(source: str, n: int) -> list:
    import cv2

    img = cv2.imread(source)
    if img is not None:
        return [img] * n
    cap = cv2.VideoCapture(source)
    out = []
    while len(out) < n:
        ok, f = cap.read()
        if not ok:
            break
        out.append(f)
    cap.release()
    if not out:
        raise ValueError(f"kare okunamadı: {source}")
    return out


def _run_live_with_retry(cfg: Config, args: argparse.Namespace, tries: int = 3,
                         sleep=None) -> int:
    """Canlı mod başlangıçta geçici bir hatayla (IPC kanalı, bozuk satır...) düşerse birkaç kez
    yeniden dener: mpv ile birlikte gizli başlatılan süreç tek hatada ölüp takibi bırakmasın.
    Kalıcı hatalar (model/dosya yok) ve Ctrl+C yeniden denenmez."""
    import time

    sleep = sleep or time.sleep
    for i in range(1, tries + 1):
        try:
            return run_live_cmd(cfg, args)
        except KeyboardInterrupt:
            return 0
        except (FileNotFoundError, ImportError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            errlog.record("canlı mod başlatma", e)
            return 1
        except (ValueError, MpvIpcError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            errlog.record(f"canlı mod başlatma (deneme {i}/{tries})", e)
            if i == tries:
                return 1
            print("yeniden deneniyor...", file=sys.stderr)
            sleep(2.0)
        except Exception as e:  # beklenmeyen çökme de günlüğe girsin
            errlog.record("canlı mod ÇÖKTÜ", e)
            raise
    return 1


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    args = build_parser().parse_args(argv)
    cfg = Config.load(args.config) if args.config and Path(args.config).is_file() else Config()
    args.cfg_path = args.config or "tracker_config.json"  # canlı `track-save` hedefi
    try:  # S1: device=auto sırası (varsayılan dml,cuda; TAKIPLI_PROVIDER_ORDER geçer)
        if args.cmd not in ("ping", "view", "listen"):  # numpy'siz çalışırlar; detector numpy ister
            from .detector import set_auto_order

            set_auto_order(cfg.provider_order)
    except ValueError as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 1
    if args.cmd == "providers":  # mpv bağlantısı gerekmez
        return providers_cmd(cfg, args)
    if args.cmd == "detect":  # mpv bağlantısı gerekmez
        try:
            return detect_image(cfg, args)
        except (FileNotFoundError, ValueError, ImportError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            return 1
    if args.cmd == "sam-bench":  # mpv bağlantısı gerekmez
        try:
            return sam_bench_cmd(cfg, args)
        except KeyboardInterrupt:
            return 130
        except (FileNotFoundError, ValueError, ImportError, OSError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            return 1
    if args.cmd == "sam-first":  # mpv bağlantısı gerekmez
        try:
            return sam_first_cmd(cfg, args)
        except KeyboardInterrupt:
            return 130
        except (FileNotFoundError, ValueError, ImportError, OSError, RuntimeError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            return 1
    if args.cmd == "sam-preview":  # mpv bağlantısı gerekmez
        try:
            return sam_preview_cmd(cfg, args)
        except KeyboardInterrupt:
            return 130
        except (FileNotFoundError, ValueError, ImportError, OSError, RuntimeError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            return 1
    if args.cmd == "sam-camera":  # mpv bağlantısı gerekmez
        try:
            return sam_camera_cmd(cfg, args)
        except (FileNotFoundError, ValueError, KeyError, OSError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            return 1
    if args.cmd == "sam-track":  # mpv bağlantısı gerekmez
        try:
            return sam_track_cmd(cfg, args)
        except KeyboardInterrupt:
            return 130
        except (FileNotFoundError, ValueError, ImportError, OSError, RuntimeError) as e:  # NoInitialMask ValueError
            print(f"HATA: {e}", file=sys.stderr)
            return 1
    if args.cmd == "pose-bench":
        try:
            return pose_bench_cmd(cfg, args)
        except KeyboardInterrupt:
            return 130
        except (FileNotFoundError, ValueError, ImportError, OSError) as e:
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
    if args.cmd == "update":
        return run_update_cmd(cfg, args)
    if args.cmd == "export":
        _log_if_headless(args.cfg_path, "takipli-aktarma-log.txt")
        try:
            return run_export_cmd(cfg, args)
        except KeyboardInterrupt:
            return 130
        except (FileNotFoundError, ValueError, RuntimeError, OSError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            return 1
    if args.cmd in ("offline", "offline-view"):
        try:
            fn = run_offline_cmd if args.cmd == "offline" else run_offline_view_cmd
            if args.cmd == "offline":  # mpv'nin arka planda başlattığı tarama konsolsuzdur
                _log_if_headless(args.cfg_path, "takipli-tarama-log.txt")
            return fn(cfg, args)
        except KeyboardInterrupt:
            return 130
        except (FileNotFoundError, ValueError, ImportError, OSError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            return 1
    if args.cmd == "live":
        args.headless = _log_if_headless(args.cfg_path) is not None
        return _run_live_with_retry(cfg, args)
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
