# -------------------------------------------------------------------------
#     Copyright (C) 2005-2013 Martin Strohalm <www.mmass.org>

#     This program is free software; you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation; either version 3 of the License, or
#     (at your option) any later version.

#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#     GNU General Public License for more details.

#     Complete text of GNU GPL can be found in the file LICENSE.TXT in the
#     main directory of the program.
# -------------------------------------------------------------------------


# load libs
import sys
import os
import copy
import json
import tempfile
import xml.dom.minidom
from importlib import resources
from typing import SupportsIndex
try:
    from xdgenvpy import XDGPackage  # type: ignore[import-untyped]
except ImportError:
    from xdgenvpy.xdgenv import XDGPackage  # type: ignore[import-untyped]


MODULE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_default_config_source_dir():
    """Return location of bundled default config XML files."""

    return os.path.join(MODULE_DIR, "configs")


def get_default_config_source_path(filename):
    return os.path.join(get_default_config_source_dir(), filename)


def copy_default_config_file(filename, destination):
    """Copy bundled default XML config to destination.

    Uses package resources first so installed distributions do not depend on
    source-tree paths.
    """

    try:
        resource = resources.files("gui").joinpath("configs", filename)
        with resources.as_file(resource) as source_path:
            with open(source_path, "rb") as src, open(destination, "wb") as dst:
                dst.write(src.read())
        return True
    except Exception:
        pass

    try:
        source_path = get_default_config_source_path(filename)
        with open(source_path, "rb") as src, open(destination, "wb") as dst:
            dst.write(src.read())
        return True
    except Exception:
        return False


def _currentUmask():
    """Read the process umask without leaving it changed."""

    mask = os.umask(0)
    os.umask(mask)
    return mask


def write_file_atomically(path, data):
    """Write bytes to path via a temp file in the same dir, then os.replace().

    A truncating in-place write leaves a half-written file behind if the
    process dies or the disk fills mid-write; for config.xml that means the
    next launch cannot parse it. os.replace() is atomic on POSIX and on
    Windows, so readers only ever see the old file or the complete new one.
    """

    # Resolve symlinks first: os.replace() onto a symlink would replace the
    # LINK with a regular file, silently detaching a config the user
    # deliberately pointed at shared or external storage. Writing through to
    # the link target keeps that setup intact, matching what a plain open()
    # used to do.
    path = os.path.realpath(path)

    directory = os.path.dirname(os.path.abspath(path))
    handle, tmppath = tempfile.mkstemp(
        dir=directory, prefix=".%s." % os.path.basename(path), suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        # mkstemp() always creates 0600; keep whatever mode the file already
        # had, or fall back to the usual umask-derived mode for a new one
        try:
            os.chmod(tmppath, os.stat(path).st_mode & 0o7777)
        except OSError:
            os.chmod(tmppath, 0o666 & ~_currentUmask())

        os.replace(tmppath, path)
        return True
    except Exception:
        try:
            os.unlink(tmppath)
        except OSError:
            pass
        return False


def get_legacy_windows_config_dir():
    """Return legacy Windows config directory located next to gui package."""

    confdir = os.path.sep
    for folder in os.path.dirname(os.path.realpath(__file__)).split(os.path.sep)[:-1]:
        path = os.path.join(confdir, folder)
        if os.path.isdir(path):
            confdir = path
        if os.path.isfile(path):
            break
    return os.path.join(confdir, "configs")

# SET VERSION
# -----------

try:
    import importlib.metadata
    version = importlib.metadata.version("mmass")
except Exception:
    try:
        import re
        pyproject_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pyproject.toml")
        with open(pyproject_path, "r", encoding="utf-8") as f:
            _m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.MULTILINE)
            version = _m.group(1) if _m else "unknown"
    except Exception:
        version = "unknown"
nightbuild = ""


# SET CONFIG FOLDER
# -----------------

# An explicit override wins on every platform. Used by the test suite so a run
# can never read or migrate the developer's own settings, and useful for a
# portable install that keeps its config beside the program.
_config_dir_override = os.environ.get("MMASS_CONFIG_DIR")

if _config_dir_override:
    confdir = os.path.expanduser(_config_dir_override)
    try:
        os.makedirs(confdir, exist_ok=True)
    except Exception:
        pass

# set config folder for MAC OS X
elif sys.platform == "darwin":
    confdir = get_default_config_source_dir()
    support = os.path.expanduser("~/Library/Application Support/")
    userconf = os.path.join(support, "mMass")
    if os.path.exists(support) and not os.path.exists(userconf):
        try:
            os.mkdir(userconf)
        except Exception:
            pass
    if os.path.exists(userconf):
        confdir = userconf

# set config folder for Linux
elif sys.platform.startswith("linux") or sys.platform.startswith("freebsd"):
    confdir = get_default_config_source_dir()
    home = os.path.expanduser("~")
    userconf = XDGPackage("mmass").XDG_CONFIG_HOME
    if os.path.exists(home) and not os.path.exists(userconf):
        try:
            os.mkdir(userconf)
        except Exception:
            pass
    if os.path.exists(userconf):
        confdir = userconf

# set config folder for Windows
else:
    legacy_confdir = get_legacy_windows_config_dir()
    confdir = legacy_confdir

    appdata = os.environ.get("APPDATA")
    if appdata:
        userconf = os.path.join(appdata, "mMass")
        try:
            os.makedirs(userconf, exist_ok=True)
        except Exception:
            pass

        if os.path.exists(userconf):
            confdir = userconf

            # One-time migration from legacy install-local config files.
            try:
                if os.path.exists(legacy_confdir):
                    for filename in os.listdir(legacy_confdir):
                        # Both formats: a user who pinned MMASS_CONFIG_DIR at
                        # the install directory (the documented way to share a
                        # config between machines) already has .json files
                        # there, and skipping them would silently hand them a
                        # default profile the first time they unset it.
                        if not filename.lower().endswith((".xml", ".json")):
                            continue
                        source = os.path.join(legacy_confdir, filename)
                        target = os.path.join(userconf, filename)
                        if os.path.isfile(source) and not os.path.exists(target):
                            with open(source, "rb") as src, open(target, "wb") as dst:
                                dst.write(src.read())
            except Exception:
                pass

    if not os.path.exists(confdir):
        try:
            os.makedirs(confdir, exist_ok=True)
        except Exception:
            pass

if not os.path.exists(confdir):
    raise IOError("Configuration folder cannot be found!")


_auto_save_enabled = False

class ConfigList(list):
    def __setitem__(self, key, value):
        super(ConfigList, self).__setitem__(key, value)
        if _auto_save_enabled:
            saveConfig()
    def __delitem__(self, key):
        super(ConfigList, self).__delitem__(key)
        if _auto_save_enabled:
            saveConfig()
    def append(self, x):
        super(ConfigList, self).append(x)
        if _auto_save_enabled:
            saveConfig()
    def extend(self, x):
        super(ConfigList, self).extend(x)
        if _auto_save_enabled:
            saveConfig()
    def remove(self, x):
        super(ConfigList, self).remove(x)
        if _auto_save_enabled:
            saveConfig()
    def insert(self, i, x):
        super(ConfigList, self).insert(i, x)
        if _auto_save_enabled:
            saveConfig()
    def pop(self, i: SupportsIndex = -1):
        res = super(ConfigList, self).pop(i)
        if _auto_save_enabled:
            saveConfig()
        return res
    def clear(self):
        del self[:]

