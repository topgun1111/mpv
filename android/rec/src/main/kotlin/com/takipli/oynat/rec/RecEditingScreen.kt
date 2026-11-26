package com.takipli.oynat.rec

import android.net.Uri
import android.view.TextureView
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.VideoFrameProcessor
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.transformer.Transformer
import com.takipli.oynat.core.Grade
import com.takipli.oynat.core.GradeControl
import com.takipli.oynat.core.GradeQuality
import com.takipli.oynat.core.HazePreset
import java.io.File
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt

/** A dedicated editor: original camera keys/zoom/recording state are never touched. */
@Composable
internal fun RecEditingScreen(source: Uri, info: VideoInfo, initialPosition: Long, onClose: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val host = LocalView.current
    var grade by remember { mutableStateOf(Grade()) }
    var original by remember { mutableStateOf(false) }
    var options by remember { mutableStateOf(EditOutput()) }
    var showOptions by remember { mutableStateOf(false) }
    var largePreview by remember { mutableStateOf(false) }
    var active by remember { mutableStateOf<Transformer?>(null) }
    var saving by remember { mutableStateOf(false) }
    var temp by remember { mutableStateOf<File?>(null) }
    var status by remember { mutableStateOf("") }
    var progress by remember { mutableFloatStateOf(0f) }
    var pos by remember { mutableLongStateOf(initialPosition) }
    var duration by remember { mutableLongStateOf((info.durationS * 1000).toLong().coerceAtLeast(1)) }
    var playing by remember { mutableStateOf(false) }
    val ref = remember { AtomicReference(Grade()) }
    val disposed = remember { AtomicReference(false) }
    val player = remember { ExoPlayer.Builder(ctx, EditingRenderersFactory(ctx)).build() }
    val effect = remember { GradeEffect { ref.get() } }
    val busy = active != null || saving

    fun load(at: Long) {
        player.setVideoEffects(listOfNotNull(RecExporter.rotationEffect(info.userRot), effect))
        player.setMediaItem(MediaItem.fromUri(source)); player.prepare(); player.seekTo(at); player.pause()
    }
    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onPlayerError(error: PlaybackException) {
                status = "Preview failed: " + (error.cause?.message ?: error.errorCodeName)
            }
        }
        player.addListener(listener)
        load(initialPosition)
        onDispose {
            disposed.set(true)
            active?.cancel()
            // Completed exports may be copying in the IO coroutine; never remove its input mid-copy.
            if (!saving) temp?.delete()
            player.removeListener(listener); player.release()
            host.keepScreenOn = false
        }
    }
    SideEffect { host.keepScreenOn = true }
    LaunchedEffect(player) {
        while (true) {
            if (active == null && !saving) {
                pos = player.currentPosition.coerceAtLeast(0)
                if (player.duration > 0) duration = player.duration
                playing = player.isPlaying
            }
            delay(100)
        }
    }
    // A same-position seek may be ignored by ExoPlayer. Media3 1.8 supports
    // REDRAW of its cached input frame, without seeking or restarting playback.
    // Keep the GL thread's snapshot current, even during continuous slider drags.
    SideEffect { ref.set(if (original) Grade() else grade) }
    LaunchedEffect(player) {
        snapshotFlow { Triple(grade, original, active != null || saving) }
            .collect { (settings, before, exporting) ->
                ref.set(if (before) Grade() else settings)
                if (!exporting && !player.isPlaying && player.mediaItemCount > 0 &&
                    player.playerError == null
                ) {
                    player.setVideoEffects(VideoFrameProcessor.REDRAW)
                }
                // snapshotFlow conflates rapid updates; limit redraw requests to 20/s.
                delay(50)
            }
    }
    LaunchedEffect(active) {
        val t = active ?: return@LaunchedEffect
        while (active === t) {
            progress = RecExporter.progress(t).coerceAtLeast(0f)
            delay(200)
        }
    }
    fun cancel() {
        val t = active ?: return
        active = null
        t.cancel()
        temp?.delete(); temp = null
        status = "Export cancelled"
        load(pos)
    }
    BackHandler {
        if (active != null) cancel()
        else if (!saving && largePreview) largePreview = false
        else if (!saving) onClose()
    }

    fun export() {
        if (busy) return
        val at = player.currentPosition.coerceAtLeast(0)
        val snapshot = grade
        val selected = options
        val out = File(ctx.cacheDir, "edit-" + UUID.randomUUID() + ".mp4")
        temp = out
        progress = 0f; status = "Preparing edited video..."
        player.pause(); player.stop(); player.clearMediaItems()
        var finished = false
        fun finish(message: String) {
            finished = true
            out.delete()
            if (disposed.get()) return
            active = null; saving = false
            temp = null
            status = message
            load(at)
        }
        try {
            val t = EditExporter.start(ctx, source, info, snapshot, selected, out,
                onDone = {
                    if (disposed.get()) {
                        out.delete()
                    } else {
                    active = null; saving = true
                    status = "Saving edited video..."
                    scope.launch {
                        try {
                            val name = "Edited_" + UUID.randomUUID().toString().take(8) + ".mp4"
                            withContext(Dispatchers.IO) {
                                try { RecExporter.saveToMovies(ctx, out, name) } finally { out.delete() }
                            }
                            finish("Saved to Movies/TakipliOynat/" + name)
                        } catch (e: CancellationException) {
                            out.delete()
                            throw e
                        } catch (e: Exception) { finish("Save failed: " + e.message) }
                    }
                    }
                },
                onError = { e -> finish("Export failed: " + e.errorCodeName + " " + (e.message ?: "")) },
            )
            if (!finished && !saving) active = t
        } catch (e: Exception) {
            finish("Export failed: " + e.message)
        }
    }

    Column(
        Modifier.fillMaxSize().safeDrawingPadding().padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onClose, enabled = !busy) { Text("Back") }
            Text("Editing", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            TextButton(onClick = { showOptions = true }, enabled = !busy) { Text("Export settings") }
        }
        BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
            // Unfolded screens and landscape use the full height of the workspace.
            // Narrow portrait screens give the preview most of the available height.
            val sideBySide = maxWidth >= 500.dp || maxWidth > maxHeight * 1.2f
            if (sideBySide) {
                Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    EditingPreview(
                        player, info, pos, duration, playing, original, busy, largePreview,
                        onSeek = { pos = it; player.seekTo(it) },
                        onCompare = { original = !original },
                        onExpand = { largePreview = !largePreview },
                        modifier = Modifier.weight(1.15f).fillMaxHeight(),
                    )
                    if (!largePreview) {
                        EditingControls(grade, original, busy,
                            onGrade = { grade = it; original = false },
                            modifier = Modifier.weight(1f).fillMaxHeight(),
                        )
                    }
                }
            } else {
                Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    EditingPreview(
                        player, info, pos, duration, playing, original, busy, largePreview,
                        onSeek = { pos = it; player.seekTo(it) },
                        onCompare = { original = !original },
                        onExpand = { largePreview = !largePreview },
                        modifier = Modifier.weight(1.8f).fillMaxWidth(),
                    )
                    if (!largePreview) {
                        EditingControls(grade, original, busy,
                            onGrade = { grade = it; original = false },
                            modifier = Modifier.weight(1f).fillMaxWidth(),
                        )
                    }
                }
            }
        }
        if (busy) LinearProgressIndicator(progress = { progress }, modifier = Modifier.fillMaxWidth())
        if (status.isNotBlank()) Text(status, style = MaterialTheme.typography.bodySmall, maxLines = 3)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            if (active != null) OutlinedButton(onClick = { cancel() }) { Text("Cancel") }
            Text(if (options.hevc) "HEVC" else "H.264", modifier = Modifier.weight(1f))
            Button(onClick = { showOptions = true }, enabled = !busy) { Text("Export edited video") }
        }
    }
    if (showOptions) {
        AlertDialog(
            onDismissRequest = { showOptions = false },
            title = { Text("Export options") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Quality")
                    GradeQuality.entries.forEach { q ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(selected = options.quality == q, onClick = { options = options.copy(quality = q) })
                            Text(q.label)
                        }
                    }
                    if (options.quality == GradeQuality.CUSTOM) {
                        Text("Target: " + options.customMbps + " Mbps")
                        Slider(value = options.customMbps.toFloat(), onValueChange = { options = options.copy(customMbps = it.roundToInt()) },
                            valueRange = 2f..100f)
                    }
                    Text("Target bitrate: " + String.format(java.util.Locale.ROOT, "%.1f Mbps", options.bitrate(info) / 1e6))
                    Text("Codec")
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterChip(selected = !options.hevc, onClick = { options = options.copy(hevc = false) }, label = { Text("H.264") })
                        FilterChip(selected = options.hevc, onClick = { options = options.copy(hevc = true) }, label = { Text("HEVC") })
                    }
                    Text("Encoder")
                    EditEncoder.entries.forEach { enc ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(selected = options.encoder == enc, onClick = { options = options.copy(encoder = enc) })
                            Text(enc.label)
                        }
                    }
                    Text("Original resolution and speed. Saved to Movies/TakipliOynat. GPU colour processing; encoder availability depends on your device.",
                        style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = { Button(onClick = { showOptions = false; export() }) { Text("Export") } },
            dismissButton = { TextButton(onClick = { showOptions = false }) { Text("Done") } },
        )
    }
}

