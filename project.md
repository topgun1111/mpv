# project.md — Takipli Oynat: Roadmap (post Part 22)

Goal: track + zoom on people and their body parts simultaneously, never losing focus. Personal use (AGPL OK).
Baseline (see handover.md): ByteTrack + YOLOX/YOLOv8 person detector, Kalman + lookahead, zero-phase offline smoothing, WorldPointTracker (camera-motion compensated), OSNet re-ID code (no weights), team/jersey code, YOLOv8s-pose single-keypoint tracker (live only).

## Audit: earlier recommendations vs. actual code
| Recommendation | Status in code | Verdict |
|---|---|---|
| Offline two-pass smoothing | `smooth_zero_phase` + bidirectional gap fill in `offline.py` | DONE — drop; only tune on real footage |
| Camera-motion compensation | `WorldPointTracker` (LK + RANSAC affine) — only for point/rect tracking, NOT in ByteTrack/player path or offline | PARTIAL — port GMC into ByteTrack predict step + offline |
| Better detector | YOLOX-S + YOLOv8n; pose model already finds persons | CHANGE — use one pose model (YOLO11m-pose) for boxes + keypoints, single inference |
| Re-ID | `reid.py` complete, no weights shipped | KEEP — export OSNet in CI (`scripts/export_reid.py`) |
| Follow-cam MP4 export | absent | KEEP, top priority |
| Click-to-track via SAM 2 | absent | DEMOTE — heavy, DirectML unproven; body-part goal is better served by pose |
| Ball/object classes | absent | LATER |
| Multi-target / group framing | single target only | PROMOTE — needed for "people + parts at once" |
| Shot-cut detection | absent | KEEP, cheap |
| Heatmaps/stats | absent | LAST (needs homography) |
| Top menu bar (new request) | only on-screen panel (Part 16) + hotkeys; `track.lua` 697 lines | NEW — Parts M1–M4 |
| Open video with point → auto offline scan (new request) | `offline` CLI + `o` key exist; no auto-switch | NEW — Parts A1–A2 |

## Gaps vs. goal (found in code)
- `KeypointTracker` is live-only; `offline.py`/`track.json` have no keypoints → no lookahead/zero-phase on parts.
- Keypoint tracker re-runs full-frame pose every step and re-associates by IoU/centre only → ID swaps in crowds; not bound to ByteTrack ID or OSNet gallery.
- Part lost when conf < `kp_min_conf` → immediate "lost" instead of inferring from neighbours or falling back to person box.
- COCO-17 has no hands, face parts, toes → "body parts" limited to wrists/ankles/etc.
- Keypoints smoothed only by view EMA; raw keypoint jitter (±several px) feeds the camera.
- Nothing validated on real footage/mpv/Windows. Biggest risk.

- No discoverable UI: features live behind hotkeys (t, r, x, o, ctrl+…) and a hidden panel → every new feature needs a menu entry first.

## Session sizing (free Claude, weekday sessions)
- 1 part = 1 session: ≤3–4 files touched, ≤~300 changed lines, tests included, handover.md updated, full zip delivered.
- Each part is independently shippable; none leaves the app broken. Features not yet built show disabled (greyed) in the menu.
- Pure-Python parts first (testable on Linux CI); Lua parts kept small, with logic pushed to testable Python where possible.
- Never start a part you can't finish: if tokens run low, stop at the last green test and note it in handover.md.

## Design decisions
- **Menu bar**: drawn in `track.lua` with mpv ASS overlay (reuse Part 16 panel hit-testing/rect code); no new dependency, works inside the portable mpv. Auto-hides; appears on mouse at top edge or `Alt`/`F10`; large touch-friendly targets option. Menu model is a data table (`menu.lua`) so items/shortcuts/state are declarative. Fallback if too painful: bundle `uosc` (MIT) and register our items through its menu API.
- **Open dialog**: mpv has no native file dialog → `track.lua` runs `powershell.exe -STA` (WinForms OpenFileDialog/FolderBrowserDialog/ListBox, VB InputBox for URL) via async `subprocess`, stdout = chosen path → `loadfile`. (tkinter is NOT in the embeddable Python.) Reuse the same approach for "Save view…", "Export…" (SaveFileDialog).
- **Hybrid tracking** (open with point): start live tracking immediately; in parallel a background offline scan (`offline.py`) runs; when scan covers current time and live quality is worse, switch to precomputed views seamlessly.
- **Quality score** (live vs. offline): lost-frame %, view jitter, ID switches, live lag; sampled over a sliding window.

## Parts
Status: P23, M1, M2 done → next M3.

### Foundation
- **P23 — Bench harness** ✅ (`tracker/bench.py`; real-clip runs pending on Windows): `python -m tracker bench video.mp4` → ID switches, lost %, jitter px/s, fps, latency, JSON report. Run on 2–3 real clips; fix first real-world breakages (pose `[1,56,N]` layout, DirectML fp16, `complex` mouse bindings). Output feeds A2's quality score.

