"""Converting peaks to envelopes must not depend on which peaks are selected.

The rules, for mspy.recalculate_neighborhood_envelopes:

* a plain peak stays a plain peak unless the user converts it -- converting its
  neighbour leaves it exactly as it was;
* converting a peak re-fits the envelopes fitted together with it, so the result
  is the same whether the user converts that one peak, it and its neighbouring
  envelopes, or the whole list;
* only when a neighbour is NOT an envelope may converting it too change the
  result -- it then becomes an envelope.

"Fitted together" is wider than overlapping: the fit reads each cluster's signal
several FWHMs beyond its isotopes, and its pedestal and area uncertainty are read
off the spectrum up to ENVELOPE_NOISE_NULL_REACH around it, wherever no known
species is -- so converting a peak changes envelopes whose readings land on it.

The tests compare everything a peak and its envelope carry (area, uncertainty,
pedestal, isotope grid, width, intensity, ...), not only the area, on forests of
overlapping envelopes of mixed charge, width and height in a noisy spectrum.
"""

import copy
import random

import numpy
import pytest

import mspy
from mspy import mod_peakpicking as mpp

PARAMS = {
    "massTolerance": 0.05,
    "isotopeShift": 0.0,
    "maxCharge": 3,
    "intTolerance": 0.5,
    "labelEnvelope": "1st",
    "envelopeIntensity": "maximum",
    "envelopeNonIdeality": 0.40,
    "envelopeRefinePattern": 1,
    "seedCharge": 1,
}

# (mono m/z, charge, height, FWHM) of each species
FOREST_MIXED = [
    (1501.832, 3, 222.0, 0.060),
    (1504.732, 3, 297.6, 0.088),
    (1507.163, 2, 41.2, 0.122),
    (1508.797, 2, 302.1, 0.079),
    (1512.256, 1, 183.1, 0.061),
    (1514.883, 1, 497.5, 0.103),
    (1516.530, 1, 840.2, 0.096),
    (1518.907, 1, 864.2, 0.051),
]
FOREST_HIGH_CHARGE = [
    (1501.454, 3, 51.5, 0.077),
    (1503.700, 3, 379.6, 0.113),
    (1505.725, 3, 567.6, 0.070),
    (1507.112, 3, 248.2, 0.095),
    (1510.077, 1, 239.2, 0.122),
    (1511.003, 2, 58.1, 0.095),
    (1514.345, 1, 498.7, 0.131),
    (1517.261, 1, 49.3, 0.070),
]
# charge-1 species 2 Da apart: each one's +2 is the next one's mono
FOREST_CHAIN = [
    (1798.0, 1, 500.0, 0.11),
    (1800.0, 1, 800.0, 0.11),
    (1802.0, 1, 600.0, 0.11),
    (1804.0, 1, 400.0, 0.11),
    (1806.0, 1, 300.0, 0.11),
]
FORESTS = {"mixed": FOREST_MIXED, "high-charge": FOREST_HIGH_CHARGE, "chain": FOREST_CHAIN}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _isotope_peaks(mono, charge, height, fwhm, n=10):
    """Peaks of one averagine envelope, heights following its pattern."""
    spacing = mspy.ISOTOPE_DISTANCE / charge
    grid = [
        mspy.peak(mz=mono + i * spacing, charge=charge, isotope=i, fwhm=fwhm) for i in range(n)
    ]
    weights = mpp._cluster_weights(grid)
    return [mspy.peak(mz=p.mz, ai=w * height, fwhm=fwhm) for p, w in zip(grid, weights, strict=True)]


