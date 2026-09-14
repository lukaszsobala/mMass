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

"""Peak picking that uses a whole multi-scan run (an LC-MS chromatogram).

Picking each scan on its own asks every scan to decide, from its own noise, which
species exist, what charge they carry and where their isotope envelopes lie --
and neighbouring scans of the same species then disagree (one scan calls a +2
isotope its own envelope, the next misses a weak species altogether). Pooling
answers those questions once, from the averaged signal of many scans, where the
noise is lower and a species that is really there is seen consistently:

1. ``acquisitiongroups`` sorts the run into scans that can be averaged at all
   (same MS level, polarity and scan type -- an Orbitrap full scan and an ion
   trap full scan of the same run cannot share a peak list).
2. ``poolscans`` / ``poolwindows`` average the profiles of a group on one shared
   m/z raster (the whole group, or a moving window of neighbouring scans).
3. The normal peak-picking pipeline runs on the pooled spectrum; its peaks and
   envelopes are the run's species.
4. ``labelpooled`` labels those species in each scan: position, charge, FWHM and
   envelope shape come from the pool, only the intensities (and envelope areas)
   are measured in the scan, and a species too weak in that scan is left out.
"""

# load libs
import copy
import math
import re

import numpy

# load stopper
from .mod_stopper import CHECK_FORCE_QUIT

# load objects
from . import obj_peaklist
from . import obj_scan

# load modules
from . import calculations
from . import mod_peakpicking
from . import mod_signal

# POOLING CONSTANTS
# -----------------

# A step between two points of a scan this many times longer than the steps
# around it is a gap, not sampling: zero-dropped profile data (Orbitrap, most
# converted TOF data) only keeps the points around peaks. Nothing was measured
# above zero inside a gap, so the pooled raster reads zero there instead of a
# straight line drawn between two unrelated peaks.
POOL_GAP_FACTOR = 3.0

# Points of different scans closer than this fraction of their native sampling
# step share one node of the pooled raster (see calculations.signal_common_raster).
POOL_MERGE_FRACTION = 0.5

# Two scans whose sampling steps differ by more than this factor at the same m/z
# were not acquired the same way (e.g. a high- and a low-resolution full scan
# interleaved in one run) and are never averaged together.
POOL_SAMPLING_RATIO = 3.0

# Half-width of the window, as a fraction of the pooled FWHM, in which a pooled
# peak's height is read in a scan. Wide enough to follow the small m/z drift
# between scans, narrow enough not to read a neighbouring peak or pick the top of
# the noise around a missing one.
POOL_HEIGHT_WINDOW = 0.25

# Scan alignment. Scans of one run are rarely calibrated identically: in the
# LC-MS example run whole Orbitrap scans sit 2-7 ppm off their neighbours (every
# strong peak of a scan moves together), which is a third of a peak width, and
# MALDI spots drift far more. Averaging unaligned scans smears every peak, so
# each scan's relative m/z offset is measured on the strongest isolated peaks of
# the pool and removed before pooling -- and the same offset is applied when the
# pooled peaks are measured back in that scan.
POOL_ALIGN_ANCHORS = 40
POOL_ALIGN_MIN_ANCHORS = 3
POOL_ALIGN_MAX_PPM = 100.0
POOL_ALIGN_ITERATIONS = 2


# SCAN GROUPING
# -------------


def acquisitionkey(meta):
    """Key identifying scans that were acquired the same way.

    meta (dict) - scan metadata as returned by a parser's scanlist()
    """

    msLevel = meta.get("msLevel") or 1
    polarity = meta.get("polarity")

    # the vendor filter string (Thermo) names the analyser, range and scan type;
    # otherwise the instrument configuration a scan refers to separates analysers
    acquisition = meta.get("filterString") or ""
    acquisition = re.sub(r"\s+", " ", acquisition).strip()
    if not acquisition:
        acquisition = meta.get("instrumentConfigurationRef") or ""

    # fragment spectra of different precursors are different spectra
    precursor = None
    if msLevel > 1 and meta.get("precursorMZ") is not None:
        precursor = round(float(meta["precursorMZ"]), 2)

    return (msLevel, polarity, acquisition, precursor)


