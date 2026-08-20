# -------------------------------------------------------------------------
#     Copyright (C) 2005-2013 Martin Strohalm <www.mmass.org>

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

# load libs
import os
import threading
import wx
import wx.grid

# load modules
from . import mwx
from . import images
from . import config
from . import alignment
from .dlg_export_alignment import dlgExportAlignment, separatorValue
from .mixins import MakeModalMixin
import mspy

# FLOATING PANEL WITH COMPARE PEAKLISTS TOOL
# ------------------------------------------


# proportional cell fill and the aligned table have to agree on how intense a
# peak is, or the widest bar in a group would not be the peak the export picks
_peak_intensity = alignment.peakIntensity


# no edge at all, i.e. a cell that is not part of a group outline
NO_BORDER = (False, False, False, False)

# thickness of the group outline, in pixels
BORDER_WIDTH = 2


def _drawGroupBorder(dc, rect, colour, edges):
    """Draw this cell's share of the outline around a group of matched peaks.

    The outline is assembled cell by cell: the top and bottom row of a group
    draw a horizontal edge across every column and the first and last column
    draw the sides, which together box the whole block in. wxGrid's cell rect
    already excludes the pixel the grid line goes in, so the edges can sit right
    on the rect without being painted over afterwards.

    The edges are filled bars rather than thick lines: a wide pen straddles the
    coordinate it is given (and does so differently per platform), which would
    push half of the outline outside the cell.
    """

    if colour is None or not any(edges):
        return

    top, bottom, left, right = edges
    width = min(BORDER_WIDTH, rect.height, rect.width)

    dc.SetBrush(wx.Brush(colour))
    dc.SetPen(wx.TRANSPARENT_PEN)

    if top:
        dc.DrawRectangle(rect.x, rect.y, rect.width, width)
    if bottom:
        dc.DrawRectangle(
            rect.x, rect.y + rect.height - width, rect.width, width
        )
    if left:
        dc.DrawRectangle(rect.x, rect.y, width, rect.height)
    if right:
        dc.DrawRectangle(
            rect.x + rect.width - width, rect.y, width, rect.height
        )


class _GroupBorderRenderer(wx.grid.GridCellStringRenderer):
    """Ordinary text cell that also draws its share of the group outline."""

    def __init__(self, borderColour=None, borderEdges=NO_BORDER):
        super().__init__()
        self._borderColour = borderColour
        self._borderEdges = borderEdges

    def Draw(self, grid, attr, dc, rect, row, col, isSelected):
        super().Draw(grid, attr, dc, rect, row, col, isSelected)
        _drawGroupBorder(dc, rect, self._borderColour, self._borderEdges)

    def Clone(self):
        return _GroupBorderRenderer(self._borderColour, self._borderEdges)


class _IntensityFillRenderer(wx.grid.GridCellRenderer):
    """Fill a grid cell from the bottom proportionally to intensity."""

    def __init__(
        self, colour, fraction, borderColour=None, borderEdges=NO_BORDER
    ):
        super().__init__()
        if isinstance(colour, (list, tuple)):
            colour = wx.Colour(*colour)
        self._colour = colour
        self._fraction = max(0.0, min(1.0, fraction))
        self._borderColour = borderColour
        self._borderEdges = borderEdges

    def Draw(self, grid, attr, dc, rect, row, col, isSelected):
        if isSelected:
            bgColour = grid.GetSelectionBackground()
        else:
            bgColour = grid.GetDefaultCellBackgroundColour()
        dc.SetBrush(wx.Brush(bgColour))
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.DrawRectangle(rect)

        filled = self._fraction > 0.0 and self._colour.IsOk()
        if filled:
            fillHeight = max(1, int(round(rect.height * self._fraction)))
            fillRect = wx.Rect(
                rect.x,
                rect.y + rect.height - fillHeight,
                rect.width,
                fillHeight,
            )
            dc.SetBrush(wx.Brush(self._colour))
            dc.DrawRectangle(fillRect)

        value = grid.GetCellValue(row, col)
        if value:
            # GetFont() is the window font, not the cell font, so the mark
            # would not follow SetDefaultCellFont
            dc.SetFont(
                attr.GetFont() if attr.HasFont() else grid.GetDefaultCellFont()
            )
            if isSelected:
                textColour = grid.GetSelectionForeground()
            else:
                # the label is centred, so it lands on the fill only once that
                # reaches halfway up; picking the colour from whatever is
                # actually behind it keeps it readable in dark mode too
                behind = self._colour if (filled and self._fraction >= 0.5) else bgColour
                textColour = mwx.readableOn(behind)
            dc.SetTextForeground(textColour)
            dc.DrawLabel(value, rect, wx.ALIGN_CENTER | wx.ALIGN_CENTER_VERTICAL)

        _drawGroupBorder(dc, rect, self._borderColour, self._borderEdges)

    def GetBestSize(self, grid, attr, dc, row, col):
        return wx.Size(20, grid.GetDefaultRowSize())

    def Clone(self):
        return _IntensityFillRenderer(
            self._colour, self._fraction, self._borderColour, self._borderEdges
        )


