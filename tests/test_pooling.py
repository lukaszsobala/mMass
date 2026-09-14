"""Peak picking from pooled scans of a run (mspy.mod_pooling).

"Find Peaks" on an LC-MS run can pool the scans acquired the same way, pick the
pooled spectrum once and label the result in every scan. These tests build small
synthetic runs whose truth is known -- species, charges, abundances and per-scan
calibration offsets -- so each stage can be checked against it.
"""

import math

import numpy
import pytest

import mspy
from mspy import mod_peakpicking as mpp
from mspy import mod_pooling as mpool


PROTON = 1.00727646688


# ---------------------------------------------------------------------------
# Synthetic runs
# ---------------------------------------------------------------------------


def _raster(lo, hi, step=0.004, reference=800.0):
    """An Orbitrap-like m/z raster whose step grows as m/z^1.5."""

    values = [lo]
    while values[-1] < hi:
        values.append(values[-1] + step * (values[-1] / reference) ** 1.5)
    return numpy.array(values)


def _envelope(x, mono, charge, height, fwhm, ppm=0.0):
    """Protein-averagine isotope envelope with its apex isotope at `height`."""

    lam = (mono - PROTON) * charge * mpp.AVERAGINE_MODELS["protein"]["lambdaFactor"]
    weights = [math.exp(-lam) * lam**k / math.factorial(k) for k in range(10)]
    apex = max(weights)
    sigma = fwhm / 2.3548
    y = numpy.zeros(len(x))
    for k, weight in enumerate(weights):
        if weight / apex < 0.005:
            continue
        centre = (mono + k * mpp.ISOTOPE_DISTANCE / charge) * (1.0 + ppm * 1e-6)
        y += height * weight / apex * numpy.exp(-0.5 * ((x - centre) / sigma) ** 2)
    return y


def _run(species, nscans=12, noise=10.0, ppms=None, lo=780.0, hi=1230.0, seed=3, zeroDrop=False):
    """Scans of one acquisition: `species` is a list of (mono, charge, height).

    `height` may be a callable of the scan index, for species whose abundance
    changes along the run.
    """

    rng = numpy.random.default_rng(seed)
    x = _raster(lo, hi)
    ppms = ppms if ppms is not None else [0.0] * nscans
    scans = []
    for index in range(nscans):
        y = numpy.clip(rng.normal(2.0 * noise, noise, len(x)), 0.0, None)
        for mono, charge, height in species:
            h = height(index) if callable(height) else height
            y += _envelope(x, mono, charge, h, mono / 40000.0, ppm=ppms[index])
        profile = numpy.column_stack([x, y])
        if zeroDrop:
            keep = y > 6.0 * noise
            keep = keep | numpy.roll(keep, 1) | numpy.roll(keep, -1)
            profile = profile[keep]
            profile[profile[:, 1] <= 6.0 * noise, 1] = 0.0
        scan = mspy.scan(profile=profile)
        scan.scanNumber = index + 1
        scan.msLevel = 1
        scan.retentionTime = float(index)
        scans.append(scan)
    return scans


def _pick(scan, snThreshold):
    """The Find Peaks pipeline (panel_processing.pickPeaksOnScan), through `scan`."""

    scan.labelscan(pickingHeight=0.5, snThreshold=snThreshold, baselineWindow=0.01, baselineOffset=0.5)
    scan.deisotope(maxCharge=3, mzTolerance=0.02, intTolerance=0.5, averagineType="protein")
    scan.labelenvelopes(
        label="1st",
        intensity="maximum",
        mzTolerance=0.02,
        nonIdeality=0.5,
        averagineType="protein",
        refinePattern=True,
        preserveSeeds=True,
        relaxed=True,
    )
    scan.remisotopes()
    scan.remuncharged()


def _find(peaklist, mono, charge, ppm=15.0):
    for peak in peaklist:
        if peak.charge == charge and abs(peak.mz - mono) / mono * 1e6 < ppm:
            return peak
    return None


# ---------------------------------------------------------------------------
# Which scans may be pooled
# ---------------------------------------------------------------------------


