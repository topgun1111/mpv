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
    ):
        self.pipeline, self.cfg, self.reid = pipeline, cfg, reid  # reid: ReIdManager | None
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

    def _clear_lost(self) -> None:
        self._lost, self._lost_t0, self._lost_from, self._zooming_out = 0, None, None, False

    def _reset_tracking(self) -> None:
        self.pipeline.reset()
        self.smoother.reset()
        self.flt.reset()
        self.target_id = None
        self._click = None
        self._last_t = None
        self._clear_lost()
        self._view = View()
        self._id_mark = 0
        if self.reid:
            self.reid.reset()

    def _release(self) -> Output:
        """Hedefi bırak: görünüm 1x'e döner; takip açık kalır, yeni tıklama hedef seçer."""
        had = self.target_id is not None
        self.target_id = None
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
            return Output(osd=status_text(self.cfg, self.target_id))
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
        if self.target_id is None:
            return "Takip: hedef seç (tıkla)"
        if self._lost_t0 is not None:
            return "Takip: hedef kayıp" + (" (uzaklaşıyor)" if self._zooming_out else "")
        return f"Takip: ID {self.target_id}"

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
            had = self.target_id is not None
            click = self._click
            self._reset_tracking()
            self._click = click
            if had:
                self._last_t = t
                return Output(view=View(), osd="Atlama: hedefi yeniden seç")
        self._last_t = t
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
                if self.target_id is None:
                    self.smoother.reset()  # yeni hedefe geçişte yumuşatıcı korunur: kayarak gider
                elif self._zooming_out:
                    self.smoother.seed(self._view)  # zoom-out'tan yeni hedefe sıçramadan geç
                self.target_id = picked.id
                self._clear_lost()
                self.flt.reset()  # süzgeç eski hedefin hızını taşımasın
                if self.reid:
                    self.reid.reset()  # galeri eski kişiye aitti
                osd = f"Hedef: ID {picked.id}"
        if self.target_id is None:
            return Output(osd=osd)
        tr = next((x for x in tracks if x.id == self.target_id), None)
        if tr is None and self.reid is not None:
            tr, osd = self._try_reid(frame, t, tracks, osd)
        if tr is None:
            return self._on_lost(t, osd)
        self._id_mark = max([self._id_mark, *(x.id for x in tracks)])
        if self.reid is not None:
            self.reid.observe(frame, t, tr, [x for x in tracks if x is not tr])
        if self._zooming_out:  # zoom-out sırasında bulundu: bulunduğumuz görünümden devam
            self.smoother.seed(self._view)
        self._clear_lost()
        self.flt.update(tr.bbox.scaled(1 / fw, 1 / fh), t)  # kare boyutuna göre normalize
        lead = self.flt.lookahead(self.cfg.lookahead_s, self.cfg.max_lead).scaled(fw, fh)
        raw = compute_view(lead, fw, fh, self.cfg.target_fill, self.cfg.min_zoom,
                           self.cfg.max_zoom)
        self._view = self.smoother.update(raw)
        return Output(view=self._view, osd=osd)

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
    last_hud = ""
    min_dt = 1.0 / max(cfg.live_fps, 1.0)
    last_view: View | None = None
    n, lag_sum, t_stat = 0, 0.0, clock()

    def sync_hud() -> None:
        nonlocal last_hud
        text = ctl.hud_text()
        if text == last_hud:
            return
        last_hud = text
        try:
            mpv.command("script-message-to", "track", HUD_MSG, text)
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

    log("Canlı mod hazır (Ctrl+C ile çık). mpv'de t ile takibi aç, oyuncuya sol tıkla.")
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
                    f"hedef={ctl.target_id}, izler={len(ctl.last_tracks)}")
                n, lag_sum, t_stat = 0, 0.0, clock()
            rest = min_dt - (clock() - t0)
            if rest > 0:
                sleep(rest)
    except MpvIpcError as e:
        log(f"mpv bağlantısı kesildi: {e}")
