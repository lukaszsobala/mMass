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
import copy
import math
import numpy

# load stopper
from .mod_stopper import CHECK_FORCE_QUIT

# load blocks
from . import blocks

# load objects
from . import obj_compound
from . import obj_peak
from . import obj_peaklist

# load modules
from . import mod_basics
from . import mod_signal

# BASIC CONSTANTS
# ---------------

ISOTOPE_DISTANCE = 1.00287
AVERAGE_AMINO = {"C": 4.9384, "H": 7.7583, "N": 1.3577, "O": 1.4773, "S": 0.0417}
AVERAGE_BASE = {"C": 9.75, "H": 12.25, "N": 3.75, "O": 6, "P": 1}
ENVELOPE_NON_IDEALITY_DEFAULT = 0.20

# Averagine models selectable for isotope-envelope modeling. Each maps a short
# key to (a) the average building-block elemental composition used to build a
# real isotope pattern, and (b) the Poisson "lambda factor": the expected number
# of +1 isotopes per dalton, which the fast isotope approximation multiplies by
# the neutral mass. The +1 spacing is dominated by 13C (1.07% natural
# abundance), so the factor is ~ (carbons per block / block mass) * 0.0107. The
# protein factor reproduces the historical 0.000475 constant; the others follow
# from their carbon density (more carbon per Da -> larger factor):
#   carbohydrate  C6H10O5 (anhydrohexose):  6 / 162.14 * 0.0107 = 0.000396
#   lipid         C16H32O2 (fatty acyl):   16 / 256.43 * 0.0107 = 0.000668
AVERAGINE_MODELS = {
    "protein": {
        "label": "Protein (amino acid)",
        "composition": AVERAGE_AMINO,
        "lambdaFactor": 0.000475,
    },
    "carbohydrate": {
        "label": "Carbohydrate (hexose)",
        "composition": {"C": 6, "H": 10, "O": 5},
        "lambdaFactor": 0.000396,
    },
    "lipid": {
        "label": "Lipid (fatty acyl)",
        "composition": {"C": 16, "H": 32, "O": 2},
        "lambdaFactor": 0.000668,
    },
}
DEFAULT_AVERAGINE = "protein"


def _averagine_model(averagineType):
    """Resolve an averagine type key to its model dict (falls back to protein)."""

    return AVERAGINE_MODELS.get(averagineType, AVERAGINE_MODELS[DEFAULT_AVERAGINE])


def _averagine_lambda(averagineType):
    """Poisson lambda factor (expected +1 isotopes per Da) for an averagine type."""

    return _averagine_model(averagineType)["lambdaFactor"]


def _averagine_composition(averagineType):
    """Average building-block composition for an averagine type."""

    return _averagine_model(averagineType)["composition"]

# Minimum number of isotopes a deisotoped envelope must span. Applied as a hard
# floor: the signal/decay guards may only extend the tail beyond this length,
# never trim below it.
MIN_ENVELOPE_LENGTH = 3

# Minimum expected signal-to-noise for a theoretical isotope to be worth
# modeling when extending an envelope's tail. Combined with the base peak's
# measured S/N this gives an intensity-adaptive cutoff (see relabelenvelopes).
ENVELOPE_TAIL_SN_LIMIT = 1.0

# Bounds on the relative tail cutoff, expressed as a fraction of the *tallest*
# theoretical isotope (the envelope apex), NOT of the monoisotopic / first peak.
# The theoretical pattern is normalised to its apex, so this is correct even for
# heavy species where the first peak is far from the tallest. Keeps the estimate
# within a realistic single-envelope dynamic range.
ENVELOPE_TAIL_CUTOFF_MIN = 0.0005
ENVELOPE_TAIL_CUTOFF_MAX = 0.05

# A real isotope tail past the apex decays monotonically. When walking the tail
# outward, allow only this much rise relative to the previous position before
# concluding the signal belongs to a different species (and stopping). Prevents
# the tail from marching across neighbouring peaks in crowded regions.
ENVELOPE_TAIL_RISE_TOLERANCE = 1.5

# Past the apex a real isotope tail decays *continuously*. When the observed
# signal collapses below this fraction of the previous isotope it has dropped to
# baseline/noise -- the envelope has ended -- so the position is not modelled.
# This is shape-agnostic (it does not assume an averagine profile) and stops a
# trailing peak being placed on flat spectrum even at a permissive S/N limit.
ENVELOPE_TAIL_MIN_DECAY = 0.1


# PEAK PICKING FUNCTIONS
# ----------------------


def _mass_scalar(value, massType=0):
    """Return scalar mass from float or (mono, average) tuple-like values."""

    if isinstance(value, (tuple, list)):
        if len(value) > massType:
            return float(value[massType])
        if len(value) > 0:
            return float(value[0])
        return 0.0
    return float(value)


def labelpoint(signal, mz, baseline=None):
    """Return labeled peak at given x-value.
    signal (numpy array) - signal data points
    mz (float) - x-value to label
    baseline (numpy array) - signal baseline
    """

    # check signal type
    if not isinstance(signal, numpy.ndarray):
        raise TypeError("Signal must be NumPy array!")

    # check baseline type
    if baseline is not None and not isinstance(baseline, numpy.ndarray):
        raise TypeError("Baseline must be NumPy array!")

    # check signal data
    if len(signal) == 0:
        return None

    # check m/z value
    if mz <= 0:
        return None

    # get peak intensity
    ai = mod_signal.intensity(signal, mz)
    if not ai:
        return None

    # get peak baseline and s/n
    base = 0.0
    sn = None
    if baseline is None:
        base, noise = mod_signal.noise(signal, x=mz)
        if noise:
            sn = (ai - base) / noise
    else:
        idx = mod_signal.locate(baseline, mz)
        if (idx > 0) and (idx < len(baseline)):
            base = mod_signal.interpolate(
                (baseline[idx - 1][0], baseline[idx - 1][1]),
                (baseline[idx][0], baseline[idx][1]),
                x=mz,
            )
            noise = mod_signal.interpolate(
                (baseline[idx - 1][0], baseline[idx - 1][2]),
                (baseline[idx][0], baseline[idx][2]),
                x=mz,
            )
            if noise:
                sn = (ai - base) / noise

    # check peak intensity
    if ai <= base:
        return None

    # get peak fwhm
    height = base + (ai - base) * 0.5
    fwhm = mod_signal.width(signal, mz, height)

    # make peak object
    peak = obj_peak.peak(mz=mz, ai=ai, base=base, sn=sn, fwhm=fwhm)

    return peak


# ----


def labelpeak(signal, mz=None, minX=None, maxX=None, pickingHeight=0.75, baseline=None):
    """Return labeled peak in given m/z range.
    signal (numpy array) - signal data points
    mz (float) - x-value to label
    minX (float) - x-range start
    maxX (float) - x-range end
    pickingHeight (float) - centroiding height
    baseline (numpy array) - signal baseline
    """

    # check signal type
    if not isinstance(signal, numpy.ndarray):
        raise TypeError("Signal must be NumPy array!")

    # check baseline type
    if baseline is not None and not isinstance(baseline, numpy.ndarray):
        raise TypeError("Baseline must be NumPy array!")

    # check m/z value or range
    if mz is None and minX is None and maxX is None:
        raise TypeError("m/z value or range must be specified!")

    # check signal data
    if len(signal) == 0:
        return None

    # check m/z value
    if mz is not None:
        minX = mz
    if mz is None and (minX is None or maxX is None):
        raise TypeError("Both minX and maxX must be specified when mz is not set!")
    if minX is None:
        return None
    if minX <= 0:
        return False

    # get index of given m/z or range maximum
    if mz is not None:
        imax = mod_signal.locate(signal, mz)
    else:
        i1 = mod_signal.locate(signal, minX)
        i2 = mod_signal.locate(signal, maxX)
        imax = i1
        if i1 != i2:
            imax += mod_signal.basepeak(signal[i1:i2])
    if (imax == 0) or (imax == len(signal)):
        return None

    # get centroid height
    h = signal[imax][1] * pickingHeight
    if baseline is not None:
        idx = mod_signal.locate(baseline, signal[imax][0])
        if (idx > 0) and (idx < len(baseline)):
            base = mod_signal.interpolate(
                (baseline[idx - 1][0], baseline[idx - 1][1]),
                (baseline[idx][0], baseline[idx][1]),
                x=signal[imax][0],
            )
            h = ((signal[imax][1] - base) * pickingHeight) + base

    # get centroid
    ileft = imax - 1
    while (ileft > 0) and (signal[ileft][1] > h):
        ileft -= 1

    iright = imax
    while (iright < len(signal) - 1) and (signal[iright][1] > h):
        iright += 1

    leftMZ = mod_signal.interpolate(signal[ileft], signal[ileft + 1], y=h)
    rightMZ = mod_signal.interpolate(signal[iright - 1], signal[iright], y=h)

    # check range
    if mz is None:
        rangeMin = minX if minX is not None else leftMZ
        rangeMax = maxX if maxX is not None else rightMZ
        if (leftMZ < rangeMin or rightMZ > rangeMax) and (leftMZ != rightMZ):
            return None

    # label peak in the newly found selection
    if mz is not None and leftMZ != rightMZ:
        peak = labelpeak(
            signal=signal,
            minX=leftMZ,
            maxX=rightMZ,
            pickingHeight=pickingHeight,
            baseline=baseline,
        )

    # label current point
    else:
        peak = labelpoint(
            signal=signal, mz=((leftMZ + rightMZ) / 2.0), baseline=baseline
        )

    return peak


# ----


def labelscan(
    signal,
    minX=None,
    maxX=None,
    pickingHeight=0.75,
    absThreshold=0.0,
    relThreshold=0.0,
    snThreshold=0.0,
    baseline=None,
):
    """Return centroided peaklist for given data points.
    signal (numpy array) - signal data points
    minX (float) - x-range start
    maxX (float) - x-range end
    pickingHeight (float) - centroiding height
    absThreshold (float) - absolute intensity threshold
    relThreshold (float) - relative intensity threshold
    snThreshold (float) - signal to noise threshold
    baseline (numpy array) - signal baseline
    """

    # check signal type
    if not isinstance(signal, numpy.ndarray):
        raise TypeError("Signal must be NumPy array!")

    # check baseline type
    if baseline is not None and not isinstance(baseline, numpy.ndarray):
        raise TypeError("Baseline must be NumPy array!")

    # crop data
    if minX is not None and maxX is not None:
        i1 = mod_signal.locate(signal, minX)
        i2 = mod_signal.locate(signal, maxX)
        signal = signal[i1:i2]

    # check data points
    if len(signal) == 0:
        return obj_peaklist.peaklist([])

    # get local maxima
    buff = []
    basepeak = mod_signal.basepeak(signal)
    threshold = max(signal[basepeak][1] * relThreshold, absThreshold)
    for peak in mod_signal.maxima(signal):
        if peak[1] >= threshold:
            buff.append([peak[0], peak[1], 0.0, None, None])  # mz, ai, base, sn, fwhm

    CHECK_FORCE_QUIT()

    # get peaks baseline and s/n
    basepeak = 0.0
    if baseline is not None:
        for peak in buff:
            idx = mod_signal.locate(baseline, peak[0])
            if (idx > 0) and (idx < len(baseline)):
                p1 = baseline[idx - 1]
                p2 = baseline[idx]
                peak[2] = mod_signal.interpolate(
                    (p1[0], p1[1]), (p2[0], p2[1]), x=peak[0]
                )
                noise = mod_signal.interpolate(
                    (p1[0], p1[2]), (p2[0], p2[2]), x=peak[0]
                )
                intens = peak[1] - peak[2]
                if noise:
                    peak[3] = intens / noise
                if intens > basepeak:
                    basepeak = intens

    CHECK_FORCE_QUIT()

    # remove peaks bellow threshold
    threshold = max(basepeak * relThreshold, absThreshold)
    candidates = []
    for peak in buff:
        if (
            peak[0] > 0
            and (peak[1] - peak[2]) >= threshold
            and (not peak[3] or peak[3] >= snThreshold)
        ):
            candidates.append(peak)

    # make centroides
    if pickingHeight < 1.0:
        buff = []
        previous = None
        for peak in candidates:

            CHECK_FORCE_QUIT()

            # calc peak height
            h = ((peak[1] - peak[2]) * pickingHeight) + peak[2]

            # get centroid indexes
            idx = mod_signal.locate(signal, peak[0])
            if (idx == 0) or (idx == len(signal)):
                continue

            ileft = idx - 1
            while (ileft > 0) and (signal[ileft][1] > h):
                ileft -= 1

            iright = idx
            while (iright < len(signal) - 1) and (signal[iright][1] > h):
                iright += 1

            # calculate peak mz
            leftMZ = mod_signal.interpolate(signal[ileft], signal[ileft + 1], y=h)
            rightMZ = mod_signal.interpolate(signal[iright - 1], signal[iright], y=h)
            peak[0] = (leftMZ + rightMZ) / 2.0

            # get peak intensity
            intens = mod_signal.intensity(signal, peak[0])
            if intens and intens <= peak[1]:
                peak[1] = intens
            else:
                continue

            # try to group with previous peak
            if previous is not None and leftMZ < previous:
                if peak[1] > buff[-1][1]:
                    buff[-1] = peak
                    previous = rightMZ
            else:
                buff.append(peak)
                previous = rightMZ

        # store as candidates
        candidates = buff

    CHECK_FORCE_QUIT()

    # get peaks baseline and s/n
    basepeak = 0.0
    if baseline is not None:
        for peak in candidates:
            idx = mod_signal.locate(baseline, peak[0])
            if (idx > 0) and (idx < len(baseline)):
                p1 = baseline[idx - 1]
                p2 = baseline[idx]
                peak[2] = mod_signal.interpolate(
                    (p1[0], p1[1]), (p2[0], p2[1]), x=peak[0]
                )
                noise = mod_signal.interpolate(
                    (p1[0], p1[2]), (p2[0], p2[2]), x=peak[0]
                )
                intens = peak[1] - peak[2]
                if noise:
                    peak[3] = intens / noise
                if intens > basepeak:
                    basepeak = intens

    CHECK_FORCE_QUIT()

    # remove peaks bellow threshold and calculate fwhm
    threshold = max(basepeak * relThreshold, absThreshold)
    centroides = []
    for peak in candidates:
        if (
            peak[0] > 0
            and (peak[1] - peak[2]) >= threshold
            and (not peak[3] or peak[3] >= snThreshold)
        ):
            peak[4] = mod_signal.width(
                signal, peak[0], (peak[2] + ((peak[1] - peak[2]) * 0.5))
            )
            centroides.append(
                obj_peak.peak(
                    mz=peak[0], ai=peak[1], base=peak[2], sn=peak[3], fwhm=peak[4]
                )
            )

    # return peaklist object
    return obj_peaklist.peaklist(centroides)


# ----


def envcentroid(isotopes, pickingHeight=0.5, intensity="maximum"):
    """Calculate envelope centroid for given isotopes.
    isotopes (mspy.peaklist or list of mspy.peak) envelope isotopes
    pickingHeight (float) - centroiding height
    intensity (maximum | sum | average) envelope intensity type
    """

    # check isotopes
    if len(isotopes) == 0:
        return None
    elif len(isotopes) == 1:
        return isotopes[0]

    # check peaklist object
    if not isinstance(isotopes, obj_peaklist.peaklist):
        isotopes = obj_peaklist.peaklist(isotopes)

    basepeak = isotopes.basepeak
    if basepeak is None:
        return None

    # get sums
    sumMZ = 0.0
    sumIntensity = 0.0
    for isotope in isotopes:
        sumMZ += isotope.mz * isotope.intensity
        sumIntensity += isotope.intensity

    # get average m/z
    mz = sumMZ / sumIntensity

    # get ai, base and sn
    base = basepeak.base
    sn = basepeak.sn
    fwhm = basepeak.fwhm
    if intensity == "sum":
        displayAI = base + sumIntensity
    elif intensity == "average":
        displayAI = base + sumIntensity / len(isotopes)
    else:
        displayAI = basepeak.ai
    ai = displayAI
    if basepeak.sn and basepeak.ai != base:
        sn = (displayAI - base) * basepeak.sn / (basepeak.ai - base)

    # get envelope width
    minInt = basepeak.intensity * pickingHeight
    i1 = None
    i2 = None
    for x, isotope in enumerate(isotopes):
        if isotope.intensity >= minInt:
            i2 = x
            if i1 is None:
                i1 = x

    if i1 is None or i2 is None:
        return None

    mz1 = isotopes[i1].mz
    mz2 = isotopes[i2].mz
    if i1 != 0:
        mz1 = mod_signal.interpolate(
            (isotopes[i1 - 1].mz, isotopes[i1 - 1].ai),
            (isotopes[i1].mz, isotopes[i1].ai),
            y=minInt,
        )
    if i2 < len(isotopes) - 1:
        mz2 = mod_signal.interpolate(
            (isotopes[i2].mz, isotopes[i2].ai),
            (isotopes[i2 + 1].mz, isotopes[i2 + 1].ai),
            y=minInt,
        )
    if mz1 != mz2:
        fwhm = abs(mz2 - mz1)

    # make peak
    peak = obj_peak.peak(mz=mz, ai=ai, base=base, sn=sn, fwhm=fwhm)

    return peak


# ----