class ConfigDict(dict):
    def __init__(self, *args, **kwargs):
        super(ConfigDict, self).__init__(*args, **kwargs)
        for k, v in self.items():
            if isinstance(v, list) and not isinstance(v, ConfigList):
                super(ConfigDict, self).__setitem__(k, ConfigList(v))
            elif isinstance(v, dict) and not isinstance(v, ConfigDict):
                super(ConfigDict, self).__setitem__(k, ConfigDict(v))

    def __setitem__(self, key, value):
        if isinstance(value, list) and not isinstance(value, ConfigList):
            value = ConfigList(value)
        elif isinstance(value, dict) and not isinstance(value, ConfigDict):
            value = ConfigDict(value)
        super(ConfigDict, self).__setitem__(key, value)
        if _auto_save_enabled:
            saveConfig()

    def __delitem__(self, key):
        super(ConfigDict, self).__delitem__(key)
        if _auto_save_enabled:
            saveConfig()

# INIT DEFAULT VALUES
# -------------------

internal = {
    "canvasXrange": None,
}

main = {
    "appWidth": 1050,
    "appHeight": 620,
    "appMaximized": 0,
    "unlockGUI": 0,
    "layout": "default",
    "documentsWidth": 195,
    "documentsHeight": 195,
    "peaklistWidth": 300,
    "peaklistHeight": 195,
    "mzDigits": 4,
    "intDigits": 0,
    "ppmDigits": 1,
    "chargeDigits": 2,
    "dataPrecision": 32,
    "lastDir": "",
    "lastSeqDir": "",
    "errorUnits": "Da",
    "printQuality": 5,
    "useServer": 1,
    "serverPort": 65456,
    "reverseScrolling": 0,
    "macListCtrlGeneric": 1,
    "peaklistColumns": [
        "mz",
        "int",
        "envarea",
        "envint",
        "rel",
        "sn",
        "z",
        "fwhm",
        "resol",
    ],
    "cursorInfo": ["mz", "dist", "ppm", "z"],
    "updatesEnabled": 1,
    "updatesChecked": "",
    "updatesCurrent": version,
    "updatesAvailable": version,
    # newest version the user asked not to be reminded about again; the
    # startup notification stays silent for it and for anything older
    "updatesSkipped": "",
    "latestVersionUrl": "https://api.github.com/repos/lukaszsobala/mMass/releases",
}

recent = []

colours = [
    [16, 71, 185],
    [50, 140, 0],
    [241, 144, 0],
    [76, 199, 197],
    [143, 143, 21],
    [38, 122, 255],
    [38, 143, 73],
    [237, 187, 0],
    [120, 109, 255],
    [179, 78, 0],
    [128, 191, 189],
    [137, 136, 68],
    [200, 136, 18],
    [197, 202, 61],
    [123, 182, 255],
    [69, 67, 138],
    [24, 129, 131],
    [131, 129, 131],
    [69, 126, 198],
    [189, 193, 123],
    [127, 34, 0],
    [76, 78, 76],
    [31, 74, 145],
    [15, 78, 75],
    [79, 26, 81],
]

export = {
    "imageWidth": 750,
    "imageHeight": 500,
    "imageUnits": "px",
    "imageResolution": 72,
    "imageFontsScale": 1,
    "imageDrawingsScale": 1,
    "imageFormat": "PNG",
    "peaklistColumns": ["mz", "int"],
    "peaklistFormat": "ASCII",
    "peaklistSeparator": "tab",
    "spectrumSeparator": "tab",
    "spectrumFormat": "ASCII",
}

spectrum = {
    "xLabel": "m/z",
    "yLabel": "a.i.",
    "showGrid": 1,
    "showMinorTicks": 1,
    "showLegend": 1,
    "showPosBars": 1,
    "showGel": 1,
    "showGelLegend": 1,
    "showTracker": 1,
    "showNotations": 1,
    "showLabels": 1,
    "showAllLabels": 1,
    "showTicks": 1,
    "showDataPoints": 1,
    "showCursorImage": 1,
    "posBarSize": 7,
    "gelHeight": 19,
    "autoscale": 1,
    "normalize": 0,
    "overlapLabels": 0,
    "checkLimits": 1,
    "labelAngle": 90,
    "labelCharge": 1,
    "labelGroup": 0,
    "labelBgr": 1,
    "labelFontSize": 10,
    "axisFontSize": 10,
    "tickColour": [255, 75, 75],
    "tmpSpectrumColour": [255, 0, 0],
    "notationMarksColour": [0, 255, 0],
    "notationMaxLength": 40,
    "notationMarks": 1,
    "notationLabels": 0,
    "notationMZ": 0,
    "filterSize": 1.0,
}

match = {
    "tolerance": 0.2,
    "units": "Da",
    "ignoreCharge": 0,
    "filterAnnotations": 0,
    "filterMatches": 0,
    "filterUnselected": 0,
    "filterIsotopes": 1,
    "filterUnknown": 0,
}

processing = {
    "math": {
        "operation": "normalize",
        "multiplier": 1,
        "preservePeaks": 1,
    },
    "crop": {
        "lowMass": 500,
        "highMass": 5000,
    },
    "baseline": {
        "precision": 100,
        "offset": 0.25,
        "allowNegative": 0,
        "preservePeaks": 1,
    },
    "smoothing": {
        "method": "SG",
        "windowSize": 0.15,
        "cycles": 5,
        "preservePeaks": 1,
    },
    "peakpicking": {
        "snThreshold": 25.0,
        "absIntThreshold": 0,
        "relIntThreshold": 0.0,
        "pickingHeight": 1.00,
        "baseline": 1,
        "smoothing": 0,
        "deisotoping": 1,
        "monoisotopic": 0,
        "removeShoulders": 0,
        "averagineType": "protein",
    },
    "deisotoping": {
        "maxCharge": 1,
        "massTolerance": 0.02,
        "intTolerance": 0.85,
        "isotopeShift": 0.0,
        "removeIsotopes": 1,
        "removeUnknown": 1,
        "labelEnvelope": "1st",
        "envelopeIntensity": "maximum",
        "envelopeNonIdeality": 0.40,
        "setAsMonoisotopic": 0,
        "convertToEnvelopes": 1,
    },
    "deconvolution": {
        "massType": 0,
        "groupWindow": 0.01,
        "groupPeaks": 1,
        "forceGroupWindow": 0,
    },
    "batch": {
        "math": 0,
        "crop": 0,
        "baseline": 0,
        "smoothing": 0,
        "peakpicking": 0,
        "deisotoping": 0,
        "deconvolution": 0,
        "stepOrder": ['smoothing', 'baseline', 'math', 'peakpicking', 'crop', 'deisotoping', 'deconvolution'],
    },
}

