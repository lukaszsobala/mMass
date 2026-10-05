#!/usr/bin/env python3
"""Replace wxPython's Linux configure options for the wxWidgets build.

wxPython's buildtools/build_wxwidgets.py adds ``--with-sdl`` on every
non-macOS platform and otherwise lets configure pick up whatever optional
libraries the build host has. For a relocatable bundle that is the wrong
default: each system library wx links against becomes a dependency of the
installed package, and the image libraries in particular have different
sonames on different distributions (libjpeg.so.8 vs .62, libtiff.so.5 vs .6).

The image libraries are therefore built in (as wxPython already does on macOS
and Windows), and features mMass does not use are switched off.
"""

import sys
from pathlib import Path

ANCHOR = 'wxpy_configure_opts.append("--with-sdl")'

LINUX_OPTIONS = [
    # built-in copies: symbol-prefixed, so they never clash with the system
    # copies the host's GTK loads
    "--with-libjpeg=builtin",
    "--with-libpng=builtin",
    "--with-libtiff=builtin",
    "--with-libwebp=builtin",
    "--with-regex=builtin",
    # features mMass does not use, and which would each pull in a host library
    "--without-sdl",
    "--without-libnotify",
    "--without-libcurl",
    "--disable-spellcheck",
    "--without-libmspack",
    "--disable-mediactrl",
    "--disable-webview",
    "--disable-secretstore",
]


def main() -> int:
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    if text.count(ANCHOR) != 1:
        print(f"{path}: expected exactly one {ANCHOR!r}; the wxPython build "
              "scripts changed, so this patch needs revisiting.")
        return 1
    replacement = f"wxpy_configure_opts.extend({LINUX_OPTIONS!r})"
    path.write_text(text.replace(ANCHOR, replacement), encoding="utf-8")
    print(f"Patched {path}: {' '.join(LINUX_OPTIONS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
