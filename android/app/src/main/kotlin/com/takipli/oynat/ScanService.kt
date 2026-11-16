package com.takipli.oynat

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import com.takipli.oynat.core.Config
import com.takipli.oynat.core.Formats
import com.takipli.oynat.core.TargetPick
import com.takipli.oynat.core.applyPicks
import com.takipli.oynat.core.buildTargetViews
import com.takipli.oynat.core.rangeTag
import com.takipli.oynat.core.scanSig
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.io.File

/** What the UI shows. The scan itself lives in [ScanService], so it survives the screen going off and the activity closing. */
sealed interface ScanUi {
    data object Idle : ScanUi
    class Running(val p: ScanProgress?, val pv: ScanPreview? = null) : ScanUi
    /** `targetText` null = nobody was at the picked point (scan is kept; pick again without rescanning). */
    class Done(val samples: Int, val cached: Boolean, val targetText: String?, val file: String, val xRealtime: Double, val preview: Boolean) : ScanUi
    /** The target has been gone for a few seconds: the scan is PAUSED at video time `t` until [ScanService.resolveLost] is called. */
    class Lost(val t: Double, val uri: String, val videoId: String, val p: ScanProgress?) : ScanUi
    class Failed(val message: String, val cancelled: Boolean) : ScanUi
    /** Cancel was pressed: the partial scan is being turned into a previewable / exportable result. */
    data object Saving : ScanUi
    /**
     * Cancelled. `file` = result built from the processed part (null = nothing usable: no samples, or the scan had already finished),
     * `targetText` null = nobody was found at the pick in the processed part. The interrupted scan itself is kept for resuming
     * until [ScanService.clearProgress].
     */
    class Cancelled(val samples: Int, val t: Double, val file: String?, val targetText: String?) : ScanUi
}

/**
 * Part 11 foreground service: runs [Scanner] with the pose model, then resolves the user's [TargetPick] to {person, part}
 * and stores `target` + `views` in the scan's `track.json` (so the part can be changed later without rescanning).
 * Intent extras say what to scan; START_REDELIVER_INTENT restarts an interrupted scan, which resumes from `.partial`.
 */
