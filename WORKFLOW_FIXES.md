# CI model-export and tracking build fixes

This patch addresses the failures in the supplied GitHub Actions log and adds stricter release gates.

## Changes

- Android pose exports now use a pinned PyTorch 2.5.1 / Torchvision 0.20.1 CPU toolchain with ONNX 1.17.0 and ONNX Runtime 1.20.1. This avoids the PyTorch 2.6+ Dynamo exporter path that raised `onnxscript.onnx_opset.opset23` import errors.
- Pose export validates the ONNX graph and confirms the expected `[1, 56, N]` output layout; it then loads the model with ONNX Runtime before copying it into app assets.
- EdgeTAM environments explicitly install `huggingface_hub`, which timm needs for the configured Hugging Face backbone.
- SAM checkpoints are stored outside app assets via `MODEL_CKPT_DIR` (or a sibling checkpoint directory by default), preventing `.pt` files from being packaged into the APK.
- Android model-report validation now runs before Gradle packaging and checks the required pose/SAM graph set.
- APK contents are checked by flavor: the pose APK is checked for both pose models; the SAM APK is checked for its pose model and both five-graph SAM variants.
- PC packaging now runs the ONNX model report before the manifest/checksum verification step. The Re-ID exporter explicitly selects the legacy Torch exporter where supported and retains a compatibility fallback.
- Diagnostic artifacts are uploaded even when earlier Android build steps fail.

## Validation performed in this environment

- Python syntax compilation passed for the modified export scripts.
- All workflow YAML files parsed successfully.
- Focused workflow/model-report/release tests passed: 19 passed, 4 skipped.
- The full 927-test suite did not finish within the available execution window; it had passed through approximately 82% when a long-running test exceeded the timeout.
- Ruff could not be run here because the Ruff executable is not present and this environment cannot reach package indexes. The original CI log reports 15 Ruff findings; those need a fresh CI run to expose their exact diagnostics.
- Model export, Android Gradle builds, and on-device tracking were not executed here because model downloads, external repositories, Android SDK dependencies, and a device are unavailable in this environment.

A successful GitHub Actions run and a real-device tracking test are still required before treating the APKs as verified releases.
