# PROGRESS

Current session: 9
Next smallest task: tracking state machine (see `docs/Lower body.md`, Session 9). Still open on your side: the Session 8 `sam-track --preview --posture` run + `P`-key check, the Session 7 `sam-track --preview --pose` run + `P`-key check, the Session 1 provider diagnostics, the Session 2 export + `sam-bench` runs, the Session 3 `sam-first` run, the Session 4/5 `sam-track` runs (with and without `--no-gate`) and the Session 6 `sam-preview` + `P`-key check in mpv on a 30 s clip (all need the exported graphs).

## Sessions

- [x] 0. Repo audit (read-only), done 2026-11-17 → `docs/IMPLEMENTATION_AUDIT.md`
- [x] 1. GPU provider: DirectML vs CUDA, optional CUDA path (code done 2026-11-17; your PC measurements pending)
- [x] 2. Export the 5 EdgeTAM graphs + PC loader + benchmark (code done 2026-11-17; your export and PC runs pending)
- [x] 3. PC SAM engine: rectangle prompt → first mask (code done 2026-11-17; your `sam-first` run on the real graphs pending)
- [x] 4. PC SAM memory loop: forward tracking with `MemoryBank`, per-frame records (code done 2026-11-17; your `sam-track` run on a 30 s clip pending)
- [x] 5. Port `TrackGate` to Python: confidence gating, jump rejection (code done 2026-11-17; your `sam-track` runs with/without `--no-gate` pending)
- [x] 6. Mask outline + combined rectangle in the selection/preview (code done 2026-11-18; your `sam-preview` run + mpv `P` check pending)
- [x] 7. Lower-body region: visible vs anatomical, left/right evidence (code done 2026-11-18; your `--pose` run + mpv `P` check pending)
- [x] 8. Posture (seated/standing), desk occlusion, sit↔stand transitions (code done 2026-11-18; your `--posture` run + mpv `P` check pending)
- [ ] 9. Tracking state machine (7 states)
- [ ] 10. Re-entry with existing Re-ID + future-frame verification
- [ ] 11. Camera: 70% occupancy, no zoom pumping from foot movement
- [ ] 12. Bidirectional refinement (backward SAM pass)
- [ ] 13. Export: NVENC + fallback, validation, optional stabilization
- [ ] 14. Real-clip validation and Definition of done

## Latest checkpoint

SESSION CHECKPOINT

Phase: M2 (reliable tracker)
Task: Session 8, posture (seated/standing), desk occlusion, sit↔stand
Files inspected: docs/{Lower body,PROGRESS,DECISIONS,TEST_RESULTS,KNOWN_ISSUES}.md, handover.md (first lines + S1-S7 tail), tracker/{lowerbody,parts,sam_preview,sam_track,main}.py, mpv/portable_config/scripts/track.lua (preview overlay), tests/{test_lowerbody,test_sam_track}.py (helpers), pyproject.toml
Files changed: tracker/posture.py (new), tracker/main.py (`sam-track --posture`), tracker/sam_track.py (optional `posture` block in `make_doc`), mpv/portable_config/scripts/track.lua (posture word in the SAM label), tests/test_posture.py (new), pyproject.toml (E501 for the 2 new files), docs/{PROGRESS,DECISIONS,TEST_RESULTS,KNOWN_ISSUES,Lower body}.md, handover.md

What changed: `PostureModel` wraps the S7 `LowerBodyModel` (same `update` signature, S7 regions passed through untouched). It adds: (1) a SEATED/STANDING/TRANSITION classifier from hip-knee-ankle geometry in torso-length units plus the visible/anatomical ratio, with exponential smoothing, hysteresis and a dwell time (no flicker; `direction` = standing_up/sitting_down; held when there is no evidence); (2) per-leg status visible / moved / hidden / left_frame / unknown (hidden vs moved vs left the frame), reusing S7's swap decision so crossing legs keep identity; (3) a desk rule: a SAM mask that is much wider than the previous anatomical region and mostly outside it (or wider than 4.5 torso lengths) is not used as evidence, no fixed desk height; (4) a seated region that keeps the hidden upper-leg box and the last visible shin/foot box (anchored to the hips) for 20 s while the desk hides the legs; (5) a standing/walking region with the short S7 hold, mixed with the seated one by a rate-limited `blend`, then S7's foot-lead cap, dead zone and smoothing. `sam-track --posture` writes a `posture` block to `.sam.json` and the preview; `track.lua` appends the posture word to the label. `--pose` alone is unchanged. No zoom/camera change.

