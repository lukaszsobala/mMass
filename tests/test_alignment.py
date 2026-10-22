"""Tests for the aligned peak table built by the Compare Peak Lists tool.

gui/alignment.py imports neither wxPython nor gui.config, so the whole table
builder is exercised here headlessly; only mspy is needed, for real peak
objects.
"""

import mspy

from gui import alignment


def peak(mz, ai=100.0, **kwargs):
    return mspy.peak(mz=mz, ai=ai, **kwargs)


def envelopePeak(mz, area, ai=1.0):
    return mspy.peak(mz=mz, ai=ai, envelope={"area": area, "sumint": area * 2})


def columnsOf(header, rows, name):
    """Values of one named column, top to bottom."""

    index = header.index(name)
    return [row[index] for row in rows]


# ---------------------------------------------------------------------------
# Table shape
# ---------------------------------------------------------------------------


def test_header_names_every_document_even_without_peaks():
    groups = [[(0, 100.0, peak(100.0))]]

    header, rows = alignment.buildAlignmentTable(
        groups, ["a", "b"], statColumns=["count"], peakColumns=["mz"]
    )

    assert header == ["Documents in group", "a | m/z", "b | m/z"]
    assert rows == [[1, 100.0, None]]


def test_duplicate_titles_get_distinct_column_names():
    header, _rows = alignment.buildAlignmentTable(
        [[(0, 100.0, peak(100.0))]],
        ["sample", "sample", "sample"],
        statColumns=[],
        peakColumns=["mz"],
    )

    assert header == ["sample | m/z", "sample(2) | m/z", "sample(3) | m/z"]


def test_blank_title_falls_back_to_position():
    header, _rows = alignment.buildAlignmentTable(
        [[(0, 100.0, peak(100.0))]],
        ["", "  "],
        statColumns=[],
        peakColumns=["mz"],
    )

    assert header == ["document1 | m/z", "document2 | m/z"]


def test_columns_follow_canonical_order_not_request_order():
    header, _rows = alignment.buildAlignmentTable(
        [[(0, 100.0, peak(100.0))]],
        ["a"],
        statColumns=["count", "median", "mean"],
        peakColumns=["sn", "mz"],
    )

    assert header == ["Median m/z", "Mean m/z", "Documents in group", "a | m/z", "a | s/n"]


def test_unknown_columns_are_dropped():
    header, _rows = alignment.buildAlignmentTable(
        [[(0, 100.0, peak(100.0))]],
        ["a"],
        statColumns=["median", "nonsense"],
        peakColumns=["mz", "nonsense"],
    )

    assert header == ["Median m/z", "a | m/z"]


def test_empty_groups_produce_no_rows():
    _header, rows = alignment.buildAlignmentTable(
        [[], []], ["a"], statColumns=["median"], peakColumns=["mz"]
    )

    assert rows == []


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------


def test_summary_describes_the_mz_of_the_group():
    group = [
        (0, 100.0, peak(100.0)),
        (1, 100.4, peak(100.4)),
        (2, 100.2, peak(100.2)),
    ]

    header, rows = alignment.buildAlignmentTable(
        [group],
        ["a", "b", "c"],
        statColumns=["median", "mean", "min", "max", "range", "count"],
        peakColumns=[],
    )

    row = dict(zip(header, rows[0], strict=True))
    assert row["Median m/z"] == 100.2
    assert abs(row["Mean m/z"] - 100.2) < 1e-9
    assert row["Lowest m/z"] == 100.0
    assert row["Highest m/z"] == 100.4
    assert abs(row["Highest - lowest"] - 0.4) < 1e-9
    assert row["Documents in group"] == 3


def test_median_of_an_even_group_is_the_midpoint():
    group = [(0, 100.0, peak(100.0)), (1, 101.0, peak(101.0))]

    header, rows = alignment.buildAlignmentTable(
        [group], ["a", "b"], statColumns=["median"], peakColumns=[]
    )

    assert rows[0][header.index("Median m/z")] == 100.5


def test_range_in_ppm_is_relative_to_the_mean():
    group = [(0, 999.9, peak(999.9)), (1, 1000.1, peak(1000.1))]

    header, rows = alignment.buildAlignmentTable(
        [group], ["a", "b"], statColumns=["rangeppm"], peakColumns=[]
    )

    assert abs(rows[0][header.index("Highest - lowest (ppm)")] - 200.0) < 1e-6


