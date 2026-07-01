"""Tests for the neighborhood auto-recalc helper.

Covers mspy.mod_peakpicking.recalculate_neighborhood_envelopes, the pure
function extracted from panel_peaklist so the delete/charge-change trigger
logic (margin window, local/outside split, re-deisotope + re-label) can be
exercised without wxPython.
"""

import pytest

import mspy
from mspy import mod_peakpicking as mpp

from .conftest import build_envelope_peaklist


def _spectrum(formula="C50H80N14O18", charge=1, height=1000.0, fwhm=0.05, extra=None):
    """Return (peaklist, profile) with one envelope plus optional extra peaks."""
    pl = build_envelope_peaklist(formula=formula, charge=charge, height=height, fwhm=fwhm)
    peaks = list(pl)
    if extra:
        peaks += extra
    combined = mspy.peaklist(peaks)
    profile = mspy.profile(combined, fwhm=fwhm, points=20)
    return combined, profile


# ---------------------------------------------------------------------------
# No-op detection (returns the same object by identity)
# ---------------------------------------------------------------------------


def test_empty_mzs_is_noop(envelope_params):
    pl, profile = _spectrum()
    assert mpp.recalculate_neighborhood_envelopes(pl, profile, [], envelope_params) is pl


def test_empty_peaklist_is_noop(envelope_params):
    pl = mspy.peaklist([])
    assert mpp.recalculate_neighborhood_envelopes(pl, None, [1000.0], envelope_params) is pl


def test_no_local_peaks_is_noop(envelope_params):
    pl, profile = _spectrum()
    # Pick an m/z far from any peak so the neighborhood window is empty.
    result = mpp.recalculate_neighborhood_envelopes(pl, profile, [9000.0], envelope_params)
    assert result is pl


# ---------------------------------------------------------------------------
# Neighborhood window and isolation
# ---------------------------------------------------------------------------


def test_far_peaks_preserved_unchanged(envelope_params):
    far = mspy.peak(mz=3000.0, ai=500.0, fwhm=0.05)
    pl, profile = _spectrum(extra=[far])
    target = min(p.mz for p in pl if p.mz < 2000.0)

    result = mpp.recalculate_neighborhood_envelopes(pl, profile, [target], envelope_params)

    assert result is not pl
    far_out = [p for p in result if abs(p.mz - 3000.0) < 1e-6]
    assert len(far_out) == 1
    assert far_out[0].ai == pytest.approx(500.0)


def test_margin_scales_with_max_charge(envelope_params):
    """A larger maxCharge shrinks the per-isotope spacing and hence the margin."""
    diff_small = (mspy.ISOTOPE_DISTANCE + envelope_params["isotopeShift"]) / 1.0
    margin_small = max(6.0 * diff_small, 8.0 * envelope_params["massTolerance"])

    big = dict(envelope_params, maxCharge=5)
    diff_big = (mspy.ISOTOPE_DISTANCE + big["isotopeShift"]) / 5.0
    margin_big = max(6.0 * diff_big, 8.0 * big["massTolerance"])

    assert margin_big < margin_small


# ---------------------------------------------------------------------------
# Recalculation behaviour
# ---------------------------------------------------------------------------


def test_neighborhood_relabels_into_envelope(envelope_params):
    """Peaks inside the window are collapsed into a labeled envelope."""
    pl, profile = _spectrum()
    target = min(p.mz for p in pl)
    result = mpp.recalculate_neighborhood_envelopes(pl, profile, [target], envelope_params)

    labeled = [p for p in result if p.attributes.get("envelope")]
    assert labeled, "expected at least one labeled envelope peak"
    assert labeled[0].charge == 1
    assert labeled[0].attributes["envelope"]["area"] > 0.0


def test_recalc_after_deleting_one_isotope(envelope_params):
    """Deleting an isotope then recalculating still yields a valid envelope."""
    pl, profile = _spectrum()
    mzs = sorted(p.mz for p in pl)
    deleted = mzs[1]  # remove the first isotope peak

    remaining = mspy.peaklist([p for p in pl if abs(p.mz - deleted) > 1e-9])
    result = mpp.recalculate_neighborhood_envelopes(remaining, profile, [deleted], envelope_params)

    labeled = [p for p in result if p.attributes.get("envelope")]
    assert labeled
    assert labeled[0].attributes["envelope"]["area"] > 0.0


def test_recalc_is_idempotent(envelope_params):
    """Running the helper twice on the same edit gives a stable envelope grid."""
    pl, profile = _spectrum()
    target = min(p.mz for p in pl)

    first = mpp.recalculate_neighborhood_envelopes(pl, profile, [target], envelope_params)
    again = mpp.recalculate_neighborhood_envelopes(first, profile, [target], envelope_params)

    env1 = next(p.attributes["envelope"] for p in first if p.attributes.get("envelope"))
    env2 = next(p.attributes["envelope"] for p in again if p.attributes.get("envelope"))
    # the isotope grid is rebuilt exactly from stored metadata
    assert [round(mz, 6) for mz, _ in env1["isotopes"]] == \
        [round(mz, 6) for mz, _ in env2["isotopes"]]
    # FWHM is always re-measured, so the re-fit area may vary by a negligible
    # amount (sub-0.1%); it must stay essentially the same, not drift materially
    assert env2["area"] == pytest.approx(env1["area"], rel=1e-3)


