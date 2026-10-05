#!/usr/bin/env bash
# Build a wxPython wheel for Linux from the PyPI sdist.
#
# PyPI has no Linux wheels of wxPython, and the per-distribution wheels on
# extras.wxpython.org stop at 4.2.x and cover x86_64 only, so the bundle
# builds use a wheel built here. It is slow (tens of minutes), which is why CI
# builds it once per wxPython version, Python version and architecture and
# keeps it as a release asset (see .github/workflows/linux-wxpython-wheel.yml).
#
# Usage: build_wxpython_wheel.sh <wxpython-version> <output-dir>
# The Python interpreter is taken from $PYTHON (default: python3).

set -euo pipefail

WX_VERSION="${1:?wxPython version required}"
OUT_DIR="$(realpath -m "${2:?output directory required}")"
PYTHON="${PYTHON:-python3}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

mkdir -p "$OUT_DIR"
cd "$WORK_DIR"

"$PYTHON" -m pip download --no-deps --no-binary :all: \
    "wxPython==${WX_VERSION}" -d .
tar xzf "wxpython-${WX_VERSION}.tar.gz"
SRC_DIR="$WORK_DIR/wxpython-${WX_VERSION}"

# build.py has no way to pass extra configure options to wxWidgets, so the one
# Linux-only line of the option list is swapped for ours.
"$PYTHON" "$SCRIPT_DIR/configure_wxpython.py" \
    "$SRC_DIR/buildtools/build_wxwidgets.py"

# -v: without it pip shows nothing of the build for tens of minutes
"$PYTHON" -m pip wheel -v --no-deps -w "$WORK_DIR/raw" "$SRC_DIR"

# The libraries are built with debug info (420 MB unpacked, _core alone
# 210 MB); strip it and repack, which also rewrites the RECORD hashes.
"$PYTHON" -m pip install wheel
"$PYTHON" -m wheel unpack -d "$WORK_DIR/unpacked" "$WORK_DIR"/raw/wxpython-*.whl
find "$WORK_DIR/unpacked" -type f -name '*.so*' -exec strip --strip-unneeded {} +
"$PYTHON" -m wheel pack -d "$OUT_DIR" "$WORK_DIR"/unpacked/wxpython-*

ls -l "$OUT_DIR"
