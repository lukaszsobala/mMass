"""The sequence tools window: storing digest matches with Annotate.

The window is built without being shown; it needs a display for the wx.App
and skips without.
"""

import os

import pytest

import mspy

panel = pytest.importorskip("gui.panel_sequence", reason="GUI stack (wx) not available")
from gui import doc  # noqa: E402


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


def _document(title, chain):
    document = doc.document()
    document.title = title
    sequence = mspy.sequence(chain, title=title)
    sequence.matches = []  # pyright: ignore[reportAttributeAccessIssue]
    document.sequences.append(sequence)
    return document


@pytest.fixture
def window(wx_app):
    import wx

    class Parent(wx.Frame):
        """Stands in for the main frame: its documents and change notice."""

        def __init__(self):
            wx.Frame.__init__(self, None, -1, "test")
            self.documents = [
                _document("other", "PEPTIDEK"),
                _document("myoglobin", "GLSDGEWQQVLNVWGKVEADIAGHGQEVLIRLFTGHPETLEK"),
            ]
            self.changed = []

        def onDocumentChanged(self, items=()):
            self.changed.append(items)

    parent = Parent()
    frame = panel.panelSequence(parent, tool="digest")
    yield frame, parent
    frame.Destroy()
    parent.Destroy()


def _digestWithMatch(frame, document):
    """Digest the document's sequence and match one peptide to a peak."""

    frame.setData(document.sequences[0])
    frame.onToolSelected(tool="digest")
    frame.onDigest(None)
    item = next(i for i in frame.currentDigest if i[6].format("S") == "LFTGHPETLEK")
    item[-1].append(doc.match(label="", mz=item[2] + 0.01, ai=1000.0, theoretical=item[2]))
    return item


def test_annotate_stores_the_matches_in_the_document_of_the_sequence(window):
    frame, parent = window
    myoglobin = parent.documents[1]
    _digestWithMatch(frame, myoglobin)

    frame.onAnnotate(None)

    assert len(myoglobin.sequences[0].matches) == 1
    assert "LFTGHPETLEK" in myoglobin.sequences[0].matches[0].label
    assert parent.changed
    assert myoglobin.undoLabel() == "Annotate Sequence Matches"
    assert parent.documents[0].undoLabel() is None


def test_annotate_can_be_undone(window):
    frame, parent = window
    myoglobin = parent.documents[1]
    _digestWithMatch(frame, myoglobin)
    frame.onAnnotate(None)

    myoglobin.restore()

    assert myoglobin.sequences[0].matches == []


def test_annotate_does_nothing_for_a_sequence_no_document_holds(window):
    frame, parent = window
    myoglobin = parent.documents[1]
    _digestWithMatch(frame, myoglobin)
    del parent.documents[1]

    frame.onAnnotate(None)

    assert not parent.changed
