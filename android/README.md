# Takipli Oynat — Android

Android version of the PC tracking follow-cam, in the same repo. Plan and status: `../handover-android.md`.

| Module | What |
|---|---|
| `core/` | Pure Kotlin (no Android imports): geometry, formats, ByteTrack, view building. Tested on plain JVM. |
| `app/` | Android app (Compose UI, decode, ONNX Runtime, export). |

## Build

CI (`.github/workflows/build-all.yml` starts `android.yml`, next to the PC builds) runs on every push and uses Gradle 8.14.3 directly, so no Gradle wrapper
is committed. Locally:

```
cd android
gradle :core:test :app:assemblePoseDebug     # APK: app/build/outputs/apk/pose/debug/app-pose-debug.apk
gradle :app:assembleSamDebug                # SAM build (applicationId com.takipli.oynat.sam): app-sam-debug.apk
```

Needs JDK 17+ and the Android SDK (platform 36). To get a local wrapper once: `gradle wrapper --gradle-version 8.14.3`
(then commit `gradlew`, `gradlew.bat`, `gradle/wrapper/*`).

`VERSION` at the repo root is shared with the PC app (`versionName`; `versionCode = major*10000 + minor*100 + patch`).
Only the phone ABI `arm64-v8a` is built.

## Pose benchmark (Parts 5-6, CPU and NPU)

Home → "Pose benchmark (CPU)". Models come from `app/src/<flavor>/assets/models/*.onnx` (`pose` or `sam`; CI exports them; the folders are git-ignored)
or from `Android/data/com.takipli.oynat/files/models/` on the phone. Local build without CI: put `.onnx` files in the flavor's assets folder first.

## Release build (Part 15)

CI builds a **signed release APK** on every `v*` tag when these repository secrets exist (otherwise the step is skipped with a
warning and only the debug APK is uploaded):

| Secret | Content |
|---|---|
| `ANDROID_KEYSTORE_B64` | the keystore file, base64: `base64 -w0 release.jks` |
| `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD` | as used when the keystore was created |

Create a keystore once (keep it and the passwords safe; losing them means phones cannot update the app, only reinstall):

```
keytool -genkeypair -v -keystore release.jks -alias takipli -keyalg RSA -keysize 4096 -validity 10000
```

Local signed build: `KEYSTORE_PATH=/abs/path/release.jks KEYSTORE_PASSWORD=... KEY_ALIAS=takipli KEY_PASSWORD=... gradle :app:assemblePoseRelease` (or `assembleSamRelease`).
The APK is attached to the GitHub Release **only in a private repository** (it contains AGPL-3.0 pose models for personal use);
in a public repository it stays a workflow artifact (`TakipliOynat-Android-Release`).

## Error log

Home screen footer: **Share error log** sends a text with the app version, device and the latest errors (scan, export, player,
crashes); **Clear error log** empties it. The file is `files/logs/error.log` (capped at 100 KB).

## Versioning and in-app updates

- **Version:** `VERSION` (X.Y.Z, shared with the PC app) is the public number. `python scripts/bump_version.py patch|minor|major|X.Y.Z` changes it everywhere it is pinned (`python scripts/version.py check` verifies). Every CI file is named `<App>-X.Y.Z-b<run>` and one GitHub Release per run carries all apps.
  CI adds a build number (GitHub run number): `versionCode = (X*10000 + Y*100 + Z) * 1000 + build` (build capped at 999, 0 locally), so every CI build is newer than the last.
- **Releases (private repository only, signed):** every push to `main` publishes a prerelease `vX.Y.Z-b<run>` (newest 8 kept); a `v*` tag publishes a normal Release.
  Files: `TakipliOynat-Android-<pose|sam>-X.Y.Z-b<run>.apk`. Needs the four keystore secrets (see Release build); without them nothing is published.
- **App:** Home -> Updates: enter the repository (`owner/name`, filled by CI builds) and, for a private repository, a fine-grained read-only token
  (Contents: read). Check -> Download and install. Each build only offers its own flavor (`pose` or `sam`).
- **Rules the phone enforces:** the update must be signed with the same key as the installed app, and its versionCode must be higher.
  CI **debug** APKs get a random debug key each run, so they can never update each other: install the signed release once (uninstall a debug build first), then update in-app.
  Allow "install unknown apps" for the app when asked.

## Record-only variant (`rec/`)

A second, much smaller app from the same repo: **Takipli Record** (`com.takipli.oynat.rec`, installs next to the full app). Only the manual
camera: pick a clip, play it, pinch to zoom and drag at the same time while recording, export the recorded camera path to MP4
(`Movies/TakipliOynat`). No pose, tracking, scanning, ONNX Runtime, QNN, OpenCV, updater or network permission. It depends only on `:core`
(pure Kotlin view/export maths) and reads the same `VERSION`.

- **Full screen** button on the preview: the preview fills the screen (system bars hidden) and every control is an overlay: exit, rotate left/right,
  play/pause, seek, speed, REC/STOP, Export. Back exits full screen (stops the take first if recording).
- **Rotate** buttons turn the video 90 degrees (preview and export); recorded moves are cleared on rotate because they were made in the old orientation.
- Build: `cd android && gradle :rec:assembleDebug` -> `rec/build/outputs/apk/debug/rec-debug.apk`. CI: `.github/workflows/android-rec.yml` (started by `build-all.yml`) (artifact `TakipliKayit-Android`).

## Frontal seated lower-body tracking (camera slightly below knee level)

The core module now includes `LowerBodyModel.kt` for the frontal, slightly-upward camera
profile (8° is a nominal profile label, not a measured camera calibration). It separates the
**anatomical target envelope** from an optional **visible-pixel envelope**. When knee/ankle
landmarks are implausible or hidden, the anatomical envelope is anchored at the hips and
scaled from shoulder-to-hip torso length; the existing robust landmark sanitizer still
rejects distal joints that are too far from their anatomical roots. `presetBoxes()` uses this
estimate for its robust lower-body fallback and applies a per-track short-gap filter, so the
camera target does not collapse immediately to a tiny visible fragment.

`estimateLowerBody(..., deskOcclusionY = ...)` can clip a visible-region estimate below a
detected horizontal desk/front-panel boundary while preserving the full anatomical box.
The boundary is an explicit input: **this change does not yet detect desks or desk edges from
video pixels**. Until such a detector is connected, pass `null`; do not treat SAM's person mask
as a desk detector. `LowerBodyTemporalFilter` provides the short-gap hold and smoothing used by `presetBoxes()`.

The model is designed for a frontal camera at approximately knee height, tilted slightly
upward. It does not yet perform camera-pitch calibration or automatic desk-edge detection;
the optional boundary must come from a future detector or explicit input. It does not assume
a top-down view of the tabletop.
