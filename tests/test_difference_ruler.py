"""Difference ruler: difference lists, matching, the library, and saved rulers.

The lists and matching live in gui.differences, the user's lists in gui.libs,
and the rulers themselves on gui.doc documents. All of those import wx, so the
module skips where the GUI stack is unavailable. The drawing checks also need
a wx.App, which needs a display, and skip without one.

gui.libs loads the user's monomers, enzymes and modifications into mspy when it
is first imported, so it is only imported inside tests, with mspy's libraries
put back afterwards -- see test_library_io.
"""

import json
import os

import pytest

import mspy

differences = pytest.importorskip("gui.differences", reason="GUI stack (wx) not available")
gdoc = pytest.importorskip("gui.doc", reason="GUI stack (wx) not available")
processing = pytest.importorskip("gui.processing", reason="GUI stack (wx) not available")


HEX = 162.052824
PHOSPHO = 79.966331


@pytest.fixture(autouse=True)
def pristine_libraries():
    """Put mspy's libraries back after a test that may have imported gui.libs."""

    saved = {
        "monomers": dict(mspy.monomers),
        "enzymes": dict(mspy.enzymes),
        "modifications": dict(mspy.modifications),
    }
    try:
        yield
    finally:
        for name, entries in saved.items():
            library = getattr(mspy, name)
            library.clear()
            library.update(entries)


@pytest.fixture
def libs():
    return pytest.importorskip("gui.libs", reason="GUI stack (wx) not available")


@pytest.fixture
def user_lists(libs):
    """libs.differences holding a known list, restored afterwards."""

    saved = dict(libs.differences)
    libs.differences.clear()
    libs.differences["Test Mods"] = [
        ("Phospho", PHOSPHO, 79.979917),
        ("Oxidation", 15.994915, 15.999405),
    ]
    try:
        yield libs.differences
    finally:
        libs.differences.clear()
        libs.differences.update(saved)


# MATCHING
# --------


def test_builtin_lists_hold_residue_masses():
    lists = differences.builtinLists()

    assert lists[differences.AMINOACIDS]["G"][0] == pytest.approx(57.02146, abs=1e-4)
    assert lists[differences.DIPEPTIDES]["GG"][0] == pytest.approx(114.04293, abs=1e-4)
    assert lists[differences.SUGARS]["Hex"][0] == pytest.approx(HEX, abs=1e-5)
    # average masses are kept alongside the monoisotopic ones
    assert lists[differences.SUGARS]["Hex"][1] > lists[differences.SUGARS]["Hex"][0]


def test_match_names_a_difference_and_sorts_by_error():
    candidates = differences.entries([differences.SUGARS, differences.AMINOACIDS])

    matches = differences.match(HEX + 0.002, candidates, tolerance=0.01)

    assert [m[0] for m in matches] == ["Hex"]
    assert matches[0][1] == pytest.approx(0.002, abs=1e-6)
    assert matches[0][2] == differences.SUGARS

    # K and Q are 0.036 apart: a loose tolerance finds both, closest first
    lysine = differences.builtinLists()[differences.AMINOACIDS]["K"][0]
    matches = differences.match(lysine, candidates, tolerance=0.1)
    assert [m[0] for m in matches][:2] == ["K", "Q"]


def test_match_outside_tolerance_finds_nothing():
    candidates = differences.entries([differences.SUGARS])
    assert differences.match(HEX + 0.05, candidates, tolerance=0.01) == []


def test_match_at_charge_scales_difference_and_tolerance():
    candidates = differences.entries([differences.SUGARS])

    # a Hex step in a 2+ series is half a Hex apart in m/z
    matches = differences.match(HEX / 2 + 0.004, candidates, tolerance=0.005, charge=2)
    assert [m[0] for m in matches] == ["Hex"]

    # the same step read as 1+ matches nothing
    assert differences.match(HEX / 2, candidates, tolerance=0.005) == []

    # negative ions carry a negative charge; the series is the same
    assert differences.match(HEX / 2, candidates, tolerance=0.005, charge=-2)


