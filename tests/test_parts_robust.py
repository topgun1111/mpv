"""Oklüzyon dayanıklı parça kutusu: masa arkasında oturan kişi (uydurma bacak eklemleri, yalnız üst gövde görünür)."""
from tracker import parts

W = H = 1000


def _seated(knee=(0.45, 1.05, 0.5), ankle=(0.45, 1.4, 0.5)):
    row = [0.0] * 51

    def setj(j, x, y, c):
        row[3 * j:3 * j + 3] = [x, y, c]

    setj(5, 0.4, 0.25, 0.9)
    setj(6, 0.6, 0.25, 0.9)
    setj(11, 0.42, 0.55, 0.8)
    setj(12, 0.58, 0.55, 0.8)
    setj(13, *knee)
    setj(15, *ankle)
    return row


def test_invented_joints_are_dropped_and_legs_hang_from_the_hips():
    row = _seated()
    old = parts.group_box(parts.PRESETS["left_leg"], row, W, H, 500, 0.35, 0.10, 0.02, True, False)
    assert old[0][3] > 0.8  # eski kural: dev kutu (uydurma diz/ayak bileği)
    assert parts.group_box(parts.PRESETS["left_leg"], row, W, H, 500, 0.35, 0.10, 0.02, True, True) is None
    box = parts.anchored_leg_box("left_leg", row, W, H, 0.35, 500)
    assert box is not None and abs(box[1] - 0.7) < 1e-9 and abs(box[3] - 0.3) < 1e-9  # kalçadan 1 gövde boyu aşağı


def test_plausible_low_confidence_knee_is_kept():
    row = _seated(knee=(0.45, 0.8, 0.25), ankle=(0.0, 0.0, 0.0))
    g = parts.group_box(parts.PRESETS["left_leg"], row, W, H, 500, 0.35, 0.10, 0.02, False, True)
    assert g is not None and g[0][3] < 0.6


def test_standing_person_is_unchanged():
    st = [0.0] * 51
    for j, (x, y) in {5: (.4, .25), 6: (.6, .25), 11: (.42, .55), 12: (.58, .55), 13: (.42, .72),
                      14: (.58, .72), 15: (.42, .9), 16: (.58, .9)}.items():
        st[3 * j:3 * j + 3] = [x, y, 0.9]
    a = parts.group_box(parts.PRESETS["legs"], st, W, H, 800, 0.35, 0.10, 0.02, True, False)
    b = parts.group_box(parts.PRESETS["legs"], st, W, H, 800, 0.35, 0.10, 0.02, True, True)
    assert a == b
