"""Tests for the Numba @njit kernels in mspy.calculations.

These assert the compiled kernels agree with their pure-Python mod_signal
wrappers, so a Numba/NumPy upgrade that changes behaviour is caught. The first
call triggers JIT compilation (a one-off cost).
"""

import numpy
import pytest

import mspy
from mspy import calculations as calc
from mspy import mod_signal


@pytest.fixture(scope="module")
def gaussian_signal():
    pl = mspy.peaklist([mspy.peak(mz=1000.0, ai=1000.0, fwhm=0.1)])
    return mspy.profile(pl, fwhm=0.1, points=50)


def test_signal_intensity_matches_wrapper(gaussian_signal):
    sig = gaussian_signal
    for mz in (999.95, 1000.0, 1000.05):
        assert float(calc.signal_intensity(sig, mz)) == pytest.approx(
            mod_signal.intensity(sig, mz), rel=1e-9, abs=1e-9
        )


def test_signal_centroid_matches_wrapper(gaussian_signal):
    sig = gaussian_signal
    assert float(calc.signal_centroid(sig, 1000.0, 500.0)) == pytest.approx(
        mod_signal.centroid(sig, 1000.0, 500.0), rel=1e-9
    )


def test_signal_width_matches_wrapper(gaussian_signal):
    sig = gaussian_signal
    assert float(calc.signal_width(sig, 1000.0, 500.0)) == pytest.approx(
        mod_signal.width(sig, 1000.0, 500.0), rel=1e-9
    )


def test_signal_intensity_interpolates_between_points():
    sig = numpy.array([[0.0, 0.0], [10.0, 100.0]], dtype=numpy.float64)
    assert float(calc.signal_intensity(sig, 5.0)) == pytest.approx(50.0)


def test_signal_intensity_zero_outside_range():
    sig = numpy.array([[0.0, 5.0], [10.0, 5.0]], dtype=numpy.float64)
    assert float(calc.signal_intensity(sig, -1.0)) == pytest.approx(0.0)
    assert float(calc.signal_intensity(sig, 11.0)) == pytest.approx(0.0)


def test_signal_locate_x_monotonic():
    sig = numpy.array([[float(i), 0.0] for i in range(20)], dtype=numpy.float64)
    assert int(calc.signal_locate_x(sig, 7.5)) == 8


def test_signal_gaussian_apex():
    peak = calc.signal_gaussian(1000.0, 0.0, 100.0, 0.1, 200)
    apex = peak[int(numpy.argmax(peak[:, 1]))]
    assert apex[0] == pytest.approx(1000.0, abs=0.01)
    assert apex[1] == pytest.approx(100.0, rel=0.02)
