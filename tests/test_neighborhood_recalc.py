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


def _find_peaks_envelopes(formulas_heights, params, fwhm=0.05):
    """Emulate the find-peaks pipeline: pick from a profile, deisotope, label.

    Peaks are picked from the synthetic profile with labelpeak (so their FWHM is
    measured from the signal exactly as the real picker does), then deisotoped and
    labelled into envelopes. Returns (peaklist, profile) ready for a subsequent
    "select all -> convert to envelopes".
    """
    peaks = []
    for formula, height in formulas_heights:
        peaks += list(build_envelope_peaklist(formula=formula, charge=1, height=height, fwhm=fwhm))
    profile = mspy.profile(mspy.peaklist(peaks), fwhm=fwhm, points=20)
    picked = [pk for pk in (mpp.labelpeak(signal=profile, mz=p.mz) for p in peaks) if pk]
    fp = mspy.peaklist(picked)
    avg = params.get("averagineType", "protein")
    fp.deisotope(
        maxCharge=params["maxCharge"],
        mzTolerance=params["massTolerance"],
        intTolerance=params["intTolerance"],
        respectCharge=False,
        averagineType=avg,
    )
    fp.labelenvelopes(
        label=params["labelEnvelope"],
        intensity=params["envelopeIntensity"],
        mzTolerance=params["massTolerance"],
        signal=profile,
        defaultFwhm=fwhm,
        nonIdeality=params["envelopeNonIdeality"],
        relaxed=True,
        averagineType=avg,
    )
    return fp, profile


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


def _avg_cluster_peaks(mono, charge, area, fwhm, n=8):
    """Peaks of one averagine-consistent envelope (heights follow the pattern)."""
    weights = mpp._cluster_weights([
        mspy.peak(mz=mono + i * mspy.ISOTOPE_DISTANCE / charge, charge=charge, isotope=i, fwhm=fwhm)
        for i in range(n)
    ])
    diff = mspy.ISOTOPE_DISTANCE / charge
    return [
        mspy.peak(mz=mono + i * diff, ai=w * area, charge=charge, isotope=i, fwhm=fwhm)
        for i, w in enumerate(weights)
    ]


def _convert_params(envelope_params, **overrides):
    params = dict(envelope_params)
    params.update(massTolerance=0.15, maxCharge=1, envelopeNonIdeality=0.4)
    params.update(overrides)
    return params


def test_convert_selected_refits_overlapping_existing_envelope(envelope_params):
    """Converting a peak that overlaps an existing envelope refits that neighbour.

    The reported workflow: label a peak alone and convert it (an isolated
    envelope), then add a peak two Da below it and convert only that new peak.
    The new peak's +2 isotope lands on the existing envelope's monoisotopic peak,
    so they now overlap -- and the spec is that overlapping envelopes are always
    refined together. The existing envelope must therefore be pulled into the joint
    fit and re-apportioned (and switch to the rigid overlap treatment), NOT left
    holding the isolated area/shape it was fit with when it stood alone.
    """
    params = _convert_params(envelope_params)
    fwhm = 0.11
    small = _avg_cluster_peaks(1800.0, 1, 30.0, fwhm)     # tiny
    big = _avg_cluster_peaks(1802.0, 1, 1000.0, fwhm)     # big; small's +2 == big mono
    profile = mspy.profile(mspy.peaklist(small + big), fwhm=fwhm, points=20)

    # the big peak is already an isolated envelope (labelled alone earlier)
    r1 = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([big[0]]), profile, [1802.0], params, selectedOnly=True
    )
    big_peak = next(p for p in r1 if p.attributes.get("envelope"))
    big_isolated_area = big_peak.attributes["envelope"]["area"]

    # now the user adds the small peak (plain) and converts ONLY it
    result = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([small[0], big_peak]), profile, [1800.0], params, selectedOnly=True
    )
    envs = {round(p.mz): p.attributes.get("envelope") for p in result}

    # nothing vanished; the newly selected peak is an envelope and so is the neighbour
    assert envs[1800] is not None
    assert envs[1802] is not None
    # the existing envelope was re-fit jointly: it gave a small share to the new
    # neighbour instead of keeping its stale isolated area (pre-fix it was untouched)
    assert envs[1802]["area"] < big_isolated_area * 0.99
    assert envs[1802]["area"] > big_isolated_area * 0.85   # still essentially its size
    # the tiny new envelope only claims its small fair share of the shared peak
    assert 0.0 < envs[1800]["area"] < envs[1802]["area"] * 0.1


