"""S13b: sabitleme (gmc.py kestirimi + yol yumuşatma + render)."""
import math

import cv2
import numpy as np

from tracker import stabilize as sb


def _tex(h=240, w=320, seed=3):
    rng = np.random.default_rng(seed)
    return cv2.GaussianBlur((rng.random((h, w)) * 255).astype(np.uint8), (0, 0), 2)


def _shift(g, dx, dy):
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.cvtColor(cv2.warpAffine(g, M, (g.shape[1], g.shape[0]),
                                       borderMode=cv2.BORDER_REFLECT), cv2.COLOR_GRAY2BGR)


def test_decompose_compose_roundtrip():
    W = sb.compose(7.5, -3.0, 0.05, 0.02)
    tx, ty, ang, ls = sb.decompose(W)
    assert abs(tx - 7.5) < 1e-9 and abs(ty + 3) < 1e-9 and abs(ang - 0.05) < 1e-9
    assert abs(ls - 0.02) < 1e-9
    assert np.allclose(sb.compose(tx, ty, ang, ls), W)


def test_moving_average_edges_and_constant():
    x = np.arange(10, dtype=float)
    y = sb.moving_average(x, 2)
    assert abs(y[5] - 5) < 1e-9 and abs(y[0] - 1.0) < 1e-9  # uçta pencere daralır
    assert np.allclose(sb.moving_average(np.full(7, 3.0), 3), 3.0)
    assert np.allclose(sb.moving_average(x, 0), x)


def test_constant_path_gives_identity_and_no_margin():
    paths = [np.eye(3)] * 20
    cors, margin = sb.corrections(paths, 10.0, (320, 240))
    assert margin == 1.0 and all(np.allclose(c, np.eye(3)) for c in cors)
    assert sb.corrections([], 10.0, (320, 240)) == ([], 1.0)


def test_jitter_is_removed_but_slow_pan_is_kept():
    n, fps = 60, 10.0
    pan = np.linspace(0, 60, n)  # yavaş kaydırma
    jit = 4.0 * np.sin(np.arange(n) * 2.1)  # hızlı titreme
    paths = [sb.compose(float(p + j), 0.0, 0.0, 0.0) for p, j in zip(pan, jit)]
    cors, margin = sb.corrections(paths, fps, (320, 240), window_s=1.0)
    after = np.array([(p @ np.linalg.inv(c))[0, 2] for c, p in zip(cors, paths)])  # etkin yol
    mid = slice(8, n - 8)
    assert np.std(np.diff(after[mid])) < 0.4 * np.std(np.diff((pan + jit)[mid]))
    assert abs(after[n // 2] - pan[n // 2]) < 3.0  # kaydırma silinmedi
    assert 1.0 <= margin <= sb.MAX_MARGIN


def test_correction_is_clamped_and_margin_capped():
    paths = [sb.compose(0, 0, 0, 0)] * 10 + [sb.compose(500.0, 300.0, 1.0, 0.0)] + \
            [sb.compose(0, 0, 0, 0)] * 10
    cors, margin = sb.corrections(paths, 10.0, (320, 240), window_s=0.2)
    for c in cors:
        tx, ty, ang, _ = sb.decompose(c)
        assert abs(tx) <= sb.MAX_SHIFT * 320 + 1e-6 and abs(ty) <= sb.MAX_SHIFT * 240 + 1e-6
        assert abs(ang) <= sb.MAX_ROT + 1e-9
    assert margin <= sb.MAX_MARGIN


def test_margin_hides_borders():
    M = sb.compose(15.0, -10.0, math.radians(2), 0.0)
    need = sb._border_need(M, 320, 240)
    full = sb.margin_matrix(need, (320, 240)) @ M
    inv = np.linalg.inv(full)
    for x, y in ((0, 0), (319, 0), (319, 239), (0, 239)):
        u, v, _ = inv @ np.array([x, y, 1.0])
        assert -1.0 <= u <= 321.0 and -1.0 <= v <= 241.0


def test_plan_on_shaky_frames_reduces_residual_motion():
    g = _tex()
    rng = np.random.default_rng(5)
    offs = rng.uniform(-4, 4, (30, 2))
    frames = [_shift(g, dx, dy) for dx, dy in offs]
    cors, margin, size = sb.plan(iter(frames), 10.0, 1.0)
    assert size == (320, 240) and len(cors) == 30 and 1.0 <= margin <= sb.MAX_MARGIN

    def residual(imgs):
        gs = [cv2.cvtColor(i, cv2.COLOR_BGR2GRAY).astype(np.float32) for i in imgs]
        sh = [cv2.phaseCorrelate(a, b)[0] for a, b in zip(gs, gs[1:])]
        return float(np.std([s[0] for s in sh]) + np.std([s[1] for s in sh]))

    out = []
    for f, c in zip(frames, cors):
        M = sb.render_matrix(c, margin, size)
        out.append(cv2.warpAffine(f, M[:2], size, borderMode=cv2.BORDER_REPLICATE))
    assert residual(out[3:-3]) < 0.6 * residual(frames[3:-3])


def test_untrackable_frames_do_not_move_path():
    flat = np.full((120, 160, 3), 90, np.uint8)  # köşe yok → kestirilemez → kimlik
    cors, margin, _ = sb.plan(iter([flat] * 6), 10.0)
    assert margin == 1.0 and all(np.allclose(c, np.eye(3)) for c in cors)
