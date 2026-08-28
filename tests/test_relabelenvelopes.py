"""Tests for envelope (re)labeling -- the heart of the recalculation pipeline.

Covers mspy.mod_peakpicking.relabelenvelopes and peaklist.labelenvelopes:
label/intensity modes, envelope metadata, idempotency of re-runs, and the
tail-length floor.
"""

import pytest

import mspy
from mspy import mod_peakpicking as mpp

from .helpers import assert_isotopes_equal, build_envelope_peaklist


def _deisotoped(charge=1, height=1000.0, fwhm=0.05):
    pl = build_envelope_peaklist(charge=charge, height=height, fwhm=fwhm)
    profile = mspy.profile(pl, fwhm=fwhm, points=20)
    pl.deisotope(maxCharge=3, mzTolerance=0.05, intTolerance=0.5)
    return pl, profile


# ---------------------------------------------------------------------------
# Label modes
# ---------------------------------------------------------------------------


def test_label_1st_collapses_to_monoisotopic_peak():
    pl, profile = _deisotoped()
    mono_mz = min(p.mz for p in pl)
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)

    assert len(pl) == 1
    assert pl[0].mz == pytest.approx(mono_mz, abs=1e-6)
    assert pl[0].isotope == 0
    assert pl[0].charge == 1


def test_label_isotopes_keeps_all_peaks_indexed():
    pl, profile = _deisotoped()
    n = len(pl)
    pl.labelenvelopes(label="isotopes", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)

    assert len(pl) == n
    assert [p.isotope for p in pl] == list(range(n))
    assert all(p.charge == 1 for p in pl)


def test_label_centroid_returns_single_charged_peak():
    pl, profile = _deisotoped()
    lo, hi = min(p.mz for p in pl), max(p.mz for p in pl)
    pl.labelenvelopes(label="centroid", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)

    assert len(pl) == 1
    assert pl[0].charge == 1
    assert lo <= pl[0].mz <= hi  # centroid sits within the cluster


