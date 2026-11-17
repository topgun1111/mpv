# Lower Body: Session Plan (updated after the Session 0 audit)

Companion to `docs/PROJECT_SPEC.md` (the roadmap) and `docs/IMPLEMENTATION_AUDIT.md` (what exists).
Project: Takipli Oynat, PC build (Windows, mpv + Python). Hardware: RTX 3050 Laptop 6 GB, Ryzen 5 5600, 16 GB RAM. Offline-first.
Free Claude account, weekdays: **15 sessions (0–14)**, one per weekday, about three weeks.

**Status: Sessions 0-9 done in code (2026-11-17/18); Sessions 1-9 still need your PC runs (see `TEST_RESULTS.md`, `DECISIONS.md` "SAM graphs", "SAM engine", "SAM memory loop", "TrackGate", "Lower-body region", "Posture" and "Tracking state machine"). Next: Session 10.**

---

## What the audit changed

| Old plan | Now | Why |
|---|---|---|
| 3 "Memory tracker core" and 4 "Bank hardening" | **3, 4, 5** (three sessions) | No PC SAM engine exists. It must be written from Android `SamEngine.kt`. `TrackGate` exists only in Kotlin |
| 2 "Benchmark graphs" | Export graphs **and** benchmark | The 5 ONNX graphs are not in the repo |
| 1 "CUDA check" | DirectML vs CUDA decision | `onnxruntime-directml` and `onnxruntime-gpu` conflict |
| 5 "Selection UI" | Smaller (6) | Right-drag rectangle and Open-with-target already exist. Only the mask outline is new |
| 6 "Combined region" | Smaller (7) | `legs`/`feet` presets and `TargetSet` union exist. New: visible vs anatomical split |
| 8 "State machine" | Same (9), smaller | Lost/hold logic exists, no 7-state enum |
| 9 "Re-ID" | Smaller (10) | `reid.py` is complete; wire it for lower-body re-entry |
| 10 + 11 "Camera" | **One session (11)** | Smoothing, dead zone, hold and zoom-out exist. New: 70% default, anti-pumping |
| 12 "Bidirectional" | Smaller (12) | Zero-phase smoothing and gap fill exist; add a backward SAM pass |
| 13 + 14 "Stabilize + export" | **One session (13)** + validation (14) | `gmc.py` exists; no NVENC, no validation |

---

## How to use this file

For every session:

1. Open a **new** Claude chat. Attach only the files that session needs (listed in each prompt).
2. Paste the **Master instruction**, then that session's **prompt**.
3. Let Claude finish and print the **SESSION CHECKPOINT**.
4. Paste the checkpoint into `docs/PROGRESS.md`, tick the session, commit.
5. Run the "Run on your PC" commands yourself. Claude's chat cannot use your GPU or Windows.
6. If the usage limit hits: stop at the last green test, note it in `PROGRESS.md`, resume the same session next day.

Token savers:

- One session = one task. Do not start the next one in the same chat.
- For `handover.md` read only the first ~30 lines. Add one short entry at the end, in the repo's style.
- Do not touch `android/` unless the session says so (it is a reference for the port).
- Python tests: `python -m pytest -q -p no:cacheprovider` (they pass on CPU without a GPU).

---

## Session overview

