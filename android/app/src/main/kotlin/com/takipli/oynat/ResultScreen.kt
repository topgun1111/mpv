package com.takipli.oynat

import android.net.Uri
import android.os.SystemClock
import android.view.TextureView
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Slider
import androidx.compose.material3.Tab
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.transformer.Transformer
import com.takipli.oynat.core.CamMode
import com.takipli.oynat.core.CamPath
import com.takipli.oynat.core.CamPos
import com.takipli.oynat.core.CamZoom
import com.takipli.oynat.core.RecSeg
import com.takipli.oynat.core.appendKey
import com.takipli.oynat.core.applyGestureAt
import com.takipli.oynat.core.mergeSegment
import com.takipli.oynat.core.mergeSegments
import com.takipli.oynat.core.View as CamView
import com.takipli.oynat.core.Config
import com.takipli.oynat.core.Formats
import com.takipli.oynat.core.PRESETS
import com.takipli.oynat.core.StabPlan
import com.takipli.oynat.core.Target
import com.takipli.oynat.core.TrackDoc
import com.takipli.oynat.core.enoughSpaceForExport
import com.takipli.oynat.core.exportBitrate
import com.takipli.oynat.core.exportBytesNeeded
import com.takipli.oynat.core.progressStallFinding
import com.takipli.oynat.core.Tuning
import com.takipli.oynat.core.rebuildViews
import com.takipli.oynat.core.viewAtSmooth
import com.takipli.oynat.core.viewTransform
import com.takipli.oynat.core.of
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.Locale

/** Part 13: play the video with the follow-camera views, tune them with sliders, switch the body part, save. */
@Composable
fun ResultScreen(file: String, onBack: () -> Unit) {
    var doc by remember { mutableStateOf<TrackDoc?>(null) }
    var err by remember { mutableStateOf("") }
    val ctx0 = LocalContext.current
    LaunchedEffect(file) {
        try { doc = withContext(Dispatchers.IO) { Formats.parseTrack(File(file).readText()) } }
        catch (e: Throwable) { ErrorLog.record(ctx0, "result-load", e); err = Safety.friendly(ctx0, e) }
    }
    val d = doc
    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        TextButton(onClick = onBack) { Text(stringResource(R.string.back)) }
        when {
            err.isNotEmpty() -> Text(err)
            d == null -> Text(stringResource(R.string.result_loading))
            d.target == null -> Text(stringResource(R.string.result_no_target))
            else -> ResultBody(d, d.target!!, File(file))
        }
    }
}

