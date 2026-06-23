"""Tests for the deisotoping stage of the envelope recalculation pipeline.

Covers mspy.mod_peakpicking.deisotope (charge + isotope assignment) and the
low-level cluster pattern helpers it shares with envelope relabeling.
"""

import numpy
import pytest

import mspy
from mspy import mod_peakpicking as mpp

from .conftest import build_envelope_peaklist


# ---------------------------------------------------------------------------
# Charge / isotope assignment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("charge", [1, 2, 3])
def test_clean_envelope_charge_and_isotope(charge):
    """A clean single-species envelope is assigned the right charge + isotope order."""
    pl = build_envelope_peaklist(charge=charge, height=1000.0)
    n = len(pl)
    pl.deisotope(maxCharge=4, mzTolerance=0.05, intTolerance=0.5)

    assert [p.charge for p in pl] == [charge] * n
    assert [p.isotope for p in pl] == list(range(n))


def test_isotope_spacing_matches_charge():
    """Detected isotope spacing is ISOTOPE_DISTANCE / charge."""
    charge = 2
    pl = build_envelope_peaklist(charge=charge, height=1000.0)
    pl.deisotope(maxCharge=3, mzTolerance=0.05, intTolerance=0.5)

    mzs = sorted(p.mz for p in pl)
    spacing = mzs[1] - mzs[0]
    assert spacing == pytest.approx(mspy.ISOTOPE_DISTANCE / charge, abs=0.02)


def test_maxcharge_cap_respected():
    """A +3 envelope is not detected if maxCharge only allows +1."""
    pl = build_envelope_peaklist(charge=3, height=1000.0)
    pl.deisotope(maxCharge=1, mzTolerance=0.05, intTolerance=0.5)
    # No +1 spacing exists in a +3 cluster, so nothing becomes a multi-peak
    # envelope; charges must never exceed the cap.
    assert all((p.charge is None or abs(p.charge) <= 1) for p in pl)


def test_respect_charge_preserves_existing(make_peaklist):
    """respectCharge=True keeps a pre-assigned charge instead of re-deriving it."""
    pl = build_envelope_peaklist(charge=2, height=1000.0)
    for p in pl:
        p.setcharge(2)
        p.setisotope(None)

    pl.deisotope(maxCharge=5, mzTolerance=0.05, intTolerance=0.5,
                 respectCharge=True, seedCharge=1)
    assert all(p.charge == 2 for p in pl)


def test_respect_charge_seed_fallback():
    """respectCharge=True falls back to seedCharge for unassigned single peaks."""
    pl = mspy.peaklist([mspy.peak(mz=900.0, ai=1000.0)])
    pl.deisotope(maxCharge=5, respectCharge=True, seedCharge=3)
    assert pl[0].charge == 3


def test_no_isotopes_leaves_singleton_uncharged():
    """An isolated peak with no neighbors gets no charge in normal mode."""
    pl = mspy.peaklist([mspy.peak(mz=1234.5, ai=500.0)])
    pl.deisotope(maxCharge=4, mzTolerance=0.05, intTolerance=0.5)
    assert pl[0].charge is None
    assert pl[0].isotope is None


def test_isotope_shift_changes_spacing():
    """A non-zero isotopeShift widens the accepted spacing (HDX-style)."""
    charge = 1
    shift = 0.1
    base = 1000.0
    diff = (mspy.ISOTOPE_DISTANCE + shift) / charge
    peaks = [mspy.peak(mz=base + k * diff, ai=ai)
             for k, ai in enumerate((1000.0, 600.0, 220.0))]
    pl = mspy.peaklist(peaks)
    pl.deisotope(maxCharge=2, mzTolerance=0.03, intTolerance=0.6, isotopeShift=shift)

    assert pl[0].charge == 1
    assert [p.isotope for p in pl] == [0, 1, 2]


def test_two_species_not_merged_into_one_charge_series():
    """Two distinct, well-separated envelopes keep their own monoisotopic peaks."""
    a = build_envelope_peaklist(formula="C50H80N14O18", charge=1, height=1000.0)
    b = build_envelope_peaklist(formula="C70H110N18O22", charge=1, height=800.0)
    combined = mspy.peaklist(list(a) + list(b))
    combined.deisotope(maxCharge=3, mzTolerance=0.05, intTolerance=0.5)

    monos = [p for p in combined if p.isotope == 0]
    # Each species contributes exactly one monoisotopic peak.
    assert len(monos) == 2