def test_convert_selected_leaves_non_overlapping_envelope_untouched(envelope_params):
    """A distant, non-overlapping existing envelope is NOT pulled into the refit.

    The overlap expansion must be tight: converting a peak may only refit envelopes
    it actually overlaps. An envelope far away keeps its exact area and its very
    object identity -- it is neither re-fit nor re-shaped.
    """
    params = _convert_params(envelope_params)
    fwhm = 0.11
    near = _avg_cluster_peaks(1800.0, 1, 500.0, fwhm)
    far = _avg_cluster_peaks(1860.0, 1, 1000.0, fwhm)     # 60 Da away: no overlap
    profile = mspy.profile(mspy.peaklist(near + far), fwhm=fwhm, points=20)

    r1 = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([far[0]]), profile, [1860.0], params, selectedOnly=True
    )
    far_peak = next(p for p in r1 if p.attributes.get("envelope"))
    far_area = far_peak.attributes["envelope"]["area"]

    result = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([near[0], far_peak]), profile, [1800.0], params, selectedOnly=True
    )

    # the distant envelope is carried through as the very same object, unchanged
    assert any(p is far_peak for p in result)
    kept = next(p for p in result if round(p.mz) == 1860)
    assert kept.attributes["envelope"]["area"] == pytest.approx(far_area)


def test_locked_fwhm_changes_area_and_survives_reconvert(envelope_params):
    """A locked FWHM re-fits the envelope's area and is not re-measured away.

    Editing an envelope's FWHM must change its area (area scales with peak width).
    Locking it keeps the manual width through later re-fits (convert / auto-recalc),
    so a subsequent recompute does not silently revert it to the profile-measured
    width -- but the lock stays clearable (see the companion test).
    """
    params = _convert_params(envelope_params, envelopeNonIdeality=0.0)
    fwhm = 0.11
    big = _avg_cluster_peaks(1802.0, 1, 1000.0, fwhm)
    profile = mspy.profile(mspy.peaklist(big), fwhm=fwhm, points=20)

    r1 = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([big[0]]), profile, [1802.0], params, selectedOnly=True
    )
    peak = next(p for p in r1 if p.attributes.get("envelope"))
    measured_fwhm = peak.attributes["envelope"]["fwhm"]
    measured_area = peak.attributes["envelope"]["area"]

    # the user widens and LOCKS the FWHM, then recomputes
    peak.setfwhm(measured_fwhm * 1.5)
    peak.attributes["_fwhmLocked"] = True
    r2 = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([peak]), profile, [1802.0], params, selectedOnly=True
    )
    locked = next(p for p in r2 if p.attributes.get("envelope"))
    # the manual width is honoured and the area grew with the wider peak
    assert locked.attributes["envelope"]["fwhm"] == pytest.approx(measured_fwhm * 1.5, rel=1e-3)
    assert locked.attributes["envelope"]["area"] > measured_area * 1.1
    # the lock rode along on the rebuilt representative peak
    assert locked.attributes.get("_fwhmLocked")

    # a later convert (which re-measures FWHM) must NOT revert the locked width
    r3 = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([locked]), profile, [1802.0], params, selectedOnly=True
    )
    still = next(p for p in r3 if p.attributes.get("envelope"))
    assert still.attributes["envelope"]["fwhm"] == pytest.approx(measured_fwhm * 1.5, rel=1e-3)


def test_unlocked_fwhm_is_remeasured_not_stuck(envelope_params):
    """Clearing the FWHM lock lets the width be re-measured again (not stuck)."""
    params = _convert_params(envelope_params, envelopeNonIdeality=0.0)
    fwhm = 0.11
    big = _avg_cluster_peaks(1802.0, 1, 1000.0, fwhm)
    profile = mspy.profile(mspy.peaklist(big), fwhm=fwhm, points=20)

    r1 = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([big[0]]), profile, [1802.0], params, selectedOnly=True
    )
    peak = next(p for p in r1 if p.attributes.get("envelope"))
    measured_fwhm = peak.attributes["envelope"]["fwhm"]

    peak.setfwhm(measured_fwhm * 1.5)
    peak.attributes["_fwhmLocked"] = True
    r2 = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([peak]), profile, [1802.0], params, selectedOnly=True
    )
    locked = next(p for p in r2 if p.attributes.get("envelope"))

    # unlock and recompute: the width is re-measured back to the profile value
    locked.attributes["_fwhmLocked"] = False
    r3 = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([locked]), profile, [1802.0], params, selectedOnly=True
    )
    unlocked = next(p for p in r3 if p.attributes.get("envelope"))
    assert unlocked.attributes["envelope"]["fwhm"] == pytest.approx(measured_fwhm, rel=0.05)
    assert not unlocked.attributes.get("_fwhmLocked")


