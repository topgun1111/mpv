# TEST RESULTS

Only real, measured results go here. Never paste estimates. Earlier RTX 3060 numbers were estimates, not RTX 3050 benchmarks.

## 2026-11-17, Session 0 (CPU, Linux scratch copy)

Command: `python3 -I -m pytest -q -p no:cacheprovider --ignore=tests/test_lua_menu.py`
Result: **465 passed, 1 skipped** in 6.05 s.
Not run: `tests/test_lua_menu.py`, Lua harnesses, Kotlin tests (`gradle :core:test`), anything on Windows, DirectML or CUDA.

## 2026-11-17, Session 1 (CPU, Linux scratch copy)

Command: `python3 -I -m pytest -q -p no:cacheprovider --ignore=tests/test_lua_menu.py` and `ruff check .` (CI runs both).
Result: **479 passed, 1 skipped** (14 new tests in `tests/test_providers.py`); ruff clean.
Real CLI run in the sandbox (no GPU): `python -m tracker providers --device cuda` printed ONNX Runtime 1.29.0, providers `AzureExecutionProvider, CPUExecutionProvider`, selection CPU for every device, and the "CUDA sağlayıcısı yok" warning, as expected.
Not run: anything on your Windows PC, DirectML, or CUDA.

## 2026-11-17, Session 2 (Linux scratch copy, CPU, no pytest/ruff)

`pytest` and `ruff` could not be installed in this session (no network), so the repo's own commands were **not run**. Instead:
- `tests/test_sam_bench.py` (20 tests) was run with a small stand-in runner written for this session (it supplies `tmp_path`, `monkeypatch`, `importorskip`): 20 passed. Breaking the fallback check on purpose made the matching test fail, so the tests do detect it.
- The other test files were run through the same stand-in: 403 passed, 9 failed or errored. The same counts (403 / 9) come out on the untouched Session 1 zip (stand-in limits: `parametrize`, fixtures from helper modules, `approx`), so they are not caused by this session. This is not a replacement for `pytest`.
- Real ONNX Runtime 1.31.0 (CPU) ran `python -m tracker sam-bench` on five tiny hand-written graphs with the real graph file names: exit code 0, five rows, provider `CPUExecutionProvider`, JSON and `.md` files written. Those graphs are not EdgeTAM, so the timings mean nothing.
- Not run: the real five graphs, DirectML, CUDA, `--fp16` conversion (`onnx` and `onnxconverter-common` are not installed here), `nvidia-smi` VRAM sampling on a real GPU, the new workflow on GitHub.

Your part: `python -m pytest -q -p no:cacheprovider` and `ruff check .` (record the counts here), then the export and `sam-bench` runs from `DECISIONS.md` ("SAM graphs").

## 2026-11-17, Session 3 (Linux scratch copy, CPU, no pytest/ruff)

`pytest` and `ruff` are still not installable offline, so the repo's own commands were **not run**.
- `tests/test_sam_engine.py` (28 tests, fake sessions, no model files): 28 passed in a stand-in runner that supplies `tmp_path`, `monkeypatch`, `capsys`, `pytest.raises`, `pytest.approx`.
- The other test files were run file by file through the same stand-in on the untouched uploaded zip and on this tree: 433 passed / 34 failed on both. The identical counts show this session changed none of them; the 34 are stand-in limits (as in Session 2), not real failures. Not a replacement for `pytest`.
- Not run: the real EdgeTAM graphs (not in the repo), DirectML, CUDA, `sam-first` on a real image, `ruff check .` (new files have E501 ignored in `pyproject.toml`, other rules unchecked).

Your part: `python -m pytest -q -p no:cacheprovider` and `ruff check .` (record the counts), then `sam-first` from `DECISIONS.md` ("SAM engine"):

```text
(paste: python -m tracker sam-first models\sam-edgetam <image> --rect x1,y1,x2,y2 --device dml)
```

## 2026-11-17, Session 4 (Linux scratch copy, CPU, no pytest/ruff)

