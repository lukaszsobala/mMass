"""Peak Differences: labelling the differences found in the spectrum.

The helpers that pick the differences to label and name them live in
gui.panel_peak_differences, which imports wx, so the module skips where the
GUI stack is unavailable.
"""

import pytest

panel = pytest.importorskip(
    "gui.panel_peak_differences", reason="GUI stack (wx) not available"
)
gdoc = pytest.importorskip("gui.doc", reason="GUI stack (wx) not available")


HEX = 162.052824
SINGLES = [("Hex", HEX, 162.1406, "Sugars"), ("dHex", 146.057909, 146.1412, "Sugars")]
PAIRS = [("2×Hex", 2 * HEX, 324.2812, "Sugars")]


def table(mzs, matched=()):
    """Differences table as runSearch makes it, the (i, j) in matched matched."""

    rows = []
    for x, mz in enumerate(mzs):
        row = [(mz, x)]
        for y in range(x + 1):
            row.append((mz - mzs[y], "single" if (x, y + 1) in matched else False))
        rows.append(row)
    return rows


def test_table_position_mirrors_the_grid():
    assert panel.tablePosition(2, 2) is None
    # below and above the diagonal show the same difference
    assert panel.tablePosition(2, 0) == (2, 1)
    assert panel.tablePosition(0, 2) == (2, 1)


def test_matched_positions_skip_the_peak_with_itself():
    rows = table([1000.0, 1162.052824, 1324.1], matched={(1, 1), (2, 2)})
    assert panel.matchedPositions(rows) == [(1, 1), (2, 2)]
    for i, j in panel.matchedPositions(rows):
        assert rows[i][j][0] == pytest.approx(rows[i][0][0] - rows[j - 1][0][0])


def test_difference_matches_prefer_value_then_singles_over_pairs():
    matches = panel.differenceMatches(HEX + 0.001, None, SINGLES, PAIRS, 0.01)
    assert [m[0] for m in matches] == ["Hex"]
    assert matches[0][3] == pytest.approx(HEX)

    # pairs only without a single entry matching
    matches = panel.differenceMatches(2 * HEX, None, SINGLES, PAIRS, 0.01)
    assert [m[0] for m in matches] == ["2×Hex"]

    # the value searched for comes first
    matches = panel.differenceMatches(HEX, 162.05, SINGLES, PAIRS, 0.01)
    assert [m[0] for m in matches] == ["162.05", "Hex"]
    assert matches[0][3] == 162.05

    assert panel.differenceMatches(50.0, None, SINGLES, PAIRS, 0.01) == []


def test_has_ruler_matches_both_ends_and_scan():
    rulers = [gdoc.ruler(1000.0, 1.0, 1162.052824, 1.0, scanID=3)]
    assert panel.hasRuler(rulers, 1000.0, 1162.052824, 3)
    assert not panel.hasRuler(rulers, 1000.0, 1162.052824, None)
    assert not panel.hasRuler(rulers, 1000.0, 1324.1, 3)


def test_a_value_searched_for_names_the_label_on_its_own():
    # no lists at all: the value typed in is all there is to match
    matches = panel.differenceMatches(18.0105, 18.0, [], [], 0.05)
    assert [m[0] for m in matches] == ["18"]
    assert matches[0][3] == 18.0
    assert panel.valueName(162.05) == "162.05"
    assert panel.valueName(18.0) == "18"


# CHOOSING ENTRIES

differences = pytest.importorskip("gui.differences", reason="GUI stack (wx) not available")

ENTRIES = ["Hex", "dHex", "HexNAc"]


def test_list_state_goes_by_the_entries_left_out():
    assert differences.listState([], [], "Sugars", ENTRIES) == "none"
    assert differences.listState(["Sugars"], [], "Sugars", ENTRIES) == "all"
    assert differences.listState(["Sugars"], [["Sugars", "Hex"]], "Sugars", ENTRIES) == "some"
    left = [["Sugars", name] for name in ENTRIES]
    assert differences.listState(["Sugars"], left, "Sugars", ENTRIES) == "none"


def test_ticking_a_list_matches_all_of_it():
    lists, excluded = differences.setListMatched(
        ["Sugars"], [["Sugars", "Hex"], ["Other", "X"]], "Sugars", True
    )
    assert lists == ["Sugars"]
    assert excluded == [["Other", "X"]]

    lists, excluded = differences.setListMatched(lists, excluded, "Sugars", False)
    assert lists == []


def test_ticking_an_entry_of_a_list_not_matched_matches_it_alone():
    lists, excluded = differences.setEntryMatched([], [], "Sugars", "dHex", True, ENTRIES)
    assert lists == ["Sugars"]
    assert sorted(excluded) == [["Sugars", "Hex"], ["Sugars", "HexNAc"]]

    # unticking an entry leaves it out; the last one stops the list
    lists, excluded = differences.setEntryMatched(lists, excluded, "Sugars", "Hex", True, ENTRIES)
    lists, excluded = differences.setEntryMatched(lists, excluded, "Sugars", "Hex", False, ENTRIES)
    assert differences.listState(lists, excluded, "Sugars", ENTRIES) == "some"
    lists, excluded = differences.setEntryMatched(lists, excluded, "Sugars", "dHex", False, ENTRIES)
    assert lists == [] and excluded == []


def test_entries_left_out_are_not_matched_nor_are_their_pairs(monkeypatch):
    masses = {"Gly": (57.02146, 57.05), "Ala": (71.03711, 71.08)}
    monkeypatch.setattr(differences, "getList", lambda name: dict(masses))
    monkeypatch.setattr(differences, "listPairs", lambda name: True)

    names = [entry[0] for entry in differences.entries(["AA"], excluded=[("AA", "Ala")])]
    assert names == ["Gly", "2×Gly"]


def test_lists_summary_says_how_much_of_a_list_is_matched():
    items = {"Sugars": ENTRIES, "Amino acids": ["Gly", "Ala"]}
    pairs = {"Amino acids": True}
    text = panel.listsSummary(["Sugars", "Amino acids"], [["Sugars", "Hex"]], items, pairs)
    assert text == "Sugars 2/3, Amino acids (+pairs)"
    assert panel.listsSummary([], [], items, pairs) == "none"
