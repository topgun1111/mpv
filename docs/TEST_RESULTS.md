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

## Re-entry with Re-ID, Session 10 (your PC)

```text
(paste: python -m tracker sam-track models\sam-edgetam klip.mp4 --rect x1,y1,x2,y2 --max-seconds 90 --device dml --preview --posture --reid)
The `durum:` and `re-ID:` lines: ...
Observed in mpv (P): walk out and back (candidate -> reacquired timing), a stranger walking in first (other_person), two similar people (ambiguous_reentry): ...
Any return that read REACQUIRED but was the wrong person, any true return that stayed uncertain, `doğrulanamadı` count and why: ...
```

Linux scratch copy (CPU, real pytest 9.1.1, Python 3.13): `python -m pytest -q -p no:cacheprovider --ignore=tests/test_lua_menu.py` 720 passed, 1 skipped (29 new in `tests/test_reentry.py`; the 691 before are unchanged); `ruff check .` clean (ruff 1.2.0). Fake embedder/pose/SAM only: no real OSNet, no GPU.

## Camera, Session 11 (your PC)

```text
(paste: python -m tracker sam-track models\sam-edgetam klip.mp4 --rect x1,y1,x2,y2 --max-seconds 90 --device dml --preview --posture --camera)
The `kamera:` line (median occupancy, zoom range, fastest change): ...
(paste: python -m tracker export klip.mp4, then look at klip_*.mp4)
Observed in the export: foot wiggle / crossed legs / extended foot (size changes?), sit down and stand up (smooth? how long?), desk mask (never zoomed in?), an occlusion (held?) and a return (eased in?): ...
Any moment the zoom pumped or the feet were cut off, and which constant you changed (`lower_window_s`, `lower_zoom_tol`, `lower_zoom_rate`, `camera.PERSIST_S`): ...
```

Linux scratch copy (CPU, Python 3.12, no pytest/ruff installable offline): `tests/test_camera.py` 35 passed through a stand-in runner; the whole `tests/` (minus `test_lua_menu.py`) 693 passed / 57 failed-or-errored, the same 57 that fail on the untouched upload (659 passed / 57 there; the 57 are stand-in limits). Mutation checks: removing the start threshold, the persistence, the trimming, the desk filter, the PARTIALLY_OCCLUDED exclusion, the hold, the re-entry ramp or the rate limit each makes at least one new test fail. Real `python -m pytest -q -p no:cacheprovider` and `ruff check .` NOT run.

## Bidirectional refinement, Session 12 (your PC)

```text
python -m tracker sam-refine models\sam-edgetam klip.mp4.sam.json --plan
(paste: the interval list)
python -m tracker sam-refine models\sam-edgetam klip.mp4.sam.json --device dml --camera
(paste: one line per interval + the summary line + the camera line)
```

Look at: intervals closed vs open vs mismatch; unresolved reasons (`identity` and `identity_cut` are expected around a stranger; many `no_backward` or `closure_mismatch` mean backward SAM does not hold); frames repaired in a desk occlusion; time and peak VRAM compared with the forward run: ...

Linux scratch copy (CPU, Python 3.12, no pytest/ruff installable offline): `tests/test_bidir.py` 55 passed through a stand-in runner; the whole `tests/` (minus `test_lua_menu.py`) 760 passed / 54 failed-or-errored, the same 54 that fail on the untouched upload (705 passed / 54 there; the 54 are stand-in limits). 28 mutation checks on `bidir.py`: each removed rule makes at least one test fail. Real `python -m pytest -q -p no:cacheprovider` and `ruff check .` NOT run.

## Session 14: real-clip validation (your PC)

No features were added. This section is the test plan, the tables you fill in, and the Definition-of-done check. Nothing below the "Linux scratch copy" line was run on a real clip, a real graph or a GPU.

### 0. Linux scratch copy (CPU, 2026-11-18, real tools)

