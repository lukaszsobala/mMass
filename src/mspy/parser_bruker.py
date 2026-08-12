# -------------------------------------------------------------------------
#     Copyright (C) 2008-2011 Martin Strohalm <www.mmass.org>

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
import datetime
import os
import os.path
import re
import time

import numpy

# load objects
from . import obj_scan


# PARSE BRUKER FLEX (XMASS) DATA
# ------------------------------
#
# A Bruker flex-series dataset is a directory tree, not a single file. Each
# acquisition lives in its own folder:
#
#     <dataset>/<spot>/<run>/<1SRef|1SLin>/fid      binary TOF trace (int32)
#     <dataset>/<spot>/<run>/<1SRef|1SLin>/acqu     acquisition parameters
#
# The fid holds intensities only; the TOF-to-m/z calibration constants
# (ML1/ML2/ML3, DELAY, DW) live in acqu. OpenMS' XMassFile reader parses acqu
# and applies that calibration, which is why the raw fid is read through
# pyOpenMS here rather than unpacked by hand.
#
# Note this covers the flex/XMASS family only. Bruker's later .baf/.yep/.d
# (Compass, timsTOF) containers need the vendor SDK and are NOT supported.
#
# The path handed to the parser can be a single fid, one dataset folder, or a
# folder holding several datasets - the fids are found by walking the tree, so
# a whole plate of datasets opens in one go. Everything that describes an
# acquisition (operator, instrument, date, polarity, spot) is therefore read
# per fid rather than once for the tree: acquisitions collected on different
# days, in different modes or by different operators can sit under the same
# folder.

# acqu is JCAMP-DX-ish: '##$NAME= value' for instrument parameters and
# '##NAME= value' (sometimes dotted, e.g. '##.IONIZATION MODE=') for the
# standard JCAMP fields. Text values are wrapped in angle brackets.
ACQU_PATTERN = re.compile(r"^##\$?([^=]+)=\s*(.*)\s*$")


