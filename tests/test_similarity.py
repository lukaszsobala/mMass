"""Spectrum similarity (mod_similarity) and grouping (mod_grouping).

All spectra are synthetic: Gaussian peaks on a noisy profile, with an optional
broad baseline hump, a precursor m/z and a polarity.
"""

import numpy
import pytest

import mspy
from mspy import mod_stopper
from mspy import mod_grouping, mod_similarity


def make_scan(
    peaks,
    lo=50.0,
    hi=1000.0,
    precursor=None,
    polarity=1,
    noise=0.05,
    hump=0.0,
    seed=0,
    fwhm=0.12,
    step=0.02,
    title="s",
):
    """A scan whose profile holds `peaks` [(mz, height), ...] on noise."""

    rng = numpy.random.default_rng(seed)
    x = numpy.arange(lo, hi, step)
    y = numpy.abs(rng.normal(0, noise, len(x)))
    if hump:
        y += hump * numpy.exp(-0.5 * ((x - 0.5 * (lo + hi)) / (0.2 * (hi - lo))) ** 2)
    sigma = fwhm / 2.3548
    for mz, h in peaks:
        k = (x > mz - 5 * sigma) & (x < mz + 5 * sigma)
        y[k] += h * numpy.exp(-0.5 * ((x[k] - mz) / sigma) ** 2)
    s = mspy.scan(profile=numpy.column_stack([x, y]))
    s.precursorMZ = precursor
    s.polarity = polarity
    s.title = title
    return s


def random_peaks(seed, lo, hi, count=25):
    rng = numpy.random.default_rng(seed)
    return [
        (float(m), float(h))
        for m, h in zip(
            rng.uniform(lo, hi, count), rng.uniform(2, 20, count), strict=True
        )
    ]


# ---------------------------------------------------------------------------
# similarity
# ---------------------------------------------------------------------------


def test_identical_spectra_score_one():
    peaks = random_peaks(1, 100, 900)
    a = make_scan(peaks, seed=1)
    b = make_scan(peaks, seed=2)  # same peaks, different noise
    res = mspy.similaritymatrix([a, b])
    assert res.similarity[0, 1] > 0.9


def test_unrelated_spectra_score_near_zero():
    scans = [make_scan(random_peaks(10 + k, 100, 900), seed=k) for k in range(6)]
    res = mspy.similaritymatrix(scans)
    off = res.similarity[numpy.triu_indices(6, 1)]
    assert abs(off.mean()) < 0.1
    assert off.max() < 0.3


def test_range_does_not_drive_similarity():
    """The same fragments, one spectrum with a much longer range."""

    shared = [(150.0, 10.0), (230.5, 6.0), (311.2, 8.0), (402.7, 5.0)]
    short = make_scan(shared, hi=520, precursor=512.0, seed=1)
    long_ = make_scan(
        shared + random_peaks(5, 560, 980, 15), hi=1100, precursor=1003.0, seed=2
    )
    other = make_scan(random_peaks(7, 100, 500, 4), hi=520, precursor=515.0, seed=3)
    res = mspy.similaritymatrix([short, long_, other], axes="mz")
    assert res.similarity[0, 1] > 0.7
    assert abs(res.similarity[0, 2]) < 0.25


def test_shared_baseline_and_noise_do_not_create_similarity():
    a = make_scan(random_peaks(20, 100, 900), hump=30.0, noise=1.0, seed=1)
    b = make_scan(random_peaks(21, 100, 900), hump=30.0, noise=1.0, seed=2)
    res = mspy.similaritymatrix([a, b])
    assert abs(res.similarity[0, 1]) < 0.2


