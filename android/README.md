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
gradle :core:test :app:assembleDebug        # APK: app/build/outputs/apk/debug/app-debug.apk
```

Needs JDK 17+ and the Android SDK (platform 36). To get a local wrapper once: `gradle wrapper --gradle-version 8.14.3`
(then commit `gradlew`, `gradlew.bat`, `gradle/wrapper/*`).

`VERSION` at the repo root is shared with the PC app (`versionName`; `versionCode = major*10000 + minor*100 + patch`).
Only the phone ABI `arm64-v8a` is built.