- `python3 -I -m pytest -q -p no:cacheprovider --ignore=tests/test_lua_menu.py`: **863 passed, 1 skipped** in 15.5 s (pytest 9.1.1).
- `ruff check .` (0.16.9): **3 findings, all old**: E501 at `tests/test_export_nvenc.py:15` and `:61`, I001 at `tracker/bidir.py:36` (`--fix` can sort it). None from Session 13 or 14.
- `python -m tracker.export_check` (sandbox ffmpeg): lists `libx264`, `h264_nvenc`, `hevc_nvenc`, `av1_nvenc`, `h264_qsv`; `nvenc_works: false` (no GPU, trial encode fails); hwaccel `cuda` listed. Listed is not working.
- Synthetic export, 8 s / 25 fps / 640x360 testsrc + 440 Hz sine, views `[[0,0,0,0],[4,0.8,0.05,0.1],[8,0.8,0.05,0.1]]`:
  - `export klip.mp4 --encoder auto` -> `200 kare, 640x360, ses dahil, libx264, 1 sn`, `doğrulama: tamam`.
  - `export klip.mp4 --stabilize --decode auto` -> NVDEC failed (`Cannot load libcuda.so.1`), warning printed, fell back to CPU decode, `200 kare, ses dahil, 2 sn`, `doğrulama: tamam`.
  - 200 frames in, 200 out, audio kept: the Session 13 frame-loss fix holds on this clip. It proves nothing about NVENC, NVDEC or a real moving shot.

### 1a. Automatic run (replaces typing the commands in section 1)

Put the clips in `klipler\` and double-click `launcher\Dogrula.bat` (or `python -m tracker.autotest --clips klipler --device dml`). It runs preflight (`providers`, `export_check`, `sam-bench`), then per clip: old-tracker baseline, `sam-track` with all flags, `sam-refine --plan`, `sam-refine --camera`, `export`, `export --stabilize`; samples GPU memory (nvidia-smi, or Windows `typeperf`, whole card) and checks the produced files: tracked ratio, expected states, 70 % occupancy, zoom pumping (reversals per minute) and zoom rate limit, refine frame counts, export validation. Report: `validation\<time>\report.md` + `report.json` + one log per step; exit code 1 on any failure. The box is taken automatically from the first frame (lower half of the person box, preview PNG saved for a quick look) unless `X.mp4.test.json` gives `rect`, `start` and `expect` (`min_tracked`, `states_include`, `states_exclude`). Only the failure path and the pure checks were run here (873 tests); the happy path needs the real graphs. The observations in table 2b (what you *see*) stay manual.

Single file: drag a video onto `launcher\Test.bat`, or run `launcher\Sag-Tik-Ekle.bat` once to get "Takipli Oynat ile test et" in the right-click menu of video files. The log goes to the Desktop: a `Takipli-Test-<clip>-<time>` folder (report, one log per step, rectangle preview) and the same report as a single `.md` file. `Sag-Tik-Kaldir.bat` removes the menu entry.

### 1. Test plan (3 clips, about 60-90 s each, 1080p or 720p as you normally record)

| Clip | Scene | What it must show |
|---|---|---|
| A `seated.mp4` | Frontal, seated behind a desk, 60 s: feet wiggle, legs crossed once, one foot stretched out | Desk never in the target, no zoom pumping, 70 % occupancy |
| B `sitwalk.mp4` | Sits 20 s, stands up, walks across the room, sits down again | Sit<->stand transitions, walking, posture word, camera follows |
| C `leave.mp4` | Seated, a desk occlusion (someone passes in front), subject leaves the frame, returns after 10-20 s; second take: another person walks in first | Temporary occlusion, exit and re-entry, wrong-person rejection |

Rectangle: in the first frame, draw one box around both legs and both feet. Read X1,Y1,X2,Y2 (pixels) from a screenshot of frame 0; `--start SN` if the box is drawn later.

**Once, before the clips** (paste outputs into section 2):

```text
python -m pytest -q -p no:cacheprovider
ruff check .
python -m tracker.export_check
python -m tracker providers --device dml
python -m tracker sam-bench models\sam-edgetam --device dml --out sam-bench-dml.json
(CUDA venv) python -m tracker sam-bench models\sam-edgetam --device cuda --out sam-bench-cuda.json
```

If `sam-bench` fails, stop: nothing after it can run (see problem 1 in `KNOWN_ISSUES.md`).

**Per clip** (replace `X` with the clip name; keep each step's console text):

```text
rem 0. Old tracker as the baseline (person target from the rectangle; the CLI has no legs preset), exported BEFORE the SAM views exist
python -m tracker bench X.mp4 --device dml --max-seconds 60 --out X.bench.json
python -m tracker offline X.mp4 --pose --device dml --select-rect SN NX1 NY1 NX2 NY2
python -m tracker export X.mp4 --out X_base.mp4

