"""Ayarlar (JSON ile yüklenip kaydedilebilir)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def default_ipc_path() -> str:
    return r"\\.\pipe\mpv" if os.name == "nt" else "/tmp/mpv.sock"


@dataclass
class Config:
    ipc_path: str = ""
    target_fill: float = 0.30
    min_zoom: float = 0.0
    max_zoom: float = 2.5
    alpha_pos: float = 0.15
    alpha_zoom: float = 0.08
    dead_zone_pos: float = 0.01
    dead_zone_zoom: float = 0.05
    model_path: str = "models/yolov8n.onnx"
    det_conf: float = 0.25
    det_iou: float = 0.45
    det_size: int = 640
    device: str = "auto"  # auto | dml | cuda | cpu
    live_det_conf: float = 0.1  # canlı mod: ByteTrack düşük skor aşaması için (low_thr ile aynı)
    live_fps: float = 10.0  # canlı mod en fazla işleme hızı (screenshot-raw IPC'de ağır)
    pick_tol: float = 0.03  # kutu dışı tıklama toleransı (kare yüksekliği oranı)
    seek_jump: float = 2.0  # sn; time-pos bundan fazla ileri atlarsa / geri giderse atlama sayılır
    lookahead_s: float = 0.15  # sn; hedef merkezi hız yönünde bu kadar ileri alınır (0: kapalı)
    max_lead: float = 0.15  # lookahead'in kare genişliği/yüksekliği oranında üst sınırı
    kf_accel: float = 0.5  # hedef Kalman süreç gürültüsü: ivme std (kare boyutu/sn²)
    kf_meas: float = 0.01  # hedef Kalman ölçüm gürültüsü std (kare boyutu oranı)

    def __post_init__(self) -> None:
        if not self.ipc_path:
            self.ipc_path = default_ipc_path()

    @classmethod
    def load(cls, path: str | Path) -> Config:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