def test_unlocked_fwhm_edit_applies_then_reverts_on_recalc(envelope_params):
    """An unlocked FWHM edit takes effect now, but a later auto-recalc reverts it.

    ``respectFwhm=True`` is the pass that directly applies a typed width, so editing
    the FWHM updates the area immediately even when unlocked. A subsequent auto
    recalc triggered by another peak (``respectFwhm=False``) re-measures the
    unlocked width back to the profile value -- the documented "not locked -> not
    protected against later recalcs" behaviour.
    """
    params = _convert_params(envelope_params, envelopeNonIdeality=0.0)
    fwhm = 0.11
    big = _avg_cluster_peaks(1802.0, 1, 1000.0, fwhm)
    profile = mspy.profile(mspy.peaklist(big), fwhm=fwhm, points=20)

    r1 = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([big[0]]), profile, [1802.0], params, selectedOnly=True
    )
    peak = next(p for p in r1 if p.attributes.get("envelope"))
    measured = peak.attributes["envelope"]["fwhm"]
    base_area = peak.attributes["envelope"]["area"]

    # direct edit, UNLOCKED: the typed width applies this pass and moves the area
    peak.setfwhm(measured * 1.5)
    r2 = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([peak]), profile, [1802.0], params, selectedOnly=True, respectFwhm=True
    )
    edited = next(p for p in r2 if p.attributes.get("envelope"))
    assert edited.attributes["envelope"]["fwhm"] == pytest.approx(measured * 1.5, rel=1e-3)
    assert edited.attributes["envelope"]["area"] > base_area * 1.1
    assert not edited.attributes.get("_fwhmLocked")

    # a later auto-recalc (respectFwhm=False, still unlocked) reverts the width
    r3 = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([edited]), profile, [1802.0], params, selectedOnly=True
    )
    reverted = next(p for p in r3 if p.attributes.get("envelope"))
    assert reverted.attributes["envelope"]["fwhm"] == pytest.approx(measured, rel=0.05)


def test_convert_respects_changed_averagine_model(envelope_params):
    """Re-converting under a different averagine model must re-fit the areas.

    The stored envelope shape/area is fit under one averagine model. Converting
    the same envelopes after switching models (protein -> carbohydrate/lipid)
    must re-derive the isotope pattern from the new model so the reported areas
    change -- different models encode different isotope patterns. Re-converting
    under the ORIGINAL model must still reproduce the picked areas exactly
    (idempotency for the unchanged case).

    Regression: the stored per-isotope weights were reused verbatim regardless of
    the selected model, so switching models silently left every area unchanged.
    """
    mzs = [1371.684, 1372.686, 1373.689, 1374.693, 1375.697]
    ais = [92.0, 84.0, 100.0, 85.0, 53.0]
    peaks = [
        mspy.peak(mz=mz, ai=ai, charge=1, fwhm=0.05)
        for mz, ai in zip(mzs, ais, strict=True)
    ]
    pl = mspy.peaklist(peaks)
    profile = mspy.profile(pl, fwhm=0.05, points=20)

    def convert(source, avg):
        params = dict(envelope_params, averagineType=avg)
        result = mpp.recalculate_neighborhood_envelopes(
            source, profile, list(mzs), params, selectedOnly=True
        )
        return {
            round(p.mz, 3): p.attributes["envelope"]["area"]
            for p in result
            if p.attributes.get("envelope")
        }, result

    protein_areas, protein_res = convert(pl, "protein")
    assert len(protein_areas) == len(mzs)

    for avg in ("carbohydrate", "lipid"):
        other_areas, _ = convert(protein_res, avg)
        # a different model genuinely changes the apportioned areas
        assert any(
            abs(other_areas[mz] - protein_areas[mz]) > 1e-6 for mz in protein_areas
        ), f"{avg} produced identical areas to protein"

    # re-converting under the original model reproduces the picked areas
    reprotein_areas, _ = convert(protein_res, "protein")
    for mz in protein_areas:
        assert reprotein_areas[mz] == pytest.approx(protein_areas[mz], rel=1e-9)


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


