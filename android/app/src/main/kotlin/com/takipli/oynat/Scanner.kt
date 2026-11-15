package com.takipli.oynat

import android.content.Context
import android.net.Uri
import android.os.SystemClock
import com.takipli.oynat.core.ByteTracker
import com.takipli.oynat.core.Config
import com.takipli.oynat.core.Formats
import com.takipli.oynat.core.LostWatch
import com.takipli.oynat.core.PreviewHold
import com.takipli.oynat.core.ScanPipeline
import com.takipli.oynat.core.Target
import com.takipli.oynat.core.TargetPick
import com.takipli.oynat.core.TrackDoc
import com.takipli.oynat.core.buildScanDoc
import com.takipli.oynat.core.livePickTarget
import com.takipli.oynat.core.liveRelink
import com.takipli.oynat.core.previewOverlay
import com.takipli.oynat.core.scanSig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import java.io.File

class ScanProgress(
    /** samples so far, including the ones loaded from an interrupted scan */
    val samples: Int,
    /** estimate of the final sample count (0 = unknown duration) */
    val total: Int,
    val t: Double,
    val cuts: Int,
    /** samples that came from the interrupted scan this run resumed */
    val resumed: Int,
)

class ScanResult(val doc: TrackDoc, val cached: Boolean, val wallS: Double, val newSamples: Int, val videoS: Double, val repicks: List<TargetPick> = emptyList()) {
    val xRealtime: Double get() = if (wallS > 0) videoS / wallS else 0.0
}

/**
 * Part 9 scan engine: decode (Part 7) -> pose model (Part 5/6) -> camera motion + cut (Part 8) -> ByteTrack +
 * pose association (`core.ScanPipeline`) -> `track.json` version 2. Resumable: an interrupted or cancelled scan leaves
 * `<trackFile>.partial`; the next call with the same signature (video, fps, model) continues after its last sample.
 * A finished scan with a matching signature is returned without work (cache).
 */
object Scanner {
    private const val SAVE_EVERY_MS = 30_000L

    private fun readDoc(f: File, sig: String): TrackDoc? =
        runCatching { Formats.parseTrack(f.readText()) }.getOrNull()?.takeIf { it.sig == sig && it.samples.isNotEmpty() }

    /** The interrupted scan of `trackFile` (`<trackFile>.partial`), or null when there is none / it holds no samples. */
    internal fun loadPartial(trackFile: File): TrackDoc? =
        runCatching { Formats.parseTrack(File(trackFile.path + ".partial").readText()) }.getOrNull()?.takeIf { it.samples.isNotEmpty() }

    internal fun writeAtomic(f: File, doc: TrackDoc) {
        f.parentFile?.mkdirs()
        val tmp = File(f.path + ".tmp")
        tmp.writeText(Formats.encodeTrack(doc))
        if (!tmp.renameTo(f)) { f.delete(); check(tmp.renameTo(f)) { "cannot write ${f.name}" } }
    }

