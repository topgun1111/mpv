#!/usr/bin/env python3
"""Run the quick checks CI would run, before you push (about 20 seconds, no network needed).

    python scripts/precheck.py            # ruff, flavor parity, workflow lint, pytest
    python scripts/precheck.py --fast     # skip pytest

Workflow lint uses `actionlint` when it is on PATH (https://github.com/rhysd/actionlint), and always
runs a built-in check for the mistake that broke build-all once: a `runner.*` context in a job-level
`env`, which GitHub rejects as "Unrecognized named-value".
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"


def run(title: str, cmd: list[str]) -> bool:
    print(f"\n== {title}: {' '.join(cmd)}")
    ok = subprocess.run(cmd, cwd=ROOT).returncode == 0
    print("   ok" if ok else "   FAILED")
    return ok


def job_env_context_check() -> bool:
    """`runner`, `steps` and `job` contexts are not allowed in a job-level `env:`."""
    print("\n== workflows: job-level env contexts")
    bad = []
    for path in sorted(WF.glob("*.yml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        in_env = False
        for n, line in enumerate(lines, 1):
            if re.match(r"^    env:\s*(#.*)?$", line):  # 4 spaces = job level
                in_env = True
                continue
            if in_env:
                if line.startswith("      ") or not line.strip():
                    if re.search(r"\$\{\{[^}]*\b(runner|steps|job)\.", line):
                        bad.append(f"{path.name}:{n}: {line.strip()}")
                else:
                    in_env = False
    for b in bad:
        print("   -", b)
    print("   ok" if not bad else "   FAILED (set it in a step, or via $GITHUB_ENV / $RUNNER_TEMP)")
    return not bad


def ruff_cmd() -> list[str]:
    if shutil.which("ruff"):
        return ["ruff", "check", "."]
    return [sys.executable, "-m", "ruff", "check", "."]


def powershell_variable_check() -> bool:
    """PowerShell reads "$name: text" as a scoped variable and fails to parse; it needs "${name}: text"."""
    print("\n== workflows: PowerShell `$var:` in strings")
    pattern = re.compile(r'"[^"\n]*\$[A-Za-z_]\w*:(?=[\s"])')
    bad = []
    for path in sorted(WF.glob("*.yml")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and "pwsh" not in line and "$GITHUB" not in line and "$RUNNER" not in line:
                bad.append(f"{path.name}:{n}: {line.strip()[:110]}")
    for b in bad:
        print("   -", b)
    print("   ok" if not bad else "   FAILED (write ${name}: instead of $name:)")
    return not bad


def main(argv: list[str]) -> int:
    results = [
        run("lint", ruff_cmd()),
        run("android flavors", [sys.executable, "scripts/check_flavors.py"]),
        job_env_context_check(),
        powershell_variable_check(),
    ]
    if shutil.which("actionlint"):
        results.append(run("actionlint", ["actionlint"]))
    else:
        print("\n== actionlint not installed: skipped (optional; CI runs it)")
    if "--fast" not in argv:
        results.append(run("tests", [sys.executable, "-m", "pytest", "-q"]))
    print("\nALL CHECKS PASSED" if all(results) else "\nSOME CHECKS FAILED")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
