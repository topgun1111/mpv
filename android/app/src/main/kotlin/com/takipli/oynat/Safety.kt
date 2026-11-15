package com.takipli.oynat

import android.app.Application
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import android.os.BatteryManager
import android.os.Build
import android.os.StatFs
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentValues
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import com.takipli.oynat.core.ErrKind
import com.takipli.oynat.core.classifyError
import com.takipli.oynat.core.logLine
import com.takipli.oynat.core.lowBattery
import com.takipli.oynat.core.trimLog
import kotlinx.coroutines.delay
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Part 15: process setup. Installs the crash logger and removes the half-written export a killed process leaves behind. */
class App : Application() {
    override fun onCreate() {
        super.onCreate()
        ErrorLog.installCrashHandler(this)
        Diag.install(this) // Debug Part 1: exit reasons, watchdog, thermal/memory events, previous logcat
        runCatching { File(cacheDir, "export").deleteRecursively() }
    }
}

/** Plain-text error log in `files/logs/error.log` (newest last, capped). Shared from the home screen. */
object ErrorLog {
    private const val MAX_CHARS = 100_000
    private const val SHARE_CHARS = 40_000
    private val lock = Any()
    private fun file(ctx: Context) = File(ctx.filesDir, "logs/error.log")

    fun record(ctx: Context, where: String, t: Throwable, codeName: String? = null) {
        runCatching {
            val kind = classifyError(codeName, t.message, t.javaClass.name)
            val frames = t.stackTrace.take(5).joinToString(" <- ") { "${it.className.substringAfterLast('.')}.${it.methodName}:${it.lineNumber}" }
            val stamp = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).format(Date())
            // Debug Part 1: the cause chain (ORT/Media3 hide the real reason one level down), the thread, and the phone's state right now.
            val causes = generateSequence(t.cause) { it.cause }.take(3).joinToString("") { " | caused by ${it.javaClass.simpleName}: ${it.message.orEmpty().take(160)}" }
            val line = logLine(stamp, where, kind, "${t.javaClass.simpleName}: ${t.message.orEmpty()} [${codeName ?: "-"}] @ $frames$causes") +
                " {thread ${Thread.currentThread().name} | ${Diag.vitals(ctx)}}"
            appendLine(ctx, line)
        }
    }

    /** Appends one finished line (also used by [Diag] for WARN/PREDICT/ERROR events). */
    fun appendLine(ctx: Context, line: String) {
        runCatching {
            synchronized(lock) {
                val f = file(ctx)
                f.parentFile?.mkdirs()
                f.writeText(trimLog((if (f.isFile) f.readText() else "") + line + "\n", MAX_CHARS))
            }
        }
    }

    fun read(ctx: Context): String = runCatching { synchronized(lock) { file(ctx).takeIf { it.isFile }?.readText().orEmpty() } }.getOrDefault("")

    fun clear(ctx: Context) { runCatching { synchronized(lock) { file(ctx).delete() } } }

    /** Compact report (about 9 KB, findings first, repeated lines collapsed): what to paste into the next session. */
    fun report(ctx: Context): String = Diag.report(ctx, full = false)

    /** Everything, up to 250 KB; goes to a file (Save full report). */
    fun reportFull(ctx: Context): String = Diag.report(ctx, full = true)

    fun installCrashHandler(app: Application) {
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { th, e ->
            record(app, "crash:${th.name}", e)
            Diag.crashContext(app, e)
            previous?.uncaughtException(th, e)
        }
    }
}

/** Breadcrumbs for native crashes: every line is appended and closed at once, so the last line survives a killed process. */
object Trace {
    private fun file(ctx: Context) = File(ctx.filesDir, "logs/trace.log")
    fun reset(ctx: Context) { runCatching { file(ctx).apply { parentFile?.mkdirs(); writeText("") } } }
    fun step(ctx: Context, msg: String) {
        runCatching { val f = file(ctx); f.parentFile?.mkdirs(); f.appendText("${System.currentTimeMillis() % 100_000_000L} $msg\n") }
    }
    fun read(ctx: Context): String = runCatching { file(ctx).takeIf { it.isFile }?.readText().orEmpty() }.getOrDefault("")
}

/** Preflight checks and user-facing messages. */
object Safety {
    /** An error as one friendly sentence plus the short technical reason in brackets (the log has the full line). */
    fun friendly(ctx: Context, t: Throwable, codeName: String? = null): String {
        val id = when (classifyError(codeName, t.message, t.javaClass.name)) {
            ErrKind.NO_SPACE -> R.string.err_no_space
            ErrKind.MODEL_MISSING -> R.string.err_model
            ErrKind.VIDEO_ACCESS -> R.string.err_video
            ErrKind.CODEC -> R.string.err_codec
            ErrKind.OTHER -> R.string.err_other
        }
        val raw = (codeName ?: t.message ?: t.javaClass.simpleName).take(160)
        return ctx.getString(id) + "\n[" + raw + "]"
    }

    /** False when the picked video can no longer be opened (file moved or deleted, or the SAF grant was lost). */
    fun videoReadable(ctx: Context, uri: Uri): Boolean =
        runCatching { ctx.contentResolver.openFileDescriptor(uri, "r")?.use { true } ?: false }.getOrDefault(false)

