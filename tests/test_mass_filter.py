"""Mass filter: which peaks "Remove" deletes.

panel_mass_filter imports wx, so the module skips where the GUI stack is
unavailable; the function tested needs no window.
"""

import pytest

import mspy

panel = pytest.importorskip("gui.panel_mass_filter", reason="GUI stack (wx) not available")
gdoc = pytest.importorskip("gui.doc", reason="GUI stack (wx) not available")


def _matches(peaklist, indexes):
    out = []
    for index in indexes:
        match = gdoc.match("", peaklist[index].mz, peaklist[index].ai)
        match.peakIndex = index
        out.append(match)
    return out


def _peaks(*mzs):
    return mspy.peaklist([mspy.peak(mz=mz, ai=100.0) for mz in mzs])


def test_matches_name_the_peaks_they_were_made_on():
    peaks = _peaks(100.0, 200.0, 300.0)
    assert panel.matchedPeakIndexes(peaks, _matches(peaks, [2, 0, 2])) == [2, 0]


def test_peaks_picked_again_since_matching_are_found_by_mz():
    """A new peak below shifts the list: the matched peak is deleted, not the
    one that came to stand at its old index."""
    matched = _matches(_peaks(100.0, 200.0, 300.0), [1])
    repicked = _peaks(50.0, 100.0, 200.0, 300.0)
    assert panel.matchedPeakIndexes(repicked, matched) == [2]


def test_a_matched_peak_gone_since_is_left_out():
    matched = _matches(_peaks(100.0, 200.0, 300.0), [1, 2])
    repicked = _peaks(100.0, 200.4)
    assert panel.matchedPeakIndexes(repicked, matched) == []
