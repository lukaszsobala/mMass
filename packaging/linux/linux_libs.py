"""Which shared libraries the Linux bundle carries and which the host provides.

PyInstaller collects the whole ldd closure of every extension module, which
for wxPython means the entire GTK 3 desktop stack. Shipping that stack is the
wrong trade on Linux: an old GTK ignores the host's themes, input methods and
pixbuf loaders, and because the PyInstaller bootloader puts the bundle first
on LD_LIBRARY_PATH, every bundled copy of a library the host's own libraries
also use (zlib, libffi, OpenSSL, ...) shadows the host's newer copy and can
break them with "version `X' not found".

So the libraries below are taken from the host -- glibc, the GTK 3 stack and
the base libraries that stack itself loads -- and everything else the bundle
needs is bundled. The build host is AlmaLinux 9 (glibc 2.34, GTK 3.24.31),
which every target distribution matches or exceeds.

``HOST_LIBS`` maps each host soname to the Debian/Ubuntu package that provides
it. Packages renamed in the 64-bit time_t transition (Ubuntu 24.04, Debian 13)
are given as "new | old" alternatives. RPM requirements are generated from the
sonames themselves (``libgtk-3.so.0()(64bit)``), which works across Fedora,
RHEL and openSUSE without per-distribution package names.

Used by mMass-linux.spec (to prune the collected binaries) and by
build_linux_packages.py (to verify the bundle and generate dependencies).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

GLIBC = "libc6"

HOST_LIBS = {
    # C and C++ runtime
    "libc.so.6": GLIBC,
    "libm.so.6": GLIBC,
    "libdl.so.2": GLIBC,
    "libpthread.so.0": GLIBC,
    "librt.so.1": GLIBC,
    "libutil.so.1": GLIBC,
    "libresolv.so.2": GLIBC,
    "ld-linux-x86-64.so.2": GLIBC,
    "ld-linux-aarch64.so.1": GLIBC,
    "libstdc++.so.6": "libstdc++6",
    "libgcc_s.so.1": "libgcc-s1",
    # base libraries the GTK stack shares with Python's extension modules
    "libz.so.1": "zlib1g",
    "libexpat.so.1": "libexpat1",
    "libffi.so.8": "libffi8",
    "liblzma.so.5": "liblzma5",
    "libzstd.so.1": "libzstd1",
    "libuuid.so.1": "libuuid1",
    "libssl.so.3": "libssl3t64 | libssl3",
    "libcrypto.so.3": "libssl3t64 | libssl3",
    # GLib and GTK 3. libgthread-2.0 (an empty compatibility stub, which wx
    # links when built on Enterprise Linux) is bundled instead: openSUSE ships
    # it apart from GLib, so a GTK 3 install does not bring it
    "libglib-2.0.so.0": "libglib2.0-0t64 | libglib2.0-0",
    "libgobject-2.0.so.0": "libglib2.0-0t64 | libglib2.0-0",
    "libgio-2.0.so.0": "libglib2.0-0t64 | libglib2.0-0",
    "libgmodule-2.0.so.0": "libglib2.0-0t64 | libglib2.0-0",
    "libgtk-3.so.0": "libgtk-3-0t64 | libgtk-3-0",
    "libgdk-3.so.0": "libgtk-3-0t64 | libgtk-3-0",
    "libgdk_pixbuf-2.0.so.0": "libgdk-pixbuf-2.0-0 | libgdk-pixbuf2.0-0",
    "libatk-1.0.so.0": "libatk1.0-0t64 | libatk1.0-0",
    "libpango-1.0.so.0": "libpango-1.0-0",
    "libpangocairo-1.0.so.0": "libpango-1.0-0",
    "libpangoft2-1.0.so.0": "libpango-1.0-0",
    "libcairo.so.2": "libcairo2",
    "libcairo-gobject.so.2": "libcairo-gobject2",
    "libharfbuzz.so.0": "libharfbuzz0b",
    "libfontconfig.so.1": "libfontconfig1",
    "libfreetype.so.6": "libfreetype6",
    # X11 and Wayland. libSM/libICE (session management) and libXtst
    # (wx.UIActionSimulator) are bundled instead: wx is their only user, and a
    # GTK 3 install does not bring them everywhere (openSUSE), which matters
    # for the AppImage
    "libX11.so.6": "libx11-6",
    "libXext.so.6": "libxext6",
    "libXi.so.6": "libxi6",
    "libXxf86vm.so.1": "libxxf86vm1",
    "libwayland-client.so.0": "libwayland-client0",
    "libwayland-egl.so.1": "libwayland-egl1",
    "libxkbcommon.so.0": "libxkbcommon0",
    # OpenGL (only reached through wx.glcanvas, which mMass does not import)
    "libGL.so.1": "libgl1",
    "libEGL.so.1": "libegl1",
    "libGLU.so.1": "libglu1-mesa",
}

_NEEDED = re.compile(r"^\s*NEEDED\s+(\S+)", re.MULTILINE)
_GLIBC_VERSION = re.compile(r"\bGLIBC_(\d+)\.(\d+)(?:\.(\d+))?\b")


def is_elf(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(4) == b"\x7fELF"
    except OSError:
        return False


def _objdump(path: Path) -> str:
    return subprocess.run(
        ["objdump", "-p", str(path)], check=True, capture_output=True, text=True
    ).stdout


def needed(path: Path) -> list[str]:
    """The DT_NEEDED entries (direct dependencies) of an ELF file."""
    return _NEEDED.findall(_objdump(path))


def glibc_requirement(path: Path) -> tuple[int, ...]:
    """The newest GLIBC_x.y symbol version an ELF file requires."""
    versions = [
        tuple(int(part) for part in match if part)
        for match in _GLIBC_VERSION.findall(_objdump(path))
    ]
    return max(versions, default=(0,))


def prune(binaries, is_payload):
    """Keep only the collected libraries the payload actually reaches.

    ``binaries`` is PyInstaller's TOC of (dest_name, src_path, typecode).
    ``is_payload(dest_name)`` marks the roots: extension modules, libpython
    and libraries shipped inside wheels. Starting from them, DT_NEEDED is
    followed through the collected binaries; host libraries end the walk.
    Returns (kept TOC, sorted list of host sonames reached).
    """
    by_name = {}
    for entry in binaries:
        by_name.setdefault(Path(entry[0]).name, entry)

    keep = set()
    host = set()
    missing = set()
    pending = [entry for entry in binaries if is_payload(entry[0])]
    while pending:
        entry = pending.pop()
        if entry[0] in keep:
            continue
        keep.add(entry[0])
        if not is_elf(Path(entry[1])):
            continue
        for soname in needed(Path(entry[1])):
            if soname in HOST_LIBS:
                host.add(soname)
            elif soname in by_name:
                pending.append(by_name[soname])
            else:
                missing.add(soname)

    if missing:
        raise SystemExit(
            "Libraries needed by the bundle but neither collected nor listed "
            f"as host libraries in linux_libs.HOST_LIBS: {sorted(missing)}"
        )
    kept = [entry for entry in binaries if entry[0] in keep]
    return kept, sorted(host)


def inspect_bundle(root: Path):
    """Check a built bundle directory and report its host dependencies.

    Every DT_NEEDED of every ELF file in the bundle must be either a file in
    the bundle or a listed host library, and no listed host library may be
    in the bundle. Returns (sorted host sonames, newest GLIBC version).
    """
    files = [path for path in root.rglob("*") if path.is_file() and is_elf(path)]
    present = {path.name for path in root.rglob("*")}

    shadowing = sorted(present & HOST_LIBS.keys())
    if shadowing:
        raise SystemExit(f"Host libraries were bundled: {shadowing}")

    host = set()
    missing = {}
    glibc = (0,)
    for path in files:
        for soname in needed(path):
            if soname in HOST_LIBS:
                host.add(soname)
            elif soname not in present:
                missing.setdefault(soname, []).append(str(path.relative_to(root)))
        glibc = max(glibc, glibc_requirement(path))

    if missing:
        lines = [f"  {name} (needed by {', '.join(users[:3])})" for name, users in sorted(missing.items())]
        raise SystemExit("Unresolved libraries in the bundle:\n" + "\n".join(lines))
    return sorted(host), glibc


def deb_depends(host_sonames, glibc) -> list[str]:
    packages = []
    for soname in host_sonames:
        package = HOST_LIBS[soname]
        if package == GLIBC:
            package = f"{GLIBC} (>= {'.'.join(map(str, glibc))})"
        if package not in packages:
            packages.append(package)
    return sorted(packages)


def rpm_requires(host_sonames, glibc) -> list[str]:
    requires = [f"{soname}()(64bit)" for soname in host_sonames
                if HOST_LIBS[soname] != GLIBC]
    requires.append(f"libc.so.6(GLIBC_{'.'.join(map(str, glibc))})(64bit)")
    return sorted(requires)
