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

import numpy
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


def test_ppm_tolerance_applies_at_each_peak():
    candidates = differences.entries([differences.SUGARS])
    peaks = (1000.0, 1000.0 + HEX)

    # each peak may be 10 ppm off at its own m/z: 0.0100 + 0.0116 = 0.0216
    assert differences.match(HEX + 0.021, candidates, 10, units="ppm", mzs=peaks)
    assert not differences.match(HEX + 0.022, candidates, 10, units="ppm", mzs=peaks)
    # 10 ppm of the higher peak alone (0.0116) would have missed this one
    assert differences.match(HEX + 0.015, candidates, 10, units="ppm", mzs=peaks)
    # the same ppm are tighter lower down the m/z scale
    assert not differences.match(HEX + 0.015, candidates, 10, units="ppm", mzs=(400.0, 400.0 + HEX))

    # each match carries the theoretical mass it was matched against
    name, error, listName, theoretical = differences.match(
        HEX + 0.015, candidates, 10, units="ppm", mzs=peaks
    )[0]
    assert (name, listName) == ("Hex", differences.SUGARS)
    assert theoretical == pytest.approx(HEX, abs=1e-5)
    assert error == pytest.approx(0.015, abs=1e-5)


def test_ppm_tolerance_scales_with_charge():
    candidates = differences.entries([differences.SUGARS])
    peaks = (1000.0, 1000.0 + HEX / 2)  # 5 ppm: 0.0050 + 0.0054 = 0.0104 m/z

    # at 2+ the m/z step is half the mass step, and so is the m/z tolerance
    assert differences.match(HEX / 2 + 0.010, candidates, 5, charge=2, units="ppm", mzs=peaks)
    assert not differences.match(HEX / 2 + 0.011, candidates, 5, charge=2, units="ppm", mzs=peaks)


def test_da_tolerance_ignores_the_peaks():
    candidates = differences.entries([differences.SUGARS])
    assert differences.match(HEX + 0.05, candidates, 0.06, mzs=(1.0, 2.0))
    assert differences.toleranceMz(0.06, "Da", (1000.0, 1162.0)) == 0.06


def test_error_text():
    assert differences.errorText(0.0012, digits=4) == "+0.0012"
    assert differences.errorText(-0.0012, digits=3) == "-0.001"
    # ppm on the tolerance's footing: of both peaks' m/z, per m/z unit
    assert differences.errorText(0.002, units="ppm", mzs=(400.0, 600.0)) == "+2.0 ppm"
    assert differences.errorText(0.004, charge=2, units="ppm", mzs=(400.0, 600.0)) == "+2.0 ppm"


def test_ppm_error_within_tolerance_means_matched():
    candidates = differences.entries([differences.SUGARS])
    peaks = (1000.0, 1000.0 + HEX)
    ((name, error, _list, _theoretical),) = differences.match(
        HEX + 0.02, candidates, 10, units="ppm", mzs=peaks
    )
    shown = float(differences.errorText(error, units="ppm", mzs=peaks).split()[0])
    assert abs(shown) <= 10


def test_ruler_text_unmatched_shows_the_difference():
    assert differences.rulerText("", 162.05282, digits=3) == "162.053"
    assert differences.rulerText("", 162.05282, options={"labelDiff": 0}, digits=3) == "162.053"


