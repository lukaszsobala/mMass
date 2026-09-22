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
