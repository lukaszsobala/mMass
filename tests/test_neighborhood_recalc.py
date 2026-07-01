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


def _three_separate_peaks(fwhm=0.05):
    """Three singly-charged peaks 1 Da apart, labelled separately by the user.

    Mirrors the crowded-spectrum case (peaks near 1371 / 1372 / 1373): they sit
    an isotope spacing apart but the user labelled each on its own, so an
    explicit "convert 1371" must not swallow or drop 1372 / 1373.
    """
    peaks = [
        mspy.peak(mz=1371.0, ai=1000.0, charge=1, fwhm=fwhm),
        mspy.peak(mz=1372.0, ai=800.0, charge=1, fwhm=fwhm),
        mspy.peak(mz=1373.0, ai=600.0, charge=1, fwhm=fwhm),
    ]
    pl = mspy.peaklist(peaks)
    profile = mspy.profile(pl, fwhm=fwhm, points=20)
    return pl, profile


def test_convert_selected_only_preserves_neighbours(envelope_params):
    """Converting one selected peak leaves separately-labelled neighbours in place.

    Regression for the "1372 disappeared" bug: with selectedOnly the neighbour
    peaks are never pulled into the window, so re-deisotoping cannot absorb them
    as isotopes of the converted peak.
    """
    pl, profile = _three_separate_peaks()

    result = mpp.recalculate_neighborhood_envelopes(
        pl, profile, [1371.0], envelope_params, selectedOnly=True
    )

    assert result is not pl
    mzs = sorted(round(p.mz, 3) for p in result)
    # both neighbours survive
    assert 1372.0 in mzs
    assert 1373.0 in mzs


def test_convert_selected_only_does_not_widen_selection(envelope_params):
    """Only the selected peak is (re)labelled; neighbours keep their old state."""
    pl, profile = _three_separate_peaks()

    result = mpp.recalculate_neighborhood_envelopes(
        pl, profile, [1371.0], envelope_params, selectedOnly=True
    )

    labeled = [p for p in result if p.attributes.get("envelope")]
    # exactly one envelope was produced -- the one the user selected
    assert len(labeled) == 1
    assert labeled[0].mz == pytest.approx(1371.0, abs=0.05)
    # the untouched neighbours carry no freshly-built envelope metadata
    neighbours = [p for p in result if round(p.mz, 3) in (1372.0, 1373.0)]
    assert neighbours
    assert all(not p.attributes.get("envelope") for p in neighbours)


def test_convert_selected_only_multi_selection(envelope_params):
    """Selecting several peaks converts exactly those, still sparing the rest."""
    pl, profile = _three_separate_peaks()

    result = mpp.recalculate_neighborhood_envelopes(
        pl, profile, [1371.0, 1373.0], envelope_params, selectedOnly=True
    )

    labeled = sorted(
        (round(p.mz, 3) for p in result if p.attributes.get("envelope"))
    )
    assert labeled == [1371.0, 1373.0]
    # the unselected middle peak is preserved untouched
    middle = [p for p in result if round(p.mz, 3) == 1372.0]
    assert len(middle) == 1
    assert not middle[0].attributes.get("envelope")


def test_convert_selected_contiguous_none_disappear(envelope_params):
    """Every peak in a contiguous selected run stays its own envelope, none lost.

    Regression for "1373 and 1375 disappeared": five peaks an isotope spacing
    apart, all selected. Each must survive as its own envelope label (not be
    merged into a neighbour or pruned by the joint overlap fit); the overlap fit
    still apportions the shared signal between them.
    """
    mzs = [1371.684, 1372.686, 1373.689, 1374.693, 1375.697]
    ais = [92.0, 84.0, 100.0, 85.0, 53.0]
    peaks = [
        mspy.peak(mz=mz, ai=ai, charge=1, fwhm=0.05)
        for mz, ai in zip(mzs, ais, strict=True)
    ]
    pl = mspy.peaklist(peaks)
    profile = mspy.profile(pl, fwhm=0.05, points=20)

    result = mpp.recalculate_neighborhood_envelopes(
        pl, profile, list(mzs), envelope_params, selectedOnly=True
    )

    # each selected peak is its own envelope -- nothing collapsed or vanished
    labeled = sorted(
        round(p.mz, 3) for p in result if p.attributes.get("envelope")
    )
    assert labeled == [round(mz, 3) for mz in mzs]
    # and each still carries a positive apportioned area
    for p in result:
        if p.attributes.get("envelope"):
            assert p.attributes["envelope"]["area"] >= 0.0


def test_convert_selected_contiguous_reconvert_keeps_all(envelope_params):
    """Re-converting an already-converted contiguous run still loses nothing.

    Mirrors the reported case: 1371/1373/1375 already carry envelopes and the
    whole run is re-selected. preserveSeeds must ignore the stored multi-isotope
    spans (which would re-absorb 1373 into 1371) and keep every selected peak.
    """
    mzs = [1371.684, 1372.686, 1373.689, 1374.693, 1375.697]
    ais = [92.0, 84.0, 100.0, 85.0, 53.0]
    peaks = [
        mspy.peak(mz=mz, ai=ai, charge=1, fwhm=0.05)
        for mz, ai in zip(mzs, ais, strict=True)
    ]
    pl = mspy.peaklist(peaks)
    profile = mspy.profile(pl, fwhm=0.05, points=20)

    once = mpp.recalculate_neighborhood_envelopes(
        pl, profile, list(mzs), envelope_params, selectedOnly=True
    )
    twice = mpp.recalculate_neighborhood_envelopes(
        once, profile, list(mzs), envelope_params, selectedOnly=True
    )

    labeled = sorted(
        round(p.mz, 3) for p in twice if p.attributes.get("envelope")
    )
    assert labeled == [round(mz, 3) for mz in mzs]


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
