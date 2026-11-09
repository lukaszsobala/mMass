"""Tests for the undo history of documents (gui.undo, gui.doc)."""

import copy

import numpy
import pytest

import mspy

pytest.importorskip("gui.doc", reason="GUI stack (wx) not available")

from gui import config, doc, undo  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_histories():
    """Steps left by other tests count against the shared memory budget."""

    for history in list(undo._histories):
        history.clear()
    yield


def _profile(points=1000, height=100.0):
    x = numpy.linspace(400.0, 410.0, points)
    return numpy.column_stack([x, height * numpy.exp(-0.5 * ((x - 405.0) / 0.05) ** 2)])


def _document(points=1000):
    document = doc.document()
    document.spectrum = mspy.scan(profile=_profile(points), peaklist=mspy.peaklist([]))
    return document


def _addPeak(document, mz, label=None):
    document.backup(("spectrum"), label=label)
    document.spectrum.peaklist.append(mspy.peak(mz=mz, ai=10.0))


def _mzs(document):
    return [peak.mz for peak in document.spectrum.peaklist]


def _run(scans=3):
    """An LC-MS run showing its first scan."""

    document = doc.document()
    document.scanlist = {scanID: {"retentionTime": 10.0 * scanID} for scanID in range(1, scans + 1)}
    for scanID in document.scanlist:
        document.scanCache[scanID] = mspy.scan(profile=_profile(), peaklist=mspy.peaklist([]))
    document.spectrum = document.scanCache[1]
    document.currentScanID = 1
    return document


def test_undo_and_redo_go_back_and_forward_many_steps():
    document = _document()
    for mz in (401.0, 402.0, 403.0):
        _addPeak(document, mz)

    assert document.restore() == ("spectrum",)
    assert _mzs(document) == [401.0, 402.0]
    document.restore()
    document.restore()
    assert _mzs(document) == []
    assert document.restore() is False

    document.forward()
    document.forward()
    assert _mzs(document) == [401.0, 402.0]
    document.forward()
    assert _mzs(document) == [401.0, 402.0, 403.0]
    assert document.forward() is False


def test_a_new_edit_after_undo_drops_what_was_undone():
    document = _document()
    _addPeak(document, 401.0)
    _addPeak(document, 402.0)
    document.restore()

    _addPeak(document, 409.0)

    assert document.redo is None and document.forward() is False
    document.restore()
    assert _mzs(document) == [401.0]


def test_undo_and_redo_say_what_they_change():
    document = _document()
    assert document.undoLabel() is None and document.redoLabel() is None

    _addPeak(document, 401.0, label="Add Peak")
    document.backup(("rulers",))
    assert document.undoLabel() == "Difference Label Edit"

    document.restore()
    assert document.undoLabel() == "Add Peak"
    assert document.redoLabel() == "Difference Label Edit"


def test_stripping_parts_a_step_lacks_leaves_it_alone(monkeypatch):
    step = undo.Step("Add Peak", ("spectrum",), {"spectrum": mspy.scan()})
    monkeypatch.setattr(undo, "approximateSize", lambda value: pytest.fail("measured again"))

    assert step.strip(undo.DOCUMENT_ITEMS)
    assert step.items == ("spectrum",)


def test_a_single_name_is_one_part_not_its_letters():
    assert undo.normalizeItems("annotations") == ("annotations",)
    assert undo.normalizeItems(("spectrum", "notations")) == ("spectrum", "notations")
    assert undo.normalizeItems(None) == ()


def test_a_run_of_typing_is_one_step():
    document = _document()
    _addPeak(document, 401.0, label="Add Peak")
    for text in ("n", "no", "not", "note"):
        document.backup(("info",), label="Document Information", coalesce=True)
        document.notes = text

    assert [step.label for step in document.history().undoSteps] == ["Add Peak", "Document Information"]
    document.restore()
    assert document.notes == ""