def test_label_monoisotope_returns_single_peak():
    pl, profile = _deisotoped()
    pl.labelenvelopes(label="monoisotope", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    assert len(pl) == 1
    assert pl[0].isotope == 0


# ---------------------------------------------------------------------------
# Intensity modes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["maximum", "average", "sum"])
def test_intensity_modes_are_ordered(mode):
    """sum >= maximum >= average for a multi-peak envelope label."""
    results = {}
    for m in ("maximum", "average", "sum"):
        pl, profile = _deisotoped()
        pl.labelenvelopes(label="1st", intensity=m, signal=profile,
                          defaultFwhm=0.05, nonIdeality=0.4)
        results[m] = pl[0].ai

    assert results["sum"] >= results["maximum"] >= results["average"]
    assert results[mode] > 0.0


# ---------------------------------------------------------------------------
# Envelope metadata
# ---------------------------------------------------------------------------


def test_envelope_metadata_shape():
    pl, profile = _deisotoped()
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    env = pl[0].attributes["envelope"]

    assert set(env.keys()) == {
        "area", "sumint", "fwhm", "shape", "isotopes", "averagineType", "detected",
    }
    assert env["shape"] == "gaussian"
    assert env["area"] > 0.0
    assert env["sumint"] > 0.0
    assert env["fwhm"] > 0.0
    assert len(env["isotopes"]) >= 1
    # every isotope of this clean synthetic envelope was a detected peak
    assert env["detected"] == len(env["isotopes"])
    for mz, weight in env["isotopes"]:
        assert float(weight) >= 0.0
        assert float(mz) > 0.0


def test_envelope_isotope_mzs_are_ordered_and_spaced():
    charge = 2
    pl, profile = _deisotoped(charge=charge)
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    isotopes = pl[0].attributes["envelope"]["isotopes"]

    mzs = [float(mz) for mz, _ in isotopes]
    assert mzs == sorted(mzs)
    if len(mzs) >= 2:
        spacing = mzs[1] - mzs[0]
        assert spacing == pytest.approx(mspy.ISOTOPE_DISTANCE / charge, abs=0.03)


# ---------------------------------------------------------------------------
# Idempotency (key regression area)
# ---------------------------------------------------------------------------


def test_relabel_is_idempotent_on_isotope_positions():
    """Re-running labeling rebuilds the exact same isotope grid (stored-envelope path)."""
    pl, profile = _deisotoped()
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    first = list(pl[0].attributes["envelope"]["isotopes"])

    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    second = list(pl[0].attributes["envelope"]["isotopes"])

    assert_isotopes_equal(first, second)


def test_relabel_idempotent_area_stable():
    """Area stays stable across re-runs against the same profile."""
    pl, profile = _deisotoped()
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    area1 = pl[0].attributes["envelope"]["area"]
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    area2 = pl[0].attributes["envelope"]["area"]
    assert area2 == pytest.approx(area1, rel=1e-6)


def test_reconstruct_cluster_from_envelope_roundtrip():
    """_reconstruct_cluster_from_envelope rebuilds positions from stored metadata."""
    charge = 1
    diff = mspy.ISOTOPE_DISTANCE / charge
    parent = mspy.peak(mz=1000.0, ai=1000.0, charge=charge, isotope=0, fwhm=0.05)
    envelope = {
        "area": 100.0,
        "sumint": 200.0,
        "fwhm": 0.05,
        "shape": "gaussian",
        "isotopes": [(1000.0, 1.0), (1000.0 + diff, 0.6), (1000.0 + 2 * diff, 0.2)],
    }
    cluster = mpp._reconstruct_cluster_from_envelope(parent, envelope)

    assert [p.isotope for p in cluster] == [0, 1, 2]
    assert all(p.charge == charge for p in cluster)
    assert [round(p.mz, 6) for p in cluster] == [round(mz, 6) for mz, _ in envelope["isotopes"]]


def test_reconstruct_cluster_indexes_isotopes_by_mz_not_list_order():
    """A merged/irregular stored grid is indexed by m/z position, not list order.

    find-peaks' `_merge_adjacent_clusters` can fuse two overlapping envelopes into
    one stored shape with repeated m/z positions (e.g. [0,1,1,2,2,3] worth of
    peaks). If the rebuild numbered isotopes by list order ([0,1,2,3,4,5]) then
    `_cluster_weights` would look up the wrong theoretical weight per peak and the
    converted area would diverge from the picked one. The index must follow m/z.
    Also checks the exact fitted weight is carried on each peak (`_envweight`) so
    the overlap fit can reproduce the stored shape.
    """
    charge = 1
    diff = mspy.ISOTOPE_DISTANCE / charge
    mono = 981.5
    # two 3-isotope envelopes merged: positions repeat at isotope indices 0..3
    isotopes = [
        (mono, 1.0),
        (mono + diff, 0.7),
        (mono + diff, 0.6),
        (mono + 2 * diff, 0.4),
        (mono + 2 * diff, 0.3),
        (mono + 3 * diff, 0.1),
    ]
    parent = mspy.peak(mz=mono, ai=1000.0, charge=charge, isotope=0, fwhm=0.05)
    envelope = {"area": 50.0, "sumint": 100.0, "fwhm": 0.05,
                "shape": "gaussian", "isotopes": isotopes}

    cluster = mpp._reconstruct_cluster_from_envelope(parent, envelope)

    # indices track m/z (duplicate positions share an index), NOT 0..5 list order
    assert [p.isotope for p in cluster] == [0, 1, 1, 2, 2, 3]
    # the exact fitted weight is preserved per peak for the overlap fit
    assert [p.attributes["_envweight"] for p in cluster] == [w for _, w in isotopes]


# ---------------------------------------------------------------------------
# Tail length floor
# ---------------------------------------------------------------------------


def test_envelope_respects_min_length_floor():
    """A short detected cluster is extended to at least MIN_ENVELOPE_LENGTH isotopes."""
    charge = 1
    diff = mspy.ISOTOPE_DISTANCE / charge
    # Only two observed peaks, but the modeled envelope tail must reach the floor.
    peaks = [mspy.peak(mz=1500.0, ai=1000.0, fwhm=0.05),
             mspy.peak(mz=1500.0 + diff, ai=650.0, fwhm=0.05)]
    pl = mspy.peaklist(peaks)
    profile = mspy.profile(pl, fwhm=0.05, points=20)
    pl.deisotope(maxCharge=2, mzTolerance=0.05, intTolerance=0.6)
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)

    env = pl[0].attributes["envelope"]
    assert len(env["isotopes"]) >= mpp.MIN_ENVELOPE_LENGTH


def test_labelenvelopes_without_profile_still_produces_envelope():
    """No profile -> area falls back to peak-height estimate, no crash."""
    pl, _ = _deisotoped()
    pl.labelenvelopes(label="1st", signal=None, defaultFwhm=0.05, nonIdeality=0.4)
    env = pl[0].attributes["envelope"]
    assert env["area"] > 0.0


