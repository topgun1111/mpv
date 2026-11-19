# PC integration audit and patch report

Date: 2026-11-19
Source: uploaded `mpv.zip` (Takipli Oynat project)

## Changes made

- Changed live skeleton activation so that, when the pose model is available and live tracking is enabled, the 17-point COCO skeleton is displayed automatically. The existing `J` key still toggles it. This is independent of the selected body-part preset.
- Clarified that SAM produces segmentation masks and the separate pose model produces anatomical keypoints. SAM alone cannot produce a skeleton.
- Updated `PC_MODEL_SELECTION.md` with the automatic-skeleton behavior and its model dependency.

## Verified in this environment

- Python compile check: `python -m compileall -q tracker scripts recorder` passed.
- Focused integration tests: 105 passed in 9.44 seconds, covering skeleton serialization, SAM live integration/tracking/engine, and mpv Lua tracker/offline/menu/panel harnesses.

## Not verified / blockers in the uploaded archive

- Full pytest suite did not complete within the 15-minute execution limit in this environment. It progressed through roughly one third of the suite before timing out; this is not a test failure result.
- This archive does not contain `mpv/mpv.exe`, bundled `python/python.exe`, person detector ONNX weights, pose ONNX weights, or the five SAM ONNX graphs. Therefore the Windows desktop app cannot be launched end-to-end from this archive alone.
- Windows-specific IPC, DirectML/CUDA provider selection, actual GPU inference, model loading, real-video tracking, and mpv overlay rendering need to be tested on the target Windows PC.
- The live SAM path is already wired: rectangle selection emits `track-rect`; `LiveController` uses `sam_live.make_factory`; the factory selects SAM when all required selected-model ONNX files exist and falls back to the legacy point tracker otherwise. The F2 comment and implementation confirm this path.
- SAM model selection is persisted in config and used by the SAM engine factory. The selected SAM variant does not replace the default YOLO/ByteTrack detector.
- Skeleton display depends on the pose ONNX model being installed and loadable. With no pose model, the app intentionally continues without skeleton rendering.
- The standard Windows launchers explicitly require a writable `E:\Tracking` directory; this remains an installation prerequisite.

## Windows acceptance checklist

1. Install/extract the complete Windows package including mpv, Python runtime, detector/pose models, and the selected SAM model graph set.
2. Ensure `E:\Tracking` exists and is writable, or intentionally revise the launcher data-directory setting for the target PC.
3. Start with `launcher\Baslat.bat`; confirm the tracker console reports successful IPC connection and the intended ONNX execution provider.
4. Confirm pose model load succeeds, enable live tracking, and verify the skeleton appears automatically; press `J` to hide/show.
5. Select a rectangle with right-button drag; verify SAM is loaded (not silently falling back), masks/boxes track across frames, and logs show no model/provider errors.
6. Repeat with both EdgeTAM and SAM 2.1 Small if both graph sets are installed.
7. Test a real clip, occlusion, target leaving/re-entering frame, resolution changes, and export.

## Overall

The code-level PC integration for SAM and the mpv rectangle-selection path is present in this uploaded revision. Automatic skeleton display has been patched. The project is not yet certifiable as fully working on a PC because the archive lacks the runtime binaries/model weights and this environment cannot exercise Windows mpv, hardware acceleration, or real footage.
