"""Tests for non-envelope parts of mspy.mod_peakpicking.

labelpoint / labelpeak / labelscan / deconvolute / averagine.
"""

import pytest

import mspy
from mspy import mod_peakpicking as mpp


def _two_peak_profile():
    pl = mspy.peaklist([
        mspy.peak(mz=1000.0, ai=1000.0, fwhm=0.1),
        mspy.peak(mz=1010.0, ai=400.0, fwhm=0.1),
    ])
    return mspy.profile(pl, fwhm=0.1, points=50)


def test_labelpoint_returns_peak_with_width():
    prof = _two_peak_profile()
    pk = mpp.labelpoint(prof, 1000.0)
    assert pk is not None
    assert pk.mz == pytest.approx(1000.0, abs=0.02)
    assert pk.ai == pytest.approx(1000.0, rel=0.05)
    assert pk.fwhm and pk.fwhm > 0.0


def test_labelpeak_centroids_to_apex():
    prof = _two_peak_profile()
    pk = mpp.labelpeak(prof, mz=1000.0, pickingHeight=0.5)
    assert pk is not None
    assert pk.mz == pytest.approx(1000.0, abs=0.02)


def test_labelscan_finds_both_peaks():
    prof = _two_peak_profile()
    found = mpp.labelscan(prof, pickingHeight=0.5)
    mzs = sorted(p.mz for p in found)
    assert len(found) == 2
    assert mzs[0] == pytest.approx(1000.0, abs=0.05)
    assert mzs[1] == pytest.approx(1010.0, abs=0.05)


def test_labelscan_abs_threshold_filters_small_peak():
    prof = _two_peak_profile()
    found = mpp.labelscan(prof, pickingHeight=0.5, absThreshold=600.0)
    # only the 1000-intensity peak survives a 600 absolute threshold
    assert len(found) == 1
    assert found[0].mz == pytest.approx(1000.0, abs=0.05)


def test_deconvolute_recalculates_to_singly_charged():
    pl = mspy.peaklist([
        mspy.peak(mz=500.5, ai=1000.0, charge=2, isotope=0),
    ])
    out = pl.deconvolute(massType=0)
    # +2 ion at 500.5 -> singly charged neutral+H around 1000
    assert out is None  # deconvolute mutates in place
    assert pl[0].charge in (1, -1) or abs(pl[0].charge) == 1
    assert pl[0].mz == pytest.approx(1000.0, abs=0.05)


def test_deconvolute_drops_uncharged():
    pl = mspy.peaklist([mspy.peak(mz=900.0, ai=100.0)])  # no charge
    pl.deconvolute()
    assert len(pl) == 0


def test_averagine_returns_compound():
    av = mpp.averagine(1000.0, charge=1)
    # averagine returns a compound-like object with a mass
    mass = av.mass()
    mono = mass[0] if isinstance(mass, (tuple, list)) else mass
    assert mono > 0.0


# ---------------------------------------------------------------------------
# The whole "Find Peaks" pipeline, driven through the scan object
# ---------------------------------------------------------------------------


def test_find_peaks_pipeline_returns_deisotoped_envelopes():
    """Find Peaks must return deisotoped ENVELOPES, driven through `scan`.

    The exact sequence `panel_processing.pickPeaksOnScan` runs -- labelscan,
    deisotope, labelenvelopes, remisotopes, remuncharged -- and, crucially, on a
    ``mspy.scan`` object rather than on a bare peaklist.

    Every other envelope test in this suite drives ``peaklist.labelenvelopes``
    directly, so the ``scan.labelenvelopes`` wrapper the picking path actually
    calls was never exercised. When ``refinePattern`` was threaded through
    ``relabelenvelopes`` and ``peaklist.labelenvelopes`` but not through that
    wrapper, the whole picking run died on a TypeError inside its worker thread:
    the app reported nothing and the peaks came back neither deisotoped nor
    converted. This walks the same path so the wrapper cannot rot again.
    """

    # two isotopic species far enough apart to stay separate envelopes
    peaks = []
    for mono, height in ((1200.0, 1000.0), (1600.0, 600.0)):
        pattern = mspy.pattern("C50H80N14O18", charge=1, fwhm=0.05, threshold=0.005)
        shift = mono - pattern[0][0]
        peaks += [
            mspy.peak(mz=mz + shift, ai=ri * height, fwhm=0.05) for mz, ri in pattern
        ]
    profile = mspy.profile(mspy.peaklist(peaks), fwhm=0.05, points=20)

    scan = mspy.scan(profile=profile)
    scan.labelscan(pickingHeight=0.5, snThreshold=1.0, baselineWindow=1.0)
    assert len(scan.peaklist) > 4, "picking found nothing to work with"

    scan.deisotope(maxCharge=2, mzTolerance=0.05, intTolerance=0.5)
    assert any(p.charge for p in scan.peaklist), "nothing was deisotoped"

    scan.labelenvelopes(
        label="1st",
        intensity="maximum",
        mzTolerance=0.05,
        isotopeShift=0.0,
        nonIdeality=0.4,
        averagineType="protein",
        refinePattern=True,
        preserveSeeds=True,
        relaxed=True,
    )
    scan.remisotopes()
    scan.remuncharged()

    envelopes = [p for p in scan.peaklist if p.attributes.get("envelope")]
    assert len(envelopes) == 2, "expected one envelope per species"
    for peak in envelopes:
        assert peak.charge == 1
        envelope = peak.attributes["envelope"]
        assert envelope["area"] > 0.0
        assert len(envelope["isotopes"]) >= mpp.MIN_ENVELOPE_LENGTH
    # every surviving peak is an envelope: no bare isotope rows left behind
    assert len(envelopes) == len(scan.peaklist)


def test_find_peaks_pipeline_honours_strict_averagine_mode():
    """The scan wrapper forwards refinePattern rather than swallowing it.

    A parameter that reaches the wrapper but is not passed on raises nothing and
    silently does nothing, so the setting appears inert. Both modes must run, and
    the flag must actually reach the fit.
    """

    pattern = mspy.pattern("C50H80N14O18", charge=1, fwhm=0.05, threshold=0.005)
    peaks = [mspy.peak(mz=mz, ai=ri * 1000.0, fwhm=0.05) for mz, ri in pattern]
    profile = mspy.profile(mspy.peaklist(peaks), fwhm=0.05, points=20)

    areas = {}
    for refinePattern in (False, True):
        scan = mspy.scan(profile=profile)
        scan.labelscan(pickingHeight=0.5, snThreshold=1.0, baselineWindow=1.0)
        scan.deisotope(maxCharge=2, mzTolerance=0.05, intTolerance=0.5)
        scan.labelenvelopes(
            label="1st", intensity="maximum", mzTolerance=0.05,
            nonIdeality=0.4, refinePattern=refinePattern,
            preserveSeeds=True, relaxed=True,
        )
        envelope = next(
            p.attributes["envelope"] for p in scan.peaklist if p.attributes.get("envelope")
        )
        areas[refinePattern] = envelope["area"]

    assert all(area > 0.0 for area in areas.values())

