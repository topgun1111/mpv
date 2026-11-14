package com.takipli.oynat

import android.Manifest
import android.content.Intent
import android.graphics.Bitmap
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
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.gestures.detectTapGestures
import com.takipli.oynat.core.COCO_SKELETON
import com.takipli.oynat.core.PRESETS
import com.takipli.oynat.core.Pose
import com.takipli.oynat.core.TargetPick
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale

private val PICK_FPS = listOf(10, 15, 20)

/**
 * Part 11: open a video -> first frame -> tap a person or a body part (and/or choose a part preset) -> scan in the
 * foreground service ([ScanService]); the screen can go off or the app can be closed while it runs.
 */
@Composable
fun PickScreen(onBack: () -> Unit, onResult: (String) -> Unit = {}) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val models = remember { ModelStore.list(ctx) }
    val ui by ScanService.state.collectAsState()
    var uri by remember { mutableStateOf<Uri?>(null) }
    var videoId by remember { mutableStateOf("") }
    var frame by remember { mutableStateOf<Bitmap?>(null) }
    var frameT by remember { mutableStateOf(0.0) }
    var tap by remember { mutableStateOf<Offset?>(null) } // normalized 0..1
    var preset by remember { mutableStateOf<String?>(null) } // null = automatic (tapped joint decides)
    var exact by remember { mutableStateOf(false) }
    var draw by remember { mutableStateOf(false) } // Part 18: freehand region instead of a tap
    val strokes = remember { androidx.compose.runtime.mutableStateListOf<List<Offset>>() }
    var curStroke by remember { mutableStateOf<List<Offset>>(emptyList()) }
    var free by remember { mutableStateOf(false) } // Part 16: follow the exact tapped spot
    var zoomLog2 by remember { mutableStateOf(1.5f) }
    var fps by remember { mutableStateOf(PICK_FPS[1]) }
    var npu by remember { mutableStateOf(false) }
    var preview by remember { mutableStateOf(true) }
    var model by remember { mutableStateOf(models.firstOrNull { it.contains("v8s") } ?: models.firstOrNull().orEmpty()) }
    var error by remember { mutableStateOf("") }
    val running = ui is ScanUi.Running
    // People the model finds on the first frame (null = still detecting). Only a guide: the tap is resolved after the scan.
    var found by remember { mutableStateOf<List<Pose>?>(null) }
    LaunchedEffect(frame, model) {
        val f = frame ?: return@LaunchedEffect
        if (model.isEmpty()) return@LaunchedEffect
        found = null
        found = try {
            withContext(Dispatchers.Default) { PoseRunner(ctx, model, threads = 4).use { it.detect(f).poses } }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            ErrorLog.record(ctx, "first-frame-detect", e)
            emptyList()
        }
    }

    val notifPerm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { u ->
        if (u == null) return@rememberLauncherForActivityResult
        runCatching { ctx.contentResolver.takePersistableUriPermission(u, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
        scope.launch {
            error = ""; tap = null; frame = null; ScanService.reset()
            try {
                videoId = withContext(Dispatchers.IO) { videoIdOf(ctx, u) }
                VideoDecoder.sample(ctx, u, 1.0, 0.0) { f -> frame = f.bitmap; frameT = f.t; false }
                uri = u
            } catch (e: Throwable) {
                uri = null; ErrorLog.record(ctx, "open-video", e); error = Safety.friendly(ctx, e)
            }
        }
    }

    Column(
        Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp).verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        TextButton(onClick = onBack, enabled = !running) { Text(stringResource(R.string.back)) }
        Text(stringResource(R.string.pick_title), style = MaterialTheme.typography.headlineSmall)
        if (models.isEmpty()) Text(stringResource(R.string.bench_no_models))
        OutlinedButton(enabled = !running, onClick = { picker.launch(arrayOf("video/*")) }) { Text(stringResource(R.string.decode_pick)) }
        if (error.isNotEmpty()) Text(error)

        val bmp = frame
        if (uri != null && bmp != null && !running && ui !is ScanUi.Done) {
            Text(stringResource(R.string.pick_hint))
            val fl = found
            Text(
                when {
                    fl == null -> stringResource(R.string.pick_detecting)
                    fl.isEmpty() -> stringResource(R.string.pick_none)
                    else -> stringResource(R.string.pick_found, fl.size)
                },
            )
            Box(Modifier.fillMaxWidth().aspectRatio(bmp.width / bmp.height.toFloat())) {
                Image(bmp.asImageBitmap(), null, Modifier.matchParentSize())
                Canvas(
                    Modifier.matchParentSize().pointerInput(draw) {
                        fun nrm(o: Offset) = Offset((o.x / size.width).coerceIn(0f, 1f), (o.y / size.height).coerceIn(0f, 1f))
                        if (draw) androidx.compose.foundation.gestures.detectDragGestures(
                            onDragStart = { o -> curStroke = listOf(nrm(o)) },
                            onDrag = { c, _ -> curStroke = curStroke + nrm(c.position) },
                            onDragEnd = { if (curStroke.size >= 3) strokes.add(curStroke); curStroke = emptyList() },
                            onDragCancel = { curStroke = emptyList() },
                        ) else detectTapGestures { o -> tap = nrm(o) }
                    },
                ) {
                    found?.forEach { p ->
                        val b = p.bbox
                        fun fx(x: Double) = (x / bmp.width * size.width).toFloat()
                        fun fy(y: Double) = (y / bmp.height * size.height).toFloat()
                        drawRect(Color.White, Offset(fx(b.x1), fy(b.y1)), Size(fx(b.x2) - fx(b.x1), fy(b.y2) - fy(b.y1)), style = Stroke(2f))
                        for ((a, c) in COCO_SKELETON) {
                            if (p.conf(a) >= 0.35 && p.conf(c) >= 0.35) drawLine(Color.Yellow, Offset(fx(p.x(a)), fy(p.y(a))), Offset(fx(p.x(c)), fy(p.y(c))), 3f)
                        }
                    }
                    for (st in strokes + listOf(curStroke)) if (st.size >= 2) {
                        val path = androidx.compose.ui.graphics.Path()
                        st.forEachIndexed { i, o -> if (i == 0) path.moveTo(o.x * size.width, o.y * size.height) else path.lineTo(o.x * size.width, o.y * size.height) }
                        path.close()
                        drawPath(path, Color(0x4400E5FF)); drawPath(path, Color.Cyan, style = Stroke(3f))
                    }
                    if (!draw) tap?.let { c ->
                        val p = Offset(c.x * size.width, c.y * size.height)
                        drawCircle(Color.Red, 14f, p, style = Stroke(width = 4f)); drawCircle(Color.White, 4f, p)
                    }
                }
            }
            Text(stringResource(R.string.pick_part), style = MaterialTheme.typography.labelLarge)
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = preset == null, onClick = { preset = null }, label = { Text(stringResource(R.string.pick_auto)) })
                PRESETS.keys.forEach { p -> FilterChip(selected = preset == p, onClick = { preset = p }, label = { Text(p.replace('_', ' ')) }) }
            }
            FilterChip(
                selected = exact, enabled = preset == null, onClick = { exact = !exact },
                label = { Text(stringResource(R.string.pick_exact)) },
            )
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                models.forEach { m -> FilterChip(selected = m == model, onClick = { model = m }, label = { Text(m.removeSuffix(".onnx")) }) }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PICK_FPS.forEach { c -> FilterChip(selected = c == fps, onClick = { fps = c }, label = { Text("$c fps") }) }
                FilterChip(selected = npu, onClick = { npu = !npu }, label = { Text("NPU") })
                FilterChip(selected = preview, onClick = { preview = !preview }, label = { Text(stringResource(R.string.pick_preview)) })
            }
            FilterChip(selected = free, onClick = { free = !free; if (!free) draw = false }, label = { Text(stringResource(R.string.pick_free)) })
            if (free) {
                FilterChip(selected = draw, onClick = { draw = !draw }, label = { Text(stringResource(R.string.pick_draw)) })
            }
            if (draw) {
                Text(stringResource(R.string.pick_draw_hint), fontSize = 12.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(enabled = strokes.isNotEmpty(), onClick = { strokes.removeLastOrNull() }) { Text(stringResource(R.string.pick_undo)) }
                    OutlinedButton(enabled = strokes.isNotEmpty(), onClick = { strokes.clear() }) { Text(stringResource(R.string.pick_clear)) }
                }
            }
            if (free && !draw) {
                Text(stringResource(R.string.pick_zoom, Math.pow(2.0, zoomLog2.toDouble())), style = MaterialTheme.typography.labelLarge)
                androidx.compose.material3.Slider(value = zoomLog2, onValueChange = { zoomLog2 = it }, valueRange = 0.5f..2.5f)
            }
            BatteryWarning()
            Button(
                enabled = (if (draw) strokes.isNotEmpty() else tap != null) && model.isNotEmpty(),
                onClick = {
                    val shapes = if (draw) strokes.map { st -> com.takipli.oynat.core.simplifyStroke(st.map { listOf(it.x.toDouble(), it.y.toDouble()) }, 0.004) }.filter { it.size >= 3 } else emptyList()
                    if (draw && shapes.isEmpty()) return@Button
                    val t = if (draw) com.takipli.oynat.core.shapeBounds(shapes)!!.let { Offset(it[0].toFloat(), it[1].toFloat()) } else tap ?: return@Button
                    notifPerm.launch(Manifest.permission.POST_NOTIFICATIONS)
                    ScanService.start(ctx, uri!!, videoId, model, npu, fps.toDouble(), TargetPick(frameT, t.x.toDouble(), t.y.toDouble(), preset = preset, exact = exact && preset == null, free = free, zoom = if (free && !draw) zoomLog2.toDouble() else null, shapes = shapes), preview)
                },
            ) { Text(stringResource(R.string.pick_start)) }
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
            is ScanUi.Failed -> Text(s.message)
            ScanUi.Idle -> {}
        }
    }
}
