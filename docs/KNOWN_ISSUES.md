# KNOWN ISSUES

From the Session 0 audit (2026-11-17).

1. No PC EdgeTAM/SAM runtime exists (only the bank reference and the export script).
2. `TrackGate` exists only in Kotlin.
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
