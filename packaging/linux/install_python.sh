#!/usr/bin/env bash
# Create a virtual environment on a python-build-standalone CPython X.Y and
# print its bin directory.
#
# The distribution Pythons of the build system are too old, and the builds
# actions/setup-python uses are made on Ubuntu (22.04's needs glibc 2.35, one
# more than Enterprise Linux 9 has). python-build-standalone targets glibc
# 2.17 and comes with the shared libpython PyInstaller needs; uv (pinned
# below) installs it. uv marks its Pythons as externally managed, so packages
# go into a virtual environment.
#
# Usage: install_python.sh <X.Y> <venv-dir>

set -euo pipefail

VERSION="${1:?Python version (X.Y) required}"
VENV_DIR="$(realpath -m "${2:?virtual environment directory required}")"

UV_VERSION="0.13.0"
case "$(uname -m)" in
    x86_64) UV_SHA256="1468ebd5a5541121837c5a2817b9972ba6090fa6caa3d142620850a47fb75154" ;;
    aarch64) UV_SHA256="3ccfb6af6e242433eb552f7d9676abd5412c6595c497e990d9c8cb7b5bd4d2c3" ;;
    *) echo "Unsupported architecture: $(uname -m)" >&2; exit 2 ;;
esac

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
UV_ARCHIVE="uv-$(uname -m)-unknown-linux-gnu"
curl -sSfL -o "$WORK_DIR/uv.tar.gz" \
    "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${UV_ARCHIVE}.tar.gz"
echo "$UV_SHA256  $WORK_DIR/uv.tar.gz" | sha256sum -c - >&2
tar xzf "$WORK_DIR/uv.tar.gz" -C "$WORK_DIR"
UV="$WORK_DIR/$UV_ARCHIVE/uv"

# the interpreter must outlive this script: keep it beside the environment
export UV_PYTHON_INSTALL_DIR="${VENV_DIR}-python"
"$UV" python install "$VERSION" >&2
"$UV" venv --seed --python "$VERSION" "$VENV_DIR" >&2

echo "$VENV_DIR/bin"