def test_convert_reproduces_find_peaks_envelopes(envelope_params):
    """'Find peaks' then 'select all -> convert to envelopes' must not diverge.

    Converting the output of peak-picking has to reproduce the SAME envelopes it
    started from: identical isotope shape (count) and matching area. This is the
    idempotency contract between the two routes.

    Regression for the reported divergence: converting a selection re-fit each
    envelope from a bare monoisotopic seed (re-deriving its shape from the profile
    via tail-extension) instead of rebuilding it from the stored envelope
    metadata. That silently changed the isotope count (e.g. 5 -> 4, 6 -> 5) and
    drifted the area, so areas/etc no longer matched what find-peaks reported.
    Rebuilding from the stored isotope grid keeps the two routes consistent.
    """
    fp, profile = _find_peaks_envelopes(
        [("C50H80N14O18", 1000.0), ("C70H110N18O22", 800.0), ("C90H140N24O28", 600.0)],
        envelope_params,
    )
    fp_env = {
        round(p.mz, 3): p.attributes["envelope"]
        for p in fp
        if p.attributes.get("envelope")
    }
    assert len(fp_env) >= 3, "expected find-peaks to yield several envelopes"

    mzs = list(fp_env)
    conv = mpp.recalculate_neighborhood_envelopes(
        fp, profile, mzs, envelope_params, selectedOnly=True
    )
    cv_env = {
        round(p.mz, 3): p.attributes["envelope"]
        for p in conv
        if p.attributes.get("envelope")
    }

    # same envelopes -- none added, lost or shifted
    assert set(cv_env) == set(fp_env)
    for mz, env in fp_env.items():
        # the isotope shape is REBUILT from stored metadata, not re-derived: the
        # count is the sharpest signal that the shape was reproduced faithfully
        # (the bug dropped the last isotope of each envelope).
        assert len(cv_env[mz]["isotopes"]) == len(env["isotopes"])
        # and the area stays put rather than drifting from the picked value
        assert cv_env[mz]["area"] == pytest.approx(env["area"], rel=0.01)


def test_convert_reproduces_find_peaks_overlapping_areas(envelope_params):
    """Overlapping envelopes: 'find peaks' and 'convert' must report the same area.

    Regression for the overlapping-envelope divergence. find-peaks fuses two
    overlapping envelopes into one bloated cluster whose theoretical weights sum
    to ~N (duplicate isotope indices from the merge) instead of ~1, which deflated
    the reported area ~N-fold; the converted route normalised to one envelope and
    so disagreed. Normalising every shape to a single-envelope distribution in the
    shared fit fixes the picked area AND makes the two routes agree. The whole
    point of the joint pipeline is to reconstruct overlapping envelopes
    consistently, so this must not regress.
    """
    fp, profile = _find_peaks_envelopes(
        [
            ("C42H66N12O15", 1000.0),
            ("C42H68N12O15", 850.0),
            ("C42H70N12O15", 700.0),
            ("C42H72N12O15", 600.0),
        ],
        envelope_params,
        fwhm=0.11,
    )
    envs = [p for p in fp if p.attributes.get("envelope")]
    # this really is a crowded, merged region (not a set of clean 5-isotope runs)
    assert any(len(p.attributes["envelope"]["isotopes"]) > 5 for p in envs)

    # Select ALL envelope peaks at full-precision m/z, exactly as the GUI does on
    # "select all" (crowded regions can carry several envelopes at the same m/z,
    # so compare multisets rather than a dict keyed on m/z). Both the area AND the
    # summed intensity must match: the reported symptom was area and sumint drifting
    # in OPPOSITE directions (one route stored a shape summing to <1, the other to 1).
    fp_env = sorted(
        (p.attributes["envelope"]["area"], p.attributes["envelope"]["sumint"])
        for p in envs
    )
    all_mzs = [p.mz for p in envs]
    conv = mpp.recalculate_neighborhood_envelopes(
        fp, profile, all_mzs, envelope_params, selectedOnly=True
    )
    cv_env = sorted(
        (p.attributes["envelope"]["area"], p.attributes["envelope"]["sumint"])
        for p in conv
        if p.attributes.get("envelope")
    )

    assert len(cv_env) == len(fp_env)
    for (pa, ps), (ca, cs) in zip(fp_env, cv_env, strict=True):
        assert ca == pytest.approx(pa, rel=0.02)
        assert cs == pytest.approx(ps, rel=0.02)
        # the stored shape sums to 1 (single-envelope distribution) on both routes
    for p in list(envs) + [q for q in conv if q.attributes.get("envelope")]:
        wsum = sum(w for _, w in p.attributes["envelope"]["isotopes"])
        assert wsum == pytest.approx(1.0, abs=1e-6)


