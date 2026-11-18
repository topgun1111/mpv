"""Canlı ayarlar (Parça 13): mpv tuşlarıyla (track.lua → `track-setting`) anında değişen değerler.

`adjust(cfg, anahtar, yön)` config'i yerinde değiştirir, sınırlara kırpar ve OSD metni döndürür.
yön: +1 / -1 (bir adım), 0 = varsayılana dön. Değerler her karede cfg'den okunur
(`target_fill`, `lookahead_s`); yumuşatıcı katsayıları `LiveController` içinde yeniden kurulur.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .config import Config


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    attrs: tuple[str, ...]  # ilki gösterilen/sınırlanan; mul ise diğerleri aynı oranda ölçeklenir
    step: float  # mul=False: toplanır; mul=True: çarpan (yön üssü)
    lo: float
    hi: float
    mul: bool
    fmt: Callable[[float], str]


SETTINGS: dict[str, Setting] = {s.key: s for s in (
    Setting("fill", "Doluluk (hedef kareyi ne kadar doldurur)", ("target_fill",),
            0.05, 0.10, 0.80, False, lambda v: f"%{v * 100:.0f}"),
    Setting("speed", "Tepki hızı (yüksek = hızlı takip, düşük = akıcı)",
            ("alpha_pos", "alpha_zoom"), 1.25, 0.03, 0.60, True, lambda v: f"{v:.2f}"),
    Setting("lead", "Öngörü (hız yönünde ileri bakış)", ("lookahead_s",),
            0.05, 0.0, 0.60, False, lambda v: f"{v:.2f} sn"),
)}


# Tracker paneli (L tuşu / «Tracker» sekmesi) ek ayarları. SETTINGS (Ctrl+ tuşları) ayrı kalır.
# Hepsi canlı okunur: kayıp/zoom-out/hafıza anında, nokta kutusu + eşik bir sonraki seçimde.
EXTRA: dict[str, Setting] = {s.key: s for s in (
    Setting("hold", "Kayıp bekleme", ("lost_hold_s",), 0.25, 0.0, 5.0, False,
            lambda v: f"{v:.2f} sn"),
    Setting("zoomout", "Zoom-out süresi", ("lost_zoomout_s",), 0.5, 0.0, 6.0, False,
            lambda v: f"{v:.1f} sn"),
    Setting("memory", "Kare dışı hafıza", ("kp_hold_s",), 0.5, 0.0, 5.0, False,
            lambda v: f"{v:.1f} sn"),
    Setting("pbox", "Nokta kutusu", ("point_box",), 0.01, 0.02, 0.20, False,
            lambda v: f"%{v * 100:.0f}"),
    Setting("pscore", "Nokta hassasiyeti", ("point_min_score",), 0.05, 0.20, 0.90, False,
            lambda v: f"{v:.2f}"),
    Setting("kpconf", "Eklem güveni", ("kp_min_conf",), 0.05, 0.10, 0.80, False,
            lambda v: f"{v:.2f}"),
)}

# Açma/kapama seçenekleri: anahtar -> etiket
FLAGS: dict[str, str] = {
    "kp_world": "Kamera telafili eklem",
    "kp_filter": "Eklem süzgeci (titreme azaltır)",
    "kp_robust": "Sağlam parça kutusu",
    "kp_reacq_single": "Tek kişiyse yeniden bağla",
    "cut_detect": "Çekim kesmesi algıla",
}


def _show(cfg: Config, s: Setting) -> str:
    return f"{s.label.split(' (')[0]}: {s.fmt(getattr(cfg, s.attrs[0]))}"


def reset_all(cfg: Config) -> str:
    d = Config(ipc_path=cfg.ipc_path)
    for s in (*SETTINGS.values(), *EXTRA.values()):
        for a in s.attrs:
            setattr(cfg, a, getattr(d, a))
    for k in FLAGS:
        setattr(cfg, k, getattr(d, k))
    return "Ayarlar varsayılana döndü"


def adjust(cfg: Config, key: str, direction: int) -> str | None:
    """Ayarı değiştir; OSD metni döndür (bilinmeyen anahtar → None)."""
    if key == "all" and direction == 0:
        return reset_all(cfg)
    s = SETTINGS.get(key) or EXTRA.get(key)
    if s is None:
        return None
    cur = getattr(cfg, s.attrs[0])
    if direction == 0:
        d = Config(ipc_path=cfg.ipc_path)
        for a in s.attrs:
            setattr(cfg, a, getattr(d, a))
        return _show(cfg, s) + " (varsayılan)"
    new = cur * s.step ** direction if s.mul else cur + s.step * direction
    new = round(min(max(new, s.lo), s.hi), 4)
    if new == round(cur, 4):
        return _show(cfg, s) + (" (üst sınır)" if direction > 0 else " (alt sınır)")
    if s.mul and cur > 0:
        f = new / cur
        for a in s.attrs[1:]:
            setattr(cfg, a, min(round(getattr(cfg, a) * f, 4), 1.0))
    setattr(cfg, s.attrs[0], new)
    return _show(cfg, s)


def status_text(cfg: Config, target_id: int | None, point: bool = False) -> str:
    """Tüm canlı ayarlar + hedef (`h` tuşu). point: sağ tıkla seçilen nesne izleniyor."""
    parts = [_show(cfg, s) for s in SETTINGS.values()]
    if point:
        parts.append("Hedef: nesne (sağ tık noktası)")
    else:
        parts.append("Hedef: " + ("yok" if target_id is None else f"ID {target_id}"))
    return "\n".join(parts)


def toggle_flag(cfg: Config, key: str) -> str | None:
    """Açma/kapama seçeneğini çevir (bilinmeyen anahtar → None)."""
    if key not in FLAGS:
        return None
    new = not bool(getattr(cfg, key))
    setattr(cfg, key, new)
    return f"{FLAGS[key]}: {'açık' if new else 'kapalı'}"


def panel_snapshot(cfg: Config) -> dict:
    """Tracker paneli için ayar özeti: sayısal → [değer, alt, üst, metin]; seçenekler → bool."""
    out: dict = {}
    for k, s in (*SETTINGS.items(), *EXTRA.items()):
        v = getattr(cfg, s.attrs[0])
        out[k] = [round(v, 4), s.lo, s.hi, s.fmt(v)]
    out["flags"] = {k: bool(getattr(cfg, k)) for k in FLAGS}
    try:  # ekran kartı listesi (panel «Ekran kartı» bölümü); alınamazsa bölüm «—» gösterir
        from . import gpu

        out["gpu"] = gpu.snapshot(cfg)
    except Exception:  # noqa: BLE001, S110
        pass
    return out
