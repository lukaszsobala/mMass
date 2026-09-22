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
import threading
import bisect

import wx
import wx.grid
from typing import Any

# load modules
from . import mwx
from . import images
from . import config
from . import differences
from .mixins import MakeModalMixin
import mspy

# FLOATING PANEL WITH PEAK DIFFERENCES TOOL
# -----------------------------------------


# Background colour of a highlighted difference, by the kind of match found.
# The hues are saturated enough to read against either theme's cell background;
# the text drawn on them is derived per cell (see mwx.readableOn) rather than
# fixed, so a pale highlight never ends up light-on-light in dark mode.
MATCH_COLOURS = {
    "value": wx.Colour(0, 140, 70),
    "single": wx.Colour(0, 200, 255),
    "pair": wx.Colour(100, 255, 255),
}


class panelPeakDifferences(wx.Frame, MakeModalMixin):
    """Peak differences tool."""

    def __init__(self, parent):
        wx.Frame.__init__(
            self,
            parent,
            -1,
            "Peak Differences",
            size=wx.Size(500, 400),
            style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT,
        )

        self.parent = parent

        self.processing = None

        self.currentDocument = None
        self.currentDifference = None
        self.currentDifferences = None
        self.currentMatches = None

        # init the lists matched against
        self.initLists()

        # make gui items
        self.makeGUI()
        self.Bind(wx.EVT_CLOSE, self.onClose)

        # apply dark mode
        mwx.applyDarkMode(self)

    # ----

    def makeGUI(self):
        """Make panel gui."""

        # make toolbar
        toolbar = self.makeToolbar()

        # make panels
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
            self, -1, images.lib["bgrToolbarNoBorder"], size=(-1, mwx.TOOLBAR_HEIGHT)
        )

        # make match fields
        difference_label = wx.StaticText(panel, -1, "Difference:")
        difference_label.SetFont(wx.SMALL_FONT)

        self.difference_value = wx.TextCtrl(
            panel,
            -1,
            "",
            size=wx.Size(100, -1),
            style=wx.TE_PROCESS_ENTER,
            validator=mwx.validator("floatPos"),
        )
        self.difference_value.Bind(wx.EVT_TEXT_ENTER, self.onSearch)

        self.lists_butt = wx.Button(
            panel, -1, "Lists", size=wx.Size(-1, mwx.SMALL_BUTTON_HEIGHT)
        )
        self.lists_butt.SetToolTip(
            wx.ToolTip("Lists of the Mass Differences library (Libraries menu) to match")
        )
        self.lists_butt.Bind(wx.EVT_BUTTON, self.onListsMenu)

        self.lists_label = wx.StaticText(panel, -1, "")
        self.lists_label.SetFont(wx.SMALL_FONT)
        self.updateListsLabel()

        massType_label = wx.StaticText(panel, -1, "Mass:")
        massType_label.SetFont(wx.SMALL_FONT)

        self.massTypeMo_radio = wx.RadioButton(panel, -1, "Mo", style=wx.RB_GROUP)
        self.massTypeMo_radio.SetFont(wx.SMALL_FONT)
        self.massTypeMo_radio.SetValue(True)

        self.massTypeAv_radio = wx.RadioButton(panel, -1, "Av")
        self.massTypeAv_radio.SetFont(wx.SMALL_FONT)
        self.massTypeAv_radio.SetValue(config.peakDifferences["massType"])

        tolerance_label = wx.StaticText(panel, -1, "Tolerance:")
        tolerance_label.SetFont(wx.SMALL_FONT)

        self.tolerance_value = wx.TextCtrl(
            panel,
            -1,
            str(config.peakDifferences["tolerance"]),
            size=wx.Size(50, -1),
            validator=mwx.validator("floatPos"),
        )

        toleranceUnits_label = wx.StaticText(panel, -1, "m/z")
        toleranceUnits_label.SetFont(wx.SMALL_FONT)

        self.consolidate_check = wx.CheckBox(panel, -1, "Hide unmatched")
        self.consolidate_check.SetFont(wx.SMALL_FONT)
        self.consolidate_check.SetValue(config.peakDifferences["consolidate"])

        self.search_butt = wx.Button(
            panel, -1, "Search", size=wx.Size(-1, mwx.SMALL_BUTTON_HEIGHT)
        )
        self.search_butt.Bind(wx.EVT_BUTTON, self.onSearch)

        # pack elements
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.AddSpacer(mwx.CONTROLBAR_LSPACE)
        sizer.Add(difference_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(self.difference_value, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(20)
        sizer.Add(self.lists_butt, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(self.lists_label, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(20)
        sizer.Add(massType_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(self.massTypeMo_radio, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(self.massTypeAv_radio, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(20)
        sizer.Add(tolerance_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(self.tolerance_value, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(toleranceUnits_label, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(20)
        sizer.Add(self.consolidate_check, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddStretchSpacer()
        sizer.AddSpacer(20)
        sizer.Add(self.search_butt, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(mwx.CONTROLBAR_RSPACE)

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        mainSizer.Add(sizer, 1, wx.EXPAND)
        panel.SetSizer(mainSizer)
        mainSizer.Fit(panel)

        return panel

    # ----

    def makeMainPanel(self):
        """Make differences panel."""

        panel = wx.Panel(self, -1)

        # make table
        self.makeDifferencesGrid(panel)
        self.makeMatchesGrid(panel)

        # pack main
        mainSizer = wx.BoxSizer(wx.HORIZONTAL)
        mainSizer.Add(self.differencesGrid, 1, wx.EXPAND)
        mainSizer.AddSpacer(mwx.SASH_SIZE)
        mainSizer.Add(self.matchesGrid, 0, wx.EXPAND)

        # fit layout
        panel.SetSizer(mainSizer)

        return panel

    # ----

    def makeDifferencesGrid(self, panel):
        """Make differences grid."""

        # make table
        self.differencesGrid = wx.grid.Grid(
            panel, -1, size=wx.Size(700, 500), style=mwx.GRID_STYLE
        )
        self.differencesGrid.CreateGrid(0, 0)
        self.differencesGrid.DisableDragColSize()
        self.differencesGrid.DisableDragRowSize()
        rowHeight = mwx.gridRowHeight(self.differencesGrid, wx.SMALL_FONT)
        self.differencesGrid.SetColLabelSize(rowHeight)
        self.differencesGrid.SetDefaultRowSize(rowHeight)
        self.differencesGrid.SetLabelFont(wx.SMALL_FONT)
        self.differencesGrid.SetDefaultCellFont(wx.SMALL_FONT)
        self.differencesGrid.SetDefaultCellAlignment(wx.ALIGN_CENTER, wx.ALIGN_CENTER)
        mwx.applyGridTheme(self.differencesGrid)

        self.differencesGrid.Bind(wx.grid.EVT_GRID_SELECT_CELL, self.onCellSelected)
        self.differencesGrid.Bind(
            wx.grid.EVT_GRID_CELL_LEFT_DCLICK, self.onCellActivated
        )

    # ----

    def makeMatchesGrid(self, panel):
        """Make matches grid."""

        # make table
        self.matchesGrid = wx.grid.Grid(
            panel, -1, size=wx.Size(200, 400), style=mwx.GRID_STYLE
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

    # ----

    def onThemeChanged(self):
        """Recolour the grids after a live light/dark switch.

        wxGrid paints its own cells, so a repaint alone leaves them in the old
        theme.  The match highlights are fixed hues that read on either
        background, so only the defaults, labels and grid lines change and the
        grids do not have to be filled again.
        """

        for grid in (self.differencesGrid, self.matchesGrid):
            mwx.applyGridTheme(grid)
            grid.ForceRefresh()

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
        self.Destroy()

    # ----

    def onProcessing(self, status=True):
        """Show processing gauge."""

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
        self.differencesGrid.SetMinSize(self.differencesGrid.GetSize())
        self.Layout()
        self.mainSizer.Fit(self)
        try:
            wx.GetApp().Yield()
        except Exception:
            pass
        try:
            self.differencesGrid.SetMinSize(wx.Size(-1, -1))
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

    def onCellSelected(self, evt):
        """Grid cell selected."""

        evt.Skip()

        # get cell
        col = evt.GetCol()
        row = evt.GetRow()

        if not self.currentDifferences:
            return

        # highlight selected cell
        self.differencesGrid.SelectBlock(row, col, row, col)

        # get peaks and diff
        mz1 = self.currentDifferences[col][0][0]
        mz2 = self.currentDifferences[row][0][0]
        diff = abs(mz1 - mz2)

        # highlight masses in plot
        self.parent.updateMassPoints([mz1, mz2])

        # search diff
        self.searchSelected(diff)
        self.updateMatchesGrid()

    # ----

    def onCellActivated(self, evt):
        """Grid cell activated."""

        evt.Skip()

        # get cell
        col = evt.GetCol()
        row = evt.GetRow()

        if not self.currentDifferences:
            return

        # highlight selected cell
        self.differencesGrid.SelectBlock(row, col, row, col)

        # get peaks and diff
        mz1 = self.currentDifferences[col][0][0]
        mz2 = self.currentDifferences[row][0][0]
        diff = abs(mz1 - mz2)

        # highlight masses in plot
        self.parent.updateMassPoints([mz1, mz2])

        # send difference into mass to formula tool
        self.parent.onToolsMassToFormula(
            mass=diff,
            charge=0,
            tolerance=config.peakDifferences["tolerance"],
            units="Da",
            agentFormula="",
        )

    # ----

    def onSearch(self, evt):
        """Generate differences and search for specified mass(es)."""

        # check processing
        if self.processing:
            return

        # clear previous
        self.currentDifferences = None
        self.currentMatches = None

        # check document
        if not self.currentDocument:
            wx.Bell()
            return

        # get params
        if not self.getParams():
            wx.Bell()
            self.updateDifferencesGrid()
            self.updateMatchesGrid()
            return

        # show processing gauge
        self.onProcessing(True)
        self.search_butt.Enable(False)

        # do processing
        self.processing = threading.Thread(target=self.runSearch)
        self.processing.start()

        # pulse gauge while working
        while self.processing and self.processing.is_alive():
            self.gauge.pulse()

        # update gui
        self.updateDifferencesGrid()
        self.updateMatchesGrid()

        # hide processing gauge
        self.onProcessing(False)
        self.search_butt.Enable(True)

    # ----

    def setData(self, document):
        """Set data."""

        # set new document
        self.currentDocument = document
        self.currentDifferences = None
        self.currentMatches = None

        # update gui
        self.updateDifferencesGrid()
        self.updateMatchesGrid()

    # ----

    def getParams(self):
        """Get all params from dialog."""

        # try to get values
        try:

            if self.difference_value.GetValue():
                self.currentDifference = float(self.difference_value.GetValue())
            else:
                self.currentDifference = None

            config.peakDifferences["tolerance"] = float(self.tolerance_value.GetValue())
            self.initLists()
            config.peakDifferences["massType"] = int(self.massTypeAv_radio.GetValue())
            config.peakDifferences["consolidate"] = int(
                self.consolidate_check.GetValue()
            )

            return True

        except Exception:
            wx.Bell()
            return False

    # ----

    def updateDifferencesGrid(self):
        """Update grid values."""

        # erase grid
        if self.differencesGrid.GetNumberRows():
            self.differencesGrid.DeleteRows(0, self.differencesGrid.GetNumberRows())
        if self.differencesGrid.GetNumberCols():
            self.differencesGrid.DeleteCols(0, self.differencesGrid.GetNumberCols())

        # check differences
        if not self.currentDifferences:
            return

        # get grid size
        size = len(self.currentDifferences)

        # create new cells
        self.differencesGrid.AppendCols(size)
        self.differencesGrid.AppendRows(size)

        # create labels
        mzFormat = "%0." + repr(config.main["mzDigits"]) + "f"
        cellAttr = wx.grid.GridCellAttr()
        cellAttr.SetReadOnly(True)
        labels = []
        for x in range(size):
            label = mzFormat % self.currentDifferences[x][0][0]
            labels.append(label)
            self.differencesGrid.SetColLabelValue(x, label)
            self.differencesGrid.SetRowLabelValue(x, label)
            self.differencesGrid.SetColAttr(x, cellAttr.Clone())

        # Size the columns and the row-label gutter to the labels. Their widths
        # are fixed pixel defaults while the label font is DPI-scaled, so on a
        # large font the m/z labels ran into each other. Every cell here holds
        # an m/z number of the same shape, so measuring the widest label sizes
        # them all -- much cheaper than AutoSizeColumns on an n x n grid.
        if labels:
            dc = wx.ClientDC(self.differencesGrid)
            dc.SetFont(wx.SMALL_FONT)
            colWidth = (
                max(dc.GetTextExtent(label)[0] for label in labels)
                + 2 * mwx.GRID_CELL_PADDING
            )
            self.differencesGrid.SetDefaultColSize(colWidth, True)
            self.differencesGrid.SetRowLabelSize(colWidth)

        # paste data
        mzFormat = "%0." + repr(config.main["mzDigits"]) + "f"
        for x in range(size):
            for y in range(size):

                # get difference indexes
                if y == x:
                    self.differencesGrid.SetCellValue(x, y, "---")
                    continue
                elif y < x:
                    i = x
                    j = y + 1
                else:
                    i = y
                    j = x + 1

                # set value
                diff = mzFormat % self.currentDifferences[i][j][0]
                self.differencesGrid.SetCellValue(x, y, diff)

                # highlight matches
                colour = MATCH_COLOURS.get(self.currentDifferences[i][j][1])
                if colour is None:
                    continue

                self.differencesGrid.SetCellBackgroundColour(x, y, colour)
                self.differencesGrid.SetCellTextColour(x, y, mwx.readableOn(colour))

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
        self.matchesGrid.AppendCols(2)
        self.matchesGrid.AppendRows(len(self.currentMatches))
        self.matchesGrid.SetColLabelValue(0, "match")
        self.matchesGrid.SetColLabelValue(1, "error")

        # NOTE: SetAlignment takes (horizontal, vertical). These used to pass
        # ALIGN_TOP as the horizontal argument, which is 0 (== ALIGN_LEFT), so
        # the intended alignment never took effect anyway.
        for x in range(2):
            cellAttr = wx.grid.GridCellAttr()
            cellAttr.SetAlignment(wx.ALIGN_CENTER, wx.ALIGN_CENTER)
            cellAttr.SetReadOnly(True)
            self.matchesGrid.SetColAttr(x, cellAttr)

        # set format
        errFormat = "%0." + repr(config.main["mzDigits"]) + "f"

        # add data
        for i, match in enumerate(self.currentMatches):
            error = errFormat % match[1]
            self.matchesGrid.SetCellValue(i, 0, match[0])
            self.matchesGrid.SetCellValue(i, 1, error)

        # AutoSize fits the text exactly, leaving centred values flush against
        # the cell edge, so give the columns some air
        self.matchesGrid.AutoSizeColumns(True)
        for x in range(2):
            self.matchesGrid.SetColSize(
                x, self.matchesGrid.GetColSize(x) + 2 * mwx.GRID_CELL_PADDING
            )

    # ----

    def searchSelected(self, diff):
        """Search difference for specified value or the lists' entries."""

        self.currentMatches = []

        # search for value
        if self.currentDifference:
            error = diff - self.currentDifference
            if abs(error) <= config.peakDifferences["tolerance"]:
                self.currentMatches.append([str(self.currentDifference), error])

        # search the lists
        massType = config.peakDifferences["massType"]
        for name, mono, avg, _listName in self._entries:
            error = diff - (avg if massType else mono)
            if abs(error) <= config.peakDifferences["tolerance"]:
                self.currentMatches.append([name, error])

    # ----

    def runSearch(self):
        """Calculate differences for current peaklist and search for matches."""

        # run task
        try:

            # get peaklist
            if self.currentDocument is None:
                self.currentDifferences = []
                return False

            peaklist = self.currentDocument.spectrum.peaklist
            if not peaklist:
                return False

            # init limits
            diffMin = 0.0
            diffMax = 0.0
            if self.currentDifference:
                diffMin = self.currentDifference - config.peakDifferences["tolerance"]
                diffMax = self.currentDifference + config.peakDifferences["tolerance"]
            tolerance = config.peakDifferences["tolerance"]
            massType = config.peakDifferences["massType"]
            singles = self._singles[massType]
            pairs = self._pairs[massType]

            # calc differences
            self.currentDifferences = []
            for x in range(len(peaklist)):
                rowBuff: list[tuple[float, Any]] = [(peaklist[x].mz, x)]
                for y in range(x + 1):

                    mspy.CHECK_FORCE_QUIT()

                    diff = peaklist[x].mz - peaklist[y].mz
                    match = False

                    # match specified value
                    if self.currentDifference is not None and (
                        diffMin <= diff <= diffMax
                    ):
                        match = "value"

                    # match an entry of the lists, else a pair of them
                    if not match and _within(singles, diff, tolerance):
                        match = "single"
                    if not match and _within(pairs, diff, tolerance):
                        match = "pair"

                    # append difference
                    rowBuff.append((diff, match))

                # append row
                self.currentDifferences.append(rowBuff)

            # consolidate table - remove unmatched peaks
            if config.peakDifferences["consolidate"]:
                self.consolidateTable()

        # task canceled
        except mspy.ForceQuit:
            self.currentDifferences = []
            return

    # ----

    def initLists(self):
        """Collect the entries of the lists matched, and their pairs."""

        lists = config.peakDifferences["lists"]
        self._entries = differences.entries(lists)
        singles = differences.entries(lists, pairs=False)
        singleNames = {(entry[0], entry[3]) for entry in singles}
        pairs = [entry for entry in self._entries if (entry[0], entry[3]) not in singleNames]

        # sorted masses, mono and average, to look differences up in
        self._singles = [sorted(entry[1 + massType] for entry in singles) for massType in (0, 1)]
        self._pairs = [sorted(entry[1 + massType] for entry in pairs) for massType in (0, 1)]

    # ----

    def updateListsLabel(self):
        """Name the lists matched next to the Lists button."""

        lists = config.peakDifferences["lists"]
        text = ", ".join(
            name + (" (+pairs)" if differences.listPairs(name) else "") for name in lists
        )
        self.lists_label.SetLabel(text or "none")
        self.lists_label.GetParent().Layout()

    # ----

    def onListsMenu(self, evt=None):
        """Choose the lists to match."""

        menu = wx.Menu()
        handlers = {}
        for name in differences.availableLists():
            itemID = wx.NewIdRef()
            item = menu.AppendCheckItem(itemID, name)
            item.Check(name in config.peakDifferences["lists"])
            handlers[int(itemID)] = name

        def onMenu(evt):
            name = handlers.get(evt.GetId())
            if name is None:
                return
            lists = [item for item in config.peakDifferences["lists"] if item != name]
            if name not in config.peakDifferences["lists"]:
                lists.append(name)
            config.peakDifferences["lists"] = lists
            self.initLists()
            self.updateListsLabel()

        menu.Bind(wx.EVT_MENU, onMenu)
        self.lists_butt.PopupMenu(menu)
        menu.Destroy()

    # ----

    def consolidateTable(self):
        """Remove unmatched peaks."""

        if not self.currentDifferences:
            self.currentDifferences = []
            return

        # find matches
        indexes = []
        for i, row in enumerate(self.currentDifferences):
            for j, item in enumerate(row[1:]):
                if item[1]:
                    if i not in indexes:
                        indexes.append(i)
                    if j not in indexes:
                        indexes.append(j)

        # sort indexes
        indexes.sort()

        # consolidate table
        buff = []
        for i in indexes[:]:
            row = self.currentDifferences[i]
            rowBuff = [row[0]]
            for j, item in enumerate(row[1:]):
                if j in indexes:
                    rowBuff.append(item)
            buff.append(rowBuff)

        self.currentDifferences = buff

    # ----



def _within(masses, diff, tolerance):
    """Whether any of the sorted masses is within tolerance of diff."""

    index = bisect.bisect_left(masses, diff - tolerance)
    return index < len(masses) and masses[index] <= diff + tolerance
