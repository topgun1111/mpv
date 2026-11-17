package com.takipli.oynat.rec

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.net.Uri
import android.view.TextureView
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.transformer.Transformer
import com.takipli.oynat.core.REC_SPEED_PRESETS
import com.takipli.oynat.core.View as CamView
import com.takipli.oynat.core.ViewKey
import com.takipli.oynat.core.ErrKind
import com.takipli.oynat.core.appendKey
import com.takipli.oynat.core.applyGestureAt
import com.takipli.oynat.core.classifyError
import com.takipli.oynat.core.clampRecSpeed
import com.takipli.oynat.core.normalizeRotation
import com.takipli.oynat.core.recKeyDt
import com.takipli.oynat.core.viewTransform
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.min
import kotlin.math.pow

private val ZERO_VIEW = CamView(0.0, 0.0, 0.0)
private val OVERLAY_BG = Color.Black.copy(alpha = 0.55f)
private val REC_RED = Color(0xFFD32F2F)

private fun Context.findActivity(): Activity? {
    var c: Context = this
    while (c is ContextWrapper) {
        if (c is Activity) return c
        c = c.baseContext
    }
    return null
}

private fun clock(ms: Long): String {
    val s = (ms / 1000).coerceAtLeast(0)
    return String.format(Locale.ROOT, "%d:%02d", s / 60, s % 60)
}

private fun speedLabel(s: Double): String =
    (if (s == s.toInt().toDouble()) s.toInt().toString() else String.format(Locale.ROOT, "%.2f", s).trimEnd('0')) + "×"

private fun friendly(ctx: Context, t: Throwable, codeName: String? = null): String {
    val id = when (classifyError(codeName, t.message, t.javaClass.name)) {
        ErrKind.NO_SPACE -> R.string.err_no_space
        ErrKind.VIDEO_ACCESS -> R.string.err_video
        ErrKind.CODEC -> R.string.err_codec
        else -> R.string.err_other
    }
    return ctx.getString(id) + "\n[" + (codeName ?: t.message ?: t.javaClass.simpleName).take(160) + "]"
}

/**
 * Record-only app: pick a clip, play it, pinch to zoom and drag at the same time while recording, then export the recorded camera path.
 * Two layouts share one player: the normal page (with a Full screen button on the preview) and the full-screen recording view
 * (preview fills the screen, every control is an overlay on top of it).
 */
