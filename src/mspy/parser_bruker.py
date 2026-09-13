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

# -------------------------------------------------------------------------
#     ATTRIBUTION
#
#     The TOF-to-m/z calibration in this file is derived from
#     readBrukerFlexData by Sebastian Gibb (the reader behind MALDIquant):
#
#         https://github.com/sgibb/readBrukerFlexData/
#
#     Specifically, the meaning and field order of the
#     'V1.0CTOF2CalibrationConstants' block in ##$NTBCal, the cubic
#     TOF-to-m/z model and its trailing mass offset, and the ##$HPCStr High
#     Precision Calibration correction all follow that package's reading of
#     the format; _tofToMassQuadratic, _tofToMassCubic, _applyHPC and
#     _hpcCoefficients are ports of its .tof2mass, .ctof2calibration, .hpc
#     and .extractHPCConstants. The cubic is solved differently here (Newton
#     from the quadratic estimate rather than polyroot), and its time axis
#     starts from the block's own DELAY rather than ##$DELAY (checked against
#     FlexAnalysis exports), but the model is theirs, not independent work.
#
#     readBrukerFlexData is licensed GPL (>= 3) and mMass is
#     GPL-3.0-or-later, so this places no restriction on mMass beyond its
#     own licence.
#
#     The LIFT (MS/MS) calibration is NOT from that package, which does not
#     support LIFT: it detects such spectra and returns their raw flight
#     times. The reading of the 'V1.0CLift2CalibrationConstants' block here
#     was worked out for mMass by comparing the raw fid against FlexAnalysis'
#     own mzXML export of the same acquisitions.
#
#     No OpenMS or pyOpenMS code is present or was copied. This module used
#     to call pyOpenMS' XMassFile reader, which applies only the ##$ML*
#     quadratic; that dependency was dropped rather than ported.
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
# except LIFT (MS/MS) acquisitions, which sit one level deeper, in a folder
# named after the precursor:
#
#     <dataset>/<spot>/<run>/<precursor>.LIFT/1SRef/fid
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
                "msLevel": _msLevel(params),
                "pointsCount": _pointsCount(params),
                "polarity": _polarity(params),
                "retentionTime": None,
                "lowMZ": None,
                "highMZ": None,
                "basePeakMZ": None,
                "basePeakIntensity": None,
                "totIonCurrent": None,
                "precursorMZ": _precursorMZ(params),
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
        scan.msLevel = _msLevel(params)
        scan.precursorMZ = _precursorMZ(params)
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
# The model is readBrukerFlexData's - see ATTRIBUTION at the top of the file -
# with one departure: the flight time of each sample is counted from the DELAY
# and DW inside the block, not from ##$DELAY and ##$DW as that package does.
# ##$DELAY is the block's value rounded down to a whole nanosecond, and using
# it puts every m/z out by 15-39 ppm.
#
# That is settled by FlexAnalysis' own mzXML export of 'Cubic Enhanced'
# spectra: with the block's DELAY every sample lands within 0.06 ppm of
# FlexAnalysis' m/z - half the step of the 32-bit floats that export is
# written in, so as close as it can show - and with the integer the whole
# axis is off. The trailing 'order' value is ignored, as it is in
# readBrukerFlexData, and nothing in the exports says it should not be.
# ##$CalStar - flexControl's calibrant list - is consistent with either DELAY
# (to 10-20 ppm), since it records the flight time of each calibrant rather
# than the sample it sits at, so it cannot tell the two apart.

NTBCAL_MARKER = "V1.0CTOF2CalibrationConstants"


