# Takipli Oynat — Android

Android version of the PC tracking follow-cam, in the same repo. Plan and status: `../handover-android.md`.

| Module | What |
|---|---|
| `core/` | Pure Kotlin (no Android imports): geometry, formats, ByteTrack, view building. Tested on plain JVM. |
| `app/` | Android app (Compose UI, decode, ONNX Runtime, export). |

## Build

CI (`.github/workflows/android.yml`) runs on every push and uses Gradle 8.14.3 directly, so no Gradle wrapper
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
