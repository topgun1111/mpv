package com.takipli.oynat.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** Otomatik kameraman: varsayılan davranış değişmez; mod, konum, zoom stratejisi ve look-ahead beklenen etkiyi verir. */
class DirectorTest {
    private val cfg = Config()

    /** Özne soldan sağa yürür ve yaklaşır (kutu büyür); 1 sn, 10 örnek/sn. */
    private val ts = (0..19).map { it * 0.1 }
    private val boxes: Map<Int, DoubleArray> = ts.indices.associateWith {
        val h = 0.10 + 0.004 * it // küçük özne: pencere dar, kenar kırpması konum testlerini bozmaz
        doubleArrayOf(0.30 + 0.02 * it, 0.5, h * 0.4, h)
    }

    private fun views(d: Director) = viewsFromBoxes(ts, boxes, cfg, director = d)

    @Test
    fun defaultDirectorKeepsOldViews() {
        assertEquals(viewsFromBoxes(ts, boxes, cfg), views(Director()))
        assertTrue(Director().isDefault)
    }

    @Test
    fun followLocksZoomButPans() {
        val v = views(Director(mode = CamMode.FOLLOW))
        assertTrue(v.map { it[1] }.distinct().size == 1) // zoom sabit
        assertTrue(v.map { it[2] }.distinct().size > 1) // pan değişir
    }

    @Test
    fun sizeModeAdaptsZoomToGrowingSubject() {
        val v = views(Director(mode = CamMode.SIZE, zoom = CamZoom.ZOOM_CROP, pos = CamPos.CENTER, lookAheadS = 0.0))
        assertTrue(v.first()[1] > v.last()[1]) // özne büyüdü -> zoom azaldı
    }

    @Test
    fun cinematicZoomIsCalmerThanSize() {
        fun travel(v: List<ViewKey>) = v.zipWithNext { a, b -> kotlin.math.abs(a[1] - b[1]) }.sum()
        val size = views(Director(mode = CamMode.SIZE, lookAheadS = 0.0))
        val cine = views(Director(mode = CamMode.CINEMATIC, lookAheadS = 0.0))
        assertTrue(travel(cine) <= travel(size) + 1e-9)
    }

    @Test
    fun zoomOnlyKeepsWindowCentred() {
        val v = views(Director(zoom = CamZoom.ZOOM_ONLY))
        assertTrue(v.all { it[2] == 0.0 && it[3] == 0.0 })
    }

    @Test
    fun positionShiftsSubjectInFrame() {
        val d = Director(mode = CamMode.FOLLOW)
        val l = views(d.copy(pos = CamPos.LEFT)); val c = views(d.copy(pos = CamPos.CENTER)); val r = views(d.copy(pos = CamPos.RIGHT))
        val k = 10 // ortada: kenar kırpması yok
        // pan = 0.5 - pencere merkezi; özne solda görünsün -> pencere merkezi özneden sağda -> pan daha küçük
        assertTrue(l[k][2] < c[k][2] && c[k][2] < r[k][2])
        // özne gerçekten istenen oranda: pencere merkezi + (p - 0.5) * pencere genişliği = özne x
        val z = c[k][1]; val cw = 1.0 / Math.pow(2.0, z)
        val subjectX = boxes.getValue(k)[0]
        val winL = (0.5 - l[k][2]) - cw / 2
        assertEquals(0.35, (subjectX - winL) / cw, 0.02)
    }

    @Test
    fun lookAheadMovesCameraEarly() {
        val base = Director(mode = CamMode.FOLLOW, lookAheadS = 0.0)
        val a = views(base); val b = views(base.copy(lookAheadS = 0.5))
        val k = 8
        assertTrue(b[k][2] < a[k][2]) // özne sağa yürüyor: pan = 0.5 - merkez; önden giden kamera merkezi daha sağda -> pan daha küçük
        assertEquals(0.25, Director(mode = CamMode.CINEMATIC).effectiveLookAheadS(), 1e-12)
        assertEquals(1.0, Director(lookAheadS = 9.0).effectiveLookAheadS(), 1e-12)
    }

    @Test
    fun tuningPassesDirectorToRebuild() {
        val row = (0 until N_KPT).flatMap { listOf(0.5, 0.5, 0.9) }
        val doc = TrackDoc(
            version = 2, video = VideoInfo(w = 1000, h = 1000, fps = 10.0, duration = 1.0), sampleFps = 10.0,
            samples = (0..9).map { Sample(it * 0.1, d = listOf(listOf(1.0, 0.1 + 0.05 * it, 0.3, 0.3 + 0.05 * it, 0.7, 0.9)), kp = mapOf("1" to row)) },
        )
        val t = Target(1, preset = "person")
        val zo = rebuildViews(doc, t, cfg, Tuning(director = Director(zoom = CamZoom.ZOOM_ONLY)))
        assertTrue(zo.all { it[2] == 0.0 && it[3] == 0.0 })
        assertEquals(buildTargetViews(doc, t, cfg), rebuildViews(doc, t, cfg, Tuning()))
    }
}