def test_neutral_losses_link_different_precursors():
    """Two precursors 28 Da apart, sharing only their losses of 59 and 183."""

    def frag(P, seed):
        # the losses dominate, as P - 59 does in phosphocholine lipid spectra
        return make_scan(
            [(P - 59.0735, 40.0), (P - 183.066, 25.0)]
            + random_peaks(seed, 100, 500, 2),
            hi=P + 20,
            precursor=P,
            seed=seed,
        )

    a, b = frag(800.0, 31), frag(828.0, 32)
    both = mspy.similaritymatrix([a, b], axes="both").similarity[0, 1]
    mz_only = mspy.similaritymatrix([a, b], axes="mz").similarity[0, 1]
    loss_only = mspy.similaritymatrix([a, b], axes="loss").similarity[0, 1]
    # a shared loss counts once on the loss axis, while the same ions sit at
    # different m/z: about half of each spectrum's signal is shared
    assert abs(mz_only) < 0.1
    assert loss_only > 0.4
    assert both > mz_only + 0.15


def test_polarities_are_not_compared_unless_neutral_mass():
    glycans = [700.0, 862.05, 1024.1, 1186.16]  # neutral masses
    pos = make_scan(
        [(m + 22.989218, 10.0) for m in glycans], hi=1300, polarity=1, seed=1
    )
    neg = make_scan(
        [(m - 1.007276, 10.0) for m in glycans], hi=1300, polarity=-1, seed=2
    )
    pos2 = make_scan(
        [(m + 22.989218, 10.0) for m in glycans], hi=1300, polarity=1, seed=3
    )
    res = mspy.similaritymatrix([pos, neg, pos2])
    assert numpy.isnan(res.similarity[0, 1])
    assert not res.comparable[0, 1]
    assert res.similarity[0, 2] > 0.8
    neutral = mspy.similaritymatrix(
        [pos, neg], neutralMass=True, posAdduct="Na", negAdduct="H"
    )
    assert neutral.similarity[0, 1] > 0.8


def test_peak_source_uses_peaklist():
    a = make_scan([], seed=1)
    b = make_scan([], seed=2)
    for s in (a, b):
        s.peaklist = mspy.peaklist(
            [
                mspy.peak(mz=m, ai=h)
                for m, h in [(200.0, 10.0), (350.0, 5.0), (512.3, 8.0)]
            ]
        )
    res = mspy.similaritymatrix([a, b], source="peaks")
    assert res.similarity[0, 1] > 0.9


def test_unknown_parameter_is_rejected():
    with pytest.raises(ValueError):
        mspy.similarityparams(tolerence=0.2)


def test_bootstrap_is_deterministic_with_a_seed():
    scans = [make_scan(random_peaks(40 + k, 100, 900), seed=k) for k in range(4)]
    res = mspy.similaritymatrix(scans)
    a = list(mspy.bootstrapmatrices(res, 5, seed=3))
    b = list(mspy.bootstrapmatrices(res, 5, seed=3))
    assert len(a) == len(b) == 5
    assert all(numpy.allclose(x, y, equal_nan=True) for x, y in zip(a, b, strict=True))


def test_lag_smear_matches_explicit_mean():
    rng = numpy.random.default_rng(0)
    v = rng.random(200)
    got = mod_similarity._lagsmear(v, 3, 7)
    padded = numpy.concatenate([numpy.zeros(10), v, numpy.zeros(10)])
    want = numpy.array(
        [
            numpy.mean(
                [padded[10 + b + t] for t in list(range(3, 8)) + list(range(-7, -2))]
            )
            for b in range(200)
        ]
    )
    assert numpy.allclose(got, want)


# ---------------------------------------------------------------------------
# grouping
# ---------------------------------------------------------------------------


def test_upgma_hand_example():
    # distances: a-b 0.2, c-d 0.4, between pairs 0.8 / 0.9 / 0.7 / 0.6
    D = numpy.array(
        [[0, 0.2, 0.8, 0.9], [0.2, 0, 0.7, 0.6], [0.8, 0.7, 0, 0.4], [0.9, 0.6, 0.4, 0]]
    )
    Z = mod_grouping.upgma(1 - D)
    assert tuple(Z[0, :2]) == (0, 1) and Z[0, 2] == pytest.approx(0.2)
    assert tuple(Z[1, :2]) == (2, 3) and Z[1, 2] == pytest.approx(0.4)
    assert Z[2, 2] == pytest.approx((0.8 + 0.9 + 0.7 + 0.6) / 4)
    assert mod_grouping.treeorder(Z) == [0, 1, 2, 3]