Tests/commands run: `tests/test_posture.py` and the lowerbody / SAM / preview / gate / parts / packaging / lua-ci test files through a stand-in runner (pytest and ruff are not installable offline here); `track.lua` loaded with texlua (syntax only)

Test results: 33 new tests passed (stand-in): sit down, stand up, no flicker with noisy keypoints, hidden legs behind the desk, frame-cut legs, one hidden leg, foot wiggle, lifted foot, crossed legs, hidden/moved/left-frame/unknown, desk mask rejected (and shown to widen the region when the filter is off), shin/thigh held behind the desk and expiry, standing hold, smooth blend, S7 output unchanged, JSON/row/preview/make_doc/CLI. Neighbouring files unchanged: test_lowerbody 27, test_sam_track 48, test_sam_preview 15, test_trackgate 10, test_sam_engine 28, test_parts 4, test_parts_robust 3, test_parts_b3 8, test_ci_lua 1, test_no_conflict_markers 2, test_packaging 17; test_offline_pose 8 passed / 1 failed (stand-in `approx` limit, same on the untouched zip). Real `pytest -q` and `ruff check .` NOT run

Known failures: none seen in the new code

Unverified assumptions: all thresholds (`THIGH_*`, `REACH_*`, `ENTER_*`/`STAND_AT`/`SIT_AT`, `DESK_*`, hold times) are first guesses from body proportions, never tuned on a real clip; YOLOv8-pose keypoints behind a desk behave like the synthetic rows; the posture geometry assumes a frontal camera (a side view of a seated person has no foreshortened thigh but should still read as seated by the ankle drop); the "legs hidden" cue is weak by design and a standing person with knees undetected for 2-3 s could read as seated (the regions barely differ then); the desk rule misses a desk mask that is not much wider than the body region; a rejected desk mask is not removed from SAM's memory (Session 5 gate); the Lua label was never rendered in mpv; ruff rules other than E501 on the new files (e.g. import order of `_SIDES`)

Next smallest task: Session 9 (tracking state machine, 7 states)
Exact command to resume: new chat, paste Master instruction + Session 9 prompt from `docs/Lower body.md`; first run `python -m tracker sam-track models\sam-edgetam klip.mp4 --rect X1,Y1,X2,Y2 --max-seconds 30 --preview --posture`, open the clip in mpv, press `P`, and note whether the posture word flips on sit/stand and where the cyan box looks wrong

Previous checkpoint (Session 7):

SESSION CHECKPOINT

Phase: M2 (reliable tracker)
Task: Session 7, lower-body region (visible vs anatomical)
Files inspected: docs/{Lower body,PROGRESS,DECISIONS,TEST_RESULTS}.md, handover.md (first 30 lines + tail), tracker/{parts,targets,sam_preview,sam_track,pose,offscreen}.py, tracker/main.py (sam-track, sam-preview), mpv/portable_config/scripts/track.lua (preview overlay), tests/{test_parts_robust,test_sam_preview,test_sam_track}.py (helpers)
Files changed: tracker/lowerbody.py (new), tracker/main.py (`--pose`/`--pose-model` for `sam-track` and `sam-preview`), tracker/sam_preview.py (`lower` payload), tracker/sam_track.py (optional `lower` block in `make_doc`), mpv/portable_config/scripts/track.lua (2 extra boxes), tests/test_lowerbody.py (new), pyproject.toml (E501 for the 2 new files), docs/{PROGRESS,DECISIONS,Lower body}.md, handover.md

What changed: `LowerBodyModel` keeps two regions per frame: visible (reliable knee/ankle + clipped SAM mask) and anatomical (hip down to the last visible foot, at least 1 torso length, hidden thighs included, always containing visible), plus per-leg evidence (left/right, hidden/held, mask overlap) and ONE framing rectangle (stretched-foot cap, dead zone, smoothing). Missing landmarks are held or mirrored, never "limb gone"; left/right swaps are repaired by continuity; the desk side/torso part of a mask is clipped. `Follower` matches the pose to the SAM box (seated person box extended downward). `sam-track --pose` writes `lower` rows to `.sam.json` and the preview; the cyan preview rectangle is now the framing. No zoom/camera change.