def test_ruler_text_follows_the_label_options():
    def text(**options):
        return differences.rulerText(
            "K / Q", (128.094963 + 0.0012) / 2, charge=2, theoretical=128.094963,
            mzs=(736.0, 800.0), options=options, digits=4,
        )

    assert text() == "K / Q (2+)  64.0481"
    assert text(labelDiff=0) == "K / Q (2+)"
    assert text(labelAllNames=0) == "K (2+)  64.0481"
    assert text(labelCharge=0, labelDiff=0) == "K / Q"
    assert text(labelDiff=0, labelError=1) == "K / Q (2+)  +0.0012"
    assert text(labelName=0, labelError=1) == "64.0481  +0.0012"
    # nothing ticked: still the names, never a blank ruler
    assert text(labelName=0, labelDiff=0) == "K / Q"
    # error in ppm of the peak m/z
    assert differences.rulerText(
        "Hex", HEX + 0.002, theoretical=HEX, mzs=(400.0, 600.0),
        options={"labelDiff": 0, "labelError": 1}, units="ppm",
    ) == "Hex  +2.0 ppm"
    # negative ions
    assert differences.rulerText("Hex", HEX / 2, charge=-2, options={"labelDiff": 0}) == "Hex (2-)"


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
    document.rulers.append(
        gdoc.ruler(1000.0, 10.0, 1162.052824, 5.0, label="Hex <1>", charge=1, theoretical=HEX)
    )
    document.rulers.append(
        gdoc.ruler(500.0, 1.0, 540.5, 2.0, label="", charge=2, scanID=7, height=12.5)
    )
    document.rulers.append(
        gdoc.ruler(700.0, 1.0, 828.095, 1.0, label="K", picked=True, note='loss of "K" & <more>')
    )

    path = str(tmp_path / "rulers.msd")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(document.msd())

    reloaded = gdoc.parseMSD(path).getDocument().rulers

    assert len(reloaded) == 3
    first, second, third = reloaded
    assert (first.mz1, first.mz2, first.label, first.charge, first.scanID) == (
        pytest.approx(1000.0),
        pytest.approx(1162.052824),
        "Hex <1>",
        1,
        None,
    )
    assert (first.ai1, first.ai2) == (pytest.approx(10.0), pytest.approx(5.0))
    assert first.theoretical == pytest.approx(HEX)
    assert (second.label, second.charge, second.scanID, second.theoretical) == ("", 2, 7, None)
    # a bar put at a height by hand stays there; the others are placed as drawn
    assert first.height is None
    assert second.height == pytest.approx(12.5)
    # the user's own text and the match they picked
    assert (first.note, first.picked) == (None, False)
    assert (third.label, third.picked, third.note) == ("K", True, 'loss of "K" & <more>')


def test_document_without_rulers_writes_no_element():
    assert "<rulers>" not in gdoc.document().msd()


def test_report_lists_rulers():
    document = gdoc.document()
    document.rulers.append(
        gdoc.ruler(1000.0, 1.0, 1162.055824, 1.0, label="Hex", charge=1, theoretical=HEX)
    )

    html = document.report()

    assert "Difference Labels" in html
    assert "<td>Hex</td>" in html
    assert "162.05" in html
    assert "0.0030" in html  # observed minus theoretical


def test_report_shows_notes():
    document = gdoc.document()
    document.rulers.append(gdoc.ruler(1000.0, 1.0, 1162.0, 1.0, label="Hex", note="core <Fuc>"))

    assert "<td>core &lt;Fuc&gt;</td>" in document.report()


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
    assert spectrum.rulerEndIntensity(1000.0, 99.0) == pytest.approx(40.0)
    # no peak there: where it was put, not the profile
    assert spectrum.rulerEndIntensity(1162.0, 99.0) == pytest.approx(99.0)
    assert spectrum.rulerEndIntensity(2000.0, 99.0) == pytest.approx(99.0)


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


def test_drawn_rulers_can_be_found_and_hidden(wx_app):
    import wx

    from mspy import plot_objects

    scan = mspy.scan(
        peaklist=[mspy.peak(mz=1000.0, ai=40.0), mspy.peak(mz=1162.0, ai=30.0)],
    )
    spectrum = plot_objects.spectrum(scan)
    # 1 px per m/z unit from x = -900, and 5 px per intensity unit upwards
    spectrum.currentTransform = (1.0, -5.0, -900.0, 280.0)
    spectrum.peaklistPoints = numpy.array([[1000.0, 40.0], [1162.0, 30.0]])
    spectrum.setProperties(rulers=[(1000.0, 40.0, 1162.0, 30.0, "Hex", 7)])

    def draw():
        bitmap = wx.Bitmap(400, 300)
        dc = wx.MemoryDC(bitmap)
        spectrum.drawOverlays(dc, {"drawings": 1.0, "fonts": 1.0})
        dc.SelectObject(wx.NullBitmap)

    draw()
    (key, (x1, y1, x2, y2, yBar, box)), = spectrum.rulerGeometry
    assert key == 7
    assert (x1, x2) == (100.0, 262.0)

    # the ends of the bar pick that end up, the rest of it and the text the
    # ruler (the leads are too short here to tell apart from the label, see
    # test_labels_meeting_at_a_peak_are_picked_up_by_their_own_bar)
    assert spectrum.rulerAt(x1 + 3, yBar) == (7, 1)
    assert spectrum.rulerAt(x2 + 2, yBar + 1) == (7, 2)
    assert spectrum.rulerAt((x1 + x2) / 2, yBar) == (7, 0)
    assert spectrum.rulerAt((x1 + x2) / 2, yBar + 60) is None

    # a ruler being edited is left out, and cannot be picked up
    spectrum.setProperties(hiddenRuler=7)
    draw()
    assert spectrum.rulerGeometry == []
    assert spectrum.rulerAt(x1 + 3, yBar) is None

    # neither can hidden rulers
    spectrum.setProperties(hiddenRuler=None, showRulers=False)
    draw()
    assert spectrum.rulerAt(x1 + 3, yBar) is None


