# Android occlusion regression checklist

## What changed

1. Pose scan: short missing detections do not stop the scan before the ID-recovery window (8 s). A free-point/region pick never uses a missing **pose anchor** as a reason to pause its separate SAM/flow tracker.
2. Target identity: colour evidence and an optional 512-dimensional OSNet person Re-ID signature are collected only from clear, isolated person boxes and saved in the local track file. Geometric relinking rejects mismatching neural evidence and ambiguous candidates; strong neural agreement can rescue a misleading colour histogram. A missing/unavailable neural model leaves the previous colour-and-geometry behavior intact. OSNet is packaged offline with **both** Android APKs, on CPU initially to avoid NPU compilation stalls. These embeddings represent appearance, not a guarantee of personal identity.
3. Android SAM build: missing limb/foot keypoint spans can trigger a second, offline SAM pass, **only around at most two short internal gaps** (each at most 4 s at 3 fps). Leading/trailing absences, shot cuts and long gaps never launch an automatic full-video SAM scan. Each window has a 75 s timeout, after which the pose result is preserved. Confident pose observations take priority; masks are accepted only with confidence, position and size checks. Pose-only APK keeps the existing optical/pose behavior.
4. Offline view building: ID fragments are examined forwards and backwards; a bounded gap holds the crop instead of zooming to the full frame. Shot changes reset the hold.
5. Temporal target memory (Android robust views only): the last reliable person/limb/object box retains its size and follows a damped, camera-corrected velocity for up to 3 s by default. A generic person-box slice does not overwrite a recently observed limb/foot. Memory expires, does not predict before the first trustworthy observation, and resets on cuts or broken timestamps. The result screen has a 0–6 s **Predict position while hidden** slider; setting it to zero disables the feature. It does not run additional neural inferences during scanning.

## Automated validation

Run `gradle :core:test :app:assemblePoseRelease :app:assembleSamRelease` from `android/` with the ONNX assets created by CI. The core tests include:

- `AppearanceTest` / `ReidTest` / `RelinkTest`: mismatching clothing signatures, invalid neural vectors, gallery resumption and contamination rejection, neural mismatch and agreement, ambiguous candidates, forward/backward ID continuity, shot cuts.
- `BodySamTest`: a visible hip with a hidden knee, SAM mask recovery, rejection of a distant mask.
- `BodySamTest` bounded recovery planning: short internal gaps only; cut and long-gap exclusions.
- `OcclusionRegressionTest` / `LowerBodyViewsTest`: 3 s occlusion, stable zoom, delayed alert, and hold expiration at cuts.
- `TemporalMemoryTest`: velocity memory, weak-slice suppression, camera compensation, expiration, cut/time reset and end-to-end foot framing.

## Real-video acceptance tests (still required)

Use three 10–30 s clips: (A) a person walking in front of the chosen student for 1–3 s; (B) sitting behind a desk with knees/feet partially covered; (C) target exiting then returning, while a second person remains in view. On both the SAM and pose APKs:

1. Pick the actual person/limb. Confirm the preview shows that ID and a crop before the obstruction.
2. Observe the video after full scan, not just the first-stage pose preview. There must be no unexpected manual-pick pause under 8 s in Pose mode or a pose-anchor pause in SAM point mode.
3. Record: wrong-ID transitions (goal 0), longest target-absent time, zoom range during the gap, and whether the target was recovered without manual intervention.
4. Compare EdgeTAM vs SAM 2.1 Small separately: note inference/fallback in the diagnostics log. A successful APK compilation is not evidence of correct tracking.
5. During SAM body recovery, the progress bar labels **frame preparation** and **mask analysis** separately. Cancelling at this stage must keep the already completed pose scan exportable. If ONNX Runtime does not return from a native call, the timeout may only take effect after that call returns.
6. During Pose and SAM scans, check OSNet initialization in diagnostics (`MODEL_READY` or `MODEL_UNAVAILABLE`), scan duration with several visible people, identity after an occlusion and after a resumed scan, and whether clean near-identical clothing causes a wrong merge. The similarity thresholds (0.78 / 0.92) require calibration on diverse real videos.
7. Compare the same obscured person/foot in Results with the new temporal memory slider at 0 s and at 3 s. Check that a moving target does not freeze immediately, the zoom/part box survives a brief leg obstruction, a visible fallback slice does not pull the camera onto the desk, and a 5+ s absence or a shot cut does not cause indefinite prediction. Verify any resumed scan remains consistent.

**Model attribution:** Qualcomm [OSNet](https://aihub.qualcomm.com/compute/models/osnet) x1.0, [MIT licensed](https://huggingface.co/qualcomm/OSNet); the GitHub Actions build downloads its pinned `v0.66.0` ONNX float package and verifies its SHA-256. No model download is needed while scanning.

**Limits:** Colour and OSNet signatures cannot reliably distinguish all look-alikes, clothing changes or heavy occlusion, and cannot help when no clean detections exist. Local track files store 512-value identity features and must be treated as sensitive appearance-derived data. SAM's limb pass can be computationally expensive on a phone. Real-video thresholds, CPU runtime and battery usage need device validation; never mark occlusion tracking as solved based on synthetic fixtures alone.