### Menu bar (M)
- **M1 — Menu engine + bar shell** ✅ (`script-modules/trackmenu.lua`; real mpv run pending): declarative menu table, top bar (File · View · Tracking · Tools · Settings · Help), hover/click/dropdown, auto-hide, keyboard nav (F10, arrows, Esc), enabled/checked state, shortcut hints. Wire existing actions only (toggle, reset, release, offline, HUD, panel). Python test for menu table/state; Lua harness test for hit-testing.
- **M2 — File menu** ✅ (`script-modules/trackfiles.lua`; real Windows run pending): Open video, Open recent, Open folder/URL, Close, Save/Load view snapshot (`<video>.view.json`, static zoom/pan/rotate — NOT the per-frame `.views.json`), Export (greyed until E1), Exit. Remembers last dir. Dialogs = PowerShell+WinForms, not tkinter (embeddable Python ships no tkinter).
- **M3 — View + Tracking menus**: View: zoom presets, fill %, fit/fill/original, fullscreen, always-on-top, HUD on/off, overlay toggles (box, dot, IDs, trails — greyed until built). Tracking: mode submenu (Off · Click object · Rectangle · Player ID · Body part · Auto-scan), target actions (release, switch, lock), lookahead/smoothing sliders as stepper items.
- **M4 — Tools + Settings + Help**: Tools: run offline scan now, cancel scan, bench, open models folder, check models. Settings dialog (stepper list for `Config` keys, Save/Reset → `settings.json`), device (auto/dml/cuda/cpu), live fps, model selection. Help: shortcuts list, about, version, licences. Status bar line (mode · fps · device · scan progress).

### Open-with-point + auto-scan (A)
- **A1 — Open with point & background scan**: CLI/menu "Open video with target…": pick video → first frame shown paused → user right-click/drag selects target → start live immediately and spawn `offline` scan in a background process (progress in status bar, resumable, writes `.track.json`). Target stored as `(t, point/rect)` and resolved to ID/part when scan reaches it.
- **A2 — Auto-switch to precomputed**: sliding-window quality score (from P23 metrics); if live is worse than offline-derived views (or live fps < budget) → switch to offline views with eased handover, OSD "Using scanned track"; manual override in Tracking menu (Live / Scanned / Auto). Seek handling: live while scan hasn't reached `t`.
- **A3 — Scan cache**: hash(video path+size+mtime+model) → reuse tracks on reopen; "Rescan" menu item; scan-ahead throttling when playback is running.

### Body parts (B) — pose in offline + robustness
- **B1 — Pose in offline pipeline (schema v2)**: per-ID keypoints in `track.json` (`"kp"`), v1 reader kept; part target `{id, part}`; zero-phase smoothing + gap fill per keypoint → `views`.
- **B2 — Robust part tracking**: bind part to ByteTrack ID; pose↔track association by keypoint-in-box; One-Euro filter per keypoint; occlusion fallback chain (parent joint + limb ratio → person sub-box → person → zoom-out).
- **B3 — Part presets + menu**: head/torso/arms/legs/feet/hands keypoint-group boxes; Tracking → Body part submenu; hotkey cycle; part switch without re-scan.

### Multi-target (T)
- **T1 — Target set + union framing**: N persons/parts, priority weights, min-zoom cap; zoom hysteresis. Menu: Tracking → Add/remove target.
- **T2 — Group/ball modes**: group centre; ball + nearest players (ball model from O1).

### Output (E)
- **E1 — Follow-cam export**: `export` CLI + File → Export: per-frame crop/scale from `views.json`, ffmpeg pipe (`libx264 -crf 18 -preset veryfast`), original audio mux, VFR-safe pts, progress bar in status.
- **E2 — Export options**: output size/aspect (16:9, 9:16), burn-in overlays, picture-in-picture of full frame, batch queue.

### Engine upgrades (G)
- **G1 — Camera-motion compensation in tracker**: extract GMC to `tracker/gmc.py`; use in ByteTrack prediction + offline.
- **G2 — Single pose-detector**: YOLO11m-pose replaces separate person detector when pose present; fp16/DirectML benchmark vs v8s-pose.
- **G3 — Re-ID weights**: `export_reid.py` (OSNet ONNX) in CI, model checksums, wire gallery into B2 recovery.
- **G4 — Shot-cut detection**: histogram/edge diff + LK inlier collapse → reset + re-acquire (re-ID/pose); cuts logged in `track.json`.

### Later (O)
- **O1 — Objects & ball**: class selector (sports ball, car, animals); small-ball tiled/fine-tuned model.
- **O2 — Whole-body pose**: RTMPose-wholebody (hands, face, toes) on selected crops; presets extend.
- **O3 — Overlays & stats**: trails, all-ID labels, team boxes; pitch homography → heatmap/distance/speed.
- **Parked**: SAM 2 click-to-track (check DirectML/ONNX viability first).

## Cross-cutting rules
- Every part: synthetic tests + (once P23 exists) one real-clip bench line in handover.md.
- New feature = menu item (greyed until implemented) + config key with conservative default.
- Live fps budget: pose/re-ID only on selected targets or every N frames; interpolate between.
- No new heavy dependency without CI pruning check.

## Suggested order (≈1 part per weekday session)
P23 → M1 → M2 → M3 → A1 → A2 → M4 → B1 → B2 → E1 → B3 → T1 → G1 → A3 → G2 → G3 → G4 → E2 → T2 → O1 → O2 → O3
