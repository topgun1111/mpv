"""S11: alt vücut kamerası. `.sam.json` kayıtlarından `<video>.views.json` anahtar kareleri üretir (saf Python).

Mevcut kamera yönetmeni (`geometry.compute_view`, `smooth`, `offline._views_from_boxes`) YENİDEN YAZILMAZ; yalnız
alt vücut için şunlar eklenir:

1. Doluluk: birleşik bölge çıktı karesi yüksekliğinin `cfg.lower_fill` (0.70) kadarını kaplar. Genel `target_fill`
   (0.30) DEĞİŞMEZ; yalnız bu modül 0.70 kullanır.
2. Zoom girdisi ham SAM kutusu DEĞİL: duruşa duyarlı kadraj bölgesi (S8 `posture.framing`; yoksa S7 `lower.framing`;
   hiçbiri yoksa SAM'in son TEMİZ boyutu). Zoom yalnız kanıtı sağlam karelerden beslenir: durum TRACKED/REACQUIRED,
   maske masa sayılmamış (`desk`). Yarı örtülü (masa/bacak), kayıp ve aday karelerde zoom ESKİ DEĞERDE kalır → masa
   ya da örtülen bacak zoom'u yakınlaştırmaz.
3. Ayak kıpırtısı, bacak çaprazlama, öne uzanan ayak: (a) zoom hedefi 2 sn'lik pencerede kırpılmış ortalama (üst/alt
   %25 atılır; salınımı ortalar, tek karelik sıçramayı atar, monoton geçişi bozmaz), (b) duruşa bağlı başlatma eşiği
   ve kalıcılık süresi (oturanda geniş eşik, 1.5 sn): küçük ya da geçici sapma zoom'u kıpırdatmaz; kalıcı değişimde
   zoom hedefe oturur, (c) hız sınırı (yakınlaşma yavaş, uzaklaşma 1.5 kat hızlı).
4. Kayıpta bekle: durum makinesinin `hold` bayrağı (S9) kamerayı son görünümde tutar; sonrası mevcut mantık: `lost_zoomout_s`
   içinde 1x'e uzaklaş. Geri dönüşte (çevrimdışı, gelecek bilinir) dönüşten ÖNCE yumuşakça yeni görünüme geçilir.
5. Kamera kimlik takibinden bağımsızdır: yalnız bölge kutusu + durum dizgisi okur; Re-ID/SAM çağırmaz.

Eşikler ilk tahmindir; gerçek klipte ayarlanmadı.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .geometry import View, pan_for_center
from .posture import SEATED, STANDING, TRANSITION, UNKNOWN
from .smooth import DeadZone, ease_view, smooth_zero_phase
from .trackstate import (
    LOST_STATES,
    PARTIALLY_OCCLUDED,
    REACQUIRED,
    TEMPORARILY_LOST,
    TRACKED,
)

Box = tuple[float, float, float, float]

W_FIT = 0.90  # bölge genişliği çıktı genişliğinin en çok bu kadarı (geometry.zoom_for_bbox ile aynı)
TRIM = 0.25  # kırpılmış ortalama: alttan ve üstten atılan pay
SETTLE_Z = 0.01  # hareket, hedefle fark bu kadar (log2, ~%0.7 boyut) kalınca biter: doluluk %70'e oturur
OUT_FACTOR = 1.5  # uzaklaşma hızı = yakınlaşma hızı × bu (kesilen ayağı geri getirmek yakınlaşmaktan güvenli)
DT_MAX = 1.0  # tek adımda hız sınırı için sayılan en uzun süre (kayıp sonrası ilk karede sıçrama olmasın)
NO_REGION_HOLD_S = 1.5  # durum iyi ama bölge yoksa (poz yok) kamera bu kadar tutar
# ölü bölge çarpanı (cfg.lower_zoom_tol ile çarpılır): oturanda ayaklar çok oynar → geniş; geçişte gerçek boyut
# değişir → dar
TOL_MULT = {SEATED: 2.0, STANDING: 1.0, TRANSITION: 0.8, UNKNOWN: 1.2}
# eşik aşıldıktan sonra zoom'un kıpırdaması için hedefin eşiğin ötesinde KESİNTİSİZ kalması gereken süre (sn): ayak/bacak
# hareketi geçicidir, boyut/duruş değişimi kalıcıdır. Geçişte (kalkış/oturuş) hemen.
PERSIST_S = {SEATED: 1.5, STANDING: 0.8, TRANSITION: 0.0, UNKNOWN: 1.0}
ZOOM_STATES = (TRACKED, REACQUIRED)  # zoom bu durumlarda beslenir
PAN_STATES = (TRACKED, PARTIALLY_OCCLUDED, REACQUIRED)  # kaydırma bu durumlarda beslenir
KIND = "sam-lower"  # views.json `target.kind`


@dataclass
class CamFrame:
    """Kamera için bir kare: bölge kutusu (normalize) + duruş + durum. Saf veri; model çağrısı yok."""

    t: float
    box: Box | None = None  # birleşik bölge (kadraj); yoksa None
    posture: str = UNKNOWN
    desk: bool = False  # S8: bu karede maske masa sayıldı
    state: str = TRACKED
    hold: bool = False  # S9: kamera son kırpımı tutmalı


@dataclass
class Camera:
    """`build` çıktısı: anahtar kareler + kare başına görünüm + doluluk ölçüsü."""

    ts: list[float]
    views: list[list[float]]  # [t, zoom, pan_x, pan_y], yinelenenler atılmış
    per_frame: list[View]
    occupancy: list[float | None]  # kare başına bölge yüksekliği / çıktı yüksekliği (yalnız bölgesi olan kareler)
    zoom_ok: list[bool]
    held: int = 0  # kayıpta/boşlukta tutulan ya da uzaklaşılan kare sayısı

    def summary(self) -> str:
        occ = sorted(o for o, ok in zip(self.occupancy, self.zoom_ok, strict=True) if ok and o is not None)
        zs = [v.zoom for v in self.per_frame]
        rate = max((abs(b.zoom - a.zoom) / max(t2 - t1, 1e-6)
                    for a, b, t1, t2 in zip(self.per_frame, self.per_frame[1:], self.ts, self.ts[1:], strict=False)),
                   default=0.0)
        med = f"{occ[len(occ) // 2]:.2f}" if occ else "yok"
        rng = f"{min(zs):.2f}..{max(zs):.2f}" if zs else "yok"
        return (f"kamera: {len(self.ts)} kare · {len(self.views)} anahtar kare · zoom(log2) {rng} · en hızlı değişim "
                f"{rate:.2f}/sn · doluluk (ortanca, zoom kareleri) {med} · tutulan/uzaklaşılan kare {self.held}")


# --- girdi: .sam.json -> CamFrame ---

def _col(block: dict[str, Any] | None, name: str) -> int | None:
    return block["fields"].index(name) if block and name in block.get("fields", []) else None


def frames_from_doc(doc: dict[str, Any], cfg: Config | None = None) -> tuple[list[CamFrame], str]:
    """`.sam.json` belgesi -> (kareler, bölge kaynağı: posture | lower | sam).

    Bölge: `posture` bloğu varsa duruşa duyarlı kadraj, yoksa `lower` kadrajı, yoksa SAM kutusu merkezli son TEMİZ boyut
    (`w`,`h`; kutunun kendi yüksekliği DEĞİL). Durum: `state` bloğu varsa o; yoksa kayıttan türetilir."""
    cfg = cfg or Config()
    recs, names = doc["records"], doc["fields"]
    ix = {n: names.index(n) for n in ("t", "tracked", "accepted", "x1", "y1", "x2", "y2", "clean", "w", "h")}
    post, low, stt = doc.get("posture"), doc.get("lower"), doc.get("state")
    n = len(recs)
    out: list[CamFrame] = []
    lost_since: float | None = None
    src = "sam"
    if post and len(post["rows"]) == n:
        src = "posture"
    elif low and len(low["rows"]) == n:
        src = "lower"
    for i, r in enumerate(recs):
        t = float(r[ix["t"]])
        box: Box | None = None
        posture, desk = UNKNOWN, False
        if src == "posture":
            row = post["rows"][i]
            c = [_col(post, k) for k in ("fx1", "fy1", "fx2", "fy2")]
            vals = [row[k] for k in c]  # type: ignore[index]
            box = None if None in vals else (vals[0], vals[1], vals[2], vals[3])
            posture = row[_col(post, "posture")]  # type: ignore[index]
            desk = bool(row[_col(post, "desk")])  # type: ignore[index]
        elif src == "lower":
            row = low["rows"][i]
            vals = [row[_col(low, k)] for k in ("fx1", "fy1", "fx2", "fy2")]  # type: ignore[index]
            box = None if None in vals else (vals[0], vals[1], vals[2], vals[3])
        elif r[ix["x1"]] is not None and r[ix["w"]] is not None:
            cx, cy = (r[ix["x1"]] + r[ix["x2"]]) / 2, (r[ix["y1"]] + r[ix["y2"]]) / 2
            w, h = r[ix["w"]], r[ix["h"]]
            box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        if stt and len(stt["rows"]) == n:
            row = stt["rows"][i]
            state, hold = row[_col(stt, "state")], bool(row[_col(stt, "hold")])
        else:  # `state` bloğu yok: kayıttan türet (S9 makinesinin yalın hali)
            ok = bool(r[ix["tracked"]]) and bool(r[ix["accepted"]])
            state = (TRACKED if r[ix["clean"]] else PARTIALLY_OCCLUDED) if ok else TEMPORARILY_LOST
            lost_since = None if ok else (t if lost_since is None else lost_since)
            hold = (not ok) and lost_since is not None and t - lost_since <= cfg.lost_hold_s
        out.append(CamFrame(t, box, posture, desk, state, hold))
    return out, src


# --- çekirdek ---

def _trimmed_mean(vals: list[float]) -> float:
    s = sorted(vals)
    k = int(len(s) * TRIM)
    core = s[k: len(s) - k] or s
    return sum(core) / len(core)


def zoom_target(box: Box, fill: float, cfg: Config) -> float:
    """Bölge yüksekliği çıktının `fill` kadarını, genişliği en çok `W_FIT` kadarını kaplasın (log2)."""
    h = max(box[3] - box[1], 1e-6)
    w = max(box[2] - box[0], 1e-6)
    scale = min(fill / h, W_FIT / w)
    return min(max(math.log2(max(scale, 1e-6)), cfg.min_zoom), cfg.max_zoom)


def _runs(idx: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for i in idx:
        if out and out[-1][-1] == i - 1:
            out[-1].append(i)
        else:
            out.append([i])
    return out


def _zoom_path(frames: list[CamFrame], ok: list[bool], cfg: Config) -> list[float | None]:
    """Kanıtlı karelerde: pencere kırpılmış ortalaması -> ölü bölge -> hız sınırı. Diğer karelerde son değer."""
    n = len(frames)
    idx = [i for i in range(n) if ok[i]]
    raw = {i: zoom_target(frames[i].box, cfg.lower_fill, cfg) for i in idx}  # type: ignore[arg-type]
    half = max(cfg.lower_window_s, 0.0) / 2.0
    tz: dict[int, float] = {}
    lo = hi = 0
    for i in idx:
        while frames[idx[lo]].t < frames[i].t - half - 1e-9:
            lo += 1
        while hi + 1 < len(idx) and frames[idx[hi + 1]].t <= frames[i].t + half + 1e-9:
            hi += 1
        tz[i] = _trimmed_mean([raw[j] for j in idx[lo: hi + 1]])
    out: list[float | None] = [None] * n
    z: float | None = None
    moving = False  # Schmitt tetikleyici: eşik kalıcı aşılınca hareket başlar, hedefe OTURANA dek sürer (doluluk %70'te kalır)
    beyond: float | None = None  # hedefin eşiğin ötesinde kalmaya başladığı an
    last_t = 0.0
    for i in range(n):
        if ok[i]:
            tgt = tz[i]
            if z is None:
                z = tgt  # ilk kanıt: tam doluluk
            else:
                dt = min(max(frames[i].t - last_t, 0.0), DT_MAX)
                tol = cfg.lower_zoom_tol * TOL_MULT.get(frames[i].posture, TOL_MULT[UNKNOWN])
                d = tgt - z
                if abs(d) > tol:
                    beyond = frames[i].t if beyond is None else beyond
                    if not moving and frames[i].t - beyond >= PERSIST_S.get(frames[i].posture, PERSIST_S[UNKNOWN]) - 1e-9:
                        moving = True
                else:
                    beyond = None
                if moving and abs(d) <= SETTLE_Z:
                    moving = False
                if moving:
                    rate = cfg.lower_zoom_rate * (1.0 if d > 0 else OUT_FACTOR)
                    z += min(max(d, -rate * dt), rate * dt)
            last_t = frames[i].t
        out[i] = z
    first = next((v for v in out if v is not None), None)
    return [first if v is None else v for v in out] if first is not None else out


def build(frames: list[CamFrame], cfg: Config | None = None) -> Camera:
    """Kare dizisi -> kamera. Zoom ve kaydırma kanıtı ayrı; kayıp boşlukları bekle -> uzaklaş -> önceden yaklaş."""
    cfg = cfg or Config()
    n = len(frames)
    ts = [f.t for f in frames]
    if n == 0:
        return Camera([], [], [], [], [])
    pan_ok = [f.box is not None and f.state in PAN_STATES for f in frames]
    zoom_ok = [pan_ok[i] and frames[i].state in ZOOM_STATES and not frames[i].desk for i in range(n)]
    if not any(zoom_ok):  # hiç temiz kare yok (hep yarı örtülü): kaydırma kanıtı zoom'u da beslesin
        zoom_ok = [p and not f.desk for p, f in zip(pan_ok, frames, strict=True)]
    zoom = _zoom_path(frames, zoom_ok, cfg) if any(zoom_ok) else [None] * n

    views: dict[int, View] = {}
    # kaydırma: kesintisiz kanıt dizilerinde ölü bölge + sıfır-faz yumuşatma (offline._views_from_boxes ile aynı alfa)
    for run in _runs([i for i in range(n) if pan_ok[i] and zoom[i] is not None]):
        dz = [DeadZone(cfg.dead_zone_pos), DeadZone(cfg.dead_zone_pos)]
        cs = [[], []]
        for i in run:
            b = frames[i].box
            assert b is not None
            cs[0].append(dz[0].update((b[0] + b[2]) / 2))
            cs[1].append(dz[1].update((b[1] + b[3]) / 2))
        sm = [smooth_zero_phase(c, cfg.offline_alpha) for c in cs]
        for j, i in enumerate(run):
            z = zoom[i]
            assert z is not None
            px, py = pan_for_center(sm[0][j], sm[1][j], z)
            views[i] = View(z, px, py)

    # boşluklar: bekle (durum makinesinin `hold`'u) -> 1x'e uzaklaş -> dönüşten önce yeni görünüme yaklaş
    held = 0
    last_ev_t: float | None = None
    eff: list[bool] = []
    for i, f in enumerate(frames):
        if i in views:
            last_ev_t = f.t
            eff.append(True)
        else:
            silent = last_ev_t is None or f.t - last_ev_t <= NO_REGION_HOLD_S
            eff.append(f.hold or (f.state not in LOST_STATES and f.state in PAN_STATES and silent))
    dur, reacq = max(cfg.lost_zoomout_s, 0.0), max(cfg.lower_reacq_s, 0.0)
    i = 0
    while i < n:
        if i in views:
            i += 1
            continue
        j = i
        while j < n and j not in views:
            j += 1
        prev = views.get(i - 1) if i > 0 else None  # boşluklar azami uzunlukta: i-1 hep kanıtlı kare
        nxt = views.get(j) if j < n else None
        t_prev = ts[i - 1] if i > 0 else ts[i]
        cur = prev if prev is not None else View()
        base, prog, zooming = cur, 0.0, False
        last_t = t_prev
        gap: list[View] = []
        for k in range(i, j):
            dt = max(ts[k] - last_t, 0.0)
            last_t = ts[k]
            if prev is None:
                v = View()  # hiç görünüm yok (klip başı): 1x
            elif eff[k]:
                v = cur  # tut
            else:
                zooming = True
                prog += dt
                v = ease_view(base, View(), (prog / dur) if dur > 0 else 1.0)
            cur = v
            gap.append(v)
            held += 1
        if nxt is not None:
            ramp = dur if zooming else reacq
            t1 = ts[j]
            ts0 = max(t1 - ramp, t_prev)
            for k in range(i, j):
                if ts[k] >= ts0 and t1 > ts0:
                    gap[k - i] = ease_view(gap[k - i], nxt, (ts[k] - ts0) / (t1 - ts0))
        for k in range(i, j):
            views[k] = gap[k - i]
        i = j

    per_frame = [views[k] for k in range(n)]
    occ = [None if f.box is None else (f.box[3] - f.box[1]) * 2.0 ** per_frame[k].zoom for k, f in enumerate(frames)]
    return Camera(ts, _keyframes(ts, per_frame), per_frame, occ, zoom_ok, held)


def _keyframes(ts: list[float], vs: list[View]) -> list[list[float]]:
    """Sabit duran yinelenen anahtar kareleri at (offline._views_from_boxes adım 4 ile aynı)."""
    keys = [[ts[k], round(vs[k].zoom, 4), round(vs[k].pan_x, 4), round(vs[k].pan_y, 4)] for k in range(len(vs))]
    out = []
    for k, kf in enumerate(keys):
        if 0 < k < len(keys) - 1 and keys[k - 1][1:] == kf[1:] == keys[k + 1][1:]:
            continue
        out.append(kf)
    return out


# --- dosya ---

def views_path_for(sam_json: str | os.PathLike) -> Path:
    """`x.mp4.sam.json` -> `x.mp4.views.json` (Lua `<video>.views.json` arar)."""
    p = Path(sam_json)
    if p.name.endswith(".sam.json"):
        return p.with_name(p.name[: -len(".sam.json")] + ".views.json")
    return p.with_name(p.stem + ".views.json")


def views_from_doc(doc: dict[str, Any], cfg: Config | None = None) -> tuple[Camera, str]:
    frames, src = frames_from_doc(doc, cfg)
    return build(frames, cfg), src


def save_views(doc: dict[str, Any], cam: Camera, path: str | os.PathLike, source: str) -> Path:
    """Lua'nın okuduğu küçük dosya (sürüm 1, `offline.save_views` ile aynı düzen); `target.kind` = `sam-lower`."""
    small: dict[str, Any] = {"version": 1, "video": {"path": doc["video"].get("path", "")},
                             "target": {"kind": KIND, "source": source}, "views": cam.views}
    if doc.get("vsig"):
        small["vsig"] = doc["vsig"]
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(small, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return p