def test_groups_are_ordered_by_mean_mz():
    groups = [
        [(0, 300.0, peak(300.0))],
        [(0, 100.0, peak(100.0))],
        [(0, 200.0, peak(200.0))],
    ]

    header, rows = alignment.buildAlignmentTable(
        [g for g in groups], ["a"], statColumns=["mean"], peakColumns=[]
    )

    assert columnsOf(header, rows, "Mean m/z") == [100.0, 200.0, 300.0]


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------


def test_most_intense_peak_of_a_document_takes_the_block():
    group = [
        (0, 100.0, peak(100.0, ai=10.0)),
        (0, 100.1, peak(100.1, ai=90.0)),
        (1, 100.05, peak(100.05, ai=50.0)),
    ]

    header, rows = alignment.buildAlignmentTable(
        group and [group],
        ["a", "b"],
        statColumns=["count", "duplicate"],
        peakColumns=["mz"],
    )

    aligned = [row for row in rows if row[header.index("Duplicate flag")] == ""]
    assert len(aligned) == 1
    assert aligned[0][header.index("a | m/z")] == 100.1
    assert aligned[0][header.index("b | m/z")] == 100.05
    assert aligned[0][header.index("Documents in group")] == 2


def test_envelope_area_outranks_ai_when_choosing_the_representative():
    group = [
        (0, 100.0, peak(100.0, ai=90.0)),
        (0, 100.1, envelopePeak(100.1, area=1000.0, ai=5.0)),
    ]

    header, rows = alignment.buildAlignmentTable(
        [group], ["a"], statColumns=["duplicate"], peakColumns=["mz"]
    )

    aligned = [row for row in rows if row[header.index("Duplicate flag")] == ""]
    assert aligned[0][header.index("a | m/z")] == 100.1


def test_duplicates_keep_their_place_in_mz_order():
    group = [
        (0, 99.9, peak(99.9, ai=10.0)),
        (0, 100.0, peak(100.0, ai=90.0)),
        (0, 100.2, peak(100.2, ai=20.0)),
    ]

    header, rows = alignment.buildAlignmentTable(
        [group], ["a"], statColumns=["duplicate"], peakColumns=["mz"]
    )

    assert columnsOf(header, rows, "a | m/z") == [99.9, 100.0, 100.2]
    assert columnsOf(header, rows, "Duplicate flag") == [
        alignment.DUPLICATE_FLAG,
        "",
        alignment.DUPLICATE_FLAG,
    ]


def test_a_duplicate_row_summarises_only_its_own_peak():
    group = [
        (0, 100.0, peak(100.0, ai=90.0)),
        (0, 100.2, peak(100.2, ai=20.0)),
        (1, 100.1, peak(100.1, ai=50.0)),
    ]

    header, rows = alignment.buildAlignmentTable(
        [group],
        ["a", "b"],
        statColumns=["count", "range", "duplicate"],
        peakColumns=["mz"],
    )

    duplicate = [
        row for row in rows if row[header.index("Duplicate flag")] == alignment.DUPLICATE_FLAG
    ][0]
    assert duplicate[header.index("Documents in group")] == 1
    assert duplicate[header.index("Highest - lowest")] == 0.0
    assert duplicate[header.index("b | m/z")] is None


def test_duplicates_can_be_left_out_entirely():
    group = [
        (0, 100.0, peak(100.0, ai=90.0)),
        (0, 100.2, peak(100.2, ai=20.0)),
    ]

    header, rows = alignment.buildAlignmentTable(
        [group],
        ["a"],
        statColumns=["duplicate"],
        peakColumns=["mz"],
        duplicates=alignment.DUPLICATES_IGNORE,
    )

    assert len(rows) == 1
    assert rows[0][header.index("a | m/z")] == 100.0


# ---------------------------------------------------------------------------
# Group ID
# ---------------------------------------------------------------------------


def test_groups_are_numbered_in_mz_order():
    groups = [
        [(0, 300.0, peak(300.0))],
        [(0, 100.0, peak(100.0))],
        [(0, 200.0, peak(200.0))],
    ]

    header, rows = alignment.buildAlignmentTable(
        groups, ["a"], statColumns=["id", "mean"], peakColumns=[]
    )

    assert columnsOf(header, rows, "Group ID") == [1, 2, 3]
    assert columnsOf(header, rows, "Mean m/z") == [100.0, 200.0, 300.0]