def test_relabelenvelopes_requires_peaklist_object():
    with pytest.raises(TypeError):
        mpp.relabelenvelopes([mspy.peak(mz=1000.0, charge=1, isotope=0)])


def test_relabelenvelopes_empty_returns_empty():
    out = mpp.relabelenvelopes(mspy.peaklist([]))
    assert len(out) == 0


# ---------------------------------------------------------------------------
# Envelope extent (how many isotopes are modelled)
# ---------------------------------------------------------------------------

# spectra/example_env4.msd: two species two Da apart, monoisotopic peaks and
# surrounding heights read off the real profile. Their masses differ by 0.2%, so
# averagine gives them the same theoretical pattern to three decimals -- they are
# equivalent species and must be modelled with equivalent envelopes.
_ENV4_ROWS = [
    (900.494, 1332.0), (901.506, 1333.0), (902.511, 1575.0),
    (903.510, 600.0), (904.509, 257.0), (905.509, 421.0),
]

_EXTENT_PARAMS = {
    "massTolerance": 0.05, "isotopeShift": 0.0, "maxCharge": 3,
    "intTolerance": 0.5, "labelEnvelope": "1st", "envelopeIntensity": "maximum",
    "envelopeNonIdeality": 0.40, "envelopeRefinePattern": 1, "seedCharge": 1,
}


def _extents(seeds, rows=_ENV4_ROWS):
    """Convert ``seeds`` to envelopes against a profile built from ``rows``.

    Returns {mono m/z: number of modelled isotopes}. The profile always holds ALL
    of ``rows``, so a species can be converted with or without its neighbour
    seeded while the neighbour's signal stays in the spectrum either way.
    """

    heights = dict(rows)
    profile = mspy.profile(
        mspy.peaklist([mspy.peak(mz=mz, ai=ai, fwhm=0.05) for mz, ai in rows]),
        fwhm=0.05, points=20,
    )
    peaklist = mspy.peaklist([
        mspy.peak(mz=mz, ai=heights[mz], charge=1, isotope=0, fwhm=0.05)
        for mz in seeds
    ])
    result = mpp.recalculate_neighborhood_envelopes(
        peaklist, profile, list(seeds), _EXTENT_PARAMS, selectedOnly=True
    )
    return {
        round(p.mz, 3): len(p.attributes["envelope"]["isotopes"])
        for p in result if p.attributes.get("envelope")
    }


def test_equivalent_species_get_equivalent_envelopes():
    """Two species of the same mass must be modelled with the same envelope.

    ``spectra/example_env4.msd``. 900.49 and 902.51 differ in mass by 0.2%, so
    averagine predicts the same isotope pattern for both to three decimals -- the
    data says nothing that would give one more isotopes than the other. Yet the
    extent used to be walked outward against the observed profile ("keep going
    while there is signal here"), which asks the wrong question: signal at a tail
    position is not evidence for THIS envelope unless this envelope could have
    produced it. So 900.49 was modelled with 5 isotopes -- its 4th and 5th, at 1.3%
    and 0.14% of its own apex, propped up by signal that is really 902.51's mono
    and +1 -- while 902.51 got 3, cut short by an unrelated peak rising at 905.5.
    The user saw one species drawn with five peaks and its twin with three.
    """

    extents = _extents([900.494, 902.511])

    assert len(extents) == 2
    assert len(set(extents.values())) == 1  # pre-fix: {900.494: 5, 902.511: 3}


def test_envelope_extent_ignores_a_neighbours_signal():
    """An envelope's extent must not change because a neighbour sits under its tail.

    The sharper form of the test above, and the invariant that makes it hold: the
    SAME species, converted with and without its neighbour seeded, is modelled with
    the same number of isotopes. The neighbour's peaks are in the profile either
    way, so anything that reads the raw profile to decide the extent will differ
    between the two -- pre-fix 900.49 came back with 5 isotopes and 902.51 with 3,
    whether or not the other was converted alongside.
    """

    together = _extents([900.494, 902.511])
    lowerAlone = _extents([900.494])
    upperAlone = _extents([902.511])

    assert lowerAlone[900.494] == together[900.494]
    assert upperAlone[902.511] == together[902.511]


