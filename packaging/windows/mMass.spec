from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules


PROJECT_ROOT = Path(__file__).resolve().parents[2]

datas = [
    (str(PROJECT_ROOT / "src" / "gui" / "configs"), "gui/configs"),
    (str(PROJECT_ROOT / "license.txt"), "."),
]
datas += collect_data_files("xdgenvpy")

hiddenimports = []
hiddenimports += collect_submodules("numba")
hiddenimports += collect_submodules("scipy")


a = Analysis(
    [str(PROJECT_ROOT / "src" / "mmass_app" / "app.py")],
    pathex=[str(PROJECT_ROOT / "src"), str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
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
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="mMass",
)