def test_duplicate_rows_carry_the_id_of_their_group():
    groups = [
        [(0, 100.0, peak(100.0, ai=90.0)), (0, 100.2, peak(100.2, ai=20.0))],
        [(0, 200.0, peak(200.0))],
    ]

    header, rows = alignment.buildAlignmentTable(
        groups, ["a"], statColumns=["id", "duplicate"], peakColumns=["mz"]
    )

    assert columnsOf(header, rows, "Group ID") == [1, 1, 2]
    assert columnsOf(header, rows, "Duplicate flag") == [
        "",
        alignment.DUPLICATE_FLAG,
        "",
    ]


# ---------------------------------------------------------------------------
# Duplicates added up
# ---------------------------------------------------------------------------


def test_duplicates_can_be_added_up():
    group = [
        (0, 100.0, peak(100.0, ai=90.0, base=10.0, sn=5.0)),
        (0, 100.2, peak(100.2, ai=30.0, base=10.0, sn=9.0)),
    ]

    header, rows = alignment.buildAlignmentTable(
        [group],
        ["a"],
        statColumns=[],
        peakColumns=["mz", "ai", "base", "int", "sn"],
        duplicates=alignment.DUPLICATES_SUM,
    )

    assert len(rows) == 1
    row = dict(zip(header, rows[0], strict=True))
    # additive columns are summed, the rest comes from the most intense peak
    assert row["a | a.i."] == 120.0
    assert row["a | Baseline"] == 20.0
    assert row["a | Intensity"] == 100.0
    assert row["a | m/z"] == 100.0
    assert row["a | s/n"] == 5.0


def test_adding_up_a_column_nobody_has_stays_empty():
    group = [(0, 100.0, envelopePeak(100.0, 10.0)), (0, 100.1, peak(100.1))]

    header, rows = alignment.buildAlignmentTable(
        [group],
        ["a"],
        statColumns=[],
        peakColumns=["envarea"],
        duplicates=alignment.DUPLICATES_SUM,
    )

    assert rows[0] == [10.0]


# ---------------------------------------------------------------------------
# ppm error
# ---------------------------------------------------------------------------


def test_ppm_error_is_measured_against_the_group_median():
    group = [
        (0, 1000.000, peak(1000.000)),
        (1, 1000.001, peak(1000.001)),
        (2, 1000.002, peak(1000.002)),
    ]

    header, rows = alignment.buildAlignmentTable(
        [group], ["a", "b", "c"], statColumns=[], peakColumns=["ppm"]
    )

    errors = rows[0]
    assert abs(errors[0] + 1.0) < 1e-3
    assert abs(errors[1]) < 1e-3
    assert abs(errors[2] - 1.0) < 1e-3


def test_a_duplicate_shows_its_distance_from_the_group_not_from_itself():
    group = [
        (0, 1000.000, peak(1000.000, ai=90.0)),
        (0, 1000.010, peak(1000.010, ai=10.0)),
        (1, 1000.000, peak(1000.000)),
    ]

    header, rows = alignment.buildAlignmentTable(
        [group],
        ["a", "b"],
        statColumns=["duplicate"],
        peakColumns=["ppm"],
    )

    duplicate = [row for row in rows if row[0] == alignment.DUPLICATE_FLAG][0]
    assert abs(duplicate[1] - 10.0) < 1e-6


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------


def test_columns_of_one_kind_can_sit_next_to_each_other():
    group = [
        (0, 100.0, peak(100.0, ai=10.0)),
        (1, 100.1, peak(100.1, ai=20.0)),
    ]

    header, rows = alignment.buildAlignmentTable(
        [group],
        ["a", "b"],
        statColumns=[],
        peakColumns=["mz", "ai"],
        layout=alignment.LAYOUT_COLUMN,
    )

    # same names as the per-document layout, only in another order
    assert header == ["a | m/z", "b | m/z", "a | a.i.", "b | a.i."]
    assert rows == [[100.0, 100.1, 10.0, 20.0]]


def test_both_wide_layouts_hold_the_same_values():
    group = [
        (0, 100.0, peak(100.0, ai=10.0)),
        (2, 100.1, peak(100.1, ai=20.0)),
    ]
    kwargs = dict(statColumns=["id"], peakColumns=["mz", "ai"])

    _h1, byDocument = alignment.buildAlignmentTable([group], ["a", "b", "c"], **kwargs)
    _h2, byColumn = alignment.buildAlignmentTable(
        [group], ["a", "b", "c"], layout=alignment.LAYOUT_COLUMN, **kwargs
    )

    assert byDocument == [[1, 100.0, 10.0, None, None, 100.1, 20.0]]
    assert byColumn == [[1, 100.0, None, 100.1, 10.0, None, 20.0]]


