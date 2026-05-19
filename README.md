# mMass

This is a fork of the official repository for mMass on Python3.

This version contains fixes that allow it to launch using modern Python and updated requirements. Currently it works on Linux.

Many thanks to Martin Strohalm for his hard work on the project over many years!

## Installation

mMass is now a fully pure-Python package (native C extensions were removed and replaced with Numba/SciPy), making it trivial to install via modern package managers like `uv` or `pip`.

### Linux (and MacOS / Windows)
We recommend using [uv](https://github.com/astral-sh/uv) or pip to install the package directly into a virtual environment.

```sh
# Clone the repository
git clone https://github.com/lukaszsobala/mMass.git
cd mMass

# Install via uv (creates a virtual environment automatically and is extremely fast)
uv pip install -e .

# Or using standard pip
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Depending on your Linux distribution, you may need system-level GUI dependencies installed for wxPython to build or run seamlessly. For example, on Debian/Ubuntu:
```sh
sudo apt-get install python3-dev libgtk-3-dev freeglut3-dev libwebkitgtk-?.0-dev libjpeg-dev libpng-dev libtiff-dev libsdl-dev libnotify-dev libsm-dev
```

### Running the application
Once installed, the CLI wrapper is available globally within your virtual environment:

```sh
mmass
```

You can also run it generically:

```sh
python mmass.py
```

## Packaging
Because the legacy C extensions have been removed, pre-building ABI-specific wheels targeting `manylinux` arrays via Docker is **no longer required**. 

Simply build it using modern Python buildup tools:
```sh
pip install build
python -m build
```
The universal wheel and source dist will be produced natively in `dist/`.

## Contributing

Issues can be file in the GitHub bug tracker.  PRs welcomed!

## Release procedure

* Not regulated yet

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