Tests/commands run: `tests/test_lowerbody.py` and the parts / SAM / preview / gate / targets test files through a stand-in runner (pytest and ruff are not installable offline here); `track.lua` loaded with texlua (syntax only)

Test results: 27 new tests passed (stand-in); 123 tests in the neighbouring files passed. Real `pytest -q` and `ruff check .` NOT run

Known failures: none seen

Unverified assumptions: the Lua boxes were never rendered in mpv; YOLOv8-pose keypoints behind a desk behave like the synthetic rows (knees/ankles low-confidence or absent, hips visible); constants (`LEG_REACH` 1.0 L, `FULL_LEG` 2.0 L, dead zone 6 %, foot lead 0.4 L) are first guesses, not tuned on a real clip; `--pose` cost per frame on the RTX 3050 (never measured); the pose model finds the seated person at all (box matching assumes legs lie below the person box); ruff rules other than E501 on the new files

Next smallest task: Session 8 (posture seated/standing, desk occlusion, sit↔stand)
Exact command to resume: new chat, paste Master instruction + Session 8 prompt from `docs/Lower body.md`; first run `python -m tracker sam-track models\sam-edgetam klip.mp4 --rect X1,Y1,X2,Y2 --max-seconds 30 --preview --pose`, open the clip in mpv, press `P` and note where magenta/orange/cyan look wrong

Previous checkpoint (Session 6):

SESSION CHECKPOINT

Phase: M2 (reliable tracker)
Task: Session 6, mask outline + combined rectangle preview
Files inspected: docs/{Lower body,PROGRESS,DECISIONS}.md (Session 6 parts), handover.md (tail), tracker/{sam_engine,sam_track,main}.py, mpv/portable_config/scripts/track.lua (dot overlay, scan poll), tests/test_sam_track.py (helpers)
Files changed: tracker/sam_preview.py (new), tracker/main.py (`sam-preview` command, `sam-track --preview`), mpv/portable_config/scripts/track.lua + input.conf (`P` overlay), tests/test_sam_preview.py (new), pyproject.toml (E501 for the 2 new files), docs/PROGRESS.md, handover.md

What changed: all logic is in `tracker/sam_preview.py` (mask -> normalized outline <= 96 points, combined rectangle, state/confidence payload, atomic `<video>.sam.preview.json`, throttled `Writer`). `sam-preview MODEL_DIR VIDEO --rect ...` runs the first-mask step and writes a CONFIRM (or NO_MASK) preview; redraw = run it again with a new `--rect`. `sam-track --preview` writes outline, rectangle, conf and state (TRACKED/LOST placeholder until Session 9) at most every 0.5 s and a DONE frame at the end. `track.lua` only draws that file (`P` toggles, polls 0.5 s): green outline, cyan combined rectangle (= mask box for now; Session 7 makes it legs+feet), yellow drawn rectangle, state/conf text. Right-click/right-drag untouched.

Tests/commands run: `tests/test_sam_preview.py` (15), `test_sam_track.py`, `test_trackgate.py`, `test_sam_engine.py` through a stand-in runner (pytest is not installed here); `track.lua` loads with texlua (syntax only).

Test results: 15 new + 48 + 10 + 28 passed in the stand-in runner. Not run with real pytest or ruff.

Known failures: none seen.

Unverified assumptions: the Lua overlay was never rendered in mpv (no Lua test added; only a syntax load); `ruff` import order for `from test_sam_track import ...` in the new test; ASS border-only polygon (`\1a&HFF&` + `\bord`) looks right in libass.

Next smallest task: Session 7 (lower-body region, visible vs anatomical)
Exact command to resume: new chat, paste Master instruction + Session 7 prompt from `docs/Lower body.md`. First: `python -m tracker sam-preview models\sam-edgetam klip.mp4 --rect X1,Y1,X2,Y2 --device dml`, open the video in mpv, press `P`; then `python -m tracker sam-track models\sam-edgetam klip.mp4 --rect X1,Y1,X2,Y2 --max-seconds 30 --preview` and watch the overlay.

Previous checkpoint (Session 5):

SESSION CHECKPOINT