@Composable
fun RecScreen() {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var uri by remember { mutableStateOf<Uri?>(null) }
    var info by remember { mutableStateOf<VideoInfo?>(null) }
    var error by remember { mutableStateOf("") }
    var view by remember { mutableStateOf(ZERO_VIEW) }
    var keys by remember { mutableStateOf<List<ViewKey>>(emptyList()) }
    var recording by remember { mutableStateOf(false) }
    var playing by remember { mutableStateOf(false) }
    var posMs by remember { mutableLongStateOf(0L) }
    var durationMs by remember { mutableLongStateOf(1L) }
    var exporter by remember { mutableStateOf<Transformer?>(null) }
    var exportProgress by remember { mutableStateOf(0f) }
    var exportMessage by remember { mutableStateOf("") }
    var speed by remember { mutableStateOf(1.0) }
    var fullscreen by remember { mutableStateOf(false) }
    val player = remember { ExoPlayer.Builder(ctx).build() }
    val hostView = LocalView.current
    SideEffect { hostView.keepScreenOn = recording || exporter != null || fullscreen }
    DisposableEffect(Unit) { onDispose { exporter?.cancel(); player.release(); hostView.keepScreenOn = false } }
    var volume by remember { mutableStateOf(1f) }; var muted by remember { mutableStateOf(false) } // preview volume only; the export is unaffected
    SideEffect { player.volume = if (muted) 0f else volume }

    // Full screen = immersive (system bars hidden; a swipe from the edge shows them briefly).
    DisposableEffect(fullscreen) {
        val window = ctx.findActivity()?.window
        if (window != null) {
            val c = WindowCompat.getInsetsController(window, hostView)
            if (fullscreen) {
                c.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                c.hide(WindowInsetsCompat.Type.systemBars())
            } else {
                c.show(WindowInsetsCompat.Type.systemBars())
            }
        }
        onDispose { window?.let { WindowCompat.getInsetsController(it, hostView).show(WindowInsetsCompat.Type.systemBars()) } }
    }
    // The preview surface is created again when the layout switches: repaint the current frame once it is attached.
    LaunchedEffect(fullscreen) {
        delay(150)
        if (!player.isPlaying && player.mediaItemCount > 0) player.seekTo(player.currentPosition)
    }

    fun stopRecording() {
        recording = false
        player.pause()
        keys = appendKey(keys, player.currentPosition.coerceAtLeast(0) / 1000.0, view)
    }

    fun startRecording() {
        keys = emptyList(); view = ZERO_VIEW; exportMessage = ""
        player.seekTo(0); player.play(); recording = true
    }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { picked ->
        if (picked != null) {
            runCatching { ctx.contentResolver.takePersistableUriPermission(picked, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
            scope.launch {
                try {
                    val vi = withContext(Dispatchers.IO) { RecVideo.probe(ctx, picked) }
                    info = vi; uri = picked; error = ""; keys = emptyList(); view = ZERO_VIEW; exportMessage = ""
                    durationMs = (vi.durationS * 1000).toLong().coerceAtLeast(1); posMs = 0
                    player.setVideoEffects(listOfNotNull(RecExporter.rotationEffect(vi.userRot)))
                    player.setMediaItem(MediaItem.fromUri(picked)); player.prepare(); player.pause()
                    player.playbackParameters = PlaybackParameters(speed.toFloat())
                } catch (t: Throwable) { error = friendly(ctx, t); info = null; uri = null }
            }
        }
    }

    LaunchedEffect(player) {
        while (true) {
            posMs = player.currentPosition.coerceAtLeast(0)
            if (player.duration > 0) durationMs = player.duration
            playing = player.isPlaying
            delay(33)
        }
    }
    LaunchedEffect(recording) {
        while (recording) {
            if (player.isPlaying) keys = appendKey(keys, player.currentPosition.coerceAtLeast(0) / 1000.0, view, recKeyDt(speed))
            else if (player.playbackState == Player.STATE_ENDED) { stopRecording(); break } // end of clip = end of take
            delay(33)
        }
    }
    LaunchedEffect(exporter) {
        val active = exporter ?: return@LaunchedEffect
        while (exporter === active) {
            exportProgress = RecExporter.progress(active).coerceAtLeast(0f)
            delay(250)
        }
    }

    BackHandler(enabled = fullscreen) { if (recording) stopRecording() else fullscreen = false }

    // Speed only changes the preview player. Keys are stamped with the video's own clock, so the export keeps the original speed.
    fun applySpeed(s: Double) {
        speed = clampRecSpeed(s)
        player.playbackParameters = PlaybackParameters(speed.toFloat())
    }

    fun togglePlay() {
        if (player.isPlaying) player.pause() else {
            if (player.playbackState == Player.STATE_ENDED) player.seekTo(0)
            player.play()
        }
    }

    fun reloadPreview(source: Uri, rot: Int, at: Long) {
        runCatching {
            player.setVideoEffects(listOfNotNull(RecExporter.rotationEffect(rot)))
            player.setMediaItem(MediaItem.fromUri(source)); player.prepare(); player.seekTo(at); player.pause()
            player.playbackParameters = PlaybackParameters(speed.toFloat())
        }
    }

    // Manual clockwise turn of the video (preview + export). Recorded moves were made in the old orientation, so they are cleared.
    fun rotate(delta: Int) {
        val source = uri ?: return
        val vi = info ?: return
        if (recording || exporter != null) return
        val rot = normalizeRotation(vi.userRot + delta)
        RecRot.set(ctx, source.toString(), rot)
        info = vi.copy(userRot = rot)
        keys = emptyList(); view = ZERO_VIEW; exportMessage = ""
        reloadPreview(source, rot, player.currentPosition.coerceAtLeast(0))
    }

    fun startExport() {
        val source = uri ?: return
        val vi = info ?: return
        if (keys.isEmpty()) { exportMessage = ctx.getString(R.string.record_first); return }
        val finalKeys = if (keys.size == 1) keys + listOf(keys.first().mapIndexed { i, v -> if (i == 0) v + 0.04 else v }) else keys
        val out = File(ctx.cacheDir, "manual-camera.mp4")
        exportMessage = ctx.getString(R.string.preparing); exportProgress = 0f
        val resumeAt = player.currentPosition.coerceAtLeast(0)
        player.pause(); player.stop(); player.clearMediaItems(); System.gc()
        var completed = false
        fun finish(message: String) { completed = true; exporter = null; exportMessage = message; reloadPreview(source, vi.userRot, resumeAt) }
        try {
            val started = RecExporter.start(
                ctx, source, finalKeys, out, vi.width, vi.height,
                (vi.frameRate ?: 30.0).coerceIn(1.0, 60.0), false, vi.userRot, vi.bitrate,
                onDone = {
                    scope.launch {
                        try {
                            val name = "Takipli_Kayit_" + SimpleDateFormat("yyyyMMdd_HHmmss", Locale.ROOT).format(Date()) + ".mp4"
                            withContext(Dispatchers.IO) { RecExporter.saveToMovies(ctx, out, name); out.delete() }
                            finish(ctx.getString(R.string.saved, name))
                        } catch (t: Throwable) { out.delete(); finish(friendly(ctx, t)) }
                    }
                },
                onError = { e -> out.delete(); finish(friendly(ctx, e, e.errorCodeName)) },
            )
            if (!completed) exporter = started
        } catch (t: Throwable) { finish(friendly(ctx, t)) }
    }

    val vi = info
    val loaded = uri != null && vi != null
    val exporting = exporter != null
    val aspect = if (vi != null) (vi.width.toFloat() / vi.height.toFloat()).coerceIn(0.25f, 4f) else 1f
    val onGesture: (Double, Double, Double, Double, Double) -> Unit = { ax, ay, dx, dy, z -> view = applyGestureAt(view, ax, ay, dx, dy, z, 4.0) }
    val exportLine = if (exporting) stringResource(R.string.exporting, (exportProgress * 100).toInt()) else exportMessage

    if (fullscreen && loaded) {
        // ---- Full screen: the preview fills the screen, everything else is an overlay ----
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            PreviewSurface(player, view, aspect, recording, onGesture, Modifier.fillMaxSize())
            Box(Modifier.fillMaxSize().safeDrawingPadding().padding(8.dp)) {
                Row(Modifier.fillMaxWidth().align(Alignment.TopCenter), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    OverlayButton(stringResource(R.string.exit_full_screen), { if (recording) stopRecording(); fullscreen = false })
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                        OverlayButton(stringResource(R.string.rotate_left), { rotate(-90) }, enabled = !recording && !exporting)
                        OverlayButton(stringResource(R.string.rotate_right), { rotate(90) }, enabled = !recording && !exporting)
                    }
                    Text(
                        if (recording) stringResource(R.string.rec_badge) else String.format(Locale.ROOT, "%.1f×", 2.0.pow(view.zoom)),
                        color = if (recording) REC_RED else Color.White, fontWeight = FontWeight.Bold, fontSize = 16.sp,
                        modifier = Modifier.clip(RoundedCornerShape(50)).background(OVERLAY_BG).padding(horizontal = 12.dp, vertical = 8.dp),
                    )
                }
                if (!recording && !exporting && keys.isEmpty() && exportMessage.isEmpty()) {
                    Text(
                        stringResource(R.string.fs_hint), color = Color.White, fontSize = 13.sp,
                        modifier = Modifier.align(Alignment.Center).clip(RoundedCornerShape(12.dp)).background(OVERLAY_BG).padding(12.dp),
                    )
                }
                Column(Modifier.fillMaxWidth().align(Alignment.BottomCenter).clip(RoundedCornerShape(16.dp)).background(OVERLAY_BG).padding(horizontal = 12.dp, vertical = 8.dp)) {
                    if (exportLine.isNotEmpty()) Text(exportLine, color = Color.White, fontSize = 13.sp)
                    if (exporting) LinearProgressIndicator(progress = { exportProgress }, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(clock(posMs), color = Color.White, fontSize = 12.sp)
                        Slider(
                            value = posMs.toFloat().coerceIn(0f, durationMs.toFloat()),
                            onValueChange = { if (!recording) { posMs = it.toLong(); player.seekTo(posMs) } },
                            valueRange = 0f..durationMs.toFloat(), enabled = !recording && !exporting,
                            colors = SliderDefaults.colors(thumbColor = Color.White, activeTrackColor = Color.White, inactiveTrackColor = Color.White.copy(alpha = 0.3f)),
                            modifier = Modifier.weight(1f).padding(horizontal = 8.dp),
                        )
                        Text(clock(durationMs), color = Color.White, fontSize = 12.sp)
                    }
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                        OverlayButton(stringResource(if (playing) R.string.pause else R.string.play), { togglePlay() }, enabled = !exporting)
                        OverlayButton(speedLabel(speed), {
                            applySpeed(REC_SPEED_PRESETS.firstOrNull { it > speed + 1e-6 } ?: REC_SPEED_PRESETS.first())
                        }, enabled = !exporting)
                        OverlayButton(if (muted || volume == 0f) "\uD83D\uDD07" else "\uD83D\uDD0A", { muted = !muted })
                        Box(Modifier.weight(1f))
                        if (!recording && keys.isNotEmpty()) OverlayButton(stringResource(R.string.export_mp4), { startExport() }, enabled = !exporting)
                        OverlayButton(
                            stringResource(if (recording) R.string.stop_short else R.string.rec_short),
                            { if (recording) stopRecording() else startRecording() },
                            enabled = !exporting, accent = true,
                        )
                    }
                }
            }
        }
    } else {
        // ---- Normal page ----
        Column(
            Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(stringResource(R.string.title), style = MaterialTheme.typography.headlineSmall)
            Text(stringResource(R.string.subtitle), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedButton(onClick = { picker.launch(arrayOf("video/*")) }, enabled = !exporting && !recording, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(if (uri == null) R.string.choose_video else R.string.change_video))
            }
            if (error.isNotEmpty()) Text(error, color = MaterialTheme.colorScheme.error)
            if (loaded && vi != null) {
                Box(Modifier.fillMaxWidth().height(300.dp).clip(RoundedCornerShape(16.dp))) {
                    PreviewSurface(player, view, aspect, recording, onGesture, Modifier.fillMaxSize())
                    if (recording) Text(stringResource(R.string.rec_badge), color = REC_RED, fontWeight = FontWeight.Bold, modifier = Modifier.padding(12.dp))
                    OverlayButton(stringResource(R.string.full_screen), { fullscreen = true }, modifier = Modifier.align(Alignment.BottomEnd).padding(8.dp))
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    OutlinedButton(onClick = { rotate(-90) }, enabled = !recording && !exporting) { Text(stringResource(R.string.rotate_left)) }
                    OutlinedButton(onClick = { rotate(90) }, enabled = !recording && !exporting) { Text(stringResource(R.string.rotate_right)) }
                    Text(String.format(Locale.ROOT, "%.1f×", 2.0.pow(view.zoom)), modifier = Modifier.padding(start = 4.dp))
                }
                Text(stringResource(R.string.rotate_note), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { togglePlay() }, enabled = !exporting) { Text(stringResource(if (playing) R.string.pause else R.string.play)) }
                    OutlinedButton(onClick = { view = ZERO_VIEW }, enabled = !recording && !exporting) { Text(stringResource(R.string.reset_view)) }
                }
                Slider(
                    value = posMs.toFloat().coerceIn(0f, durationMs.toFloat()),
                    onValueChange = { if (!recording) { posMs = it.toLong(); player.seekTo(posMs) } },
                    valueRange = 0f..durationMs.toFloat(), enabled = !recording && !exporting,
                )
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    OutlinedButton(onClick = { muted = !muted }) { Text(if (muted || volume == 0f) "\uD83D\uDD07" else "\uD83D\uDD0A") }
                    Slider(value = if (muted) 0f else volume, onValueChange = { volume = it; muted = it == 0f }, modifier = Modifier.weight(1f))
                }
                Text(stringResource(R.string.keyframes_info, clock(posMs), clock(durationMs), keys.size), style = MaterialTheme.typography.labelSmall)
                Text(stringResource(R.string.speed_title), style = MaterialTheme.typography.titleSmall)
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    REC_SPEED_PRESETS.forEach { p ->
                        FilterChip(selected = speed == p, enabled = !exporting, onClick = { applySpeed(p) }, label = { Text(speedLabel(p)) })
                    }
                }
                Text(stringResource(R.string.speed_note), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { if (recording) stopRecording() else startRecording() }, enabled = !exporting, modifier = Modifier.weight(1f)) {
                        Text(stringResource(if (recording) R.string.rec_stop else R.string.rec_start))
                    }
                    OutlinedButton(onClick = { startExport() }, enabled = !recording && !exporting && keys.isNotEmpty(), modifier = Modifier.weight(1f)) {
                        Text(stringResource(R.string.export_mp4))
                    }
                }
                if (exporting) LinearProgressIndicator(progress = { exportProgress }, modifier = Modifier.fillMaxWidth())
                if (exportLine.isNotEmpty()) Text(exportLine, style = MaterialTheme.typography.bodySmall)
            }
            Text(stringResource(R.string.version_label, BuildConfig.VERSION_NAME), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/**
 * The video surface. Fills the given area, shows the frame letterboxed, applies the camera [view] (zoom + pan) to it and, while
 * [recording], turns two-finger pinch + drag on the WHOLE area into [onGesture] (finger centre and shift as fractions of the video frame).
 */
@Composable
private fun PreviewSurface(
    player: ExoPlayer, view: CamView, aspect: Float, recording: Boolean,
    onGesture: (ax: Double, ay: Double, dx: Double, dy: Double, zoom: Double) -> Unit,
    modifier: Modifier,
) {
    BoxWithConstraints(
        modifier.background(Color.Black).clipToBounds().pointerInput(recording, aspect) {
            if (recording) detectTransformGestures { centroid, pan, zoom, _ ->
                val bw = size.width.toFloat(); val bh = size.height.toFloat()
                val fw = min(bw, bh * aspect); val fh = fw / aspect
                val ox = (bw - fw) / 2f; val oy = (bh - fh) / 2f
                val ax = ((centroid.x - ox) / fw).coerceIn(0f, 1f)
                val ay = ((centroid.y - oy) / fh).coerceIn(0f, 1f)
                onGesture(ax.toDouble(), ay.toDouble(), (pan.x / fw).toDouble(), (pan.y / fh).toDouble(), zoom.toDouble())
            }
        },
        contentAlignment = Alignment.Center,
    ) {
        val fitW = minOf(maxWidth, maxHeight * aspect)
        val fitH = fitW / aspect
        Box(Modifier.size(fitW, fitH).clipToBounds()) {
            AndroidView(
                factory = { c -> TextureView(c).also { tv -> player.setVideoTextureView(tv) } },
                modifier = Modifier.fillMaxSize().graphicsLayer {
                    val tr = viewTransform(view)
                    scaleX = tr[0].toFloat(); scaleY = tr[0].toFloat()
                    translationX = (tr[1] * size.width).toFloat(); translationY = (tr[2] * size.height).toFloat()
                },
            )
        }
    }
}

@Composable
private fun OverlayButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true, accent: Boolean = false) {
    Button(
        onClick = onClick, enabled = enabled, modifier = modifier,
        colors = ButtonDefaults.buttonColors(
            containerColor = if (accent) REC_RED else OVERLAY_BG, contentColor = Color.White,
            disabledContainerColor = OVERLAY_BG.copy(alpha = 0.3f), disabledContentColor = Color.White.copy(alpha = 0.4f),
        ),
        contentPadding = PaddingValues(horizontal = 14.dp, vertical = 8.dp),
    ) { Text(text, fontWeight = FontWeight.SemiBold) }
}