def test_envelope_extent_grows_with_mass():
    """The modelled extent is a property of the SPECIES, not a per-spectrum constant.

    The averagine lambda is proportional to neutral mass, so a heavier envelope has
    more significant isotopes and must be modelled with more of them. (Files whose
    species span a narrow mass range all come out the same length, which is correct
    but easy to mistake for a fixed number.) The count also depends on the
    averagine model's carbon density, and -- since it is derived from the NEUTRAL
    mass -- not on the charge the species happens to be seen at.
    """

    def extent(mz, charge=1, averagine="protein"):
        peak = mspy.peak(mz=mz, ai=100.0, charge=charge, isotope=0, fwhm=0.05)
        return mpp._theory_envelope_length(peak, averagineType=averagine)

    lengths = [extent(mz) for mz in (900.0, 1500.0, 2340.0, 3650.0, 8000.0)]
    assert lengths == sorted(lengths)
    assert lengths[0] < lengths[-1]          # genuinely mass-dependent, not fixed
    # carbon-richer model -> heavier tail -> more isotopes at the same mass
    assert extent(3000.0, averagine="lipid") > extent(3000.0, averagine="carbohydrate")
    # the same neutral species is modelled identically at any charge
    assert extent(30000.0, charge=1) == extent(3000.0, charge=10)


def test_heavy_envelope_is_not_collapsed_to_the_minimum():
    """A species whose monoisotopic peak is below the cutoff still gets its envelope.

    Past roughly 13 kDa (protein; ~9.5 kDa for the carbon-richer lipid model) the
    envelope climbs to a mid-envelope apex before it decays, and the monoisotopic
    peak is itself under ``ENVELOPE_TAIL_SIGNIFICANCE`` of that apex. Counting the
    leading RUN of isotopes above the cutoff therefore stopped at index 0 and
    collapsed the whole envelope to ``MIN_ENVELOPE_LENGTH``. The cutoff may only
    decide where the tail ends: the isotopes between the mono and the apex belong
    to the envelope whatever their own size, since an envelope cannot have a gap.
    """

    heavy = mspy.peak(mz=25000.0, ai=100.0, charge=1, isotope=0, fwhm=0.05)
    pattern = mpp._cluster_pattern(heavy, 30)
    apex = max(pattern)

    # the premise: this species' mono really is below the cutoff
    assert pattern[0] < apex * mpp.ENVELOPE_TAIL_SIGNIFICANCE

    length = mpp._theory_envelope_length(heavy)
    assert length > mpp.MIN_ENVELOPE_LENGTH        # pre-fix it was exactly 3
    # it runs out to the last significant isotope, and stops there
    assert pattern[length - 1] >= apex * mpp.ENVELOPE_TAIL_SIGNIFICANCE
    assert all(w < apex * mpp.ENVELOPE_TAIL_SIGNIFICANCE for w in pattern[length:])


def test_envelope_extent_matches_the_theoretical_significance_cutoff():
    """The extent is exactly the theoretically significant part of the pattern.

    Pins the rule down: every isotope carrying at least
    ``ENVELOPE_TAIL_SIGNIFICANCE`` of the envelope's apex is modelled, and nothing
    beyond it. Anything fainter cannot move the fitted area, while the claim it
    would stake on whatever m/z it lands on is real -- which is how the old 0.05%
    cutoff let a tail wander onto a neighbour.
    """

    extents = _extents([900.494, 902.511])

    seed = mspy.peak(mz=900.494, ai=1332.0, charge=1, isotope=0, fwhm=0.05)
    pattern = mpp._cluster_pattern(seed, 30)
    apex = max(pattern)
    expected = sum(1 for w in pattern if w >= apex * mpp.ENVELOPE_TAIL_SIGNIFICANCE)

    assert expected >= mpp.MIN_ENVELOPE_LENGTH
    assert extents[900.494] == expected


def _with_stored_grid(mz, ai, positions):
    """A converted peak carrying a stored envelope grid at ``positions``."""

    peak = mspy.peak(mz=mz, ai=ai, charge=1, isotope=0, fwhm=0.05)
    weights = mpp._poisson_weights(list(range(len(positions))), 0.43)
    peak.attributes["envelope"] = {
        "area": 1.0, "sumint": ai, "fwhm": 0.05, "shape": "gaussian",
        "isotopes": [(p, w) for p, w in zip(positions, weights, strict=True)],
    }
    return peak


