"""Tests for the deisotoping stage of the envelope recalculation pipeline.

Covers mspy.mod_peakpicking.deisotope (charge + isotope assignment) and the
low-level cluster pattern helpers it shares with envelope relabeling.
"""

import numpy
import pytest

import mspy
from mspy import mod_peakpicking as mpp

from .helpers import build_envelope_peaklist


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


# ---------------------------------------------------------------------------
# Monoisotopic plausibility: chemical-noise ridges
# ---------------------------------------------------------------------------


def _comb(count=16, start=650.0, intensity=400.0, jitter=(), fwhm=0.05):
    """A ridge of equally intense peaks one isotope spacing apart, and its profile.

    Models the unresolved matrix/chemical-noise comb that fills the low-m/z end of
    a MALDI spectrum. ``jitter`` overrides individual heights by index. Returns
    (peaklist of every tooth, profile) -- tests pick which teeth the "picker"
    found by building a peak list from a subset.
    """
    heights = dict(jitter)
    teeth = mspy.peaklist([
        mspy.peak(mz=start + i * mspy.ISOTOPE_DISTANCE,
                  ai=heights.get(i, intensity), fwhm=fwhm)
        for i in range(count)
    ])
    return teeth, mspy.profile(teeth, fwhm=fwhm, points=20)


def _ridge(picked, index, profile, tolerance=0.02):
    return mpp._sits_on_isotope_ridge(
        mspy.peaklist(picked), index, mspy.ISOTOPE_DISTANCE, tolerance, signal=profile
    )


def test_ridge_helper_sees_an_unexplained_comb_below_a_tooth():
    """A tooth whose ridge is in the signal but not in the peak list is background.

    This is the case peak picking creates: the tooth cleared the S/N threshold,
    everything under it did not, so the peak list shows the tooth standing alone.
    """
    teeth, profile = _comb()
    assert _ridge([teeth[10]], 0, profile)


def test_ridge_helper_ignores_a_ridge_the_peak_list_explains():
    """The same signal is NOT a veto when picked peaks account for every rung.

    A crowd of genuine overlapping species puts just as long a run of comparable
    peaks below the topmost one -- but those peaks were picked, and the rest of
    the pipeline models them. Only rungs nothing accounts for count.
    """
    teeth, profile = _comb()
    assert not _ridge(list(teeth), 10, profile)


def test_ridge_helper_clears_a_peak_standing_above_the_comb():
    """A peak well above its neighbours has no rung at all -- nothing reaches half of it."""
    teeth, profile = _comb(jitter={10: 1600.0})
    assert not _ridge([teeth[10]], 0, profile)


def test_ridge_helper_stops_at_a_gap():
    """The run must be uninterrupted: an empty rung ends the walk.

    A candidate with nothing directly below it is a plausible monoisotope no
    matter what lies further down.
    """
    teeth, profile = _comb(jitter={9: 10.0})
    assert not _ridge([teeth[10]], 0, profile)


def test_ridge_helper_needs_the_raw_signal():
    """With no signal to read, nothing is vetoed.

    The peak list alone cannot answer the question -- picking has already removed
    most of a ridge -- so a caller that supplies no profile gets the old
    behaviour rather than a guess.
    """
    teeth, _ = _comb()
    assert not mpp._sits_on_isotope_ridge(
        mspy.peaklist([teeth[10]]), 0, mspy.ISOTOPE_DISTANCE, 0.02, signal=None
    )


def _picked_comb(threshold=500.0, **kwargs):
    """Pick a comb the way the real picker does: only teeth above a threshold."""
    teeth, profile = _comb(**kwargs)
    scan = mspy.scan(profile=profile)
    scan.labelscan(pickingHeight=1.0, absThreshold=threshold, baselineWindow=1.0)
    return scan


def test_noise_comb_does_not_become_a_crowd_of_species():
    """Teeth that clear the picking threshold are still not handed a charge.

    Reproduces spectra/example6.msd at snThreshold 20: a couple of teeth of the
    600-700 comb rise above the threshold and used to be declared species -- each
    then growing a full theoretical envelope out of background. Their "+1" is far
    too intense for their pattern, and deisotoping wrote that off as an overlap
    rather than as evidence against the assignment, so they were accepted having
    confirmed no isotope at all.
    """
    # teeth 8 and 9 clear the threshold; 14 is a real species with a real +1
    scan = _picked_comb(count=20, jitter={8: 620.0, 9: 590.0, 14: 1740.0, 15: 630.0})
    scan.deisotope(maxCharge=1, mzTolerance=0.02, intTolerance=0.5)

    charged = [p.mz for p in scan.peaklist if p.charge is not None]
    assert charged, "everything was rejected, including the real peak"
    # the two teeth sit on eight rungs of comb that no picked peak explains
    assert not any(abs(mz - (650.0 + 8 * mspy.ISOTOPE_DISTANCE)) < 0.1 for mz in charged)
    assert not any(abs(mz - (650.0 + 9 * mspy.ISOTOPE_DISTANCE)) < 0.1 for mz in charged)


