package com.takipli.oynat

import android.content.Intent
import android.net.Uri
import android.os.SystemClock
import android.view.TextureView
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.transformer.Transformer
import com.takipli.oynat.core.View as CamView
import com.takipli.oynat.core.ViewKey
import com.takipli.oynat.core.appendKey
import com.takipli.oynat.core.applyGestureAt
import com.takipli.oynat.core.viewTransform
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.pow

/** Standalone manual camera mode: play any clip, pinch/drag the live frame, record the camera path, then render it to MP4. */
@Composable
fun RecordScreen(onBack: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var uri by remember { mutableStateOf<Uri?>(null) }
    var info by remember { mutableStateOf<VideoInfo?>(null) }
    var error by remember { mutableStateOf("") }
    var view by remember { mutableStateOf(CamView(0.0, 0.0, 0.0)) }
    var keys by remember { mutableStateOf<List<ViewKey>>(emptyList()) }
    var recording by remember { mutableStateOf(false) }
    var playing by remember { mutableStateOf(false) }
    var posMs by remember { mutableLongStateOf(0L) }
    var durationMs by remember { mutableLongStateOf(1L) }
    var exporter by remember { mutableStateOf<Transformer?>(null) }
    var exportProgress by remember { mutableStateOf(0f) }
    var exportMessage by remember { mutableStateOf("") }
    var hevc by remember { mutableStateOf(false) }
    val player = remember { ExoPlayer.Builder(ctx).build() }
    val hostView = LocalView.current
    SideEffect { hostView.keepScreenOn = recording || exporter != null }
    DisposableEffect(Unit) { onDispose { exporter?.cancel(); player.release(); hostView.keepScreenOn = false } }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { picked ->
        if (picked != null) {
            runCatching { ctx.contentResolver.takePersistableUriPermission(picked, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
            scope.launch {
                try {
                    val vi = withContext(Dispatchers.IO) { VideoDecoder.probe(ctx, picked) }
                    info = vi; uri = picked; error = ""; keys = emptyList(); view = CamView(0.0, 0.0, 0.0)
                    durationMs = (vi.durationS * 1000).toLong().coerceAtLeast(1); posMs = 0
                    player.setVideoEffects(listOfNotNull(Exporter.rotationEffect(vi.userRot)))
                    player.setMediaItem(MediaItem.fromUri(picked)); player.prepare(); player.pause()
                } catch (t: Throwable) { error = Safety.friendly(ctx, t); info = null; uri = null }
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
            if (player.isPlaying) keys = appendKey(keys, player.currentPosition.coerceAtLeast(0) / 1000.0, view)
            delay(33)
        }
    }
    LaunchedEffect(exporter) {
        val active = exporter ?: return@LaunchedEffect
        while (exporter === active) {
            exportProgress = Exporter.progress(active).coerceAtLeast(0f)
            delay(250)
        }
    }

    fun restorePreview(source: Uri) {
        runCatching { player.setMediaItem(MediaItem.fromUri(source)); player.prepare(); player.seekTo(posMs); player.pause() }
    }

    fun startExport() {
        val source = uri ?: return
        val vi = info ?: return
        if (keys.isEmpty()) { exportMessage = "Record a camera move before exporting."; return }
        val finalKeys = if (keys.size == 1) keys + listOf(keys.first().mapIndexed { i, v -> if (i == 0) v + 0.04 else v }) else keys
        val out = File(ctx.cacheDir, "manual-camera.mp4")
        exportMessage = "Preparing video…"; exportProgress = 0f
        player.pause(); player.stop(); player.clearMediaItems(); System.gc()
        var completed = false
        fun finish(message: String) { completed = true; exporter = null; exportMessage = message; restorePreview(source) }
        try {
            val started = Exporter.start(
                ctx, source, finalKeys, out, vi.width, vi.height,
                (vi.frameRate ?: 30.0).coerceIn(1.0, 60.0), hevc,
                rot = vi.userRot,
                onDone = {
                    scope.launch {
                        try {
                            val name = "Takipli_Manual_" + SimpleDateFormat("yyyyMMdd_HHmmss", Locale.ROOT).format(Date()) + ".mp4"
                            withContext(Dispatchers.IO) { Exporter.saveToMovies(ctx, out, name); out.delete() }
                            finish("Saved to Movies/TakipliOynat/$name")
                        } catch (t: Throwable) { out.delete(); finish(Safety.friendly(ctx, t)) }
                    }
                },
                onError = { e -> out.delete(); finish(Safety.friendly(ctx, e, e.errorCodeName)) },
            )
            if (!completed) exporter = started
        } catch (t: Throwable) { finish(Safety.friendly(ctx, t)) }
    }

    Column(
        Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        TextButton(onClick = onBack, enabled = exporter == null && !recording) { Text("← Back") }
        Text("Manual camera", style = MaterialTheme.typography.headlineSmall)
        Text("Play a video, then pinch to zoom and drag to reframe. Record captures your camera movement and exports a new video.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedButton(onClick = { picker.launch(arrayOf("video/*")) }, enabled = exporter == null && !recording, modifier = Modifier.fillMaxWidth()) { Text(if (uri == null) "Choose video" else "Change video") }
        if (error.isNotEmpty()) Text(error, color = MaterialTheme.colorScheme.error)
        val vi = info
        if (uri != null && vi != null) {
            // Bounded viewport: portrait videos no longer expand the page beyond the screen.
            androidx.compose.foundation.layout.BoxWithConstraints(
                Modifier.fillMaxWidth().height(300.dp).clip(RoundedCornerShape(16.dp))
                    .clipToBounds().background(Color.Black),
                contentAlignment = Alignment.Center
            ) {
                val videoAspect = (vi.width.toFloat() / vi.height.toFloat()).coerceIn(0.25f, 4f)
                val fittedWidth = minOf(maxWidth, maxHeight * videoAspect)
                val fittedHeight = fittedWidth / videoAspect
                Box(
                    Modifier.size(width = fittedWidth, height = fittedHeight).clipToBounds()
                        .pointerInput(recording) {
                            if (recording) detectTransformGestures { centroid, pan, zoom, _ ->
                                val w = size.width.toDouble(); val h = size.height.toDouble()
                                view = applyGestureAt(view, centroid.x / w, centroid.y / h, pan.x / w, pan.y / h, zoom.toDouble(), 4.0)
                            }
                        }
                ) {
                    AndroidView(factory = { TextureView(it).also { tv -> player.setVideoTextureView(tv) } }, modifier = Modifier.fillMaxSize().graphicsLayer {
                        val tr = viewTransform(view); scaleX = tr[0].toFloat(); scaleY = tr[0].toFloat()
                        translationX = (tr[1] * size.width).toFloat(); translationY = (tr[2] * size.height).toFloat()
                    })
                    if (recording) Text("● REC", color = Color.Red, modifier = Modifier.padding(12.dp))
                }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { if (player.isPlaying) player.pause() else player.play() }, enabled = exporter == null) { Text(if (playing) "Pause" else "Play") }
                OutlinedButton(onClick = { view = CamView(0.0, 0.0, 0.0) }, enabled = !recording && exporter == null) { Text("Reset view") }
                Text("${String.format(Locale.ROOT, "%.1f", view.zoom.let { 2.0.pow(it) })}×", modifier = Modifier.padding(top = 12.dp))
            }
            Slider(value = posMs.toFloat().coerceIn(0f, durationMs.toFloat()), onValueChange = { if (!recording) { posMs = it.toLong(); player.seekTo(posMs) } }, valueRange = 0f..durationMs.toFloat(), enabled = !recording && exporter == null)
            Text("${posMs / 1000}s / ${durationMs / 1000}s · ${keys.size} camera keyframes", style = MaterialTheme.typography.labelSmall)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    if (!recording) {
                        keys = emptyList(); view = CamView(0.0, 0.0, 0.0); player.seekTo(0); player.play(); recording = true
                    } else { recording = false; player.pause(); keys = appendKey(keys, player.currentPosition / 1000.0, view) }
                }, enabled = exporter == null, modifier = Modifier.weight(1f)) { Text(if (recording) "Stop recording" else "● Start recording") }
                OutlinedButton(onClick = { startExport() }, enabled = !recording && exporter == null && keys.isNotEmpty(), modifier = Modifier.weight(1f)) { Text("Export MP4") }
            }
            if (exporter != null) LinearProgressIndicator(progress = { exportProgress }, modifier = Modifier.fillMaxWidth())
            if (exportMessage.isNotEmpty()) Text(exportMessage, style = MaterialTheme.typography.bodySmall)
        }
    }
}
