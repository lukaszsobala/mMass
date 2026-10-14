"""Version information of the Windows executables.

Windows keeps a version twice: as four 16-bit numbers (the FILEVERSION and
PRODUCTVERSION of a version resource, NSIS's VIProductVersion), which is what
compares, and as text, which is what Explorer's Details tab shows. A
pre-release such as 7.0.0-beta34 has no numbers of its own, so it gets those of
the release it leads to (7.0.0.0) and the pre-release flag, and the text keeps
the full version.

Used by mMass.spec (the version resource of mMass.exe) and by
build_windows_installer.py (that of the installer).
"""

from __future__ import annotations

import re
from pathlib import Path

COMPANY_NAME = "mMass Project"
COPYRIGHT = "GPL-3.0-or-later"

_VS_FF_PRERELEASE = 0x2


def read_project_version(project_root: Path) -> str:
    pyproject = project_root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Could not find version in {pyproject}")
    return match.group(1)


def numeric_version(version: str) -> tuple[int, int, int, int]:
    """The four numbers of a version such as 7.0.0-beta34: (7, 0, 0, 0)."""

    match = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?", version)
    if not match:
        raise ValueError(f"Not a version: {version!r}")
    numbers = tuple(int(part or 0) for part in match.groups())
    if any(number > 0xFFFF for number in numbers):
        raise ValueError(f"Version numbers must be below 65536: {version!r}")
    return numbers


def is_prerelease(version: str) -> bool:
    return re.fullmatch(r"[\d.]+", version) is None


def version_resource(version: str):
    """The version resource of mMass.exe, for the EXE(version=...) of a spec."""

    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = numeric_version(version)
    strings = [
        ("CompanyName", COMPANY_NAME),
        ("FileDescription", "mMass"),
        ("FileVersion", version),
        ("InternalName", "mMass"),
        ("LegalCopyright", COPYRIGHT),
        ("OriginalFilename", "mMass.exe"),
        ("ProductName", "mMass"),
        ("ProductVersion", version),
    ]
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=numbers,
            prodvers=numbers,
            mask=0x3F,
            flags=_VS_FF_PRERELEASE if is_prerelease(version) else 0,
            OS=0x40004,  # VOS_NT_WINDOWS32
            fileType=0x1,  # VFT_APP
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            # 0409: US English, 04B0 = 1200: Unicode
            StringFileInfo(
                [StringTable("040904B0", [StringStruct(k, v) for k, v in strings])]
            ),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )
