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
5. ``guidinggroups`` / ``crossguide`` let a finer acquisition guide a coarser one
   recording the same ions (Orbitrap and ion trap full scans of one run): the
   coarse analyser cannot resolve isotopes, so its own pool gives blends with
   wrong charges. The finer pool's species are labelled in the coarse scans
   instead, at the coarse analyser's own peak width and calibration.
"""

# load libs
import copy
import math
import re

import numpy

# load stopper
from .mod_stopper import CHECK_FORCE_QUIT

# load objects
from . import obj_peak
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

# Guidance between acquisitions. The coarse analyser's width and m/z offset are
# found by broadening the fine pool until it looks like the coarse one: offsets
# are measured in this many stretches of equal coarse signal (an ion trap's offset
# against an Orbitrap drifts by a fraction of a peak width along m/z), a stretch
# counts only when the broadened reference correlates with it at least this well,
# and the width read from the coarse peaks (those at least this fraction of the
# strongest) is refined in each stretch by these factors.
POOL_GUIDE_SEGMENTS = 6
POOL_GUIDE_ANCHOR_FRACTION = 0.05
POOL_GUIDE_NOISE_WIDTHS = 2.0
POOL_GUIDE_MIN_CORRELATION = 0.5
POOL_GUIDE_SCALES = tuple(2.0 ** (i / 6.0) for i in range(-12, 13))
POOL_GUIDE_GRID_POINTS = 2000000
POOL_GUIDE_ITERATIONS = 2

# A species that the reference predicts to be less than this fraction of the
# signal at its own tallest isotope is not labelled in a guided scan: that
# analyser records it as part of a much stronger neighbour's peak.
POOL_GUIDE_MIN_SHARE = 0.1

# Local placement in a scan (see _local_shifts): how far, as a fraction of the
# FWHM, a group of species may slide from its modelled position, and how well
# its shape must then match.
POOL_LOCAL_REACH = 0.5
POOL_LOCAL_MIN_CORRELATION = 0.8

# Area of a Gaussian peak of height 1 and FWHM 1.
GAUSSIAN_AREA = math.sqrt(math.pi / (4.0 * math.log(2.0)))


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


# ----


def _set_steps(scans):
    """Sampling step profile of a set of scans (median of its first few)."""

    rows = [_sampling_profile(s.profile)[1] for s in scans[:5] if s.hasprofile()]
    if not rows:
        return None

    stack = numpy.vstack(rows)
    steps = numpy.full(stack.shape[1], numpy.nan)
    for b in range(stack.shape[1]):
        column = stack[:, b][~numpy.isnan(stack[:, b])]
        if len(column):
            steps[b] = float(numpy.median(column))

    return steps


# ----


def guidinggroups(scanSets, keys):
    """Pair each set of scans with a finer acquisition of the same ions.

    scanSets (list of lists of mspy.scan) - the poolable scan sets of one run
    keys (list) - acquisitionkey of each set

    Returns, for each set, the index of the set whose species should be labelled
    in it, or None when it is picked from its own pool. A set is guided by the
    finest set of the same MS level, polarity and precursor that samples the m/z
    both cover at least POOL_SAMPLING_RATIO times more densely. Whether its peaks
    really are that much narrower is checked by `crossguide`.
    """

    steps = [_set_steps(scans) for scans in scanSets]
    result: list[int | None] = [None] * len(scanSets)

    for i, key in enumerate(keys):
        mine = steps[i]
        if mine is None:
            continue
        bestRatio = POOL_SAMPLING_RATIO
        for j, other in enumerate(keys):
            theirs = steps[j]
            if j == i or theirs is None:
                continue
            if (key[0], key[1], key[3]) != (other[0], other[1], other[3]):
                continue
            common = ~numpy.isnan(mine) & ~numpy.isnan(theirs)
            if not numpy.any(common):
                continue
            ratio = float(numpy.median(mine[common] / theirs[common]))
            if ratio >= bestRatio:
                result[i] = j
                bestRatio = ratio

    # a guide is picked from its own pool: follow a chain to its finest end
    for i in range(len(result)):
        seen = {i}
        guide = result[i]
        while guide is not None:
            further = result[guide]
            if further is None or further in seen:
                break
            seen.add(further)
            guide = further
        result[i] = guide

    return result


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


def _pooledscan(scans, points=None, peaklist=None):
    """Make the pooled scan object, carrying metadata shared by its scans.

    The pooled scan holds profile points, or (centroided scans) a peaklist.
    """

    if peaklist is not None:
        pooled = obj_scan.scan(peaklist=peaklist)
    else:
        pooled = obj_scan.scan(profile=points)

    first = scans[0]
    pooled.msLevel = first.msLevel
    pooled.polarity = first.polarity
    pooled.precursorMZ = first.precursorMZ
    pooled.precursorCharge = first.precursorCharge

    # fragment spectra of one precursor record it at slightly different m/z
    precursors = [s.precursorMZ for s in scans if s.precursorMZ is not None]
    if precursors:
        pooled.precursorMZ = sum(precursors) / len(precursors)

    times = [s.retentionTime for s in scans if s.retentionTime is not None]
    if times:
        pooled.retentionTime = sum(times) / len(times)

    pooled.attributes["pooledScans"] = [s.scanNumber for s in scans]

    return pooled


# ----


def _pool(profiles, raster, average=True):
    """Average (or sum) profiles on a raster; returns compacted profile points."""

    total = numpy.zeros(len(raster))
    coverage = numpy.zeros(len(raster))
    for profile in profiles:

        CHECK_FORCE_QUIT()

        values, covered = _resample(profile, raster)
        total += values
        coverage += covered

    if not average:
        return _compact(raster, total)

    mean = numpy.divide(
        total, coverage, out=numpy.zeros(len(raster)), where=coverage > 0
    )

    return _compact(raster, mean)


# ----


def poolscans(scans, align=True, raster=None, average=True):
    """Average the profiles of several scans on one shared m/z raster.

    scans (list of mspy.scan) - scans to pool (a scan without profile data
        contributes nothing but keeps its place in the offsets)
    align (bool) - remove each scan's relative m/z offset before pooling
    raster (numpy array or None) - raster to use, built from the scans if None
    average (bool) - average the scans (True) or sum them (False)

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

    pooled = _pooledscan(scans, _pool(profiles, raster, average))
    pooled.attributes["alignment"] = offsets

    return pooled