# Pristine in-code processing defaults for the dialog's "Default" preset,
# captured here before a user config.xml is ever loaded over `processing`.
processing_defaults = copy.deepcopy(processing)

calibration = {
    "fitting": "quadratic",
    "tolerance": 50,
    "units": "ppm",
    "statCutOff": 800,
}

sequence = {
    "editor": {
        "gridSize": 20,
    },
    "digest": {
        "maxMods": 1,
        "maxCharge": 1,
        "massType": 0,
        "enzyme": "Trypsin",
        "miscl": 1,
        "lowMass": 500,
        "highMass": 5000,
        "retainPos": 0,
        "allowMods": 0,
        "listTemplateAmino": "b.S.a [m]",
        "listTemplateCustom": "b . [ S ] . a [m]",
        "matchTemplateAmino": "h b.S.a [m]",
        "matchTemplateCustom": " h b . [ S ] . a [m]",
    },
    "fragment": {
        "maxMods": 1,
        "maxCharge": 1,
        "massType": 1,
        "fragments": ["a", "b", "y", "-NH3", "-H2O"],
        "maxLosses": 2,
        "filterFragments": 1,
        "listTemplateAmino": "b.S.a [m]",
        "listTemplateCustom": "b . [ S ] . a [m]",
        "matchTemplateAmino": "f h [m]",
        "matchTemplateCustom": "f h [m]",
    },
    "search": {
        "mass": 0,
        "maxMods": 1,
        "charge": 1,
        "massType": 0,
        "enzyme": "Trypsin",
        "semiSpecific": True,
        "tolerance": 0.2,
        "units": "Da",
        "retainPos": 0,
        "listTemplateAmino": "b.S.a [m]",
        "listTemplateCustom": "b . [ S ] . a [m]",
    },
}

massCalculator = {
    "ionseriesAgent": "H",
    "ionseriesAgentCharge": 1,
    "ionseriesPolarity": 1,
    "patternFwhm": 0.1,
    "patternIntensity": 100,
    "patternBaseline": 0,
    "patternShift": 0,
    "patternThreshold": 0.001,
    "patternShowPeaks": 1,
    "patternPeakShape": "gaussian",
}

massfilter = {}

massToFormula = {
    "countLimit": 1000,
    "massLimit": 3000,
    "charge": 1,
    "ionization": "H",
    "tolerance": 1.0,
    "units": "ppm",
    "formulaMin": "",
    "formulaMax": "",
    "autoCHNO": 1,
    "checkPattern": 1,
    "rules": ["HC", "NOPSC", "NOPS", "RDBE", "RDBEInt"],
    "HCMin": 0.1,
    "HCMax": 3,
    "NCMax": 4,
    "OCMax": 3,
    "PCMax": 2,
    "SCMax": 3,
    "RDBEMin": -1,
    "RDBEMax": 40,
    "PubChemScript": "https://pubchem.ncbi.nlm.nih.gov/search/search.cgi",
    "ChemSpiderScript": "https://www.chemspider.com/Search.aspx",
    "METLINScript": "https://metlin.scripps.edu/metabo_list_adv.php",
    "HMDBScript": "https://www.hmdb.ca/search",
    "LipidMAPSScript": "https://www.lipidmaps.org/data/structure/LMSDSearch.php",
}

massDefectPlot = {
    "xAxis": "mz",
    "yAxis": "standard",
    "nominalMass": "floor",
    "kendrickFormula": "CH2",
    "relIntCutoff": 0.0,
    "removeIsotopes": 0,
    "ignoreCharge": 1,
    "showNotations": 0,
    "showAllDocuments": 0,
}

compoundsSearch = {
    "massType": 0,
    "maxCharge": 1,
    "radicals": 0,
    "adducts": ["Na", "K"],
}

peakDifferences = {
    "aminoacids": 1,
    "dipeptides": 0,
    "sugars": 0,
    "permesugars": 0,
    "massType": 0,
    "tolerance": 0.1,
    "consolidate": 0,
}

comparePeaklists = {
    "compare": "peaklists",
    "tolerance": 0.2,
    "units": "Da",
    "ignoreCharge": 0,
    "ratioCheck": 0,
    "ratioDirection": 1,
    "ratioThreshold": 2,
    "alignmentStats": ["median", "mean", "min", "max", "range", "count", "duplicate"],
    "alignmentColumns": ["mz", "int", "sn", "fwhm", "resol", "envarea", "envint"],
    "alignmentDuplicates": "rows",
    "alignmentSeparator": "tab",
}

spectrumGenerator = {
    "fwhm": 0.1,
    "points": 10,
    "noise": 0,
    "forceFwhm": 0,
    "peakShape": "gaussian",
    "showPeaks": 1,
    "showOverlay": 0,
    "showFlipped": 0,
}

envelopeFit = {
    "loss": "H",
    "gain": "H{2}",
    "fit": "spectrum",
    "scaleMin": 0,
    "scaleMax": 10,
    "charge": 1,
    "fwhm": 0.01,
    "forceFwhm": 0,
    "peakShape": "gaussian",
    "autoAlign": 1,
    "relThreshold": 0.05,
}

mascot = {
    "common": {
        "title": "",
        "userName": "",
        "userEmail": "",
        "server": "Matrix Science",
        "searchType": "pmf",
        "filterAnnotations": 0,
        "filterMatches": 0,
        "filterUnselected": 0,
        "filterIsotopes": 1,
        "filterUnknown": 0,
    },
    "pmf": {
        "database": "SwissProt",
        "taxonomy": "All entries",
        "enzyme": "Trypsin",
        "miscleavages": 1,
        "fixedMods": [],
        "variableMods": [],
        "hiddenMods": 0,
        "proteinMass": "",
        "peptideTol": 0.1,
        "peptideTolUnits": "Da",
        "massType": "Monoisotopic",
        "charge": "1+",
        "decoy": 0,
        "report": "AUTO",
    },
    "sq": {
        "database": "SwissProt",
        "taxonomy": "All entries",
        "enzyme": "Trypsin",
        "miscleavages": 1,
        "fixedMods": [],
        "variableMods": [],
        "hiddenMods": 0,
        "peptideTol": 0.1,
        "peptideTolUnits": "Da",
        "msmsTol": 0.2,
        "msmsTolUnits": "Da",
        "massType": "Average",
        "charge": "1+",
        "instrument": "Default",
        "quantitation": "None",
        "decoy": 0,
        "report": "AUTO",
    },
    "mis": {
        "database": "SwissProt",
        "taxonomy": "All entries",
        "enzyme": "Trypsin",
        "miscleavages": 1,
        "fixedMods": [],
        "variableMods": [],
        "hiddenMods": 0,
        "peptideMass": "",
        "peptideTol": 0.1,
        "peptideTolUnits": "Da",
        "msmsTol": 0.2,
        "msmsTolUnits": "Da",
        "massType": "Average",
        "charge": "1+",
        "instrument": "Default",
        "quantitation": "None",
        "decoy": 0,
        "errorTolerant": 0,
        "report": "AUTO",
    },
}

