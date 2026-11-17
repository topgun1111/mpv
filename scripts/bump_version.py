"""Old entry point, kept so the documented command still works: same as `python scripts/version.py bump ...`.

Usage: python scripts/bump_version.py patch|minor|major|X.Y.Z
Then: git commit -am "Version X.Y.Z"; git tag vX.Y.Z; git push --follow-tags   (a v* tag publishes a normal Release).
See scripts/version.py for the whole scheme (every main push already publishes a prerelease vX.Y.Z-b<run number>).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import version  # noqa: E402

if __name__ == "__main__":
    sys.exit(version.main(["bump", *sys.argv[1:]]))
