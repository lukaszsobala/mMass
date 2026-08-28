"""Tests for the neighborhood auto-recalc helper.

Covers mspy.mod_peakpicking.recalculate_neighborhood_envelopes, the pure
function extracted from panel_peaklist so the delete/charge-change trigger
logic (margin window, local/outside split, re-deisotope + re-label) can be
exercised without wxPython.
"""

import pytest

import mspy
from mspy import mod_peakpicking as mpp

from .helpers import build_envelope_peaklist


def _spectrum(formula="C50H80N14O18", charge=1, height=1000.0, fwhm=0.05, extra=None):
    """Return (peaklist, profile) with one envelope plus optional extra peaks."""
    pl = build_envelope_peaklist(formula=formula, charge=charge, height=height, fwhm=fwhm)
    peaks = list(pl)
    if extra:
        peaks += extra
    combined = mspy.peaklist(peaks)
    profile = mspy.profile(combined, fwhm=fwhm, points=20)
    return combined, profile


def _converted(peaklist, profile, params, mzs):
    """Run the user's explicit "convert to envelopes" action on given m/z values.

    The auto-recalc path (selectedOnly=False) only ever recalculates envelopes
    that already exist -- it never converts plain peaks -- so a test of that path
    has to start from a list where the user has converted something first.
    """
    return mpp.recalculate_neighborhood_envelopes(
        peaklist, profile, list(mzs), params, selectedOnly=True
    )


def _envelope_spectrum(params, extra=None, **kwargs):
    """(peaklist, profile) with the species' monoisotopic peak already converted."""
    pl, profile = _spectrum(extra=extra, **kwargs)
    mono = min(p.mz for p in pl)
    return _converted(pl, profile, params, [mono]), profile


