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

    assert header == ["count", "a_mz", "b_mz"]
    assert rows == [[1, 100.0, None]]


def test_duplicate_titles_get_distinct_column_names():
    header, _rows = alignment.buildAlignmentTable(
        [[(0, 100.0, peak(100.0))]],
        ["sample", "sample", "sample"],
        statColumns=[],
        peakColumns=["mz"],
    )

    assert header == ["sample_mz", "sample(2)_mz", "sample(3)_mz"]


def test_blank_title_falls_back_to_position():
    header, _rows = alignment.buildAlignmentTable(
        [[(0, 100.0, peak(100.0))]],
        ["", "  "],
        statColumns=[],
        peakColumns=["mz"],
    )

    assert header == ["document1_mz", "document2_mz"]


def test_columns_follow_canonical_order_not_request_order():
    header, _rows = alignment.buildAlignmentTable(
        [[(0, 100.0, peak(100.0))]],
        ["a"],
        statColumns=["count", "median", "mean"],
        peakColumns=["sn", "mz"],
    )

    assert header == ["median", "mean", "count", "a_mz", "a_sn"]


def test_unknown_columns_are_dropped():
    header, _rows = alignment.buildAlignmentTable(
        [[(0, 100.0, peak(100.0))]],
        ["a"],
        statColumns=["median", "nonsense"],
        peakColumns=["mz", "nonsense"],
    )

    assert header == ["median", "a_mz"]


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
    assert row["median"] == 100.2
    assert abs(row["mean"] - 100.2) < 1e-9
    assert row["min"] == 100.0
    assert row["max"] == 100.4
    assert abs(row["range"] - 0.4) < 1e-9
    assert row["count"] == 3


def test_median_of_an_even_group_is_the_midpoint():
    group = [(0, 100.0, peak(100.0)), (1, 101.0, peak(101.0))]

    header, rows = alignment.buildAlignmentTable(
        [group], ["a", "b"], statColumns=["median"], peakColumns=[]
    )

    assert rows[0][header.index("median")] == 100.5


def test_range_in_ppm_is_relative_to_the_mean():
    group = [(0, 999.9, peak(999.9)), (1, 1000.1, peak(1000.1))]

    header, rows = alignment.buildAlignmentTable(
        [group], ["a", "b"], statColumns=["rangeppm"], peakColumns=[]
    )

    assert abs(rows[0][header.index("rangeppm")] - 200.0) < 1e-6


def test_groups_are_ordered_by_mean_mz():
    groups = [
        [(0, 300.0, peak(300.0))],
        [(0, 100.0, peak(100.0))],
        [(0, 200.0, peak(200.0))],
    ]

    header, rows = alignment.buildAlignmentTable(
        [g for g in groups], ["a"], statColumns=["mean"], peakColumns=[]
    )

    assert columnsOf(header, rows, "mean") == [100.0, 200.0, 300.0]


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

    aligned = [row for row in rows if row[header.index("duplicate")] == ""]
    assert len(aligned) == 1
    assert aligned[0][header.index("a_mz")] == 100.1
    assert aligned[0][header.index("b_mz")] == 100.05
    assert aligned[0][header.index("count")] == 2


def test_envelope_area_outranks_ai_when_choosing_the_representative():
    group = [
        (0, 100.0, peak(100.0, ai=90.0)),
        (0, 100.1, envelopePeak(100.1, area=1000.0, ai=5.0)),
    ]

    header, rows = alignment.buildAlignmentTable(
        [group], ["a"], statColumns=["duplicate"], peakColumns=["mz"]
    )

    aligned = [row for row in rows if row[header.index("duplicate")] == ""]
    assert aligned[0][header.index("a_mz")] == 100.1


def test_duplicates_keep_their_place_in_mz_order():
    group = [
        (0, 99.9, peak(99.9, ai=10.0)),
        (0, 100.0, peak(100.0, ai=90.0)),
        (0, 100.2, peak(100.2, ai=20.0)),
    ]

    header, rows = alignment.buildAlignmentTable(
        [group], ["a"], statColumns=["duplicate"], peakColumns=["mz"]
    )

    assert columnsOf(header, rows, "a_mz") == [99.9, 100.0, 100.2]
    assert columnsOf(header, rows, "duplicate") == [
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
        row for row in rows if row[header.index("duplicate")] == alignment.DUPLICATE_FLAG
    ][0]
    assert duplicate[header.index("count")] == 1
    assert duplicate[header.index("range")] == 0.0
    assert duplicate[header.index("b_mz")] is None


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
    assert rows[0][header.index("a_mz")] == 100.0


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
    assert row["a_mz"] == 500.0
    assert row["a_ai"] == 120.0
    assert row["a_base"] == 20.0
    assert row["a_int"] == 100.0
    assert row["a_sn"] == 9.0
    assert row["a_z"] == 2
    assert row["a_fwhm"] == 0.05
    assert abs(row["a_resol"] - 10000.0) < 1e-6
    assert row["a_mass"] is not None


def test_envelope_columns_come_from_the_envelope_attribute():
    header, rows = alignment.buildAlignmentTable(
        [[(0, 100.0, envelopePeak(100.0, area=250.0))]],
        ["a"],
        statColumns=[],
        peakColumns=["envarea", "envint"],
    )

    row = dict(zip(header, rows[0], strict=True))
    assert row["a_envarea"] == 250.0
    assert row["a_envint"] == 500.0


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
    assert row["a_mz"] == 700.4
    assert row["a_label"] == "y5"
    assert row["a_theoretical"] == 700.4
    assert row["a_int"] == 30.0
    assert row["a_sn"] is None


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
