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