def test_acquisition_groups_keep_analysers_apart_and_skip_centroids():
    """An interleaved high- and low-resolution full scan never share a group.

    The example LC-MS run alternates "FTMS + p ESI Full ms" and "ITMS + p ESI Full
    ms" scans; pooling them would average an Orbitrap profile with an ion trap
    one. Centroided scans have no profile to pool and are left out, and every
    group is in retention-time order.
    """

    scanlist = {
        1: {"msLevel": 1, "polarity": 1, "retentionTime": 20.0, "spectrumType": "continuous",
            "filterString": "FTMS + p ESI Full ms [200.00-2000.00]"},
        2: {"msLevel": 1, "polarity": 1, "retentionTime": 21.0, "spectrumType": "continuous",
            "filterString": "ITMS + p ESI Full ms [200.00-2000.00]"},
        3: {"msLevel": 2, "polarity": 1, "retentionTime": 22.0, "spectrumType": "discrete",
            "filterString": "ITMS + c ESI d Full ms2 810.79@cid35.00", "precursorMZ": 810.79},
        4: {"msLevel": 1, "polarity": 1, "retentionTime": 10.0, "spectrumType": "continuous",
            "filterString": "FTMS + p ESI Full ms [200.00-2000.00]"},
        5: {"msLevel": 1, "polarity": 1, "retentionTime": 30.0, "spectrumType": "continuous",
            "instrumentConfigurationRef": "IC2"},
        6: {"msLevel": 1, "polarity": -1, "retentionTime": 31.0, "spectrumType": "continuous",
            "instrumentConfigurationRef": "IC2"},
    }

    groups = mspy.acquisitiongroups(scanlist)

    assert [4, 1] in groups  # FTMS, in retention-time order
    assert [2] in groups  # ITMS
    assert [5] in groups and [6] in groups  # polarity separates too
    assert all(3 not in group for group in groups)  # centroided MS2


def test_sampling_groups_split_scans_of_different_resolution():
    """Without acquisition metadata, the sampling step still tells analysers apart."""

    x = numpy.linspace(200.0, 2000.0, 200000)  # 0.009 step, ten times finer
    fine = [mspy.scan(profile=numpy.column_stack([x, numpy.ones(len(x))])) for _ in range(2)]
    coarse = numpy.arange(200.0, 2000.0, 0.09)
    wide = mspy.scan(profile=numpy.column_stack([coarse, numpy.ones(len(coarse))]))

    assert mspy.samplinggroups([fine[0], wide, fine[1]]) == [[0, 2], [1]]


# ---------------------------------------------------------------------------
# The pooled spectrum
# ---------------------------------------------------------------------------


def test_common_raster_reproduces_a_shared_acquisition_raster():
    """Scans on one raster (with different points dropped) pool onto that raster."""

    x = _raster(780.0, 900.0)
    keepA = numpy.arange(len(x)) % 3 != 0
    keepB = numpy.arange(len(x)) % 3 != 1
    profiles = [
        numpy.column_stack([x[keepA], numpy.ones(int(keepA.sum()))]),
        numpy.column_stack([x[keepB], numpy.ones(int(keepB.sum()))]),
    ]

    raster = mspy.commonraster(profiles)

    assert numpy.array_equal(raster, x)


def test_common_raster_does_not_multiply_nodes_for_shifted_rasters():
    """Many slightly shifted rasters give about one node per native step, not per scan."""

    x = _raster(780.0, 800.0)
    profiles = [
        numpy.column_stack([x * (1.0 + shift * 1e-6), numpy.ones(len(x))])
        for shift in numpy.linspace(-2.0, 2.0, 25)
    ]

    raster = mspy.commonraster(profiles)

    assert len(raster) <= 2 * len(x)
    assert numpy.all(numpy.diff(raster) > 0.0)