class parseBruker:
    """Parse data from a Bruker flex-series (XMASS) dataset."""

    def __init__(self, path):
        self.path = path
        self._fids = None
        self._info = {}

        # check path
        if not os.path.exists(path):
            raise IOError("File not found! --> " + self.path)

    # ----

    def load(self):
        """Discover the acquisitions (fid files) in this dataset."""

        if self._fids is not None:
            return self._fids

        self._fids = {}
        for index, fidPath in enumerate(findFIDs(self.path), 1):
            self._fids[index] = fidPath

        return self._fids

    # ----

    def info(self, scanID=None):
        """Get document info for one acquisition (default: the first).

        The operator, instrument and date belong to the acquisition, so they
        are read from that acquisition's own acqu file - hoisting the first
        one would stamp the whole tree with it, which is wrong as soon as more
        than one dataset was opened at once.
        """

        data = {
            "title": "",
            "operator": "",
            "contact": "",
            "institution": "",
            "date": "",
            "instrument": "",
            "notes": "",
        }

        fids = self.load()
        if not fids:
            return data

        if scanID is None:
            scanID = min(fids)
        if scanID not in fids:
            return data

        if scanID in self._info:
            return self._info[scanID]

        fidPath = fids[scanID]
        params = _readAcqu(fidPath)

        # name the dataset the acquisition belongs to, not the folder the user
        # happened to open - those differ when several datasets were opened
        data["title"] = _datasetName(fidPath)
        if len(fids) > 1:
            data["title"] = "%s %s" % (data["title"], _spotLabel(fidPath, params))

        data["operator"] = params.get("OWNER", "")
        # ##SPECTROMETER/DATASYSTEM names the instrument ('Bruker Flex
        # Series'); ##$INSTRUM only names the acquisition PC ('FLEX-PC')
        data["instrument"] = params.get("SPECTROMETER/DATASYSTEM", "") or params.get(
            "INSTRUM", ""
        )
        data["date"] = _acquisitionDate(params)

        self._info[scanID] = data
        return data

    # ----

    def scanlist(self):
        """Get list of all acquisitions in the dataset."""

        fids = self.load()
        if not fids:
            return False

        scanlist = {}
        for scanID, fidPath in fids.items():
            params = _readAcqu(fidPath)

            scanlist[scanID] = {
                "title": _spotName(fidPath, params, self.path),
                "scanNumber": scanID,
                "parentScanNumber": None,
                "msLevel": 1,
                "pointsCount": _pointsCount(params),
                "polarity": _polarity(params),
                "retentionTime": None,
                "lowMZ": None,
                "highMZ": None,
                "basePeakMZ": None,
                "basePeakIntensity": None,
                "totIonCurrent": None,
                "precursorMZ": None,
                "precursorIntensity": None,
                "precursorCharge": None,
                # a fid is the raw TOF trace, always a profile
                "spectrumType": "continuous",
            }

        return scanlist

    # ----

    def scan(self, scanID=None):
        """Get spectrum from document."""

        fids = self.load()
        if not fids:
            return False

        # default to the first acquisition
        if scanID is None:
            scanID = min(fids)
        if scanID not in fids:
            return False

        return self._makeScan(scanID, fids[scanID])

    # ----

    def _makeScan(self, scanID, fidPath):
        """Make scan object from a single fid."""

        points = _readFID(fidPath)
        if points is None:
            return False

        scan = obj_scan.scan(profile=points)

        # set metadata
        params = _readAcqu(fidPath)
        scan.title = _spotName(fidPath, params, self.path)
        scan.scanNumber = scanID
        scan.msLevel = 1
        scan.polarity = _polarity(params)

        if len(points):
            intensities = points[:, 1]
            basePeak = int(intensities.argmax())
            scan.totIonCurrent = float(intensities.sum())
            scan.basePeakMZ = float(points[basePeak, 0])
            scan.basePeakIntensity = float(intensities[basePeak])

        return scan


# HELPERS
# -------


def findFIDs(path):
    """Get sorted paths of all fid files in a dataset directory or file."""

    # a single acquisition was given directly
    if os.path.isfile(path):
        if os.path.basename(path).lower().startswith("fid"):
            return [path]
        return []

    fids = []
    for dirpath, _dirnames, filenames in os.walk(path):
        for fileName in filenames:
            if fileName.lower() == "fid":
                fids.append(os.path.join(dirpath, fileName))

    return sorted(fids)


def _readFID(fidPath):
    """Read one fid into an [[mz, intensity], ..] array via pyOpenMS."""

    # imported here rather than at module level only to keep it off the
    # application start-up path - it costs ~0.3 s and nothing but Bruker
    # import needs it
    import pyopenms

    # OpenMS picks the XMASS reader by file name, so the path has to be the
    # fid itself - it then reads the calibration from the sibling acqu file
    experiment = pyopenms.MSExperiment()
    try:
        pyopenms.FileHandler().loadExperiment(fidPath, experiment)
    except Exception:
        return None

    if not experiment.getNrSpectra():
        return None

    mzArray, intArray = experiment.getSpectrum(0).get_peaks()
    if not len(mzArray):
        return numpy.array([])

    points = numpy.empty((len(mzArray), 2), dtype=numpy.float64)
    points[:, 0] = mzArray
    points[:, 1] = intArray

    return points


def _readAcqu(fidPath):
    """Read the acquisition parameters sitting next to a fid."""

    params = {}

    acquPath = os.path.join(os.path.dirname(fidPath), "acqu")
    if not os.path.exists(acquPath):
        return params

    try:
        with open(acquPath, "rb") as document:
            lines = document.readlines()
    except IOError:
        return params

    for line in lines:
        line = line.decode("utf-8", "replace").strip()
        parts = ACQU_PATTERN.match(line)
        if not parts:
            continue

        value = parts.group(2).strip()

        # text values are wrapped in angle brackets
        if value.startswith("<") and value.endswith(">"):
            value = value[1:-1]

        params[parts.group(1)] = value

    return params