def _massAxis(params, count):
    """Build the m/z axis of an acquisition from its calibration constants."""

    # LIFT spectra carry a calibration of their own, and their ##$ML* fields
    # are placeholders (ML1= 20000, ML2= ML3= 0) that would put a 1000 Da
    # fragment at 59. A block that cannot be used falls through to them all
    # the same, so the spectrum still opens rather than not at all.
    lift = _liftCalibration(params)
    if lift is not None:
        masses = _liftMasses(lift, count)
        if masses is not None:
            return masses

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

    constants = _ctof2Constants(params)
    if constants is not None:
        # the block's own DELAY and DW, not the rounded ##$DELAY - see
        # CALIBRATION above
        delay, dwell, ml2, ml1, ml3, cubic, offset = constants[:7]
        tof = delay + numpy.arange(count, dtype=numpy.float64) * dwell
        masses = _tofToMassCubic(tof, ml1, ml2, ml3, cubic, offset)
    else:
        # ##$DELAY is all there is; no export of such a spectrum has been
        # available to check it against
        tof = delay + numpy.arange(count, dtype=numpy.float64) * dwell
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


# LIFT CALIBRATION
# ----------------
#
# A LIFT spectrum holds the fragments of one precursor, re-accelerated in the
# LIFT cell once the precursor has flown there. Their flight time is not a
# quadratic in sqrt(m/z) at all, so ##$ML* is left at placeholder values and
# the calibration lives in ##$NTBCal instead, as a
# 'V1.0CLift2CalibrationConstants' block laid out as
#
#     V3.0CTOFCalibrationConstants  DELAY  DW  0 0 0  2  N
#     N x polynomial                  the instrument's calibration, one per
#                                     calibrant precursor
#     1 x polynomial                  (identity in every file seen)
#     V1.0VectorDouble k  k values    (not used)
#     0 0  T0 T0  PRECURSOR
#     1 x polynomial                  the calibration for THIS precursor
#     1 x polynomial                  (identity in every file seen)
#     6 flags
#
# where each polynomial is
#
#     V1.0CCalibPolynomial V1.0VectorDouble k  c0 .. c(k-1)  MASS  ULOW  UHIGH
#
# The one that applies is the one flexControl already interpolated for the
# precursor that was actually selected, and it gives the flight time measured
# from T0 as a function of u = sqrt(m/z):
#
#     tof - T0 = c0 + c1*u + ... + c6*u**6        ULOW <= u <= UHIGH
#
# T0 is close to ##$TLft + ##$TLift - roughly when the precursor reaches the
# LIFT cell - but only to within 0.3 ns, which is why it is read from the
# block. UHIGH is sqrt(PRECURSOR), since no fragment outweighs its precursor.
# Outside [ULOW, UHIGH] the curve continues as a straight line along the
# tangent at the nearer end, NOT as the polynomial: extrapolating the
# polynomial itself puts the edges of the spectrum out by several ns at the
# light end and tens of ns at the heavy one, while the tangent matches.
#
# As for the cubic MS1 calibration, the flight time axis starts at the DELAY
# in this block, not at ##$DELAY, which is that value rounded down to a whole
# nanosecond: here the integer puts every sample a fraction of a nanosecond
# early, which is 25-150 ppm. Unlike it, ##$HPC* is not applied: HPC is
# fitted to an MS1 calibration, and LIFT acquisitions carry ##$HPClUse= yes
# but with an empty ##$HPCStr and order 0 anyway.
#
# Checked against the mzXML FlexAnalysis exported for three precursors, in
# positive and negative mode, a fragment spectrum and a precursor spectrum of
# each: every exported point lands within 0.06 ppm of the m/z computed here,
# which is half the step of the 32-bit floats that export is written in -
# i.e. as close as that file can show.

LIFT_MARKER = "V1.0CLift2CalibrationConstants"
POLYNOMIAL_MARKER = "V1.0CCalibPolynomial"