| # | Session | Spec part | Status | Done when |
|---|---|---|---|---|
| 0 | Repo audit (read-only) | Prep | **Done** | Audit docs exist |
| 1 | GPU provider: DirectML vs CUDA | 3 | **Code done**, your PC runs pending | Chosen provider runs, CPU fallback intact |
| 2 | Export 5 EdgeTAM graphs, PC loader, benchmark | 3 | **Code done**, your PC runs pending | Real numbers in `TEST_RESULTS.md` |
| 3 | PC SAM engine: rectangle → first mask | 4 | **Code done**, your PC run pending | Mask + box for frame 1 |
| 4 | PC SAM memory loop (forward tracking) | 4 | **Code done**, your PC run pending | Masks across a clip, per-frame records |
| 5 | Port `TrackGate`: gating + jump rejection | 4 | **Code done**, your PC run pending | Bad frames never enter memory |
| 6 | Mask outline + combined rectangle preview | 5 | **Code done**, your PC run pending | Overlay shows mask, rectangle, state |
| 7 | Lower-body region: visible vs anatomical | 6 | **Code done**, your PC run pending | One framing rectangle, left/right evidence |
| 8 | Posture, desk occlusion, sit↔stand | 6 | **Code done**, your PC run pending | Desk never becomes target |
| 9 | Tracking state machine (7 states) | 7 | **Code done**, your PC run pending | Transitions tested |
| 10 | Re-entry: existing Re-ID + future frames | 7 | | Ambiguous re-entry flagged |
| 11 | Camera: 70% occupancy, no foot zoom pumping | 8 | | Stable apparent size |
| 12 | Bidirectional refinement (backward SAM pass) | 9 | | Uncertain intervals repaired |
| 13 | Export: NVENC + fallback, validation, optional stabilization | 10 | | Valid file, audio and timing kept |
| 14 | Real-clip validation + Definition of done | 12 | | Checklist recorded |

Milestones: **M1** sessions 0–2 (GPU, graphs) · **M2** 3–10 (reliable tracker) · **M3** 11 (camera) · **M4** 12–14 (refine, export, validate).
Spare day recommended after session 4 (the new SAM engine is the largest new code) and after session 11.

---

## Master instruction (paste at the start of every session)

```text
You are continuing an existing PC video-tracking project
(Takipli Oynat: Windows, mpv + Python in tracker/).

Read:
docs/Lower body.md (only the session named below)
docs/PROGRESS.md
docs/IMPLEMENTATION_AUDIT.md (only the rows you need)
handover.md (first 30 lines only)

We have limited Claude free-account usage.

Work only on the session task given below.
Do not implement future sessions.
Inspect existing code before editing.
Reuse existing modules; avoid rewriting working code.
Do not touch android/ (read-only reference).

Target hardware:
RTX 3050 Laptop, 6 GB VRAM
Ryzen 5 5600
16 GB RAM

The workflow is offline-first.

The primary target is one combined region
containing both legs and both feet.
Track individual limbs internally as supporting evidence.

The main scene is a frontal seated person behind a desk.
Handle desk occlusion without treating the desk as part of the target.

Keep the repo's style (Turkish comments/docstrings are fine,
match the surrounding code) and keep tests passing:
python -m pytest -q -p no:cacheprovider

Implement the smallest safe change, add focused tests,
update docs/PROGRESS.md and add one short entry to handover.md.

Deliver ONLY the changed/new files in a zip,
preserving the original folder structure.

You cannot run my GPU or Windows. For anything that needs them,
give me exact commands to run and where to paste the output.
Never claim an unrun test passed.

At the end, output the SESSION CHECKPOINT.
```

## Session checkpoint (Claude outputs this at the end)

```text
SESSION CHECKPOINT

Phase:
Task:
Files inspected:
Files changed:

What changed:

Tests/commands run:

Test results:

Known failures:

Unverified assumptions:

Next smallest task:

Exact command to resume:
```

---

## Session prompts

### Session 0: Repo audit. DONE

Result: `docs/IMPLEMENTATION_AUDIT.md`, `PROGRESS.md`, `DECISIONS.md`, `KNOWN_ISSUES.md`, `TEST_RESULTS.md`. 465 tests pass on CPU.

---

### Session 1: GPU provider, DirectML vs CUDA (Part 3). CODE DONE

Delivered: `python -m tracker providers [--device] [--model] [--json]`, `provider_order` config + `TAKIPLI_PROVIDER_ORDER`, `preload_cuda`, CUDA venv recipe in `DECISIONS.md`, 14 tests. Your part: run the diagnostic in the DirectML environment and a CUDA venv and paste into `TEST_RESULTS.md`. The original prompt is kept below for reference.

