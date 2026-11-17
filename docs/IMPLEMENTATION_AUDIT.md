# IMPLEMENTATION AUDIT (Session 0, read-only)

Repo: `mpv.zip` → Takipli Oynat, version 1.2.0 (`VERSION`, `tracker/__init__.py`).
Date: 2026-11-17. No source file was changed. Findings come from reading the code and running the Python tests on CPU in a scratch copy (see `TEST_RESULTS.md`). Nothing was run on a GPU or on Windows.

Legend: **exists** = implemented and tested | **partial** = some of it exists | **missing** = not in repo

## 1. What the repo is

- **PC (Windows):** portable mpv + Lua UI (`mpv/portable_config/scripts/track.lua`, `mpcbar.lua`) + Python tracker (`tracker/`, 10.4k lines incl. recorder/scripts). Live and offline modes. ONNX Runtime, DirectML by default.
- **Android (Kotlin):** `android/core` (pure logic, unit tested), `android/app` (UI, two flavors `pose` and `sam`), `android/rec` (recorder).
- **Project rules (handover.md):** one part per session, update `handover.md`, GitHub Actions builds. `handover.md` is ~590 lines: read only its first ~30 lines to save tokens.
- **Language:** code comments, docstrings and `handover.md` are mostly Turkish.
- **models/ has no weights in the zip** (only `manifest.json`, `MODELLER.txt`). Weights are fetched or exported by CI. Nothing model-related could be run here.

## 2. Roadmap item vs. repo

| Roadmap item | Status | Where | What it does today |
|---|---|---|---|
| YOLO person detection | exists | `tracker/detector.py` | YOLOX-S / YOLOv8 person detector, ONNX |
| Pose estimation | exists | `tracker/pose.py`, `models/yolov8s-pose.onnx` (optional yolo11m-pose, rtmpose-wholebody) | COCO-17 keypoints, `KeypointTracker`, `PartTracker` |
| Legs/feet part presets | exists | `tracker/parts.py` | `legs`, `left_leg`, `right_leg`, `feet`, `left_foot`, `right_foot` = keypoint-group boxes, with fallback to a person sub-box |
| Seated/desk handling | **partial** | `parts.py` (`anchored_leg_box`, `infer_joint`, `sanitize_row`) | Uses torso length when the lower body is hidden; infers missing ankle/knee from a parent joint. No desk detection, no sitting/standing classifier |
| EdgeTAM / SAM on **PC** | **missing** | none | No SAM runtime in `tracker/`. Only `tracker/edgetam_bank.py` (44 lines, bank reference) and `scripts/export_sam2.py` (CI export, 345 lines) |
| EdgeTAM / SAM on Android | exists, **not compiled/run here** | `android/app/src/sam/.../SamEngine.kt` (549 lines), `core/MemoryBank.kt`, `core/TrackGate.kt` | Full engine with 5 graphs: `sam-encoder`, `sam-decoder`, `sam-decoder-trk`, `sam-memenc`, `sam-memattn` |
| Memory bank | exists on both | `tracker/edgetam_bank.py`, `core/MemoryBank.kt` | Bounded (7 memory / 16 pointer slots), slot 0 = prompted frame |
| Confidence gating / mask-jump rejection | exists on Android only | `core/TrackGate.kt` (73 lines), `TrackGateTest.kt` | `remember()` only clean, confident, normal-size frames; `accept()` rejects jumps by object-pointer cosine; keeps last clean size when partly covered. **No Python version** |
| Per-frame tracking records | exists (person) | `offline.py` → `track.json` schema v2 incl. keypoints | No mask/confidence-accepted fields for SAM |
| Tracking states (7 states) | **missing** | `core/LostWatch.kt`, `config.lost_hold_s` | Only present/lost + hold/zoom-out. No state enum |
| Re-ID | exists | `tracker/reid.py` (387 lines), OSNet x0.25 (optional in manifest), config `reid_*`, `kp_reid` | Gallery, cosine threshold + margin, live auto-enable if model file exists. Android: `core/Relink.kt` |
| ByteTrack | exists | `tracker/bytetrack.py`, `core/ByteTrack.kt` | Persistent IDs |
| Optical flow / camera motion | exists | `tracker/gmc.py`, `point.py` (`WorldPointTracker`), `core/Gmc.kt` | LK + RANSAC affine; used in ByteTrack prediction |
| Kalman / smoothing | exists | `tracker/smooth.py`, `core/Kalman.kt`, `OneEuro.kt` | EMA, dead zone, lookahead, zero-phase offline smoothing |
| Camera director | **mostly exists** | `geometry.py` (`compute_view`), `smooth.py`, `offline._views_from_boxes`, `core/Director.kt` | Smooth pan/zoom, dead zones, hold then zoom-out on loss, zoom-in before return, gap interpolation |
| Target size (70%) | **partial** | `config.target_fill` | Default is **0.30**, not 0.70. Configurable. `PART_FIT = 0.70` in `parts.py` is a minimum fit for parts |
| Anti zoom-pumping from foot movement | **missing** | n/a | Zoom follows box size; no anatomical-region or posture input |
| Multi-region / union framing | exists | `tracker/targets.py` (`TargetSet`) | Union box of several targets, min-zoom, hysteresis |
| Selection UI | exists | Lua right-click / right-drag rectangle, "Open with target" (A1), `PickScreen.kt` | No SAM mask outline preview on PC |
| Bidirectional / offline refinement | **partial** | `offline.py` | Zero-phase smoothing + gap fill. No forward/backward mask tracking comparison |
| GPU: CUDA | **partial** | `detector.select_providers` | Order is **DirectML → CUDA → CPU**. `requirements.txt` installs `onnxruntime-directml` on Windows, which does **not** provide CUDA (the CUDA package is `onnxruntime-gpu`; the two cannot be installed together) |
| GPU benchmarking | **partial** | `tracker/bench.py` (tracking quality), `pose-bench` command, Android `SamBenchSection.kt` | No PC benchmark for the 5 SAM graphs; no VRAM measurement |
| Export | exists | `tracker/export.py` | ffmpeg pipe, `libx264 -crf 18 -preset veryfast`, audio copy, VFR-safe |
| NVENC / NVDEC | **missing** | n/a | No `nvenc`/`nvdec`/`hwaccel` anywhere |
| Stabilization on export | **missing on PC** | `core/Stabilize.kt` (Android) | PC export applies views only |
| Export validation | **missing** | n/a | |

