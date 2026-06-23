"""Tests for envelope profile reconstruction (display path).

Covers mspy.mod_peakpicking.envelopeprofile: rebuilding a continuous Gaussian
profile from a stored envelope metadata dict.
"""

import numpy
import pytest

import mspy
from mspy import mod_peakpicking as mpp


def _envelope(charge=1, area=100.0, fwhm=0.05, weights=(1.0, 0.6, 0.22)):
    diff = mspy.ISOTOPE_DISTANCE / charge
    isotopes = [(1000.0 + i * diff, w) for i, w in enumerate(weights)]
    return {
        "area": area,
        "sumint": sum(weights) * 100.0,
        "fwhm": fwhm,
        "shape": "gaussian",
        "isotopes": isotopes,
    }


def test_profile_columns_and_monotonic_raster():
    prof = mpp.envelopeprofile(_envelope())
    assert prof.ndim == 2 and prof.shape[1] == 2
    xs = prof[:, 0]
    assert numpy.all(numpy.diff(xs) > 0)


def test_profile_integral_matches_area():
    """Trapezoidal integral of the reconstructed profile ~ stored area * sum(weights)."""
    weights = (1.0, 0.6, 0.22)
    env = _envelope(area=100.0, weights=weights)
    prof = mpp.envelopeprofile(env, points=200)
    integral = numpy.trapezoid(prof[:, 1], prof[:, 0])
    assert integral == pytest.approx(env["area"] * sum(weights), rel=0.02)


def test_profile_peaks_align_with_isotopes():
    """Local maxima of the profile sit at the isotope m/z positions."""
    env = _envelope(fwhm=0.03, weights=(1.0, 0.6, 0.25))
    prof = mpp.envelopeprofile(env, points=200)
    x, y = prof[:, 0], prof[:, 1]

    for mz, _ in env["isotopes"]:
        window = (x > mz - 0.1) & (x < mz + 0.1)
        apex = x[window][numpy.argmax(y[window])]
        assert apex == pytest.approx(mz, abs=env["fwhm"])


def test_empty_envelope_returns_empty():
    assert mpp.envelopeprofile(None).size == 0
    assert mpp.envelopeprofile({}).size == 0


def test_zero_area_returns_empty():
    assert mpp.envelopeprofile(_envelope(area=0.0)).size == 0


def test_respects_supplied_raster():
    env = _envelope()
    raster = numpy.arange(999.0, 1004.0, 0.01)
    prof = mpp.envelopeprofile(env, raster=raster)
    assert len(prof) == len(raster)
    assert prof[0, 0] == pytest.approx(raster[0])