profound = {
    "script": "https://prowl.rockefeller.edu/prowl-cgi/profound.exe",
    "title": "",
    "database": "NCBI nr",
    "taxonomy": "All taxa",
    "enzyme": "Trypsin",
    "miscleavages": 1,
    "fixedMods": [],
    "variableMods": [],
    "proteinMassLow": 0,
    "proteinMassHigh": 300,
    "proteinPILow": 0,
    "proteinPIHigh": 14,
    "peptideTol": 0.1,
    "peptideTolUnits": "Da",
    "massType": "Monoisotopic",
    "charge": "MH+",
    "ranking": "expect",
    "expectation": 1,
    "candidates": 10,
    "filterAnnotations": 0,
    "filterMatches": 0,
    "filterUnselected": 0,
    "filterIsotopes": 1,
    "filterUnknown": 0,
}

prospector = {
    "common": {
        "title": "",
        "script": "https://prospector.ucsf.edu/prospector/cgi-bin/mssearch.cgi",
        "searchType": "msfit",
        "filterAnnotations": 0,
        "filterMatches": 0,
        "filterUnselected": 0,
        "filterIsotopes": 1,
        "filterUnknown": 0,
    },
    "msfit": {
        "database": "SwissProt",
        "taxonomy": "All",
        "enzyme": "Trypsin",
        "miscleavages": 1,
        "fixedMods": [],
        "variableMods": [],
        "proteinMassLow": 0,
        "proteinMassHigh": 300,
        "proteinPILow": 0,
        "proteinPIHigh": 14,
        "peptideTol": 0.1,
        "peptideTolUnits": "Da",
        "massType": "Monoisotopic",
        "instrument": "MALDI-TOFTOF",
        "minMatches": 4,
        "maxMods": 1,
        "report": 5,
        "pfactor": 0.4,
    },
    "mstag": {
        "database": "SwissProt",
        "taxonomy": "All",
        "enzyme": "Trypsin",
        "miscleavages": 1,
        "fixedMods": [],
        "variableMods": [],
        "peptideMass": "",
        "peptideTol": 0.1,
        "peptideTolUnits": "Da",
        "peptideCharge": "1",
        "msmsTol": 0.2,
        "msmsTolUnits": "Da",
        "massType": "Monoisotopic",
        "instrument": "MALDI-TOFTOF",
        "maxMods": 1,
        "report": 5,
    },
}

links = {
    "mMassHomepage": "https://github.com/lukaszsobala/mMass",
    "mMassIssues": "https://github.com/lukaszsobala/mMass/issues",
    "mMassCite": "https://web.archive.org/web/20220307182056/http://www.mmass.org/donate/papers.php",
    "mMassDownload": "https://github.com/lukaszsobala/mMass/releases",
    "mMassWhatsNew": "https://github.com/lukaszsobala/mMass/releases",
    "biomedmstools": "https://ms.biomed.cas.cz/MSTools/",
    "blast": "https://www.ebi.ac.uk/Tools/blastall/",
    "clustalw": "https://www.ebi.ac.uk/Tools/clustalw/",
    "deltamass": "https://www.abrf.org/index.cfm/dm.home",
    "emblebi": "https://www.ebi.ac.uk/services/",
    "expasy": "https://www.expasy.org/",
    "fasta": "https://www.ebi.ac.uk/Tools/fasta33/",
    "matrixscience": "https://www.matrixscience.com/",
    "muscle": "https://phylogenomics.berkeley.edu/cgi-bin/muscle/input_muscle.py",
    "ncbi": "https://www.ncbi.nlm.nih.gov/Entrez/",
    "pdb": "https://www.rcsb.org/pdb/",
    "pir": "https://pir.georgetown.edu/",
    "profound": "https://prowl.rockefeller.edu/prowl-cgi/profound.exe",
    "prospector": "https://prospector.ucsf.edu/",
    "unimod": "https://www.unimod.org/",
    "uniprot": "https://www.uniprot.org/",
}

# Links whose URL is owned by the defaults above rather than by the user's
# config XML. Their values are force-synced on every launch: a stale value in
# an existing config (e.g. an old http:// URL) is ignored on load and dropped
# on save, so default updates reach existing installs. Only genuinely custom
# links (names not built into mMass) are read from / written to the user XML.
# "Retired" names are links that no longer exist and must never be restored.
_builtinLinks = frozenset(links)
_retiredLinks = frozenset({"mMassTwitter", "mMassForum", "mMassDonate"})


def isManagedLink(name):
    """Whether a link's URL is force-synced to the code default."""
    return name in _builtinLinks or name in _retiredLinks

replacements = {
    "sequences": {
        "general": {
            "pattern": r"^([A-Z0-9_]+[\.0-9]*)$",
            "url": "https://www.ncbi.nlm.nih.gov/protein/%s",
        },
        "gi": {
            "pattern": r"^gi\|?([0-9]+[\.0-9]*)$",
            "url": "https://www.ncbi.nlm.nih.gov/protein/%s",
        },
        "gb": {
            "pattern": r"^gb\|?([A-Z]{3}[0-9]{5}[\.0-9]*)$",
            "url": "https://www.ncbi.nlm.nih.gov/protein/%s",
        },
        "sp": {
            "pattern": r"^sp\|?([A-Z][A-Z0-9]+)$",
            "url": "https://www.uniprot.org/uniprot/%s",
        },
        "ref": {
            "pattern": r"^ref\|?([A-Z]{2}_[0-9]+[\.0-9]*)$",
            "url": "https://www.ncbi.nlm.nih.gov/protein/%s",
        },
    },
    "compounds": {
        "PubChemC": {
            "pattern": "CID([0-9]{1,10})",
            "url": "https://pubchem.ncbi.nlm.nih.gov/summary/summary.cgi?cid=%s",
        },
        "LipidMaps": {
            "pattern": "(LM[A-Z]{2}[0-9]{4}[0-9A-Z]{2}[0-9]{2})",
            "url": "https://www.lipidmaps.org/data/LMSDRecord.php?LMID=%s",
        },
        "NORINE": {
            "pattern": "(NOR[0-9]{5})",
            "url": "https://bioinfo.lifl.fr/norine/result.jsp?ID=%s",
        },
    },
}


# LOAD AND SAVE CONFIG FILE
# -------------------------


class _suspendAutoSave(object):
    """Pause config autosave for the duration of a bulk update.

    loadConfig() fills sections in field by field, and several values are only
    normalized after the raw string has been assigned (hex "rrggbb" -> [r,g,b],
    ";"-joined text -> list). With autosave live, the first such assignment
    fires saveConfig() over a half-converted section, which raises. Startup
    happens to be safe because autosave is still off, but any later reload
    would hit it.
    """

    def __enter__(self):
        global _auto_save_enabled
        self._previous = _auto_save_enabled
        _auto_save_enabled = False
        return self

    def __exit__(self, *exc_info):
        global _auto_save_enabled
        _auto_save_enabled = self._previous
        return False


