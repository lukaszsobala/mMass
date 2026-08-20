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
import wx
import wx.grid
from typing import Any

# load modules
from . import mwx
from . import images
from . import config
from .mixins import MakeModalMixin
import mspy

# FLOATING PANEL WITH PEAK DIFFERENCES TOOL
# -----------------------------------------


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

        # init amino acids and dipeptides
        self.initAminoacids()

        # init sugars and permethylated sugars
        self.initSugars()

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

        self.aminoacids_check = wx.CheckBox(panel, -1, "Amino acids")
        self.aminoacids_check.SetFont(wx.SMALL_FONT)
        self.aminoacids_check.SetValue(config.peakDifferences["aminoacids"])

        self.dipeptides_check = wx.CheckBox(panel, -1, "Dipeptides")
        self.dipeptides_check.SetFont(wx.SMALL_FONT)
        self.dipeptides_check.SetValue(config.peakDifferences["dipeptides"])

        self.sugars_check = wx.CheckBox(panel, -1, "Sugars")
        self.sugars_check.SetFont(wx.SMALL_FONT)
        self.sugars_check.SetValue(config.peakDifferences["sugars"])

        self.permesugars_check = wx.CheckBox(panel, -1, "PerMe-Sugars")
        self.permesugars_check.SetFont(wx.SMALL_FONT)
        self.permesugars_check.SetValue(config.peakDifferences["permesugars"])

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

        self.consolidate_check = wx.CheckBox(panel, -1, "Hide umatched")
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
        sizer.Add(self.aminoacids_check, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(self.dipeptides_check, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.AddSpacer(20)
        sizer.Add(self.sugars_check, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(self.permesugars_check, 0, wx.ALIGN_CENTER_VERTICAL)
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

        dark = images.is_dark_mode()
        cell_bg = wx.Colour(30, 30, 30) if dark else wx.WHITE
        cell_fg = wx.Colour(220, 220, 220) if dark else wx.BLACK
        label_bg = wx.Colour(45, 45, 45) if dark else wx.Colour(245, 245, 245)
        grid_line = wx.Colour(70, 70, 70) if dark else wx.Colour(220, 220, 220)

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
        self.differencesGrid.SetLabelBackgroundColour(label_bg)
        self.differencesGrid.SetLabelTextColour(cell_fg)
        self.differencesGrid.SetDefaultCellFont(wx.SMALL_FONT)
        self.differencesGrid.SetDefaultCellAlignment(wx.ALIGN_CENTER, wx.ALIGN_CENTER)
        self.differencesGrid.SetDefaultCellBackgroundColour(cell_bg)
        self.differencesGrid.SetDefaultCellTextColour(cell_fg)
        self.differencesGrid.EnableGridLines(True)
        self.differencesGrid.SetGridLineColour(grid_line)

        self.differencesGrid.Bind(wx.grid.EVT_GRID_SELECT_CELL, self.onCellSelected)
        self.differencesGrid.Bind(
            wx.grid.EVT_GRID_CELL_LEFT_DCLICK, self.onCellActivated
        )

    # ----

    def makeMatchesGrid(self, panel):
        """Make matches grid."""

        dark = images.is_dark_mode()
        cell_bg = wx.Colour(30, 30, 30) if dark else wx.WHITE
        cell_fg = wx.Colour(220, 220, 220) if dark else wx.BLACK
        label_bg = wx.Colour(45, 45, 45) if dark else wx.Colour(245, 245, 245)
        grid_line = wx.Colour(70, 70, 70) if dark else wx.Colour(220, 220, 220)

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
        self.matchesGrid.SetLabelBackgroundColour(label_bg)
        self.matchesGrid.SetLabelTextColour(cell_fg)
        self.matchesGrid.SetDefaultCellFont(wx.SMALL_FONT)
        self.matchesGrid.SetDefaultCellAlignment(wx.ALIGN_CENTER, wx.ALIGN_CENTER)
        self.matchesGrid.SetDefaultCellBackgroundColour(cell_bg)
        self.matchesGrid.SetDefaultCellTextColour(cell_fg)
        self.matchesGrid.EnableGridLines(True)
        self.matchesGrid.SetGridLineColour(grid_line)

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

            config.peakDifferences["aminoacids"] = int(self.aminoacids_check.GetValue())
            config.peakDifferences["dipeptides"] = int(self.dipeptides_check.GetValue())
            config.peakDifferences["sugars"] = int(self.sugars_check.GetValue())
            config.peakDifferences["permesugars"] = int(
                self.permesugars_check.GetValue()
            )
            config.peakDifferences["tolerance"] = float(self.tolerance_value.GetValue())
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
                if not self.currentDifferences[i][j][1]:
                    continue
                elif self.currentDifferences[i][j][1] == "value":
                    self.differencesGrid.SetCellBackgroundColour(
                        x, y, wx.Colour(0, 140, 70)
                    )
                    self.differencesGrid.SetCellTextColour(x, y, wx.WHITE)
                elif self.currentDifferences[i][j][1] == "amino":
                    self.differencesGrid.SetCellBackgroundColour(
                        x, y, wx.Colour(0, 200, 255)
                    )
                    self.differencesGrid.SetCellTextColour(x, y, wx.BLACK)
                elif self.currentDifferences[i][j][1] == "dipep":
                    self.differencesGrid.SetCellBackgroundColour(
                        x, y, wx.Colour(100, 255, 255)
                    )
                    self.differencesGrid.SetCellTextColour(x, y, wx.BLACK)
                elif self.currentDifferences[i][j][1] == "sugar":
                    self.differencesGrid.SetCellBackgroundColour(
                        x, y, wx.Colour(255, 170, 0)
                    )
                    self.differencesGrid.SetCellTextColour(x, y, wx.BLACK)
                elif self.currentDifferences[i][j][1] == "permesugar":
                    self.differencesGrid.SetCellBackgroundColour(
                        x, y, wx.Colour(255, 210, 100)
                    )
                    self.differencesGrid.SetCellTextColour(x, y, wx.BLACK)

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
        """Search difference for specified value, aminoacids or dipeptides."""

        self.currentMatches = []

        # search for value
        if self.currentDifference:
            error = diff - self.currentDifference
            if abs(error) <= config.peakDifferences["tolerance"]:
                self.currentMatches.append([str(self.currentDifference), error])

        # search for aminoacids
        if config.peakDifferences["aminoacids"]:
            for aa in self._aaMasses:
                error = diff - self._aaMasses[aa][config.peakDifferences["massType"]]
                if abs(error) <= config.peakDifferences["tolerance"]:
                    self.currentMatches.append([aa, error])

        # search for dipeptides
        if config.peakDifferences["dipeptides"]:
            for dip in self._dipMasses:
                error = diff - self._dipMasses[dip][config.peakDifferences["massType"]]
                if abs(error) <= config.peakDifferences["tolerance"]:
                    self.currentMatches.append([dip, error])

        # search for sugars
        if config.peakDifferences["sugars"]:
            for sug in self._sugarMasses:
                error = diff - self._sugarMasses[sug][config.peakDifferences["massType"]]
                if abs(error) <= config.peakDifferences["tolerance"]:
                    self.currentMatches.append([sug, error])

        # search for permethylated sugars
        if config.peakDifferences["permesugars"]:
            for sug in self._permeSugarMasses:
                error = (
                    diff
                    - self._permeSugarMasses[sug][config.peakDifferences["massType"]]
                )
                if abs(error) <= config.peakDifferences["tolerance"]:
                    self.currentMatches.append([sug, error])

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
            aaMin = self._aaLimits[0] - config.peakDifferences["tolerance"]
            aaMax = self._aaLimits[1] + config.peakDifferences["tolerance"]
            dipMin = self._dipLimits[0] - config.peakDifferences["tolerance"]
            dipMax = self._dipLimits[1] + config.peakDifferences["tolerance"]
            sugMin = self._sugarLimits[0] - config.peakDifferences["tolerance"]
            sugMax = self._sugarLimits[1] + config.peakDifferences["tolerance"]
            permeMin = self._permeSugarLimits[0] - config.peakDifferences["tolerance"]
            permeMax = self._permeSugarLimits[1] + config.peakDifferences["tolerance"]

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

                    # match amino acids
                    if (
                        not match
                        and config.peakDifferences["aminoacids"]
                        and (aaMin <= diff <= aaMax)
                    ):
                        for aa in self._aaMasses:
                            error = (
                                diff
                                - self._aaMasses[aa][config.peakDifferences["massType"]]
                            )
                            if abs(error) <= config.peakDifferences["tolerance"]:
                                match = "amino"
                                break

                    # match dipeptides
                    if (
                        not match
                        and config.peakDifferences["dipeptides"]
                        and (dipMin <= diff <= dipMax)
                    ):
                        for dip in self._dipMasses:
                            error = (
                                diff
                                - self._dipMasses[dip][
                                    config.peakDifferences["massType"]
                                ]
                            )
                            if abs(error) <= config.peakDifferences["tolerance"]:
                                match = "dipep"
                                break

                    # match sugars
                    if (
                        not match
                        and config.peakDifferences["sugars"]
                        and (sugMin <= diff <= sugMax)
                    ):
                        for sug in self._sugarMasses:
                            error = (
                                diff
                                - self._sugarMasses[sug][
                                    config.peakDifferences["massType"]
                                ]
                            )
                            if abs(error) <= config.peakDifferences["tolerance"]:
                                match = "sugar"
                                break

                    # match permethylated sugars
                    if (
                        not match
                        and config.peakDifferences["permesugars"]
                        and (permeMin <= diff <= permeMax)
                    ):
                        for sug in self._permeSugarMasses:
                            error = (
                                diff
                                - self._permeSugarMasses[sug][
                                    config.peakDifferences["massType"]
                                ]
                            )
                            if abs(error) <= config.peakDifferences["tolerance"]:
                                match = "permesugar"
                                break

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

    def initAminoacids(self):
        """Calculate amino acids / dipeptides masses and ranges."""

        self._aaLimits = [0.0, 1000.0]
        self._dipLimits = [0.0, 1000.0]
        self._aaMasses = {}
        self._dipMasses = {}

        # get amino acids
        aminoacids = []
        for abbr in mspy.monomers:
            if mspy.monomers[abbr].category == "_InternalAA":
                aminoacids.append(abbr)
                self._aaMasses[abbr] = self._to_mass_pair(mspy.monomers[abbr].mass)

        # approximate mass limits
        masses = []
        for aa in aminoacids:
            masses.append(self._to_mass_pair(mspy.monomers[aa].mass)[1])
        self._aaLimits = [min(masses) - 1, max(masses) + 1]
        self._dipLimits = [2 * self._aaLimits[0] - 1, 2 * self._aaLimits[1] + 1]

        # generate dipeptides
        for x in range(len(aminoacids)):
            for y in range(x, len(aminoacids)):

                aX = aminoacids[x]
                aY = aminoacids[y]

                massX = self._to_mass_pair(mspy.monomers[aX].mass)
                massY = self._to_mass_pair(mspy.monomers[aY].mass)
                mass = (massX[0] + massY[0], massX[1] + massY[1])

                if aX != aY:
                    label = "%s%s/%s%s" % (aX, aY, aY, aX)
                else:
                    label = aX + aY

                self._dipMasses[label] = mass

    # ----

    def initSugars(self):
        """Calculate sugar / permethylated sugar masses and ranges."""

        # elemental formulas of residue (glycosidic) masses
        sugarFormulas = {
            "Hex": "C6H10O5",
            "dHex": "C6H10O4",
            "HexNAc": "C8H13NO5",
            "NeuAc": "C11H17NO8",
            "NeuGc": "C11H17NO9",
            "KDN": "C9H14O8",
            "HexA": "C6H8O6",
            "HexN": "C6H11NO4",
            "Pent": "C5H8O4",
        }
        permeSugarFormulas = {
            "Hex-PM": "C9H16O5",
            "dHex-PM": "C8H14O4",
            "HexNAc-PM": "C11H19NO5",
            "NeuAc-PM": "C16H27NO8",
            "NeuGc-PM": "C17H29NO9",
            "KDN-PM": "C14H24O8",
            "HexA-PM": "C9H14O6",
            "Pent-PM": "C7H12O4",
        }

        self._sugarMasses = {}
        for abbr, formula in sugarFormulas.items():
            mass = mspy.obj_compound.compound(formula).mass()
            self._sugarMasses[abbr] = self._to_mass_pair(mass)

        self._permeSugarMasses = {}
        for abbr, formula in permeSugarFormulas.items():
            mass = mspy.obj_compound.compound(formula).mass()
            self._permeSugarMasses[abbr] = self._to_mass_pair(mass)

        # approximate mass limits (span mono..avg to cover both mass types)
        self._sugarLimits = self._massLimits(self._sugarMasses)
        self._permeSugarLimits = self._massLimits(self._permeSugarMasses)

    # ----

    def _massLimits(self, masses):
        """Get [min, max] limits spanning mono and average masses."""

        if not masses:
            return [0.0, 1000.0]

        lows = [pair[0] for pair in masses.values()]
        highs = [pair[1] for pair in masses.values()]
        return [min(lows) - 1, max(highs) + 1]

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

    def _to_mass_pair(self, mass):
        """Normalize monomer mass into (mono, avg) tuple."""

        if isinstance(mass, (tuple, list)) and len(mass) >= 2:
            return (float(mass[0]), float(mass[1]))
        if isinstance(mass, (tuple, list)) and len(mass) == 1:
            value = float(mass[0])
            return (value, value)
        if isinstance(mass, (tuple, list)):
            return (0.0, 0.0)
        if mass is None:
            return (0.0, 0.0)
        value = float(mass)
        return (value, value)

    # ----
