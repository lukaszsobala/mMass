# -------------------------------------------------------------------------
#     This program is free software; you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation; either version 3 of the License, or
#     (at your option) any later version.

#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#     GNU General Public License for more details.

#     Complete text of GNU GPL can be found in the file LICENSE.TXT in the
#     main directory of the program.
# -------------------------------------------------------------------------

"""Spectrum Similarity tool: group the visible spectra by similarity.

The similarity (mspy.similaritymatrix) is corrected for the m/z range of each
pair, so fragment spectra of related compounds come together rather than
spectra of similar precursor mass.  Groups are communities of a spectral
network (mspy.groupspectra), with bootstrap confidence.

Three views of one comparison: the similarity matrix (ordered by group), the
average-linkage tree, and the groups with the signals their members share.
Clicking a cell, a clade or a group shows only those documents in the main
window; Restore puts the visibility back.
"""

import inspect
import math
import os
import threading
import time
import traceback

import numpy
import wx

import mspy

from . import config
from . import images
from . import mwx
from . import similarity_results as results

# FLOATING PANEL WITH SPECTRUM SIMILARITY TOOL
# --------------------------------------------

# config keys passed on to mspy.similaritymatrix unchanged
_SIMILARITY_KEYS = (
    "source",
    "tolerance",
    "axes",
    "binWidth",
    "minMZ",
    "isolation",
    "baselineWindow",
    "noiseWindow",
    "snr",
    "transform",
    "posAdduct",
    "negAdduct",
)
_FLOAT_KEYS = (
    "tolerance",
    "binWidth",
    "minMZ",
    "isolation",
    "baselineWindow",
    "noiseWindow",
    "snr",
)


def similaritySettings(settings):
    """mspy.similaritymatrix parameters from config.spectrumSimilarity."""

    params = {key: settings[key] for key in _SIMILARITY_KEYS}
    for key in _FLOAT_KEYS:
        params[key] = float(params[key])
    params["weighting"] = "rarity" if settings["weighting"] else "none"
    params["chanceCorrection"] = bool(settings["chanceCorrection"])
    params["neutralMass"] = bool(settings["neutralMass"])
    return params


def groupingSettings(settings):
    """mspy.groupspectra parameters from config.spectrumSimilarity."""

    edge = str(settings["edge"]).strip()
    return {
        "method": settings["method"],
        "edge": "auto" if edge == "auto" else float(edge),
        "topK": int(settings["topK"]),
        "resolution": float(settings["resolution"]),
        "cut": float(settings["cut"]),
        "replicates": int(settings["replicates"]),
        "seed": int(settings["seed"]),
    }


def defaultSettings():
    """The analysis defaults, as config.spectrumSimilarity values (from mspy,
    so the tool and `mmass cluster` start from the same place)."""

    sim = mspy.similarityparams()
    grouping = {
        name: p.default
        for name, p in inspect.signature(mspy.groupspectra).parameters.items()
        if p.default is not inspect.Parameter.empty
    }
    out = {key: sim[key] for key in _SIMILARITY_KEYS}
    out["weighting"] = int(sim["weighting"] == "rarity")
    out["chanceCorrection"] = int(sim["chanceCorrection"])
    out["neutralMass"] = int(sim["neutralMass"])
    for key in ("method", "topK", "resolution", "cut", "seed", "replicates"):
        out[key] = grouping[key]
    out["edge"] = str(grouping["edge"])
    return out


POS_ADDUCTS = [("Na", "[M+Na]+"), ("H", "[M+H]+"), ("K", "[M+K]+"), ("NH4", "[M+NH4]+")]
NEG_ADDUCTS = [("H", "[M-H]-"), ("Cl", "[M+Cl]-"), ("HCOO", "[M+HCOO]-")]

# hover help of the settings (dialog and tool bar), one or two short lines
TIPS = {
    "source": "What is compared: the whole spectra or the picked peaks.",
    "profile": "The whole spectra, with baseline and noise removed.",
    "peaks": "Only the picked peaks.",
    "tolerance": "Signals this far apart in m/z (Da) still match.",
    "replicates": "Repeats on resampled spectra, to show how stable the groups are\n(0 = off, faster).",
    "settings": "Signal cleaning, comparison and grouping settings.",
    "compare": "Compare the visible documents.",
    "matrix": "Similarity of every pair, with the groups as squares.",
    "tree": "Tree of the spectra, with bootstrap support at the branches.",
    "groups": "The groups, with the ions and losses their members share.",
    "baselineWindow": "Background is followed over this width;\nhumps broader than it are removed as baseline.",
    "noiseWindow": "Local noise is measured over this width.",
    "snr": "Only signal this many times above the local noise is compared.",
    "minMZ": "Signal below this m/z is ignored.",
    "isolation": "Fragment spectra: this much on each side of the precursor m/z is ignored.",
    "binWidth": "Spacing of the grid the spectra are compared on;\nsmaller is finer but slower.",
    "axes": "Spectra with a precursor m/z (MS/MS).\nOthers are always compared on m/z.",
    "axesBoth": "Fragment ions and the masses lost from the precursor.",
    "axesMz": "Fragment ions only.",
    "axesLoss": "Masses lost from the precursor only;\nevery spectrum needs a precursor m/z.",
    "transform": "How peak heights are scaled before comparing.",
    "sqrt": "Tames large peaks without hiding small ones.",
    "log": "Small peaks count almost as much as large ones.",
    "none": "Large peaks dominate.",
    "weighting": "Signals most spectra have count less than rare ones.",
    "chanceCorrection": "Subtracts the similarity expected by chance for the pair's m/z range\nand peak density: 0 = chance, 1 = identical.",
    "neutralMass": "Compare positive and negative spectra, assuming one ion type per polarity.\nOff: each polarity is grouped on its own.",
    "posAdduct": "Ion type assumed for every positive spectrum.",
    "negAdduct": "Ion type assumed for every negative spectrum.",
    "network": "Groups are communities of a network linking each spectrum\nto its most similar ones.",
    "treeCut": "Groups are the branches of the tree cut at a similarity.",
    "edge": 'Spectra are linked only from this similarity up.\n"auto" sets it from the pairs (for sets of mostly unrelated spectra).',
    "topK": "Two spectra are linked only if each is one of the other's\nN most similar spectra (N = this number).",
    "resolution": "Higher splits the network into more, smaller groups.",
    "cut": "Branches joining above this similarity form one group.",
    "seed": "Seed of the bootstrap and the network grouping;\nthe same seed gives the same result.",
}

# similarity falling this steeply with the difference in m/z range hints at
# miscalibrated fragment spectra (uncalibrated LIFT spectra gave -0.57)
RANGE_WARNING = -0.5


# COMPARISON
# ----------


def fingerprint(scan):
    """What the comparison read from a spectrum, condensed: a change in it
    (processing, peak picking, undo) makes the comparison out of date, while
    showing or hiding the document does not."""

    if scan is None:
        return None
    profile = scan.profile
    if profile is not None and len(profile):
        data = (len(profile), float(numpy.asarray(profile)[:, 1].sum()))
    else:
        data = (0, 0.0)
    peaks = [(p.mz, p.intensity) for p in scan.peaklist]
    return (id(scan), data, len(peaks), float(numpy.sum(peaks)) if peaks else 0.0,
            scan.precursorMZ, scan.polarity)



class comparison:
    """One comparison: the documents, their labels and the mspy results."""

    def __init__(self, documents, items, sim, grp, similarity, grouping):
        self.documents = documents
        self.items = items
        self.labels = [item.label for item in items]
        self.sim = sim
        self.grp = grp
        self.similarity = similarity
        self.grouping = grouping

        # the matrix is ordered by group (tree order within each), so every
        # group is a block on the diagonal
        rank = {i: k for k, i in enumerate(grp.order)}
        self.matrixOrder = sorted(grp.order, key=lambda i: (grp.groups[i], rank[i]))

        self.groups = results.groups_in_order(grp)
        self._features = {}
        self.fingerprints = [fingerprint(d.spectrum) for d in documents]
        self.stale = False

    # ----

    def features(self, members):
        """Shared m/z and losses of members (cached)."""

        key = tuple(sorted(members))
        if key not in self._features:
            self._features[key] = mspy.sharedfeatures(self.sim, list(members))
        return self._features[key]

    # ----

    def multiGroups(self):
        return [(c, m) for c, m in self.groups if len(m) > 1]

    # ----

    def singles(self):
        return [m[0] for c, m in self.groups if len(m) == 1]


# CANVASES
# --------


def _themeColours():
    """Colours of the canvases in the current theme."""

    if images.is_dark_mode():
        return {
            "background": wx.Colour(30, 30, 30),
            "text": wx.Colour(220, 220, 220),
            "muted": wx.Colour(130, 130, 130),
            "faint": wx.Colour(60, 60, 60),
            "ramp": ((36, 40, 48), (49, 110, 170), (170, 215, 255)),
            "accent": wx.Colour(120, 180, 240),
            "hover": wx.Colour(255, 170, 60),
        }
    return {
        "background": wx.WHITE,
        "text": wx.BLACK,
        "muted": wx.Colour(130, 130, 130),
        "faint": wx.Colour(225, 225, 225),
        "ramp": ((247, 251, 255), (107, 174, 214), (8, 48, 107)),
        "accent": wx.Colour(33, 102, 172),
        "hover": wx.Colour(230, 120, 0),
    }


def _rampColour(ramp, value):
    """Colour of value (0..1) on a three-stop ramp."""

    value = min(max(value, 0.0), 1.0)
    if value <= 0.5:
        a, b, t = ramp[0], ramp[1], value / 0.5
    else:
        a, b, t = ramp[1], ramp[2], (value - 0.5) / 0.5
    return wx.Colour(*[int(round(x + (y - x) * t)) for x, y in zip(a, b, strict=True)])


def _fitText(dc, text, width):
    """text, shortened with an ellipsis to fit width pixels."""

    if width <= 0:
        return ""
    if dc.GetTextExtent(text)[0] <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if dc.GetTextExtent(text[:mid] + "…")[0] <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…" if lo else ""