def _spectrum(species, noise=3.0, seed=0):
    """(seeds, profile): a noisy profile of the species on a baseline, and one
    plain charged monoisotopic peak per species, picked off the profile as peak
    picking leaves them before conversion.

    The seeds come as a plain list: an mspy.peaklist has ONE iteration cursor, so
    a test looping over one while the code under test iterates it again would
    silently stop after the first peak."""
    peaks = [p for mono, z, height, fwhm in species for p in _isotope_peaks(mono, z, height, fwhm)]
    profile = mspy.profile(mspy.peaklist(peaks), fwhm=0.08, points=20)
    if noise:
        rng = numpy.random.default_rng(seed)
        profile[:, 1] += rng.normal(0.0, noise, len(profile)) + 3.0 * noise
    seeds = []
    for mono, z, _height, _fwhm in species:
        peak = mpp.labelpeak(signal=profile, mz=mono)
        assert peak is not None
        peak.setcharge(z)
        peak.setisotope(0)
        seeds.append(peak)
    return seeds, profile


def _comb_spectrum(species, low=960.0, high=1080.0, seed=4):
    """Like `_spectrum`, on a wide window with chemical noise -- a bump at every
    mass unit -- for the pedestal's comb template and the uncertainty's readings
    to find, ENVELOPE_NOISE_NULL_REACH either side of every species."""
    x = numpy.arange(low, high, 0.004)
    y = 10.0 + numpy.random.default_rng(seed).normal(0.0, 1.0, len(x))
    y += 4.0 * numpy.exp(-0.5 * ((x - numpy.round(x - 0.45) - 0.45) / 0.06) ** 2)
    for mono, z, height, fwhm in species:
        sigma = fwhm / 2.3548
        for p in _isotope_peaks(mono, z, height, fwhm):
            y += p.ai * numpy.exp(-0.5 * ((x - p.mz) / sigma) ** 2)
    profile = numpy.column_stack((x, y)).astype(numpy.float64)
    seeds = []
    for mono, z, _height, _fwhm in species:
        peak = mpp.labelpeak(signal=profile, mz=mono)
        assert peak is not None
        peak.setcharge(z)
        peak.setisotope(0)
        seeds.append(peak)
    return seeds, profile


def _peaklist(peaks):
    return peaks if isinstance(peaks, mspy.peaklist) else mspy.peaklist(list(peaks))


def _convert(peaks, profile, mzs, params=PARAMS):
    """The "Convert to Envelopes" action on the peaks at the given m/z."""
    return mpp.recalculate_neighborhood_envelopes(
        _peaklist(peaks), profile, list(mzs), params, selectedOnly=True
    )


def _convert_all(peaks, profile, params=PARAMS):
    peaks = list(peaks)
    return _convert(peaks, profile, [p.mz for p in peaks], params)


def _envelope_at(peaklist, mz):
    """The monoisotopic envelope peak nearest m/z."""
    return min(
        (p for p in peaklist if p.attributes.get("envelope") and p.isotope in (None, 0)),
        key=lambda p: abs(p.mz - mz),
    )


def _without_envelope_of(peaklist, mz):
    """The peaks of the list, less every row of the envelope nearest m/z."""
    group = _envelope_at(peaklist, mz).group
    return [p for p in peaklist if p.group != group]


def _state(peak):
    return {
        "mz": peak.mz,
        "ai": peak.ai,
        "base": peak.base,
        "sn": peak.sn,
        "charge": peak.charge,
        "isotope": peak.isotope,
        "fwhm": peak.fwhm,
        "attributes": peak.attributes,
    }