def test_typing_after_undo_or_another_edit_is_a_new_step():
    document = _document()
    document.backup(("info",), label="Document Information", coalesce=True)
    document.notes = "a"
    _addPeak(document, 401.0, label="Add Peak")
    document.backup(("info",), label="Document Information", coalesce=True)
    document.notes = "ab"
    document.restore()
    document.backup(("info",), label="Document Information", coalesce=True)

    labels = [step.label for step in document.history().undoSteps]
    assert labels == ["Document Information", "Add Peak", "Document Information"]


def test_old_steps_go_past_the_step_limit(monkeypatch):
    # a copy: the real section would save itself to the config file
    monkeypatch.setattr(config, "main", dict(config.main, undoSteps=3))
    document = _document()
    for mz in (401.0, 402.0, 403.0, 404.0, 405.0):
        _addPeak(document, mz)

    while document.restore():
        pass

    assert _mzs(document) == [401.0, 402.0]


def test_unchanged_profiles_are_stored_once():
    document = _document(points=100000)
    for mz in numpy.linspace(401.0, 409.0, 20):
        _addPeak(document, float(mz))

    profileBytes = document.spectrum.profile.nbytes
    assert profileBytes < undo.memoryUsed() < 2 * profileBytes


def test_the_history_never_sees_later_edits_of_a_profile():
    document = _document()
    original = document.spectrum.profile.copy()
    _addPeak(document, 401.0)
    _addPeak(document, 402.0)

    document.restore()
    document.spectrum.profile[:, 1] *= 2.0
    document.restore()

    numpy.testing.assert_array_equal(document.spectrum.profile, original)


def test_the_oldest_steps_of_all_documents_go_past_the_memory_budget(monkeypatch):
    first, second = _document(points=50000), _document(points=50000)
    profileBytes = first.spectrum.profile.nbytes
    monkeypatch.setattr(doc, "undoLimits", lambda: (50, int(3.5 * profileBytes)))

    def smooth(document):
        document.backup(("spectrum"), label="Smoothing")
        document.spectrum.profile = document.spectrum.profile * 0.9

    smooth(first)
    smooth(first)
    smooth(second)
    smooth(second)

    # four different profiles do not fit: the oldest step, the first
    # document's first, went
    assert len(first.history().undoSteps) == 1
    assert len(second.history().undoSteps) == 2
    assert undo.memoryUsed() <= 3.5 * profileBytes


def test_the_step_just_made_stays_even_over_the_budget(monkeypatch):
    monkeypatch.setattr(doc, "undoLimits", lambda: (50, 1))
    document = _document()

    _addPeak(document, 401.0)
    _addPeak(document, 402.0)

    assert len(document.history().undoSteps) == 1
    document.restore()
    assert _mzs(document) == [401.0]


def test_notations_bring_back_annotations_and_sequence_matches():
    document = _document()
    document.annotations.append(doc.annotation("a", 401.0, 10.0))
    sequence = mspy.sequence("ACDEFGHIK")
    sequence.matches = [doc.match("b2", 402.0, 10.0)]  # pyright: ignore[reportAttributeAccessIssue]
    document.sequences.append(sequence)

    document.backup(("spectrum", "notations"), label="Peak Picking")
    del document.annotations[:]
    del document.sequences[0].matches[:]
    document.restore()

    assert [item.label for item in document.annotations] == ["a"]
    assert [item.label for item in document.sequences[0].matches] == ["b2"]


def test_a_cancelled_edit_leaves_no_step_and_keeps_what_can_be_redone():
    document = _document()
    _addPeak(document, 401.0, label="Add Peak")
    _addPeak(document, 402.0, label="Label Peak")
    document.restore()
    document.backup(("annotations"), label="Edit Annotation")

    document.discardBackup()

    assert document.undoLabel() == "Add Peak"
    assert document.redoLabel() == "Label Peak"
    document.forward()
    assert _mzs(document) == [401.0, 402.0]


def test_an_edited_sequence_does_not_come_back_by_undo():
    document = _document()
    sequence = mspy.sequence("ACDEFGHIK")
    sequence.matches = []  # pyright: ignore[reportAttributeAccessIssue]
    document.sequences.append(sequence)
    _addPeak(document, 401.0, label="Add Peak")
    document.backup(("sequences"), label="Annotate Sequence Matches")
    document.backup(("spectrum", "notations"), label="Peak Picking")

    document.forgetSteps(("sequences", "notations"))

    steps = document.history().undoSteps
    assert [step.label for step in steps] == ["Add Peak", "Peak Picking"]
    assert steps[-1].items == ("spectrum",) and set(steps[-1].state) == {"spectrum"}