class _canvas(wx.ScrolledWindow):
    """A drawn view of a comparison, with hover and click callbacks.

    owner gets hover(text or None) and the view-specific click calls.

    Rows never get shorter than a name in the smallest label font needs:
    when the spectra do not fit at that height, the view scrolls instead of
    leaving names out.  The layout is worked out from the visible size
    (layout()), and requiredSize() gives the area it covers.

    The names sit to the right of the drawing; the boundary between them can
    be dragged (and double-clicked for the automatic layout).  Its position
    is kept as a share of the width in config.spectrumSimilarity[SPLIT_KEY],
    0 meaning automatic.
    """

    SPLIT_KEY = ""

    # in the automatic layout the names get up to this share of the width
    AUTO_LABEL_SHARE = 0.45

    # limits of a dragged split, as a share of the width
    SPLIT_RANGE = (0.15, 0.95)

    # smallest font the names shrink to; rows are never shorter than it needs
    MIN_LABEL_POINTS = 6.5

    def __init__(self, parent, owner):
        wx.ScrolledWindow.__init__(
            self, parent, -1, style=wx.BORDER_SUNKEN | wx.HSCROLL | wx.VSCROLL
        )
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetScrollRate(self.FromDIP(10), self.FromDIP(10))
        self.owner = owner
        self.data: comparison | None = None
        self.colours = _themeColours()
        self.hovered = None

        # x of the names / drawing boundary (set by draw), and a drag of it
        self._divider = None
        self._overDivider = False
        self._dragSplit = None

        self.Bind(wx.EVT_PAINT, self.onPaint)
        self.Bind(wx.EVT_SIZE, self._onSize)
        self.Bind(wx.EVT_MOTION, self._onMouseMotion)
        self.Bind(wx.EVT_LEAVE_WINDOW, self.onLeave)
        self.Bind(wx.EVT_LEFT_DOWN, self._onLeftDown)
        self.Bind(wx.EVT_LEFT_UP, self._onLeftUp)
        self.Bind(wx.EVT_LEFT_DCLICK, self._onDoubleClick)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._onCaptureLost)

    # ----

    @property
    def comp(self) -> "comparison":
        """The comparison on show (drawing code runs only when there is one)."""

        assert self.data is not None
        return self.data

    # ----

    def setData(self, data):
        self.data = data
        self.hovered = None
        self.Scroll(0, 0)
        self.updateVirtualSize()

    # ----

    def _onSize(self, evt):
        evt.Skip()
        self.updateVirtualSize()

    # ----

    def updateVirtualSize(self):
        """Make the scrollable area cover the layout for the visible size."""

        cw, ch = self.GetClientSize()
        if self.data is None or cw <= 0 or ch <= 0:
            self.SetVirtualSize(max(cw, 1), max(ch, 1))
        else:
            dc = wx.ClientDC(self)
            dc.SetFont(wx.SMALL_FONT)
            vw, vh = self.requiredSize(dc, cw, ch)
            self.SetVirtualSize(max(cw, int(math.ceil(vw))), max(ch, int(math.ceil(vh))))
        self.Refresh()

    # ----

    def requiredSize(self, dc, w, h):
        """(width, height) the drawing covers when the visible size is w x h."""

        return w, h

    # ----

    def minRow(self, dc):
        """Shortest row: the height of a name in the smallest label font."""

        font = wx.Font(wx.SMALL_FONT)
        font.SetFractionalPointSize(
            min(font.GetFractionalPointSize(), self.MIN_LABEL_POINTS)
        )
        dc.SetFont(font)
        height = dc.GetCharHeight()
        dc.SetFont(wx.SMALL_FONT)
        return float(height)

    # ----

    def extentWidth(self, w):
        """Width to draw names into: the scrollable width when it is wider."""

        return max(w, self.GetVirtualSize()[0])

    # ----

    def onThemeChanged(self):
        self.colours = _themeColours()
        self.Refresh()

    # ----

    def onPaint(self, evt):
        dc = wx.AutoBufferedPaintDC(self)
        self.DoPrepareDC(dc)
        dc.SetBackground(wx.Brush(self.colours["background"]))
        dc.Clear()
        dc.SetFont(wx.SMALL_FONT)
        w, h = self.GetClientSize()
        if self.data is None:
            self._divider = None
            self.drawEmpty(dc, w, h)
            return
        self.draw(dc, w, h)
        if self._divider is not None and (self._overDivider or self._dragSplit is not None):
            dc.SetPen(wx.Pen(self.colours["muted"], 1, wx.PENSTYLE_DOT))
            dc.DrawLine(self._divider, 0, self._divider, self.GetVirtualSize()[1])

    # SPLIT
    # -----

    def splitValue(self):
        """The dragged split as a share of the width, or None for automatic."""

        if self._dragSplit is not None:
            return self._dragSplit
        try:
            value = float(config.spectrumSimilarity.get(self.SPLIT_KEY, 0.0))
        except (TypeError, ValueError):
            return None
        low, high = self.SPLIT_RANGE
        return value if low <= value <= high else None

    # ----

    def nearDivider(self, pos):
        return (
            self.data is not None
            and self._divider is not None
            and abs(pos.x - self._divider) <= self.FromDIP(4)
        )

    # ----

    def _setOverDivider(self, over):
        if over != self._overDivider:
            self._overDivider = over
            self.SetCursor(wx.Cursor(wx.CURSOR_SIZEWE) if over else wx.NullCursor)
            self.Refresh()

    # ----

    def eventPosition(self, evt):
        """Mouse position of evt in drawing (scrolled) coordinates."""

        return self.CalcUnscrolledPosition(evt.GetPosition())

    # ----

    def _onMouseMotion(self, evt):
        pos = self.eventPosition(evt)
        if self._dragSplit is not None:
            low, high = self.SPLIT_RANGE
            width = max(1, self.GetClientSize()[0])
            self._dragSplit = min(high, max(low, pos.x / float(width)))
            self.updateVirtualSize()
            return
        if self.nearDivider(pos):
            self._setOverDivider(True)
            self.setHovered(
                None, "Drag to give the names more or less room; double-click to reset"
            )
            return
        self._setOverDivider(False)
        self.onMotion(pos)

    # ----

    def _onLeftDown(self, evt):
        if not self.nearDivider(self.eventPosition(evt)):
            evt.Skip()
            return
        width = max(1, self.GetClientSize()[0])
        self._dragSplit = (self._divider or 0) / float(width)
        self.CaptureMouse()

    # ----

    def _endDrag(self):
        if self.HasCapture():
            self.ReleaseMouse()
        if self._dragSplit is not None:
            config.spectrumSimilarity[self.SPLIT_KEY] = round(self._dragSplit, 3)
        self._dragSplit = None
        self.updateVirtualSize()

    # ----

    def _onLeftUp(self, evt):
        if self._dragSplit is not None:
            self._endDrag()
            return
        pos = self.eventPosition(evt)
        if not self.nearDivider(pos):
            self.onClick(pos)

    # ----

    def _onCaptureLost(self, evt):
        self._endDrag()

    # ----

    def _onDoubleClick(self, evt):
        if not self.nearDivider(self.eventPosition(evt)):
            evt.Skip()
            return
        if self._dragSplit is not None:
            self._endDrag()
        config.spectrumSimilarity[self.SPLIT_KEY] = 0.0
        self.updateVirtualSize()

    # ----

    def drawEmpty(self, dc, w, h):
        text = self.owner.emptyText()
        dc.SetTextForeground(self.colours["muted"])
        tw, th = dc.GetTextExtent(text)
        dc.DrawText(text, max(0, (w - tw) // 2), max(0, (h - th) // 2))

    # ----

    def onLeave(self, evt):
        if self._dragSplit is None:
            self._setOverDivider(False)
        if self.hovered is not None:
            self.hovered = None
            self.Refresh()
        self.owner.hover(None)

    # ----

    def setHovered(self, hovered, text):
        if hovered != self.hovered:
            self.hovered = hovered
            self.Refresh()
        self.owner.hover(text)

    # ----

    def labelGeometry(self, dc, x, labelWidth):
        """Where the labels go when they start at x, beside the matrix or the
        tree: (x of group numbers, x of swatches, x of names, name width)."""

        pad = self.FromDIP(6)
        x1 = x + dc.GetTextExtent("00")[0] + pad
        x2 = x1 + self.swatchSize(dc) + pad // 2
        return x, x1, x2, max(0, labelWidth)

    # ----

    def labelOverhead(self, dc):
        """Width of the group number and colour in front of each name."""

        x0, _, x2, _ = self.labelGeometry(dc, 0, 0)
        return x2 - x0

    # ----

    def widestLabel(self, dc):
        return max(dc.GetTextExtent(t)[0] for t in self.comp.labels)

    # ----

    def autoLabelWidth(self, dc, w):
        """Room the automatic layout gives the names: all they need, up to
        AUTO_LABEL_SHARE of the width."""

        return min(self.widestLabel(dc), int(self.AUTO_LABEL_SHARE * w))

    # ----

    def swatchSize(self, dc):
        return max(4, int(dc.GetCharHeight() * 0.75))

    # ----

    def fitLabelFont(self, dc, rowHeight):
        """Use the small font for the names, shrunk to fit rows of rowHeight,
        down to MIN_LABEL_POINTS (rows are never shorter than that needs)."""

        font = wx.Font(wx.SMALL_FONT)
        dc.SetFont(font)
        th = dc.GetCharHeight()
        if th > rowHeight:
            points = font.GetFractionalPointSize()
            font.SetFractionalPointSize(
                max(min(points, self.MIN_LABEL_POINTS), points * rowHeight / float(th))
            )
        self._labelFont = font
        dc.SetFont(wx.SMALL_FONT)

    # ----

    def drawLabel(self, dc, i, y, rowHeight, geometry, groupNumber=None, bold=False):
        """Group number, document colour and label of spectrum i, centred on
        a row of rowHeight starting at y."""

        x0, x1, x2, labelWidth = geometry
        font = wx.Font(getattr(self, "_labelFont", wx.SMALL_FONT))
        if bold:
            font.SetWeight(wx.FONTWEIGHT_BOLD)
        dc.SetFont(font)
        th = dc.GetCharHeight()
        dc.SetFont(wx.SMALL_FONT)
        swatch = min(self.swatchSize(dc), max(2, int(rowHeight) - 1))
        mid = y + rowHeight / 2.0

        colour = self.comp.documents[i].colour
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(wx.Colour(*colour[:3])))
        dc.DrawRectangle(x1, int(mid - swatch / 2.0), swatch, swatch)

        if rowHeight < 0.6 * th:
            return
        dc.SetFont(font)
        dc.SetTextForeground(self.colours["text"])
        dc.DrawText(
            _fitText(dc, self.comp.labels[i], labelWidth), x2, int(mid - th / 2.0)
        )
        if groupNumber is not None:
            dc.SetTextForeground(self.colours["muted"])
            dc.DrawText(str(groupNumber), x0, int(mid - th / 2.0))
        dc.SetFont(wx.SMALL_FONT)

    # ----

    def onMotion(self, pos):
        pass

    # ----

    def onClick(self, pos):
        pass

    # ----

    def draw(self, dc, w, h):
        pass


class matrixCanvas(_canvas):
    """The corrected similarity of every pair, ordered by group."""

    SPLIT_KEY = "matrixSplit"

    def layout(self, dc, w, h):
        """(left, top, cell size, legend height) for a visible size of w x h.

        The matrix is square.  The automatic layout fits it to the window;
        a dragged split sets its width, and so its height and the spacing of
        the names, and the view scrolls when it gets taller than the window.
        Cells are never smaller than a row of names needs.
        """

        n = len(self.comp.matrixOrder)
        pad = self.FromDIP(6)
        left = pad
        top = pad + self.swatchSize(dc) + pad
        legend = dc.GetCharHeight() + self.FromDIP(14)
        split = self.splitValue()
        if split is None:
            room = w - left - 2 * pad - self.labelOverhead(dc) - self.autoLabelWidth(dc, w)
            room = min(room, h - top - legend - pad)
        else:
            room = int(split * w) - left - pad
        size = max(self.minRow(dc), room / float(n))
        return left, top, size, legend

    # ----

    def requiredSize(self, dc, w, h):
        n = len(self.comp.matrixOrder)
        pad = self.FromDIP(6)
        left, top, size, legend = self.layout(dc, w, h)
        names = self.widestLabel(dc)  # in full: the view scrolls rather than cut them
        width = left + n * size + pad + self.labelOverhead(dc) + names + pad
        return width, top + n * size + legend + pad

    # ----

    def draw(self, dc, w, h):
        data = self.comp
        order = data.matrixOrder
        n = len(order)
        S = data.sim.similarity
        pad = self.FromDIP(6)
        th = dc.GetCharHeight()
        swatch = self.swatchSize(dc)
        overhead = self.labelOverhead(dc)
        left, top, size, legend = self.layout(dc, w, h)
        self._layout = (left, top, size, n)

        def edge(k):
            return int(round(k * size))

        # the names take whatever is left, so they are shortened only when
        # there is no room
        labelsStart = left + edge(n) + pad
        self._divider = labelsStart - pad // 2
        geometry = self.labelGeometry(
            dc, labelsStart, self.extentWidth(w) - pad - labelsStart - overhead
        )
        self.fitLabelFont(dc, size)

        # cells
        dc.SetPen(wx.TRANSPARENT_PEN)
        for r, i in enumerate(order):
            y = top + edge(r)
            hgt = max(1, edge(r + 1) - edge(r))
            for c, j in enumerate(order):
                x = left + edge(c)
                wid = max(1, edge(c + 1) - edge(c))
                if i == j:
                    colour = self.colours["faint"]
                elif numpy.isfinite(S[i, j]):
                    colour = _rampColour(self.colours["ramp"], S[i, j])
                else:
                    colour = self.colours["background"]
                dc.SetBrush(wx.Brush(colour))
                dc.DrawRectangle(x, y, wid, hgt)
                if i != j and not numpy.isfinite(S[i, j]) and wid > 3:
                    dc.SetPen(wx.Pen(self.colours["faint"], 1))
                    dc.DrawLine(x, y + hgt - 1, x + wid - 1, y)
                    dc.SetPen(wx.TRANSPARENT_PEN)

        # group blocks; the hovered one, cell or name stands out
        position = {i: k for k, i in enumerate(order)}
        hovered: tuple = tuple(self.hovered) if self.hovered else ("",)
        self._blocks = []
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        for number, members in data.multiGroups():
            a = min(position[i] for i in members)
            b = max(position[i] for i in members) + 1
            rect = wx.Rect(left + edge(a), top + edge(a), edge(b) - edge(a), edge(b) - edge(a))
            self._blocks.append((number, members, rect))
            on = hovered == ("group", number)
            dc.SetPen(
                wx.Pen(
                    self.colours["hover"] if on else self.colours["text"],
                    self.FromDIP(3 if on else 2),
                )
            )
            dc.DrawRectangle(rect)

        if hovered[0] == "cell":
            _, r, c = hovered
            dc.SetPen(wx.Pen(self.colours["hover"], self.FromDIP(2)))
            dc.DrawRectangle(
                left + edge(c), top + edge(r), max(2, edge(c + 1) - edge(c)),
                max(2, edge(r + 1) - edge(r)),
            )

        # labels: rows, and the document colours over the columns
        first = {}
        for c, members in data.groups:
            if len(members) > 1:
                first[min(members, key=lambda i: position[i])] = c
        if hovered[0] == "cell":
            boldRows = {order[hovered[1]], order[hovered[2]]}
        elif hovered[0] == "group":
            boldRows = {i for i in order if data.grp.groups[i] == hovered[1]}
        elif hovered[0] == "leaf":
            boldRows = {hovered[1]}
        else:
            boldRows = set()
        self._labelRows = []
        self._groupColumn = (geometry[0], geometry[1])
        for r, i in enumerate(order):
            self._labelRows.append((top + edge(r), top + edge(r + 1), i))
            self.drawLabel(
                dc, i, top + r * size, size, geometry,
                groupNumber=first.get(i), bold=i in boldRows,
            )
            colour = data.documents[i].colour
            sw = min(swatch, max(2, edge(r + 1) - edge(r) - 1))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(wx.Colour(*colour[:3])))
            dc.DrawRectangle(
                left + edge(r) + (edge(r + 1) - edge(r) - sw) // 2, pad, sw, sw
            )

        self.drawLegend(dc, left, top + edge(n) + self.FromDIP(8), th)

    # ----

    def drawLegend(self, dc, x, y, th):
        """Colour scale under the matrix."""

        barWidth = self.FromDIP(120)
        barHeight = max(6, th // 2)
        dc.SetTextForeground(self.colours["muted"])
        label = "similarity  0"
        dc.DrawText(label, x, y)
        x += dc.GetTextExtent(label)[0] + self.FromDIP(4)
        dc.SetPen(wx.TRANSPARENT_PEN)
        for k in range(barWidth):
            dc.SetBrush(wx.Brush(_rampColour(self.colours["ramp"], k / float(barWidth - 1))))
            dc.DrawRectangle(x + k, y + (th - barHeight) // 2, 1, barHeight)
        x += barWidth + self.FromDIP(4)
        dc.DrawText("1", x, y)
        if not self.comp.sim.comparable.all():
            x += self.FromDIP(24)
            dc.SetPen(wx.Pen(self.colours["faint"], 1))
            dc.SetBrush(wx.Brush(self.colours["background"]))
            dc.DrawRectangle(x, y + (th - barHeight) // 2, barHeight * 2, barHeight)
            dc.DrawText("not compared", x + barHeight * 2 + self.FromDIP(4), y)

    # ----

    def cellAt(self, pos):
        layout = getattr(self, "_layout", None)
        if self.data is None or layout is None:
            return None
        left, top, size, n = layout
        c = int((pos.x - left) // size)
        r = int((pos.y - top) // size)
        if 0 <= r < n and 0 <= c < n and pos.x >= left and pos.y >= top:
            return r, c
        return None

    # ----

    def itemAt(self, pos):
        """What is under pos: ("group", number), ("cell", row, column) or
        ("leaf", spectrum); None for nothing.

        A group is picked on its outline or its number beside the names.
        """

        if self.data is None:
            return None
        slack = self.FromDIP(3)
        for number, _, rect in getattr(self, "_blocks", []):
            outer = wx.Rect(rect).Inflate(slack, slack)
            inner = wx.Rect(rect).Deflate(slack, slack)
            if outer.Contains(pos) and not inner.Contains(pos):
                return ("group", number)
        cell = self.cellAt(pos)
        if cell is not None:
            return ("cell", cell[0], cell[1])
        x0, x1 = getattr(self, "_groupColumn", (0, 0))
        for y0, y1, i in getattr(self, "_labelRows", []):
            if y0 <= pos.y < y1 and pos.x >= x0:
                number = self.comp.grp.groups[i]
                if pos.x < x1 and numpy.count_nonzero(self.comp.grp.groups == number) > 1:
                    return ("group", int(number))
                return ("leaf", i)
        return None

    # ----

    def onMotion(self, pos):
        item = self.itemAt(pos)
        if item is None:
            self.setHovered(None, None)
            return
        order = self.comp.matrixOrder
        if item[0] == "group":
            text = self.owner.groupHoverText(item[1])
        elif item[0] == "cell":
            text = self.owner.pairText(order[item[1]], order[item[2]])
        else:
            text = self.owner.spectrumText(item[1])
        self.setHovered(item, text)

    # ----

    def onClick(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return
        order = self.comp.matrixOrder
        if item[0] == "group":
            self.owner.showGroup(item[1])
        elif item[0] == "cell":
            self.owner.showSpectra({order[item[1]], order[item[2]]})
        else:
            self.owner.showSpectra({item[1]})


class treeCanvas(_canvas):
    """Average-linkage trees (one per polarity) with bootstrap support."""

    SPLIT_KEY = "treeSplit"

    def layout(self, dc, w, h):
        """(x where the names start, row height, top, gap between trees in
        rows, axis height) for a visible size of w x h."""

        grp = self.comp.grp
        pad = self.FromDIP(6)
        th = dc.GetCharHeight()
        overhead = self.labelOverhead(dc)
        split = self.splitValue()
        if split is None:
            labelsStart = w - pad - overhead - self.autoLabelWidth(dc, w)
        else:
            labelsStart = int(split * w)
        labelsStart = max(labelsStart, pad + self.FromDIP(120))
        gap = 0.8 if len(grp.trees) > 1 else 0.0
        rows = len(grp.order) + gap * (len(grp.trees) - 1)
        axis = th + self.FromDIP(12)
        top = pad + (th if len(grp.trees) > 1 else 0)
        rowHeight = max(self.minRow(dc), (h - top - axis - pad) / rows)
        return labelsStart, rowHeight, top, gap, axis

    # ----

    def requiredSize(self, dc, w, h):
        grp = self.comp.grp
        pad = self.FromDIP(6)
        labelsStart, rowHeight, top, gap, axis = self.layout(dc, w, h)
        rows = len(grp.order) + gap * (len(grp.trees) - 1)
        names = self.widestLabel(dc)  # in full: the view scrolls rather than cut them
        width = labelsStart + self.labelOverhead(dc) + names + pad
        return width, top + rows * rowHeight + axis + pad

    # ----

    def draw(self, dc, w, h):
        data = self.comp
        grp = data.grp
        pad = self.FromDIP(6)
        th = dc.GetCharHeight()
        overhead = self.labelOverhead(dc)
        labelsStart, rowHeight, top, gap, axis = self.layout(dc, w, h)
        geometry = self.labelGeometry(
            dc, labelsStart, self.extentWidth(w) - pad - labelsStart - overhead
        )
        self._labelsStart = labelsStart
        self._divider = labelsStart - pad // 2
        trees = sorted(
            [t for t in grp.trees], key=lambda t: -len(t[0])
        )  # the display order of groupspectra
        self.fitLabelFont(dc, rowHeight)

        # the root on the left, the leaves on the right beside their names
        x0 = pad + dc.GetTextExtent("100")[0] + self.FromDIP(3)
        x1 = labelsStart - pad
        heights = [float(Z[:, 2].max()) for _, Z, _ in trees if len(Z)]
        dmax = max(heights + [0.05])

        def xmap(d):
            return int(round(x1 - (x1 - x0) * d / dmax))

        group = grp.groups
        sizes = numpy.bincount(group)
        self._nodes = []
        self._rows = []
        y = float(top)
        for comp, Z, support in trees:
            if len(trees) > 1:
                pol = data.items[comp[0]].scan.polarity
                caption = {1: "positive", -1: "negative"}.get(pol, "")
                if caption:
                    dc.SetTextForeground(self.colours["muted"])
                    dc.DrawText(caption, x0, int(y - th))
            leaves = mspy.treeorder(Z) if len(Z) else list(range(len(comp)))
            ys = {}
            for local in leaves:
                i = comp[local]
                ys[local] = y + rowHeight / 2.0
                hovered = self.hovered == ("leaf", i)
                # a group need not be one clade, so every member is numbered
                self.drawLabel(
                    dc, i, y, rowHeight, geometry,
                    groupNumber=group[i] if sizes[group[i]] > 1 else None,
                    bold=hovered,
                )
                self._rows.append((y, y + rowHeight, i))
                y += rowHeight
            y += gap * rowHeight

            # branches
            n = len(comp)
            pos = {k: (x1, ys[k]) for k in range(n)}
            members = {k: [comp[k]] for k in range(n)}
            for k, (a, b, d, _) in enumerate(Z):
                a, b = int(a), int(b)
                xa, ya = pos[a]
                xb, yb = pos[b]
                xn = xmap(d)
                inside = members[a] + members[b]
                one = len({group[i] for i in inside}) == 1 and sizes[group[inside[0]]] > 1
                hovered = self.hovered == ("node", tuple(sorted(inside)))
                colour = self.colours["hover"] if hovered else (
                    self.colours["accent"] if one else self.colours["muted"]
                )
                dc.SetPen(wx.Pen(colour, self.FromDIP(2) if (one or hovered) else 1))
                dc.DrawLine(xa, int(ya), xn, int(ya))
                dc.DrawLine(xb, int(yb), xn, int(yb))
                dc.DrawLine(xn, int(min(ya, yb)), xn, int(max(ya, yb)))
                pos[n + k] = (xn, (ya + yb) / 2.0)
                members[n + k] = inside
                sup = None if support is None else float(support[k])
                self._nodes.append((xn, min(ya, yb), max(ya, yb), inside, d, sup))
                # the root is in every tree, so its support says nothing
                if sup is not None and k < len(Z) - 1 and rowHeight >= th * 0.6:
                    text = "%d" % round(100 * sup)
                    dc.SetTextForeground(self.colours["muted"])
                    dc.DrawText(
                        text,
                        xn - dc.GetTextExtent(text)[0] - self.FromDIP(3),
                        int((ya + yb) / 2.0 - th),
                    )

        self.drawAxis(dc, x0, x1, int(y - gap * rowHeight) + self.FromDIP(4), dmax, th)

    # ----

    def drawAxis(self, dc, x0, x1, y, dmax, th):
        """Similarity scale: 1 at the leaves."""

        dc.SetPen(wx.Pen(self.colours["muted"], 1))
        dc.SetTextForeground(self.colours["muted"])
        dc.DrawLine(x0, y, x1, y)
        step = 0.1 if dmax <= 0.6 else (0.2 if dmax <= 1.2 else 0.5)
        k = 0
        while k * step <= dmax + 1e-9:
            x = int(round(x1 - (x1 - x0) * (k * step) / dmax))
            dc.DrawLine(x, y, x, y + self.FromDIP(3))
            text = "%g" % round(1.0 - k * step, 2)
            tw = dc.GetTextExtent(text)[0]
            dc.DrawText(text, x - tw // 2, y + self.FromDIP(3))
            k += 1
        dc.DrawText("similarity", x1 + self.FromDIP(12), y + self.FromDIP(3))

    # ----

    def itemAt(self, pos):
        if self.data is None:
            return None
        slack = self.FromDIP(4)
        for x, ya, yb, inside, d, sup in getattr(self, "_nodes", []):
            if abs(pos.x - x) <= slack and ya - slack <= pos.y <= yb + slack:
                return ("node", tuple(sorted(inside))), (inside, d, sup)
        for ya, yb, i in getattr(self, "_rows", []):
            if ya <= pos.y < yb and pos.x >= getattr(self, "_labelsStart", 0):
                return ("leaf", i), i
        return None

    # ----

    def onMotion(self, pos):
        found = self.itemAt(pos)
        if found is None:
            self.setHovered(None, None)
            return
        key, info = found
        if key[0] == "node":
            inside, d, sup = info
            text = self.owner.cladeText(inside, 1.0 - d, sup)
        else:
            text = self.owner.spectrumText(info)
        self.setHovered(key, text)

    # ----

    def onClick(self, pos):
        found = self.itemAt(pos)
        if found is None:
            return
        key, info = found
        if key[0] == "node":
            self.owner.showSpectra(set(info[0]))
        else:
            self.owner.showSpectra({info})


# SETTINGS
# --------


class dlgSimilaritySettings(wx.Dialog):
    """The analysis settings the tool bar has no room for."""

    def __init__(self, parent):
        wx.Dialog.__init__(
            self, parent, -1, "Spectrum Similarity Settings",
            style=wx.DEFAULT_DIALOG_STYLE,
        )

        sizer = self.makeGUI()
        self.setData(config.spectrumSimilarity)
        self.onNeutralMass()
        self.onMethod()

        self.Layout()
        sizer.Fit(self)
        self.SetSizer(sizer)
        self.SetMinSize(self.GetSize())

        mwx.applyDarkMode(self)
        self.CentreOnParent()

    # ----

    def _field(self, width=70, kind="floatPos"):
        return wx.TextCtrl(self, -1, "", size=wx.Size(width, -1), validator=mwx.validator(kind))

    # ----

    def _label(self, text, tip):
        label = wx.StaticText(self, -1, text)
        label.SetToolTip(TIPS[tip])
        return label

    # ----

    def _grid(self, rows):
        """GridBagSizer of (label, control, units, tip key) rows; the tip is
        shown over the label and the control."""

        grid = wx.GridBagSizer(mwx.GRIDBAG_VSPACE, mwx.GRIDBAG_HSPACE)
        for r, (label, control, units, tip) in enumerate(rows):
            control.SetToolTip(TIPS[tip])
            grid.Add(
                self._label(label, tip), (r, 0),
                flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL,
            )
            grid.Add(control, (r, 1), flag=wx.ALIGN_CENTER_VERTICAL)
            if units:
                grid.Add(wx.StaticText(self, -1, units), (r, 2), flag=wx.ALIGN_CENTER_VERTICAL)
        return grid

    # ----

    def makeGUI(self):
        """Make GUI elements."""

        # signal
        self.baselineWindow_value = self._field()
        self.noiseWindow_value = self._field()
        self.snr_value = self._field()
        self.minMZ_value = self._field()
        self.isolation_value = self._field()
        self.binWidth_value = self._field()
        signalBox = mwx.staticBoxSizer(self, "Signal", wx.VERTICAL)
        signalBox.Add(
            self._grid(
                [
                    ("Baseline window:", self.baselineWindow_value, "Da", "baselineWindow"),
                    ("Noise window:", self.noiseWindow_value, "Da", "noiseWindow"),
                    ("Signal above noise:", self.snr_value, "×", "snr"),
                    ("Low-mass limit:", self.minMZ_value, "m/z", "minMZ"),
                    ("Precursor window:", self.isolation_value, "Da", "isolation"),
                    ("Grid step:", self.binWidth_value, "Da", "binWidth"),
                ]
            ),
            0, wx.ALL, 5,
        )

        # comparison
        self.axesBoth_radio = wx.RadioButton(self, -1, "m/z and losses", style=wx.RB_GROUP)
        self.axesMz_radio = wx.RadioButton(self, -1, "m/z only")
        self.axesLoss_radio = wx.RadioButton(self, -1, "Losses only")
        self.axesBoth_radio.SetToolTip(TIPS["axesBoth"])
        self.axesMz_radio.SetToolTip(TIPS["axesMz"])
        self.axesLoss_radio.SetToolTip(TIPS["axesLoss"])
        self.transformSqrt_radio = wx.RadioButton(self, -1, "Square root", style=wx.RB_GROUP)
        self.transformLog_radio = wx.RadioButton(self, -1, "Logarithm")
        self.transformNone_radio = wx.RadioButton(self, -1, "As measured")
        self.transformSqrt_radio.SetToolTip(TIPS["sqrt"])
        self.transformLog_radio.SetToolTip(TIPS["log"])
        self.transformNone_radio.SetToolTip(TIPS["none"])
        self.weighting_check = wx.CheckBox(self, -1, "Count signals most spectra share less")
        self.weighting_check.SetToolTip(TIPS["weighting"])
        self.chance_check = wx.CheckBox(self, -1, "Correct for chance similarity")
        self.chance_check.SetToolTip(TIPS["chanceCorrection"])
        compareBox = mwx.staticBoxSizer(self, "Comparison", wx.VERTICAL)
        grid = wx.GridBagSizer(mwx.GRIDBAG_VSPACE, mwx.GRIDBAG_HSPACE)
        grid.Add(self._label("Fragment spectra:", "axes"), (0, 0), flag=wx.ALIGN_RIGHT)
        grid.Add(self.axesBoth_radio, (0, 1))
        grid.Add(self.axesMz_radio, (1, 1))
        grid.Add(self.axesLoss_radio, (2, 1))
        grid.Add(self._label("Intensity:", "transform"), (3, 0), flag=wx.ALIGN_RIGHT)
        grid.Add(self.transformSqrt_radio, (3, 1))
        grid.Add(self.transformLog_radio, (4, 1))
        grid.Add(self.transformNone_radio, (5, 1))
        compareBox.Add(grid, 0, wx.ALL, 5)
        compareBox.Add(self.weighting_check, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        compareBox.Add(self.chance_check, 0, wx.ALL, 5)

        # polarity
        self.neutralMass_check = wx.CheckBox(self, -1, "Compare polarities on neutral mass")
        self.neutralMass_check.SetToolTip(TIPS["neutralMass"])
        self.neutralMass_check.Bind(wx.EVT_CHECKBOX, self.onNeutralMass)
        self.posAdduct_choice = wx.Choice(self, -1, choices=[t for _, t in POS_ADDUCTS])
        self.negAdduct_choice = wx.Choice(self, -1, choices=[t for _, t in NEG_ADDUCTS])
        mwx.fitChoice(self.posAdduct_choice)
        mwx.fitChoice(self.negAdduct_choice)
        polarityBox = mwx.staticBoxSizer(self, "Polarity", wx.VERTICAL)
        polarityBox.Add(self.neutralMass_check, 0, wx.ALL, 5)
        polarityBox.Add(
            self._grid(
                [
                    ("Positive ions:", self.posAdduct_choice, "", "posAdduct"),
                    ("Negative ions:", self.negAdduct_choice, "", "negAdduct"),
                ]
            ),
            0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5,
        )

        # grouping
        self.methodNetwork_radio = wx.RadioButton(self, -1, "Network", style=wx.RB_GROUP)
        self.methodTree_radio = wx.RadioButton(self, -1, "Tree cut")
        self.methodNetwork_radio.Bind(wx.EVT_RADIOBUTTON, self.onMethod)
        self.methodTree_radio.Bind(wx.EVT_RADIOBUTTON, self.onMethod)
        self.methodNetwork_radio.SetToolTip(TIPS["network"])
        self.methodTree_radio.SetToolTip(TIPS["treeCut"])
        self.edge_value = wx.TextCtrl(self, -1, "", size=wx.Size(70, -1))
        self.topK_value = self._field(kind="intPos")
        self.resolution_value = self._field()
        self.cut_value = self._field(kind="float")
        self.seed_value = self._field(kind="intPos")
        groupBox = mwx.staticBoxSizer(self, "Groups", wx.VERTICAL)
        methods = wx.BoxSizer(wx.HORIZONTAL)
        methods.Add(self.methodNetwork_radio, 0, wx.RIGHT, 10)
        methods.Add(self.methodTree_radio, 0)
        groupBox.Add(methods, 0, wx.ALL, 5)
        groupBox.Add(
            self._grid(
                [
                    ("Link at similarity:", self.edge_value, "", "edge"),
                    ("Mutual top matches:", self.topK_value, "", "topK"),
                    ("Resolution:", self.resolution_value, "", "resolution"),
                    ("Cut tree at similarity:", self.cut_value, "", "cut"),
                    ("Random seed:", self.seed_value, "", "seed"),
                ]
            ),
            0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5,
        )

        # buttons
        defaults_butt = wx.Button(self, -1, "Defaults")
        defaults_butt.Bind(wx.EVT_BUTTON, self.onDefaults)
        cancel_butt = wx.Button(self, wx.ID_CANCEL, "Cancel")
        ok_butt = wx.Button(self, wx.ID_OK, "OK")
        ok_butt.Bind(wx.EVT_BUTTON, self.onOK)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(defaults_butt, 0, wx.RIGHT, 30)
        buttons.Add(cancel_butt, 0, wx.RIGHT, 15)
        buttons.Add(ok_butt, 0)

        leftColumn = wx.BoxSizer(wx.VERTICAL)
        leftColumn.Add(signalBox, 0, wx.EXPAND)
        leftColumn.AddSpacer(mwx.PANEL_SPACE_MAIN)
        leftColumn.Add(polarityBox, 0, wx.EXPAND)
        rightColumn = wx.BoxSizer(wx.VERTICAL)
        rightColumn.Add(compareBox, 0, wx.EXPAND)
        rightColumn.AddSpacer(mwx.PANEL_SPACE_MAIN)
        rightColumn.Add(groupBox, 0, wx.EXPAND)
        columns = wx.BoxSizer(wx.HORIZONTAL)
        columns.Add(leftColumn, 0, wx.EXPAND | wx.RIGHT, mwx.PANEL_SPACE_MAIN)
        columns.Add(rightColumn, 0, wx.EXPAND)

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        mainSizer.Add(columns, 1, wx.EXPAND | wx.ALL, mwx.PANEL_SPACE_MAIN)
        mainSizer.Add(buttons, 0, wx.CENTER | wx.LEFT | wx.RIGHT | wx.BOTTOM, mwx.PANEL_SPACE_MAIN)
        return mainSizer

    # ----

    def setData(self, settings):
        """Show settings (config.spectrumSimilarity or the defaults)."""

        for key in ("baselineWindow", "noiseWindow", "snr", "minMZ", "isolation", "binWidth"):
            getattr(self, key + "_value").ChangeValue("%g" % settings[key])
        self.axesBoth_radio.SetValue(settings["axes"] == "both")
        self.axesMz_radio.SetValue(settings["axes"] == "mz")
        self.axesLoss_radio.SetValue(settings["axes"] == "loss")
        self.transformSqrt_radio.SetValue(settings["transform"] == "sqrt")
        self.transformLog_radio.SetValue(settings["transform"] == "log")
        self.transformNone_radio.SetValue(settings["transform"] == "none")
        self.weighting_check.SetValue(bool(settings["weighting"]))
        self.chance_check.SetValue(bool(settings["chanceCorrection"]))
        self.neutralMass_check.SetValue(bool(settings["neutralMass"]))
        self.posAdduct_choice.SetSelection([k for k, _ in POS_ADDUCTS].index(settings["posAdduct"]))
        self.negAdduct_choice.SetSelection([k for k, _ in NEG_ADDUCTS].index(settings["negAdduct"]))
        self.methodNetwork_radio.SetValue(settings["method"] == "network")
        self.methodTree_radio.SetValue(settings["method"] == "tree")
        self.edge_value.ChangeValue(str(settings["edge"]))
        self.topK_value.ChangeValue(str(int(settings["topK"])))
        self.resolution_value.ChangeValue("%g" % settings["resolution"])
        self.cut_value.ChangeValue("%g" % settings["cut"])
        self.seed_value.ChangeValue(str(int(settings["seed"])))

    # ----

    def onNeutralMass(self, evt=None):
        enabled = self.neutralMass_check.GetValue()
        self.posAdduct_choice.Enable(enabled)
        self.negAdduct_choice.Enable(enabled)

    # ----

    def onMethod(self, evt=None):
        network = self.methodNetwork_radio.GetValue()
        for ctrl in (self.edge_value, self.topK_value, self.resolution_value):
            ctrl.Enable(network)
        self.cut_value.Enable(not network)

    # ----

    def onDefaults(self, evt):
        self.setData(defaultSettings())
        self.onNeutralMass()
        self.onMethod()

    # ----

    def getSettings(self):
        """The settings as typed, or None after pointing at a bad value."""

        out = {}
        current = self.baselineWindow_value
        positive = {
            "baselineWindow": self.baselineWindow_value,
            "noiseWindow": self.noiseWindow_value,
            "snr": self.snr_value,
            "isolation": self.isolation_value,
            "binWidth": self.binWidth_value,
            "resolution": self.resolution_value,
        }
        def finite(ctrl):
            value = float(ctrl.GetValue())
            if not math.isfinite(value):
                raise ValueError
            return value

        try:
            for key, ctrl in positive.items():
                current = ctrl
                out[key] = finite(ctrl)
                if out[key] <= 0:
                    raise ValueError
            current = self.minMZ_value
            out["minMZ"] = finite(self.minMZ_value)
            if out["minMZ"] < 0:
                raise ValueError
            current = self.topK_value
            out["topK"] = int(self.topK_value.GetValue())
            if out["topK"] < 1:
                raise ValueError
            current = self.cut_value
            out["cut"] = finite(self.cut_value)
            current = self.seed_value
            out["seed"] = int(self.seed_value.GetValue())
            if out["seed"] < 0:
                raise ValueError
            current = self.edge_value
            edge = self.edge_value.GetValue().strip().lower()
            if edge != "auto" and not math.isfinite(float(edge)):
                raise ValueError
            out["edge"] = edge
        except ValueError:
            wx.Bell()
            current.SetFocus()
            current.SelectAll()
            return None

        if self.axesMz_radio.GetValue():
            out["axes"] = "mz"
        elif self.axesLoss_radio.GetValue():
            out["axes"] = "loss"
        else:
            out["axes"] = "both"
        if self.transformLog_radio.GetValue():
            out["transform"] = "log"
        elif self.transformNone_radio.GetValue():
            out["transform"] = "none"
        else:
            out["transform"] = "sqrt"
        out["weighting"] = int(self.weighting_check.GetValue())
        out["chanceCorrection"] = int(self.chance_check.GetValue())
        out["neutralMass"] = int(self.neutralMass_check.GetValue())
        out["posAdduct"] = POS_ADDUCTS[self.posAdduct_choice.GetSelection()][0]
        out["negAdduct"] = NEG_ADDUCTS[self.negAdduct_choice.GetSelection()][0]
        out["method"] = "tree" if self.methodTree_radio.GetValue() else "network"
        return out

    # ----

    def onOK(self, evt):
        settings = self.getSettings()
        if settings is None:
            return
        for key, value in settings.items():
            config.spectrumSimilarity[key] = value
        self.EndModal(wx.ID_OK)


# MAIN FRAME
# ----------


class panelSpectrumSimilarity(wx.Frame):
    """Spectrum similarity tool."""

    VIEWS = ("matrix", "tree", "groups")

    def __init__(self, parent):
        wx.Frame.__init__(
            self,
            parent,
            -1,
            "Spectrum Similarity",
            size=wx.Size(820, 620),
            style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT,
        )

        self.parent = parent
        self.processing = None
        self._outcome = None
        self._disabler = None

        # documents Compare would use, the comparison on show, and the
        # visibility to put back after showing a pair or a group
        self.allDocuments = []
        self.current = None
        self.savedVisibility = None
        self.notice = ""

        self.makeGUI()
        self.Bind(wx.EVT_CLOSE, self.onClose)
        mwx.applyDarkMode(self)
        self.updateStatus()

    # ----

    def makeGUI(self):
        """Make panel gui."""

        toolbar = self.toolbar = self.makeToolbar()
        self.book = wx.Simplebook(self, -1)
        self.matrixCanvas = matrixCanvas(self.book, self)
        self.treeCanvas = treeCanvas(self.book, self)
        self.groupsPage = self.makeGroupsPage(self.book)
        self.book.AddPage(self.matrixCanvas, "Matrix")
        self.book.AddPage(self.treeCanvas, "Tree")
        self.book.AddPage(self.groupsPage, "Groups")
        bottombar = self.bottombar = self.makeBottombar()
        gauge = self.makeGaugePanel()

        self.mainSizer = wx.BoxSizer(wx.VERTICAL)
        self.mainSizer.Add(toolbar, 0, wx.EXPAND)
        self.mainSizer.Add(self.book, 1, wx.EXPAND)
        self.mainSizer.Add(bottombar, 0, wx.EXPAND)
        self.mainSizer.Add(gauge, 0, wx.EXPAND)
        self.mainSizer.Hide(3)

        # GTK ignores a frame size set before Show, so the size comes from the
        # sizer minimum: the page asks for the room wanted, then lets go of it
        bars = toolbar.GetBestSize().height + bottombar.GetBestSize().height
        width, height = self.initialSize(toolbar.GetBestSize().width)
        self.book.SetMinSize(wx.Size(width, max(self.FromDIP(200), height - bars)))
        self.SetSizer(self.mainSizer)
        self.mainSizer.Fit(self)
        self.SetMinSize(self.GetSize())

        # let go only once shown: GTK sizes the window from these hints
        minimum = wx.Size(toolbar.GetBestSize().width, bars + self.FromDIP(240))
        wx.CallAfter(self._releaseMinSize, minimum)
        self.selectView(config.spectrumSimilarity["view"])

    # ----

    def _releaseMinSize(self, minimum):
        """After the window opened at its starting size, let it shrink."""

        try:
            self.book.SetMinSize(wx.Size(self.FromDIP(200), self.FromDIP(200)))
            self.SetMinSize(minimum)
            self.Layout()
        except RuntimeError:
            pass  # closed meanwhile

    # ----

    # window size (DIP) when none is remembered
    DEFAULT_SIZE = (1100, 760)

    def initialSize(self, minWidth):
        """Inner size to open at: the size it was closed at (or DEFAULT_SIZE),
        never larger than the free area of the screen the main window is on."""

        settings = config.spectrumSimilarity
        width = int(settings["windowWidth"]) or self.DEFAULT_SIZE[0]
        height = int(settings["windowHeight"]) or self.DEFAULT_SIZE[1]
        width, height = self.FromDIP(wx.Size(width, height))
        try:
            index = wx.Display.GetFromWindow(self.parent)
            if index == wx.NOT_FOUND:
                index = 0
            area = wx.Display(index).GetClientArea()
            # leave room for the title bar and the window frame
            width = min(width, area.width - self.FromDIP(20))
            height = min(height, area.height - self.FromDIP(60))
        except Exception:
            pass
        return max(width, minWidth), max(height, self.FromDIP(300))

    # ----

    def makeToolbar(self):
        """Make toolbar."""

        panel = mwx.bgrPanel(
            self, -1, images.lib["bgrToolbarNoBorder"], size=wx.Size(-1, mwx.TOOLBAR_HEIGHT)
        )

        source_label = wx.StaticText(panel, -1, "Compare:")
        source_label.SetFont(wx.SMALL_FONT)
        source_label.SetToolTip(TIPS["source"])
        self.sourceProfile_radio = wx.RadioButton(panel, -1, "Profiles", style=wx.RB_GROUP)
        self.sourceProfile_radio.SetFont(wx.SMALL_FONT)
        self.sourceProfile_radio.SetToolTip(TIPS["profile"])
        self.sourcePeaks_radio = wx.RadioButton(panel, -1, "Peak lists")
        self.sourcePeaks_radio.SetFont(wx.SMALL_FONT)
        self.sourcePeaks_radio.SetToolTip(TIPS["peaks"])
        self.sourcePeaks_radio.SetValue(config.spectrumSimilarity["source"] == "peaks")
        self.sourceProfile_radio.SetValue(config.spectrumSimilarity["source"] != "peaks")

        tolerance_label = wx.StaticText(panel, -1, "Tolerance:")
        tolerance_label.SetFont(wx.SMALL_FONT)
        tolerance_label.SetToolTip(TIPS["tolerance"])
        self.tolerance_value = wx.TextCtrl(
            panel, -1, "%g" % config.spectrumSimilarity["tolerance"],
            size=wx.Size(50, -1), style=wx.TE_PROCESS_ENTER,
            validator=mwx.validator("floatPos"),
        )
        self.tolerance_value.SetToolTip(TIPS["tolerance"])
        self.tolerance_value.Bind(wx.EVT_TEXT_ENTER, self.onCompare)
        tolerance_units = wx.StaticText(panel, -1, "Da")
        tolerance_units.SetFont(wx.SMALL_FONT)

        replicates_label = wx.StaticText(panel, -1, "Bootstrap:")
        replicates_label.SetFont(wx.SMALL_FONT)
        replicates_label.SetToolTip(TIPS["replicates"])
        self.replicates_value = wx.TextCtrl(
            panel, -1, str(int(config.spectrumSimilarity["replicates"])),
            size=wx.Size(50, -1), style=wx.TE_PROCESS_ENTER,
            validator=mwx.validator("intPos"),
        )
        self.replicates_value.SetToolTip(TIPS["replicates"])
        self.replicates_value.Bind(wx.EVT_TEXT_ENTER, self.onCompare)

        settings_butt = wx.Button(
            panel, -1, "Settings...", size=wx.Size(-1, mwx.SMALL_BUTTON_HEIGHT)
        )
        settings_butt.SetToolTip(TIPS["settings"])
        settings_butt.Bind(wx.EVT_BUTTON, self.onSettings)

        self.compare_butt = wx.Button(
            panel, -1, "Compare", size=wx.Size(-1, mwx.SMALL_BUTTON_HEIGHT)
        )
        self.compare_butt.SetToolTip(TIPS["compare"])
        self.compare_butt.Bind(wx.EVT_BUTTON, self.onCompare)

        self.export_butt = wx.Button(
            panel, -1, "Export...", size=wx.Size(-1, mwx.SMALL_BUTTON_HEIGHT)
        )
        self.export_butt.SetToolTip("Tables, trees and a report, as mmass cluster writes them.")
        self.export_butt.Bind(wx.EVT_BUTTON, self.onExport)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.AddSpacer(mwx.CONTROLBAR_LSPACE)
        sizer.Add(source_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(self.sourceProfile_radio, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(self.sourcePeaks_radio, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(20)
        sizer.Add(tolerance_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(self.tolerance_value, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(tolerance_units, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(20)
        sizer.Add(replicates_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(self.replicates_value, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(20)
        sizer.Add(settings_butt, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddStretchSpacer()
        sizer.AddSpacer(20)
        sizer.Add(self.compare_butt, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        sizer.Add(self.export_butt, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(mwx.CONTROLBAR_RSPACE)

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        mainSizer.Add(sizer, 1, wx.EXPAND)
        panel.SetSizer(mainSizer)
        mainSizer.Fit(panel)
        return panel

    # ----

    def makeGroupsPage(self, parent):
        """The groups, and the members and shared signals of the one selected."""

        page = wx.Panel(parent, -1)
        self.groupsList = wx.ListCtrl(page, -1, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for col, (title, width) in enumerate(
            [("Group", 60), ("Spectra", 60), ("Similarity", 75), ("Together", 70), ("Weakest", 70)]
        ):
            self.groupsList.InsertColumn(
                col, title, wx.LIST_FORMAT_LEFT if col == 0 else wx.LIST_FORMAT_RIGHT
            )
            self.groupsList.SetColumnWidth(col, self.FromDIP(width))
        self.groupsList.SetFont(wx.SMALL_FONT)
        self.groupsList.Bind(wx.EVT_LIST_ITEM_SELECTED, self.onGroupSelected)
        self.groupsList.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.onShowGroup)

        self.groupDetails = wx.TextCtrl(
            page, -1, "", style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP
        )
        font = wx.Font(wx.FontInfo(wx.SMALL_FONT.GetPointSize()).Family(wx.FONTFAMILY_TELETYPE))
        self.groupDetails.SetFont(font)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.groupsList, 0, wx.EXPAND)
        sizer.AddSpacer(mwx.SASH_SIZE)
        sizer.Add(self.groupDetails, 1, wx.EXPAND)
        self.groupsList.SetMinSize(wx.Size(self.FromDIP(345), -1))
        page.SetSizer(sizer)
        return page

    # ----

    def makeBottombar(self):
        """View switch, the status line, and the show / restore buttons."""

        panel = mwx.bgrPanel(
            self, -1, images.lib["bgrControlbar"], size=(-1, mwx.CONTROLBAR_HEIGHT)
        )

        self.view_radios = {}
        for k, (view, label) in enumerate(
            [("matrix", "Matrix"), ("tree", "Tree"), ("groups", "Groups")]
        ):
            radio = wx.RadioButton(panel, -1, label, style=wx.RB_GROUP if k == 0 else 0)
            radio.SetFont(wx.SMALL_FONT)
            radio.SetToolTip(TIPS[view])
            radio.Bind(wx.EVT_RADIOBUTTON, lambda evt, view=view: self.selectView(view))
            self.view_radios[view] = radio

        self.status_label = wx.StaticText(
            panel, -1, "", style=wx.ST_ELLIPSIZE_END | wx.ST_NO_AUTORESIZE
        )
        self.status_label.SetFont(wx.SMALL_FONT)

        self.showGroup_butt = wx.Button(
            panel, -1, "Show Group", size=wx.Size(-1, mwx.SMALL_BUTTON_HEIGHT)
        )
        self.showGroup_butt.SetToolTip("Show only this group's documents.")
        self.showGroup_butt.Bind(wx.EVT_BUTTON, self.onShowGroup)
        self.restore_butt = wx.Button(
            panel, -1, "Restore", size=wx.Size(-1, mwx.SMALL_BUTTON_HEIGHT)
        )
        self.restore_butt.SetToolTip("Show the documents that were visible before.")
        self.restore_butt.Bind(wx.EVT_BUTTON, self.onRestore)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.AddSpacer(mwx.CONTROLBAR_LSPACE)
        for view in self.VIEWS:
            sizer.Add(self.view_radios[view], 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.AddSpacer(15)
        sizer.Add(self.status_label, 1, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(15)
        sizer.Add(self.showGroup_butt, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        sizer.Add(self.restore_butt, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(mwx.CONTROLBAR_RSPACE)

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        mainSizer.Add(sizer, 1, wx.EXPAND)
        mainSizer.Fit(panel)
        panel.SetSizer(mainSizer)
        return panel

    # ----

    def makeGaugePanel(self):
        """Make processing gauge."""

        panel = wx.Panel(self, -1)
        self.gauge = mwx.gauge(panel, -1)
        stop_butt = mwx.makeBitmapButton(
            panel, -1, images.lib["stopper"], style=wx.BORDER_NONE
        )
        stop_butt.Bind(wx.EVT_BUTTON, self.onStop)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.gauge, 1, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(10)
        sizer.Add(stop_butt, 0, wx.ALIGN_CENTER_VERTICAL)

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        if wx.Platform == "__WXMAC__":
            mainSizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.TOP, -1)
        mainSizer.Add(sizer, 1, wx.EXPAND | wx.ALL, mwx.GAUGE_SPACE)
        panel.SetSizer(mainSizer)
        mainSizer.Fit(panel)
        return panel

    # ----

    def onClose(self, evt):
        """Destroy this frame."""

        if self.processing is not None:
            wx.Bell()
            return
        if not (self.IsMaximized() or self.IsIconized()):
            width, height = self.ToDIP(self.GetClientSize())
            config.spectrumSimilarity["windowWidth"] = int(width)
            config.spectrumSimilarity["windowHeight"] = int(height)
        self.Destroy()

    # ----

    def onThemeChanged(self):
        """The canvases paint themselves; the rest follows the system."""

        self.matrixCanvas.onThemeChanged()
        self.treeCanvas.onThemeChanged()

    # DOCUMENTS
    # ---------

    def setData(self, documents):
        """The main window's documents changed (list, visibility or data)."""

        self.allDocuments = list(documents)

        if self.current is not None and any(
            not any(d is x for x in self.allDocuments) for d in self.current.documents
        ):
            # Restore stays available for the documents still open (pruned below)
            self.setComparison(None)
            self.notice = "A compared document was closed."
        elif self.current is not None and not self.current.stale:
            now = [fingerprint(d.spectrum) for d in self.current.documents]
            if now != self.current.fingerprints:
                self.current.stale = True

        if self.savedVisibility is not None:
            self.savedVisibility = {
                d: v for d, v in self.savedVisibility.items()
                if any(d is x for x in self.allDocuments)
            }

        self.updateButtons()
        self.updateStatus()

    # ----

    def candidates(self):
        """The documents Compare uses: the visible ones, or while a pair or a
        group is shown here, those visible before."""

        if self.savedVisibility is not None:
            return [d for d in self.allDocuments if self.savedVisibility.get(d, d.visible)]
        return [d for d in self.allDocuments if d.visible]

    # ----

    def usable(self, documents, source):
        """(documents with data for the source, how many without)."""

        out = []
        for document in documents:
            scan = document.spectrum
            if scan is None:
                continue
            hasProfile = scan.profile is not None and len(scan.profile) > 0
            hasPeaks = len(scan.peaklist) > 0
            if hasPeaks or (source == "profile" and hasProfile):
                out.append(document)
        return out, len(documents) - len(out)

    # COMPARING
    # ---------

    def getParams(self):
        """Read the tool bar into config; False after pointing at a bad value."""

        settings = config.spectrumSimilarity
        try:
            tolerance = float(self.tolerance_value.GetValue())
            if not (math.isfinite(tolerance) and tolerance > 0):
                raise ValueError
        except ValueError:
            wx.Bell()
            self.tolerance_value.SetFocus()
            return False
        try:
            replicates = int(self.replicates_value.GetValue())
            if replicates < 0:
                raise ValueError
        except ValueError:
            wx.Bell()
            self.replicates_value.SetFocus()
            return False
        settings["tolerance"] = tolerance
        settings["replicates"] = replicates
        settings["source"] = "peaks" if self.sourcePeaks_radio.GetValue() else "profile"
        return True

    # ----

    def onCompare(self, evt=None):
        """Compare the visible documents."""

        if self.processing is not None:
            return
        if not self.getParams():
            return

        settings = config.spectrumSimilarity
        try:
            similarity = similaritySettings(settings)
            grouping = groupingSettings(settings)
            mspy.similarityparams(**similarity)
        except (ValueError, KeyError) as exc:
            wx.Bell()
            self.notice = "Settings: %s" % exc
            self.updateStatus()
            return

        documents, skipped = self.usable(self.candidates(), similarity["source"])
        if similarity["axes"] == "loss":
            without = [d for d in documents if not d.spectrum.precursorMZ]
            if without:
                wx.Bell()
                self.notice = (
                    "Losses only compares fragment spectra: %d of the documents have "
                    "no precursor m/z (see Settings)." % len(without)
                )
                self.updateStatus()
                return
        if len(documents) < 2:
            wx.Bell()
            self.notice = "At least two visible documents with %s are needed." % (
                "peaks" if similarity["source"] == "peaks" else "data"
            )
            self.updateStatus()
            return

        items = [results.Item(d.spectrum, d.title or "untitled", d.path or "") for d in documents]
        results.unique_labels(items)

        self.onProcessing(True)
        self._outcome = None
        self.processing = threading.Thread(
            target=self.runCompare, args=(items, similarity, grouping)
        )
        self.processing.start()
        while self.processing.is_alive():
            # mwx.gauge.pulse() would disable this window too, and Stop with it
            self.gauge.Pulse()
            try:
                wx.SafeYield(self, True)
            except Exception:
                pass
            time.sleep(0.05)
        self.onProcessing(False)

        outcome = self._outcome or ("error", "nothing came back")
        if outcome[0] == "done":
            sim, grp = outcome[1], outcome[2]
            sim.labels = [item.label for item in items]
            self.setComparison(comparison(documents, items, sim, grp, similarity, grouping))
            self.notice = (
                "%d document(s) without %s left out." % (
                    skipped, "peaks" if similarity["source"] == "peaks" else "data"
                )
                if skipped else ""
            )
        elif outcome[0] == "stopped":
            self.notice = "Stopped."
        else:
            wx.Bell()
            self.notice = "The comparison failed: %s" % outcome[1]
        self.updateStatus()

    # ----

    def runCompare(self, items, similarity, grouping):
        """Worker thread: similarity and groups."""

        try:
            sim = mspy.similaritymatrix(
                [item.scan for item in items],
                stopper=mspy.CHECK_FORCE_QUIT,
                blocks=grouping["replicates"] > 0,  # only the bootstrap needs them
                **similarity,
            )
            grp = mspy.groupspectra(sim, stopper=mspy.CHECK_FORCE_QUIT, **grouping)
            self._outcome = ("done", sim, grp)
        except mspy.ForceQuit:
            self._outcome = ("stopped",)
        except ValueError as exc:
            self._outcome = ("error", str(exc))
        except Exception as exc:
            traceback.print_exc()
            self._outcome = ("error", repr(exc))

    # ----

    def onProcessing(self, status=True):
        """Show the gauge while comparing; every other window is blocked, and
        here everything but Stop."""

        self.gauge.SetValue(0)
        if status:
            # skip this window: a plain WindowDisabler would disable Stop too
            self._disabler = wx.WindowDisabler(self)
            self.mainSizer.Show(3)
        else:
            self._disabler = None
            self.mainSizer.Hide(3)
            self.processing = None
            mspy.start()
        for part in (self.toolbar, self.book, self.bottombar):
            part.Enable(not status)
        self.Layout()

    # ----

    def onStop(self, evt):
        """Cancel the comparison."""

        if self.processing and self.processing.is_alive():
            mspy.stop()
        else:
            wx.Bell()

    # ----

    def onSettings(self, evt):
        """Edit the analysis settings."""

        if self.processing is not None:
            return
        dlg = dlgSimilaritySettings(self)
        changed = dlg.ShowModal() == wx.ID_OK
        dlg.Destroy()
        if changed and self.current is not None:
            self.notice = "Settings changed: Compare again to apply them."
            self.updateStatus()

    # RESULTS
    # -------

    def setComparison(self, data):
        self.current = data
        self.matrixCanvas.setData(data)
        self.treeCanvas.setData(data)
        self.updateGroupsList()
        self.updateButtons()

    # ----

    def emptyText(self):
        n = len(self.candidates())
        if n < 2:
            return "Show at least two documents to compare them."
        return "Compare groups the %d visible documents by similarity." % n

    # ----

    def summary(self):
        """One line about the comparison on show."""

        data = self.current
        if data is None:
            return ""
        grp = data.grp
        multi = len(data.multiGroups())
        parts = [
            "%d spectra" % len(data.documents),
            "%d group%s, %d not grouped" % (multi, "" if multi == 1 else "s", len(data.singles())),
        ]
        if grp.stability is not None:
            parts.append("stability %.2f" % grp.stability)
        if not data.sim.comparable.all():
            parts.append("polarities grouped apart")
        rho, rhoApart = mspy.rangedependence(data.sim)
        if numpy.isfinite(rhoApart) and rhoApart < RANGE_WARNING:
            parts.append(
                "similarity falls with m/z range (ρ %.2f): check the calibration" % rhoApart
            )
        elif numpy.isfinite(rho):
            parts.append("range dependence ρ %.2f" % rho)
        return " · ".join(parts)

    # ----

    def updateStatus(self, text=None):
        if text is None:
            parts = [p for p in (self.summary(), self.notice) if p]
            if self.current is not None and self.current.stale:
                parts.append("A compared spectrum changed: Compare again.")
            if (
                self.current is not None
                and self.savedVisibility is None
                and {id(d) for d in self.candidates()} != {id(d) for d in self.current.documents}
            ):
                parts.append("The visible documents changed: Compare again to include them.")
            text = " · ".join(parts)
            if self.current is None:
                self.matrixCanvas.Refresh()
                self.treeCanvas.Refresh()
        self.status_label.SetLabel(text)
        self.status_label.SetToolTip(text or "")

    # ----

    def hover(self, text):
        """A canvas shows text for what is under the cursor (None: nothing)."""

        self.updateStatus(text)

    # ----

    def pairText(self, i, j):
        data = self.current
        if data is None:
            return None
        a, b = data.labels[i], data.labels[j]
        if i == j:
            return self.spectrumText(i)
        S = data.sim.similarity[i, j]
        if not numpy.isfinite(S):
            pi, pj = data.items[i].scan.polarity, data.items[j].scan.polarity
            different = (
                not data.similarity.get("neutralMass")
                and pi is not None and pj is not None and (pi > 0) != (pj > 0)
            )
            reason = "different polarity" if different else "no m/z range in common"
            return "%s × %s: not compared (%s)" % (a, b, reason)
        text = "%s × %s: similarity %.2f (cosine %.2f, chance %.2f)" % (
            a, b, S, data.sim.cosine[i, j], data.sim.chance[i, j]
        )
        if data.grp.coMembership is not None:
            text += " · together in %.0f%%" % (100 * data.grp.coMembership[i, j])
        return text

    # ----

    def spectrumText(self, i):
        data = self.current
        if data is None:
            return None
        scan = data.items[i].scan
        text = "%s: group %d" % (data.labels[i], data.grp.groups[i])
        if scan.precursorMZ:
            text += ", precursor %.2f" % scan.precursorMZ
        near = results.nearest(data.sim, i)
        if near is not None:
            text += ", nearest %s (%.2f)" % (data.labels[near], data.sim.similarity[i, near])
        return text

    # ----

    def groupHoverText(self, number):
        data = self.current
        if data is None:
            return None
        members = [i for i in range(len(data.labels)) if data.grp.groups[i] == number]
        mean, share, _ = results.group_summary(data.sim, data.grp, members)
        text = "Group %d: %d spectra, mean similarity %.2f" % (number, len(members), mean)
        if share is not None:
            text += ", together in %.0f%% of replicates" % (100 * share)
        return text + " · click to show them"

    # ----

    def cladeText(self, members, similarity, support):
        text = "%d spectra joined at similarity %.2f" % (len(members), similarity)
        if support is not None:
            text += ", in %.0f%% of the bootstrap trees" % (100 * support)
        return text + " · click to show them"

    # GROUPS VIEW
    # -----------

    def updateGroupsList(self):
        self.groupsList.DeleteAllItems()
        self.groupDetails.SetValue("")
        self._listGroups = []
        data = self.current
        if data is None:
            return
        for c, members in data.multiGroups():
            mean, share, weakest = results.group_summary(data.sim, data.grp, members)
            row = self.groupsList.InsertItem(self.groupsList.GetItemCount(), str(c))
            self.groupsList.SetItem(row, 1, str(len(members)))
            self.groupsList.SetItem(row, 2, "%.2f" % mean if numpy.isfinite(mean) else "")
            self.groupsList.SetItem(row, 3, "%.0f%%" % (100 * share) if share is not None else "")
            self.groupsList.SetItem(row, 4, "%.0f%%" % (100 * weakest) if weakest is not None else "")
            self._listGroups.append((c, members))
        singles = data.singles()
        if singles:
            row = self.groupsList.InsertItem(self.groupsList.GetItemCount(), "none")
            self.groupsList.SetItem(row, 1, str(len(singles)))
            self._listGroups.append((None, singles))
        if self._listGroups:
            self.groupsList.Select(0)

    # ----

    def selectedGroup(self):
        row = self.groupsList.GetFirstSelected()
        if row < 0 or row >= len(getattr(self, "_listGroups", [])):
            return None
        return self._listGroups[row]

    # ----

    def onGroupSelected(self, evt):
        group = self.selectedGroup()
        self.updateButtons()
        if group is None or self.current is None:
            return
        self.groupDetails.SetValue(self.groupText(*group))

    # ----

    def groupText(self, number, members):
        """Members and shared signals of a group, as text."""

        data = self.current
        assert data is not None
        lines = []
        if number is None:
            lines.append("Not grouped: %d spectra" % len(members))
            lines.append("")
            for i in members:
                near = results.nearest(data.sim, i)
                nearText = (
                    "  nearest %s (%.2f)" % (data.labels[near], data.sim.similarity[i, near])
                    if near is not None else ""
                )
                lines.append("  %s%s" % (data.labels[i], nearText))
            return "\n".join(lines)

        mean, share, weakest = results.group_summary(data.sim, data.grp, members)
        head = "Group %d: %d spectra, mean similarity %.2f" % (number, len(members), mean)
        if share is not None and weakest is not None:
            head += "\nTogether in %.0f%% of the bootstrap replicates (weakest pair %.0f%%)" % (
                100 * share, 100 * weakest
            )
        lines += [head, ""]
        for i in members:
            mine = results.together(data.grp, i)
            extra = "  together %.0f%%" % (100 * mine) if mine is not None else ""
            lines.append("  %s%s" % (data.labels[i], extra))

        feats = data.features(members)
        for axis, title in (("mz", "Shared m/z"), ("loss", "Shared losses (Da)")):
            if not feats[axis]:
                continue
            lines += ["", "%s  (members with signal; others with signal)" % title]
            for f in feats[axis]:
                others = "" if f["others"] is None else "%d/%d" % (f["others"], f["othersCovered"])
                note = "  = m/z %.2f" % f["mirror"] if f.get("mirror") is not None else ""
                lines.append(
                    "  %-28s %5s  %7s%s" % (
                        results.feature_text(f), "%d/%d" % (f["members"], f["covered"]), others, note
                    )
                )
        return "\n".join(lines)

    # SHOWING DOCUMENTS
    # -----------------

    def showSpectra(self, indices):
        """Show only these spectra (indices into the comparison) in the main window."""

        if self.current is None or self.processing is not None:
            return
        documents = [self.current.documents[i] for i in sorted(indices)]
        previous = self.parent.showDocumentsOnly(documents)
        if self.savedVisibility is None:
            self.savedVisibility = previous
        self.updateButtons()
        self.updateStatus()

    # ----

    def showGroup(self, number):
        """Show a group's documents and select it in the groups view."""

        for row, (c, members) in enumerate(getattr(self, "_listGroups", [])):
            if c == number:
                self.groupsList.Select(row)
                self.groupsList.Focus(row)
                self.showSpectra(set(members))
                return

    # ----

    def onShowGroup(self, evt=None):
        group = self.selectedGroup()
        if group is None:
            wx.Bell()
            return
        self.showSpectra(set(group[1]))

    # ----

    def onRestore(self, evt=None):
        if self.savedVisibility is None or self.processing is not None:
            wx.Bell()
            return
        saved = self.savedVisibility
        self.savedVisibility = None
        self.parent.restoreDocumentsVisibility(saved)
        self.updateButtons()
        self.updateStatus()

    # ----

    def selectView(self, view):
        if view not in self.VIEWS:
            view = "matrix"
        self.book.SetSelection(self.VIEWS.index(view))
        self.view_radios[view].SetValue(True)
        config.spectrumSimilarity["view"] = view
        self.updateButtons()

    # ----

    def updateButtons(self):
        if not hasattr(self, "restore_butt"):
            return
        self.restore_butt.Enable(self.savedVisibility is not None)
        self.showGroup_butt.Enable(
            self.current is not None
            and self.book.GetSelection() == self.VIEWS.index("groups")
            and self.selectedGroup() is not None
        )
        self.export_butt.Enable(self.current is not None and not self.current.stale)

    # EXPORT
    # ------

    def onExport(self, evt):
        """Write the tables, trees and report into a folder."""

        data = self.current
        if data is None or data.stale or self.processing is not None:
            wx.Bell()
            return

        first = data.documents[0] if data.documents else None
        start = mwx.saveDialogDir(getattr(first, "path", ""), config.main["lastDir"])
        dlg = wx.DirDialog(self, "Export Similarity Results", start)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        folder = dlg.GetPath()
        dlg.Destroy()

        existing = results.outputs_in_the_way(folder)
        if existing:
            message = mwx.dlgMessage(
                self,
                title="Replace the results in this folder?",
                message="It already holds %s." % ", ".join(existing),
                buttons=[(wx.ID_CANCEL, "Cancel", 80, False, 15), (wx.ID_OK, "Replace", 80, True, 0)],
            )
            replace = message.ShowModal() == wx.ID_OK
            message.Destroy()
            if not replace:
                return

        try:
            results.write_results(
                folder, data.items, data.sim, data.grp, data.similarity, data.grouping,
                source="mMass Spectrum Similarity",
            )
        except OSError as exc:
            wx.Bell()
            self.notice = "Export failed: %s" % exc
            self.updateStatus()
            return
        config.main["lastDir"] = folder
        self.notice = "Exported to %s" % os.path.basename(folder.rstrip(os.sep))
        self.updateStatus()