def _acquisitionDate(params):
    """Get the date the data was collected, as instrument local time."""

    # ##$AQ_DATE is the acquisition timestamp, ISO 8601 with a UTC offset.
    # It is kept as the instrument's wall clock rather than converted, since
    # that is what the operator saw.
    stamp = params.get("AQ_DATE", "")
    if stamp:
        try:
            return datetime.datetime.fromisoformat(stamp).ctime()
        except ValueError:
            pass

    # ##$DATE is an older unix-timestamp field; flex leaves it at 0
    try:
        seconds = int(params.get("DATE", 0))
        if seconds > 0:
            return time.ctime(seconds)
    except ValueError:
        pass

    return ""


def _polarity(params):
    """Get the ion polarity as mMass expects it (1, -1 or None).

    Polarity comes from ##$POLARI, where 0 is negative and 1 is positive.

    NOT from ##.IONIZATION MODE, and so NOT from OpenMS either: OpenMS takes
    the polarity from the sign on that JCAMP field, but flexControl writes
    'LD+' there unconditionally - it reads LD+ on negative-mode acquisitions
    too, which makes every negative spectrum come out as positive. ##$POLARI
    is the field that actually tracks the acquisition (verified against
    negative and positive runs, and against the polarity of the reference
    masses flexControl embeds in ##$CalStar).
    """

    polarity = params.get("POLARI", "").strip()
    if polarity == "1":
        return 1
    elif polarity == "0":
        return -1

    return None


def _pointsCount(params):
    """Get the number of data points from the acquisition parameters."""

    try:
        return int(params["TD"])
    except (KeyError, ValueError):
        return None


def _spotLabel(fidPath, params):
    """Get the bare label of a single acquisition."""

    # the sample position (e.g. 'M9' or 'A1') is the meaningful label
    spot = params.get("SPOTNO", "") or params.get("PATCHNO", "")
    if spot:
        return spot

    # otherwise fall back to the spot folder, e.g. '0_M9' - not the folder the
    # fid sits in directly, which is the '1SRef' every acquisition shares
    return os.path.basename(_spotDir(fidPath))


def _spotName(fidPath, params, root=None):
    """Get a human-readable name for a single acquisition.

    Spot labels repeat across datasets - 'M9' is a position on every plate -
    so when root is a folder holding more than the one dataset, the label is
    qualified with the dataset the acquisition came from.
    """

    spot = _spotLabel(fidPath, params)

    if root and os.path.isdir(root) and os.path.normpath(root) != datasetDir(fidPath):
        return "%s %s" % (_datasetName(fidPath), spot)

    return spot


def _levelsUp(path, levels):
    """Get the ancestor directory the given number of levels above path."""

    for _level in range(levels):
        parent = os.path.dirname(path)
        if not parent or parent == path:
            break
        path = parent

    return path


# a fid sits at <dataset>/<spot>/<run>/<1SRef>/fid, so its spot folder is two
# levels above the folder holding it and its dataset folder three
def _spotDir(fidPath):
    """Get the spot folder holding a single acquisition."""

    return os.path.normpath(_levelsUp(os.path.dirname(fidPath), 2))


def datasetDir(fidPath):
    """Get the dataset folder a single acquisition belongs to.

    Public because opening one fid directly still means working on the whole
    dataset it came from: the GUI needs the dataset folder to decide where
    results belong, not the '1SRef' the fid happens to sit in.
    """

    return os.path.normpath(_levelsUp(os.path.dirname(fidPath), 3))


def _datasetName(path):
    """Get the dataset name for a fid or a dataset folder."""

    if os.path.isfile(path):
        path = datasetDir(path)

    return os.path.basename(os.path.normpath(path))
