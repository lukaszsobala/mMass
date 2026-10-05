#!/usr/bin/env python3
"""Build the Linux mMass bundle (one-folder) with PyInstaller."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the Linux mMass bundle (one-folder)."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow running on non-Linux hosts (for CI/cross checks).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    project_root = script_path.parents[2]

    if not sys.platform.startswith("linux") and not args.force:
        print("This build procedure targets Linux. Re-run on Linux or use --force.")
        return 2

    spec_file = script_path.with_name("mMass-linux.spec")
    entry_file = project_root / "src" / "mmass_app" / "app.py"
    config_dir = project_root / "src" / "gui" / "configs"

    for path in (spec_file, entry_file, config_dir):
        if not path.exists():
            print(f"Expected file not found: {path}")
            return 2

    if shutil.which("pyinstaller") is None:
        print("PyInstaller is not installed in this environment.")
        print("Install it with: pip install pyinstaller")
        return 2
    if shutil.which("objdump") is None:
        print("objdump (binutils) is needed to inspect the collected libraries.")
        return 2

    dist_dir = project_root / "build" / "dist" / "linux"
    work_dir = project_root / "build" / "pyinstaller" / "linux"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        str(spec_file),
    ]

    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(project_root))

    output = dist_dir / "mmass"
    print("Linux bundle ready:", output)
    print("Main executable:", output / "mmass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
