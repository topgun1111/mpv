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


def test_editing_zoom_is_preview_only_and_survives_layout_changes():
    screen = (REC / "RecEditingScreen.kt").read_text(encoding="utf-8")
    assert "var previewView by remember(source)" in screen
    assert screen.count("previewView = previewView,") == 2
    assert screen.count("onResetZoom = { previewView = CamView(0.0, 0.0, 0.0) }") == 2
    assert "detectTransformGestures" in screen and "viewTransform(previewView)" in screen
    assert "pointerInput(aspect, busy)" in screen and "rememberUpdatedState(onGesture)" in screen
    assert "applyGestureAt(previewView, ax, ay, dx, dy, zoom, 4.0)" in screen
    export = screen.split("fun export() {", 1)[1].split("    Column(", 1)[0]
    assert "previewView" not in export and "EditExporter.start" in export


def test_recording_preview_accepts_gestures_without_recording_keys():
    screen = (REC / "RecScreen.kt").read_text(encoding="utf-8")
    assert screen.count("PreviewSurface(player, view, aspect, !exporting,") == 2
    assert "if (gesturesEnabled) detectTransformGestures" in screen
    assert "LaunchedEffect(recording)" in screen and "while (recording)" in screen
    assert 'keys = emptyList(); view = ZERO_VIEW; exportMessage = ""' in screen