# ----


def combinescans(scans, average=True, align=True):
    """Combine scans of one acquisition into a single spectrum.

    scans (list of mspy.scan) - scans to combine, e.g. those under a range of a
        chromatogram trace
    average (bool) - average the scans (True) or sum them (False)
    align (bool) - remove each scan's relative m/z offset before combining

    Returns (combined scan, indexes into `scans` of the scans used), or
    (None, []) when there is nothing to combine. Profiles are combined when
    any scan has one, and the peaks picked in single scans do not carry over;
    scans sampled at very different densities are never combined (see
    `samplinggroups`) -- when the scans fall into several such groups the
    largest one is used. Centroided scans (peak lists only, as most MS/MS
    spectra are stored) are combined peak by peak (see `combinecentroids`).
    """

    indexes = [i for i, s in enumerate(scans) if s.hasprofile()]
    if not indexes:
        return combinecentroids(scans, average=average)

    groups = samplinggroups([scans[i] for i in indexes])
    used = [indexes[i] for i in max(groups, key=len)]
    members = [scans[i] for i in used]

    combined = poolscans(members, align=align and len(members) > 1, average=average)
    combined.scanNumber = None
    filterString = members[0].attributes.get("filterString")
    if filterString:
        combined.attributes["filterString"] = filterString

    return combined, used


# ----


def _centroid_tolerance(lists):
    """Largest m/z difference (Da, as a function of m/z) of one peak between scans.

    Two peaks of one scan are distinct, so a peak cannot move between scans by
    as much as the closest peaks of a scan lie apart: half the closest spacing
    (the 5th percentile, in Da and relative) is taken. The Da term holds for
    analysers of constant width (an ion trap centroids no closer than ~0.6 Da),
    the relative one for those whose width grows with m/z.
    """

    steps = []
    relative = []
    for mz in lists:
        if len(mz) < 2:
            continue
        d = numpy.diff(mz)
        keep = d > 0
        steps.append(d[keep])
        relative.append(d[keep] / mz[:-1][keep])
    if not steps:
        return 0.0, 0.0

    steps = numpy.concatenate(steps)
    relative = numpy.concatenate(relative)
    return 0.5 * float(numpy.percentile(steps, 5)), 0.5 * float(numpy.percentile(relative, 5))


# ----


def combinecentroids(scans, average=True):
    """Combine the peak lists of centroided scans into one.

    scans (list of mspy.scan) - scans holding peak lists
    average (bool) - average the intensities over the scans (True, a peak
        missing in a scan counting as zero there) or sum them (False)

    Peaks of different scans closer than the centroid tolerance (see
    `_centroid_tolerance`) are one peak, taking at most one peak of each scan;
    its m/z is their intensity-weighted mean. Returns (combined scan, indexes
    into `scans` of the scans used), or (None, []) when no scan has peaks.
    """

    used = [i for i, s in enumerate(scans) if len(s.peaklist)]
    if not used:
        return None, []

    lists = []
    for i in used:
        mz = numpy.array([peak.mz for peak in scans[i].peaklist], dtype=float)
        ai = numpy.array([peak.ai for peak in scans[i].peaklist], dtype=float)
        order = numpy.argsort(mz)
        lists.append((mz[order], ai[order]))

    tolDa, tolRel = _centroid_tolerance([mz for mz, _ai in lists])

    mz = numpy.concatenate([item[0] for item in lists])
    ai = numpy.concatenate([item[1] for item in lists])
    owner = numpy.concatenate([numpy.full(len(item[0]), n) for n, item in enumerate(lists)])
    order = numpy.argsort(mz, kind="stable")
    mz, ai, owner = mz[order], ai[order], owner[order]

    scale = 1.0 / len(used) if average else 1.0
    peaks = []
    start = 0
    while start < len(mz):

        CHECK_FORCE_QUIT()

        tolerance = max(tolDa, tolRel * mz[start])
        owners = {int(owner[start])}
        end = start + 1
        while (
            end < len(mz)
            and mz[end] - mz[start] <= tolerance
            and int(owner[end]) not in owners
        ):
            owners.add(int(owner[end]))
            end += 1

        weights = ai[start:end]
        if weights.sum() > 0:
            centre = float(numpy.average(mz[start:end], weights=weights))
        else:
            centre = float(mz[start:end].mean())
        peaks.append(obj_peak.peak(mz=centre, ai=float(weights.sum()) * scale))
        start = end

    combined = _pooledscan([scans[i] for i in used], peaklist=obj_peaklist.peaklist(peaks))
    combined.scanNumber = None
    filterString = scans[used[0]].attributes.get("filterString")
    if filterString:
        combined.attributes["filterString"] = filterString

    return combined, used


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


