# Takipli Oynat — Native Windows

Native Qt 6 / OpenCV desktop video tracking application, no Python runtime. It opens videos, detects people, draws bounding boxes and YOLO pose skeletons, selects a person, follows them with a smoothed virtual camera, previews the cropped video, and exports MP4 video. A fallback OpenCV HOG detector works without a downloaded model but is unreliable for seated people and does **not** produce a skeleton.

## Build (Windows 11, Visual Studio 2022)

Install CMake, Visual Studio C++ tools, and vcpkg. In this directory:

```powershell
cmake -S . -B build -G "Visual Studio 17 2022" -A x64 -DCMAKE_TOOLCHAIN_FILE="C:/vcpkg/scripts/buildsystems/vcpkg.cmake"
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
```

The `vcpkg.json` manifest installs Qt Widgets and OpenCV. The initial dependency build can take a long time. The GitHub Actions workflow builds the executable but does not yet deploy its DLLs, so the executable artifact is **not portable** by itself.

## Model

For skeleton detection load a compatible **YOLOv8-pose or YOLO11-pose ONNX model** exported with fixed 640×640 input and 17 COCO keypoints. Expected output: float32 `[1,56,N]` or `[1,N,56]`. Models with different outputs are rejected and logged. ONNX inference uses OpenCV CPU by default for reliability; **CUDA acceleration is not implemented**. A model is not included; supply one you have the right to use.

## Workflow

Open video → optionally load pose ONNX → Play → click a person in the processed preview → adjust target occupancy → Export MP4. Export reprocesses the entire source from the beginning and automatically selects the largest detected person; it does not persist a manual click made during preview. The exported file contains video only (no audio). Export uses the `mp4v` codec and is written to a temporary `.partial.mp4` file before renaming.

## Extensive diagnostics

Each launch creates a timestamped log at `%LOCALAPPDATA%/TakipliOynatNative/logs/` (actual Qt application-data path may include organization naming). Logs record Qt/OpenCV versions, OS, file paths, video FPS/resolution/frame counts, model load failures, detection/tracking state every 60 preview frames, every 30 export frames, export progress, errors and exit codes. GitHub Actions uploads a diagnostics artifact on every run, including failures. Logs may include sensitive local file paths: review before sharing.

## Known limitations

This is an integrated implementation but has **not been compiled or exercised on Windows in the authoring environment**. The exported video currently omits audio. The HOG fallback is weak on seated or partly occluded people. Automatic reacquisition after long occlusion can switch subjects. Selecting a person in preview does not transfer that selection to export. GPU inference, user-selected limb tracking, speed adjustment, video scrubbing, and bundled runtime DLL packaging remain unimplemented. Do not mistake the availability of source code for a verified production build.
