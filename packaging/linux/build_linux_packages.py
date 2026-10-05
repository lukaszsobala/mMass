#!/usr/bin/env python3
"""Build the Linux packages of mMass (.deb, .rpm, .AppImage) from the bundle.

The PyInstaller bundle is checked first (linux_libs.inspect_bundle): every
library it needs must be either bundled or a known host library, and the host
libraries it actually uses become the package dependencies. The .deb and .rpm
are then made with nfpm, and the AppImage with appimagetool. All three carry
the same bundle; the .deb/.rpm install it to /opt/mmass.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

import linux_libs

# platform.machine() -> (Debian architecture, RPM/AppImage architecture);
# nfpm takes the Debian (Go) name and maps it for RPM itself
ARCHITECTURES = {
    "x86_64": ("amd64", "x86_64"),
    "aarch64": ("arm64", "aarch64"),
}
FORMATS = ("deb", "rpm", "appimage")
ICON_SIZES = (16, 32, 48, 128, 256, 512)

DESCRIPTION = """\
Open source mass spectrometry tool.
mMass presents a comprehensive and platform independent multifunctional
mass spectrometry tool. It supports data processing (peak picking,
deisotoping, calibration, ...) and interpretation of MS and MS/MS data
(sequence and compound tools, mass and formula calculators, database
searches)."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build .deb, .rpm and .AppImage packages of mMass."
    )
    parser.add_argument(
        "--skip-bundle",
        action="store_true",
        help="Skip running PyInstaller and reuse an existing bundle.",
    )
    parser.add_argument(
        "--bundle",
        default=None,
        help="Path to the one-folder bundle (default: build/dist/linux/mmass).",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Override version label (default: project version).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Where to write the packages (default: build/installer/linux).",
    )
    parser.add_argument(
        "--formats",
        default=",".join(FORMATS),
        help=f"Comma-separated subset of {', '.join(FORMATS)} (default: all).",
    )
    parser.add_argument(
        "--maintainer",
        default="Łukasz Sobala <lukasz.sobala@hirszfeld.pl>",
        help="Maintainer field of the .deb/.rpm.",
    )
    parser.add_argument(
        "--max-glibc",
        default="2.34",
        help="Fail if the bundle needs a newer glibc (default: 2.34, the "
        "glibc of Enterprise Linux 9, the oldest supported system).",
    )
    parser.add_argument("--nfpm", default="nfpm", help="nfpm executable.")
    parser.add_argument(
        "--appimagetool", default="appimagetool", help="appimagetool executable."
    )
    return parser.parse_args()


def read_project_version(project_root: Path) -> str:
    pyproject = project_root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Could not find version in {pyproject}")
    return match.group(1)


def install_shared_files(root: Path, project_root: Path, here: Path) -> None:
    """Desktop entry, icons and MIME types under <root>/usr/share."""
    share = root / "usr" / "share"
    (share / "applications").mkdir(parents=True, exist_ok=True)
    shutil.copy2(here / "mmass.desktop", share / "applications" / "mmass.desktop")
    (share / "mime" / "packages").mkdir(parents=True, exist_ok=True)
    shutil.copy2(here / "mmass-mime.xml", share / "mime" / "packages" / "mmass.xml")
    images = project_root / "src" / "gui" / "images" / "gtk"
    for size in ICON_SIZES:
        target = share / "icons" / "hicolor" / f"{size}x{size}" / "apps"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(images / f"icon_{size}.png", target / "mmass.png")


def build_system_packages(args, formats, bundle, stage, output_dir, version,
                          deb_arch, rpm_arch, host, glibc, project_root, here):
    root = stage / "root"
    install_shared_files(root, project_root, here)

    contents = [
        {"src": str(bundle), "dst": "/opt/mmass", "type": "tree"},
        {"src": "/opt/mmass/mmass", "dst": "/usr/bin/mmass", "type": "symlink"},
    ]
    # files one by one, so the packages do not claim the shared directories
    # (/usr/share/icons/hicolor/...) as their own
    contents += [
        {"src": str(path), "dst": "/" + str(path.relative_to(root))}
        for path in sorted(root.rglob("*")) if path.is_file()
    ]
    contents += [
        {
            "src": str(project_root / "license.txt"),
            "dst": "/usr/share/doc/mmass/copyright",
            "packager": "deb",
        },
        {
            "src": str(project_root / "license.txt"),
            "dst": "/usr/share/licenses/mmass/license.txt",
            "packager": "rpm",
            "type": "license",
        },
    ]
    config = {
        "name": "mmass",
        "arch": deb_arch,
        "platform": "linux",
        "version": version,
        # 7.0.0-beta32 -> 7.0.0~beta32, which sorts before 7.0.0
        "version_schema": "semver",
        "release": "1",
        "section": "science",
        "priority": "optional",
        "maintainer": args.maintainer,
        "vendor": "mMass",
        "homepage": "https://github.com/lukaszsobala/mMass",
        "license": "GPL-3.0-or-later",
        "description": DESCRIPTION,
        "contents": contents,
        "overrides": {
            "deb": {"depends": linux_libs.deb_depends(host, glibc)},
            "rpm": {"depends": linux_libs.rpm_requires(host, glibc)},
        },
        "rpm": {"group": "Applications/Engineering", "compression": "zstd"},
        "deb": {"compression": "xz"},
    }
    # JSON is valid YAML, which nfpm reads
    config_file = stage / "nfpm.yaml"
    config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print("deb Depends:", ", ".join(config["overrides"]["deb"]["depends"]))
    print("rpm Requires:", ", ".join(config["overrides"]["rpm"]["depends"]))

    outputs = []
    for fmt, arch in (("deb", deb_arch), ("rpm", rpm_arch)):
        if fmt not in formats:
            continue
        target = output_dir / f"mMass-{version}-linux-{arch}.{fmt}"
        cmd = [args.nfpm, "package", "--config", str(config_file),
               "--packager", fmt, "--target", str(target)]
        print("Running:", " ".join(cmd))
        subprocess.run(cmd, check=True)
        outputs.append(target)
    return outputs