# GUIDANCE BETWEEN ACQUISITIONS
# -----------------------------


def _peak_widths(profile):
    """(m/z, FWHM) arrays of the strongest separated peaks of a profile.

    Noise maxima are narrow too: only peaks that stand out, and that span more
    than a couple of sampling steps, can tell the width.
    """

    anchors = _anchors(profile)
    if anchors:
        x = profile[:, 0]
        steps = _native_spacing(x)
        strongest = max(h for _mz, _w, h in anchors)
        anchors = [
            (mz, w)
            for mz, w, h in anchors
            if h >= POOL_GUIDE_ANCHOR_FRACTION * strongest
            and w >= 2.0 * steps[min(len(x) - 1, int(numpy.searchsorted(x, mz)))]
        ]
    if len(anchors) < POOL_ALIGN_MIN_ANCHORS:
        return None

    return numpy.array([a[0] for a in anchors]), numpy.array([a[1] for a in anchors])


# ----


def _guide_fwhm(guide, mz):
    """FWHM the guided analyser records at m/z."""

    coefficient, exponent = guide["fwhm"]
    return coefficient * numpy.power(mz, exponent)


# ----


def _guide_shift(guide, mz):
    """How far above the reference the guided analyser reads m/z (in Da)."""

    slope, intercept, first, last = guide["shift"]
    return intercept + slope * numpy.clip(numpy.asarray(mz, dtype=float), first, last)


# ----


def _match(x, y, grid, model, reach, step):
    """Shift of the model that correlates best with (x, y): (shift, correlation)."""

    yNorm = math.sqrt(float(numpy.sum(y * y)))
    if yNorm <= 0.0:
        return 0.0, 0.0

    shifts = numpy.arange(-reach, reach + 0.5 * step, step)
    scores = numpy.zeros(len(shifts))
    for k, shift in enumerate(shifts):
        values = numpy.interp(x - shift, grid, model, left=0.0, right=0.0)
        norm = math.sqrt(float(numpy.sum(values * values)))
        if norm > 0.0:
            scores[k] = float(numpy.sum(y * values)) / (yNorm * norm)

    k = int(numpy.argmax(scores))
    shift = float(shifts[k])
    if 0 < k < len(shifts) - 1:
        curvature = scores[k - 1] - 2.0 * scores[k] + scores[k + 1]
        if curvature < 0.0:
            shift += 0.5 * step * (scores[k - 1] - scores[k + 1]) / curvature

    return shift, float(scores[k])


# ----


def _correlation(x, y, values):
    """Normalised correlation of two signals sampled at the same points."""

    norm = math.sqrt(float(numpy.sum(y * y)) * float(numpy.sum(values * values)))
    return float(numpy.sum(y * values)) / norm if norm > 0.0 else 0.0


# ----


def _above_noise(profile):
    """Profile with its noise removed: only what rises above baseline + noise width.

    Broadening lowers a peak by the ratio of the two widths but leaves a noise
    floor as it is, so a floor that is negligible in the fine pool would outweigh
    its peaks once broadened, and decide the match.
    """

    points = numpy.array(profile, dtype=numpy.float64)
    if len(points) < 2:
        return points
    baseline = mod_signal.baseline(points, window=0.1)
    floor = baseline[:, 1] + POOL_GUIDE_NOISE_WIDTHS * baseline[:, 2]
    points[:, 1] = numpy.clip(
        points[:, 1] - numpy.interp(points[:, 0], baseline[:, 0], floor), 0.0, None
    )
    return points


# ----


def _reference_arrays(profile):
    """(m/z, intensity, sampling step) of a reference profile, ready to broaden."""

    points = _above_noise(profile)
    mz = numpy.ascontiguousarray(points[:, 0], dtype=numpy.float64)
    intensity = numpy.ascontiguousarray(points[:, 1], dtype=numpy.float64)
    spacing = _native_spacing(mz)
    spacing[~numpy.isfinite(spacing)] = 0.0
    return mz, intensity, spacing


# ----


def _broadened(reference, positions, fwhm):
    """The reference as the guided analyser would record it, at sorted positions."""

    positions = numpy.ascontiguousarray(positions, dtype=numpy.float64)
    sigma = numpy.broadcast_to(numpy.asarray(fwhm, dtype=numpy.float64), positions.shape)
    sigma = numpy.ascontiguousarray(sigma / (2.0 * math.sqrt(2.0 * math.log(2.0))))
    mz, intensity, spacing = reference
    return calculations.signal_gaussian_blur(mz, intensity, spacing, positions, sigma)


# ----


def _guide_model(reference, guide):
    """Broadened reference on a grid fine enough to shift it over: (positions, values)."""

    lo, hi = guide["range"]
    finest = float(min(_guide_fwhm(guide, lo), _guide_fwhm(guide, hi)))
    count = int(min(POOL_GUIDE_GRID_POINTS, max(2, (hi - lo) / (0.1 * finest))))
    positions = numpy.linspace(lo, hi, count)
    return positions, _broadened(reference, positions, _guide_fwhm(guide, positions))


# ----


def _inside(profile, guide):
    """(x, y) of the points of a noise-clipped profile inside the guide's range."""

    lo, hi = guide["range"]
    inside = (profile[:, 0] >= lo) & (profile[:, 0] <= hi)
    return profile[inside, 0], profile[inside, 1]


