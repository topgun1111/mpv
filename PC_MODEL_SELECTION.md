# PC SAM model selection

The Windows/PC Tracker panel now contains an **AI MODEL SELECTION · SAM** section.
Open the Tracker panel with `L` or the top-bar **Tracker** item, then choose **EdgeTAM** or **SAM 2.1 Small**. The selected family is persisted in `%APPDATA%/TakipliOynat/config.json` as `sam_model_variant`.

The panel checks for all five required ONNX graphs in these locations:

- `sam-models/edgetam/`
- `sam-models/small/`

Required files: `sam-encoder.onnx`, `sam-decoder.onnx`, `sam-decoder-trk.onnx`, `sam-memenc.onnx`, and `sam-memattn.onnx`.

When `model_dir` is omitted, the PC SAM commands use the selected directory automatically: `sam-bench`, `sam-first`, `sam-preview`, `sam-track`, and `sam-refine`. Existing explicit-directory command syntax remains supported.

The selection applies to SAM prompt-driven segmentation/tracking workflows. It does **not** replace the application's default YOLO/ByteTrack live detector; that pipeline remains unchanged when this setting is changed. GPU/Execution Provider selection remains in the existing **Ekran Kartı** section.

To populate the folders, download the matching `sam-models-edgetam` and/or `sam-models-small` GitHub Actions artifacts and extract each artifact's ONNX files into the corresponding directory above.


## Automatic live skeleton display

When the pose ONNX model is installed and the live tracker is enabled, the 17-point COCO
skeleton is now sent to mpv automatically. Press `J` to hide/show it. This is independent
of the selected tracking target and of SAM segmentation: SAM supplies masks, while the
pose model supplies anatomical keypoints. If the pose model is absent or fails to load,
skeleton display remains unavailable and the tracker continues without it.
