"""Envelope areas are measured above a local pedestal, with an uncertainty.

The joint area fit (mspy.mod_peakpicking._fit_envelope_areas_detailed) fits a
smooth pedestal under every overlap group together with the envelopes, takes it
off, and only then apportions the signal. These tests pin the contract:

* a baseline left under the peaks is not counted as area, and the area does not
  depend on how -- or whether -- the profile was baseline-corrected first;
* it holds where peaks leave no gap to read the baseline from (a crowded
  low-resolution region), and an unlabelled peak in the window does not lift it;
* a profile whose baseline was cut to zero (smoothed, zeros between the peaks)
  keeps its areas: the floor is the pedestal;
* noise below the pedestal is not clipped away, so weak envelopes are not
  inflated;
* the reported one-sigma uncertainty matches the scatter of the area over noise;
* the envelope stores the pedestal it was measured above, so it can be drawn on
  it, and its peaks' intensities are measured above the same pedestal.
"""

import math

import numpy
import pytest

import mspy
from mspy import mod_peakpicking as mpp


SQ2PI = math.sqrt(2.0 * math.pi)


def _sigma(fwhm):
    return fwhm / (2.0 * math.sqrt(2.0 * math.log(2.0)))


def _pattern(mono):
    """The modelled isotopes (mz, weight) of a charge-1 species, weights sum 1."""

    parent = mspy.peak(mz=mono, ai=1.0, charge=1, isotope=0)
    length = mpp._theory_envelope_length(parent)
    weights = mpp._cluster_pattern(parent, length)
    total = sum(weights)
    return [(mono + i * mpp.ISOTOPE_DISTANCE, w / total) for i, w in enumerate(weights)]


def _area_for_height(mono, height, fwhm):
    """Area that gives the monoisotopic apex `height`."""

    return height * _sigma(fwhm) * SQ2PI / _pattern(mono)[0][1]


def _render(x, species, fwhm):
    """Clean profile of (mono, area) species."""

    sigma = _sigma(fwhm)
    y = numpy.zeros_like(x)
    for mono, area in species:
        for mz, w in _pattern(mono):
            y += area * w / (sigma * SQ2PI) * numpy.exp(-0.5 * ((x - mz) / sigma) ** 2)
    return y


def _clusters(species, fwhm):
    return [
        [
            mspy.peak(mz=mz, ai=1.0, charge=1, isotope=i, fwhm=fwhm)
            for i, (mz, _w) in enumerate(_pattern(mono))
        ]
        for mono, _area in species
    ]


def _fit(species, x, y, fwhm, nonIdeality=0.2):
    """Reported areas and uncertainties (normalised as relabelenvelopes does)."""

    signal = numpy.column_stack((x, y)).astype(numpy.float64)
    areas, shapes, details = mpp._fit_envelope_areas_detailed(
        _clusters(species, fwhm), signal, fwhm, nonIdeality=nonIdeality
    )
    sums = [math.fsum(w for _mz, w in shape) for shape in shapes]
    reported = numpy.array([a * s for a, s in zip(areas, sums, strict=True)])
    errors = numpy.array(
        [(d.get("areaError") or 0.0) * s for d, s in zip(details, sums, strict=True)]
    )
    return reported, errors, details


FWHM = 0.1
X = numpy.arange(800.0, 1300.0, FWHM / 15)
MONOS = [850.42, 950.47, 1050.52, 1150.57]
HEIGHTS = [300.0, 100.0, 30.0, 10.0]
SPECIES = [(m, _area_for_height(m, h, FWHM)) for m, h in zip(MONOS, HEIGHTS, strict=True)]
TRUTH = numpy.array([a for _m, a in SPECIES])
CLEAN = _render(X, SPECIES, FWHM)
# a MALDI-like baseline: decaying, and well above the weaker peaks
BASELINE = 60.0 * numpy.exp(-(X - 800.0) / 250.0) + 8.0


# ---------------------------------------------------------------------------
# The pedestal is not area
# ---------------------------------------------------------------------------


def test_baseline_under_envelopes_is_not_counted_as_area():
    """On the raw profile the old fit counted the baseline under each envelope:
    +30% for a peak five times taller than its baseline, several-fold for one
    near it. Above the fitted pedestal every area is recovered."""

    areas, _errors, _details = _fit(SPECIES, X, CLEAN + BASELINE, FWHM)

    assert areas == pytest.approx(TRUTH, rel=0.02)