rem 1. SAM forward pass: everything on, 10 fps sampling
python -m tracker sam-track models\sam-edgetam X.mp4 --rect X1,Y1,X2,Y2 --max-seconds 90 --device dml --preview --posture --reid --camera
rem    open X.mp4 in mpv, press P, watch the overlay once; note errors in table 2b

rem 2. Backward refinement
python -m tracker sam-refine models\sam-edgetam X.mp4.sam.json --plan
python -m tracker sam-refine models\sam-edgetam X.mp4.sam.json --device dml --camera

rem 3. Export (replace x264 with nvenc only after export_check shows nvenc_works true)
python -m tracker export X.mp4 --out X_sam.mp4
python -m tracker export X.mp4 --stabilize --decode auto --out X_sam_stab.mp4
```

Step 0 must run first: `sam-camera` / `sam-refine --camera` REPLACE `X.mp4.views.json`. Look at `X_base.mp4` against `X_sam.mp4` side by side. Run clip C twice (with and without the stranger).

### 2. Results tables (fill in; real numbers only)

**2a. Measurements**

| Clip | Command | Frames | Tracked / lost | fps | Peak VRAM MB | `durum:` line | `re-ID:` line | `kamera:` (occupancy, zoom range, fastest change) | `sam-refine` summary | `doğrulama:` |
|---|---|---|---|---|---|---|---|---|---|---|
| A | sam-track | | | | | | n/a | | | |
| A | sam-refine / export | | | | | | | | | |
| B | sam-track | | | | | | n/a | | | |
| B | sam-refine / export | | | | | | | | | |
| C | sam-track | | | | | | | | | |
| C | sam-refine / export | | | | | | | | | |
| C + stranger | sam-track | | | | | | | | | |

**2b. Observations (what you saw in mpv `P` and in the exported file)**

| Clip | Moment (time) | Expected | Seen | Which constant or module |
|---|---|---|---|---|
| A | desk in front of the legs | mask outline stays on the legs, cyan box does not grow onto the desk | | |
| A | foot wiggle / crossed legs / stretched foot | zoom unchanged | | |
| B | sit -> stand, stand -> sit | posture word flips once each, zoom changes smoothly | | |
| B | walking | cyan box follows both legs and feet | | |
| C | someone passes in front | PARTIALLY_OCCLUDED or TEMPORARILY_LOST, view held, then back | | |
| C | subject leaves and returns | OUT_OF_FRAME -> CANDIDATE -> REACQUIRED (Re-ID), eased-in zoom | | |
| C + stranger | stranger arrives first | `other_person`, camera does not follow them | | |
| all | export | audio in sync, same duration and frame count as the source | | |

**2c. GPU memory** (Windows Task Manager, "Dedicated GPU memory", read while `sam-track` and `sam-refine` run; DirectML has no `nvidia-smi` number): forward peak ___ MB, backward peak ___ MB, limit 6144 MB.

### 3. Definition of done (docs/PROJECT_SPEC.md is not in the upload; the list is the reminder in `Lower body.md`)

Status words: **verified** = proven by a run here or by you on a real clip; **unverified** = code and synthetic tests exist, no real run; **failed** = known not met. Today nothing is verified on a real clip.

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | User can select both legs and feet using one rectangle | **failed** (as stated) | One box works only as `sam-track --rect X1,Y1,X2,Y2` / `sam-preview` (CLI, pixels). mpv right-drag starts `offline --select-rect` (old tracker, `track.lua:1251`), not SAM; `track.lua` only draws `sam.preview.json`. The `legs`/`feet` presets exist (`parts.py`) for the old tracker |
| 2 | AI tracks the combined region | unverified | `sam_track.py` + `lowerbody.py` framing; `test_sam_track` 48, `test_lowerbody` 27, fake graphs. Real EdgeTAM graphs never exported or run (KNOWN_ISSUES 10, 13) |
| 3 | Individual limbs tracked internally | unverified | Per-leg evidence visible/moved/hidden/left_frame, swap repair (`lowerbody.py`, `posture.py`; 27 + 32 tests, synthetic keypoints). Real YOLOv8-pose behind a desk untested |
| 4 | Desk occlusion does not destroy the region | unverified | Desk-mask rejection, hidden-thigh hold 20 s, TrackGate (`posture.py` `DESK_*`, `trackgate.py`; tests incl. "mask jumps onto a desk box"). Thresholds are guesses; a rejected desk mask still stays in SAM memory (KI 17) |
| 5 | Sitting-to-standing transitions work | unverified | `PostureModel` hysteresis + dwell, `test_posture` sit/stand sequences. Frontal camera assumed |
| 6 | Walking movement is tracked | unverified | Standing/walking region + foot-lead cap (`test_lowerbody`, `test_posture`); no real walking clip |
| 7 | Temporary occlusion is handled | unverified | `trackstate.py` 7 states, hold flag, `test_trackstate` 31, `test_camera` hold/ease-in |
| 8 | Same person reacquired after leaving, when evidence permits | unverified | `reentry.py` accept 3 / reject 2 / uncertain 3 s, `test_reentry` 29 with a fake embedder. OSNet x0.25 ImageNet weights on a seated upper-body crop untested (KI 22) |
| 9 | Camera keeps a configurable apparent size | unverified | `lower_fill` 0.70, `kamera:` line, `test_camera` 35. The global `target_fill` stays 0.30 (KI 7, intended) |
| 10 | Foot movements do not cause zoom pumping | unverified | 2 s trimmed mean, start threshold, persistence, rate limit; foot-wiggle, leg-cross, stretched-foot tests. A foot excursion longer than the persistence does change zoom by design (KI 27) |
| 11 | Camera motion is smooth | unverified | Rate limit 0.25 log2/s, pan smoothing; never rendered on a real export (KI 29) |
| 12 | Offline refinement improves uncertain intervals | unverified | `bidir.py` closed/open/mismatch rules, 55 tests + 28 mutation checks. "Improves" can only be judged on a real clip; backward SAM on EdgeTAM untested (KI 31, 32) |
| 13 | Export preserves audio and timing | **verified** on the synthetic clip only | 200 -> 200 frames, audio kept, `doğrulama: tamam` (section 0); `test_export_s13b` 11 + `test_export_check` ran with the sandbox ffmpeg. NVENC and NVDEC never ran on a GPU; `recorder/export.py` still has the `-shortest` frame loss |
| 14 | GPU memory usage remains controlled | unverified | By construction: refine window <= 150 frames at 1024 px, fresh bank per interval, bank slots capped. Nothing measured: `sam-bench` never run, DirectML gives no VRAM number |

Summary: 1 failed, 1 verified (synthetic scope), 12 unverified.

### 4. Top 5 problems and follow-up sessions

| # | Problem | Why it matters | Follow-up |
|---|---|---|---|
| 1 | The whole SAM chain has never touched a real graph, a real clip or the GPU (graphs not exported, memory-graph contract and `export_sam2.py` RoPE rewrite untested, VRAM unmeasured) | Every status above stays "unverified" until this runs; the first run will probably expose a contract mismatch | **F1**: export graphs in CI, run the plan above, fix only what breaks, paste real numbers here |
| 2 | One rectangle in mpv does not reach SAM, and the result is five manual commands that overwrite `views.json` | Item 1 fails; the chain is too fragile for daily use | **F2**: mpv right-drag -> `sam-track --rect`, one `lower-body` command (track, refine, camera, export), no silent overwrite of an `offline-view` result |
| 3 | Wrong-person risk: a rejected stranger can still enter SAM's memory; if the state says TRACKED while SAM sits on the stranger the camera follows them (KI 17, 24, 30) | A camera that follows the wrong person is worse than a static one | **F3**: memory hygiene (drop or quarantine rejected frames), identity check on every tracked frame |
| 4 | `MANUAL_RESELECT_REQUIRED` is only a label: nothing pauses, asks, or lets the user redraw; `reset()` has no UI caller (KI 21) | After a long loss the result stays wrong until a rerun | **F4**: reselect flow (redraw rectangle at time T, resume from there) |
| 5 | About 40 constants are first guesses (posture, state machine, Re-ID thresholds, camera), and OSNet x0.25 is ImageNet-trained, not Re-ID-trained | Defaults will misbehave on the first real clips; with a frontal-camera assumption | **F5**: tune from the table in section 2b, one constant group per commit, keep every change in `DECISIONS.md`; consider a Re-ID-trained model if the stranger test fails |

Smaller items to fold into F1-F5: 3 old ruff findings (`ruff check . --fix` handles `bidir.py`); `recorder/export.py` `-shortest`; `handover.md` test count is stale (now 863 + 1 skipped).

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