def envmono(isotopes, charge, intensity="maximum", composition=AVERAGE_AMINO):
    """Calculate envelope centroid for given isotopes.
    isotopes (mspy.peaklist or list of mspy.peak) - envelope isotopes
    charge (int) - peak charge
    intensity (maximum | sum | average) - envelope intensity type
    composition (dict) - averagine building-block composition
    """

    # check isotopes
    if len(isotopes) == 0:
        return None

    # check peaklist object
    if not isinstance(isotopes, obj_peaklist.peaklist):
        isotopes = obj_peaklist.peaklist(isotopes)

    basepeak = isotopes.basepeak
    if basepeak is None:
        return None

    # calc averagine
    avFormula = averagine(basepeak.mz, charge=charge, composition=composition)
    avPattern = avFormula.pattern(fwhm=0.1, threshold=0.001, charge=charge)
    avPattern = obj_peaklist.peaklist(avPattern)
    avBasepeak = avPattern.basepeak
    if avBasepeak is None:
        return None

    # get envelope centroid
    points = numpy.array([(p.mz, p.intensity) for p in isotopes])
    centroid = labelpeak(points, mz=basepeak.mz, pickingHeight=0.8)
    if not centroid:
        centroid = basepeak

    # get averagine centroid
    points = numpy.array([(p.mz, p.intensity) for p in avPattern])
    avCentroid = labelpeak(points, mz=avBasepeak.mz, pickingHeight=0.8)
    if not avCentroid:
        avCentroid = avBasepeak

    # align profiles and get monoisotopic mass
    shift = centroid.mz - avCentroid.mz
    errors = [(abs(p.mz - avBasepeak.mz - shift), p.mz) for p in isotopes]
    mz = min(errors)[1] - (avBasepeak.mz - avFormula.mz(charge)[0])

    # sum intensities
    sumIntensity = 0
    for isotope in isotopes:
        sumIntensity += isotope.intensity

    # get ai, base and sn
    base = basepeak.base
    sn = basepeak.sn
    fwhm = basepeak.fwhm
    if intensity == "sum":
        displayAI = base + sumIntensity
    elif intensity == "average":
        displayAI = base + sumIntensity / len(isotopes)
    else:
        displayAI = basepeak.ai
    ai = displayAI
    if basepeak.sn and basepeak.ai != base:
        sn = (displayAI - base) * basepeak.sn / (basepeak.ai - base)

    # make peak
    peak = obj_peak.peak(mz=mz, ai=ai, base=base, sn=sn, fwhm=fwhm, isotope=0)

    return peak


# ----


def labelenvelope(
    isotopes, charge=None, label="1st", intensity="maximum",
    averagineType=DEFAULT_AVERAGINE,
):
    """Convert isotope peaks to requested envelope labels."""

    # check isotopes
    if len(isotopes) == 0:
        return []

    # check peaklist object
    if not isinstance(isotopes, obj_peaklist.peaklist):
        isotopes = obj_peaklist.peaklist(isotopes)

    if charge is None:
        charge = isotopes[0].charge

    # label monoisotopic peak
    if label == "monoisotope":
        peak = envmono(
            isotopes, charge=charge, intensity=intensity,
            composition=_averagine_composition(averagineType),
        )
        return [peak] if peak else []

    # label envelope centroid
    elif label == "centroid":
        peak = envcentroid(isotopes, pickingHeight=0.5, intensity=intensity)
        if peak:
            peak.setcharge(charge)
        return [peak] if peak else []

    # label all isotopes
    elif label == "isotopes":
        peaks = copy.deepcopy(list(isotopes))
        for x, peak in enumerate(peaks):
            peak.setcharge(charge)
            peak.setisotope(x)
        return peaks

    # label 1st isotope
    basepeak = isotopes[0]
    sumIntensity = 0.0
    sumBase = 0.0
    for peak in isotopes:
        sumIntensity += peak.intensity
        sumBase += peak.base

    base = basepeak.base
    sn = basepeak.sn
    if intensity == "sum":
        displayAI = base + sumIntensity
    elif intensity == "average":
        displayAI = base + sumIntensity / len(isotopes)
    else:
        displayAI = basepeak.ai

    if basepeak.sn and basepeak.ai != basepeak.base:
        sn = (displayAI - base) * basepeak.sn / (basepeak.ai - basepeak.base)

    peak = obj_peak.peak(
        mz=isotopes[0].mz,
        ai=displayAI,
        base=base,
        sn=sn,
        charge=charge,
        isotope=0,
        fwhm=None,
    )

    return [peak]


# ----


def envelopeprofile(envelope, raster=None, points=30):
    """Make Gaussian profile for one envelope metadata dict."""

    if not envelope:
        return numpy.array([])

    isotopes = envelope.get("isotopes", [])
    area = float(envelope.get("area", 0.0))
    fwhm = float(envelope.get("fwhm", 0.1))
    if not isotopes or area <= 0.0 or fwhm <= 0.0:
        return numpy.array([])

    sigma = _fwhm_to_sigma(fwhm)
    if sigma <= 0.0:
        return numpy.array([])

    # build raster around isotope cluster
    if raster is None:
        mzs = [float(x[0]) for x in isotopes]
        start = min(mzs) - 5.0 * fwhm
        stop = max(mzs) + 5.0 * fwhm
        step = max(fwhm / float(max(5, points)), 1e-5)
        raster = numpy.arange(start, stop + step, step)
    elif not isinstance(raster, numpy.ndarray):
        raster = numpy.array(raster, dtype=float)

    y = numpy.zeros(len(raster), dtype=float)
    norm = sigma * math.sqrt(2.0 * math.pi)
    for mz, weight in isotopes:
        amplitude = area * float(weight) / norm
        y += amplitude * numpy.exp(-0.5 * ((raster - float(mz)) / sigma) ** 2)

    return numpy.column_stack((raster, y))


# ----


def _fwhm_to_sigma(fwhm):
    """Convert FWHM to sigma for Gaussian profile."""

    if fwhm <= 0.0:
        return 0.0
    return fwhm / (2.0 * math.sqrt(2.0 * math.log(2.0)))


# ----


def _cluster_weights(cluster, averagineType=DEFAULT_AVERAGINE):
    """Get normalized isotope weights from theoretical pattern."""

    if not cluster:
        return []

    parent = cluster[0]
    if parent.charge:
        # Reconstruct true monoisotopic mass to scale Poisson correctly
        mono_mz = parent.mz
        first_iso = getattr(parent, 'isotope', 0)
        if first_iso is None:
            first_iso = 0
        if first_iso > 0:
            mono_mz -= first_iso * (ISOTOPE_DISTANCE / abs(parent.charge))

        neutralMass = _mass_scalar(
            mod_basics.mz(mono_mz, charge=0, currentCharge=parent.charge, massType=1),
            massType=1,
        )
        lam = max(0.0, neutralMass * _averagine_lambda(averagineType))

        # Find maximum required isotope index
        max_iso = 30
        for i, p in enumerate(cluster):
            iso_idx = getattr(p, 'isotope', i)
            if iso_idx is None:
                iso_idx = i
            max_iso = max(max_iso, int(iso_idx) + 1)

        pattern = []
        p_val = math.exp(-lam) if lam < 700 else 0.0
        for i in range(max_iso):
            if i == 0:
                pattern.append(p_val)
            else:
                p_val = p_val * (lam / i)
                pattern.append(p_val)

        total = sum(pattern)
        if total > 0.0:
            weights = []
            for i, peak in enumerate(cluster):
                iso_idx = getattr(peak, 'isotope', i)
                if iso_idx is None:
                    iso_idx = i
                iso_idx = int(iso_idx)
                weights.append(pattern[iso_idx] / total if iso_idx < len(pattern) else 0.0)
            return weights

    intensities = [max(0.0, p.intensity) for p in cluster]
    total = sum(intensities)
    if total <= 0.0:
        return [1.0 / len(cluster)] * len(cluster)
    return [x / total for x in intensities]


# ----


def _cluster_fwhm(cluster, defaultFwhm):
    """Get representative FWHM for isotope cluster."""

    fwhms = [p.fwhm for p in cluster if p.fwhm and p.fwhm > 0.0]

    if not fwhms:
        return defaultFwhm
    return sum(fwhms) / float(len(fwhms))


# ----


def _cluster_isotope_model(
    cluster, signal=None, defaultFwhm=0.1, nonIdeality=None,
    averagineType=DEFAULT_AVERAGINE,
):
    """Get isotope weights for a cluster, optionally softened by profile evidence."""

    fwhm = float(_cluster_fwhm(cluster, defaultFwhm))
    weights = _cluster_weights(cluster, averagineType=averagineType)
    isotopes = [(float(p.mz), float(w)) for p, w in zip(cluster, weights, strict=True)]

    if signal is None or len(signal) == 0 or fwhm <= 0.0:
        return isotopes

    x = signal[:, 0].astype(float)
    y = signal[:, 1].astype(float)
    if len(x) == 0:
        return isotopes

    mzs = [mz for mz, _ in isotopes]
    lo = min(mzs) - 6.0 * fwhm
    hi = max(mzs) + 6.0 * fwhm
    mask = (x >= lo) & (x <= hi)
    if not numpy.any(mask):
        return isotopes

    x = x[mask]
    y = y[mask].copy()
    y[y < 0.0] = 0.0

    return _soft_isotope_model(
        isotopes,
        x,
        y,
        fwhm,
        nonIdeality=nonIdeality,
    )


# ----


def _isotonic_nondecreasing(values):
    """Least-squares non-decreasing fit via pool-adjacent-violators (PAVA).

    Returns the closest (in squared error) non-decreasing sequence to `values`.
    PAVA only ever replaces a run of points by their mean, so the sum of the
    output equals the sum of the input exactly -- which is what lets the
    unimodal projection below preserve the total envelope area.
    """

    stack = []  # each entry is a [sum, count] pool, left to right
    for value in values:
        pool_sum = float(value)
        pool_count = 1
        # merge while the previous pool's mean exceeds this one's (a violation)
        while stack and stack[-1][0] / stack[-1][1] > pool_sum / pool_count:
            prev_sum, prev_count = stack.pop()
            pool_sum += prev_sum
            pool_count += prev_count
        stack.append([pool_sum, pool_count])

    out = numpy.empty(len(values), dtype=float)
    i = 0
    for pool_sum, pool_count in stack:
        out[i:i + pool_count] = pool_sum / pool_count
        i += pool_count
    return out


def _project_unimodal(weights):
    """Closest (least-squares) unimodal sequence to `weights`, area-preserving.

    A single-species isotope envelope is unimodal: its weights rise (weakly) to a
    peak isotope and fall thereafter -- they never dip in the middle and rise
    again. When a wide non-ideality band lets observed noise or an overlapping
    species push an interior isotope down (a notch) or to zero (a gap), the
    blended weights can stop being unimodal. This projects them back onto the
    nearest unimodal shape.

    Every candidate peak position splits the weights into a non-decreasing prefix
    and a non-increasing suffix, each fitted by PAVA; the concatenation of a
    non-decreasing run followed by a non-increasing run is unimodal for any split,
    and PAVA preserves each part's sum, so the total (the envelope area) is
    conserved. The split with the smallest squared error is kept.
    """

    w = numpy.asarray(weights, dtype=float)
    n = len(w)
    if n <= 2:
        # any sequence of length <= 2 is already unimodal
        return w.copy()

    best_fit = w.copy()
    best_err = numpy.inf
    for split in range(n + 1):
        left = _isotonic_nondecreasing(w[:split])
        # a non-increasing fit is a non-decreasing fit of the reversed data
        right = _isotonic_nondecreasing(w[split:][::-1])[::-1]
        fit = numpy.concatenate([left, right])
        err = float(numpy.sum((fit - w) ** 2))
        if err < best_err:
            best_err = err
            best_fit = fit
    return best_fit


def _soft_isotope_model(isotopes, x, y, fwhm, nonIdeality=None):
    """Reshape averagine isotopes toward observed evidence within a bounded band.

    Theoretical averagine is the backbone. Each isotope weight may move toward its
    observed apex, but only within a band of +/- `nonIdeality` (relative) around
    its theoretical value, so a contaminant sitting on an isotope position --
    implausibly tall for that isotope -- is clipped back to a physical height
    instead of being swallowed into the envelope, while a genuine, modest
    non-averagine deviation (e.g. a +1 slightly below averagine) is followed. At
    `nonIdeality == 0` the shape is rigidly theoretical.

    The clipped weights are restored to sum 1 by a single UNIFORM rescale, which
    preserves the observed *ratios* among the in-band isotopes. This is what lets
    the high-abundance, high-S/N peaks that drive the fit (the mono and +1) keep
    their observed proportions, so the modelled envelope matches them without
    over- or under-shooting. Faint tail isotopes, whose band around a tiny theory
    weight is correspondingly tiny, stay essentially on theory regardless of
    noise (they may undershoot the data -- they are not trusted to reshape the
    envelope). A final unimodality projection keeps the result a plausible
    single-species pattern.
    """

    if not isotopes:
        return []

    ordered = sorted([(float(mz), max(0.0, float(weight))) for mz, weight in isotopes])
    theory = numpy.array([w for _, w in ordered], dtype=float)
    total = float(numpy.sum(theory))
    if total <= 0.0:
        return ordered
    theory /= total

    obs = numpy.zeros(len(ordered), dtype=float)
    if len(x) and len(y) and fwhm > 0.0:
        half_window = max(0.35 * float(fwhm), 1e-4)
        for i, (mz, _) in enumerate(ordered):
            i1 = numpy.searchsorted(x, mz - half_window, side='left')
            i2 = numpy.searchsorted(x, mz + half_window, side='right')
            if i1 < i2:
                obs[i] = max(0.0, float(numpy.max(y[i1:i2])))

    obs_total = float(numpy.sum(obs))
    if obs_total > 0.0:
        obs /= obs_total
    else:
        obs = theory.copy()

    if nonIdeality is None:
        nonIdeality = ENVELOPE_NON_IDEALITY_DEFAULT
    deviation = max(0.0, min(float(nonIdeality), 1.0))

    if obs_total <= 0.0 or deviation <= 0.0:
        # no observed evidence, or non-ideality switched off -> pure theory
        return [(ordered[i][0], float(theory[i])) for i in range(len(ordered))]

    # Band each isotope to +/- `deviation` (relative) around its theoretical
    # weight, then follow the observed value inside that band. The band is
    # relative to theory, so it is tight for the faint tail (whose ideal share is
    # tiny) and wide for the abundant isotopes; a contaminant implausibly tall for
    # its isotope position is clipped back, while a modest real deviation is kept.
    upper = (1.0 + deviation) * theory
    lower = (1.0 - deviation) * theory
    blended = numpy.clip(obs, lower, upper)

    # Restore sum 1 by a single UNIFORM rescale (absorbed by the fitted
    # amplitude). Crucially this is NOT the old residual-redistribution, which
    # pushed a clipped tail's mass up onto the mono and +1 and made a fully
    # covered monoisotopic peak overshoot its +1. A uniform scale preserves the
    # observed ratios among the in-band isotopes, so the high-S/N peaks that drive
    # the fit keep their observed proportions and the model matches them.
    total = float(numpy.sum(blended))
    if total <= 0.0:
        return ordered
    blended = blended / total

    # Unimodality guard: observed noise can push an interior isotope down (a
    # notch) below its neighbours. Project onto the nearest unimodal shape (PAVA,
    # area-preserving) so the model stays a plausible single-species pattern.
    blended = _project_unimodal(blended)

    blended_total = float(numpy.sum(blended))
    if blended_total <= 0.0:
        return ordered

    return [(ordered[i][0], float(blended[i])) for i in range(len(ordered))]


# ----


def _cluster_pattern(parent, size, averagineType=DEFAULT_AVERAGINE):
    """Get expected isotope pattern slice for parent peak using Poisson Averagine approximation."""
    if size <= 0:
        return []

    neutralMass = _mass_scalar(
        mod_basics.mz(parent.mz, charge=0, currentCharge=parent.charge, massType=1),
        massType=1,
    )

    # Averagine Poisson approximation: expected number of +1 isotopes per Da,
    # dominated by 13C. The factor depends on the selected averagine type's
    # carbon density (see AVERAGINE_MODELS); protein ~ 0.000475.
    lam = neutralMass * _averagine_lambda(averagineType)

    pattern = []
    p = math.exp(-lam) if lam < 700 else 0.0
    for i in range(size):
        if i == 0:
            pattern.append(p)
        else:
            p = p * (lam / i)
            pattern.append(p)

    # If lambda is huge, exponential might underflow to 0. Fallback scaling:
    if sum(pattern) <= 0.0:
        return [1.0] + [0.0] * (size - 1)

    max_p = max(pattern)
    return [x / max_p for x in pattern]


# ----