def test_ruler_put_at_a_height_stays_there_and_others_stack_clear(wx_app):
    import wx

    from mspy import plot_objects

    scan = mspy.scan(
        peaklist=[mspy.peak(mz=1000.0, ai=40.0), mspy.peak(mz=1162.0, ai=30.0)],
    )
    spectrum = plot_objects.spectrum(scan)
    spectrum.currentTransform = (1.0, -5.0, -900.0, 280.0)
    spectrum.peaklistPoints = numpy.array([[1000.0, 40.0], [1162.0, 30.0]])
    # the automatic one comes first by m/z, the one put at intensity 30
    # (screen y 130) sits exactly where it would go
    spectrum.setProperties(
        rulers=[
            (1000.0, 40.0, 1162.0, 30.0, "Hex", 0, None),
            (1010.0, 40.0, 1150.0, 30.0, "Hex", 1, 26.0),
        ]
    )

    bitmap = wx.Bitmap(400, 300)
    dc = wx.MemoryDC(bitmap)
    spectrum.drawOverlays(dc, {"drawings": 1.0, "fonts": 1.0})
    dc.SelectObject(wx.NullBitmap)

    geometry = dict(spectrum.rulerGeometry)
    assert geometry[1][4] == pytest.approx(26.0 * -5.0 + 280.0)
    # the automatic one is lifted clear of it
    assert geometry[0][5][3] <= geometry[1][5][1]


# SERIES
# ------

LADDER = [("Hex", HEX, HEX, "Sugars")]


def test_series_follows_the_ladder_through_its_peaks():
    # a Hex ladder 1000 -> 1162 -> 1324 -> 1486, with a weak peak at 1144
    # (1162 - H2O) that nothing matches from here, and one at 1081 halfway
    mzs = [1000.0, 1081.0, 1144.0, 1000.0 + HEX, 1000.0 + 2 * HEX, 1000.0 + 3 * HEX]
    ais = [50.0, 1.0, 2.0, 40.0, 30.0, 20.0]

    path = differences.findSeries(mzs, ais, 0, 5, LADDER, 0.01)

    assert path == [0, 3, 4, 5]


def test_series_prefers_strong_peaks_over_noise_that_fits():
    # the ladder 1000 -> 1162 -> 1324 has a weak alternative middle peak just
    # within tolerance of the strong one; the strong one is taken
    mzs = [1000.0, 1000.0 + HEX - 0.004, 1000.0 + HEX + 0.001, 1000.0 + 2 * HEX]
    ais = [50.0, 0.5, 40.0, 30.0]

    path = differences.findSeries(mzs, ais, 0, 3, LADDER, 0.01)

    assert path == [0, 2, 3]


def test_series_needs_a_peak_in_between():
    mzs = [1000.0, 1100.0, 1000.0 + HEX]
    ais = [50.0, 10.0, 40.0]

    # one direct step is not a series
    assert differences.findSeries(mzs, ais, 0, 2, LADDER, 0.01) is None


def test_series_at_charge_two_in_ppm():
    step = HEX / 2
    mzs = [800.0, 800.0 + step, 800.0 + 2 * step + 0.002]
    ais = [10.0, 9.0, 8.0]

    assert differences.findSeries(mzs, ais, 0, 2, LADDER, 5, charge=2, units="ppm") == [0, 1, 2]
    # 0.002 m/z at 2+ is 0.004 Da, beyond 1 ppm of ~2100 m/z
    assert differences.findSeries(mzs, ais, 0, 2, LADDER, 1, charge=2, units="ppm") is None


