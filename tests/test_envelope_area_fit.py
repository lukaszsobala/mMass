"""Tests for the NNLS envelope area fit -- the most regression-prone step.

Covers mspy.mod_peakpicking._fit_envelope_areas: ground-truth recovery for an
isolated envelope, deconvolution of overlapping envelopes, non-negativity,
the no-profile fallback, and stability under small perturbations.
"""

import numpy
import pytest

import mspy
from mspy import mod_peakpicking as mpp


WEIGHTS = [1.0, 0.6, 0.22, 0.06]


def _cluster_at(mono, charge, height, weights=WEIGHTS, fwhm=0.05):
    diff = mspy.ISOTOPE_DISTANCE / charge
    return [
        mspy.peak(mz=mono + i * diff, ai=w * height, charge=charge, isotope=i, fwhm=fwhm)
        for i, w in enumerate(weights)
    ]


def _profile(*clusters, fwhm=0.05):
    peaks = [p for c in clusters for p in c]
    return mspy.profile(mspy.peaklist(peaks), fwhm=fwhm, points=20)


# ---------------------------------------------------------------------------
# Single envelope
# ---------------------------------------------------------------------------


def test_single_area_is_positive_and_finite():
    cluster = _cluster_at(1000.0, 1, 1000.0)
    area = mpp._fit_envelope_areas([cluster], _profile(cluster), 0.05, nonIdeality=0.4)[0]
    assert area > 0.0
    assert numpy.isfinite(area)


def test_area_scales_linearly_with_height():
    """Doubling the peak heights doubles the fitted area."""
    lo = _cluster_at(1000.0, 1, 500.0)
    hi = _cluster_at(1000.0, 1, 1000.0)
    area_lo = mpp._fit_envelope_areas([lo], _profile(lo), 0.05, 0.4)[0]
    area_hi = mpp._fit_envelope_areas([hi], _profile(hi), 0.05, 0.4)[0]
    assert area_hi / area_lo == pytest.approx(2.0, rel=0.05)


# ---------------------------------------------------------------------------
# Overlapping envelopes (core failure mode)
# ---------------------------------------------------------------------------


def test_overlapping_envelopes_are_deconvolved():
    """Two overlapping envelopes both get positive areas ranked by intensity."""
    tall = _cluster_at(1000.0, 1, 1000.0)
    short = _cluster_at(1002.0, 1, 400.0)  # overlaps tall, 2 Da higher
    areas = mpp._fit_envelope_areas([tall, short], _profile(tall, short), 0.05, 0.4)

    assert all(a > 0.0 for a in areas)
    assert areas[0] > areas[1]
    # roughly tracks the 1000:400 intensity ratio (heuristic softening loosens it)
    assert areas[0] / areas[1] == pytest.approx(2.5, rel=0.4)


def test_overlap_areas_track_swapped_intensities():
    """When the shorter/taller roles swap, the fitted ranking swaps too."""
    short = _cluster_at(1000.0, 1, 400.0)
    tall = _cluster_at(1002.0, 1, 1000.0)
    areas = mpp._fit_envelope_areas([short, tall], _profile(short, tall), 0.05, 0.4)
    assert areas[1] > areas[0]


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


def test_areas_are_non_negative_for_noisy_profile():
    cluster = _cluster_at(1200.0, 2, 800.0)
    profile = _profile(cluster)
    rng = numpy.random.default_rng(0)
    profile[:, 1] += rng.normal(0.0, 5.0, size=len(profile))
    areas = mpp._fit_envelope_areas([cluster], profile, 0.05, 0.4)
    assert all(a >= 0.0 for a in areas)


def test_no_profile_fallback_uses_peak_heights():
    cluster = _cluster_at(1000.0, 1, 1000.0)
    areas = mpp._fit_envelope_areas([cluster], None, 0.05, 0.4)
    assert areas[0] > 0.0


def test_empty_signal_array_does_not_raise():
    cluster = _cluster_at(1000.0, 1, 1000.0)
    areas = mpp._fit_envelope_areas([cluster], numpy.empty((0, 2)), 0.05, 0.4)
    assert all(a >= 0.0 for a in areas)


def test_area_stable_under_small_perturbation():
    """A small change to peak heights moves the area only a little."""
    base = _cluster_at(1000.0, 1, 1000.0)
    area0 = mpp._fit_envelope_areas([base], _profile(base), 0.05, 0.4)[0]

    perturbed = _cluster_at(1000.0, 1, 1000.0)
    for p in perturbed:
        p.setai(p.ai * 1.02)
    area1 = mpp._fit_envelope_areas([perturbed], _profile(perturbed), 0.05, 0.4)[0]

    assert area1 == pytest.approx(area0, rel=0.05)
