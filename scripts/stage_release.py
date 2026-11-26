"""Stage only permitted versioned binaries directly on a Build All draft release."""
from __future__ import annotations

import argparse
import glob
import os
import subprocess
from pathlib import Path

from release_assets import classify, pick


def collect(patterns: list[str]) -> list[Path]:
    found: set[Path] = set()
    for pattern in patterns:
        matches = [Path(p) for p in glob.glob(pattern) if Path(p).is_file()]
        if not matches:
            raise SystemExit(f"No output matching {pattern}")
        found.update(matches)
    return sorted(found)


def stage(patterns: list[str], tag: str, private: bool, tag_release: bool) -> int:
    if not tag:
        raise SystemExit("Draft release tag is required")
    files = collect(patterns)
    chosen, skipped = pick(files, private, tag_release)
    for name, reason in skipped:
        print(f"Not published: {name}: {reason}")
    if not chosen:
        return 0
    draft = subprocess.check_output(
        ["gh", "release", "view", tag, "--json", "isDraft", "--jq", ".isDraft"],
        text=True,
    ).strip()
    if draft != "true":
        raise SystemExit("Refusing to upload to a published release")
    subprocess.run(["gh", "release", "upload", tag, *map(str, chosen), "--clobber"], check=True)
    return 0


def verify(root: Path, private: bool, tag_release: bool, full: str) -> int:
    files = [p for p in root.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt"]
    chosen, skipped = pick(files, private, tag_release)
    wrong_version = any(
        classify(p.name) is None or not p.stem.endswith("-" + full) for p in files
    )
    if not chosen or skipped or wrong_version:
        raise SystemExit(f"Invalid staged release assets: {skipped}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    up = sub.add_parser("upload")
    up.add_argument("patterns", nargs="+")
    v = sub.add_parser("verify")
    v.add_argument("root", type=Path)
    v.add_argument("--private", choices=("true", "false"), required=True)
    v.add_argument("--tag-release", choices=("true", "false"), required=True)
    v.add_argument("--full", required=True)
    a = ap.parse_args()
    if a.command == "upload":
        return stage(a.patterns, os.environ.get("RELEASE_TAG", ""),
                     os.environ.get("PRIVATE", "false") == "true",
                     os.environ.get("IS_TAG", "false") == "true")
    return verify(a.root, a.private == "true", a.tag_release == "true", a.full)


if __name__ == "__main__":
    raise SystemExit(main())
