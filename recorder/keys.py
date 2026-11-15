"""Kayıt anahtar kareleri, oynatma hızı ve `<video>.rec.json` dosyası.

Anahtarlar videonun KENDİ saatine (time-pos) yazılır; önizleme hızı (0.25×–2×) kaydı etkilemez,
dışa aktarma hep özgün hızdadır (Android `RecordScreen` ile aynı kural).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

REC_VERSION = 1
SPEED_MIN, SPEED_MAX = 0.25, 2.0
SPEED_PRESETS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0)
ROTATIONS = (0, 90, 180, 270)
REC_SUFFIX = ".rec.json"


def clamp_speed(speed: float) -> float:
    """[0.25, 2.0] aralığına ve 0.05 adıma yuvarlar (kayan nokta kırıntısı kalmaz)."""
    if speed != speed:  # NaN
        return 1.0
    r = round(min(max(speed, SPEED_MIN), SPEED_MAX) * 20.0) / 20.0
    return min(max(r, SPEED_MIN), SPEED_MAX)


def key_dt(speed: float) -> float:
    """Kayıt örnekleme aralığı (video sn): ~33 ms duvar saati × hız, [12 ms, 66 ms]."""
    return min(max(0.033 * clamp_speed(speed), 0.012), 0.066)


def append_key(keys: list[list[float]], t: float, view: tuple[float, float, float],
               min_dt: float = 0.03) -> list[list[float]]:
    """Anahtar ekler; zaman en az `min_dt` ilerlemediyse (geri sarma/duraklatma) eklemez."""
    if keys and t < keys[-1][0] + min_dt:
        return keys
    return keys + [[float(t), float(view[0]), float(view[1]), float(view[2])]]


def normalize_keys(keys: list[list[float]]) -> list[list[float]]:
    """Dışa aktarma için: zamana göre sıralı, aynı zamanlı olanlardan sonuncusu kalır;
    tek anahtar varsa 40 ms sonrasına kopyalanır (Android ile aynı)."""
    out: list[list[float]] = []
    for k in sorted(keys, key=lambda k: k[0]):
        row = [float(k[0]), float(k[1]), float(k[2]), float(k[3])]
        if out and row[0] == out[-1][0]:
            out[-1] = row
        else:
            out.append(row)
    if len(out) == 1:
        out.append([out[0][0] + 0.04, *out[0][1:]])
    return out


def file_sig(path: str | os.PathLike) -> str:
    """Video kimliği (ana varyantın `cache.file_sig`'i ile aynı): yol + boyut + mtime."""
    p = os.path.abspath(path)
    try:
        st = os.stat(p)
        raw = f"{os.path.normcase(p)}|{st.st_size}|{st.st_mtime_ns}"
    except OSError:
        raw = os.path.normcase(p)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def rec_path(video: str | os.PathLike) -> str:
    return f"{video}{REC_SUFFIX}"


def default_out(video: str | os.PathLike) -> str:
    p = Path(video)
    return str(p.with_name(p.stem + ".kamera.mp4"))


def save_recording(path: str | os.PathLike, video: str, keys: list[list[float]], *,
                   rotate: int = 0, speed: float = 1.0) -> None:
    """Kaydı atomik yazar (tmp + replace). Anahtar yoksa ValueError."""
    keys = normalize_keys(keys)
    if not keys:
        raise ValueError("kayıtta kamera hareketi yok")
    if rotate not in ROTATIONS:
        raise ValueError(f"geçersiz döndürme: {rotate}")
    doc = {"version": REC_VERSION, "kind": "manual-camera", "video": os.path.basename(video),
           "vsig": file_sig(video), "rotate": rotate, "speed": clamp_speed(speed), "views": keys}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    os.replace(tmp, p)


def load_recording(path: str | os.PathLike, video: str | None = None) -> dict:
    """Kaydı doğrular, döndürür ({views, rotate, speed, ...}); `video` verilirse imzayı denetler."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(d, dict) or d.get("version") != REC_VERSION:
        raise ValueError(f"{path}: desteklenmeyen kayıt sürümü")
    rows = d.get("views") or []
    keys: list[list[float]] = []
    for r in rows:
        nums = isinstance(r, list) and all(isinstance(x, (int, float)) for x in r)
        if not (nums and len(r) == 4):
            raise ValueError(f"{path}: bozuk anahtar kare: {r!r}")
        keys.append([float(x) for x in r])
    if not keys:
        raise ValueError(f"{path}: kamera anahtar karesi yok (önce kayıt yap)")
    if video is not None and d.get("vsig") not in (None, file_sig(video)):
        raise ValueError(f"{path}: bu kayıt başka bir videoya (ya da değişmiş dosyaya) ait")
    rot = d.get("rotate", 0)
    d["rotate"] = rot if rot in ROTATIONS else 0
    d["views"] = normalize_keys(keys)
    return d
