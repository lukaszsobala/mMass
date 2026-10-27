"""The spectrum's resolution curve gives weak peaks their width.

A single weak peak's own width scatters by about 1.5 / (S/N) and reads narrow
at low S/N, and an envelope's area follows its model width almost one to one.
Every width is therefore blended with the curve fitted to the spectrum's
strong, isolated peaks (mspy.mod_peakpicking.resolutioncurve).
"""

import copy
import math

import numpy
import pytest

import mspy
from mspy import mod_peakpicking as mpp

SQ2PI = math.sqrt(2.0 * math.pi)

LAWS = {
    "TOF": lambda mz: mz / 9000.0,  # constant resolving power
    "Orbitrap": lambda mz: 0.08 * (mz / 1000.0) ** 1.5,
}
STRONG = [760.4, 880.5, 1010.5, 1130.6, 1260.6, 1390.7]
WEAK = [(950.5, 25.0), (1070.6, 35.0), (1330.7, 45.0)]


def _pattern(mono):
    parent = mspy.peak(mz=mono, ai=1.0, charge=1, isotope=0)
    weights = mpp._cluster_pattern(parent, mpp._theory_envelope_length(parent))
    total = sum(weights)
    return [(mono + i * mpp.ISOTOPE_DISTANCE, w / total) for i, w in enumerate(weights)]


def _spectrum(width, seed=0, weak=WEAK, strongHeight=400.0):
    """A profile of strong and weak envelopes whose widths follow `width`, and
    each species' true (area, FWHM)."""

    x = numpy.arange(700.0, 1450.0, 0.004)
    y = numpy.full(len(x), 30.0)
    truth = {}
    for mono, height in [(m, strongHeight) for m in STRONG] + list(weak):
        fwhm = width(mono)
        sigma = fwhm / 2.3548
        pattern = _pattern(mono)
        area = height * sigma * SQ2PI / pattern[0][1]
        truth[mono] = (area, fwhm)
        for mz, w in pattern:
            y += area * w / (sigma * SQ2PI) * numpy.exp(-0.5 * ((x - mz) / sigma) ** 2)
    y += numpy.random.default_rng(seed).normal(0.0, 1.0, len(x))
    return numpy.column_stack((x, y)).astype(numpy.float64), truth


@pytest.mark.parametrize("law, exponent", [("TOF", 1.0), ("Orbitrap", 1.5)])
def test_curve_follows_the_analyser(law, exponent):
    profile, _truth = _spectrum(LAWS[law])
    curve = mpp.resolutioncurve(profile)

    assert curve is not None
    assert curve["references"] >= 5
    assert curve["exponent"] == pytest.approx(exponent, abs=0.1)
    for mz in (800.0, 1100.0, 1400.0):
        predicted, error = mpp._curve_fwhm(curve, mz)
        assert predicted == pytest.approx(LAWS[law](mz), rel=0.02)
        assert error < 0.05


@pytest.mark.parametrize("law", sorted(LAWS))
def test_weak_envelopes_get_the_instruments_width_and_their_area(law):
    """Measured on their own, these envelopes' widths read 0.83-0.94 of the truth
    and their areas with them; with the curve both are right."""

    config = pytest.importorskip("gui.config")
    from gui import processing

    settings = copy.deepcopy(config.processing)
    settings["peakpicking"]["snThreshold"] = 3.0
    for seed in range(3):
        profile, truth = _spectrum(LAWS[law], seed=seed)
        scan = mspy.scan(profile=profile)
        processing.pickPeaks(scan, settings)
        for mono, _height in WEAK:
            peak = next(
                (p for p in scan.peaklist if p.attributes.get("envelope") and abs(p.mz - mono) < 0.05),
                None,
            )
            assert peak is not None
            area, fwhm = truth[mono]
            assert peak.attributes["envelope"]["fwhm"] == pytest.approx(fwhm, rel=0.03)
            assert peak.attributes["envelope"]["area"] == pytest.approx(area, rel=0.05)


def test_a_strong_peak_keeps_its_own_width():
    """The curve does not overrule a well-measured peak: one genuinely wider than
    the instrument (an unresolved overlap) stays wide, a weak one is pulled in."""

    profile, _truth = _spectrum(LAWS["TOF"])
    curve = mpp.resolutioncurve(profile)
    instrument, _error = mpp._curve_fwhm(curve, 1000.0)

    assert mpp.resolvedfwhm(1.3 * instrument, 1000.0, 500.0, curve) == pytest.approx(1.3 * instrument, rel=0.02)
    assert mpp.resolvedfwhm(0.8 * instrument, 1000.0, 5.0, curve) == pytest.approx(instrument, rel=0.03)
    # no S/N to weigh it by: the measurement stands; none at all: the curve
    assert mpp.resolvedfwhm(0.8 * instrument, 1000.0, None, curve) == 0.8 * instrument
    assert mpp.resolvedfwhm(None, 1000.0, 5.0, curve) == pytest.approx(instrument)


def test_a_locked_width_is_left_alone():
    profile, _truth = _spectrum(LAWS["TOF"])
    locked = mspy.peak(mz=1000.0, ai=60.0, base=30.0, sn=5.0, fwhm=0.5)
    locked.attributes["_fwhmLocked"] = True
    free = mspy.peak(mz=1000.0, ai=60.0, base=30.0, sn=5.0, fwhm=0.5)

    mpp.applyresolution(mspy.peaklist([locked, free]), profile)

    assert locked.fwhm == 0.5
    assert free.fwhm == pytest.approx(1000.0 / 9000.0, rel=0.05)


def test_without_reference_peaks_widths_are_measured_as_before():
    profile, _truth = _spectrum(LAWS["TOF"], strongHeight=20.0)

    assert mpp.resolutioncurve(profile) is None
    peak = mspy.peak(mz=1000.0, ai=60.0, base=30.0, sn=5.0, fwhm=0.09)
    mpp.applyresolution(mspy.peaklist([peak]), profile)
    assert peak.fwhm == 0.09


def test_refitting_measures_widths_as_picking_does():
    """Re-fitting envelopes after an edit re-measures every width from the
    profile. It must arrive at the widths picking gave -- above the baseline and
    resolved against the same curve -- or each edit would move the areas."""

    config = pytest.importorskip("gui.config")
    from gui import processing

    settings = copy.deepcopy(config.processing)
    settings["peakpicking"]["snThreshold"] = 3.0
    profile, _truth = _spectrum(LAWS["Orbitrap"], seed=5)
    scan = mspy.scan(profile=profile)
    processing.pickPeaks(scan, settings)
    picked = {round(p.mz, 3): p.fwhm for p in scan.peaklist}

    mpp._refresh_missing_fwhm_from_profile(scan.peaklist, profile, recompute=True)

    for peak in scan.peaklist:
        assert peak.fwhm == pytest.approx(picked[round(peak.mz, 3)], rel=0.02)
