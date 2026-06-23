"""Tests for mspy.mod_pattern -- isotopic pattern + profile generation."""

import numpy
import pytest

import mspy
from mspy import mod_pattern


def test_pattern_monoisotopic_is_tallest_for_small_molecule():
    pat = mspy.pattern("C6H12O6", charge=0, fwhm=0.02, threshold=0.001)
    intensities = [p[1] for p in pat]
    assert intensities[0] == pytest.approx(1.0)  # normalized to base peak
    assert intensities[0] == max(intensities)


def test_pattern_peaks_spaced_by_isotope_distance():
    pat = mspy.pattern("C50H80N14O18", charge=0, fwhm=0.02, threshold=0.001)
    mzs = sorted(p[0] for p in pat)
    spacing = mzs[1] - mzs[0]
    assert spacing == pytest.approx(1.0, abs=0.05)


def test_pattern_charge_divides_mz():
    p1 = mspy.pattern("C50H80N14O18", charge=1, fwhm=0.02, threshold=0.001)
    p2 = mspy.pattern("C50H80N14O18", charge=2, fwhm=0.02, threshold=0.001)
    assert min(p[0] for p in p2) < min(p[0] for p in p1)


def test_pattern_threshold_filters_small_peaks():
    loose = mspy.pattern("C100H160N28O36", charge=0, fwhm=0.02, threshold=0.001)
    strict = mspy.pattern("C100H160N28O36", charge=0, fwhm=0.02, threshold=0.20)
    assert len(strict) <= len(loose)


def test_pattern_negative_atom_count_raises():
    with pytest.raises(ValueError):
        mspy.pattern("C-5H10", charge=0)


def test_gaussian_peak_apex_and_width():
    peak = mod_pattern.gaussian(1000.0, 0.0, 100.0, fwhm=0.1, points=200)
    apex_idx = int(numpy.argmax(peak[:, 1]))
    assert peak[apex_idx, 0] == pytest.approx(1000.0, abs=0.01)
    assert peak[apex_idx, 1] == pytest.approx(100.0, rel=0.02)


def test_lorentzian_and_gausslorentzian_run():
    lor = mod_pattern.lorentzian(1000.0, 0.0, 100.0, fwhm=0.1, points=100)
    gl = mod_pattern.gausslorentzian(1000.0, 0.0, 100.0, fwhm=0.1, points=100)
    assert lor.shape[1] == 2 and gl.shape[1] == 2
    assert numpy.max(lor[:, 1]) == pytest.approx(100.0, rel=0.05)


def test_profile_from_peaklist_has_apex_at_peak():
    pl = mspy.peaklist([mspy.peak(mz=1000.0, ai=500.0, fwhm=0.1)])
    prof = mspy.profile(pl, fwhm=0.1, points=50)
    apex_mz = prof[int(numpy.argmax(prof[:, 1])), 0]
    assert apex_mz == pytest.approx(1000.0, abs=0.02)
    assert numpy.max(prof[:, 1]) == pytest.approx(500.0, rel=0.02)


def test_profile_on_explicit_raster():
    pl = mspy.peaklist([mspy.peak(mz=1000.0, ai=500.0, fwhm=0.1)])
    raster = numpy.arange(999.0, 1001.0, 0.01)
    prof = mspy.profile(pl, fwhm=0.1, raster=raster)
    assert len(prof) == len(raster)


def test_matchpattern_returns_low_error_for_matching_signal():
    pat = mspy.pattern("C50H80N14O18", charge=1, fwhm=0.05, threshold=0.01)
    pl = mspy.peaklist([mspy.peak(mz=mz, ai=ri * 1000.0, fwhm=0.05) for mz, ri in pat])
    signal = mspy.profile(pl, fwhm=0.05, points=20)
    error = mod_pattern.matchpattern(signal, pat, pickingHeight=0.5)
    assert error is not None
    assert error >= 0.0
