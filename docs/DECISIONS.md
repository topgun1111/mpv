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
- **Only tracked frames are pushed; lost frames push nothing.** Difference from Android, on purpose: Android also requires a "clean" frame (conf >= 0.6, size ratio 0.6-1.6) before pushing. That is `TrackGate.remember`, Session 5. Until then every tracked frame enters memory, so a half-hidden subject (desk in front of the legs) can pollute the bank. Expect worse results than Android on desk clips until Session 5.
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