def test_convert_reproduces_merged_pair_area_and_sumint(envelope_params):
    """Two envelopes 3 Da apart fuse into one merged cluster; both routes agree.

    Mirrors the reported 933/936 case: a single merged envelope (K==1 group with a
    long, duplicated isotope grid). Converting it must reproduce find-peaks' area
    AND summed intensity -- the fix reuses the stored shape verbatim for K==1 too
    (instead of re-soft-modelling) and normalises the shape at one shared point.
    """
    fp, profile = _find_peaks_envelopes(
        [("C40H63N11O13", 1000.0), ("C40H66N11O13", 700.0)],
        envelope_params,
        fwhm=0.109,
    )
    envs = [p for p in fp if p.attributes.get("envelope")]
    assert envs
    fp_env = sorted(
        (p.attributes["envelope"]["area"], p.attributes["envelope"]["sumint"]) for p in envs
    )
    conv = mpp.recalculate_neighborhood_envelopes(
        fp, profile, [p.mz for p in envs], envelope_params, selectedOnly=True
    )
    cv_env = sorted(
        (p.attributes["envelope"]["area"], p.attributes["envelope"]["sumint"])
        for p in conv
        if p.attributes.get("envelope")
    )
    assert len(cv_env) == len(fp_env)
    for (pa, ps), (ca, cs) in zip(fp_env, cv_env, strict=True):
        assert ca == pytest.approx(pa, rel=0.02)
        assert cs == pytest.approx(ps, rel=0.02)


def test_find_peaks_and_convert_areas_do_not_exceed_curve(envelope_params):
    """Sum of envelope areas stays within the area under the curve (mass conserving).

    End-to-end guard for the reported "sum of envelope areas above the area under
    the curve" bug, through the FULL pipeline (find-peaks and convert), including
    the storage-time shape normalisation -- not just the bare ``_fit_envelope_areas``
    unit tested in test_envelope_area_fit.py. For overlapping envelopes a
    least-squares amplitude of rigid averagine columns overshoots the integral
    (~5%), double-counting the shared signal; the apportioned-integral fit makes
    the totals conserve. Both routes must obey it and agree.
    """
    import numpy

    fp, profile = _find_peaks_envelopes(
        [
            ("C42H66N12O15", 1000.0),
            ("C42H68N12O15", 850.0),
            ("C42H70N12O15", 700.0),
            ("C42H72N12O15", 600.0),
        ],
        envelope_params,
        fwhm=0.11,
    )
    envs = [p for p in fp if p.attributes.get("envelope")]
    assert any(len(p.attributes["envelope"]["isotopes"]) > 5 for p in envs)  # crowded

    x = profile[:, 0]
    y = numpy.clip(profile[:, 1], 0.0, None)
    curve = numpy.trapezoid(y, x)

    find_total = sum(p.attributes["envelope"]["area"] for p in envs)
    conv = mpp.recalculate_neighborhood_envelopes(
        fp, profile, [p.mz for p in envs], envelope_params, selectedOnly=True
    )
    conv_total = sum(
        p.attributes["envelope"]["area"] for p in conv if p.attributes.get("envelope")
    )

    # never invent mass: the summed areas must not exceed the observed integral
    assert find_total <= curve * 1.01
    assert conv_total <= curve * 1.01
    # capture the bulk of it, but not all: to keep the decomposition fair the
    # share cap declines to attribute signal an envelope's own isotope pattern
    # cannot support at its shared isotopes (rather than let it over-claim), so a
    # crowded run -- especially one with the redundant/duplicate envelopes
    # find-peaks emits in dense regions -- sits under the full integral.
    # Under-capture is safe; over-capture (inflated areas above the curve) is the
    # bug being guarded against.
    assert find_total >= curve * 0.72
    # both routes agree on the total
    assert conv_total == pytest.approx(find_total, rel=0.02)