    /**
     * `videoId` identifies the video file (the caller uses uri + size + modified time). `fps` = sample rate.
     * Throws on decode/model errors after saving the partial scan; cancels cleanly (partial saved).
     */
    suspend fun scan(
        ctx: Context,
        uri: Uri,
        videoId: String,
        runner: PoseRunner,
        fps: Double,
        trackFile: File,
        cfg: Config = Config(),
        maxSide: Int = 960,
        pick: TargetPick? = null,
        /** A-B scan: only `[rangeA, rangeB]` seconds are scanned (null = clip start / end). The pick frame must lie inside. */
        rangeA: Double? = null,
        rangeB: Double? = null,
        onPreview: ((ScanPreview) -> Unit)? = null,
        /** The target has been gone for a few seconds: the scan WAITS here for the user (new pick, or null = go on unchanged). */
        onLost: (suspend (Double) -> TargetPick?)? = null,
        onProgress: (ScanProgress) -> Unit = {},
    ): ScanResult = withContext(Dispatchers.Default) {
        val t0 = SystemClock.elapsedRealtime()
        val info = VideoDecoder.probe(ctx, uri)
        val modelTag = "${runner.modelName}:${(runner.modelMb * 1e6).toLong()}" + if (runner.npu) ":npu" else ""
        val sig = scanSig(videoId + (if (info.userRot != 0) "|rot${info.userRot}" else "") + rangeTag(rangeA, rangeB), fps, modelTag) // a manual rotation changes every frame: new cache key
        val partial = File(trackFile.path + ".partial")

        readDoc(trackFile, sig)?.takeIf { it.version >= 2 }?.let { // the signature includes the turn, so an older cached file without the stored value was made with the current one
            val d = if (it.video.rot < 0) it.copy(video = it.video.copy(rot = info.userRot)) else it
            return@withContext ScanResult(d, true, 0.0, 0, 0.0)
        }
        val prior = readDoc(partial, sig)?.samples.orEmpty()
        val pipe = ScanPipeline(cfg, ByteTracker.fromConfig(cfg, fps)) // loss window in seconds, not samples: a few seconds of occlusion keep the ID at any scan fps
        val pvHold = PreviewHold(cfg.kpHoldS)
        pipe.resume(prior)
        val startS = prior.lastOrNull()?.let { it.t + 0.5 / fps } ?: (rangeA ?: 0.0).coerceAtLeast(0.0) // half a grid step: next grid time, no repeat
        val endS = rangeB ?: Double.POSITIVE_INFINITY
        val clipRange = if (rangeA == null && rangeB == null) null else listOf(rangeA ?: 0.0, rangeB ?: info.durationS)
        val useAnalysis = (cfg.gmc || cfg.cutDetect) && OpenCvFlow.available
        val analyzer = if (useAnalysis) FrameAnalyzer(cfg.gmcSide, cfg.cutHist, cfg.cutDiff) else null
        val total = if (info.durationS > 0) prior.size + ((minOf(info.durationS, endS) - startS) * fps).toInt().coerceAtLeast(0) else 0
        var cuts = prior.count { it.cut == 1 }
        var lastSave = SystemClock.elapsedRealtime()
        var lastPreview = 0L
        var liveTarget: Target? = null
        var liveTried = false
        var liveRef: com.takipli.oynat.core.FreeRef? = null
        var curPick = pick
        val repicks = ArrayList<TargetPick>()
        val lostWatch = LostWatch()
        // Debug Part 1: predictive watch (throttling, memory, battery) + where the time goes per frame
        val watch = ScanWatch(ctx, "scan", total, fps)
        var lastCb = 0L
        Diag.preflightStorage(ctx, "scan files", ((info.durationS * fps).toLong() * 6_000L) + (8L shl 20))

        fun snapshot() = buildScanDoc(
            uri.toString(), info.width, info.height, info.frameRate ?: fps, info.durationS, fps,
            pipe.samples.toList(), sig, videoId, info.userRot, // the turn is stored so later stages use the scan's own orientation
        ).copy(range = clipRange)

        try {
            VideoDecoder.sample(ctx, uri, fps, startS, endS, maxSide = maxSide, userRot = info.userRot) { f ->
                currentCoroutineContext().ensureActive()
                val cb0 = System.nanoTime()
                val bmp = f.bitmap
                val pr = runner.detectRobust(bmp, cfg.liveDetConf, cfg.detIou)
                val poses = pr.poses
                val an0 = System.nanoTime()
                // Like Pipeline.step: a failed camera estimate never stops tracking.
                val a = analyzer?.let { runCatching { it.analyze(bmp, pipe.boxes) }.getOrNull() }
                val anMs = (System.nanoTime() - an0) / 1e6
                var pvMs = 0.0
                val cut = cfg.cutDetect && a?.cut == true
                val motion = if (cfg.gmc && a != null && !cut && a.motionOk) a.motion else null
                val s = pipe.step(f.t, bmp.width, bmp.height, poses, motion, cut)
                // Live target: resolved once the scan has reached the pick frame (independent of the preview, the loss alert needs it too)
                val cp = curPick
                if (liveTarget == null && !liveTried && cp != null && s.t >= cp.t - 0.5 / fps) {
                    liveTried = true
                    liveTarget = livePickTarget(pipe.samples, bmp.width, bmp.height, cp, cfg)
                    liveRef = com.takipli.oynat.core.freeRef(pipe.samples, liveTarget)
                }
                // The tracker may give the person a new ID: link it (cheap check, the relink search runs on every 3rd sample while absent)
                if (liveTarget != null && pipe.samples.size % 3 == 0) liveTarget = liveRelink(pipe.samples, bmp.width, bmp.height, liveTarget, s)
                // Target gone for a few seconds: vibrate + let the user jump to a clear frame and pick again, then go on
                val lt = liveTarget
                if (onLost != null && lt != null && lt.id >= 0) {
                    val ids = setOf(lt.id) + lt.linked
                    val present = s.d.any { it.size >= 6 && it[0].toInt() in ids }
                    if (lostWatch.update(s.t, present)) {
                        val np = onLost(s.t)
                        if (np != null) {
                            repicks += np; curPick = np; liveTarget = null; liveTried = false; liveRef = null
                            lostWatch.reset(maxOf(s.t, np.t) + 1.0)
                        } else lostWatch.snooze(s.t + 6.0)
                    }
                }
                // Part 12: at most ~5 small previews per second; only a bitmap copy + a tiny overlay, never blocks the scan
                val now = SystemClock.elapsedRealtime()
                if (onPreview != null && now - lastPreview >= PREVIEW_MIN_MS) {
                    lastPreview = now
                    val pv0 = System.nanoTime()
                    // The scan starts at 0 s but the pick was made on a later frame: resolve only once the scan has reached the pick frame
                    // (resolveTap takes the sample nearest to pick.t, so earlier it hit a wrong frame or nothing, and no green crop / red box showed).
                    onPreview(ScanPreview(f.t, previewBitmap(bmp), pvHold.apply(f.t, previewOverlay(s, bmp.width, bmp.height, liveTarget, cfg, liveRef))))
                    pvMs = (System.nanoTime() - pv0) / 1e6
                }
                bmp.recycle()
                if (s.cut == 1) cuts++
                onProgress(ScanProgress(pipe.samples.size, total, f.t, cuts, prior.size))
                if (lastCb != 0L) watch.frame((cb0 - lastCb) / 1e6, pr.totalMs, anMs, pvMs, pipe.samples.size)
                lastCb = cb0
                if (SystemClock.elapsedRealtime() - lastSave >= SAVE_EVERY_MS) {
                    writeAtomic(partial, snapshot()); lastSave = SystemClock.elapsedRealtime()
                }
                true
            }
        } catch (e: Throwable) {
            watch.finish(false, "${e.javaClass.simpleName}: ${(e.message ?: "").take(120)} after ${pipe.samples.size} samples")
            withContext(NonCancellable) {
                if (pipe.samples.isNotEmpty()) runCatching { writeAtomic(partial, snapshot()) }
                Unit
            }
            throw e
        }
        val doc = snapshot()
        writeAtomic(trackFile, doc)
        partial.delete()
        val newSamples = pipe.samples.size - prior.size
        watch.finish(true, "$newSamples new samples, ${pipe.samples.size} total, cuts $cuts")
        Diag.checkTimeline(ctx, pipe.samples.map { it.t }, 1.0 / fps)
        val videoS = if (newSamples > 0) pipe.samples.last().t - (prior.lastOrNull()?.t ?: pipe.samples.first().t) else 0.0
        ScanResult(doc, false, (SystemClock.elapsedRealtime() - t0) / 1000.0, newSamples, videoS, repicks)
    }
}
