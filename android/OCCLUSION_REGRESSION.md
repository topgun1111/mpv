# Android occlusion regression checklist

## What changed

1. Pose scan: short missing detections do not stop the scan before the ID-recovery window (8 s). A free-point/region pick never uses a missing **pose anchor** as a reason to pause its separate SAM/flow tracker.
2. Target identity: conservative low-cost colour evidence from clear person boxes is stored in the local track file. Geometric relinking rejects conflicting appearance evidence and similarly plausible candidates. This is **not neural Re-ID** and must not be assumed reliable for identical uniforms/clothing.
3. Android SAM build: missing limb/foot keypoint spans can trigger a second, offline SAM pass, **only around at most two short internal gaps** (each at most 4 s at 3 fps). Leading/trailing absences, shot cuts and long gaps never launch an automatic full-video SAM scan. Each window has a 75 s timeout, after which the pose result is preserved. Confident pose observations take priority; masks are accepted only with confidence, position and size checks. Pose-only APK keeps the existing optical/pose behavior.
4. Offline view building: ID fragments are examined forwards and backwards; a bounded gap holds the crop instead of zooming to the full frame. Shot changes reset the hold.

## Automated validation

Run `gradle :core:test :app:assemblePoseRelease :app:assembleSamRelease` from `android/` with the ONNX assets created by CI. The core tests include:

- `AppearanceTest` / `RelinkTest`: mismatching clothing signatures, ambiguous candidates, forward/backward ID continuity, shot cuts.
- `BodySamTest`: a visible hip with a hidden knee, SAM mask recovery, rejection of a distant mask.
- `BodySamTest` bounded recovery planning: short internal gaps only; cut and long-gap exclusions.
- `OcclusionRegressionTest` / `LowerBodyViewsTest`: 3 s occlusion, stable zoom, delayed alert, and hold expiration at cuts.

## Real-video acceptance tests (still required)

Use three 10–30 s clips: (A) a person walking in front of the chosen student for 1–3 s; (B) sitting behind a desk with knees/feet partially covered; (C) target exiting then returning, while a second person remains in view. On both the SAM and pose APKs:

1. Pick the actual person/limb. Confirm the preview shows that ID and a crop before the obstruction.
2. Observe the video after full scan, not just the first-stage pose preview. There must be no unexpected manual-pick pause under 8 s in Pose mode or a pose-anchor pause in SAM point mode.
3. Record: wrong-ID transitions (goal 0), longest target-absent time, zoom range during the gap, and whether the target was recovered without manual intervention.
4. Compare EdgeTAM vs SAM 2.1 Small separately: note inference/fallback in the diagnostics log. A successful APK compilation is not evidence of correct tracking.
5. During SAM body recovery, the progress bar labels **frame preparation** and **mask analysis** separately. Cancelling at this stage must keep the already completed pose scan exportable. If ONNX Runtime does not return from a native call, the timeout may only take effect after that call returns.

**Limits:** Colour histograms cannot establish identity for two similarly clothed people. SAM's extra limb pass can be computationally expensive on a phone. Real-video thresholds and NPU/CPU runtime need device validation; never mark occlusion tracking as solved based on synthetic fixtures alone.
