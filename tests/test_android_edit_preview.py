"""Regression wiring for Android Recording's independent video editor."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REC = ROOT / "android/rec/src/main/kotlin/com/takipli/oynat/rec"


def test_paused_editing_requests_native_frame_redraw():
    screen = (REC / "RecEditingScreen.kt").read_text(encoding="utf-8")
    refresh = screen.split("snapshotFlow { Triple", 1)[1].split("LaunchedEffect(active)", 1)[0]
    assert "VideoFrameProcessor.REDRAW" in refresh
    assert "player.setVideoEffects(VideoFrameProcessor.REDRAW)" in refresh
    assert "ref.set(if (before) Grade() else settings)" in refresh
    assert "seekTo(" not in refresh
    assert "delay(50)" in refresh


def test_preview_has_adaptive_layout_and_expand_control():
    screen = (REC / "RecEditingScreen.kt").read_text(encoding="utf-8")
    assert "val sideBySide = maxWidth >= 500.dp" in screen
    assert "Modifier.weight(1.15f).fillMaxHeight()" in screen
    assert "Modifier.weight(1.8f).fillMaxWidth()" in screen
    assert screen.count("if (!largePreview)") == 2
    assert 'Text(if (large) "Controls" else "Enlarge")' in screen
    assert "Modifier.size(w, w / aspect)" in screen
    assert "clearVideoTextureView" in screen


def test_editor_enables_replayable_cache_on_its_own_player():
    screen = (REC / "RecEditingScreen.kt").read_text(encoding="utf-8")
    assert "ExoPlayer.Builder(ctx, EditingRenderersFactory(ctx))" in screen
    java = ROOT / "android/rec/src/main/java/com/takipli/oynat/rec/EditingRenderersFactory.java"
    factory = java.read_text(encoding="utf-8")
    assert "extends DefaultRenderersFactory" in factory
    assert "createPlaybackVideoGraphWrapper(" in factory
    assert ".setEnablePlaylistMode(true)" in factory
    assert ".setEnableReplayableCache(true)" in factory
    assert ".setClock(getClock())" in factory
    assert "EditingRenderersFactory" not in (REC / "RecScreen.kt").read_text(encoding="utf-8")
    assert "FlowRow(" in screen