    /** Free bytes on the volume of [dir]; `Long.MAX_VALUE` when unknown (never blocks on a failed reading). */
    fun freeBytes(dir: File): Long = runCatching { StatFs(dir.path).availableBytes }.getOrDefault(Long.MAX_VALUE)

    fun batteryLow(ctx: Context): Boolean {
        val i = ctx.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return false
        val level = i.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = i.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        val status = i.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        val charging = status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL
        return lowBattery(if (level >= 0 && scale > 0) level * 100 / scale else -1, charging)
    }

    enum class LogOut { SHARE, COPY, SAVE }

    /**
     * Builds the report off the main thread (it reads logcat) and delivers it: SHARE = compact text through the share sheet,
     * COPY = compact text to the clipboard, SAVE = full report as a .txt in Downloads. [done] gets a short status for the screen.
     */
    fun deliverLog(ctx: Context, how: LogOut, done: (String) -> Unit) {
        val app = ctx.applicationContext
        val ui = Handler(Looper.getMainLooper())
        kotlin.concurrent.thread(name = "log-report", isDaemon = true) {
            val msg = runCatching {
                when (how) {
                    LogOut.SHARE -> {
                        val text = ErrorLog.report(app)
                        ui.post { app.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text), null).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                        ""
                    }
                    LogOut.COPY -> {
                        val text = ErrorLog.report(app)
                        ui.post { app.getSystemService(ClipboardManager::class.java)?.setPrimaryClip(ClipData.newPlainText("takipli report", text)) }
                        app.getString(R.string.log_copied, text.length / 1024 + 1)
                    }
                    LogOut.SAVE -> {
                        val name = "takipli-debug-${Diag.stampForFile()}.txt"
                        val cv = ContentValues().apply {
                            put(MediaStore.Downloads.DISPLAY_NAME, name)
                            put(MediaStore.Downloads.MIME_TYPE, "text/plain")
                            put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                        }
                        val uri = app.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv) ?: error("cannot create $name")
                        app.contentResolver.openOutputStream(uri)?.use { it.write(ErrorLog.reportFull(app).toByteArray()) }
                        Diag.persistReport(app)
                        app.getString(R.string.log_saved, "Downloads/$name")
                    }
                }
            }.getOrElse { "${it.javaClass.simpleName}: ${it.message}" }
            ui.post { done(msg) }
        }
    }
}

/** Shown only while the battery is low and the phone is not charging (checked every 30 s). */
@Composable
fun BatteryWarning() {
    val ctx = LocalContext.current
    var low by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { while (true) { low = Safety.batteryLow(ctx); delay(30_000) } }
    if (low) Text(stringResource(R.string.battery_low), color = MaterialTheme.colorScheme.error)
}

/** Home screen footer: licence summary and the error log / debug buttons (Debug Part 1). */
@Composable
fun AboutSection() {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var msg by remember { mutableStateOf("") }
    var checking by remember { mutableStateOf(false) }
    var job by remember { mutableStateOf<Job?>(null) }
    var checkText by remember { mutableStateOf("") }
    Text(stringResource(R.string.about_licences), style = MaterialTheme.typography.bodySmall)
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        // Share = compact text (findings first, about 9 KB) for pasting; Copy = same to the clipboard; Save = everything as a file in Downloads.
        OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = { msg = ""; Safety.deliverLog(ctx, Safety.LogOut.SHARE) { if (it.isNotEmpty()) msg = it } }) { Text(stringResource(R.string.log_share)) }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { Safety.deliverLog(ctx, Safety.LogOut.COPY) { msg = it } }) { Text(stringResource(R.string.log_copy)) }
            OutlinedButton(onClick = { Safety.deliverLog(ctx, Safety.LogOut.SAVE) { msg = it } }) { Text(stringResource(R.string.log_save)) }
        }
        OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = {
            if (checking) { job?.cancel(); return@OutlinedButton }
            checking = true; checkText = ""; msg = ""
            job = scope.launch {
                try {
                    checkText = Diag.selfCheck(ctx) { msg = ctx.getString(R.string.selfcheck_running, it) }
                    msg = ctx.getString(R.string.selfcheck_done)
                } catch (e: CancellationException) {
                    msg = ctx.getString(R.string.selfcheck_stopped)
                } catch (e: Throwable) {
                    ErrorLog.record(ctx, "selfcheck", e); msg = Safety.friendly(ctx, e)
                } finally { checking = false }
            }
        }) { Text(stringResource(if (checking) R.string.selfcheck_stop else R.string.selfcheck_run)) }
        OutlinedButton(onClick = { ErrorLog.clear(ctx); runCatching { File(ctx.filesDir, "logs").listFiles()?.forEach { it.delete() } }; msg = ctx.getString(R.string.log_cleared) }) { Text(stringResource(R.string.log_clear)) }
    }
    if (msg.isNotEmpty()) Text(msg)
    if (checkText.isNotEmpty()) Text(checkText, fontFamily = FontFamily.Monospace, fontSize = 11.sp)
}