def test_area_does_not_depend_on_prior_baseline_correction():
    """Raw, baseline-subtracted, or subtracted too little (the offset the
    baseline correction leaves on purpose): the same area every time."""

    raw, _e, _d = _fit(SPECIES, X, CLEAN + BASELINE, FWHM)
    corrected, _e, _d = _fit(SPECIES, X, CLEAN, FWHM)
    partly, _e, _d = _fit(SPECIES, X, CLEAN + 0.3 * BASELINE, FWHM)

    assert raw == pytest.approx(corrected, rel=0.01)
    assert partly == pytest.approx(corrected, rel=0.01)


def test_crowded_low_resolution_region_keeps_its_areas():
    """Where overlapping envelopes leave no clean gap, the spectrum-wide median
    baseline rides up into the peaks (subtracting it cut such areas to a quarter).
    The pedestal is fitted together with the envelopes, whose isotope structure
    tells it apart from a flat background."""

    fwhm = 0.5
    x = numpy.arange(980.0, 1060.0, fwhm / 12)
    rng = numpy.random.default_rng(5)
    species = [
        (1000.3 + 1.63 * i, _area_for_height(1000.3 + 1.63 * i, rng.uniform(20, 120), fwhm))
        for i in range(20)
    ]
    truth = numpy.array([a for _m, a in species])
    baseline = 30.0 + 0.2 * (x - 980.0)

    areas, _errors, _details = _fit(species, x, _render(x, species, fwhm) + baseline, fwhm)

    ratios = areas / truth
    assert numpy.median(ratios) == pytest.approx(1.0, abs=0.02)
    assert numpy.all(numpy.abs(ratios - 1.0) < 0.05)


def test_unlabelled_peak_does_not_lift_the_pedestal():
    """A strong peak nobody labelled sits in the fit window. It is well above the
    model, so it does not inform the pedestal and the envelope keeps its area."""

    fwhm = 0.1
    x = numpy.arange(990.0, 1012.0, fwhm / 15)
    species = [(1000.5, _area_for_height(1000.5, 50.0, fwhm))]
    junk = [(1004.9, _area_for_height(1004.9, 150.0, fwhm))]
    y = _render(x, species + junk, fwhm) + 20.0

    areas, _errors, _details = _fit(species, x, y, fwhm)

    assert areas[0] == pytest.approx(species[0][1], rel=0.03)


# ---------------------------------------------------------------------------
# Profiles with a floor
# ---------------------------------------------------------------------------


def _smooth(y, points):
    kernel = numpy.exp(-0.5 * (numpy.arange(-4 * points, 4 * points + 1) / points) ** 2)
    return numpy.convolve(y, kernel / kernel.sum(), mode="same")


def test_baseline_cut_to_zero_between_peaks_keeps_the_areas():
    """Smoothed and baseline-cut data: the valleys between peaks are exactly zero.
    The floor is the pedestal (fitting one would read the mean of the noise left
    above the floor as baseline), and the areas are those of the clean signal."""

    rng = numpy.random.default_rng(11)
    noisy = CLEAN + BASELINE + rng.normal(0.0, 1.0, len(X))
    cut = numpy.clip(_smooth(noisy, 3) - _smooth(BASELINE, 3), 0.0, None)
    assert numpy.mean(cut == 0.0) > 0.3

    # smoothing widened the peaks; the fit is told the width it can see
    fwhm = math.sqrt(FWHM**2 + (2.3548 * 3 * FWHM / 15) ** 2)
    areas, errors, details = _fit(SPECIES, X, cut, fwhm)

    assert areas[:3] == pytest.approx(TRUTH[:3], rel=0.03)
    assert areas[3] == pytest.approx(TRUTH[3], rel=0.10)
    for detail in details:
        assert all(level == 0.0 for _mz, level in detail["pedestal"])
    assert numpy.all(numpy.isfinite(errors))