Files: `tracker/detector.py` (`select_providers`, `Detector`), `requirements.txt`, `tracker/main.py` (`pose-bench`), `tests/test_detector.py`, `scripts/fetch_deps.ps1`.

```text
Implement only GPU provider readiness. No SAM yet.

Facts from the audit:
- select_providers order is DirectML -> CUDA -> CPU.
- requirements.txt installs onnxruntime-directml on Windows,
  which has NO CUDA provider. onnxruntime-gpu would be needed,
  and the two packages cannot be installed together.

Tasks:
1. Add a small `providers` diagnostic command (or extend an existing
   one) that prints: ORT version, available providers, the provider
   actually selected, and any load error.
2. Make the provider order configurable (config key, default unchanged:
   DirectML) so CUDA can be tried without code edits.
3. Document in docs/DECISIONS.md exactly how to set up a CUDA
   environment (separate venv with onnxruntime-gpu, required CUDA and
   cuDNN versions for the installed ORT version) without breaking the
   DirectML default.
4. Keep CPU fallback. Add tests with fake provider lists.

Do not add SAM code. Do not change defaults.

Run on your PC (paste output into docs/TEST_RESULTS.md):
the new diagnostic in the DirectML environment, then in a CUDA venv.
```

---

### Session 2: Export the 5 graphs, PC loader, benchmark (Part 3). CODE DONE

Delivered: `python -m tracker sam-bench MODEL_DIR [--device] [--runs] [--warmup] [--fp16] [--out]` (`tracker/sam_bench.py`), manual workflow `.github/workflows/sam-export.yml`, export + benchmark commands in `DECISIONS.md`, 20 tests. Your part: export the graphs (Actions or torch machine), run `sam-bench` on EdgeTAM and SAM 2.1 Small, paste the table into `TEST_RESULTS.md`. The original prompt is kept below for reference.

Files: `scripts/export_sam2.py`, `tracker/bench.py`, `tests/test_edgetam_contract.py`, `.github/workflows/build.yml` (read only unless a CI export step is missing), reference `android/.../sam/SamEngine.kt` (graph I/O only).

```text
Implement only graph export plumbing and a PC benchmark.

Graphs (static shapes, float32 I/O): sam-encoder, sam-decoder,
sam-decoder-trk, sam-memenc, sam-memattn. They are NOT in the repo.

Tasks:
1. Give me the exact commands to export them with
   scripts/export_sam2.py (EdgeTAM first, then small), either in
   GitHub Actions or on a machine with torch. Do not run torch here.
2. Add tracker/sam_bench.py + a CLI command `sam-bench MODEL_DIR`:
   for each graph measure load time, warm-up, average latency
   (N runs), peak VRAM when CUDA is used (or note "n/a" on DirectML),
   errors, and the provider actually used. Test fp16 where the
   provider supports it. Follow the pose-bench style.
3. Output a JSON report and a Markdown table row set.
4. Tests with fake sessions (no model files).

Do not default to SAM 2.1 Large (6 GB VRAM).
Do not implement tracking yet.

Run on your PC: `sam-bench` on EdgeTAM, then SAM 2.1 Small.
Paste the table into docs/TEST_RESULTS.md. Estimates are not results.
```

---

### Session 3: PC SAM engine, rectangle to first mask (Part 4). CODE DONE

Delivered: `tracker/sam_engine.py` (`SamEngine.encode/segment_rect/first_mask`), `python -m tracker sam-first MODEL_DIR IMAGE --rect x1,y1,x2,y2 [--norm] [--device] [--rule best|smallest] [--out]`, 28 tests, decisions in `DECISIONS.md` ("SAM engine"; squash resize instead of letterbox, best-iou rule). Your part: run `sam-first` on one image with the exported EdgeTAM graphs and paste the output into `TEST_RESULTS.md`. The original prompt is kept below for reference.