# ----


def _segments(x, y):
    """Stretches of equal signal: a list of (slice, signal-weighted centre)."""

    cumulative = numpy.cumsum(y)
    edges = numpy.searchsorted(
        cumulative, numpy.linspace(0.0, cumulative[-1], POOL_GUIDE_SEGMENTS + 1)
    )
    edges[0] = 0
    edges[-1] = len(x)

    segments = []
    for k in range(POOL_GUIDE_SEGMENTS):
        if edges[k + 1] - edges[k] < 2:
            continue
        segment = slice(int(edges[k]), int(edges[k + 1]))
        weight = max(float(numpy.sum(y[segment])), 1e-300)
        segments.append((segment, float(numpy.sum(x[segment] * y[segment]) / weight)))

    return segments


# ----


def _fit_shift(guide, x, y, segments, model):
    """Straight line through the shifts of the stretches that match, or None.

    model - (positions, values) of the broadened reference
    """

    positions = []
    values = []
    weights = []
    for segment, centre in segments:

        CHECK_FORCE_QUIT()

        fwhm = float(_guide_fwhm(guide, centre))
        shift, score = _match(x[segment], y[segment], model[0], model[1], 1.5 * fwhm, fwhm / 40.0)
        if score >= POOL_GUIDE_MIN_CORRELATION:
            positions.append(centre)
            values.append(shift)
            weights.append(score)
    if not positions:
        return None

    # a calibration difference is smooth along m/z; a line through the stretches
    # correlates as well as following each of them, with less noise
    first = min(positions)
    last = max(positions)
    if len(positions) >= 3 and last > first:
        slope, intercept = numpy.polyfit(positions, values, 1, w=weights)
        return float(slope), float(intercept), first, last
    return 0.0, float(numpy.average(values, weights=weights)), first, last


# ----


def _fit_width(reference, guide, x, y, anchors):
    """(coefficient, exponent) of the guided FWHM, or None.

    anchors - (m/z, FWHM) arrays of the guided pool's strongest separated peaks

    Around each of those peaks the width is the one at which the broadened
    reference, read where the guided analyser records it, correlates best. Only
    about one peak is compared at a time: over a wider stretch, species whose
    relative intensities differ between the analysers make a wider model fit
    better, and a model wider than the peaks reads their tops too low. How the
    width grows with m/z (constant in a trap, rising in a TOF, an Orbitrap or an
    FT-ICR) is fitted through the peaks, after dropping those a blend or a
    species missing from the reference sets far off the others.
    """

    positions = []
    logWidths = []
    weights = []
    for mz in anchors[0]:
        base = float(_guide_fwhm(guide, mz))
        window = (x >= mz - 1.5 * base) & (x <= mz + 1.5 * base)
        if numpy.count_nonzero(window) < 4:
            continue
        segX = x[window]
        segY = y[window]
        shifted = segX - _guide_shift(guide, segX)
        scores = []
        for scale in POOL_GUIDE_SCALES:

            CHECK_FORCE_QUIT()

            scores.append(_correlation(segX, segY, _broadened(reference, shifted, base * scale)))
        k = int(numpy.argmax(scores))
        if scores[k] < POOL_GUIDE_MIN_CORRELATION:
            continue
        logWidth = math.log(base * POOL_GUIDE_SCALES[k])
        if 0 < k < len(scores) - 1:
            curvature = scores[k - 1] - 2.0 * scores[k] + scores[k + 1]
            if curvature < 0.0:
                step = math.log(POOL_GUIDE_SCALES[k + 1] / POOL_GUIDE_SCALES[k])
                logWidth += 0.5 * step * (scores[k - 1] - scores[k + 1]) / curvature
        positions.append(math.log(mz))
        logWidths.append(logWidth)
        weights.append(scores[k])
    if not positions:
        return None

    positions = numpy.array(positions)
    logWidths = numpy.array(logWidths)
    weights = numpy.array(weights)
    keep = numpy.ones(len(positions), dtype=bool)
    exponent = 0.0
    intercept = 0.0
    for _iteration in range(3):
        exponent = 0.0
        if numpy.count_nonzero(keep) >= 3 and numpy.ptp(positions[keep]) > 0.05:
            exponent = float(
                numpy.polyfit(positions[keep], logWidths[keep], 1, w=weights[keep])[0]
            )
            exponent = min(2.0, max(0.0, exponent))
        intercept = _weighted_median(
            logWidths[keep] - exponent * positions[keep], weights[keep]
        )
        residual = logWidths - (intercept + exponent * positions)
        spread = 1.4826 * float(numpy.median(numpy.abs(residual[keep])))
        # log-widths within 5% of each other need no trimming
        updated = numpy.abs(residual) <= max(3.0 * spread, 0.05)
        if numpy.array_equal(updated, keep) or numpy.count_nonzero(updated) == 0:
            break
        keep = updated

    return math.exp(intercept), exponent


# ----


def _measure_guide(reference, own, guide):
    """Refine a guide's shift and width against a noise-clipped guided pool."""

    anchors = _peak_widths(own)
    if anchors is None:
        return None
    x, y = _inside(own, guide)
    if len(x) < 2 or float(numpy.sum(y)) <= 0.0:
        return None
    segments = _segments(x, y)

    line = _fit_shift(guide, x, y, segments, _guide_model(reference, guide))
    if line is None:
        return None
    guide["shift"] = line

    fwhm = _fit_width(reference, guide, x, y, anchors)
    if fwhm is not None:
        guide["fwhm"] = fwhm

    model = _guide_model(reference, guide)
    line = _fit_shift(guide, x, y, segments, model)
    if line is None:
        return None
    guide["shift"] = line
    guide["correlation"] = _correlation(
        x, y, numpy.interp(x - _guide_shift(guide, x), model[0], model[1], left=0.0, right=0.0)
    )

    return guide