def loadLegacyConfigXML(path):
    """Read a pre-7.0 config.xml into the live sections.

    Retained for the one-way migration to config.json (and for a user who
    restores an old profile years from now). Nothing writes this format any
    more -- see saveConfig() for the current one.
    """

    with _suspendAutoSave():
        _loadLegacyConfigXML(path)
        _validateConfig()


def _loadLegacyConfigXML(path):
    """Parse config XML and get data."""

    # parse XML
    document = xml.dom.minidom.parse(path)

    # main
    mainTags = document.getElementsByTagName("main")
    if mainTags:
        _getParams(mainTags[0], main)

        if not isinstance(main["cursorInfo"], list):
            main["cursorInfo"] = main["cursorInfo"].split(";")

        if not isinstance(main["peaklistColumns"], list):
            main["peaklistColumns"] = main["peaklistColumns"].split(";")

    # recent files
    recentTags = document.getElementsByTagName("recent")
    if recentTags:
        pathTags = recentTags[0].getElementsByTagName("path")
        if pathTags:
            del recent[:]
            for pathTag in pathTags:
                recent.append(pathTag.getAttribute("value"))

    # colours
    coloursTags = document.getElementsByTagName("colours")
    if coloursTags:
        colourTags = coloursTags[0].getElementsByTagName("colour")
        if colourTags:
            del colours[:]
            for colourTag in colourTags:
                col = colourTag.getAttribute("value")
                colours.append([int(c, 16) for c in (col[0:2], col[2:4], col[4:6])])

    # export
    exportTags = document.getElementsByTagName("export")
    if exportTags:
        _getParams(exportTags[0], export)

        if not isinstance(export["peaklistColumns"], list):
            export["peaklistColumns"] = export["peaklistColumns"].split(";")

    # spectrum
    spectrumTags = document.getElementsByTagName("spectrum")
    if spectrumTags:
        _getParams(spectrumTags[0], spectrum)

        if not isinstance(spectrum["tickColour"], list):
            col = spectrum["tickColour"]
            spectrum["tickColour"] = [
                int(c, 16) for c in (col[0:2], col[2:4], col[4:6])
            ]

        if not isinstance(spectrum["tmpSpectrumColour"], list):
            col = spectrum["tmpSpectrumColour"]
            spectrum["tmpSpectrumColour"] = [
                int(c, 16) for c in (col[0:2], col[2:4], col[4:6])
            ]

        if not isinstance(spectrum["notationMarksColour"], list):
            col = spectrum["notationMarksColour"]
            spectrum["notationMarksColour"] = [
                int(c, 16) for c in (col[0:2], col[2:4], col[4:6])
            ]

    # match
    matchTags = document.getElementsByTagName("match")
    if matchTags:
        _getParams(matchTags[0], match)

    # processing
    processingTags = document.getElementsByTagName("processing")
    if processingTags:

        mathTags = processingTags[0].getElementsByTagName("math")
        if mathTags:
            _getParams(mathTags[0], processing["math"])

        cropTags = processingTags[0].getElementsByTagName("crop")
        if cropTags:
            _getParams(cropTags[0], processing["crop"])

        baselineTags = processingTags[0].getElementsByTagName("baseline")
        if baselineTags:
            _getParams(baselineTags[0], processing["baseline"])

        smoothingTags = processingTags[0].getElementsByTagName("smoothing")
        if smoothingTags:
            _getParams(smoothingTags[0], processing["smoothing"])

        peakpickingTags = processingTags[0].getElementsByTagName("peakpicking")
        if peakpickingTags:
            _getParams(peakpickingTags[0], processing["peakpicking"])

        deisotopingTags = processingTags[0].getElementsByTagName("deisotoping")
        if deisotopingTags:
            _getParams(deisotopingTags[0], processing["deisotoping"])
            processing["deisotoping"]["envelopeNonIdeality"] = min(
                max(processing["deisotoping"]["envelopeNonIdeality"], 0.0), 1.0
            )

        # averagine model: written under <peakpicking> since 7.0.0-beta22, under
        # <deisotoping> before that -- fall back to the old spot so existing
        # configs keep their model
        picked = {"averagineType": ""}
        if peakpickingTags:
            _getParams(peakpickingTags[0], picked)
        if not picked["averagineType"] and deisotopingTags:
            legacy = {"averagineType": ""}
            _getParams(deisotopingTags[0], legacy)
            if legacy["averagineType"]:
                processing["peakpicking"]["averagineType"] = legacy["averagineType"]
        if processing["peakpicking"]["averagineType"] not in (
            "protein",
            "carbohydrate",
            "lipid",
        ):
            processing["peakpicking"]["averagineType"] = "protein"

        deconvolutionTags = processingTags[0].getElementsByTagName("deconvolution")
        if deconvolutionTags:
            _getParams(deconvolutionTags[0], processing["deconvolution"])

        batchTags = processingTags[0].getElementsByTagName("batch")
        if batchTags:
            _getParams(batchTags[0], processing["batch"])

            if not isinstance(processing["batch"]["stepOrder"], list):
                processing["batch"]["stepOrder"] = [
                    step
                    for step in processing["batch"]["stepOrder"].split(";")
                    if step
                ]

    # calibration
    calibrationTags = document.getElementsByTagName("calibration")
    if calibrationTags:
        _getParams(calibrationTags[0], calibration)

    # sequence
    sequenceTags = document.getElementsByTagName("sequence")
    if sequenceTags:

        editorTags = sequenceTags[0].getElementsByTagName("editor")
        if editorTags:
            _getParams(editorTags[0], sequence["editor"])

        digestTags = sequenceTags[0].getElementsByTagName("digest")
        if digestTags:
            _getParams(digestTags[0], sequence["digest"])

        fragmentTags = sequenceTags[0].getElementsByTagName("fragment")
        if fragmentTags:
            _getParams(fragmentTags[0], sequence["fragment"])

        searchTags = sequenceTags[0].getElementsByTagName("search")
        if searchTags:
            _getParams(searchTags[0], sequence["search"])

        if not isinstance(sequence["fragment"]["fragments"], list):
            sequence["fragment"]["fragments"] = sequence["fragment"]["fragments"].split(
                ";"
            )

    # mass calculator
    massCalculatorTags = document.getElementsByTagName("massCalculator")
    if massCalculatorTags:
        _getParams(massCalculatorTags[0], massCalculator)

    # mass to formula
    massToFormulaTags = document.getElementsByTagName("massToFormula")
    if massToFormulaTags:
        _getParams(massToFormulaTags[0], massToFormula)

        if not isinstance(massToFormula["rules"], list):
            massToFormula["rules"] = massToFormula["rules"].split(";")

    # mass defect plot
    massDefectPlotTags = document.getElementsByTagName("massDefectPlot")
    if massDefectPlotTags:
        _getParams(massDefectPlotTags[0], massDefectPlot)

    # compounds search
    compoundsSearchTags = document.getElementsByTagName("compoundsSearch")
    if compoundsSearchTags:
        _getParams(compoundsSearchTags[0], compoundsSearch)

        if not isinstance(compoundsSearch["adducts"], list):
            compoundsSearch["adducts"] = compoundsSearch["adducts"].split(";")

    # peak differences
    peakDifferencesTags = document.getElementsByTagName("peakDifferences")
    if peakDifferencesTags:
        _getParams(peakDifferencesTags[0], peakDifferences)

    # compare peaklists
    comparePeaklistsTags = document.getElementsByTagName("comparePeaklists")
    if comparePeaklistsTags:
        _getParams(comparePeaklistsTags[0], comparePeaklists)

        for key in ("alignmentStats", "alignmentColumns"):
            if not isinstance(comparePeaklists[key], list):
                value = comparePeaklists[key]
                comparePeaklists[key] = value.split(";") if value else []

    # spectrum generator
    spectrumGeneratorTags = document.getElementsByTagName("spectrumGenerator")
    if spectrumGeneratorTags:
        _getParams(spectrumGeneratorTags[0], spectrumGenerator)

    # envelope fit
    envelopeFitTags = document.getElementsByTagName("envelopeFit")
    if envelopeFitTags:
        _getParams(envelopeFitTags[0], envelopeFit)

    # mascot
    mascotTags = document.getElementsByTagName("mascot")
    if mascotTags:

        commonTags = mascotTags[0].getElementsByTagName("common")
        if commonTags:
            _getParams(commonTags[0], mascot["common"])

        pmfTags = mascotTags[0].getElementsByTagName("pmf")
        if pmfTags:
            _getParams(pmfTags[0], mascot["pmf"])

        sqTags = mascotTags[0].getElementsByTagName("sq")
        if sqTags:
            _getParams(sqTags[0], mascot["sq"])

        misTags = mascotTags[0].getElementsByTagName("mis")
        if misTags:
            _getParams(misTags[0], mascot["mis"])

        for key in ("pmf", "sq", "mis"):
            if not isinstance(mascot[key]["fixedMods"], list):
                mascot[key]["fixedMods"] = mascot[key]["fixedMods"].split(";")
            if not isinstance(mascot[key]["variableMods"], list):
                mascot[key]["variableMods"] = mascot[key]["variableMods"].split(";")

    # profound
    profoundTags = document.getElementsByTagName("profound")
    if profoundTags:
        _getParams(profoundTags[0], profound)

        if not isinstance(profound["fixedMods"], list):
            profound["fixedMods"] = profound["fixedMods"].split(";")
        if not isinstance(profound["variableMods"], list):
            profound["variableMods"] = profound["variableMods"].split(";")

    # prospector
    prospectorTags = document.getElementsByTagName("prospector")
    if prospectorTags:

        commonTags = prospectorTags[0].getElementsByTagName("common")
        if commonTags:
            _getParams(commonTags[0], prospector["common"])

        msfitTags = prospectorTags[0].getElementsByTagName("msfit")
        if msfitTags:
            _getParams(msfitTags[0], prospector["msfit"])

        mstagTags = prospectorTags[0].getElementsByTagName("mstag")
        if mstagTags:
            _getParams(mstagTags[0], prospector["mstag"])

        for key in ("msfit", "mstag"):
            if not isinstance(prospector[key]["fixedMods"], list):
                prospector[key]["fixedMods"] = prospector[key]["fixedMods"].split(";")
            if not isinstance(prospector[key]["variableMods"], list):
                prospector[key]["variableMods"] = prospector[key]["variableMods"].split(
                    ";"
                )

    # links
    linksTags = document.getElementsByTagName("links")
    if linksTags:
        linkTags = linksTags[0].getElementsByTagName("link")
        for linkTag in linkTags:
            name = linkTag.getAttribute("name")
            value = linkTag.getAttribute("value")
            # managed links keep the code default; only load custom links
            if not isManagedLink(name):
                links[name] = value