def test_louvain_recovers_planted_groups():
    rng = numpy.random.default_rng(5)
    sizes = [2, 3, 4, 5]
    truth = numpy.repeat(numpy.arange(len(sizes)), sizes)
    n = len(truth)
    W = numpy.where(
        truth[:, None] == truth[None, :], rng.uniform(0.4, 0.9, (n, n)), 0.0
    )
    W = numpy.triu(W, 1)
    W = W + W.T
    assert mod_grouping.adjustedrand(
        truth, mod_grouping.louvain(W, seed=0)
    ) == pytest.approx(1.0)


def test_adjusted_rand_values():
    assert mod_grouping.adjustedrand([0, 0, 1, 1], [5, 5, 7, 7]) == pytest.approx(1.0)
    assert mod_grouping.adjustedrand([0, 0, 1, 1], [0, 1, 0, 1]) < 0


def test_newick_has_all_leaves_and_support():
    Z = mod_grouping.upgma(
        1 - numpy.array([[0, 0.2, 0.8], [0.2, 0, 0.7], [0.8, 0.7, 0]])
    )
    text = mod_grouping.newick(Z, ["a b", "c", "d"], support=numpy.array([0.9, 1.0]))
    assert text.endswith(";") and "'a b'" in text and ")90:" in text


def family(base, seeds, lo=100, hi=900, precursor=None):
    """Spectra sharing `base` peaks, each with a few peaks of its own."""

    return [
        make_scan(
            base + random_peaks(s, lo, hi, 4), hi=hi + 50, precursor=precursor, seed=s
        )
        for s in seeds
    ]


def test_groupspectra_finds_families_and_leaves_loners():
    fam1 = family(random_peaks(101, 100, 900, 15), [1, 2, 3])
    fam2 = family(random_peaks(202, 100, 900, 15), [4, 5, 6])
    loners = [
        make_scan(random_peaks(300 + k, 100, 900), hi=950, seed=10 + k)
        for k in range(3)
    ]
    scans = fam1 + fam2 + loners
    sim = mspy.similaritymatrix(scans)
    res = mspy.groupspectra(sim, replicates=30, seed=1)
    g = res.groups
    assert len({g[0], g[1], g[2]}) == 1
    assert len({g[3], g[4], g[5]}) == 1
    assert g[0] != g[3]
    assert len({g[6], g[7], g[8]} - {g[0], g[3]}) == 3  # loners stay apart
    assert res.coMembership is not None
    assert res.coMembership[0, 1] > 0.8
    assert res.stability is not None and res.stability > 0.5
    assert sorted(res.order) == list(range(len(scans)))


def test_groupspectra_tree_method_and_polarity_split():
    fam = family(random_peaks(101, 100, 900, 15), [1, 2])
    neg = family(random_peaks(101, 100, 900, 15), [3, 4])
    for s in neg:
        s.polarity = -1
    sim = mspy.similaritymatrix(fam + neg)
    res = mspy.groupspectra(sim, method="tree", cut=0.3, replicates=10)
    assert len(res.trees) == 2  # one tree per polarity
    assert res.groups[0] == res.groups[1] and res.groups[2] == res.groups[3]
    assert res.groups[0] != res.groups[2]


def test_sharedfeatures_reports_the_family_ion():
    base = [(345.6, 15.0), (512.2, 10.0)]
    scans = family(base, [1, 2, 3]) + [
        make_scan(random_peaks(400 + k, 100, 900), hi=950, seed=20 + k)
        for k in range(3)
    ]
    sim = mspy.similaritymatrix(scans, axes="mz")
    feats = mspy.sharedfeatures(sim, [0, 1, 2])
    positions = [p for f in feats["mz"] for p in f["positions"]]
    assert any(abs(p - 345.6) < 0.3 for p in positions)
    assert any(abs(p - 512.2) < 0.3 for p in positions)