# ----


def _scan_offsets(reference, guide, profiles):
    """How far each guided scan reads above the guide's shift line (Da).

    Scans of a trap jitter by a good fraction of their peak width, far more than
    the ppm alignment of `alignmentoffsets` is built to follow. Each scan is
    matched as a whole against the broadened reference; a scan that does not
    match keeps the typical offset.
    """

    model = _guide_model(reference, guide)
    offsets: list[float | None] = [None] * len(profiles)
    for i, profile in enumerate(profiles):

        CHECK_FORCE_QUIT()

        if len(profile) < 2:
            continue
        x, y = _inside(_above_noise(profile), guide)
        if len(x) < 2 or float(numpy.sum(y)) <= 0.0:
            continue
        centre = float(numpy.sum(x * y) / numpy.sum(y))
        fwhm = float(_guide_fwhm(guide, centre))
        shift, score = _match(x - _guide_shift(guide, x), y, model[0], model[1], fwhm, fwhm / 10.0)
        if score >= POOL_GUIDE_MIN_CORRELATION:
            offsets[i] = shift

    # the shift line is measured on the pool, which reads like the typical scan
    matched = [offset for offset in offsets if offset is not None]
    centre = float(numpy.median(matched)) if matched else 0.0
    return [offset - centre if offset is not None else 0.0 for offset in offsets]


# ----


def crossguide(reference, guided):
    """Measure how a coarser acquisition records the ions of a finer one.

    reference (mspy.scan) - pooled scan of the finer acquisition
    guided (mspy.scan or list of mspy.scan) - the coarser acquisition: its scans,
        or one (pooled) scan

    Returns a guide for `labelpooled` (take one scan's with `scanguide`), or None
    when the two cannot be matched: the guided peaks are not POOL_SAMPLING_RATIO
    times wider, there are too few peaks, or the reference broadened to the
    guided width does not resemble the guided signal anywhere. The guide holds:

    "fwhm" - (coefficient, exponent) of the guided FWHM = coefficient * mz**exponent
    "shift" - (slope, intercept, first, last): the guided analyser reads m/z
        intercept + slope * mz Da above the reference, held flat outside the
        first..last m/z where it was measured
    "offsets" - how many Da each guided scan reads above that line
    "range" - (lo, hi) m/z both acquisitions cover
    "correlation" - how well the broadened reference matches the guided pool

    Given the scans, each scan's own offset is measured and removed before the
    width is read from their pool: unaligned, a trap's jitter widens the pooled
    peaks, and a model wider than the scans' peaks reads their tops too low.
    """

    scans = list(guided) if isinstance(guided, (list, tuple)) else [guided]
    profiles = [s.profile if s.hasprofile() else numpy.empty((0, 2)) for s in scans]
    if not reference.hasprofile() or not any(len(p) for p in profiles):
        return None

    def pooled(offsets):
        moved = []
        for profile, offset in zip(profiles, offsets, strict=True):
            if len(profile):
                profile = profile.copy()
                profile[:, 0] -= offset
                moved.append(profile)
        if len(moved) == 1:
            return _above_noise(moved[0])
        return _above_noise(_pool(moved, commonraster(moved)))

    ref = reference.profile
    own = pooled([0.0] * len(profiles))
    if len(own) < 2:
        return None
    lo = max(float(ref[0, 0]), float(own[0, 0]))
    hi = min(float(ref[-1, 0]), float(own[-1, 0]))
    if hi <= lo:
        return None

    widths = _peak_widths(own)
    refWidths = _peak_widths(_above_noise(ref))
    if widths is None or refWidths is None:
        return None
    relative = float(numpy.median(widths[1] / widths[0]))
    if relative < POOL_SAMPLING_RATIO * float(numpy.median(refWidths[1] / refWidths[0])):
        return None

    CHECK_FORCE_QUIT()

    arrays = _reference_arrays(ref)
    guide = {
        "fwhm": (float(numpy.median(widths[1])), 0.0),
        "shift": (0.0, 0.0, lo, hi),
        "range": (lo, hi),
    }
    guide = _measure_guide(arrays, own, guide)
    if guide is None:
        return None

    offsets = [0.0] * len(profiles)
    if len(profiles) > 1:
        for _iteration in range(POOL_GUIDE_ITERATIONS):
            offsets = _scan_offsets(arrays, guide, profiles)
            measured = _measure_guide(arrays, pooled(offsets), dict(guide))
            if measured is None:
                break
            guide = measured
        offsets = _scan_offsets(arrays, guide, profiles)
    guide["offsets"] = offsets

    return guide


# ----


def scanguide(guide, index):
    """The guide of one guided scan: the set's guide with that scan's offset."""

    single = dict(guide)
    slope, intercept, first, last = guide["shift"]
    offsets = guide.get("offsets") or []
    offset = offsets[index] if 0 <= index < len(offsets) else 0.0
    single["shift"] = (slope, intercept + offset, first, last)
    single["offsets"] = [0.0]
    return single


# ----


