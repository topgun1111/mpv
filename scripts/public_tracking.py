"""Prepare and validate public Windows tracking packages without restricted weights."""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

from verify_models import check, load_manifest, write_sums

ROOT = Path(__file__).resolve().parent.parent
MODEL_NAMES = {
    "yolox_s.onnx", "YOLOX_LICENSE.txt", "MODELLER.txt", "manifest.json",
    "SHA256SUMS.txt", "PUBLIC_MODELS.txt", ".gitkeep",
}
SAM_GRAPHS = {
    "sam-encoder.onnx", "sam-decoder.onnx", "sam-decoder-trk.onnx",
    "sam-memenc.onnx", "sam-memattn.onnx",
}
SAM_FILES = {
    f"sam-models/{variant}/{name}"
    for variant in ("edgetam", "small")
    for name in SAM_GRAPHS | {"SHA256SUMS.txt"}
} | {"sam-models/APACHE_LICENSE.txt", "sam-models/NOTICE.txt"}
REQUIRED = {f"models/{name}" for name in MODEL_NAMES - {".gitkeep"}} | SAM_FILES
NOTICE = (
    "Public Tracking package: YOLOX-S, EdgeTAM and SAM 2.1 Small are included.\n"
    "Optional Ultralytics pose, OSNet and RTMPose weights are not redistributed.\n"
    "Existing local models are retained on installer upgrades. Fresh installations\n"
    "can add locally obtained weights in models/; see MODELLER.txt.\n"
    "Haze editing and export do not require any pose model.\n"
)
SAM_NOTICE = (
    "EdgeTAM and SAM 2.1 checkpoints: Copyright Meta Platforms, Inc. and affiliates.\n"
    "Apache License 2.0, see APACHE_LICENSE.txt.\n"
    "https://github.com/facebookresearch/EdgeTAM\n"
    "https://github.com/facebookresearch/sam2\n"
    "Changes: exported to ONNX, with graph wrappers and real-valued RoPE adaptation\n"
    "in this project's scripts/export_sam2.py.\n"
)


def verify_model_paths(paths: set[str]) -> None:
    missing = REQUIRED - paths
    unexpected = {
        name for name in paths
        if (name.lower().startswith("models/") or name.lower().startswith("sam-models/"))
        and name not in REQUIRED and name != "models/.gitkeep"
    }
    if missing or unexpected:
        raise ValueError(
            f"Public model payload: missing={sorted(missing)}, extra={sorted(unexpected)}"
        )


def prepare(root: Path) -> None:
    models = root / "models"
    sam = root / "sam-models"
    if not models.is_dir() or not sam.is_dir():
        raise ValueError("Missing tracking model directories")
    # Disposable build outputs, never the user's installed model directory.
    for p in models.iterdir():
        if p.name not in MODEL_NAMES:
            print(f"Omitting public weight/file: {p.name}")
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()
    manifest = models / "manifest.json"
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["files"] = [
        e for e in doc["files"]
        if not e["path"].startswith("models/") or e["path"] == "models/yolox_s.onnx"
    ]
    doc["note"] = "Public package manifest; optional user-installed weights are not bundled."
    manifest.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    errors, sums = check(root, load_manifest(manifest))
    if errors:
        raise ValueError("; ".join(errors))
    write_sums(root, sums)
    (models / "PUBLIC_MODELS.txt").write_text(NOTICE, encoding="utf-8")
    shutil.copyfile(ROOT / "models/SAM_APACHE_LICENSE.txt", sam / "APACHE_LICENSE.txt")
    (sam / "NOTICE.txt").write_text(SAM_NOTICE, encoding="utf-8")
    verify_model_paths({p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()})
    print("PUBLIC TRACKING PAYLOAD VERIFIED")


def verify_archive(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set()
        for info in archive.infolist():
            if info.is_dir():
                continue
            parts = info.filename.replace("\\", "/").split("/")
            if len(parts) < 2 or parts[0] != "TakipliOynat" or ".." in parts:
                raise ValueError(f"Unexpected public archive entry: {info.filename}")
            name = "/".join(parts[1:])
            if name in names:
                raise ValueError(f"Duplicate archive entry: {name}")
            names.add(name)
        verify_model_paths(names)


def verify_release_pair(files: list[Path]) -> None:
    installers = {
        p.name.removeprefix("TakipliOynat-Setup-").removesuffix(".exe")
        for p in files if p.name.startswith("TakipliOynat-Setup-")
    }
    archives = {
        p.name.removeprefix("TakipliOynat-Portable-").removesuffix(".zip"): p
        for p in files if p.name.startswith("TakipliOynat-Portable-")
    }
    if installers != set(archives):
        raise ValueError("Public tracking release requires a matching installer and verified ZIP")
    for path in archives.values():
        verify_archive(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    prepare(args.package)


if __name__ == "__main__":
    main()