## 3. Things that differ from what the roadmap assumed

1. **There is no PC SAM engine to "port or complete".** It has to be written from `SamEngine.kt`, using `edgetam_bank.py` and the graph contract in `scripts/export_sam2.py` and `tests/test_edgetam_contract.py`. This is the largest unplanned item.
2. **`TrackGate` existed only in Kotlin** (ported in Session 5: `tracker/trackgate.py`). Python needed a port (73 lines of pure maths, easy), plus the tests.
3. **The 5 ONNX graphs are not in the repo.** `export_sam2.py` needs `torch` and the EdgeTAM/SAM2 package (CI only). They must be exported before any PC benchmark. Graphs use static shapes (1024×1024 input) and float32 I/O.
4. **CUDA is not just a switch.** `onnxruntime-directml` and `onnxruntime-gpu` conflict, and CUDA needs matching CUDA/cuDNN runtime DLLs. Decide between DirectML and CUDA first (see `DECISIONS.md`).
5. **Much of the camera work already exists.** Sessions 10 and 11 of the old plan merge into one.
6. **Both-legs-and-feet region already exists as a keypoint box** (`legs` preset + `TargetSet`). What is new is the SAM-mask-based region and the visible vs anatomical split.
7. **P23/V1 real-clip validation on Windows was never done** (handover: "AÇIK"). Existing tracker quality on real footage is unknown.
8. **Android code is uncompiled** (`android/REMAINING.md`). Treat `SamEngine.kt` as a reference, not as proven.

## 4. Test status (CPU, Linux scratch copy)

465 passed, 1 skipped (handover.md said 374 earlier; later work added tests). `tests/test_lua_menu.py` was excluded from the run. Kotlin tests, Lua harness tests, Windows, DirectML and CUDA were not run.

## 5. Recommended changes to the plan

See `docs/Lower body.md` for the revised 15-session plan. Summary:

- Old 3 and 4 (memory tracker) become **three** sessions: PC SAM engine first frame, PC SAM memory loop, TrackGate port.
- Old 10 and 11 (camera) merge into **one** session.
- Old 13 (stabilization) merges into export.
- Re-ID, state machine and bidirectional sessions get smaller because parts exist.
