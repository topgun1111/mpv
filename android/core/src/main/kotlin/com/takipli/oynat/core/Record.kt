package com.takipli.oynat.core

import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow

// ---- Kayıt modu: video oynarken zoom ve konumu elle yönet; kaydedilen anahtar kareler otomatik kadrajın yerine geçer. ----

private const val LN2 = 0.6931471805599453

/** Elle kaydedilmiş bir parça: [t0, t1] aralığı için anahtar kareler `[t, zoom, panX, panY]` (zaman artan). */
data class RecSeg(val t0: Double, val t1: Double, val keys: List<ViewKey>)

/** Pan'ı kırpma penceresi kare dışına taşmayacak şekilde sınırlar (`cropRect` ile aynı kural). */
fun clampView(v: View, maxZoom: Double): View {
    val z = min(max(v.zoom, 0.0), maxZoom)
    val lim = max(0.5 - 0.5 / 2.0.pow(z), 0.0)
    return View(z, min(max(v.panX, -lim), lim), min(max(v.panY, -lim), lim))
}

/**
 * Bir dokunma hareketini görünüme uygular. [dxFrac]/[dyFrac]: parmağın gösterim yüzeyinin genişlik/yüksekliğine oranıyla kayması
 * (içerik parmakla birlikte kayar), [zoomFactor]: iki parmakla büyütme çarpanı (1 = değişmez).
 */
fun applyGesture(v: View, dxFrac: Double, dyFrac: Double, zoomFactor: Double, maxZoom: Double): View {
    val z = v.zoom + (if (zoomFactor > 0) ln(zoomFactor) / LN2 else 0.0)
    val s = 2.0.pow(max(v.zoom, 0.0)) // pan, kare birimiyle: yüzeydeki kayma / ölçek
    return clampView(View(z, v.panX + dxFrac / s, v.panY + dyFrac / s), maxZoom)
}

/** Parçayı görünümlere işler: [t0, t1] içindeki eski anahtarlar silinir, kayıt girer. Başlangıç değeri kayıt anındaki görünümdür, süreklilik bozulmaz. */
fun mergeSegment(views: List<ViewKey>, seg: RecSeg): List<ViewKey> {
    if (seg.keys.isEmpty()) return views
    val before = views.filter { it[0] < seg.t0 }
    val after = views.filter { it[0] > seg.t1 }
    return before + seg.keys.sortedBy { it[0] } + after
}

fun mergeSegments(views: List<ViewKey>, segs: List<RecSeg>): List<ViewKey> = segs.fold(views) { acc, s -> mergeSegment(acc, s) }

/** Kayıt sırasında anahtar kare ekler: yalnız zaman en az [minDt] ilerlediyse (gerisarma/duraklatma anahtar üretmez). */
fun appendKey(keys: List<ViewKey>, t: Double, v: View, minDt: Double = 0.03): List<ViewKey> {
    val last = keys.lastOrNull()
    if (last != null && t < last[0] + minDt) return keys
    return keys + listOf(listOf(t, v.zoom, v.panX, v.panY))
}
