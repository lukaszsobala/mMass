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


def test_non_ideality_changes_area_of_non_averagine_envelope():
    """nonIdeality must actually move the area of an isolated non-averagine peak.

    The area is the amplitude of the fitted isotope model, not a raw integral of
    the data, so a shape allowed to bend toward a non-averagine profile (here the
    +1 isotope is far taller than averagine predicts) captures more of the peak
    and yields a larger area. With no flex the rigid averagine model under-fits
    the inflated isotope and reports a smaller area. If the two were equal the
    parameter would be inert -- which is the bug this guards against.
    """

    # +1 isotope deliberately inflated well above the averagine expectation
    cluster = _cluster_at(1000.0, 1, 1000.0, weights=[1.0, 0.95, 0.30, 0.05])
    profile = _profile(cluster)

    rigid = mpp._fit_envelope_areas([cluster], profile, 0.05, nonIdeality=0.0)[0]
    flexible = mpp._fit_envelope_areas([cluster], profile, 0.05, nonIdeality=0.5)[0]

    assert rigid > 0.0
    assert flexible > rigid * 1.05  # at least a few % larger -- the knob works


def test_non_ideality_reacts_for_converted_isolated_envelope():
    """nonIdeality must move an ISOLATED envelope's area even on the convert route.

    A converted (or re-labelled) envelope carries its previously fitted shape on
    each peak (`_envweight`), so `_fit_group_areas` sees a stored shape. Reusing
    that shape verbatim for an isolated envelope froze it and made nonIdeality a
    no-op -- the user's bug: after deleting a neighbour the survivor is isolated,
    but re-converting it at any nonIdeality gave the same area. An isolated
    envelope on a regular single-species grid must instead re-soft-model at the
    current nonIdeality (the stored shape is not reused), exactly as a fresh
    find-peaks pass would, so the setting takes effect.
    """

    # non-averagine DATA (inflated +1), with a stored (regular-grid) shape attached
    # to every peak so the convert route's storedShape branch is exercised
    cluster = _cluster_at(1000.0, 1, 1000.0, weights=[1.0, 0.95, 0.30, 0.05])
    for peak, weight in zip(cluster, mpp._cluster_weights(cluster), strict=True):
        peak.attributes["_envweight"] = float(weight)
    profile = _profile(cluster)

    rigid = mpp._fit_envelope_areas([cluster], profile, 0.05, nonIdeality=0.0)[0]
    flexible = mpp._fit_envelope_areas([cluster], profile, 0.05, nonIdeality=0.5)[0]

    assert rigid > 0.0
    # the stored shape no longer freezes the area: nonIdeality genuinely moves it
    assert flexible > rigid * 1.05


def test_is_regular_isotope_grid_distinguishes_merged_from_single():
    """The regular-grid test tells a single species from a merged representative.

    A clean single-species envelope has strictly increasing, roughly uniform
    isotope spacing; a merged representative (overlapping species collapsed onto
    one peak) carries duplicated/irregular positions. This gate is what routes an
    isolated envelope to re-soft-modelling (regular) while keeping a merged one on
    its stored shape (irregular), so nonIdeality applies to the former only.
    """

    single = [(1000.0, 0.5), (1001.0, 0.3), (1002.0, 0.15), (1003.0, 0.05)]
    assert mpp._is_regular_isotope_grid(single)
    # a merged pair: two species' isotopes interleave and some coincide
    merged = [(906.47, 0.3), (907.47, 0.3), (909.49, 0.2), (909.49, 0.1), (910.50, 0.1)]
    assert not mpp._is_regular_isotope_grid(merged)
    # trivial grids are treated as regular (nothing to merge)
    assert mpp._is_regular_isotope_grid([(1000.0, 1.0)])
    assert mpp._is_regular_isotope_grid([])


