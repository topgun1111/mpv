# handover-debug.md — predictive debugging for the Android app

Created 2026-11-15. Read together with `handover-android.md` (source of truth for the app). New session: do the next ⬜ part, update this file. **D4 read the first real report (build #45 runs on the phone, so CI compiled). Next: D5 = the failing real action (scan / export) with Copy report, not only the self-check.**

## Why
The user is on mobile data and cannot download an APK for every test. One run must therefore leave enough data to diagnose it, and to predict what is about to fail. Everything extends the existing error log (`Safety.kt` -> `ErrorLog`), so the existing **Share error log** button now carries it all. The user pastes reports into chat: **keep reports small** (compact report ≈ 9 KB, repeated lines collapsed, findings first).

## Status
| Part | What | Status |
|---|---|---|
| D1 | Core predictors + device snapshot + exit reasons + watchdog + scan watch + self-check + report channels + hooks in Scanner / PoseRunner / Qnn / SAM bench | ✅ written 2026-11-15 |
| D2 | Remaining hooks (decoder, export, player, pick, updater), post-pick target findings, SAM bench warm-up, chip layout | ✅ written 2026-11-15 (app side never compiled) |
| D3 | Type-check D1+D2 without Gradle (`android/tools/typecheck/run.sh`), resource audit | ✅ 2026-11-15 (no errors found; no code changed) |
| D4 | First real report (self-check, build #45, sam flavor) read and recorded | ✅ 2026-11-15 (no code change) |
| D5 | Report after a real scan and a real export (THROTTLE / MEM / SCAN_TICK / EXPORT_* lines); act on what it shows | 🟨 first reports read (bench + scan screenshot), report/bench fixed; scan and export telemetry still missing |

Verification D1: `core/Diagnostics.kt` + `DiagnosticsTest.kt` (10 tests) compiled with Kotlin 2.0.21 and run outside Gradle (kotlin.test shim): all green. App files (`Diag.kt`, `Safety.kt`, `Scanner.kt`, `PoseRunner.kt`, `QnnSessions.kt`, `SamBenchSection.kt`) were NOT compiled (no Android SDK here); only checked for syntax-class errors. **First thing in D2: push, read the CI compile errors, fix.**

## What D1 adds
**Core (`core/.../Diagnostics.kt`, pure, tested):** `Sev`/`Finding` (stable `code`), `benchFindings` (mean above p95, spikes, jitter), `firstRunFinding`, `modelContractFindings`/`shapeMismatch`/`looksLikePoseInput`, `Throughput` (baseline, EWMA, slowdown, ETA, THROTTLE), `slopePerS`/`secondsToLimit`/`memoryFinding` (MEM_HIGH, MEM_LEAK), `batteryFinding`, `storageFinding`, `timelineStats`/`timelineFindings`, `lowConfFinding`, `jumpFinding`, `cosine`/`parityFinding`, `eventLine`, `dedupeLog`, `buildReport`, `topFindings`.

**App (`app/.../Diag.kt`, new):**
- `Diag.event/note` -> INFO to `files/logs/diag.log` (60 KB cap); WARN/PREDICT/ERROR also to `error.log` (same `time | where | LEVEL | msg` shape).
- `Diag.vitals(ctx)`: heap, native heap, free RAM, thermal, battery %/temp, free disk, threads. `ErrorLog.record` now appends it plus the thread and the cause chain to every error line.
- `Diag.snapshot`: device/SoC/API, RAM and app limits, power-save, thermal headroom, storage per folder, QNN/ORT/OpenCV libs in `nativeLibraryDir`, ORT providers, models (+side-loaded), QNN ctx cache, pending scan files.
- `Diag.exits` / `recordNewExits`: `ApplicationExitInfo` (API 30+). **Native crashes in ORT/QNN, OOM kills and ANRs never reach the Java crash handler: this is where they show** (PREV_EXIT, with the last Trace steps).
- Boot capture of the previous run's logcat (`logs/prev-logcat.txt`), live logcat (W/E) in reports.
- `startWatchdog`: MAIN_STALL with the main-thread stack when the UI thread blocks > 1 s (ANR at 5 s).
- Lifecycle breadcrumbs into `Trace`, `TRIM_MEMORY`/`LOW_MEMORY`, `THERMAL` events, `Diag.crashContext` (OOM flag, main stack, vitals).
- `Diag.contract` (used by `PoseRunner`): reads declared shapes first; a non-pose graph now throws "not a pose model" instead of ORT_INVALID_ARGUMENT.
- `Diag.bench` (used by `PoseRunner.bench`), `Qnn.npuSession` logs NPU_SESSION / NPU_SESSION_FAIL (cache hit/miss, ms, ctx size), `PoseRunner` logs MODEL_LOADED / NPU_FALLBACK.
- `ScanWatch` (used by `Scanner.scan`): per-frame split decode/other vs pose vs analysis vs preview, THROTTLE/MEM/BATTERY predictions (each at most every 2 min), SCAN_TICK every 30 s, SCAN_START/END/ABORT, timeline check, storage preflight.
- `Diag.selfCheck`: every model on CPU and NPU, fixed pseudo-random input, 1 first + 5 steady runs, contract, NaN check, NPU-vs-CPU cosine. Saved to `logs/selfcheck.txt`, included in reports.
- `SamBenchReport.findings()`: same checks on the EdgeTAM bench, printed as `! WARN ...` lines under the bench text.

**Channels (all four exist so data always gets out):** Share error log (compact text) · Copy report (clipboard) · Save full report (`Downloads/takipli-debug-<time>.txt`, up to 250 KB) · automatic `Android/data/<id>/files/logs/last-report.txt` (written when the app goes to background and at a crash). Strings en+tr added (9 each).

## How the user tests (one install, ~3 minutes)
1. Home -> **Run self-check** (all models, CPU+NPU) -> wait for "finished".
2. Do the usual action that failed (scan / export).
3. Home -> **Copy report** -> paste in chat. If it is too small for a crash: **Save full report**.

## Finding codes (grep these)
BENCH_OUTLIER, BENCH_SPIKE, BENCH_JITTER, BENCH_FEW, FIRST_RUN_SLOW, MODEL_IO, MODEL_NOT_POSE, DYN_SHAPE, POSE_STRIDE, POSE_OUT, THROTTLE, MEM_HIGH, MEM_LEAK, BATTERY_DIES, NO_SPACE, LOW_SPACE, TIME_BACKWARDS, TIME_DUP, TIME_GAPS, LOW_CONF, NAN, JUMPY, NPU_PARITY, NPU_NAN, NPU_LOAD_FAIL, CPU_LOAD_FAIL, NPU_RUN_FAIL, CPU_RUN_FAIL, CONTRACT, NAN_OUT, QNN_LIBS_MISSING, SOC_NOT_V75, NPU_SESSION(_FAIL), NPU_FALLBACK, PREV_EXIT, MAIN_STALL, TRIM_MEMORY, LOW_MEMORY, THERMAL, HOT_BENCH, CRASH_CTX, SCAN_START/TICK/END/ABORT.

## Seen in the user's screenshots (2026-11-15) — now explained, not all fixed
1. `ORT_INVALID_ARGUMENT ... image_embed index 1 Got: 3 Expected: 256`: a SAM graph (`sam-decoder`) was selected in the **pose** bench (model chips list every model). D1 gives MODEL_NOT_POSE. **D2: hide `sam-*` from the pose bench chips.**
2. EdgeTAM bench `encoder NPU 1196.7 ms (p95 598.3)`: mean above p95 = a few huge runs (first-run compile) inside the 20 runs. D1 flags BENCH_OUTLIER. **D2: warm up / drop the first run in `SamEngine.bench` (sam source set, not touched in D1).** Also CPU encoder varied 495-1201 ms between runs at 12-15 % battery: check `power-save` and `thermal` in the snapshot before trusting any bench.
3. Scan speed `0.04 x realtime (preview on)` for a 611-sample "legs" scan vs 0.22-0.23 x for pose-only NPU scans: probably the per-frame SAM prompt tracker (memory graphs missing). SCAN_TICK now splits the time per frame; read it from the next report.
4. Pose-bench selfie: face points fine, body points (shoulders/arm) drawn at wrong places with low confidence. **D2: draw keypoints only above a confidence threshold; LOW_CONF data from real scans.**
5. UI layout (not debugging): the `NPU` chip on the pick/scan screen wraps letter by letter, "Resume from middle" wraps. **D2 or UI task.**

## D2 plan
1. Push, fix CI compile errors of D1 (never compiled), run `:core:test`.
2. Hooks: `VideoDecoder` (decode ms/frame, frames dropped, MediaCodec errors, timestamp order), `Exporter` (storage predict via `exportBytesNeeded`, progress-stall detector, speed x-realtime), `ResultScreen` player errors, `PickScreen` first-frame detect time, `UpdateScreen`.
3. After `applyPick` in `ScanService`: `lowConfFinding` on the target's keypoint confidences, `jumpFinding` on its centre track, `NPU_PARITY` on a real frame.
4. Items 1, 2, 4, 5 above.
5. Read the first real report from the phone, update the codes table.

## D2 — done (2026-11-15)
Verification: `core/Diagnostics.kt` + `DiagnosticsTest.kt` (13 tests, 3 new) compiled with Kotlin 2.0.21 (the compiler jar inside Gradle) and run with JUnit outside Gradle: green. App files below were NOT compiled (no Android SDK; Google Maven unreachable).
- Core (new, pure): `targetFindings(doc)` (LOW_CONF on the target's joints, TARGET_ABSENT when the ID is in < 50 % of samples, JUMPY on the follow-camera pan, cuts skipped), `decodeFindings` (DECODE_NONE / DECODE_SLOW > 300 ms median / DECODE_MISS), `progressStallFinding` (EXPORT_STALL after 45 s frozen), `speedFinding` (SLOW_RUN / SPEED).
- `VideoDecoder.sample`: times the first 200 frames, counts retriever misses, logs DECODE_ERROR (not on cancel) and the decode findings (skipped for the 1-frame pick-screen calls).
- `ResultScreen`/export: storage preflight (need x2), EXPORT_START line, EXPORT_TICK every 15 s (progress + vitals), stall detector, SLOW_RUN/SPEED at the end, EXPORT_FAIL (with error code), EXPORT_CANCEL, PLAYER_ERROR (position + vitals).
- `ScanService`: after `applyPick`: PICK_NO_TARGET, `targetFindings`, SCAN_SPEED, SLOW_RUN below 0.1 x.
- `PickScreen`: FIRST_FRAME_DETECT (people, ms, size, model), NO_PEOPLE (blank frame), OPEN_VIDEO_FAIL. `UpdateScreen`: UPDATE_CHECK, UPDATE_DOWNLOAD.
- SAM bench: 3 *timed* warm-up runs kept out of the stats; their first-run cost is reported as FIRST_RUN_SLOW. If BENCH_OUTLIER still shows after this, it is not compile cost but NPU stalls or thermal/power-save: read `thermal` and `power-save` first.
- Layout: the `NPU` chip, fps row (ScanScreen) and the Decode buttons now scroll horizontally and never wrap.
- Already done in D1 (found while reading): pose bench hides `sam-*` and draws keypoints only above `KP_MIN_CONF` 0.35 (`BenchScreen`).
- Not done: `NPU_PARITY` on a real pick frame (needs a second CPU session next to the NPU one on the pick screen: costs ~1 s and memory; the self-check already compares both on pseudo-random input). Do it in D3 only if the first real report shows suspicious NPU keypoints.
New codes: TARGET_ABSENT, JUMPY (scan), DECODE_NONE/SLOW/MISS/ERROR, EXPORT_START/TICK/STALL/FAIL/CANCEL, SLOW_RUN, SPEED, SCAN_SPEED, PICK_NO_TARGET, FIRST_FRAME_DETECT, NO_PEOPLE, OPEN_VIDEO_FAIL, PLAYER_ERROR, UPDATE_CHECK/DOWNLOAD.

## D3 — done (2026-11-15): compile check without Gradle
No CI log and no phone report were available, so D3 type-checked the code here. **No compile error was found and no source file was changed.**
- Tooling (new, reusable): `android/tools/typecheck/run.sh` downloads kotlinc 2.1.21 (conda-forge) and `android.jar` API 35 (Sable/android-platforms on GitHub; Maven Central/Google Maven stay unreachable), stubs `kotlinx.serialization`, `kotlinx.coroutines`, ONNX Runtime and `FileProvider`, generates `R`/`BuildConfig` stubs, and compiles both flavors. `pip install zstandard` once. Result today: `core OK`, and the only errors are in `PointScanner.kt` (needs the excluded OpenCV classes). Anything else in that list is a real error.
- Compiled clean (full type check against real `android.jar`): all of `core/` (incl. `Diagnostics.kt`), `Diag.kt` (+`ScanWatch`), `Safety.kt` (`ErrorLog`, `Trace`, `Safety`; its `@Composable` tail excluded), `Scanner.kt`, `ScanService.kt`, `PoseRunner.kt`, `QnnSessions.kt`, `VideoDecoder.kt`, `Updater.kt`, `SamEngine.kt` (pose and sam), `SamBenchReport`.
- NOT type-checked (need Compose/Media3/OpenCV jars): `Safety.kt` tail (`AboutSection`, `BatteryWarning`), `PickScreen`, `ResultScreen`, `ScanScreen`, `DecodeScreen`, `BenchScreen`, `UpdateScreen`, `SamBenchSection` UI, `Exporter`, `DenseCamera`, `FrameAnalyzer`, `RegionTracker`, `PointTracker`. They were read by hand: all D1/D2 hunks parse cleanly (no syntax-class error from the compiler), every imported/called symbol exists with a matching signature (`progressStallFinding`, `speedFinding`, `exportBytesNeeded`, `Exporter.progress`, `Updater.repo/token`, `Pose.conf`, `ErrorLog.record(..., codeName)`), `rememberScrollState`/`horizontalScroll`/`CancellationException` imports present.
- Resources: every `R.string.*` used in code exists in `values/` and `values-tr/` (150 each, same names, no duplicates across `strings*.xml`, valid XML, `%%` escapes fine).
- Stub caveat: the ONNX Runtime stub follows the Java API from memory (`getInputInfo()`, `OnnxTensor.createTensor` overloads, `Result.get(int)`, `getAvailableProviders()` as `EnumSet`); if Gradle disagrees on one of these, fix it in `Diag.kt` (the only D1 file that touches the ORT API beyond `PoseRunner`/`QnnSessions`, which compiled before D1).
- Still open for D4: first Gradle/CI run (Compose/Media3 files), `:core:test` (JUnit not available here; `DiagnosticsTest` ran only through the shim in D1/D2), first real report from the phone, update the code table.

## D4 — first real report (2026-11-15, vivo V2436A, SM8650, Android 17 / API 37, 1.2.0-sam #45)
CI compiled everything (the APK runs; no Gradle error was reported). Self-check finished in 190 s, **no WARN/ERROR finding at all**, all 4 models load on CPU and NPU, `NPU matches CPU` (cosine 1.0000) for every model, no NaN.
| model | CPU median | NPU median | NPU first compile (ctx-cache miss) |
|---|---|---|---|
| yolov8s-pose | 222.3 ms | **7.3 ms** (30x) | 111 s |
| sam-encoder | 481.7 ms | 387.3 ms (1.2x) | 56 s |
| sam-decoder | 43.5 ms | 37.9 ms | 6 s |
| sam-decoder-trk | 38.0 ms | 32.5 ms | 6 s |
Reading it:
1. Pose is fully on the HTP; the EdgeTAM graphs gain little on the NPU (1.2x encoder, ~1.15x decoders): likely ops falling back to CPU or fp32 on HTP. Not a bug (parity is exact), but it explains the slow `legs` scans (SAM per frame ~0.4 s encoder). Check the QNN op-fallback log (ORT verbose) only if SAM speed matters.
2. **The first NPU load after install costs ~3 min in total** (yolov8s-pose 111 s, encoder 56 s); the contexts are now cached (`qnn_ctx` 63 MB), later loads should be seconds. If the app's first scan ever looks hung, this is why: worth a UI hint later (NPU_SESSION says `ctx-cache miss`).
3. Phone state during the run: **power-save ON**, battery 20-21 %, thermal 0, headroom 0.6, RAM free 3.5-4.6 GB, heap 23/256 MB. Benchmarks taken like this are pessimistic; turn power-save off for real timings.
4. APK carries every Hexagon arch (V68, V69, V73, V79 stubs/skels, Dsp, Gpu ~ 60 MB) though only V75 is used on this SoC (`SOC_NOT_V75` did not fire). Optional later: `packaging { jniLibs { excludes += ... } }` for the unused ones (keep `libQnnHtp`, `HtpPrepare`, `HtpV75Stub/Skel`, `System`; verify on the phone after).
5. Logcat at the end of the self-check: FastRPC teardown errors (`remote_munmap64 failed`, `notif_fastrpc_thread exited`) and qdgralloc `ReleaseBuffer ref_count`: they appear when the NPU sessions are closed after the check, no run failed and nothing crashed. Treat as vendor teardown noise unless a later report shows them before a failure.
6. Trace shows the user left the app during the 56 s encoder compile; the self-check continued in the background and finished. Fine.
Not covered yet (D5): real scan (SCAN_START/TICK/END, THROTTLE, MEM_*), export (EXPORT_START/TICK/END), pick screen (FIRST_FRAME_DETECT), previous-exit list (empty here: no crash since install).

## D5 (part 1) — reports 12:11 (build #45, 10-12 % battery, power-save ON) + screenshots
Read: EdgeTAM bench x2, self-check x2, one 4K/20 s scan Done screen (`#6 legs`, 611 samples, **0.04 x realtime**, preview on).
1. **Bench speed-up was misleading (fixed)**: the `x` column used the mean. One NPU stall (max 18 922 ms in 20 runs, after the 3 warm-ups, so not compile) gave `encoder NPU 1360 ms x0.4`; the median is 401.9 ms vs CPU 425.8 ms = x1.06. `SamBenchReport.text` now prints `median (mean, p95)` and `x` from medians. Stalls come from power-save/low battery; rerun with power-save off and charging before trusting NPU numbers.
2. NPU parity fine (IoU 0.997, cosine 0.9996, self-check 1.0000). Decoder graphs 1.0-1.4x only, encoder ~1.0-1.1x: the EdgeTAM graphs barely use the HTP (see D4 item 1). Self-check medians are stable: encoder CPU 403 / NPU 386, decoder 39.5 / 35.9, decoder-trk 37.6 / 38.2, pose 225 / 6.9.
3. **Memory graphs are still missing** (`sam-decoder-trk` present; `sam-memenc`, `sam-memattn` absent): scans use the prompt-per-frame tracker (encoder every frame, ~0.4 s). Re-run the CI export (`scripts/export_sam2.py`) and ship the two graphs.
4. **0.04 x realtime = ~0.83 s per sample** (611 samples in ~509 s). Pose is 7 ms and the decoders ~40 ms, so the cost is the frame source: `VideoDecoder.sample` uses `MediaMetadataRetriever.getFrameAtTime(OPTION_CLOSEST)` on a 3840x2160 clip = a seek + GOP decode + a 33 MB ARGB bitmap per sample. Not confirmed: the scan's SCAN_TICK / DECODE_SLOW lines were not in the report (see 5). Candidate fixes after the numbers confirm it: `getScaledFrameAtTime` (check rotation on the phone), a lower scan fps for 4K (15 fps halves it), sequential MediaCodec decode (the ImageReader path crashed natively on this phone).
5. **Report gap (fixed)**: compact report cut the telemetry to the last ~2 KB (self-check lines), so SCAN_START/TICK/END and DECODE_* never showed. New section `last scan / decode / export` (after top findings) keeps the last 10 SCAN_/EXPORT_/DECODE_/SLOW_RUN/SPEED/FIRST_FRAME/PICK_/TARGET_/JUMPY/LOW_CONF/PLAYER_ lines.
6. Other lines: `NO_PEOPLE` = t=0 frame of the clip has nobody (seek first); `SCAN_ABORT` after 32 samples = job cancelled (cancel button or the vivo cleaner: `FORCE STOP ... single-cleaner` at 12:06:10; the scan is a foreground service, so check "Unrestricted" battery for the app if it dies in the background); `BATTERY_LOW` at 10 % is correct.
Next (D5 part 2): scan a clip, press **Copy report** right after "Done", paste it; the new section carries SCAN_TICK (split per frame) and the DECODE_* verdict. Then export one clip and repeat.

## D5 (part 2) — why the memory graphs were missing (reproduced locally, fixed)
`export_sam2.py edgetam` failed in the memory part, so CI fell back to `--no-memory`. Two causes, both reproduced with the real `edgetam.pt` (CPU torch, pip + GitHub only) and fixed in the script:
1. `sam-memenc`: EdgeTAM's `_encode_new_memory` never uses `object_score_logits`, so the ONNX export dropped that input and the check/app `run()` failed (`Invalid input name: object_score`). `MemEnc.forward` now adds `0.0 * object_score.sum()` (exactly +0) to keep it connected.
2. `sam-memattn`: the cross-attention is `RoPEAttentionv2` (`apply_rotary_enc_v2`, `freqs_cis_q/_k`), which the real-valued RoPE patch did not cover, so the trace hit complex constants (`ScalarType ComplexFloat`). Added `rope_v2` (real maths, tiled frequencies like the original) and convert `freqs_cis_q/_k` too (4 functions patched now).
Result: all 5 graphs export and match PyTorch (max |onnx - torch| <= 2.3e-5; encoder 8.8e-6, memattn 3.5e-6). Not tested here: the app's use of the memory bank on the phone. Next CI build should show no "memory export failed" warning and no "memory part is missing" on the pick screen; then compare scan speed (memory tracker vs prompt tracker) with `lastRun`.
