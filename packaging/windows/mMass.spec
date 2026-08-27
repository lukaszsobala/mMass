from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]
APP_ICON = PROJECT_ROOT / "src" / "gui" / "images" / "msw" / "icon.ico"
APP_MANIFEST = Path(SPECPATH) / "mMass.manifest"

datas = [
    (str(PROJECT_ROOT / "src" / "gui" / "configs"), "gui/configs"),
    (str(PROJECT_ROOT / "license.txt"), "."),
    (str(PROJECT_ROOT / "User Guide.pdf"), "."),
]
datas += collect_data_files("xdgenvpy")

# Nothing to force in: PyInstaller's bundled hooks already collect numba and
# llvmlite correctly. A blanket collect_submodules("numba") would additionally
# pull in numba.tests, which imports pandas/matplotlib/pytest when they happen
# to be present in the build environment -- making the bundle depend on what is
# incidentally installed on the build machine.
hiddenimports = []

# SciPy is not a runtime dependency (mspy.calculations grows its own local
# maxima kernel); exclude it so a stray transitive import cannot drag ~70 MB of
# DLLs and Python back into the bundle.
#
# Matplotlib is only there because pyopenms declares it: it is used solely by
# pyopenms/plotting.py, which pyopenms/__init__.py never imports and which does
# its matplotlib imports inside the plotting functions themselves. mMass calls
# neither, so excluding it is safe -- verified by importing pyopenms and
# constructing MSExperiment/FileHandler with matplotlib blocked.
#
# Note that pandas cannot be excluded the same way: pyopenms/__init__.py
# imports ._dataframes unconditionally, and that module imports pandas at the
# top level, so dropping pandas breaks "import pyopenms" outright.
excludes = ["scipy", "matplotlib"]


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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=str(APP_ICON),
    manifest=str(APP_MANIFEST),
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="mMass",
)