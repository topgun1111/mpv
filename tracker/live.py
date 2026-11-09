"""Canlı mod (Parça 5): mpv'den kare al → Pipeline → ViewSmoother → IPC `set_view`.

Mantık (`LiveController`) IO'dan ayrıdır ve testlidir; `run_live` döngüsü IO'yu yürütür.
Olaylar (Lua tıklama/aç-kapa/sıfırla) ayrı bir IPC bağlantısında iş parçacığıyla okunur: Windows
pipe'ında okuma bloklar ve aynı tutaçta eşzamanlı yazmayı da engeller; mpv çok istemciyi destekler.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

from .clicks import (
    DOT_MSG,
    HUD_MSG,
    RELEASE_MSG,
    RESET_MSG,
    SAVE_MSG,
    SETTING_MSG,
    STATUS_MSG,
    TOGGLE_MSG,
    message_name,
    parse_click,
)
from .config import Config
from .frames import grab_frame
from .geometry import View, compute_view
from .ipc import MpvCommandError, MpvIpc, MpvIpcError
from .settings import adjust, status_text
from .smooth import BoxFilter, ViewSmoother, ease_view

CLOSED = {"event": "__closed__"}


class EventListener(threading.Thread):
    """Kendi bağlantısından mpv olaylarını `out` kuyruğuna aktarır; kopunca CLOSED koyar."""

    def __init__(self, path: str, out: queue.Queue):
        super().__init__(daemon=True)
        self.path, self.out = path, out
        self._stop_evt = threading.Event()

    def stop(self) -> None:
        self._stop_evt.set()

    def run(self) -> None:
        try:
            with MpvIpc(self.path) as conn:
                while not self._stop_evt.is_set():
                    ev = conn.poll_event(0.5)
                    if ev is not None:
                        self.out.put(ev)
        except MpvIpcError:
            pass
        self.out.put(CLOSED)


@dataclass(frozen=True)
class Output:
    view: View | None = None  # uygulanacak görünüm (None: değiştirme)
    osd: str | None = None


def _default_point_factory(frame, px: float, py: float, cfg: Config, box=None):
    from .point import WorldPointTracker  # cv2 yalnız nesne takibi başlayınca içe aktarılır

    return WorldPointTracker(frame, px, py, box=box, box_frac=cfg.point_box,
                             refine=cfg.point_refine, max_side=cfg.point_max_side,
                             min_score=cfg.point_min_score)


def _box_gap(t, px: float, py: float) -> float:
    """Noktanın kutuya uzaklığı (px); içindeyse 0."""
    b = t.bbox
    dx = max(b.x1 - px, 0.0, px - b.x2)
    dy = max(b.y1 - py, 0.0, py - b.y2)
    return (dx * dx + dy * dy) ** 0.5


def pick_track(tracks, px: float, py: float, tol: float = 0.0):
    """Tıklanan noktadaki izi seçer; yoksa None.

    1) Nokta bir veya daha fazla kutunun içindeyse: kutu boyutuna göre normalize merkez
       uzaklığı en küçük olan (iç içe/çakışan kutularda küçük kutuyu tıklamak mümkün kalır);
       eşitlikte alanı küçük olan.
    2) Hiçbirinin içinde değilse: kutu kenarına `tol` piksel içindeki en yakın iz (tol=0: yok).
    """
    hits = [t for t in tracks if t.bbox.contains(px, py)]
    if hits:
        def score(t):
            b = t.bbox
            nx = (px - b.cx) / max(b.w, 1e-6)
            ny = (py - b.cy) / max(b.h, 1e-6)
            return (nx * nx + ny * ny, b.w * b.h)

        return min(hits, key=score)
    if tol <= 0:
        return None
    near = [(g, t) for t in tracks if (g := _box_gap(t, px, py)) <= tol]
    return min(near, key=lambda gt: gt[0])[1] if near else None


class LiveController:
    def __init__(
        self,
        pipeline,
        cfg: Config,
        smoother: ViewSmoother | None = None,
        box_filter: BoxFilter | None = None,
        reid=None,
        cfg_path: str | None = None,
        point_factory=None,
    ):
        self.pipeline, self.cfg, self.reid = pipeline, cfg, reid  # reid: ReIdManager | None
        # (kare, px, py, cfg) -> update(kare) -> BBox | None veren nesne; testte sahtesi verilir
        self._point_factory = point_factory or _default_point_factory
        self.point = None  # sağ tıkla seçilen sınıfsız nesne izleyici (tracker/point.py)
        self.cfg_path = cfg_path  # `track-save` ayarları buraya yazar
        self._id_mark = 0  # hedef son görüldüğünde izlerin en büyük ID'si (ID'ler artan)
        self.flt = box_filter or BoxFilter(cfg.kf_accel, cfg.kf_meas)
        self.smoother = smoother or ViewSmoother(
            cfg.alpha_pos, cfg.alpha_zoom, cfg.dead_zone_pos, cfg.dead_zone_zoom
        )
        self.enabled = False
        self.target_id: int | None = None
        self.last_tracks: list = []
        self._click = None
        self._last_t: float | None = None
        self._lost = 0  # üst üste hedefsiz kare sayısı
        self._lost_t0: float | None = None  # kaybın başladığı video zamanı
        self._lost_from: View | None = None  # kayıp anındaki görünüm (zoom-out başlangıcı)
        self._zooming_out = False
        self._view = View()  # en son uygulanması istenen görünüm
        self._dot: tuple[float, float] | None = None  # son görülen hedef merkezi (video-normalize)

    @property
    def has_target(self) -> bool:
        return self.target_id is not None or self.point is not None

    def dot(self) -> tuple[float, float] | None:
        """Ekranda kırmızı nokta olarak gösterilecek konum; hedef yok/kayıpsa None."""
        return self._dot if self.enabled and self.has_target and self._lost_t0 is None else None

    def _clear_lost(self) -> None:
        self._lost, self._lost_t0, self._lost_from, self._zooming_out = 0, None, None, False

    def _reset_tracking(self) -> None:
        self.pipeline.reset()
        self.smoother.reset()
        self.flt.reset()
        self.target_id = None
        self.point = None
        self._click = None
        self._last_t = None
        self._clear_lost()
        self._view = View()
        self._id_mark = 0
        if self.reid:
            self.reid.reset()

    def _release(self) -> Output:
        """Hedefi bırak: görünüm 1x'e döner; takip açık kalır, yeni tıklama hedef seçer."""
        had = self.has_target
        self.target_id = None
        self.point = None
        self._clear_lost()
        self.smoother.reset()
        self.flt.reset()
        self._view = View()
        if self.reid:
            self.reid.reset()
        if not had:
            return Output(osd="Bırakılacak hedef yok")
        return Output(view=View(), osd="Hedef bırakıldı")

    def handle_event(self, ev: dict) -> Output:
        click = parse_click(ev)
        if click:
            self.enabled = True  # toggle olayı kaçmış olsa da tıklama takibi açar
            self._click = click
            return Output()
        name = message_name(ev)
        if name == TOGGLE_MSG:
            on = (ev.get("args") or [None, "off"])[1:2] == ["on"]
            self.enabled = on
            if not on:
                self._reset_tracking()
                return Output(view=View())
            return Output()
        if name == RESET_MSG:
            self._reset_tracking()
            return Output(view=View())
        if name == RELEASE_MSG:
            self._click = None
            return self._release()
        if name == SETTING_MSG:
            return self._on_setting(ev.get("args") or [])
        if name == STATUS_MSG:
            return Output(osd=status_text(self.cfg, self.target_id, self.point is not None))
        if name == SAVE_MSG:
            return self._on_save()
        return Output()

    def _on_setting(self, args: list) -> Output:
        try:
            key, direction = str(args[1]), int(float(args[2]))
        except (IndexError, ValueError):
            return Output()
        osd = adjust(self.cfg, key, max(-1, min(1, direction)))
        if osd is None:
            return Output()
        self.smoother.set_alpha(self.cfg.alpha_pos, self.cfg.alpha_zoom)
        return Output(osd=osd)

    def _on_save(self) -> Output:
        if not self.cfg_path:
            return Output(osd="Kaydedilemedi: config yolu yok")
        try:
            self.cfg.save(self.cfg_path)
        except OSError as e:
            return Output(osd=f"Kaydedilemedi: {e}")
        return Output(osd=f"Ayarlar kaydedildi: {self.cfg_path}")

    def hud_text(self) -> str:
        """Köşe etiketi (boş = gizle). Python → Lua `track-hud`."""
        if not self.enabled or not self.cfg.hud:
            return ""
        if not self.has_target:
            return "Takip: hedef seç (tıkla)"
        if self._lost_t0 is not None:
            return "Takip: hedef kayıp" + (" (uzaklaşıyor)" if self._zooming_out else "")
        return "Takip: nesne" if self.point is not None else f"Takip: ID {self.target_id}"

    def needs_frame(self, t: float) -> bool:
        """Duraklatılmış (time-pos değişmiyor) ve bekleyen tıklama yoksa kare işlemeye gerek yok."""
        if not self.enabled:
            return False
        return self._click is not None or self._last_t is None or abs(t - self._last_t) > 1e-6

    def step(self, frame, t: float) -> Output:
        if not self.enabled:
            return Output()
        fh, fw = frame.shape[:2]
        prev = self._last_t
        if prev is not None and (t < prev - 0.05 or t - prev > self.cfg.seek_jump):
            had = self.has_target
            click = self._click
            self._reset_tracking()
            self._click = click
            if had:
                self._last_t = t
                return Output(view=View(), osd="Atlama: hedefi yeniden seç")
        self._last_t = t
        click = self._click
        if click is not None and click.kind in ("point", "rect"):  # sağ tık / sol sürükleme: herhangi bir nesne
            self._click = None
            return self._start_point(frame, t, click)
        if self.point is not None and click is None:  # nesne izleniyor: detector gerekmez
            return self._step_point(frame, t, None)
        tracks = self.pipeline.step(frame)
        self.last_tracks = tracks
        osd = None
        if self._click is not None:
            click, self._click = self._click, None
            tol = self.cfg.pick_tol * fh
            picked = pick_track(tracks, click.px * fw / click.vw, click.py * fh / click.vh, tol)
            if picked is None:
                osd = "Burada kişi yok"  # mevcut hedef (varsa) korunur
            elif picked.id == self.target_id:  # hedefin üstüne tekrar tıklama: bırak
                out = self._release()
                return Output(view=out.view, osd=out.osd)
            else:
                if not self.has_target:
                    self.smoother.reset()  # yeni hedefe geçişte yumuşatıcı korunur: kayarak gider
                elif self._zooming_out:
                    self.smoother.seed(self._view)  # zoom-out'tan yeni hedefe sıçramadan geç
                self.point = None  # oyuncu seçildi: nesne izleyici bırakılır
                self.target_id = picked.id
                self._clear_lost()
                self.flt.reset()  # süzgeç eski hedefin hızını taşımasın
                if self.reid:
                    self.reid.reset()  # galeri eski kişiye aitti
                osd = f"Hedef: ID {picked.id}"
        if self.target_id is None:
            if self.point is not None:  # oyuncu bulunamadı: nesne takibi kesilmesin
                return self._step_point(frame, t, osd)
            return Output(osd=osd)
        tr = next((x for x in tracks if x.id == self.target_id), None)
        if tr is None and self.reid is not None:
            tr, osd = self._try_reid(frame, t, tracks, osd)
        if tr is None:
            return self._on_lost(t, osd)
        self._id_mark = max([self._id_mark, *(x.id for x in tracks)])
        if self.reid is not None:
            self.reid.observe(frame, t, tr, [x for x in tracks if x is not tr])
        return self._follow(tr.bbox, fw, fh, t, osd)

    def _follow(self, bbox, fw: int, fh: int, t: float, osd: str | None) -> Output:
        """Hedef kutusu görüldü (oyuncu ya da nesne): süzgeç → görünüm → yumuşatıcı."""
        if self._zooming_out:  # zoom-out sırasında bulundu: bulunduğumuz görünümden devam
            self.smoother.seed(self._view)
        self._clear_lost()
        vis = getattr(self.point, "visible", True) if self.point is not None else True
        self._dot = (bbox.cx / fw, bbox.cy / fh) if vis else None  # kare dışında nokta çizilmez
        self.flt.update(bbox.scaled(1 / fw, 1 / fh), t)  # kare boyutuna göre normalize
        lead = self.flt.lookahead(self.cfg.lookahead_s, self.cfg.max_lead).scaled(fw, fh)
        raw = compute_view(lead, fw, fh, self.cfg.target_fill, self.cfg.min_zoom,
                           self.cfg.max_zoom)
        self._view = self.smoother.update(raw)
        return Output(view=self._view, osd=osd)

    def _start_point(self, frame, t: float, click) -> Output:
        """Sağ tık: tıklanan noktadaki HERHANGİ bir nesneyi takip etmeye başla (sınıf önemsiz).
        Zaten izlenen hedefin üstüne tekrar sağ tık hedefi bırakır."""
        fh, fw = frame.shape[:2]
        px, py = click.px * fw / click.vw, click.py * fh / click.vh
        box = None
        if click.kind == "rect" and click.box is not None:
            x1, y1, x2, y2 = click.box
            sx, sy = fw / click.vw, fh / click.vh
            box = (x1 * sx, y1 * sy, max(x2 * sx, x1 * sx + 4), max(y2 * sy, y1 * sy + 4))
            px, py = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        if (box is None and self.point is not None and self._lost_t0 is None
                and self.point.bbox.contains(px, py)):
            out = self._release()
            return Output(view=out.view, osd=out.osd)
        cur = next((x for x in self.last_tracks if x.id == self.target_id), None)
        if box is None and cur is not None and cur.bbox.contains(px, py):  # izlenen oyuncuya tekrar sağ tık
            out = self._release()
            return Output(view=out.view, osd=out.osd)
        try:
            pt = (self._point_factory(frame, px, py, self.cfg, box=box) if box is not None
                  else self._point_factory(frame, px, py, self.cfg))
        except Exception as e:  # cv2 yok / kare bozuk: takip döngüsü düşmesin
            return Output(osd=f"Nesne takibi başlatılamadı: {e}")
        if not self.has_target:
            self.smoother.reset()  # ilk hedef: doğrudan oraya; sonrakilerde kayarak geçilir
        elif self._zooming_out:
            self.smoother.seed(self._view)
        self.target_id = None
        self.last_tracks = []
        self.pipeline.reset()  # oyuncu izleri artık gerekmez; sonraki sol tık taze başlar
        if self.reid:
            self.reid.reset()
        self.point = pt
        self._clear_lost()
        self.flt.reset()
        return self._follow(pt.bbox, fw, fh, t, "Hedef: nesne")

    def _step_point(self, frame, t: float, osd: str | None) -> Output:
        fh, fw = frame.shape[:2]
        box = self.point.update(frame)
        if box is None:
            return self._on_lost(t, osd)
        return self._follow(box, fw, fh, t, osd)

    def _try_reid(self, frame, t: float, tracks, osd: str | None):
        """Hedef ID'si yok: kayıp sırasında doğan yeni izler arasında galeriye uyan varsa hedefi
        ona bağla (ByteTrack ID değiştirmişse)."""
        cands = [x for x in tracks
                 if x.id > self._id_mark and x.age >= self.cfg.reid_min_age]
        cand = self.reid.match(frame, t, cands, tracks)
        if cand is None:
            return None, osd
        self.target_id = cand.id
        self.flt.reset()  # konum sıçradı: eski hız/konum geçersiz
        return cand, f"Hedef yeniden bulundu: ID {cand.id}"

    def _on_lost(self, t: float, osd: str | None) -> Output:
        """Hedef bu karede yok: `lost_hold_s` son görünümde bekle, sonra `lost_zoomout_s` içinde
        1x'e kademeli zoom-out; hedef geri gelirse (aynı ID) takip kaldığı yerden sürer.
        Süre video zamanıyla ölçülür (duraklatma/atlama gerçek süreyi şişirmez)."""
        self._lost += 1
        if self._lost_t0 is None:
            self._lost_t0, self._lost_from = t, self._view
            osd = osd or "Hedef kayboldu"
        el = t - self._lost_t0 - max(self.cfg.lost_hold_s, 0.0)
        if el < 0.0:
            return Output(osd=osd)  # bekle
        self._zooming_out = True
        dur = self.cfg.lost_zoomout_s
        assert self._lost_from is not None
        self._view = ease_view(self._lost_from, View(), el / dur if dur > 0 else 1.0)
        return Output(view=self._view, osd=osd)


