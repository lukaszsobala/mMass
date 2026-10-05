#!/usr/bin/env bash
# Install the Ubuntu packages needed to build the wxPython wheel and the
# Linux packages of mMass. Meant for the Ubuntu 22.04 build host (CI runner or
# an ubuntu:22.04 container); run as root or with sudo available.
#
# Deliberately absent: the -dev packages of webkit2gtk, gstreamer, SDL2,
# libnotify, libsecret, libcurl, libjpeg and libtiff. mMass uses only core wx,
# wx.aui and wx.grid, so without them wxWidgets builds without the features
# that would add host dependencies, and uses its built-in image libraries
# (whose sonames differ between distributions) instead of the system ones.

set -euo pipefail

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

export DEBIAN_FRONTEND=noninteractive
$SUDO apt-get update
$SUDO apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    file \
    libgl1-mesa-dev \
    libglu1-mesa-dev \
    libgtk-3-dev \
    libsm-dev \
    libxtst-dev \
    pkg-config
