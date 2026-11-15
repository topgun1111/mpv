package com.takipli.oynat

import android.graphics.Bitmap
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.takipli.oynat.core.COCO_SKELETON
import com.takipli.oynat.core.PreviewOverlay
import com.takipli.oynat.core.TargetState
import com.takipli.oynat.core.previewInfoLines
import kotlin.math.max

/** Part 12: one preview frame from the running scan: small bitmap (longer side <= [PREVIEW_SIDE]) + what to draw on it. */
class ScanPreview(val t: Double, val bitmap: Bitmap, val overlay: PreviewOverlay)

const val PREVIEW_SIDE = 320
const val PREVIEW_MIN_MS = 200L // at most ~5 previews per second

/** Downscaled copy that is safe to keep after the scanner recycles `src`. */
fun previewBitmap(src: Bitmap): Bitmap {
    val r = PREVIEW_SIDE.toFloat() / max(src.width, src.height)
    if (r >= 1f) return src.copy(Bitmap.Config.ARGB_8888, false)
    return Bitmap.createScaledBitmap(src, max(1, (src.width * r).toInt()), max(1, (src.height * r).toInt()), true)
}

private const val KP_MIN = 0.35 // = Config.kpMinConf (joints below it are not drawn)

/** Frame + skeletons + target person (yellow) + part box (red) + camera crop (green) + status text (zoom, target state, camera motion / cut). */
@Composable
fun ScanPreviewView(p: ScanPreview) {
    Box(Modifier.fillMaxWidth().aspectRatio(p.bitmap.width / p.bitmap.height.toFloat())) {
        Image(p.bitmap.asImageBitmap(), null, Modifier.matchParentSize())
        Canvas(Modifier.matchParentSize()) {
            fun at(x: Double, y: Double) = Offset((x * size.width).toFloat(), (y * size.height).toFloat())
            fun rect(b: DoubleArray, c: Color, w: Float) =
                drawRect(c, at(b[0], b[1]), Size(((b[2] - b[0]) * size.width).toFloat(), ((b[3] - b[1]) * size.height).toFloat()), style = Stroke(w))
            val part = p.overlay.partBox
            fun inPart(x: Double, y: Double) = part != null && x in part[0]..part[2] && y in part[1]..part[3]
            for (o in p.overlay.persons) {
                val c = if (o.isTarget) Color.Yellow else Color.White
                rect(o.box, c.copy(alpha = if (o.isTarget) 1f else 0.5f), 2f)
                val k = o.kp ?: continue
                for ((a, b) in COCO_SKELETON) if (k[3 * a + 2] >= KP_MIN && k[3 * b + 2] >= KP_MIN) {
                    // the tracked part (bones inside the red box) is bold; the rest of the body is faint, so the stick figure does not hide what is followed
                    val bold = o.isTarget && (part == null || (inPart(k[3 * a], k[3 * a + 1]) && inPart(k[3 * b], k[3 * b + 1])))
                    drawLine(if (bold) c else c.copy(alpha = 0.3f), at(k[3 * a], k[3 * a + 1]), at(k[3 * b], k[3 * b + 1]), if (bold) 6f else 2f)
                }
            }
            val held = p.overlay.targetState == TargetState.LOST // target hidden: the last boxes are kept (faded) for a moment
            val fade = if (held) 0.5f else 1f
            part?.let { rect(it, Color.Red.copy(alpha = fade), 4f) }
            p.overlay.crop?.let { rect(it, Color.Green.copy(alpha = fade), 3f) }
        }
        val (l1, l2) = previewInfoLines(p.overlay)
        val c1 = when (p.overlay.targetState) {
            TargetState.TRACKING -> Color.Green
            TargetState.LOST -> Color.Red
            TargetState.NONE -> Color.White
        }
        Column(Modifier.align(Alignment.TopStart).padding(4.dp).background(Color.Black.copy(alpha = 0.55f)).padding(horizontal = 4.dp, vertical = 2.dp)) {
            Text(l1, color = c1, fontSize = 11.sp)
            Text(l2, color = if (p.overlay.cut) Color.Yellow else Color.White, fontSize = 11.sp)
        }
    }
}