def run_live(
    mpv,
    events: queue.Queue,
    pipeline,
    cfg: Config,
    *,
    grab=grab_frame,
    stop: threading.Event | None = None,
    log=print,
    clock=time.monotonic,
    sleep=time.sleep,
    stats_every: float = 0.0,
    reid=None,
    cfg_path: str | None = None,
) -> None:
    ctl = LiveController(pipeline, cfg, reid=reid, cfg_path=cfg_path)
    last_hud: tuple[str, bool] = ("", False)
    min_dt = 1.0 / max(cfg.live_fps, 1.0)
    last_view: View | None = None
    n, lag_sum, t_stat = 0, 0.0, clock()

    last_dot: tuple[str, str] = ("", "")

    def sync_dot() -> None:
        # Kırmızı takip noktası (Lua `track-dot`); yalnız konum değişince gönderilir
        nonlocal last_dot
        d = ctl.dot()
        msg = ("off", "") if d is None else (f"{d[0]:.4f}", f"{d[1]:.4f}")
        if msg == last_dot:
            return
        last_dot = msg
        try:
            mpv.command("script-message-to", "track", DOT_MSG, *(m for m in msg if m))
        except MpvCommandError as e:
            log(f"nokta gönderilemedi: {e}")

    def sync_hud() -> None:
        # Lua'ya (etiket metni, hedef kilitli mi) gider; yalnız ikisinden biri değişince.
        # "Kilitli" ekran üstü zoom +/- düğmesinin ne yapacağını belirler (doluluk / video zoom).
        nonlocal last_hud
        state = (ctl.hud_text(), ctl.has_target and ctl.enabled)
        if state == last_hud:
            return
        last_hud = state
        try:
            mpv.command("script-message-to", "track", HUD_MSG, state[0], "1" if state[1] else "0")
        except MpvCommandError as e:
            log(f"HUD gönderilemedi: {e}")

    def emit(out: Output) -> None:
        nonlocal last_view
        if out.osd:
            log(out.osd)
            try:
                mpv.command("show-text", out.osd, 1500)
            except MpvCommandError as e:  # OSD hatası döngüyü durdurmasın
                log(f"OSD gösterilemedi: {e}")
        if out.view is not None and out.view != last_view:
            try:
                mpv.set_view(out.view)
                last_view = out.view
            except MpvCommandError as e:  # mpv reddetti: sonraki karede yeniden dene
                log(f"görünüm uygulanamadı: {e}")
        sync_hud()
        sync_dot()

    log("Canlı mod hazır (Ctrl+C ile çık). mpv'de herhangi bir nesneye sağ tıkla: takip "
        "kendiliğinden açılır (oyuncu kimliği için sol tık).")
    try:
        while not (stop is not None and stop.is_set()):
            t0 = clock()
            timeout = 0.0 if ctl.enabled else 0.1  # kapalıyken olayı bekleyerek boşta kal
            while True:
                try:
                    ev = events.get(timeout=timeout)
                except queue.Empty:
                    break
                timeout = 0.0
                if ev.get("event") == CLOSED["event"]:
                    log("mpv bağlantısı kapandı.")
                    return
                emit(ctl.handle_event(ev))
            if not ctl.enabled:
                continue
            try:
                t = mpv.get_property("time-pos")
                if t is None or not ctl.needs_frame(float(t)):
                    sleep(0.05)
                    continue
                frame = grab(mpv)
            except MpvCommandError:  # video yok / property unavailable
                sleep(0.2)
                continue
            emit(ctl.step(frame, float(t)))
            n += 1
            lag_sum += clock() - t0
            if stats_every and clock() - t_stat >= stats_every:
                dt = clock() - t_stat
                log(f"{n / dt:.1f} kare/sn, gecikme {lag_sum / n * 1000:.0f} ms, "
                    f"hedef={'nesne' if ctl.point is not None else ctl.target_id}, "
                    f"izler={len(ctl.last_tracks)}")
                n, lag_sum, t_stat = 0, 0.0, clock()
            rest = min_dt - (clock() - t0)
            if rest > 0:
                sleep(rest)
    except MpvIpcError as e:
        log(f"mpv bağlantısı kesildi: {e}")
