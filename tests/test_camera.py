"""S11: alt vücut kamerası (camera.py). Saf Python; model, GPU ve gerçek video gerekmez.

Sentetik bölge dizileri: 10 kare/sn, bölge normalize kutu. Oturan kişi: x .30-.60, y .45-.95 (yükseklik .50).
"""
import ast
import json
import math
from pathlib import Path

import pytest
from test_posture import _FakePoseEstimator
from test_sam_track import GOOD, _cli

from tracker import camera as cam
from tracker import posture as pm
from tracker import sam_track as st
from tracker import trackstate as ts
from tracker.camera import CamFrame
from tracker.config import Config
from tracker.main import main

FPS = 10.0
SEATED_BOX = (0.30, 0.45, 0.60, 0.95)
T, PART, TL, OUT, CAND, RE, MAN = (ts.TRACKED, ts.PARTIALLY_OCCLUDED, ts.TEMPORARILY_LOST, ts.OUT_OF_FRAME,
                                   ts.REACQUISITION_CANDIDATE, ts.REACQUIRED, ts.MANUAL_RESELECT_REQUIRED)


def frames(n, fn, t0=0.0):
    """fn(i, t) -> CamFrame alanları (box, posture, state, hold, desk) sözlüğü ya da yalnız box."""
    out = []
    for i in range(n):
        t = t0 + i / FPS
        r = fn(i, t)
        kw = r if isinstance(r, dict) else {"box": r}
        out.append(CamFrame(t, **kw))
    return out


def seated(box=SEATED_BOX, **kw):
    return {"box": box, "posture": pm.SEATED, **kw}


def zoom_span(c, lo=0, hi=None):
    zs = [v.zoom for v in c.per_frame[lo:hi]]
    return max(zs) - min(zs)


def max_rate(c):
    return max(abs(b.zoom - a.zoom) / (t2 - t1) for a, b, t1, t2 in zip(c.per_frame, c.per_frame[1:], c.ts, c.ts[1:]))


def resize(box, h_scale=1.0, w_scale=1.0, bottom=None):
    """Üst kenar sabit; yüksekliği/genişliği ölçekle (merkez x sabit). `bottom`: alt kenarı doğrudan ver."""
    x1, y1, x2, y2 = box
    cx, w = (x1 + x2) / 2, (x2 - x1) * w_scale
    y2n = y1 + (y2 - y1) * h_scale if bottom is None else bottom
    return (cx - w / 2, y1, cx + w / 2, y2n)


# --- doluluk ---

def test_defaults_lower_fill_is_70_percent_and_global_target_fill_unchanged():
    c = Config()
    assert c.lower_fill == 0.70 and c.target_fill == 0.30  # genel varsayılan DEĞİŞMEDİ


def test_static_region_fills_70_percent_of_output_height():
    c = cam.build(frames(60, lambda i, t: seated()))
    assert all(o == pytest.approx(0.70, abs=0.005) for o in c.occupancy)
    assert zoom_span(c) < 1e-6  # kıpırdamayan bölge: zoom sabit


def test_fill_is_configurable_and_width_always_fits():
    c = cam.build(frames(30, lambda i, t: seated()), Config(lower_fill=0.5))
    assert all(o == pytest.approx(0.50, abs=0.005) for o in c.occupancy)
    wide = (0.05, 0.45, 0.95, 0.95)  # yükseklik .5 ama genişlik .9 -> 0.70/0.5 zoom'u sığmaz; genişlik sınırlar
    c = cam.build(frames(30, lambda i, t: seated(wide)))
    z = c.per_frame[0].zoom
    assert 0.9 * 2 ** z <= 0.9 + 1e-6 and c.occupancy[0] < 0.70


def test_pan_never_shows_border():
    c = cam.build(frames(40, lambda i, t: seated((0.0, 0.5, 0.3, 1.0))))
    for v in c.per_frame:
        lim = 0.5 - 0.5 / 2 ** v.zoom
        assert abs(v.pan_x) <= lim + 1e-9 and abs(v.pan_y) <= lim + 1e-9