def test_pooling_reads_zero_inside_gaps_of_zero_dropped_data():
    """Two peaks of a zero-dropped scan are not joined by interpolation.

    Only the points around peaks are stored, so the raster nodes another scan
    contributes between them lie in a gap: nothing was recorded there above zero.
    """

    dense = _raster(780.0, 800.0)
    peaks = numpy.zeros(len(dense))
    peaks[100:110] = 50.0
    peaks[900:910] = 50.0
    keep = peaks > 0
    sparse = numpy.column_stack([dense[keep], peaks[keep]])
    flat = numpy.column_stack([dense, numpy.zeros(len(dense))])

    pooled = mspy.poolscans([mspy.scan(profile=sparse), mspy.scan(profile=flat)], align=False)

    between = (pooled.profile[:, 0] > dense[200]) & (pooled.profile[:, 0] < dense[800])
    assert numpy.all(pooled.profile[between, 1] == 0.0)
    assert pooled.profile[:, 1].max() == pytest.approx(25.0)


def test_pooled_noise_drops_with_the_number_of_scans():
    """Averaging N scans lowers the noise mMass measures by about sqrt(N)."""

    single = _run([], nscans=1, lo=780.0, hi=880.0)
    many = _run([], nscans=16, lo=780.0, hi=880.0)

    alone = single[0].noise()[1]
    pooled = mspy.poolscans(many, align=False).noise()[1]

    assert pooled < alone / 3.0


@pytest.mark.parametrize("spread", [0.0, 5.0, 40.0])
def test_alignment_recovers_each_scans_calibration_offset(spread):
    """Per-scan offsets are found to a fraction of a ppm, up to tens of ppm.

    The coarse search matters beyond about a peak width (20-30 ppm here): the
    centroid refinement alone only sees one width around each anchor and pulled
    a 30 ppm run apart instead of together.
    """

    rng = numpy.random.default_rng(11)
    ppms = list(rng.normal(0.0, spread, 8)) if spread else [0.0] * 8
    species = [(800.40, 2, 3000.0), (883.45, 1, 2000.0), (1046.54, 1, 2500.0), (1199.67, 1, 1500.0)]
    scans = _run(species, nscans=8, ppms=ppms)

    offsets = numpy.array(mspy.alignmentoffsets(scans))
    truth = numpy.array(ppms)

    # offsets are relative to the pool, whose calibration is the typical scan's
    residual = (offsets - numpy.median(offsets)) - (truth - numpy.median(truth))
    assert numpy.max(numpy.abs(residual)) < 0.5


def test_alignment_keeps_pooled_peaks_at_their_true_width():
    """Pooling drifting scans without alignment smears every peak.

    Compared with the true FWHM rather than with single scans: mMass's width
    measurement reads a single noisy scan narrower than the peak really is.
    """

    rng = numpy.random.default_rng(5)
    ppms = list(rng.normal(0.0, 10.0, 10))
    species = [(800.40, 2, 3000.0), (883.45, 1, 2000.0), (1046.54, 1, 2500.0), (1199.67, 1, 1500.0)]
    scans = _run(species, nscans=10, ppms=ppms)
    smeared = mspy.poolscans(scans, align=False)
    aligned = mspy.poolscans(scans, align=True)

    def widths(scan):
        return numpy.array([
            mspy.labelpeak(scan.profile, mz=mono, pickingHeight=0.5).fwhm / (mono / 40000.0)
            for mono, _charge, _height in species
        ])

    # 10 ppm of drift against peaks 25-37 ppm wide
    assert numpy.mean(widths(smeared)) > 1.2
    assert numpy.all(numpy.abs(widths(aligned) - 1.0) < 0.1)


def test_pool_windows_cover_the_whole_run_like_poolscans():
    """A window wider than the run is the whole-run pool, for every scan."""

    scans = _run([(800.40, 2, 500.0)], nscans=5, lo=780.0, hi=830.0)
    whole = mspy.poolscans(scans, align=False)

    windows = list(mspy.poolwindows(scans, 10, align=False))

    assert [index for index, _pooled in windows] == list(range(5))
    for _index, pooled in windows:
        assert numpy.allclose(pooled.profile, whole.profile)