class panelComparePeaklists(wx.Frame, MakeModalMixin):
    """Compare peaklists tool."""

    # how long typing has to pause before the peaks are re-grouped
    COMPARE_DELAY = 500

    def __init__(self, parent):
        wx.Frame.__init__(
            self,
            parent,
            -1,
            "Compare Peak Lists",
            size=wx.Size(500, 400),
            style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT,
        )

        self.parent = parent

        self.processing = None

        self.currentDocuments = []
        self.currentPeaklist = []
        self.currentMatches = []

        self._maxSize = 0

        # debounced re-compare: the numeric fields re-group the peaks on their
        # own a moment after typing stops, so no Enter / extra click is needed
        self._lastCompareSnapshot = None
        self._guiReady = False
        self._compareTimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.onCompareTimer, self._compareTimer)

        # make gui items
        self.makeGUI()
        self._guiReady = True
        self.Bind(wx.EVT_CLOSE, self.onClose)

        # apply dark mode
        mwx.applyDarkMode(self)

    # ----

    def makeGUI(self):
        """Make panel gui."""

        # make toolbar
        toolbar = self.makeToolbar()

        # make panel
        mainPanel = self.makeMainPanel()
        gauge = self.makeGaugePanel()

        # pack element
        self.mainSizer = wx.BoxSizer(wx.VERTICAL)
        self.mainSizer.Add(toolbar, 0, wx.EXPAND, 0)
        self.mainSizer.Add(mainPanel, 1, wx.EXPAND, 0)
        self.mainSizer.Add(gauge, 0, wx.EXPAND, 0)

        # hide gauge
        self.mainSizer.Hide(2)

        # fit layout
        self.mainSizer.Fit(self)
        self.SetSizer(self.mainSizer)
        self.SetMinSize(self.GetSize())

    # ----

    def makeToolbar(self):
        """Make toolbar."""

        # init toolbar
        panel = mwx.bgrPanel(
            self,
            -1,
            images.lib["bgrToolbarNoBorder"],
            size=wx.Size(-1, mwx.TOOLBAR_HEIGHT),
        )

        # make elements
        compare_label = wx.StaticText(panel, -1, "Compare:")
        compare_label.SetFont(wx.SMALL_FONT)

        choices = ["Peak Lists", "Notations (measured)", "Notations (theoretical)"]
        self.compare_choice = wx.Choice(
            panel, -1, choices=choices, size=wx.Size(180, mwx.SMALL_CHOICE_HEIGHT)
        )
        mwx.fitChoice(self.compare_choice, min_width=180)
        self.compare_choice.Bind(wx.EVT_CHOICE, self.onUpdatePeaklist)
        self.compare_choice.Select(0)
        if config.comparePeaklists["compare"] == "measured":
            self.compare_choice.Select(1)
        elif config.comparePeaklists["compare"] == "theoretical":
            self.compare_choice.Select(2)

        tolerance_label = wx.StaticText(panel, -1, "Tolerance:")
        tolerance_label.SetFont(wx.SMALL_FONT)

        self.tolerance_value = wx.TextCtrl(
            panel,
            -1,
            str(config.comparePeaklists["tolerance"]),
            size=wx.Size(60, -1),
            style=wx.TE_PROCESS_ENTER,
            validator=mwx.validator("floatPos"),
        )
        self.tolerance_value.Bind(wx.EVT_TEXT_ENTER, self.onCompare)
        self.tolerance_value.Bind(wx.EVT_TEXT, self.onCompareValueTyped)

        self.unitsDa_radio = wx.RadioButton(panel, -1, "Da", style=wx.RB_GROUP)
        self.unitsDa_radio.SetFont(wx.SMALL_FONT)
        self.unitsDa_radio.SetValue(True)
        self.unitsDa_radio.Bind(wx.EVT_RADIOBUTTON, self.onCompare)

        self.unitsPpm_radio = wx.RadioButton(panel, -1, "ppm")
        self.unitsPpm_radio.SetFont(wx.SMALL_FONT)
        self.unitsPpm_radio.SetValue((config.comparePeaklists["units"] == "ppm"))
        self.unitsPpm_radio.Bind(wx.EVT_RADIOBUTTON, self.onCompare)

        self.ignoreCharge_check = wx.CheckBox(panel, -1, "Ignore charge")
        self.ignoreCharge_check.SetFont(wx.SMALL_FONT)
        self.ignoreCharge_check.SetValue(config.comparePeaklists["ignoreCharge"])
        self.ignoreCharge_check.Bind(wx.EVT_CHECKBOX, self.onCompare)

        self.ratioCheck_check = wx.CheckBox(panel, -1, "Int. ratio:")
        self.ratioCheck_check.SetFont(wx.SMALL_FONT)
        self.ratioCheck_check.SetValue(config.comparePeaklists["ratioCheck"])
        self.ratioCheck_check.Bind(wx.EVT_CHECKBOX, self.onRatioCheckChanged)

        self.ratioDirection_choice = wx.Choice(
            panel,
            -1,
            choices=["Above", "Below"],
            size=wx.Size(80, mwx.SMALL_CHOICE_HEIGHT),
        )
        mwx.fitChoice(self.ratioDirection_choice, min_width=80)
        self.ratioDirection_choice.Select(0)
        if config.comparePeaklists["ratioDirection"] == -1:
            self.ratioDirection_choice.Select(1)
        self.ratioDirection_choice.Bind(wx.EVT_CHOICE, self.onCompare)

        self.ratioThreshold_value = wx.TextCtrl(
            panel,
            -1,
            str(config.comparePeaklists["ratioThreshold"]),
            size=wx.Size(50, -1),
            style=wx.TE_PROCESS_ENTER,
            validator=mwx.validator("floatPos"),
        )
        self.ratioThreshold_value.Bind(wx.EVT_TEXT_ENTER, self.onCompare)
        self.ratioThreshold_value.Bind(wx.EVT_TEXT, self.onCompareValueTyped)

        self.consensus_butt = wx.Button(
            panel, -1, "Consensus", size=wx.Size(-1, mwx.SMALL_BUTTON_HEIGHT)
        )
        self.consensus_butt.Bind(wx.EVT_BUTTON, self.onConsensus)

        self.export_butt = wx.Button(
            panel, -1, "Export Table...", size=wx.Size(-1, mwx.SMALL_BUTTON_HEIGHT)
        )
        self.export_butt.Bind(wx.EVT_BUTTON, self.onExportAlignment)

        self.onRatioCheckChanged()

        # pack elements
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.AddSpacer(mwx.CONTROLBAR_LSPACE)
        sizer.Add(compare_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(self.compare_choice, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(20)
        sizer.Add(tolerance_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(self.tolerance_value, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(10)
        sizer.Add(self.unitsDa_radio, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(self.unitsPpm_radio, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(20)
        sizer.Add(self.ignoreCharge_check, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(20)
        sizer.Add(self.ratioCheck_check, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(
            self.ratioDirection_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10
        )
        sizer.Add(self.ratioThreshold_value, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddStretchSpacer()
        sizer.AddSpacer(20)
        sizer.Add(self.consensus_butt, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        sizer.Add(self.export_butt, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(mwx.CONTROLBAR_RSPACE)

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        mainSizer.Add(sizer, 1, wx.EXPAND)
        panel.SetSizer(mainSizer)
        mainSizer.Fit(panel)

        return panel

    # ----

    def makeMainPanel(self):
        """Make main panel."""

        panel = wx.Panel(self, -1)

        # make grids
        self.makePeaklistGrid(panel)
        self.makeMatchesGrid(panel)

        # pack main
        mainSizer = wx.BoxSizer(wx.HORIZONTAL)
        mainSizer.Add(self.peaklistGrid, 1, wx.EXPAND)
        mainSizer.AddSpacer(mwx.SASH_SIZE)
        mainSizer.Add(self.matchesGrid, 0, wx.EXPAND)

        # fit layout
        panel.SetSizer(mainSizer)

        return panel

    # ----

    def makePeaklistGrid(self, panel):
        """Make total peaklist grid."""

        self._groupBorderColour = self._themedGroupBorderColour()

        # make table
        self.peaklistGrid = wx.grid.Grid(
            panel, -1, size=wx.Size(225, 400), style=mwx.GRID_STYLE
        )
        self.peaklistGrid.CreateGrid(0, 0)
        self.peaklistGrid.SetSelectionMode(wx.grid.Grid.GridSelectRows)
        self.peaklistGrid.DisableDragColSize()
        self.peaklistGrid.DisableDragRowSize()
        rowHeight = mwx.gridRowHeight(self.peaklistGrid, wx.SMALL_FONT)
        self.peaklistGrid.SetColLabelSize(rowHeight)
        self.peaklistGrid.SetRowLabelSize(0)
        self.peaklistGrid.SetDefaultRowSize(rowHeight)
        self.peaklistGrid.AutoSizeColumns(True)
        self.peaklistGrid.SetLabelFont(wx.SMALL_FONT)
        self.peaklistGrid.SetDefaultCellFont(wx.SMALL_FONT)
        self.peaklistGrid.SetDefaultCellAlignment(wx.ALIGN_CENTER, wx.ALIGN_CENTER)
        mwx.applyGridTheme(self.peaklistGrid)

        self.peaklistGrid.Bind(
            wx.grid.EVT_GRID_SELECT_CELL, self.onPeaklistCellSelected
        )
        self.peaklistGrid.Bind(wx.EVT_KEY_DOWN, self.onPeaklistKey)

    # ----

    def makeMatchesGrid(self, panel):
        """Make matches grid."""

        # make table
        self.matchesGrid = wx.grid.Grid(
            panel, -1, size=wx.Size(225, 400), style=mwx.GRID_STYLE
        )
        self.matchesGrid.CreateGrid(0, 0)
        self.matchesGrid.DisableDragColSize()
        self.matchesGrid.DisableDragRowSize()
        rowHeight = mwx.gridRowHeight(self.matchesGrid, wx.SMALL_FONT)
        self.matchesGrid.SetColLabelSize(rowHeight)
        self.matchesGrid.SetRowLabelSize(0)
        self.matchesGrid.SetDefaultRowSize(rowHeight)
        self.matchesGrid.AutoSizeColumns(True)
        self.matchesGrid.SetLabelFont(wx.SMALL_FONT)
        self.matchesGrid.SetDefaultCellFont(wx.SMALL_FONT)
        self.matchesGrid.SetDefaultCellAlignment(wx.ALIGN_CENTER, wx.ALIGN_CENTER)
        mwx.applyGridTheme(self.matchesGrid)

        self.matchesGrid.Bind(wx.EVT_KEY_DOWN, self.onMatchesKey)

    # ----

    def _themedGroupBorderColour(self):
        """Colour of the outline drawn around a group of matched peaks.

        It has to stand clear of the grid lines AND stay visible on top of a
        document colour fill, so it is deliberately much stronger than the grid
        line colour in both themes.
        """

        if images.is_dark_mode():
            return wx.Colour(190, 190, 190)

        return wx.Colour(60, 60, 60)

    # ----

    def onThemeChanged(self):
        """Recolour the grids after a live light/dark switch.

        wxGrid paints its own cells, so a repaint alone leaves them in the old
        theme.  Both grids additionally need filling again rather than just
        recolouring: the peaklist grid bakes the group outline colour into its
        cell renderers, and both draw the documents' own colours, which the
        main frame has just inverted for the new theme.  Neither refill
        recomputes anything -- they redraw what is already there.
        """

        for grid in (self.peaklistGrid, self.matchesGrid):
            mwx.applyGridTheme(grid)

        self._groupBorderColour = self._themedGroupBorderColour()
        self.updatePeaklistGrid(recreate=False)
        self.updateMatchesGrid()

    # ----

    def makeGaugePanel(self):
        """Make processing gauge."""

        panel = wx.Panel(self, -1)

        # make elements
        self.gauge = mwx.gauge(panel, -1)

        stop_butt = mwx.makeBitmapButton(
            panel, -1, images.lib["stopper"], style=wx.BORDER_NONE
        )
        stop_butt.Bind(wx.EVT_BUTTON, self.onStop)

        # pack elements
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.gauge, 1, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(10)
        sizer.Add(stop_butt, 0, wx.ALIGN_CENTER_VERTICAL)

        # fit layout
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        if wx.Platform == "__WXMAC__":
            mainSizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.TOP, -1)
        mainSizer.Add(sizer, 1, wx.EXPAND | wx.ALL, mwx.GAUGE_SPACE)
        panel.SetSizer(mainSizer)
        mainSizer.Fit(panel)

        return panel

    # ----

    def onClose(self, evt):
        """Hide this frame."""

        # check processing
        if self.processing is not None:
            wx.Bell()
            return

        # close self
        self._compareTimer.Stop()
        self.Destroy()

    # ----

    def _compareSnapshot(self):
        """The settings that decide the grouping, used to spot real changes."""

        return (
            self.tolerance_value.GetValue().strip(),
            self.unitsPpm_radio.GetValue(),
            self.ignoreCharge_check.GetValue(),
            self.ratioCheck_check.GetValue(),
            self.ratioDirection_choice.GetStringSelection(),
            self.ratioThreshold_value.GetValue().strip(),
        )

    # ----

    def _compareValuesReady(self):
        """True when the typed numbers are usable for grouping.

        A half-typed value ("", "0", "0.") is not an instruction to group
        everything into one bucket, it is a value the user is still writing, so
        it is ignored and the current results are left alone until it makes
        sense again.
        """

        try:
            if float(self.tolerance_value.GetValue()) <= 0:
                return False
        except ValueError:
            return False

        if self.ratioCheck_check.GetValue():
            try:
                if float(self.ratioThreshold_value.GetValue()) <= 0:
                    return False
            except ValueError:
                return False

        return True

    # ----

    def _waitForProcessing(self, quiet=False):
        """Block until the worker thread is done.

        The visible path pulses the gauge, which yields to the event loop so the
        Stop button stays live. The quiet path has no gauge and no Stop button,
        so it just waits: keystrokes typed meanwhile queue up instead of being
        swallowed by the yield, and the caret does not move.
        """

        while self.processing and self.processing.is_alive():
            if quiet:
                self.processing.join(0.02)
            else:
                self.gauge.pulse()

    # ----

    def _grabFocusState(self):
        """Remember the caret in a numeric field before a refresh disables it.

        The refresh puts the whole frame behind a wx.WindowDisabler (see
        onProcessing / MakeModalMixin), which drops the keyboard focus, so a
        field the user is still typing in loses its caret. Only our own two
        numeric fields are tracked -- the grids look after their own focus.
        """

        focus = wx.Window.FindFocus()
        for ctrl in (self.tolerance_value, self.ratioThreshold_value):
            if focus is ctrl:
                break
        else:
            return None

        try:
            return (ctrl, ctrl.GetInsertionPoint(), ctrl.GetSelection())
        except RuntimeError:
            return None

    # ----

    def _restoreFocusState(self, state):
        """Put the caret back where _grabFocusState found it."""

        if state is None:
            return

        ctrl, insertion, selection = state

        def restore():
            try:
                ctrl.SetFocus()
                ctrl.SetInsertionPoint(insertion)
                if selection[0] != selection[1]:
                    ctrl.SetSelection(selection[0], selection[1])
            except RuntimeError:
                # the field went away with the frame
                pass

        # once now, and once more after the grid's own deferred scrolling has
        # run, so nothing that is still queued can take the focus back
        restore()
        wx.CallAfter(restore)

    # ----

    def onCompareValueTyped(self, evt=None):
        """A numeric field was typed in: (re)arm the debounced re-compare."""

        if evt is not None:
            evt.Skip()

        # the controls the check reads are not all built yet
        if not self._guiReady:
            return

        # nothing usable typed (yet) - keep the current results on screen
        if not self._compareValuesReady():
            self._compareTimer.Stop()
            return

        # restart the countdown, so it only fires once typing settles
        self._compareTimer.Start(self.COMPARE_DELAY, oneShot=wx.TIMER_ONE_SHOT)

    # ----

    def onCompareTimer(self, evt=None):
        """Typing has settled: re-group the peaks if anything actually changed."""

        if not self._compareValuesReady():
            return

        # a compare is already running - come back once it is done
        if self.processing:
            self._compareTimer.Start(self.COMPARE_DELAY, oneShot=wx.TIMER_ONE_SHOT)
            return

        if self._compareSnapshot() == self._lastCompareSnapshot:
            return

        # quiet: this was not asked for by a click, so it must not steal the
        # focus, the caret or the keystrokes still coming in
        self.onCompare(None, quiet=True)

    # ----

    def onProcessing(self, status=True, quiet=False):
        """Show processing gauge."""

        # A debounced auto-refresh runs quietly. The normal path puts the whole
        # frame behind a wx.WindowDisabler and pumps events through
        # wx.SafeYield(), which drops the focus and swallows keystrokes -- fine
        # for a button the user just pressed, not for a field they are still
        # typing in. It also resizes the frame to fit the gauge in and out.
        if quiet:
            if not status:
                self.processing = None
                mspy.start()
            return

        self.gauge.SetValue(0)

        if status:
            self.MakeModal(True)
            self.mainSizer.Show(2)
        else:
            self.MakeModal(False)
            self.mainSizer.Hide(2)
            self.processing = None
            mspy.start()

        # fit layout
        self.peaklistGrid.SetMinSize(self.peaklistGrid.GetSize())
        self.Layout()
        self.mainSizer.Fit(self)
        try:
            wx.GetApp().Yield()
        except Exception:
            pass
        try:
            self.peaklistGrid.SetMinSize(wx.Size(-1, -1))
        except RuntimeError:
            pass

    # ----

    def onStop(self, evt):
        """Cancel current processing."""

        if self.processing and self.processing.is_alive():
            mspy.stop()
        else:
            wx.Bell()

    # ----

    def onRatioCheckChanged(self, evt=None):
        """Disable ratio chacking options."""

        enabled = self.ratioCheck_check.IsChecked()
        self.ratioDirection_choice.Enable(enabled)
        self.ratioThreshold_value.Enable(enabled)
        if evt is not None:
            self.onCompare(evt)

    # ----

    def onConsensus(self, evt):
        """Create consensus peaklist."""

        # check processing
        if self.processing:
            return

        # check documents
        if not self.currentDocuments:
            wx.Bell()
            return

        # generate matched groups
        matched_groups = []
        for p in self.currentPeaklist:
            group_found = False
            for group in matched_groups:
                mz_avg = sum(x[0] for x in group) / len(group)
                error = mspy.delta(mz_avg, p[0], config.comparePeaklists["units"])
                if abs(error) <= config.comparePeaklists["tolerance"]:
                    group.append(p)
                    group_found = True
                    break
            if not group_found:
                matched_groups.append([p])

        # create new document
        from . import doc
        new_doc = doc.document()
        new_doc.title = "Consensus"
        new_doc.colour = self.parent.getFreeColour()

        new_peaks = []
        for group in matched_groups:
            mz_avg = sum(x[0] for x in group) / len(group)
            ai_avg = sum(x[3] for x in group) / len(group)
            p_obj = mspy.peak(mz=mz_avg, ai=ai_avg)
            new_peaks.append(p_obj)

        if new_doc.spectrum is None:
            wx.Bell()
            return

        new_doc.spectrum.peaklist = mspy.peaklist(new_peaks)
        self.parent.onDocumentNew(document=new_doc)

    # ----

    def _alignmentGroups(self):
        """Matched peaks as groups of (documentIndex, mz, peak).

        Built from the very spans that are outlined in the grid, so the table
        that leaves the tool holds the same groups the user was looking at when
        they asked for it.
        """

        groups = []

        for start, end in self._peakGroups():
            group = []
            for row in self.currentPeaklist[start : end + 1]:
                # row is [mz, documentIndex, charge, intensity, matches, peak, document]
                group.append((row[1], row[0], row[5]))
            groups.append(group)

        return groups

    # ----

    def onExportAlignment(self, evt):
        """Export the matched peaks as one aligned table."""

        # check processing
        if self.processing:
            return

        # check data
        if not self.currentDocuments or not self.currentPeaklist:
            wx.Bell()
            return

        groups = self._alignmentGroups()

        # get columns
        dlg = dlgExportAlignment(
            self, documents=len(self.currentDocuments), groups=len(groups)
        )
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        destination = dlg.destination
        dlg.Destroy()

        # make the table
        header, rows = alignment.buildAlignmentTable(
            groups,
            [getattr(document, "title", "") for document in self.currentDocuments],
            statColumns=config.comparePeaklists["alignmentStats"],
            peakColumns=config.comparePeaklists["alignmentColumns"],
            duplicates=config.comparePeaklists["alignmentDuplicates"],
        )

        separator = separatorValue(config.comparePeaklists["alignmentSeparator"])
        buff = alignment.formatTable(header, rows, separator=separator)

        if destination == "clipboard":
            obj = wx.TextDataObject()
            obj.SetText(buff.rstrip())
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(obj)
                wx.TheClipboard.Close()
            return

        self.saveAlignment(buff, separator)

    # ----

    def saveAlignment(self, buff, separator):
        """Ask for a path and write the aligned table there."""

        if separator == ",":
            fileName = "alignment.csv"
            fileType = "CSV file|*.csv"
        else:
            fileName = "alignment.txt"
            fileType = "ASCII file|*.txt"

        # default next to the first of the compared documents
        document = self.currentDocuments[0] if self.currentDocuments else None
        exportDir = mwx.saveDialogDir(
            getattr(document, "path", ""), config.main["lastDir"]
        )

        dlg = wx.FileDialog(
            self,
            "Export Alignment",
            exportDir,
            fileName,
            fileType,
            wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        path = dlg.GetPath()
        config.main["lastDir"] = os.path.split(path)[0]
        dlg.Destroy()

        try:
            with open(path, "wb") as f:
                f.write(buff.encode("utf-8"))
        except IOError:
            wx.Bell()

    # ----

    def onPeaklistCellSelected(self, evt):
        """Show more info for selected cell."""

        evt.Skip()

        if getattr(self, '_ignore_selection_events', False):
            return

        # check documents
        if not self.currentDocuments:
            return

        # get slection
        row = evt.GetRow()

        # get peak index
        pkIndex = row

        # highlight mass in plot
        self.parent.updateMassPoints([self.currentPeaklist[pkIndex][0]])

        # compare selected mass
        self.compareSelected(pkIndex)
        self.updateMatchesGrid()

    # ----

    def onPeaklistKey(self, evt):
        """Key pressed."""

        # get key
        key = evt.GetKeyCode()

        # copy
        if key == 67 and evt.CmdDown():
            self.copyPeaklist()

        # delete
        elif key == wx.WXK_DELETE or (key == wx.WXK_BACK and evt.CmdDown()):
            self.onDeleteSelected()

        # other keys
        else:
            evt.Skip()

    # ----

    def onDeleteSelected(self):
        """Delete selected peaks."""

        if not self.currentPeaklist:
            return

        selectedRows = self._getSelectedPeaklistRows()
        selectedRows = [
            row for row in selectedRows if 0 <= row < len(self.currentPeaklist)
        ]
        if not selectedRows:
            return

        changedDocIndexes = []

        if config.comparePeaklists["compare"] == "peaklists":
            indexesByDoc = {}
            documentsByDoc = {}

            for row in selectedRows:
                p_info = self.currentPeaklist[row]
                item = p_info[5]
                document = p_info[6]

                # NOTE: p_info[1] indexes self.currentDocuments (visible documents
                # only), which is NOT the index the main frame uses. Everything
                # reported back to the parent must use the parent's own index.
                docIndex = self._parentDocIndex(document)
                if docIndex is None:
                    continue
                documentsByDoc[docIndex] = document

                peaks = document.spectrum.peaklist.peaks
                idx = self._indexOf(peaks, item)
                if idx is not None:
                    indexesByDoc.setdefault(docIndex, set()).add(idx)

            for docIndex in sorted(indexesByDoc):
                document = documentsByDoc[docIndex]
                indexes = sorted(indexesByDoc[docIndex])
                if not indexes:
                    continue

                document.backup(("spectrum"))
                peaklist = document.spectrum.peaklist
                deletedMzs = [peaklist[i].mz for i in indexes]
                peaklist.delete(indexes)

                if self.parent.peaklistPanel and deletedMzs:
                    self.parent.peaklistPanel._recalculateNeighborhoodEnvelopes(
                        deletedMzs, document=document
                    )

                changedDocIndexes.append(docIndex)

        elif config.comparePeaklists["compare"] in ("measured", "theoretical"):
            indexesByDoc = {}
            documentsByDoc = {}

            for row in selectedRows:
                p_info = self.currentPeaklist[row]
                item = p_info[5]
                document = p_info[6]

                docIndex = self._parentDocIndex(document)
                if docIndex is None:
                    continue
                documentsByDoc[docIndex] = document

                idx = self._indexOf(document.annotations, item)
                if idx is not None:
                    indexesByDoc.setdefault(docIndex, set()).add(idx)

            for docIndex in sorted(indexesByDoc):
                document = documentsByDoc[docIndex]
                indexes = sorted(indexesByDoc[docIndex], reverse=True)
                if not indexes:
                    continue

                document.backup(("annotations"))
                for idx in indexes:
                    del document.annotations[idx]

                changedDocIndexes.append(docIndex)

        if changedDocIndexes:
            if config.comparePeaklists["compare"] == "peaklists":
                items = ("spectrum",)
            else:
                items = ("annotations",)

            # the deleted peak may still be highlighted in the canvas (this grid
            # highlights the selected mass); drop the marks so no arrow is left
            # pointing at a peak that no longer exists
            self.parent.updateMassPoints(None)

            # refresh this grid first, so the row that was just deleted cannot be
            # re-selected / re-used while the parent update is still pending
            self.onUpdatePeaklist()

            wx.CallAfter(
                self.parent.onDocumentChangedMulti,
                indexes=changedDocIndexes,
                items=items,
            )

    # ----

    def _parentDocIndex(self, document):
        """Translate a document object into the parent's document index.

        self.currentDocuments holds only the VISIBLE documents, so its indexes
        do not match the parent's self.documents whenever a document is hidden.
        Anything handed back to the parent (onDocumentChangedMulti) must use the
        parent's index or the wrong spectrum gets refreshed / marked dirty.
        """

        documents = getattr(self.parent, "documents", None)
        if not documents:
            return None

        for i, doc_ in enumerate(documents):
            if doc_ is document:
                return i

        return None

    # ----

    @staticmethod
    def _indexOf(sequence, item):
        """Index of item within sequence, matched by identity.

        Peaks/annotations can compare equal without being the same object, so
        list.index() may return a neighbouring item's position and delete the
        wrong one.
        """

        for i, current in enumerate(sequence):
            if current is item:
                return i

        return None

    # ----

    def _getSelectedPeaklistRows(self):
        """Return unique selected rows from grid row selections, blocks, or cursor."""

        rows = set()

        try:
            rows.update(self.peaklistGrid.GetSelectedRows())
        except Exception:
            pass

        try:
            topLeft = self.peaklistGrid.GetSelectionBlockTopLeft()
            bottomRight = self.peaklistGrid.GetSelectionBlockBottomRight()
            for i in range(min(len(topLeft), len(bottomRight))):
                topRow = topLeft[i][0]
                bottomRow = bottomRight[i][0]
                for row in range(topRow, bottomRow + 1):
                    rows.add(row)
        except Exception:
            pass

        if not rows:
            try:
                row = self.peaklistGrid.GetGridCursorRow()
                if row >= 0:
                    rows.add(row)
            except Exception:
                pass

        return sorted(rows)

    # ----

    def onMatchesKey(self, evt):
        """Key pressed."""

        # get key
        key = evt.GetKeyCode()

        # copy
        if key == 67 and evt.CmdDown():
            self.copyMatches()

        # other keys
        else:
            evt.Skip()

    # ----

    def onCompare(self, evt, quiet=False):
        """Compare data."""

        # a compare is happening now, so any pending debounced one is moot
        self._compareTimer.Stop()

        # check processing
        if self.processing:
            return

        # keep the caret in the field being typed in across the refresh
        focusState = self._grabFocusState()

        # check documents
        if not self.currentDocuments:
            wx.Bell()
            return

        # get params
        if not self.getParams():
            wx.Bell()
            return

        # save state
        try:
            scroll_x, scroll_y = self.peaklistGrid.GetViewStart()
            sel_row = self.peaklistGrid.GetGridCursorRow()
        except Exception:
            scroll_x, scroll_y = 0, 0
            sel_row = -1

        # show processing gauge
        self.onProcessing(True, quiet=quiet)
        self.consensus_butt.Enable(False)
        self.export_butt.Enable(False)

        # do processing to get peaklists
        self.processing = threading.Thread(target=self.runGetPeaklists)
        self.processing.start()

        # pulse gauge while working
        self._waitForProcessing(quiet)

        # AUTO COMPARE if possible
        if self.currentDocuments and self.currentPeaklist and self.getParams():
            self.processing = threading.Thread(target=self.runCompare)
            self.processing.start()
            self._waitForProcessing(quiet)

        self._ignore_selection_events = True
        # update gui with recreate=True
        self.updatePeaklistGrid()
        self.updateMatchesGrid()

        # restore state
        if sel_row >= 0 and self.currentPeaklist:
            # We want to stay at the same index effectively, but ensure we don't exceed boundaries.
            best_row = min(sel_row, len(self.currentPeaklist) - 1)
            if best_row < self.peaklistGrid.GetNumberRows():
                self.peaklistGrid.SetGridCursor(best_row, 0)
                self.peaklistGrid.SelectRow(best_row)
                # DO NOT update parent mass points here to avoid view jump!
            wx.CallAfter(self.peaklistGrid.Scroll, scroll_x, scroll_y)

        wx.CallAfter(lambda: setattr(self, '_ignore_selection_events', False))


        # remember what these results were computed from, so the debounced
        # re-compare can skip a change that is not really a change
        self._lastCompareSnapshot = self._compareSnapshot()

        # hide processing gauge
        self.onProcessing(False, quiet=quiet)
        self.consensus_butt.Enable(True)
        self.export_butt.Enable(True)

        # give the caret back to the field being typed in
        self._restoreFocusState(focusState)

    # ----

    def onUpdatePeaklist(self, evt=None):
        """Get relevant peaks lists."""

        # check processing
        if self.processing:
            return

        # get peak list type
        value = self.compare_choice.GetStringSelection()
        if value == "Notations (measured)":
            config.comparePeaklists["compare"] = "measured"
        elif value == "Notations (theoretical)":
            config.comparePeaklists["compare"] = "theoretical"
        else:
            config.comparePeaklists["compare"] = "peaklists"

        # check documents
        if not self.currentDocuments:
            wx.Bell()
            return

        # save state
        try:
            scroll_x, scroll_y = self.peaklistGrid.GetViewStart()
            sel_row = self.peaklistGrid.GetGridCursorRow()
        except Exception:
            scroll_x, scroll_y = 0, 0
            sel_row = -1

        # show processing gauge
        self.onProcessing(True)
        self.consensus_butt.Enable(False)
        self.export_butt.Enable(False)

        # do processing to get peaklists
        self.processing = threading.Thread(target=self.runGetPeaklists)
        self.processing.start()

        # pulse gauge while working
        while self.processing and self.processing.is_alive():
            self.gauge.pulse()

        # AUTO COMPARE if possible
        if self.currentDocuments and self.currentPeaklist and self.getParams():
            self.processing = threading.Thread(target=self.runCompare)
            self.processing.start()
            while self.processing and self.processing.is_alive():
                self.gauge.pulse()

        self._ignore_selection_events = True
        # update gui with recreate=True
        self.updatePeaklistGrid()
        self.updateMatchesGrid()

        # restore state
        if sel_row >= 0 and self.currentPeaklist:
            # We want to stay at the same index effectively, but ensure we don't exceed boundaries.
            best_row = min(sel_row, len(self.currentPeaklist) - 1)
            if best_row < self.peaklistGrid.GetNumberRows():
                self.peaklistGrid.SetGridCursor(best_row, 0)
                self.peaklistGrid.SelectRow(best_row)
                # DO NOT update parent mass points here to avoid view jump!
            wx.CallAfter(self.peaklistGrid.Scroll, scroll_x, scroll_y)

        wx.CallAfter(lambda: setattr(self, '_ignore_selection_events', False))


        # remember what these results were computed from, so the debounced
        # re-compare can skip a change that is not really a change
        self._lastCompareSnapshot = self._compareSnapshot()

        # hide processing gauge
        self.onProcessing(False)
        self.consensus_butt.Enable(True)
        self.export_butt.Enable(True)

    # ----

    def setData(self, documents):
        """Set data."""

        # DO NOT clear currentPeaklist yet, because onUpdatePeaklist needs it to save the scroll/selection state.
        self.currentDocuments = []
        self.currentMatches = []

        # get visible documents only
        for document in documents:
            if document.visible:
                self.currentDocuments.append(document)

        # update peak lists
        self.onUpdatePeaklist()

    # ----

    def getParams(self):
        """Get all params from dialog."""

        # try to get values
        try:

            config.comparePeaklists["tolerance"] = float(
                self.tolerance_value.GetValue()
            )

            config.comparePeaklists["units"] = "ppm"
            if self.unitsDa_radio.GetValue():
                config.comparePeaklists["units"] = "Da"

            config.comparePeaklists["ignoreCharge"] = 0
            if self.ignoreCharge_check.GetValue():
                config.comparePeaklists["ignoreCharge"] = 1

            config.comparePeaklists["ratioCheck"] = 0
            if self.ratioCheck_check.GetValue():
                config.comparePeaklists["ratioCheck"] = 1

            config.comparePeaklists["ratioDirection"] = -1
            if self.ratioDirection_choice.GetStringSelection() == "Above":
                config.comparePeaklists["ratioDirection"] = 1

            if self.ratioCheck_check.GetValue():
                config.comparePeaklists["ratioThreshold"] = float(
                    self.ratioThreshold_value.GetValue()
                )

            return True

        except Exception:
            wx.Bell()
            return False

    # ----

    def updatePeaklistGrid(self, recreate=True):
        """Update current total peaklist grid."""

        # make new grid
        if recreate or not self.currentPeaklist:

            # erase grid
            if self.peaklistGrid.GetNumberRows():
                self.peaklistGrid.DeleteRows(0, self.peaklistGrid.GetNumberRows())
            if self.peaklistGrid.GetNumberCols():
                self.peaklistGrid.DeleteCols(0, self.peaklistGrid.GetNumberCols())

            # check peaklist
            if not self.currentPeaklist:
                return

            # make new grid
            count = len(self.currentDocuments)
            self.peaklistGrid.AppendCols(count + 1)
            self.peaklistGrid.AppendRows(len(self.currentPeaklist))
            self.peaklistGrid.SetColLabelValue(0, "m/z")
            cellAttr = wx.grid.GridCellAttr()
            cellAttr.SetReadOnly(True)
            for x in range(count + 1):
                self.peaklistGrid.SetColAttr(x, cellAttr.Clone())
            for x in range(1, count + 1):
                self.peaklistGrid.SetColLabelValue(x, "*")
                self.peaklistGrid.SetColSize(x, 20)

        # set formats
        mzFormat = "%0." + repr(config.main["mzDigits"]) + "f"

        # work out which rows hold the same peak, so the block can be boxed in
        count = len(self.currentDocuments)
        lastCol = count
        groupEdges = {}
        for first, last in self._peakGroups():
            for row in range(first, last + 1):
                groupEdges[row] = (row == first, row == last)

        def borderEdges(row, col):
            """Which edges of the group outline this cell has to draw."""

            if row not in groupEdges:
                return NO_BORDER
            top, bottom = groupEdges[row]
            return (top, bottom, col == 0, col == lastCol)

        # add data
        for i, item in enumerate(self.currentPeaklist):

            # add mz
            mz = mzFormat % item[0]
            self.peaklistGrid.SetCellValue(i, 0, mz)
            self.peaklistGrid.SetCellRenderer(
                i,
                0,
                _GroupBorderRenderer(self._groupBorderColour, borderEdges(i, 0)),
            )

            # add matches
            rowMax = max((v for v in item[4] if v is not None), default=0.0)
            for x in range(count):
                intensity = item[4][x]
                if intensity is not None:
                    fraction = float(intensity) / rowMax if rowMax > 0 else 1.0
                    fillColour = self.currentDocuments[x].colour
                else:
                    fraction = 0.0
                    fillColour = wx.NullColour

                self.peaklistGrid.SetCellRenderer(
                    i,
                    x + 1,
                    _IntensityFillRenderer(
                        fillColour,
                        fraction,
                        self._groupBorderColour,
                        borderEdges(i, x + 1),
                    ),
                )

                if x == item[1]:
                    self.peaklistGrid.SetCellValue(i, x + 1, "*")
                    self.peaklistGrid.SetCellAlignment(
                        i, x + 1, wx.ALIGN_CENTER, wx.ALIGN_CENTER
                    )

        # AutoSize fits the text exactly, which would leave the centred values
        # touching the group outline, so give the text column some air
        self.peaklistGrid.AutoSizeColumns(True)
        self.peaklistGrid.SetColSize(
            0, self.peaklistGrid.GetColSize(0) + 2 * mwx.GRID_CELL_PADDING
        )

    # ----

    def updateMatchesGrid(self):
        """Update current matches."""

        # erase grid
        if self.matchesGrid.GetNumberRows():
            self.matchesGrid.DeleteRows(0, self.matchesGrid.GetNumberRows())
        if self.matchesGrid.GetNumberCols():
            self.matchesGrid.DeleteCols(0, self.matchesGrid.GetNumberCols())

        # check matches
        if not self.currentMatches:
            return

        # make grid
        self.matchesGrid.AppendCols(5)
        self.matchesGrid.AppendRows(len(self.currentMatches))
        self.matchesGrid.SetColLabelValue(0, "*")
        self.matchesGrid.SetColLabelValue(1, "m/z")
        self.matchesGrid.SetColLabelValue(2, "error")
        self.matchesGrid.SetColLabelValue(3, "a/b")
        self.matchesGrid.SetColLabelValue(4, "b/a")
        cellAttr = wx.grid.GridCellAttr()
        cellAttr.SetReadOnly(True)
        for x in range(5):
            self.matchesGrid.SetColAttr(x, cellAttr.Clone())
        self.matchesGrid.SetColSize(0, 20)

        # set formats
        mzFormat = "%0." + repr(config.main["mzDigits"]) + "f"
        errFormat = "%0." + repr(config.main["mzDigits"]) + "f"
        if config.comparePeaklists["units"] == "ppm":
            errFormat = "%0." + repr(config.main["ppmDigits"]) + "f"

        # add data
        for i, match in enumerate(self.currentMatches):
            mz = mzFormat % match[1]
            error = errFormat % match[2]
            ratio1 = "%0.2f" % match[3]
            ratio2 = "%0.2f" % match[4]

            self.matchesGrid.SetCellValue(i, 1, mz)
            self.matchesGrid.SetCellValue(i, 2, error)
            self.matchesGrid.SetCellValue(i, 3, ratio1)
            self.matchesGrid.SetCellValue(i, 4, ratio2)
            self.matchesGrid.SetCellBackgroundColour(
                i, 0, self.currentDocuments[match[0]].colour
            )
            if match[5]:
                self.matchesGrid.SetCellAlignment(
                    i, 0, wx.ALIGN_CENTER, wx.ALIGN_CENTER
                )
                self.matchesGrid.SetCellValue(i, 0, "*")

        # same as above: centred text needs a margin AutoSize does not give it
        self.matchesGrid.AutoSizeColumns(True)
        for x in range(1, 5):
            self.matchesGrid.SetColSize(
                x, self.matchesGrid.GetColSize(x) + 2 * mwx.GRID_CELL_PADDING
            )

    # ----

    def runGetPeaklists(self):
        """Filter peaklists according to specified type."""

        # empty current data
        self.currentPeaklist = []
        self.currentMatches = []
        self._maxSize = 0

        # run task
        try:

            # get peaklist
            count = len(self.currentDocuments)
            for x, document in enumerate(self.currentDocuments):
                size = 0

                # use measured notations
                if config.comparePeaklists["compare"] == "measured":
                    items = []
                    for item in document.annotations:
                        items.append(item)
                    for sequence in document.sequences:
                        for item in sequence.matches:
                            items.append(item)
                    for item in items:
                        # [mz, docIndex, z, intensity, [matches]]
                        self.currentPeaklist.append(
                            [
                                round(item.mz, 6),
                                x,
                                item.charge,
                                item.ai - item.base,
                                count * [None],
                                item,
                                document,
                            ]
                        )
                        self.currentPeaklist[-1][4][x] = _peak_intensity(item)
                        size += 1

                # use theoretical notations
                elif config.comparePeaklists["compare"] == "theoretical":
                    items = []
                    for item in document.annotations:
                        if item.theoretical is not None:
                            items.append(item)
                    for sequence in document.sequences:
                        for item in sequence.matches:
                            if item.theoretical is not None:
                                items.append(item)
                    for item in items:
                        self.currentPeaklist.append(
                            [
                                round(item.theoretical, 6),
                                x,
                                item.charge,
                                item.ai - item.base,
                                count * [None],
                                item,
                                document,
                            ]
                        )
                        self.currentPeaklist[-1][4][x] = _peak_intensity(item)
                        size += 1

                # use peaklists
                else:
                    for item in document.spectrum.peaklist:
                        self.currentPeaklist.append(
                            [
                                round(item.mz, 6),
                                x,
                                item.charge,
                                item.ai - item.base,
                                count * [None],
                                item,
                                document,
                            ]
                        )
                        self.currentPeaklist[-1][4][x] = _peak_intensity(item)
                        size += 1

                # remember max peaklist size
                self._maxSize = max(size, self._maxSize)

            # sort peaklist by mz
            self.currentPeaklist.sort(key=lambda x: x[0])

        # task canceled
        except mspy.ForceQuit:
            self.currentPeaklist = []
            self._maxSize = 0
            return

    # ----

    def runCompare(self):
        """Compare all peaklists."""

        self.currentMatches = []

        # run task
        try:

            # erase previous matches
            count = len(self.currentDocuments)
            for _i, item in enumerate(self.currentPeaklist):
                item[4] = count * [None]
                item[4][item[1]] = _peak_intensity(item[5])

            # compare peaklists
            count = len(self.currentPeaklist)
            for i in range(count):
                for j in range(i, count):
                    p1 = self.currentPeaklist[i]
                    p2 = self.currentPeaklist[j]

                    # the list is sorted by m/z, so once p2 is further than the
                    # tolerance above p1 nothing after it can match either
                    error = mspy.delta(p1[0], p2[0], config.comparePeaklists["units"])
                    if (
                        abs(error) > config.comparePeaklists["tolerance"]
                        and error < 0
                    ):
                        break

                    # save matched
                    if self._peaksMatch(p1, p2):
                        p1[4][p2[1]] = _peak_intensity(p2[5])
                        p2[4][p1[1]] = _peak_intensity(p1[5])

        # task canceled
        except mspy.ForceQuit:
            return


    # ----

    def _peaksMatch(self, p1, p2):
        """Whether two peaks count as the same peak under the current settings.

        Kept in one place so the outline drawn around a group in the grid can
        never disagree with the matches the comparison itself found.
        """

        # check charge
        if (
            not config.comparePeaklists["ignoreCharge"]
            and (p1[2] != p2[2])
            and (p1[2] is not None and p2[2] is not None)
        ):
            return False

        # check error
        error = mspy.delta(p1[0], p2[0], config.comparePeaklists["units"])
        if abs(error) > config.comparePeaklists["tolerance"]:
            return False

        # check ratio
        if config.comparePeaklists["ratioCheck"] and p1[3] and p2[3]:

            ratio = p1[3] / p2[3]
            if (
                config.comparePeaklists["ratioThreshold"] > 1
                and ratio < 1
                or config.comparePeaklists["ratioThreshold"] < 1
                and ratio > 1
            ):
                ratio = 1.0 / ratio

            if (
                config.comparePeaklists["ratioDirection"] == 1
                and ratio < config.comparePeaklists["ratioThreshold"]
            ) or (
                config.comparePeaklists["ratioDirection"] == -1
                and ratio > config.comparePeaklists["ratioThreshold"]
            ):
                return False

        return True

    # ----

    def _peakGroups(self):
        """Row spans of the grid that hold one and the same peak.

        The rows are sorted by m/z, so a group is a run of neighbouring rows
        that keep matching; it ends at the first row that does not match the one
        above it. Every row belongs to exactly one span, so a peak that matched
        nothing is a group of its own and is boxed in on its own -- the height of
        the box is then what tells the two apart.
        """

        groups = []
        peaklist = self.currentPeaklist
        start = 0

        for i in range(1, len(peaklist) + 1):
            if i < len(peaklist) and self._peaksMatch(peaklist[i - 1], peaklist[i]):
                continue
            groups.append((start, i - 1))
            start = i

        return groups

    # ----

    def compareSelected(self, pkIndex):
        """Compare selected mass only."""

        self.currentMatches = []

        # get current peak
        p1 = self.currentPeaklist[pkIndex]

        # compare mass
        for p2 in self.currentPeaklist:

            # check charge
            if (
                not config.comparePeaklists["ignoreCharge"]
                and (p1[2] != p2[2])
                and (p1[2] is not None and p2[2] is not None)
            ):
                continue

            # check error
            error = mspy.delta(p1[0], p2[0], config.comparePeaklists["units"])
            if abs(error) <= config.comparePeaklists["tolerance"]:
                ratio1 = p1[3] / p2[3]
                ratio2 = 1 / ratio1
                self.currentMatches.append(
                    [p2[1], p2[0], error, ratio1, ratio2, p1[1] == p2[1]]
                )
            elif error < 0:
                break

        # sort matches by document
        self.currentMatches.sort()

    # ----

    def copyPeaklist(self):
        """Copy total peaklist table into clipboard."""

        # get default bgr colour
        defaultColour = self.peaklistGrid.GetDefaultCellBackgroundColour()

        # get data
        buff = ""
        for row in range(self.peaklistGrid.GetNumberRows()):
            line = ""
            for col in range(self.peaklistGrid.GetNumberCols()):
                value = self.peaklistGrid.GetCellValue(row, col)
                if (
                    value == ""
                    and defaultColour
                    != self.peaklistGrid.GetCellBackgroundColour(row, col)
                ):
                    value = "x"
                line += value + "\t"
            buff += "%s\n" % (line.rstrip())

        # make text object for data
        obj = wx.TextDataObject()
        obj.SetText(buff.rstrip())

        # paste to clipboard
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(obj)
            wx.TheClipboard.Close()

    # ----

    def copyMatches(self):
        """Copy matches table into clipboard."""

        # get data
        buff = ""
        for row in range(self.matchesGrid.GetNumberRows()):
            line = ""
            for col in range(1, self.matchesGrid.GetNumberCols()):
                line += self.matchesGrid.GetCellValue(row, col) + "\t"
            buff += "%s\n" % (line.rstrip())

        # make text object for data
        obj = wx.TextDataObject()
        obj.SetText(buff.rstrip())

        # paste to clipboard
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(obj)
            wx.TheClipboard.Close()

    # ----