# ----


def acquisitiongroups(scanlist):
    """Group the scans of a run that may be pooled together.

    scanlist (dict) - {scanID: metadata} as returned by a parser's scanlist()

    Returns a list of scan ID lists, each ordered by retention time. Centroided
    scans are left out (there is no profile to pool). Scans of one group can
    still differ in sampling when the file carries no acquisition metadata; see
    `samplinggroups` for the check made once the profiles are loaded.
    """

    groups = {}
    for scanID, meta in scanlist.items():
        if meta.get("spectrumType") == "discrete":
            continue
        groups.setdefault(acquisitionkey(meta), []).append(scanID)

    def _order(scanID):
        rt = scanlist[scanID].get("retentionTime")
        return (rt is None, rt if rt is not None else 0.0)

    result = []
    for scanIDs in groups.values():
        result.append(sorted(scanIDs, key=_order))

    # stable order: groups appear in the order of their first scan in the file
    position = {scanID: index for index, scanID in enumerate(scanlist)}
    result.sort(key=lambda ids: min(position[i] for i in ids))

    return result


# ----


def _sampling_profile(profile):
    """Native sampling step of a profile as a function of m/z.

    Returns (edges, steps): geometric m/z bins and the lower-quartile step of the
    points falling into each (NaN where the scan has no points). The lower
    quartile ignores the long steps across gaps of zero-dropped data.
    """

    edges = numpy.geomspace(1.0, 1.0e6, 145)
    steps = numpy.full(len(edges) - 1, numpy.nan)
    if len(profile) < 3:
        return edges, steps

    x = profile[:, 0]
    d = numpy.diff(x)
    mid = x[:-1]
    valid = d > 0
    d = d[valid]
    mid = mid[valid]
    bins = numpy.searchsorted(edges, mid, side="right") - 1
    for b in numpy.unique(bins):
        if 0 <= b < len(steps):
            values = d[bins == b]
            if len(values) >= 4:
                steps[b] = numpy.percentile(values, 25)

    return edges, steps


# ----


def samplinggroups(scans):
    """Split scans by sampling density.

    scans (list of mspy.scan) - scans of one acquisition group

    Returns a list of index lists into `scans`. Scans whose sampling step at the
    same m/z differs by more than POOL_SAMPLING_RATIO end up in different groups,
    so data acquired at very different resolutions is never averaged even when
    the file does not say how each scan was acquired.
    """

    groups = []
    references = []
    for index, scan in enumerate(scans):
        _edges, steps = _sampling_profile(scan.profile)

        placed = False
        for g, reference in enumerate(references):
            common = ~numpy.isnan(steps) & ~numpy.isnan(reference)
            if not numpy.any(common):
                continue
            ratio = float(numpy.median(steps[common] / reference[common]))
            if 1.0 / POOL_SAMPLING_RATIO <= ratio <= POOL_SAMPLING_RATIO:
                groups[g].append(index)
                placed = True
                break

        if not placed:
            groups.append([index])
            references.append(steps)

    return groups


# POOLING
# -------


def _native_spacing(x):
    """Sampling step each point of a profile has in its own scan."""

    n = len(x)
    if n < 2:
        return numpy.full(n, numpy.inf)

    d = numpy.diff(x)
    left = numpy.concatenate(([numpy.inf], d))
    right = numpy.concatenate((d, [numpy.inf]))
    return numpy.minimum(left, right)


# ----


