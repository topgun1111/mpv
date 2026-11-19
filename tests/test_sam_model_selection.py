from types import SimpleNamespace

from tracker.live import LiveController
from tracker.settings import panel_snapshot


class _Log:
    def __init__(self):
        self.notes = []

    def note(self, value):
        self.notes.append(value)


def test_pc_sam_model_selection_persists_config(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg = SimpleNamespace(sam_model_variant="edgetam", save=lambda path: cfg_path.write_text(
        '{"sam_model_variant": "' + cfg.sam_model_variant + '"}', encoding="utf-8"))
    ctl = LiveController.__new__(LiveController)
    ctl.cfg = cfg
    ctl.cfg_path = str(cfg_path)
    ctl.cfg_dirty = False
    ctl.tlog = _Log()

    out = ctl._on_sam_model(["track-sam-model", "sam2_small"])

    assert cfg.sam_model_variant == "sam2_small"
    assert '"sam_model_variant": "sam2_small"' in cfg_path.read_text(encoding="utf-8")
    assert ctl.cfg_dirty is True
    assert "SAM 2.1 Small" in out.osd
    assert ctl.tlog.notes == ["PC SAM modeli seçildi: SAM 2.1 Small"]


def test_pc_sam_model_selection_rejects_unknown_variant():
    ctl = LiveController.__new__(LiveController)
    ctl.cfg = SimpleNamespace(sam_model_variant="edgetam")
    ctl.cfg_path = None
    ctl.cfg_dirty = False
    ctl.tlog = _Log()

    out = ctl._on_sam_model(["track-sam-model", "unknown"])

    assert ctl.cfg.sam_model_variant == "edgetam"
    assert "Bilinmeyen" in out.osd


def test_panel_snapshot_exposes_both_sam_model_choices():
    cfg = SimpleNamespace(sam_model_variant="edgetam")
    # panel_snapshot also serializes all ordinary settings; use the real Config defaults.
    from tracker.config import Config
    snap = panel_snapshot(Config())
    assert snap["sam_model"]["cur"] == "edgetam"
    assert [item["id"] for item in snap["sam_model"]["items"]] == ["edgetam", "sam2_small"]
    assert all(item["total"] == 5 for item in snap["sam_model"]["items"])


def test_sam_commands_allow_selected_model_default():
    from tracker.main import build_parser
    parser = build_parser()
    # With only the media path, argparse assigns it to the required media positional,
    # leaving model_dir unset so the persisted PC picker is used.
    first = parser.parse_args(["sam-first", "frame.png", "--rect", "0,0,20,20"])
    track = parser.parse_args(["sam-track", "clip.mp4", "--rect", "0,0,20,20"])
    preview = parser.parse_args(["sam-preview", "clip.mp4", "--rect", "0,0,20,20"])
    assert first.model_dir is None and first.image == "frame.png"
    assert track.model_dir is None and track.video == "clip.mp4"
    assert preview.model_dir is None and preview.video == "clip.mp4"