def test_pool_windows_follow_an_eluting_species():
    """A narrow window keeps a species at its own abundance where it elutes."""

    elution = lambda i: 2000.0 * math.exp(-0.5 * ((i - 2) / 0.8) ** 2)  # noqa: E731
    scans = _run([(800.40, 2, elution)], nscans=12, lo=780.0, hi=830.0)

    apex = dict(mspy.poolwindows(scans, 1, align=False))
    height = lambda s: mspy.labelpeak(s.profile, mz=800.40, pickingHeight=0.5).ai  # noqa: E731

    assert height(apex[2]) > 3.0 * height(mspy.poolscans(scans, align=False))


# ---------------------------------------------------------------------------
# Labelling pooled peaks in a scan
# ---------------------------------------------------------------------------


def test_labelled_peaks_keep_pooled_positions_and_widths():
    """Position, charge and FWHM come from the pool, intensity from the scan."""

    scans = _run([(800.40, 2, 400.0), (1046.54, 1, 300.0)], nscans=6, noise=10.0)
    pooled = mspy.poolscans(scans)
    _pick(pooled, snThreshold=5.0)
    features = list(pooled.peaklist)
    assert len(features) == 2

    for scan, offset in zip(scans, pooled.attributes["alignment"], strict=True):
        scan.baseline(window=0.01, offset=0.5)
        scan.labelpooled(pooled.peaklist, snThreshold=3.0, baselineWindow=0.01,
                         baselineOffset=0.5, averagineType="protein", alignment=offset)
        assert len(scan.peaklist) == 2
        for peak, feature in zip(scan.peaklist, features, strict=True):
            assert peak.mz == feature.mz
            assert peak.charge == feature.charge
            assert peak.fwhm == feature.fwhm
            assert peak.attributes["envelope"]["isotopes"][0][0] == pytest.approx(
                feature.attributes["envelope"]["isotopes"][0][0]
            )
            # measured in THIS scan
            assert peak.ai == pytest.approx(
                mpool._height(scan.profile[:, 0], scan.profile[:, 1], peak.mz,
                              mpool.POOL_HEIGHT_WINDOW * peak.fwhm),
            )


def test_labelled_envelope_area_follows_the_scans_abundance():
    """The same species at twice the abundance gets about twice the area."""

    abundance = lambda i: 300.0 * (1 + i)  # noqa: E731
    scans = _run([(1046.54, 1, abundance)], nscans=4, noise=5.0, lo=1030.0, hi=1060.0)
    pooled = mspy.poolscans(scans)
    _pick(pooled, snThreshold=5.0)

    areas = []
    for scan, offset in zip(scans, pooled.attributes["alignment"], strict=True):
        scan.labelpooled(pooled.peaklist, snThreshold=3.0, baselineWindow=0.01,
                         baselineOffset=0.5, averagineType="protein", alignment=offset)
        areas.append(scan.peaklist[0].attributes["envelope"]["area"])

    assert areas[1] / areas[0] == pytest.approx(2.0, rel=0.15)
    assert areas[3] / areas[0] == pytest.approx(4.0, rel=0.15)


def test_species_too_weak_in_a_scan_is_left_out_there():
    """A species absent from some scans is labelled only where it reaches the S/N."""

    present = lambda i: 600.0 if i < 3 else 0.0  # noqa: E731
    scans = _run([(800.40, 2, 600.0), (1046.54, 1, present)], nscans=6, noise=10.0)
    pooled = mspy.poolscans(scans)
    _pick(pooled, snThreshold=5.0)
    assert _find(pooled.peaklist, 1046.54, 1) is not None

    for index, (scan, offset) in enumerate(zip(scans, pooled.attributes["alignment"], strict=True)):
        scan.labelpooled(pooled.peaklist, snThreshold=3.0, baselineWindow=0.01,
                         baselineOffset=0.5, averagineType="protein", alignment=offset)
        assert _find(scan.peaklist, 800.40, 2) is not None
        assert (_find(scan.peaklist, 1046.54, 1) is not None) == (index < 3)


