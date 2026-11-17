# PROGRESS

Current session: 5
Next smallest task: port `TrackGate` to Python and wire it into the SAM loop (see `docs/Lower body.md`, Session 5). Still open on your side: the Session 1 provider diagnostics, the Session 2 export + `sam-bench` runs, the Session 3 `sam-first` run and the Session 4 `sam-track` run on a 30 s clip (all need the exported graphs).

## Sessions

- [x] 0. Repo audit (read-only), done 2026-11-17 → `docs/IMPLEMENTATION_AUDIT.md`
- [x] 1. GPU provider: DirectML vs CUDA, optional CUDA path (code done 2026-11-17; your PC measurements pending)
- [x] 2. Export the 5 EdgeTAM graphs + PC loader + benchmark (code done 2026-11-17; your export and PC runs pending)
- [x] 3. PC SAM engine: rectangle prompt → first mask (code done 2026-11-17; your `sam-first` run on the real graphs pending)
- [x] 4. PC SAM memory loop: forward tracking with `MemoryBank`, per-frame records (code done 2026-11-17; your `sam-track` run on a 30 s clip pending)
- [ ] 5. Port `TrackGate` to Python: confidence gating, jump rejection
- [ ] 6. Mask outline + combined rectangle in the selection/preview
- [ ] 7. Lower-body region: visible vs anatomical, left/right evidence
- [ ] 8. Posture (seated/standing), desk occlusion, sit↔stand transitions
- [ ] 9. Tracking state machine (7 states)
- [ ] 10. Re-entry with existing Re-ID + future-frame verification
- [ ] 11. Camera: 70% occupancy, no zoom pumping from foot movement
- [ ] 12. Bidirectional refinement (backward SAM pass)
- [ ] 13. Export: NVENC + fallback, validation, optional stabilization
- [ ] 14. Real-clip validation and Definition of done

## Latest checkpoint

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
