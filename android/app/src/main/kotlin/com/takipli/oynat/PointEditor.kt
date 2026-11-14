package com.takipli.oynat

import android.graphics.Bitmap
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.os.Build
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
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
import com.takipli.oynat.core.Config
import com.takipli.oynat.core.FreePick
import com.takipli.oynat.core.TrackDoc
import com.takipli.oynat.core.fuseFreePoint
import com.takipli.oynat.core.nextWeak
import com.takipli.oynat.core.withPin
import com.takipli.oynat.core.withoutPin
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.util.Locale
import kotlin.math.abs

private fun nearestSample(ts: List<Double>, t: Double): Int {
    var lo = 0; var hi = ts.size - 1
    while (hi - lo > 1) { val m = (lo + hi) / 2; if (ts[m] <= t) lo = m else hi = m }
    return if (abs(ts[lo] - t) <= abs(ts[hi] - t)) lo else hi
}

/**
 * Part 17: manual corrections for a free-point target. Shows the full frame at the playhead with the tracked point and its
 * trail, a confidence timeline (green/yellow/red, white = pin), tap/drag to place the point, nudge, step by sample, jump
 * to weak spots or pins, pin / unpin, zoom, and "re-track with pins". Pins apply to the views instantly; re-tracking
 * lets the tracker follow the point between pins.
 */
