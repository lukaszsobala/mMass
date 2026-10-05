#!/usr/bin/env bash
# Install the packages needed to build the wxPython wheel and the Linux
# packages of mMass. Meant for the almalinux:9 build container: its glibc
# (2.34), GTK and libstdc++ set the oldest system the packages run on, and
# Enterprise Linux 9 is the oldest target. Run as root or with sudo available.
#
# Deliberately absent: the -devel packages of webkit2gtk, gstreamer, SDL2,
# libnotify, libsecret, libcurl, libjpeg and libtiff. mMass uses only core wx,
# wx.aui and wx.grid, so without them wxWidgets builds without the features
# that would add host dependencies, and uses its built-in image libraries
# (whose sonames differ between distributions) instead of the system ones.

set -euo pipefail

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

$SUDO dnf install -y -q \
    binutils \
    file \
    findutils \
    gcc-c++ \
    git \
    gtk3-devel \
    gzip \
    jq \
    libSM-devel \
    libXtst-devel \
    make \
    mesa-libGL-devel \
    mesa-libGLU-devel \
    tar \
    which \
    xorg-x11-server-Xvfb