# --- ayak kıpırtısı, çaprazlama, uzanan ayak: zoom değişmez ---

def test_foot_wiggle_does_not_pump_zoom():
    def fn(i, t):
        d = 0.04 * math.sin(2 * math.pi * 1.5 * t)  # alt kenar ±.04 (bölge yüksekliğinin %8'i), 1.5 Hz
        return seated(resize(SEATED_BOX, bottom=SEATED_BOX[3] + d))
    c = cam.build(frames(150, fn))
    assert zoom_span(c) < 0.03


def test_one_frame_foot_spike_is_ignored():
    def fn(i, t):
        return seated(resize(SEATED_BOX, bottom=1.0 if i == 40 else SEATED_BOX[3]))
    c = cam.build(frames(100, fn))
    assert zoom_span(c) < 1e-6


def test_leg_cross_keeps_zoom_inside_tolerance():
    def fn(i, t):  # 3-5.5 sn: bacaklar çapraz -> alt kenar %12 yukarı, genişlik %30 dar
        crossed = 3.0 <= t < 5.5
        return seated(resize(SEATED_BOX, h_scale=0.88, w_scale=0.7) if crossed else SEATED_BOX)
    c = cam.build(frames(100, fn))
    assert zoom_span(c) < 0.05


def test_extended_foot_keeps_zoom_inside_tolerance():
    def fn(i, t):  # 2-5 sn: bir ayak öne uzanır -> alt kenar bölge yüksekliğinin %15'i kadar iner
        ext = 2.0 <= t < 5.0
        return seated(resize(SEATED_BOX, h_scale=1.15) if ext else SEATED_BOX)
    c = cam.build(frames(100, fn))
    assert zoom_span(c) < 0.05


def test_large_but_short_foot_excursion_is_ignored_while_persistent_change_is_not():
    """1 sn'lik büyük sapma (eşiğin çok ötesi) geçicidir; kalıcılık süresini dolduramaz."""
    c = cam.build(frames(100, lambda i, t: seated(resize(SEATED_BOX, h_scale=1.4) if 4.0 <= t < 5.0 else SEATED_BOX)))
    assert zoom_span(c) < 0.05


def test_persistence_alone_rejects_a_transient_excursion():
    """Pencere süzgeci kapalı (lower_window_s=0): geçici sapmayı yalnız kalıcılık süresi bastırır."""
    cfg = Config(lower_window_s=0.0)
    c = cam.build(frames(100, lambda i, t: seated(resize(SEATED_BOX, h_scale=1.4) if 4.0 <= t < 5.0 else SEATED_BOX)), cfg)
    assert zoom_span(c) < 1e-6
    c = cam.build(frames(100, lambda i, t: seated(resize(SEATED_BOX, h_scale=1.4) if t >= 4.0 else SEATED_BOX)), cfg)
    assert zoom_span(c) > 0.3  # aynı sapma kalıcıysa zoom izler


def test_trimmed_window_alone_rejects_a_short_spike():
    """Geçiş duruşunda kalıcılık süresi 0: 0.4 sn'lik dev sıçramayı yalnız kırpılmış ortalama bastırır."""
    def fn(i, t):
        spike = 4.0 <= t < 4.4
        return {"box": resize(SEATED_BOX, h_scale=0.3 if spike else 1.0), "posture": pm.TRANSITION}
    c = cam.build(frames(100, fn))
    assert zoom_span(c) < 1e-6


def test_real_size_change_is_followed_but_rate_limited():
    """Ölü bölge kamerayı dondurmaz: özne gerçekten yaklaşırsa (yükseklik 2x) zoom uzaklaşır, hız sınırıyla."""
    cfg = Config()
    c = cam.build(frames(200, lambda i, t: seated(resize(SEATED_BOX, h_scale=0.5) if t >= 5 else SEATED_BOX)))
    z0, z1 = c.per_frame[0].zoom, c.per_frame[-1].zoom
    assert z1 - z0 > 0.95 and c.occupancy[-1] == pytest.approx(0.70, abs=0.01)  # ~1 log2 değişim izlendi, doluluk %70'e oturdu
    assert max_rate(c) <= cfg.lower_zoom_rate * cam.OUT_FACTOR + 1e-6