/** Controls never cover the actual image. The preview keeps its aspect ratio, without cropping. */
@Composable
private fun EditingPreview(
    player: ExoPlayer, info: VideoInfo, pos: Long, duration: Long,
    playing: Boolean, original: Boolean, busy: Boolean, large: Boolean,
    onSeek: (Long) -> Unit, onCompare: () -> Unit, onExpand: () -> Unit, modifier: Modifier,
) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(2.dp)) {
        BoxWithConstraints(
            Modifier.weight(1f).fillMaxWidth().background(Color.Black),
            contentAlignment = Alignment.Center,
        ) {
            val aspect = (info.width.toFloat() / info.height.coerceAtLeast(1)).coerceIn(0.1f, 10f)
            val w = minOf(maxWidth, maxHeight * aspect)
            AndroidView(
                factory = { c -> TextureView(c).also { player.setVideoTextureView(it) } },
                onRelease = { player.clearVideoTextureView(it) },
                modifier = Modifier.size(w, w / aspect),
            )
            Text(
                if (original) "ORIGINAL" else "EDITED",
                modifier = Modifier.align(Alignment.TopStart).background(Color.Black.copy(alpha = 0.65f))
                    .padding(horizontal = 8.dp, vertical = 4.dp),
                color = Color.White, style = MaterialTheme.typography.labelSmall,
            )
        }
        Slider(
            value = pos.toFloat().coerceIn(0f, duration.toFloat().coerceAtLeast(1f)),
            onValueChange = { onSeek(it.toLong()) },
            valueRange = 0f..duration.toFloat().coerceAtLeast(1f),
            enabled = !busy, modifier = Modifier.fillMaxWidth(),
        )
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(onClick = {
                if (player.isPlaying) player.pause() else {
                    if (player.playbackState == Player.STATE_ENDED) player.seekTo(0)
                    player.play()
                }
            }, enabled = !busy, contentPadding = PaddingValues(horizontal = 8.dp)) {
                Text(if (playing) "Pause" else "Play")
            }
            TextButton(onClick = onCompare, enabled = !busy, contentPadding = PaddingValues(horizontal = 8.dp)) {
                Text(if (original) "Edited" else "Original")
            }
            TextButton(onClick = onExpand, enabled = !busy, contentPadding = PaddingValues(horizontal = 8.dp)) {
                Text(if (large) "Controls" else "Enlarge")
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun EditingControls(
    grade: Grade, original: Boolean, busy: Boolean, onGrade: (Grade) -> Unit, modifier: Modifier,
) {
    Column(modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            HazePreset.entries.forEach { p ->
                FilterChip(selected = grade == p.grade && !original, enabled = !busy,
                    onClick = { onGrade(p.grade) }, label = { Text(p.label) })
            }
            OutlinedButton(onClick = { onGrade(Grade()) }, enabled = !busy) { Text("Reset") }
        }
        GradeControl.entries.forEach { c ->
            Column(Modifier.fillMaxWidth()) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(c.label, style = MaterialTheme.typography.labelLarge)
                    Text(grade[c].toString(), style = MaterialTheme.typography.labelLarge)
                }
                Slider(value = grade[c].toFloat(), onValueChange = {
                    onGrade(grade.with(c, it.roundToInt()))
                }, valueRange = c.min.toFloat()..c.max.toFloat(),
                    enabled = !busy, modifier = Modifier.fillMaxWidth())
            }
        }
    }
}
