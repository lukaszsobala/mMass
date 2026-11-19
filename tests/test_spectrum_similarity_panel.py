"""The Spectrum Similarity tool window.

The settings checks need wxPython (the module imports it) but no display.
The window checks build the frame without showing it and draw its canvases
into a memory bitmap; they need a display for the wx.App and skip without.
"""

import inspect
import os

import pytest

import mspy
from mmass_app import cli

from .test_similarity import make_scan, random_peaks

panel = pytest.importorskip(
    "gui.panel_spectrum_similarity", reason="GUI stack (wx) not available"
)
from gui import config  # noqa: E402
from gui import similarity_results as results  # noqa: E402

# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------


def test_the_settings_reach_mspy_parameters():
    """Settings are passed on as keyword dicts, which the signature test in
    test_api_signatures cannot see: a renamed key on either side fails here."""

    settings = dict(config.spectrumSimilarity)
    mspy.similarityparams(**panel.similaritySettings(settings))  # raises on unknown keys
    grouping = panel.groupingSettings(settings)
    assert set(grouping) <= set(inspect.signature(mspy.groupspectra).parameters)
    assert "stopper" in inspect.signature(mspy.similaritymatrix).parameters

    settings["edge"] = "auto"
    assert panel.groupingSettings(settings)["edge"] == "auto"


def test_the_config_defaults_are_the_mspy_defaults():
    defaults = panel.defaultSettings()
    for key, value in defaults.items():
        assert config.spectrumSimilarity[key] == value, key


def test_export_writes_what_mmass_cluster_writes():
    assert set(results.OUTPUTS) == set(cli.CLUSTER_OUTPUTS)


def test_a_bad_choice_in_the_settings_file_is_replaced(monkeypatch):
    # a plain copy: nothing here may reach a settings file
    monkeypatch.setattr(config, "spectrumSimilarity", dict(config.spectrumSimilarity))
    config.spectrumSimilarity["axes"] = "sideways"
    config.spectrumSimilarity["edge"] = "high"
    with config._suspendAutoSave():
        config._validateConfig()
    assert config.spectrumSimilarity["axes"] == "both"
    assert config.spectrumSimilarity["edge"] == "0.2"


# ---------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------


@pytest.fixture
def wx_app():
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) and os.name != "nt":
        pytest.skip("no display for a wx.App")
    wx = pytest.importorskip("wx")
    app = wx.App.Get() or wx.App(False)
    from gui import images

    if "bgrToolbarNoBorder" not in images.lib:
        images.loadImages()
    return app


def _documents():
    from gui import doc

    base1 = random_peaks(101, 100, 900, 15)
    base2 = random_peaks(202, 100, 900, 15)
    out = []
    for k, (name, base) in enumerate(
        [("a1", base1), ("a2", base1), ("a3", base1), ("b1", base2), ("b2", base2), ("b3", base2)]
    ):
        document = doc.document()
        document.title = name
        document.path = "/data/%s.mzML" % name
        document.colour = (40 * k, 100, 200)  # pyright: ignore[reportAttributeAccessIssue]
        document.spectrum = make_scan(base + random_peaks(k + 1, 100, 900, 4), hi=950, seed=k)
        out.append(document)
    loner = doc.document()
    loner.title = "loner"
    loner.path = "/data/loner.mzML"
    loner.spectrum = make_scan(random_peaks(303, 100, 900), hi=950, seed=9)
    out.append(loner)
    empty = doc.document()
    empty.title = "empty"
    empty.spectrum = mspy.scan()
    out.append(empty)
    return out


@pytest.fixture
def window(wx_app, monkeypatch):
    import wx

    monkeypatch.setattr(config, "spectrumSimilarity", dict(config.spectrumSimilarity))
    monkeypatch.setattr(config, "main", dict(config.main))
    config.spectrumSimilarity["replicates"] = 10

    class Parent(wx.Frame):
        """Stands in for the main frame's document visibility calls."""

        def __init__(self):
            wx.Frame.__init__(self, None, -1, "test")
            self.documents = _documents()

        def showDocumentsOnly(self, documents):
            previous = {d: d.visible for d in self.documents}
            for d in self.documents:
                d.visible = any(d is x for x in documents)
            return previous

        def restoreDocumentsVisibility(self, previous):
            for d in self.documents:
                d.visible = previous.get(d, d.visible)

    parent = Parent()
    frame = panel.panelSpectrumSimilarity(parent)
    frame.setData(parent.documents)
    yield frame, parent
    frame.Destroy()
    parent.Destroy()


