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
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import com.takipli.oynat.core.Config
import com.takipli.oynat.core.Formats
import com.takipli.oynat.core.TargetPick
import com.takipli.oynat.core.TrackDoc
import com.takipli.oynat.core.PointTrack
import com.takipli.oynat.core.applyPicks
import com.takipli.oynat.core.buildTargetViews
import com.takipli.oynat.core.bodySamWindows
import com.takipli.oynat.core.occlusionStats
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
    class Running(val p: ScanProgress?, val pv: ScanPreview? = null, val warning: String? = null) : ScanUi
    /** `targetText` null = nobody was at the picked point (scan is kept; pick again without rescanning). */
    class Done(val samples: Int, val cached: Boolean, val targetText: String?, val file: String, val xRealtime: Double, val preview: Boolean) : ScanUi
    /** The target has been gone for a few seconds: the scan is PAUSED at video time `t` until [ScanService.resolveLost] is called. */
    class Lost(val t: Double, val uri: String, val videoId: String, val p: ScanProgress?) : ScanUi
    class Failed(val message: String, val cancelled: Boolean) : ScanUi
    /**
     * Cancel was pressed: the partial scan is being turned into a previewable / exportable result.
     * `samples` / `t` = what was scanned so far; `done` / `total` = steps of the tracker pass over that part (total 0 = no step count yet).
     */
    class Saving(val samples: Int = 0, val t: Double = 0.0, val done: Int = 0, val total: Int = 0) : ScanUi
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
    private val watchdogHandler = Handler(Looper.getMainLooper())
    @Volatile private var lastAdvanceMs = 0L
    @Volatile private var stallReported = false
    private val watchdog = object : Runnable {
        override fun run() {
            if (job?.isActive == true) {
                val since = SystemClock.elapsedRealtime() - lastAdvanceMs
                if (!cancelling && pendingLost == null && since >= STALL_MS && !stallReported) {
                    stallReported = true
                    val p = lastProgress
                    Diag.note(this@ScanService, "scan", "NO_PROGRESS", "no sample or tracking update for ${since / 1000}s; stage=${p?.stage}, samples=${p?.samples}/${p?.total}, t=${p?.t}", com.takipli.oynat.core.Sev.WARN)
                    val warning = getString(R.string.scan_stall_hint)
                    post(ScanUi.Running(p, warning = warning))
                    notify(note(warning, p))
                }
                watchdogHandler.postDelayed(this, WATCHDOG_POLL_MS)
            }
        }
    }

    private fun progressed(p: ScanProgress) {
        lastAdvanceMs = SystemClock.elapsedRealtime()
        stallReported = false
        lastProgress = p
    }

    override fun onBind(i: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_CANCEL) {
            val j = job
            if (j != null) j.cancel() else { cancelling = false; post(ScanUi.Cancelled(0, 0.0, null, null)); stopSelf() }
            return START_NOT_STICKY
        }
        if (intent == null || job?.isActive == true) return START_NOT_STICKY
        startForeground(NOTE_ID, note(getString(R.string.scan_notify_start), null), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        wake = (getSystemService(POWER_SERVICE) as PowerManager).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "takipli:scan")
            .apply { acquire(WAKE_MAX_MS) }
        cancelling = false
        lastAdvanceMs = SystemClock.elapsedRealtime()
        stallReported = false
        post(ScanUi.Running(null))
        job = scope.launch { run(intent); stopSelf(startId) }
        watchdogHandler.postDelayed(watchdog, WATCHDOG_POLL_MS)
        return START_REDELIVER_INTENT
    }

    private suspend fun run(i: Intent) {
        cancelCtx = null; seenRepicks.clear(); lastProgress = null
        var completedPose: TrackDoc? = null
        try {
            val uri = Uri.parse(i.getStringExtra(X_URI))
            val videoId = i.getStringExtra(X_VIDEO_ID).orEmpty()
            val requestedFps = i.getDoubleExtra(X_FPS, 10.0)
            // Android scans keep the crop through short occlusions; the core default stays
            // unchanged for PC/golden compatibility. ResultScreen can still tune this value.
            val cfg = Config(lostBridgeS = 4.0)
            val pick = Formats.json.decodeFromString<TargetPick>(i.getStringExtra(X_PICK).orEmpty())
            // The SAM point tracker uses 6 fps internally. No point/region scan needs
            // a 30/60-fps YOLO prepass (and 60 random video seeks every second).
            val fps = if (pick.free) requestedFps.coerceIn(1.0, 10.0) else requestedFps
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
                try { d.await().also { np -> if (np != null) seenRepicks += np } } finally {
                    pendingLost = null; lastAdvanceMs = SystemClock.elapsedRealtime(); post(ScanUi.Running(lastP, lastPv))
                }
            }
            val runner = if (pick.free) null else PoseRunner(this, i.getStringExtra(X_MODEL).orEmpty(), threads = 4, wantNpu = i.getBooleanExtra(X_NPU, false))
            val res = try {
                Scanner.scan(this, uri, videoId, runner, fps, file, cfg, pick = pick, rangeA = ra, rangeB = rb, onPreview = if (withPreview) ({ v: ScanPreview -> lastPv = v }) else null, onLost = onLost) { p ->
                    lastP = p; progressed(p)
                    post(ScanUi.Running(p, lastPv))
                    val now = SystemClock.elapsedRealtime()
                    if (now - lastNote >= 1000) { lastNote = now; notify(note(getString(R.string.scan_notify_run, p.samples, p.total), p)) }
                }
            } finally { runner?.close() }
            completedPose = res.doc
            var picked = applyPicks(if (pick.free) res.doc.copy(pt = null) else res.doc, pick, res.repicks, cfg, robust = true) // repicks: the user picked again after the target was lost
            val fp = picked?.target?.free
            if (picked != null && fp != null && (SamEngine.hasModels(this) || OpenCvFlow.available)) { // SAM can work even without OpenCV
                try {
                    val initial = ScanProgress(0, 1, fp.t, 0, 0, ScanStage.POINT_DECODE)
                    progressed(initial)
                    post(ScanUi.Running(initial, null))
                    Diag.note(this, "point", "POINT_TRACK_START", "${picked.samples.size} scan samples; SAM=${SamEngine.hasModels(this)}")
                    val pt = PointScanner.run(this, uri, picked, fp) { d, tot, t, stage ->
                        val progress = ScanProgress(d, tot, t, 0, 0, stage)
                        progressed(progress)
                        post(ScanUi.Running(progress, null))
                        val now = SystemClock.elapsedRealtime()
                        if (now - lastNote >= 1000) {
                            lastNote = now
                            notify(note(getString(if (stage == ScanStage.POINT_DECODE) R.string.scan_point_decode else R.string.scan_point_track, d, tot), progress))
                        }
                    }
                    val d2 = picked.copy(pt = pt)
                    picked = d2.copy(views = buildTargetViews(d2, d2.target!!, cfg, robust = true))
                } catch (e: CancellationException) { throw e } catch (e: Throwable) { ErrorLog.record(this, "point", e) } // keeps the anchor-only views
            }
            // A full-video SAM pass could take minutes after the pose scan had
            // already finished, leaving the UI apparently frozen at 50%. Run
            // only on short, internal keypoint gaps, at a reduced sample rate.
            val windows = picked?.target?.let { bodySamWindows(requireNotNull(picked), it, pick.t, cfg) }.orEmpty()
            if (windows.isNotEmpty() && picked != null && SamEngine.hasModels(this)) {
                try {
                    val base = requireNotNull(picked)
                    val combined = MutableList(base.samples.size) { emptyList<Double>() }
                    var recovered = 0
                    for ((wi, window) in windows.withIndex()) {
                        Diag.note(this, "body-sam", "RECOVERY_START", "window ${wi + 1}/${windows.size} ${window.startS}..${window.endS}s, seed ${window.seed.t}s")
                        val sam = kotlinx.coroutines.withTimeoutOrNull(BODY_SAM_WINDOW_MAX_MS) {
                            SamEngine.trackRange(this@ScanService, uri, base, window.seed,
                                window.startS, window.endS, BODY_SAM_FPS) { d, tot, t ->
                                val decodeTotal = tot / 2
                                val decoding = d < decodeTotal
                                val stageProgress = ScanProgress(
                                    if (decoding) d else d - decodeTotal,
                                    if (decoding) decodeTotal else tot - decodeTotal,
                                    t, 0, 0, if (decoding) ScanStage.SAM_DECODE else ScanStage.SAM_TRACK,
                                    wi + 1, windows.size,
                                )
                                progressed(stageProgress)
                                post(ScanUi.Running(stageProgress, null))
                                val now = SystemClock.elapsedRealtime()
                                if (now - lastNote >= 1000) {
                                    lastNote = now
                                    val label = getString(if (decoding) R.string.scan_sam_decode else R.string.scan_sam_track,
                                        wi + 1, windows.size, stageProgress.samples, stageProgress.total)
                                    notify(note(label, stageProgress))
                                }
                            }
                        }
                        if (sam == null) {
                            Diag.note(this, "body-sam", "RECOVERY_SKIPPED", "window ${wi + 1} timed out or returned no masks; pose views preserved", com.takipli.oynat.core.Sev.WARN)
                            continue
                        }
                        for ((j, row) in sam.a.withIndex()) {
                            if (j >= combined.size || row.size < 5 || row[2] < 0.6) continue
                            if (combined[j].size < 5 || row[2] > combined[j][2]) { combined[j] = row; recovered++ }
                        }
                    }
                    if (recovered > 0) {
                        val merged = base.copy(pt = PointTrack(a = combined), samSeedT = windows.first().seed.t)
                        picked = merged.copy(views = buildTargetViews(merged, merged.target!!, cfg, robust = true))
                    }
                    Diag.note(this, "body-sam", "RECOVERY_END", "$recovered usable rows across ${windows.size} bounded windows")
                } catch (e: CancellationException) { throw e }
                catch (e: Throwable) { ErrorLog.record(this, "body-sam", e) }
            }
            val out = picked ?: res.doc
            if (picked != null) Scanner.writeAtomic(file, picked)
            // Debug Part 2: is the chosen target actually trackable? (joint confidence, presence, camera jumps)
            if (picked == null) Diag.note(this, "scan", "PICK_NO_TARGET", "nobody at the picked point (t=${pick.t}); the scan is kept, pick again", com.takipli.oynat.core.Sev.WARN)
            else runCatching { com.takipli.oynat.core.targetFindings(picked).forEach { Diag.event(this, "scan", it) } }
            picked?.let { pk -> Diag.note(this, "scan", "OCCLUSION_SUMMARY", occlusionStats(pk, cfg).summary()) }
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
            val sp = lastProgress
            post(ScanUi.Saving(sp?.samples ?: 0, sp?.t ?: 0.0)) // no-op look if cancel() already showed it; also covers the notification's Cancel button
            runCatching { notify(note(getString(R.string.scan_saving_partial), null)) }
            val saved = withContext(NonCancellable) {
                val partial = c?.let { partialResult(it) }
                if (partial != null) partial else if (c != null && completedPose != null) {
                    // The pose scan was already finished when the optional SAM
                    // pass was cancelled. Preserve its usable views for export.
                    runCatching {
                        val doc = requireNotNull(completedPose)
                        val ready = applyPicks(if (c.pick.free) doc.copy(pt = null) else doc,
                            c.pick, c.repicks.toList(), c.cfg, robust = true) ?: doc
                        val dst = cancelledFile(c.file)
                        Scanner.writeAtomic(dst, ready)
                        val target = ready.target
                        val desc = target?.let { "#${it.id} " + (it.preset ?: it.part?.let { j -> "joint $j" } ?: "person") }
                        ScanUi.Cancelled(ready.samples.size, ready.samples.last().t, dst.path, desc)
                    }.getOrNull()
                } else null
            }
            post(saved ?: ScanUi.Cancelled(0, 0.0, null, null))
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
    @Volatile private var lastProgress: ScanProgress? = null
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
        if (picked != null && fp != null && (SamEngine.hasModels(this) || OpenCvFlow.available)) { // SAM can work without OpenCV
            try {
                // Bounded: this runs NonCancellable after the user pressed Cancel, and the tracker decodes the whole scanned part again
                // (4K HEVC ~0.4 s per frame): unbounded it left the screen on "preparing..." for minutes. On timeout the anchor-only views are kept.
                val svc: Context = this; val base: TrackDoc = picked
                val pt = kotlinx.coroutines.withTimeoutOrNull(PARTIAL_TRACK_MAX_MS) { PointScanner.run(svc, c.uri, base, fp, allowSam = false) { d, tot, _, _ -> post(ScanUi.Saving(part.samples.size, last, d, tot)) } }
                if (pt == null) Diag.note(this, "scan", "PARTIAL_TRACK_TIMEOUT", "free-point pass over the partial scan exceeded ${PARTIAL_TRACK_MAX_MS / 1000} s: kept the anchor-only result", com.takipli.oynat.core.Sev.WARN)
                else {
                    val d2 = base.copy(pt = pt)
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
        watchdogHandler.removeCallbacks(watchdog)
        wake?.takeIf { it.isHeld }?.release()
        scope.coroutineContext[Job]?.cancel()
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL = "scan"
        private const val NOTE_ID = 11
        private const val WAKE_MAX_MS = 4 * 60 * 60 * 1000L
        private const val BODY_SAM_FPS = 3.0
        private const val BODY_SAM_WINDOW_MAX_MS = 75_000L
        private const val STALL_MS = 90_000L
        private const val WATCHDOG_POLL_MS = 15_000L
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
        /** Cancel was pressed and the scan has not finished stopping: late Running/Lost updates from it must not replace the Saving screen. */
        @Volatile private var cancelling = false
        private fun post(u: ScanUi) { if (cancelling && (u is ScanUi.Running || u is ScanUi.Lost)) return; _state.value = u }

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
            cancelling = false
            _state.value = ScanUi.Running(null)
            ctx.startForegroundService(
                Intent(ctx, ScanService::class.java).putExtra(X_URI, uri.toString()).putExtra(X_VIDEO_ID, videoId)
                    .putExtra(X_MODEL, model).putExtra(X_NPU, npu).putExtra(X_PREVIEW, preview).putExtra(X_FPS, fps).apply { if (rangeA != null) putExtra(X_A, rangeA); if (rangeB != null) putExtra(X_B, rangeB) }
                    .putExtra(X_PICK, Formats.json.encodeToString(pick)),
            )
        }

        fun cancel(ctx: Context) {
            // Show the saving screen at once (the scan needs a moment to stop and write its partial result): no frozen-looking screen
            when (val s = _state.value) {
                is ScanUi.Running -> { cancelling = true; _state.value = ScanUi.Saving(s.p?.samples ?: 0, s.p?.t ?: 0.0) }
                is ScanUi.Lost -> { cancelling = true; _state.value = ScanUi.Saving(s.p?.samples ?: 0, s.p?.t ?: 0.0) }
                else -> {}
            }
            ctx.startService(Intent(ctx, ScanService::class.java).setAction(ACTION_CANCEL))
        }

        fun reset() { _state.value = ScanUi.Idle }
    }
}
