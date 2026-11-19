"""S3: PC EdgeTAM motoru, yalnız ilk kare: dikdörtgen -> ilk maske (Android `SamEngine.kt` portu).

Akış: görüntü (RGB, ImageNet ort/std, 1024x1024) -> `sam-encoder` -> `sam-decoder` (3 aday maske)
-> en iyi aday -> maske, kare-uzayı kutusu, skorlar, `obj_ptr`.

Kararlar (docs/DECISIONS.md "SAM engine"):
- Yeniden boyutlama SIKIŞTIRMALIDIR (letterbox yok): SAM 2 ve Android `chw()` görüntüyü en-boy oranını
  bozarak 1024x1024'e çeker. Bu yüzden koordinatlar [0, 1] normalize uzayında taşınır ve kareye `w`, `h`
  ile ölçeklenir; geri çevirmek için pad/offset yoktur.
- Dikdörtgen istemi = iki köşe (etiket 2 ve 3) + kutunun merkezinde bir pozitif nokta (etiket 1),
  Android `prompt3` ile aynı. Kullanılmayan yuva etiketi -1'dir.
- Aday seçimi: dikdörtgen için en yüksek `iou_predictions` ("best"). Android'in dokunma kuralı
  ("smallest": en iyiye yakın olanların en küçüğü) isteğe bağlı olarak durur.

S4: bellek grafikleri (`sam-decoder-trk`, `sam-memenc`, `sam-memattn`) isteğe bağlı yüklenir (`memory=True`);
motor yalnız TEK grafik çağrısı yapar (`memorize`, `condition`, `decode_track`). Video döngüsü, banka ve kayıtlar
`tracker/sam_track.py`'dedir. Kapı (TrackGate), arayüz ve zoom YOK.
`onnxruntime` yalnız oturum açılırken (tembel) içe aktarılır; testler sahte oturum verir.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .detector import resolve_model_path
from .sam_bench import open_session

S = 1024  # girdi kenarı; `point_coords` bu uzaydadır
M = 256  # düşük çözünürlüklü maske kenarı
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
ENC, DEC = "sam-encoder", "sam-decoder"
DEC_TRK, MEMENC, MEMATTN = "sam-decoder-trk", "sam-memenc", "sam-memattn"
MEMORY_GRAPHS = (DEC_TRK, MEMENC, MEMATTN)
ENC_OUT = ("high_res_feats_0", "high_res_feats_1", "image_embed", "image_feat")
DEC_OUT = ("low_res_masks", "iou_predictions", "obj_ptrs", "object_score")
LABEL_POS, LABEL_BOX_1, LABEL_BOX_2, LABEL_NONE = 1.0, 2.0, 3.0, -1.0
MIN_RECT_PX = 2.0  # bundan küçük kenarlı dikdörtgen istem sayılmaz
BEST_RATIO = 0.85  # "smallest" kuralı: en iyi iou'nun bu oranı ve üstü

Rect = tuple[float, float, float, float]
SessionFactory = Callable[[Path, str], tuple[Any, list[str]]]


# --- ön işleme ---

def preprocess(frame_bgr: np.ndarray) -> np.ndarray:
    """BGR uint8 HxWx3 -> [1, 3, 1024, 1024] float32 (RGB, ImageNet ort/std; sıkıştırmalı yeniden boyut)."""
    import cv2

    if frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
        raise ValueError(f"BGR kare bekleniyor (H, W, 3), gelen: {frame_bgr.shape}")
    img = cv2.resize(frame_bgr, (S, S), interpolation=cv2.INTER_LINEAR)
    rgb = img[:, :, ::-1].astype(np.float32) / 255.0
    rgb = (rgb - np.asarray(MEAN, np.float32)) / np.asarray(STD, np.float32)
    return np.ascontiguousarray(rgb.transpose(2, 0, 1)[None], dtype=np.float32)


# --- istem (dikdörtgen) ---

def clamp_rect(rect: Rect, w: int, h: int) -> Rect:
    """Piksel dikdörtgenini sıralar ve kareye kırpar; çok küçükse ValueError."""
    x1, y1, x2, y2 = (float(v) for v in rect)
    if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
        raise ValueError("dikdörtgen sayıları sonlu olmalı")
    x1, x2 = sorted((min(max(x1, 0.0), w), min(max(x2, 0.0), w)))
    y1, y2 = sorted((min(max(y1, 0.0), h), min(max(y2, 0.0), h)))
    if x2 - x1 < MIN_RECT_PX or y2 - y1 < MIN_RECT_PX:
        raise ValueError(f"dikdörtgen çok küçük ya da kare dışında: {x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f}")
    return x1, y1, x2, y2


def box_prompt(rect: Rect, w: int, h: int) -> tuple[np.ndarray, np.ndarray]:
    """`sam-decoder` istemi: coords [1, 3, 2] (1024 px), labels [1, 3] = köşe 2, köşe 3, merkez nokta 1."""
    x1, y1, x2, y2 = clamp_rect(rect, w, h)
    sx, sy = S / w, S / h
    coords = np.array([[[x1 * sx, y1 * sy], [x2 * sx, y2 * sy], [(x1 + x2) / 2 * sx, (y1 + y2) / 2 * sy]]],
                      np.float32)
    labels = np.array([[LABEL_BOX_1, LABEL_BOX_2, LABEL_POS]], np.float32)
    return coords, labels


def parse_rect(text: str, w: int, h: int, normalized: bool = False) -> Rect:
    """`x1,y1,x2,y2` -> piksel dikdörtgeni (`normalized`: değerler 0-1 oranı)."""
    parts = text.replace(" ", "").split(",")
    if len(parts) != 4:
        raise ValueError("dikdörtgen `x1,y1,x2,y2` biçiminde olmalı")
    try:
        v = [float(p) for p in parts]
    except ValueError as e:
        raise ValueError("dikdörtgen sayılardan oluşmalı") from e
    if normalized:
        v = [v[0] * w, v[1] * h, v[2] * w, v[3] * h]
    return clamp_rect((v[0], v[1], v[2], v[3]), w, h)


# --- aday maskeler ---

@dataclass(frozen=True)
class Candidate:
    index: int
    iou: float  # decoder'ın tahmin ettiği IoU
    area: float  # maske alanı / (M*M); 0 = boş maske
    box: tuple[float, float, float, float] | None  # normalize (x1, y1, x2, y2); boş maskede None
    centroid: tuple[float, float] | None  # normalize (cx, cy)


def analyse(logits: np.ndarray, index: int, iou: float) -> Candidate:
    """Tek aday maskenin (M, M logit; > 0 = nesne) alanı, normalize kutusu ve ağırlık merkezi (Kotlin `analyse`)."""
    ys, xs = np.nonzero(logits > 0)
    if xs.size == 0:
        return Candidate(index, float(iou), 0.0, None, None)
    box = (float(xs.min()) / M, float(ys.min()) / M, float(xs.max() + 1) / M, float(ys.max() + 1) / M)
    return Candidate(index, float(iou), xs.size / (M * M), box, (float(xs.mean()) / M, float(ys.mean()) / M))


def pick_candidate(cands: list[Candidate], rule: str = "best") -> int:
    """Seçilen adayın sırası; hepsi boşsa -1.

    best: en yüksek iou. smallest (Android dokunma kuralı): iou'su en iyinin %85'i ve üstü olanların en küçüğü.
    """
    if rule not in ("best", "smallest"):
        raise ValueError(f"bilinmeyen aday kuralı '{rule}' (best, smallest)")
    valid = [c for c in cands if c.area > 0]
    if not valid:
        return -1
    top = max(c.iou for c in valid)
    if rule == "best":
        return max(valid, key=lambda c: c.iou).index
    return min((c for c in valid if c.iou >= BEST_RATIO * top), key=lambda c: c.area).index


# --- koordinatlar ---

def to_frame_box(box_norm: tuple[float, float, float, float], w: int, h: int) -> Rect:
    """Normalize kutuyu kare pikseline çevirir (sıkıştırmalı yeniden boyut: yalnız ölçek)."""
    x1, y1, x2, y2 = box_norm
    return x1 * w, y1 * h, x2 * w, y2 * h


def to_norm_box(box_px: Rect, w: int, h: int) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = box_px
    return x1 / w, y1 / h, x2 / w, y2 / h


def upscale_mask(logits: np.ndarray, w: int, h: int) -> np.ndarray:
    """(M, M) logit -> (h, w) bool: logitler çift doğrusal büyütülür, sonra > 0 (SAM 2 son işleme)."""
    import cv2

    return cv2.resize(logits.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR) > 0


# --- sonuç ---

@dataclass
class Encoded:
    """Bir karenin encoder çıktıları; aynı kareye birden çok istem için bir kez hesaplanır."""

    hr0: np.ndarray
    hr1: np.ndarray
    embed: np.ndarray  # `sam-decoder` girdisi (ilk kare: bellek yok)
    feat: np.ndarray  # ham öznitelik: S4'te `sam-memenc` girdisi
    size: tuple[int, int]  # kare (w, h)


@dataclass
class FirstMask:
    mask_logits: np.ndarray  # (M, M) seçilen adayın logitleri; S4'te `sam-memenc` girdisi
    mask: np.ndarray  # (M, M) bool
    box_norm: tuple[float, float, float, float]
    box: Rect  # kare pikseli
    iou: float  # seçilen adayın `iou_predictions` değeri
    object_score: float  # logit; > 0 = nesne var
    obj_ptr: np.ndarray  # (256,)
    index: int
    candidates: tuple[Candidate, ...]
    rect: Rect  # istemde kullanılan (kırpılmış) dikdörtgen, piksel
    size: tuple[int, int]
    image_feat: np.ndarray = field(repr=False)  # S4 için taşınır; bu oturumda kullanılmaz

    @property
    def object_prob(self) -> float:
        return 1.0 / (1.0 + math.exp(-max(min(self.object_score, 60.0), -60.0)))


@dataclass
class TrackedMask:
    """`sam-decoder-trk` sonucu (bellek koşullu, istemsiz tek maske)."""

    mask_logits: np.ndarray  # (M, M); `sam-memenc` girdisi
    cand: Candidate  # alan, normalize kutu, ağırlık merkezi
    iou: float
    object_score: float  # logit; > 0 = nesne var
    obj_ptr: np.ndarray  # (256,)


@dataclass(frozen=True)
class MemoryLayout:
    """`sam-memattn` statik girdileri: K bellek yuvası, P işaretçi yuvası, bir yuvanın şekli."""

    k: int
    p: int
    frame_shape: tuple[int, ...]  # mem_feats = [K, *frame_shape]

    @property
    def frame_size(self) -> int:
        return int(np.prod(self.frame_shape, dtype=np.int64))


def input_shape(session: Any, name: str) -> tuple[int, ...]:
    """Oturumun statik girdi şekli; dinamik/bilinmeyen boyutta RuntimeError (grafikler statik dışa aktarılır)."""
    for inp in session.get_inputs():
        if inp.name == name:
            shape = tuple(inp.shape or ())
            if not shape or not all(isinstance(d, int) and d > 0 for d in shape):
                raise RuntimeError(f"'{name}' girdisinin şekli statik değil: {shape}")
            return shape
    raise RuntimeError(f"oturumda '{name}' girdisi yok")


# --- motor ---

class SamEngine:
    """`sam-encoder` + `sam-decoder` ile ilk kare; `memory=True` ile bellek grafikleri de (S4).

    `sessions` verilirse model dosyası aranmaz (testler); bellek grafikleri sözlükte varsa kullanılır.
    """

    def __init__(self, model_dir: str | Path | None = None, device: str = "auto", *,
                 sessions: dict[str, Any] | None = None, factory: SessionFactory | None = None,
                 rule: str = "best", memory: bool = False) -> None:
        pick_candidate([], rule)  # kuralı erken doğrula
        self.rule = rule
        self.device = device
        self.requested: dict[str, list[str]] = {}
        self.timing: dict[str, list[float]] = {}  # grafik -> [toplam ms, çağrı sayısı]
        if sessions is not None:
            names = (ENC, DEC) + tuple(n for n in MEMORY_GRAPHS if n in sessions)
            self._s = {n: sessions[n] for n in names}
            return
        if model_dir is None:
            raise ValueError("model_dir ya da sessions gerekli")
        d = resolve_model_path(model_dir)
        if not d.is_dir():
            raise FileNotFoundError(f"model klasörü yok: {d}")
        need = (ENC, DEC) + (MEMORY_GRAPHS if memory else ())
        missing = [f"{n}.onnx" for n in need if not (d / f"{n}.onnx").is_file()]
        if missing:
            raise FileNotFoundError(f"{d} içinde yok: {', '.join(missing)} (bkz. docs/DECISIONS.md \"SAM graphs\")")
        make: SessionFactory = factory or (lambda p, dev: open_session(p, dev))
        self._s = {}
        for n in need:
            self._s[n], self.requested[n] = make(d / f"{n}.onnx", device)

    @property
    def has_memory(self) -> bool:
        return all(n in self._s for n in MEMORY_GRAPHS)

    def _run(self, name: str, feed: dict[str, np.ndarray], out_names: tuple[str, ...]) -> list[Any]:
        """Grafik çağrısı + süre sayacı (`timing`); çıktı sayısı denetlenir."""
        t0 = time.perf_counter()
        outs = self._s[name].run(list(out_names), feed)
        acc = self.timing.setdefault(name, [0.0, 0.0])
        acc[0] += (time.perf_counter() - t0) * 1000
        acc[1] += 1
        if len(outs) != len(out_names):
            raise RuntimeError(f"{name}: {len(out_names)} çıktı beklenirdi, {len(outs)} geldi")
        return outs

    def providers(self) -> dict[str, dict[str, Any]]:
        """Grafik başına gerçekte kullanılan sağlayıcı ve istenenden düşüldü mü."""
        out: dict[str, dict[str, Any]] = {}
        for n, s in self._s.items():
            used = list(s.get_providers()) if hasattr(s, "get_providers") else []
            want = self.requested.get(n) or []
            out[n] = {"provider": used[0] if used else "?",
                      "fell_back": bool(used and want and used[0] != want[0])}
        return out

    def encode(self, frame_bgr: np.ndarray) -> Encoded:
        h, w = frame_bgr.shape[:2]
        outs = self._run(ENC, {"image": preprocess(frame_bgr)}, ENC_OUT)
        o = {n: np.asarray(a, np.float32) for n, a in zip(ENC_OUT, outs)}
        return Encoded(o["high_res_feats_0"], o["high_res_feats_1"], o["image_embed"], o["image_feat"], (w, h))

    def segment_rect(self, enc: Encoded, rect: Rect) -> FirstMask | None:
        """Dikdörtgen isteminden ilk maske; hiçbir aday nesne bulamazsa None (kullanıcı yeniden çizer)."""
        w, h = enc.size
        clipped = clamp_rect(rect, w, h)
        coords, labels = box_prompt(clipped, w, h)
        outs = self._run(DEC, {
            "image_embed": enc.embed, "high_res_feats_0": enc.hr0, "high_res_feats_1": enc.hr1,
            "point_coords": coords, "point_labels": labels}, DEC_OUT)
        masks, iou, ptrs, score = (np.asarray(a, np.float32) for a in outs)
        if masks.ndim != 4 or masks.shape[2:] != (M, M):
            raise RuntimeError(f"{DEC}: beklenmeyen maske boyutu {tuple(masks.shape)} (beklenen [1, N, {M}, {M}])")
        masks, iou, ptrs = masks[0], iou.reshape(-1), ptrs[0]
        if not (masks.shape[0] == iou.size == ptrs.shape[0]):
            raise RuntimeError(f"{DEC}: aday sayıları uyuşmuyor ({masks.shape[0]}, {iou.size}, {ptrs.shape[0]})")
        cands = [analyse(masks[k], k, float(iou[k])) for k in range(masks.shape[0])]
        best = pick_candidate(cands, self.rule)
        if best < 0:
            return None
        c = cands[best]
        assert c.box is not None
        return FirstMask(
            mask_logits=masks[best].copy(), mask=masks[best] > 0, box_norm=c.box,
            box=to_frame_box(c.box, w, h), iou=c.iou, object_score=float(score.reshape(-1)[0]),
            obj_ptr=ptrs[best].copy(), index=best, candidates=tuple(cands), rect=clipped, size=(w, h),
            image_feat=enc.feat)

    def first_mask(self, frame_bgr: np.ndarray, rect: Rect) -> FirstMask | None:
        """Tek çağrıda encoder + decoder."""
        return self.segment_rect(self.encode(frame_bgr), rect)

    # --- S4: bellek grafikleri (her biri tek çağrı; döngü ve banka sam_track.py'de) ---

    def _need_memory(self) -> None:
        if not self.has_memory:
            miss = [f"{n}.onnx" for n in MEMORY_GRAPHS if n not in self._s]
            raise RuntimeError(f"bellek grafikleri yüklü değil ({', '.join(miss)}): SamEngine(..., memory=True)")

    def memory_layout(self) -> MemoryLayout:
        """`sam-memattn` girdilerinden K, P ve yuva şekli (Kotlin `memShape`/`ptrs` okuması)."""
        self._need_memory()
        s = self._s[MEMATTN]
        mem = input_shape(s, "mem_feats")
        ptr = input_shape(s, "ptrs")
        if len(mem) < 2 or len(ptr) != 2 or ptr[1] != 256:
            raise RuntimeError(f"{MEMATTN}: beklenmeyen girdi şekilleri mem_feats={mem}, ptrs={ptr}")
        return MemoryLayout(k=mem[0], p=ptr[0], frame_shape=mem[1:])

    def memorize(self, feat: np.ndarray, mask_logits: np.ndarray, object_score: float) -> np.ndarray:
        """`sam-memenc`: bir karenin maskesini bellek özniteliğine çevirir -> (1, *frame_shape)."""
        self._need_memory()
        outs = self._run(MEMENC, {
            "image_feat": feat,
            "low_res_mask": np.ascontiguousarray(mask_logits, np.float32).reshape(1, 1, M, M),
            "object_score": np.array([[object_score]], np.float32)}, ("mem_feat",))
        out = np.asarray(outs[0], np.float32)
        lay = self.memory_layout()
        if out.size != lay.frame_size:
            raise RuntimeError(f"{MEMENC}: bellek karesi {out.size} sayı, {MEMATTN} {lay.frame_size} bekliyor")
        return out.reshape(1, *lay.frame_shape)

    def condition(self, feat: np.ndarray, mem_feats: np.ndarray, ptrs: np.ndarray) -> np.ndarray:
        """`sam-memattn`: kare özniteliğini bellekle koşullar -> `image_embed` [1, 256, 64, 64]."""
        self._need_memory()
        outs = self._run(MEMATTN, {"image_feat": feat, "mem_feats": mem_feats, "ptrs": ptrs}, ("image_embed",))
        return np.asarray(outs[0], np.float32)

    def decode_track(self, enc: Encoded, embed: np.ndarray) -> TrackedMask:
        """`sam-decoder-trk`: istemsiz (etiket -1) tek maske; `embed` bellek koşullu gömme."""
        self._need_memory()
        outs = self._run(DEC_TRK, {
            "image_embed": embed, "high_res_feats_0": enc.hr0, "high_res_feats_1": enc.hr1,
            "point_coords": np.zeros((1, 1, 2), np.float32),
            "point_labels": np.full((1, 1), LABEL_NONE, np.float32)}, DEC_OUT)
        masks, iou, ptrs, score = (np.asarray(a, np.float32) for a in outs)
        if masks.ndim != 4 or masks.shape[1] != 1 or masks.shape[2:] != (M, M):
            raise RuntimeError(f"{DEC_TRK}: beklenmeyen maske boyutu {tuple(masks.shape)} (beklenen [1, 1, {M}, {M}])")
        logits = masks[0, 0].copy()
        return TrackedMask(mask_logits=logits, cand=analyse(logits, 0, float(iou.reshape(-1)[0])),
                           iou=float(iou.reshape(-1)[0]), object_score=float(score.reshape(-1)[0]),
                           obj_ptr=ptrs.reshape(-1, ptrs.shape[-1])[0].copy())


# --- görüntü yardımcıları (CLI) ---

def read_image(path: str | Path) -> np.ndarray:
    """BGR uint8; Türkçe/Unicode yollarda da çalışır (`cv2.imread` Windows'ta bunlarda başarısız olur)."""
    import cv2

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"görüntü yok: {p}")
    img = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"görüntü okunamadı: {p}")
    return img


