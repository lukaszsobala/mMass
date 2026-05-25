#!/usr/bin/env python3
"""Build a Windows installer for mMass from the PyInstaller bundle."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a Windows installer executable for mMass."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow running on non-Windows hosts (for CI/cross checks).",
    )
    parser.add_argument(
        "--skip-bundle",
        action="store_true",
        help="Skip running PyInstaller and reuse an existing bundle.",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Override installer version label (default: project version).",
    )
    parser.add_argument(
        "--bundle-dir",
        default=None,
        help="Path to mMass one-folder bundle (default: build/dist/windows/mMass).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Path to write installer executable (default: build/installer/windows).",
    )
    parser.add_argument(
        "--output-name",
        default=None,
        help="Installer filename (default: mMass-<version>-windows-x64-setup.exe).",
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

    if not sys.platform.startswith("win") and not args.force:
        print("This build procedure targets Windows. Re-run on Windows or use --force.")
        return 2

    bundle_script = script_path.with_name("build_windows_exe.py")
    installer_script = script_path.with_name("mMass_installer.nsi")
    if not bundle_script.exists():
        print(f"Bundle build script not found: {bundle_script}")
        return 2
    if not installer_script.exists():
        print(f"Installer script not found: {installer_script}")
        return 2

    if not args.skip_bundle:
        bundle_cmd = [sys.executable, str(bundle_script)]
        if args.force:
            bundle_cmd.append("--force")
        print("Running:", " ".join(bundle_cmd))
        subprocess.run(bundle_cmd, cwd=str(project_root), check=True)

    default_bundle_dir = project_root / "build" / "dist" / "windows" / "mMass"
    bundle_dir = Path(args.bundle_dir).resolve() if args.bundle_dir else default_bundle_dir
    if not bundle_dir.exists() or not bundle_dir.is_dir():
        print(f"Bundle directory not found: {bundle_dir}")
        return 2
    if not (bundle_dir / "mMass.exe").exists():
        print(f"Expected executable not found in bundle: {bundle_dir / 'mMass.exe'}")
        return 2

    if shutil.which("makensis") is None:
        print("NSIS compiler (makensis) is not installed or not on PATH.")
        print("Install NSIS from https://nsis.sourceforge.io/Download")
        return 2

    version = args.version or read_project_version(project_root)
    default_output_dir = project_root / "build" / "installer" / "windows"
    output_dir = Path(args.output_dir).resolve() if args.output_dir else default_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    output_name = args.output_name or f"mMass-{version}-windows-x64-setup.exe"
    output_file = output_dir / output_name

    nsis_cmd = [
        "makensis",
        f"/DAPP_VERSION={version}",
        f"/DSOURCE_DIR={bundle_dir}",
        f"/DOUTPUT_NAME={output_file}",
        str(installer_script),
    ]

    print("Running:", " ".join(str(x) for x in nsis_cmd))
    subprocess.run(nsis_cmd, cwd=str(project_root), check=True)

    print("Windows installer ready:", output_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())