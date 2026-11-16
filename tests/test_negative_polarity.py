"""Charges are signed: negative-mode spectra get negative charges.

Label Envelope always signed the charge it assigns from the spectrum's
polarity, while deisotoping (Find Peaks), Convert to Envelopes and the
neighbourhood recalculation used the max. charge and the fallback charge as
given, so a negative-mode peak came out as z=+1 -- [M+H]+ instead of [M-H]-,
its neutral mass two protons off. The same data read as negative mode must
now give the same peaks and envelopes as in positive mode, only with the
charges negated.
"""

import pytest

import mspy

from .helpers import build_envelope_peaklist, scalar

pytest.importorskip("gui.doc", reason="GUI stack (wx) not available")

from gui import doc, processing  # noqa: E402


@pytest.fixture
def settings(envelope_params):
    deisotoping = {key: value for key, value in envelope_params.items() if key != "seedCharge"}
    deisotoping.update(
        convertToEnvelopes=False, removeIsotopes=False, removeUnknown=False
    )
    return {"deisotoping": deisotoping, "peakpicking": {"averagineType": "protein"}}


def _scan(polarity):
    """Two species, a singly and a doubly charged one, read as the given
    polarity (the same m/z data either way, so only the sign may differ)."""

    single = build_envelope_peaklist(formula="C50H80N14O18", charge=1, height=1000.0)
    double = build_envelope_peaklist(formula="C90H140N26O30", charge=2, height=600.0)
    peaklist = mspy.peaklist([mspy.peak(mz=p.mz, ai=p.ai, fwhm=p.fwhm) for p in list(single) + list(double)])
    scan = mspy.scan(profile=mspy.profile(peaklist, fwhm=0.05, points=20), peaklist=peaklist)
    scan.polarity = polarity
    return scan


def _charges(peaklist):
    return [(round(peak.mz, 6), peak.charge, peak.isotope) for peak in peaklist]


def _envelopes(peaklist):
    return [peak for peak in peaklist if peak.attributes.get("envelope")]


def test_a_charge_takes_the_sign_of_the_polarity():
    assert processing.signedCharge(2, -1) == -2
    assert processing.signedCharge(2, 1) == 2
    assert processing.signedCharge(2, None) == 2
    # typed negative by hand: kept, whatever the polarity says
    assert processing.signedCharge(-2, -1) == -2
    assert processing.signedCharge(-2, 1) == -2
    assert processing.signedCharge(None, -1) is None


def test_the_fallback_seed_charge_is_negative_in_negative_mode():
    plain = mspy.peak(mz=500.0, ai=10.0)
    charged = mspy.peak(mz=600.0, ai=10.0)
    charged.charge = -2

    assert processing.seedCharge([plain], polarity=-1) == -1
    assert processing.seedCharge([plain], "3", polarity=-1) == -3
    assert processing.seedCharge([plain], "-3", polarity=-1) == -3
    # a charged peak's own charge is taken as it is
    assert processing.seedCharge([plain, charged], "3", polarity=-1) == -2
    assert processing.seedCharge([plain], polarity=1) == 1


def test_envelope_params_sign_both_charges():
    deisotoping = {
        "massTolerance": 0.05, "isotopeShift": 0.0, "maxCharge": 3,
        "intTolerance": 0.5, "labelEnvelope": "1st", "envelopeIntensity": "maximum",
        "envelopeNonIdeality": 0.4,
    }
    settings = {"deisotoping": deisotoping, "peakpicking": {}}

    params = processing.envelopeParams(settings, seedCharge=2, polarity=-1)
    assert (params["maxCharge"], params["seedCharge"]) == (-3, -2)

    params = processing.envelopeParams(settings, seedCharge=2, polarity=1)
    assert (params["maxCharge"], params["seedCharge"]) == (3, 2)


def test_find_peaks_charges_negative_mode_peaks_negatively(settings):
    positive, negative = _scan(1), _scan(-1)

    processing.deisotopeScan(positive, settings)
    processing.deisotopeScan(negative, settings)

    found = _charges(positive.peaklist)
    assert {1, 2} <= {charge for _mz, charge, _iso in found}
    assert _charges(negative.peaklist) == [
        (mz, -charge if charge else charge, isotope) for mz, charge, isotope in found
    ]


