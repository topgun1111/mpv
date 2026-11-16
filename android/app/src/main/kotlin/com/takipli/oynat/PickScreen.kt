package com.takipli.oynat

import android.Manifest
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Matrix
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.takipli.oynat.core.normalizeRotation
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.calculateCentroid
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.positionChanged
import androidx.compose.ui.layout.onSizeChanged
import com.takipli.oynat.core.COCO_SKELETON
import com.takipli.oynat.core.Config
import com.takipli.oynat.core.PART_GROUPS
import com.takipli.oynat.core.PART_RGB
import com.takipli.oynat.core.PRESETS
import com.takipli.oynat.core.Pose
import com.takipli.oynat.core.TargetPick
import com.takipli.oynat.core.firstFrameDoc
import com.takipli.oynat.core.highlightPick
import com.takipli.oynat.core.partHit
import com.takipli.oynat.core.partLabel
import com.takipli.oynat.core.pickPersons
import com.takipli.oynat.core.presetForJoint
import com.takipli.oynat.core.presetRegions
import com.takipli.oynat.core.withMinScore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale

private val PICK_FPS = listOf(10, 15, 20, 30, 60)

private fun fmtClock(s: Double): String {
    val v = s.coerceAtLeast(0.0)
    val m = (v / 60).toInt()
    return String.format(Locale.US, "%d:%04.1f", m, v - m * 60)
}

private fun partColor(preset: String?): Color = Color(0xFF000000.toInt() or ((preset?.let { PART_RGB[it] }) ?: 0xFFFFFF))

/**
 * Part 11: open a video -> first frame -> tap a person or a body part (and/or choose a part preset) -> scan in the
 * foreground service ([ScanService]); the screen can go off or the app can be closed while it runs.
 */