def _cluster_sn(cluster):
    """Estimate local S/N for a cluster from peak-level S/N values."""

    values = [p.sn for p in cluster if p.sn and p.sn > 0.0]
    if not values:
        return None

    values.sort()
    n = len(values)
    if n % 2:
        return values[n // 2]
    return 0.5 * (values[(n // 2) - 1] + values[n // 2])


# ----


def _sn_quality(cluster):
    """Map local S/N to [0, 1] quality where 1 means clean signal."""

    sn = _cluster_sn(cluster)
    if sn is None:
        return 0.5

    # 3 is near detection threshold, 25 is generally clean.
    q = (sn - 3.0) / 22.0
    if q < 0.0:
        return 0.0
    if q > 1.0:
        return 1.0
    return q


# ----


def _adaptive_mz_tolerance(baseTolerance, cluster):
    """Relax m/z matching in noisy regions, tighten in clean regions."""

    q = _sn_quality(cluster)
    factor = 0.9 + (1.35 - 0.9) * (1.0 - q)
    return baseTolerance * factor


# ----


def _snap_to_local_apex(sigX, sigY, center, window, floor=0.0):
    """m/z of the profile maximum nearest `center`, within +/- window.

    Used to lock a modeled tail isotope onto the real peak that sits at the
    expected isotope spacing instead of the bare grid point. When two close
    peaks straddle the grid, the candidate *closest to the expected position*
    wins -- not the tallest -- so the envelope never snaps onto a taller
    neighbouring species' peak. Only maxima above `floor` qualify; with none
    (e.g. a forced placeholder on flat noise) the grid `center` is kept. The
    search is bounded to +/- window (the mass tolerance), so the snap can never
    move an isotope onto -- or swap it with -- a neighbour.
    """

    if sigX is None or len(sigX) == 0:
        return center

    i1 = int(numpy.searchsorted(sigX, center - window, side="left"))
    i2 = int(numpy.searchsorted(sigX, center + window, side="right"))
    if i2 - i1 < 1:
        return center

    best_mz = None
    best_dist = None
    for j in range(i1, i2):
        val = float(sigY[j])
        if val <= 0.0 or val < floor:
            continue
        # local maximum: not lower than its immediate neighbours
        if j > 0 and sigY[j - 1] > val:
            continue
        if j < len(sigY) - 1 and sigY[j + 1] > val:
            continue
        dist = abs(float(sigX[j]) - center)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_mz = float(sigX[j])

    return best_mz if best_mz is not None else center


# ----


def _cluster_observed_pattern(parent, cluster, isotopeShift=0.0):
    """Build observed isotope intensities indexed by inferred isotope number."""

    if not parent.charge:
        return None, None

    difference = (ISOTOPE_DISTANCE + isotopeShift) / abs(parent.charge)
    if difference <= 0.0:
        return None, None

    inferred = []
    maxMzError = 0.0
    for peak in cluster:
        isotope = int(round((peak.mz - parent.mz) / difference))
        if isotope < 0:
            return None, None
        expected = parent.mz + isotope * difference
        maxMzError = max(maxMzError, abs(peak.mz - expected))
        inferred.append((isotope, max(0.0, peak.intensity)))

    if not inferred:
        return None, None

    maxIsotope = max([x[0] for x in inferred])
    observed = numpy.zeros(maxIsotope + 1, dtype=float)
    for isotope, intensity in inferred:
        observed[isotope] = max(observed[isotope], intensity)

    return observed, maxMzError


# ----


def _cluster_pattern_error(
    parent, cluster, isotopeShift=0.0, relaxed=False,
    averagineType=DEFAULT_AVERAGINE,
):
    """Return fit error for expected isotope pattern; None means invalid."""

    if len(cluster) < 2:
        return 0.0

    observed, maxMzError = _cluster_observed_pattern(parent, cluster, isotopeShift)
    if observed is None or len(observed) < 2:
        return None
    if maxMzError is None:
        return None

    pattern = _cluster_pattern(parent, len(observed), averagineType=averagineType)
    if len(pattern) < len(observed):
        return None

    quality = _sn_quality(cluster)

    # Reject internal missing isotopes when expected abundance is non-trivial.
    maxPattern = max(pattern)
    gapThreshold = 0.20 - (0.12 * quality)
    if relaxed:
        gapThreshold *= 2.5  # Allow bigger gaps in manual mode
    for isotope in range(1, len(observed) - 1):
        if observed[isotope] > 0.0:
            continue
        relative = pattern[isotope] / maxPattern
        if relative >= gapThreshold:
            return None

    # Fit one scale factor to expected pattern.
    expected = numpy.array(pattern, dtype=float)
    denom = float(numpy.dot(expected, expected))
    if denom <= 0.0:
        return None
    scale = float(numpy.dot(observed, expected)) / denom
    if scale <= 0.0:
        return None

    predicted = expected * scale
    if float(numpy.max(predicted)) <= 0.0:
        return None

    # Weighted relative error for significant isotopes.
    mask = predicted >= (float(numpy.max(predicted)) * 0.03)
    if not numpy.any(mask):
        return None

    delta = observed - predicted
    overError = numpy.maximum(delta, 0.0) / (predicted + 1e-12)
    underError = numpy.maximum(-delta, 0.0) / (predicted + 1e-12)
    # Undercalled isotopes are common in overlap/noise; penalize them less
    # than overshoot while still enforcing no impossible internal gaps.
    underWeight = 0.30 + (1.0 - quality) * 0.20
    relError = overError + underWeight * underError
    weights = expected / max(expected)
    weightedError = float(
        numpy.sum(relError[mask] * weights[mask]) / max(numpy.sum(weights[mask]), 1e-12)
    )
    maxOverError = float(numpy.max(overError[mask]))

    # Mode can drift a bit in noisy overlap, but not arbitrarily.
    expectedMode = int(numpy.argmax(expected))
    observedMode = int(numpy.argmax(observed))
    maxModeShift = 1
    if quality < 0.35:
        maxModeShift = 2
    if relaxed:
        maxModeShift = 100 # Disable mode-shift check in manual mode
    if observedMode > expectedMode + maxModeShift:
        return None

    # Keep m/z-index consistency reasonably tight.
    expectedDiff = (ISOTOPE_DISTANCE + isotopeShift) / abs(parent.charge)
    mzErrorNorm = maxMzError / max(expectedDiff, 1e-12)

    # Adaptive acceptance thresholds: strict at high S/N, relaxed at low S/N.
    weightedLimit = 0.55 + ((1.0 - quality) * 1.05)
    maxOverLimit = 1.20 + ((1.0 - quality) * 0.95)
    mzNormLimit = 0.22 + ((1.0 - quality) * 0.18)
    if relaxed:
        weightedLimit *= 5.0 # Highly relaxed mode
        maxOverLimit *= 5.0
        mzNormLimit *= 2.0
    if (
        weightedError > weightedLimit
        or maxOverError > maxOverLimit
        or mzErrorNorm > mzNormLimit
    ):
        return None

    return weightedError


# ----


def _is_plausible_cluster(
    parent, cluster, isotopeShift=0.0, relaxed=False,
    averagineType=DEFAULT_AVERAGINE,
):
    """Reject clusters that do not fit expected isotopic pattern."""

    return (
        _cluster_pattern_error(
            parent,
            cluster,
            isotopeShift,
            relaxed=relaxed,
            averagineType=averagineType,
        )
        is not None
    )


# ----


def _merge_adjacent_clusters(
    clusters, mzTolerance, isotopeShift, relaxed=False,
    averagineType=DEFAULT_AVERAGINE,
):
    """Merge neighboring clusters when they are consistent with one envelope."""

    if len(clusters) < 2:
        return clusters

    merged = list(clusters)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(merged) - 1:
            left = merged[i]
            right = merged[i + 1]
            if not left or not right:
                i += 1
                continue

            parent = left[0]
            rightParent = right[0]
            if not parent.charge or rightParent.charge != parent.charge:
                i += 1
                continue

            difference = (ISOTOPE_DISTANCE + isotopeShift) / abs(parent.charge)
            if difference <= 0.0:
                i += 1
                continue

            delta = rightParent.mz - parent.mz
            if delta <= 0.0:
                i += 1
                continue

            expectedIsotope = int(round(delta / difference))
            if expectedIsotope < 1:
                i += 1
                continue

            # Envelopes are strictly continuous: never fuse two clusters that
            # are separated by missing isotopes. The right cluster's first peak
            # must fall at or before the isotope position immediately after the
            # left cluster ends (overlap or direct adjacency); a larger step
            # means there is a gap between them, so they are distinct envelopes.
            if expectedIsotope > len(left):
                i += 1
                continue

            expectedMz = parent.mz + expectedIsotope * difference
            # scale the matching window by 1/charge, like the isotope spacing
            chargeTol = mzTolerance / abs(parent.charge)
            dynamicTol = max(
                _adaptive_mz_tolerance(chargeTol, left),
                _adaptive_mz_tolerance(chargeTol, right),
            )
            if abs(rightParent.mz - expectedMz) > dynamicTol:
                i += 1
                continue

            trial = sorted(left + right, key=lambda p: p.mz)
            # Two clusters that OVERLAP -- sharing isotope positions -- are two
            # distinct species, not one envelope split by a gap. Fusing them makes a
            # single representative carrying a DUPLICATED, irregular isotope grid (two
            # combs interleaved), which then over-claims the shared signal and cannot
            # be re-derived from positions. That is exactly the merge the "convert to
            # envelopes" route has to undo, so "find peaks" and "convert" disagree
            # (example_env4.msd: 900.49 fused 902.51 into a 10-isotope grid). Only
            # merge genuinely adjacent fragments (no shared positions); leave
            # overlapping species as separate seeds so the joint fit apportions them,
            # and both routes produce the same clean single-species envelopes.
            trialMzs = [p.mz for p in trial]
            minGap = min(
                (trialMzs[k + 1] - trialMzs[k] for k in range(len(trialMzs) - 1)),
                default=difference,
            )
            if minGap < 0.5 * difference:
                i += 1
                continue
            # Enforce true envelope shape for merging even in relaxed mode,
            # so overlapping envelopes don't get squashed together.
            if not _is_plausible_cluster(
                parent,
                trial,
                isotopeShift,
                relaxed=False,
                averagineType=averagineType,
            ):
                i += 1
                continue

            merged[i] = trial
            del merged[i + 1]
            changed = True

        # keep scanning after successful merge pass

    return merged


# ----


def _envelope_gaussian_column(x, isotopes, sigma):
    """Build one envelope basis column: a sum of unit-area Gaussians.

    Each isotope contributes a Gaussian whose integral equals its weight, so
    the column integrates to sum(weights). With weights normalised to 1 the
    fitted coefficient is therefore the total envelope area.
    """

    norm = sigma * math.sqrt(2.0 * math.pi)
    column = numpy.zeros(len(x), dtype=float)
    if norm <= 0.0:
        return column
    for mz, weight in isotopes:
        column += (float(weight) / norm) * numpy.exp(
            -0.5 * ((x - float(mz)) / sigma) ** 2
        )
    return column


# ----


ENVELOPE_CAP_ANCHOR_FRACTION = 0.75
ENVELOPE_CAP_CONTEST_FRACTION = 0.10
ENVELOPE_CAP_CONTEST_MIN_FRACTION = 0.50

# A buried envelope's major peak is trimmed to its residual (see the gated
# residual pass in `_apportion_group_areas`) only when the neighbour dominating
# that shared peak is itself a MINOR isotope of its own pattern -- its weight is
# below this fraction of its apex. Below the gate the neighbour takes only a
# small bite of the shared peak, so the residual leaves the buried species its
# real share; above it (a light species' +1 sitting under a heavier mono) the
# residual would crush a real labelled peak, so the shape split is kept instead.
# Sits between the measured minor-tail cases (dominant weight ~0.20-0.37, trimmed)
# and the major-peak case that must stay visible (test_small_envelope_under_large
# _neighbour_keeps_fair_share, dominant weight ~0.475, left alone).
ENVELOPE_RESIDUAL_MINOR_GATE = 0.40


def _envelope_amp_cap(areaColumn, x, capSignal, shaped, fwhm, otherFrac=None):
    """Largest amplitude whose modelled envelope stays under ``capSignal``.

    ``capSignal`` here is the envelope's own *apportioned share* ``g_k`` of the
    observed profile (see `_apportion_group_areas`), NOT the raw observed curve.
    For a unit-area column the amplitude is bounded by
    ``min_i g_k(apex_i) / column(apex_i)`` over a *chosen subset* of this
    envelope's isotope apexes, where ``g_k`` and ``column`` are each the local
    maximum in a small window around the isotope (window maxima, so a slight
    grid/position offset or an inter-isotope valley cannot distort the ratio --
    sampling the raw column everywhere over-clamped to zero at the valleys).

    Capping against the *share* rather than the observed total is what makes the
    decomposition add up: because the shares sum to the observed curve
    (``sum_k g_k = y``), holding every envelope's model under its own share at a
    peak it *shares* with a neighbour means the summed model can never exceed the
    observed peak. So two envelopes that overlap at one m/z (a lower species'
    isotope and a higher species' mono) split that peak fairly and their
    contributions sum to it -- neither takes it whole.

    **Which isotopes bind the cap (contested-aware).** Only two kinds of isotope
    are allowed to lower the amplitude:

    * the **abundant anchor** isotopes (weight >= ``ENVELOPE_CAP_ANCHOR_FRACTION``
      of the apex). These set a ceiling that scales with the envelope's own peak
      height, which is what keeps similar-height overlapping envelopes comparable
      and stops the highest-m/z envelope of a selection from inflating on the
      untracked peak-forest to its right (there its share is ~1 but its column has
      only a tiny tail weight, so the near-mono apexes bound the area tightly).

    * the **contested significant** isotopes -- those where another labelled
      envelope in the group genuinely competes for the signal (``otherFrac`` at the
      apex exceeds ``ENVELOPE_CAP_CONTEST_FRACTION``) *and* which are themselves a
      significant peak of this envelope (weight >= ``ENVELOPE_CAP_CONTEST_MIN_FRACTION``
      of the apex). This is where the no-overshoot guarantee is actually needed: two
      envelopes competing for a *major* peak (a light species' +1 on a heavier
      mono) must each be held to their fair share so the sum stays under it.

    A contested isotope that is only a **minor tail** of this envelope (below
    ``ENVELOPE_CAP_CONTEST_MIN_FRACTION`` of the apex) is deliberately NOT allowed
    to bind, even though a neighbour competes there. Because one amplitude drives
    every isotope, capping the envelope at a shared *minor* peak drags the whole
    envelope down -- including its unshared, fully-owned mono/+1 -- crushing a
    dominant envelope to a fraction of its real area and pulling the group total
    *below* the usable area (the ``example_env3.msd`` regression: a small species'
    mono landing on a large envelope's +2 collapsed the large one to ~42%). The
    shared minor peak is instead held under the observed curve by the *neighbour's*
    cap, for which that peak is a major/anchor isotope -- the envelope that owns it
    is the one that bounds it.

    An isotope that is neither abundant nor contested-significant -- one the
    envelope owns outright but that simply sits below the modelled pattern (a
    non-averagine tail, a noisy minor isotope) -- is likewise NOT allowed to bind.
    Letting such an isotope into the ``min`` was the old over-strictness: a single
    depressed isotope the envelope plainly owns dragged the whole amplitude down
    and starved the monoisotopic peak, even with no neighbour to protect. The
    model may now cover its own mono fully and, at most, poke cosmetically above
    its own depressed tail (no shared signal is over-claimed). ``otherFrac`` is
    the per-point fraction of the structural signal contributed by the *other*
    envelopes in the group; ``None`` (an isolated envelope, no competitors) means
    nothing is contested and only the abundant anchor binds.
    """

    if not shaped or areaColumn.size == 0:
        return None

    weights = [max(0.0, float(w)) for _mz, w in shaped]
    wMax = max(weights) if weights else 0.0
    if wMax <= 0.0:
        return None

    # window half-width: wide enough to catch the real apex (which may sit a
    # fraction of the peak width off the model grid) yet far inside the isotope
    # spacing so it never samples a neighbouring isotope
    halfWin = max(0.6 * float(fwhm), 1e-3)
    anchorWeight = ENVELOPE_CAP_ANCHOR_FRACTION * wMax

    cap = None
    for (mz, w) in shaped:
        # skip the near-zero tail entirely: unreliable and never a real ceiling
        if float(w) < 0.1 * wMax:
            continue
        i1 = int(numpy.searchsorted(x, mz - halfWin, side="left"))
        i2 = int(numpy.searchsorted(x, mz + halfWin, side="right"))
        if i2 <= i1:
            continue

        isAnchor = float(w) >= anchorWeight
        contested = False
        if otherFrac is not None:
            # a contested isotope may bind only if it is itself a *significant*
            # peak of this envelope. A minor tail isotope (e.g. a +2/+3 at a small
            # fraction of the apex) that happens to coincide with a neighbour's
            # monoisotopic peak must NOT bind: since one amplitude drives every
            # isotope, capping the envelope at that shared minor peak drags the
            # whole envelope -- including its unshared, fully-owned mono/+1 -- down
            # with it, crushing a dominant envelope to a fraction of its real area
            # (the example_env3.msd regression). Requiring the contested isotope to
            # be a significant peak keeps the cap where two envelopes genuinely
            # compete for a *major* peak (a light species' +1 on a heavier mono),
            # so the group total is still held to the usable area, without letting
            # a shared tail crush the group total below it.
            isMajor = float(w) >= ENVELOPE_CAP_CONTEST_MIN_FRACTION * wMax
            contested = (
                isMajor
                and float(otherFrac[i1:i2].max()) >= ENVELOPE_CAP_CONTEST_FRACTION
            )
        # an isotope the envelope owns outright, or a minor tail it merely shares,
        # must not pull the amplitude below what its own abundant peaks support
        if not (isAnchor or contested):
            continue

        colPeak = float(areaColumn[i1:i2].max())
        if colPeak <= 0.0:
            continue
        sigPeak = float(capSignal[i1:i2].max())
        ratio = sigPeak / colPeak
        cap = ratio if cap is None else min(cap, ratio)
    return cap


def _dominant_shared_weight(k, capInfo, x):
    """Largest apex-relative weight any OTHER envelope has at one of envelope k's
    own MAJOR isotopes -- the "signal 1" residual discriminator.

    For each of k's significant peaks (weight >= ``ENVELOPE_CAP_CONTEST_MIN_FRACTION``
    of its apex) we look at every other envelope's pattern for an isotope at the
    same m/z and take that neighbour's own apex-relative weight there. A small
    result means k's major peak sits on a neighbour's MINOR tail (the neighbour
    takes only a small bite, so trimming k to the residual leaves it its fair
    share); a large result means it sits on a neighbour's MAJOR peak (a light
    species' +1 under a heavier mono), where the residual would crush a real
    labelled peak. Returns 0.0 when nothing competes at k's major peaks.
    """

    shaped, fwhm = capInfo[k]
    if not shaped:
        return 0.0
    halfWin = max(0.6 * float(fwhm), 1e-3)
    wMax = max((float(w) for _mz, w in shaped), default=0.0) or 1.0
    worst = 0.0
    for (mz, w) in shaped:
        if float(w) < ENVELOPE_CAP_CONTEST_MIN_FRACTION * wMax:
            continue
        for j, (shpJ, _fwhmJ) in enumerate(capInfo):
            if j == k or not shpJ:
                continue
            wMaxJ = max((float(wj) for _m, wj in shpJ), default=0.0) or 1.0
            for (mzj, wj) in shpJ:
                if abs(float(mzj) - float(mz)) <= halfWin:
                    rel = float(wj) / wMaxJ
                    if rel > worst:
                        worst = rel
    return worst


def _has_unshared_major(k, capInfo, otherFrac, x):
    """True if envelope k owns a MAJOR isotope outright -- the "signal 2" tiebreaker.

    A significant peak of k (weight >= ``ENVELOPE_CAP_CONTEST_MIN_FRACTION`` of its
    apex) that no neighbour competes for (``otherFrac`` there below
    ``ENVELOPE_CAP_CONTEST_FRACTION``) is independent evidence of k's real size, so
    its residual can be trusted even when a neighbour dominates the shared peak.
    This is what separates a buried species with its own clean anchor (safe to
    trim) from a fully nested one whose every peak lies under a neighbour (must be
    kept visible by the shape split). ``None`` otherFrac (isolated) has no
    competitors, so the question does not arise and this returns False.
    """

    shaped, fwhm = capInfo[k]
    if not shaped or otherFrac is None:
        return False
    halfWin = max(0.6 * float(fwhm), 1e-3)
    wMax = max((float(w) for _mz, w in shaped), default=0.0) or 1.0
    for (mz, w) in shaped:
        if float(w) < ENVELOPE_CAP_CONTEST_MIN_FRACTION * wMax:
            continue
        i1 = int(numpy.searchsorted(x, mz - halfWin, side="left"))
        i2 = int(numpy.searchsorted(x, mz + halfWin, side="right"))
        if i2 <= i1:
            continue
        if float(otherFrac[i1:i2].max()) < ENVELOPE_CAP_CONTEST_FRACTION:
            return True
    return False


def _apportion_group_areas(areaColumns, apexColumns, x, y, capInfo=None):
    """Split the observed signal among overlapping envelopes, then fit each area.

    Two column sets are supplied per envelope:

    * `apexColumns[k]` -- the isotope pattern rendered as gaussians and normalised
      so its most abundant (*apex*) isotope equals 1. These drive the *base* split:
      at each point ``share_k(x) = apex_k(x) / sum_j apex_j(x)``. Because every
      envelope is normalised to its own tallest peak, this base split does NOT
      depend on absolute abundance -- so a tall lower-m/z species' isotope tail
      cannot swamp and rob a shorter higher-m/z neighbour, and a small labelled
      envelope whose every peak is buried under a much taller neighbour still keeps
      a meaningful share instead of collapsing to zero. Normalising to the apex
      rather than the monoisotopic peak is what keeps the split fair for heavy
      envelopes, whose apex is +2/+4/+5 and whose mono is a tiny sliver: comparing
      two overlapping species at their representative (tallest) peak no longer
      flattens a genuine abundance difference the way comparing at the mono did.

    * `areaColumns[k]` -- the same pattern but normalised to unit *area* (a unit
      coefficient integrates to one). Each envelope's area is the least-squares
      amplitude of this column fitted to that envelope's apportioned share of the
      signal, ``g_k = y * share_k``. Fitting the model (rather than just
      integrating ``g_k``) is what lets the isotope *shape* matter: for an
      isolated, non-averagine envelope a shape allowed to bend toward the data
      (larger nonIdeality) captures more of the peak and yields a different area,
      so the nonIdeality parameter actually moves the number.

    The base (equal-weight) split alone is unfair in the *opposite* direction: it
    ignores abundance entirely, so a tiny envelope whose faint isotope happens to
    coincide with a much larger neighbour's *monoisotopic* peak is handed a share
    of that big peak far beyond anything its own small pattern could account for
    (e.g. a 1% contributor claiming ~30% of the peak), and the big envelope's area
    drops accordingly. The physical statement the user wants is that the observed
    peak equals the *sum of what each envelope actually contributes there* -- a
    neighbour's +2 isotope plus the mono, adding up to the whole -- and that split
    must be consistent with each envelope's own amplitude.

    So one **refinement pass** follows the base split: the share is re-weighted by
    each envelope's fitted model ``amp_k * areaCol_k`` (its actual predicted
    intensity), then areas are re-fit. An envelope with independent evidence of
    being small -- a clean, unshared anchor peak that pins its amplitude low --
    then claims only its small physical share of a shared peak, and the dominant
    envelope recovers the rest. This is one mass-conserving Gauss-Seidel step of a
    non-negative deconvolution seeded from the fair base split. It is deliberately
    a *single* damped step, NOT run to convergence: full convergence is the plain
    least-squares/NNLS solution, which drives a fully buried labelled envelope's
    area to (near) zero -- the regression the base apex-normalised split exists to
    prevent. One step removes the gross over-crediting without erasing a buried
    label. (For an isolated envelope, ``K == 1``, the share is identically one both
    passes, so the refinement is a no-op and the fit is unchanged.)

    Least squares can still over-claim where an envelope's isotope tail runs into
    signal from *untracked* species (its share there is ~1 because nothing
    competes), pulling the amplitude up until its modelled peak pokes above the
    observed curve. `capInfo[k] = (shaped, fwhm)` lets each amplitude be capped so
    the model stays under that envelope's OWN apportioned share ``g_k`` at its
    isotope apexes (see `_envelope_amp_cap`). The cap is applied on the refinement
    pass; it only lowers amplitudes, never raises them.

    A **gated residual trim** then removes the remaining pointwise over-crediting.
    Where a buried species' MAJOR peak sits on a neighbour's MINOR tail, the shape
    split still hands it more of the shared peak than the residual (observed minus
    the neighbours' own fitted contribution) can support, so the summed model pokes
    above the curve at that peak even though the group integral is bounded. Each
    such envelope is re-fit to that residual and trimmed to it (never raised).
    ``_dominant_shared_weight`` and ``_has_unshared_major`` gate it so it fires only
    where the residual equals the fair share -- a neighbour that takes only a small
    minor-tail bite, or an envelope with its own unshared major peak to pin it --
    and never on a light species' +1 buried under a heavier mono, which the shape
    split keeps visible. It is one damped Gauss-Seidel step from a frozen amplitude
    snapshot (so it is order-independent) and, by trimming an over-credited buried
    species to its fair value, it also lets the dominant recover toward its true
    area instead of being dragged down by the ceiling below. Areas that are already
    fair (the residual supports at least the current amplitude) are left untouched,
    so a real, well-fit overlap is unchanged.

    Finally a **group-total ceiling** enforces the conservation invariant at the
    level the user reads it -- the whole overlap group. The per-envelope cap bounds
    each envelope at its *peaks*, but a neighbour whose mono sits on a dominant
    envelope's tail can still push the *summed* model above the observed curve
    where they overlap, so the group claims more area than the spectrum holds. A
    single uniform rescale of every amplitude to the observed integral holds the
    group total to the available area; being uniform it preserves the split (buried
    labels keep their visible share, the dominant is only trimmed proportionally),
    so it conserves mass without re-crushing anyone. It acts only on overlap groups
    (``K > 1``) and only when the group would otherwise overshoot.
    """

    K = len(areaColumns)
    if K == 0 or len(x) == 0:
        return [0.0] * K

    yy = numpy.clip(y, 0.0, None)

    # structural competition per envelope: at each point, the fraction of the
    # (abundance-normalised) signal contributed by the OTHER envelopes in the
    # group. Used to decide which of an envelope's isotopes are genuinely shared
    # -- and so may bind its amplitude cap -- versus owned outright. Built from the
    # unit-area columns (shape, not fitted amplitude) so it reflects real overlap,
    # not this pass's provisional amplitudes.
    structuralTotal = numpy.zeros(len(x), dtype=float)
    for col in areaColumns:
        structuralTotal = structuralTotal + col
    safeStructural = numpy.where(structuralTotal > 0.0, structuralTotal, 1.0)
    otherFracs = [
        numpy.clip((structuralTotal - areaColumns[k]) / safeStructural, 0.0, 1.0)
        if K > 1 else None
        for k in range(K)
    ]

    def _pass(weightColumns, useCap):
        """One apportionment pass over `weightColumns` (the per-envelope columns
        that drive the split). Returns the least-squares amplitude per envelope,
        optionally capped. The active region -- where some envelope predicts signal
        -- keeps baseline noise between/outside the isotope peaks out of the fit;
        where nothing predicts signal the share is undefined (0/0) and there is
        nothing to attribute."""
        total = numpy.zeros(len(x), dtype=float)
        for col in weightColumns:
            total = total + col
        peak = float(total.max()) if total.size else 0.0
        threshold = 1e-6 * peak if peak > 0.0 else 0.0
        active = total > threshold
        safeTotal = numpy.where(active, total, 1.0)

        amps = []
        for k, (areaCol, wcol) in enumerate(zip(areaColumns, weightColumns, strict=True)):
            share = numpy.where(active, wcol / safeTotal, 0.0)
            g = yy * share
            denom = float(numpy.dot(areaCol, areaCol))
            amp = float(numpy.dot(areaCol, g)) / denom if denom > 0.0 else 0.0
            if useCap and capInfo is not None:
                shaped, fwhm = capInfo[k]
                cap = _envelope_amp_cap(
                    areaCol, x, g, shaped, fwhm, otherFrac=otherFracs[k]
                )
                if cap is not None:
                    amp = min(amp, cap)
            amps.append(max(0.0, amp))
        return amps

    # base split: equal-weight, abundance-independent (apex-normalised columns)
    baseAmps = _pass(apexColumns, useCap=False)

    # one refinement step: re-weight the split by each envelope's fitted model
    # amp_k * areaCol_k (its actual predicted intensity), then re-fit and cap. A
    # single step -- not convergence -- so gross over-crediting of a shared peak is
    # removed while a fully buried labelled envelope is not driven to zero.
    refineColumns = [
        max(0.0, baseAmps[k]) * areaColumns[k] for k in range(K)
    ]
    amps = _pass(refineColumns, useCap=True)

    # Gated residual trim (one damped Gauss-Seidel step). The shape split keeps a
    # buried species visible, but where that species' MAJOR peak sits on a
    # neighbour's MINOR tail it is still handed more of the shared peak than the
    # residual -- observed minus the neighbours' own fitted contribution -- can
    # support, leaving a pointwise overshoot at the shared peak even though the
    # group integral is bounded (the parked ``example_env3`` overshoot). Trim such
    # an envelope to its residual. Guarded so it fires only where residual == fair
    # share:
    #   * the neighbour dominating this envelope's major peak must itself be a
    #     MINOR isotope there (`_dominant_shared_weight` below the gate) -- a small
    #     bite that leaves the buried species its real share; OR
    #   * the envelope must own an unshared major peak (`_has_unshared_major`) that
    #     independently pins its size, so the residual is trustworthy even against
    #     a major dominant.
    # When the shared peak is a MAJOR peak of the neighbour (a light species' +1 on
    # a heavier mono) and the envelope has no independent evidence, the residual
    # would crush a real labelled peak, so the shape split is kept and the envelope
    # stays visible. The residual only ever LOWERS an amplitude, and every
    # candidate is computed from a single frozen snapshot of the pre-trim
    # amplitudes, so the result does not depend on the order the envelopes are
    # visited. Isolated envelopes (K == 1) share no peak and are left untouched.
    if K > 1 and capInfo is not None and len(x) > 1:
        frozen = list(amps)
        model = numpy.zeros(len(x), dtype=float)
        for amp, col in zip(frozen, areaColumns, strict=True):
            model = model + amp * col
        for k in range(K):
            shaped, _fwhm = capInfo[k]
            if not shaped:
                continue
            gentle = _dominant_shared_weight(k, capInfo, x) < ENVELOPE_RESIDUAL_MINOR_GATE
            if not (gentle or _has_unshared_major(k, capInfo, otherFracs[k], x)):
                continue
            # residual = observed minus every OTHER envelope's fitted contribution
            others = model - frozen[k] * areaColumns[k]
            residual = numpy.clip(yy - others, 0.0, None)
            areaCol = areaColumns[k]
            denom = float(numpy.dot(areaCol, areaCol))
            if denom <= 0.0:
                continue
            ampResid = float(numpy.dot(areaCol, residual)) / denom
            if ampResid < amps[k]:
                amps[k] = max(0.0, ampResid)

    # Group-total ceiling. The per-envelope cap holds each envelope under its own
    # apportioned share at its *peaks*, but once a dominant envelope is (correctly)
    # allowed to keep its full amplitude, a neighbour whose monoisotopic peak sits
    # on the dominant's tail can still leave the *summed* model above the observed
    # curve where they overlap -- so the group as a whole claims more area than the
    # spectrum holds there. The invariant the user cares about is at this group
    # level: the total fitted area may not exceed the area actually available under
    # the group's peaks. Enforce it with a single uniform rescale of every
    # amplitude to the observed integral. Being uniform, it preserves the relative
    # split -- a buried label keeps its visible share and the dominant is only
    # trimmed proportionally ("a bit smaller, not crushed") -- so it conserves the
    # group total without re-crushing anyone or re-opening the abundance question.
    # Only overlap groups have a shared budget; an isolated envelope (K == 1) is
    # bounded by its own cap and is left untouched.
    if K > 1 and len(x) > 1:
        model = numpy.zeros(len(x), dtype=float)
        for amp, col in zip(amps, areaColumns, strict=True):
            model = model + amp * col
        modelInt = float(numpy.trapezoid(model, x))
        budget = float(numpy.trapezoid(yy, x))
        if modelInt > budget > 0.0:
            scale = budget / modelInt
            amps = [amp * scale for amp in amps]
    return amps


# ----


def _overlap_groups(intervals):
    """Partition cluster indices into connected overlap groups.

    `intervals` is a list of (lo, hi) m/z spans (one per cluster). Two clusters
    interact in the joint fit only if their spans overlap, and overlap is
    transitive, so the clusters split into independent connected components.
    Fitting each component on its own keeps every NNLS matrix small (important
    when the whole spectrum is fit at once) while giving exactly the same result
    as one big joint fit, because non-overlapping envelopes never share signal.
    """

    order = sorted(range(len(intervals)), key=lambda i: intervals[i][0])
    groups = []
    current = []
    currentHi = float("-inf")
    for i in order:
        lo, hi = intervals[i]
        if current and lo <= currentHi:
            current.append(i)
            currentHi = max(currentHi, hi)
        else:
            if current:
                groups.append(current)
            current = [i]
            currentHi = hi
    if current:
        groups.append(current)
    return groups


# ----


def _is_regular_isotope_grid(shaped):
    """True if `shaped` is a clean single-species isotope grid.

    `shaped` is a list of (mz, weight). A genuine single envelope has strictly
    increasing positions spaced by roughly one isotope step, so every gap is close
    to the typical gap. A *merged* representative -- several overlapping envelopes
    collapsed onto one peak (the "1st" label) -- instead carries duplicated or
    irregular positions (two species' isotopes interleave, some coincide), which
    cannot be re-derived from an averagine grid.

    This is what lets an isolated envelope re-soft-model against the current
    non-ideality (a regular grid) while a merged one keeps its stored shape (an
    irregular grid): once the user deletes a neighbour, the survivor is a regular
    grid again and is correctly treated as isolated. A gap much smaller than the
    typical spacing means two positions are effectively the same isotope -- a
    duplicate that only a merged/collapsed shape produces.
    """

    positions = sorted(float(mz) for mz, _w in shaped)
    if len(positions) < 2:
        return True
    gaps = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
    minGap = min(gaps)
    if minGap <= 0.0:
        return False
    medGap = sorted(gaps)[len(gaps) // 2]
    if medGap <= 0.0:
        return False
    # any gap under half the typical isotope spacing is a duplicated position
    return minGap >= 0.5 * medGap


def _fit_group_areas(metas, x, y, nonIdeality):
    """Apportion the observed signal among a group of (overlapping) envelopes.

    `metas` holds (fwhm, sigma, theoryIsotopes) for each envelope in the group.
    Areas come from `_apportion_group_areas`: the observed signal at every point
    is split among the envelopes in proportion to their isotope patterns
    (normalised to each envelope's own monoisotopic peak), so a tall lower-m/z
    species cannot rob a shorter higher-m/z neighbour, and the summed model stays
    within the observed curve.

    Isotope *shape* is handled differently depending on overlap:

    * An isolated envelope (the only one in its group) may bend its isotope
      pattern from averagine toward the data -- real, especially high-mass,
      envelopes are not perfectly averagine, and with nothing overlapping it the
      bend cannot steal a neighbour's signal. This keeps single-envelope areas
      accurate.

    * Overlapping envelopes keep the rigid averagine pattern, so the isotope
      contributions are scaled by theory alone and the apportionment is clean and
      symmetric.

    Returns (areas, shapes): the fitted area per envelope and the per-isotope
    (mz, weight) model used for each envelope (weights summing to 1), so the
    caller can store and draw exactly the envelope the area was fitted to.
    """

    K = len(metas)
    if nonIdeality is None:
        nonIdeality = ENVELOPE_NON_IDEALITY_DEFAULT

    norm_ok = [sigma > 0.0 and bool(isotopes) for _fwhm, sigma, isotopes, _stored in metas]

    # the theoretical (averagine) pattern is the default shape
    shapes = [list(isotopes) for _fwhm, _sigma, isotopes, _stored in metas]

    areaColumns = []
    apexColumns = []
    capInfo = []
    for k, (fwhm, sigma, isotopes, storedShape) in enumerate(metas):
        if not norm_ok[k]:
            areaColumns.append(numpy.zeros(len(x), dtype=float))
            apexColumns.append(numpy.zeros(len(x), dtype=float))
            capInfo.append(([], 0.0))
            continue

        # Shape selection:
        #
        # * Isolated envelope (the only one in its group) with a regular,
        #   single-species isotope grid: always soft-model at the CURRENT
        #   non-ideality, so the user's preference takes effect -- including on the
        #   "Convert to Envelopes" route, where the envelope carries a stored shape.
        #   A stored shape is deliberately NOT reused here: reusing it froze the
        #   shape and made non-ideality a no-op after a neighbour was deleted and
        #   the survivor became isolated. Re-softening is idempotent at a fixed
        #   non-ideality (same theoretical pattern + data), so an unchanged setting
        #   still reproduces the picked value. (Spec: non-ideality is effective for
        #   non-overlapping envelopes, inert for overlapping ones.)
        #
        # * A stored shape on a MERGED/irregular grid -- several overlapping species
        #   collapsed onto one representative -- is reused verbatim: that shape
        #   cannot be re-derived from the positions (they are duplicated), and even
        #   though it forms a K==1 group it is not a single species, so non-ideality
        #   does not apply.
        #
        # * An overlapping envelope on a REGULAR grid keeps the rigid averagine
        #   pattern, so a flexing tail cannot claim a neighbour's peak -- and it does
        #   so whether or not it carries a stored shape. A stored REGULAR shape is
        #   deliberately NOT reused in an overlap group: if the envelope was fit
        #   ISOLATED earlier it stored a soft-modelled (data-bent) shape, and reusing
        #   that bent shape here lets it over-claim the shared signal, so the fit
        #   depends on the ORDER in which peaks were converted (converting a new
        #   neighbour later gives it less area than converting the whole group at
        #   once). Re-deriving the rigid averagine makes a previously-converted
        #   regular envelope behave exactly like a fresh seed, so "convert to
        #   envelopes" is order-independent. (Idempotency is preserved: find-peaks
        #   stores the rigid averagine for overlapping envelopes, so reuse vs.
        #   re-derive coincide there -- only the isolated-then-overlapped case moves.)
        if K == 1 and (storedShape is None or _is_regular_isotope_grid(storedShape)):
            shaped = _soft_isotope_model(isotopes, x, y, fwhm, nonIdeality=nonIdeality)
            shapes[k] = shaped
        elif storedShape is not None and not _is_regular_isotope_grid(storedShape):
            shaped = storedShape
            shapes[k] = shaped
        else:
            shaped = isotopes

        # area-normalised column (unit coefficient integrates to one) for the
        # per-envelope amplitude fit, and the same column scaled so its most
        # abundant (apex) isotope is 1 for the abundance-independent signal split.
        # Normalising to the theoretical APEX -- not the monoisotopic peak -- is
        # what makes the split fair for heavy envelopes whose apex is +2/+4/+5:
        # comparing two overlapping species at their representative (tallest)
        # peak, rather than at a mono that may be a tiny sliver of a heavy
        # pattern, no longer flattens a genuine abundance difference between them.
        # The apex weight is a fixed per-envelope scalar from the pattern, so it
        # stays stable in crowded regions (it does not depend on the neighbours).
        areaColumn = _envelope_gaussian_column(x, shaped, sigma)
        wApex = max((float(w) for _mz, w in shaped), default=0.0)
        if wApex <= 0.0:
            wApex = 1.0
        norm = sigma * math.sqrt(2.0 * math.pi)
        areaColumns.append(areaColumn)
        apexColumns.append(areaColumn * (norm / wApex))
        # the fitted shape + width, so the apportionment can cap each amplitude
        # against this envelope's own apportioned share at its isotope apexes
        capInfo.append((shaped, fwhm))

    areas = _apportion_group_areas(areaColumns, apexColumns, x, y, capInfo=capInfo)
    return areas, shapes


# ----


def _fit_envelope_areas_shaped(
    clusters, signal, defaultFwhm, nonIdeality=None,
    averagineType=DEFAULT_AVERAGINE,
):
    """Joint envelope area fit, also returning the isotope shape used per cluster.

    Overlapping envelopes are fit together (globally apportioning the shared
    signal); non-overlapping ones are fit independently for speed. Without a
    profile each area is estimated from the envelope's own peak heights.

    Returns (areas, shapes) where shapes[k] is the per-isotope (mz, weight)
    model the fit used for cluster k (weights summing to 1), so callers can
    store and draw exactly the envelope the area was fitted to.
    """

    # fallback when profile is not available
    if signal is None or len(signal) == 0:
        # Without a profile we cannot run the joint NNLS, so each envelope's
        # area is estimated independently from its current peak heights. We do
        # NOT reuse a stored "area" here: that froze the value and meant editing
        # or adding/removing a neighbouring peak never recalculated nearby
        # envelopes (e.g. when working on a chromatogram slice or any derived
        # spectrum that carries no profile). Recomputing from the live peaks is
        # responsive to edits and still deterministic, so re-running stays
        # idempotent.
        areas = []
        shapes = []
        for cluster in clusters:
            fwhm = _cluster_fwhm(cluster, defaultFwhm)
            sigma = _fwhm_to_sigma(fwhm)
            scale = sigma * math.sqrt(2.0 * math.pi)

            # Find the most intense peak to securely anchor the area prediction
            best_idx = 0
            best_int = 0.0
            for i, p in enumerate(cluster):
                if p.intensity > best_int:
                    best_int = p.intensity
                    best_idx = i

            weights = _cluster_weights(cluster, averagineType=averagineType)
            w = weights[best_idx] if best_idx < len(weights) and weights[best_idx] > 0 else 1.0
            areas.append(max(0.0, best_int / w) * scale)
            # no profile to reshape against: the shape is the theoretical pattern
            shapes.append([(p.mz, wt) for p, wt in zip(cluster, weights, strict=True)])
        return areas, shapes

    xFull = signal[:, 0].astype(float)
    yFull = signal[:, 1].astype(float)
    if len(xFull) == 0:
        return [0.0] * len(clusters), [[] for _ in clusters]

    # per-cluster geometry and m/z span (padded for the Gaussian wings)
    metas = []
    intervals = []
    for cluster in clusters:
        fwhm = _cluster_fwhm(cluster, defaultFwhm)
        sigma = _fwhm_to_sigma(fwhm)
        weights = _cluster_weights(cluster, averagineType=averagineType)
        isotopes = [(p.mz, w) for p, w in zip(cluster, weights, strict=True)]

        # the exact fitted shape carried over from a stored envelope (only when
        # every peak has one, i.e. this cluster was rebuilt from an envelope). It
        # lets an overlap fit reproduce the picked area instead of re-deriving a
        # shape that differs for merged/irregular isotope grids.
        storedW = [p.attributes.get("_envweight") for p in cluster]
        storedShape = None
        if all(w is not None for w in storedW):
            tot = sum(max(0.0, float(w)) for w in storedW)
            if tot > 0.0:
                storedShape = [
                    (p.mz, max(0.0, float(w)) / tot)
                    for p, w in zip(cluster, storedW, strict=True)
                ]
        metas.append((fwhm, sigma, isotopes, storedShape))

        mzs = [p.mz for p in cluster]
        pad = 6.0 * max(fwhm, defaultFwhm)
        intervals.append((min(mzs) - pad, max(mzs) + pad))

    areas = [0.0] * len(clusters)
    shapes = [list(meta[2]) for meta in metas]

    # fit each connected overlap group on its own local signal window
    for group in _overlap_groups(intervals):
        lo = min(intervals[i][0] for i in group)
        hi = max(intervals[i][1] for i in group)
        mask = (xFull >= lo) & (xFull <= hi)
        x = xFull[mask]
        if len(x) == 0:
            continue
        # copy so the zero-floor never mutates the caller's spectrum
        y = yFull[mask].copy()
        y[y < 0.0] = 0.0

        groupMetas = [metas[i] for i in group]
        groupAreas, groupShapes = _fit_group_areas(groupMetas, x, y, nonIdeality)
        for idx, area, shape in zip(group, groupAreas, groupShapes, strict=True):
            areas[idx] = area
            shapes[idx] = shape

    return areas, shapes


def _fit_envelope_areas(
    clusters, signal, defaultFwhm, nonIdeality=None,
    averagineType=DEFAULT_AVERAGINE,
):
    """Joint envelope area fit. See `_fit_envelope_areas_shaped` for details."""

    areas, _shapes = _fit_envelope_areas_shaped(
        clusters, signal, defaultFwhm, nonIdeality=nonIdeality,
        averagineType=averagineType,
    )
    return areas


# ----


def _reconstruct_cluster_from_envelope(parent, envelope, averagineType=DEFAULT_AVERAGINE):
    """Rebuild a peak's cluster from its stored envelope metadata.

    When envelopes are collapsed to a single representative (the "1st" label)
    the individual isotope peaks are discarded. Re-running detection would then
    re-derive the cluster from the theoretical grid and the fitted area would
    drift slightly, so the peak-picking and "Convert to Envelopes" routes give
    inconsistent values. Rebuilding the exact isotope positions from the stored
    envelope makes re-running idempotent. The area is still re-fit against the
    profile afterwards (jointly over all clusters), so editing peaks and
    recalculating a neighbourhood keeps working as before.

    `averagineType` is the model the current run is using. When it matches the
    model the stored envelope was fit under, the exact fitted weights are carried
    over (`_envweight`) so re-converting reproduces the picked shape and area.
    When the user has switched models the stored weights are dropped instead:
    only the isotope POSITIONS (charge/spacing grid) are kept and the fit
    re-derives the intensity pattern from the new averagine, so a different model
    yields the different area it should. A legacy envelope carrying no model tag
    is treated as the default so the common protein case stays idempotent.
    """

    isotopes = envelope.get("isotopes") or []
    fwhm = envelope.get("fwhm") or parent.fwhm
    storedAveragine = envelope.get("averagineType", DEFAULT_AVERAGINE)
    reuseWeights = storedAveragine == averagineType

    # true isotope spacing, so the isotope index of each stored position reflects
    # its m/z (not its list order). A stored shape can hold irregular or repeated
    # positions -- e.g. one merged from two overlapping envelopes -- for which the
    # list index would be wrong; the m/z-derived index keeps `_cluster_weights`
    # consistent with what peak-picking used.
    monoMz = float(isotopes[0][0]) if isotopes else parent.mz
    spacing = ISOTOPE_DISTANCE / abs(parent.charge) if parent.charge else ISOTOPE_DISTANCE

    cluster = []
    for i, iso in enumerate(isotopes):
        peak = copy.deepcopy(parent)
        peak.setmz(float(iso[0]))
        # the monoisotopic peak keeps the representative's real intensity; the
        # remaining positions are placeholders (intensity 0) because the area is
        # re-fit from the profile, not from these intensities
        if i != 0:
            peak.setai(peak.base)
        if fwhm:
            peak.setfwhm(fwhm)
        peak.setcharge(parent.charge)
        if spacing > 0.0:
            peak.setisotope(int(round((float(iso[0]) - monoMz) / spacing)))
        else:
            peak.setisotope(i)
        # remember the exact fitted weight. For OVERLAPPING (K>1) clusters the fit
        # reuses it so re-fitting reproduces the stored shape (and area) that
        # peak-picking produced -- irregular/merged shapes cannot be re-derived
        # from positions alone. Isolated (K==1) envelopes ignore it and re-soften
        # from the theoretical pattern, so a changed algorithm still re-derives.
        # Dropped entirely when the averagine model has changed, so the fit
        # rebuilds the pattern (and area) from the newly selected model.
        if reuseWeights:
            peak.attributes["_envweight"] = float(iso[1])
        cluster.append(peak)

    return cluster


def relabelenvelopes(
    peaklist,
    label="1st",
    intensity="maximum",
    mzTolerance=0.15,
    isotopeShift=0.0,
    signal=None,
    defaultFwhm=0.1,
    nonIdeality=None,
    relaxed=False,
    averagineType=DEFAULT_AVERAGINE,
    preserveSeeds=False,
):
    """Convert deisotoped peak clusters to envelope labels.

    preserveSeeds (bool) - when True every input peak is kept as its own envelope
        seed: peaks are never absorbed into one another, adjacent clusters are not
        merged, and zero-area clusters are not pruned. Each seed's area is still
        obtained from the single joint overlap-aware fit, so overlapping seeds
        share the observed signal correctly ("many isotopes under one curve")
        while none of the explicitly chosen peaks can vanish. Used by the
        "convert to envelopes" action on an explicit selection.
    """

    # check peaklist
    if not isinstance(peaklist, obj_peaklist.peaklist):
        raise TypeError("Peak list must be mspy.peaklist object!")

    if not peaklist:
        return obj_peaklist.peaklist([])

    result = obj_peaklist.peaklist([])
    used = set()
    clusters = []

    for x, parent in enumerate(peaklist):

        CHECK_FORCE_QUIT()

        if parent.charge is None or (parent.isotope is not None and parent.isotope != 0):
            continue
        # Also skip if it strictly fits inside an existing cluster and is not an overlap.
        # NNLS will handle it if we spawn too many, but let's just use `x in used` normally, except wait.
        if (not relaxed) and x in used:
            continue

        # If this peak already carries a detected envelope (e.g. re-running
        # detection on already-converted peaks, or converting the output of
        # find-peaks), rebuild its cluster exactly from the stored isotope
        # positions so the result is idempotent -- this is what keeps the
        # peak-picking and "Convert to Envelopes" routes giving the same areas.
        # The rebuild only deep-copies the parent onto the stored grid; it never
        # consumes another peaklist peak, so it is safe under preserveSeeds (each
        # selected peak still rebuilds its OWN envelope and none is absorbed).
        # The area is re-fit below like every other cluster.
        storedEnvelope = (
            parent.attributes.get("envelope")
            if hasattr(parent, "attributes")
            else None
        )
        if isinstance(storedEnvelope, dict) and storedEnvelope.get("isotopes"):
            storedIsos = storedEnvelope["isotopes"]
            # A merged / irregular stored grid -- two overlapping species fused into
            # one representative by find-peaks, with duplicated isotope positions --
            # must only be reused for an ISOLATED envelope. Once a NEIGHBOUR seed is
            # present (e.g. find-peaks found the first species merged, then the user
            # labelled the second and is converting it) the merge is stale: reusing
            # it lets this envelope keep the neighbour's isotopes, so its area
            # balloons and the neighbour is crushed (example_env4_failes.msd: 900.49
            # kept a 10-isotope grid -> area 82, and 902.51 collapsed to 22 instead
            # of the correct 61 / 70). An irregular shape must not survive inside a
            # neighbourhood -- rebuild it as a clean single-species seed so the joint
            # fit re-apportions the shared signal. A regular grid is always safe to
            # reuse (its positions are clean); only an irregular one is dropped, and
            # only when a neighbouring seed actually overlaps its span (so the K==1
            # merged-representative case that has no neighbour is still reproduced).
            reuseStored = True
            if not _is_regular_isotope_grid(storedIsos):
                gridMzs = [float(m) for m, _w in storedIsos]
                gridLo, gridHi = min(gridMzs), max(gridMzs)
                # index by position -- do NOT iterate `peaklist` here: obj_peaklist's
                # iterator keeps a single shared cursor, so a nested `for ... in
                # peaklist` would reset the outer seed loop's cursor and drop every
                # seed after this one.
                for j in range(len(peaklist)):
                    if j == x:
                        continue
                    other = peaklist[j]
                    if other.charge is None or other.isotope not in (None, 0):
                        continue
                    # a seed past the mono but inside the merged span is a species
                    # this grid absorbed -> the merge must be undone
                    if gridLo + mzTolerance < other.mz <= gridHi + mzTolerance:
                        reuseStored = False
                        break
            if reuseStored:
                used.add(x)
                clusters.append(
                    _reconstruct_cluster_from_envelope(
                        parent, storedEnvelope, averagineType=averagineType
                    )
                )
                continue

        cluster = [copy.deepcopy(parent)]
        indexes = [x]
        next_isotope = 1
        difference = (ISOTOPE_DISTANCE + isotopeShift) / abs(parent.charge)
        # Isotope spacing shrinks as 1/charge, so the m/z matching window must
        # shrink the same way (half for 2+, a third for 3+ ...). Using a fixed
        # absolute window would, at high charge, be a large fraction of the
        # spacing and could match a neighbouring isotope or a foreign peak.
        chargeTol = mzTolerance / abs(parent.charge)
        # In preserveSeeds mode we never absorb the following peaks: each selected
        # seed stays on its own so no chosen peak is swallowed by a neighbour. The
        # envelope tail below is still grown from the profile, and the joint fit
        # apportions the shared signal between overlapping seeds.
        while not preserveSeeds:
            found = None
            found_isotope = None
            best_error = None
            best_pattern_error = None
            dynamicTol = _adaptive_mz_tolerance(chargeTol, cluster)

            # Strictly forbid gaps; envelopes must be a continuous series.
            for isotope in [next_isotope]:
                expected = parent.mz + isotope * difference

                for y in range(indexes[-1] + 1, len(peaklist)):
                    peak = peaklist[y]
                    if peak.mz > expected + dynamicTol:
                        break
                    if peak.charge != parent.charge:
                        continue

                    # Respect deisotoping assignments when available.
                    if peak.isotope is not None and peak.isotope != isotope:
                        continue

                    error = abs(peak.mz - expected)
                    if error > dynamicTol:
                        continue

                    trial_cluster = cluster + [copy.deepcopy(peak)]
                    pattern_error = _cluster_pattern_error(
                        parent,
                        trial_cluster,
                        isotopeShift,
                        relaxed=relaxed,
                        averagineType=averagineType,
                    )
                    if pattern_error is None:
                        if relaxed:
                            pattern_error = 999.0
                        else:
                            continue

                    if (
                        best_pattern_error is None
                        or pattern_error < best_pattern_error
                        or (
                            pattern_error == best_pattern_error
                            and (best_error is None or error < best_error)
                        )
                    ):
                        found = y
                        found_isotope = isotope
                        best_error = error
                        best_pattern_error = pattern_error

            if found is None:
                break
            if found_isotope is None:
                break

            cluster.append(copy.deepcopy(peaklist[found]))
            indexes.append(found)
            next_isotope = found_isotope + 1

        # Decide how far to extend the modeled envelope tail.
        #
        # The extent is bounded by the *observed* signal, so we never model
        # isotope peaks where the spectrum is flat. Starting just past the
        # detected isotopes we walk outward and keep a position only while
        #   (a) theory still predicts a non-negligible isotope there, and
        #   (b) the measured profile there rises above the local noise floor.
        # The first position that fails stops the tail (isotope envelopes decay
        # monotonically, so there are no gaps to jump).
        #
        # The noise floor is an *absolute* estimate (a peak's intensity / its
        # S/N gives the local noise level), and the test compares observed
        # signal against it. It therefore does not depend on which isotope is
        # the base peak -- it behaves the same whether the monoisotopic peak
        # dominates (small molecules) or a mid-envelope isotope dominates
        # (proteins), and it cannot fabricate peaks in empty m/z regions.
        ideal_pattern = _cluster_pattern(parent, 30, averagineType=averagineType)
        max_p = max(ideal_pattern) if ideal_pattern else 1.0
        theoryFloor = max_p * ENVELOPE_TAIL_CUTOFF_MIN

        # index of the theoretical envelope apex. Above ~2 kDa the monoisotopic
        # peak is no longer the tallest: the envelope climbs to a mid-envelope
        # apex before it decays. The decay guard below must therefore only apply
        # *past* this apex; before it, a rising tail is legitimate.
        apexIndex = int(numpy.argmax(ideal_pattern)) if len(ideal_pattern) else 0

        # Absolute noise estimate. Prefer the most intense peak's measured S/N;
        # if that is unavailable, estimate the local noise floor directly from
        # the profile (median of the surrounding baseline). This guarantees the
        # signal floor below is always active when a profile exists -- otherwise
        # the code would fall through to a theory-only cutoff with no signal
        # check and could place a trailing isotope on flat spectrum.
        basePeak = max(cluster, key=lambda p: p.intensity) if cluster else parent
        noise = 0.0
        if (
            basePeak is not None
            and basePeak.sn
            and basePeak.sn > 0.0
            and basePeak.intensity > 0.0
        ):
            noise = basePeak.intensity / float(basePeak.sn)
        elif signal is not None and len(signal) > 0:
            sigAll = numpy.asarray(signal, dtype=float)
            lo = parent.mz - 3.0
            hi = parent.mz + len(ideal_pattern) * difference + 3.0
            localMask = (sigAll[:, 0] >= lo) & (sigAll[:, 0] <= hi)
            localY = sigAll[localMask, 1]
            if len(localY) > 0:
                noise = float(numpy.median(localY))

        # Best-fit rigid offset of the modelled isotope grid to the detected
        # peaks. The tail placeholders (and the positions sampled below) then
        # follow the *measured* isotope progression instead of a grid pinned
        # rigidly to the parent, so they line up with the real signal. The
        # offset is intensity-weighted (dominated by the best-measured peaks)
        # and clamped to the mass tolerance, while the spacing itself is left
        # unchanged. A constant spacing plus a tolerance-bounded shift means the
        # isotopes keep their relative distances and can never drift onto -- or
        # swap with -- a neighbouring envelope's peaks.
        gridOffset = 0.0
        offsetWeight = 0.0
        for k, p in enumerate(cluster):
            if p.intensity > 0.0:
                gridOffset += p.intensity * (p.mz - (parent.mz + k * difference))
                offsetWeight += p.intensity
        if offsetWeight > 0.0:
            gridOffset = max(
                -chargeTol, min(chargeTol, gridOffset / offsetWeight)
            )

        useSignal = signal is not None and len(signal) > 0 and noise > 0.0
        sigX = sigY = numpy.empty(0)
        # The tail's "is there a real isotope here?" test is gated by the *mass
        # tolerance*, not the peak width. A genuine continuation isotope of this
        # envelope has its apex within the (charge-scaled) tolerance of the
        # predicted grid position; a neighbouring species sits on its own grid
        # at a consistently offset m/z, so its peaks fall outside this window and
        # cannot be absorbed -- no matter how intense they are. This is the same
        # tolerance the detected-isotope matching loop and the cluster merge use,
        # so the tail honours `mzTolerance` consistently with the rest of the
        # pipeline. (Previously the window was scaled to the peak width and so
        # ignored the tolerance entirely: tightening mzTolerance did nothing and
        # strong off-grid peaks still extended the envelope.)
        sampleWindow = _adaptive_mz_tolerance(chargeTol, cluster)
        signalFloor = ENVELOPE_TAIL_SN_LIMIT * noise
        if useSignal:
            sigArr = numpy.asarray(signal, dtype=float)
            sigX = sigArr[:, 0]
            sigY = sigArr[:, 1]

        target_length = len(cluster)
        prevObs = float(cluster[-1].intensity) if cluster else 0.0
        for mi in range(len(cluster), len(ideal_pattern)):

            # stop where theory no longer predicts a meaningful isotope
            if ideal_pattern[mi] < theoryFloor:
                break

            if useSignal:
                mzPos = parent.mz + mi * difference + gridOffset

                # observed signal at this position, sampled only within the
                # mass tolerance so off-grid foreign peaks are never counted
                i1 = numpy.searchsorted(sigX, mzPos - sampleWindow, side="left")
                i2 = numpy.searchsorted(sigX, mzPos + sampleWindow, side="right")
                obs = float(numpy.max(sigY[i1:i2])) if i1 < i2 else 0.0

                # stop where the spectrum is flat (no signal above the noise)
                if obs < signalFloor:
                    break

                # Past the apex a genuine envelope decays continuously. Two ways
                # the observed signal can betray that this position is *not* a
                # real isotope of this envelope:
                #   - it rises sharply  -> we have stepped onto a neighbouring
                #     species (before the apex a rise is legitimate, so this is
                #     only checked past it);
                #   - it collapses to a small fraction of the previous isotope
                #     -> the real envelope has ended and what remains is baseline
                #     noise, so the trailing peak must not be modelled.
                if mi > apexIndex:
                    if obs > prevObs * ENVELOPE_TAIL_RISE_TOLERANCE:
                        break
                    if obs < prevObs * ENVELOPE_TAIL_MIN_DECAY:
                        break
                prevObs = obs
            else:
                # no profile to verify against: fall back to a conservative
                # relative cutoff so the tail cannot run away into empty m/z
                if ideal_pattern[mi] < max_p * ENVELOPE_TAIL_CUTOFF_MAX:
                    break

            target_length = mi + 1

        # Enforce the minimum envelope length first; the anti-hallucination /
        # decay guards above act only as an *upper* bound and must never shorten
        # an envelope below this floor. A genuine deisotoped envelope spans at
        # least three isotopes, so we keep that minimum even where the third
        # isotope sits just under the noise. The placeholder is added at the
        # theoretical isotope position (intensity 0), so it cannot absorb a
        # neighbouring peak.
        target_length = max(target_length, min(MIN_ENVELOPE_LENGTH, len(ideal_pattern)))

        if len(cluster) < target_length:
            for mi in range(len(cluster), target_length):
                gridMz = parent.mz + mi * difference + gridOffset
                # Snap the placeholder onto the real peak at the expected
                # spacing (within the mass tolerance) so a modeled tail isotope
                # locks onto the genuine peak instead of floating at the bare
                # grid point between two close peaks. Proximity to the expected
                # position decides, so it cannot jump to a taller neighbour, and
                # the tolerance bound stops it drifting onto another envelope. A
                # forced placeholder on flat noise finds no apex and stays put.
                if useSignal:
                    mzPos = _snap_to_local_apex(
                        sigX, sigY, gridMz, sampleWindow, floor=signalFloor
                    )
                else:
                    mzPos = gridMz
                dummy = copy.deepcopy(parent)
                dummy.mz = mzPos
                dummy.intensity = 0.0
                dummy.charge = parent.charge
                dummy.isotope = mi
                cluster.append(dummy)

        used.update(indexes)
        clusters.append(cluster)

    if not clusters:
        return copy.deepcopy(peaklist)

    # preserveSeeds keeps every selected seed as its own envelope: adjacent
    # clusters are not fused together (that would make a chosen peak disappear
    # into a neighbour).
    if not preserveSeeds:
        clusters = _merge_adjacent_clusters(
            clusters,
            mzTolerance,
            isotopeShift,
            relaxed=relaxed,
            averagineType=averagineType,
        )

    if not clusters:
        return copy.deepcopy(peaklist)

    areas, shapes = _fit_envelope_areas_shaped(
        clusters,
        signal,
        defaultFwhm,
        nonIdeality=nonIdeality,
        averagineType=averagineType,
    )

    # Re-calculate NNLS areas as fallbacks if needed, but mainly prune zero ones.
    # preserveSeeds keeps all clusters even at (near) zero area: the joint fit may
    # apportion little signal to an overlapped seed, but the user selected it, so
    # it must survive as its own envelope rather than being pruned away.
    max_area = max([a for a in areas]) if areas else 0.0
    pruned_clusters = []
    pruned_areas = []
    pruned_shapes = []
    for c, cluster in enumerate(clusters):
        a = float(max(0.0, areas[c])) if c < len(areas) else 0.0
        if preserveSeeds or a > max_area * 1e-6 or len(clusters) == 1:
            pruned_clusters.append(cluster)
            pruned_areas.append(a)
            pruned_shapes.append(shapes[c] if c < len(shapes) else [])
    clusters = pruned_clusters
    areas = pruned_areas
    shapes = pruned_shapes

    for c, cluster in enumerate(clusters):
        parent = cluster[0]
        # Use the exact isotope shape the area fit used, so the stored/drawn
        # envelope matches the fitted area (in crowded regions the overlap-aware
        # fit deliberately keeps the shape tighter than a raw re-derivation would
        # -- re-deriving here from the raw signal would draw a different envelope
        # than the one whose area we report). Fall back to the theoretical model
        # only if the fit produced nothing usable.
        isotopes_data = shapes[c] if c < len(shapes) and shapes[c] else (
            _cluster_isotope_model(
                cluster,
                signal=signal,
                defaultFwhm=defaultFwhm,
                nonIdeality=nonIdeality,
                averagineType=averagineType,
            )
        )
        fwhm_val = float(_cluster_fwhm(cluster, defaultFwhm))

        # Normalise the isotope shape to a single-envelope distribution (weights
        # sum to 1) and rescale the area by that same sum. This is the ONE place
        # every fit path passes through, so it makes the reported area consistent
        # regardless of which path produced the shape: `_cluster_weights` returns
        # pattern[idx]/pattern_total (a clean 5-isotope run sums to ~0.86-0.99, a
        # merged/duplicated grid to ~N), and the various fallbacks (no-profile,
        # theoretical) don't renormalise. Without this, "find peaks" and "convert
        # to envelopes" could report different areas for the same envelope. The
        # rescale keeps area*weight (the drawn envelope) and sumint invariant, so
        # only the bare `area` number is put on a common scale.
        area_val = float(areas[c])
        shapeSum = math.fsum(float(w) for _, w in isotopes_data)
        if shapeSum > 0.0:
            isotopes_data = [(mz, float(w) / shapeSum) for mz, w in isotopes_data]
            area_val *= shapeSum

        # summed envelope intensity: the sum of the intensities (heights) of the
        # isotope peaks that make up this envelope. It is derived from the same
        # fitted model as the envelope area so the two always recalculate
        # together: area is the integrated NNLS amplitude (sum of gaussian
        # areas), and for gaussian peaks of a given width the height equals
        # area / (sigma * sqrt(2*pi)). Summing over the modeled isotopes gives
        #   sumint = area / (sigma * sqrt(2*pi)) * sum(isotope weights)
        # which stays consistent with the area whenever envelopes are re-fit
        # (e.g. after nearby peaks change) and does not depend on the live peak
        # rows, so it is robust to envelopes being collapsed to a single peak.
        sigma = _fwhm_to_sigma(fwhm_val)
        norm = sigma * math.sqrt(2.0 * math.pi)
        weightSum = sum(float(w) for _, w in isotopes_data)
        sumint = (area_val / norm) * weightSum if norm > 0.0 else 0.0

        envelope = {
            "area": area_val,
            "sumint": sumint,
            "fwhm": fwhm_val,
            "shape": "gaussian",
            "isotopes": isotopes_data,
            # the averagine model the shape/area were fit under, so re-converting
            # can tell whether the stored shape may be reused verbatim (same model
            # -> idempotent) or must be re-derived (user switched models -> the
            # isotope pattern, and hence the apportioned area, genuinely changes).
            "averagineType": averagineType,
        }

        peaks = labelenvelope(
            cluster,
            charge=parent.charge,
            label=label,
            intensity=intensity,
            averagineType=averagineType,
        )

        # carry a user FWHM lock onto the (freshly built) representative peak, so
        # the manual width survives the re-fit and is not re-measured next time
        fwhmLocked = bool(getattr(parent, "attributes", {}).get("_fwhmLocked"))

        groupname = result.groupname()
        if label == "isotopes":
            for isotope, peak in enumerate(peaks):
                peak.setcharge(parent.charge)
                peak.setisotope(isotope)
                peak.setfwhm(fwhm_val)
                peak.setgroup(groupname)
                peak.attributes["envelope"] = envelope
                if fwhmLocked:
                    peak.attributes["_fwhmLocked"] = True
                result.append(peak)
        else:
            for peak in peaks:
                peak.setcharge(parent.charge)
                peak.setisotope(0)
                peak.setfwhm(fwhm_val)
                peak.setgroup(groupname)
                peak.attributes["envelope"] = envelope
                if fwhmLocked:
                    peak.attributes["_fwhmLocked"] = True
                result.append(peak)

    for x, peak in enumerate(peaklist):
        if x in used:
            continue
        peak = copy.deepcopy(peak)
        peak.setgroup("")
        result.append(peak)

    return result


# ----


def _isotope_pattern_at_mass(neutralMass, averagineType=DEFAULT_AVERAGINE, size=12):
    """Apex-normalized isotope pattern for a neutral mass and averagine type.

    Protein uses the precomputed real-averagine lookup table (unchanged); the
    other types use the Poisson +1 approximation scaled by their carbon density
    (see AVERAGINE_MODELS). Only ratios between adjacent isotopes are used by the
    caller, so the apex normalization here matches the lookup table convention.
    """

    if averagineType == DEFAULT_AVERAGINE:
        idx = int(min(15000, int(max(0.0, neutralMass))) / 200)
        return patternLookupTable[idx]

    lam = max(0.0, neutralMass * _averagine_lambda(averagineType))
    pattern = []
    p = math.exp(-lam) if lam < 700 else 0.0
    for i in range(size):
        if i == 0:
            pattern.append(p)
        else:
            p = p * (lam / i)
            pattern.append(p)

    apex = max(pattern) if pattern else 0.0
    if apex <= 0.0:
        return [1.0] + [0.0] * (size - 1)
    return [x / apex for x in pattern]


# ----


def deisotope(
    peaklist,
    maxCharge=1,
    mzTolerance=0.15,
    intTolerance=0.5,
    isotopeShift=0.0,
    respectCharge=False,
    seedCharge=1,
    averagineType=DEFAULT_AVERAGINE,
):
    """Isotopes determination and calculation of peaks charge.
    peaklist (mspy.peaklist) - peaklist to process
    maxCharge (float) - max charge to be searched
    mzTolerance (float) - absolute m/z tolerance for isotopes distance
    intTolerance (float) - relative intensity tolerance for isotopes and model (in %/100)
    isotopeShift (float) - isotope distance correction (neutral mass) (for HDX etc.)
    averagineType (str) - averagine model key (protein | carbohydrate | lipid)
    """

    # check peaklist
    if not isinstance(peaklist, obj_peaklist.peaklist):
        raise TypeError("Peak list must be mspy.peaklist object!")

    # clear previous results unless caller wants to preserve / respect charge
    if not respectCharge:
        for peak in peaklist:
            peak.setcharge(None)
            peak.setisotope(None)

    # get charges
    if maxCharge < 0:
        charges = [-x for x in range(1, abs(maxCharge) + 1)]
    else:
        charges = [x for x in range(1, maxCharge + 1)]
    charges.reverse()

    # walk in a peaklist
    maxIndex = len(peaklist)
    for x, parent in enumerate(peaklist):

        CHECK_FORCE_QUIT()

        # skip assigned peaks
        if parent.isotope is not None:
            continue

        # try all charge states or the caller-provided charge seed
        if respectCharge:
            if parent.charge is None:
                candidateCharges = [seedCharge]
            else:
                candidateCharges = [parent.charge]
        else:
            candidateCharges = charges

        for z in candidateCharges:
            cluster = [parent]

            # search for next isotope within m/z tolerance
            difference = (ISOTOPE_DISTANCE + isotopeShift) / abs(z)
            y = 1
            while x + y < maxIndex:
                mzError = peaklist[x + y].mz - cluster[-1].mz - difference
                if abs(mzError) <= mzTolerance:
                    cluster.append(peaklist[x + y])
                elif mzError > mzTolerance:
                    break
                y += 1

            # no isotope found
            if len(cluster) == 1:
                continue

            # get theoretical isotopic pattern
            neutralMass = _mass_scalar(mod_basics.mz(parent.mz, 0, z))
            pattern = _isotope_pattern_at_mass(neutralMass, averagineType)

            # check minimal number of isotopes in the cluster
            limit = 0
            for p in pattern:
                if p >= 0.33:
                    limit += 1
            if len(cluster) < limit and abs(z) > 1:
                continue

            # check peak intensities in cluster
            valid = True
            isotope = 1
            limit = min(len(pattern), len(cluster))
            while isotope < limit:

                # calc theoretical intensity from previous peak and current error
                intTheoretical = (
                    cluster[isotope - 1].intensity / pattern[isotope - 1]
                ) * pattern[isotope]
                intError = cluster[isotope].intensity - intTheoretical

                # intensity in tolerance
                if abs(intError) <= (intTheoretical * intTolerance):
                    cluster[isotope].setisotope(isotope)
                    cluster[isotope].setcharge(z)

                # intensity is higher (overlap)
                elif intError > 0:
                    pass

                # intensity is lower and first isotope is checked (nonsense)
                elif intError < 0 and isotope == 1:
                    valid = False
                    break

                # try next peak
                isotope += 1

            # cluster is OK, set parent peak and skip other charges
            if valid:
                parent.setisotope(0)
                parent.setcharge(z)
                break

        if respectCharge and parent.charge is None:
            parent.setcharge(seedCharge)

# ----


def _fwhm_is_locked(peak):
    """True if the user has pinned this peak's FWHM in the editor.

    A locked FWHM (``attributes["_fwhmLocked"]``) is a deliberate manual override:
    it must survive re-measurement (so a subsequent "Convert to Envelopes" or auto
    recalc does not silently revert it to the value measured from the profile), yet
    stay editable -- clearing the lock lets the width be re-measured again.
    """

    if not hasattr(peak, "attributes"):
        return False
    return bool(peak.attributes.get("_fwhmLocked")) and bool(peak.fwhm) and peak.fwhm > 0.0


def _sync_stored_envelope_fwhm(peak):
    """Make a peak's stored envelope width follow the peak's own FWHM.

    The refit rebuilds the envelope from the stored ``envelope["fwhm"]``, so when a
    width must be respected (a locked peak, or the peak the user is directly
    editing) its stored envelope width is synced to the live FWHM first.
    """

    if not hasattr(peak, "attributes"):
        return
    stored = peak.attributes.get("envelope")
    if isinstance(stored, dict) and stored.get("fwhm") and peak.fwhm and peak.fwhm > 0.0:
        stored["fwhm"] = peak.fwhm


def _refresh_missing_fwhm_from_profile(peaklist, profile, recompute=False, respectAll=False):
    """Refresh FWHM values from the profile signal at each peak m/z.

    By default only peaks with a missing/zero FWHM are filled in. With
    ``recompute=True`` EVERY peak's FWHM is re-measured from the profile,
    overwriting any stale value -- needed when the FWHM algorithm has changed and
    the caller wants freshly measured widths (e.g. "Convert to Envelopes"). Peaks
    that carry stored envelope metadata (rebuilt via
    _reconstruct_cluster_from_envelope, which prefers the stored FWHM) also get
    that stored value refreshed, so the freshly measured width is the one
    actually used. An existing value is only replaced by a valid new measurement,
    so a failed re-measurement never wipes a usable FWHM.

    A FWHM the user has LOCKED in the editor is never re-measured; instead its
    stored envelope width is synced to the locked value, so the area refit uses the
    manual width. ``respectAll=True`` extends that to EVERY peak with a usable
    FWHM (regardless of lock) -- used for the pass that directly applies a manual
    FWHM edit, where the typed width must take effect this time even if the peak is
    not locked. Unlocking (and a normal ``respectAll=False`` recompute) restores
    re-measurement.
    """

    if profile is None or len(profile) == 0:
        return

    for peak in peaklist:
        respect = _fwhm_is_locked(peak) or (
            respectAll and bool(peak.fwhm) and peak.fwhm > 0.0
        )
        if respect:
            # keep this width and make the stored envelope follow it, so the refit
            # (which rebuilds from the stored FWHM) uses the respected value
            _sync_stored_envelope_fwhm(peak)
            continue

        if not recompute and peak.fwhm and peak.fwhm > 0.0:
            continue

        labeled = labelpoint(signal=profile, mz=peak.mz)
        if labeled and labeled.fwhm and labeled.fwhm > 0.0:
            peak.setfwhm(labeled.fwhm)
            if recompute and hasattr(peak, "attributes"):
                stored = peak.attributes.get("envelope")
                if isinstance(stored, dict) and stored.get("fwhm"):
                    stored["fwhm"] = labeled.fwhm


# ----


def _envelope_overlap_span(peak, isotopeShift, averagineType, pad):
    """(lo, hi) m/z span an envelope seeded at `peak` occupies, padded by `pad`.

    Uses the stored isotope positions when the peak already carries an envelope;
    otherwise estimates the reach of the averagine envelope a monoisotopic seed
    would grow (isotopes extend upward in m/z), so overlap with a neighbour can be
    judged before the envelope is actually built.
    """

    env = peak.attributes.get("envelope") if hasattr(peak, "attributes") else None
    isos = env.get("isotopes") if isinstance(env, dict) else None
    if isos:
        mzs = [float(mz) for mz, _w in isos]
        lo, hi = min(mzs), max(mzs)
    else:
        z = abs(int(peak.charge)) if peak.charge else 1
        spacing = (ISOTOPE_DISTANCE + isotopeShift) / z
        neutralMass = _mass_scalar(mod_basics.mz(peak.mz, 0, z))
        pattern = _isotope_pattern_at_mass(neutralMass, averagineType)
        # count isotopes carrying non-negligible signal, so the reach covers the
        # whole envelope tail that could overlap a neighbour
        n = sum(1 for p in pattern if p >= 0.02) or 1
        lo = peak.mz
        hi = peak.mz + (n - 1) * spacing
    return (lo - pad, hi + pad)


def _selection_overlap_indices(peaklist, seedIdx, isotopeShift, averagineType, pad):
    """Expand selected peak indices to their connected envelope-overlap component.

    Spec: overlapping envelopes are always refined together. When the user
    converts (or reconverts) a selection, any overlapping neighbour that is a real
    species -- transitively -- must be refit jointly and converted with it, so the
    shared signal is re-apportioned (otherwise the neighbour keeps a stale isolated
    area, or the selected peak is fit alone and over-claims the neighbour's signal).

    A neighbour counts as a real species -- and is pulled in -- when it is either:
    * an EXISTING envelope (already carries the ``envelope`` attribute), or
    * a DEISOTOPED SEED: a charged, monoisotopic peak. Such a peak is a latent
      envelope (it has a charge and therefore an isotope pattern), so a "Find peaks"
      result whose neighbours are still plain charged peaks -- not yet labelled as
      envelopes -- is joined and converted exactly like one whose neighbours were
      already enveloped. Without this, converting a peak added next to a find-peaks
      neighbour fit it alone and reported too large an area.

    A truly bare peak (no charge assigned) is NOT a committed species and is left
    untouched, so the selection is not widened into unassigned/noise peaks.

    Returns the expanded index set (always a superset of `seedIdx`).
    """

    seedIdx = set(seedIdx)
    # candidate nodes: the selected peaks plus every overlapping real species
    # (existing envelope or charged monoisotopic seed)
    nodes = list(seedIdx)
    for i, peak in enumerate(peaklist):
        if i in seedIdx:
            continue
        env = peak.attributes.get("envelope") if hasattr(peak, "attributes") else None
        isEnvelope = isinstance(env, dict)
        isChargedSeed = bool(getattr(peak, "charge", None)) and getattr(
            peak, "isotope", None
        ) in (None, 0)
        if isEnvelope or isChargedSeed:
            nodes.append(i)

    if len(nodes) == len(seedIdx):
        return seedIdx  # no other real species anywhere -- nothing to pull in

    spans = {
        i: _envelope_overlap_span(peaklist[i], isotopeShift, averagineType, pad)
        for i in nodes
    }
    order = sorted(nodes, key=lambda i: spans[i][0])

    # sweep the node spans into connected overlap components (transitive), then
    # keep every component that contains at least one selected peak
    result = set(seedIdx)
    current = []
    currentHi = None
    for i in order:
        lo, hi = spans[i]
        if current and currentHi is not None and lo <= currentHi:
            current.append(i)
            currentHi = max(currentHi, hi)
        else:
            if current and any(j in seedIdx for j in current):
                result.update(current)
            current = [i]
            currentHi = hi
    if current and any(j in seedIdx for j in current):
        result.update(current)
    return result


def _dedupe_local_group_names(labeled, reserved):
    """Remap freshly-labelled local group names off the ones already in use.

    ``relabelenvelopes`` (invoked on just the local subset by
    ``recalculate_neighborhood_envelopes`` below) restarts group names from "A"
    with no knowledge of the groups carried by the untouched peaks outside the
    neighbourhood. Left as-is, a per-selection "convert to envelopes" stamps
    A/B/C onto new envelopes even though those letters already label OTHER
    envelopes elsewhere in the list, so two unrelated envelopes end up sharing a
    group. Here each distinct incoming local group is renamed to the next group
    name not in ``reserved`` (nor already handed out), preserving the local
    grouping so every isotope of one envelope keeps a shared label. Peaks with no
    group (plain, un-enveloped peaks) are left untouched.

    When ``reserved`` is empty (the whole-list convert / peak-picking paths, where
    every peak is local) the mapping reproduces A/B/C in first-encounter order, so
    it is a no-op there and the order-independent full relabel is unchanged.
    """
    used = set(reserved)
    namer = obj_peaklist.peaklist([])

    def _fresh():
        size = 1
        while True:
            for name in namer._generateGroupNames(size):
                if name not in used:
                    return name
            size += 1

    mapping = {}
    for peak in labeled:
        g = getattr(peak, "group", "")
        if not g or g in mapping:
            continue
        newName = _fresh()
        used.add(newName)
        mapping[g] = newName

    if mapping:
        for peak in labeled:
            g = getattr(peak, "group", "")
            if g in mapping:
                peak.setgroup(mapping[g])
    return labeled


def recalculate_neighborhood_envelopes(
    peaklist, profile, mzs, params, selectedOnly=False, respectFwhm=False,
):
    """Re-run envelope detection on the m/z neighborhood around given peaks.

    Pure helper (no wx / no config dependency) extracted from the peaklist GUI
    panel so the neighborhood selection + deisotope + envelope-labeling logic
    can be unit tested directly. Returns a NEW mspy.peaklist: peaks outside the
    neighborhood are preserved unchanged, peaks inside it are re-deisotoped and
    re-labeled into envelopes. When there is nothing to do (no mzs, empty
    peaklist, or no peaks fall inside the neighborhood window) the original
    peaklist is returned unchanged (the same object), so callers can detect a
    no-op by identity.

    peaklist (mspy.peaklist) - current peak list
    profile (numpy array or None) - spectrum profile for area fitting and fwhm
    mzs (list of float) - m/z values of the edited / selected peaks
    params (dict) - processing parameters, keys:
        massTolerance, isotopeShift, maxCharge, intTolerance,
        labelEnvelope, envelopeIntensity, envelopeNonIdeality,
        seedCharge (optional, default 1),
        averagineType (optional, default "protein")
    selectedOnly (bool) - when True, operate strictly on the peaks matching the
        given m/z values (the explicit "convert to envelopes" action): no margin
        window is added and neighbouring peaks are neither re-deisotoped nor
        absorbed. The envelope tail is still reconstructed from the profile, so a
        single monoisotopic seed yields a full envelope while its neighbours stay
        in the list untouched. When False (default, the auto-recalc after a
        delete / charge edit), the surrounding neighbourhood is re-fit as a whole.
    respectFwhm (bool) - when True, no peak's FWHM is re-measured from the profile
        (every usable width is kept as-is); used for the pass that directly applies
        a manual FWHM edit, so the typed width takes effect this time even for an
        unlocked peak. When False (default) unlocked peaks are re-measured; locked
        peaks are always kept.
    """

    if not mzs:
        return peaklist
    if not isinstance(peaklist, obj_peaklist.peaklist) or not len(peaklist):
        return peaklist

    tolerance = params["massTolerance"]
    isotopeShift = params["isotopeShift"]
    maxCharge = max(1, abs(int(params["maxCharge"])))
    difference = (ISOTOPE_DISTANCE + isotopeShift) / float(maxCharge)
    averagineType = params.get("averagineType", DEFAULT_AVERAGINE)

    localPeaks = []
    outsidePeaks = []
    if selectedOnly:
        # Convert-to-envelopes: match each selected m/z to its own peak (nearest
        # within tolerance). Plain (non-envelope) neighbours are never touched, so
        # an explicit selection is never widened into new labels and nothing
        # silently vanishes from the list.
        localIdx = set()
        for target in mzs:
            best = None
            bestErr = tolerance
            for i, peak in enumerate(peaklist):
                if i in localIdx:
                    continue
                err = abs(peak.mz - target)
                if err <= bestErr:
                    best = i
                    bestErr = err
            if best is not None:
                localIdx.add(best)
        # ...but existing envelopes that OVERLAP the selection are pulled into the
        # joint fit (spec: overlapping envelopes are always refined together), so a
        # neighbour is re-apportioned and switches to the rigid overlap treatment
        # instead of keeping the isolated area/shape it was fit with when alone.
        localIdx = _selection_overlap_indices(
            peaklist, localIdx, isotopeShift, averagineType,
            pad=max(2.0 * tolerance, 0.5 * difference),
        )
        for i, peak in enumerate(peaklist):
            (localPeaks if i in localIdx else outsidePeaks).append(peak)
    else:
        # Isotope spacing shrinks as 1/charge, so the neighborhood must be wide
        # enough to capture a full envelope at the lowest charge (largest spacing).
        margin = max(6.0 * difference, 8.0 * tolerance)
        minMz = min(mzs) - margin
        maxMz = max(mzs) + margin
        for peak in peaklist:
            if minMz <= peak.mz <= maxMz:
                localPeaks.append(peak)
            else:
                outsidePeaks.append(peak)

    if not localPeaks:
        return peaklist

    hasProfile = profile is not None and len(profile) > 0

    def _label_local(group, preserveSeeds=False):
        """Deisotope + envelope-label one group of peaks, returning the result.

        With preserveSeeds every peak in the group becomes its own envelope seed
        (nothing is merged, absorbed or pruned away); their areas still come from
        the single joint overlap-aware fit.
        """
        gpl = obj_peaklist.peaklist(group)
        # Re-measure FWHM for every peak (not just missing ones): peaks carried
        # over from an earlier run may hold FWHM values from a superseded
        # algorithm, and "convert to envelopes" must reflect the current
        # measurement. `respectFwhm` (the pass that directly applies a manual FWHM
        # edit) keeps every usable width as-is instead, so the typed value takes
        # effect; a locked width is always kept regardless.
        _refresh_missing_fwhm_from_profile(
            gpl, profile, recompute=True, respectAll=respectFwhm
        )

        # Existing charges are respected; seedCharge is only a fallback for peaks
        # that carry no charge assignment yet.
        gpl.deisotope(
            maxCharge=params["maxCharge"],
            mzTolerance=tolerance,
            intTolerance=params["intTolerance"],
            isotopeShift=isotopeShift,
            respectCharge=True,
            seedCharge=int(params.get("seedCharge", 1)),
            averagineType=averagineType,
        )

        if preserveSeeds:
            # Deisotoping chains contiguous peaks (isotope 1, 2, ...); reset every
            # peak to a monoisotopic seed so each selected peak is labelled as its
            # own envelope instead of being folded into a neighbour.
            for p in gpl:
                p.setisotope(0)

        defaultFwhm = 0.1
        if gpl.basepeak and gpl.basepeak.fwhm:
            defaultFwhm = gpl.basepeak.fwhm

        gpl.labelenvelopes(
            label=params["labelEnvelope"],
            intensity=params["envelopeIntensity"],
            mzTolerance=tolerance,
            isotopeShift=isotopeShift,
            signal=profile if hasProfile else None,
            defaultFwhm=defaultFwhm,
            nonIdeality=params["envelopeNonIdeality"],
            relaxed=True,
            averagineType=averagineType,
            preserveSeeds=preserveSeeds,
        )
        return list(gpl)

    labeled = _label_local(localPeaks, preserveSeeds=selectedOnly)

    # _label_local relabels its local subset from group "A" with no knowledge of
    # the groups already carried by the untouched outside peaks; remap so a
    # per-selection convert doesn't reuse letters that already label other
    # envelopes in the list (a no-op when there are no reserved outside groups).
    reserved = {p.group for p in outsidePeaks if getattr(p, "group", "")}
    labeled = _dedupe_local_group_names(labeled, reserved)

    return obj_peaklist.peaklist(outsidePeaks + labeled)


# ----


def deconvolute(peaklist, massType=0):
    """Recalculate peaklist to singly charged.
    peaklist (mspy.peaklist) - peak list to deconvolute
    massType (0 or 1) - mass type used for m/z re-calculation, 0 = monoisotopic, 1 = average
    """

    # recalculate peaks
    buff = []
    for peak in copy.deepcopy(peaklist):

        CHECK_FORCE_QUIT()

        # uncharged peak
        if not peak.charge:
            continue

        # charge is correct
        elif abs(peak.charge) == 1:
            buff.append(peak)

        # recalculate peak
        else:

            # set fwhm
            if peak.fwhm:
                newFwhm = abs(peak.fwhm * peak.charge)
                peak.setfwhm(newFwhm)

            # set m/z and charge
            if peak.charge < 0:
                newMz = mod_basics.mz(
                    mass=peak.mz,
                    charge=-1,
                    currentCharge=peak.charge,
                    massType=massType,
                )
                peak.setmz(newMz)
                peak.setcharge(-1)
            else:
                newMz = mod_basics.mz(
                    mass=peak.mz, charge=1, currentCharge=peak.charge, massType=massType
                )
                peak.setmz(newMz)
                peak.setcharge(1)

            # store peak
            buff.append(peak)

    # remove baseline
    if buff:
        for peak in buff:
            peak.setsn(None)
            peak.setai(peak.intensity)
            peak.setbase(0.0)

    # update peaklist
    peaklist = obj_peaklist.peaklist(buff)

    return peaklist


# ----


# PATTERN LOOKUP TABLE
# --------------------


def averagine(mz, charge=0, composition=AVERAGE_AMINO):
    """Calculate average formula for given mass and building block composition.
    mz (float) - peak m/z
    charge (int) - peak charge
    composition (dict) - building block composition
    """

    # get average mass of block
    blockMass = 0.0
    for element in composition:
        blockMass += blocks.elements[element].mass[1] * composition[element]

    # get block count
    neutralMass = _mass_scalar(
        mod_basics.mz(mz, charge=0, currentCharge=charge, massType=1),
        massType=1,
    )
    count = max(1, neutralMass / blockMass)

    # make formula
    formula = ""
    for element in composition:
        formula += "%s%d" % (element, int(composition[element] * count))
    formula = obj_compound.compound(formula)

    # add some hydrogens to reach the mass
    formulaMass = _mass_scalar(formula.mass(1), massType=1)
    hydrogenMass = float(blocks.elements["H"].mass[1])
    hydrogens = int(round((neutralMass - formulaMass) / hydrogenMass))
    hydrogens = max(hydrogens, -1 * formula.count("H"))
    formula += "H%d" % hydrogens

    return formula


# ----


def _gentable(highmass, step=200, composition=AVERAGE_AMINO, table="tuple"):
    """Print pattern lookup table."""

    for mass in range(0, highmass, step):
        formula = averagine(mass, charge=0, composition=composition)

        pattern = ""
        for _mz, abundance in formula.pattern(fwhm=0.1, threshold=0.001):
            pattern += "%.3f, " % abundance

        if table == "tuple":
            print("(%s), #%d" % (pattern[:-2], mass))
        elif table == "dict":
            print("%d: (%s)," % (mass, pattern[:-2]))


# ----


# pattern lookup table for amino building block
patternLookupTable = (
    (1.000, 0.059, 0.003),  # 0
    (1.000, 0.122, 0.013),  # 200
    (1.000, 0.241, 0.040, 0.005),  # 400
    (1.000, 0.303, 0.059, 0.008),  # 600
    (1.000, 0.426, 0.109, 0.020, 0.003),  # 800
    (1.000, 0.533, 0.166, 0.038, 0.006),  # 1000
    (1.000, 0.655, 0.244, 0.066, 0.014, 0.002),  # 1200
    (1.000, 0.786, 0.388, 0.143, 0.042, 0.009, 0.001),  # 1400
    (1.000, 0.845, 0.441, 0.171, 0.053, 0.013, 0.002),  # 1600
    (1.000, 0.967, 0.557, 0.236, 0.080, 0.021, 0.005),  # 1800
    (0.921, 1.000, 0.630, 0.291, 0.107, 0.032, 0.007, 0.001),  # 2000
    (0.828, 1.000, 0.687, 0.343, 0.136, 0.044, 0.011, 0.002),  # 2200
    (0.752, 1.000, 0.744, 0.400, 0.171, 0.060, 0.017, 0.004),  # 2400
    (0.720, 1.000, 0.772, 0.428, 0.188, 0.068, 0.020, 0.005),  # 2600
    (0.667, 1.000, 0.825, 0.487, 0.228, 0.088, 0.028, 0.007),  # 2800
    (0.616, 1.000, 0.884, 0.556, 0.276, 0.113, 0.039, 0.010, 0.002),  # 3000
    (0.574, 1.000, 0.941, 0.628, 0.330, 0.143, 0.052, 0.015, 0.003),  # 3200
    (0.536, 0.999, 1.000, 0.706, 0.392, 0.179, 0.069, 0.022, 0.005),  # 3400
    (0.506, 0.972, 1.000, 0.725, 0.412, 0.193, 0.077, 0.025, 0.006),  # 3600
    (0.449, 0.919, 1.000, 0.764, 0.457, 0.226, 0.094, 0.033, 0.009, 0.001),  # 3800
    (0.392, 0.853, 1.000, 0.831, 0.543, 0.295, 0.136, 0.053, 0.017, 0.004),  # 4000
    (0.353, 0.812, 1.000, 0.869, 0.593, 0.336, 0.162, 0.067, 0.023, 0.006),  # 4200
    (0.321, 0.776, 1.000, 0.907, 0.644, 0.379, 0.190, 0.082, 0.030, 0.009),  # 4400
    (
        0.308,
        0.760,
        1.000,
        0.924,
        0.669,
        0.401,
        0.205,
        0.090,
        0.033,
        0.011,
        0.001,
    ),  # 4600
    (
        0.282,
        0.729,
        1.000,
        0.962,
        0.723,
        0.451,
        0.239,
        0.110,
        0.042,
        0.014,
        0.003,
    ),  # 4800
    (
        0.258,
        0.699,
        1.000,
        1.000,
        0.780,
        0.504,
        0.277,
        0.132,
        0.053,
        0.018,
        0.004,
    ),  # 5000
    (
        0.228,
        0.645,
        0.962,
        1.000,
        0.809,
        0.542,
        0.308,
        0.153,
        0.065,
        0.023,
        0.007,
    ),  # 5200
    (
        0.203,
        0.598,
        0.927,
        1.000,
        0.839,
        0.581,
        0.343,
        0.176,
        0.078,
        0.029,
        0.010,
    ),  # 5400
    (
        0.192,
        0.577,
        0.911,
        1.000,
        0.854,
        0.602,
        0.361,
        0.189,
        0.086,
        0.033,
        0.011,
    ),  # 5600
    (
        0.171,
        0.536,
        0.880,
        1.000,
        0.884,
        0.644,
        0.399,
        0.216,
        0.102,
        0.040,
        0.014,
        0.003,
    ),  # 5800
    (
        0.154,
        0.501,
        0.851,
        1.000,
        0.912,
        0.686,
        0.439,
        0.244,
        0.120,
        0.050,
        0.018,
        0.004,
    ),  # 6000
    (
        0.139,
        0.468,
        0.823,
        1.000,
        0.942,
        0.730,
        0.482,
        0.278,
        0.141,
        0.062,
        0.023,
        0.007,
    ),  # 6200
    (
        0.126,
        0.441,
        0.799,
        1.000,
        0.969,
        0.772,
        0.524,
        0.310,
        0.162,
        0.073,
        0.028,
        0.009,
    ),  # 6400
    (
        0.121,
        0.427,
        0.787,
        1.000,
        0.983,
        0.794,
        0.547,
        0.328,
        0.174,
        0.080,
        0.031,
        0.011,
    ),  # 6600
    (
        0.104,
        0.381,
        0.732,
        0.971,
        1.000,
        0.848,
        0.614,
        0.390,
        0.219,
        0.109,
        0.045,
        0.016,
        0.004,
    ),  # 6800
    (
        0.092,
        0.349,
        0.691,
        0.944,
        1.000,
        0.872,
        0.648,
        0.422,
        0.244,
        0.125,
        0.054,
        0.020,
        0.006,
    ),  # 7000
    (
        0.082,
        0.321,
        0.654,
        0.919,
        1.000,
        0.894,
        0.682,
        0.456,
        0.270,
        0.143,
        0.063,
        0.024,
        0.008,
    ),  # 7200
    (
        0.073,
        0.296,
        0.620,
        0.895,
        1.000,
        0.917,
        0.718,
        0.492,
        0.299,
        0.162,
        0.077,
        0.030,
        0.011,
    ),  # 7400
    (
        0.069,
        0.284,
        0.604,
        0.884,
        1.000,
        0.929,
        0.735,
        0.509,
        0.313,
        0.172,
        0.084,
        0.033,
        0.012,
    ),  # 7600
    (
        0.062,
        0.262,
        0.573,
        0.861,
        1.000,
        0.952,
        0.772,
        0.548,
        0.345,
        0.195,
        0.098,
        0.040,
        0.015,
        0.003,
    ),  # 7800
    (
        0.056,
        0.243,
        0.544,
        0.839,
        1.000,
        0.976,
        0.811,
        0.589,
        0.380,
        0.220,
        0.114,
        0.049,
        0.019,
        0.005,
    ),  # 8000
    (
        0.051,
        0.227,
        0.521,
        0.821,
        1.000,
        0.997,
        0.846,
        0.628,
        0.413,
        0.244,
        0.130,
        0.058,
        0.022,
        0.007,
    ),  # 8200
    (
        0.045,
        0.206,
        0.486,
        0.786,
        0.980,
        1.000,
        0.869,
        0.660,
        0.444,
        0.268,
        0.147,
        0.070,
        0.027,
        0.010,
    ),  # 8400
    (
        0.042,
        0.196,
        0.468,
        0.767,
        0.968,
        1.000,
        0.879,
        0.676,
        0.460,
        0.281,
        0.156,
        0.075,
        0.030,
        0.011,
    ),  # 8600
    (
        0.038,
        0.179,
        0.437,
        0.733,
        0.947,
        1.000,
        0.899,
        0.705,
        0.491,
        0.307,
        0.173,
        0.086,
        0.036,
        0.013,
        0.002,
    ),  # 8800
    (
        0.033,
        0.163,
        0.408,
        0.701,
        0.926,
        1.000,
        0.919,
        0.736,
        0.524,
        0.335,
        0.193,
        0.099,
        0.043,
        0.016,
        0.004,
    ),  # 9000
    (
        0.030,
        0.149,
        0.382,
        0.670,
        0.906,
        1.000,
        0.938,
        0.768,
        0.558,
        0.364,
        0.215,
        0.113,
        0.051,
        0.020,
        0.006,
    ),  # 9200
    (
        0.026,
        0.132,
        0.348,
        0.629,
        0.877,
        1.000,
        0.971,
        0.823,
        0.620,
        0.420,
        0.258,
        0.143,
        0.069,
        0.028,
        0.010,
    ),  # 9400
    (
        0.024,
        0.126,
        0.337,
        0.616,
        0.868,
        1.000,
        0.981,
        0.839,
        0.638,
        0.437,
        0.271,
        0.153,
        0.074,
        0.031,
        0.011,
    ),  # 9600
    (
        0.022,
        0.116,
        0.317,
        0.592,
        0.851,
        1.000,
        1.000,
        0.872,
        0.676,
        0.472,
        0.298,
        0.172,
        0.087,
        0.037,
        0.014,
        0.002,
    ),  # 9800
    (
        0.020,
        0.106,
        0.294,
        0.561,
        0.822,
        0.983,
        1.000,
        0.888,
        0.700,
        0.498,
        0.320,
        0.188,
        0.099,
        0.043,
        0.017,
        0.004,
    ),  # 10000
    (
        0.017,
        0.096,
        0.272,
        0.529,
        0.790,
        0.965,
        1.000,
        0.905,
        0.727,
        0.526,
        0.346,
        0.207,
        0.113,
        0.050,
        0.020,
        0.006,
    ),  # 10200
    (
        0.015,
        0.087,
        0.251,
        0.499,
        0.761,
        0.946,
        1.000,
        0.922,
        0.755,
        0.556,
        0.373,
        0.227,
        0.126,
        0.061,
        0.024,
        0.008,
    ),  # 10400
    (
        0.014,
        0.083,
        0.242,
        0.486,
        0.747,
        0.937,
        1.000,
        0.930,
        0.768,
        0.570,
        0.385,
        0.237,
        0.134,
        0.065,
        0.026,
        0.009,
    ),  # 10600
    (
        0.013,
        0.075,
        0.225,
        0.459,
        0.720,
        0.920,
        1.000,
        0.947,
        0.796,
        0.602,
        0.415,
        0.260,
        0.149,
        0.075,
        0.032,
        0.012,
        0.001,
    ),  # 10800
    (
        0.012,
        0.069,
        0.208,
        0.435,
        0.695,
        0.904,
        1.000,
        0.963,
        0.824,
        0.633,
        0.443,
        0.284,
        0.165,
        0.085,
        0.037,
        0.015,
        0.002,
    ),  # 11000
    (
        0.010,
        0.063,
        0.194,
        0.412,
        0.669,
        0.888,
        1.000,
        0.980,
        0.852,
        0.667,
        0.475,
        0.309,
        0.184,
        0.098,
        0.044,
        0.018,
        0.005,
    ),  # 11200
    (
        0.009,
        0.057,
        0.180,
        0.391,
        0.646,
        0.872,
        1.000,
        0.997,
        0.882,
        0.702,
        0.509,
        0.336,
        0.204,
        0.113,
        0.052,
        0.021,
        0.006,
    ),  # 11400
    (
        0.009,
        0.054,
        0.173,
        0.379,
        0.631,
        0.861,
        0.995,
        1.000,
        0.892,
        0.717,
        0.523,
        0.350,
        0.214,
        0.119,
        0.057,
        0.023,
        0.008,
    ),  # 11600
    (
        0.008,
        0.049,
        0.160,
        0.355,
        0.602,
        0.834,
        0.980,
        1.000,
        0.906,
        0.739,
        0.548,
        0.373,
        0.231,
        0.132,
        0.066,
        0.026,
        0.010,
    ),  # 11800
    (
        0.007,
        0.042,
        0.141,
        0.321,
        0.557,
        0.791,
        0.953,
        1.000,
        0.931,
        0.781,
        0.596,
        0.417,
        0.268,
        0.158,
        0.082,
        0.037,
        0.014,
        0.002,
    ),  # 12000
    (
        0.006,
        0.038,
        0.130,
        0.301,
        0.531,
        0.767,
        0.939,
        1.000,
        0.945,
        0.805,
        0.624,
        0.443,
        0.289,
        0.174,
        0.093,
        0.043,
        0.017,
        0.004,
    ),  # 12200
    (
        0.005,
        0.035,
        0.120,
        0.283,
        0.507,
        0.744,
        0.925,
        1.000,
        0.960,
        0.830,
        0.653,
        0.470,
        0.312,
        0.191,
        0.106,
        0.051,
        0.020,
        0.006,
    ),  # 12400
    (
        0.005,
        0.033,
        0.115,
        0.274,
        0.495,
        0.732,
        0.918,
        1.000,
        0.967,
        0.842,
        0.668,
        0.485,
        0.324,
        0.200,
        0.112,
        0.054,
        0.023,
        0.007,
    ),  # 12600
    (
        0.004,
        0.030,
        0.107,
        0.257,
        0.472,
        0.710,
        0.904,
        1.000,
        0.982,
        0.868,
        0.699,
        0.515,
        0.351,
        0.219,
        0.126,
        0.063,
        0.027,
        0.010,
    ),  # 12800
    (
        0.004,
        0.027,
        0.098,
        0.242,
        0.450,
        0.689,
        0.890,
        1.000,
        0.997,
        0.894,
        0.731,
        0.547,
        0.378,
        0.241,
        0.141,
        0.072,
        0.032,
        0.012,
        0.002,
    ),  # 13000
    (
        0.003,
        0.025,
        0.090,
        0.224,
        0.426,
        0.661,
        0.867,
        0.989,
        1.000,
        0.911,
        0.756,
        0.574,
        0.402,
        0.260,
        0.155,
        0.082,
        0.037,
        0.014,
        0.003,
    ),  # 13200
    (
        0.003,
        0.022,
        0.082,
        0.208,
        0.402,
        0.633,
        0.843,
        0.975,
        1.000,
        0.925,
        0.777,
        0.598,
        0.425,
        0.279,
        0.169,
        0.092,
        0.043,
        0.017,
        0.005,
    ),  # 13400
    (
        0.003,
        0.021,
        0.079,
        0.202,
        0.392,
        0.621,
        0.833,
        0.969,
        1.000,
        0.930,
        0.786,
        0.609,
        0.435,
        0.288,
        0.176,
        0.097,
        0.046,
        0.018,
        0.006,
    ),  # 13600
    (
        0.003,
        0.019,
        0.073,
        0.188,
        0.370,
        0.595,
        0.810,
        0.955,
        1.000,
        0.943,
        0.808,
        0.634,
        0.460,
        0.309,
        0.191,
        0.108,
        0.053,
        0.022,
        0.007,
    ),  # 13800
    (
        0.002,
        0.017,
        0.067,
        0.175,
        0.350,
        0.570,
        0.787,
        0.942,
        1.000,
        0.956,
        0.831,
        0.662,
        0.487,
        0.331,
        0.209,
        0.121,
        0.062,
        0.026,
        0.010,
    ),  # 14000
    (
        0.002,
        0.016,
        0.061,
        0.163,
        0.330,
        0.547,
        0.765,
        0.929,
        1.000,
        0.968,
        0.855,
        0.690,
        0.515,
        0.356,
        0.227,
        0.135,
        0.070,
        0.031,
        0.012,
        0.002,
    ),  # 14200
    (
        0.002,
        0.014,
        0.056,
        0.151,
        0.312,
        0.524,
        0.743,
        0.916,
        1.000,
        0.982,
        0.878,
        0.718,
        0.544,
        0.382,
        0.247,
        0.149,
        0.079,
        0.037,
        0.014,
        0.003,
    ),  # 14400
    (
        0.002,
        0.013,
        0.054,
        0.146,
        0.304,
        0.514,
        0.733,
        0.909,
        1.000,
        0.989,
        0.890,
        0.733,
        0.559,
        0.395,
        0.257,
        0.156,
        0.084,
        0.039,
        0.016,
        0.004,
    ),  # 14600
    (
        0.001,
        0.012,
        0.047,
        0.131,
        0.276,
        0.478,
        0.697,
        0.881,
        0.989,
        1.000,
        0.920,
        0.777,
        0.605,
        0.437,
        0.292,
        0.182,
        0.102,
        0.051,
        0.022,
        0.007,
    ),  # 14800
    (
        0.001,
        0.010,
        0.043,
        0.121,
        0.259,
        0.454,
        0.671,
        0.859,
        0.977,
        1.000,
        0.932,
        0.797,
        0.629,
        0.460,
        0.312,
        0.197,
        0.114,
        0.058,
        0.025,
        0.008,
        0.001,
    ),  # 15000
)