def test_non_ideality_is_inert_for_overlapping_envelopes():
    """nonIdeality must NOT move overlapping areas -- crowds use theoretical ratios.

    The complement of the test above: a flexing isotope shape in a crowd could
    bend a tail onto a neighbour's peak and claim its signal, so overlapping
    (K>1) envelopes are held to the rigid averagine pattern and nonIdeality is
    deliberately inert. Only isolated (K==1) envelopes soft-shape. This guards the
    K==1/K>1 boundary in `_fit_group_areas` (if soft-shaping ever leaked into the
    overlap branch these areas would drift with the knob).
    """
    a = _averagine_cluster(1000.0, 1, 100.0)
    b = _averagine_cluster(1001.0, 1, 100.0)
    profile = _profile(a, b)

    rigid = mpp._fit_envelope_areas([a, b], profile, 0.05, nonIdeality=0.0)
    flexed = mpp._fit_envelope_areas([a, b], profile, 0.05, nonIdeality=1.0)

    assert all(r > 0.0 for r in rigid)
    for r, f in zip(rigid, flexed, strict=True):
        assert f == pytest.approx(r, abs=1e-9)


# ---------------------------------------------------------------------------
# Averagine model selection
# ---------------------------------------------------------------------------


def test_averagine_models_registered():
    """The three selectable averagine models exist with distinct lambda factors."""
    assert set(mpp.AVERAGINE_MODELS) == {"protein", "carbohydrate", "lipid"}
    assert mpp.DEFAULT_AVERAGINE == "protein"
    # carbon density drives the +1 isotope rate: lipid > protein > carbohydrate
    assert (
        mpp._averagine_lambda("carbohydrate")
        < mpp._averagine_lambda("protein")
        < mpp._averagine_lambda("lipid")
    )