# --- otur / kalk ---

def _sit_stand(t):
    """0-4 sn oturur, 4-6 sn kalkar (geçiş), 6-10 sn ayakta, 10-12 sn oturur."""
    seated_h, stand_h = 0.50, 0.80
    if t < 4:
        h, p = seated_h, pm.SEATED
    elif t < 6:
        k = (t - 4) / 2
        h, p = seated_h + (stand_h - seated_h) * k, pm.TRANSITION
    elif t < 10:
        h, p = stand_h, pm.STANDING
    elif t < 12:
        k = (t - 10) / 2
        h, p = stand_h + (seated_h - stand_h) * k, pm.TRANSITION
    else:
        h, p = seated_h, pm.SEATED
    return {"box": (0.35, 0.10, 0.55, 0.10 + h), "posture": p}


def test_stand_up_and_sit_down_follow_smoothly_and_return():
    cfg = Config()
    c = cam.build(frames(160, lambda i, t: _sit_stand(t)), cfg)
    assert max_rate(c) <= cfg.lower_zoom_rate * cam.OUT_FACTOR + 1e-6  # kalkarken de hız sınırı geçerli
    z_seat, z_stand = c.per_frame[10].zoom, c.per_frame[90].zoom
    assert z_stand < z_seat - 0.2  # ayakta bölge büyük -> uzaklaşıldı
    assert c.per_frame[-1].zoom == pytest.approx(z_seat, abs=0.02)  # tekrar oturunca aynı doluluğa döner
    ups = [b.zoom - a.zoom for a, b in zip(c.per_frame, c.per_frame[1:])]
    assert max(ups[:60]) <= 1e-9  # kalkış sırasında yakınlaşma yok (geri geri oynamaz)


def test_foot_wiggle_while_standing_still_stable():
    def fn(i, t):
        d = 0.05 * math.sin(2 * math.pi * 2.0 * t)
        return {"box": (0.35, 0.10, 0.55, 0.90 + d), "posture": pm.STANDING}
    c = cam.build(frames(100, fn))
    assert zoom_span(c) < 0.05


# --- masa / kısmi oklüzyon: zoom yakınlaşmaz ---

def test_desk_flagged_frames_never_zoom_in():
    def fn(i, t):  # 3-6 sn maske masa sayıldı ve bölge küçüldü (masa arkası kırpıldı)
        if 3 <= t < 6:
            return seated((0.40, 0.70, 0.50, 0.80), desk=True)
        return seated()
    c = cam.build(frames(100, fn))
    assert zoom_span(c) < 1e-6  # masa karelerinde zoom eski değerde


def test_partially_occluded_frames_hold_zoom_but_pan_follows():
    def fn(i, t):
        if 3 <= t < 6:  # masa/bacak örtüyor: küçük ve sağa kaymış bölge
            return seated((0.62, 0.70, 0.72, 0.80), state=PART)
        return seated()
    c = cam.build(frames(100, fn))
    assert zoom_span(c) < 1e-6
    assert c.per_frame[45].pan_x < c.per_frame[10].pan_x - 0.01  # kaydırma yine de takip etti (sağa -> pan azalır)


def test_tiny_region_is_capped_by_max_zoom():
    c = cam.build(frames(30, lambda i, t: seated((0.5, 0.5, 0.52, 0.52))), Config(max_zoom=1.5))
    assert max(v.zoom for v in c.per_frame) <= 1.5 + 1e-9


# --- kayıpta bekle, uzaklaş, yumuşak dön ---

