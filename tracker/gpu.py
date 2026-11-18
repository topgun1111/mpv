"""Ekran kartı (GPU) listesi ve seçimi.

Windows'ta DXGI ile (ctypes; ek paket yok) kartlar sıralanır; sıra DirectML `device_id` ile aynıdır.
DXGI açılmazsa PowerShell `Win32_VideoController` adlarına düşülür. Seçim `Config.device` + `Config.gpu`
olarak saklanır: `auto`, `cpu`, `dml:<dxgi sırası>`, `cuda:<NVIDIA sırası>` (panel kimliği = bu metin).
`detector.set_gpu` seçimi ONNX Runtime sağlayıcı seçeneğine (`device_id`) çevirir.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Any

VENDORS = {0x10DE: "NVIDIA", 0x1002: "AMD", 0x1022: "AMD", 0x8086: "Intel", 0x1414: "Microsoft"}
DML, CUDA = "DmlExecutionProvider", "CUDAExecutionProvider"


@dataclass(frozen=True)
class Adapter:
    index: int  # DXGI sırası (DirectML device_id)
    name: str
    vendor_id: int = 0
    vram_mb: int = 0
    software: bool = False

    @property
    def nvidia(self) -> bool:
        return self.vendor_id == 0x10DE


def _vendor_from_name(name: str) -> int:
    n = name.lower()
    if "nvidia" in n or "geforce" in n or "quadro" in n:
        return 0x10DE
    if "amd" in n or "radeon" in n:
        return 0x1002
    if "intel" in n:
        return 0x8086
    return 0


def _enum_dxgi() -> list[Adapter]:
    """DXGI 1.1 ile kartları say (yalnız Windows). Hata → boş liste."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import (
        POINTER,
        byref,
        c_size_t,
        c_ubyte,
        c_uint,
        c_ulong,
        c_ushort,
        c_void_p,
        c_wchar,
    )

    class GUID(ctypes.Structure):
        _fields_ = [("a", c_ulong), ("b", c_ushort), ("c", c_ushort), ("d", c_ubyte * 8)]

    class LUID(ctypes.Structure):
        _fields_ = [("lo", c_ulong), ("hi", ctypes.c_long)]

    class DESC1(ctypes.Structure):
        _fields_ = [("Description", c_wchar * 128), ("VendorId", c_uint), ("DeviceId", c_uint),
                    ("SubSysId", c_uint), ("Revision", c_uint), ("DedicatedVideoMemory", c_size_t),
                    ("DedicatedSystemMemory", c_size_t), ("SharedSystemMemory", c_size_t),
                    ("AdapterLuid", LUID), ("Flags", c_uint)]

    # IID_IDXGIFactory1 = 770AAE78-F26F-4DBA-A829-253C83D1B387
    iid = GUID(0x770AAE78, 0xF26F, 0x4DBA, (c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))

    def vcall(obj: int, idx: int, argtypes: list, *args: Any) -> int:
        vtbl = ctypes.cast(c_void_p(obj), POINTER(c_void_p))[0]
        fn_addr = ctypes.cast(c_void_p(vtbl), POINTER(c_void_p))[idx]
        fn = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, *argtypes)(fn_addr)
        return fn(obj, *args)

    dxgi = ctypes.WinDLL("dxgi")
    factory = c_void_p()
    if dxgi.CreateDXGIFactory1(byref(iid), byref(factory)) < 0 or not factory.value:
        return []
    out: list[Adapter] = []
    try:
        i = 0
        while i < 16:
            ad = c_void_p()
            if vcall(factory.value, 12, [c_uint, POINTER(c_void_p)], i, byref(ad)) < 0 or not ad.value:
                break  # DXGI_ERROR_NOT_FOUND: liste bitti
            try:
                d = DESC1()
                if vcall(ad.value, 10, [POINTER(DESC1)], byref(d)) >= 0:
                    out.append(Adapter(i, d.Description.strip(), int(d.VendorId),
                                       int(d.DedicatedVideoMemory // (1024 * 1024)),
                                       bool(d.Flags & 2)))
            finally:
                vcall(ad.value, 2, [])  # Release
            i += 1
    finally:
        vcall(factory.value, 2, [])
    return out


def _enum_powershell() -> list[Adapter]:
    if os.name != "nt":
        return []
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
         "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"],
        capture_output=True, text=True, timeout=8, creationflags=flags, encoding="utf-8")
    names = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    return [Adapter(i, n, _vendor_from_name(n)) for i, n in enumerate(names)]


_cache: list[Adapter] | None = None


