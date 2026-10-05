# mMass

This is a fork of the official repository for mMass on Python3. The purpose of this fork is to modernize the mMass codebase and make it maintainable, as well as fix bugs and add user-friendly functions.

This version contains fixes that allow it to launch using modern Python and updated requirements. So far it has been tested to work on Linux (`amd64`, `arm64` and `riscv64`), Windows 11 (`x86_64`), and macOS on Apple Silicon (`arm64`).

Many thanks to Martin Strohalm for his hard work on the project over many years!

Thank you also to Dreaming Spires for the initial Python 3 port.

## Installation

The easiest way is a ready-made package from the
[releases page](https://github.com/lukaszsobala/mMass/releases):

| System | File | |
| --- | --- | --- |
| Windows (x64) | `mMass-<version>-windows-x64-setup.exe` | run the installer |
| macOS (Apple Silicon) | `mMass-<version>-macos-arm64.dmg` | see [macOS](#macos) |
| Ubuntu, Debian, Mint, ... | `mMass-<version>-linux-amd64.deb` / `-arm64.deb` | see [Linux](#linux) |
| Fedora, RHEL, AlmaLinux, Rocky, openSUSE, ... | `mMass-<version>-linux-x86_64.rpm` / `-aarch64.rpm` | see [Linux](#linux) |
| Any other Linux | `mMass-<version>-linux-x86_64.AppImage` / `-aarch64.AppImage` | see [Linux](#linux) |

mMass can also be [run from source](#running-from-source) with Python, on these
systems and others (it has been tested on Linux `riscv64` as well).

### Linux

The packages run on any distribution at least as new as RHEL/AlmaLinux/Rocky 9,
Ubuntu 22.04, Debian 12, Fedora 35 or openSUSE Leap 16, on `x86_64` and `aarch64`.
They need GTK 3, which every desktop has; the `.deb` and `.rpm` install whatever
else is missing.

```sh
sudo apt install ./mMass-<version>-linux-amd64.deb                          # Ubuntu, Debian
sudo dnf install ./mMass-<version>-linux-x86_64.rpm                         # Fedora, RHEL, Alma, Rocky
sudo zypper install --allow-unsigned-rpm ./mMass-<version>-linux-x86_64.rpm # openSUSE
```

mMass then appears in the applications menu, opens its file types (`.msd`,
`.mses`, mzML, mzXML, mzData, MGF) from the file manager, and runs from a
terminal as `mmass`. To remove it, use `sudo apt remove mmass`,
`sudo dnf remove mmass` or `sudo zypper remove mmass`; your settings in
`~/.config/mmass` are kept.

The AppImage needs no installation:

```sh
chmod +x mMass-<version>-linux-x86_64.AppImage
./mMass-<version>-linux-x86_64.AppImage
```

It uses FUSE, which desktop systems have; where it is missing (e.g. in a
container), add `--appimage-extract-and-run`. Tools such as
[Gear Lever](https://flathub.org/apps/it.mijorus.gearlever) can add it to the
applications menu.

<details>
<summary>Which systems the Linux packages are tested on</summary>

Every build is installed and started on AlmaLinux 9 and 10, Ubuntu 22.04 and
24.04, Debian 12 and 13, the latest Fedora and openSUSE Tumbleweed, on both
architectures. Exceptions: on AlmaLinux 10 the window is not opened (it has no
virtual display server for the test), and openSUSE is tested on `x86_64` only
(its `aarch64` mirrors proved unreliable).

</details>

### macOS

Copy `mMass.app` from the disk image into **Applications** and start it from
there. The app is not yet signed by Apple, so:

- **macOS may refuse to open it** the first time ("cannot be opened because Apple
  cannot check it", or "is damaged"). Right-click the app → **Open** → **Open**,
  or allow it in **System Settings → Privacy & Security → Open Anyway**.
- **The first launch is slow**: the Dock icon may bounce for a minute or more
  before the window appears. Later launches are fast.

<details>
<summary>Why, and other ways to deal with it</summary>

Because the build is unsigned, macOS Gatekeeper scans the whole bundle on the
first run, on top of the cold load of the scientific stack (Numba/LLVM) and the
first-run Numba cache warmup. The quarantine flag can also be cleared from a
terminal:

```sh
xattr -dr com.apple.quarantine /Applications/mMass.app
```

Don't run the app from the mounted `.dmg`: from the read-only image, macOS
moves it to a random location first (*app translocation*), which can stop the
window from appearing.

On macOS, running mMass [from source](#running-from-source) avoids all of this:
it starts quickly and always reflects the current code.

</details>

### Windows

Run the installer. Settings are stored in `%APPDATA%\mMass` (settings an older version kept
in its install folder are copied there on first start). Uninstalling keeps them, unless
you tick the option to remove them.

### Running from source

mMass is a pure-Python package (Numba instead of native C extensions), installed
with [uv](https://github.com/astral-sh/uv) or pip into a virtual environment:

```bash
git clone https://github.com/lukaszsobala/mMass.git
cd mMass

uv venv && source .venv/bin/activate && uv pip install -e .
# or: python -m venv .venv && source .venv/bin/activate && pip install -e .

mmass
```

On Windows and macOS wxPython installs from a prebuilt wheel. On Linux it is
compiled, which takes from 5 minutes on a fast computer to an hour on a slow
one, and needs development packages, e.g. on Ubuntu 26.04 or Debian 13:

```bash
sudo apt install python3-dev libgtk-3-dev freeglut3-dev libwebkitgtk-6.0-dev libjpeg-dev libpng-dev libtiff-dev libsdl2-dev libnotify-dev libsm-dev
```

`python src/mmass_app/app.py` also starts mMass from a checkout.

## Using mMass

Documents, Bruker dataset folders or a saved session (`.mses`) given on the
command line are opened at startup:

```sh
mmass spectrum.mzML spectrum2.msd bruker_dataset/
mmass --help
```

Two commands work without the GUI: `mmass convert` converts documents (and
draws spectra as images), and `mmass process` runs processing steps such as
baseline correction, smoothing and peak picking on many files at once:

```sh
mmass convert spectrum.mzML spectrum.msd
mmass process *.mzML --baseline --smooth --find-peaks -f csv --peak-list -d peaks
```

<details>
<summary>Converting from the command line</summary>

`mmass convert` uses the spectrum settings of the GUI for images:

```sh
mmass convert spectrum.mzML spectrum.msd
mmass convert *.mzML bruker_dataset/ -f png -d images --size 1920x1080
mmass convert run.mzML scan.txt --scan 42   # one spectrum of an LC-MS run
mmass convert --help
```

Outputs are msd, mzML, mzXML, text (txt/xy/asc/csv; the profile, or the peak list with
`--peak-list`), MGF (peak list) and images (PNG, JPEG, TIFF, BMP, SVG; light by default, `--dark`
for a dark background, `--range 400-1500` to show part of the spectrum). A conversion that
cannot work, such as a session or a FASTA file into a spectrum format, or several spectra into
one text file, is refused with the reason. Image output needs a display; on a headless machine run
it under `xvfb-run`.

</details>

<details>
<summary>Processing from the command line</summary>

`mmass process` runs processing steps, in the order given, before writing the result:

```sh
mmass process sample.mzML --baseline --smooth --find-peaks sample.msd
mmass process *.mzML --find-peaks -f csv --peak-list --columns mz,intensity,charge,envarea -d peaks
mmass process spectra/*.msd --crop 500-3000 --find-peaks --in-place --dry-run
mmass process run.mzML --find-peaks --preset Default --set snThreshold=10 -f mzml -d picked
mmass process --show-settings
```

The steps are `--crop LOW-HIGH`, `--baseline`, `--smooth`, `--find-peaks`, `--deisotope` and
`--math OPERATION`, where the operation is `normalize`, `multiply` (by the `math.multiplier`
setting) or `squareroot` (`sqrt`); math between spectra is left to the GUI. The steps use your own
settings from the Processing panel; `--preset NAME` starts from saved presets instead (`Default` is
the built-in settings, the same on every computer), and `--set` changes single settings for this run
only, e.g. `--set snThreshold=10` (a key that two sections share needs its section, as in
`baseline.preservePeaks`). `--show-settings` prints what the steps would use.

A recipe file holds the steps and settings, so that the same processing can be run on batch after
batch. It lists them one per line, as on the command line without the dashes:

```sh
# MALDI peptides, as a peak list
preset MALDI-TOF Peptides
set snThreshold=8        # a little more sensitive than the preset

crop 600-4000
baseline
smooth
find-peaks
math normalize

peak-list
columns mz, intensity, charge, envarea
```

```sh
mmass process plate1/*.mzML --recipe peptides.recipe -f csv -d plate1-peaks
```

A recipe runs where `--recipe` stands among the other options, which can add steps before or after
it or change its settings (a later `--set` wins). It says what to do with each spectrum, not which
files to read or where to write, so `--format`, `--output`, `--output-dir`, `--in-place` and the like stay
on the command line.

Each input is processed on its own and written to its own output, so a file that fails does not stop
the others. An LC-MS run written whole has every scan processed. Results go to a new file unless
`--in-place` is given, which rewrites msd, txt/xy/asc and single-spectrum MGF files. Each is replaced
only once it has been processed and written completely. mzML and mzXML files are never rewritten,
since mMass would drop the metadata it does not read. Steps whose results the output cannot
hold are refused, e.g. `--find-peaks` into a text profile. `--dry-run` reads and processes every
input and reports what would be written, without writing anything.

Both commands can write one input to standard output with `-o -` and the format given by `--format`,
e.g. `mmass process sample.mzML --find-peaks --peak-list -f csv -o - | sort -t, -k2 -gr`. They exit
with 0 when every input was written, 1 when some could not be, and 2 when the arguments are wrong.

</details>

### Configuration files

Settings and libraries are JSON, stored per user:

| Platform | Location |
| --- | --- |
| Linux / BSD | `$XDG_CONFIG_HOME/mmass` (usually `~/.config/mmass`) |
| macOS | `~/Library/Application Support/mMass` |
| Windows | `%APPDATA%\mMass` |

`config.json` holds settings; the seven libraries (`monomers`, `modifications`,
`enzymes`, `presets`, `references`, `compounds`, `mascot`) sit beside it. Set
`MMASS_CONFIG_DIR` to override the location on any platform — useful for a
portable install, or to point a second machine at a shared directory.

<details>
<summary>Settings from mMass versions before 7.0</summary>

Releases before 7.0 used XML. Each file is migrated once, automatically, on
first launch: the values are rewritten as JSON and the original is renamed to
`<name>.xml.migrated` rather than deleted, so nothing is lost and you can roll
back by removing the `.json` and dropping the `.migrated` suffix.

If you keep a config file symlinked at a shared location (a partition mounted
from another OS, a network drive), migration writes the JSON next to the link
target and leaves a symlink in the config directory, so the sharing survives.
The original XML on the share is left untouched, so another machine still
running an older mMass keeps working.

The compound and reference library editors import either format, so libraries
shared by other mMass users still load whether they are XML or JSON.

</details>

### High-DPI scaling

The UI scales itself to your display automatically (Windows, macOS, GNOME and KDE on
both X11 and Wayland). To override the detected factor, set `MMASS_UI_SCALE`
(e.g. `MMASS_UI_SCALE=2 mmass` for 200%), or set `MMASS_UI_AUTOSCALE=0` to
disable autodetection.

## Building packages

The release packages are built by the GitHub workflows in `.github/workflows/`.
A wheel and source distribution are built with:

```bash
uv pip install build
python -m build
```

<details>
<summary>Windows installer</summary>

A one-folder app bundle is built with PyInstaller and wrapped into an installer
`.exe` with NSIS. On a Windows host:

```powershell
python -m pip install -e .
python -m pip install pyinstaller
# Install NSIS so `makensis` is on PATH.
python packaging/windows/build_windows_installer.py
```

The installer is written to `build/installer/windows/`.

</details>

<details>
<summary>macOS app and disk image</summary>

An `arm64` `.app` bundle (PyInstaller) is built and wrapped into a `.dmg`:

```sh
python packaging/macos/build_macos_dmg.py
```

The `.app` is written to `build/dist/macos/` and the `.dmg` to
`build/installer/macos/`. The build is **ad-hoc signed and not notarized**.
Signing and notarization with an Apple Developer ID, which removes the
Gatekeeper prompt and the slow first launch, is documented in
[`packaging/macos/SIGNING.md`](packaging/macos/SIGNING.md).

</details>

<details>
<summary>Linux packages</summary>

The packages hold a PyInstaller bundle (installed to `/opt/mmass`, with `mmass`
on the `PATH`) that uses the system's GTK 3 and glibc. They are built on
AlmaLinux 9, which sets the oldest system they run on (glibc 2.34).

They are built by `.github/workflows/linux-packages.yml` in an `almalinux:9`
container, with a [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
Python. PyPI has no Linux wheels of wxPython, so
`.github/workflows/linux-wxpython-wheel.yml` builds one from the sdist (without
the wxWidgets features mMass does not use, and with built-in image libraries)
once per wxPython version, Python version and architecture, and keeps it as an
asset of a `wxpython-<version>-linux-r<revision>` prerelease for later builds;
the versions are set in `packaging/linux/wxpython-wheel.env`.

Local build, in an `almalinux:9` container (`docker run -it -v "$PWD:/src" -w /src almalinux:9`):

```sh
packaging/linux/install_build_deps.sh
packaging/linux/install_packaging_tools.sh /usr/local/bin   # nfpm, appimagetool
export PATH="$(packaging/linux/install_python.sh 3.14 /opt/venv):$PATH"
packaging/linux/build_wxpython_wheel.sh 4.3.1 wheelhouse    # slow; or reuse a wheel
python -m pip install wheelhouse/wxpython-*.whl -e . pyinstaller
python packaging/linux/build_linux_packages.py
packaging/linux/smoke_test.sh build/dist/linux/mmass/mmass
```

Then, to install and run the packages on a clean system:

```sh
docker run --rm -v "$PWD:/src:ro" ubuntu:24.04 \
    sh /src/packaging/linux/install_test.sh /src/build/installer/linux
```

The bundle is written to `build/dist/linux/` and the packages to
`build/installer/linux/`. Which libraries the bundle takes from the host, and
the package dependencies that follow from them, are listed in
`packaging/linux/linux_libs.py`. The build fails if the bundle needs a library
that is neither bundled nor listed there, a glibc newer than 2.34, or reports a
version other than the one in `pyproject.toml` (remove a stale
`mMass.egg-info` and reinstall if it does).

</details>

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

### Third-party code

The Bruker flex (XMASS) TOF-to-m/z calibration in
[`src/mspy/parser_bruker.py`](src/mspy/parser_bruker.py) is derived from
[readBrukerFlexData](https://github.com/sgibb/readBrukerFlexData/) by Sebastian
Gibb, the reader behind MALDIquant: the interpretation of the `##$NTBCal`
calibration block, the cubic flight-time model and the `##$HPCStr` High
Precision Calibration correction all follow that package. readBrukerFlexData is
licensed GPL (>= 3), which is compatible with mMass' own GPL-3.0-or-later; the
file itself carries the details.