def _lost_then_back(lost_state, hold_until, gap=(4.0, 6.0), back_box=SEATED_BOX, n=200):
    def fn(i, t):
        if gap[0] <= t < gap[1]:
            return {"box": None, "state": lost_state, "hold": (t - gap[0]) < hold_until, "posture": pm.UNKNOWN}
        return seated(SEATED_BOX if t < gap[0] else back_box)
    return frames(n, fn)


def test_short_occlusion_holds_framing_then_returns_without_pumping():
    c = cam.build(_lost_then_back(TL, hold_until=9.0, gap=(4.0, 4.8)))
    zs = [v.zoom for v in c.per_frame]
    assert max(zs) - min(zs) < 1e-6  # tutma: uzaklaşma yok, zoom sabit
    assert max_rate(c) < 1e-6


def test_long_loss_holds_then_zooms_out_then_eases_back_in():
    cfg = Config()
    c = cam.build(_lost_then_back(OUT, hold_until=cfg.lost_hold_s, gap=(4.0, 12.0), n=240), cfg)
    z_in = c.per_frame[10].zoom
    i_hold = int((4.0 + 0.5) * FPS)  # tutma süresi içinde
    assert c.per_frame[i_hold].zoom == pytest.approx(z_in, abs=1e-6)
    i_late = int(9.0 * FPS)  # uzaklaşma bitti, dönüş ön-yaklaşması başlamadı
    assert c.per_frame[i_late].zoom == pytest.approx(0.0, abs=1e-6)  # 1x
    assert c.per_frame[-1].zoom == pytest.approx(z_in, abs=1e-6)  # geri geldi
    # dönüşe doğru tek karede büyük sıçrama yok
    assert max_rate(c) < 1.0


def test_reacquisition_pan_moves_smoothly_not_in_one_frame():
    back = (0.55, 0.45, 0.85, 0.95)  # özne kayıptan sonra .25 sağda döner
    c = cam.build(_lost_then_back(TL, hold_until=9.0, gap=(4.0, 6.0), back_box=back))
    pans = [v.pan_x for v in c.per_frame]
    total = abs(pans[-1] - pans[10])
    assert total > 0.05
    steps = [abs(b - a) for a, b in zip(pans, pans[1:])]
    assert max(steps) < 0.5 * total  # geçiş kareler arasına yayıldı


def test_candidate_state_holds_until_confirmed():
    def fn(i, t):
        if 4 <= t < 5:
            return {"box": None, "state": TL, "hold": True}
        if 5 <= t < 7:  # aday: kamera eski kırpımda bekler (hold), bölge henüz güvenilmez
            return {"box": (0.60, 0.45, 0.90, 0.95), "state": CAND, "hold": True}
        return seated()
    c = cam.build(frames(120, fn))
    assert zoom_span(c) < 1e-6
    pans = [v.pan_x for v in c.per_frame]
    assert abs(pans[int(6.0 * FPS)] - pans[10]) < 0.02  # aday karelerinde kaydırma da eski yerde (aday kanıt sayılmaz)


def test_manual_reselect_zooms_out():
    c = cam.build(_lost_then_back(MAN, hold_until=0.0, gap=(2.0, 20.0), n=200))
    assert c.per_frame[150].zoom == pytest.approx(0.0, abs=1e-6)


def test_missing_region_with_good_state_holds_briefly_then_zooms_out():
    def fn(i, t):  # poz modeli sustu: durum TRACKED ama bölge yok
        return {"box": None} if t >= 3 else seated()
    c = cam.build(frames(150, fn))
    z_in = c.per_frame[0].zoom
    assert c.per_frame[int(4.0 * FPS)].zoom == pytest.approx(z_in, abs=1e-6)  # NO_REGION_HOLD_S içinde
    assert c.per_frame[-1].zoom == pytest.approx(0.0, abs=1e-6)  # sonra uzaklaşılır


def test_start_without_evidence_eases_in_from_1x_and_empty_input():
    def fn(i, t):
        return seated() if t >= 3 else {"box": None, "state": TL, "hold": False}
    c = cam.build(frames(80, fn))
    assert c.per_frame[0].zoom == 0.0 and c.per_frame[-1].zoom > 0.3
    assert max_rate(c) < 1.0
    e = cam.build([])
    assert e.views == [] and e.per_frame == []


