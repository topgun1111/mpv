package com.takipli.oynat.core

import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt

// ---- Otomatik kameraman (CameraDirector): takip verisinden kadraj kararı. Takip modelinden bağımsızdır. ----

/** Kameranın davranışı. */
enum class CamMode {
    /** Özneyi hedef boyutta tutar (eski, varsayılan davranış). */
    SIZE,

    /** SIZE + yavaş/ölü bölgeli zoom + hafif look-ahead: insan kameramanı gibi sakin. */
    CINEMATIC,

    /** Zoom sabit, yalnız kaydırır (özne büyüyüp küçülse de zoom değişmez). */
    FOLLOW,
}

/** Öznenin çıktı karesindeki yatay yeri (kare genişliğinin oranı). */
enum class CamPos(val x: Double) { LEFT(0.35), CENTER(0.5), RIGHT(0.65) }

/** Hangi hareketlere izin var. */
enum class CamZoom {
    /** Zoom + kaydırma. */
    ZOOM_CROP,

    /** Zoom sabit (öznenin ortanca boyutuna göre), yalnız kırpma penceresi kayar. */
    CROP_ONLY,

    /** Yalnız zoom, pencere kare ortasında kalır. */
    ZOOM_ONLY,
}

/**
 * Kamera yönetmeni ayarları. Varsayılan = eski davranış (görüntüler birebir aynı çıkar).
 * [lookAheadS]: null = moda göre (CINEMATIC 0.25 sn, diğerleri 0); sınır 0..1 sn. Çevrimdışı olduğumuz için "gelecek"
 * zaten bilinir; look-ahead kamerayı özneden biraz önce hareket ettirir ve gecikmeli takip hissini azaltır.
 */
data class Director(
    val mode: CamMode = CamMode.SIZE,
    val pos: CamPos = CamPos.CENTER,
    val zoom: CamZoom = CamZoom.ZOOM_CROP,
    val lookAheadS: Double? = null,
) {
    val isDefault: Boolean get() = this == Director()

    /** FOLLOW modu zoom'u kilitler; CROP_ONLY ile aynı etkiyi verir. */
    val lockZoom: Boolean get() = mode == CamMode.FOLLOW || zoom == CamZoom.CROP_ONLY

    fun effectiveLookAheadS(): Double = min(max(lookAheadS ?: if (mode == CamMode.CINEMATIC) 0.25 else 0.0, 0.0), 1.0)
}

/**
 * Bir sürekli takip aralığı için görüntüler. [sm]: düzeltilmiş kutu dizileri (cx, cy, w, h; normalize), [dt]: örnek aralığı (sn).
 * Aralığın sonunda look-ahead kaydırması son örneğe sıkışır (kamera aralık dışına bakmaz).
 */
internal fun directRun(sm: List<DoubleArray>, dt: Double, cfg: Config, minFit: Double, d: Director): List<View> {
    val n = sm[0].size
    val shift = if (dt > 0) (d.effectiveLookAheadS() / dt).roundToInt() else 0
    fun boxAt(j: Int): BBox {
        val k = min(j + shift, n - 1)
        return BBox(sm[0][k] - sm[2][k] / 2, sm[1][k] - sm[3][k] / 2, sm[0][k] + sm[2][k] / 2, sm[1][k] + sm[3][k] / 2)
    }
    // zoom serisi (log2): özne boyutundan; sonra strateji/moda göre sakinleştirilir
    var z = DoubleArray(n) { zoomForBbox(boxAt(it), 1.0, 1.0, cfg.targetFill, cfg.minZoom, cfg.maxZoom, minFit) }
    if (d.lockZoom) {
        val med = z.sorted()[n / 2]
        z = DoubleArray(n) { med }
    } else if (d.mode == CamMode.CINEMATIC) {
        z = smoothZeroPhase(z, cfg.offlineAlpha * 0.5) // zoom, kaydırmadan daha yavaş
        val dz = cfg.deadZoneZoom
        var cur = z[0]
        for (i in 0 until n) { // ölü bölge: küçük boy değişimi zoom'u oynatmaz
            if (z[i] > cur + dz) cur = z[i] - dz else if (z[i] < cur - dz) cur = z[i] + dz
            z[i] = cur
        }
    }
    return List(n) { j ->
        val b = boxAt(j)
        val zoom = max(z[j], 0.0)
        val cw = 1.0 / 2.0.pow(zoom) // kırpma penceresinin normalize genişliği
        val half = cw / 2
        if (d.zoom == CamZoom.ZOOM_ONLY) {
            View(zoom, 0.0, 0.0)
        } else {
            val cx = (b.cx + (0.5 - d.pos.x) * cw).coerceIn(half, 1.0 - half)
            val cy = b.cy.coerceIn(half, 1.0 - half)
            View(zoom, 0.5 - cx, 0.5 - cy)
        }
    }
}
