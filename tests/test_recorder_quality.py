"""Dışa aktarma kalitesi: CLI varsayılanı yüksek kalite, ana varyantla eşlik bozulmadan."""
from recorder.export import ffmpeg_cmd
from recorder.main import build_parser


def test_cli_defaults_are_high_quality():
    args = build_parser().parse_args(["export", "v.mp4"])
    assert args.crf == 14 and args.preset == "medium"  # önceki: 18 / veryfast


def test_ffmpeg_preset_is_configurable_and_default_unchanged():
    base = ffmpeg_cmd("ff", (64, 64), 25.0, "i", "o", audio=False)
    assert base[base.index("-preset") + 1] == "veryfast"  # ana varyantla eşlik
    hq = ffmpeg_cmd("ff", (64, 64), 25.0, "i", "o", audio=False, crf=14, preset="medium")
    assert hq[hq.index("-crf") + 1] == "14" and hq[hq.index("-preset") + 1] == "medium"