def test_reconvert_rebuilds_a_stale_stored_grid():
    """Converting again applies the CURRENT method, it does not replay the saved one.

    A converted envelope stores its isotope grid, and the grid is reused verbatim
    so conversion stays idempotent. But that also froze envelopes built by an older
    method: on ``spectra/example_env4.msd`` -- 900.49 saved with 5 isotopes (its
    tail had walked onto 902.51's peaks) and 902.51 with 3 (cut short by an
    unrelated peak above it) -- "Convert All to Envelopes" faithfully reproduced
    the old mismatched pair. The only way to get a correct envelope was to delete
    the peak and label it again, which is not something a user should have to
    discover. A grid that disagrees with the current method is stale: rebuild it.
    """

    heights = dict(_ENV4_ROWS)
    profile = mspy.profile(
        mspy.peaklist([mspy.peak(mz=mz, ai=ai, fwhm=0.05) for mz, ai in _ENV4_ROWS]),
        fwhm=0.05, points=20,
    )
    # the two grids exactly as the old method saved them
    peaklist = mspy.peaklist([
        _with_stored_grid(900.494, heights[900.494],
                          [900.494, 901.506, 902.511, 903.510, 904.509]),
        _with_stored_grid(902.511, heights[902.511],
                          [902.511, 903.510, 904.509]),
    ])

    result = mpp.recalculate_neighborhood_envelopes(
        peaklist, profile, [900.494, 902.511], _EXTENT_PARAMS, selectedOnly=True
    )
    extents = {
        round(p.mz, 3): len(p.attributes["envelope"]["isotopes"])
        for p in result if p.attributes.get("envelope")
    }

    seed = mspy.peak(mz=900.494, ai=heights[900.494], charge=1, isotope=0, fwhm=0.05)
    expected = mpp._theory_envelope_length(seed)
    assert extents == {900.494: expected, 902.511: expected}


def test_reconvert_keeps_detected_isotopes_beyond_the_theoretical_tail():
    """A grid longer than theory is kept only where the extra isotopes were DETECTED.

    Theory alone cannot settle this. On the measured files the isotope that must
    be DROPPED (example_env5's 1002.43, saved with six isotopes whose last two sit
    on noise) carries 0.84% of its apex, while the one that must be KEPT here is
    smaller still at 0.39% -- so no significance cutoff separates them. The
    difference is that one was a real detected peak and the other was tail an
    older method walked onto the neighbouring noise, and after conversion the
    isotope peaks are gone from the list, so a rebuild can never re-derive it.
    That is what the recorded ``detected`` count is for.
    """

    pl, profile = _deisotoped()
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    stored = list(pl[0].attributes["envelope"]["isotopes"])
    detected = pl[0].attributes["envelope"]["detected"]

    # deisotoping really did find more isotopes than the theoretical extent
    assert detected == len(stored) > mpp._theory_envelope_length(pl[0])

    # re-labelling keeps them: they are evidence, not a modelled tail
    pl.labelenvelopes(label="1st", signal=profile, defaultFwhm=0.05, nonIdeality=0.4)
    assert_isotopes_equal(stored, pl[0].attributes["envelope"]["isotopes"])


def test_reconvert_rebuilds_a_long_grid_with_no_detection_record():
    """An over-long grid from before the count existed is rebuilt to theory.

    ``spectra/example_env5_failed.msd``: 1002.43 was saved with six isotopes by the
    old profile-walked tail, the last two sitting on noise between neighbouring
    species. Such a grid reports no ``detected`` count, so only its monoisotopic
    peak is known to be real and it is measured against the plain theoretical
    extent -- which is what strips the invented tail.
    """

    heights = dict(_ENV4_ROWS)
    profile = mspy.profile(
        mspy.peaklist([mspy.peak(mz=mz, ai=ai, fwhm=0.05) for mz, ai in _ENV4_ROWS]),
        fwhm=0.05, points=20,
    )
    # a legacy grid: two isotopes longer than theory, and no "detected" key
    stale = _with_stored_grid(
        900.494, heights[900.494],
        [900.494, 901.506, 902.511, 903.510, 904.509, 905.509],
    )
    assert "detected" not in stale.attributes["envelope"]

    result = mpp.recalculate_neighborhood_envelopes(
        mspy.peaklist([stale]), profile, [900.494], _EXTENT_PARAMS, selectedOnly=True
    )
    envelope = next(p.attributes["envelope"] for p in result)

    seed = mspy.peak(mz=900.494, ai=heights[900.494], charge=1, isotope=0, fwhm=0.05)
    assert len(envelope["isotopes"]) == mpp._theory_envelope_length(seed)