def test_match_uses_average_masses_when_asked(user_lists):
    candidates = differences.entries(["Test Mods"])

    assert differences.match(79.980, candidates, tolerance=0.002, massType=1)
    assert not differences.match(79.980, candidates, tolerance=0.002, massType=0)


def test_user_lists_follow_builtin_ones(user_lists):
    names = differences.availableLists()

    assert names[: len(differences.BUILTIN)] == list(differences.BUILTIN)
    assert "Test Mods" in names
    assert differences.getList("gone") == {}


def test_ruler_text():
    assert differences.rulerText("", 162.05282, digits=3) == "162.053"
    assert differences.rulerText("Hex", 162.05282, digits=3) == "Hex"
    assert differences.rulerText("Hex", 162.05282, showDiff=True, digits=2) == "Hex  162.05"
    assert differences.rulerText("Hex", 81.02641, charge=2, digits=2) == "Hex (2+)"
    assert differences.rulerText("Hex", 81.02641, charge=-2, digits=2) == "Hex (2-)"


def test_match_names_keeps_the_closest_few():
    matches = [("A", 0.001, "x"), ("B", 0.002, "x"), ("A", 0.003, "y"), ("C", 0.004, "x"), ("D", 0.005, "x")]
    assert differences.matchNames(matches) == "A / B / C / ..."
    assert differences.matchNames(matches, maxNames=5) == "A / B / C / D"
    assert differences.matchNames([]) == ""


def test_ruler_charge():
    assert differences.rulerCharge(2, 2) == 2
    assert differences.rulerCharge(None, 3) == 3
    assert differences.rulerCharge(-2, None) == -2
    assert differences.rulerCharge(2, 3) == 1
    assert differences.rulerCharge(None, None) == 1


# LIBRARY
# -------


def test_differences_library_round_trip(tmp_path, libs, user_lists):
    path = str(tmp_path / "differences.json")

    assert libs.saveDifferences(path)
    saved = dict(libs.differences)
    libs.differences.clear()
    libs.loadDifferences(path)

    assert libs.differences == saved


def test_differences_library_reads_short_and_skips_bad_entries(libs):
    parsed = libs.parseDifferences(
        {
            "Mixed": [
                ["Mono only", 10.5],
                ["Both", 1, 2],
                ["Bad mass", "x"],
                ["Too short"],
                "not a list",
            ],
            "Not a list": {"a": 1},
        }
    )

    assert parsed == {"Mixed": [("Mono only", 10.5, 10.5), ("Both", 1.0, 2.0)]}


def test_bundled_default_library_is_valid(libs):
    path = os.path.join(os.path.dirname(libs.__file__), "configs", "differences.json")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    parsed = libs.parseDifferences(data["differences"])
    masses = {name: (mono, avg) for items in parsed.values() for name, mono, avg in items}

    assert masses["Phosphorylation"][0] == pytest.approx(PHOSPHO, abs=1e-5)
    assert masses["Na-H"][0] == pytest.approx(21.98194, abs=1e-5)
    # no user list may shadow a built-in one
    assert not set(parsed) & set(differences.BUILTIN)


# RULERS ON DOCUMENTS
# -------------------


def test_ruler_keeps_lower_mz_first():
    ruler = gdoc.ruler(1162.5, 50.0, 1000.4, 80.0, label="Hex")

    assert (ruler.mz1, ruler.ai1, ruler.mz2, ruler.ai2) == (1000.4, 80.0, 1162.5, 50.0)
    assert ruler.diff == pytest.approx(162.1)


