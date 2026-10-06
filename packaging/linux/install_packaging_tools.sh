#!/usr/bin/env bash
# Download the pinned packaging tools, checking their SHA-256:
#   nfpm         -- makes the .deb and .rpm (no dpkg-deb/rpmbuild needed)
#   appimagetool -- makes the .AppImage
#
# Usage: install_packaging_tools.sh <bin-dir>

set -euo pipefail

BIN_DIR="$(realpath -m "${1:?bin directory required}")"

NFPM_VERSION="2.47.0"
APPIMAGETOOL_VERSION="1.9.1"

case "$(uname -m)" in
    x86_64)
        NFPM_ARCH="x86_64"
        NFPM_SHA256="0660ca602b2d2d2ae4781a06c692b3eeb9d437ffea05b831d76e41f4a3188783"
        APPIMAGETOOL_ARCH="x86_64"
        APPIMAGETOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
        ;;
    aarch64)
        NFPM_ARCH="arm64"
        NFPM_SHA256="1c0f5f2999b9a974bfb04fdb0cc3306096de530ac5dbb25d739cc5f5219c919c"
        APPIMAGETOOL_ARCH="aarch64"
        APPIMAGETOOL_SHA256="f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158"
        ;;
    *)
        echo "Unsupported architecture: $(uname -m)" >&2
        exit 2
        ;;
esac

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
mkdir -p "$BIN_DIR"

download() {  # url sha256 destination
    curl -sSfL -o "$3" "$1"
    echo "$2  $3" | sha256sum -c -
}

download "https://github.com/goreleaser/nfpm/releases/download/v${NFPM_VERSION}/nfpm_${NFPM_VERSION}_Linux_${NFPM_ARCH}.tar.gz" \
    "$NFPM_SHA256" "$WORK_DIR/nfpm.tar.gz"
tar xzf "$WORK_DIR/nfpm.tar.gz" -C "$BIN_DIR" nfpm

download "https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-${APPIMAGETOOL_ARCH}.AppImage" \
    "$APPIMAGETOOL_SHA256" "$BIN_DIR/appimagetool"
chmod +x "$BIN_DIR/appimagetool"

echo "Installed nfpm ${NFPM_VERSION} and appimagetool ${APPIMAGETOOL_VERSION} to ${BIN_DIR}"