def guidecovers(guide, profile):
    """True when a guide's m/z range covers the whole profile of a scan."""

    if len(profile) == 0:
        return True

    lo, hi = guide["range"]
    first = float(profile[0, 0])
    last = float(profile[-1, 0])
    return first >= lo - float(_guide_fwhm(guide, lo)) and last <= hi + float(_guide_fwhm(guide, hi))


# ----


def _feature_position(peak):
    """m/z a feature is placed by: its envelope's first isotope, or the peak."""

    envelope = peak.attributes.get("envelope") if hasattr(peak, "attributes") else None
    if isinstance(envelope, dict) and envelope.get("isotopes"):
        return float(envelope["isotopes"][0][0])
    return float(peak.mz)


# ----


def guidedfeatures(guide, reference, own=None):
    """Features to label in a guided scan.

    guide (dict) - as returned by crossguide
    reference (mspy.peaklist) - peaks picked in the reference pool
    own (mspy.peaklist or None) - peaks picked in the guided set's own pool, for
        the m/z the reference does not cover

    Returns a peaklist of the reference features inside the guide's range and
    the own features outside it.
    """

    lo, hi = guide["range"]
    peaks = [p for p in reference if lo <= _feature_position(p) <= hi]
    if own is not None:
        peaks += [p for p in own if not lo <= _feature_position(p) <= hi]

    # a peaklist rescales the relative intensities of its peaks; one deep copy
    # leaves the source lists alone and keeps envelope members sharing their dict
    return obj_peaklist.peaklist(copy.deepcopy(peaks))


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
    guide=None,
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
    guide (dict or None) - this scan's guide (see crossguide and scanguide), when
        the features inside its range were picked in a finer acquisition; those
        are labelled as `_labelguided` describes, without `alignment`

    Every labelled peak keeps its pooled charge, isotope, FWHM and group, and is
    placed where this scan records it: the pooled position moved by the scan's
    `alignment`, then by what `_local_shifts` measures around it. The pooled m/z
    is kept as the peak's "referenceMz" attribute. Its intensity, baseline and
    S/N are measured in the scan, and an envelope has its area re-fit to the scan
    with the same overlap-aware joint fit picking uses. A peak (or envelope, judged at its
    theoretically tallest isotope) below `snThreshold` in the scan is left out --
    but a missing envelope still takes part in the area fit, so a neighbour cannot
    claim whatever signal it does have.
    """

    if not isinstance(features, obj_peaklist.peaklist):
        raise TypeError("Features must be mspy.peaklist object!")

    if signal is None or len(signal) == 0 or not len(features):
        return obj_peaklist.peaklist([])

    if guide is not None:
        lo, hi = guide["range"]
        inside = []
        outside = []
        for index in range(len(features)):
            peak = features[index]
            if lo <= _feature_position(peak) <= hi:
                inside.append(peak)
            else:
                outside.append(peak)

        labelled = []
        if outside:
            labelled += list(
                labelpooled(
                    signal,
                    obj_peaklist.peaklist(copy.deepcopy(outside)),
                    baseline=baseline,
                    snThreshold=snThreshold,
                    label=label,
                    intensity=intensity,
                    nonIdeality=nonIdeality,
                    averagineType=averagineType,
                    refinePattern=refinePattern,
                    alignment=alignment,
                )
            )
        # the guide already maps the reference onto this scan's own m/z axis
        labelled += _labelguided(signal, inside, baseline, guide, snThreshold, label, intensity)
        return obj_peaklist.peaklist(labelled)

    # the pooled positions, moved to where this scan records them
    features = _features_in_scan(features, signal, baseline, alignment)

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


def _signal_above_baseline(signal, baseline):
    """(x, y) of a profile with its baseline level taken off (clipped at zero)."""

    x = signal[:, 0]
    y = numpy.asarray(signal[:, 1], dtype=float)
    if baseline is not None and len(baseline):
        y = y - numpy.interp(x, baseline[:, 0], baseline[:, 1])
    return x, numpy.clip(y, 0.0, None)


# ----


def _local_shifts(signal, baseline, components):
    """How far each group of overlapping species sits from its modelled position.

    components - dicts with "isotopes" [(mz, weight)], "sigma" and "prior" (the
        relative abundance the species is modelled with)

    Pooled positions and a scan's overall offset still leave each scan's peaks a
    little off in places (a scan's calibration is not a single number), so the
    species of each overlap group are slid together by up to POOL_LOCAL_REACH of
    their FWHM to where their modelled shape correlates best with the scan. A
    group is only moved when the match is good and the best shift lies inside
    the searched range; otherwise it stays where it was modelled. Noise needs no
    gate of its own: it lowers the correlation. Returns a shift in Da per
    component.
    """

    shifts = [0.0] * len(components)
    if not components or len(signal) < 3:
        return shifts

    x, y = _signal_above_baseline(signal, baseline)

    intervals = []
    for component in components:
        mzs = [mz for mz, _w in component["isotopes"]]
        reach = 3.0 * component["sigma"]
        intervals.append((min(mzs) - reach, max(mzs) + reach))

    for group in mod_peakpicking._overlap_groups(intervals):

        CHECK_FORCE_QUIT()

        members = [components[k] for k in group]
        sigma = min(c["sigma"] for c in members)
        if sigma <= 0.0:
            continue
        reach = POOL_LOCAL_REACH * sigma * 2.0 * math.sqrt(2.0 * math.log(2.0))
        lo = min(intervals[k][0] for k in group) - reach
        hi = max(intervals[k][1] for k in group) + reach
        i1 = int(numpy.searchsorted(x, lo, side="left"))
        i2 = int(numpy.searchsorted(x, hi, side="right"))
        if i2 - i1 < 3:
            continue
        xs = x[i1:i2]
        ys = y[i1:i2]

        if not numpy.any(ys > 0.0):
            continue

        step = reach / 10.0
        deltas = numpy.arange(-10, 11) * step
        scores = numpy.zeros(len(deltas))
        for j, delta in enumerate(deltas):
            model = numpy.zeros(len(xs))
            for c in members:
                model += c["prior"] * mod_peakpicking._envelope_gaussian_column(
                    xs - delta, c["isotopes"], c["sigma"]
                )
            scores[j] = _correlation(xs, ys, model)

        j = int(numpy.argmax(scores))
        if scores[j] < POOL_LOCAL_MIN_CORRELATION or j in (0, len(deltas) - 1):
            continue
        delta = float(deltas[j])
        curvature = scores[j - 1] - 2.0 * scores[j] + scores[j + 1]
        if curvature < 0.0:
            delta += 0.5 * step * (scores[j - 1] - scores[j + 1]) / curvature
        for k in group:
            shifts[k] = delta

    return shifts


# ----


def _features_in_scan(features, signal, baseline, alignment):
    """Copies of pooled features placed where one scan records them.

    Positions move by the scan's `alignment` (ppm) and then by `_local_shifts`;
    each copy keeps the pooled m/z as "referenceMz".
    """

    peaks = copy.deepcopy([features[i] for i in range(len(features))])
    scale = 1.0 + alignment * 1e-6
    defaultFwhm = 0.1
    if features.basepeak is not None and features.basepeak.fwhm:
        defaultFwhm = features.basepeak.fwhm

    # one component per envelope (its members share the dict) or plain peak
    components = []
    byEnvelope = {}
    for peak in peaks:
        envelope = peak.attributes.get("envelope")
        if isinstance(envelope, dict) and envelope.get("isotopes"):
            if id(envelope) in byEnvelope:
                components[byEnvelope[id(envelope)]]["members"].append(peak)
                continue
            byEnvelope[id(envelope)] = len(components)
            isotopes = [(float(mz) * scale, max(0.0, float(w))) for mz, w in envelope["isotopes"]]
            fwhm = float(envelope.get("fwhm") or peak.fwhm or defaultFwhm)
            prior = float(envelope.get("area") or 0.0)
        else:
            envelope = None
            isotopes = [(float(peak.mz) * scale, 1.0)]
            fwhm = float(peak.fwhm or defaultFwhm)
            prior = max(0.0, peak.ai - peak.base) * fwhm * GAUSSIAN_AREA
        components.append(
            {
                "members": [peak],
                "envelope": envelope,
                "isotopes": isotopes,
                "sigma": mod_peakpicking._fwhm_to_sigma(fwhm),
                "prior": prior if prior > 0.0 else 1.0,
            }
        )

    shifts = _local_shifts(signal, baseline, components)

    for component, shift in zip(components, shifts, strict=True):
        if component["envelope"] is not None:
            component["envelope"]["isotopes"] = [
                (mz + shift, w) for mz, w in component["isotopes"]
            ]
        for peak in component["members"]:
            peak.attributes["referenceMz"] = float(peak.mz)
            peak.setmz(float(peak.mz) * scale + shift)

    return obj_peaklist.peaklist(peaks)


# ----


def _labelguided(signal, peaks, baseline, guide, snThreshold, label, intensity):
    """Label species picked in a finer acquisition in a scan of a coarser one.

    signal, baseline - the scan's profile and baseline
    peaks (list of mspy.peak) - the finer acquisition's features
    guide (dict) - this scan's guide (see scanguide)

    Charges and isotope patterns come from the reference, which resolved them.
    Every species is fitted where this analyser records it and at its FWHM, and
    its envelope is stored there, so it is drawn over this scan's peaks. Where
    species overlap, the scan's signal is shared among them in proportion to what
    the reference measured: the coarse scan cannot tell apart species closer than
    its peak width, and the reference did. Each species' area is then the fit of
    its own pattern to its share.

    Every labelled peak sits on its envelope, at the m/z this scan records (the
    guide's position, refined by `_local_shifts`), and
    keeps the reference position it was matched to as its "referenceMz"
    attribute: the two analysers disagree by more than a coarse peak's width
    allows to hide, and the finer reference is the more accurate mass. A species
    left out: one whose fitted tallest isotope stays below
    `snThreshold`, and one that is only a sliver (below POOL_GUIDE_MIN_SHARE) of
    the signal the reference predicts at its tallest isotope -- a faint neighbour
    the reference resolved but this analyser records as part of another peak.
    Both still take their share of the signal, so no neighbour absorbs it.
    """

    if not peaks:
        return []

    x = signal[:, 0]
    y = numpy.asarray(signal[:, 1], dtype=float)
    if baseline is not None and len(baseline):
        y = y - numpy.interp(x, baseline[:, 0], baseline[:, 1])
    y = numpy.clip(y, 0.0, None)

    # one component per species: an envelope with all of its member peaks, or a
    # plain peak
    components = []
    byEnvelope = {}
    for peak in peaks:
        envelope = peak.attributes.get("envelope") if hasattr(peak, "attributes") else None
        if isinstance(envelope, dict) and envelope.get("isotopes"):
            if id(envelope) in byEnvelope:
                components[byEnvelope[id(envelope)]]["members"].append(peak)
                continue
            byEnvelope[id(envelope)] = len(components)
            isotopes = [(float(mz), max(0.0, float(w))) for mz, w in envelope["isotopes"]]
            prior = float(envelope.get("area") or 0.0)
        else:
            envelope = None
            isotopes = [(float(peak.mz), 1.0)]
            prior = max(0.0, peak.ai - peak.base) * (peak.fwhm or 0.0) * GAUSSIAN_AREA

        total = math.fsum(w for _mz, w in isotopes) or 1.0
        isotopes = [(mz + float(_guide_shift(guide, mz)), w / total) for mz, w in isotopes]
        fwhm = float(_guide_fwhm(guide, isotopes[0][0]))
        components.append(
            {
                "members": [peak],
                "envelope": envelope,
                "isotopes": isotopes,
                "fwhm": fwhm,
                "sigma": mod_peakpicking._fwhm_to_sigma(fwhm),
                "prior": prior,
                "apex": max(range(len(isotopes)), key=lambda i: isotopes[i][1]),
            }
        )

    # a species the reference could not measure still gets a small share
    largest = max(c["prior"] for c in components)
    for component in components:
        prior = component["prior"]
        component["prior"] = max(prior, 1e-6 * largest) if largest > 0.0 else 1.0

    # the guide places every species by the scan's overall calibration; each
    # group then settles where this scan actually records it
    shifts = _local_shifts(signal, baseline, components)
    for component, shift in zip(components, shifts, strict=True):
        component["isotopes"] = [(mz + shift, w) for mz, w in component["isotopes"]]
        component["shift"] = shift

    intervals = []
    for component in components:
        mzs = [mz for mz, _w in component["isotopes"]]
        reach = 4.0 * component["sigma"]
        intervals.append((min(mzs) - reach, max(mzs) + reach))

    areas = [0.0] * len(components)
    shares = [1.0] * len(components)
    for group in mod_peakpicking._overlap_groups(intervals):

        CHECK_FORCE_QUIT()

        members = [components[k] for k in group]

        # the share of each species at its own tallest isotope, before any data
        for k, component in zip(group, members, strict=True):
            at = numpy.array([component["isotopes"][component["apex"]][0]])
            predicted = [
                other["prior"]
                * float(mod_peakpicking._envelope_gaussian_column(at, other["isotopes"], other["sigma"])[0])
                for other in members
            ]
            total = math.fsum(predicted)
            shares[k] = predicted[group.index(k)] / total if total > 0.0 else 1.0

        lo = min(intervals[k][0] for k in group)
        hi = max(intervals[k][1] for k in group)
        mask = (x >= lo) & (x <= hi)
        if not numpy.any(mask):
            continue
        xs = x[mask]
        ys = y[mask]

        columns = [
            mod_peakpicking._envelope_gaussian_column(xs, c["isotopes"], c["sigma"])
            for c in members
        ]
        predicted = sum(c["prior"] * column for c, column in zip(members, columns, strict=True))
        for k, component, column in zip(group, members, columns, strict=True):
            share = numpy.divide(
                component["prior"] * column,
                predicted,
                out=numpy.zeros(len(xs)),
                where=predicted > 0.0,
            )
            energy = float(numpy.sum(column * column))
            if energy > 0.0:
                areas[k] = max(0.0, float(numpy.sum(column * ys * share)) / energy)

    labelled = []
    for k, component in enumerate(components):

        CHECK_FORCE_QUIT()

        area = areas[k]
        isotopes = component["isotopes"]
        fwhm = component["fwhm"]
        norm = component["sigma"] * math.sqrt(2.0 * math.pi)
        if area <= 0.0 or norm <= 0.0 or shares[k] < POOL_GUIDE_MIN_SHARE:
            continue

        # (ai, base, sn) of every isotope, as the fit draws it on the baseline
        measured = []
        for mz, w in isotopes:
            base, noise = _baseline_at(baseline, mz)
            height = area * w / norm
            measured.append((base + height, base, height / noise if noise else None))
        ai, base, sn = measured[component["apex"]]
        if not _is_present(ai, base, sn, snThreshold):
            continue

        envelope = component["envelope"]
        if envelope is None:
            peak = component["members"][0]
            new = copy.deepcopy(peak)
            new.setmz(isotopes[0][0])
            new.attributes["referenceMz"] = float(peak.mz)
            new.setfwhm(fwhm)
            new.setai(measured[0][0])
            new.setbase(measured[0][1])
            new.setsn(measured[0][2])
            labelled.append(new)
            continue

        updated = dict(envelope)
        updated["area"] = area
        updated["sumint"] = area / norm
        updated["isotopes"] = isotopes
        updated["fwhm"] = fwhm

        if label == "isotopes":
            display = None
        else:
            display = _envelope_display(envelope, measured, label, intensity)

        for peak in component["members"]:
            new = copy.deepcopy(peak)
            inScan = float(peak.mz) + float(_guide_shift(guide, peak.mz)) + component["shift"]
            if display is None:
                nearest = min(range(len(isotopes)), key=lambda i: abs(isotopes[i][0] - inScan))
                ai, base, sn = measured[nearest]
            else:
                ai, base, sn = display
            new.setmz(inScan)
            new.attributes["referenceMz"] = float(peak.mz)
            new.setfwhm(fwhm)
            new.setai(ai)
            new.setbase(base)
            new.setsn(sn)
            new.attributes["envelope"] = updated
            labelled.append(new)

    return labelled


# ----