def test_long_layout_has_a_row_per_peak():
    groups = [
        [(0, 100.0, peak(100.0, ai=10.0)), (1, 100.1, peak(100.1, ai=20.0))],
        [(1, 200.0, peak(200.0, ai=30.0))],
    ]

    header, rows = alignment.buildAlignmentTable(
        groups,
        ["a", "b"],
        statColumns=["count"],
        peakColumns=["mz", "ai"],
        layout=alignment.LAYOUT_LONG,
    )

    assert header == ["Group ID", "Document", "Documents in group", "m/z", "a.i."]
    assert rows == [
        [1, "a", 2, 100.0, 10.0],
        [1, "b", 2, 100.1, 20.0],
        [2, "b", 1, 200.0, 30.0],
    ]


def test_long_layout_always_says_which_group_a_row_is_in():
    header, rows = alignment.buildAlignmentTable(
        [[(0, 100.0, peak(100.0))]],
        ["a"],
        statColumns=[],
        peakColumns=["mz"],
        layout=alignment.LAYOUT_LONG,
    )

    assert header == ["Group ID", "Document", "m/z"]
    assert rows == [[1, "a", 100.0]]


def test_long_layout_flags_duplicates_and_keeps_the_group_summary():
    group = [
        (0, 100.0, peak(100.0, ai=90.0)),
        (0, 100.2, peak(100.2, ai=20.0)),
        (1, 100.1, peak(100.1, ai=50.0)),
    ]

    header, rows = alignment.buildAlignmentTable(
        [group],
        ["a", "b"],
        statColumns=["count", "duplicate"],
        peakColumns=["mz"],
        layout=alignment.LAYOUT_LONG,
    )

    assert header == ["Group ID", "Document", "Documents in group", "Duplicate flag", "m/z"]
    assert rows == [
        [1, "a", 2, "", 100.0],
        [1, "a", 2, alignment.DUPLICATE_FLAG, 100.2],
        [1, "b", 2, "", 100.1],
    ]


def test_long_layout_without_duplicate_rows():
    group = [
        (0, 100.0, peak(100.0, ai=90.0)),
        (0, 100.2, peak(100.2, ai=20.0)),
    ]

    _header, rows = alignment.buildAlignmentTable(
        [group],
        ["a"],
        statColumns=[],
        peakColumns=["mz"],
        duplicates=alignment.DUPLICATES_IGNORE,
        layout=alignment.LAYOUT_LONG,
    )

    assert rows == [[1, "a", 100.0]]


# ---------------------------------------------------------------------------
# Two-row header
# ---------------------------------------------------------------------------


def test_two_row_header_puts_the_document_above_its_columns():
    header, rows = alignment.buildAlignmentTable(
        [[(0, 100.0, peak(100.0)), (1, 100.1, peak(100.1))]],
        ["a", "b"],
        statColumns=["id"],
        peakColumns=["mz", "ai"],
        twoRowHeader=True,
    )

    assert header == [
        ["", "a", "a", "b", "b"],
        ["Group ID", "m/z", "a.i.", "m/z", "a.i."],
    ]
    assert len(rows[0]) == 5


def test_two_row_header_names_the_document_above_when_blocked_by_column_too():
    header, _rows = alignment.buildAlignmentTable(
        [[(0, 100.0, peak(100.0))]],
        ["a", "b"],
        statColumns=[],
        peakColumns=["mz", "ai"],
        layout=alignment.LAYOUT_COLUMN,
        twoRowHeader=True,
    )

    assert header == [
        ["a", "b", "a", "b"],
        ["m/z", "m/z", "a.i.", "a.i."],
    ]


def test_long_layout_keeps_one_header_row():
    header, _rows = alignment.buildAlignmentTable(
        [[(0, 100.0, peak(100.0))]],
        ["a"],
        statColumns=[],
        peakColumns=["mz"],
        layout=alignment.LAYOUT_LONG,
        twoRowHeader=True,
    )

    assert header == ["Group ID", "Document", "m/z"]


