import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

sys.path.insert(0, SPECPATH)
import linux_libs  # noqa: E402


PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]

datas = [
    (str(PROJECT_ROOT / "src" / "gui" / "configs"), "gui/configs"),
    (str(PROJECT_ROOT / "license.txt"), "."),
    (str(PROJECT_ROOT / "User Guide.pdf"), "."),
]
datas += collect_data_files("xdgenvpy")

# See the Windows spec: PyInstaller's own hooks collect numba and llvmlite.
hiddenimports = []

# Guards against stray transitive imports, as in the Windows and macOS specs.
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


def _is_payload(dest_name):
    # extension modules and the libraries wheels ship sit in package
    # directories; the system libraries PyInstaller pulls in sit at the top
    return "/" in dest_name or Path(dest_name).name.startswith("libpython")


# numba's TBB threading layer needs libtbb, which neither the bundle nor most
# hosts have; without the module numba uses its OpenMP or workqueue layer
a.binaries = [b for b in a.binaries if "numba/np/ufunc/tbbpool" not in b[0]]

# Drop the GTK stack and other host libraries (see linux_libs.py).
a.binaries, _host = linux_libs.prune(a.binaries, _is_payload)
print("Host libraries used by the bundle:", " ".join(_host))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    # lowercase like the pip console script; it is also the GTK program name,
    # so the window matches mmass.desktop
    name="mmass",
    debug=False,
    bootloader_ignore_signals=False,
    # stripping auditwheel-patched libraries (numpy.libs) corrupts them
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
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
    upx=False,
    upx_exclude=[],
    name="mmass",
)
