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