def test_noise_below_the_pedestal_is_not_clipped():
    """Clipping the signal above the pedestal at zero would read half the noise as
    signal and inflate every weak envelope; the fit is linear and keeps it."""

    weak = [(1000.5, _area_for_height(1000.5, 5.0, FWHM))]
    x = numpy.arange(990.0, 1012.0, FWHM / 15)
    clean = _render(x, weak, FWHM)
    ratios = []
    for seed in range(30):
        rng = numpy.random.default_rng(100 + seed)
        areas, _e, _d = _fit(weak, x, clean + 20.0 + rng.normal(0.0, 2.0, len(x)), FWHM, nonIdeality=0.0)
        ratios.append(areas[0] / weak[0][1])

    assert numpy.mean(ratios) == pytest.approx(1.0, abs=0.06)


# ---------------------------------------------------------------------------
# Uncertainty
# ---------------------------------------------------------------------------


def test_area_uncertainty_matches_the_scatter_over_noise():
    """The one-sigma uncertainty reported with each area is the spread the area
    actually shows over repeated noise draws."""

    areas, errors = [], []
    for seed in range(40):
        rng = numpy.random.default_rng(500 + seed)
        y = CLEAN + BASELINE + rng.normal(0.0, 2.0, len(X))
        a, e, _d = _fit(SPECIES, X, y, FWHM, nonIdeality=0.0)
        areas.append(a)
        errors.append(e)
    scatter = numpy.std(areas, axis=0)
    reported = numpy.mean(errors, axis=0)

    # the strongest envelope's scatter is dominated by the single-point cap, which
    # the linear estimate does not model; the rest must match
    for k in range(1, len(SPECIES)):
        assert 0.7 < reported[k] / scatter[k] < 1.3


def test_area_uncertainty_grows_as_the_signal_weakens():
    rng = numpy.random.default_rng(3)
    areas, errors, _d = _fit(SPECIES, X, CLEAN + BASELINE + rng.normal(0.0, 2.0, len(X)), FWHM)

    relative = errors / areas
    assert list(relative) == sorted(relative)


def test_noise_free_profile_has_no_area_uncertainty():
    # all that is left is the straight pedestal's misfit to the curved baseline
    areas, errors, _details = _fit(SPECIES, X, CLEAN + BASELINE, FWHM)

    assert numpy.all(errors / areas < 1e-4)


def test_no_profile_means_no_pedestal_and_no_uncertainty():
    _areas, _shapes, details = mpp._fit_envelope_areas_detailed(
        _clusters(SPECIES, FWHM), None, FWHM
    )

    assert details == [{} for _cluster in SPECIES]


def test_area_uncertainty_ignores_unlabelled_structure():
    """Peaks nobody labelled -- shoulders half as tall as every envelope -- only
    add signal. They must not pass for noise: noise is read from BELOW the
    pedestal, where they never reach. (Read from the whole residual they raised
    the uncertainty about sevenfold; what remains is their small share of the
    off-peak points.)"""

    rng = numpy.random.default_rng(9)
    shoulders = [(m + 0.35, _area_for_height(m + 0.35, 0.5 * h, FWHM)) for m, h in zip(MONOS, HEIGHTS, strict=True)]
    noise = rng.normal(0.0, 0.5, len(X))
    plain, plainErrors, _d = _fit(SPECIES, X, CLEAN + BASELINE + noise, FWHM, nonIdeality=0.0)
    busy, busyErrors, _d = _fit(
        SPECIES, X, CLEAN + _render(X, shoulders, FWHM) + BASELINE + noise, FWHM, nonIdeality=0.0
    )

    assert numpy.all(busyErrors < 2.0 * plainErrors)


# ---------------------------------------------------------------------------
# What is stored and drawn
# ---------------------------------------------------------------------------


def _labelled(signal_y, fwhm=FWHM):
    """Pick the species as deisotoped peaks and convert them to envelopes."""

    peaks = []
    for mono, _area in SPECIES:
        for i, (mz, _w) in enumerate(_pattern(mono)):
            ai = float(numpy.interp(mz, X, signal_y))
            base = float(numpy.interp(mz, X, BASELINE)) * 0.5  # a picking baseline set too low
            peaks.append(mspy.peak(mz=mz, ai=ai, base=base, sn=(ai - base) / 2.0, charge=1, isotope=i, fwhm=fwhm))
    peaklist = mspy.peaklist(peaks)
    signal = numpy.column_stack((X, signal_y)).astype(numpy.float64)
    peaklist.labelenvelopes(label="1st", signal=signal, defaultFwhm=fwhm, nonIdeality=0.2, preserveSeeds=True)
    return peaklist


