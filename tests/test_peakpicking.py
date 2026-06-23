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
