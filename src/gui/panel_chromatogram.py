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
from . import doc
from mspy.plot_canvas import canvas as plot_canvas
from mspy.plot_objects import container as plot_container, points as plot_points

# trace colours on a white canvas, one per acquisition of the run
TIC_COLOURS = ((16, 71, 185), (200, 80, 0), (120, 40, 160), (0, 130, 130))
BPC_COLOURS = ((50, 140, 0), (180, 40, 90), (130, 110, 0), (90, 90, 90))

# how far the traces that are not browsed fade towards the canvas
INACTIVE_FADE = 0.6

# a drag narrower than this (pixels) is a click, not a range
MIN_RANGE_PIXELS = 3

# a trace button's label is cut to this many characters (the tooltip has it all)
TRACE_LABEL_CHARS = 14

# marks the control-bar buttons that open a menu
MENU_MARK = " \u25be"


# what the chromatogram traces show, for their check boxes
TIC_HELP = "Total ion current: the summed intensity of all ions in each scan."
BPC_HELP = "Base peak chromatogram: the intensity of the strongest peak in each scan."

# mass analysers named at the start of a Thermo filter string
ANALYSERS = {
    "FTMS": "Fourier transform analyser (Orbitrap or FT-ICR): high resolution",
    "ITMS": "Ion trap analyser: fast and sensitive, low resolution",
    "ASTMS": "Astral analyser: high resolution at high speed",
    "TOFMS": "Time-of-flight analyser",
    "SQMS": "Single quadrupole analyser",
    "TQMS": "Triple quadrupole analyser",
    "SECTORMS": "Magnetic sector analyser",
}


def traceHelp(trace):
    """Tooltip of a trace button: what the trace is, then its acquisition."""

    key = trace.get("key")
    acquisition = key[2] if key else ""
    if (trace.get("msLevel") or 1) > 1:
        what = "Fragment spectra (MS/MS), one dot per spectrum"
    else:
        analyser = acquisition.split(" ")[0].upper() if acquisition else ""
        what = ANALYSERS.get(analyser, "Full scans (MS1)")

    count = doc.scansText(len(trace.get("scans") or []))
    detail = "%s, %s" % (acquisition, count) if acquisition else count

    return "%s.\n%s" % (what, detail)


def _faded(colour, fraction):
    """A white-canvas colour moved `fraction` of the way to white."""

    return tuple(int(round(c + (255 - c) * fraction)) for c in colour)


def makeChromatogramPlots(
    chromatograms,
    showTIC=True,
    showBPC=True,
    minPoints=1,
    legendSuffix="",
    active=None,
    hidden=(),
):
    """Plot objects for the traces of doc.makeChromatograms, one per acquisition.

    Every trace is normalised on its own, so scans of different analysers (with
    ion currents an order of magnitude apart) share the canvas without one
    flattening the other. Traces with fewer than `minPoints` points are skipped.
    With `active` (a trace index), that trace is drawn with a dot at every scan
    and the others fade, showing which acquisition is being browsed. Traces of
    fragment spectra (see doc.makeChromatograms) are dots only: each is a
    single event of its own precursor, and lines between them would mean
    nothing. Traces whose index is in `hidden` are left out, unless browsed;
    the others keep their colours.
    """

    plots = []
    traces = (chromatograms or {}).get("traces", [])
    for kind, show, colours in (("tic", showTIC, TIC_COLOURS), ("bpc", showBPC, BPC_COLOURS)):
        if not show:
            continue
        for index, trace in enumerate(traces):
            if index in hidden and index != active:
                continue
            points = trace.get(kind) or []
            if len(points) < minPoints:
                continue
            legend = kind.upper()
            if trace.get("label"):
                legend += " " + trace["label"]
            legend += legendSuffix
            colour = colours[index % len(colours)]
            browsed = active is not None and index == active
            if active is not None and not browsed and len(traces) > 1:
                colour = _faded(colour, INACTIVE_FADE)
            colour = mwx.themedPlotColour(colour)
            events = (trace.get("msLevel") or 1) > 1
            plots.append(
                plot_points(
                    list(points),
                    lineColour=colour,
                    pointColour=colour,
                    legend=legend,
                    showLines=not events,
                    showPoints=browsed or events,
                    pointSize=3,
                    exactFit=True,
                    normalized=True,
                )
            )

    return plots


