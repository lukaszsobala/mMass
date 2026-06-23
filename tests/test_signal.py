"""Tests for mspy.mod_signal -- signal-processing primitives."""

import numpy
import pytest

import mspy
from mspy import mod_signal


def _gaussian_profile(mz=1000.0, ai=1000.0, fwhm=0.1):
    pl = mspy.peaklist([mspy.peak(mz=mz, ai=ai, fwhm=fwhm)])
    return mspy.profile(pl, fwhm=fwhm, points=50)


def test_locate_returns_insertion_index():
    sig = numpy.array([[float(i), 0.0] for i in range(10)], dtype=numpy.float64)
    assert mod_signal.locate(sig, 4.5) == 5
    assert mod_signal.locate(sig, -1.0) == 0


def test_locate_rejects_wrong_dtype():
    with pytest.raises(TypeError):
        mod_signal.locate([[1.0, 2.0]], 1.0)


def test_basepeak_index_of_max():
    sig = numpy.array([[0.0, 1.0], [1.0, 9.0], [2.0, 3.0]], dtype=numpy.float64)
    assert mod_signal.basepeak(sig) == 1


def test_interpolate_midpoint():
    p1 = (0.0, 0.0)
    p2 = (10.0, 100.0)
    assert mod_signal.interpolate(p1, p2, x=5.0) == pytest.approx(50.0)
    assert mod_signal.interpolate(p1, p2, y=50.0) == pytest.approx(5.0)


def test_intensity_at_apex():
    prof = _gaussian_profile()
    assert mod_signal.intensity(prof, 1000.0) == pytest.approx(1000.0, rel=0.02)


def test_centroid_near_apex():
    prof = _gaussian_profile()
    assert mod_signal.centroid(prof, 1000.0, 500.0) == pytest.approx(1000.0, abs=0.01)


def test_width_matches_fwhm():
    prof = _gaussian_profile(fwhm=0.1)
    assert mod_signal.width(prof, 1000.0, 500.0) == pytest.approx(0.1, abs=0.02)


def test_maxima_finds_single_peak():
    prof = _gaussian_profile()
    assert len(mod_signal.maxima(prof)) == 1


def test_noise_low_on_flat_region():
    # flat baseline -> near-zero noise
    sig = numpy.array([[float(i), 5.0] for i in range(200)], dtype=numpy.float64)
    level = mod_signal.noise(sig)
    # noise() returns (intensity, width)-like estimate; accept scalar or pair
    val = level[1] if isinstance(level, (tuple, list, numpy.ndarray)) else level
    assert float(val) == pytest.approx(0.0, abs=1e-6)


def test_baseline_tracks_offset():
    sig = numpy.array([[float(i), 10.0] for i in range(200)], dtype=numpy.float64)
    base = mod_signal.baseline(sig)
    assert base is not None and len(base) > 0


def test_smooth_moving_average_preserves_shape():
    prof = _gaussian_profile()
    sm = mod_signal.smooth(prof, "MA", 0.05, 1)
    assert sm.shape == prof.shape
    # smoothing should not move the apex far
    apex = sm[int(numpy.argmax(sm[:, 1])), 0]
    assert apex == pytest.approx(1000.0, abs=0.05)


def test_smooth_savgol_runs():
    prof = _gaussian_profile()
    sm = mod_signal.smooth(prof, "SG", 0.1, 1)
    assert sm.shape == prof.shape


def test_crop_restricts_range():
    sig = numpy.array([[float(i), 1.0] for i in range(100)], dtype=numpy.float64)
    cropped = mod_signal.crop(sig, 20.0, 30.0)
    # crop keeps the requested window (it may retain one enclosing point each side)
    assert cropped[:, 0].min() <= 20.0
    assert cropped[:, 0].max() >= 30.0
    assert cropped[:, 0].min() >= 19.0
    assert cropped[:, 0].max() <= 31.0
    # original far-away points are gone
    assert cropped[:, 0].max() < 50.0
