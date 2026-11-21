package com.takipli.oynat

import android.graphics.Bitmap
import com.takipli.oynat.core.APPEARANCE_BINS

/** Low-cost clothing-colour evidence from a clean person box (normalized x1/y1/x2/y2). */
object PersonAppearance {
    fun describe(image: Bitmap, box: List<Double>): List<Double>? {
        if (box.size < 4 || image.width <= 0 || image.height <= 0) return null
        if (box.take(4).any { !it.isFinite() }) return null
        val left = (box[0] * image.width).toInt().coerceIn(0, image.width - 1)
        val right = (box[2] * image.width).toInt().coerceIn(0, image.width)
        val top = (box[1] * image.height).toInt().coerceIn(0, image.height - 1)
        val bottom = (box[3] * image.height).toInt().coerceIn(0, image.height)
        if (right - left < 16 || bottom - top < 60) return null
        val width = right - left; val height = bottom - top
        val hist = DoubleArray(APPEARANCE_BINS)
        // Centre of the torso/legs avoids much of the background and outline pixels.
        for (half in 0..1) for (yy in 0 until 12) for (xx in 0 until 12) {
            val x = (left + width * (0.25 + 0.50 * (xx + 0.5) / 12.0)).toInt().coerceIn(left, right - 1)
            val relY = if (half == 0) 0.18 + 0.33 * (yy + 0.5) / 12.0 else 0.53 + 0.36 * (yy + 0.5) / 12.0
            val y = (top + height * relY).toInt().coerceIn(top, bottom - 1)
            val rgb = image.getPixel(x, y)
            hist[half * 24 + ((rgb shr 16) and 255) / 32]++
            hist[half * 24 + 8 + ((rgb shr 8) and 255) / 32]++
            hist[half * 24 + 16 + (rgb and 255) / 32]++
        }
        for (i in hist.indices) hist[i] /= 144.0
        return hist.toList()
    }
}