`pytest` and `ruff` are still not installable offline, so the repo's own commands were **not run**.
- `tests/test_sam_track.py` (39 tests, fake graphs that carry frame numbers through memenc/memattn so the slot order can be read; a real MJPG clip for `Clip` and the CLI): 39 passed in the stand-in runner.
- `test_sam_engine`, `test_sam_bench`, `test_edgetam_contract`, `test_providers`, `test_scan`, `test_offline_pose`: 79 passed / 6 failed on both the untouched uploaded zip and this tree (stand-in limits: chained `approx` comparisons and provider-order tests), so the engine change (`_run` wrapper) broke nothing there. Not a replacement for `pytest`.
- Whole `tests/` file by file through the stand-in: 365 passed / 9 failed on the untouched zip, 404 passed / 9 failed on this tree (the same 9; +39 are the new file). 18 files (the `test_lua_*` ones, `test_live`, `test_export`, `test_ipc`, ...) printed no result in the stand-in on either tree, so they are not covered by these counts.
- Not run: the real EdgeTAM graphs, DirectML, CUDA, `sam-track` on a real clip, `ruff check .`.

Your part: `python -m pytest -q -p no:cacheprovider` and `ruff check .` (record the counts), then `sam-track` from `DECISIONS.md` ("SAM memory loop"):

```text
(paste: python -m tracker sam-track models\sam-edgetam klip.mp4 --rect x1,y1,x2,y2 --max-seconds 30 --device dml)
(paste: the same with --device cuda in the CUDA venv)
```

## Lower-body region, Session 7 (your PC)

```text
(paste: python -m tracker sam-track models\sam-edgetam klip.mp4 --rect x1,y1,x2,y2 --max-seconds 30 --device dml --preview --pose)
(paste: the same without --pose, for the fps difference)
Observed in mpv (P): anatomical (magenta) / visible (orange) / framing (cyan) on a seated clip, a foot wiggle, crossed legs, one leg hidden: ...
```

## Posture, Session 8 (your PC)

```text
(paste: python -m tracker sam-track models\sam-edgetam klip.mp4 --rect x1,y1,x2,y2 --max-seconds 30 --device dml --preview --posture)
Observed in mpv (P): posture word (seated / transition / standing) on sit-down and stand-up, flicker: ...
Cyan framing while the desk hides the legs / while walking / one foot stretched: ...
Frames with lower.desk_mask true and what the mask covered: ...
```

Stand-in results (not a replacement for `pytest`): `tests/test_posture.py` 33 passed; neighbouring files unchanged (see `PROGRESS.md`). Real `pytest -q` and `ruff check .` not run here.

## State machine, Session 9 (your PC)

```text
(paste: python -m tracker sam-track models\sam-edgetam klip.mp4 --rect x1,y1,x2,y2 --max-seconds 60 --device dml --preview --posture)
The `durum:` line (frames per state, transition count): ...
Observed in mpv (P): colours/labels on desk occlusion, short dropout, walk out and back, a long loss: ...
Any seated loss that read OUT_OF_FRAME, any exit that read TEMPORARILY_LOST, flicker between TRACKED and PARTIALLY_OCCLUDED: ...
```

Linux scratch copy (CPU, real pytest 9.2.0): `python -m pytest -q -p no:cacheprovider` 693 passed, 1 skipped (31 new in `tests/test_trackstate.py`); `ruff check .` 31 findings, the same as the untouched upload (none in the new or changed code). `track.lua` loaded with texlua (syntax only).

## Provider diagnostics (your PC, paste outputs here)

### DirectML environment
```text
(paste: python -m tracker providers --device dml --model models\yolox_s.onnx)
```

### CUDA venv
```text
(paste: python -m tracker providers --device cuda --model models\yolox_s.onnx)
```

## GPU benchmarks (RTX 3050 Laptop, 6 GB)

| Date | Model/graph | Provider | Precision | Load s | Warm-up ms | Avg ms | Peak VRAM MB | Notes |
|---|---|---|---|---|---|---|---|---|
| (none yet) | | | | | | | | |
