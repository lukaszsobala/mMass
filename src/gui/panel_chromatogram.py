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
import wx

# load modules
from . import mwx
from . import config
from mspy.plot_canvas import canvas as plot_canvas
from mspy.plot_objects import container as plot_container, points as plot_points

# CHROMATOGRAM PANEL
# ------------------


class panelChromatogram(wx.Panel):
    """Interactive chromatogram (TIC/BPC) for browsing LC-MS runs.

    Clicking the chromatogram loads the nearest MS1 scan into the spectrum
    viewer. The parent frame is responsible for actually loading and showing
    the scan via its ``selectChromatogramScan`` method.
    """

    def __init__(self, parent):
        wx.Panel.__init__(
            self,
            parent,
            -1,
            size=wx.Size(300, 160),
            style=wx.NO_FULL_REPAINT_ON_RESIZE,
        )

        self.parent = parent
        self.currentDocument = None  # doc.document or None

        self.showTIC = True
        self.showBPC = False

        # make GUI
        self.makeGUI()

    # ----

    def makeGUI(self):
        """Make GUI elements."""

        self.makeCanvas()
        controlbar = self.makeControlbar()

        # pack elements
        self.mainSizer = wx.BoxSizer(wx.VERTICAL)
        self.mainSizer.Add(self.canvas, 1, wx.EXPAND)
        self.mainSizer.Add(controlbar, 0, wx.EXPAND)

        self.SetSizer(self.mainSizer)

        # recolour the control-bar widgets for the current theme (the canvas
        # themes itself; applyThemeToWindow leaves it alone as it is a
        # wx.Window, not a panel)
        mwx.applyThemeToWindow(self)

    # ----

    def makeCanvas(self):
        """Make plot canvas and set default parameters."""

        self.canvas = plot_canvas(
            self, size=wx.Size(-1, 130), style=mwx.PLOTCANVAS_STYLE_PANEL
        )

        self.canvas.setProperties(xLabel="min")
        self.canvas.setProperties(yLabel="norm. ion current")
        self.canvas.setProperties(showGrid=True)
        self.canvas.setProperties(showMinorTicks=False)
        self.canvas.setProperties(showLegend=True)
        self.canvas.setProperties(showXPosBar=False)
        self.canvas.setProperties(showYPosBar=False)
        self.canvas.setProperties(showGel=False)
        self.canvas.setProperties(checkLimits=True)
        self.canvas.setProperties(autoScaleY=True)
        self.canvas.setProperties(zoomAxis="x")
        self.canvas.setProperties(xPosDigits=2)
        self.canvas.setProperties(yPosDigits=2)
        self.canvas.setProperties(reverseScrolling=config.main["reverseScrolling"])
        self.canvas.setProperties(reverseDrawing=True)
        self.canvas.setLMBFunction("xDistance")
        self.canvas.setMFunction("cross")

        axisFont = wx.Font(
            config.spectrum["axisFontSize"],
            wx.FONTFAMILY_SWISS,
            wx.FONTSTYLE_NORMAL,
            wx.FONTWEIGHT_NORMAL,
            False,
        )
        self.canvas.setProperties(axisFont=axisFont)

        self.canvas.Bind(wx.EVT_LEFT_UP, self.onCanvasLMU)

        self.canvas.draw(plot_container([]))

    # ----

    def makeControlbar(self):
        """Make bottom control bar with TIC/BPC toggles and scan info."""

        panel = wx.Panel(self, -1, size=wx.Size(-1, mwx.CONTROLBAR_HEIGHT))

        self.ticCheck = wx.CheckBox(panel, -1, "TIC")
        self.ticCheck.SetFont(wx.SMALL_FONT)
        self.ticCheck.SetValue(self.showTIC)
        self.ticCheck.Bind(wx.EVT_CHECKBOX, self.onChromTypeChanged)

        self.bpcCheck = wx.CheckBox(panel, -1, "BPC")
        self.bpcCheck.SetFont(wx.SMALL_FONT)
        self.bpcCheck.SetValue(self.showBPC)
        self.bpcCheck.Bind(wx.EVT_CHECKBOX, self.onChromTypeChanged)

        self.scanLabel = wx.StaticText(panel, -1, "")
        self.scanLabel.SetFont(wx.SMALL_FONT)

        self.extractButt = wx.Button(panel, -1, "Extract Scans...", size=wx.Size(-1, -1))
        self.extractButt.SetFont(wx.SMALL_FONT)
        self.extractButt.Bind(wx.EVT_BUTTON, self.onExtractScans)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.ticCheck, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(self.bpcCheck, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(self.scanLabel, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 12)
        sizer.Add(self.extractButt, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        panel.SetSizer(sizer)
        return panel

    # ----

    def setData(self, document):
        """Set the active document and (re)draw its chromatogram.

        ``document`` should be a doc.document that is an LC-MS run
        (``islcms()`` True); anything else clears the panel.
        """

        if document is not None and document.islcms():
            self.currentDocument = document
            self.updateChromatogram()
            self.highlightCurrentScan()
            self.updateScanLabel()
        else:
            self.currentDocument = None
            self.canvas.draw(plot_container([]))
            self.scanLabel.SetLabel("")

    # ----

    def updateChromatogram(self):
        """Rebuild and draw the chromatogram traces for the current run."""

        container = plot_container([])

        if self.currentDocument is None:
            self.canvas.draw(container)
            return

        chroms = self.currentDocument.chromatograms or {}

        # trace colours follow the theme, matching the main spectrum view
        ticColour = mwx.themedPlotColour((16, 71, 185))
        bpcColour = mwx.themedPlotColour((50, 140, 0))

        if self.showTIC and chroms.get("tic"):
            container.append(
                plot_points(
                    list(chroms["tic"]),
                    lineColour=ticColour,
                    legend="TIC",
                    showLines=True,
                    showPoints=False,
                    exactFit=True,
                    normalized=True,
                )
            )

        if self.showBPC and chroms.get("bpc"):
            container.append(
                plot_points(
                    list(chroms["bpc"]),
                    lineColour=bpcColour,
                    legend="BPC",
                    showLines=True,
                    showPoints=False,
                    exactFit=True,
                    normalized=True,
                )
            )

        self.canvas.draw(container)

    # ----

    def onThemeChanged(self):
        """Redraw the traces in the new theme's colours.

        The colours are baked into the plot objects when the container is
        built, so the traces have to be made again rather than repainted.
        """

        self.updateChromatogram()
        self.highlightCurrentScan()

    # ----

    def highlightCurrentScan(self):
        """Mark the retention time of the currently shown scan."""

        if self.currentDocument is None:
            return

        scanID = self.currentDocument.currentScanID
        scanlist = self.currentDocument.scanlist or {}
        if scanID in scanlist:
            rt = scanlist[scanID].get("retentionTime")
            if rt is not None:
                self.canvas.highlightXPoints([rt / 60.0])
                return

        self.canvas.highlightXPoints([])

    # ----

    def updateScanLabel(self):
        """Show a short summary of the currently selected scan."""

        if self.currentDocument is None:
            self.scanLabel.SetLabel("")
            return

        scanID = self.currentDocument.currentScanID
        scanlist = self.currentDocument.scanlist or {}
        meta = scanlist.get(scanID)
        if not meta:
            self.scanLabel.SetLabel("")
            return

        parts = ["scan %s" % meta.get("scanNumber", scanID)]
        rt = meta.get("retentionTime")
        if rt is not None:
            parts.append("%.2f min" % (rt / 60.0))
        msLevel = meta.get("msLevel")
        if msLevel is not None:
            parts.append("MS%s" % msLevel)

        self.scanLabel.SetLabel("   ".join(parts))

    # ----

    def onChromTypeChanged(self, evt):
        """Toggle TIC/BPC traces."""

        self.showTIC = self.ticCheck.GetValue()
        self.showBPC = self.bpcCheck.GetValue()
        self.updateChromatogram()
        self.highlightCurrentScan()

    # ----

    def onExtractScans(self, evt):
        """Open the classic scan picker to extract individual scans."""

        if self.currentDocument is not None:
            self.parent.onExtractScansFromChromatogram(self.currentDocument)

    # ----

    def onCanvasLMU(self, evt):
        """Load the scan nearest to the clicked retention time."""

        if self.currentDocument is None:
            self.canvas.onLMU(evt)
            return

        # get cursor position before passing the event on
        position = self.canvas.getCursorPosition()
        self.canvas.onLMU(evt)
        if not position:
            return

        retention = position[0] * 60.0
        scanID = self.nearestScan(retention)
        if scanID is not None and scanID != self.currentDocument.currentScanID:
            self.parent.selectChromatogramScan(self.currentDocument, scanID)

    # ----

    def nearestScan(self, retention):
        """Return the scanNumber of the MS1 scan closest to a retention time."""

        if self.currentDocument is None:
            return None

        scanlist = self.currentDocument.scanlist or {}

        best = None
        bestDiff = None
        for scanID, meta in scanlist.items():
            rt = meta.get("retentionTime")
            if rt is None:
                continue
            # prefer MS1 survey scans for chromatogram navigation
            if meta.get("msLevel") not in (None, 1):
                continue
            diff = abs(rt - retention)
            if bestDiff is None or diff < bestDiff:
                bestDiff = diff
                best = scanID

        # fall back to any scan if no MS1 scans are present
        if best is None:
            for scanID, meta in scanlist.items():
                rt = meta.get("retentionTime")
                if rt is None:
                    continue
                diff = abs(rt - retention)
                if bestDiff is None or diff < bestDiff:
                    bestDiff = diff
                    best = scanID

        return best

    # ----