Files: new `tracker/sam_engine.py`, `tracker/edgetam_bank.py` (reuse), `android/.../sam/SamEngine.kt` (reference), `scripts/export_sam2.py` docstring (I/O contract), `tests/test_edgetam_contract.py`.

```text
Write the PC EdgeTAM engine, first frame only.

Port the structure of Android SamEngine.kt (reference, uncompiled):
encoder -> decoder with a rectangle prompt (point labels 2/3 =
box corners; 1024x1024 input, ImageNet mean/std, RGB).

Tasks:
1. tracker/sam_engine.py: load graphs via the existing provider
   selection, preprocess, run encoder + decoder, pick the best of
   the 3 candidate masks by iou_predictions, return mask, box,
   score, object_score, obj_ptr.
2. Mask -> frame-space box (undo the 1024 resize/letterbox).
3. Keep the graph names consistent with the contract test.
4. Tests with fake sessions: shapes, box prompt encoding,
   coordinate round-trip.

Do not implement memory, video loops, UI or zoom.
Run on your PC: one image + rectangle -> save mask outline PNG.
```

---

### Session 4: PC SAM memory loop (Part 4). CODE DONE

Delivered: `tracker/sam_track.py` (`track_video` generator, `Clip`, records, `<video>.sam.json`), `SamEngine(memory=True)` with `memory_layout/memorize/condition/decode_track`, `python -m tracker sam-track MODEL_DIR VIDEO --rect x1,y1,x2,y2 [--start] [--fps] [--max-seconds] [--norm] [--device] [--rule] [--out] [--no-save]`, 39 tests, decisions in `DECISIONS.md` ("SAM memory loop"; every tracked frame is pushed until the Session 5 gate, `accepted` is always True). Your part: run `sam-track` on a 30 s clip with the exported graphs and paste the output (fps, VRAM, tracked/lost) into `TEST_RESULTS.md`. The original prompt is kept below for reference.

Files: `tracker/sam_engine.py`, `tracker/edgetam_bank.py`, `tracker/frames.py` or `offline.VideoSource` (sequential decode), `tracker/offline.py` (record format, read only), `core/SamEngine.kt` (reference).

```text
Add forward tracking to the PC SAM engine.

Use the existing MemoryBank (tracker/edgetam_bank.py): slot 0 =
prompted frame, slot d = d steps back; 7 memory + 16 pointer slots;
only tracked frames are pushed.

Tasks:
1. After frame 1: sam-memenc pushes into the bank; later frames use
   sam-memattn (memory-conditioned embed) then sam-decoder-trk.
2. A `track_video(video, rect, ...)` generator decoding sequentially,
   yielding one record per frame: t, mask box, score, object_score,
   accepted flag (always true until Session 5), tracked/lost.
3. Bounded memory (bank is fixed size; free per-frame tensors).
4. Save records next to track.json without changing the existing
   schema (new optional field / separate file).
5. Tests with fake graphs: slot order, bounded size, lost frames
   push nothing.

Do not add gating, UI, zoom or Re-ID.
Run on your PC: a 30 s clip; report fps and peak VRAM.
```

---

### Session 5: Port TrackGate (Part 4). CODE DONE

Delivered: `tracker/trackgate.py` (Kotlin constants and maths), gate wired into `track_video` (`use_gate`, `gate`), `accepted`/`clean`/`w`/`h` record fields (`.sam.json` version 2), `sam-track --no-gate`, 10 + 9 new tests, decisions in `DECISIONS.md` ("TrackGate"). Your part: run `sam-track` with and without `--no-gate` on the same 30 s clip and paste both outputs into `TEST_RESULTS.md`. The original prompt is kept below for reference.

Files: new `tracker/trackgate.py`, `tracker/sam_engine.py`, `android/.../core/TrackGate.kt` and `TrackGateTest.kt` (reference), `tests/`.

