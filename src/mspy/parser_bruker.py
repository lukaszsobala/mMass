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
import math
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
# The fid holds intensities only - TD little-endian int32 samples, no header -
# and the TOF-to-m/z calibration lives in acqu. Both are read here directly.
#
# This used to go through pyOpenMS' XMassFile reader, which mis-calibrates
# every spectrum flexControl fitted with more than a quadratic: see the
# CALIBRATION section below for what that reader leaves out and why the axis
# is now computed here instead.
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

    def spansDatasets(self):
        """Tell whether the opened path holds acquisitions from several datasets.

        Asked of the acquisitions rather than of the path, since the path can
        be anywhere in the tree - the folder browser cannot select a fid, so a
        single acquisition is often opened by picking the '1SRef' it sits in.
        """

        fids = self.load()

        return len({datasetDir(fidPath) for fidPath in fids.values()}) > 1

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

        qualify = self.spansDatasets()

        scanlist = {}
        for scanID, fidPath in fids.items():
            params = _readAcqu(fidPath)

            scanlist[scanID] = {
                "title": _spotName(fidPath, params, qualify),
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

        params = _readAcqu(fidPath)

        points = _readFID(fidPath, params)
        if points is None:
            return False

        scan = obj_scan.scan(profile=points)

        # set metadata
        scan.title = _spotName(fidPath, params, self.spansDatasets())
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


def _readFID(fidPath, params=None):
    """Read one fid into an [[mz, intensity], ..] array."""

    if params is None:
        params = _readAcqu(fidPath)

    intensities = _readIntensities(fidPath, params)
    if intensities is None:
        return None
    if not len(intensities):
        return numpy.array([])

    masses = _massAxis(params, len(intensities))
    if masses is None:
        return None

    points = numpy.empty((len(intensities), 2), dtype=numpy.float64)
    points[:, 0] = masses
    points[:, 1] = intensities

    return points


def _readIntensities(fidPath, params):
    """Read the raw TOF trace out of a fid.

    A fid is a bare block of TD 32-bit integers - no header, no padding - and
    ##$BYTORDA gives the byte order (0 little, 1 big).
    """

    try:
        byteOrder = int(params.get("BYTORDA", 0))
    except ValueError:
        byteOrder = 0
    dtype = numpy.dtype(numpy.int32).newbyteorder(">" if byteOrder else "<")

    count = _pointsCount(params)
    if count is None:
        return None

    try:
        intensities = numpy.fromfile(fidPath, dtype=dtype, count=count)
    except (IOError, OSError, ValueError):
        return None

    # a truncated acquisition is still worth showing, so short reads are kept
    # rather than rejected - only the samples actually present are used
    return intensities.astype(numpy.float64)


# CALIBRATION
# -----------
#
# flexControl stores the TOF-to-m/z calibration twice, and the two copies do
# not agree. ##$ML1/##$ML2/##$ML3 describe a quadratic
#
#     tof = ML2 + sqrt(1e12/ML1)*u + ML3*u**2          (u = sqrt(m/z))
#
# but when the instrument was calibrated with a higher-order method - the
# 'Cubic Enhanced' that ##$CalStar names - the coefficients that were actually
# fitted live in ##$NTBCal, as a 'V1.0CTOF2CalibrationConstants' block of
#
#     DELAY  DW  ML2  ML1  ML3  A3  OFFSET  order
#
# adding a cubic term and a constant mass offset:
#
#     tof = ML2 + sqrt(1e12/ML1)*u + ML3*u**2 + A3*u**3,   m/z = u**2 - OFFSET
#
# The ##$ML* fields are NOT updated to match, so reading them alone silently
# drops both extra terms. OpenMS' XMassFile does exactly that (its reader has
# no notion of ##$NTBCal at all), which put every affected spectrum out by
# 4000-10000 ppm - 3 Da at m/z 622, 56 Da at m/z 5728 on the reference masses
# flexControl itself recorded in ##$CalStar. Hence this module reads ##$NTBCal
# and falls back to the quadratic only when no cubic block is present.
#
# This mirrors readBrukerFlexData (the reader behind MALDIquant), whose output
# the axis below reproduces to ~1e-10 Da. Note that package warns the block is
# not fully understood (sgibb/readBrukerFlexData#3); the trailing 'order' value
# is ignored here as it is there.

NTBCAL_MARKER = "V1.0CTOF2CalibrationConstants"


def _massAxis(params, count):
    """Build the m/z axis of an acquisition from its calibration constants."""

    try:
        delay = float(params["DELAY"])
        dwell = float(params["DW"])
        ml1 = float(params["ML1"])
        ml2 = float(params["ML2"])
        ml3 = float(params["ML3"])
    except (KeyError, ValueError):
        return None

    if ml1 <= 0:
        return None

    # ##$DELAY is the integer sample clock; ##$NTBCal carries the same value
    # with a fractional part, but the integer is what the samples are on
    tof = delay + numpy.arange(count, dtype=numpy.float64) * dwell

    constants = _ctof2Constants(params)
    if constants is not None:
        _, _, ml2, ml1, ml3, cubic, offset = constants[:7]
        masses = _tofToMassCubic(tof, ml1, ml2, ml3, cubic, offset)
    else:
        masses = _tofToMassQuadratic(tof, ml1, ml2, ml3)

    return _applyHPC(masses, params)


def _ctof2Constants(params):
    """Get the V1.0CTOF2CalibrationConstants block out of ##$NTBCal.

    The field holds two identical copies of the block; the first is taken.
    Returns None when the acquisition carries no such block, which is the
    signal to fall back to the plain ##$ML* quadratic.
    """

    raw = params.get("NTBCal", "")
    if NTBCAL_MARKER not in raw:
        return None

    values = []
    for token in raw.split(NTBCAL_MARKER, 1)[1].split():
        try:
            values.append(float(token))
        except ValueError:
            # the numbers run until the next marker word
            break

    # DELAY DW ML2 ML1 ML3 A3 OFFSET, plus a trailing order that is not used
    if len(values) < 7 or values[3] <= 0:
        return None

    return values


def _tofToMassQuadratic(tof, ml1, ml2, ml3):
    """Convert TOF to m/z with the plain ##$ML* quadratic."""

    scale = math.sqrt(1e12 / ml1)

    if ml3 == 0:
        return ((tof - ml2) / scale) ** 2

    return (
        (-scale + numpy.sqrt(scale * scale - 4 * ml3 * (ml2 - tof))) / (2 * ml3)
    ) ** 2


def _tofToMassCubic(tof, ml1, ml2, ml3, cubic, offset):
    """Convert TOF to m/z with the cubic ##$NTBCal calibration.

    Solves A3*u**3 + ML3*u**2 + scale*u + (ML2 - tof) = 0 for u = sqrt(m/z).
    There is no need to pick between roots: the cubic is strongly dominated by
    its linear term over any physical flight time, so Newton started from the
    quadratic solution converges on the one root that means anything.
    """

    if cubic == 0:
        return _tofToMassQuadratic(tof, ml1, ml2, ml3) - offset

    scale = math.sqrt(1e12 / ml1)

    # start from the quadratic answer, which is already within ~1% of the root
    u = numpy.sqrt(numpy.abs(_tofToMassQuadratic(tof, ml1, ml2, ml3)))

    for _iteration in range(12):
        residual = ((cubic * u + ml3) * u + scale) * u + (ml2 - tof)
        slope = (3 * cubic * u + 2 * ml3) * u + scale
        # a stationary point would be far outside the physical range; leaving
        # those samples where they are keeps the whole axis finite
        step = numpy.where(slope != 0, residual / numpy.where(slope != 0, slope, 1), 0)
        u = u - step
        if numpy.all(numpy.abs(step) <= 1e-12 * numpy.abs(u)):
            break

    # below ML2 the flight time is unphysical; the sign keeps such samples
    # monotonic rather than folding them back over the real ones
    return u * u * numpy.sign(tof - ml2) - offset


def _applyHPC(masses, params):
    """Apply High Precision Calibration, when the acquisition used it.

    HPC is a polynomial correction flexControl fits on top of the TOF
    calibration and applies only between ##$HPClBLo and ##$HPClBHi. It is off
    in every dataset seen so far (##$HPClUse= no, ##$HPCStr= <>), so this is
    a faithful port of what readBrukerFlexData does rather than something
    that has been checked against a real HPC acquisition.
    """

    if params.get("HPClUse", "").strip().lower() not in ("yes", "true", "on", "1"):
        return masses

    try:
        lowMass = float(params.get("HPClBLo", 0))
        highMass = float(params.get("HPClBHi", 0))
        order = int(float(params.get("HPClOrd", 0)))
    except ValueError:
        return masses

    if order <= 0 or lowMass <= 0 or highMass <= lowMass:
        return masses

    coefficients = _hpcCoefficients(params.get("HPCStr", ""))
    if coefficients is None:
        return masses

    # numpy.polyval wants the highest power first; the block is stored the
    # other way round
    corrected = masses[(masses >= lowMass) & (masses <= highMass)]
    masses = masses.copy()
    masses[(masses >= lowMass) & (masses <= highMass)] = corrected - numpy.polyval(
        coefficients[::-1], corrected
    )

    return masses


def _hpcCoefficients(hpcStr):
    """Get the HPC polynomial coefficients from ##$HPCStr, lowest power first."""

    tokens = hpcStr.split()
    if "V1.0VectorDouble" not in tokens or "c2" not in tokens:
        return None

    start = tokens.index("V1.0VectorDouble") + 2
    end = tokens.index("c2")
    if start >= end:
        return None

    try:
        return numpy.array([float(token) for token in tokens[start:end]])
    except ValueError:
        return None


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


def _spotName(fidPath, params, qualify=False):
    """Get a human-readable name for a single acquisition.

    Spot labels repeat across datasets - 'M9' is a position on every plate -
    so when several datasets were opened at once the label is qualified with
    the dataset the acquisition came from.
    """

    spot = _spotLabel(fidPath, params)

    if qualify:
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
