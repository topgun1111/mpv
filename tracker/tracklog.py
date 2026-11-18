"""Video başına takip günlüğü: masaüstü `TakipLog/<video>-<kısa özet>.log`.

Amaç: hata ayıklama. Her video için tek dosya; canlı takip, çevrimdışı tarama ve dışa aktarma süreçleri
aynı dosyaya EKLER (satır başında süreç etiketi). İçerik:
  - oturum başlığı: sürüm, Python/OS, ONNX Runtime + sağlayıcılar, seçili ekran kartı, her modelin GERÇEKTE
    hangi sağlayıcıyla açıldığı (GPU istendi ama CPU'ya düştüyse UYARI), video bilgisi;
  - olaylar: özellik durum DEĞİŞİMLERİ (OK / HATA / DÜZELDİ), hedef başlangıç/kayıp/geri bulma/bitiş, çekim kesmesi;
  - ÖZET: özellik başına OK/HATA/BOŞ sayacı ve «çalıştı / kısmen / çalışmadı» hükmü; hedef başına takip oranı.
Hiçbir zaman hata fırlatmaz. Etkin günlük yoksa (`activate` çağrılmadıysa) tüm işlevler sessizce geçer;
testler ve harici kullanım masaüstüne yazmaz.
"""
from __future__ import annotations

import hashlib
import os
import platform
import re
import threading
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

FOLDER = "TakipLog"
MAX_BYTES = 2_000_000
PERF_EVERY_S = 30.0
FAIL_REPEAT = 100  # aynı özellik ardışık bu kadar hata verirse bir satır daha yaz

# Özellik adları (özette görünür)
F_FRAME = "kare alma"
F_DETECT = "kişi tespiti"
F_POINT = "nesne takibi"
F_KEYPOINT = "eklem/parça takibi"
F_POSE = "poz tahmini"
F_CAM = "kamera telafisi"
F_CUT = "çekim kesmesi algısı"
F_REID = "Re-ID kurtarma"
F_VIEW = "görünüm uygulama (zoom/kaydırma)"
F_SCANNED = "taranmış ize geçiş"


def log_dir() -> Path | None:
    """Masaüstü/TakipLog (masaüstü yoksa ana klasör/TakipLog)."""
    try:
        from .errlog import desktop_dir

        base = desktop_dir() or Path.home()
        return base / FOLDER
    except Exception:  # noqa: BLE001
        return None


_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def log_name(video: str) -> str:
    """`<ad (≤60)>-<6 hane özet>.log`; özet aynı adlı farklı klasör videolarını ayırır."""
    v = str(video)
    base = re.split(r"[\\/]", v.split("?")[0])[-1] if v else ""  # Windows yolu Linux'ta da bölünür
    stem = base.rsplit(".", 1)[0] if "." in base[1:] else base
    stem = _BAD.sub("_", stem).strip(" .") or "video"
    h = hashlib.md5(v.encode("utf-8", "replace")).hexdigest()[:6]  # noqa: S324 (yalnız ad ayırıcı)
    return f"{stem[:60]}-{h}.log"


def _short_exc(exc: BaseException | str | None, full: bool = False) -> str:
    if exc is None:
        return ""
    if isinstance(exc, BaseException):
        head = f"{type(exc).__name__}: {exc}"
        if not full:
            return head
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
        return tb
    return str(exc)


class _Feat:
    __slots__ = ("ok", "fail", "idle", "state", "streak", "last_detail")

    def __init__(self) -> None:
        self.ok = self.fail = self.idle = self.streak = 0
        self.state: str | None = None  # None | "ok" | "fail"
        self.last_detail = ""


class _Target:
    def __init__(self, label: str, t: float | None) -> None:
        self.label, self.t0, self.t_last = label, t, t
        self.n_ok = self.n_lost = self.episodes = 0
        self.longest = 0.0
        self.lost_since: float | None = None
        self.wall0 = time.time()