```text
Port core/TrackGate.kt to Python (73 lines of pure maths) and wire it
into the PC SAM loop.

Behavior to keep:
- remember(conf, ratio): only clean, confident, normal-size frames
  enter the memory bank (conf >= 0.6, size ratio 0.6-1.6).
- accept(dist, boxSize, lost, sim): reject mask jumps and reappearances
  that do not look like the subject (cosine of object pointers,
  threshold learned from clean frames; everything passes until 3
  clean frames were seen).
- size(): keep the last clean size when the subject is partly covered
  (so the desk or a leg cover does not make the camera zoom in).
- relax(lost): threshold relaxes after long loss so it never deadlocks.

Tasks:
1. tracker/trackgate.py with the same constants.
2. Port TrackGateTest.kt cases to pytest.
3. Wire into the loop: a rejected frame is not pushed to the bank and
   is recorded as rejected.
4. Add a test where a mask jumps onto a "desk" box and is rejected.

Do not change the Kotlin code or implement UI/zoom.
```

---

### Session 6: Mask outline and combined rectangle preview (Part 5). CODE DONE

Files: `mpv/portable_config/scripts/track.lua` (ASS overlay code only), `tracker/live.py` / `tracker/main.py` message path, `tests/test_lua_panel.py`.

```text
Add the selection and preview for the SAM tracker.

Already exists: right-drag rectangle, Open-with-target (A1), HUD, dot.
New:
1. After the rectangle is drawn, run the SAM first-mask step and show
   the mask outline + combined rectangle for confirmation.
2. During offline processing show: mask outline, combined rectangle,
   tracking confidence, tracking state (placeholder until Session 9).
3. Let the user redraw the rectangle before confirming.
4. Keep logic in testable Python; keep Lua changes small.

Do not redesign other screens. Do not change right-click behavior.
```

---

### Session 7: Lower-body region, visible vs anatomical (Part 6). CODE DONE

Delivered: `tracker/lowerbody.py` (`LowerBodyModel`, `Follower`, `pick_pose`), `sam-track --pose [--pose-model]` and `sam-preview --pose`, optional `lower` block in `<video>.sam.json`, `lower` object + framing rectangle in the preview file, two extra boxes in `track.lua` (magenta anatomical, orange visible), 27 tests, decisions in `DECISIONS.md` ("Lower-body region"). Your part: run `sam-track --preview --pose` on a seated-at-desk clip, press `P` in mpv, paste observations into `TEST_RESULTS.md`. The original prompt is kept below for reference.

Files: `tracker/parts.py` (`PRESETS`, `anchored_leg_box`, `group_box`), `tracker/pose.py`, `tracker/targets.py`, SAM records from Session 4, `tests/test_parts*.py`.

```text
Implement the combined lower-body region model on top of what exists.

Already exists: `legs`, `left_leg`, `right_leg`, `feet` presets;
torso-length fallback; TargetSet union.

Maintain two regions per frame:
1. Visible region: currently visible legs and feet (pose keypoints +
   SAM mask).
2. Anatomical region: estimated full lower body, including hidden
   thighs.

Track left and right legs separately as evidence. Output one
combined framing region. Individual foot movement must not make
the region chase one foot; crossing legs must not lose identity;
one hidden leg must not collapse the region.

Do not hard-code a universal desk height. A missing landmark must
not mean the limb has disappeared.

Add debug overlay fields and focused tests. No zoom changes.
```

---

### Session 8: Posture, desk occlusion, sit↔stand (Part 6). CODE DONE

Delivered: `tracker/posture.py` (`PostureModel` on top of `LowerBodyModel`, `PostureFrame`, `desk_like`), `sam-track --posture` (`posture` block in `.sam.json`, posture fields + posture-aware framing in the preview, posture word in the mpv label), 33 tests, decisions in `DECISIONS.md` ("Posture, desk occlusion, sit↔stand"). Your part: run `sam-track --preview --posture` on a seated-at-desk clip that includes sitting down/standing up, press `P` in mpv, paste observations into `TEST_RESULTS.md`. The original prompt is kept below for reference.