def test_rulers_survive_msd_round_trip(tmp_path):
    document = gdoc.document()
    document.spectrum.setpeaklist(mspy.peaklist([mspy.peak(mz=1000.0, ai=10.0)]))
    document.rulers.append(gdoc.ruler(1000.0, 10.0, 1162.052824, 5.0, label="Hex <1>", charge=1))
    document.rulers.append(gdoc.ruler(500.0, 1.0, 540.5, 2.0, label="", charge=2, scanID=7))

    path = str(tmp_path / "rulers.msd")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(document.msd())

    reloaded = gdoc.parseMSD(path).getDocument().rulers

    assert len(reloaded) == 2
    first, second = reloaded
    assert (first.mz1, first.mz2, first.label, first.charge, first.scanID) == (
        pytest.approx(1000.0),
        pytest.approx(1162.052824),
        "Hex <1>",
        1,
        None,
    )
    assert (first.ai1, first.ai2) == (pytest.approx(10.0), pytest.approx(5.0))
    assert (second.label, second.charge, second.scanID) == ("", 2, 7)


def test_document_without_rulers_writes_no_element():
    assert "<rulers>" not in gdoc.document().msd()


def test_report_lists_rulers():
    document = gdoc.document()
    document.rulers.append(gdoc.ruler(1000.0, 1.0, 1162.052824, 1.0, label="Hex", charge=1))

    html = document.report()

    assert "Difference Rulers" in html
    assert "<td>Hex</td>" in html
    assert "162.05" in html


def test_rulers_undo_and_redo():
    document = gdoc.document()
    first = gdoc.ruler(100.0, 1.0, 200.0, 1.0)
    document.rulers.append(first)

    document.backup(("rulers",))
    document.rulers.append(gdoc.ruler(300.0, 1.0, 400.0, 1.0))

    assert document.restore() == ("rulers",)
    assert [r.mz1 for r in document.rulers] == [100.0]

    assert document.forward() == ("rulers",)
    assert [r.mz1 for r in document.rulers] == [100.0, 300.0]


def test_crop_drops_rulers_that_leave_the_range():
    document = gdoc.document()
    document.rulers[:] = [
        gdoc.ruler(100.0, 1.0, 200.0, 1.0),
        gdoc.ruler(450.0, 1.0, 520.0, 1.0),
        gdoc.ruler(600.0, 1.0, 700.0, 1.0),
    ]

    processing.cropNotations(document, 90.0, 500.0)

    assert [r.mz1 for r in document.rulers] == [100.0]


# DRAWING
# -------


@pytest.fixture
def wx_app():
    """A wx.App, when there is a display to make one on."""

    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) and os.name != "nt":
        pytest.skip("no display for a wx.App")
    wx = pytest.importorskip("wx")
    app = wx.App.Get() or wx.App(False)
    return app


def test_ruler_ends_follow_the_current_peak_heights(wx_app):
    from mspy import plot_objects

    scan = mspy.scan(
        profile=[[999.0, 0.0], [1000.0, 40.0], [1001.0, 0.0], [1161.0, 0.0], [1162.0, 30.0], [1163.0, 0.0]],
        peaklist=[mspy.peak(mz=1000.0, ai=40.0)],
    )
    spectrum = plot_objects.spectrum(scan)

    # a peak at the end: its intensity now, not the stored one
    assert spectrum._rulerHeight(1000.0, 99.0) == pytest.approx(40.0)
    # no peak there: the profile
    assert spectrum._rulerHeight(1162.0, 99.0) == pytest.approx(30.0)
    # neither: what was stored
    assert spectrum._rulerHeight(2000.0, 99.0) == pytest.approx(99.0)


def test_overlapping_rulers_are_stacked(wx_app):
    import wx

    from mspy import plot_objects

    bitmap = wx.Bitmap(400, 300)
    dc = wx.MemoryDC(bitmap)
    font = wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
    placed = []

    for x1, x2 in ((50, 200), (100, 250), (300, 350)):
        plot_objects.drawRuler(
            dc, x1, 200, x2, 200, "Hex", colour=(230, 120, 0), font=font,
            bgrColour=(255, 255, 255), placed=placed,
        )
    dc.SelectObject(wx.NullBitmap)

    first, second, third = placed
    # the second overlaps the first, so it is lifted clear of it
    assert second[3] <= first[1]
    # the third is clear of both and stays down
    assert third[1] == first[1]