class TrackLog:
    def __init__(self, directory: str | Path | None = None, proc: str = "canlı",
                 version: str = "", device_text: str = "") -> None:
        self.dir = Path(directory) if directory else log_dir()
        self.proc = proc
        self.version = version
        self.device_text = device_text  # başlıkta «Ekran kartı: ...»
        self._lock = threading.RLock()
        self._startup: list[str] = []  # video açılmadan önceki oturum satırları (her videoya yazılır)
        self.video: str | None = None
        self.path: Path | None = None
        self.last_path: Path | None = None  # son kapanan videonun dosyası (tanı/test)
        self.feat: dict[str, _Feat] = {}
        self._tgt: _Target | None = None
        self._targets_done: list[str] = []
        self._perf = [0, 0.0, 0.0]  # kare, toplam gecikme, en büyük gecikme (özet)
        self._pw = [0, 0.0, time.monotonic()]  # PERF penceresi
        self._t_now: float | None = None  # son bilinen video zamanı (satırlara eklenir)
        self._opened_at = 0.0

    # ---- düşük seviye yazım ------------------------------------------------------------
    def _stamp(self) -> str:
        s = time.strftime("%H:%M:%S")
        pid = os.getpid()
        t = f" v={self._t_now:.1f}s" if self._t_now is not None else ""
        return f"[{s}] [{self.proc}#{pid}]{t}"

    def _write(self, lines: list[str]) -> None:
        if self.path is None or not lines:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > MAX_BYTES:
                old = self.path.with_suffix(".old.log")
                try:
                    old.unlink()
                except OSError:
                    pass
                self.path.replace(old)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:  # noqa: BLE001, S110
            pass

    def _line(self, level: str, text: str) -> None:
        self._write([f"{self._stamp()} {level:<6} {text}"])

    # ---- oturum / video ----------------------------------------------------------------
    def startup(self, level: str, text: str) -> None:
        """Oturum düzeyi satır (model yükleme vb.): video açıksa hemen, açılacaksa başlıkta yazılır."""
        with self._lock:
            line = f"{self._stamp()} {level:<6} {text}"
            self._startup = (self._startup + [line])[-80:]
            if self.path is not None:
                self._write([line])

    def _system_lines(self) -> list[str]:
        L = [f"Uygulama: Takipli Oynat {self.version}".rstrip(),
             f"Sistem: {platform.platform()} · Python {platform.python_version()}"]
        try:
            import onnxruntime as ort

            L.append(f"ONNX Runtime {getattr(ort, '__version__', '?')}: "
                     + ", ".join(ort.get_available_providers()))
        except Exception as e:  # noqa: BLE001
            L.append(f"ONNX Runtime: YOK/yüklenemedi ({type(e).__name__}: {e})")
        if self.device_text:
            L.append(f"Ekran kartı seçimi: {self.device_text}")
        return L

    def open_video(self, video: str, meta: dict[str, Any] | None = None) -> None:
        with self._lock:
            if self.video is not None:
                self.close_video("video değişti")
            if not self.dir:
                return
            self.video, self.path = str(video), self.dir / log_name(str(video))
            self.last_path = self.path
            self.feat, self._tgt, self._targets_done = {}, None, []
            self._perf, self._pw = [0, 0.0, 0.0], [0, 0.0, time.monotonic()]
            self._t_now = None
            self._opened_at = time.time()
            head = ["", "=" * 78,
                    f"OTURUM {time.strftime('%Y-%m-%d %H:%M:%S')} · süreç: {self.proc} · pid {os.getpid()}",
                    f"Video: {video}"]
            for k, v in (meta or {}).items():
                if v not in (None, "", 0):
                    head.append(f"  {k}: {v}")
            head += ["  " + s for s in self._system_lines()]
            if self._startup:
                head.append("  -- açılış / model yükleme --")
                head += ["  " + s for s in self._startup]
            head.append("=" * 78)
            self._write(head)

    def close_video(self, reason: str = "kapandı") -> None:
        with self._lock:
            if self.video is None:
                return
            self._end_target(reason)
            self._write(self._summary_lines(reason))
            self.video = self.path = None

    # ---- özellik sayaçları -------------------------------------------------------------
    def _f(self, name: str) -> _Feat:
        f = self.feat.get(name)
        if f is None:
            f = self.feat[name] = _Feat()
        return f

    def ok(self, name: str) -> None:
        """Özellik bu adımda çalıştı. Yalnız ilk başarı ve hatadan dönüş satır yazar."""
        with self._lock:
            f = self._f(name)
            f.ok += 1
            f.streak = 0
            if f.state != "ok":
                self._line("OK" if f.state is None else "DÜZELDİ", name)
                f.state = "ok"

    def idle(self, name: str) -> None:
        """Özellik çalıştı ama sonuç yok (ör. karede kişi yok)."""
        with self._lock:
            self._f(name).idle += 1

    def fail(self, name: str, exc: BaseException | str | None = None) -> None:
        """Özellik hata verdi. İlk hata tam ayrıntıyla, sonrakiler yalnız sayılır."""
        with self._lock:
            if self.path is None:  # video yok: açılış satırı olarak sakla
                self.startup("HATA", f"{name}: {_short_exc(exc)}")
                return
            f = self._f(name)
            f.fail += 1
            f.streak += 1
            f.last_detail = _short_exc(exc)
            if f.state != "fail":
                f.state = "fail"
                f.streak = 1
                self._write([f"{self._stamp()} HATA   {name}: {_short_exc(exc)}"]
                            + [f"    {ln}" for ln in _short_exc(exc, full=True).splitlines()[-12:]
                               if isinstance(exc, BaseException)])
            elif f.streak % FAIL_REPEAT == 0:
                self._line("HATA", f"{name}: aynı hata {f.streak} kez üst üste ({f.last_detail})")

    def note(self, text: str, level: str = "BİLGİ") -> None:
        with self._lock:
            self._line(level, text)

    def set_time(self, t: float | None) -> None:
        self._t_now = t

    # ---- model açılışı -----------------------------------------------------------------
    def model_opened(self, path: Any, requested: list[str], session: Any) -> None:
        name = Path(str(path)).name
        try:
            used = list(session.get_providers())
        except Exception:  # noqa: BLE001
            used = []
        short = used[0] if used else "?"
        if requested and used and used[0] != requested[0]:
            self.startup("UYARI", f"model {name}: {requested[0]} istendi ama {short} ile açıldı "
                                  "(sürücü/DLL sorunu olabilir; hız düşer)")
        else:
            self.startup("OK", f"model {name}: {short}")

    # ---- hedef ------------------------------------------------------------------------
    def target_start(self, label: str, t: float | None = None) -> None:
        with self._lock:
            if self._tgt is not None:
                self._end_target("yeni hedef seçildi")
            self._tgt = _Target(label, t)
            if t is not None:
                self._t_now = t
            self._line("HEDEF", f"başladı: {label}")

    def tracked(self, t: float | None = None) -> None:
        with self._lock:
            g = self._tgt
            if g is None:
                return
            g.n_ok += 1
            if t is not None:
                self._t_now = g.t_last = t
            if g.lost_since is not None:
                dur = (t - g.lost_since) if (t is not None) else 0.0
                g.longest = max(g.longest, dur)
                g.lost_since = None
                self._line("HEDEF", f"geri bulundu: {g.label} (kayıp {dur:.1f} sn)")

    def lost(self, t: float | None = None) -> None:
        with self._lock:
            g = self._tgt
            if g is None:
                return
            g.n_lost += 1
            if t is not None:
                self._t_now = g.t_last = t
            if g.lost_since is None:
                g.lost_since = t if t is not None else 0.0
                g.episodes += 1
                self._line("UYARI", f"hedef kayboldu: {g.label}")

    def target_end(self, reason: str) -> None:
        with self._lock:
            self._end_target(reason)

    def _end_target(self, reason: str) -> None:
        g, self._tgt = self._tgt, None
        if g is None:
            return
        total = g.n_ok + g.n_lost
        ratio = (100.0 * g.n_ok / total) if total else 0.0
        if g.lost_since is not None and g.t_last is not None:
            g.longest = max(g.longest, g.t_last - g.lost_since)
        verdict = "OK" if ratio >= 80 else ("UYARI" if ratio >= 50 else "HATA")
        if total == 0:
            verdict = "HATA"
        span = (g.t_last - g.t0) if (g.t0 is not None and g.t_last is not None) else 0.0
        text = (f"bitti: {g.label} | sebep: {reason} | video süresi {span:.1f} sn | izlenen {g.n_ok} kare, "
                f"kayıp {g.n_lost} kare | takip oranı %{ratio:.0f} | kayıp bölüm {g.episodes}, "
                f"en uzun {g.longest:.1f} sn")
        self._line(verdict, "hedef " + text)
        self._targets_done.append(f"{verdict:<5} {g.label}: %{ratio:.0f} takip, {g.episodes} kayıp bölüm")

    # ---- başarım ----------------------------------------------------------------------
    def frame(self, lag_s: float) -> None:
        """Her işlenen kare: gecikme (sn). ~30 sn'de bir PERF satırı."""
        with self._lock:
            self._perf[0] += 1
            self._perf[1] += lag_s
            self._perf[2] = max(self._perf[2], lag_s)
            w = self._pw
            w[0] += 1
            w[1] += lag_s
            now = time.monotonic()
            if now - w[2] >= PERF_EVERY_S and self.path is not None:
                dt = now - w[2]
                self._line("PERF", f"{w[0] / dt:.1f} kare/sn · ortalama gecikme {w[1] / w[0] * 1000:.0f} ms")
                self._pw = [0, 0.0, now]

    # ---- özet -------------------------------------------------------------------------
    def verdict(self, f: _Feat) -> str:
        if f.fail and not f.ok:
            return "ÇALIŞMADI"
        if f.fail:
            return f"KISMEN ({f.fail} hata)"
        if f.ok:
            return "OK"
        return "SONUÇ YOK" if f.idle else "-"

    def _summary_lines(self, reason: str) -> list[str]:
        L = ["", f"---- ÖZET ({self.proc}, {reason}) " + "-" * 40]
        if self._perf[0]:
            L.append(f"İşlenen kare: {self._perf[0]} · ortalama gecikme "
                     f"{self._perf[1] / self._perf[0] * 1000:.0f} ms · en büyük {self._perf[2] * 1000:.0f} ms")
        L.append(f"{'Özellik':<36}{'OK':>8}{'HATA':>8}{'BOŞ':>8}  Durum")
        bad: list[str] = []
        for name, f in self.feat.items():
            v = self.verdict(f)
            L.append(f"{name:<36}{f.ok:>8}{f.fail:>8}{f.idle:>8}  {v}")
            if f.fail:
                L.append(f"    son hata: {f.last_detail}")
                bad.append(name)
        for t in self._targets_done:
            L.append(f"Hedef: {t}")
        for s in self._startup:
            if " HATA " in s or " UYARI " in s:
                L.append("Açılış: " + s.split("] ", 2)[-1])
                bad.append("açılış")
        L.append("SONUÇ: " + ("tüm özellikler çalıştı" if not bad and self.feat
                              else ("sorun var: " + ", ".join(dict.fromkeys(bad)) if bad
                                    else "özellik verisi yok")))
        L.append("-" * 78)
        return L