def test_two_row_header_is_written_as_two_lines():
    header, rows = alignment.buildAlignmentTable(
        [[(0, 100.0, peak(100.0))]],
        ["a"],
        statColumns=["id"],
        peakColumns=["mz"],
        twoRowHeader=True,
    )

    lines = alignment.formatTable(header, rows).splitlines()

    assert lines == ["\ta", "Group ID\tm/z", "1\t100"]


# ---------------------------------------------------------------------------
# Cell values
# ---------------------------------------------------------------------------


def test_peak_columns_read_from_the_peak():
    item = mspy.peak(mz=500.0, ai=120.0, base=20.0, sn=9.0, charge=2, fwhm=0.05)

    header, rows = alignment.buildAlignmentTable(
        [[(0, 500.0, item)]],
        ["a"],
        statColumns=[],
        peakColumns=["mz", "ai", "base", "int", "sn", "z", "fwhm", "resol", "mass"],
    )

    row = dict(zip(header, rows[0], strict=True))
    assert row["a | m/z"] == 500.0
    assert row["a | a.i."] == 120.0
    assert row["a | Baseline"] == 20.0
    assert row["a | Intensity"] == 100.0
    assert row["a | s/n"] == 9.0
    assert row["a | Charge"] == 2
    assert row["a | FWHM"] == 0.05
    assert abs(row["a | Resolution"] - 10000.0) < 1e-6
    assert row["a | Mass"] is not None


def test_envelope_columns_come_from_the_envelope_attribute():
    header, rows = alignment.buildAlignmentTable(
        [[(0, 100.0, envelopePeak(100.0, area=250.0))]],
        ["a"],
        statColumns=[],
        peakColumns=["envarea", "envint"],
    )

    row = dict(zip(header, rows[0], strict=True))
    assert row["a | Envelope area"] == 250.0
    assert row["a | Envelope int. sum"] == 500.0


def test_columns_a_peak_cannot_supply_stay_empty():
    header, rows = alignment.buildAlignmentTable(
        [[(0, 100.0, peak(100.0))]],
        ["a"],
        statColumns=[],
        peakColumns=["sn", "fwhm", "resol", "envarea", "envint", "group", "label"],
    )

    assert all(value is None for value in rows[0])


def test_notation_objects_supply_what_they_have():
    class notation:
        def __init__(self):
            self.label = "y5"
            self.mz = 700.5
            self.ai = 30.0
            self.base = 0.0
            self.charge = 1
            self.theoretical = 700.4

    header, rows = alignment.buildAlignmentTable(
        [[(0, 700.4, notation())]],
        ["a"],
        statColumns=[],
        peakColumns=["mz", "label", "theoretical", "sn", "int"],
    )

    row = dict(zip(header, rows[0], strict=True))
    # the alignment ran on the theoretical m/z, so that is what the m/z column
    # holds -- otherwise it would disagree with the summary columns
    assert row["a | m/z"] == 700.4
    assert row["a | Label"] == "y5"
    assert row["a | Theoretical m/z"] == 700.4
    assert row["a | Intensity"] == 30.0
    assert row["a | s/n"] is None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def test_missing_values_become_empty_cells():
    text = alignment.formatTable(["a", "b"], [[1.5, None]])

    assert text == "a\tb\n1.5\t\n"


def test_text_cells_cannot_break_the_table():
    text = alignment.formatTable(["a"], [["one\ttwo\nthree"]])

    assert text.splitlines()[1] == "one two three"


def test_floats_are_written_at_full_measured_precision():
    text = alignment.formatTable(["a"], [[1000.12345678]])

    assert text.splitlines()[1] == "1000.12345678"


def test_subtraction_noise_does_not_reach_the_table():
    # 100.1 - 100.0 is 0.09999999999999432 in binary floating point, and a
    # column headed "range" showing that reads as a bug
    _header, rows = alignment.buildAlignmentTable(
        [[(0, 100.0, peak(100.0)), (1, 100.1, peak(100.1))]],
        ["a", "b"],
        statColumns=["range"],
        peakColumns=[],
    )

    assert alignment.formatTable(["range"], rows).splitlines()[1] == "0.1"


def test_integers_are_not_written_as_floats():
    text = alignment.formatTable(["count"], [[3]])

    assert text.splitlines()[1] == "3"


def test_separator_is_used_throughout():
    text = alignment.formatTable(["a", "b"], [[1, 2]], separator=",")

    assert text == "a,b\n1,2\n"
