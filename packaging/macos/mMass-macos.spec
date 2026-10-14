import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]
APP_ICON = PROJECT_ROOT / "src" / "gui" / "images" / "mac" / "icon.icns"

# The build wrapper injects the project version via the environment.
APP_VERSION = os.environ.get("MMASS_APP_VERSION", "0.0.0")

datas = [
    (str(PROJECT_ROOT / "src" / "gui" / "configs"), "gui/configs"),
    (str(PROJECT_ROOT / "license.txt"), "."),
    (str(PROJECT_ROOT / "User Guide.pdf"), "."),
]
datas += collect_data_files("xdgenvpy")

# Document icons go to Contents/Resources, where the Info.plist below finds
# them by file name.
DOC_ICONS = PROJECT_ROOT / "src" / "gui" / "images" / "mac"
datas += [(str(icon), ".") for icon in sorted(DOC_ICONS.glob("icon_doc_*.icns"))]


def _file_type(uti, description, extensions, conforms_to, icon):
    return {
        "UTTypeIdentifier": uti,
        "UTTypeDescription": description,
        "UTTypeConformsTo": conforms_to,
        "UTTypeIconFile": icon,
        "UTTypeTagSpecification": {"public.filename-extension": extensions},
    }


def _document_type(name, uti, icon, role, rank):
    return {
        "CFBundleTypeName": name,
        "LSItemContentTypes": [uti],
        "CFBundleTypeIconFile": icon,
        "CFBundleTypeRole": role,
        "LSHandlerRank": rank,
    }


# mMass's own formats are exported (declared and owned by mMass), the open
# data formats imported: mMass describes them but other programs may claim
# them, so it opens them only as an alternative (LSHandlerRank).
EXPORTED_TYPES = [
    ("org.mmass.msd", "mMass Spectrum Document", ["msd"], ["public.xml"], "icon_doc_msd.icns"),
    ("org.mmass.mses", "mMass Session", ["mses"], ["public.xml"], "icon_doc_mses.icns"),
]
IMPORTED_TYPES = [
    ("org.mmass.mzml", "mzML Mass Spectrometry Data", ["mzml"], ["public.xml"], "icon_doc_mzml.icns"),
    ("org.mmass.mzxml", "mzXML Mass Spectrometry Data", ["mzxml"], ["public.xml"], "icon_doc_mzxml.icns"),
    ("org.mmass.mzdata", "mzData Mass Spectrometry Data", ["mzdata"], ["public.xml"], "icon_doc_mzdata.icns"),
    ("org.mmass.mgf", "Mascot Generic Format Peak List", ["mgf"], ["public.plain-text"], "icon_doc_mgf.icns"),
    ("org.mmass.xy", "XY Spectrum Data", ["xy"], ["public.plain-text"], "icon_doc_xy.icns"),
]

# Nothing to force in: PyInstaller's bundled hooks already collect numba and
# llvmlite correctly. A blanket collect_submodules("numba") would additionally
# pull in numba.tests, which imports pandas/matplotlib/pytest when they happen
# to be present in the build environment -- making the bundle depend on what is
# incidentally installed on the build machine.
hiddenimports = []

# None of these is a runtime dependency: mspy.calculations grows its own local
# maxima kernel rather than calling SciPy, and nothing in mMass imports pandas
# or matplotlib. They are listed so that a stray transitive import cannot drag
# tens of MB of DLLs and Python back into the bundle.
#
# Matplotlib and pandas used to arrive with pyopenms, which declared both; that
# dependency is gone (Bruker fid reading and its TOF calibration are done in
# mspy.parser_bruker now), so a clean build environment should not have any of
# the three to begin with. The excludes stay as a guard, not as a fix.
excludes = ["scipy", "matplotlib", "pandas"]


a = Analysis(
    [str(PROJECT_ROOT / "src" / "mmass_app" / "app.py")],
    pathex=[str(PROJECT_ROOT / "src"), str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mMass",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,  # let macOS pass Finder "Open With" file args to argv
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
    icon=str(APP_ICON),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="mMass",
)

app = BUNDLE(
    coll,
    name="mMass.app",
    icon=str(APP_ICON),
    bundle_identifier="org.mmass.mMass",
    version=APP_VERSION,
    info_plist={
        "CFBundleName": "mMass",
        "CFBundleDisplayName": "mMass",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "NSHumanReadableCopyright": "GPL-3.0-or-later",
        "UTExportedTypeDeclarations": [_file_type(*t) for t in EXPORTED_TYPES],
        "UTImportedTypeDeclarations": [_file_type(*t) for t in IMPORTED_TYPES],
        "CFBundleDocumentTypes": [
            _document_type(description, uti, icon, "Editor", "Owner")
            for uti, description, _, _, icon in EXPORTED_TYPES
        ]
        + [
            _document_type(description, uti, icon, "Viewer", "Alternate")
            for uti, description, _, _, icon in IMPORTED_TYPES
        ]
        + [
            # generic text and XML exports, which mMass reads as well
            {
                "CFBundleTypeName": "Mass Spectrometry Data",
                "CFBundleTypeExtensions": ["xml", "asc", "txt"],
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
            },
        ],
    },
)
