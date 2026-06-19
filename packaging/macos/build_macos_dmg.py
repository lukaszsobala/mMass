#!/usr/bin/env python3
"""Build a macOS .dmg installer for mMass from the .app bundle."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a macOS .dmg disk image for mMass."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow running on non-macOS hosts (for CI/cross checks).",
    )
    parser.add_argument(
        "--skip-bundle",
        action="store_true",
        help="Skip running PyInstaller and reuse an existing .app bundle.",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Override version label (default: project version).",
    )
    parser.add_argument(
        "--app-bundle",
        default=None,
        help="Path to mMass.app (default: build/dist/macos/mMass.app).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Path to write the .dmg (default: build/installer/macos).",
    )
    parser.add_argument(
        "--output-name",
        default=None,
        help="DMG filename (default: mMass-<version>-macos-arm64.dmg).",
    )
    return parser.parse_args()


def run_hdiutil_create(hdiutil_cmd: list[str], volname: str) -> None:
    """Run ``hdiutil create`` with retries.

    On CI runners ``hdiutil create`` intermittently fails with
    "Resource busy" when another process (Spotlight indexing, Disk
    Arbitration, or file handles lingering from the just-completed
    PyInstaller signing) touches the staging directory mid-create. The
    failure is transient, so flush pending writes, clear any stale mount of
    the same volume name, and retry with backoff.
    """
    attempts = 5
    for attempt in range(1, attempts + 1):
        # Flush filesystem buffers so freshly written/signed files are settled.
        subprocess.run(["sync"], check=False)

        # Detach any stale mount left over from a previous (failed) attempt.
        mount_point = Path("/Volumes") / volname
        if mount_point.exists():
            subprocess.run(
                ["hdiutil", "detach", str(mount_point), "-force"], check=False
            )

        result = subprocess.run(hdiutil_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return

        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if attempt == attempts or "Resource busy" not in (result.stdout + result.stderr):
            raise subprocess.CalledProcessError(result.returncode, hdiutil_cmd)

        delay = 5 * attempt
        print(
            f"hdiutil create failed (Resource busy), retrying in {delay}s "
            f"(attempt {attempt}/{attempts})..."
        )
        time.sleep(delay)


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

    if not args.skip_bundle:
        bundle_script = script_path.with_name("build_macos_app.py")
        if not bundle_script.exists():
            print(f"Bundle build script not found: {bundle_script}")
            return 2
        bundle_cmd = [sys.executable, str(bundle_script)]
        if args.force:
            bundle_cmd.append("--force")
        if args.version:
            bundle_cmd += ["--version", args.version]
        print("Running:", " ".join(bundle_cmd))
        subprocess.run(bundle_cmd, cwd=str(project_root), check=True)

    default_bundle = project_root / "build" / "dist" / "macos" / "mMass.app"
    app_bundle = Path(args.app_bundle).resolve() if args.app_bundle else default_bundle
    if not app_bundle.exists() or not app_bundle.is_dir():
        print(f".app bundle not found: {app_bundle}")
        return 2

    if shutil.which("hdiutil") is None:
        print("hdiutil not found; this script must run on macOS.")
        return 2

    version = args.version or read_project_version(project_root)
    default_output_dir = project_root / "build" / "installer" / "macos"
    output_dir = Path(args.output_dir).resolve() if args.output_dir else default_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    output_name = args.output_name or f"mMass-{version}-macos-arm64.dmg"
    output_file = output_dir / output_name
    if output_file.exists():
        output_file.unlink()

    # Stage a clean directory holding the app plus an /Applications symlink so
    # the mounted image presents the familiar drag-to-install layout.
    with tempfile.TemporaryDirectory() as staging_str:
        staging = Path(staging_str)
        staged_app = staging / app_bundle.name
        print(f"Staging {app_bundle} -> {staged_app}")
        shutil.copytree(app_bundle, staged_app, symlinks=True)
        (staging / "Applications").symlink_to("/Applications")

        volname = f"mMass {version}"
        hdiutil_cmd = [
            "hdiutil",
            "create",
            "-volname",
            volname,
            "-srcfolder",
            str(staging),
            "-ov",
            "-format",
            "UDZO",
            str(output_file),
        ]
        print("Running:", " ".join(hdiutil_cmd))
        run_hdiutil_create(hdiutil_cmd, volname)

    print("macOS installer ready:", output_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
