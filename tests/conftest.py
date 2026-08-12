"""Shared pytest fixtures for the mMass test suite.

Only fixtures live here -- pytest imports this file automatically and makes
every ``@pytest.fixture`` below available to the whole suite by name, with no
import needed in the test modules. Plain helper functions and constants live in
helpers.py, which test modules import explicitly.

Everything here imports ``mspy`` only -- no wxPython -- so the suite runs
headless. The Numba ``@njit`` kernels in ``mspy/calculations.py`` compile lazily
on first use (a one-off few-second cost per session); nothing here assumes a
compilation cache.
"""

import os

import pytest

import mspy

from .helpers import build_envelope_peaklist


# ---------------------------------------------------------------------------
# Processing parameters
# ---------------------------------------------------------------------------


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


@pytest.fixture
def sample_bruker():
    """Path to a bundled negative-mode Bruker flex dataset, or skip."""

    path = os.path.join(_REPO_ROOT, "spectra", "RN_M9_std_2AA_2")
    if not os.path.exists(path):
        pytest.skip("sample Bruker data not available (spectra/ is gitignored)")
    return path


@pytest.fixture
def sample_bruker_positive():
    """Path to a bundled positive-mode Bruker flex dataset, or skip.

    Paired with sample_bruker so polarity handling can be checked against one
    acquisition of each sign rather than against a single file.
    """

    path = os.path.join(_REPO_ROOT, "spectra", "RP_K7_MK_duchy_lipids_NOR_2")
    if not os.path.exists(path):
        pytest.skip("sample Bruker data not available (spectra/ is gitignored)")
    return path