class _Null:
    """Etkin günlük yok: her çağrı boş."""

    def __getattr__(self, name: str):
        return lambda *a, **k: None


NULL: Any = _Null()
_active: TrackLog | None = None


def activate(tl: TrackLog | None) -> None:
    global _active
    _active = tl


def active() -> Any:
    return _active if _active is not None else NULL


def forward(where: str, exc: BaseException | str | None) -> None:
    """errlog.record köprüsü: her kayıtlı hata etkin video günlüğüne özellik hatası olur."""
    if _active is not None:
        _active.fail(where, exc)


def model_opened(path: Any, requested: list[str], session: Any) -> None:
    if _active is not None:
        try:
            _active.model_opened(path, requested, session)
        except Exception:  # noqa: BLE001, S110
            pass


@contextmanager
def operation(video: str | None, name: str, cfg: Any = None) -> Iterator[TrackLog]:
    """Çevrimdışı tarama / dışa aktarma gibi tek seferlik işlemler için video günlüğü."""
    ver = ""
    try:
        from . import __version__ as ver
    except Exception:  # noqa: BLE001
        pass
    dev = ""
    if cfg is not None:
        try:
            from .gpu import config_text

            dev = config_text(cfg)
        except Exception:  # noqa: BLE001
            dev = ""
    tl = TrackLog(proc=name, version=ver, device_text=dev)
    prev = _active
    activate(tl)
    t0 = time.monotonic()
    if video:
        tl.open_video(video)
        tl.note(f"{name} başladı")
    try:
        yield tl
    except KeyboardInterrupt:
        tl.note("kullanıcı iptal etti", "UYARI")
        raise
    except BaseException as e:
        tl.fail(name, e)
        raise
    finally:
        tl.note(f"{name} bitti ({time.monotonic() - t0:.1f} sn)")
        tl.close_video("işlem bitti")
        activate(prev)