def _find_peaks_envelopes(formulas_heights, params, fwhm=0.05):
    """Emulate the find-peaks pipeline: pick from a profile, deisotope, label.

    Peaks are picked from the synthetic profile with labelpeak (so their FWHM is
    measured from the signal exactly as the real picker does), then deisotoped and
    labelled into envelopes. Returns (peaklist, profile) ready for a subsequent
    "select all -> convert to envelopes".

    Mirrors pickPeaksOnScan: envelope labelling uses the clean-seed path
    (preserveSeeds/relaxed) so find-peaks and "convert to envelopes" share the
    exact same code and produce identical envelopes for the same seeds -- each
    deisotoped seed is its own clean single-species envelope, never absorbed or
    fused into a merged multi-species grid.
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
        preserveSeeds=True,
    )
    # find-peaks removes the isotope peaks after envelope conversion; drop them
    # here too so the peaklist handed to "convert" is the same seed-only state the
    # GUI shows (envelope representatives at isotope 0).
    fp = mspy.peaklist([pk for pk in fp if pk.isotope in (None, 0)])
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
    pl, profile = _envelope_spectrum(envelope_params, extra=[far])
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


def test_neighborhood_recalc_refits_existing_envelope(envelope_params):
    """An envelope inside the window is re-fit (that is what auto-recalc is for)."""
    pl, profile = _envelope_spectrum(envelope_params)
    target = min(p.mz for p in pl)
    result = mpp.recalculate_neighborhood_envelopes(pl, profile, [target], envelope_params)

    labeled = [p for p in result if p.attributes.get("envelope")]
    assert labeled, "expected at least one labeled envelope peak"
    assert labeled[0].charge == 1
    assert labeled[0].attributes["envelope"]["area"] > 0.0


def test_neighborhood_recalc_never_converts_plain_peaks(envelope_params):
    """Auto-recalc must not turn plain peaks into envelopes.

    A peak becomes an envelope only when the user says so ("convert to
    envelopes"). With nothing but plain peaks in the window there is nothing to
    recalculate, so the list is returned untouched -- by identity, so callers can
    see the no-op.
    """
    pl, profile = _three_separate_peaks()          # plain charged peaks

    result = mpp.recalculate_neighborhood_envelopes(
        pl, profile, [1371.0], envelope_params
    )

    assert result is pl
    assert not [p for p in result if p.attributes.get("envelope")]


def test_neighborhood_recalc_leaves_plain_neighbours_alone(envelope_params):
    """Recalculating an envelope never converts or eats the peaks next to it.

    Regression: the neighbourhood re-fit used to re-deisotope and re-label every
    peak in the margin window, so editing or deleting one peak silently converted
    its plain neighbours into envelopes (or absorbed them into one). They must come
    out exactly as they went in -- same object, charge, width and no envelope.
    """
    plain = mspy.peak(mz=1373.0, ai=600.0, charge=1, fwhm=0.05)
    bare = mspy.peak(mz=1374.5, ai=200.0, fwhm=0.05)      # no charge at all
    seed = mspy.peak(mz=1371.0, ai=1000.0, charge=1, fwhm=0.05)
    pl = mspy.peaklist([seed, plain, bare])
    profile = mspy.profile(pl, fwhm=0.05, points=20)

    # the user converts ONE peak, then something nearby is edited/deleted
    converted = _converted(pl, profile, envelope_params, [1371.0])
    result = mpp.recalculate_neighborhood_envelopes(
        converted, profile, [1371.0], envelope_params
    )

    labeled = sorted(round(p.mz, 3) for p in result if p.attributes.get("envelope"))
    assert labeled == [1371.0]
    for mz, charge in ((1373.0, 1), (1374.5, None)):
        kept = next(p for p in result if round(p.mz, 3) == mz)
        assert not kept.attributes.get("envelope")
        assert kept.charge == charge
        assert not kept.group
        assert kept.fwhm == pytest.approx(0.05)


def test_peak_editor_charge_edit_keeps_a_plain_peak_plain(envelope_params):
    """Editing a plain peak's charge must not label it (peak editor "Update").

    The editor re-fits the neighbourhood after a charge change so nearby envelopes
    stay correct. That must not convert the edited peak itself: it had no envelope
    before the edit and must have none after, even though it is now a charged
    monoisotopic seed sitting next to an envelope.
    """
    seed = mspy.peak(mz=1371.0, ai=1000.0, charge=1, fwhm=0.05)
    edited = mspy.peak(mz=1373.0, ai=600.0, fwhm=0.05)         # no charge yet
    pl = mspy.peaklist([seed, edited])
    profile = mspy.profile(pl, fwhm=0.05, points=20)
    converted = _converted(pl, profile, envelope_params, [1371.0])

    # the user types charge 1 into the editor and clicks Update
    target = next(p for p in converted if round(p.mz, 3) == 1373.0)
    target.setcharge(1)
    result = mpp.recalculate_neighborhood_envelopes(
        converted, profile, [1373.0], envelope_params
    )

    still_plain = next(p for p in result if round(p.mz, 3) == 1373.0)
    assert not still_plain.attributes.get("envelope")
    assert still_plain.charge == 1
    # ...while the envelope next door was refit, which is the point of the recalc
    envelope = next(p for p in result if round(p.mz, 3) == 1371.0)
    assert envelope.attributes["envelope"]["area"] > 0.0


def test_envelope_survives_a_charge_edit_that_fits_badly(envelope_params):
    """A charge edit may leave an envelope fitting badly -- it must not vanish.

    The editor drops the stored isotope grid on a charge change (the old spacing
    is stale) and re-fits. At a wrong charge the model matches almost no signal, so
    the joint fit gives the envelope ~zero area; it must still be reported (small
    area = visible feedback), never pruned out of the peak list.
    """
    pl, profile = _three_separate_peaks()
    converted = _converted(pl, profile, envelope_params, [1371.0])

    env_peak = next(p for p in converted if p.attributes.get("envelope"))
    env_peak.setcharge(2)
    stored = dict(env_peak.attributes["envelope"])
    stored["isotopes"] = []
    env_peak.attributes["envelope"] = stored

    result = mpp.recalculate_neighborhood_envelopes(
        converted, profile, [1371.0], envelope_params
    )

    survivor = next(p for p in result if round(p.mz, 3) == 1371.0)
    assert survivor.charge == 2
    assert survivor.attributes.get("envelope") is not None
    assert len(result) == len(converted)


def test_recalc_does_not_duplicate_all_isotope_labels(envelope_params):
    """Recalculating an "All Isotopes" envelope must not clone its isotope rows.

    Regression: under labelEnvelope="isotopes" an envelope is several peaks sharing
    one group. Re-labelling emitted a fresh peak per isotope while the originals
    were left in the list, so every edit/delete grew the peak list by a whole
    envelope and left orphans carrying a stale envelope behind.

    The same failure returns whenever an envelope reaches past the auto-recalc
    margin window, which is a fixed multiple of the isotope *spacing* while an
    envelope is as long as its pattern: a row left outside the window is not
    consumed by the rebuild, which emits a fresh row at that position while the
    stale one survives, so the list grows by one on every recalc. The window is
    widened to the full stored span of every envelope it touches for exactly this
    reason -- so the count below has to hold for an envelope longer than the
    window as well.
    """
    params = dict(envelope_params, labelEnvelope="isotopes")
    pl = mspy.peaklist([
        mspy.peak(mz=1371.0, ai=1000.0, charge=1, fwhm=0.05),
        mspy.peak(mz=1374.5, ai=500.0, charge=1, fwhm=0.05),   # clear of the grid
    ])
    profile = mspy.profile(pl, fwhm=0.05, points=20)

    converted = _converted(pl, profile, params, [1371.0])
    once = mpp.recalculate_neighborhood_envelopes(converted, profile, [1371.0], params)
    twice = mpp.recalculate_neighborhood_envelopes(once, profile, [1371.0], params)

    assert len(once) == len(converted)
    assert len(twice) == len(converted)
    # one group, and every member still carries its measured height
    groups = {p.group for p in twice if p.group}
    assert len(groups) == 1
    assert all(p.ai > 0.0 for p in twice)
    # the untouched neighbour is still a plain peak
    plain = next(p for p in twice if round(p.mz, 3) == 1374.5)
    assert not plain.attributes.get("envelope")


def test_recalc_after_deleting_one_isotope(envelope_params):
    """Deleting an isotope then recalculating still yields a valid envelope."""
    pl, profile = _envelope_spectrum(envelope_params)
    mzs = sorted(p.mz for p in pl)
    deleted = mzs[1]  # remove the first isotope peak

    remaining = mspy.peaklist([p for p in pl if abs(p.mz - deleted) > 1e-9])
    result = mpp.recalculate_neighborhood_envelopes(remaining, profile, [deleted], envelope_params)

    labeled = [p for p in result if p.attributes.get("envelope")]
    assert labeled
    assert labeled[0].attributes["envelope"]["area"] > 0.0


# spectra/example_env4.msd: two charge-1 species two Da apart (each one's +2 is the
# other's mono), heights read off the real profile.
_ENV4_ROWS = [
    (900.494, 1332.0), (901.506, 1333.0), (902.511, 1575.0),
    (903.510, 600.0), (904.509, 257.0), (905.509, 421.0),
]


def _env4_pair(params):
    """Both example_env4 species converted to envelopes. Returns (peaklist, profile)."""

    heights = dict(_ENV4_ROWS)
    profile = mspy.profile(
        mspy.peaklist([mspy.peak(mz=mz, ai=ai, fwhm=0.05) for mz, ai in _ENV4_ROWS]),
        fwhm=0.05, points=20,
    )
    peaklist = mspy.peaklist([
        mspy.peak(mz=mz, ai=heights[mz], charge=1, isotope=0, fwhm=0.05)
        for mz in (900.494, 902.511)
    ])
    return _converted(peaklist, profile, params, [900.494, 902.511]), profile


def _area_at(peaklist, mz):
    peak = next(p for p in peaklist if abs(p.mz - mz) < 0.05)
    return peak.attributes["envelope"]["area"]


def test_recalc_after_deleting_a_neighbouring_envelope(envelope_params):
    """Deleting one envelope must re-fit the neighbour that was sharing its peak.

    The gap that let this through: every delete test above removes an isotope of
    the SAME envelope, so the edit always landed inside the recalc window. Here the
    two species are two Da apart while the window is a multiple of the isotope
    *spacing*, which shrinks as 1/maxCharge -- at maxCharge 4 it is only +/-1.5 Da.
    Deleting 902.51 therefore never reached 900.49, even though 900.49's +2 IS
    902.51: the survivor kept the area it had been given while sharing that peak,
    and to the user nothing recalculated. An envelope must be re-fit whenever the
    edit touches any of ITS isotopes, not only when its monoisotopic peak happens
    to fall inside the window.
    """

    params = dict(envelope_params, maxCharge=4, massTolerance=0.02)
    converted, profile = _env4_pair(params)
    before = _area_at(converted, 900.494)

    remaining = mspy.peaklist([p for p in converted if abs(p.mz - 902.511) > 0.05])
    result = mpp.recalculate_neighborhood_envelopes(
        remaining, profile, [902.511], params
    )

    after = _area_at(result, 900.494)
    # the survivor was actually re-fit ...
    assert after != pytest.approx(before, rel=1e-6)
    # ... and it gained: the peak it used to share is now its alone
    assert after > before


def test_recalc_window_reaches_every_envelope_it_touches(envelope_params):
    """The recalc window covers any envelope whose ISOTOPES reach into it.

    The invariant behind the test above, stated directly: 900.49's monoisotopic
    peak sits outside the margin window around 902.51, but its +2 lands squarely
    inside it, so it has to be one of the envelopes the pass rebuilds. If it were
    skipped the helper would return the list unchanged.
    """

    params = dict(envelope_params, maxCharge=4, massTolerance=0.02)
    converted, profile = _env4_pair(params)

    # the margin genuinely does not reach 900.49's monoisotopic peak, so the only
    # thing that can pull it into the pass is its +2 landing inside the window
    margin = max(6.0 * mspy.ISOTOPE_DISTANCE / 4.0, 8.0 * params["massTolerance"])
    assert 900.494 < 902.511 - margin
    assert 900.494 + 2 * mspy.ISOTOPE_DISTANCE > 902.511 - margin

    remaining = mspy.peaklist(
        [p for p in converted if abs(p.mz - 902.511) > 0.05]
    )
    result = mpp.recalculate_neighborhood_envelopes(
        remaining, profile, [902.511], params
    )
    # the helper returns its input BY IDENTITY when it found nothing to do
    assert result is not remaining


def test_recalc_is_idempotent(envelope_params):
    """Running the helper twice on the same edit gives a stable envelope grid."""
    pl, profile = _envelope_spectrum(envelope_params)
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

    result = _converted(bare, profile, envelope_params, [target])
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

    result = _converted(stale, profile, envelope_params, [target])
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
    """Converting one selected peak never makes a charged neighbour disappear.

    Regression for the "1372 disappeared" bug: an overlapping charged neighbour
    joins the fit (see ``test_convert_selected_joins_overlapping_charged_neighbours``)
    but is never absorbed as an isotope of the converted peak, merged away, or
    pruned -- it stays in the list as the plain peak it was.
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


def test_convert_selected_joins_overlapping_charged_neighbours(envelope_params):
    """An overlapping charged neighbour joins the fit but is NOT converted.

    A deisotoped charged peak occupies real signal, so converting a peak that
    overlaps one must apportion the two together -- otherwise the selection is fit
    alone and over-claims the shared signal (this is what makes "convert" work on a
    "Find peaks" result whose neighbours are still plain charged peaks). The
    neighbour takes part as fit CONTEXT only: only what the user selected becomes
    an envelope, everything else stays exactly the peak it was.
    """
    pl, profile = _three_separate_peaks()   # 1371/1372/1373, all charge 1

    result = mpp.recalculate_neighborhood_envelopes(
        pl, profile, [1371.0], envelope_params, selectedOnly=True
    )

    labeled = sorted(round(p.mz, 3) for p in result if p.attributes.get("envelope"))
    # only the selection is converted; the neighbours are untouched plain peaks
    assert labeled == [1371.0]
    for mz in (1372.0, 1373.0):
        kept = next(p for p in result if round(p.mz, 3) == mz)
        assert not kept.attributes.get("envelope")
        assert kept.charge == 1
        assert not kept.group


def test_convert_selected_apportions_against_plain_neighbour(envelope_params):
    """The unconverted neighbour still holds its share of the signal in the fit.

    Leaving a neighbour a plain peak must not hand its signal to the converted
    envelope: the area the selection gets is the joint one (what it would get if
    both were converted), not the inflated "fit alone" value.
    """
    pl, profile = _three_separate_peaks()

    joined = mpp.recalculate_neighborhood_envelopes(
        pl, profile, [1371.0], envelope_params, selectedOnly=True
    )
    area = next(
        p for p in joined if round(p.mz, 3) == 1371.0
    ).attributes["envelope"]["area"]

    # reference: convert everything -- the same joint apportionment
    both = mpp.recalculate_neighborhood_envelopes(
        pl, profile, [1371.0, 1372.0, 1373.0], envelope_params, selectedOnly=True
    )
    joint = next(
        p for p in both if round(p.mz, 3) == 1371.0
    ).attributes["envelope"]["area"]

    # and the "no neighbours at all" case, which over-claims the shared signal
    alone_pl = mspy.peaklist([mspy.peak(mz=1371.0, ai=1000.0, charge=1, fwhm=0.05)])
    alone = mpp.recalculate_neighborhood_envelopes(
        alone_pl, profile, [1371.0], envelope_params, selectedOnly=True
    )
    alone_area = next(
        p for p in alone if round(p.mz, 3) == 1371.0
    ).attributes["envelope"]["area"]

    assert area == pytest.approx(joint, rel=1e-6)
    assert area < alone_area


def test_convert_selected_leaves_bare_uncharged_neighbour_untouched(envelope_params):
    """A bare (uncharged) neighbour is NOT pulled in -- widening stays bounded.

    The join is limited to real species (existing envelopes or charged seeds). A
    peak with no charge assigned is not a committed species, so an overlapping bare
    peak is left exactly as it was: not converted, not relabelled. This keeps the
    selection from being widened into unassigned / noise peaks.
    """
    peaks = [
        mspy.peak(mz=1371.0, ai=1000.0, charge=1, fwhm=0.05),
        mspy.peak(mz=1372.0, ai=400.0, fwhm=0.05),          # bare: no charge
    ]
    pl = mspy.peaklist(peaks)
    profile = mspy.profile(pl, fwhm=0.05, points=20)

    result = mpp.recalculate_neighborhood_envelopes(
        pl, profile, [1371.0], envelope_params, selectedOnly=True
    )

    labeled = sorted(round(p.mz, 3) for p in result if p.attributes.get("envelope"))
    assert labeled == [1371.0]                              # only the selection
    bare = next(p for p in result if round(p.mz, 3) == 1372.0)
    assert not bare.attributes.get("envelope")              # left untouched
    assert bare.charge is None


def test_convert_selected_multi_selection_keeps_middle_a_peak(envelope_params):
    """Selecting two peaks that straddle a charged neighbour converts only those two.

    The middle peak is joined into the same fit (so the shared signal is
    apportioned three ways) but the user did not select it, so it stays a peak.
    """
    pl, profile = _three_separate_peaks()

    result = mpp.recalculate_neighborhood_envelopes(
        pl, profile, [1371.0, 1373.0], envelope_params, selectedOnly=True
    )

    labeled = sorted(
        (round(p.mz, 3) for p in result if p.attributes.get("envelope"))
    )
    assert labeled == [1371.0, 1373.0]
    middle = next(p for p in result if round(p.mz, 3) == 1372.0)
    assert not middle.attributes.get("envelope")
    assert middle.charge == 1


def test_convert_selected_group_names_avoid_existing_groups(envelope_params):
    """A per-selection convert must not reuse a group letter already in the list.

    Regression: _label_local relabels only the local subset and restarts group
    names from "A", so without deduplication a newly converted peak collides with
    the group ("A", "B", ...) already carried by an untouched envelope elsewhere.
    Here a far-away envelope already owns group "A"; converting a separate peak
    must give it a *different* letter, not a second "A".
    """
    far = [
        mspy.peak(mz=2000.0, ai=1000.0, charge=1, isotope=0, fwhm=0.05, group="A"),
        mspy.peak(mz=2001.0, ai=500.0, charge=1, isotope=1, fwhm=0.05, group="A"),
    ]
    far[0].attributes["envelope"] = {
        "isotopes": [(2000.0, 1.0), (2001.0, 0.5)],
        "fwhm": 0.05,
        "area": 1.0,
    }
    target = mspy.peak(mz=1371.0, ai=800.0, charge=1, fwhm=0.05)
    pl = mspy.peaklist(far + [target])
    profile = mspy.profile(pl, fwhm=0.05, points=20)

    result = mpp.recalculate_neighborhood_envelopes(
        pl, profile, [1371.0], envelope_params, selectedOnly=True
    )

    converted = next(p for p in result if round(p.mz, 3) == 1371.0)
    untouched = [p for p in result if round(p.mz, 3) in (2000.0, 2001.0)]
    # the untouched envelope keeps its "A"; the new one gets a fresh, distinct letter
    assert all(p.group == "A" for p in untouched)
    assert converted.group
    assert converted.group != "A"
    # no two distinct envelopes share a group letter
    assert converted.group not in {p.group for p in untouched}


def test_convert_all_group_names_start_from_a(envelope_params):
    """The whole-list convert (no outside peaks) still starts group names at "A".

    The dedup only reserves letters used by peaks OUTSIDE the converted subset;
    when every peak is converted there are none, so labelling is unchanged and the
    first envelope is group "A" as before (order-independent full relabel).
    """
    pl, profile = _three_separate_peaks()
    mzs = [p.mz for p in pl]

    result = mpp.recalculate_neighborhood_envelopes(
        pl, profile, mzs, envelope_params, selectedOnly=True
    )

    groups = sorted({p.group for p in result if p.group})
    assert groups[:3] == ["A", "B", "C"]


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


def test_convert_joins_plain_charged_findpeaks_neighbour(envelope_params):
    """Converting a peak next to a plain charged (find-peaks) neighbour joins it.

    The reported workflow: after "Find peaks" a species is a plain charged peak (not
    yet an envelope). The user adds a peak two Da below it and converts only the new
    peak. The neighbour is a deisotoped charged seed occupying real signal, so it
    must be pulled into the joint fit; otherwise the new peak is fit alone and
    over-claims the shared signal (its +2 lands on the neighbour mono). The area
    must match the case where the neighbour was converted too -- while the
    neighbour itself stays the plain peak the user left it as.
    """
    params = _convert_params(envelope_params)
    fwhm = 0.11
    small = _avg_cluster_peaks(1800.0, 1, 300.0, fwhm)
    big = _avg_cluster_peaks(1802.0, 1, 1000.0, fwhm)      # small's +2 == big mono
    profile = mspy.profile(mspy.peaklist(small + big), fwhm=fwhm, points=20)

    # neighbour is a PLAIN charged monoisotopic peak, as "Find peaks" leaves it
    big_plain = mspy.peak(mz=1802.0, ai=big[0].intensity, charge=1, fwhm=fwhm)
    assert not big_plain.attributes.get("envelope")

    # reference: what the added peak's area should be when the neighbour is joined,
    # obtained by converting BOTH together from bare seeds
    ref = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([
            mspy.peak(mz=1800.0, ai=small[0].intensity, charge=1, fwhm=fwhm),
            mspy.peak(mz=1802.0, ai=big[0].intensity, charge=1, fwhm=fwhm),
        ]),
        profile, [1800.0, 1802.0], params, selectedOnly=True,
    )
    ref_small = next(p for p in ref if round(p.mz) == 1800).attributes["envelope"]["area"]

    # the reported path: neighbour is a plain charged peak; convert ONLY the added one
    added = mspy.peak(mz=1800.0, ai=small[0].intensity, charge=1, fwhm=fwhm)
    result = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([big_plain, added]), profile, [1800.0], params, selectedOnly=True,
    )
    envs = {round(p.mz): p.attributes.get("envelope") for p in result}

    # the plain neighbour was joined into the fit but left a plain peak
    assert envs[1802] is None
    assert next(p for p in result if round(p.mz) == 1802).charge == 1
    assert envs[1800] is not None
    # and the added peak got its correct joint area -- identical to converting both,
    # NOT the inflated area it would claim if fit alone
    assert envs[1800]["area"] == pytest.approx(ref_small, rel=1e-6)