def _differences(a, b, path=""):
    """Where two values differ (relative 1e-9 for numbers), as readable paths."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = ["%s.%s: only on one side" % (path, k) for k in set(a) ^ set(b)]
        for key in set(a) & set(b):
            out += _differences(a[key], b[key], "%s.%s" % (path, key))
        return out
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return ["%s: %d items vs %d" % (path, len(a), len(b))]
        out = []
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            out += _differences(x, y, "%s[%d]" % (path, i))
        return out
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(a - b) <= 1e-9 * max(abs(a), abs(b), 1e-9):
                return []
    elif a == b:
        return []
    return ["%s: %r vs %r" % (path, a, b)]


def assert_same_peaklist(expected, actual):
    """Both lists hold the same peaks in the same state; group names may differ
    (a conversion names new envelopes after the ones already in the list), but
    the grouping itself must not."""
    expected = sorted(expected, key=lambda p: p.mz)
    actual = sorted(actual, key=lambda p: p.mz)
    assert [round(p.mz, 6) for p in actual] == [round(p.mz, 6) for p in expected]
    groups = {}
    problems = []
    for a, b in zip(expected, actual, strict=True):
        if groups.setdefault(a.group, b.group) != b.group:
            problems.append("%.4f: grouped differently" % a.mz)
        problems += ["%.4f%s" % (a.mz, d) for d in _differences(_state(a), _state(b))]
    assert not problems, "\n".join(problems[:20])


def _snapshot(peaklist):
    return [(id(p), copy.deepcopy(_state(p)), p.group) for p in peaklist]


# ---------------------------------------------------------------------------
# Converting one peak next to envelopes = converting everything
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(FORESTS))
def test_converting_one_peak_equals_converting_all(name):
    """Every other species already an envelope, one a plain peak: converting
    that peak alone gives exactly what converting the whole list gives.

    Reported: converting one peak did not always re-fit its neighbours properly.
    It missed neighbours the fit puts together with it -- the selection
    estimated an envelope's reach from its isotopes above 2% of the apex, while
    the fit models them down to 1% and reads FWHMs beyond -- and it fitted with
    the width of the selection's base peak rather than the list's. Converting
    one peak then gave areas up to 65% off in these forests.
    """
    seeds, profile = _spectrum(FORESTS[name])
    everything = _convert_all(seeds, profile)

    for seed in seeds:
        peaklist = mspy.peaklist(_without_envelope_of(everything, seed.mz) + [copy.deepcopy(seed)])

        one = _convert(peaklist, profile, [seed.mz])

        assert_same_peaklist(_convert_all(peaklist, profile), one)
        assert_same_peaklist(everything, one)


@pytest.mark.parametrize("name", sorted(FORESTS))
def test_converting_two_neighbours_equals_converting_all(name):
    seeds, profile = _spectrum(FORESTS[name])
    everything = _convert_all(seeds, profile)

    for first, second in zip(seeds[:-1], seeds[1:], strict=True):
        rest = _without_envelope_of(_without_envelope_of(everything, first.mz), second.mz)
        peaklist = mspy.peaklist(rest + [copy.deepcopy(first), copy.deepcopy(second)])

        both = _convert(peaklist, profile, [first.mz, second.mz])

        assert_same_peaklist(everything, both)


def test_converting_one_peak_with_its_envelope_neighbours_selected_too():
    """Selecting the neighbouring envelopes along with the peak changes nothing."""
    seeds, profile = _spectrum(FOREST_MIXED)
    everything = _convert_all(seeds, profile)
    seed = seeds[3]
    rest = _without_envelope_of(everything, seed.mz)
    peaklist = mspy.peaklist(rest + [copy.deepcopy(seed)])
    neighbours = [p.mz for p in rest if abs(p.mz - seed.mz) < 6.0]
    assert len(neighbours) >= 3

    alone = _convert(peaklist, profile, [seed.mz])
    together = _convert(peaklist, profile, [seed.mz] + neighbours)

    assert_same_peaklist(together, alone)


def test_converting_a_peak_with_no_charge_yet():
    """A peak labelled by hand has no charge; deisotoping gives it one. The
    result still matches converting the whole list."""
    seeds, profile = _spectrum(FOREST_MIXED)
    everything = _convert_all(seeds, profile)

    for seed in seeds:
        bare = copy.deepcopy(seed)
        bare.setcharge(None)
        bare.setisotope(None)
        peaklist = mspy.peaklist(_without_envelope_of(everything, seed.mz) + [bare])

        assert_same_peaklist(
            _convert_all(peaklist, profile), _convert(peaklist, profile, [seed.mz])
        )


def test_all_isotopes_label_converting_one_peak_equals_converting_all():
    params = dict(PARAMS, labelEnvelope="isotopes")
    seeds, profile = _spectrum(FOREST_MIXED)
    everything = _convert_all(seeds, profile, params)

    for seed in seeds:
        peaklist = mspy.peaklist(_without_envelope_of(everything, seed.mz) + [copy.deepcopy(seed)])

        assert_same_peaklist(everything, _convert(peaklist, profile, [seed.mz], params))


# ---------------------------------------------------------------------------
# The neighbours are re-fitted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(FORESTS))
def test_neighbours_converted_before_the_peak_existed_are_refitted(name):
    """The workflow: convert the species around a peak, then label the peak and
    convert it. The neighbours were fitted without it and claimed its signal;
    converting it must re-fit every one of them, to what converting all of them
    together gives."""
    seeds, profile = _spectrum(FORESTS[name])
    everything = _convert_all(seeds, profile)

    for k, seed in enumerate(seeds):
        others = [copy.deepcopy(p) for i, p in enumerate(seeds) if i != k]
        before = _convert_all(others, profile)

        after = _convert(list(before) + [copy.deepcopy(seed)], profile, [seed.mz])

        assert_same_peaklist(everything, after)


def test_refitting_reaches_neighbours_of_neighbours():
    """The middle species overlaps both ends, which do not overlap each other:
    converting one end still re-fits the far end -- the middle one's area moved,
    and the far end shares signal with it."""
    species = [(1800.0, 1, 600.0, 0.11), (1802.0, 1, 900.0, 0.11), (1808.0, 1, 500.0, 0.11)]
    seeds, profile = _spectrum(species)
    everything = _convert_all(seeds, profile)
    # the far end only reaches the middle one, not the converted end
    near, middle, far = (_envelope_at(everything, mz) for mz in (1800.0, 1802.0, 1808.0))
    assert max(mz for mz, _w in near.attributes["envelope"]["isotopes"]) < far.mz - 1.0

    before = _convert_all(mspy.peaklist([copy.deepcopy(p) for p in seeds[1:]]), profile)
    after = _convert(mspy.peaklist(list(before) + [copy.deepcopy(seeds[0])]), profile, [1800.0])

    assert _envelope_at(after, 1808.0).attributes["envelope"]["area"] != pytest.approx(
        _envelope_at(before, 1808.0).attributes["envelope"]["area"], rel=1e-6
    )
    assert_same_peaklist(everything, after)


def test_neighbour_reached_only_by_the_modelled_tail_is_refitted():
    """A charge-3 species is modelled with 10 isotopes; its last one lands on a
    charge-1 species 3 Da up, which an estimate from the isotopes above 2% of
    the apex never reached. Converting the charge-3 peak must re-fit it."""
    species = [(1507.066, 3, 250.0, 0.095), (1510.078, 1, 240.0, 0.12)]
    seeds, profile = _spectrum(species)
    everything = _convert_all(seeds, profile)
    isotopes = _envelope_at(everything, 1507.066).attributes["envelope"]["isotopes"]
    assert abs(isotopes[-1][0] - 1510.078) < 0.05

    before = _convert_all(mspy.peaklist([copy.deepcopy(seeds[1])]), profile)
    after = _convert(mspy.peaklist(list(before) + [copy.deepcopy(seeds[0])]), profile, [1507.066])

    assert_same_peaklist(everything, after)


def test_base_peak_far_away_does_not_change_a_conversion():
    """The width a cluster is fitted with when it has none sets every fit
    window. It is the base peak's -- of the whole list, not of the peaks being
    converted -- so a strong, broad species far away counts the same either way."""
    species = [(1500.0, 1, 200.0, 0.05), (1502.0, 1, 150.0, 0.05), (1560.0, 1, 5000.0, 0.25)]
    seeds, profile = _spectrum(species)
    everything = _convert_all(seeds, profile)

    peaklist = mspy.peaklist(_without_envelope_of(everything, 1500.0) + [copy.deepcopy(seeds[0])])

    assert_same_peaklist(everything, _convert(peaklist, profile, [1500.0]))


# an isolated species, and envelopes 12-28 Da away: not fitted with it, but
# reading their pedestal and uncertainty over its span
FOREST_FAR = [
    (1002.43, 1, 60.0, 0.1),
    (1014.41, 1, 50.0, 0.1),
    (1016.44, 1, 150.0, 0.1),
    (1030.45, 1, 120.0, 0.1),
]


def test_converting_a_peak_refits_envelopes_reading_noise_over_it():
    """The far envelopes were converted while the peak was not in the list, so
    their uncertainty -- and their pedestal's comb -- was read over its signal
    as if it were background. Converting it makes its span known; they must be
    recalculated, as converting everything recalculates them."""
    seeds, profile = _comb_spectrum(FOREST_FAR)
    everything = _convert_all(seeds, profile)
    before = _convert_all([copy.deepcopy(p) for p in seeds[1:]], profile)

    after = _convert(list(before) + [copy.deepcopy(seeds[0])], profile, [1002.43])

    far = _envelope_at(before, 1014.41).attributes["envelope"]
    assert _envelope_at(after, 1014.41).attributes["envelope"]["areaError"] < 0.8 * far["areaError"]
    assert_same_peaklist(everything, after)


def test_deleting_a_peak_refits_envelopes_reading_noise_over_it():
    seeds, profile = _comb_spectrum(FOREST_FAR)
    everything = _convert_all(seeds, profile)
    rest = mspy.peaklist(_without_envelope_of(everything, 1002.43))

    recalculated = mpp.recalculate_neighborhood_envelopes(rest, profile, [1002.43], PARAMS)

    assert_same_peaklist(_convert_all(rest, profile), recalculated)


@pytest.mark.parametrize("sn", [5.0, 40.0])
def test_reconverting_does_not_depend_on_the_last_pedestal(sn):
    """An envelope's S/N is read off the pedestal of its last fit, so it carries
    history. Here A's +1 and +2 sit on the flank of a much larger B, whose +1
    apex is 0.055 Da off A's +2 position: inside the window an isotope may snap
    within at low S/N, outside it at high. Re-converting used to rebuild A's
    grid with a window set by that S/N -- an earlier fit could move its isotopes.
    A grid on A's own isotope positions is kept as it is instead."""
    a = 1000.0
    species = [(a, 1, 60.0, 0.1), (a + mspy.ISOTOPE_DISTANCE - 0.055, 1, 400.0, 0.1)]
    seeds, profile = _spectrum(species, noise=1.0)
    everything = _convert_all(seeds, profile)

    # as if A had last been fitted on another pedestal: same noise, other S/N
    earlier = copy.deepcopy(list(everything))
    peak = _envelope_at(earlier, a)
    noise = (peak.ai - peak.base) / peak.sn
    peak.setbase(peak.ai - sn * noise)
    peak.setsn(sn)

    assert_same_peaklist(everything, _convert_all(earlier, profile))


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_conversion_order_does_not_matter(seed):
    """All species are plain charged peaks after picking; converting them one at
    a time, in any order, ends where converting them all at once does."""
    seeds, profile = _spectrum(FOREST_MIXED)
    everything = _convert_all(seeds, profile)
    order = list(range(len(seeds)))
    random.Random(seed).shuffle(order)

    current = seeds
    for k in order:
        current = _convert(current, profile, [seeds[k].mz])

    assert_same_peaklist(everything, current)