Files: `tracker/parts.py`, new `tracker/posture.py`, SAM mask + pose records, tests.

```text
Add posture and desk handling.

1. Posture classifier: SEATED / STANDING / TRANSITION from pose
   (hip-knee-ankle geometry, visible vs anatomical region ratio),
   with hysteresis so it does not flicker.
2. Distinguish: body part hidden / moved / left the frame.
3. Seated mode: keep the estimated upper-leg region behind the desk;
   update from visible shins, ankles and feet; the desk is never
   part of the SAM target (use mask-vs-region overlap, no fixed
   desk height).
4. Walking mode: switch to the full visible estimate, keep identity,
   smooth the transition.

Tests with synthetic keypoint sequences (sit down, stand up,
cross legs, one leg hidden). No zoom changes.
```

---

### Session 9: Tracking state machine (Part 7). CODE DONE

Delivered: `tracker/trackstate.py` (`TrackStateMachine`, `StateFrame`, `Anchor`, `ALLOWED` transition table), run on every `sam-track` (no new flag): `state` block in `<video>.sam.json` (optional, schema version unchanged), `track` block + machine state in the preview file, state colours and absence time in the mpv label, `lost_hold_s` from the config is the camera hold, 31 tests, decisions in `DECISIONS.md` ("Tracking state machine"). Your part: run `sam-track --preview --posture` on a clip with a desk occlusion, a leave/re-enter and (if you have one) a long loss, press `P`, paste the `durum:` line and observations into `TEST_RESULTS.md`. The original prompt is kept below for reference.

Files: new `tracker/trackstate.py`, `tracker/offline.py` (records), `tracker/config.py` (`lost_hold_s`), `core/LostWatch.kt` (reference).

```text
Implement the tracking states:
TRACKED, PARTIALLY_OCCLUDED, TEMPORARILY_LOST, OUT_OF_FRAME,
REACQUISITION_CANDIDATE, REACQUIRED, MANUAL_RESELECT_REQUIRED.

Reuse existing lost/hold logic. Distinguish partial occlusion,
temporary loss, frame exit and re-entry using mask ratio, TrackGate
results and box position near the frame edge.
Preserve the last reliable identity info and the previous camera crop.

Add the state to the per-frame records and to the preview overlay
field from Session 6. Transition tests only. No Re-ID matching yet.
```

---

### Session 10: Re-entry with existing Re-ID (Part 7)

Files: `tracker/reid.py`, `tracker/config.py` (`reid_*`, `kp_reid`), `tracker/trackstate.py`, `offline.py`.

```text
Wire the EXISTING Re-ID (tracker/reid.py, OSNet) into lower-body
recovery. Do not write a new Re-ID.

1. When state is OUT_OF_FRAME or TEMPORARILY_LOST, build candidates
   from later detections: appearance (Re-ID), body proportions,
   motion and timing.
2. Offline: look at future frames to verify a candidate before
   accepting it (REACQUISITION_CANDIDATE -> REACQUIRED).
3. If still uncertain, mark the interval MANUAL_RESELECT_REQUIRED.
4. Never attach to the next person who appears. Do not switch
   identity on weak confidence.

Tests: jump rejection and ambiguous re-entry (two similar people).
Note: osnet weights are optional in models/manifest.json; handle
a missing file gracefully.
```

---

### Session 11: Camera, 70% occupancy, no foot zoom pumping (Part 8)

Files: `tracker/geometry.py` (`compute_view`), `tracker/smooth.py`, `tracker/offline.py` (`_views_from_boxes`), `tracker/config.py` (`target_fill` 0.30 today), tests.