class ScanService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var job: Job? = null
    private var wake: PowerManager.WakeLock? = null

    override fun onBind(i: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_CANCEL) { job?.cancel() ?: stopSelf(); return START_NOT_STICKY }
        if (intent == null || job?.isActive == true) return START_NOT_STICKY
        startForeground(NOTE_ID, note(getString(R.string.scan_notify_start), null), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        wake = (getSystemService(POWER_SERVICE) as PowerManager).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "takipli:scan")
            .apply { acquire(WAKE_MAX_MS) }
        post(ScanUi.Running(null))
        job = scope.launch { run(intent); stopSelf(startId) }
        return START_REDELIVER_INTENT
    }

    private suspend fun run(i: Intent) {
        cancelCtx = null; seenRepicks.clear()
        try {
            val uri = Uri.parse(i.getStringExtra(X_URI))
            val videoId = i.getStringExtra(X_VIDEO_ID).orEmpty()
            val fps = i.getDoubleExtra(X_FPS, 10.0)
            val cfg = Config()
            val pick = Formats.json.decodeFromString<TargetPick>(i.getStringExtra(X_PICK).orEmpty())
            val ra = i.getDoubleExtra(X_A, Double.NaN).takeIf { !it.isNaN() }; val rb = i.getDoubleExtra(X_B, Double.NaN).takeIf { !it.isNaN() }
            val file = scanFile(this, videoId, ra, rb)
            cancelCtx = CancelCtx(file, pick, cfg, uri, seenRepicks)
            val withPreview = i.getBooleanExtra(X_PREVIEW, true)
            var lastNote = 0L
            var lastPv: ScanPreview? = null
            var lastP: ScanProgress? = null
            // Target gone for a few seconds: vibrate, pause here, and wait for the user (new pick or "go on"); the UI calls resolveLost()
            val onLost: suspend (Double) -> TargetPick? = { t ->
                alertLost()
                val d = CompletableDeferred<TargetPick?>()
                pendingLost = d
                notify(note(getString(R.string.scan_notify_lost), null))
                post(ScanUi.Lost(t, i.getStringExtra(X_URI).orEmpty(), videoId, lastP))
                try { d.await().also { np -> if (np != null) seenRepicks += np } } finally { pendingLost = null; post(ScanUi.Running(lastP, lastPv)) }
            }
            val res = PoseRunner(this, i.getStringExtra(X_MODEL).orEmpty(), threads = 4, wantNpu = i.getBooleanExtra(X_NPU, false)).use { runner ->
                Scanner.scan(this, uri, videoId, runner, fps, file, cfg, pick = pick, rangeA = ra, rangeB = rb, onPreview = if (withPreview) ({ v: ScanPreview -> lastPv = v }) else null, onLost = onLost) { p ->
                    lastP = p
                    post(ScanUi.Running(p, lastPv))
                    val now = SystemClock.elapsedRealtime()
                    if (now - lastNote >= 1000) { lastNote = now; notify(note(getString(R.string.scan_notify_run, p.samples, p.total), p)) }
                }
            }
            var picked = applyPicks(if (pick.free) res.doc.copy(pt = null) else res.doc, pick, res.repicks, cfg, robust = true) // repicks: the user picked again after the target was lost
            val fp = picked?.target?.free
            if (picked != null && fp != null && OpenCvFlow.available) { // Part 16b: tracker passes for the tapped spot
                try {
                    val pt = PointScanner.run(this, uri, picked, fp) { d, tot, t -> post(ScanUi.Running(ScanProgress(d, tot, t, 0, 0), null)) }
                    val d2 = picked.copy(pt = pt)
                    picked = d2.copy(views = buildTargetViews(d2, d2.target!!, cfg, robust = true))
                } catch (e: CancellationException) { throw e } catch (e: Throwable) { ErrorLog.record(this, "point", e) } // keeps the anchor-only views
            }
            val out = picked ?: res.doc
            if (picked != null) Scanner.writeAtomic(file, picked)
            // Debug Part 2: is the chosen target actually trackable? (joint confidence, presence, camera jumps)
            if (picked == null) Diag.note(this, "scan", "PICK_NO_TARGET", "nobody at the picked point (t=${pick.t}); the scan is kept, pick again", com.takipli.oynat.core.Sev.WARN)
            else runCatching { com.takipli.oynat.core.targetFindings(picked).forEach { Diag.event(this, "scan", it) } }
            // zoom range of the built views (flat = a part target that never zooms)
            picked?.let { pk -> runCatching { val z = pk.views.map { it[1] }; Diag.note(this, "scan", "VIEWS_ZOOM", "target=${pk.target?.preset ?: pk.target?.part ?: (if (pk.target?.free != null) "free" else "person")} keys=${z.size} zoom(log2) min=${"%.2f".format(java.util.Locale.ROOT, z.minOrNull() ?: 0.0)} max=${"%.2f".format(java.util.Locale.ROOT, z.maxOrNull() ?: 0.0)} fill=${cfg.targetFill} maxZoom=${cfg.maxZoom}") } }
            Diag.note(this, "scan", "SCAN_SPEED", "${"%.2f".format(java.util.Locale.ROOT, res.xRealtime)} x realtime, ${res.newSamples} new samples, model ${i.getStringExtra(X_MODEL)} npu=${i.getBooleanExtra(X_NPU, false)} preview=$withPreview")
            if (res.newSamples > 0) Diag.event(this, "scan", com.takipli.oynat.core.speedFinding("scan", res.xRealtime, 0.1))
            val tg = picked?.target
            val text = tg?.let { if (it.free != null) "#${it.id} free point" else "#${it.id} " + (it.preset ?: it.part?.let { j -> "joint $j" } ?: "person") }
            cancelledFile(file).let { c -> listOf(c, File(c.path.replace(".track.json", ".views.json")), File(c.path.replace(".track.json", ".cam.json"))).forEach { it.delete() } } // the finished scan replaces an earlier partial result
            post(ScanUi.Done(out.samples.size, res.cached, text, file.path, res.xRealtime, withPreview))
        } catch (e: CancellationException) {
            val c = cancelCtx
            post(ScanUi.Saving)
            post(withContext(NonCancellable) { c?.let { partialResult(it) } } ?: ScanUi.Cancelled(0, 0.0, null, null))
        } catch (e: Throwable) {
            ErrorLog.record(this, "scan", e)
            post(ScanUi.Failed(Safety.friendly(this, e), false))
        } finally {
            wake?.takeIf { it.isHeld }?.release()
        }
    }

    /** Everything [partialResult] needs from the scan that was running (set in [run]). */
    private class CancelCtx(val file: File, val pick: TargetPick, val cfg: Config, val uri: Uri, val repicks: List<TargetPick>)
    @Volatile private var cancelCtx: CancelCtx? = null
    private val seenRepicks = java.util.Collections.synchronizedList(ArrayList<TargetPick>())

    /**
     * Cancel pressed: resolve the pick on the samples scanned so far (`<track>.partial`, written by [Scanner] on cancel) and store the
     * result as `<id>.cancelled.track.json` (never as the real track file: that name is the "scan finished" cache). The partial scan
     * stays for resuming. null = nothing to show.
     */
    private suspend fun partialResult(c: CancelCtx): ScanUi.Cancelled? = try {
        val part = Scanner.loadPartial(c.file) ?: return null
        val last = part.samples.last().t
        var picked = applyPicks(if (c.pick.free) part.copy(pt = null) else part, c.pick, c.repicks.toList(), c.cfg, robust = true)
        val fp = picked?.target?.free
        if (picked != null && fp != null && OpenCvFlow.available) { // free point: tracker passes over the processed part only (PointScanner stops after the last sample)
            try {
                // Bounded: this runs NonCancellable after the user pressed Cancel, and the tracker decodes the whole scanned part again
                // (4K HEVC ~0.4 s per frame): unbounded it left the screen on "preparing..." for minutes. On timeout the anchor-only views are kept.
                val pt = kotlinx.coroutines.withTimeoutOrNull(PARTIAL_TRACK_MAX_MS) { PointScanner.run(this, c.uri, picked, fp) }
                if (pt == null) Diag.note(this, "scan", "PARTIAL_TRACK_TIMEOUT", "free-point pass over the partial scan exceeded ${PARTIAL_TRACK_MAX_MS / 1000} s: kept the anchor-only result", com.takipli.oynat.core.Sev.WARN)
                else {
                    val d2 = picked.copy(pt = pt)
                    picked = d2.copy(views = buildTargetViews(d2, d2.target!!, c.cfg, robust = true))
                }
            } catch (e: CancellationException) { throw e } catch (e: Throwable) { ErrorLog.record(this, "point-partial", e) }
        }
        val out = cancelledFile(c.file)
        if (picked != null) Scanner.writeAtomic(out, picked)
        val tg = picked?.target
        val text = tg?.let { if (it.free != null) "#${it.id} free point" else "#${it.id} " + (it.preset ?: it.part?.let { j -> "joint $j" } ?: "person") }
        Diag.note(this, "scan", "SCAN_CANCELLED", "kept ${part.samples.size} samples up to t=${"%.1f".format(java.util.Locale.ROOT, last)} s, target=${text ?: "none"}")
        ScanUi.Cancelled(part.samples.size, last, if (picked != null) out.path else null, text)
    } catch (e: Throwable) {
        ErrorLog.record(this, "scan-cancel", e)
        null
    }

    private val PARTIAL_TRACK_MAX_MS = 60_000L

    private fun alertLost() {
        runCatching {
            val v: Vibrator = if (Build.VERSION.SDK_INT >= 31) getSystemService(VibratorManager::class.java).defaultVibrator
            else @Suppress("DEPRECATION") (getSystemService(Context.VIBRATOR_SERVICE) as Vibrator)
            v.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 300, 150, 300, 150, 600), -1))
        }
    }

    private fun notify(n: Notification) = getSystemService(NotificationManager::class.java).notify(NOTE_ID, n)

    private fun note(text: String, p: ScanProgress?): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, getString(R.string.scan_channel), NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val cancel = PendingIntent.getService(
            this, 1, Intent(this, ScanService::class.java).setAction(ACTION_CANCEL), PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download).setContentTitle(getString(R.string.app_name)).setContentText(text)
            .setOngoing(true).setOnlyAlertOnce(true).setContentIntent(open)
            .addAction(Notification.Action.Builder(android.R.drawable.ic_menu_close_clear_cancel, getString(R.string.scan_cancel), cancel).build())
            .apply { if (p != null && p.total > 0) setProgress(p.total, p.samples.coerceAtMost(p.total), false) }
            .build()
    }

    override fun onDestroy() {
        wake?.takeIf { it.isHeld }?.release()
        scope.coroutineContext[Job]?.cancel()
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL = "scan"
        private const val NOTE_ID = 11
        private const val WAKE_MAX_MS = 4 * 60 * 60 * 1000L
        private const val ACTION_CANCEL = "com.takipli.oynat.SCAN_CANCEL"
        private const val X_A = "range_a"; private const val X_B = "range_b"
        private const val X_URI = "uri"; private const val X_VIDEO_ID = "video_id"; private const val X_FPS = "fps"
        private const val X_PREVIEW = "preview"; private const val X_PICK = "pick"; private const val X_MODEL = "model"; private const val X_NPU = "npu"

        @Volatile private var pendingLost: CompletableDeferred<TargetPick?>? = null

        /** Answer to a [ScanUi.Lost] pause: a new pick (the scan goes on and links it to the target) or null = go on without changing anything. */
        fun resolveLost(pick: TargetPick?) { pendingLost?.complete(pick) }

        private val _state = MutableStateFlow<ScanUi>(ScanUi.Idle)
        /** Written by the service, read by the UI. */
        val state: StateFlow<ScanUi> = _state
        private fun post(u: ScanUi) { _state.value = u }

        /** `files/scans/<id>.track.json`: one file per video (id from `videoId`), shared with the Part 9 cache. */
        fun scanFile(ctx: Context, videoId: String, a: Double? = null, b: Double? = null) = File(ctx.filesDir, "scans/${scanSig(videoId + rangeTag(a, b), 0.0, "")}.track.json")

        /** Result built from a cancelled scan (`<id>.cancelled.track.json`); ResultScreen exports only its processed part. */
        fun cancelledFile(trackFile: File) = File(trackFile.path.removeSuffix(".track.json") + ".cancelled.track.json")

        /**
         * "Clear progress": forgets the interrupted scan of this video (the `.partial` resume point) and the partial result with its
         * views / camera files, so the next scan starts from 0 s. A finished scan (the cache) is not touched.
         */
        fun clearProgress(ctx: Context, videoId: String, a: Double? = null, b: Double? = null) {
            val track = scanFile(ctx, videoId, a, b)
            val c = cancelledFile(track)
            listOf(File(track.path + ".partial"), File(track.path + ".partial.tmp"), c, File(c.path + ".tmp"),
                File(c.path.replace(".track.json", ".views.json")), File(c.path.replace(".track.json", ".cam.json"))).forEach { it.delete() }
            _state.value = ScanUi.Idle
        }

        fun start(ctx: Context, uri: Uri, videoId: String, model: String, npu: Boolean, fps: Double, pick: TargetPick, preview: Boolean = true, rangeA: Double? = null, rangeB: Double? = null) {
            _state.value = ScanUi.Running(null)
            ctx.startForegroundService(
                Intent(ctx, ScanService::class.java).putExtra(X_URI, uri.toString()).putExtra(X_VIDEO_ID, videoId)
                    .putExtra(X_MODEL, model).putExtra(X_NPU, npu).putExtra(X_PREVIEW, preview).putExtra(X_FPS, fps).apply { if (rangeA != null) putExtra(X_A, rangeA); if (rangeB != null) putExtra(X_B, rangeB) }
                    .putExtra(X_PICK, Formats.json.encodeToString(pick)),
            )
        }

        fun cancel(ctx: Context) {
            ctx.startService(Intent(ctx, ScanService::class.java).setAction(ACTION_CANCEL))
        }

        fun reset() { _state.value = ScanUi.Idle }
    }
}
