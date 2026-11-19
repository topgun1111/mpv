"""Choose the files that go on the GitHub Release of one CI run (called by the `release` job in build-all.yml).

All five builds (PC full, PC recording, Android pose, Android sam, Android record) land on ONE release, which carries
the shared version (see scripts/version.py). Licence rules, unchanged from the old per-workflow publishing:
  - PC full installer/zip and the Android pose/sam APKs contain the Ultralytics pose models (AGPL-3.0, personal use).
    Android pose/sam: private repositories only. PC full: private repositories, or a v* tag (as before).
  - The recording apps (PC + Android) have no models and are always published.

Usage: python scripts/release_assets.py DIR --private true|false --tag-release true|false --list assets.txt --notes notes.md
Writes DIR/SHA256SUMS.txt, the list of files to upload (one per line) and the release notes header. Exit 1 if nothing is left.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

# (file name prefix, extension, group, contains AGPL models)
RULES = (
    ("TakipliOynat-Setup-", ".exe", "PC full", True),
    ("TakipliOynat-Portable-", ".zip", "PC full", True),
    ("TakipliOynatKayit-Setup-", ".exe", "PC recording", False),
    ("TakipliOynatKayit-Portable-", ".zip", "PC recording", False),
    ("TakipliOynat-Android-", ".apk", "Android pose/sam", True),
    ("TakipliKayit-Android-", ".apk", "Android record", False),
)


# The shared naming scheme: <App>-<X.Y.Z>-b<run number>.<ext> (debug APKs are named ...-<X.Y.Z>-debug.apk and never match)
VERSIONED = re.compile(r"-\d+\.\d+\.\d+-b\d+\.[a-z]+$")


def classify(name: str) -> tuple[str, bool] | None:
    if not VERSIONED.search(name):
        return None
    for prefix, ext, group, agpl in RULES:
        if name.startswith(prefix) and name.endswith(ext):
            return group, agpl
    return None


def allowed(name: str, group: str, agpl: bool, private: bool, tag_release: bool) -> bool:
    if not agpl or private:
        return True
    return group == "PC full" and tag_release  # public repository: only the PC release on a v* tag (as before)


def pick(files: list[Path], private: bool, tag_release: bool) -> tuple[list[Path], list[tuple[str, str]]]:
    chosen: list[Path] = []
    skipped: list[tuple[str, str]] = []
    for f in sorted(files):
        c = classify(f.name)
        if c is None:
            skipped.append((f.name, "not a release file"))
        elif allowed(f.name, c[0], c[1], private, tag_release):
            chosen.append(f)
        else:
            skipped.append((f.name, "contains AGPL-3.0 models: public repository, kept as a workflow artifact"))
    return chosen, skipped


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def notes(chosen: list[Path], skipped: list[tuple[str, str]]) -> str:
    lines = ["| Group | File |", "|---|---|"]
    lines += [f"| {classify(p.name)[0]} | `{p.name}` |" for p in chosen if classify(p.name)]
    out = "\n".join(lines)
    left_out = [s for s in skipped if s[1] != "not a release file"]
    if left_out:
        out += "\n\nNot attached (" + left_out[0][1] + "): " + ", ".join(f"`{n}`" for n, _ in left_out)
    return out + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dir")
    ap.add_argument("--private", required=True, choices=("true", "false"))
    ap.add_argument("--tag-release", required=True, choices=("true", "false"))
    ap.add_argument("--list", required=True)
    ap.add_argument("--notes", required=True)
    a = ap.parse_args(argv)
    root = Path(a.dir)
    files = [p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"]
    chosen, skipped = pick(files, a.private == "true", a.tag_release == "true")
    for name, why in skipped:
        print(f"skipped {name}: {why}")
    if not chosen:
        print("no release files found", file=sys.stderr)
        return 1
    sums = root / "SHA256SUMS.txt"
    sums.write_text("".join(f"{sha256(p)}  {p.name}\n" for p in chosen), encoding="utf-8")
    Path(a.list).write_text("".join(f"{p}\n" for p in [*chosen, sums]), encoding="utf-8")
    Path(a.notes).write_text(notes(chosen, skipped), encoding="utf-8")
    print(f"{len(chosen)} files + SHA256SUMS.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
