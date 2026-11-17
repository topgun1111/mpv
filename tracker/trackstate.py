"""S9: izleme durum makinesi (7 durum). Saf Python; model/GPU/IO yok.

`TrackStateMachine.update(rec)` her `sam_track.TrackRecord` için bir `StateFrame` üretir:

  TRACKED                   temiz kare: maske güvenli, boyut normal
  PARTIALLY_OCCLUDED        izleniyor ama kare temiz değil (maske oranı düşük/yüksek ya da güven düşük): masa/bacak/
                            başka nesne örtüyor. Kamera boyutu son temiz boyutta kalır (`trackgate.size`)
  TEMPORARILY_LOST          kare izlenmedi (maske yok / güven düşük / `TrackGate` reddetti) ve özne kenara gitmiyordu
  OUT_OF_FRAME              kare izlenmedi ve son görünen kutu kenara değiyordu VE kenara doğru gidiyordu (ya da
                            küçülüyordu): özne kare dışına çıkıyor
  REACQUISITION_CANDIDATE   kayıptan sonra ilk izlenen kare(ler): henüz doğrulanmadı, kamera eski kırpımda bekler
  REACQUIRED                aday `confirm_frames` kare üst üste izlendi: özne geri geldi (S10 burada Re-ID ile doğrular)
  MANUAL_RESELECT_REQUIRED  kayıp çok uzadı: kullanıcının hedefi yeniden seçmesi gerekir (`reset()` ile çıkılır; kayıp
                            sürerken bir izlenen kare yine de aday olur)

Geçişler `ALLOWED` tablosunda; testler rastgele kare dizilerinde yalnız bu geçişlerin görüldüğünü doğrular.

Girdiler (yeni sinyal üretilmez, hazır olanlar kullanılır):
  - `rec.tracked` / `rec.accepted` / `rec.clean` / `rec.ratio`: S4/S5 (maske oranı, `TrackGate` sonucu);
  - `rec.box`: kutunun kareye göre konumu (kenara değme + son kareler boyunca kenara doğru hareket/küçülme);
  - `legs_left` (isteğe bağlı): S8 her iki bacak `left_frame` ise True; kutu kenara değiyorsa çıkış sayılır.

Kutu YALNIZ kenara değiyor diye çıkış sayılmaz: oturan kişinin alt vücut kutusu kare altına dayalı kalabilir (kadraj bacağı
keser) ve masa arkasındaki kayıp bir çıkış değildir. Kenara doğru gidiş ya da kenarda küçülme gerekir.

Son güvenilir kimlik bilgisi (`anchor`: son temiz karenin kutusu, boyutu, zamanı) ve önceki kamera kırpımı (`StateFrame.crop`)
kayıp, aday ve doğrulama boyunca korunur. `hold`: kamera son kırpımı tutmalı (kayıp `hold_s` = `cfg.lost_hold_s` içinde ya da
aday doğrulanana dek); sonrası mevcut zoom-out mantığına bırakılır (S11).
`lost_s`: şimdiye dek süren yokluk; aday/REACQUIRED karelerinde az önce biten yokluğun uzunluğu (S10 için).

Süre/eşik sabitleri ilk tahmindir, gerçek klipte ayarlanmadı.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Any

from . import trackgate

TRACKED = "TRACKED"
PARTIALLY_OCCLUDED = "PARTIALLY_OCCLUDED"
TEMPORARILY_LOST = "TEMPORARILY_LOST"
OUT_OF_FRAME = "OUT_OF_FRAME"
REACQUISITION_CANDIDATE = "REACQUISITION_CANDIDATE"
REACQUIRED = "REACQUIRED"
MANUAL_RESELECT_REQUIRED = "MANUAL_RESELECT_REQUIRED"
STATES = (TRACKED, PARTIALLY_OCCLUDED, TEMPORARILY_LOST, OUT_OF_FRAME, REACQUISITION_CANDIDATE, REACQUIRED,
          MANUAL_RESELECT_REQUIRED)

LOST_STATES = (TEMPORARILY_LOST, OUT_OF_FRAME, MANUAL_RESELECT_REQUIRED)

# Kendine dönüş her zaman serbest. Başlangıç: ilk kare herhangi bir duruma girebilir (TRACKED/PARTIAL/TEMPORARILY_LOST).
ALLOWED: dict[str, frozenset[str]] = {
    TRACKED: frozenset({PARTIALLY_OCCLUDED, TEMPORARILY_LOST, OUT_OF_FRAME}),
    PARTIALLY_OCCLUDED: frozenset({TRACKED, TEMPORARILY_LOST, OUT_OF_FRAME}),
    # kısa kayıp (<= hold_s) doğrudan sürer; uzun kayıp aday olur; süre dolarsa elle seçim
    TEMPORARILY_LOST: frozenset({TRACKED, PARTIALLY_OCCLUDED, REACQUISITION_CANDIDATE, MANUAL_RESELECT_REQUIRED}),
    # kare dışından dönüş her zaman aday + doğrulama (hemen sürmez)
    OUT_OF_FRAME: frozenset({REACQUISITION_CANDIDATE, MANUAL_RESELECT_REQUIRED}),
    # aday bir kayıp karede eski kayıp durumuna (ya da süre dolduysa MANUAL'a) döner
    REACQUISITION_CANDIDATE: frozenset({REACQUIRED, TEMPORARILY_LOST, OUT_OF_FRAME, MANUAL_RESELECT_REQUIRED}),
    REACQUIRED: frozenset({TRACKED, PARTIALLY_OCCLUDED, TEMPORARILY_LOST, OUT_OF_FRAME}),
    MANUAL_RESELECT_REQUIRED: frozenset({REACQUISITION_CANDIDATE}),
}

# Maske oranı/temizlik: `trackgate.PARTIAL_RATIO` (0.6) ve `remember` aralığı kullanılır; yeni sabit yok.
PARTIAL_FRAMES = 2  # temiz olmayan kare üst üste bu kadar olunca PARTIALLY_OCCLUDED (oran < PARTIAL_RATIO ise hemen)
CLEAN_FRAMES = 2  # PARTIALLY_OCCLUDED'dan TRACKED'a dönmek için üst üste temiz kare
CONFIRM_FRAMES = 3  # aday -> REACQUIRED için üst üste izlenen kare (örnekleme hızında; varsayılan 10/sn ≈ 0.3 sn)
SETTLE_FRAMES = 3  # REACQUIRED durumunda kalınan kare sayısı
MANUAL_LOST_S = 8.0  # TEMPORARILY_LOST bu kadar sürerse elle seçim (TrackGate benzerlik eşiği ~3.6 sn'de tamamen gevşer)
OUT_MAX_S = 30.0  # kare dışındaki öznenin geri dönmesi için beklenen en uzun süre
EDGE_MARGIN = 0.03  # kutu kenara bu kadar (karenin oranı) yakınsa "kenara değiyor"
EXIT_LOOKBACK = 6  # çıkış kararı için bakılan son izlenen kare sayısı
EXIT_MOVE = 0.03  # kenara doğru merkez kayması (karenin oranı), LOOKBACK boyunca
EXIT_SHRINK = 0.85  # kenara değen kutunun genişliği/yüksekliği LOOKBACK başına göre bu orana inmişse çıkış

EDGES = ("left", "right", "top", "bottom")
Box = tuple[float, float, float, float]

ROW_FIELDS = ("t", "state", "reason", "lost_s", "edge", "hold", "cx1", "cy1", "cx2", "cy2")


def touching(box: Box, margin: float = EDGE_MARGIN) -> tuple[str, ...]:
    """Normalize kutunun değdiği kare kenarları (left/right/top/bottom)."""
    x1, y1, x2, y2 = box
    out = []
    if x1 <= margin:
        out.append("left")
    if x2 >= 1.0 - margin:
        out.append("right")
    if y1 <= margin:
        out.append("top")
    if y2 >= 1.0 - margin:
        out.append("bottom")
    return tuple(out)


@dataclass(frozen=True)
class Anchor:
    """Son güvenilir (temiz) izlenen kare: kayıp/aday boyunca korunan kimlik ve kırpım bilgisi. S10 Re-ID bunu kullanır."""

    index: int
    t: float
    box: Box
    size: tuple[float, float]  # kamera için normalize (w, h): son temiz boyut
    conf: float
    ratio: float


@dataclass
class StateFrame:
    index: int
    t: float
    state: str
    prev: str | None  # önceki karenin durumu (ilk karede None)
    reason: str  # kısa kod: ok, start, blip, low_ratio, big_ratio, low_conf, recovering, no_mask, gate, exit_<kenar>,
    #              timeout, resumed, back, confirmed, settling
    lost_s: float = 0.0
    edge: str | None = None  # OUT_OF_FRAME: çıkılan kenar; aday/REACQUIRED: kutunun değdiği kenar (giriş kenarı)
    hold: bool = False  # kamera son kırpımı tutmalı
    crop: Box | None = None  # son güvenilir kare kutusu (önceki kamera kırpımının dayanağı); hiç temiz kare yoksa None

    @property
    def changed(self) -> bool:
        return self.prev is not None and self.prev != self.state

    @property
    def lost(self) -> bool:
        return self.state in LOST_STATES

    def to_dict(self) -> dict[str, Any]:
        """Önizleme dosyasındaki `track` bloğu."""
        return {"state": self.state, "prev": self.prev, "reason": self.reason, "lost_s": round(self.lost_s, 2),
                "edge": self.edge, "hold": self.hold,
                "crop": None if self.crop is None else [round(v, 4) for v in self.crop]}

    def row(self) -> list[Any]:
        """`.sam.json` `state.rows` satırı (alan sırası `ROW_FIELDS`)."""
        c = self.crop or (None,) * 4
        return [round(self.t, 4), self.state, self.reason, round(self.lost_s, 2), self.edge, int(self.hold),
                *[None if v is None else round(v, 4) for v in c]]


class TrackStateMachine:
    """Kare kare durum izleyici. `update` her kayıt için tam bir kez, zaman sırasıyla çağrılır."""

    def __init__(self, hold_s: float = 1.0, *, manual_s: float = MANUAL_LOST_S, out_max_s: float = OUT_MAX_S,
                 confirm_frames: int = CONFIRM_FRAMES, settle_frames: int = SETTLE_FRAMES,
                 partial_frames: int = PARTIAL_FRAMES, clean_frames: int = CLEAN_FRAMES) -> None:
        self.hold_s = max(hold_s, 0.0)
        self.manual_s, self.out_max_s = manual_s, out_max_s
        self.confirm_frames, self.settle_frames = max(confirm_frames, 1), max(settle_frames, 0)
        self.partial_frames, self.clean_frames = max(partial_frames, 1), max(clean_frames, 1)
        self.state: str | None = None
        self.anchor: Anchor | None = None
        self.counts: Counter[str] = Counter()
        self.transitions: list[tuple[float, str | None, str, str]] = []  # (t, önceki, yeni, neden)
        self._hist: deque[tuple[float, Box]] = deque(maxlen=EXIT_LOOKBACK)  # son izlenen kareler (t, kutu)
        self._lost_since = 0.0
        self._lost_state: str = TEMPORARILY_LOST  # aday olmadan önceki kayıp durumu
        self._exit_edge: str | None = None
        self._gap = 0.0  # az önce biten yokluk (aday/REACQUIRED karelerinde lost_s)
        self._cand = self._settle = self._un = self._cl = 0

    # --- dış API ---

    def reset(self, t: float = 0.0) -> None:
        """Kullanıcı hedefi (yeniden) seçti: kayıp unutulur, durum TRACKED'a döner, eski kimlik/kırpım atılır."""
        if self.state != TRACKED:
            self.transitions.append((float(t), self.state, TRACKED, "reset"))
        self.state = TRACKED
        self.anchor = None
        self._hist.clear()
        self._exit_edge = None
        self._gap = 0.0
        self._cand = self._settle = self._un = self._cl = 0

    def update(self, rec: Any, *, legs_left: bool = False) -> StateFrame:
        """`rec`: `sam_track.TrackRecord` (t, index, tracked, accepted, clean, ratio, conf, box, size)."""
        t = float(rec.t)
        prev = self.state
        seen = bool(rec.tracked and rec.box is not None)
        if seen:
            new, reason = self._on_seen(rec, t, prev)
        else:
            new, reason = self._on_lost(rec, t, prev, legs_left)
        self.state = new
        frame = self._frame(rec, t, prev, new, reason, seen)
        self.counts[new] += 1
        if prev != new:
            self.transitions.append((t, prev, new, reason))
        return frame

    def summary(self) -> str:
        parts = [f"{s} {self.counts[s]}" for s in STATES if self.counts[s]]
        return "durum: " + (", ".join(parts) if parts else "kare yok") + f" · geçiş {max(len(self.transitions) - 1, 0)}"

    # --- geçişler ---

    def _on_seen(self, rec: Any, t: float, prev: str | None) -> tuple[str, str]:
        box = tuple(rec.box)
        self._hist.append((t, box))
        if rec.clean:
            size = tuple(rec.size) if rec.size else (box[2] - box[0], box[3] - box[1])
            self.anchor = Anchor(rec.index, t, box, size, float(rec.conf), float(rec.ratio))
            self._cl, self._un = self._cl + 1, 0
        else:
            self._un, self._cl = self._un + 1, 0
        if prev in LOST_STATES:
            gap = t - self._lost_since
            if prev == TEMPORARILY_LOST and gap <= self.hold_s:
                return self._base(rec, TRACKED, "resumed")  # kamera kırpımı tuttu; kimlik şüphesi yok
            self._lost_state, self._gap, self._cand = prev, gap, 1
            return REACQUISITION_CANDIDATE, "back"
        if prev == REACQUISITION_CANDIDATE:
            self._cand += 1
            if self._cand >= self.confirm_frames:
                self._settle = 0
                return REACQUIRED, "confirmed"
            return REACQUISITION_CANDIDATE, "back"
        if prev == REACQUIRED:
            self._settle += 1
            if self._settle < self.settle_frames:
                return REACQUIRED, "settling"
        return self._base(rec, prev, "start" if prev is None else "ok")

    def _base(self, rec: Any, prev: str | None, ok: str) -> tuple[str, str]:
        """TRACKED <-> PARTIALLY_OCCLUDED, titremesin diye iki yönde de kare sayısıyla."""
        strong = rec.ratio < trackgate.PARTIAL_RATIO  # gate'in "kısmen örtülü" eşiği: hemen
        why = self._why(rec)
        if prev == PARTIALLY_OCCLUDED:
            if self._cl >= self.clean_frames:
                return TRACKED, ok
            return PARTIALLY_OCCLUDED, why if not rec.clean else "recovering"
        if not rec.clean and (strong or self._un >= self.partial_frames):
            return PARTIALLY_OCCLUDED, why
        return TRACKED, "blip" if (not rec.clean and ok == "ok") else ok  # blip: tek temiz olmayan kare, durum değişmez

    @staticmethod
    def _why(rec: Any) -> str:
        if rec.ratio < trackgate.PARTIAL_RATIO:
            return "low_ratio"
        if rec.ratio > trackgate.REMEMBER_MAX_RATIO:
            return "big_ratio"
        return "low_conf"

    def _on_lost(self, rec: Any, t: float, prev: str | None, legs_left: bool) -> tuple[str, str]:
        self._un = self._cl = 0
        why = "no_mask" if rec.accepted else "gate"  # gate: bir maske var ama özneye benzemiyor (ör. masa)
        if prev in (None, TRACKED, PARTIALLY_OCCLUDED, REACQUIRED):
            self._lost_since = t
            self._exit_edge = self._detect_exit(legs_left)
            new, reason = (OUT_OF_FRAME, f"exit_{self._exit_edge}") if self._exit_edge else (TEMPORARILY_LOST, why)
        elif prev == REACQUISITION_CANDIDATE:
            new, reason = self._lost_state, why  # aday tutmadı: eski kayıp sürüyor (yokluk süresi kesilmedi)
        else:
            new, reason = prev, why
        if new in (TEMPORARILY_LOST, OUT_OF_FRAME):
            if t - self._lost_since >= (self.out_max_s if new == OUT_OF_FRAME else self.manual_s):
                new, reason = MANUAL_RESELECT_REQUIRED, "timeout"
        return new, reason

    def _detect_exit(self, legs_left: bool) -> str | None:
        """Son izlenen kutu kenara değiyor VE o kenara doğru gidiyor/küçülüyor mu? Yalnız değmek yetmez."""
        if not self._hist:
            return None
        edges = touching(self._hist[-1][1])
        if not edges:
            return None
        if legs_left:
            return edges[0]
        first, last = self._hist[0][1], self._hist[-1][1]
        fw, fh = first[2] - first[0], first[3] - first[1]
        lw, lh = last[2] - last[0], last[3] - last[1]
        dx = (last[0] + last[2] - first[0] - first[2]) / 2  # merkez kayması
        dy = (last[1] + last[3] - first[1] - first[3]) / 2
        for e in edges:
            moved = {"left": -dx, "right": dx, "top": -dy, "bottom": dy}[e]
            shrunk = (lw <= EXIT_SHRINK * fw) if e in ("left", "right") else (lh <= EXIT_SHRINK * fh)
            if len(self._hist) > 1 and (moved >= EXIT_MOVE or shrunk):
                return e
        return None

    # --- çıktı ---

    def _frame(self, rec: Any, t: float, prev: str | None, new: str, reason: str, seen: bool) -> StateFrame:
        if new in LOST_STATES:
            lost_s = t - self._lost_since
        elif new in (REACQUISITION_CANDIDATE, REACQUIRED):
            lost_s = self._gap
        else:
            lost_s = 0.0
        edge = None
        if new == OUT_OF_FRAME:
            edge = self._exit_edge
        elif new in (REACQUISITION_CANDIDATE, REACQUIRED) and seen:
            e = touching(tuple(rec.box))
            edge = e[0] if e else None
        hold = (new in (TEMPORARILY_LOST, OUT_OF_FRAME) and lost_s <= self.hold_s) or new == REACQUISITION_CANDIDATE
        return StateFrame(index=int(rec.index), t=t, state=new, prev=prev, reason=reason, lost_s=lost_s, edge=edge,
                          hold=hold, crop=self.anchor.box if self.anchor else None)