Phase: M2 (reliable tracker)
Task: Session 5, port TrackGate (gating + jump rejection)
Files inspected: docs/{Lower body,PROGRESS,DECISIONS,KNOWN_ISSUES,IMPLEMENTATION_AUDIT}.md, handover.md (S1-S4 tail), android/core/.../TrackGate.kt + TrackGateTest.kt, android/app/src/sam/.../SamEngine.kt (`walkMemory`), tracker/{sam_track,sam_engine,edgetam_bank,main}.py, tests/test_sam_track.py
Files changed: tracker/trackgate.py (new), tracker/sam_track.py (gate in the loop, record fields, schema v2), tracker/main.py (`--no-gate`, gate summary), tests/test_trackgate.py (new), tests/test_sam_track.py, pyproject.toml (E501 for the two new files), handover.md, docs/*
What changed: `TrackGate` ported with the Kotlin constants (a test compares them with the Kotlin source). In `track_video` a frame that passes the S4 confidence check now goes through `accept` (jump / reappearance must look like the subject by object-pointer cosine; learned from the first clean frames) and `remember` (only clean frames enter the bank; 12 unclean frames in a row force one in). A gate rejection is a lost frame with `accepted` False and pushes nothing. Records gain `clean`, `w`, `h` (camera size = last clean size while the mask is under 0.6x), `.sam.json` version 2 with a `gate` block. `sam-track --no-gate` restores S4 behaviour; the console shows the gate summary and the count of tracked-but-not-remembered frames.
Tests/commands run: `tests/test_trackgate.py`, `tests/test_sam_track.py` and the SAM/scan/cache/packaging/edgetam test files through a stand-in runner (pytest and ruff not installable offline here)
Test results: 10 new gate tests + 9 new loop tests (incl. "mask jumps onto a desk box and is rejected") passed (stand-in); one S4 test adapted (`use_gate=False`), one renamed, the round-trip test extended. Neighbouring files unchanged. Real `pytest -q` and `ruff check .` NOT run
Known failures: none seen in the new code (stand-in has no `pytest.fixture`, so `test_providers.py` cannot be imported there, same on the untouched zip)
Unverified assumptions: Android thresholds suit legs behind a desk (they were tuned for phone clips; the first ~3 clean frames are ungated); object pointers of the real graphs separate "subject" from "desk" by cosine (only fake pointers ran); that desk frames score conf >= 0.35 at all (if the real graphs already call them lost, the gate is idle there); speed unchanged (cosine on 256 floats); ruff rules other than E501 on the new files
Next smallest task: Session 6
Exact command to resume: new chat, paste Master instruction + Session 6 prompt from `docs/Lower body.md`; first run `sam-track` with and without `--no-gate` (`docs/DECISIONS.md`, "TrackGate") on a 30 s clip

Previous checkpoint (Session 4):

SESSION CHECKPOINT

Phase: M2 (reliable tracker)
Task: Session 4, PC SAM memory loop (forward tracking)
Files inspected: docs/{Lower body,PROGRESS,DECISIONS,TEST_RESULTS,KNOWN_ISSUES}.md, handover.md (first 30 lines + tail), tracker/{sam_engine,sam_bench,edgetam_bank,offline (VideoSource),cache,main}.py, scripts/export_sam2.py (graph I/O header), android/.../sam/SamEngine.kt (`walkMemory`), tests/{test_sam_engine,test_sam_bench,test_edgetam_contract,test_scan}.py
Files changed: tracker/sam_track.py (new), tracker/sam_engine.py (memory graphs, `_run` timing wrapper, 4 methods), tracker/main.py (`sam-track`), tests/test_sam_track.py (new), pyproject.toml (E501 for the two new files), handover.md, docs/*
What changed: `SamEngine(memory=True)` loads `sam-decoder-trk`, `sam-memenc`, `sam-memattn`; `track_video(engine, frames, rect)` is a lazy generator: frame 0 = encoder + decoder + memenc + `MemoryBank.reset`; later frames = encoder, memattn (bank slots), decoder-trk, then memenc + push only when tracked (Android tracked/lost rule, no gate). One record per frame (t, state, accepted=True, normalized box, iou, object_score, conf, area, ratio). `Clip` samples a video at `--fps` from `--start`. Records are saved to `<video>.sam.json` (separate file, `track.json` schema untouched, atomic, partial save on Ctrl+C). `python -m tracker sam-track MODEL_DIR VIDEO --rect ...` prints frames, tracked/lost, fps, ms per graph, provider (fall-back flag) and peak VRAM on CUDA.
Tests/commands run: `tests/test_sam_track.py` plus the SAM, provider, scan and offline-pose test files through a stand-in runner (pytest and ruff are not installable offline here)
Test results: 39 new tests passed (stand-in). The neighbouring files give identical results on the untouched uploaded zip and on this tree (stand-in limits, see TEST_RESULTS). Real `pytest -q` and `ruff check .` NOT run
Known failures: none seen in the new code
Unverified assumptions: the real graphs accept these inputs (`mem_feats` [K, ...] / `ptrs` [P, 256] static, `mem_feat` output size equals one `mem_feats` slot, decoder-trk accepts coords [1,1,2] with label -1); the Android tracked/lost thresholds suit legs behind a desk; speed and VRAM on the RTX 3050 (never measured); without the gate (Session 5) half-hidden frames enter memory; DirectML first-run behaviour; ruff rules other than E501 on the new files
Next smallest task: Session 5
Exact command to resume: new chat, paste Master instruction + Session 5 prompt from `docs/Lower body.md`; first run `sam-track` (`docs/DECISIONS.md`, "SAM memory loop") on a 30 s clip so the loop is proven on real graphs

Previous checkpoint (Session 3):

SESSION CHECKPOINT

Phase: M2 (reliable tracker)
Task: Session 3, PC SAM engine: rectangle to first mask
Files inspected: docs/{Lower body,PROGRESS,IMPLEMENTATION_AUDIT,DECISIONS,TEST_RESULTS}.md, handover.md (first 30 lines + tail), android/.../sam/SamEngine.kt (prompt3, analyse, pickCandidate, chw, decode), scripts/export_sam2.py (graph I/O header), tracker/{edgetam_bank,providers,detector,sam_bench,main}.py, tests/{test_edgetam_contract,test_sam_bench}.py
Files changed: tracker/sam_engine.py (new), tracker/main.py (`sam-first`), tests/test_sam_engine.py (new), pyproject.toml (E501 for the two new files), handover.md, docs/*
What changed: `SamEngine` (encoder + decoder only): preprocess (RGB, ImageNet mean/std, squash to 1024), rectangle prompt (corners 2/3 + centre point 1), best-iou candidate (Android "smallest" rule optional), mask to normalized and frame-pixel box, scores and `obj_ptr`, provider report with fall-back flag. `python -m tracker sam-first MODEL_DIR IMAGE --rect x1,y1,x2,y2 [--norm] [--device] [--rule] [--out]` writes a contour PNG. No memory, video loop, UI or zoom.
Tests/commands run: `tests/test_sam_engine.py` and the rest of `tests/` through a stand-in runner (pytest and ruff are not installable offline here)
Test results: 28 new tests passed (stand-in); other files 433 passed / 34 failed-or-errored, identical on the untouched uploaded zip (stand-in limits). Real `pytest -q` and `ruff check .` NOT run
Known failures: none seen in the new code
Unverified assumptions: the real graphs accept these inputs and return the output names/shapes in `export_sam2.py` (only fake sessions ran); squash resize matches the exported graphs' training preprocessing (SAM 2 does this, not run); "best" beats "smallest" for legs behind a desk; DirectML first-run behaviour; ruff rules other than E501 on the new files
Next smallest task: Session 4
Exact command to resume: new chat, paste Master instruction + Session 4 prompt from `docs/Lower body.md`; first run `sam-first` (`docs/DECISIONS.md`, "SAM engine") so the graphs and the engine are proven on a real image

Previous checkpoint (Session 2):

SESSION CHECKPOINT

Phase: M1 (GPU + repo understood)
Task: Session 2, graph export plumbing + `sam-bench`
Files inspected: scripts/export_sam2.py, tests/test_edgetam_contract.py, tracker/{providers,detector,bench,edgetam_bank}.py, tracker/main.py (pose-bench, dispatch), android/.../sam/SamEngine.kt (graph I/O, randomInputs, bench), .github/workflows/{android,build-all,ci}.yml, tests/test_build_all.py, tests/test_providers.py, docs/*
Files changed: tracker/sam_bench.py (new), tracker/main.py, tests/test_sam_bench.py (new), .github/workflows/sam-export.yml (new), pyproject.toml (E501 for the two new Python files), handover.md, docs/*
What changed: `python -m tracker sam-bench MODEL_DIR [--device] [--runs] [--warmup] [--fp16] [--out]`: per graph load time, cold warm-up, avg/p50/p95 ms, provider actually used (+ fell_back), NaN/Inf check, peak VRAM via nvidia-smi on CUDA only (n/a on DirectML), optional fp16 variant with output difference vs fp32; JSON report, Markdown rows in the TEST_RESULTS table format, one-frame chain sum. New manual workflow `SAM export (PC)` uploads the five graphs. Export and benchmark commands in `DECISIONS.md`.
Tests/commands run: `tests/test_sam_bench.py` and the existing files through a stand-in runner (pytest and ruff are not installable offline here); real ORT 1.31.0 CPU CLI run on five tiny hand-written ONNX graphs
Test results: 20 new tests passed (stand-in); rest of the suite 403 passed / 9 failed-or-errored, identical counts on the untouched Session 1 zip (stand-in limits). Real `pytest -q` and `ruff check .` NOT run
Known failures: none seen in the new code
Unverified assumptions: `export_sam2.py` really produces the five graphs (not run); `onnxconverter-common` fp16 conversion on these graphs; DirectML first-run behaviour and nvidia-smi sampling on your RTX 3050; the new workflow on GitHub; ruff import-order/line rules on the new files (E501 ignored for them like `providers.py`)
Next smallest task: Session 3
Exact command to resume: new chat, paste Master instruction + Session 3 prompt from `docs/Lower body.md`; first run the export and `sam-bench` from `docs/DECISIONS.md` ("SAM graphs") so the graphs exist

Previous checkpoint (Session 1):

SESSION CHECKPOINT

Phase: M1 (GPU + repo understood)
Task: Session 1, GPU provider diagnostics
Files inspected: tracker/detector.py (select_providers, Detector), tracker/config.py, tracker/main.py (pose-bench, dispatch), tracker/reid.py + number.py (session creation), tests/test_detector.py, pyproject.toml
Files changed: tracker/detector.py, tracker/config.py, tracker/main.py, tracker/providers.py (new), tests/test_providers.py (new), pyproject.toml, handover.md, docs/*
What changed: `providers` command; `provider_order` config + `TAKIPLI_PROVIDER_ORDER` env (default unchanged); `preload_cuda` when CUDA is selected; CUDA venv recipe in DECISIONS.md
Tests/commands run: pytest (full, minus test_lua_menu.py), ruff check ., `python -m tracker providers --device cuda` in the sandbox
Test results: 479 passed, 1 skipped; ruff clean; CLI printed the expected CPU-only report
Known failures: none seen
Unverified assumptions: CUDA preload and the CUDA venv recipe on your RTX 3050 / Windows; NVIDIA driver needed for a CUDA 13.0 build; DirectML session options unchanged
Next smallest task: Session 2
Exact command to resume: new chat, paste Master instruction + Session 2 prompt from `docs/Lower body.md`

Previous checkpoint (Session 0):

SESSION CHECKPOINT

Phase: M1 (GPU + repo understood)
Task: Session 0, repo audit
Files inspected: handover.md (lines 1-169, 540-592), tracker/{edgetam_bank,parts,pose,gmc,export,offline,bench,detector,config,main}.py (outlines/greps), scripts/export_sam2.py (head), models/manifest.json, android/core/{TrackGate,Hardening,LostWatch}.kt, android/REMAINING.md, tests/test_edgetam_contract.py (head)
Files changed: none in the repo; added docs/ (this folder)
What changed: created audit and progress docs only
Tests/commands run: `pytest -q -p no:cacheprovider --ignore=tests/test_lua_menu.py` in a scratch copy
Test results: 465 passed, 1 skipped
Known failures: none seen; GPU/Windows/Kotlin/Lua not run
Unverified assumptions: Android SamEngine.kt is a correct reference (uncompiled); 5 ONNX graphs export cleanly (not run)
Next smallest task: Session 1
Exact command to resume: new chat → paste Master instruction + Session 1 prompt from `docs/Lower body.md`

## Known blockers

- No ONNX graphs or weights in the repo; export needs CI or a machine with torch.
- Real-GPU measurements must be run by the user on the RTX 3050 laptop.