def _draw(canvas):
    import wx

    bitmap = wx.Bitmap(700, 500)
    dc = wx.MemoryDC(bitmap)
    dc.SetFont(wx.SMALL_FONT)
    canvas.draw(dc, 700, 500)
    dc.SelectObject(wx.NullBitmap)


def _compare(frame):
    """Press Compare; return the comparison on show."""

    frame.onCompare()
    data = frame.current
    assert data is not None
    return data


def test_compare_groups_the_visible_documents(window):
    frame, parent = window
    assert frame.current is None
    data = _compare(frame)
    # the document without data is left out, and said so
    assert [d.title for d in data.documents] == ["a1", "a2", "a3", "b1", "b2", "b3", "loner"]
    assert "without data left out" in frame.status_label.GetLabel()
    groups = {data.labels[i]: data.grp.groups[i] for i in range(len(data.labels))}
    assert groups["a1"] == groups["a2"] == groups["a3"] != groups["b1"]
    assert groups["b1"] == groups["b2"] == groups["b3"] != groups["loner"]
    # each group is a block of the matrix
    order = [data.labels[i] for i in data.matrixOrder]
    assert sorted(order[:3]) in (["a1", "a2", "a3"], ["b1", "b2", "b3"])
    assert order[-1] == "loner"


def test_the_views_draw_and_explain_what_is_under_the_cursor(window):
    frame, parent = window
    data = _compare(frame)
    for canvas in (frame.matrixCanvas, frame.treeCanvas):
        _draw(canvas)
    frame.treeCanvas.onThemeChanged()
    _draw(frame.treeCanvas)

    a1, b1 = data.labels.index("a1"), data.labels.index("b1")
    text = frame.pairText(a1, b1)
    assert text.startswith("a1 × b1: similarity") and "together in" in text
    assert frame.spectrumText(a1).startswith("a1: group")
    assert "in 50% of the bootstrap trees" in frame.cladeText([a1, b1], 0.4, 0.5)

    # the matrix knows which cell is under the cursor
    import wx

    left, top, size, n = frame.matrixCanvas._layout
    cell = frame.matrixCanvas.cellAt(wx.Point(int(left + 1.5 * size), int(top + 0.5 * size)))
    assert cell == (0, 1)
    assert frame.matrixCanvas.cellAt(wx.Point(0, 0)) is None


def test_the_groups_view_lists_members_and_shared_signals(window):
    frame, parent = window
    data = _compare(frame)
    assert frame.groupsList.GetItemCount() == 3  # two groups and the ungrouped
    frame.groupsList.Select(0)
    number, members = frame.selectedGroup()
    text = frame.groupText(number, members)
    assert text.startswith("Group 1: 3 spectra") and "Shared m/z" in text
    assert "Not grouped: 1 spectra" in frame.groupText(None, data.singles())


def test_show_and_restore_change_only_the_visibility(window):
    frame, parent = window
    frame.onCompare()
    frame.selectView("groups")
    frame.groupsList.Select(0)
    frame.onShowGroup()
    shown = [d.title for d in parent.documents if d.visible]
    assert len(shown) == 3
    assert frame.restore_butt.IsEnabled()

    # a second show keeps what to restore; Compare still uses the documents
    # visible before
    frame.showSpectra({0, 1})
    frame.setData(parent.documents)
    assert len(frame.candidates()) == len(parent.documents)

    frame.onRestore()
    assert all(d.visible for d in parent.documents)
    assert not frame.restore_butt.IsEnabled()


def test_closing_a_compared_document_drops_the_comparison(window):
    frame, parent = window
    frame.onCompare()
    frame.setData(parent.documents[1:])
    assert frame.current is None
    assert "closed" in frame.status_label.GetLabel()


def test_export_writes_the_cluster_files(window, tmp_path, monkeypatch):
    import wx

    frame, parent = window
    frame.onCompare()

    class Picker:
        def __init__(self, *args, **kwargs):
            pass

        def ShowModal(self):
            return wx.ID_OK

        def GetPath(self):
            return str(tmp_path)

        def Destroy(self):
            pass

    monkeypatch.setattr(wx, "DirDialog", Picker)
    frame.onExport(None)
    for name in results.OUTPUTS:
        assert (tmp_path / name).exists(), name
    assert "mMass Spectrum Similarity" in (tmp_path / "REPORT.md").read_text()