# ----


# Settings that are deliberately NOT persisted, as dotted paths. Two kinds:
#
#   * code-owned constants -- service URLs and HTML report templates. The
#     in-code value must win on every launch; persisting them would pin a
#     user's config to whatever shipped when they first ran the app, so they
#     would never pick up a corrected URL or template on upgrade.
#   * dead keys -- read somewhere (or nowhere) but never written by any GUI
#     control, so there is no user choice to remember.
#
# This list is the authority: the serializer skips exactly these and writes
# everything else, so a newly added setting is persisted automatically rather
# than having to be hand-added to a writer. tests/test_config_drift.py asserts
# the list still matches the code.
NOT_PERSISTED = frozenset(
    {
        # code-owned constants
        "main.latestVersionUrl",
        "massToFormula.PubChemScript",
        "massToFormula.ChemSpiderScript",
        "massToFormula.METLINScript",
        "massToFormula.HMDBScript",
        "massToFormula.LipidMAPSScript",
        "sequence.digest.listTemplateAmino",
        "sequence.digest.listTemplateCustom",
        "sequence.digest.matchTemplateAmino",
        "sequence.digest.matchTemplateCustom",
        "sequence.fragment.listTemplateAmino",
        "sequence.fragment.listTemplateCustom",
        "sequence.fragment.matchTemplateAmino",
        "sequence.fragment.matchTemplateCustom",
        "sequence.search.listTemplateAmino",
        "sequence.search.listTemplateCustom",
        # dead keys: no GUI control writes these
        "main.unlockGUI",
        "main.dataPrecision",
        "processing.peakpicking.monoisotopic",
        "massDefectPlot.xAxis",
    }
)

# bumped only when a change needs a migration step in _upgradeConfigData()
CONFIG_SCHEMA_VERSION = 2


def saveConfig(path=None):
    """Serialize the config sections to JSON."""

    if path is None:
        path = getConfigPath()

    data = {"schemaVersion": CONFIG_SCHEMA_VERSION}
    for name in _CONFIG_SECTIONS:
        section = globals()[name]
        if name == "links":
            # managed links are forced to the code default on every launch, so
            # only the user's own additions are worth storing
            data[name] = {
                key: value for key, value in section.items() if not isManagedLink(key)
            }
        else:
            data[name] = _stripExcluded(_plainCopy(section), name)

    try:
        encoded = json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False)
    except (TypeError, ValueError):
        return False

    return write_file_atomically(path, (encoded + "\n").encode("utf-8"))


def _stripExcluded(node, prefix):
    """Drop NOT_PERSISTED leaves from a plain copy of a section."""

    if not isinstance(node, dict):
        return node

    return {
        key: _stripExcluded(value, "%s.%s" % (prefix, key))
        for key, value in node.items()
        if "%s.%s" % (prefix, key) not in NOT_PERSISTED
    }


def loadConfig(path=None):
    """Read a JSON config and merge it over the in-code defaults."""

    if path is None:
        path = getConfigPath()

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("config root must be a JSON object")

    with _suspendAutoSave():
        _upgradeConfigData(data)
        _applySections(data)
        _validateConfig()