def commonraster(profiles):
    """Build the m/z raster a set of profiles is pooled on.

    profiles (list of numpy arrays) - profile data points of each scan
    """

    CHUNK = 32

    unionX = numpy.empty(0)
    unionS = numpy.empty(0)
    for start in range(0, len(profiles), CHUNK):

        CHECK_FORCE_QUIT()

        chunk = [p for p in profiles[start : start + CHUNK] if len(p)]
        if not chunk:
            continue
        x = numpy.concatenate([unionX] + [p[:, 0] for p in chunk])
        s = numpy.concatenate([unionS] + [_native_spacing(p[:, 0]) for p in chunk])

        # exact duplicates (scans on one shared raster) keep the finest step
        order = numpy.lexsort((s, x))
        x = x[order]
        s = s[order]
        keep = numpy.concatenate(([True], numpy.diff(x) > 0))
        unionX = x[keep]
        unionS = s[keep]

    if len(unionX) == 0:
        return unionX

    return calculations.signal_common_raster(
        unionX.astype(numpy.float64),
        unionS.astype(numpy.float64),
        float(POOL_MERGE_FRACTION),
    )


# ----


def _resample(profile, raster):
    """Profile values on the pooled raster, and which nodes the scan covers."""

    values = numpy.zeros(len(raster))
    covered = numpy.zeros(len(raster), dtype=bool)
    if len(profile) == 0 or len(raster) == 0:
        return values, covered

    x = profile[:, 0]
    y = profile[:, 1]

    lo = numpy.searchsorted(raster, x[0], side="left")
    hi = numpy.searchsorted(raster, x[-1], side="right")
    if hi <= lo:
        return values, covered

    values[lo:hi] = numpy.interp(raster[lo:hi], x, y)
    covered[lo:hi] = True

    # nothing above zero was recorded inside a gap of zero-dropped data
    if len(x) > 2:
        d = numpy.diff(x)
        around = numpy.minimum(
            numpy.concatenate(([numpy.inf], d[:-1])),
            numpy.concatenate((d[1:], [numpy.inf])),
        )
        gaps = numpy.nonzero(d > POOL_GAP_FACTOR * around)[0]
        if len(gaps):
            starts = numpy.searchsorted(raster, x[gaps], side="right")
            ends = numpy.searchsorted(raster, x[gaps + 1], side="left")
            marks = numpy.zeros(len(raster) + 1, dtype=numpy.int64)
            numpy.add.at(marks, starts, 1)
            numpy.add.at(marks, ends, -1)
            inside = numpy.cumsum(marks[:-1]) > 0
            values[inside] = 0.0

    return values, covered


# ----


def _shifted(profile, ppm):
    """Profile with its m/z axis moved back by a relative offset (in ppm)."""

    if not ppm or len(profile) == 0:
        return profile

    shifted = profile.copy()
    shifted[:, 0] = profile[:, 0] / (1.0 + ppm * 1e-6)
    return shifted


# ----


def _anchors(points):
    """Strong, well separated peaks of a pooled profile to align scans on.

    Returns a list of (m/z, fwhm, height), strongest first.
    """

    if len(points) < 5:
        return []

    maxima = numpy.asarray(mod_signal.maxima(points), dtype=float)
    if len(maxima) == 0:
        return []
    maxima = maxima[numpy.argsort(-maxima[:, 1])]

    anchors = []
    for mz, height in maxima[: POOL_ALIGN_ANCHORS * 5]:
        if height <= 0.0:
            break
        fwhm = mod_signal.width(points, mz, height * 0.5)
        if not fwhm or fwhm <= 0.0:
            continue
        # a neighbour within a few widths would pull the centroid
        if any(abs(mz - other) < 3.0 * max(fwhm, w) for other, w, _h in anchors):
            continue
        anchors.append((float(mz), float(fwhm), float(height)))
        if len(anchors) >= POOL_ALIGN_ANCHORS:
            break

    return anchors


# ----


def _local_centroid(x, y, center, halfWidth):
    """Half-height centroid of the peak inside center +/- halfWidth (or None)."""

    i1 = numpy.searchsorted(x, center - halfWidth, side="left")
    i2 = numpy.searchsorted(x, center + halfWidth, side="right")
    if i2 - i1 < 2:
        return None

    segX = x[i1:i2]
    segY = y[i1:i2]
    weights = segY - 0.5 * float(numpy.max(segY))
    weights[weights < 0.0] = 0.0
    total = float(numpy.sum(weights))
    if total <= 0.0:
        return None

    return float(numpy.sum(segX * weights) / total)


