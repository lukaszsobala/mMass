#!/bin/sh
# Test the Linux packages on a clean system (run as root in a container of
# the distribution under test): the AppImage on the host's GTK, then the
# .deb or .rpm installed with its declared dependencies only.
#
# Usage: install_test.sh <directory with the packages>

set -eu

PACKAGES="$(cd "${1:?package directory required}" && pwd)"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
. /etc/os-release

case " ${ID} ${ID_LIKE:-} " in
    *" debian "*|*" ubuntu "*) family=deb ;;
    *" fedora "*|*" rhel "*) family=dnf ;;
    *" suse "*|*" opensuse "*) family=zypper ;;
    *) echo "Unsupported distribution: ${PRETTY_NAME:-$ID}" >&2; exit 2 ;;
esac
echo "== ${PRETTY_NAME:-$ID} ($(uname -m))"

# GTK 3 first: the AppImage relies on the host's, as on any desktop
case "$family" in
    deb)
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -q
        apt-get install -y -q xvfb gawk libgtk-3-0t64 \
            || apt-get install -y -q xvfb gawk libgtk-3-0 ;;
    dnf)
        dnf install -y -q gawk gtk3
        # Enterprise Linux 10 has no Xvfb any more
        if ! dnf install -y -q xorg-x11-server-Xvfb; then
            echo "No Xvfb on ${PRETTY_NAME:-$ID}: the GUI start is not tested"
            export MMASS_SMOKE_NO_GUI=1
        fi ;;
    zypper)
        # --force-resolution: busybox-gawk (which git-core, for one, pulls in)
        # conflicts with gawk and makes a non-interactive zypper give up
        zypper --non-interactive --quiet install --force-resolution \
            xorg-x11-server-Xvfb gawk libgtk-3-0 ;;
esac

echo "== AppImage"
appimage=$(ls "$PACKAGES"/*.AppImage)
# artifact downloads drop the executable bit
[ -x "$appimage" ] || chmod +x "$appimage"
# no FUSE in containers
APPIMAGE_EXTRACT_AND_RUN=1 sh "$HERE/smoke_test.sh" "$appimage"

echo "== system package"
case "$family" in
    deb)
        apt-get install -y -q "$(ls "$PACKAGES"/*.deb)" ;;
    dnf)
        dnf install -y -q "$(ls "$PACKAGES"/*.rpm)" ;;
    zypper)
        zypper --non-interactive --quiet install --allow-unsigned-rpm "$(ls "$PACKAGES"/*.rpm)" ;;
esac
sh "$HERE/smoke_test.sh" mmass

echo "== removal"
case "$family" in
    deb) apt-get remove -y -q mmass ;;
    dnf) dnf remove -y -q mmass ;;
    zypper) zypper --non-interactive --quiet remove mmass ;;
esac
test ! -e /opt/mmass
test ! -e /usr/bin/mmass

echo "All package tests passed on ${PRETTY_NAME:-$ID}."