def _applySections(data):
    """Overlay a loaded payload onto the live sections."""

    for name in _CONFIG_SECTIONS:
        if name not in data:
            continue
        loaded = data[name]
        target = globals()[name]

        if isinstance(target, list):
            if isinstance(loaded, list):
                target[:] = loaded
        elif name == "links":
            # links the user added are not in the defaults, so the usual
            # "keys absent from target are dropped" rule would discard them
            if isinstance(loaded, dict):
                for key, value in loaded.items():
                    if isinstance(value, str) and not isManagedLink(key):
                        target[key] = value
        elif isinstance(loaded, dict):
            _mergeSection(target, loaded, name)


def _upgradeConfigData(data):
    """Bring an older on-disk payload up to CONFIG_SCHEMA_VERSION in place.

    Nothing to do yet -- schema 2 is the first JSON revision. Later format
    changes chain their fix-ups here, keyed off the stored schemaVersion, so a
    config written by any earlier release still loads.
    """

    return data


def _mergeSection(target, loaded, prefix):
    """Overlay loaded values onto target, keyed by the defaults already there.

    Keys absent from `loaded` keep their default, so settings added in a later
    release appear automatically. Keys absent from `target` are dropped -- a
    stale key from an older release does not linger.
    """

    for key, value in loaded.items():
        if key not in target:
            continue
        path = "%s.%s" % (prefix, key)
        if path in NOT_PERSISTED:
            continue

        current = target[key]
        if isinstance(current, dict):
            if isinstance(value, dict):
                _mergeSection(current, value, path)
        elif isinstance(current, list):
            if isinstance(value, list):
                target[key] = value
        else:
            coerced = _coerce(value, current)
            if coerced is not _UNSET:
                target[key] = coerced


_UNSET = object()


def _coerce(value, default):
    """Cast a loaded value to the kind of its default, or reject it.

    JSON round-trips types faithfully, so this mostly matters for values
    carried over from the XML format (which stored several numbers as strings)
    and for a hand-edited file.

    Numbers are never narrowed: plenty of settings declare an int default but
    hold a float once the user edits them -- processing.math.multiplier and
    massCalculator.patternShift among them -- so coercing to the default's
    exact type would quietly truncate 2.5 to 2.
    """

    if isinstance(default, bool):
        if isinstance(value, (bool, int, float)):
            return bool(value)
        return _UNSET

    if isinstance(default, (int, float)):
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                pass
            try:
                return float(value)
            except ValueError:
                return _UNSET
        return _UNSET

    if isinstance(default, str):
        # several fields ("" meaning unset, a number once the user fills them
        # in) are str/number unions; keep numbers readable as text
        if isinstance(value, bool):
            return _UNSET
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return value
        return _UNSET

    return value if type(value) is type(default) else _UNSET


def _validateConfig():
    """Clamp loaded values that the pipeline requires to be in range."""

    deisotoping = processing["deisotoping"]
    deisotoping["envelopeNonIdeality"] = min(
        max(deisotoping["envelopeNonIdeality"], 0.0), 1.0
    )

    if processing["peakpicking"]["averagineType"] not in (
        "protein",
        "carbohydrate",
        "lipid",
    ):
        processing["peakpicking"]["averagineType"] = "protein"



def _getParams(sectionTag, section):
    """Get params from nodes."""

    if sectionTag:
        paramTags = sectionTag.getElementsByTagName("param")
        if paramTags:
            if paramTags:
                for paramTag in paramTags:
                    name = paramTag.getAttribute("name")
                    value = paramTag.getAttribute("value")
                    valueType = paramTag.getAttribute("type")
                    if name in section:
                        converter = {"unicode": str, "str": str, "float": float, "int": int}.get(valueType)
                        if converter is not None:
                            try:
                                section[name] = converter(value)
                            except Exception:
                                pass


# ----




# ----


CONFIG_FILENAME = "config.json"
LEGACY_CONFIG_FILENAME = "config.xml"


def getConfigPath():
    """Path of the user's settings file."""

    return os.path.join(confdir, CONFIG_FILENAME)


# libraries shipped as bundled defaults and editable by the user
LIBRARY_NAMES = (
    "monomers",
    "modifications",
    "enzymes",
    "presets",
    "references",
    "compounds",
    "mascot",
)


def getLibraryPath(name):
    """Path of a user library file."""

    return os.path.join(confdir, name + ".json")


def getLegacyLibraryPath(name):
    """Path a pre-7.0 release would have used for the same library."""

    return os.path.join(confdir, name + ".xml")


def _resolveMigrationTarget(localPath, legacyPath):
    """Decide where a migrated file goes, honouring a symlinked legacy file.

    A user who symlinks e.g. references.xml at a shared location -- a partition
    mounted from another OS, a network drive -- is saying "keep this file over
    there". Writing the migrated JSON into the config directory instead would
    quietly end the sharing: nothing is lost, but edits stop crossing over and
    the divergence is only noticed much later.

    Returns (writePath, linkPath). linkPath is None when no symlink is
    involved; otherwise the JSON belongs next to the link target and a symlink
    to it is left in the config directory.
    """

    if not os.path.islink(legacyPath):
        return localPath, None

    try:
        shared = os.path.join(
            os.path.dirname(os.path.realpath(legacyPath)),
            os.path.basename(localPath),
        )
    except OSError:
        return localPath, None

    return shared, localPath


def _placeMigrationLink(linkPath, writePath):
    """Point the config directory at a migrated file kept elsewhere."""

    if linkPath is None or os.path.abspath(linkPath) == os.path.abspath(writePath):
        return True

    try:
        if os.path.lexists(linkPath):
            os.unlink(linkPath)
        os.symlink(writePath, linkPath)
        return True
    except (OSError, NotImplementedError, AttributeError):
        # Windows refuses symlinks without Developer Mode or elevation. Fall
        # back to a plain copy so the app still starts; the two sides simply
        # stop tracking each other until the user re-links them.
        try:
            with open(writePath, "rb") as src, open(linkPath, "wb") as dst:
                dst.write(src.read())
            sys.stderr.write(
                "mMass: could not symlink %s to %s; copied it instead, so the "
                "two locations will no longer stay in sync\n" % (linkPath, writePath)
            )
            return True
        except OSError:
            return False


def migrateLegacyLibrary(name, readXML, saveJSON):
    """One-way migration of one pre-7.0 library XML to JSON.

    Reads the old file with its legacy reader, writes the values back out as
    JSON and renames the XML aside rather than deleting it. Returns True when a
    migration actually happened.
    """

    local = getLibraryPath(name)
    legacy = getLegacyLibraryPath(name)
    if os.path.lexists(local) or not os.path.exists(legacy):
        return False

    target, link = _resolveMigrationTarget(local, legacy)

    try:
        readXML(legacy)
    except Exception as exc:
        sys.stderr.write("mMass: could not migrate %s (%s)\n" % (legacy, exc))
        return False

    if os.path.exists(target):
        # the shared location was already migrated, most likely by the same
        # library being opened from another machine -- adopt it rather than
        # overwriting whatever it now holds
        sys.stderr.write("mMass: adopting already-migrated %s\n" % target)
    elif not saveJSON(target):
        sys.stderr.write("mMass: could not write %s\n" % target)
        return False

    if not _placeMigrationLink(link, target):
        sys.stderr.write("mMass: could not link %s to %s\n" % (link, target))
        return False

    # renames the symlink itself, never the file it points at: another machine
    # still running an older mMass keeps its XML
    try:
        os.replace(legacy, legacy + ".migrated")
    except OSError:
        pass

    sys.stderr.write("mMass: library migrated from %s to %s\n" % (legacy, target))
    return True