def adapters(refresh: bool = False) -> list[Adapter]:
    """Kartlar (yazılım/WARP son sırada kalır; indeksler DXGI sırasıdır). Sonuç önbelleğe alınır."""
    global _cache
    if _cache is not None and not refresh:
        return _cache
    found: list[Adapter] = []
    for fn in (_enum_dxgi, _enum_powershell):
        try:
            found = fn()
        except Exception as e:  # noqa: BLE001
            found = []
            try:
                from . import errlog

                errlog.record("ekran kartı tarama (" + fn.__name__ + ")", e)
            except Exception:  # noqa: BLE001, S110
                pass
        if found:
            break
    _cache = found
    return found


@dataclass(frozen=True)
class Choice:
    id: str  # auto | cpu | dml:<i> | cuda:<i>
    label: str
    device: str
    gpu: int


def _label(a: Adapter, suffix: str) -> str:
    vram = f" · {a.vram_mb // 1024} GB" if a.vram_mb >= 1024 else (f" · {a.vram_mb} MB" if a.vram_mb else "")
    return f"{a.name}{vram} · {suffix}"


def choices(available: list[str] | None = None, found: list[Adapter] | None = None) -> list[Choice]:
    """Panel listesi. `available`: ONNX Runtime sağlayıcıları (None: onnxruntime'a sor)."""
    if available is None:
        try:
            import onnxruntime as ort

            available = list(ort.get_available_providers())
        except Exception:  # noqa: BLE001
            available = []
    found = adapters() if found is None else found
    out = [Choice("auto", "Otomatik (en iyi kullanılabilir)", "auto", -1)]
    real = [a for a in found if not a.software]
    nv = 0
    for a in real:
        if DML in available:
            out.append(Choice(f"dml:{a.index}", _label(a, "DirectML"), "dml", a.index))
        if CUDA in available and a.nvidia:
            out.append(Choice(f"cuda:{nv}", _label(a, "CUDA"), "cuda", nv))
        if a.nvidia:
            nv += 1
    if not real:  # kart listesi alınamadı: genel girişler
        if DML in available:
            out.append(Choice("dml:-1", "Varsayılan ekran kartı · DirectML", "dml", -1))
        if CUDA in available:
            out.append(Choice("cuda:0", "NVIDIA (ilk kart) · CUDA", "cuda", 0))
    out.append(Choice("cpu", "İşlemci (CPU) · GPU kullanma", "cpu", -1))
    return out


def current_id(cfg: Any, device: str | None = None) -> str:
    dev = (device or cfg.device or "auto").lower()
    if dev in ("auto", "cpu"):
        return dev
    return f"{dev}:{int(getattr(cfg, 'gpu', -1))}"


def apply_choice(cfg: Any, cid: str, valid: list[Choice] | None = None) -> bool:
    """Seçimi config'e yazar (kayıt/yeniden başlatma çağırana ait). Geçersiz kimlik → False."""
    valid = choices() if valid is None else valid
    c = next((x for x in valid if x.id == cid), None)
    if c is None:
        return False
    cfg.device, cfg.gpu = c.device, c.gpu
    return True


def resolve_startup(cfg: Any, override: str | None = None,
                    valid: list[Choice] | None = None) -> str | None:
    """Açılışta kartı belirler: `override` (--gpu, panel yeniden başlatması) > `cfg.default_gpu` >
    device/gpu. Kart artık yoksa (takıldı/söküldü/sürücü) Otomatik'e düşer; uyarı metni döner."""
    want = override or cfg.default_gpu
    if not want:
        return None
    valid = choices() if valid is None else valid
    if apply_choice(cfg, want, valid):
        return None
    apply_choice(cfg, "auto", valid)
    return f"seçili/varsayılan ekran kartı '{want}' bulunamadı: Otomatik kullanılıyor"


def config_text(cfg: Any, device: str | None = None) -> str:
    """Günlük başlığı için okunur seçim metni."""
    cid = current_id(cfg, device)
    try:
        for c in choices():
            if c.id == cid:
                return f"{c.label} [{cid}]"
    except Exception:  # noqa: BLE001, S110
        pass
    return f"[{cid}]"


def snapshot(cfg: Any) -> dict:
    """Tracker paneli (`track-cfg` JSON): geçerli seçim + liste. Asla hata fırlatmaz: kart listesi
    alınamazsa en azından Otomatik + İşlemci döner (panel «alınamadı» yerine seçim gösterir)."""
    cur = current_id(cfg)
    d = getattr(cfg, "default_gpu", "")
    try:
        found = choices()
    except Exception as e:  # noqa: BLE001
        try:
            from . import errlog

            errlog.record("ekran kartı listesi", e)
        except Exception:  # noqa: BLE001, S110
            pass
        found = [Choice("auto", "Otomatik (en iyi kullanılabilir)", "auto", -1),
                 Choice("cpu", "İşlemci (CPU) · GPU kullanma", "cpu", -1)]
    items = [{"id": c.id, "label": c.label + ("  ★ varsayılan" if c.id == d else "")} for c in found]
    return {"cur": cur, "default": d, "items": items}
