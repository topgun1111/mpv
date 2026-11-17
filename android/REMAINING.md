# Android UI redesign: what's left

Read `android/UI_REDESIGN.md` and the tail of `handover.md` first. Do one item per session. Work only on files under `android/`.

## Status

| Area | File | State |
|---|---|---|
| Tracking screen: Clip range / Selection / Advanced sections | `app/PickScreen.kt` | Done, **not compiled** |
| Tracking screen: sticky Scan bar | `app/PickScreen.kt` | Done, **not compiled** (the restructuring is the riskiest edit) |
| Tracking screen: two-pane landscape, one-line hint, progress + Cancel in the sticky bar | `app/PickScreen.kt`, `PreviewSize.kt` | Done (part 7), **not compiled**; the layout was rebuilt from four local `@Composable` blocks, so it is the next riskiest edit |
| Manual camera: always-visible speed card, adaptive viewport | `app/RecordScreen.kt` | Done, **not compiled** |
| Standalone recorder: same change | `rec/RecScreen.kt` | Done, **not compiled** |
| Results: adaptive viewport, duplicate-line fix | `app/ResultScreen.kt` | Partial, **not compiled** |
| Home dashboard | `app/MainActivity.kt` | First pass from an earlier session; not re-audited |

## 0. Build verification (first)

There was no Android SDK in the previous sessions, so none of the changes above has been built. Run from `android/`:

```bash
gradle :core:test :app:assemblePoseDebug :app:assembleSamDebug :rec:assembleDebug
```

If something fails, fix the compile errors in the parts above before starting new work. The likeliest places are:

- `PickScreen.kt`: the `startScan()` function and the extra `Column` level.
- `PickScreen.kt`, `RecordScreen.kt`, `RecScreen.kt`, `ResultScreen.kt`: the `import androidx.compose.ui.unit.coerceIn` added for the viewport height.
- `PickSection`, the new private composable at the bottom of `PickScreen.kt`.

## 1. Tracking screen: remaining work (`PickScreen.kt`)

Done in part 7 (not compiled): landscape / wide two-pane layout, one-line hint, progress + Cancel in the sticky bar. Mode icons skipped on purpose: the project has no icon library (no `material-icons` dependency), and the brief says no new dependencies.

- Check on a narrow phone (360 dp wide), a foldable and landscape (device only).
- Possible compile trouble: the four local blocks `headerBlock` / `videoBlock` / `controlsBlock` / `statusBlock` (`@Composable () -> Unit` vals) and `previewModifier(aspect, heightFrac)`.
- Two-pane is used only when a frame is showing (`twoPane = showPick && (landscape || width >= 600 dp)`); before a video is picked, and while scanning or on the Done / Cancelled screens, the layout is single-pane.
- Scroll state of the panes resets when the layout switches between one and two panes (rotation does this anyway).

## 2. Results screen (`ResultScreen.kt`)

- Move Play, the seek slider and the volume row into one compact transport bar under the preview.
- Make the Save and Export buttons sticky or easy to reach from every tab.
- Replace the tab labels with shorter ones if they overflow on a 360 dp screen.
- Leave the tuning code, the manual recording, `rebuild` and `startExport` untouched.

## 3. Shared design system

- Create `app/ui/Components.kt`.
- Move `PickSection` there and make it internal.
- Add a shared speed card, because `RecordScreen.kt` and `RecScreen.kt` currently duplicate it. The `rec` module is separate, so decide whether to duplicate a small copy there or add a shared module; do not add a dependency.
- Add a mode selector and a section header, and use them from the other screens.

## 4. Secondary screens (not audited yet)

Open each file, list its controls, group them into sections and add a bottom action bar where it helps:

- `ScanScreen.kt`
- `BenchScreen.kt`, plus `SamBenchSection.kt`
- `DecodeScreen.kt`
- `UpdateScreen.kt`
- `MainActivity.kt`: check the dashboard, and consider a recent-videos list only if the code already stores them

## 5. Regression checklist (on a device or emulator)

1. Open the tracking screen and open every mode. Repeat in landscape (video left, controls right).
2. Select a video and rotate it.
3. Pinch-zoom and drag the preview.
4. Scroll while the video is visible.
5. Switch modes and check that only that mode's controls show.
6. Pick body parts or points.
7. Draw freehand and a rectangle, with undo and clear.
8. Expand and collapse Advanced.
9. Start a scan, cancel it, resume it, and export a partial result.
10. Open manual recording and play, zoom and drag.
11. Change the recording speed and check that playback speed really changes.
12. Check the recording controls on a small screen.
13. Open the results screen and use every tab.
14. Navigate back from every screen.

## Not changed on purpose

The tracking, pose and SAM code, the scan service and the export pipeline were not touched. The SAM and Pose build configurations were not touched either.
