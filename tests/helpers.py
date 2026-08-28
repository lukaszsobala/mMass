"""Shared helper functions and constants for the mMass test suite.

Plain functions and data, imported explicitly by the test modules that need
them (``from .helpers import ...``). The pytest *fixtures* live next door in
conftest.py, where pytest picks them up automatically.

As with conftest, everything here imports ``mspy`` only -- no wxPython -- so
the suite runs headless.
"""

import numpy

import mspy


# ---------------------------------------------------------------------------
# Processing parameters
# ---------------------------------------------------------------------------

# The deisotoping keys the envelope pipeline reads, mirrored from the
# config.processing["deisotoping"] block in src/gui/config.py, together with a
# representative type for each. Values in the live config are user-tunable, so
# test_config_drift only checks that these KEYS still exist with compatible
# types -- not their exact values. Tests that need concrete parameters use the
# test-tuned envelope_params fixture in conftest.py.
DEISOTOPING_KEYS = {
    "maxCharge": int,
    "massTolerance": float,
    "intTolerance": float,
    "isotopeShift": float,
    "labelEnvelope": str,
    "envelopeIntensity": str,
    "envelopeNonIdeality": float,
    "envelopeRefinePattern": int,
}


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


# ---------------------------------------------------------------------------
# Assertion / conversion helpers
# ---------------------------------------------------------------------------


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
