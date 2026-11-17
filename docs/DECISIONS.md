# DECISIONS

## Open decisions

1. **DirectML or CUDA on PC?** Code is ready (Session 1); the choice needs your measurements. DirectML stays the default and CPU stays the fallback until then. See "CUDA setup" and "How to decide" below.
2. **Which SAM graphs on 6 GB VRAM?** EdgeTAM first, SAM 2.1 Small second, Base+ only if needed. No SAM 2.1 Large. Decide after Session 2 numbers.
3. **Target occupancy.** Roadmap says 70% of output height; repo default `target_fill` is 0.30. Decide in Session 11 whether 0.70 becomes the lower-body default or a preset.

## CUDA setup (Session 1)

Facts from the ONNX Runtime CUDA docs (checked 2026-11-17, https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html):

- CUDA needs the `onnxruntime-gpu` package. `onnxruntime-directml` has no CUDA provider. Keep them in **separate virtual environments**; do not install both in one (the docs page does not warn about this, but both packages ship the same `onnxruntime` module, so mixing them is unsupported and the `providers` command warns when it sees more than one).
- cuDNN must be 9.x. A build made with CUDA 12.8 needs CUDA 12.8 or newer; a build made with CUDA 13.0 needs CUDA 13.0 or newer.
- From ONNX Runtime 1.27 the PyPI `onnxruntime-gpu` is built with CUDA 13.0 by default (older versions: 12.8). Separate CUDA 12.x builds exist for 1.27 and later; the page does not give their install command (see the "Install ORT" page).
- `pip install "onnxruntime-gpu[cuda,cudnn]"` also installs the CUDA and cuDNN runtime DLLs through pip, so no manual CUDA toolkit install is needed.
- `onnxruntime.preload_dlls()` (since 1.21) loads those DLLs before the session is created. The app calls it automatically when CUDA is selected (`detector.preload_cuda`). Use `directory=""` yourself only if you test by hand with pip-installed NVIDIA packages.
- Not verified here: which NVIDIA driver version a CUDA 13.0 build needs. Check `nvidia-smi` and update the driver if the CUDA session fails to load. The RTX 3050 (Ampere) is a supported GPU generation for both CUDA 12 and 13, as far as I know.

Setup on Windows (PowerShell, from the repo folder; the DirectML environment is left untouched):

```powershell
py -3.12 -m venv venv-cuda
venv-cuda\Scripts\activate
pip install numpy opencv-python-headless
pip install "onnxruntime-gpu[cuda,cudnn]"
python -m tracker providers --device cuda --model models\yolox_s.onnx
```

Switching without code edits: in a CUDA venv `--device auto` already picks CUDA, because DirectML is not present there. `provider_order` (config) or `TAKIPLI_PROVIDER_ORDER` (environment variable, wins over config) only matters if a build offers both providers; the default `dml,cuda` is unchanged.

## SAM graphs: export and benchmark (Session 2)

The five graphs (`sam-encoder`, `sam-decoder`, `sam-decoder-trk`, `sam-memenc`, `sam-memattn`) are not in the repo. Export EdgeTAM first, then SAM 2.1 Small. Never SAM 2.1 Large (6 GB VRAM). The two model repositories both install a package named `sam2`: one variant per environment.

**Option A, GitHub Actions (no torch on your PC).** Actions tab, workflow "SAM export (PC)", Run workflow, variant `edgetam`; run it again with `small`. Download the artifact `sam-graphs-edgetam` (a zip; the five `.onnx` files are inside) and unzip it into `models\sam-edgetam\` (small: `models\sam-small\`). The script checks every file against PyTorch and stops on a mismatch. If the memory graphs fail, this workflow does not fall back to encoder + decoder only: paste the log of the failed step.

**Option B, a machine with torch (PowerShell, repo folder; a separate venv for each variant):**

```powershell
py -3.11 -m venv venv-export-edgetam
venv-export-edgetam\Scripts\activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install onnx onnxruntime timm
git clone --depth 1 https://github.com/facebookresearch/EdgeTAM.git ..\EdgeTAM
pip install -e ..\EdgeTAM
python scripts\export_sam2.py models\sam-edgetam edgetam
deactivate