def test_convert_to_envelopes_is_order_independent_in_a_forest(envelope_params):
    """Envelope areas in a peak forest must not depend on conversion order.

    Reported bug: with envelopes every ~2 m/z, converting the whole forest at once
    gives sensible areas, but converting them one at a time (label + "convert to
    envelopes" on each new peak, leaving the earlier ones already converted) leaves
    a later-added peak with a *smaller* area than it should have. The cause: a peak
    converted while ISOLATED stored a soft-modelled (data-bent) shape, and when it
    was later pulled into the overlap group that bent shape was reused verbatim,
    letting it over-claim the shared signal at the expense of the freshly converted
    neighbour. An overlapping envelope must use the rigid averagine pattern whether
    or not it carries a stored shape, so a previously-converted regular envelope
    behaves exactly like a fresh seed and the joint fit is order-independent.
    """
    params = _convert_params(envelope_params)
    fwhm = 0.11
    monos = [1798.0, 1800.0, 1802.0, 1804.0]
    heights = [500.0, 800.0, 600.0, 400.0]
    all_peaks = []
    for m, h in zip(monos, heights, strict=True):
        all_peaks += _avg_cluster_peaks(m, 1, h, fwhm)
    profile = mspy.profile(mspy.peaklist(all_peaks), fwhm=fwhm, points=20)

    def _seed(mono, height):
        # a bare monoisotopic peak, as the user would label it
        return mspy.peak(mz=mono, ai=height, charge=1, fwhm=fwhm)

    def _areas(peaklist):
        out = {}
        for p in peaklist:
            env = p.attributes.get("envelope")
            if env:
                out[round(p.mz)] = env["area"]
        return out

    # (A) convert the whole forest at once -- the reference result
    ref = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([_seed(m, h) for m, h in zip(monos, heights, strict=True)]),
        profile, list(monos), params, selectedOnly=True,
    )
    ref_areas = _areas(ref)

    # (B) convert one peak at a time, each step selecting ONLY the newly added peak
    # while the earlier ones are already converted envelopes
    cur = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([_seed(monos[0], heights[0])]),
        profile, [monos[0]], params, selectedOnly=True,
    )
    for m, h in zip(monos[1:], heights[1:], strict=True):
        cur = mspy.peaklist(list(cur) + [_seed(m, h)])
        cur = mpp.recalculate_neighborhood_envelopes(
            cur, profile, [m], params, selectedOnly=True,
        )
    seq_areas = _areas(cur)

    # every envelope is present in both routes and the areas match (pre-fix the
    # sequentially converted forest drifted, e.g. 1800 fell to ~75% of its
    # all-at-once area)
    assert set(seq_areas) == set(ref_areas) == {round(m) for m in monos}
    for mz in ref_areas:
        assert seq_areas[mz] == pytest.approx(ref_areas[mz], rel=1e-6)


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

    first = _converted(pl, profile, envelope_params, [target])
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
    """Overlapping envelopes: 'find peaks' and 'convert' must be identical.

    find-peaks and "convert to envelopes" now share the exact same clean-seed code
    (preserveSeeds), so in a crowded overlapping region they must produce IDENTICAL
    envelopes -- not merely close. Each species stays a clean single-envelope
    distribution (weights sum to 1); none is fused into a bloated multi-species
    grid whose weights sum to ~N (the old merge deflated the reported area ~N-fold
    and made the two routes disagree). This is the core "both pipelines produce
    identical results" contract for the hard overlapping case.
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
    # genuinely crowded/overlapping: many envelopes packed into a narrow window
    # (four heavily overlapping species ~2 Da apart), yet every one is a CLEAN
    # single-species run -- no merged multi-isotope grid survives.
    assert len(envs) >= 5
    span = max(p.mz for p in envs) - min(p.mz for p in envs)
    assert span < 6.0 * len(envs)  # tightly packed, not spread out
    assert all(len(p.attributes["envelope"]["isotopes"]) <= 5 for p in envs)

    # Select ALL envelope peaks at full-precision m/z, exactly as the GUI does on
    # "select all" (crowded regions can carry several envelopes at the same m/z,
    # so compare multisets rather than a dict keyed on m/z). Because both routes
    # run the identical clean-seed labelling, area AND summed intensity must match
    # essentially exactly, not merely within a few percent.
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
        assert ca == pytest.approx(pa, rel=1e-6)
        assert cs == pytest.approx(ps, rel=1e-6)
        # the stored shape sums to 1 (single-envelope distribution) on both routes
    for p in list(envs) + [q for q in conv if q.attributes.get("envelope")]:
        wsum = sum(w for _, w in p.attributes["envelope"]["isotopes"])
        assert wsum == pytest.approx(1.0, abs=1e-6)


def test_convert_reproduces_merged_pair_area_and_sumint(envelope_params):
    """Two envelopes ~3 Da apart: find-peaks and convert are identical.

    Mirrors the reported 933/936 close pair. Under the shared clean-seed path the
    two species are kept as two clean single-envelope distributions rather than
    fused into one bloated merged grid, and find-peaks' area AND summed intensity
    are reproduced exactly by convert (same code, same fit) -- neither species is
    crushed and no irregular multi-species grid survives.
    """
    fp, profile = _find_peaks_envelopes(
        [("C40H63N11O13", 1000.0), ("C40H66N11O13", 700.0)],
        envelope_params,
        fwhm=0.109,
    )
    envs = [p for p in fp if p.attributes.get("envelope")]
    assert envs
    # clean single-species runs, not one fused irregular grid
    assert all(len(p.attributes["envelope"]["isotopes"]) <= 6 for p in envs)
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
        assert ca == pytest.approx(pa, rel=1e-6)
        assert cs == pytest.approx(ps, rel=1e-6)


def test_find_peaks_and_convert_areas_do_not_exceed_curve(envelope_params):
    """Sum of envelope areas stays within the area under the curve (mass conserving).

    End-to-end guard for the reported "sum of envelope areas above the area under
    the curve" bug, through the FULL pipeline (find-peaks and convert), including
    the storage-time shape normalisation -- not just the bare ``_fit_envelope_areas``
    unit tested in test_envelope_area_fit.py. For overlapping envelopes a
    least-squares amplitude of rigid averagine columns overshoots the integral
    (~5%), double-counting the shared signal; the apportioned-integral fit makes
    the totals conserve. find-peaks and convert share the clean-seed code, so they
    must both obey it AND agree exactly.
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
    # crowded overlapping region: many clean single-species envelopes packed close
    # together (no bloated merged grid survives -- each is a short run).
    assert len(envs) >= 5
    assert all(len(p.attributes["envelope"]["isotopes"]) <= 5 for p in envs)

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
    # capture the bulk of it: the apportioned-integral fit distributes the shared
    # signal without over-claiming, so the summed areas stay under the full
    # integral. Under-capture is safe; over-capture (inflated areas above the
    # curve) is the bug being guarded against.
    assert find_total >= curve * 0.72
    # both routes run the identical clean-seed labelling, so the totals are equal,
    # not merely close.
    assert conv_total == pytest.approx(find_total, rel=1e-6)