# --- kimlik takibinden bağımsızlık ---

def test_camera_does_not_import_identity_or_model_code():
    src = Path(cam.__file__).read_text(encoding="utf-8")
    mods = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.ImportFrom):
            mods.add((n.module or "").split(".")[0] if n.level == 0 else (n.module or ""))
        elif isinstance(n, ast.Import):
            mods.update(a.name.split(".")[0] for a in n.names)
    assert not mods & {"reid", "reentry", "sam_engine", "sam_track", "detector", "pose", "onnxruntime", "cv2"}


# --- .sam.json girdisi ---

def _rec(i, tracked=True, clean=True, box=(0.3, 0.3, 0.6, 0.9), size=(0.3, 0.6)):
    return st.TrackRecord(i, i / FPS, st.TRACKED if tracked else st.LOST, True, box if tracked else None, 0.1, 0.9, 3.0,
                          0.9, 1.0, clean=clean, size=size if tracked else None)


def _doc(n=40, posture=True, state=True, lower=False, rec=_rec):
    recs = [rec(i) for i in range(n)]
    pr = [pm.PostureFrame(i / FPS, pm.SEATED, framing=SEATED_BOX).row() for i in range(n)] if posture else None
    sr = [ts.StateFrame(i, i / FPS, ts.TRACKED, None if i == 0 else ts.TRACKED, "ok").row() for i in range(n)] if state else None
    doc = st.make_doc("klip.mp4", recs, size=(640, 480), sample_fps=FPS, posture=pr, states=sr)
    if lower:
        from tracker.lowerbody import ROW_FIELDS as LF
        row = [0.0] * len(LF)
        row[LF.index("fx1")], row[LF.index("fy1")], row[LF.index("fx2")], row[LF.index("fy2")] = SEATED_BOX
        doc["lower"] = {"fields": list(LF), "rows": [[i / FPS, *row[1:]] for i in range(n)]}
    return doc


def test_doc_with_posture_uses_posture_framing_not_the_mask_box():
    doc = _doc()
    fr, src = cam.frames_from_doc(doc)
    assert src == "posture" and fr[0].box == SEATED_BOX and fr[0].posture == pm.SEATED
    c, _ = cam.views_from_doc(doc)
    assert c.occupancy[0] == pytest.approx(0.70, abs=0.005)


def test_doc_lower_only_and_sam_only_sources():
    fr, src = cam.frames_from_doc(_doc(posture=False, lower=True))
    assert src == "lower" and fr[0].box == SEATED_BOX
    fr, src = cam.frames_from_doc(_doc(posture=False))
    assert src == "sam"
    # SAM kaynağı: kutunun kendi boyu değil son TEMİZ boyut (w, h) kullanılır
    b = fr[0].box
    assert b[2] - b[0] == pytest.approx(0.3, abs=1e-3) and b[3] - b[1] == pytest.approx(0.6, abs=1e-3)


def test_sam_source_ignores_raw_mask_box_growth_when_unclean():
    def rec(i):  # maske kutusu şişiyor (masa karışıyor) ama son temiz boyut aynı kalıyor
        wide = i >= 20
        return _rec(i, clean=not wide, box=(0.1, 0.2, 0.9, 0.95) if wide else (0.3, 0.3, 0.6, 0.9))
    c, src = cam.views_from_doc(_doc(posture=False, state=False, rec=rec))
    assert src == "sam" and zoom_span(c) < 1e-6  # yarı örtülü kareler zoom'u beslemez


def test_state_derived_from_records_when_no_state_block():
    def rec(i):
        return _rec(i, tracked=not (10 <= i < 30))
    fr, _ = cam.frames_from_doc(_doc(state=False, rec=rec), Config())
    assert fr[9].state == T and fr[10].state == TL and fr[10].hold and fr[20].hold  # lost_hold_s = 1.0 sn içinde tut
    assert not fr[25].hold and fr[30].state == T


