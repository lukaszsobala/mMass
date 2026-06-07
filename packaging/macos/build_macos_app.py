#!/usr/bin/env python3
"""Build a macOS .app bundle for mMass with PyInstaller (arm64)."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the macOS mMass .app bundle (arm64)."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow running on non-macOS hosts (for CI/cross checks).",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Override bundle version label (default: project version).",
    )
    return parser.parse_args()


def read_project_version(project_root: Path) -> str:
    pyproject = project_root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Could not find version in {pyproject}")
    return match.group(1)


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    project_root = script_path.parents[2]

    if sys.platform != "darwin" and not args.force:
        print("This build procedure targets macOS. Re-run on macOS or use --force.")
        return 2

    spec_file = script_path.with_name("mMass-macos.spec")
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

    version = args.version or read_project_version(project_root)

    dist_dir = project_root / "build" / "dist" / "macos"
    work_dir = project_root / "build" / "pyinstaller" / "macos"

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

    # PyInstaller does not forward variables into the spec, so the version is
    # passed through the environment and read by the spec as MMASS_APP_VERSION.
    print("Running:", " ".join(cmd))
    print("Bundle version:", version)
    subprocess.run(
        cmd,
        check=True,
        cwd=str(project_root),
        env={**os.environ, "MMASS_APP_VERSION": version},
    )

    app_bundle = dist_dir / "mMass.app"
    if not app_bundle.exists():
        print(f"Expected .app bundle not found: {app_bundle}")
        return 2

    # Ad-hoc sign so the bundle launches without a "damaged" Gatekeeper error
    # on the building machine and after a clean drag-install.
    print("Ad-hoc signing bundle...")
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(app_bundle)],
        check=True,
    )

    print("macOS bundle ready:", app_bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