# ---------------------------------------------------------------------------
# Plain peaks stay plain
# ---------------------------------------------------------------------------


def _mixed_neighbourhood():
    """A peak with every kind of neighbour: a plain charged peak and a bare one
    overlapping it, an envelope reached through the plain one, and an envelope
    far away. Returns (peaklist, profile, peak to convert)."""
    species = [
        (1800.0, 1, 500.0, 0.11),  # converted
        (1802.0, 1, 700.0, 0.11),  # plain charged, overlaps it
        (1804.0, 1, 600.0, 0.11),  # envelope, overlaps the plain one
        (1860.0, 1, 900.0, 0.11),  # envelope, far away
    ]
    seeds, profile = _spectrum(species)
    envelopes = _convert(mspy.peaklist([seeds[2], seeds[3]]), profile, [1804.0, 1860.0])
    bare = mpp.labelpeak(signal=profile, mz=1801.0)  # no charge at all
    peaklist = mspy.peaklist([seeds[0], seeds[1], bare] + list(envelopes))
    return peaklist, profile, seeds[0]


def test_converting_a_peak_leaves_plain_neighbours_untouched():
    peaklist, profile, peak = _mixed_neighbourhood()
    plain = [p for p in peaklist if not p.attributes.get("envelope") and p is not peak]
    far = _envelope_at(peaklist, 1860.0)
    snapshot = {id(p): copy.deepcopy(_state(p)) for p in plain + [far]}

    result = _convert(peaklist, profile, [peak.mz])

    # the very same objects, in the very same state, still not envelopes
    for p in plain + [far]:
        assert any(q is p for q in result)
        assert not _differences(snapshot[id(p)], _state(p))
        if p is not far:
            assert not p.attributes.get("envelope")
            assert not p.group
    envelopes = sorted(round(p.mz) for p in result if p.attributes.get("envelope"))
    assert envelopes == [1800, 1804, 1860]