def test_state_block_hold_flag_is_used():
    doc = _doc()
    doc["state"]["rows"][5] = ts.StateFrame(5, 0.5, TL, T, "no_mask", hold=True).row()
    fr, _ = cam.frames_from_doc(doc)
    assert fr[5].state == TL and fr[5].hold is True


# --- dosya + CLI ---

def test_sam_camera_cli_writes_lua_compatible_views(tmp_path, capsys):
    doc = _doc()
    sj = tmp_path / "klip.mp4.sam.json"
    st.save_doc(sj, doc)
    assert main(["sam-camera", str(sj)]) == 0
    out = capsys.readouterr().out
    assert "bölge kaynağı: posture" in out and "doluluk" in out and "Görünümler:" in out
    d = json.loads((tmp_path / "klip.mp4.views.json").read_text(encoding="utf-8"))
    assert d["version"] == 1 and d["target"]["kind"] == "sam-lower" and d["vsig"] == doc["vsig"]
    assert d["views"] and all(len(k) == 4 for k in d["views"])
    assert [k[0] for k in d["views"]] == sorted(k[0] for k in d["views"])


def test_sam_camera_cli_fill_option_and_errors(tmp_path, capsys):
    sj = tmp_path / "k.mp4.sam.json"
    st.save_doc(sj, _doc())
    assert main(["sam-camera", str(sj), "--fill", "0.5", "--out", str(tmp_path / "o.json")]) == 0
    z50 = json.loads((tmp_path / "o.json").read_text(encoding="utf-8"))["views"][0][1]
    assert main(["sam-camera", str(sj), "--out", str(tmp_path / "p.json")]) == 0
    z70 = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))["views"][0][1]
    assert z70 > z50  # daha çok doluluk = daha çok yakınlaşma
    assert main(["sam-camera", str(sj), "--fill", "2"]) == 1
    assert main(["sam-camera", str(tmp_path / "yok.sam.json")]) == 1
    capsys.readouterr()


def test_sam_track_camera_flag_writes_views_next_to_the_video(tmp_path, monkeypatch, capsys):
    from tracker.export import load_views

    v, _ = _cli(tmp_path, monkeypatch, script=[GOOD] * 40)
    assert main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--max-seconds", "1.0", "--device", "cpu",
                 "--camera"]) == 0
    out = capsys.readouterr().out
    assert "kamera:" in out and "bölge kaynağı: sam" in out
    views = load_views(tmp_path / "klip.avi.views.json", video=str(v))  # vsig videoyla eşleşir
    assert views and all(len(k) == 4 for k in views)


def test_sam_track_posture_camera_end_to_end_uses_posture_region(tmp_path, monkeypatch, capsys):
    """Gerçek `--posture` hattı (PostureModel + TrackStateMachine satırları; yalnız poz ve SAM sahte) -> kamera."""
    import tracker.pose as pose_mod

    monkeypatch.setattr(pose_mod, "PoseEstimator", _FakePoseEstimator)
    v, _ = _cli(tmp_path, monkeypatch, script=[GOOD] * 40)
    assert main(["sam-track", str(tmp_path), str(v), "--rect", "8,8,56,40", "--max-seconds", "1.0", "--device", "cpu",
                 "--posture", "--camera"]) == 0
    assert "bölge kaynağı: posture" in capsys.readouterr().out
    doc = st.load_doc(st.sam_path(v))
    c, src = cam.views_from_doc(doc)
    assert src == "posture" and len(c.per_frame) == len(doc["records"]) and c.views
    assert zoom_span(c) < 0.05  # sabit poz: kamera sabit
    occ = [o for o, ok in zip(c.occupancy, c.zoom_ok) if ok and o is not None]
    assert occ and all(0.4 < o <= 1.0 for o in occ)


def test_views_path_for():
    assert cam.views_path_for("a/x.mp4.sam.json").name == "x.mp4.views.json"
    assert cam.views_path_for("a/y.json").name == "y.views.json"