py -3.11 -m venv venv-export-sam21
venv-export-sam21\Scripts\activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install onnx onnxruntime timm
pip install git+https://github.com/facebookresearch/sam2.git
python scripts\export_sam2.py models\sam-small small
```

**Benchmark** (in the DirectML environment, then in the CUDA venv from "CUDA setup"; one JSON and one `.md` file per run):

```powershell
python -m tracker sam-bench models\sam-edgetam --device dml  --out sam-edgetam-dml.json
python -m tracker sam-bench models\sam-edgetam --device cuda --out sam-edgetam-cuda.json   # in the CUDA venv
python -m tracker sam-bench models\sam-small   --device dml  --out sam-small-dml.json
```

Paste the table rows (the `.md` file, or the end of the console output) into `TEST_RESULTS.md` under "GPU benchmarks". Also paste the first two lines of the console output so the provider is visible. Read the results like this:

- `FELL BACK` in the notes or a CPU provider in a GPU run: that row is a CPU timing, not a GPU one. Fix the provider first (`python -m tracker providers --model <graph>`).
- Warm-up ms is the first (cold) run: DirectML compiles the graph then. Avg ms is what counts per frame.
- "One tracked frame" in the console output is the sum of the measured averages of encoder + memattn + decoder-trk + memenc, without pre/post-processing. It is the number to compare with the video frame budget.
- Peak VRAM comes from `nvidia-smi` and only exists on CUDA rows (DirectML shows `n/a`). It is the growth of the whole GPU's used memory against the value before the graph was loaded, so close other GPU programs while measuring.
- `--fp16` also measures `models\...\fp16\<graph>.onnx` (fp16 weights, fp32 inputs/outputs). If the folder has no such file, it is made with `pip install onnx onnxconverter-common` in the benchmark environment. A row with `NaN/Inf` or a large "max rel diff vs fp32" is not a usable result, however fast.
- `--runs N` (default 20) and `--warmup N` (default 3) change the sample size.

## SAM engine: rectangle to first mask (Session 3)

Code: `tracker/sam_engine.py` (`SamEngine`: `encode`, `segment_rect`, `first_mask`). It loads only `sam-encoder` and `sam-decoder`; the memory graphs belong to Session 4.

Decisions made here (all reversible; each has a test):

- **Squash resize, no letterbox.** SAM 2 and Android `chw()` stretch the frame to 1024x1024 without keeping the aspect ratio. The engine does the same, so box prompts and mask boxes are plain scaling (`x * 1024 / w`, `x_norm * w`); there is no pad or offset to undo. The Session 3 prompt said "resize/letterbox": the contract and Kotlin reference say squash, so squash wins.
- **Rectangle prompt** = two corners (labels 2 and 3) + a positive point at the rectangle centre (label 1), same as Kotlin `prompt3`. The rectangle is clipped to the frame; a rectangle under 2 px a side is rejected before any graph runs.
- **Candidate rule: highest `iou_predictions` ("best").** The Android tap rule ("smallest candidate within 85% of the best") stays available as `--rule smallest` / `SamEngine(rule="smallest")`. With a box prompt the box already removes the part-versus-whole ambiguity, so "best" is the starting default; compare both on your clips and change the default here if "smallest" frames legs better. Empty masks are never picked.
- **Returns** `FirstMask`: mask logits and bool mask (256x256), box (normalized and frame pixels), `iou`, `object_score` (logit), `obj_ptr` (256), all candidates, plus `image_feat` and `mask_logits` that Session 4 needs for `sam-memenc`. No candidate with a mask gives `None` (the UI will ask the user to redraw).
- Provider selection reuses `sam_bench.open_session` (same DirectML options, CPU fallback). `engine.providers()` reports the provider each graph really got and flags a silent fall-back.

Run on your PC (needs the exported graphs from "SAM graphs"; one image, one rectangle):

```powershell
python -m tracker sam-first models\sam-edgetam kare.png --rect 300,420,900,1000 --device dml --out kare_maske.png
python -m tracker sam-first models\sam-edgetam kare.png --rect 300,420,900,1000 --rule smallest --out kare_maske_small.png
```

`--rect x1,y1,x2,y2` is in pixels of the image (`--norm`: 0-1 fractions). Output: provider and ms of both graphs, the three candidates (iou, area), the chosen mask box, and a PNG with the mask contour (green), mask box (cyan) and your rectangle (yellow). Paste the console text into `TEST_RESULTS.md`; look at the PNG: the contour should follow both legs and feet, and behind a desk it may include the desk (that is handled in Session 8, not here).

## SAM memory loop: forward tracking (Session 4)

Code: `tracker/sam_track.py` (`track_video`, `Clip`, records and `.sam.json` helpers) and four small methods on `SamEngine` (`memory_layout`, `memorize`, `condition`, `decode_track`). Command: `python -m tracker sam-track MODEL_DIR VIDEO --rect x1,y1,x2,y2`.

Decisions made here (all reversible; each has a test):

- **Split.** `SamEngine` only makes single graph calls (and counts their time in `engine.timing`). The frame loop, the `MemoryBank`, the records and the file live in `sam_track.py`, so Session 5 (gate) and Session 12 (backward pass) change the loop without touching the engine. `SamEngine(..., memory=True)` loads the three extra graphs; `sam-first` still loads two.
- **Bank sizes are read from the graph, not hard-coded.** K (memory slots), P (pointer slots) and the shape of one memory frame come from the static input shapes of `sam-memattn`; `sam-memenc`'s output size is checked against it. The existing `MemoryBank` is reused unchanged (slot 0 = prompted frame, slot d = d tracked steps back, empty slots repeat slot 0). Dynamic shapes are rejected with a clear error.
- **Tracked or lost = the Android rule** (`walkMemory`): `object_score > 0`, non-empty mask and `conf >= 0.35`, with `conf = iou x sigmoid(object_score) x (1 if mask area is 0.25-4x the reference area, else 0.5)`. The reference area is the last tracked area (EMA 0.8/0.2, tracked frames only). A test compares these constants with the Kotlin source.
- **Only tracked frames are pushed; lost frames push nothing.** Difference from Android, on purpose: Android also requires a "clean" frame (conf >= 0.6, size ratio 0.6-1.6) before pushing. That is `TrackGate.remember`, Session 5. Until Session 5 every tracked frame entered memory (now gated, `--no-gate` restores it), so a half-hidden subject (desk in front of the legs) can pollute the bank. Expect worse results than Android on desk clips until Session 5.
- **`accepted` is always True** in every record (the gate does not exist yet). `state` carries tracked/lost. Session 5 fills `accepted` and rejected frames stop being pushed.
- **Records go to `<video>.sam.json`**, next to `.track.json` / `.views.json`; their schema is untouched. One row per sampled frame, columns in `fields`: `t, tracked, accepted, x1, y1, x2, y2, iou, object_score, conf, area, ratio` (box normalized, null when the mask is empty). The header holds the video signature (`vsig`, same as A3), start time, normalized rectangle, rule, providers actually used, memory layout, ms per graph call and counts. Writes are atomic. Ctrl+C saves what exists with `"complete": false` (exit code 130). No resume yet.
- **Sampling 10 fps by default** (`--fps`, same as `offline_fps`; Android used 6). `--start S` means the rectangle was drawn at S seconds; earlier frames are skipped (forward pass only, the backward pass is Session 12). `--max-seconds N` stops N seconds after the start.
- **No masks in the file** (size). `track_video(..., keep_masks=True)` returns a 256x256 bool mask per record for Session 6.
- **VRAM peak** is measured only when a graph runs on CUDA (same as `sam-bench`); it is the difference from before the models were loaded. DirectML prints `n/a`.
- **First-frame failure**: no mask from the rectangle raises `NoInitialMask` (exit code 1, nothing written), so the user can redraw.

Run on your PC (needs the five exported graphs; a 30 s clip, rectangle around both legs and feet in the first frame, pixels of the video frame):

```powershell
python -m tracker sam-track models\sam-edgetam klip.mp4 --rect 300,420,900,1000 --max-seconds 30 --device dml
python -m tracker sam-track models\sam-edgetam klip.mp4 --rect 300,420,900,1000 --max-seconds 30 --device cuda   # in the CUDA venv
```

Output: a progress line every 30 frames, then frames / tracked / lost, seconds and frames per second, ms per call and provider for each graph (with "(FELL BACK)" if a graph ran on CPU), peak VRAM, and the path of `klip.mp4.sam.json`. Paste the console text into `TEST_RESULTS.md`. Check by eye that "lost" runs match the moments the legs really are hidden or out of frame (the desk behaviour is not fixed until Sessions 5 and 8).

## TrackGate: gating and jump rejection (Session 5)

Code: `tracker/trackgate.py` (Kotlin `core/TrackGate.kt` port: `remember`, `cosine`, `is_jump`, `size`, `relax`, class `TrackGate` with `learn/note/accept/summary`) wired into `track_video` in `tracker/sam_track.py`. Same order as Android `walkMemory`. CLI: `sam-track ... [--no-gate]` prints `kapı: N kabul, M ret (benzerlik ref ..., K temiz kare)` and the count of tracked-but-not-remembered frames.

Decisions made here (each has a test):

- **Constants copied from Kotlin** (`REMEMBER_CONF` 0.6, ratio 0.6-1.6, `MIN_LEARN` 3, `JUMP_K` 0.75, `RESUME_K` 0.6, `FORCE_CLEAN_FRAMES` 12, relax 12/24/0.5). A test reads `TrackGate.kt` and compares them, so a drift in either file is caught. They were tuned for Android phone clips, not for legs behind a desk (open, see below).
- **Order per frame:** (1) S4 decision (object_score > 0, non-empty mask, conf >= 0.35); (2) gate `accept(dist, max(stable_w, stable_h), lost, sim)` with `sim` = max cosine of the object pointer against the prompted frame's pointer and the last clean frame's pointer; (3) `remember(conf, ratio)` decides whether the frame enters the bank. A gate rejection is a LOST frame (`state` "lost", `accepted` False), pushes nothing and adds to `lost`.
- **`accepted` means "the gate did not reject".** Frames lost by the confidence/object_score check never reach the gate and keep `accepted` True. Only a gate rejection gives `accepted` False.
- **New record fields** (`clean`, `w`, `h`; `.sam.json` schema version 1 -> 2, `gate` block in the header). `clean` = pushed to the bank. `w`,`h` = size for the camera: the last clean size while the mask is under 0.6x the reference area (a leg covered by the desk must not zoom the camera in); `null` on lost frames. The raw mask box stays in `x1..y2`. Session 6/7/11 read these; nothing reads `w`,`h` yet.
- **Learning:** the similarity reference is learned only from frames that are clean, not preceded by a loss and not preceded by an unclean frame (as Android). Until 3 such frames exist, everything passes. So the very first seconds are ungated.
- **`--no-gate` / `use_gate=False`** gives the exact S4 behaviour (every tracked frame is remembered). Use it to compare on the same clip.
- **No change to `sam_engine.py`:** the engine already returns `obj_ptr` and candidate centroids. The Android "reverse fill" of lost spans is Session 12.

Run on your PC (same clip as the Session 4 run, so the two can be compared):

```powershell
python -m tracker sam-track models\sam-edgetam klip.mp4 --rect 300,420,900,1000 --max-seconds 30 --device dml
python -m tracker sam-track models\sam-edgetam klip.mp4 --rect 300,420,900,1000 --max-seconds 30 --device dml --no-gate --out klip.nogate.sam.json
```

Paste both consoles into `TEST_RESULTS.md`. Look at: `kapı ... ret` (rejected frames should be the moments the desk or another person takes over, not the frames where the legs are visible), "belleğe girmeyen" (very high = the thresholds are too strict for legs, lower `REMEMBER_CONF`/ratio in `trackgate.py` and note it here), and whether `lost` grows compared with `--no-gate`.

## Lower-body region: visible vs anatomical (Session 7)

Code: `tracker/lowerbody.py` (pure Python: `LowerBodyModel.update`, `LowerBody`/`Leg`, `Follower`, `pick_pose`, `pose_row`). CLI: `sam-track ... --pose [--pose-model]` (pose every frame, `lower` block in `<video>.sam.json`, `lower` field + framing rectangle in the preview file) and `sam-preview ... --pose`. `track.lua` draws two extra boxes (magenta = anatomical, orange = visible); the cyan rectangle is now the framing. No zoom/camera change (Session 11).

Decisions made here (each has a test in `tests/test_lowerbody.py`):

- **Two regions per frame.** *Visible* = reliable knee/ankle joints of each leg (+ `VIS_PAD` 0.2 L) plus the SAM mask box when the mask is trusted. *Anatomical* = estimated whole lower body: per leg from the hip down to at least `LEG_REACH` 1.0 L (same as `anchored_leg_box`), further down to the lowest visible knee/ankle (+0.15 L), at most `FULL_LEG` 2.0 L; anatomical always contains visible. `L` = torso length (shoulders to hips; one visible hip uses the same-side shoulder; held up to 10 s; fallback shoulder width x 1.2, then 0.45 x person height). No fixed desk height anywhere.
- **A missing landmark is not a missing limb.** A hidden knee/ankle keeps the leg's anatomical box (hip + reach, or the last seen bottom for `HOLD_S` 1.5 s). A missing hip is mirrored from the other hip (signed separation learned when both were seen), else held, else hangs from the shoulder. No pose at all: last region is held 1.5 s (`source` "held"), then `none`. Invented behind-the-desk joints are dropped with the existing `parts._limb_point` rule.
- **SAM mask evidence is clipped**, never trusted raw: ignored under conf 0.5 or when not tracked; top cut at hip line - 0.1 L (torso out), sides at the anatomical region +-1 L (desk sides out), bottom at hip + 2.15 L. This is a first guard; the full desk rule (mask-vs-region overlap) is Session 8.
- **One framing rectangle** (`framing`, the preview's combined `rect`): anatomical region, with the bottom edge limited to `FOOT_LEAD` 0.4 L below the higher foot when both ankles are seen (one stretched foot does not pull it), feet/knees clamped to hip x +- 0.9 L, then per-edge dead zone (6 % of the region size) and 35 % step smoothing. `anatomical` stays the honest estimate; only the framing is stabilised.
- **Left/right identity by continuity.** If both far points (ankle, else knee) jump and the swapped assignment is under 0.6 x the direct cost and the jump is over 0.5 L, the two legs are swapped back (`swapped`, note). Smooth crossings and one-foot jumps are never swapped. Per-leg `evidence` (hip .2, knee .3, ankle .5 of confidence), `hidden`, `held`, `mask_overlap` are debug/support values; nothing steers the camera with them yet.
- **Pose-to-target matching:** `pick_pose` takes the person whose box (extended 1.2 x its height downward, because a seated person's box stops at the desk) covers most of the SAM box; ties and lost-mask frames use distance to the last centre. Without `--pose` nothing changes (S6 behaviour, no `lower` block).
- **Record format:** `.sam.json` gets an optional top-level `lower` = `{fields, rows}` (one row per record, `ROW_FIELDS`); `FIELDS`/schema version 2 untouched, `load_doc` unchanged. Preview file stays `v: 1` with an added `lower` object.

Run on your PC (needs the exported graphs and `models/yolov8s-pose.onnx`):

```powershell
python -m tracker sam-preview models\sam-edgetam klip.mp4 --rect X1,Y1,X2,Y2 --device dml --pose
python -m tracker sam-track models\sam-edgetam klip.mp4 --rect X1,Y1,X2,Y2 --max-seconds 30 --device dml --preview --pose
```

Open the clip in mpv and press `P`. Check: seated behind the desk, the magenta box reaches about one torso below the hips and the orange box appears only when shins/feet show; cyan stays calm while a foot wiggles, one foot is stretched, or the legs cross; a hidden leg keeps its half of the region. Note in `TEST_RESULTS.md` the pose cost per frame (fps of `sam-track` with and without `--pose`) and any frame where the cyan rectangle chases a foot or swallows the desk. Tunable constants are at the top of `lowerbody.py`.

## Posture, desk occlusion, sit↔stand (Session 8)

Code: `tracker/posture.py` (pure Python: `PostureModel.update`, `PostureFrame`, `desk_like`, `follower()`). CLI: `sam-track ... --posture` (implies pose; `--pose` alone behaves exactly as in Session 7). The `posture` block in `<video>.sam.json` (`posture.ROW_FIELDS`, one row per record) and the posture word in the mpv label (`track.lua`, after the confidence) are new; the preview file gets `lower.posture`, `lower.thigh`, `lower.leg_status`, `lower.desk_mask`, `lower.blend` and the cyan rectangle is now the posture-aware framing. `sam-preview` is untouched (one frame has no posture history). No zoom/camera change (Session 11).

Decisions made here (each has a test in `tests/test_posture.py`):

- **A layer on S7, not a rewrite.** `PostureModel` owns a `LowerBodyModel` and has the same `update(...)` signature, so `Follower` takes it unchanged. S7's visible/anatomical/left-right output is passed through untouched (a test compares the two models frame by frame); only the framing is replaced. S7's own `framing` stays in `lower.framing`.
- **Posture score** (0 = seated, 1 = standing, exponential smoothing `TAU_S` 0.35 s) from torso-length units: knee drop below the hips (`THIGH_LO/HI` .45/.75 L; a seated person facing the camera has foreshortened thighs), ankle drop (`REACH_LO/HI` 1.3/1.6 L) and visible/anatomical height (`COV_LO/HI`, weight only .1 because it is high for a seated person with visible shins). Weights .5/.3/.1; with hips hidden the hip line is shoulders + L and the observation counts 0.7.
- **Hysteresis + dwell.** SEATED leaves at score >= .45, STANDING at <= .55 (into TRANSITION); TRANSITION settles to STANDING at >= .72 or SEATED at <= .28 only after `SETTLE_S` 0.4 s beyond the threshold. `direction` = `standing_up` / `sitting_down` from where TRANSITION was entered. No evidence = the posture is held, `unknown` before the first evidence.
- **Hidden legs are weak evidence, a frame-cut leg is none.** Hips/shoulders visible, no reliable knee/ankle and the anatomical region NOT reaching the frame bottom (`EDGE_BOTTOM` .99) = a weak "seated behind the desk" observation (score .15, weight .25, about 2-3 s to flip a standing person). If the region reaches the bottom edge the legs are cut by the frame, not hidden, and nothing is observed.
- **Per-leg status** (`legs`): `visible`, `moved` (a reliable ankle/knee jumped >= .35 L since the last observation), `hidden` (person present, joints missing, not leaving), `left_frame` (last point at/near the left/right/bottom edge and not moving inward, or extrapolated outside the frame, or the leg box is cut by the frame bottom), `unknown` (no person). Left/right use S7's swap decision, so crossing legs are not "moved".
- **Desk rule, no fixed height.** Before S7 sees a SAM mask (tracked, conf >= .5) it is judged against the previous anatomical region: width >= 2.0 x that width (or a flat, wide box) AND less than .45 of the mask inside the region -> `desk_mask`, mask not used as evidence (while standing the overlap limit is .25, because a stride widens the mask); width >= 4.5 torso lengths is always rejected. The first frame has no torso length yet, so it is not checked. Only the evidence is dropped: SAM's memory stays the business of the Session 5 gate.
- **Seated region.** `thigh` = the hidden upper-leg box from the hip line down by the last measured knee drop (default .45 L, held while knees are not seen). The visible shin/foot box is stored relative to the hips and re-anchored every frame, so it is kept for `SEATED_HOLD_S` 20 s while the desk hides the legs (S7 alone collapses to 1 L after 1.5 s). The region is held for 20 s through pose dropouts, then dropped.
- **Standing/walking region** = anatomical united with visible, short hold (S7's 1.5 s). The seated and standing regions are mixed by `blend` (target 0 seated, 1 standing, the score while in TRANSITION), limited to `BLEND_RATE` 1.5 per second, then the S7 foot-lead cap (.4 L), dead zone and 35 % smoothing. A lifted foot or a foot wiggle moves the bottom edge by less than .03 of the frame in the tests.

Run on your PC (needs the exported graphs and `models/yolov8s-pose.onnx`):

```powershell
python -m tracker sam-track models\sam-edgetam klip.mp4 --rect X1,Y1,X2,Y2 --max-seconds 30 --device dml --preview --posture
```

Open the clip in mpv and press `P`. Check: the label ends with `seated` while the person sits behind the desk and does not flicker; standing up shows `transition` for about a second, then `standing`; the cyan rectangle follows the feet smoothly (no jump) and keeps covering the hidden legs behind the desk; a wide desk mask never makes the magenta/cyan boxes wider (`lower.desk_mask` true in the preview file for those frames). Constants (`THIGH_*`, `REACH_*`, `ENTER_*`, `DESK_*`, `SEATED_HOLD_S`) are first guesses, not tuned on a real clip; note which one looks wrong here.

## How to decide (Session 1 and 2)

1. In the DirectML environment: `python -m tracker providers --device dml --model models\yolox_s.onnx` and `python -m tracker pose-bench VIDEO --model models\yolov8s-pose.onnx --device dml`.
2. In the CUDA venv: the same two commands with `--device cuda`.
3. Paste both outputs into `TEST_RESULTS.md`. Look for `fell_back`/"sağlayıcı yüklenemedi" warnings first: a silent CPU fallback makes any timing meaningless.
4. Re-compare with the SAM graphs (Session 2: `sam-bench`, see "SAM graphs" above). Pick the provider that wins on the SAM graphs, since those are the heavy ones. Record the choice here under "Decided".

## Decided

- Edited files are delivered as a zip containing only changed files, with the original folder structure kept (user preference). This replaces the `handover.md` rule "zip the whole project" for this work.
- One task per Claude session; stop at a clean checkpoint.
- Offline-first. Live tracking is not a requirement.
- Primary target = one combined region for both legs and both feet; left/right limbs are tracked internally as evidence.
