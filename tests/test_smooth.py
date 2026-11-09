import pytest

from tracker.geometry import View
from tracker.smooth import DeadZone, Ema, ViewSmoother


def test_ema_first_value_passthrough_then_blend():
    e = Ema(0.5)
    assert e.update(10) == 10
    assert e.update(20) == 15


def test_ema_invalid_alpha():
    with pytest.raises(ValueError):
        Ema(0)


def test_deadzone_holds_small_moves():
    d = DeadZone(0.1)
    d.update(0.0)
    assert d.update(0.05) == 0.0
    assert d.update(0.3) == pytest.approx(0.2)


def test_view_smoother_converges():
    s = ViewSmoother(alpha_pos=0.5, alpha_zoom=0.5, dead_zone_pos=0, dead_zone_zoom=0)
    s.update(View(0, 0, 0))
    out = View()
    for _ in range(30):
        out = s.update(View(1.0, 0.2, -0.2))
    assert out.zoom == pytest.approx(1.0, abs=1e-3)
    assert out.pan_x == pytest.approx(0.2, abs=1e-3)