```text
Most of the camera director exists. Do NOT rewrite it.

Add only:
1. A lower-body preset (or config) with target occupancy 70% of
   output frame height, configurable. Do not change the global
   default without noting it in docs/DECISIONS.md.
2. Zoom input = the anatomical region + posture + mask evidence,
   NOT raw box height. A foot movement, crossed legs or an extended
   foot must not change zoom.
3. Zoom rate limits and hysteresis for lower-body mode; hold the
   framing during temporary occlusion; smooth reacquisition.
4. Keep pan/zoom control independent from identity tracking.

Tests: foot-wiggle, leg-cross, sit-down and stand-up sequences must
keep zoom within a small tolerance. Never zoom into the desk.
```

---

### Session 12: Bidirectional refinement (Part 9)

Files: `tracker/sam_engine.py`, `tracker/offline.py` (zero-phase smoothing, gap fill), records.

```text
Existing: zero-phase smoothing and gap fill in offline.py.
New: a backward SAM pass.

1. Run the SAM tracker backward from reliable anchor frames.
2. Compare forward vs backward on uncertain intervals (occlusion,
   re-entry, mask jumps).
3. Repair only where both agree or evidence clearly favors one.
   Keep high-confidence frames untouched. Do not fabricate
   certainty: unresolved frames stay flagged.
4. Keep RAM and VRAM bounded (process in windows).

Tests with synthetic forward/backward disagreement.
```

---

### Session 13: Export, NVENC, validation, optional stabilization (Part 10)

Files: `tracker/export.py` (`ffmpeg_cmd`: libx264 today), `tracker/gmc.py` (reuse for stabilization), `models/manifest.json` / ffmpeg build notes.

```text
Existing: ffmpeg pipe export, libx264 crf 18 veryfast, audio copy.
Missing: NVENC, NVDEC, validation, stabilization on PC.

1. Detect ffmpeg encoders (h264_nvenc) at runtime; use NVENC when
   available, fall back to libx264. Config flag to force either.
2. Optional NVDEC decode where it helps (decode stays sequential).
3. Optional stabilization reusing gmc.py (do not duplicate).
4. Export validation: duration, frame count, fps, audio stream,
   timestamps vs the source; clear error messages.
5. Preserve audio and frame timing.

Note: the bundled ffmpeg may lack NVENC. Report which encoders the
bundled build has; do not claim NVENC works until I run it.
Tests with fake ffmpeg output. Live tracking is not required.
```

---

### Session 14: Real-clip validation and Definition of done (Part 12)

```text
Do not add features.

1. Give me a short test plan: 3 real clips (seated at desk, sit then
   walk, leaves and re-enters), with the exact commands
   (`bench`, `sam-bench`, offline + export).
2. Create a results table in docs/TEST_RESULTS.md that I fill in.
3. Check each Definition-of-done item in docs/PROJECT_SPEC.md Part 12
   and record verified / unverified / failed with evidence.
4. List the top 5 problems found and propose follow-up sessions.
```

---

## Reminder: Definition of done (from PROJECT_SPEC.md Part 12)

- [ ] User can select both legs and feet using one rectangle.
- [ ] AI tracks the combined region.
- [ ] Individual limbs are tracked internally.
- [ ] Desk occlusion does not destroy the tracking region.
- [ ] Sitting-to-standing transitions work.
- [ ] Walking movement is tracked.
- [ ] Temporary occlusion is handled.
- [ ] The same person can be reacquired after leaving the frame when evidence permits.
- [ ] Camera maintains configurable apparent target size.
- [ ] Foot movements do not cause zoom pumping.
- [ ] Camera motion is smooth.
- [ ] Offline refinement improves uncertain intervals.
- [ ] Export preserves audio and timing.
- [ ] GPU memory usage remains controlled.

**Principle:** build a reliable tracker first, a reliable camera director second, and a polished user experience third.

---

## docs/ folder

```text
docs/
    PROJECT_SPEC.md          roadmap and requirements
    Lower body.md            this file (session plan, prompts)
    IMPLEMENTATION_AUDIT.md  what already exists
    PROGRESS.md              current position, latest checkpoint
    DECISIONS.md             open and made decisions
    KNOWN_ISSUES.md          bugs and gaps
    TEST_RESULTS.md          real measurements only
```
