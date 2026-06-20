# mMass

This is a fork of the official repository for mMass on Python3. The purpose of this fork is to modernize the mMass codebase and make it maintainable, as well as fix bugs and add user-friendly functions.

This version contains fixes that allow it to launch using modern Python and updated requirements. So far it has been tested on Linux (`amd64` and `arm64`), Windows 11 (`x86_64`), and macOS on Apple Silicon (`arm64`).

Many thanks to Martin Strohalm for his hard work on the project over many years!

Thank you also to Dreaming Spires for the initial Python 3 port.

## Installation

mMass is now a fully pure-Python package (native C extensions were removed and replaced with Numba/SciPy), making it trivial to install via modern package managers like `uv` or `pip`.

### Linux, Windows and macOS
We recommend using [uv](https://github.com/astral-sh/uv) or pip to install the package directly into a virtual environment.

On Linux, this involves compiling `wxPython`, which will take at least 5 minutes on a fast computer, and up to 1 hour on slower CPUs. On Windows and macOS the compilation is not necessary — `wxPython` installs from a prebuilt wheel almost instantly.

Depending on your environment, you may need system-level GUI dependencies installed for `wxPython` to build or run seamlessly. For example, on Ubuntu 26.04 or Debian 13 (Trixie):
```bash
sudo apt install python3-dev libgtk-3-dev freeglut3-dev libwebkitgtk-6.0-dev libjpeg-dev libpng-dev libtiff-dev libsdl2-dev libnotify-dev libsm-dev
```

```bash
# Clone the repository
git clone https://github.com/lukaszsobala/mMass.git
cd mMass

# Install via uv
uv venv
source .venv/bin/activate
uv pip install -e .

# Or using standard pip
python -m venv .venv
source .venv/bin/activate
pip install -e .
```



### Running the application
Once installed, the CLI wrapper is available globally within your virtual environment:

```sh
mmass
```

You can also run it generically:

```sh
python src/mmass_app/app.py
```

### macOS: prefer running from source

On macOS the **recommended way to run mMass is directly from Python** (the `mmass`
command in your virtual environment, as above). It starts quickly, always reflects
the current code, and avoids the packaging caveats below.

The packaged `.app` / `.dmg` build also works, but note:

- **The first launch is slow** — the Dock icon may bounce for a minute or more
  before the window appears. This is a one-time cost: the build is not yet
  signed/notarized by Apple, so macOS Gatekeeper scans the entire bundle on first
  run, on top of the cold load of the scientific stack (Numba/LLVM/SciPy) and the
  first-run Numba cache warmup. **Subsequent launches are fast.** It is not frozen
  — give it time.
- **Gatekeeper may block it** on first open (*"can't be opened because Apple cannot
  check it…"* or *"is damaged"*). Because the build is unsigned, clear it once with
  any of:
  - right-click the app → **Open** → **Open**, or
  - **System Settings → Privacy & Security → Open Anyway**, or
  - `xattr -dr com.apple.quarantine /Applications/mMass.app`
- Always **copy the app into `/Applications`** before launching (don't run it from
  the mounted `.dmg`) — running from the read-only image triggers Gatekeeper *app
  translocation*, which can prevent the window from appearing.

### High-DPI scaling

The UI scales itself to your display automatically (Windows, MacOS, GNOME and KDE on
both X11 and Wayland). To override the detected factor, set `MMASS_UI_SCALE`
(e.g. `MMASS_UI_SCALE=2 mmass` for 200%), or set `MMASS_UI_AUTOSCALE=0` to
disable autodetection.

## Packaging

Simply build mMass using modern Python buildup tools:
```bash
uv pip install build
python -m build
```
The universal wheel and source dist will be produced natively in `dist/`.

### Windows installer

The repository includes a two-step Windows packaging flow:

1. Build a one-folder app bundle with PyInstaller.
2. Wrap the bundle into a standard installer `.exe` using NSIS.

Local build (Windows host):

```powershell
python -m pip install -e .
python -m pip install pyinstaller
# Install NSIS so `makensis` is on PATH.
python packaging/windows/build_windows_installer.py
```

Installer output is written to `build/installer/windows/`.

On Windows, runtime user configuration XML files are stored in
`%APPDATA%\\mMass` (with automatic migration from legacy install-local
`gui\\configs` files on first run).

During uninstall, user XML config is kept by default. The uninstaller offers an
optional checkbox to remove `%APPDATA%\\mMass\\*.xml`.

### macOS app and disk image

The repository builds an `arm64` `.app` bundle (PyInstaller) and wraps it into a
`.dmg`:

```sh
python packaging/macos/build_macos_dmg.py
```

The `.app` is written to `build/dist/macos/` and the `.dmg` to
`build/installer/macos/`. The build is currently **ad-hoc signed and not
notarized**, so end users hit a one-time Gatekeeper prompt and a slow first launch
(see the macOS notes under *Running the application*). Signing and notarization
with an Apple Developer ID — which removes both — is documented in
[`packaging/macos/SIGNING.md`](packaging/macos/SIGNING.md).

## Contributing

Issues can be file in the GitHub bug tracker.  PRs welcomed!

## Release procedure

* Still digging for bugs before taking it out of the beta stage.

## Disclaimer

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE.

For Research Use Only. Not for use in diagnostic procedures.

## License

This program and its documentation are Copyright 2005-2013 by Martin Strohalm, 2020-2021 by Dreaming Spires.

This program, along with all associated documentation, is free software;
you can redistribute it and/or modify it under the terms of the GNU General
Public License as published by the Free Software Foundation.
See the LICENSE.TXT file for details (and make sure that you have entirely
read and understood it!)

Please note in particular that, if you use this program, or ANY part of
it - even a single line of code - in another application, the resulting
application becomes also GPL. In other words, GPL is a "contaminating" license.

If you do not understand any portion of this notice, please seek appropriate
professional legal advice. If you do not or - for any reason - you can not
accept ALL of these conditions, then you must not use nor distribute this
program.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
(file LICENSE.TXT) for more details.

The origin of this software must not be misrepresented; you must not claim
that you wrote the original software. Altered source versions must be clearly
marked as such, and must not be misrepresented as being the original software.

This notice must not be removed or altered from any source distribution.
