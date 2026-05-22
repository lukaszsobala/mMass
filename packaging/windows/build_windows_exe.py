#!/usr/bin/env python3
"""Build a Windows executable bundle for mMass with PyInstaller."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the Windows mMass executable bundle (one-folder)."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow running on non-Windows hosts (for CI/cross checks).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    project_root = script_path.parents[2]

    if not sys.platform.startswith("win") and not args.force:
        print("This build procedure targets Windows. Re-run on Windows or use --force.")
        return 2

    spec_file = script_path.with_name("mMass.spec")
    entry_file = project_root / "src" / "mmass_app" / "app.py"
    config_dir = project_root / "src" / "gui" / "configs"

    if not spec_file.exists():
        print(f"Spec file not found: {spec_file}")
        return 2
    if not entry_file.exists():
        print(f"Expected app entrypoint not found: {entry_file}")
        return 2
    if not config_dir.exists():
        print(f"Expected config directory not found: {config_dir}")
        return 2

    if shutil.which("pyinstaller") is None:
        print("PyInstaller is not installed in this environment.")
        print("Install it with: pip install pyinstaller")
        return 2

    dist_dir = project_root / "build" / "dist" / "windows"
    work_dir = project_root / "build" / "pyinstaller" / "windows"

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

    output = dist_dir / "mMass"
    print("Windows bundle ready:", output)
    print("Main executable:", output / "mMass.exe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())