def test_rangedependence_returns_two_values():
    scans = [
        make_scan(random_peaks(k, 100, 400 + 100 * k), hi=450 + 100 * k, seed=k)
        for k in range(5)
    ]
    sim = mspy.similaritymatrix(scans)
    allPairs, apart = mspy.rangedependence(sim)
    assert -1 <= allPairs <= 1


def test_groups_of_several_spectra_are_numbered_first():
    fam = family(random_peaks(101, 100, 900, 15), [1, 2, 3])
    loners = [make_scan(random_peaks(300 + k, 100, 900), hi=950, seed=10 + k) for k in range(2)]
    res = mspy.groupspectra(mspy.similaritymatrix(loners + fam), replicates=0)
    assert set(res.groups[2:]) == {1}
    assert sorted(res.groups[:2]) == [2, 3]


def test_a_stopper_ends_the_comparison():
    scans = [make_scan(random_peaks(k, 100, 900), hi=950, seed=k) for k in range(3)]
    calls = []

    def stopper():
        calls.append(1)
        if len(calls) == 2:
            raise mod_stopper.ForceQuit

    with pytest.raises(mod_stopper.ForceQuit):
        mspy.similaritymatrix(scans, stopper=stopper)
    assert len(calls) == 2


def test_spectra_without_a_precursor_are_compared_on_mz():
    """MS1 spectra have no losses: with the default axes they are compared on
    m/z (also against fragment spectra); losses only refuses them."""

    peaks = random_peaks(7, 100, 900)
    ms1 = [make_scan(peaks, hi=950, seed=k) for k in range(2)]
    ms2 = make_scan(peaks, hi=950, precursor=950.0, seed=3)
    res = mspy.similaritymatrix(ms1 + [ms2])
    assert res.similarity[0, 1] > 0.5
    assert numpy.isfinite(res.similarity[0, 2])

    with pytest.raises(ValueError, match="precursor"):
        mspy.similaritymatrix(ms1 + [ms2], axes="loss")


# ---------------------------------------------------------------------------
# review fixes
# ---------------------------------------------------------------------------


def test_a_peak_outside_the_shared_range_does_not_change_the_score():
    """The chance level comes from the shared range only, as the cosine."""

    peaks = random_peaks(11, 100, 290, 10)
    a = make_scan(peaks, hi=300, seed=1)
    b = make_scan(peaks, hi=400, seed=2)
    b_more = make_scan(peaks + [(315.0, 50.0)], hi=400, seed=2)
    s1 = mspy.similaritymatrix([a, b]).similarity[0, 1]
    s2 = mspy.similaritymatrix([a, b_more]).similarity[0, 1]
    assert s1 == pytest.approx(s2, abs=1e-9)


def test_spectra_without_a_common_range_are_not_compared():
    a = make_scan(random_peaks(1, 100, 290), lo=100, hi=300, seed=1)
    b = make_scan(random_peaks(2, 410, 590), lo=400, hi=600, seed=2)
    c = make_scan(random_peaks(3, 100, 290), lo=100, hi=300, seed=3)
    res = mspy.similaritymatrix([a, b, c])
    assert not res.comparable[0, 1] and numpy.isnan(res.similarity[0, 1])
    assert res.comparable[0, 2]


def test_fragment_spectra_are_compared_only_where_acquired():
    """Same precursor, profiles over 100-300 and 400-450: nothing in common."""

    a = make_scan(random_peaks(1, 110, 290), lo=100, hi=300, precursor=500.0, seed=1)
    b = make_scan(random_peaks(2, 405, 445), lo=400, hi=450, precursor=500.0, seed=2)
    res = mspy.similaritymatrix([a, b])
    assert not res.comparable[0, 1]


def test_a_spectrum_without_a_profile_uses_its_peaks():
    peaks = random_peaks(5, 100, 900)
    profile = make_scan(peaks, hi=950, seed=1)
    centroids = mspy.scan(peaklist=[mspy.peak(mz=mz, ai=ai) for mz, ai in peaks])
    assert mspy.similaritymatrix([profile, centroids]).similarity[0, 1] > 0.5