def test_series_skips_steps_under_the_minimum():
    # 1000 -> 1002 -> 1004 would chain on H2, but not with a 14 m/z minimum
    small = [("H2", 2.01565, 2.01588, "test")]
    mzs = [1000.0, 1002.01565, 1004.0313]
    ais = [10.0, 10.0, 10.0]

    assert differences.findSeries(mzs, ais, 0, 2, small, 0.01) == [0, 1, 2]
    assert differences.findSeries(mzs, ais, 0, 2, small, 0.01, minStep=14) is None


def test_multiples_name_whole_multiples_of_an_entry():
    matches = differences.matchMultiples(3 * HEX + 0.002, LADDER, 0.01)

    assert matches[0][0] == "3×Hex"
    assert matches[0][3] == pytest.approx(3 * HEX)
    # a single step is not a multiple, nor is a difference off the grid
    assert not differences.matchMultiples(HEX, LADDER, 0.01)
    assert not differences.matchMultiples(2.5 * HEX, LADDER, 0.01)


def test_multiples_skip_small_entries():
    small = [("H2", 2.01565, 2.01588, "test")]

    assert not differences.matchMultiples(10 * 2.01565, small, 0.01)
    assert differences.matchMultiples(10 * 2.01565, small, 0.01, minStep=0)


def test_series_name_counts_alike_steps():
    assert differences.seriesName(["Hex", "Hex", "Hex"]) == "3×Hex"
    assert differences.seriesName(["Hex", "HexNAc", "Hex"]) == "2×Hex + HexNAc"


def test_ruler_bar_sits_over_the_taller_peak(wx_app):
    import wx

    from mspy import plot_objects

    bitmap = wx.Bitmap(400, 300)
    dc = wx.MemoryDC(bitmap)
    font = wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
    # screen y grows downwards: the peak at y=100 is the taller one
    geometry = plot_objects.drawRuler(
        dc, 50, 200, 250, 100, "Hex", colour=(230, 120, 0), font=font,
        bgrColour=(255, 255, 255),
    )
    flipped = plot_objects.drawRuler(
        dc, 50, 200, 250, 100, "Hex", colour=(230, 120, 0), font=font,
        bgrColour=(255, 255, 255), flipped=True,
    )
    dc.SelectObject(wx.NullBitmap)

    assert geometry[4] < 100
    # flipped: peaks hang down, the one reaching y=200 is the taller
    assert flipped[4] > 200


def test_labels_meeting_at_a_peak_are_picked_up_by_their_own_bar(wx_app):
    from mspy import plot_objects

    spectrum = plot_objects.spectrum(mspy.scan(peaklist=[]))
    # two labels meeting at the peak at x=200: A from 100, B on to 300, their
    # bars at different heights; both leads run down to the peak top at y=150
    spectrum.rulerGeometry = [
        ("A", (100, 150, 200, 150, 120, (100, 105, 200, 124))),
        ("B", (200, 150, 300, 150, 100, (200, 85, 300, 104))),
    ]

    # each end is picked up at its own bar, never at the leads they share
    assert spectrum.rulerAt(197, 120) == ("A", 2)
    assert spectrum.rulerAt(203, 100) == ("B", 1)
    assert spectrum.rulerAt(200, 140) is None
    # the far ends, and the bar away from its ends
    assert spectrum.rulerAt(102, 121) == ("A", 1)
    assert spectrum.rulerAt(150, 115) == ("A", 0)

    # bars lined up at one height: the side of the peak the cursor is on
    spectrum.rulerGeometry = [
        ("A", (100, 150, 200, 150, 100, (100, 85, 200, 104))),
        ("B", (200, 150, 300, 150, 100, (200, 85, 300, 104))),
    ]
    assert spectrum.rulerAt(197, 100) == ("A", 2)
    assert spectrum.rulerAt(203, 100) == ("B", 1)


def test_a_labels_text_does_not_pick_it_up(wx_app):
    from mspy import plot_objects

    spectrum = plot_objects.spectrum(mspy.scan(peaklist=[]))
    # the right label's text is wider than its bar and reaches over the bar of
    # the left one, which lies at the same height; the right one is drawn last
    spectrum.rulerGeometry = [
        ("left", (100, 150, 200, 150, 100, (100, 85, 200, 104))),
        ("right", (200, 150, 240, 150, 100, (140, 85, 300, 104))),
    ]

    # the left bar under the right label's text is the left label's
    assert spectrum.rulerAt(160, 100) == ("left", 0)
    # the text itself picks up nothing
    assert spectrum.rulerAt(270, 90) is None
    assert spectrum.rulerAt(160, 90) is None