def test_real_peak_standing_above_a_comb_is_still_found():
    """A genuine species sitting ON the noise ridge keeps its charge.

    The safety half of the gate: rungs only count when they reach half the
    candidate's height, so a peak that rises above its neighbours has no ridge
    under it at all and is judged on its own isotope pattern as before.
    """
    scan = _picked_comb(count=20, jitter={8: 620.0, 9: 590.0, 14: 1740.0, 15: 630.0})
    scan.deisotope(maxCharge=1, mzTolerance=0.02, intTolerance=0.5)

    tall = [p for p in scan.peaklist if abs(p.mz - (650.0 + 14 * mspy.ISOTOPE_DISTANCE)) < 0.1]
    assert tall and tall[0].charge == 1 and tall[0].isotope == 0


def test_pattern_evidence_outranks_the_ridge():
    """A confirmed isotope keeps the charge even for a peak sitting on a ridge.

    The gate only ever vetoes candidates whose every isotope position was written
    off as "overlapped" -- resting on no positive evidence at all. Once the
    pattern check confirms one isotope, the assignment stands on its own,
    whatever is underneath.

    The peak list is built by hand rather than picked, because the two conditions
    barely coexist under a threshold: a confirmable +1 is about a third of its
    monoisotope, so a comb tall enough to be a ridge (half the monoisotope) hides
    it. Here the comb is in the signal and absent from the peak list, exactly as
    picking leaves it.
    """
    mono = 650.0 + 8 * mspy.ISOTOPE_DISTANCE
    teeth, profile = _comb(count=20, jitter={8: 1000.0, 9: 400.0}, intensity=560.0)
    picked = mspy.peaklist([teeth[8], teeth[9]])

    # the ridge is there ...
    assert mpp._sits_on_isotope_ridge(picked, 0, mspy.ISOTOPE_DISTANCE, 0.02, signal=profile)

    # ... and the confirmed +1 overrules it
    picked.deisotope(maxCharge=1, mzTolerance=0.02, intTolerance=0.5, signal=profile)
    assert picked[0].charge == 1 and picked[0].isotope == 0
    assert picked[1].isotope == 1


# ---------------------------------------------------------------------------
# Labelled envelopes survive a second pass
# ---------------------------------------------------------------------------


def _labelled_pair():
    """Two well-separated species, deisotoped and converted to envelopes."""
    a = build_envelope_peaklist(formula="C50H80N14O18", charge=1, height=1000.0)
    b = build_envelope_peaklist(formula="C70H110N18O22", charge=1, height=800.0)
    pl = mspy.peaklist(list(a) + list(b))
    profile = mspy.profile(pl, fwhm=0.05, points=20)
    pl.deisotope(maxCharge=3, mzTolerance=0.05, intTolerance=0.5)
    pl.labelenvelopes(signal=profile, label="1st", mzTolerance=0.05, nonIdeality=0.4)
    return pl


def test_deisotoping_preserves_labelled_envelopes():
    """Re-running deisotoping over a labelled spectrum keeps every envelope.

    This is the deisotoping panel's "Apply" on a spectrum that already carries
    envelopes. An envelope's isotopes live inside its model, not as separate peak
    rows, so a fresh charge search over the collapsed list cannot re-confirm the
    charge it was given -- it used to clear it, and "remove unknown" then deleted
    the envelope (spectra/example6.msd went from 49 envelopes to 4). The
    assignment a pattern fit already made has to be respected, not re-derived.
    """
    pl = _labelled_pair()
    before = [(p.mz, p.charge, p.isotope) for p in pl if p.attributes.get("envelope")]
    assert len(before) == 2

    pl.deisotope(maxCharge=3, mzTolerance=0.05, intTolerance=0.5)
    pl.remisotopes()
    pl.remuncharged()

    after = [(p.mz, p.charge, p.isotope) for p in pl if p.attributes.get("envelope")]
    assert after == before