def _is_bundled_config_path(path):
    """Return True when path points inside the bundled defaults directory.

    confdir falls back to the bundled configs/ directory when no user config
    directory can be created; a settings file written there is a build
    artifact, not user state, and must never be treated as one.
    """

    try:
        bundled = os.path.abspath(get_default_config_source_dir())
        return os.path.abspath(os.path.dirname(path)) == bundled
    except Exception:
        return False


# every module-level container loadConfig() may write into, so a failed load
# can be rolled back to the in-code defaults
_CONFIG_SECTIONS = (
    "main",
    "recent",
    "colours",
    "export",
    "spectrum",
    "match",
    "processing",
    "calibration",
    "sequence",
    "massCalculator",
    "massfilter",
    "massToFormula",
    "massDefectPlot",
    "compoundsSearch",
    "peakDifferences",
    "comparePeaklists",
    "spectrumGenerator",
    "envelopeFit",
    "mascot",
    "profound",
    "prospector",
    "links",
    "replacements",
)


def _plainCopy(value):
    """Copy a config tree into plain dict/list containers.

    Deliberately not copy.deepcopy(): deepcopying a ConfigDict rebuilds it
    through the overridden __setitem__, which fires an autosave per key -- a
    few hundred full rewrites of config.xml for a single snapshot. Plain
    containers also make the snapshot inert, so nothing it holds can trigger a
    save later; _restoreSections() puts the values back through __setitem__,
    which re-wraps them as ConfigDict/ConfigList.
    """

    if isinstance(value, dict):
        return {key: _plainCopy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plainCopy(item) for item in value]
    return value


def _snapshotSections():
    """Copy every config section so a failed load can be undone."""

    return {name: _plainCopy(globals()[name]) for name in _CONFIG_SECTIONS}


def _restoreSections(snapshot):
    """Put the sections back exactly as _snapshotSections() found them."""

    with _suspendAutoSave():
        _restoreSectionsUnsafe(snapshot)


def _restoreSectionsUnsafe(snapshot):
    for name, saved in snapshot.items():
        target = globals()[name]
        if isinstance(target, list):
            target[:] = saved
        else:
            target.clear()
            # go through __setitem__ so nested containers are re-wrapped as
            # ConfigDict/ConfigList rather than plain dict/list
            for key in saved:
                target[key] = saved[key]


def migrateLegacyConfigXML():
    """One-way migration of a pre-7.0 config.xml to config.json.

    Runs once: reads the old file with the legacy XML reader, writes the same
    values back out as JSON, then renames the XML aside rather than deleting
    it, so a user can still recover from it if anything looks wrong. Returns
    True when a migration actually happened.
    """

    local = getConfigPath()
    legacy = os.path.join(confdir, LEGACY_CONFIG_FILENAME)
    if os.path.lexists(local) or not os.path.exists(legacy):
        return False
    if _is_bundled_config_path(legacy):
        return False

    target, link = _resolveMigrationTarget(local, legacy)

    defaults = _snapshotSections()
    try:
        loadLegacyConfigXML(legacy)
    except Exception as exc:
        _restoreSections(defaults)
        sys.stderr.write(
            "mMass: could not migrate %s (%s); starting from default settings.\n"
            % (legacy, exc)
        )
        return False

    # The XML writer emitted several numeric fields as type="unicode", so the
    # legacy reader hands them back as strings. Re-apply everything through the
    # same merge the JSON loader uses, so a migrated file is typed exactly like
    # one written by saveConfig rather than carrying the old strings forward.
    carried = _snapshotSections()
    _restoreSections(defaults)
    with _suspendAutoSave():
        _applySections(carried)
        _validateConfig()

    if not saveConfig(target):
        # leave the XML untouched so the next launch can try again
        sys.stderr.write("mMass: could not write %s\n" % target)
        return False

    if not _placeMigrationLink(link, target):
        sys.stderr.write("mMass: could not link %s to %s\n" % (link, target))
        return False

    try:
        os.replace(legacy, legacy + ".migrated")
    except OSError:
        pass

    sys.stderr.write("mMass: settings migrated from %s to %s\n" % (legacy, target))
    return True


def _initialize_runtime_config():
    """Load the user's settings, otherwise keep the in-code defaults."""

    path = getConfigPath()

    if not _is_bundled_config_path(path):
        migrateLegacyConfigXML()

        if os.path.exists(path):
            snapshot = _snapshotSections()
            try:
                loadConfig(path)
                return
            except Exception as exc:
                # An unreadable settings file must never stop the app from
                # starting. Roll back any partially applied section, keep the
                # bad file for the user to inspect, and fall through to
                # writing a fresh one from the in-code defaults.
                _restoreSections(snapshot)
                damaged = path + ".corrupt"
                try:
                    os.replace(path, damaged)
                except OSError:
                    damaged = None
                sys.stderr.write(
                    "mMass: could not read %s (%s); starting from default settings.\n"
                    % (path, exc)
                )
                if damaged:
                    sys.stderr.write(
                        "mMass: the unreadable file was kept as %s\n" % damaged
                    )

    # Best effort persistence; read-only locations should still run with defaults.
    try:
        saveConfig(path)
    except IOError:
        pass



# ----

internal = ConfigDict(internal)
main = ConfigDict(main)
recent = ConfigList(recent)
export = ConfigDict(export)
spectrum = ConfigDict(spectrum)
match = ConfigDict(match)
processing = ConfigDict(processing)
calibration = ConfigDict(calibration)
sequence = ConfigDict(sequence)
massCalculator = ConfigDict(massCalculator)
massfilter = ConfigDict(massfilter)
massToFormula = ConfigDict(massToFormula)
massDefectPlot = ConfigDict(massDefectPlot)
compoundsSearch = ConfigDict(compoundsSearch)
peakDifferences = ConfigDict(peakDifferences)
comparePeaklists = ConfigDict(comparePeaklists)
spectrumGenerator = ConfigDict(spectrumGenerator)
envelopeFit = ConfigDict(envelopeFit)
mascot = ConfigDict(mascot)
profound = ConfigDict(profound)
prospector = ConfigDict(prospector)
links = ConfigDict(links)
replacements = ConfigDict(replacements)


# Defaults policy:
# - In-code dictionaries in this module are the single source of default values.
# - config.json in confdir is user runtime state persisted between launches.
# - Do not reintroduce a bundled settings file as a second defaults definition.
try:
    _initialize_runtime_config()
except Exception:
    # never let config persistence stop the application from starting
    pass

_auto_save_enabled = True

