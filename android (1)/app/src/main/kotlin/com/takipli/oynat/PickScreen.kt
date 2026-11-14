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
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
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
import com.takipli.oynat.core.PRESETS
import com.takipli.oynat.core.TargetPick
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
fun PickScreen(onBack: () -> Unit) {
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
    var fps by remember { mutableStateOf(PICK_FPS[1]) }
    var npu by remember { mutableStateOf(false) }
    var preview by remember { mutableStateOf(true) }
    var model by remember { mutableStateOf(models.firstOrNull { it.contains("v8s") } ?: models.firstOrNull().orEmpty()) }
    var error by remember { mutableStateOf("") }
    val running = ui is ScanUi.Running

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
                uri = null; error = ctx.getString(R.string.bench_error, e.message ?: e.javaClass.simpleName)
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
            Box(Modifier.fillMaxWidth().aspectRatio(bmp.width / bmp.height.toFloat())) {
                Image(bmp.asImageBitmap(), null, Modifier.matchParentSize())
                Canvas(
                    Modifier.matchParentSize().pointerInput(Unit) {
                        detectTapGestures { o -> tap = Offset((o.x / size.width).coerceIn(0f, 1f), (o.y / size.height).coerceIn(0f, 1f)) }
                    },
                ) {
                    tap?.let { c ->
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
            Button(
                enabled = tap != null && model.isNotEmpty(),
                onClick = {
                    val t = tap ?: return@Button
                    notifPerm.launch(Manifest.permission.POST_NOTIFICATIONS)
                    ScanService.start(ctx, uri!!, videoId, model, npu, fps.toDouble(), TargetPick(frameT, t.x.toDouble(), t.y.toDouble(), preset = preset, exact = exact && preset == null), preview)
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
                OutlinedButton(onClick = { ScanService.reset() }) { Text(stringResource(R.string.pick_again)) }
            }
            is ScanUi.Failed -> Text(if (s.cancelled) s.message else stringResource(R.string.bench_error, s.message))
            ScanUi.Idle -> {}
        }
    }
}