def test_averagine_type_changes_isotope_weights():
    """A heavy cluster's modeled isotope weights depend on the averagine model.

    The carbon-rich lipid model predicts a heavier (later-peaking) envelope than
    protein, while the oxygen-rich carbohydrate model predicts a lighter one, so
    the +1/mono ratio orders carbohydrate < protein < lipid. If the type were
    ignored the three would be identical -- the bug this guards against.
    """
    cluster = _cluster_at(2500.0, 1, 1000.0, weights=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    ratio = {}
    for averagine in ("protein", "carbohydrate", "lipid"):
        w = mpp._cluster_weights(cluster, averagineType=averagine)
        ratio[averagine] = w[1] / w[0]
    assert ratio["carbohydrate"] < ratio["protein"] < ratio["lipid"]


def test_averagine_type_moves_fitted_area():
    """The fitted envelope area responds to the selected averagine model."""
    cluster = _cluster_at(1500.0, 1, 1000.0)
    profile = _profile(cluster)
    areas = {
        averagine: mpp._fit_envelope_areas(
            [cluster], profile, 0.05, nonIdeality=0.2, averagineType=averagine
        )[0]
        for averagine in ("protein", "carbohydrate", "lipid")
    }
    assert all(a > 0.0 for a in areas.values())
    # the carbon-rich lipid model captures a different area than protein
    assert areas["lipid"] != pytest.approx(areas["protein"], rel=0.01)


# ---------------------------------------------------------------------------
# Unimodality guard (wide non-ideality band)
# ---------------------------------------------------------------------------


def _is_unimodal(weights, tol=1e-9):
    """True if weights rise (weakly) to a peak then fall -- no interior notch."""
    peak = int(numpy.argmax(weights))
    rising = all(weights[i] <= weights[i + 1] + tol for i in range(peak))
    falling = all(weights[i] >= weights[i + 1] - tol for i in range(peak, len(weights) - 1))
    return rising and falling


def test_project_unimodal_removes_notch_and_conserves_area():
    """A notched sequence is projected to a unimodal one with the same sum."""
    notched = numpy.array([1.0, 0.2, 0.7, 0.3, 0.05])  # dip at index 1
    fitted = mpp._project_unimodal(notched)
    assert _is_unimodal(fitted)
    assert float(numpy.sum(fitted)) == pytest.approx(float(numpy.sum(notched)))


def test_project_unimodal_leaves_monotone_input_untouched():
    """An already-unimodal envelope must pass through unchanged."""
    good = numpy.array([1.0, 0.6, 0.3, 0.1])
    fitted = mpp._project_unimodal(good)
    assert fitted == pytest.approx(good)


def test_soft_model_stays_unimodal_at_full_non_ideality():
    """At nonIdeality=1.0 a mid-envelope notch in the data is repaired.

    The observed profile dips hard at the +1 isotope (noise or an interfering
    species), which a wide non-ideality band would otherwise carve straight into
    the modeled envelope. The unimodality guard must keep the fitted weights a
    plausible single-species pattern -- monotone down from the monoisotope here --
    while conserving the total (sum 1) so the area stays meaningful.
    """

    theory = [(1000.0, 1.0), (1001.0, 0.6), (1002.0, 0.3), (1003.0, 0.1)]
    x = numpy.linspace(999.5, 1003.5, 400)
    sigma = mpp._fwhm_to_sigma(0.05)
    heights = [1.0, 0.05, 0.35, 0.09]  # deep notch at +1
    y = numpy.zeros_like(x)
    for (mz, _), h in zip(theory, heights, strict=True):
        y += h * numpy.exp(-0.5 * ((x - mz) / sigma) ** 2)

    fitted = mpp._soft_isotope_model(theory, x, y, 0.05, nonIdeality=1.0)
    weights = numpy.array([w for _, w in fitted])

    assert _is_unimodal(weights)
    assert float(numpy.sum(weights)) == pytest.approx(1.0, abs=1e-6)


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


def _averagine_cluster(mono, charge, area, fwhm=0.05, n=6):
    """Cluster whose isotope heights follow averagine, so basis == data shape."""
    weights = mpp._cluster_weights(
        [mspy.peak(mz=mono + i * mspy.ISOTOPE_DISTANCE / charge,
                   charge=charge, isotope=i, fwhm=fwhm)
         for i in range(n)]
    )
    diff = mspy.ISOTOPE_DISTANCE / charge
    return [
        mspy.peak(mz=mono + i * diff, ai=w * area, charge=charge, isotope=i, fwhm=fwhm)
        for i, w in enumerate(weights)
    ]


def test_equal_overlapping_envelopes_are_apportioned_globally():
    """Three equal envelopes one Da apart recover near-equal areas.

    This is the crowded-region regression: the +1/+2 isotopes of the lower-m/z
    species land exactly on the monoisotopic peaks of the higher-m/z ones. A
    greedy fit that lets the lower-m/z envelope claim the shared signal first
    over-estimated the low end and robbed the high end (historically ~108/103/83
    for equal inputs). The joint, overlap-aware fit must split it evenly.
    """
    clusters = [_averagine_cluster(m, 1, 100.0) for m in (1000.0, 1001.0, 1002.0)]
    profile = _profile(*clusters)
    areas = mpp._fit_envelope_areas(clusters, profile, 0.05, 0.2)

    assert all(a > 0.0 for a in areas)
    # every envelope within 10% of the others -- no lower-m/z precedence
    assert max(areas) / min(areas) == pytest.approx(1.0, abs=0.12)
    # in particular the highest-m/z envelope is not robbed
    assert areas[2] / areas[0] == pytest.approx(1.0, abs=0.1)


def test_shared_peak_is_split_not_stolen_by_lower_mz():
    """A peak shared by a lower species' isotope and a higher species' mono is
    fairly split, and the lower species does not over-claim it.

    Three overlapping charge-1 envelopes two Da apart (the example_env.msd layout):
    each species' +2 isotope lands on the next species' monoisotopic peak. The
    fair, abundance-independent split must (a) NOT let the lower-m/z envelope take
    the whole shared peak -- which would push its area up and rob the higher-m/z
    ones ("the earlier peaks steal from the later ones") -- and (b) keep the summed
    decomposition within the observed profile at that shared peak, so the parts add
    up to the whole rather than exceeding it.
    """
    clusters = [_averagine_cluster(m, 1, 100.0, fwhm=0.11) for m in (1000.0, 1002.0, 1004.0)]
    profile = _profile(*clusters, fwhm=0.11)
    areas, shapes = mpp._fit_envelope_areas_shaped(clusters, profile, 0.11, 0.2)

    # equal inputs -> near-equal areas; the lowest-m/z envelope is NOT the biggest
    assert max(areas) / min(areas) < 1.15
    assert areas[0] <= max(areas) * 1.02  # the lower-m/z one has not over-claimed

    # at the shared peak (envelope 1's mono == envelope 0's +2 position) the summed
    # reconstructed model must not exceed the observed profile: the two contributors
    # split it, they do not each take it whole
    x = profile[:, 0]
    y = profile[:, 1]
    sigma = mpp._fwhm_to_sigma(0.11)
    norm = sigma * numpy.sqrt(2 * numpy.pi)
    model = numpy.zeros_like(x)
    for area, shape in zip(areas, shapes, strict=True):
        for mz, w in shape:
            model += (area * w / norm) * numpy.exp(-0.5 * ((x - mz) / sigma) ** 2)
    shared_mz = 1002.0
    i = int(numpy.argmin(numpy.abs(x - shared_mz)))
    # within a small tolerance of the observed peak, never well above it
    assert model[i] <= y[i] * 1.03


def test_edge_envelope_does_not_claim_untracked_neighbour_forest():
    """The highest-m/z envelope must not inflate by claiming an untracked forest.

    Real crowded spectra continue past the selected envelopes: to the right of the
    highest fitted envelope sit further species whose peaks are NOT among the
    clusters being fit. The abundance-independent apportionment alone hands that
    clear right-hand signal wholesale to the highest envelope (nothing competes
    for it there), inflating its area several-fold over its equal-height
    neighbours. The per-envelope apex cap -- a modelled envelope may not rise above
    the observed signal at its own isotope peaks -- holds it to a fair share.

    This is the example_env.msd regression: three similar-height overlapping lipid
    envelopes where the highest read ~2.4x its siblings. The earlier "equal
    overlapping" test missed it because its profile contained ONLY the fitted
    clusters, leaving the highest envelope's right side empty; here the forest is
    built with every isotope of every species (the latter isotopes are exactly
    what the edge envelope over-claims, so they must not be skipped).
    """
    # six equal envelopes two Da apart (charge 1): every even isotope of a lower
    # species lands on a higher species' monoisotopic peak -- a dense forest
    forest = [_averagine_cluster(1000.0 + 2.0 * k, 1, 100.0, fwhm=0.11) for k in range(6)]
    profile = _profile(*forest, fwhm=0.11)

    # fit only the first three; the remaining three are the untracked forest to
    # the right of the highest fitted envelope
    fitted = forest[:3]
    areas = mpp._fit_envelope_areas(fitted, profile, 0.11, 0.2)

    assert all(a > 0.0 for a in areas)
    # equal inputs -> near-equal areas; the highest-m/z envelope must NOT be
    # inflated by the forest on its right (pre-fix it read ~2.9x the lowest)
    assert areas[2] / areas[0] < 1.25
    assert max(areas) / min(areas) < 1.25


def test_unequal_overlapping_envelopes_keep_their_order():
    """A more abundant envelope still gets the larger area (ordering preserved).

    The apportionment weighs each envelope's monoisotopic peak equally with a
    neighbour's overlapping isotope (independent of absolute abundance), so the
    1:2 ratio is deliberately compressed toward equal rather than recovered
    exactly -- that is the "treat them equally" behaviour. What must still hold is
    that the genuinely larger species gets the larger area, and neither is robbed.
    """
    a = _averagine_cluster(1000.0, 1, 100.0)
    b = _averagine_cluster(1001.0, 1, 200.0)
    areas = mpp._fit_envelope_areas([a, b], _profile(a, b), 0.05, 0.2)
    assert areas[0] > 0.0
    assert areas[1] > areas[0]  # the 2x species keeps the larger area


def test_small_envelope_under_large_neighbour_keeps_fair_share():
    """A small species nested under a large neighbour's isotope keeps a fair share.

    The user can add a peak whose monoisotopic m/z lands on the +1 isotope of a
    much larger lower-m/z envelope (e.g. a +1 charge species one Da apart). A
    least-squares or abundance-weighted fit lets the big envelope's averagine tail
    claim all of the shared signal and drives the smaller envelope's area to zero
    -- silently discarding a peak the user labelled. The area-independent
    apportionment instead splits the shared peak by pattern shape alone, so the
    labelled envelope keeps a substantial, clearly non-zero share no matter how
    tall its neighbour is.
    """

    big = _averagine_cluster(1000.0, 1, 1000.0)
    small = _averagine_cluster(1001.0, 1, 80.0)  # real, independent, much smaller
    profile = _profile(big, small)

    areas = mpp._fit_envelope_areas([big, small], profile, 0.05, 0.2)

    assert areas[0] > 0.0
    # not robbed: the labelled envelope keeps a meaningful fraction of the big one
    assert areas[1] / areas[0] > 0.2


def test_small_neighbour_isotope_does_not_rob_large_envelope_mono():
    """A tiny envelope's isotope must not steal a large envelope's monoisotopic peak.

    The mirror of the test above, and the ``spectra/example_env2.msd`` regression:
    the user adds a small peak two Da *below* a much larger envelope (charge 1), so
    the small species' +2 isotope lands exactly on the large species' monoisotopic
    peak. Under a purely abundance-independent (equal-weight) split the tiny
    envelope is handed an equal share of that big peak -- far more than its own
    small pattern could account for (a ~1-3% contributor claiming ~25-30% of the
    peak) -- and the large envelope's area collapses (in the file it dropped from
    ~44 to ~31). The observed peak must instead equal the *sum* of what each
    envelope actually contributes there: the small species' +2 (a few percent) plus
    the large species' mono (the rest). So the large envelope keeps essentially all
    of its area, the small one keeps only its small fair share, and the two add up
    to the peak without exceeding it.
    """

    # small two Da below big (charge 1): small's +2 == big's mono at 1802.0. A
    # moderate mass gives the small a non-trivial +2, so equal-weight over-crediting
    # is severe (big robbed to ~0.74 of its isolated area pre-fix).
    small = _averagine_cluster(1800.0, 1, 30.0, fwhm=0.11)
    big = _averagine_cluster(1802.0, 1, 1000.0, fwhm=0.11)
    profile = _profile(small, big, fwhm=0.11)

    big_alone = mpp._fit_envelope_areas([big], profile, 0.11, 0.2)[0]
    areas, shapes = mpp._fit_envelope_areas_shaped([small, big], profile, 0.11, 0.2)

    # the big envelope is NOT robbed by its tiny neighbour: it keeps essentially all
    # of the area it has when fitted alone (pre-fix it dropped to ~0.74)
    assert areas[1] >= big_alone * 0.90
    # the small envelope is kept (not discarded) but only claims its small fair
    # share -- consistent with its own ~3% pattern, not an equal split of the peak
    assert areas[0] > 0.0
    assert areas[0] < areas[1] * 0.08

    # totals check out at the shared peak (big's mono == small's +2): the summed
    # reconstruction equals the observed peak -- the parts add up to the whole and
    # never exceed it
    x = profile[:, 0]
    y = profile[:, 1]
    sigma = mpp._fwhm_to_sigma(0.11)
    norm = sigma * numpy.sqrt(2 * numpy.pi)
    model = numpy.zeros_like(x)
    for area, shape in zip(areas, shapes, strict=True):
        for mz, w in shape:
            model += (area * w / norm) * numpy.exp(-0.5 * ((x - mz) / sigma) ** 2)
    i = int(numpy.argmin(numpy.abs(x - 1802.0)))
    assert model[i] <= y[i] * 1.03          # never invents signal above the peak
    assert model[i] >= y[i] * 0.90          # the parts genuinely add up to the whole
    # and nowhere in the region does the summed model exceed the observed curve
    assert numpy.max(model - y) <= 0.03 * numpy.max(y)


def test_overlapping_model_never_exceeds_observed_curve():
    """The summed envelope model stays within the observed profile (mass conserving).

    Apportionment must divide the available signal, never invent extra: the sum of
    all fitted envelopes, reconstructed on the profile grid, may not rise above the
    observed curve. This is what guarantees every envelope area "fits within the
    available area".
    """

    clusters = [_averagine_cluster(m, 1, 100.0) for m in (1000.0, 1001.0, 1002.0)]
    profile = _profile(*clusters)
    areas = mpp._fit_envelope_areas(clusters, profile, 0.05, 0.2)

    x = profile[:, 0]
    model = numpy.zeros_like(x)
    for cluster, area in zip(clusters, areas, strict=True):
        weights = mpp._cluster_weights(cluster)
        sigma = mpp._fwhm_to_sigma(0.05)
        for p, w in zip(cluster, weights, strict=True):
            model += (area * w / (sigma * numpy.sqrt(2 * numpy.pi))) * numpy.exp(
                -0.5 * ((x - p.mz) / sigma) ** 2
            )

    # allow a small numerical tolerance relative to the peak height
    assert numpy.max(model - profile[:, 1]) <= 0.02 * numpy.max(profile[:, 1])


def test_overlapping_areas_sum_to_curve_integral():
    """Overlapping envelope areas sum to the area under the curve, not above it.

    Stronger than the pointwise check above: the *total* fitted area (which is
    what the peaklist reports and sums) must equal the integral under the observed
    profile over the envelope region -- never exceed it. A least-squares amplitude
    of rigid averagine columns overshoots the integral (~5% for a crowded run)
    even while staying within the curve at every single point, silently
    double-counting the shared signal. For overlapping envelopes the area is the
    apportioned share of the observed integral, so the sum is conserved.
    """
    clusters = [_averagine_cluster(m, 1, 100.0) for m in (1000.0, 1001.0, 1002.0)]
    profile = _profile(*clusters)
    areas = mpp._fit_envelope_areas(clusters, profile, 0.05, 0.2)

    x = profile[:, 0]
    y = numpy.clip(profile[:, 1], 0.0, None)
    lo = min(p.mz for c in clusters for p in c) - 1.0
    hi = max(p.mz for c in clusters for p in c) + 1.0
    mask = (x >= lo) & (x <= hi)
    curve_integral = numpy.trapezoid(y[mask], x[mask])

    total_area = sum(areas)
    # the summed area matches the curve integral (mass conserving) and, crucially,
    # does not exceed it
    assert total_area == pytest.approx(curve_integral, rel=0.03)
    assert total_area <= curve_integral * 1.01


@pytest.mark.parametrize("nonIdeality", [0.0, 0.2, 0.4])
def test_isolated_envelope_area_capped_by_observed_curve(nonIdeality):
    """An isolated envelope's area can never exceed the area under its own curve.

    In a crowded region a tall peak from a *different* species can land on one of
    an isolated envelope's isotope positions (e.g. mis-absorbed as its +1 isotope
    during deisotoping). A plain least-squares amplitude then inflates to explain
    that peak, and the reported area shoots far above the signal actually present
    -- the rendered envelope pokes high above the profile and the summed areas run
    above the area under the curve (the user-reported regression). The apex cap
    must hold the fitted amplitude under the observed curve.

    Tested over the usual nonIdeality range. At the *maximum* setting the isolated
    soft-model is deliberately allowed to bend all the way onto the data (an
    isolated envelope is trusted to be whatever the profile shows, since nothing
    overlaps it to steal from), so it treats the tall +1 as a genuine isotope and
    the cap no longer fights it -- that is intended shape freedom, exercised
    elsewhere, not a mass-conservation guard.
    """

    diff = mspy.ISOTOPE_DISTANCE  # charge 1
    mono = 1068.459
    # mono is a modest peak; the +1 position carries a tall contaminant (3.5x mono)
    heights = [17.0, 60.0, 8.0, 3.0]
    cluster = [
        mspy.peak(mz=mono + i * diff, ai=h, charge=1, isotope=i, fwhm=0.136)
        for i, h in enumerate(heights)
    ]
    profile = mspy.profile(mspy.peaklist(cluster), fwhm=0.136, points=20)
    curve_integral = numpy.trapezoid(numpy.clip(profile[:, 1], 0.0, None), profile[:, 0])

    area = mpp._fit_envelope_areas([cluster], profile, 0.136, nonIdeality)[0]

    # the hard invariant: never invent mass beyond what the curve holds
    assert area <= curve_integral * 1.01
    # and it must be anchored near the honest mono-implied area (~4), not the
    # ~9-13 a raw least-squares fit reports when it swallows the contaminant
    weights = mpp._cluster_weights(cluster)
    sigma = mpp._fwhm_to_sigma(0.136)
    mono_area = 17.0 / weights[0] * sigma * numpy.sqrt(2 * numpy.pi)
    assert area <= mono_area * 2.5


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