def test_plain_neighbour_does_not_make_the_selection_matter():
    """With a plain neighbour in the way, converting the peak alone or with the
    envelopes around it still gives the same; the plain one stays plain."""
    peaklist, profile, peak = _mixed_neighbourhood()

    alone = _convert(peaklist, profile, [peak.mz])
    together = _convert(peaklist, profile, [peak.mz, 1804.0, 1860.0])

    assert_same_peaklist(together, alone)
    assert not next(p for p in alone if round(p.mz) == 1802).attributes.get("envelope")


def test_converting_does_not_modify_the_list_it_was_given():
    """The undo step of a conversion is taken from the list after the conversion
    ran, so the conversion must leave it alone: a peak with no charge used to
    come back from Undo charged, its width re-measured."""
    peaklist, profile, peak = _mixed_neighbourhood()
    peak.setcharge(None)
    peak.setisotope(None)
    before = _snapshot(peaklist)

    _convert(peaklist, profile, [peak.mz])
    _convert_all(peaklist, profile)

    after = _snapshot(peaklist)
    for (idA, stateA, groupA), (idB, stateB, groupB) in zip(before, after, strict=True):
        assert idA == idB and groupA == groupB
        assert not _differences(stateA, stateB)


# ---------------------------------------------------------------------------
# Re-converting and deleting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label", ["1st", "isotopes"])
def test_reconverting_any_envelope_changes_nothing(label):
    """Under "All Isotopes" every isotope row used to write its own measured
    width into the envelope they share, so re-converting left it the width of
    the last row -- on a noisy tail a fraction of the real one."""
    params = dict(PARAMS, labelEnvelope=label)
    seeds, profile = _spectrum(FOREST_MIXED)
    everything = _convert_all(seeds, profile, params)

    for seed in seeds:
        again = _convert(everything, profile, [_envelope_at(everything, seed.mz).mz], params)
        assert_same_peaklist(everything, again)


@pytest.mark.parametrize("name", sorted(FORESTS))
def test_deleting_an_envelope_refits_what_it_was_fitted_with(name):
    """After a delete, the recalculation re-fits every envelope the deleted one
    was fitted together with -- including those its modelled tail reached
    beyond the old fixed window around the deleted peak -- to what converting
    the remaining list gives."""
    seeds, profile = _spectrum(FORESTS[name])
    everything = _convert_all(seeds, profile)

    for seed in seeds:
        deleted = _envelope_at(everything, seed.mz)
        rest = mspy.peaklist(_without_envelope_of(everything, seed.mz))

        recalculated = mpp.recalculate_neighborhood_envelopes(rest, profile, [deleted.mz], PARAMS)

        assert_same_peaklist(_convert_all(rest, profile), recalculated)