def build_appimage(args, bundle, stage, output_dir, version, arch,
                   project_root, here):
    appdir = stage / "mMass.AppDir"
    lib_dir = appdir / "usr" / "lib" / "mmass"
    shutil.copytree(bundle, lib_dir, symlinks=True)
    (appdir / "usr" / "bin").mkdir(parents=True)
    (appdir / "usr" / "bin" / "mmass").symlink_to("../lib/mmass/mmass")
    install_shared_files(appdir, project_root, here)

    # the AppDir root holds the entry point, desktop entry and icon. AppRun
    # execs the bundle so that argv[0] ends in "mmass": GTK names the program
    # (Wayland app_id, X11 WM_CLASS) after it, which ties the window to
    # mmass.desktop
    app_run = appdir / "AppRun"
    app_run.write_text(
        '#!/bin/sh\n'
        'HERE="$(dirname "$(readlink -f "$0")")"\n'
        'exec "$HERE/usr/lib/mmass/mmass" "$@"\n',
        encoding="utf-8",
    )
    app_run.chmod(0o755)
    shutil.copy2(here / "mmass.desktop", appdir / "mmass.desktop")
    shutil.copy2(project_root / "src" / "gui" / "images" / "gtk" / "icon_256.png",
                 appdir / "mmass.png")
    (appdir / ".DirIcon").symlink_to("mmass.png")

    target = output_dir / f"mMass-{version}-linux-{arch}.AppImage"
    cmd = [args.appimagetool, "--no-appstream", str(appdir), str(target)]
    print("Running:", " ".join(cmd))
    # extract-and-run: CI runners and containers have no FUSE
    env = {**os.environ, "ARCH": arch, "APPIMAGE_EXTRACT_AND_RUN": "1"}
    subprocess.run(cmd, check=True, env=env)
    return [target]


def main() -> int:
    args = parse_args()
    here = Path(__file__).resolve().parent
    project_root = here.parents[1]

    if not sys.platform.startswith("linux"):
        print("Linux packages must be built on Linux.")
        return 2

    machine = platform.machine()
    if machine not in ARCHITECTURES:
        print(f"Unsupported architecture: {machine}")
        return 2
    deb_arch, rpm_arch = ARCHITECTURES[machine]

    formats = {fmt.strip().lower() for fmt in args.formats.split(",") if fmt.strip()}
    unknown = formats - set(FORMATS)
    if unknown:
        print(f"Unknown formats: {', '.join(sorted(unknown))}")
        return 2
    for fmt, tool in (("deb", args.nfpm), ("rpm", args.nfpm),
                      ("appimage", args.appimagetool)):
        if fmt in formats and shutil.which(tool) is None:
            print(f"{tool} is needed for the {fmt} package but was not found.")
            return 2

    if not args.skip_bundle:
        bundle_script = here / "build_linux_bundle.py"
        print("Running:", bundle_script)
        subprocess.run([sys.executable, str(bundle_script)],
                       cwd=str(project_root), check=True)

    bundle = Path(args.bundle).resolve() if args.bundle else (
        project_root / "build" / "dist" / "linux" / "mmass")
    if not (bundle / "mmass").is_file():
        print(f"Bundle not found: {bundle}")
        return 2

    host, glibc = linux_libs.inspect_bundle(bundle)
    print("Bundle checked; host libraries:", " ".join(host))
    print("Newest glibc symbol version:", ".".join(map(str, glibc)))
    max_glibc = tuple(int(part) for part in args.max_glibc.split("."))
    if glibc > max_glibc:
        print(f"The bundle needs glibc {'.'.join(map(str, glibc))}, newer than "
              f"{args.max_glibc}: it was built on too new a system, or with a "
              "Python or library built on one.")
        return 2

    version = args.version or read_project_version(project_root)
    output_dir = Path(args.output_dir).resolve() if args.output_dir else (
        project_root / "build" / "installer" / "linux")
    output_dir.mkdir(parents=True, exist_ok=True)

    stage = project_root / "build" / "linux-stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    outputs = []
    if formats & {"deb", "rpm"}:
        outputs += build_system_packages(
            args, formats, bundle, stage, output_dir, version, deb_arch,
            rpm_arch, host, glibc, project_root, here)
    if "appimage" in formats:
        outputs += build_appimage(args, bundle, stage, output_dir, version,
                                  rpm_arch, project_root, here)

    for path in outputs:
        print("Linux package ready:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
