"""S5: `tracker/trackgate.py` (Android `core/TrackGate.kt` portu). TrackGateTest.kt senaryoları + Kotlin sabit denetimi."""
import re
from pathlib import Path

import numpy as np
import pytest

from tracker import trackgate as tg
from tracker.trackgate import TrackGate

ROOT = Path(__file__).resolve().parents[1]
KT = ROOT / "android/core/src/main/kotlin/com/takipli/oynat/core/TrackGate.kt"


def learned(sim=0.8):
    g = TrackGate()
    for _ in range(tg.MIN_LEARN):
        g.learn(sim)
    return g


def test_remember_only_clean_frames():
    assert tg.remember(0.8, 1.0)
    assert not tg.remember(0.5, 1.0)  # emin değil
    assert not tg.remember(0.9, 0.4)  # çoğu örtülü
    assert not tg.remember(0.9, 2.0)  # başka bir şeyle birleşmiş
    assert tg.remember(0.6, 0.6) and tg.remember(0.6, 1.6)  # sınırlar dahil


def test_cosine_basics():
    assert tg.cosine([1, 2], [2, 4]) == pytest.approx(1.0)
    assert tg.cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert tg.cosine([], []) == 0.0
    assert tg.cosine([0, 0], [1, 1]) == 0.0
    assert tg.cosine([1, 2, 3], [1, 2]) == 0.0  # boyut uyuşmaz
    assert tg.cosine(np.ones(256, np.float32), -np.ones(256, np.float32)) == pytest.approx(-1.0)


def test_jump_allowance_grows_with_lost_frames():
    assert not tg.is_jump(0.2, 0.3, 0)
    assert tg.is_jump(0.6, 0.3, 0)
    assert not tg.is_jump(0.6, 0.3, 4)  # bir süredir kayıp: özne yer değiştirmiş olabilir
    assert tg.is_jump(0.2, 0.0, 0) and not tg.is_jump(0.07, 0.0, 0)  # küçük kutuda alt sınır 0.05


def test_everything_passes_before_enough_clean_frames():
    g = TrackGate()
    assert g.accept(5.0, 0.3, 3, 0.0)
    assert g.rejected == 0
    g.learn(0.8)
    g.learn(0.8)
    assert g.accept(5.0, 0.3, 3, 0.0)  # 2 temiz kare: hâlâ serbest


def test_lookalike_after_loss_is_rejected_but_the_subject_is_accepted():
    g = learned(0.8)
    assert not g.accept(0.1, 0.3, 5, 0.2)  # özneye benzemeyen bir şeyde devam
    assert g.accept(0.1, 0.3, 5, 0.7)  # özne geri geldi
    assert g.rejected == 1


def test_far_jump_while_tracking_needs_similarity_but_normal_motion_does_not():
    g = learned(0.8)
    assert not g.accept(0.9, 0.3, 0, 0.5)  # kare boyunca sıçradı: başka bir şey
    assert g.accept(0.9, 0.3, 0, 0.7)  # gerçek hızlı hareket, hâlâ benziyor
    assert g.accept(0.05, 0.3, 0, 0.1)  # normal hareket asla kapıya takılmaz


def test_partial_mask_keeps_the_last_clean_size():
    assert tg.size(0.4, 0.1, 0.2, 0.3, 0.5) == (0.3, 0.5)
    assert tg.size(0.9, 0.1, 0.2, 0.3, 0.5) == (0.1, 0.2)
    assert tg.size(0.4, 0.1, 0.2, 0.0, 0.0) == (0.1, 0.2)  # temiz boyut henüz bilinmiyor


def test_long_loss_relaxes_the_resume_rule_so_it_never_deadlocks():
    g = learned(0.8)  # devam için 0.6 x 0.8 = 0.48 gerekir
    assert not g.accept(0.1, 0.3, 5, 0.40)
    assert not g.accept(0.1, 0.3, 12, 0.40)  # gevşeme RELAX_FROM kayıp kareden sonra başlar
    assert g.accept(0.1, 0.3, 36, 0.40)  # ~6 sn kayıp: 0.24 yeter (farklı açı / ışık)
    assert not g.accept(0.1, 0.3, 36, 0.10)  # hiç benzemeyen yine reddedilir
    assert tg.relax(0) == 1.0 and tg.relax(1000) == 0.5 and tg.relax(24) == pytest.approx(0.75)


def test_learn_is_a_running_average_and_counters_summarize():
    g = TrackGate()
    g.learn(1.0)
    assert g.ref == 1.0 and g.learned == 1  # ilk değer olduğu gibi
    g.learn(0.5)
    assert g.ref == pytest.approx(0.95)  # 0.9 x 1.0 + 0.1 x 0.5
    g.note()
    assert g.accepted == 1
    assert g.summary() == "kapı: 1 kabul, 0 ret (benzerlik ref 0.95, 2 temiz kare)"


def test_constants_match_the_kotlin_source():
    if not KT.is_file():
        pytest.skip("android/ kaynağı yok")
    kt = {m[0]: float(m[1]) for m in re.findall(r"const val (\w+) = ([\d.]+)", KT.read_text(encoding="utf-8"))}
    assert kt, "Kotlin sabitleri okunamadı"
    for name, val in kt.items():
        assert getattr(tg, name) == pytest.approx(val), name