def _stored_envelope_peak(mono, charge, fwhm):
    """A labelled envelope peak with its theoretical (protein) isotope grid."""

    peak = mspy.peak(mz=mono, ai=1.0, charge=charge, isotope=0, fwhm=fwhm)
    length = mpp._theory_envelope_length(peak, "protein")
    grid = [
        mspy.peak(mz=mono + k * mpp.ISOTOPE_DISTANCE / charge, charge=charge, isotope=k)
        for k in range(length)
    ]
    weights = mpp._cluster_weights(grid, "protein")
    peak.attributes["envelope"] = {
        "area": 1.0,
        "sumint": 1.0,
        "fwhm": fwhm,
        "shape": "gaussian",
        "isotopes": [(p.mz, w) for p, w in zip(grid, weights, strict=True)],
        "detected": 1,
        "averagineType": "protein",
    }
    return peak


def test_missing_envelope_still_accounts_for_its_own_signal():
    """A neighbour cannot claim the signal of an overlapping species left out.

    B starts two isotopes above A with the same charge. In this scan B is below
    the labelling S/N, so it is not labelled -- but it still has signal under A's
    tail, and leaving it out of the fit altogether would hand that signal to A.
    """

    x = _raster(1040.0, 1060.0)
    fwhm = 1046.54 / 40000.0
    y = _envelope(x, 1046.54, 1, 1000.0, fwhm) + _envelope(x, 1048.55, 1, 120.0, fwhm)
    scan = mspy.scan(profile=numpy.column_stack([x, y]))
    features = [
        _stored_envelope_peak(1046.54, 1, fwhm),
        _stored_envelope_peak(1048.55, 1, fwhm),
    ]

    def areaA(peaklist):
        return _find(peaklist, 1046.54, 1).attributes["envelope"]["area"]

    # B labelled too / A fitted as if B did not exist
    both = mspy.labelpooled(scan.profile, mspy.peaklist(features), averagineType="protein")
    alone = mspy.labelpooled(scan.profile, mspy.peaklist(features[:1]), averagineType="protein")
    assert len(both) == 2
    assert areaA(both) < areaA(alone)

    # a noise level at which A clears S/N 3 and B does not
    baseline = numpy.array([[1040.0, 0.0, 250.0], [1060.0, 0.0, 250.0]])
    missing = mspy.labelpooled(
        scan.profile, mspy.peaklist(features), baseline=baseline, snThreshold=3.0,
        averagineType="protein",
    )
    assert _find(missing, 1048.55, 1) is None
    assert areaA(missing) == pytest.approx(areaA(both))


# ---------------------------------------------------------------------------
# The whole thing
# ---------------------------------------------------------------------------


def test_pooled_picking_finds_species_single_scans_miss():
    """Species below the picking threshold in every scan are found and labelled.

    Picked on their own, the drifting, noisy scans find nothing at this threshold;
    pooled and aligned, both species are found with the right charge and then
    labelled in every scan, at the same positions.
    """

    rng = numpy.random.default_rng(2)
    ppms = list(rng.normal(0.0, 4.0, 16))
    species = [(800.40, 2, 250.0), (1046.54, 1, 250.0)]
    scans = _run(species, nscans=16, noise=10.0, ppms=ppms, zeroDrop=False)

    for scan in scans[:3]:
        alone = scan.duplicate()
        _pick(alone, snThreshold=10.0)
        assert _find(alone.peaklist, 800.40, 2) is None
        assert _find(alone.peaklist, 1046.54, 1) is None

    pooled = mspy.poolscans(scans)
    _pick(pooled, snThreshold=10.0)
    for mono, charge, _height in species:
        assert _find(pooled.peaklist, mono, charge, ppm=5.0) is not None

    positions = None
    for scan, offset in zip(scans, pooled.attributes["alignment"], strict=True):
        scan.labelpooled(pooled.peaklist, snThreshold=1.5, baselineWindow=0.01,
                         baselineOffset=0.5, averagineType="protein", alignment=offset)
        found = [_find(scan.peaklist, mono, charge) for mono, charge, _h in species]
        assert all(found)
        mzs = [peak.mz for peak in found]
        assert positions is None or mzs == positions
        positions = mzs