@Composable
fun PickScreen(initialMode: String = "body", onBack: () -> Unit, onResult: (String) -> Unit = {}) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val models = remember { ModelStore.list(ctx).filterNot { it.startsWith("sam-") } } // sam-* graphs are not pose models
    val ui by ScanService.state.collectAsState()
    var uri by remember { mutableStateOf<Uri?>(null) }
    var videoId by remember { mutableStateOf("") }
    var frame by remember { mutableStateOf<Bitmap?>(null) }
    var frameT by remember { mutableStateOf(0.0) }
    var rot by remember { mutableStateOf(0) } // manual clockwise rotation of the video (UserRot)
    var durationS by remember { mutableStateOf(0.0) } // 0 = unknown
    var rangeA by remember { mutableStateOf<Float?>(null) } // A-B scan: only this part of the clip is scanned (null = from the start)
    var rangeB by remember { mutableStateOf<Float?>(null) } // null = to the end
    var seekT by remember { mutableStateOf(0f) } // where the user wants the pick frame (seconds)
    var loadJob by remember { mutableStateOf<kotlinx.coroutines.Job?>(null) }
    var tap by remember { mutableStateOf<Offset?>(null) } // normalized 0..1
    var preset by remember { mutableStateOf<String?>(null) } // null = automatic (tapped joint decides)
    var exact by remember { mutableStateOf(false) }
    var draw by remember { mutableStateOf(initialMode == "freehand") } // Part 18: freehand region instead of a tap
    var rectMode by remember { mutableStateOf(false) } // Rectangle tab: a dragged box becomes a 4-corner region (same pipeline as Freehand)
    val strokes = remember { androidx.compose.runtime.mutableStateListOf<List<Offset>>() }
    var curStroke by remember { mutableStateOf<List<Offset>>(emptyList()) }
    // Preview zoom for precise dotting. View only: every point/stroke stays in normalized frame coordinates (0..1), so the scan is unaffected.
    var vz by remember { mutableStateOf(1f) } // 1 = whole frame, up to 8x
    var vo by remember { mutableStateOf(Offset.Zero) } // layer translation in px (<= 0), top-left origin
    var boxPx by remember { mutableStateOf(IntSize.Zero) }
    fun setView(z: Float, o: Offset) {
        val zz = z.coerceIn(1f, 8f); val w = boxPx.width.toFloat(); val h = boxPx.height.toFloat()
        vz = zz; vo = Offset(o.x.coerceIn(w * (1f - zz), 0f), o.y.coerceIn(h * (1f - zz), 0f))
    }
    fun zoomAbout(c: Offset, nz: Float) { val z = nz.coerceIn(1f, 8f); setView(z, c - (c - vo) * (z / vz)) }
    var multi by remember { mutableStateOf(false) } // Point mode: several dots on one limb (the first tap = `tap`, any number more in `extra`)
    val extra = remember { androidx.compose.runtime.mutableStateListOf<Offset>() }
    var zoomLog2 by remember { mutableStateOf(1.5f) }
    var keepDist by remember { mutableStateOf(true) } // fixed-zoom free picks: keep the object's apparent size (zoom follows its distance)
    var regionFixed by remember { mutableStateOf(true) } // freehand: false = keep the area's size (zoom follows it), true = fixed zoom
    var regionFill by remember { mutableStateOf(0.9f) }
    var fps by remember { mutableStateOf(PICK_FPS[0]) } // 10 fps default
    var npu by remember { mutableStateOf(true) } // NPU on by default
    var preview by remember { mutableStateOf(true) }
    var model by remember { mutableStateOf(models.firstOrNull { it.contains("v8s") } ?: models.firstOrNull().orEmpty()) }
    var error by remember { mutableStateOf("") }
    var objectMode by remember { mutableStateOf(initialMode != "body") } // false = person / body part (pose model), true = any object or spot
    val free = objectMode // "any object" = the free-point path (SAM when installed, optical flow otherwise)
    var adv by remember { mutableStateOf(false) }
    val samOk = remember { SamEngine.hasModels(ctx) }
    val samMem = remember { SamEngine.hasMemory(ctx) }
    var samCache by remember { mutableStateOf<SamFrameCache?>(null) }
    var samMask by remember { mutableStateOf<SamMask?>(null) }
    var segBusy by remember { mutableStateOf(false) }
    val running = ui is ScanUi.Running || ui is ScanUi.Saving
    val lost = ui as? ScanUi.Lost // the scan is paused: the target was gone for a few seconds
    // People the model finds on the first frame (null = still detecting). Only a guide: the tap is resolved after the scan.
    var found by remember { mutableStateOf<List<Pose>?>(null) }
    LaunchedEffect(frame, model) {
        val f = frame ?: return@LaunchedEffect
        if (model.isEmpty()) return@LaunchedEffect
        found = null
        found = try {
            withContext(Dispatchers.Default) {
                PoseRunner(ctx, model, threads = 4).use { r ->
                    val t0 = System.nanoTime()
                    val poses = r.detectRobust(f).poses
                    Diag.note(ctx, "pick", "FIRST_FRAME_DETECT", "${poses.size} people in ${"%.0f".format(java.util.Locale.ROOT, (System.nanoTime() - t0) / 1e6)} ms (${f.width}x${f.height}, $model)")
                    if (poses.isEmpty()) Diag.note(ctx, "pick", "NO_PEOPLE", "no person on the picked frame: black/blank frame? seek to another frame before scanning", com.takipli.oynat.core.Sev.WARN)
                    poses
                }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            ErrorLog.record(ctx, "first-frame-detect", e)
            emptyList()
        }
    }

    // Part 20: the same people as coloured body parts. Built from the first-frame poses with the functions the scan uses
    // (`resolvePick`, `presetBoxes`), so the highlighted part is the one that gets followed.
    val cfg = remember { Config() }
    val pickDoc = remember(found, frame, frameT) {
        val f = frame; val ps = found
        if (f == null || ps == null) null else firstFrameDoc(ps.withMinScore(cfg.poseConf), f.width, f.height, frameT)
    }
    val people = remember(pickDoc) { pickDoc?.let { pickPersons(it, cfg) }.orEmpty() }
    val hl = remember(pickDoc, tap, preset, exact, objectMode) {
        val d = pickDoc; val t = tap
        if (d == null || t == null || objectMode) null
        else highlightPick(d, TargetPick(frameT, t.x.toDouble(), t.y.toDouble(), preset = preset, exact = exact && preset == null), cfg)
    }
    // a chosen chip with no tap yet: that part on everybody
    val chipRegions = remember(pickDoc, preset, objectMode) {
        val d = pickDoc; val pr = preset
        if (d == null || pr == null || objectMode) emptyMap() else presetRegions(d, pr, cfg)
    }
    // tapping inside a drawn part selects that part (the chip follows the tap); "exact joint" keeps the tapped joint
    LaunchedEffect(tap) {
        val t = tap ?: return@LaunchedEffect
        if (objectMode || exact) return@LaunchedEffect
        partHit(people, t.x.toDouble(), t.y.toDouble())?.let { preset = it.second }
    }
    val labelPaint = remember {
        android.graphics.Paint().apply {
            isAntiAlias = true; textSize = 38f; color = android.graphics.Color.WHITE
            setShadowLayer(5f, 0f, 0f, android.graphics.Color.BLACK)
        }
    }

    // Smart select ("Any object", sam build): encode the shown frame once, then every tap only runs the small decoder.
    LaunchedEffect(frame, objectMode, draw) {
        samMask = null; samCache = null
        val f = frame ?: return@LaunchedEffect
        if (!objectMode || !samOk || draw) return@LaunchedEffect
        segBusy = true
        try { samCache = SamEngine.encodeFrame(ctx, f) }
        catch (e: CancellationException) { throw e }
        catch (e: Throwable) { ErrorLog.record(ctx, "sam-preview-encode", e) }
        finally { segBusy = false }
    }
    LaunchedEffect(tap, samCache) {
        samMask = null
        val c = samCache ?: return@LaunchedEffect
        val t = tap ?: return@LaunchedEffect
        segBusy = true
        try { samMask = SamEngine.segmentAt(ctx, c, t.x.toDouble(), t.y.toDouble()) }
        catch (e: CancellationException) { throw e }
        catch (e: Throwable) { ErrorLog.record(ctx, "sam-preview-segment", e) }
        finally { segBusy = false }
    }

    val notifPerm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { u ->
        if (u == null) return@rememberLauncherForActivityResult
        runCatching { ctx.contentResolver.takePersistableUriPermission(u, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
        scope.launch {
            error = ""; tap = null; extra.clear(); frame = null; vz = 1f; vo = Offset.Zero; ScanService.reset()
            try {
                videoId = withContext(Dispatchers.IO) { videoIdOf(ctx, u) }
                durationS = withContext(Dispatchers.IO) { runCatching { VideoDecoder.probe(ctx, u).durationS }.getOrDefault(0.0) }
                seekT = 0f; rangeA = null; rangeB = null
                rot = UserRot.get(ctx, u.toString())
                VideoDecoder.sample(ctx, u, 1.0, 0.0) { f -> frame = f.bitmap; frameT = f.t; false }
                uri = u
            } catch (e: Throwable) {
                uri = null; Diag.note(ctx, "pick", "OPEN_VIDEO_FAIL", "${e.javaClass.simpleName}: ${(e.message ?: "").take(100)} uri=${u.scheme}", com.takipli.oynat.core.Sev.ERROR); ErrorLog.record(ctx, "open-video", e); error = Safety.friendly(ctx, e)
            }
        }
    }

    fun clampT(t: Double): Double =
        if (durationS > 0) t.coerceIn(0.0, (durationS - 0.1).coerceAtLeast(0.0)) else t.coerceAtLeast(0.0)

    // The first frame is often black or unrelated to the rest of the clip: let the user pick the target on any later frame.
    // The scan tracks both ways in time from the picked frame, so nothing else changes.
    fun loadAt(t: Double) {
        val u = uri ?: return
        loadJob?.cancel()
        loadJob = scope.launch {
            try {
                VideoDecoder.sample(ctx, u, 1.0, clampT(t)) { f ->
                    frame = f.bitmap; frameT = f.t
                    tap = null; extra.clear(); strokes.clear(); curStroke = emptyList() // those points belonged to the previous frame
                    false
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                ErrorLog.record(ctx, "seek-frame", e); error = Safety.friendly(ctx, e)
            }
        }
    }

    // Turn the video by `delta` degrees clockwise (0/90/180/270). The frame on screen is turned in memory (a 90 degree turn is lossless and
    // instant), the new angle is saved for the video, so the scan decodes every frame with the same turn and the result preview/export match.
    fun turn(delta: Int) {
        val u = uri ?: return
        val b = frame ?: return
        val d = normalizeRotation(delta)
        if (d == 0) return
        rot = normalizeRotation(rot + d)
        UserRot.set(ctx, u.toString(), rot)
        frame = Bitmap.createBitmap(b, 0, 0, b.width, b.height, Matrix().apply { postRotate(d.toFloat()) }, true)
        tap = null; extra.clear(); strokes.clear(); curStroke = emptyList(); found = null; vz = 1f; vo = Offset.Zero // those points belonged to the old orientation
        if (loadJob?.isActive == true) loadAt(seekT.toDouble()) // a seek was still decoding with the old turn: decode again with the new one
    }

    // Scan paused because the target was lost: show a frame from just before the loss (the user can jump anywhere with the seek controls), tap the target, resume
    LaunchedEffect(lost?.t, lost?.uri) {
        val l = lost ?: return@LaunchedEffect
        if (uri == null) { // the screen was recreated while the scan waited: take the video from the pause itself
            val u = Uri.parse(l.uri)
            uri = u; videoId = l.videoId
            durationS = withContext(Dispatchers.IO) { runCatching { VideoDecoder.probe(ctx, u).durationS }.getOrDefault(0.0) }
            rot = UserRot.get(ctx, u.toString())
        }
        val at = (l.t - 3.0).coerceAtLeast(0.0)
        seekT = at.toFloat()
        loadAt(at)
    }

    Column(
        Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp).verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        TextButton(onClick = onBack, enabled = !running) { Text(stringResource(R.string.back)) }
        if (lost != null) {
            Text(stringResource(R.string.scan_lost_hint), color = MaterialTheme.colorScheme.error)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { ScanService.resolveLost(null) }) { Text(stringResource(R.string.scan_lost_skip)) }
                OutlinedButton(onClick = { ScanService.cancel(ctx) }) { Text(stringResource(R.string.scan_cancel)) }
            }
        }
        Text(stringResource(R.string.pick_title), style = MaterialTheme.typography.headlineSmall)
        Text(stringResource(R.string.home_modes_title), style = MaterialTheme.typography.titleSmall)
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = !objectMode, enabled = !running, onClick = {
                objectMode = false; draw = false; rectMode = false; tap = null; extra.clear(); strokes.clear(); curStroke = emptyList()
            }, label = { Text(stringResource(R.string.mode_tab_body)) })
            FilterChip(selected = objectMode && !draw, enabled = !running, onClick = {
                objectMode = true; draw = false; rectMode = false; tap = null; extra.clear(); strokes.clear(); curStroke = emptyList()
            }, label = { Text(stringResource(R.string.mode_tab_point)) })
            FilterChip(selected = objectMode && draw && !rectMode, enabled = !running, onClick = {
                objectMode = true; draw = true; rectMode = false; tap = null; extra.clear(); strokes.clear(); curStroke = emptyList()
            }, label = { Text(stringResource(R.string.mode_tab_freehand)) })
            FilterChip(selected = objectMode && draw && rectMode, enabled = !running, onClick = {
                objectMode = true; draw = true; rectMode = true; tap = null; extra.clear(); strokes.clear(); curStroke = emptyList()
            }, label = { Text(stringResource(R.string.mode_tab_rect)) })
        }
        // What really works in this install, in plain words
        Text(stringResource(R.string.status_version, BuildConfig.VERSION_NAME), fontSize = 12.sp)
        Text(stringResource(if (samMem) R.string.status_sam_full else if (samOk) R.string.status_sam_basic else R.string.status_sam_none), fontSize = 12.sp)
        Text(stringResource(if (models.isNotEmpty()) R.string.status_pose_ok else R.string.status_pose_none), fontSize = 12.sp)
        if (models.isEmpty()) Text(stringResource(R.string.bench_no_models))
        OutlinedButton(enabled = !running, onClick = { picker.launch(arrayOf("video/*")) }) { Text(stringResource(R.string.decode_pick)) }
        if (error.isNotEmpty()) Text(error)

        val bmp = frame
        if (uri != null && bmp != null && !running && ui !is ScanUi.Done && ui !is ScanUi.Cancelled) {
            // Rotate until the people stand upright (like at 0 degrees): the preview below is exactly what is tracked and exported.
            Text(stringResource(R.string.pick_rotate, rot), style = MaterialTheme.typography.labelLarge)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { turn(270) }, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.pick_rot_left)) }
                OutlinedButton(onClick = { turn(90) }, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.pick_rot_right)) }
                OutlinedButton(onClick = { turn(360 - rot) }, enabled = rot != 0, modifier = Modifier.weight(1f)) { Text(stringResource(R.string.pick_rot_reset)) }
            }
            // The selected mode is controlled by the three tabs above.
            // 2. say what to do next, in plain words
            val fl = found
            Text(
                when {
                    !objectMode -> when {
                        fl == null -> stringResource(R.string.pick_detecting)
                        fl.isEmpty() -> stringResource(R.string.pick_none)
                        hl != null -> stringResource(R.string.pick_sel, hl.target.id, partLabel(hl.target))
                        tap != null -> stringResource(R.string.pick_sel_nobody)
                        else -> stringResource(R.string.pick_found, fl.size)
                    }
                    draw && rectMode -> stringResource(R.string.pick_rect_hint)
                    draw -> stringResource(R.string.pick_draw_hint)
                    !samOk -> stringResource(R.string.pick_obj_spot)
                    samCache == null && segBusy -> stringResource(R.string.pick_obj_prep)
                    samMask != null -> stringResource(R.string.pick_obj_sel)
                    tap != null && !segBusy -> stringResource(R.string.pick_obj_none)
                    else -> stringResource(R.string.pick_obj_tap)
                },
            )
            val maskImg = remember(samMask) {
                samMask?.let { m ->
                    val b = Bitmap.createBitmap(m.size, m.size, Bitmap.Config.ARGB_8888)
                    val c = android.graphics.Color.argb(140, 0, 229, 255)
                    b.setPixels(IntArray(m.size * m.size) { if (m.inside[it]) c else 0 }, 0, m.size, 0, 0, m.size, m.size)
                    b.asImageBitmap()
                }
            }
            Box(
                previewModifier(bmp.width / bmp.height.toFloat()).clipToBounds().onSizeChanged { boxPx = it }.pointerInput(Unit) {
                    // Two fingers = pinch zoom + pan (taken before the dot/draw gestures below see them); one finger pans only while zoomed in
                    // and not drawing. A plain tap or a one-finger draw still reaches the Canvas untouched.
                    awaitEachGesture {
                        awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
                        var multiTouch = false; var panning = false; var moved = Offset.Zero
                        do {
                            val ev = awaitPointerEvent(PointerEventPass.Initial)
                            val down = ev.changes.count { it.pressed }
                            if (down >= 2) {
                                multiTouch = true
                                val c = ev.calculateCentroid(); val z = ev.calculateZoom(); val pn = ev.calculatePan()
                                val nz = (vz * z).coerceIn(1f, 8f)
                                setView(nz, c - (c - vo) * (nz / vz) + pn)
                                ev.changes.forEach { if (it.positionChanged()) it.consume() }
                            } else if (multiTouch) {
                                ev.changes.forEach { it.consume() } // the finger that stays after a pinch must not become a tap
                            } else if (vz > 1.01f && !draw) {
                                moved += ev.calculatePan()
                                if (panning || moved.getDistance() > viewConfiguration.touchSlop) {
                                    panning = true
                                    setView(vz, vo + ev.calculatePan())
                                    ev.changes.forEach { if (it.positionChanged()) it.consume() }
                                }
                            }
                        } while (ev.changes.any { it.pressed })
                    }
                },
            ) {
              Box(Modifier.matchParentSize().graphicsLayer {
                transformOrigin = TransformOrigin(0f, 0f); scaleX = vz; scaleY = vz; translationX = vo.x; translationY = vo.y
              }) {
                Image(bmp.asImageBitmap(), null, Modifier.matchParentSize())
                Canvas(
                    Modifier.matchParentSize().pointerInput(draw, rectMode) {
                        fun nrm(o: Offset) = Offset((o.x / size.width).coerceIn(0f, 1f), (o.y / size.height).coerceIn(0f, 1f))
                        if (draw && rectMode) {
                            // One box. Drag a corner = resize (opposite corner stays), drag inside = move, drag elsewhere = draw a new box.
                            var a = Offset.Zero; var mode = 0; var fixed = Offset.Zero; var grab = Offset.Zero
                            fun box(b: Offset) = listOf(Offset(a.x, a.y), Offset(b.x, a.y), Offset(b.x, b.y), Offset(a.x, b.y))
                            fun rectOf(): FloatArray? = strokes.firstOrNull()?.takeIf { it.size == 4 }?.let { p -> floatArrayOf(p.minOf { it.x }, p.minOf { it.y }, p.maxOf { it.x }, p.maxOf { it.y }) }
                            fun setRect(x1: Float, y1: Float, x2: Float, y2: Float) {
                                strokes.clear()
                                strokes.add(listOf(Offset(minOf(x1, x2), minOf(y1, y2)), Offset(maxOf(x1, x2), minOf(y1, y2)), Offset(maxOf(x1, x2), maxOf(y1, y2)), Offset(minOf(x1, x2), maxOf(y1, y2))))
                            }
                            detectDragGestures(
                                onDragStart = { o ->
                                    val p = nrm(o); val r = rectOf(); mode = 0
                                    if (r != null) {
                                        val tx = 44f / vz / size.width; val ty = 44f / vz / size.height
                                        val corner = listOf(r[0] to r[1], r[2] to r[1], r[2] to r[3], r[0] to r[3]).firstOrNull { (cx, cy) -> kotlin.math.abs(p.x - cx) < tx && kotlin.math.abs(p.y - cy) < ty }
                                        if (corner != null) { mode = 2; fixed = Offset(if (corner.first == r[0]) r[2] else r[0], if (corner.second == r[1]) r[3] else r[1]) }
                                        else if (p.x in r[0]..r[2] && p.y in r[1]..r[3]) { mode = 1; grab = p }
                                    }
                                    if (mode == 0) { a = p; curStroke = emptyList() }
                                },
                                onDrag = { c, _ ->
                                    val p = nrm(c.position)
                                    when (mode) {
                                        2 -> setRect(fixed.x, fixed.y, p.x, p.y)
                                        1 -> rectOf()?.let { r ->
                                            val dx = (p.x - grab.x).coerceIn(-r[0], 1f - r[2]); val dy = (p.y - grab.y).coerceIn(-r[1], 1f - r[3])
                                            setRect(r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy); grab = Offset(grab.x + dx, grab.y + dy)
                                        }
                                        else -> curStroke = box(p)
                                    }
                                },
                                onDragEnd = {
                                    if (mode == 0) { val w = curStroke.getOrNull(2); if (w != null && kotlin.math.abs(w.x - a.x) > 0.01f && kotlin.math.abs(w.y - a.y) > 0.01f) setRect(a.x, a.y, w.x, w.y); curStroke = emptyList() }
                                    mode = 0
                                },
                                onDragCancel = { curStroke = emptyList(); mode = 0 },
                            )
                        } else if (draw) detectDragGestures(
                            onDragStart = { o -> curStroke = listOf(nrm(o)) },
                            onDrag = { c, _ -> curStroke = curStroke + nrm(c.position) },
                            onDragEnd = { if (curStroke.size >= 3) strokes.add(curStroke); curStroke = emptyList() },
                            onDragCancel = { curStroke = emptyList() },
                        ) else detectTapGestures { o -> if (multi && tap != null) { extra.add(nrm(o)) } else tap = nrm(o) }
                    },
                ) {
                    val k = 1f / vz // the layer is scaled by vz: divide px sizes so dots and lines keep their on-screen size
                    if (!objectMode) found?.forEach { p ->
                        val b = p.bbox
                        fun fx(x: Double) = (x / bmp.width * size.width).toFloat()
                        fun fy(y: Double) = (y / bmp.height * size.height).toFloat()
                        drawRect(Color.White, Offset(fx(b.x1), fy(b.y1)), Size(fx(b.x2) - fx(b.x1), fy(b.y2) - fy(b.y1)), style = Stroke(2f * k))
                        for ((a, c) in COCO_SKELETON) {
                            if (p.conf(a) >= 0.35 && p.conf(c) >= 0.35) drawLine(Color.Yellow, Offset(fx(p.x(a)), fy(p.y(a))), Offset(fx(p.x(c)), fy(p.y(c))), 3f * k)
                        }
                    }
                    if (!objectMode && people.isNotEmpty()) {
                        fun rx(v: Double) = (v * size.width).toFloat()
                        fun ry(v: Double) = (v * size.height).toFloat()
                        fun region(b: DoubleArray, c: Color, fillA: Float, w: Float) {
                            val tl = Offset(rx(b[0]), ry(b[1])); val sz = Size(rx(b[2]) - rx(b[0]), ry(b[3]) - ry(b[1]))
                            if (fillA > 0f) drawRect(c.copy(alpha = fillA), tl, sz)
                            drawRect(c, tl, sz, style = Stroke(w * k))
                        }
                        val sel = hl
                        val nat = drawContext.canvas.nativeCanvas
                        people.forEach { p ->
                            val mine = sel != null && sel.target.id == p.id
                            when {
                                // the picked person: other parts faint, the picked part strong
                                sel != null && mine -> {
                                    p.parts.forEach { (g, b) -> region(b, partColor(g), 0.06f, 1.5f) }
                                    sel.box?.let { b ->
                                        val c = partColor(sel.target.preset ?: sel.target.part?.let { presetForJoint(it) })
                                        region(b, c, 0.40f, 5f)
                                        nat.drawText(partLabel(sel.target), rx(b[0]).coerceAtLeast(4f), (ry(b[1]) - 10f).coerceAtLeast(40f), labelPaint)
                                    }
                                }
                                sel != null -> {}
                                // a chip is chosen, nobody tapped yet: that part on everyone
                                chipRegions.isNotEmpty() -> chipRegions[p.id]?.let { b ->
                                    region(b, partColor(preset), 0.40f, 4f)
                                    nat.drawText(partLabel(com.takipli.oynat.core.Target(p.id, preset = preset)), rx(b[0]).coerceAtLeast(4f), (ry(b[1]) - 10f).coerceAtLeast(40f), labelPaint)
                                }
                                // nothing chosen: every part, coloured
                                else -> p.parts.forEach { (g, b) -> region(b, partColor(g), 0.22f, 2f) }
                            }
                            // joint dots, coloured like the part they belong to
                            val groupJoints = if (mine) sel?.target?.preset?.let { PRESETS[it] } else null
                            p.joints.forEach { (kk, jx, jy) ->
                                val big = groupJoints != null && kk in groupJoints
                                val c = Offset(rx(jx), ry(jy))
                                drawCircle(Color.Black, (if (big) 11f else 8f) * k, c)
                                drawCircle(partColor(presetForJoint(kk)), (if (big) 8f else 5f) * k, c)
                            }
                            if (people.size > 1) nat.drawText(p.id.toString(), rx(p.box[0]) + 8f, ry(p.box[1]) + 40f, labelPaint)
                        }
                    }
                    maskImg?.let { drawImage(it, dstSize = IntSize(size.width.toInt(), size.height.toInt())) }
                    samMask?.let { m ->
                        drawRect(Color.Cyan, Offset((m.x1 * size.width).toFloat(), (m.y1 * size.height).toFloat()),
                            Size(((m.x2 - m.x1) * size.width).toFloat(), ((m.y2 - m.y1) * size.height).toFloat()), style = Stroke(3f * k))
                    }
                    for (st in strokes + listOf(curStroke)) if (st.size >= 2) {
                        val path = androidx.compose.ui.graphics.Path()
                        st.forEachIndexed { i, o -> if (i == 0) path.moveTo(o.x * size.width, o.y * size.height) else path.lineTo(o.x * size.width, o.y * size.height) }
                        path.close()
                        drawPath(path, Color(0x4400E5FF)); drawPath(path, Color.Cyan, style = Stroke(3f * k))
                    }
                    if (rectMode) strokes.firstOrNull()?.takeIf { it.size == 4 }?.forEach { o -> // corner handles
                        drawCircle(Color.White, 14f * k, Offset(o.x * size.width, o.y * size.height)); drawCircle(Color.Cyan, 14f * k, Offset(o.x * size.width, o.y * size.height), style = Stroke(4f * k))
                    }
                    if (!draw) tap?.let { c ->
                        val p = Offset(c.x * size.width, c.y * size.height)
                        drawCircle(Color.Red, 14f * k, p, style = Stroke(width = 4f * k)); drawCircle(Color.White, 4f * k, p)
                        var prev = p
                        extra.forEach { e ->
                            val q = Offset(e.x * size.width, e.y * size.height)
                            drawLine(Color.Red, prev, q, strokeWidth = 3f * k)
                            drawCircle(Color.Red, 14f * k, q, style = Stroke(width = 4f * k)); drawCircle(Color.White, 4f * k, q)
                            prev = q
                        }
                    }
                }
              }
            }
            // zoom controls (pinch also works)
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                val mid = Offset(boxPx.width / 2f, boxPx.height / 2f)
                OutlinedButton(enabled = vz > 1.01f, onClick = { zoomAbout(mid, vz / 1.5f) }) { Text("\u2212") }
                OutlinedButton(enabled = vz < 7.99f, onClick = { zoomAbout(mid, vz * 1.5f) }) { Text("+") }
                OutlinedButton(enabled = vz > 1.01f, onClick = { vz = 1f; vo = Offset.Zero }) { Text(stringResource(R.string.pick_view_reset)) }
                Text(String.format(Locale.ROOT, "%.1f\u00d7", vz), style = MaterialTheme.typography.labelLarge)
            }
            Text(stringResource(R.string.pick_view_hint), fontSize = 12.sp)
            // 3. which part of the video
            Text(stringResource(R.string.pick_frame_time, fmtClock(seekT.toDouble()), if (durationS > 0) fmtClock(durationS) else "?"), style = MaterialTheme.typography.labelLarge)
            if (durationS > 0.5) {
                androidx.compose.material3.Slider(
                    value = seekT.coerceIn(0f, durationS.toFloat()),
                    onValueChange = { seekT = it },
                    onValueChangeFinished = { loadAt(seekT.toDouble()) },
                    valueRange = 0f..durationS.toFloat(),
                )
            }
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(-10.0 to "\u221210 s", -1.0 to "\u22121 s", -0.2 to "\u22120.2 s", 0.2 to "+0.2 s", 1.0 to "+1 s", 10.0 to "+10 s").forEach { (d, label) ->
                    OutlinedButton(onClick = { val t = clampT(seekT + d); seekT = t.toFloat(); loadAt(t) }) { Text(label) }
                }
            }
            Text(stringResource(R.string.pick_frame_hint), fontSize = 12.sp)
            // A-B scan: set A / B at the shown frame; only [A, B] is scanned, tracked and exported
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = rangeA != null, onClick = { rangeA = frameT.toFloat() }, label = { Text(stringResource(R.string.range_set_a, rangeA?.let { fmtClock(it.toDouble()) } ?: "—")) })
                FilterChip(selected = rangeB != null, onClick = { rangeB = frameT.toFloat() }, label = { Text(stringResource(R.string.range_set_b, rangeB?.let { fmtClock(it.toDouble()) } ?: "—")) })
                if (rangeA != null || rangeB != null) OutlinedButton(onClick = { rangeA = null; rangeB = null }) { Text(stringResource(R.string.range_clear)) }
            }
            val rangeErr = (rangeA != null && rangeB != null && rangeB!! <= rangeA!! + 0.5f) || (rangeA != null && frameT < rangeA!! - 0.05) || (rangeB != null && frameT > rangeB!! + 0.05)
            Text(stringResource(if (rangeErr) R.string.range_bad else R.string.range_hint), fontSize = 12.sp, color = if (rangeErr) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
            // 4. mode specific choices
            if (!objectMode) {
                Text(stringResource(R.string.pick_part), style = MaterialTheme.typography.labelLarge)
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(selected = preset == null, onClick = { preset = null }, label = { Text(stringResource(R.string.pick_auto)) })
                    PRESETS.keys.forEach { p ->
                        if (p in PART_GROUPS) FilterChip(
                            selected = preset == p, onClick = { preset = p }, label = { Text(p.replace('_', ' ')) },
                            leadingIcon = { Canvas(Modifier.size(10.dp)) { drawCircle(partColor(p)) } },
                        ) else FilterChip(selected = preset == p, onClick = { preset = p }, label = { Text(p.replace('_', ' ')) })
                    }
                }
            } else {
                if (!draw) {
                    Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                        androidx.compose.material3.Switch(checked = multi, enabled = !running, onCheckedChange = { multi = it; if (!it) extra.clear() })
                        Text(stringResource(R.string.pick_multi), Modifier.padding(start = 8.dp))
                    }
                    if (multi) OutlinedButton(enabled = tap != null, onClick = { if (extra.isNotEmpty()) extra.removeAt(extra.size - 1) else tap = null }) { Text(stringResource(R.string.pick_dot_undo)) }
                }
                if ((!draw || regionFixed) && extra.isEmpty()) { // same cases as the zoom slider: a fixed zoom can follow the object's distance
                    Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                        androidx.compose.material3.Switch(checked = keepDist, enabled = !running, onCheckedChange = { keepDist = it })
                        Text(stringResource(R.string.pick_keep_dist), Modifier.padding(start = 8.dp))
                    }
                    Text(stringResource(R.string.pick_keep_dist_hint), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (draw) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(enabled = strokes.isNotEmpty(), onClick = { strokes.removeLastOrNull() }) { Text(stringResource(R.string.pick_undo)) }
                    OutlinedButton(enabled = strokes.isNotEmpty(), onClick = { strokes.clear() }) { Text(stringResource(R.string.pick_clear)) }
                }
            }
            // 5. technical settings stay out of sight
            TextButton(onClick = { adv = !adv }) { Text(stringResource(if (adv) R.string.pick_adv_hide else R.string.pick_adv_show)) }
            if (adv) {
                if (!objectMode) FilterChip(selected = exact, enabled = preset == null, onClick = { exact = !exact }, label = { Text(stringResource(R.string.pick_exact)) })
                if (models.size > 1) Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    models.forEach { m -> FilterChip(selected = m == model, onClick = { model = m }, label = { Text(m.removeSuffix(".onnx")) }) }
                }
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    PICK_FPS.forEach { c -> FilterChip(selected = c == fps, onClick = { fps = c }, label = { Text("$c fps") }) }
                    FilterChip(selected = npu, onClick = { npu = !npu }, label = { Text("NPU", maxLines = 1, softWrap = false) })
                    FilterChip(selected = preview, onClick = { preview = !preview }, label = { Text(stringResource(R.string.pick_preview)) })
                }
                if (objectMode && (!draw || regionFixed) && extra.isEmpty()) {
                    Text(stringResource(R.string.pick_zoom, Math.pow(2.0, zoomLog2.toDouble())), style = MaterialTheme.typography.labelLarge)
                    androidx.compose.material3.Slider(value = zoomLog2, onValueChange = { zoomLog2 = it }, valueRange = 0.5f..2.5f)
                }
                if (objectMode && draw) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterChip(selected = !regionFixed, enabled = !running, onClick = { regionFixed = false }, label = { Text(stringResource(R.string.pick_region_keep)) })
                        FilterChip(selected = regionFixed, enabled = !running, onClick = { regionFixed = true }, label = { Text(stringResource(R.string.pick_region_fixed)) })
                    }
                    Text(stringResource(if (regionFixed) R.string.pick_region_fixed_hint else R.string.pick_region_keep_hint), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (!regionFixed) {
                        Text(stringResource(R.string.pick_region_fill, (regionFill * 100).toInt()), style = MaterialTheme.typography.labelLarge)
                        androidx.compose.material3.Slider(value = regionFill, onValueChange = { regionFill = it }, valueRange = 0.3f..0.98f)
                    }
                }
            }
            BatteryWarning()
            Button(
                enabled = (if (draw) strokes.isNotEmpty() else tap != null) && model.isNotEmpty() && !segBusy && !rangeErr,
                onClick = {
                    val shapes = if (draw) strokes.map { st -> com.takipli.oynat.core.simplifyStroke(st.map { listOf(it.x.toDouble(), it.y.toDouble()) }, 0.004) }.filter { it.size >= 3 } else emptyList()
                    if (draw && shapes.isEmpty()) return@Button
                    val dots = if (!draw && multi && extra.isNotEmpty() && tap != null) (listOf(tap!!) + extra).map { listOf(it.x.toDouble(), it.y.toDouble()) } else emptyList()
                    val t = if (draw) com.takipli.oynat.core.shapeBounds(shapes)!!.let { Offset(it[0].toFloat(), it[1].toFloat()) }
                    else if (dots.size >= 2) Offset(dots.map { it[0] }.average().toFloat(), dots.map { it[1] }.average().toFloat())
                    else tap ?: return@Button
                    val np = TargetPick(frameT, t.x.toDouble(), t.y.toDouble(), preset = if (objectMode) null else preset, exact = exact && preset == null && !objectMode, free = free, zoom = if (free && (!draw || regionFixed) && dots.isEmpty()) zoomLog2.toDouble() else null, shapes = shapes, fill = if (draw && !regionFixed) regionFill.toDouble() else null, dots = dots, keepDist = keepDist && free)
                    if (lost != null) ScanService.resolveLost(np) // paused scan: the new pick joins the target and the scan goes on
                    else {
                        notifPerm.launch(Manifest.permission.POST_NOTIFICATIONS)
                        ScanService.start(ctx, uri!!, videoId, model, npu, fps.toDouble(), np, preview, rangeA?.toDouble(), rangeB?.toDouble())
                    }
                },
            ) { Text(stringResource(if (lost != null) R.string.scan_lost_resume else R.string.pick_start)) }
        }

        when (val s = ui) {
            is ScanUi.Running -> {
                val p = s.p
                s.pv?.let { ScanPreviewView(it) }
                if (p != null && p.total > 0) LinearProgressIndicator(progress = { (p.samples.toFloat() / p.total).coerceIn(0f, 1f) })
                Text(
                    p?.let { String.format(Locale.ROOT, "%d / %d samples | t %.1f s | cuts %d", it.samples, it.total, it.t, it.cuts) }
                        ?: stringResource(R.string.pick_preparing),
                    fontFamily = FontFamily.Monospace, fontSize = 13.sp,
                )
                Text(stringResource(R.string.pick_background))
                OutlinedButton(onClick = { ScanService.cancel(ctx) }) { Text(stringResource(R.string.scan_cancel)) }
            }
            is ScanUi.Done -> {
                Text(
                    if (s.targetText != null) stringResource(R.string.pick_done, s.targetText, s.samples)
                    else stringResource(R.string.pick_nobody, s.samples),
                )
                if (!s.cached) Text(stringResource(R.string.pick_speed, String.format(Locale.ROOT, "%.2f", s.xRealtime), if (s.preview) "on" else "off"))
                Text(s.file, fontFamily = FontFamily.Monospace, fontSize = 12.sp)
                if (s.targetText != null) Button(onClick = { onResult(s.file) }) { Text(stringResource(R.string.result_open)) }
                OutlinedButton(onClick = { ScanService.reset() }) { Text(stringResource(R.string.pick_again)) }
            }
            is ScanUi.Lost -> {}
            is ScanUi.Saving -> {
                Text(stringResource(R.string.scan_saving_partial))
                if (s.samples > 0) Text(stringResource(R.string.scan_saving_kept, s.samples, fmtClock(s.t)), fontSize = 12.sp)
                if (s.total > 0) {
                    // determinate: tracker pass over the processed part (smoothed so it moves even between steps)
                    val f by androidx.compose.animation.core.animateFloatAsState((s.done.toFloat() / s.total).coerceIn(0f, 1f), androidx.compose.animation.core.tween(400), label = "saving")
                    LinearProgressIndicator(progress = { f }, modifier = Modifier.fillMaxWidth())
                    Text(stringResource(R.string.scan_saving_track, (f * 100).toInt()), fontFamily = FontFamily.Monospace, fontSize = 13.sp)
                } else LinearProgressIndicator(modifier = Modifier.fillMaxWidth()) // still stopping / writing: moving bar instead of a frozen screen
            }
            is ScanUi.Cancelled -> {
                // Cancel keeps what was scanned: preview / export that part, resume with a new pick, or throw the progress away.
                if (s.samples <= 0) Text(stringResource(R.string.scan_cancelled))
                else Text(stringResource(if (s.targetText != null) R.string.scan_cancelled_partial else R.string.scan_cancelled_nobody, s.samples, String.format(Locale.ROOT, "%.1f", s.t)))
                if (s.file != null) Button(onClick = { onResult(s.file) }) { Text(stringResource(R.string.scan_export_partial)) }
                OutlinedButton(onClick = { ScanService.reset() }) { Text(stringResource(R.string.scan_resume_pick)) }
                OutlinedButton(onClick = { ScanService.clearProgress(ctx, videoId, rangeA?.toDouble(), rangeB?.toDouble()) }) { Text(stringResource(R.string.scan_clear_progress)) }
            }
            is ScanUi.Failed -> Text(s.message)
            ScanUi.Idle -> {}
        }
    }
}