def test_a_copied_document_has_no_history():
    document = _document()
    _addPeak(document, 401.0)

    copied = copy.deepcopy(document)

    assert copied.undo is None and copied.restore() is False
    assert document.undo == ("spectrum",)
    assert _mzs(copied) == [401.0]


def test_each_scan_of_a_run_keeps_its_own_history():
    document = _run()
    _addPeak(document, 401.0, label="Add Peak")

    document.showScan(2, document.scanCache[2])
    assert document.undo is None
    _addPeak(document, 405.0, label="Label Peak")

    document.showScan(1, document.scanCache[1])
    assert document.undoLabel() == "Add Peak"
    document.restore()
    assert _mzs(document) == []
    assert [peak.mz for peak in document.scanCache[2].peaklist] == [405.0]


def test_whole_document_steps_are_forgotten_on_leaving_a_scan():
    document = _run()
    document.backup(("spectrum", "notations"), label="Peak Picking")
    document.backup(("annotations"), label="Annotate Peak")

    document.showScan(2, document.scanCache[2])
    document.showScan(1, document.scanCache[1])

    steps = document.history().undoSteps
    assert [(step.label, step.items) for step in steps] == [("Peak Picking", ("spectrum",))]


def _addRuler(document, mz, scanID):
    document.backup(("rulers",), label="Add Difference Label")
    document.rulers.append(doc.ruler(mz, 10.0, mz + 1.0, 10.0, scanID=scanID))


def test_label_steps_survive_switching_scans():
    document = _run()
    _addRuler(document, 401.0, 1)
    document.showScan(2, document.scanCache[2])
    document.showScan(1, document.scanCache[1])

    document.restore()

    assert document.rulers == []


def test_labels_edited_on_another_scan_never_come_back_by_undo():
    document = _run()
    _addRuler(document, 401.0, 1)
    document.showScan(2, document.scanCache[2])
    _addRuler(document, 405.0, 2)

    document.showScan(1, document.scanCache[1])

    assert document.undo is None
    assert [(ruler.mz1, ruler.scanID) for ruler in document.rulers] == [(401.0, 1), (405.0, 2)]


def test_only_the_labels_of_the_scan_shown_are_drawn():
    document = _run()
    document.rulers[:] = [
        doc.ruler(401.0, 10.0, 402.0, 10.0, scanID=1),
        doc.ruler(403.0, 10.0, 404.0, 10.0, scanID=2),
        doc.ruler(405.0, 10.0, 406.0, 10.0),
    ]

    assert [ruler.mz1 for ruler in document.shownRulers()] == [401.0, 405.0]


def test_a_combined_spectrum_takes_its_history_with_it():
    document = _run()
    _addPeak(document, 401.0, label="Add Peak")
    document.showCombined(
        mspy.scan(profile=_profile(), peaklist=mspy.peaklist([])),
        {"mode": "average", "scans": [1, 2], "rtRange": (10.0, 20.0), "acquisition": ""},
    )
    _addPeak(document, 405.0, label="Label Peak")

    document.showScan(1, document.scanCache[1])

    assert doc.COMBINED_SCAN_ID not in document._histories
    assert document.undoLabel() == "Add Peak"


def test_scans_edited_while_not_shown_lose_their_history():
    document = _run()
    _addPeak(document, 401.0)
    document.showScan(2, document.scanCache[2])
    _addPeak(document, 405.0)

    document.forgetOtherScans()

    assert list(document._histories) == [2]


def test_closing_a_document_frees_its_whole_history():
    document = _run()
    _addPeak(document, 401.0)
    document.showScan(2, document.scanCache[2])
    _addPeak(document, 405.0)

    document.clearHistory(allScans=True)

    assert document._histories == {} and undo.memoryUsed() == 0
