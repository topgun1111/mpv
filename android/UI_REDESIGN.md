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
