# Android lower-body tracking mode

This change adds an opt-in lower-body model to the existing Kotlin core and enables it for normal scan/pick flows when the selected preset is `legs`. It applies to both app flavors because the integration is in the shared `ScanService` and `android/core` modules.

## What changed

- `LowerBodyModel.kt`: stateful temporal model for a combined legs-and-feet region. It smooths the anatomical framing box, limits abrupt scale changes, holds the last reliable region for up to 1 second through brief missing observations, and classifies posture from COCO hip/knee/ankle angles with three-observation hysteresis.
- `Views.kt`: combines the current legs region with a conservative hip-anchored estimate when either leg has insufficient knee/ankle evidence. The temporal model is reset at shot cuts. Long losses are returned to the existing lost/zoom-out handling rather than held indefinitely.
- Lower-body mode uses a `0.70` target frame-height fill instead of the generic part target fill.
- `Pick.kt` and `ScanService.kt`: pass the opt-in flag through completed and partial scan results. The existing `legs` preset chip is the user-facing entry point.
- `Tuning.kt`: rebuilding views after tuning retains lower-body mode for the `legs` preset.

## Scope and limitations

- This is a geometry/temporal-reasoning improvement, not a new neural network or a replacement for SAM/Pose models.
- It does not yet perform explicit desk segmentation. Desk avoidance relies on the existing pose plausibility checks and the conservative hip-anchored estimate.
- Posture is classified internally, but this first integration does not yet use posture to switch between separate seated/walking camera policies.
- It does not add OSNet/Re-ID. Existing relinking and tracking gates remain responsible for identity recovery.
- The model only activates for the combined `legs` preset. Existing individual limb, freehand, rectangle and whole-person modes keep their prior behavior.

## Validation

New JVM unit tests cover scale-jump damping, short-occlusion hold, hold expiry, posture hysteresis and lower-body box persistence. The repository ZIP does not include a Gradle wrapper and this environment has no installed Gradle executable, so the full Android/core Gradle test suite and APK builds could not be run here. `LowerBodyModel.kt` was compiled independently with the available Kotlin compiler. Run from `android/` on the development PC:

```bash
gradle :core:test
./gradlew :app:assembleSamDebug :app:assemblePoseDebug
```

If a Gradle wrapper is added to the repository, prefer `./gradlew` for reproducible builds.

## Suggested real-video checks

1. Frontal seated person behind a desk, both legs visible.
2. Seated person with one thigh/knee hidden by the desk.
3. Crossed legs and repeated foot movement.
4. Brief complete occlusion followed by return.
5. Sit-to-stand and walking transition.
6. A hard scene cut, to verify no previous-person framing is carried into the next shot.

Compare the same clips with the `legs` preset before/after, especially the exported camera crop and zoom curve.
