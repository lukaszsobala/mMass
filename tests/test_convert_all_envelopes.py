"""Tests for "Convert All to Envelopes", in one document and in all of them.

The GUI action runs the helpers in gui.processing, which take the documents
and settings as arguments, so it is tested here without a window.
"""

import pytest

import mspy

from .helpers import build_envelope_peaklist

pytest.importorskip("gui.doc", reason="GUI stack (wx) not available")

from gui import doc, processing  # noqa: E402


@pytest.fixture
def settings(envelope_params):
    deisotoping = {key: value for key, value in envelope_params.items() if key != "seedCharge"}
    return {"deisotoping": deisotoping, "peakpicking": {"averagineType": "protein"}}


def _document(title, formula="C50H80N14O18", height=1000.0):
    document = doc.document()
    document.title = title
    peaklist = build_envelope_peaklist(formula=formula, height=height)
    document.spectrum = mspy.scan(
        profile=mspy.profile(peaklist, fwhm=0.05, points=20), peaklist=peaklist
    )
    return document


def _envelopes(peaklist):
    return [peak for peak in peaklist if peak.attributes.get("envelope")]


def test_the_seed_charge_is_a_charged_peak_then_the_typed_charge_then_1():
    plain = mspy.peak(mz=500.0, ai=10.0)
    charged = mspy.peak(mz=600.0, ai=10.0)
    charged.charge = 2

    assert processing.seedCharge([plain, charged], "3") == 2
    assert processing.seedCharge([plain], " 3 ") == 3
    assert processing.seedCharge([plain], "-2") == -2
    assert processing.seedCharge([plain], "0") == 1
    assert processing.seedCharge([plain], "x") == 1
    assert processing.seedCharge([plain]) == 1


def test_convert_all_turns_every_peak_into_an_envelope(settings):
    document = _document("a")
    peaklist = document.spectrum.peaklist

    result = processing.convertToEnvelopes(peaklist, document.spectrum.profile, settings)

    assert result is not peaklist
    envelopes = _envelopes(result)
    assert envelopes and all(peak.attributes["envelope"]["area"] > 0.0 for peak in envelopes)
    empty = mspy.peaklist([])
    assert processing.convertToEnvelopes(empty, None, settings) is empty


def test_jobs_skip_documents_without_peaks_and_the_typed_charge_is_the_current_documents():
    current, other = _document("current"), _document("other")
    blank = doc.document()
    blank.spectrum = mspy.scan()

    jobs = processing.envelopeJobs([current, blank, other], current=current, typed="2")

    assert [(index, document, charge) for index, document, _peaklist, charge in jobs] == [
        (0, current, 2),
        (2, other, 1),
    ]
    assert all(peaklist is document.spectrum.peaklist for _i, document, peaklist, _c in jobs)


def test_all_documents_get_what_each_would_get_alone(settings):
    documents = [_document("a"), _document("b", formula="C60H90N16O20", height=600.0)]
    expected = [
        processing.convertToEnvelopes(d.spectrum.peaklist, d.spectrum.profile, settings)
        for d in documents
    ]
    jobs = processing.envelopeJobs(documents)
    progress = {"done": 0}

    results, failures = processing.fitEnvelopeJobs(jobs, settings, progress)
    changed = []
    processing.applyEnvelopeResults(documents, jobs, results, changed)

    assert failures == [] and progress["done"] == 2 and changed == [0, 1]
    for document, alone in zip(documents, expected, strict=True):
        got = _envelopes(document.spectrum.peaklist)
        want = _envelopes(alone)
        assert [peak.mz for peak in got] == pytest.approx([peak.mz for peak in want])
        assert [peak.attributes["envelope"]["area"] for peak in got] == pytest.approx(
            [peak.attributes["envelope"]["area"] for peak in want]
        )


def test_each_document_can_be_undone_on_its_own(settings):
    documents = [_document("a"), _document("b")]
    before = [len(d.spectrum.peaklist) for d in documents]
    jobs = processing.envelopeJobs(documents)

    results, _failures = processing.fitEnvelopeJobs(jobs, settings)
    processing.applyEnvelopeResults(documents, jobs, results, [])

    assert documents[0].restore()
    assert len(documents[0].spectrum.peaklist) == before[0]
    assert not _envelopes(documents[0].spectrum.peaklist)
    assert _envelopes(documents[1].spectrum.peaklist)


def test_a_failing_document_is_reported_and_the_others_still_convert(settings, monkeypatch):
    documents = [_document("bad"), _document("good")]
    convert = processing.convertToEnvelopes

    def failing(peaklist, profile, settings, charge=None):
        if peaklist is documents[0].spectrum.peaklist:
            raise ValueError("broken")
        return convert(peaklist, profile, settings, charge)

    monkeypatch.setattr(processing, "convertToEnvelopes", failing)
    jobs = processing.envelopeJobs(documents)
    progress = {"done": 0}

    results, failures = processing.fitEnvelopeJobs(jobs, settings, progress)

    assert list(results) == [1]
    assert [(title, str(error)) for title, error in failures] == [("bad", "broken")]
    assert progress["done"] == 2


def test_results_go_only_to_the_peak_lists_they_were_fitted_from(settings):
    edited, moved, kept = _document("edited"), _document("moved"), _document("kept")
    documents = [edited, moved, kept]
    jobs = processing.envelopeJobs(documents)
    results, _failures = processing.fitEnvelopeJobs(jobs, settings)

    # meanwhile one peak list was replaced, and another document took the
    # place of one
    replacement = mspy.peaklist(list(edited.spectrum.peaklist))
    edited.spectrum.peaklist = replacement
    documents[1] = _document("opened")
    changed = []
    processing.applyEnvelopeResults(documents, jobs, results, changed)

    assert changed == [2]
    assert edited.spectrum.peaklist is replacement and edited.undo is None
    assert not _envelopes(moved.spectrum.peaklist) and moved.undo is None
    assert _envelopes(kept.spectrum.peaklist)