def draw_overlay(frame_bgr: np.ndarray, res: FirstMask) -> np.ndarray:
    """Kare üstüne: maske konturu (yeşil), maske kutusu (camgöbeği), çizilen dikdörtgen (sarı)."""
    import cv2

    h, w = frame_bgr.shape[:2]
    out = frame_bgr.copy()
    cnts, _ = cv2.findContours(upscale_mask(res.mask_logits, w, h).astype(np.uint8), cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    t = max(2, round(max(w, h) / 400))
    cv2.drawContours(out, cnts, -1, (0, 255, 0), t)

    def rect(r: Rect, color: tuple[int, int, int], th: int) -> None:
        cv2.rectangle(out, (round(r[0]), round(r[1])), (round(r[2]), round(r[3])), color, th)

    rect(res.box, (255, 255, 0), 1)
    rect(res.rect, (0, 255, 255), 1)
    return out


def save_png(path: str | Path, img_bgr: np.ndarray) -> None:
    """PNG yazar (Unicode yollarda da çalışır)."""
    import cv2

    ok, buf = cv2.imencode(".png", img_bgr)
    if not ok:
        raise ValueError("PNG kodlanamadı")
    Path(path).write_bytes(buf.tobytes())


def format_result(res: FirstMask, providers: dict[str, dict[str, Any]], ms: dict[str, float]) -> str:
    L = []
    for n in (ENC, DEC):
        p = providers.get(n, {})
        L.append(f"{n}: {p.get('provider', '?')}{' (FELL BACK)' if p.get('fell_back') else ''} · "
                 f"{ms.get(n, 0.0):.1f} ms")
    L.append("adaylar: " + " | ".join(
        f"#{c.index} iou {c.iou:.3f} alan {c.area * 100:.1f}%" + (" (seçildi)" if c.index == res.index else "")
        for c in res.candidates))
    x1, y1, x2, y2 = res.box
    L.append(f"maske kutusu (piksel): {x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f} · iou {res.iou:.3f} · "
             f"object_score {res.object_score:.2f} (p={res.object_prob:.2f})")
    return "\n".join(L)