# ----


def _weighted_median(values, weights):
    """Median of values, each counted with its weight."""

    order = numpy.argsort(values)
    values = numpy.asarray(values)[order]
    weights = numpy.asarray(weights)[order]
    cumulative = numpy.cumsum(weights)
    return float(values[numpy.searchsorted(cumulative, 0.5 * cumulative[-1])])


# ----


def _coarse_offsets(scans):
    """First, coarse relative m/z offset (ppm) of each scan.

    The peak-centroid refinement in `alignmentoffsets` only sees about one peak
    width around each anchor, so a scan shifted further than that (common between
    MALDI spots) would be matched against the wrong side of its own peaks. The
    anchors of the strongest single scan -- unsmeared by pooling -- are slid over
    every scan across +/- POOL_ALIGN_MAX_PPM, in quarter-width steps, and the
    shift that puts most of their signal on the anchors wins.
    """

    offsets = [0.0] * len(scans)

    totals = [float(numpy.sum(s.profile[:, 1])) if s.hasprofile() else 0.0 for s in scans]
    reference = scans[int(numpy.argmax(totals))]
    anchors = _anchors(reference.profile)
    if len(anchors) < POOL_ALIGN_MIN_ANCHORS:
        return offsets

    mzs = numpy.array([mz for mz, _fwhm, _h in anchors])
    heights = numpy.array([h for _mz, _fwhm, h in anchors])
    widthPpm = float(numpy.median([fwhm / mz * 1e6 for mz, fwhm, _h in anchors]))

    # peaks wider than the whole search range: any drift that could be found is
    # a small fraction of a peak width and does not need a coarse step
    if widthPpm > POOL_ALIGN_MAX_PPM:
        return offsets

    step = max(0.25, 0.25 * widthPpm)
    # symmetric about zero, so no shift at all is always one of the candidates
    reach = int(POOL_ALIGN_MAX_PPM // step)
    grid = numpy.arange(-reach, reach + 1) * step
    positions = mzs[numpy.newaxis, :] * (1.0 + grid[:, numpy.newaxis] * 1e-6)

    for i, scan in enumerate(scans):

        CHECK_FORCE_QUIT()

        if not scan.hasprofile():
            continue
        x = scan.profile[:, 0]
        y = scan.profile[:, 1]
        values = numpy.interp(positions.ravel(), x, y, left=0.0, right=0.0)
        values = values.reshape(positions.shape)
        if numpy.count_nonzero(values.max(axis=0) > 0.0) < POOL_ALIGN_MIN_ANCHORS:
            continue
        score = numpy.sum(values / heights[numpy.newaxis, :], axis=1)
        offsets[i] = float(grid[int(numpy.argmax(score))])

    # the pool is calibrated like the typical scan, not like the reference one
    centre = float(numpy.median(offsets))
    return [offset - centre for offset in offsets]


# ----


def alignmentoffsets(scans, raster=None):
    """Relative m/z offset (in ppm) of each scan against the pool of all of them.

    scans (list of mspy.scan) - scans to align (profile data)
    raster (numpy array or None) - pooling raster, built from the scans if None

    A positive offset means the scan reads m/z values that are too high. Offsets
    are found coarsely first (see `_coarse_offsets`, up to POOL_ALIGN_MAX_PPM),
    then refined on the half-height centroids of the strongest isolated peaks of
    the pool. A scan in which too few anchor peaks can be measured keeps the
    offset it has.
    """

    offsets = [0.0] * len(scans)
    if len(scans) < 2:
        return offsets

    if raster is None:
        raster = commonraster([s.profile for s in scans])

    offsets = _coarse_offsets(scans)

    for _iteration in range(POOL_ALIGN_ITERATIONS):

        CHECK_FORCE_QUIT()

        profiles = [_shifted(s.profile, offsets[i]) for i, s in enumerate(scans)]
        reference = _pool(profiles, raster)
        anchors = _anchors(reference)
        if len(anchors) < POOL_ALIGN_MIN_ANCHORS:
            break

        refX = reference[:, 0]
        refY = reference[:, 1]
        references = [_local_centroid(refX, refY, mz, fwhm) for mz, fwhm, _h in anchors]

        for i, profile in enumerate(profiles):

            CHECK_FORCE_QUIT()

            if len(profile) == 0:
                continue
            x = profile[:, 0]
            y = profile[:, 1]
            ppms = []
            weights = []
            for (_mz, fwhm, height), refMz in zip(anchors, references, strict=True):
                if refMz is None:
                    continue
                observed = _local_centroid(x, y, refMz, fwhm)
                if observed is None:
                    continue
                ppms.append((observed - refMz) / refMz * 1e6)
                weights.append(height)

            if len(ppms) < POOL_ALIGN_MIN_ANCHORS:
                continue

            # move only when the anchors agree on it: with wide or noisy peaks the
            # individual readings scatter by more than any real miscalibration,
            # and following their median would shake the scans apart
            correction = _weighted_median(ppms, weights)
            spread = 1.4826 * float(numpy.median(numpy.abs(numpy.array(ppms) - correction)))
            if abs(correction) < 2.0 * spread / math.sqrt(len(ppms)):
                continue
            offsets[i] += correction

    # an offset far past the searched range is a wrong match, not a calibration
    return [0.0 if abs(offset) > 1.5 * POOL_ALIGN_MAX_PPM else offset for offset in offsets]


# ----


def _compact(raster, values):
    """Drop the interior of zero runs, keeping the zeros that frame a peak."""

    if len(raster) == 0:
        return numpy.empty((0, 2))

    zero = values == 0.0
    prevZero = numpy.concatenate(([True], zero[:-1]))
    nextZero = numpy.concatenate((zero[1:], [True]))
    keep = ~(zero & prevZero & nextZero)

    points = numpy.empty((int(numpy.count_nonzero(keep)), 2))
    points[:, 0] = raster[keep]
    points[:, 1] = values[keep]
    return points


# ----


def _pooledscan(scans, points):
    """Make the pooled scan object, carrying metadata shared by its scans."""

    pooled = obj_scan.scan(profile=points)

    first = scans[0]
    pooled.msLevel = first.msLevel
    pooled.polarity = first.polarity
    pooled.precursorMZ = first.precursorMZ
    pooled.precursorCharge = first.precursorCharge

    times = [s.retentionTime for s in scans if s.retentionTime is not None]
    if times:
        pooled.retentionTime = sum(times) / len(times)

    pooled.attributes["pooledScans"] = [s.scanNumber for s in scans]

    return pooled


# ----


def _pool(profiles, raster):
    """Average profiles on a raster; returns compacted profile points."""

    total = numpy.zeros(len(raster))
    coverage = numpy.zeros(len(raster))
    for profile in profiles:

        CHECK_FORCE_QUIT()

        values, covered = _resample(profile, raster)
        total += values
        coverage += covered

    mean = numpy.divide(
        total, coverage, out=numpy.zeros(len(raster)), where=coverage > 0
    )

    return _compact(raster, mean)


# ----


def poolscans(scans, align=True, raster=None):
    """Average the profiles of several scans on one shared m/z raster.

    scans (list of mspy.scan) - scans to pool (a scan without profile data
        contributes nothing but keeps its place in the offsets)
    align (bool) - remove each scan's relative m/z offset before pooling
    raster (numpy array or None) - raster to use, built from the scans if None

    The average (not the sum) keeps intensities on the scale of a single scan, so
    absolute intensity thresholds keep their meaning, while the noise drops with
    the number of scans pooled. At every m/z only the scans whose range covers it
    are averaged. The per-scan offsets (ppm, in the order of `scans`) are stored
    in the pooled scan's attributes as "alignment".
    """

    if raster is None:
        raster = commonraster([s.profile for s in scans])

    offsets = alignmentoffsets(scans, raster) if align else [0.0] * len(scans)
    profiles = [_shifted(s.profile, offsets[i]) for i, s in enumerate(scans)]

    # shifted scans no longer share the raster they were measured on; a raster
    # built from their shifted points keeps every scan's own samples on a node
    if any(offsets):
        raster = commonraster(profiles)

    pooled = _pooledscan(scans, _pool(profiles, raster))
    pooled.attributes["alignment"] = offsets

    return pooled


# ----


def poolwindows(scans, window, align=True):
    """Yield (index, pooled scan) averaging each scan with its neighbours.

    scans (list of mspy.scan) - scans of one group, ordered by retention time
    window (int) - number of neighbouring scans on EACH side pooled with a scan
    align (bool) - remove each scan's relative m/z offset before pooling

    Suited to real chromatography, where a species elutes over a few scans only:
    averaging the whole run would dilute it with scans in which it is absent.
    The raster and the scan offsets are shared by all windows (offsets are
    measured against the whole group, which has the most anchor peaks), and
    running sums keep the cost linear in the number of scans. Each pooled scan
    carries the offsets of its own scans as "alignment", and the offset of the
    scan it is centred on as "offset".
    """

    n = len(scans)
    if n == 0:
        return

    window = max(0, int(window))
    raster = commonraster([s.profile for s in scans])
    offsets = alignmentoffsets(scans, raster) if align else [0.0] * n
    if any(offsets):
        raster = commonraster(
            [_shifted(s.profile, offsets[i]) for i, s in enumerate(scans)]
        )

    total = numpy.zeros(len(raster))
    coverage = numpy.zeros(len(raster), dtype=numpy.int64)
    nonzero = numpy.zeros(len(raster), dtype=numpy.int64)
    cache = {}

    def _add(i, sign):
        if i not in cache:
            cache[i] = _resample(_shifted(scans[i].profile, offsets[i]), raster)
        values, covered = cache[i]
        total[:] += sign * values
        coverage[:] += sign * covered
        nonzero[:] += sign * (values != 0.0)

    lo = 0
    hi = -1
    for index in range(n):

        CHECK_FORCE_QUIT()

        newLo = max(0, index - window)
        newHi = min(n - 1, index + window)
        while hi < newHi:
            hi += 1
            _add(hi, 1)
        while lo < newLo:
            _add(lo, -1)
            del cache[lo]
            lo += 1

        mean = numpy.divide(
            total, coverage, out=numpy.zeros(len(raster)), where=coverage > 0
        )
        # running sums leave float residue where the removed scans had signal
        mean[nonzero == 0] = 0.0

        pooled = _pooledscan(scans[lo : hi + 1], _compact(raster, mean))
        pooled.attributes["alignment"] = offsets[lo : hi + 1]
        pooled.attributes["offset"] = offsets[index]
        yield index, pooled


# LABELLING POOLED PEAKS IN A SCAN
# --------------------------------


def _height(x, y, mz, halfWindow):
    """Height of the profile at a pooled peak position, following small drift."""

    if len(x) == 0:
        return 0.0

    height = float(numpy.interp(mz, x, y, left=0.0, right=0.0))
    i1 = numpy.searchsorted(x, mz - halfWindow, side="left")
    i2 = numpy.searchsorted(x, mz + halfWindow, side="right")
    if i2 > i1:
        height = max(height, float(numpy.max(y[i1:i2])))

    return height


# ----


def _baseline_at(baseline, mz):
    """Baseline level and noise width at m/z (0 and None without a baseline)."""

    if baseline is None or len(baseline) == 0:
        return 0.0, None

    level = float(numpy.interp(mz, baseline[:, 0], baseline[:, 1]))
    noise = float(numpy.interp(mz, baseline[:, 0], baseline[:, 2]))
    return level, (noise if noise > 0.0 else None)


# ----


def _measure(x, y, baseline, mz, fwhm):
    """(ai, base, sn) of a pooled peak position in one scan."""

    halfWindow = POOL_HEIGHT_WINDOW * fwhm if fwhm and fwhm > 0.0 else 0.0
    ai = _height(x, y, mz, halfWindow)
    base, noise = _baseline_at(baseline, mz)
    sn = (ai - base) / noise if noise else None
    return ai, base, sn


# ----


def _is_present(ai, base, sn, snThreshold):
    """Same acceptance rule labelscan applies to a picked peak."""

    return (ai - base) > 0.0 and (not sn or sn >= snThreshold)


# ----


def _envelope_display(envelope, measured, label, intensity):
    """Representative (ai, base, sn) of an envelope, as the pipeline builds it.

    measured holds (ai, base, sn) at each isotope position of the envelope. Only
    the DETECTED isotopes count, exactly as labelling a freshly picked cluster
    counts its detected peaks and none of its modelled tail.
    """

    detected = max(1, min(len(measured), int(envelope.get("detected", 1) or 1)))
    real = measured[:detected]

    # "1st" reports the monoisotopic peak; the other labels the cluster base peak
    if label in ("monoisotope", "centroid"):
        index = max(range(len(real)), key=lambda i: real[i][0] - real[i][1])
    else:
        index = 0
    ai, base, sn = real[index]

    total = sum(max(0.0, a - b) for a, b, _sn in real)
    if intensity == "sum":
        displayAI = base + total
    elif intensity == "average":
        displayAI = base + total / len(measured)
    else:
        displayAI = ai

    if sn and ai != base:
        sn = (displayAI - base) * sn / (ai - base)

    return displayAI, base, sn


# ----


def labelpooled(
    signal,
    features,
    baseline=None,
    snThreshold=0.0,
    label="1st",
    intensity="maximum",
    nonIdeality=None,
    averagineType=mod_peakpicking.DEFAULT_AVERAGINE,
    refinePattern=True,
    alignment=0.0,
):
    """Label peaks found in a pooled spectrum in one of the pooled scans.

    signal (numpy array) - profile of the scan to label
    features (mspy.peaklist) - peaks picked in the pooled spectrum
    baseline (numpy array) - baseline of the scan (as scan.baseline() returns)
    snThreshold (float) - minimal S/N a peak needs in this scan to be labelled
    alignment (float) - the scan's m/z offset against the pool in ppm (see
        alignmentoffsets); removed before measuring, so the pooled positions are
        read where this scan actually recorded them
    label, intensity, nonIdeality, averagineType, refinePattern - envelope
        labelling settings, as for relabelenvelopes

    Every labelled peak keeps its pooled m/z, charge, isotope, FWHM and group;
    its intensity, baseline and S/N are measured in the scan. An envelope keeps
    its pooled isotope positions and has its area re-fit to the scan with the same
    overlap-aware joint fit picking uses. A peak (or envelope, judged at its
    theoretically tallest isotope) below `snThreshold` in the scan is left out --
    but a missing envelope still takes part in the area fit, so a neighbour cannot
    claim whatever signal it does have.
    """

    if not isinstance(features, obj_peaklist.peaklist):
        raise TypeError("Features must be mspy.peaklist object!")

    if signal is None or len(signal) == 0 or not len(features):
        return obj_peaklist.peaklist([])

    # measure on the pool's m/z axis
    signal = _shifted(signal, alignment)
    if baseline is not None and len(baseline):
        baseline = _shifted(baseline, alignment)

    x = signal[:, 0]
    y = signal[:, 1]

    defaultFwhm = 0.1
    if features.basepeak is not None and features.basepeak.fwhm:
        defaultFwhm = features.basepeak.fwhm

    labelled = []

    # envelopes: all member peaks of one envelope share one metadata dict
    envelopes = []
    envelopeMembers = {}
    for index in range(len(features)):
        peak = features[index]
        envelope = peak.attributes.get("envelope") if hasattr(peak, "attributes") else None
        if isinstance(envelope, dict) and envelope.get("isotopes"):
            key = id(envelope)
            if key not in envelopeMembers:
                envelopeMembers[key] = []
                envelopes.append(envelope)
            envelopeMembers[key].append(index)
            continue

        CHECK_FORCE_QUIT()

        # plain peak (charged or not)
        fwhm = peak.fwhm or defaultFwhm
        ai, base, sn = _measure(x, y, baseline, peak.mz, fwhm)
        if not _is_present(ai, base, sn, snThreshold):
            continue
        new = copy.deepcopy(peak)
        new.setai(ai)
        new.setbase(base)
        new.setsn(sn)
        labelled.append(new)

    # measure every envelope and decide which are present in this scan
    clusters = []
    present = []
    measurements = []
    for envelope in envelopes:

        CHECK_FORCE_QUIT()

        members = [features[i] for i in envelopeMembers[id(envelope)]]
        parent = min(members, key=lambda p: (p.isotope or 0, p.mz))
        fwhm = float(envelope.get("fwhm") or parent.fwhm or defaultFwhm)

        isotopes = [(float(mz), float(w)) for mz, w in envelope["isotopes"]]
        measured = [_measure(x, y, baseline, mz, fwhm) for mz, _w in isotopes]
        apex = max(range(len(isotopes)), key=lambda i: isotopes[i][1])
        ai, base, sn = measured[apex]
        present.append(_is_present(ai, base, sn, snThreshold))
        measurements.append(measured)

        # the cluster the pooled envelope was fitted as: positions from the pool,
        # its representative intensity from this scan
        seed = copy.deepcopy(parent)
        seed.setai(measured[0][0])
        seed.setbase(measured[0][1])
        seed.setsn(measured[0][2])
        seed.setfwhm(fwhm)
        seed.setisotope(0)
        clusters.append(
            mod_peakpicking._reconstruct_cluster_from_envelope(
                seed, envelope, averagineType=averagineType
            )
        )

    # one joint fit over present AND missing envelopes, so the overlap groups are
    # the pooled ones and a missing species still accounts for its own signal
    if clusters:
        areas, shapes = mod_peakpicking._fit_envelope_areas_shaped(
            clusters,
            signal,
            defaultFwhm,
            nonIdeality=nonIdeality,
            averagineType=averagineType,
            refinePattern=refinePattern,
        )
    else:
        areas, shapes = [], []

    for k, envelope in enumerate(envelopes):
        if not present[k]:
            continue

        CHECK_FORCE_QUIT()

        members = [features[i] for i in envelopeMembers[id(envelope)]]
        fwhm = float(envelope.get("fwhm") or defaultFwhm)

        # normalise the fitted shape and rescale the area by the same sum, as
        # relabelenvelopes does, so areas stay on the common scale
        isotopes = shapes[k] if k < len(shapes) and shapes[k] else list(envelope["isotopes"])
        area = float(max(0.0, areas[k])) if k < len(areas) else 0.0
        shapeSum = math.fsum(float(w) for _mz, w in isotopes)
        if shapeSum > 0.0:
            isotopes = [(float(mz), float(w) / shapeSum) for mz, w in isotopes]
            area *= shapeSum
        sigma = mod_peakpicking._fwhm_to_sigma(fwhm)
        norm = sigma * math.sqrt(2.0 * math.pi)
        weightSum = sum(float(w) for _mz, w in isotopes)

        updated = dict(envelope)
        updated["area"] = area
        updated["sumint"] = (area / norm) * weightSum if norm > 0.0 else 0.0
        updated["isotopes"] = isotopes

        if label == "isotopes":
            # every isotope is its own labelled peak, measured at its own m/z
            for peak in members:
                ai, base, sn = _measure(x, y, baseline, peak.mz, fwhm)
                new = copy.deepcopy(peak)
                new.setai(ai)
                new.setbase(base)
                new.setsn(sn)
                new.attributes["envelope"] = updated
                labelled.append(new)
        else:
            ai, base, sn = _envelope_display(
                envelope, measurements[k], label, intensity
            )
            for peak in members:
                new = copy.deepcopy(peak)
                new.setai(ai)
                new.setbase(base)
                new.setsn(sn)
                new.attributes["envelope"] = updated
                labelled.append(new)

    return obj_peaklist.peaklist(labelled)


# ----