def test_without_blocks_the_scores_match_but_cannot_be_bootstrapped():
    scans = [make_scan(random_peaks(40 + k, 100, 900), seed=k) for k in range(3)]
    full = mspy.similaritymatrix(scans)
    lean = mspy.similaritymatrix(scans, blocks=False)
    assert numpy.allclose(full.similarity, lean.similarity)
    assert lean.blockSums.shape[-1] == 1
    with pytest.raises(ValueError):
        list(mspy.bootstrapmatrices(lean, 2))


def test_the_bootstrap_does_not_depend_on_input_order():
    a = make_scan(random_peaks(1, 100, 900) + [(500.0, 20.0)], seed=1)
    b = make_scan(random_peaks(1, 100, 900) + [(700.0, 20.0)], seed=2)
    ab = list(mspy.bootstrapmatrices(mspy.similaritymatrix([a, b]), 20, seed=4))
    ba = list(mspy.bootstrapmatrices(mspy.similaritymatrix([b, a]), 20, seed=4))
    assert [m[0, 1] for m in ab] == pytest.approx([m[0, 1] for m in ba])


def test_unmeasured_pairs_do_not_count_as_a_distance():
    """u (unknown polarity) is identical to p and n, which were not compared:
    the tree joins u at 0 and then the third at the mean of measured pairs."""

    S = numpy.array([[1.0, 1.0, numpy.nan], [1.0, 1.0, 1.0], [numpy.nan, 1.0, 1.0]])
    Z = mod_grouping.upgma(S)
    assert Z[0, 2] == pytest.approx(0.0)
    assert Z[1, 2] == pytest.approx(0.0)  # only u-n measured, at distance 0


def test_no_bootstrap_results_when_nothing_could_be_resampled():
    pos = make_scan(random_peaks(1, 100, 900), polarity=1, seed=1)
    neg = make_scan(random_peaks(2, 100, 900), polarity=-1, seed=2)
    grp = mspy.groupspectra(mspy.similaritymatrix([pos, neg]), replicates=10)
    assert grp.coMembership is None and grp.stability is None


def test_newick_keeps_distinct_names_distinct():
    Z = mod_grouping.upgma(numpy.array([[1.0, 0.5], [0.5, 1.0]]))
    text = mspy.newick(Z, ["a:b", "a,b"])
    assert "'a:b'" in text and "'a,b'" in text


def test_smoothing_keeps_the_length_with_a_long_kernel():
    assert len(mod_similarity._gaussian(numpy.ones(12), 10.0)) == 12


def test_labels_that_would_start_a_formula_stay_text():
    from gui import similarity_results as results

    assert results.text("=HYPERLINK()") == "'=HYPERLINK()"
    assert results.text("-5 sample") == "'-5 sample"
    assert results.text("sample") == "sample"


def test_numbered_labels_skip_names_already_taken():
    from gui import similarity_results as results

    items = [results.Item(None, t, "/d/x") for t in ("Sample", "Sample", "Sample #1")]
    results.unique_labels(items)
    labels = [item.label for item in items]
    assert len(set(labels)) == 3 and "Sample #1" in labels


def test_a_failed_export_leaves_the_earlier_results_alone(tmp_path):
    from gui import similarity_results as results

    scans = [make_scan(random_peaks(40 + k, 100, 900), seed=k) for k in range(3)]
    items = [results.Item(s, "s%d" % k, "") for k, s in enumerate(scans)]
    sim = mspy.similaritymatrix(scans)
    grp = mspy.groupspectra(sim, replicates=0)
    (tmp_path / "REPORT.md").write_text("earlier run")
    (tmp_path / "trees.nwk").mkdir()  # cannot be replaced
    with pytest.raises(OSError):
        results.write_results(str(tmp_path), items, sim, grp, {}, {"replicates": 0})
    assert (tmp_path / "REPORT.md").read_text() == "earlier run"
    assert not (tmp_path / "groups.csv").exists()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".similarity-")]
