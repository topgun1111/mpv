# Android UI redesign (first implementation pass)

Scope: Android modules only. The desktop/Windows UI, tracking algorithms, model loading, scan service, export pipeline, and core geometry were left unchanged.

## What changed

- **Main app dashboard (`app/MainActivity.kt`)**: replaced the long vertical mode list with a compact 2x2 mode grid, a single primary start card, and a grouped tools panel. Mode cards use tighter spacing and clearer visual hierarchy.
- **Tracking setup (`app/PickScreen.kt`)**: made the header compact, retained the four mode chips as the primary mode selector, grouped runtime/model capability information into one status card, and made video selection full-width.
- **Manual camera inside the main app (`app/RecordScreen.kt`)**: increased the preview workspace, simplified the header, moved record/export actions directly below playback, and collapsed volume/speed into an Advanced controls panel.
- **Standalone Record app (`rec/RecScreen.kt`)**: retained its immersive full-screen recording mode, redesigned the normal page around a larger video workspace, compact transport controls and primary record/export actions, and moved rotation/audio/speed controls into a collapsible Advanced controls panel.

## Build verification

A local Android build could not be run in this environment because the `gradle` executable and Gradle wrapper are not present. The source changes were checked for balanced braces/parentheses, but this is not a substitute for Gradle compilation. Run from `android/`:

```bash
gradle :core:test :app:assemblePoseDebug :app:assembleSamDebug :rec:assembleDebug
```

## Follow-up polish

The tracking selection screen still contains several mode-dependent settings in one scrollable workflow. The next UI pass should convert those into clearly separated Selection, Clip range, and Advanced sections, and test the layout on narrow phones, foldables, and landscape orientation.

## Part 2 — PickScreen sections (not compiled)

- `PickScreen.kt`: new private `PickSection` card. Controls are grouped into **Clip range** (seek, ±step, A/B), **Selection** (mode-specific: body parts / multi-point + keep-distance / freehand+rect undo-clear) and **Advanced** (collapsed by default; now also holds the version/SAM/pose status card, so the preview moves up the screen).
- Rotation buttons moved from above the preview to directly below it (next to zoom controls).
- Strings added: `pick_sec_clip`, `pick_sec_select` (en + tr, `strings_cam.xml`).
- Still open: sticky Scan bar, Home/Result/Rec screens from the brief, landscape two-pane layout. No Android SDK was available here, so nothing was built; run the Gradle command above.

## Part 3 — RecordScreen (not compiled)

- Preview viewport height is now 50 % of the window (220–560 dp) instead of a fixed 340 dp; the page still scrolls, so controls stay reachable.
- Playback-speed slider, value readout and presets are always visible (was hidden in the collapsed panel). Same `applySpeed` / `PlaybackParameters` path as before. The collapsed panel is now "Audio" only.

## Part 4 — standalone recorder (`rec/RecScreen.kt`, not compiled)

Same change as RecordScreen: speed slider + presets always visible in their own card; viewport 50 % of window height (220–560 dp); collapsed panel is now "Rotate & audio". The immersive full-screen overlay (speed button cycling presets) is untouched.

## Part 5 — ResultScreen (not compiled)

- Preview viewport is 45 % of window height (220–520 dp) instead of fixed 300 dp; page still scrolls to the Target / Camera / Manual / Export tabs.
- Removed a duplicated `saved` message line. Tabs, tuning sliders, recording, speed and export code are unchanged.
- Still open: sticky Scan button + landscape on PickScreen, Home dashboard check, Scan/Bench/Decode/Update screens.

## Part 6 — sticky Scan bar (PickScreen, not compiled)

- Scan / Resume-after-loss is now a bottom bar outside the scrolling area, always visible once a video frame is loaded. Its click body was moved unchanged into a local `startScan()` (only `return@Button` → `return`); enable conditions are identical.
- Cancel / partial export / resume still live in the status area (`ScanUi.*`) that scrolls with the page, unchanged.
