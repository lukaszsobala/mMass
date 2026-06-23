"""Shared fixtures for the mMass test suite.

Everything here imports ``mspy`` only -- no wxPython -- so the suite runs
headless. The Numba ``@njit`` kernels in ``mspy/calculations.py`` compile lazily
on first use (a one-off few-second cost per session); nothing here assumes a
compilation cache.
"""

import os

import numpy
import pytest

import mspy


# ---------------------------------------------------------------------------
# Processing parameters
# ---------------------------------------------------------------------------

# The deisotoping keys the envelope pipeline reads, mirrored from the
# config.processing["deisotoping"] block in src/gui/config.py, together with a
# representative type for each. Values in the live config are user-tunable, so
# test_config_drift only checks that these KEYS still exist with compatible
# types -- not their exact values. Tests that need concrete parameters use the
# test-tuned envelope_params fixture below.
DEISOTOPING_KEYS = {
    "maxCharge": int,
    "massTolerance": float,
    "intTolerance": float,
    "isotopeShift": float,
    "labelEnvelope": str,
    "envelopeIntensity": str,
    "envelopeNonIdeality": float,
}


@pytest.fixture
def envelope_params():
    """Test-tuned params in the shape expected by the envelope recalc helper.

    Tolerances are looser than the shipped config defaults so the synthetic
    averagine envelopes (fwhm ~0.05) match cleanly and deterministically.
    """
    return {
        "massTolerance": 0.05,
        "isotopeShift": 0.0,
        "maxCharge": 3,
        "intTolerance": 0.5,
        "labelEnvelope": "1st",
        "envelopeIntensity": "maximum",
        "envelopeNonIdeality": 0.40,
        "seedCharge": 1,
    }


# ---------------------------------------------------------------------------
# Peak / peaklist factories
# ---------------------------------------------------------------------------


@pytest.fixture
def make_peak():
    """Build an mspy.peak from (mz, intensity[, charge, isotope, fwhm])."""

    def _make(mz, intensity=0.0, charge=None, isotope=None, fwhm=None, base=0.0):
        return mspy.peak(
            mz=mz,
            ai=intensity + base,
            base=base,
            charge=charge,
            isotope=isotope,
            fwhm=fwhm,
        )

    return _make


@pytest.fixture
def make_peaklist(make_peak):
    """Build an mspy.peaklist from a list of (mz, intensity, ...) tuples."""

    def _make(rows):
        return mspy.peaklist([make_peak(*row) if isinstance(row, tuple) else row for row in rows])

    return _make


# ---------------------------------------------------------------------------
# Synthetic isotopic envelopes
# ---------------------------------------------------------------------------


def build_envelope_peaklist(formula="C50H80N14O18", charge=1, height=1000.0,
                            fwhm=0.05, threshold=0.005):
    """A peaklist holding one realistic isotopic envelope for ``formula``.

    Intensities follow the theoretical averagine-consistent isotope pattern
    (via mspy.pattern), so deisotoping accepts the cluster. Peaks carry a fwhm
    so profile generation and area fitting have a width to work with.
    """
    pattern = mspy.pattern(formula, charge=charge, fwhm=fwhm, threshold=threshold)
    peaks = [mspy.peak(mz=mz, ai=ri * height, fwhm=fwhm) for mz, ri in pattern]
    return mspy.peaklist(peaks)


@pytest.fixture
def envelope_factory():
    """Expose build_envelope_peaklist as a fixture for parametrized tests."""
    return build_envelope_peaklist


@pytest.fixture
def single_envelope():
    """A deisotoped+profiled single +1 envelope ready for labeling/area fits.

    Returns (peaklist, profile). The peaklist is already charge/isotope
    assigned; the profile is a Gaussian reconstruction of the same peaks.
    """
    pl = build_envelope_peaklist(charge=1, height=1000.0)
    profile = mspy.profile(pl, fwhm=0.05, points=20)
    pl.deisotope(maxCharge=3, mzTolerance=0.05, intTolerance=0.5)
    return pl, profile


# ---------------------------------------------------------------------------
# Sample data files
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def sample_mzml():
    """Path to the bundled mzML sample, or skip if it is not present.

    The spectra/ directory is gitignored, so a fresh clone may not have it.
    """
    path = os.path.join(_REPO_ROOT, "spectra", "small.pwiz.1.1.mzML")
    if not os.path.exists(path):
        pytest.skip("sample mzML not available (spectra/ is gitignored)")
    return path


def scalar(value):
    """Reduce a mass/mz result to a float.

    The legacy mspy mass/mz getters return either a scalar or a (mono, avg)
    tuple depending on the massType argument; this collapses either form to the
    monoisotopic float so tests can do arithmetic without tripping the type
    checker on the untyped union return.
    """
    while isinstance(value, (tuple, list)):
        value = value[0]
    assert isinstance(value, (int, float))
    return float(value)


def assert_isotopes_equal(isos_a, isos_b, tol=1e-9):
    """Assert two stored isotope lists [(mz, weight), ...] are equal."""
    assert len(isos_a) == len(isos_b)
    for (mz_a, w_a), (mz_b, w_b) in zip(isos_a, isos_b, strict=True):
        assert abs(float(mz_a) - float(mz_b)) < tol
        assert abs(float(w_a) - float(w_b)) < tol


def as_signal(rows):
    """Build a float64 (N, 2) signal array from (x, y) rows."""
    return numpy.array(rows, dtype=numpy.float64)