def _liftCalibration(params):
    """Get the LIFT calibration for this acquisition's precursor out of ##$NTBCal.

    Returns (delay, dwell, t0, coefficients, uLow, uHigh), coefficients lowest
    power first, or None when the acquisition is not LIFT or the block does
    not have the layout described above.
    """

    raw = params.get("NTBCal", "")
    if LIFT_MARKER not in raw:
        return None

    # the field holds two identical copies of the block; the first is taken
    tokens = raw.split(LIFT_MARKER)[1].split()

    try:
        return _parseLiftBlock(tokens)
    except (IndexError, ValueError):
        return None


def _parseLiftBlock(tokens):
    """Walk one V1.0CLift2CalibrationConstants block; raises if it is malformed."""

    if tokens[0] != "V3.0CTOFCalibrationConstants":
        raise ValueError("unexpected LIFT header")

    delay = float(tokens[1])
    dwell = float(tokens[2])
    calibrants = int(tokens[7])
    position = 8

    # the calibrant polynomials, then the (identity) one after them
    for _polynomial in range(calibrants + 1):
        _coefficients, _limits, position = _readPolynomial(tokens, position)

    # a short vector that is not needed here
    if tokens[position] != "V1.0VectorDouble":
        raise ValueError("unexpected LIFT layout")
    position += 2 + int(tokens[position + 1])

    # 0 0 T0 T0 PRECURSOR
    t0 = float(tokens[position + 2])
    precursor = float(tokens[position + 4])
    position += 5

    coefficients, (mass, uLow, uHigh), position = _readPolynomial(tokens, position)

    if abs(mass - precursor) > 1e-6 * precursor:
        raise ValueError("polynomial is not for this precursor")
    if not 0 < uLow < uHigh or dwell <= 0:
        raise ValueError("unusable LIFT calibration")

    return delay, dwell, t0, coefficients, uLow, uHigh


def _readPolynomial(tokens, position):
    """Read one V1.0CCalibPolynomial; returns (coefficients, limits, next position)."""

    if (
        tokens[position] != POLYNOMIAL_MARKER
        or tokens[position + 1] != "V1.0VectorDouble"
    ):
        raise ValueError("expected a calibration polynomial")

    size = int(tokens[position + 2])
    start = position + 3
    coefficients = numpy.array([float(token) for token in tokens[start : start + size]])
    limits = tuple(float(token) for token in tokens[start + size : start + size + 3])
    if len(coefficients) != size or len(limits) != 3:
        raise IndexError("truncated calibration polynomial")

    return coefficients, limits, start + size + 3