def test_envelope_stores_its_pedestal_and_uncertainty():
    peaklist = _labelled(CLEAN + BASELINE)
    envelopes = [p.attributes["envelope"] for p in peaklist if p.attributes.get("envelope")]

    assert len(envelopes) == len(SPECIES)
    for envelope, (mono, _area) in zip(envelopes, SPECIES, strict=True):
        assert envelope["areaError"] >= 0.0
        assert mpp.pedestallevel(envelope["pedestal"], mono) == pytest.approx(
            float(numpy.interp(mono, X, BASELINE)), rel=0.02
        )


def test_envelope_is_drawn_on_its_pedestal():
    """The displayed envelope sits on the pedestal and the shaded band between
    them is exactly the area that was summed."""

    peaklist = _labelled(CLEAN + BASELINE)
    envelope = next(p.attributes["envelope"] for p in peaklist if p.attributes.get("envelope"))

    flat = mspy.envelopeprofile(envelope, points=40)
    lifted = mspy.envelopeprofile(envelope, points=40, onPedestal=True)
    pedestal = mspy.envelopepedestal(envelope, flat[:, 0])

    assert lifted[:, 1] - flat[:, 1] == pytest.approx(pedestal[:, 1])
    band = numpy.trapezoid(lifted[:, 1] - pedestal[:, 1], lifted[:, 0])
    assert band == pytest.approx(envelope["area"], rel=0.01)
    # where the envelope has died away the drawn curve meets the spectrum's floor
    assert lifted[0, 1] == pytest.approx(float(numpy.interp(lifted[0, 0], X, BASELINE)), rel=0.02)


def test_legacy_envelope_without_pedestal_is_drawn_from_zero():
    envelope = {"area": 10.0, "fwhm": 0.1, "isotopes": [(1000.0, 1.0)]}

    flat = mspy.envelopeprofile(envelope)
    lifted = mspy.envelopeprofile(envelope, onPedestal=True)

    assert lifted[:, 1] == pytest.approx(flat[:, 1])


def test_envelope_intensity_is_measured_above_the_pedestal():
    """The envelope's label reports its height above the same pedestal its area
    was measured above, not above the picking baseline."""

    peaklist = _labelled(CLEAN + BASELINE)
    for peak in peaklist:
        envelope = peak.attributes.get("envelope")
        if not envelope:
            continue
        level = mpp.pedestallevel(envelope["pedestal"], peak.mz)
        assert peak.base == pytest.approx(level)
        assert peak.intensity == pytest.approx(peak.ai - level)


# ---------------------------------------------------------------------------
# Find Peaks does not depend on how the baseline was subtracted
# ---------------------------------------------------------------------------


def test_find_peaks_measures_the_same_on_raw_and_subtracted_spectra():
    """Peaks are measured from the baseline at its true level; the relative
    offset only decides how much of the baseline "Subtract Baseline" removes.
    So a raw spectrum and the same spectrum subtracted at 25 % or 50 % offset
    give the same peaks, heights and envelope areas."""

    import copy

    config = pytest.importorskip("gui.config")
    from gui import processing

    settings = copy.deepcopy(config.processing)
    settings["peakpicking"]["snThreshold"] = 5.0
    rng = numpy.random.default_rng(21)
    profile = numpy.column_stack((X, CLEAN + BASELINE + rng.normal(0.0, 0.5, len(X))))

    def picked(offset):
        scan = mspy.scan(profile=profile.copy())
        if offset is not None:
            settings["baseline"]["offset"] = offset
            processing.subtractBaseline(scan, settings)
        processing.pickPeaks(scan, settings)
        return {
            round(peak.mz, 2): (peak.intensity, peak.sn, peak.attributes["envelope"]["area"])
            for peak in scan.peaklist
            if peak.attributes.get("envelope")
        }

    raw = picked(None)
    # the three clearly above the S/N threshold (the fourth sits right on it)
    assert set(round(m, 2) for m in MONOS[:3]) <= set(raw)
    for offset in (0.25, 0.5):
        subtracted = picked(offset)
        assert set(subtracted) == set(raw)
        for mz, (intensity, sn, area) in raw.items():
            assert subtracted[mz][0] == pytest.approx(intensity, rel=0.03, abs=0.5)
            assert subtracted[mz][1] == pytest.approx(sn, rel=0.1)
            assert subtracted[mz][2] == pytest.approx(area, rel=0.02)