# ---------------------------------------------------------------------------
# Cluster pattern helpers
# ---------------------------------------------------------------------------


def test_cluster_pattern_poisson_shape():
    """_cluster_pattern returns a normalized, single-moded Poisson averagine slice."""
    parent = mspy.peak(mz=2000.0, ai=1000.0, charge=1)
    pattern = mpp._cluster_pattern(parent, size=6)

    assert len(pattern) == 6
    assert max(pattern) == pytest.approx(1.0)
    assert all(p >= 0.0 for p in pattern)
    # light species: monoisotopic peak is the tallest
    assert pattern[0] == pytest.approx(1.0)


def test_cluster_pattern_heavy_species_shifts_apex():
    """For a heavy species the apex moves off the monoisotopic peak."""
    parent = mspy.peak(mz=8000.0, ai=1000.0, charge=1)
    pattern = mpp._cluster_pattern(parent, size=10)
    apex = pattern.index(max(pattern))
    assert apex > 0


def test_cluster_pattern_zero_size():
    assert mpp._cluster_pattern(mspy.peak(mz=1000.0, charge=1), 0) == []


def test_cluster_observed_pattern_infers_indices():
    """_cluster_observed_pattern maps peaks onto integer isotope indices."""
    charge = 1
    diff = mspy.ISOTOPE_DISTANCE / charge
    parent = mspy.peak(mz=1000.0, ai=1000.0, charge=charge)
    cluster = [parent,
               mspy.peak(mz=1000.0 + diff, ai=600.0, charge=charge),
               mspy.peak(mz=1000.0 + 2 * diff, ai=200.0, charge=charge)]
    observed, max_err = mpp._cluster_observed_pattern(parent, cluster)

    assert observed is not None
    assert max_err is not None
    assert len(observed) == 3
    assert observed[0] >= observed[1] >= observed[2]
    assert max_err < 1e-6


def test_cluster_observed_pattern_requires_charge():
    parent = mspy.peak(mz=1000.0, ai=1000.0)  # no charge
    observed, max_err = mpp._cluster_observed_pattern(parent, [parent])
    assert observed is None and max_err is None


def test_cluster_pattern_error_accepts_good_cluster():
    """A textbook decaying cluster yields a finite (non-None) fit error."""
    charge = 1
    diff = mspy.ISOTOPE_DISTANCE / charge
    parent = mspy.peak(mz=1000.0, ai=1000.0, charge=charge)
    cluster = [parent,
               mspy.peak(mz=1000.0 + diff, ai=590.0, charge=charge),
               mspy.peak(mz=1000.0 + 2 * diff, ai=210.0, charge=charge)]
    err = mpp._cluster_pattern_error(parent, cluster)
    assert err is not None
    assert err >= 0.0


def test_cluster_pattern_error_rejects_impossible_growth():
    """A cluster whose intensities grow without limit is rejected (None)."""
    charge = 1
    diff = mspy.ISOTOPE_DISTANCE / charge
    parent = mspy.peak(mz=1000.0, ai=10.0, charge=charge)
    cluster = [parent,
               mspy.peak(mz=1000.0 + diff, ai=500.0, charge=charge),
               mspy.peak(mz=1000.0 + 2 * diff, ai=5000.0, charge=charge)]
    assert mpp._cluster_pattern_error(parent, cluster) is None


def test_cluster_pattern_error_singleton_is_zero():
    parent = mspy.peak(mz=1000.0, ai=1000.0, charge=1)
    assert mpp._cluster_pattern_error(parent, [parent]) == 0.0


def test_empty_peaklist_deisotope_is_noop():
    pl = mspy.peaklist([])
    pl.deisotope(maxCharge=3)
    assert len(pl) == 0


def test_deisotope_requires_peaklist_object():
    with pytest.raises(TypeError):
        mpp.deisotope(numpy.array([[1000.0, 1.0]]), maxCharge=2)
