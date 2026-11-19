"""One version for every app in this repository.

`VERSION` (repo root, X.Y.Z) is the only number you edit. It is shared by:
  PC full app        tracker/__init__.py, installer.iss (via /DAppVersion)
  PC recording app   recorder/__init__.py, installer-recording.iss
  Android pose/sam   android/app/build.gradle.kts   (reads ../VERSION)
  Android record     android/rec/build.gradle.kts   (reads ../VERSION)

Every CI build adds the build number (GitHub run number): `X.Y.Z-b<N>`. Android needs it for versionCode
((X*10000+Y*100+Z)*1000 + N), and every release file carries it, so file names tell you exactly which build you have.

Commands
  python scripts/version.py show                       print VERSION
  python scripts/version.py check                      every pinned copy must equal VERSION (CI runs this)
  python scripts/version.py bump patch|minor|major|X.Y.Z
  python scripts/version.py release-info --ref REF --build N [--github-output]
        main push  -> tag vX.Y.Z-bN, prerelease      (installed apps see it as an update)
        v* tag     -> tag vX.Y.Z,    full release    (the tag must equal VERSION, else exit 1)

Release by hand: bump, then `git commit -am "Version X.Y.Z" && git tag vX.Y.Z && git push --follow-tags`.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"\d+\.\d+\.\d+")
TAG = re.compile(r"v(\d+\.\d+\.\d+)")
MAX_BUILD = 999  # Android versionCode leaves three digits for the build number (see build.gradle.kts)

# (file, text that pins the version) - bump rewrites these, check compares them
PINS = (
    ("tracker/__init__.py", '__version__ = "{}"'),
    ("recorder/__init__.py", '__version__ = "{}"'),
    ("tests/test_license.py", '== "{}"'),
)
# Gradle files must read the shared VERSION file instead of holding their own number
GRADLE_READERS = ("android/app/build.gradle.kts", "android/rec/build.gradle.kts")


def read_version() -> str:
    v = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not SEMVER.fullmatch(v):
        raise SystemExit(f"VERSION must be X.Y.Z, found {v!r}")
    return v


def bump(cur: str, how: str) -> str:
    if SEMVER.fullmatch(how):
        return how
    major, minor, patch = (int(x) for x in cur.split("."))
    if how == "major":
        return f"{major + 1}.0.0"
    if how == "minor":
        return f"{major}.{minor + 1}.0"
    if how == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise SystemExit(f"unknown bump '{how}' (patch | minor | major | X.Y.Z)")


def problems(root: Path = ROOT) -> list[str]:
    """Everything that disagrees with VERSION (empty list = consistent)."""
    cur = (root / "VERSION").read_text(encoding="utf-8").strip()
    out: list[str] = []
    for rel, pattern in PINS:
        p = root / rel
        if not p.is_file():
            out.append(f"{rel}: file missing")
        elif pattern.format(cur) not in p.read_text(encoding="utf-8"):
            out.append(f"{rel}: does not contain {pattern.format(cur)}")
    for rel in GRADLE_READERS:
        p = root / rel
        if p.is_file() and '"../VERSION"' not in p.read_text(encoding="utf-8"):
            out.append(f"{rel}: must read ../VERSION")
    return out


def apply(new: str, cur: str) -> None:
    (ROOT / "VERSION").write_text(new + "\n", encoding="utf-8")
    for rel, pattern in PINS:
        p = ROOT / rel
        if not p.is_file():
            print(f"warning: {rel} is missing")
            continue
        s = p.read_text(encoding="utf-8")
        old = pattern.format(cur)
        if old not in s:
            print(f"warning: {rel} does not pin {cur}; fix it by hand")
            continue
        p.write_text(s.replace(old, pattern.format(new)), encoding="utf-8")


def release_info(ref: str, build: int, base: str) -> dict[str, str]:
    full = f"{base}-b{build}"
    if ref.startswith("refs/tags/"):
        tag = ref[len("refs/tags/"):]
        m = TAG.fullmatch(tag)
        if not m:
            raise SystemExit(f"tag {tag!r} is not vX.Y.Z")
        if m.group(1) != base:
            raise SystemExit(f"tag {tag} does not match VERSION {base}: bump VERSION, commit, then tag again")
        return {"version": base, "build": str(build), "full": full, "tag": tag, "prerelease": "false"}
    return {"version": base, "build": str(build), "full": full, "tag": f"v{full}", "prerelease": "true"}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="version.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="print VERSION")
    sub.add_parser("check", help="every pinned copy must equal VERSION")
    b = sub.add_parser("bump", help="patch | minor | major | X.Y.Z")
    b.add_argument("how")
    r = sub.add_parser("release-info", help="tag / prerelease flag / full version for this CI run")
    r.add_argument("--ref", default="", help="GITHUB_REF (refs/tags/vX.Y.Z or a branch)")
    r.add_argument("--build", type=int, default=0, help="GITHUB_RUN_NUMBER")
    r.add_argument("--github-output", action="store_true", help="also append to $GITHUB_OUTPUT")
    a = ap.parse_args(argv)

    if a.cmd == "show":
        print(read_version())
        return 0
    if a.cmd == "check":
        bad = problems()
        for line in bad:
            print(f"version mismatch: {line}")
        if not bad:
            print(f"versions consistent: {read_version()}")
        return 1 if bad else 0
    if a.cmd == "bump":
        cur = read_version()
        new = bump(cur, a.how)
        apply(new, cur)
        print(f"{cur} -> {new}")
        return 0
    info = release_info(a.ref, a.build, read_version())
    if a.build > MAX_BUILD:
        print(f"::warning::build number {a.build} is above {MAX_BUILD}: Android versionCode stops growing. Bump VERSION.")
    for k, v in info.items():
        print(f"{k}={v}")
    if a.github_output:
        out = os.environ.get("GITHUB_OUTPUT")
        if not out:
            raise SystemExit("--github-output needs the GITHUB_OUTPUT environment variable")
        with open(out, "a", encoding="utf-8") as f:
            f.writelines(f"{k}={v}\n" for k, v in info.items())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