@Composable
fun PointEditor(
    doc: TrackDoc, free: FreePick, cfg: Config, posMs: Long, busy: Boolean, msg: String,
    onSeek: (Long) -> Unit, onEdit: (FreePick) -> Unit, onRetrack: () -> Unit, onCancel: () -> Unit,
) {
    val ctx = LocalContext.current
    val n = doc.samples.size
    if (n == 0) return
    val ts = remember(doc.samples) { doc.samples.map { it.t } }
    val tol = 0.5 / (doc.sampleFps.takeIf { it > 0 } ?: 10.0)
    var fused by remember { mutableStateOf<Map<Int, DoubleArray>>(emptyMap()) }
    LaunchedEffect(doc.pt, free) { fused = withContext(Dispatchers.Default) { fuseFreePoint(doc, free, cfg) } }
    val conf = remember(fused) { DoubleArray(n) { fused[it]?.get(2) ?: 0.0 } }
    val idx = remember(posMs, ts) { nearestSample(ts, posMs / 1000.0) }
    val pinIdx = remember(free.pins, ts) { free.pins.filter { it.size >= 3 }.map { nearestSample(ts, it[0]) }.toSortedSet() }
    var pending by remember(idx) { mutableStateOf<Offset?>(null) } // point the user is placing, normalized
    var zoom by remember(free.zoom) { mutableStateOf((free.zoom ?: 1.5).toFloat()) }

    val vw = doc.video.w.coerceAtLeast(1); val vh = doc.video.h.coerceAtLeast(1)
    val retriever = remember { MediaMetadataRetriever().also { r -> runCatching { r.setDataSource(ctx, Uri.parse(doc.video.path)) } } }
    DisposableEffect(Unit) { onDispose { runCatching { retriever.release() } } }
    var bmp by remember { mutableStateOf<Bitmap?>(null) }
    LaunchedEffect(idx) {
        delay(120) // scrubbing: only the frame we stop on is decoded
        bmp = withContext(Dispatchers.IO) {
            runCatching {
                val us = (ts[idx] * 1e6).toLong()
                val sc = 960.0 / maxOf(vw, vh)
                if (Build.VERSION.SDK_INT >= 27) retriever.getScaledFrameAtTime(us, MediaMetadataRetriever.OPTION_CLOSEST, (vw * sc).toInt().coerceAtLeast(2), (vh * sc).toInt().coerceAtLeast(2))
                else retriever.getFrameAtTime(us, MediaMetadataRetriever.OPTION_CLOSEST)
            }.getOrNull()
        } ?: bmp
    }

    val cur = fused[idx]?.let { Offset(it[0].toFloat(), it[1].toFloat()) }
    val place = pending ?: cur
    fun go(i: Int) = onSeek((ts[i.coerceIn(0, n - 1)] * 1000).toLong())
    fun nudge(dx: Float, dy: Float) { (place ?: Offset(0.5f, 0.5f)).let { pending = Offset((it.x + dx).coerceIn(0f, 1f), (it.y + dy).coerceIn(0f, 1f)) } }
    val step = 0.004f

    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(stringResource(R.string.edit_title), style = MaterialTheme.typography.labelLarge)
        Text(stringResource(R.string.edit_hint), fontSize = 12.sp)
        Box(Modifier.fillMaxWidth().aspectRatio(vw / vh.toFloat()).clipToBounds().background(Color.Black)) {
            bmp?.let { Image(it.asImageBitmap(), null, Modifier.fillMaxSize()) }
            Canvas(
                Modifier.fillMaxSize()
                    .pointerInput(idx) { detectTapGestures { o -> pending = Offset((o.x / size.width).coerceIn(0f, 1f), (o.y / size.height).coerceIn(0f, 1f)) } }
                    .pointerInput(idx) { detectDragGestures { c, _ -> pending = Offset((c.position.x / size.width).coerceIn(0f, 1f), (c.position.y / size.height).coerceIn(0f, 1f)) } },
            ) {
                fun px(x: Double, y: Double) = Offset((x * size.width).toFloat(), (y * size.height).toFloat())
                for (k in maxOf(0, idx - 8) until minOf(n - 1, idx + 8)) { // trail
                    val a = fused[k]; val b = fused[k + 1]
                    if (a != null && b != null) drawLine(Color(0x99FFA000), px(a[0], a[1]), px(b[0], b[1]), 3f)
                }
                if (cur != null) {
                    val c = Offset(cur.x * size.width, cur.y * size.height)
                    val col = if (idx in pinIdx) Color(0xFF00E676) else Color(0xFFFFA000)
                    drawCircle(col, 18.dp.toPx(), c, style = Stroke(3.dp.toPx()))
                    drawCircle(col, 3.dp.toPx(), c)
                }
                pending?.let {
                    val c = Offset(it.x * size.width, it.y * size.height); val r = 22.dp.toPx()
                    drawLine(Color.Cyan, Offset(c.x - r, c.y), Offset(c.x + r, c.y), 3f); drawLine(Color.Cyan, Offset(c.x, c.y - r), Offset(c.x, c.y + r), 3f)
                }
            }
        }
        Text(
            String.format(Locale.ROOT, "%d / %d | t %.2f s | conf %.2f | pins %d%s", idx + 1, n, ts[idx], conf[idx], free.pins.size, if (idx in pinIdx) " | PIN" else ""),
            fontFamily = FontFamily.Monospace, fontSize = 12.sp,
        )
        // confidence timeline: tap or drag to seek; white ticks = pins
        Canvas(
            Modifier.fillMaxWidth().height(32.dp)
                .pointerInput(n) { detectTapGestures { o -> go((o.x / size.width * (n - 1)).toInt()) } }
                .pointerInput(n) { detectHorizontalDragGestures { c, _ -> go((c.position.x / size.width * (n - 1)).toInt()) } },
        ) {
            val w = size.width / n
            for (i in 0 until n) {
                val q = conf[i]
                drawRect(if (q >= 0.7) Color(0xFF2E7D32) else if (q >= 0.4) Color(0xFFF9A825) else Color(0xFFC62828), Offset(i * w, 0f), Size(maxOf(w, 1f), size.height))
            }
            for (p in pinIdx) drawRect(Color.White, Offset(p * w, 0f), Size(maxOf(w, 2.dp.toPx()), size.height))
            drawRect(Color.Black, Offset(idx * w - 1.dp.toPx(), 0f), Size(3.dp.toPx(), size.height))
        }
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedButton(onClick = { nextWeak(conf, idx, -1)?.let { go(it) } }) { Text(stringResource(R.string.edit_prev_weak)) }
            OutlinedButton(onClick = { go(idx - 1) }) { Text("◀") }
            OutlinedButton(onClick = { go(idx + 1) }) { Text("▶") }
            OutlinedButton(onClick = { nextWeak(conf, idx, +1)?.let { go(it) } }) { Text(stringResource(R.string.edit_next_weak)) }
            OutlinedButton(enabled = pinIdx.any { it < idx }, onClick = { go(pinIdx.last { it < idx }) }) { Text(stringResource(R.string.edit_prev_pin)) }
            OutlinedButton(enabled = pinIdx.any { it > idx }, onClick = { go(pinIdx.first { it > idx }) }) { Text(stringResource(R.string.edit_next_pin)) }
        }
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedButton(onClick = { nudge(-step, 0f) }) { Text("←") }
            OutlinedButton(onClick = { nudge(step, 0f) }) { Text("→") }
            OutlinedButton(onClick = { nudge(0f, -step) }) { Text("↑") }
            OutlinedButton(onClick = { nudge(0f, step) }) { Text("↓") }
            Button(enabled = place != null, onClick = { place?.let { onEdit(free.withPin(ts[idx], it.x.toDouble(), it.y.toDouble(), tol)); pending = null } }) { Text(stringResource(R.string.edit_pin)) }
            OutlinedButton(enabled = idx in pinIdx, onClick = { onEdit(free.withoutPin(ts[idx], tol)) }) { Text(stringResource(R.string.edit_unpin)) }
            OutlinedButton(enabled = free.pins.isNotEmpty(), onClick = { onEdit(free.copy(pins = emptyList())) }) { Text(stringResource(R.string.edit_clear)) }
        }
        Text(stringResource(R.string.edit_zoom, Math.pow(2.0, zoom.toDouble())), fontSize = 12.sp)
        Slider(value = zoom, valueRange = 0.5f..2.5f, onValueChange = { zoom = it }, onValueChangeFinished = { onEdit(free.copy(zoom = zoom.toDouble())) })
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(enabled = !busy, onClick = onRetrack) { Text(stringResource(R.string.edit_retrack)) }
            OutlinedButton(enabled = busy, onClick = onCancel) { Text(stringResource(R.string.scan_cancel)) }
        }
        if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (msg.isNotEmpty()) Text(msg, fontSize = 12.sp)
    }
}