def test_the_settings_dialog_round_trips(window):
    frame, parent = window
    dlg = panel.dlgSimilaritySettings(frame)
    try:
        settings = dlg.getSettings()
        assert settings is not None
        for key, value in settings.items():
            assert config.spectrumSimilarity[key] == value, key
        dlg.edge_value.ChangeValue("strong")
        assert dlg.getSettings() is None
    finally:
        dlg.Destroy()


def test_a_group_is_picked_on_its_outline_or_number(window):
    import wx

    frame, parent = window
    data = _compare(frame)
    canvas = frame.matrixCanvas
    _draw(canvas)
    number, members, rect = canvas._blocks[0]
    assert canvas.itemAt(wx.Point(rect.x, rect.y + rect.height // 2)) == ("group", number)
    inside = canvas.itemAt(wx.Point(rect.x + rect.width // 2, rect.y + rect.height // 2))
    assert inside is not None and inside[0] == "cell"
    x0, x1 = canvas._groupColumn
    y0, y1, i = canvas._labelRows[0]
    assert canvas.itemAt(wx.Point(x0 + 1, (y0 + y1) // 2)) == ("group", data.grp.groups[i])
    assert canvas.itemAt(wx.Point(x1 + 20, (y0 + y1) // 2)) == ("leaf", i)
    assert frame.groupHoverText(number).startswith("Group %d: 3 spectra" % number)

    frame.showGroup(number)
    assert sorted(d.title for d in parent.documents if d.visible) == sorted(
        data.labels[k] for k in members
    )
    assert frame.selectedGroup() == (number, members)


def test_names_are_not_shortened_when_there_is_room(window, monkeypatch):
    import wx

    frame, parent = window
    _compare(frame)
    canvas = frame.matrixCanvas
    drawn = []
    monkeypatch.setattr(panel, "_fitText", lambda dc, text, width: drawn.append(width) or text)
    _draw(canvas)
    dc = wx.MemoryDC(wx.Bitmap(10, 10))
    dc.SetFont(wx.SMALL_FONT)
    widest = max(dc.GetTextExtent(t)[0] for t in frame.current.labels)
    assert min(drawn) >= widest


def test_the_split_moves_with_the_setting(window):
    frame, parent = window
    _compare(frame)
    for canvas, key in ((frame.matrixCanvas, "matrixSplit"), (frame.treeCanvas, "treeSplit")):
        _draw(canvas)
        automatic = canvas._divider
        config.spectrumSimilarity[key] = 0.3
        _draw(canvas)
        assert canvas._divider < automatic
        config.spectrumSimilarity[key] = 7.0  # out of range: automatic
        _draw(canvas)
        assert canvas._divider == automatic


def test_many_spectra_scroll_rather_than_lose_their_names(window, monkeypatch):
    import wx

    from gui import doc

    frame, parent = window
    many = []
    for k in range(60):
        document = doc.document()
        document.title = "spectrum %02d" % k
        document.spectrum = make_scan(random_peaks(1000 + k, 100, 900, 12), hi=950, seed=k)
        many.append(document)
    parent.documents = many
    frame.setData(many)
    _compare(frame)

    drawn = []
    real = panel._canvas.drawLabel

    def spy(self, dc, i, y, rowHeight, *args, **kwargs):
        drawn.append(rowHeight)
        return real(self, dc, i, y, rowHeight, *args, **kwargs)

    monkeypatch.setattr(panel._canvas, "drawLabel", spy)
    dc = wx.MemoryDC(wx.Bitmap(10, 10))
    dc.SetFont(wx.SMALL_FONT)
    for canvas in (frame.matrixCanvas, frame.treeCanvas):
        # a view far too short for 60 rows
        width, height = canvas.requiredSize(dc, 700, 300)
        assert height > 300
        drawn.clear()
        _draw_at(canvas, 700, 300)
        assert len(drawn) == 60
        assert min(drawn) >= canvas.minRow(dc)


def _draw_at(canvas, w, h):
    import wx

    bitmap = wx.Bitmap(w, h)
    dc = wx.MemoryDC(bitmap)
    dc.SetFont(wx.SMALL_FONT)
    canvas.draw(dc, w, h)
    dc.SelectObject(wx.NullBitmap)


def test_the_window_remembers_its_size_within_the_screen(window):
    import wx

    frame, parent = window
    config.spectrumSimilarity["windowWidth"] = 50000
    config.spectrumSimilarity["windowHeight"] = 50000
    width, height = frame.initialSize(100)
    area = wx.Display(0).GetClientArea()
    assert width <= area.width and height <= area.height

    frame.SetClientSize(wx.Size(900, 650))
    frame.onClose(None)
    assert config.spectrumSimilarity["windowWidth"] > 0
    assert config.spectrumSimilarity["windowHeight"] > 0


def test_a_dragged_split_is_not_held_back_by_the_height(window):
    import wx

    frame, parent = window
    _compare(frame)
    canvas = frame.matrixCanvas
    dc = wx.MemoryDC(wx.Bitmap(10, 10))
    dc.SetFont(wx.SMALL_FONT)
    assert canvas.requiredSize(dc, 900, 300)[1] <= 300  # automatic: fits the window
    config.spectrumSimilarity["matrixSplit"] = 0.8
    left, top, size, legend = canvas.layout(dc, 900, 300)
    assert size * len(frame.current.labels) > 0.8 * 900 - 2 * left - 1
    assert canvas.requiredSize(dc, 900, 300)[1] > 300  # taller: the view scrolls


def test_every_setting_explains_itself_on_hover(window):
    import wx

    frame, parent = window
    dlg = panel.dlgSimilaritySettings(frame)
    kinds = (wx.TextCtrl, wx.CheckBox, wx.RadioButton, wx.Choice)

    def controls(window):
        for child in window.GetChildren():
            if isinstance(child, kinds):
                yield child
            yield from controls(child)

    try:
        windows = list(controls(dlg))
        windows += [w for w in controls(frame) if w.GetParent() is not frame.groupsPage]
        assert len(windows) > 20
        silent = [w.GetName() for w in windows if not w.GetToolTipText()]
        assert not silent
        for tip in panel.TIPS.values():
            assert len(tip.splitlines()) <= 2
    finally:
        dlg.Destroy()


def test_losses_only_refuses_spectra_without_a_precursor(window):
    frame, parent = window
    config.spectrumSimilarity["axes"] = "loss"
    frame.onCompare()
    assert frame.current is None
    assert "no precursor m/z" in frame.status_label.GetLabel()



def test_an_edited_spectrum_makes_the_comparison_out_of_date(window):
    frame, parent = window
    _compare(frame)
    # showing a group changes visibility only: still current
    frame.showSpectra({0, 1})
    frame.setData(parent.documents)
    assert frame.current is not None and not frame.current.stale
    frame.onRestore()

    scan = parent.documents[0].spectrum
    scan.profile = scan.profile * 2.0  # e.g. processed
    frame.setData(parent.documents)
    assert frame.current.stale
    assert "Compare again" in frame.status_label.GetLabel()
    assert not frame.export_butt.IsEnabled()


def test_restore_survives_closing_a_compared_document(window):
    frame, parent = window
    _compare(frame)
    frame.showSpectra({0, 1})
    hidden = [d for d in parent.documents if not d.visible]
    assert hidden
    parent.documents = parent.documents[1:]
    frame.setData(parent.documents)
    assert frame.current is None
    assert frame.restore_butt.IsEnabled()
    frame.onRestore()
    assert all(d.visible for d in hidden)


def test_stop_stays_usable_while_comparing(window, monkeypatch):
    frame, parent = window
    skipped = []
    real = panel.wx.WindowDisabler

    def recorder(*args):
        skipped.extend(args)
        return real(*args)

    # the disabler must skip this window: a plain one disables Stop as well
    monkeypatch.setattr(panel.wx, "WindowDisabler", recorder)
    frame.onProcessing(True)
    assert skipped == [frame]
    try:
        assert frame.IsEnabled()
        assert not frame.toolbar.IsEnabled() and not frame.bottombar.IsEnabled()
        assert frame.gauge.GetParent().IsEnabled()
        assert frame._disabler is not None
    finally:
        frame.onProcessing(False)
    assert frame._disabler is None and frame.toolbar.IsEnabled()



def test_pairs_without_a_common_range_are_not_blamed_on_polarity(window):
    from gui import doc

    frame, parent = window
    documents = []
    for k, (lo, hi) in enumerate([(100, 300), (100, 300), (400, 600)]):
        document = doc.document()
        document.title = "r%d" % k
        document.spectrum = make_scan(
            random_peaks(50 + k, lo + 10, hi - 10), lo=lo, hi=hi, seed=k
        )
        documents.append(document)
    parent.documents = documents
    frame.setData(documents)
    _compare(frame)
    summary = frame.summary()
    assert "without a common m/z range" in summary
    assert "polarities" not in summary
    assert "no m/z range in common" in frame.pairText(0, 2)