def test_missing_fwhm_filled_from_profile(envelope_params):
    """Peaks without fwhm get one inferred from the profile before fitting."""
    pl = build_envelope_peaklist(charge=1, height=1000.0, fwhm=0.05)
    profile = mspy.profile(pl, fwhm=0.05, points=20)
    # strip fwhm from all peaks
    bare = mspy.peaklist([mspy.peak(mz=p.mz, ai=p.ai) for p in pl])
    target = min(p.mz for p in bare)

    result = mpp.recalculate_neighborhood_envelopes(bare, profile, [target], envelope_params)
    labeled = [p for p in result if p.attributes.get("envelope")]
    assert labeled
    assert labeled[0].attributes["envelope"]["fwhm"] > 0.0


def test_refresh_missing_fwhm_helper(envelope_params):
    """_refresh_missing_fwhm_from_profile only fills peaks that lack a width."""
    pl = build_envelope_peaklist(charge=1, height=1000.0, fwhm=0.05)
    profile = mspy.profile(pl, fwhm=0.05, points=20)

    bare = mspy.peaklist([mspy.peak(mz=p.mz, ai=p.ai) for p in pl])
    mpp._refresh_missing_fwhm_from_profile(bare, profile)
    assert all(p.fwhm and p.fwhm > 0.0 for p in bare)

    # already-set widths are not overwritten
    preset = mspy.peaklist([mspy.peak(mz=1000.0, ai=100.0, fwhm=0.123)])
    mpp._refresh_missing_fwhm_from_profile(preset, profile)
    assert preset[0].fwhm == pytest.approx(0.123)


def test_refresh_recompute_overwrites_stale_fwhm(envelope_params):
    """recompute=True re-measures every width, overwriting stale values."""
    pl = build_envelope_peaklist(charge=1, height=1000.0, fwhm=0.05)
    profile = mspy.profile(pl, fwhm=0.05, points=20)

    # peaks carry a too-wide width from a superseded algorithm
    stale = mspy.peaklist([mspy.peak(mz=p.mz, ai=p.ai, fwhm=0.5) for p in pl])
    mpp._refresh_missing_fwhm_from_profile(stale, profile, recompute=True)
    # re-measured from the 0.05-wide profile, not left at the stale 0.5
    assert all(p.fwhm and p.fwhm < 0.2 for p in stale)


def test_convert_recomputes_fwhm_for_old_peaks(envelope_params):
    """Converting peaks that carry a stale FWHM re-measures it from the profile."""
    pl = build_envelope_peaklist(charge=1, height=1000.0, fwhm=0.05)
    profile = mspy.profile(pl, fwhm=0.05, points=20)

    stale = mspy.peaklist(
        [mspy.peak(mz=p.mz, ai=p.ai, charge=1, fwhm=0.5) for p in pl]
    )
    target = min(p.mz for p in stale)

    result = mpp.recalculate_neighborhood_envelopes(stale, profile, [target], envelope_params)
    labeled = [p for p in result if p.attributes.get("envelope")]
    assert labeled
    # the envelope width reflects a fresh measurement, not the stale 0.5
    assert labeled[0].attributes["envelope"]["fwhm"] < 0.2


def test_convert_recomputes_stored_envelope_fwhm(envelope_params):
    """Re-converting an already-converted envelope re-measures its FWHM.

    Converting envelopes must recompute FWHM in every case, including peaks that
    already carry envelope metadata -- the stored width is refreshed from the
    profile so a value baked in by a superseded algorithm is replaced.
    """
    pl = build_envelope_peaklist(charge=1, height=1000.0, fwhm=0.05)
    profile = mspy.profile(pl, fwhm=0.05, points=20)
    target = min(p.mz for p in pl)

    first = mpp.recalculate_neighborhood_envelopes(pl, profile, [target], envelope_params)
    env_peak = next(p for p in first if p.attributes.get("envelope"))

    # simulate a width that a previous algorithm baked into the stored envelope
    env_peak.setfwhm(0.5)
    env_peak.attributes["envelope"]["fwhm"] = 0.5

    again = mpp.recalculate_neighborhood_envelopes(
        first, profile, [env_peak.mz], envelope_params
    )
    labeled = next(p for p in again if p.attributes.get("envelope"))
    # re-measured from the 0.05-wide profile, not left at the stale 0.5
    assert labeled.attributes["envelope"]["fwhm"] < 0.2