def test_deisotoping_does_not_chain_through_a_labelled_envelope(make_peak):
    """Two envelopes one dalton apart stay two species, not a species and its isotope."""
    peaks = []
    for mz, ai in ((1000.0, 1000.0), (1000.0 + mspy.ISOTOPE_DISTANCE, 900.0)):
        p = make_peak(mz, ai, charge=1, isotope=0, fwhm=0.05)
        p.attributes["envelope"] = {
            "area": ai, "sumint": ai, "fwhm": 0.05, "shape": "gaussian",
            "isotopes": [(mz, 1.0)],
        }
        peaks.append(p)
    pl = mspy.peaklist(peaks)

    pl.deisotope(maxCharge=2, mzTolerance=0.1, intTolerance=0.5)

    assert [p.isotope for p in pl] == [0, 0]
    assert [p.charge for p in pl] == [1, 1]


def test_remove_isotopes_keeps_all_isotopes_envelope_rows():
    """"Remove isotopes" must not gut an envelope labelled as All Isotopes.

    Under that label the envelope IS a run of peaks numbered 0..n sharing one
    model. With the shipped defaults ("convert to envelopes" plus "remove
    isotopes") every row but the first was deleted, silently turning the chosen
    label back into "1st Peak".
    """
    pl = build_envelope_peaklist(charge=1, height=1000.0)
    profile = mspy.profile(pl, fwhm=0.05, points=20)
    pl.deisotope(maxCharge=3, mzTolerance=0.05, intTolerance=0.5)
    pl.labelenvelopes(signal=profile, label="isotopes", mzTolerance=0.05, nonIdeality=0.4)

    rows = [p for p in pl if p.attributes.get("envelope")]
    assert len(rows) > 1 and any(p.isotope for p in rows)

    pl.remisotopes()
    assert len([p for p in pl if p.attributes.get("envelope")]) == len(rows)


def test_evidence_free_candidate_is_not_the_previous_species_plus_one():
    """No two charge-1 species one isotope spacing apart on no evidence.

    At charge z a peak one isotope spacing above a species' monoisotope IS that
    species' +1 position. The pattern check already looked at it there and
    declined to confirm it only because it was too intense -- an assumption about
    an unseen overlap. Promoting the same peak to an independent monoisotope,
    having confirmed nothing itself, claims that signal twice on no evidence.
    Produced adjacent charge-1 envelopes in a noise band (spectra/example6.msd
    963.13 and 964.15, whose "+1" runs 2.1x the theoretical ratio).
    """
    step = mspy.ISOTOPE_DISTANCE
    # a run one dalton apart whose every step is far too intense to be an isotope
    # (theory allows 38% of the peak below it; these are 79% and 97%)
    pl = mspy.peaklist([
        mspy.peak(mz=963.128 + i * step, ai=ai, fwhm=0.09)
        for i, ai in enumerate((910.0, 720.0, 700.0))
    ])
    profile = mspy.profile(pl, fwhm=0.09, points=20)

    pl.deisotope(maxCharge=1, mzTolerance=0.02, intTolerance=0.5,
                 averagineType="carbohydrate", signal=profile)

    monos = [p.mz for p in pl if p.charge is not None and p.isotope == 0]
    assert monos, "the whole run was rejected"
    for a in monos:
        for b in monos:
            assert abs(b - a - step) > 0.02, (
                "two species one isotope spacing apart at the same charge: %.3f, %.3f" % (a, b)
            )


def test_overlapping_species_one_dalton_apart_keep_their_charge():
    """The +1 rule only bites without evidence -- a real pattern still wins.

    Two species a dalton apart do occur, and when either has an isotope pattern of
    its own the pattern check confirms it. Only candidates resting on nothing are
    read as the neighbour's +1.
    """
    step = mspy.ISOTOPE_DISTANCE
    lower = mspy.peaklist([
        mspy.peak(mz=963.128, ai=910.0, fwhm=0.09),
        mspy.peak(mz=963.128 + step, ai=1400.0, fwhm=0.09),
        mspy.peak(mz=963.128 + 2 * step, ai=1400.0 * 0.381, fwhm=0.09),
    ])
    profile = mspy.profile(lower, fwhm=0.09, points=20)

    lower.deisotope(maxCharge=1, mzTolerance=0.02, intTolerance=0.5,
                    averagineType="carbohydrate", signal=profile)

    # the upper peak carries a textbook +1 of its own, so it stays a species
    upper = [p for p in lower if abs(p.mz - (963.128 + step)) < 0.01][0]
    assert upper.charge == 1 and upper.isotope == 0