def _liftMasses(lift, count):
    """Build the m/z axis of a LIFT acquisition."""

    delay, dwell, t0, coefficients, uLow, uHigh = lift
    polynomial = numpy.polynomial.Polynomial(coefficients)
    slope = polynomial.deriv()

    # the inversion below needs a curve that only ever rises across its range
    grid = numpy.linspace(uLow, uHigh, 2001)
    if not numpy.all(slope(grid) > 0):
        return None

    times = delay + numpy.arange(count, dtype=numpy.float64) * dwell - t0
    timeLow = polynomial(uLow)
    timeHigh = polynomial(uHigh)

    # inside the range: start from the tabulated curve and polish with Newton,
    # kept inside the range so it cannot wander off onto the extrapolation
    inside = (times >= timeLow) & (times <= timeHigh)
    u = numpy.interp(times[inside], polynomial(grid), grid)
    for _iteration in range(20):
        step = (polynomial(u) - times[inside]) / slope(u)
        u = numpy.clip(u - step, uLow, uHigh)
        if numpy.all(numpy.abs(step) <= 1e-13 * u):
            break

    roots = numpy.empty(count, dtype=numpy.float64)
    roots[inside] = u

    # outside it: the tangent at the nearer end
    below = times < timeLow
    above = times > timeHigh
    roots[below] = uLow + (times[below] - timeLow) / slope(uLow)
    roots[above] = uHigh + (times[above] - timeHigh) / slope(uHigh)

    # the sign keeps an (unphysical) negative root monotonic, as in the cubic
    return roots * numpy.abs(roots)


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

    NOT from ##.IONIZATION MODE: flexControl writes 'LD+' there
    unconditionally - it reads LD+ on negative-mode acquisitions too - so
    taking the sign off that JCAMP field, as readers which trust it do, makes
    every negative spectrum come out positive. ##$POLARI is the field that
    actually tracks the acquisition (verified against negative and positive
    runs, and against the polarity of the reference masses flexControl embeds
    in ##$CalStar).
    """

    polarity = params.get("POLARI", "").strip()
    if polarity == "1":
        return 1
    elif polarity == "0":
        return -1

    return None


def _isLIFT(params):
    """Tell whether an acquisition is a LIFT (MS/MS) spectrum.

    ##$SPType is 2 for LIFT (0 for a plain TOF spectrum). The calibration
    block is accepted as well, so a LIFT spectrum is still recognised in case
    the type field is missing.
    """

    return params.get("SPType", "").strip() == "2" or LIFT_MARKER in params.get(
        "NTBCal", ""
    )


def _msLevel(params):
    """Get the MS level: 2 for LIFT, 1 otherwise.

    FlexAnalysis exports the precursor ('par') spectrum of a LIFT run as MS2
    as well - it is acquired through the LIFT cell, with the precursor
    selected - so no distinction is made between the two here either.
    """

    return 2 if _isLIFT(params) else 1


def _precursorMZ(params):
    """Get the selected precursor m/z of a LIFT acquisition, else None.

    ##$Parent is filled in for every acquisition, but outside LIFT it is a
    placeholder (1000), so it is only read when the spectrum is LIFT.
    """

    if not _isLIFT(params):
        return None

    try:
        return float(params["Parent"])
    except (KeyError, ValueError):
        return None


def _pointsCount(params):
    """Get the number of data points from the acquisition parameters."""

    try:
        return int(params["TD"])
    except (KeyError, ValueError):
        return None


def _spotLabel(fidPath, params):
    """Get the bare label of a single acquisition."""

    # the sample position (e.g. 'M9' or 'A1') is the meaningful label;
    # otherwise fall back to the spot folder, e.g. '0_M9' - not the folder the
    # fid sits in directly, which is the '1SRef' every acquisition shares
    spot = params.get("SPOTNO", "") or params.get("PATCHNO", "")
    if not spot:
        spot = os.path.basename(_spotDir(fidPath))

    # a LIFT spectrum shares its spot with the MS1 spectrum it was selected
    # from, and with any other precursor fragmented there, so the precursor
    # is what tells them apart
    precursor = _precursorMZ(params)
    if precursor is not None:
        return "%s LIFT %.4f" % (spot, precursor)

    return spot


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


# a fid sits at <dataset>/<spot>/<run>/<1SRef>/fid, so its run folder is one
# level above the folder holding it, its spot folder two and its dataset folder
# three - or one more of each for LIFT, whose 1SRef sits in a
# '<precursor>.LIFT' folder inside the run
def _runDir(fidPath):
    """Get the run folder holding a single acquisition."""

    folder = os.path.dirname(os.path.dirname(fidPath))
    if os.path.basename(folder).lower().endswith(".lift"):
        folder = os.path.dirname(folder)

    return folder


def _spotDir(fidPath):
    """Get the spot folder holding a single acquisition."""

    return os.path.normpath(_levelsUp(_runDir(fidPath), 1))


def datasetDir(fidPath):
    """Get the dataset folder a single acquisition belongs to.

    Public because opening one fid directly still means working on the whole
    dataset it came from: the GUI needs the dataset folder to decide where
    results belong, not the '1SRef' the fid happens to sit in.
    """

    return os.path.normpath(_levelsUp(_runDir(fidPath), 2))


def _datasetName(path):
    """Get the dataset name for a fid or a dataset folder."""

    if os.path.isfile(path):
        path = datasetDir(path)

    return os.path.basename(os.path.normpath(path))