# CHROMATOGRAM PANEL
# ------------------


class panelChromatogram(wx.Panel):
    """Interactive chromatogram (TIC/BPC) for browsing LC-MS runs.

    A run that interleaves several kinds of MS1 scan (an Orbitrap and an ion
    trap full scan, say) has one trace per acquisition; the trace chosen in the
    control bar is the one browsed, drawn with a dot at each of its scans.
    Clicking the chromatogram loads the nearest scan of that trace, dragging
    across it combines the trace's scans under the range into one spectrum. The
    parent frame does the loading and showing (``selectChromatogramScan``,
    ``combineChromatogramScans``).
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

        # labels of the traces not drawn (unless browsed), kept for the next
        # run as its traces are likely named alike; or only the browsed trace
        # is drawn, whichever it is
        self.hiddenTraces = set()
        self.activeTraceOnly = False

        # trace drawn as the browsed one, and the document it was drawn for
        self._drawnActive = None
        self._drawnDocument = None

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

        self.canvas.Bind(wx.EVT_LEFT_DOWN, self.onCanvasLMD)
        self.canvas.Bind(wx.EVT_LEFT_UP, self.onCanvasLMU)

        # where the left button went down: (x in pixels, whether that starts a
        # range) -- kept here as well as in the canvas, see onCanvasLMU
        self._press = None

        self.canvas.draw(plot_container([]))

    # ----

    def makeControlbar(self):
        """Make bottom control bar with trace, TIC/BPC and combining controls.

        Nothing here is a drop-down list: GTK opens one as a menu with the
        chosen item over the control, which at the bottom of the screen does
        not fit and comes up as scroll arrows hiding the items. The traces are
        radio buttons (all in sight, one click away), the rest are buttons
        opening an ordinary menu, which flips upwards when it has to.
        """

        panel = wx.Panel(self, -1, size=wx.Size(-1, mwx.CONTROLBAR_HEIGHT))
        self.controlbar = panel

        # one radio button per acquisition, made in updateTraceButtons
        self.traceButtons = []
        self.traceSizer = wx.BoxSizer(wx.HORIZONTAL)

        self.ticCheck = wx.CheckBox(panel, -1, "TIC")
        self.ticCheck.SetFont(wx.SMALL_FONT)
        self.ticCheck.SetValue(self.showTIC)
        self.ticCheck.Bind(wx.EVT_CHECKBOX, self.onChromTypeChanged)
        self.ticCheck.SetToolTip(wx.ToolTip(TIC_HELP))

        self.bpcCheck = wx.CheckBox(panel, -1, "BPC")
        self.bpcCheck.SetFont(wx.SMALL_FONT)
        self.bpcCheck.SetValue(self.showBPC)
        self.bpcCheck.Bind(wx.EVT_CHECKBOX, self.onChromTypeChanged)
        self.bpcCheck.SetToolTip(wx.ToolTip(BPC_HELP))

        self.tracesButt = self._menuButton(panel, ("Traces",))
        self.tracesButt.SetToolTip(wx.ToolTip("Choose which traces are drawn"))
        self.tracesButt.Bind(wx.EVT_BUTTON, self.onTracesMenu)
        self.tracesButt.Hide()

        # cut short rather than pushing the buttons over each other in a
        # narrow pane (the Wide Spectrum layout)
        self.scanLabel = wx.StaticText(
            panel, -1, "", style=wx.ST_ELLIPSIZE_END | wx.ST_NO_AUTORESIZE
        )
        self.scanLabel.SetFont(wx.SMALL_FONT)
        # room for at least what is shown ("12 scans averaged", "scan 1234")
        dc = wx.ClientDC(self.scanLabel)
        dc.SetFont(self.scanLabel.GetFont())
        self.scanLabel.SetMinSize(wx.Size(dc.GetTextExtent("99 scans averaged")[0] + 4, -1))

        self.combineButt = self._menuButton(panel, ("Average", "Sum"))
        self.combineButt.SetToolTip(
            wx.ToolTip("How the scans under a range dragged across the chromatogram are combined")
        )
        self.combineButt.Bind(wx.EVT_BUTTON, self.onCombineMenu)
        self.updateCombineButton()

        self.extractButt = self._menuButton(panel, ("Extract",))
        self.extractButt.SetToolTip(
            wx.ToolTip("Open the combined spectrum or chosen scans as documents of their own")
        )
        self.extractButt.Bind(wx.EVT_BUTTON, self.onExtractMenu)

        self.controlSizer = sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.traceSizer, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(self.ticCheck, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(self.bpcCheck, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(self.tracesButt, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(self.scanLabel, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.combineButt, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        sizer.Add(self.extractButt, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)

        panel.SetSizer(sizer)
        return panel

    # ----

    def _menuButton(self, parent, labels):
        """A small button opening a menu, as wide as the widest of its labels."""

        button = wx.Button(parent, -1, labels[0] + MENU_MARK, style=wx.BU_EXACTFIT)
        button.SetFont(wx.SMALL_FONT)
        width = 0
        for label in labels:
            button.SetLabel(label + MENU_MARK)
            width = max(width, button.GetBestSize().GetWidth())
        button.SetLabel(labels[0] + MENU_MARK)
        button.SetMinSize(wx.Size(width + 8, -1))
        return button

    # ----

    def _popupUnder(self, button, menu):
        """Open a menu under a control-bar button (above it if no room)."""

        position = button.GetPosition()
        self.controlbar.PopupMenu(
            menu, wx.Point(position.x, position.y + button.GetSize().GetHeight())
        )
        menu.Destroy()

    # ----

    def setData(self, document):
        """Set the active document and (re)draw its chromatogram.

        ``document`` should be a doc.document that is an LC-MS run
        (``islcms()`` True); anything else clears the panel.
        """

        if document is not None and document.islcms():
            self.currentDocument = document
            self.updateTraceButtons()
            self.updateChromatogram()
            self.refreshSelection()
        else:
            self.currentDocument = None
            self._drawnDocument = None
            self.updateTraceButtons()
            self.canvas.highlightXRange(None)
            self.canvas.draw(plot_container([]))
            self.scanLabel.SetLabel("")

    # ----

    def traces(self):
        """Chromatogram traces of the current run."""

        if self.currentDocument is None:
            return []
        return (self.currentDocument.chromatograms or {}).get("traces", [])

    # ----

    def activeTraceIndex(self):
        """Index of the trace browsed: the one holding the spectrum shown."""

        document = self.currentDocument
        traces = self.traces()
        if document is None or not traces:
            return None

        key = None
        if document.combined:
            key = document.combined.get("key")
        else:
            meta = (document.scanlist or {}).get(document.currentScanID)
            if meta:
                key = doc.traceKey(meta)

        for index, trace in enumerate(traces):
            if trace.get("key") == key:
                return index

        # a scan without retention time is on no trace
        return 0

    # ----

    def updateTraceButtons(self):
        """One radio button per acquisition; none when the run has one."""

        traces = self.traces()
        labels = [self.traceLabel(trace) for trace in traces] if len(traces) > 1 else []
        if self.tracesButt.IsShown() != bool(labels):
            self.tracesButt.Show(bool(labels))
            self.controlbar.Layout()
        if labels == [button.GetLabel() for button in self.traceButtons]:
            return

        for button in self.traceButtons:
            button.Destroy()
        self.traceSizer.Clear()
        self.traceButtons = []

        for index, label in enumerate(labels):
            text = label
            if len(text) > TRACE_LABEL_CHARS:
                text = text[: TRACE_LABEL_CHARS - 1] + "\u2026"
            style = wx.RB_GROUP if index == 0 else 0
            button = wx.RadioButton(self.controlbar, -1, text, style=style)
            button.SetFont(wx.SMALL_FONT)
            button.SetToolTip(wx.ToolTip(traceHelp(traces[index])))
            button.Bind(wx.EVT_RADIOBUTTON, lambda evt, index=index: self.onTraceButton(index))
            self.traceSizer.Add(button, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4 if index else 0)
            self.traceButtons.append(button)

        mwx.applyThemeToWindow(self.controlbar)
        self.controlbar.Layout()

    # ----

    def minimumWidth(self):
        """Width the control bar needs to show every control side by side."""

        return self.controlSizer.CalcMin().GetWidth()

    # ----

    def updateChromatogram(self, keepView=False):
        """Rebuild and draw the chromatogram traces for the current run.

        keepView keeps the zoomed range (when restyling the traces of the same
        run); otherwise the whole run is shown.
        """

        container = plot_container([])

        if self.currentDocument is None:
            self._drawnDocument = None
            self.canvas.draw(container)
            return

        active = self.activeTraceIndex()
        for plot in makeChromatogramPlots(
            self.currentDocument.chromatograms,
            self.showTIC,
            self.showBPC,
            active=active,
            hidden=self.hiddenTraceIndexes(),
        ):
            container.append(plot)

        if keepView and self._drawnDocument is self.currentDocument and len(container):
            self.canvas.draw(
                container, self.canvas.getCurrentXRange(), self.canvas.getCurrentYRange()
            )
        else:
            self.canvas.draw(container)

        self._drawnActive = active
        self._drawnDocument = self.currentDocument

    # ----

    def refreshSelection(self):
        """Show what the run shows now: browsed trace, marker and label."""

        if self.currentDocument is None:
            return

        active = self.activeTraceIndex()
        if active is not None and active < len(self.traceButtons):
            if not self.traceButtons[active].GetValue():
                self.traceButtons[active].SetValue(True)
        if active != self._drawnActive or self._drawnDocument is not self.currentDocument:
            self.updateChromatogram(keepView=True)

        self.highlightCurrentScan()
        self.updateScanLabel()

    # ----

    def onThemeChanged(self):
        """Redraw the traces in the new theme's colours.

        The colours are baked into the plot objects when the container is
        built, so the traces have to be made again rather than repainted.
        """

        self.updateChromatogram(keepView=True)
        self.highlightCurrentScan()

    # ----

    def highlightCurrentScan(self):
        """Mark the retention time of the scan shown, or the combined range."""

        if self.currentDocument is None:
            return

        combined = self.currentDocument.combined
        if combined and combined.get("rtRange"):
            start, end = combined["rtRange"]
            self.canvas.highlightedPoints = []
            self.canvas.highlightXRange((start / 60.0, end / 60.0), editable=True)
            return

        self.canvas.highlightedRange = None

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
        """Show a short summary of the spectrum shown."""

        if self.currentDocument is None:
            self.scanLabel.SetLabel("")
            return

        combined = self.currentDocument.combined
        if combined:
            what = "summed" if combined.get("mode") == "sum" else "averaged"
            parts = ["%s %s" % (doc.scansText(len(combined.get("scans") or [])), what)]
            if combined.get("precursorMZ") is not None:
                parts.append("precursor %.2f" % combined["precursorMZ"])
            rtRange = combined.get("rtRange")
            if rtRange:
                parts.append("%.2f-%.2f min" % (rtRange[0] / 60.0, rtRange[1] / 60.0))
            self.scanLabel.SetLabel("   ".join(parts))
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
        if (msLevel or 1) > 1 and meta.get("precursorMZ") is not None:
            parts.append("precursor %.2f" % meta["precursorMZ"])

        self.scanLabel.SetLabel("   ".join(parts))

    # ----

    def onChromTypeChanged(self, evt):
        """Toggle TIC/BPC traces."""

        self.showTIC = self.ticCheck.GetValue()
        self.showBPC = self.bpcCheck.GetValue()
        self.updateChromatogram(keepView=True)
        self.highlightCurrentScan()

    # ----

    def traceLabel(self, trace):
        """Name of a trace in the control bar."""

        return trace.get("label") or "MS1"

    # ----

    def hiddenTraceIndexes(self):
        """Indexes of the current run's traces that are not drawn.

        The browsed trace is drawn whatever this says (makeChromatogramPlots).
        """

        return {
            index
            for index, trace in enumerate(self.traces())
            if self.activeTraceOnly or self.traceLabel(trace) in self.hiddenTraces
        }

    # ----

    def onTracesMenu(self, evt):
        """Choose which traces are drawn; the active (browsed) one always is."""

        traces = self.traces()
        active = self.activeTraceIndex()
        hidden = self.hiddenTraceIndexes()
        menu = wx.Menu()
        for index, trace in enumerate(traces):
            label = self.traceLabel(trace)
            browsed = index == active
            item = menu.AppendCheckItem(-1, label + (" (active)" if browsed else ""))
            item.Check(browsed or index not in hidden)
            item.Enable(not browsed)
            self.controlbar.Bind(
                wx.EVT_MENU, lambda evt, label=label: self.onTraceShown(label), item
            )
        menu.AppendSeparator()
        only = menu.AppendCheckItem(-1, "Active Only")
        only.Check(self.activeTraceOnly)
        every = menu.Append(-1, "Selected")
        every.Enable(bool(hidden - {active}))
        self.controlbar.Bind(
            wx.EVT_MENU,
            lambda evt: self.setHiddenTraces(self.hiddenTraces, not self.activeTraceOnly),
            only,
        )
        self.controlbar.Bind(wx.EVT_MENU, lambda evt: self.setHiddenTraces(set()), every)
        self._popupUnder(self.tracesButt, menu)

    # ----

    def onTraceShown(self, label):
        """Draw or hide a trace; only the active one drawn becomes a choice."""

        hidden = self.hiddenTraces
        if self.activeTraceOnly:
            active = self.activeTraceIndex()
            hidden = {
                self.traceLabel(trace)
                for index, trace in enumerate(self.traces())
                if index != active
            }
        self.setHiddenTraces(hidden ^ {label})

    # ----

    def setHiddenTraces(self, labels, activeOnly=False):
        """Hide the traces of these labels (or all but the active one)."""

        self.hiddenTraces = set(labels)
        self.activeTraceOnly = activeOnly
        self.updateChromatogram(keepView=True)
        self.highlightCurrentScan()

    # ----

    def onTraceButton(self, index):
        """Browse another acquisition, at the same retention time.

        A combined spectrum is made again from the new trace's scans under the
        same range; otherwise the new trace's scan nearest the shown one loads.
        """

        document = self.currentDocument
        traces = self.traces()
        if document is None or not 0 <= index < len(traces) or index == self.activeTraceIndex():
            self.refreshSelection()
            return

        trace = traces[index]
        combined = document.combined
        if combined and combined.get("rtRange"):
            # another trace's fragment spectra may be of other precursors: ask
            self.combineRange(combined["rtRange"][0], combined["rtRange"][1], trace)
        else:
            meta = (document.scanlist or {}).get(document.currentScanID) or {}
            rt = meta.get("retentionTime")
            scanID = self.nearestScan(rt if rt is not None else 0.0, trace)
            if scanID is not None and scanID != document.currentScanID:
                self.parent.selectChromatogramScan(document, scanID)

        # a switch that did not happen leaves the buttons where they were
        self.refreshSelection()

    # ----

    def updateCombineButton(self):
        """Name the way ranges are combined on its button."""

        label = "Sum" if config.main["chromatogramCombine"] == "sum" else "Average"
        self.combineButt.SetLabel(label + MENU_MARK)

    # ----

    def onCombineMenu(self, evt):
        """Choose whether ranges are averaged or summed."""

        menu = wx.Menu()
        for mode, label in (("average", "Average Scans"), ("sum", "Sum Scans")):
            item = menu.AppendRadioItem(-1, label)
            item.Check(config.main["chromatogramCombine"] == mode)
            self.controlbar.Bind(
                wx.EVT_MENU, lambda evt, mode=mode: self.onCombineModeChanged(mode), item
            )
        self._popupUnder(self.combineButt, menu)

    # ----

    def onCombineModeChanged(self, mode):
        """Average or sum ranges; a combined spectrum shown is made again."""

        if mode == config.main["chromatogramCombine"]:
            return
        config.main["chromatogramCombine"] = mode
        self.updateCombineButton()

        document = self.currentDocument
        if document is not None and document.combined and document.combined.get("rtRange"):
            start, end = document.combined["rtRange"]
            self.combineRange(start, end, precursor=document.combined.get("precursorMZ"))

    # ----

    def onExtractMenu(self, evt):
        """Offer the combined spectrum and the scan picker."""

        document = self.currentDocument
        menu = wx.Menu()
        combined = menu.Append(-1, "Combined Spectrum")
        combined.Enable(bool(document is not None and document.combined))
        scans = menu.Append(-1, "Scans...")
        scans.Enable(document is not None)
        self.controlbar.Bind(wx.EVT_MENU, self.onExtractCombined, combined)
        self.controlbar.Bind(wx.EVT_MENU, self.onExtractScans, scans)
        self._popupUnder(self.extractButt, menu)

    # ----

    def onExtractScans(self, evt):
        """Open the classic scan picker to extract individual scans."""

        if self.currentDocument is not None:
            self.parent.onExtractScansFromChromatogram(self.currentDocument)

    # ----

    def onExtractCombined(self, evt):
        """Keep the combined spectrum shown as its own document."""

        if self.currentDocument is not None:
            self.parent.onExtractCombinedSpectrum(self.currentDocument)

    # ----

    def onCanvasLMD(self, evt):
        """Remember where a click or range starts, then let the canvas have it."""

        x, y = evt.GetPosition()
        minX, minY, maxX, maxY = self.canvas.plotCoords
        inside = minX < x < maxX and minY < y < maxY
        onEdge = self.canvas._rangeEdgeAt(x) is not None if inside else False
        self._press = (x, inside and not onEdge and not evt.ControlDown())
        evt.Skip()

    # ----

    def onCanvasLMU(self, evt):
        """Load the scan nearest to a click, or combine the scans of a range.

        Whether the mouse was dragged is decided from where the button went
        down and came up, not only from the canvas's own drag: the canvas gives
        a drag up when the window system says the pointer left or was taken
        away mid-drag (which Wayland may do), and a drag it gave up must not
        turn into a click on whatever scan lies under the release.
        """

        press = self._press
        self._press = None

        if self.currentDocument is None:
            self.canvas.onLMU(evt)
            return

        # read the click and the dragged range before the canvas clears them
        position = self.canvas.getCursorPosition()
        dragged = self.canvas.getDistanceRange()
        edited = self.canvas.getEditedRange()
        self.canvas.onLMU(evt)

        release = evt.GetPosition()[0]
        moved = press is not None and abs(release - press[0]) >= MIN_RANGE_PIXELS

        # an edge of the combined range moved: combine the new range
        if edited:
            combined = self.currentDocument.combined or {}
            start, end = edited
            x1 = self.canvas.positionUserToScreen((start, 0))[0]
            x2 = self.canvas.positionUserToScreen((end, 0))[0]
            before = combined.get("rtRange") or (None, None)
            unchanged = before[0] is not None and all(
                abs(self.canvas.positionUserToScreen((old / 60.0, 0))[0] - new) < 1
                for old, new in zip(before, (x1, x2), strict=True)
            )
            if x2 - x1 >= MIN_RANGE_PIXELS and not unchanged:
                self.combineRange(start * 60.0, end * 60.0, precursor=combined.get("precursorMZ"))
            self.highlightCurrentScan()
            return

        if dragged and dragged[1] >= MIN_RANGE_PIXELS:
            (start, end), _pixels = dragged
            self.combineRange(min(start, end) * 60.0, max(start, end) * 60.0)
            return

        # a range drag the canvas lost on the way
        if moved and not dragged and press is not None and press[1]:
            minX, _minY, maxX, _maxY = self.canvas.plotCoords
            x1 = self.canvas.positionScreenToUser((press[0], 0))[0]
            x2 = self.canvas.positionScreenToUser((min(max(release, minX), maxX), 0))[0]
            self.combineRange(min(x1, x2) * 60.0, max(x1, x2) * 60.0)
            return

        # a drag is never a click
        if moved or not position:
            return

        retention = position[0] * 60.0
        scanID = self.nearestScan(retention, self.activeTrace())
        if scanID is not None and scanID != self.currentDocument.currentScanID:
            self.parent.selectChromatogramScan(self.currentDocument, scanID)

    # ----

    def activeTrace(self):
        """The trace browsed, or None for a run without chromatogram traces."""

        index = self.activeTraceIndex()
        if index is None:
            return None
        return self.traces()[index]

    # ----

    def combineRange(self, start, end, trace=None, precursor=None):
        """Combine the scans of a trace within a retention range (seconds).

        A range holding a single scan is still a range (of one scan), so it
        stays shaded with edges that can be dragged wider. On a trace of
        fragment spectra only spectra of one precursor are combined: those of
        `precursor` (m/z) when given, which is how a combined spectrum is made
        again over a changed range; otherwise the user picks one when the range
        holds several (see choosePrecursor).
        """

        document = self.currentDocument
        trace = trace or self.activeTrace()
        if document is None or trace is None:
            wx.Bell()
            return

        # the range never reaches past the run
        times = [
            meta["retentionTime"]
            for meta in (document.scanlist or {}).values()
            if meta.get("retentionTime") is not None
        ]
        if times:
            start = max(start, min(times))
            end = min(end, max(times))

        scanIDs = doc.scansInRange(document.scanlist or {}, trace["key"], start, end)
        if scanIDs and (trace.get("msLevel") or 1) > 1:
            groups = doc.precursorGroups(document.scanlist or {}, scanIDs)
            scanIDs = self.choosePrecursor(groups, precursor)
            if scanIDs is False:
                return
        if not scanIDs:
            wx.Bell()
            return

        self.parent.combineChromatogramScans(document, scanIDs, (start, end), trace["key"])

    # ----

    def choosePrecursor(self, groups, precursor=None):
        """Scan IDs of the one precursor to combine; None if there is none, False
        if the user cancelled.

        groups come from doc.precursorGroups. With `precursor` (m/z) the group
        of that precursor is taken without asking. Otherwise a single group is
        taken, and among several the user chooses, starting from the precursor
        of the fragment spectrum shown.
        """

        if precursor is not None:
            for mz, scanIDs in groups:
                if mz is not None and abs(mz - precursor) <= doc.PRECURSOR_TOLERANCE:
                    return scanIDs
            return None

        if len(groups) == 1:
            return groups[0][1]

        shown = None
        spectrum = self.currentDocument.spectrum if self.currentDocument else None
        if spectrum is not None and (spectrum.msLevel or 1) > 1:
            shown = spectrum.precursorMZ

        choices = []
        selection = 0
        for index, (mz, scanIDs) in enumerate(groups):
            name = "m/z %.2f" % mz if mz is not None else "unknown precursor"
            choices.append("%s   (%s)" % (name, doc.scansText(len(scanIDs))))
            if shown is not None and mz is not None and abs(mz - shown) <= doc.PRECURSOR_TOLERANCE:
                selection = index

        dlg = wx.SingleChoiceDialog(
            self,
            "The range holds fragment spectra of %d precursors.\nCombine the spectra of:"
            % len(groups),
            "Choose Precursor",
            choices,
        )
        dlg.SetSelection(selection)
        chosen = False
        if dlg.ShowModal() == wx.ID_OK:
            chosen = groups[dlg.GetSelection()][1]
        dlg.Destroy()

        return chosen

    # ----

    def nearestScan(self, retention, trace=None):
        """Return the ID of the scan closest to a retention time.

        With a trace, only that trace's scans are candidates. Without one (a run
        with no MS1 traces), MS1 scans are preferred, then any scan.
        """

        if self.currentDocument is None:
            return None

        scanlist = self.currentDocument.scanlist or {}

        def closest(candidates):
            best = None
            bestDiff = None
            for scanID in candidates:
                rt = scanlist[scanID].get("retentionTime")
                if rt is None:
                    continue
                diff = abs(rt - retention)
                if bestDiff is None or diff < bestDiff:
                    bestDiff = diff
                    best = scanID
            return best

        if trace is not None:
            return closest([scanID for scanID in trace.get("scans", []) if scanID in scanlist])

        # prefer MS1 survey scans for chromatogram navigation
        best = closest(
            [scanID for scanID, meta in scanlist.items() if meta.get("msLevel") in (None, 1)]
        )
        if best is None:
            best = closest(list(scanlist))
        return best

    # ----