@Composable
private fun ResultBody(doc: TrackDoc, base: Target, file: File) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val cfg = remember { Config(lostBridgeS = 6.0) } // app default: keep the zoom when something covers the subject for a few seconds
    // Result of a cancelled scan (`*.cancelled.track.json`): only the processed part exists, so preview and export stop there.
    // An A-B scan (`doc.range`) is cut the same way, and also starts at A.
    val startMs: Long = remember(doc) { ((doc.range?.firstOrNull() ?: 0.0) * 1000).toLong().coerceAtLeast(0L) }
    val partEndMs: Long? = remember(doc, file) {
        if (file.name.endsWith(".cancelled.track.json") || doc.range != null) doc.samples.lastOrNull()?.let { com.takipli.oynat.core.partialEndMs(it.t, doc.sampleFps, doc.video.duration) } else null
    }
    var target by remember { mutableStateOf(base) }
    var tuning by remember { mutableStateOf(Tuning.of(cfg).copy(lostBridgeS = 4.0)) } // keep the zoom through a few seconds of occlusion by default
    var views by remember { mutableStateOf(doc.views) }
    var follow by remember { mutableStateOf(true) }
    // Kayıt modu: oynarken pinch = zoom, sürükle = konum; kayıt anahtar kareleri otomatik kadrajın yerine geçer
    var recording by remember { mutableStateOf(false) }
    var recView by remember { mutableStateOf(CamView(0.0, 0.0, 0.0)) }
    var recKeys by remember { mutableStateOf<List<List<Double>>>(emptyList()) }
    var manual by remember { mutableStateOf<List<RecSeg>>(emptyList()) } // biten kayıtlar; ayar değişince otomatik kadraj yeniden hesaplanır, kayıtlar üstüne yeniden işlenir
    var playing by remember { mutableStateOf(false) }
    var posMs by remember { mutableLongStateOf(0L) }
    var durMs by remember { mutableLongStateOf(partEndMs ?: (doc.video.duration * 1000).toLong().coerceAtLeast(1)) }
    var saved by remember { mutableStateOf("") }
    var job by remember { mutableStateOf<Job?>(null) }
    var hevc by remember { mutableStateOf(false) }
    var stab by remember { mutableStateOf(false) } // EIS-style stabilization of the export (needs one slow pass over every frame): opt-in, so opening the preview never starts it
    var camPath by remember { mutableStateOf<CamPath?>(null) }
    var stabBusy by remember { mutableStateOf(false) }
    var stabP by remember { mutableStateOf(0f) }
    var stabMsg by remember { mutableStateOf("") }
    var exporter by remember { mutableStateOf<Transformer?>(null) }
    var exportP by remember { mutableStateOf(0f) }
    var exportMsg by remember { mutableStateOf("") }
    var playerMsg by remember { mutableStateOf("") }
    var readable by remember { mutableStateOf(true) } // false = the picked video cannot be opened any more (moved, deleted, SAF grant lost)
    val exporting = exporter != null
    val view = LocalView.current
    SideEffect { view.keepScreenOn = exporting } // the export runs in this process: keep the screen (and the app) alive
    DisposableEffect(Unit) { onDispose { exporter?.cancel(); view.keepScreenOn = false } }
    LaunchedEffect(stab) {
        if (!stab || camPath != null) return@LaunchedEffect
        stabBusy = true; stabP = 0f; stabMsg = ""
        try {
            val camFile = File(file.path.replace(".track.json", ".cam.json"))
            val sig = DenseCamera.signature(doc)
            camPath = withContext(Dispatchers.Default) {
                DenseCamera.load(camFile, sig)
                    ?: DenseCamera.analyze(ctx, Uri.parse(doc.video.path), doc, sig) { stabP = it }.also { DenseCamera.save(camFile, it) }
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Throwable) {
            ErrorLog.record(ctx, "stabilize", e)
            stabMsg = Safety.friendly(ctx, e)
            stab = false
        } finally {
            stabBusy = false
        }
    }
    LaunchedEffect(exporter) {
        val t = exporter ?: return@LaunchedEffect
        val t0 = SystemClock.elapsedRealtime()
        val hist = ArrayList<Pair<Double, Double>>()
        var lastCheck = 0L
        while (exporter === t) {
            exportP = Exporter.progress(t)
            val now = SystemClock.elapsedRealtime()
            if (exportP >= 0f) hist.add((now - t0) / 1000.0 to exportP.toDouble())
            if (hist.size > 400) hist.removeAt(0)
            if (now - lastCheck >= 15_000) { // Debug Part 2: stall detector (progress frozen) + a progress line every 15 s
                lastCheck = now
                progressStallFinding("export", hist)?.let { Diag.event(ctx, "export", it) }
                Diag.note(ctx, "export", "EXPORT_TICK", "${(exportP * 100).toInt()} % after ${(now - t0) / 1000} s | ${Diag.vitals(ctx)}")
            }
            delay(300)
        }
    }

    val rot = remember(doc) { UserRot.forDoc(ctx, doc) } // the turn this scan was made with (preview and export must match the tracking data, not a later setting)
    val player = remember { ExoPlayer.Builder(ctx).build() }
    DisposableEffect(Unit) { onDispose { player.release() } }
    var volume by remember { mutableStateOf(1f) }; var muted by remember { mutableStateOf(false) } // preview volume only; the export is unaffected
    SideEffect { player.volume = if (muted) 0f else volume }
    // The preview player keeps a 4K decoder and tens of MB of Java-heap buffers. The export (Media3 Transformer, 4K + stabilization)
    // needs that memory: build #50 died with OutOfMemoryError (heap 255/256 MB) right after Export. Park it while exporting.
    fun parkPlayer() { runCatching { player.pause(); player.stop(); player.clearMediaItems() } }
    fun resumePlayer() { runCatching { player.setMediaItem(MediaItem.fromUri(Uri.parse(doc.video.path))); player.prepare() } }
    LaunchedEffect(Unit) {
        readable = withContext(Dispatchers.IO) { Safety.videoReadable(ctx, Uri.parse(doc.video.path)) }
        player.addListener(object : Player.Listener {
            override fun onPlayerError(error: PlaybackException) {
                Diag.note(ctx, "player", "PLAYER_ERROR", "${error.errorCodeName} at ${player.currentPosition} ms of ${player.duration} | ${Diag.vitals(ctx)}", com.takipli.oynat.core.Sev.ERROR)
                ErrorLog.record(ctx, "player", error, error.errorCodeName)
                playerMsg = Safety.friendly(ctx, error, error.errorCodeName)
            }
        })
        Exporter.rotationEffect(rot)?.let { player.setVideoEffects(listOf(it)) } // the manual rotation chosen on the pick screen: the preview shows the clip upright, like the scan saw it
        player.setMediaItem(MediaItem.fromUri(Uri.parse(doc.video.path)))
        player.repeatMode = Player.REPEAT_MODE_ALL
        player.prepare()
    }
    LaunchedEffect(player) { // ~display rate while visible; cheap (reads one Long)
        while (true) {
            posMs = player.currentPosition
            if (player.duration > 0) durMs = partEndMs?.coerceAtMost(player.duration) ?: player.duration
            if (partEndMs != null && (posMs >= partEndMs || posMs < startMs)) player.seekTo(startMs) // loop inside the processed part / A-B range
            playing = player.isPlaying
            delay(33)
        }
    }

    fun rebuild(t: Target, tu: Tuning) {
        job?.cancel(); saved = ""
        val segs = manual
        job = scope.launch { views = withContext(Dispatchers.Default) { mergeSegments(rebuildViews(doc, t, cfg, tu, robust = true), segs) } }
    }
    LaunchedEffect(Unit) { rebuild(target, tuning) } // the scan was built without the occlusion bridge: apply it once on open
    fun startRecording() {
        recView = if (follow && views.isNotEmpty()) viewAtSmooth(views, posMs / 1000.0) else CamView(0.0, 0.0, 0.0)
        recKeys = emptyList(); follow = true; recording = true
    }
    fun stopRecording() {
        if (!recording) return
        recording = false
        if (recKeys.isNotEmpty()) {
            val seg = RecSeg(recKeys.first()[0], recKeys.last()[0], recKeys)
            manual = manual + seg; views = mergeSegment(views, seg); saved = ""
        }
        recKeys = emptyList()
    }
    LaunchedEffect(recording) { // ~25 Hz: yalnız oynarken anahtar kare (duraklatma/geri sarma anahtar üretmez)
        while (recording) {
            if (playing) recKeys = appendKey(recKeys, posMs / 1000.0, recView)
            delay(40)
        }
    }

    fun clock(ms: Long) = String.format(Locale.ROOT, "%d:%02d", ms / 60000, (ms / 1000) % 60)
    val vw = doc.video.w.coerceAtLeast(1); val vh = doc.video.h.coerceAtLeast(1)
    if (rot != 0) Text(stringResource(R.string.result_rotated, rot), fontSize = 12.sp)
    // Bound the result preview just like Manual Camera: portrait clips must not consume the whole page.
    BoxWithConstraints(
        Modifier.fillMaxWidth().height(300.dp)
            .clip(androidx.compose.foundation.shape.RoundedCornerShape(12.dp))
            .clipToBounds(),
        contentAlignment = Alignment.Center,
    ) {
        val videoAspect = (vw.toFloat() / vh.toFloat()).coerceIn(0.25f, 4f)
        val fittedWidth = minOf(maxWidth, maxHeight * videoAspect)
        val fittedHeight = fittedWidth / videoAspect
        Box(
            Modifier.size(width = fittedWidth, height = fittedHeight)
                .clipToBounds()
                .pointerInput(recording) {
                    if (recording) detectTransformGestures { centroid, pan, zoom, _ ->
                        val w = size.width.toDouble(); val h = size.height.toDouble()
                        recView = applyGestureAt(recView, centroid.x / w, centroid.y / h, pan.x / w, pan.y / h, zoom.toDouble(), 3.5)
                    }
                }
        ) {
            AndroidView(
                factory = { c -> TextureView(c).also { player.setVideoTextureView(it) } },
                modifier = Modifier.fillMaxSize().graphicsLayer {
                    if (recording || (follow && views.isNotEmpty())) {
                        val tr = viewTransform(if (recording) recView else viewAtSmooth(views, posMs / 1000.0))
                        scaleX = tr[0].toFloat(); scaleY = tr[0].toFloat()
                        translationX = (tr[1] * size.width).toFloat(); translationY = (tr[2] * size.height).toFloat()
                    }
                },
            )
            if (recording) Text(stringResource(R.string.rec_badge), color = androidx.compose.ui.graphics.Color.Red, modifier = Modifier.align(Alignment.TopStart).padding(8.dp))
            // HUD: which camera is driving the preview right now (behaviour, zoom strategy, live zoom)
            run {
                val auto = !recording && follow && views.isNotEmpty()
                val cv = if (recording) recView else if (auto) viewAtSmooth(views, posMs / 1000.0) else null
                val zoomX = String.format(Locale.ROOT, "%.2f", Math.pow(2.0, Math.max(cv?.zoom ?: 0.0, 0.0)))
                val dir = tuning.director
                val modeRes = when (dir.mode) { CamMode.SIZE -> R.string.cam_mode_size; CamMode.CINEMATIC -> R.string.cam_mode_cine; CamMode.FOLLOW -> R.string.cam_mode_follow }
                val zoomRes = when (dir.zoom) { CamZoom.ZOOM_CROP -> R.string.cam_zoom_crop; CamZoom.CROP_ONLY -> R.string.cam_zoom_only_crop; CamZoom.ZOOM_ONLY -> R.string.cam_zoom_only }
                val line1 = stringResource(if (recording) R.string.cam_hud_manual else if (auto) modeRes else R.string.cam_hud_off)
                val line2 = if (auto) stringResource(zoomRes) + " \u00b7 " + zoomX + "\u00d7" else zoomX + "\u00d7"
                Column(
                    Modifier.align(Alignment.BottomStart).padding(6.dp)
                        .background(androidx.compose.ui.graphics.Color(0x99000000), androidx.compose.foundation.shape.RoundedCornerShape(6.dp))
                        .padding(horizontal = 6.dp, vertical = 3.dp)
                ) {
                    Text(line1, color = androidx.compose.ui.graphics.Color.White, fontSize = 11.sp)
                    Text(line2, color = androidx.compose.ui.graphics.Color.White, fontSize = 11.sp)
                }
            }
        }
    }
    if (!readable) Text(stringResource(R.string.err_video), color = MaterialTheme.colorScheme.error)
    if (playerMsg.isNotEmpty()) Text(playerMsg, color = MaterialTheme.colorScheme.error)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = { if (player.isPlaying) player.pause() else player.play() }) { Text(stringResource(if (playing) R.string.result_pause else R.string.result_play)) }
        FilterChip(selected = follow, enabled = !recording, onClick = { follow = !follow }, label = { Text(stringResource(R.string.result_follow)) })
        Text(clock((posMs - startMs).coerceAtLeast(0L)) + " / " + clock(durMs - startMs), modifier = Modifier.align(androidx.compose.ui.Alignment.CenterVertically), style = MaterialTheme.typography.labelLarge)
    }
    Slider(value = posMs.toFloat(), valueRange = startMs.toFloat()..durMs.toFloat().coerceAtLeast(startMs + 1f), onValueChange = { posMs = it.toLong(); player.seekTo(it.toLong()) })
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        OutlinedButton(onClick = { muted = !muted }) { Text(if (muted || volume == 0f) "\uD83D\uDD07" else "\uD83D\uDD0A") }
        Slider(value = if (muted) 0f else volume, onValueChange = { volume = it; muted = it == 0f }, modifier = Modifier.weight(1f))
    }

    // Oynatma hızı (yalnız önizleme/kayıt için; dışa aktarma hızı değişmez)
    var speed by remember { mutableStateOf(1f) }
    var tab by remember { mutableStateOf(0) }
    ScrollableTabRow(selectedTabIndex = tab, edgePadding = 0.dp) {
        listOf(R.string.tab_target, R.string.tab_camera, R.string.tab_manual, R.string.tab_export).forEachIndexed { i, n ->
            Tab(selected = tab == i, onClick = { tab = i }, text = { Text(stringResource(n)) })
        }
    }
    val isObject = base.free != null
    @Composable
    fun tune(label: Int, v: Double, r: ClosedFloatingPointRange<Float>, set: (Double) -> Tuning) {
        Text(stringResource(label, String.format(Locale.ROOT, "%.2f", v)))
        Slider(value = v.toFloat(), valueRange = r, onValueChange = { tuning = set(it.toDouble()) }, onValueChangeFinished = { rebuild(target, tuning) })
    }
    // Otomatik kameraman: davranış, özne konumu, zoom stratejisi (hepsi kayıtlı taramadan yeniden hesaplanır, tarama tekrarlanmaz)
    @Composable
    fun <T> camRow(title: Int, cur: T, opts: List<Pair<T, Int>>, set: (T) -> Tuning) {
        Text(stringResource(title), style = MaterialTheme.typography.labelLarge)
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            opts.forEach { (v, label) -> FilterChip(selected = cur == v, onClick = { tuning = set(v); rebuild(target, tuning) }, label = { Text(stringResource(label)) }) }
        }
    }
    // endMs != null: partial export of the first endMs (after Cancel); null: the whole clip
    fun startExport(endMs: Long?) {
        val totalMs = (endMs ?: durMs) - startMs
        exportMsg = if (endMs != null && partEndMs == null) ctx.getString(R.string.export_saving_partial) else ""; exportP = 0f
        // preflight: enough storage for the cache file plus the copy in Movies (core `enoughSpaceForExport`)
        val need = exportBytesNeeded(exportBitrate(vw, vh, doc.video.fps, hevc), totalMs / 1000.0)
        val freeCache = Safety.freeBytes(ctx.cacheDir)
        val freeMovies = Safety.freeBytes(ctx.getExternalFilesDir(null) ?: ctx.cacheDir)
        Diag.preflightStorage(ctx, "export (cache copy + Movies copy)", need * 2)
        Diag.note(ctx, "export", "EXPORT_START", "${vw}x$vh ${doc.video.fps} fps ${if (hevc) "HEVC" else "H.264"} stab=$stab ${totalMs / 1000} s${if (endMs != null) " (partial)" else ""}, ~${need shr 20} MB | ${Diag.vitals(ctx)}")
        if (!enoughSpaceForExport(freeCache, freeMovies, need)) {
            exportMsg = ctx.getString(R.string.err_no_space_export, need / 1_048_576L, minOf(freeCache, freeMovies) / 1_048_576L)
            return
        }
        val t0 = SystemClock.elapsedRealtime()
        val tmp = File(ctx.cacheDir, "export/out.mp4")
        var finished = false // an error can arrive before start() returns: then there is no running exporter to remember
        fun finish(msg: String) { finished = true; exporter = null; exportMsg = msg; resumePlayer() }
        val rt = Runtime.getRuntime()
        val heapBefore = (rt.totalMemory() - rt.freeMemory()) shr 20
        parkPlayer(); System.gc()
        Diag.note(ctx, "export", "EXPORT_PREP", "player parked; heap $heapBefore -> ${(rt.totalMemory() - rt.freeMemory()) shr 20} of ${rt.maxMemory() shr 20} MB, stab=$stab")
        val started = try { Exporter.start(
            ctx, Uri.parse(doc.video.path), views, tmp, vw, vh, doc.video.fps, hevc,
            plan = if (stab) camPath?.let { StabPlan(it, views, vw, vh) } else null,
            startMs = startMs, endMs = endMs,
            rot = rot,
            onDone = {
                scope.launch {
                    val name = "Takipli_" + java.text.SimpleDateFormat("yyyyMMdd_HHmmss", Locale.ROOT).format(java.util.Date()) + ".mp4"
                    try {
                        withContext(Dispatchers.IO) { Exporter.saveToMovies(ctx, tmp, name); tmp.delete() }
                        val wall = (SystemClock.elapsedRealtime() - t0) / 1000.0
                        val x = if (wall > 0) totalMs / 1000.0 / wall else 0.0
                        Diag.event(ctx, "export", com.takipli.oynat.core.speedFinding("export", x, 0.3))
                        finish(if (endMs == null) ctx.getString(R.string.export_done, name, String.format(Locale.ROOT, "%.2f", x)) else ctx.getString(R.string.export_partial_done, name, String.format(Locale.ROOT, "%.1f", totalMs / 1000.0)))
                    } catch (e: Throwable) {
                        ErrorLog.record(ctx, "export-save", e)
                        tmp.delete()
                        finish(Safety.friendly(ctx, e))
                    }
                }
            },
            onError = { e ->
                Diag.note(ctx, "export", "EXPORT_FAIL", "${e.errorCodeName} after ${(SystemClock.elapsedRealtime() - t0) / 1000} s | ${Diag.vitals(ctx)}", com.takipli.oynat.core.Sev.ERROR)
                ErrorLog.record(ctx, "export", e, e.errorCodeName)
                tmp.delete()
                finish(Safety.friendly(ctx, e, e.errorCodeName))
            },
        ) } catch (e: Throwable) {
            ErrorLog.record(ctx, "export-start", e)
            finish(Safety.friendly(ctx, e))
            null
        }
        if (started != null && !finished) exporter = started
    }
    androidx.compose.material3.Surface(tonalElevation = 2.dp, shape = androidx.compose.foundation.shape.RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            when (tab) {
                0 -> { // izleme yöntemine özgü ayarlar
                    Text(stringResource(if (isObject) R.string.track_kind_object else R.string.track_kind_person), style = MaterialTheme.typography.titleSmall)
                    if (isObject) {
                        Text(stringResource(R.string.track_object_hint), fontSize = 12.sp)
                    } else {
                        Text(stringResource(R.string.pick_part), style = MaterialTheme.typography.labelLarge)
                        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            PRESETS.keys.forEach { p ->
                                FilterChip(selected = target.preset == p, onClick = { target = Target(base.id, preset = p, linked = base.linked); rebuild(target, tuning) }, label = { Text(p.replace('_', ' ')) })
                            }
                        }
                        tune(R.string.tune_box, tuning.kpBox, 0.04f..0.4f) { tuning.copy(kpBox = it) }
                    }
                    tune(R.string.tune_hold, tuning.lostHoldS, 0f..3f) { tuning.copy(lostHoldS = it) }
                    tune(R.string.tune_bridge, tuning.lostBridgeS, 0f..15f) { tuning.copy(lostBridgeS = it) }
                }
                1 -> {
                    Text(stringResource(R.string.cam_title), style = MaterialTheme.typography.titleSmall)
                    camRow(R.string.cam_mode, tuning.director.mode, listOf(CamMode.SIZE to R.string.cam_mode_size, CamMode.CINEMATIC to R.string.cam_mode_cine, CamMode.FOLLOW to R.string.cam_mode_follow)) { tuning.copy(director = tuning.director.copy(mode = it)) }
                    camRow(R.string.cam_pos, tuning.director.pos, listOf(CamPos.LEFT to R.string.cam_pos_left, CamPos.CENTER to R.string.cam_pos_center, CamPos.RIGHT to R.string.cam_pos_right)) { tuning.copy(director = tuning.director.copy(pos = it)) }
                    camRow(R.string.cam_zoom, tuning.director.zoom, listOf(CamZoom.ZOOM_CROP to R.string.cam_zoom_crop, CamZoom.CROP_ONLY to R.string.cam_zoom_only_crop, CamZoom.ZOOM_ONLY to R.string.cam_zoom_only)) { tuning.copy(director = tuning.director.copy(zoom = it)) }
                    tune(R.string.tune_fill, tuning.targetFill, 0.10f..0.85f) { tuning.copy(targetFill = it) }
                    tune(R.string.tune_maxzoom, tuning.maxZoom, 0.5f..3.5f) { tuning.copy(maxZoom = it) }
                    tune(R.string.tune_follow, tuning.followAlpha, 0.1f..0.9f) { tuning.copy(followAlpha = it) }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = { tuning = Tuning.of(cfg).copy(lostBridgeS = 4.0); rebuild(target, tuning) }) { Text(stringResource(R.string.tune_reset)) }
                    }
                }
                2 -> { // Serbest el: oynarken iki parmakla yakınlaştır + sürükle, hareketler kaydedilir
                    Button(
                        enabled = !exporting && views.isNotEmpty(),
                        colors = if (recording) androidx.compose.material3.ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error) else androidx.compose.material3.ButtonDefaults.buttonColors(),
                        onClick = { if (recording) stopRecording() else startRecording() },
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text(stringResource(if (recording) R.string.rec_stop else R.string.rec_start)) }
                    Text(stringResource(if (recording) R.string.rec_hint else R.string.rec_idle_hint), fontSize = 12.sp)
                    Text(stringResource(R.string.speed_label, String.format(Locale.ROOT, "%.2f", speed)))
                    Slider(value = speed, valueRange = 0.25f..2f, onValueChange = { speed = it; player.setPlaybackParameters(PlaybackParameters(it)) })
                    if (manual.isNotEmpty() && !recording) {
                        Text(stringResource(R.string.rec_count, manual.size), fontSize = 12.sp)
                        OutlinedButton(onClick = { manual = emptyList(); rebuild(target, tuning) }) { Text(stringResource(R.string.rec_clear)) }
                    }
                }
                else -> {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = {
                                scope.launch {
                                    try {
                                        withContext(Dispatchers.IO) {
                                            val out = doc.copy(target = target, views = views)
                                            Scanner.writeAtomic(file, out)
                                            File(file.path.replace(".track.json", ".views.json")).writeText(Formats.encodeViews(Formats.viewsOf(out)))
                                        }
                                        saved = ctx.getString(R.string.result_saved)
                                    } catch (e: Throwable) {
                                        ErrorLog.record(ctx, "save-views", e)
                                        saved = Safety.friendly(ctx, e)
                                    }
                                }
                        }) { Text(stringResource(R.string.result_save)) }
                    }
                    if (saved.isNotEmpty()) Text(saved)
                    if (saved.isNotEmpty()) Text(saved)
                    if (partEndMs != null) Text(stringResource(if (doc.range != null) R.string.result_range_note else R.string.result_partial_note, String.format(Locale.ROOT, "%.1f", startMs / 1000.0), String.format(Locale.ROOT, "%.1f", partEndMs / 1000.0)), fontSize = 12.sp)
                    Text(stringResource(R.string.export_title), style = MaterialTheme.typography.labelLarge)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterChip(selected = !hevc, enabled = !exporting, onClick = { hevc = false }, label = { Text("H.264") })
                        FilterChip(selected = hevc, enabled = !exporting, onClick = { hevc = true }, label = { Text("HEVC") })
                    }
                    FilterChip(selected = stab, enabled = !exporting && !stabBusy && partEndMs == null, onClick = { stab = !stab }, label = { Text(stringResource(R.string.stab_chip)) })
                    if (stabBusy) {
                        LinearProgressIndicator(progress = { stabP.coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
                        Text(stringResource(R.string.stab_working))
                    }
                    if (stabMsg.isNotEmpty()) Text(stabMsg)
                    BatteryWarning()
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(enabled = !exporting && !stabBusy && !recording && views.isNotEmpty() && readable, onClick = { startExport(partEndMs) }) { Text(stringResource(R.string.export_start)) }
                        OutlinedButton(enabled = exporting, onClick = {
                                val p = exportP
                                Diag.note(ctx, "export", "EXPORT_CANCEL", "cancelled by user at ${(p * 100).toInt()} %")
                                exporter?.cancel(); exporter = null
                                // Cancel keeps what is done: the first part (a little under the reported progress) is exported again as a short clip. Too little done: nothing to keep.
                                val endMs = startMs + (p * (durMs - startMs) * 0.98).toLong()
                                if (p >= 0.02f && endMs - startMs >= 1000L) startExport(endMs) else { exportMsg = ctx.getString(R.string.export_cancelled); resumePlayer() }
                        }) { Text(stringResource(R.string.scan_cancel)) }
                    }
                    if (exporting) {
                        if (exportP >= 0f) LinearProgressIndicator(progress = { exportP.coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
                        Text(stringResource(R.string.export_keep_open))
                    }
                    if (exportMsg.isNotEmpty()) Text(exportMsg)
                }
            }
        }
    }
}
