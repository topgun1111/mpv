# KNOWN ISSUES

From the Session 0 audit (2026-11-17).

1. No PC EdgeTAM/SAM runtime exists (only the bank reference and the export script).
2. ~~`TrackGate` exists only in Kotlin.~~ Ported to `tracker/trackgate.py` and wired into `sam_track.py` (Session 5); thresholds are Android's and untuned on desk footage.
3. `requirements.txt` ships `onnxruntime-directml` only; CUDA is not available through it. Session 1 added the `providers` diagnostic and a separate-venv CUDA recipe (`DECISIONS.md`); the DirectML-vs-CUDA choice is still open until measured on your PC.
4. Real-clip validation on Windows (P23/V1) was never done, so current tracker quality on real footage is unknown.
5. Android code is uncompiled (`android/REMAINING.md`).
6. No desk/posture logic; seated handling is only the torso-length fallback in `parts.py`.
7. `target_fill` default is 0.30, not the 70% the roadmap asks for.
8. No NVENC/NVDEC, no export validation, no stabilization in the PC export.
9. `handover.md` says Part tests were 374; the suite now has 466 tests (465 pass, 1 skipped). Doc is stale.
10. (Session 2) The five graphs have never been exported or timed. `export_sam2.py` itself was not run; the memory-graph export (RoPE rewrite) is the most likely part to fail.
11. (Session 2) `sam-bench --fp16` relies on `onnxconverter-common` (`keep_io_types=True`); untested on these graphs. fp16 can overflow or change the output: the report shows NaN/Inf and the difference to fp32.
12. (Session 2) VRAM is read with `nvidia-smi` (whole GPU, first GPU only) and only on CUDA rows; DirectML has no VRAM number.
13. (Session 4) `sam-track` has never run on the real graphs: the memory graph input/output contract (`mem_feats` [K, ...], `ptrs` [P, 256], `mem_feat` size, decoder-trk with label -1) is taken from `export_sam2.py` and Kotlin only.
14. (Session 4) No gate yet: every tracked frame is pushed to memory, including half-hidden ones (desk in front of the legs), and a mask that jumps onto the desk is not rejected. Session 5.
15. (Session 4) Tracked/lost uses the Android thresholds (conf 0.35, size ratio 0.25-4) untested on legs; the sampled frames are the only output (no interpolation), and a run cannot be resumed after Ctrl+C (only the partial file is kept).
16. (Session 8) Posture thresholds (`THIGH_*`, `REACH_*`, `ENTER_*`, `STAND_AT`/`SIT_AT`), hold times and the desk rule (`DESK_*`) are first guesses from body proportions; nothing was tuned on a real clip, and the posture geometry assumes a frontal camera.
17. (Session 8) The "legs hidden" cue is deliberately weak; a standing person whose knees stay undetected for 2-3 s can read as seated. A desk mask that is not much wider than the body region is not recognised as a desk (S7 clipping and the S5 gate are the only guards then). A rejected desk mask still sits in SAM's memory.
18. (Session 8) `sam-preview` has no posture (one frame); only `sam-track --posture` computes it. The mpv posture word was never rendered.
19. (Session 9) The state machine's thresholds (`MANUAL_LOST_S`, `OUT_MAX_S`, `CONFIRM_FRAMES`, `EDGE_MARGIN`, `EXIT_MOVE`, `EXIT_SHRINK`) are first guesses; never tuned on a real clip. Confirmation counts frames, so it assumes the default sampling (10/s).
20. (Session 9) A very fast exit (the box jumps to the edge and vanishes in one sample) has no motion history and reads TEMPORARILY_LOST unless `--posture` reports both legs gone. A static box resting on an edge that really leaves is only caught by that hint or by shrinking.
21. (Session 9) REACQUIRED means "tracked again for 3 frames", not "it is the same person": no Re-ID or future-frame check yet (Session 10). MANUAL_RESELECT_REQUIRED is only a state and a label: nothing pauses `sam-track` or asks the user, and `reset()` has no UI caller. The mpv colours and the absence time were never rendered.