def test_negative_mode_masses_are_deprotonated(settings):
    positive, negative = _scan(1), _scan(-1)
    processing.deisotopeScan(positive, settings)
    processing.deisotopeScan(negative, settings)

    mono = [peak for peak in positive.peaklist if peak.charge == 1 and peak.isotope == 0][0]
    twin = [peak for peak in negative.peaklist if abs(peak.mz - mono.mz) < 1e-9][0]

    # [M+H]+ and [M-H]- at the same m/z are two proton masses apart
    proton = 1.00727646688
    assert abs(scalar(twin.mass()) - scalar(mono.mass()) - 2 * proton) < 1e-4


def _assert_mirrored(positive, negative):
    """The same envelopes with the charges negated.

    Not to the last digit: the averagine pattern is built for the neutral mass,
    which at the same m/z is two protons (per charge) heavier for [M-H]- than
    for [M+H]+, so the isotope weights -- and the areas fitted with them --
    shift by a fraction of a percent. Where the isotopes are is the same.
    """

    pos, neg = _envelopes(positive), _envelopes(negative)
    assert pos and len(pos) == len(neg)
    for a, b in zip(pos, neg, strict=True):
        assert abs(a.mz - b.mz) < 1e-9
        assert b.charge == -a.charge
        envA, envB = a.attributes["envelope"], b.attributes["envelope"]
        assert envB["area"] == pytest.approx(envA["area"], rel=5e-3)
        assert envB["fwhm"] == pytest.approx(envA["fwhm"], rel=1e-9)
        assert len(envA["isotopes"]) == len(envB["isotopes"])
        for (mzA, wA), (mzB, wB) in zip(envA["isotopes"], envB["isotopes"], strict=True):
            assert float(mzB) == pytest.approx(float(mzA), abs=1e-9)
            # the weights sum to 1; the smallest tail ones move most, relatively
            assert float(wB) == pytest.approx(float(wA), abs=2e-3)


def test_convert_to_envelopes_mirrors_positive_mode(settings):
    positive, negative = _scan(1), _scan(-1)

    # uncharged peaks: the fallback seed charge alone decides the sign
    processing.convertScanToEnvelopes(positive, settings)
    processing.convertScanToEnvelopes(negative, settings)

    assert all(peak.charge > 0 for peak in _envelopes(positive.peaklist))
    _assert_mirrored(positive.peaklist, negative.peaklist)


def test_deisotoped_then_converted_mirrors_positive_mode(settings):
    positive, negative = _scan(1), _scan(-1)
    for scan in (positive, negative):
        processing.deisotopeScan(scan, settings)
        processing.convertScanToEnvelopes(scan, settings)

    _assert_mirrored(positive.peaklist, negative.peaklist)


def test_convert_all_in_all_documents_signs_each_documents_charges(settings):
    def document(polarity):
        d = doc.document()
        d.spectrum = _scan(polarity)
        return d

    negative, positive = document(-1), document(1)
    jobs = processing.envelopeJobs([negative, positive], current=negative, typed="2")
    assert [charge for _i, _d, _pl, charge in jobs] == [-2, 1]

    results, failures = processing.fitEnvelopeJobs(jobs, settings)
    assert not failures
    assert all(peak.charge < 0 for peak in _envelopes(results[0]))
    assert all(peak.charge > 0 for peak in _envelopes(results[1]))


def test_recalculating_a_neighbourhood_seeds_negative_charges(settings):
    scan = _scan(-1)
    params = processing.envelopeParams(settings, seedCharge=1, polarity=scan.polarity)

    result = mspy.recalculate_neighborhood_envelopes(
        scan.peaklist, scan.profile, [peak.mz for peak in scan.peaklist], params,
        selectedOnly=True,
    )

    envelopes = _envelopes(result)
    assert envelopes and all(peak.charge < 0 for peak in envelopes)
