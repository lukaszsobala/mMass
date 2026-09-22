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

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUndefinedVariable=false
# ruff: noqa: F403, F405

# load libs
import bisect
import wx

# load modules
from .ids import *
from . import mwx
from . import images
from . import config
from . import doc
from . import differences
import mspy
import mspy.plot

# SPECTRUM APPEARANCE
# -------------------


def applyCanvasConfig(canvas):
    """Set how a spectrum canvas looks from the spectrum config.

    Shared with images made outside the GUI (mmass convert), so they look like
    the ones exported from the panel.
    """

    canvas.setProperties(xLabel=config.spectrum["xLabel"])
    canvas.setProperties(yLabel=config.spectrum["yLabel"])
    if config.spectrum["normalize"]:
        canvas.setProperties(yLabel="r. int. (%)")
    canvas.setProperties(showZero=True)
    canvas.setProperties(gelHeight=config.spectrum["gelHeight"])
    canvas.setProperties(rulerColour=tuple(config.differenceRuler["colour"]))
    canvas.setProperties(xPosDigits=config.main["mzDigits"])
    canvas.setProperties(yPosDigits=config.main["intDigits"])
    canvas.setProperties(distanceDigits=config.main["mzDigits"])
    canvas.setProperties(overlapLabels=config.spectrum["overlapLabels"])
    canvas.setProperties(checkLimits=config.spectrum["checkLimits"])
    canvas.setProperties(autoScaleY=config.spectrum["autoscale"])
    canvas.setProperties(showGel=config.spectrum["showGel"])
    canvas.setProperties(showXPosBar=config.spectrum["showPosBars"])
    canvas.setProperties(showYPosBar=config.spectrum["showPosBars"])
    canvas.setProperties(posBarSize=config.spectrum["posBarSize"])
    canvas.setProperties(showLegend=config.spectrum["showLegend"])
    canvas.setProperties(showGrid=config.spectrum["showGrid"])
    canvas.setProperties(showMinorTicks=config.spectrum["showMinorTicks"])
    canvas.setProperties(reverseDrawing=True)
    canvas.setProperties(filterSize=config.spectrum.get("filterSize", 1.0))

    axisFont = wx.Font(
        config.spectrum["axisFontSize"],
        wx.SWISS,
        wx.FONTSTYLE_NORMAL,
        wx.FONTWEIGHT_NORMAL,
        0,
    )
    canvas.setProperties(axisFont=axisFont)


def rulerText(names, diff, charge=1, theoretical=None, mzs=None):
    """Text of a difference ruler, as the difference ruler settings say."""

    settings = config.differenceRuler
    if settings["labelShort"]:
        names = differences.shortenNames(names)
    return differences.rulerText(
        names,
        diff,
        charge,
        theoretical,
        mzs,
        options={key: settings[key] for key in differences.LABEL_DEFAULTS},
        units=settings["units"],
        digits=config.main["mzDigits"],
        ppmDigits=config.main["ppmDigits"],
    )


def labelText(ruler):
    """Text a difference label shows: the user's own, with the fields it
    names filled in (see differences.expandNote), else made from its match."""

    if ruler.note:
        names = ruler.label
        if config.differenceRuler["labelShort"]:
            names = differences.shortenNames(names)
        return differences.expandNote(
            ruler.note,
            names,
            ruler.diff,
            ruler.charge,
            ruler.theoretical,
            (ruler.mz1, ruler.mz2),
            config.differenceRuler["units"],
            config.main["mzDigits"],
            config.main["ppmDigits"],
        )
    return rulerText(
        ruler.label, ruler.diff, ruler.charge, ruler.theoretical, (ruler.mz1, ruler.mz2)
    )


def matchRuler(diff, charge=1, mzs=None):
    """Difference list entries matching a ruler, as the settings say.

    mzs are the m/z of the ruler's two ends, which a ppm tolerance is applied
    at. Without a single entry that matches, pairs of them are (for lists
    that have their pairs matched), and without those whole multiples of one
    (e.g. 3xMe, see matchMultiples).
    """

    settings = config.differenceRuler
    arguments = (
        settings["tolerance"],
        settings["massType"],
        charge,
        settings["units"],
        mzs,
    )

    # fewer, larger units win: a single entry over a pair of them (Q over
    # A+G), and either over a multiple of a smaller one (Ac over 3xMe)
    lists = settings["lists"]
    singles = differences.entries(lists, pairs=False)
    return (
        differences.match(diff, singles, *arguments)
        or differences.match(diff, differences.entries(lists, singles=False), *arguments)
        or differences.matchMultiples(diff, singles, *arguments)
    )


def applySpectrumConfig(spectrum, docData, current=True):
    """Set how a document's plot spectrum looks from the spectrum config.

    current tells whether it is the selected document, whose labels are
    always shown and whose ticks use the tick colour.
    """

    spectrum.setProperties(legend=docData.title)
    spectrum.setProperties(visible=docData.visible)
    spectrum.setProperties(flipped=docData.flipped)
    spectrum.setProperties(xOffset=docData.offset[0])
    spectrum.setProperties(yOffset=docData.offset[1])
    spectrum.setProperties(normalized=config.spectrum["normalize"])
    spectrum.setProperties(xOffsetDigits=config.main["mzDigits"])
    spectrum.setProperties(yOffsetDigits=config.main["intDigits"])

    spectrum.setProperties(showInGel=True)
    spectrum.setProperties(showSpectrum=True)
    spectrum.setProperties(showTicks=config.spectrum["showTicks"])
    spectrum.setProperties(showPoints=config.spectrum["showDataPoints"])
    spectrum.setProperties(showGelLegend=config.spectrum["showGelLegend"])
    spectrum.setProperties(spectrumColour=docData.colour)
    spectrum.setProperties(spectrumStyle=docData.style)

    spectrum.setProperties(labelAngle=config.spectrum["labelAngle"])
    spectrum.setProperties(labelCharge=config.spectrum["labelCharge"])
    spectrum.setProperties(labelGroup=config.spectrum["labelGroup"])
    spectrum.setProperties(labelDigits=config.main["mzDigits"])
    spectrum.setProperties(labelBgr=config.spectrum["labelBgr"])
    spectrum.setProperties(isotopeColour=None)

    labelFont = wx.Font(
        config.spectrum["labelFontSize"],
        wx.SWISS,
        wx.FONTSTYLE_NORMAL,
        wx.FONTWEIGHT_NORMAL,
        0,
    )
    spectrum.setProperties(labelFont=labelFont)

    # difference rulers (for an LC-MS run, those drawn on the scan shown)
    scanID = docData.currentScanID if docData.islcms() else None
    rulers = []
    for index, ruler in enumerate(getattr(docData, "rulers", [])):
        if ruler.scanID is not None and ruler.scanID != scanID:
            continue
        text = labelText(ruler)
        rulers.append(
            (
                ruler.mz1,
                ruler.ai1,
                ruler.mz2,
                ruler.ai2,
                text,
                index,
                ruler.height,
                ruler.colour,
            )
        )
    spectrum.setProperties(rulers=rulers)
    spectrum.setProperties(showRulers=bool(config.differenceRuler["show"]))
    spectrum.setProperties(hiddenRuler=None)
    spectrum.setProperties(rulerColour=tuple(config.differenceRuler["colour"]))

    if current:
        spectrum.setProperties(showLabels=config.spectrum["showLabels"])
        spectrum.setProperties(tickColour=config.spectrum["tickColour"])
    else:
        spectrum.setProperties(
            showLabels=(
                config.spectrum["showLabels"] and config.spectrum["showAllLabels"]
            )
        )
        spectrum.setProperties(tickColour=docData.colour)


# SPECTRUM PANEL WITH CANVAS AND TOOLBAR
# --------------------------------------


class panelSpectrum(wx.Panel):
    """Make spectrum panel."""

    def __init__(self, parent, documents):
        wx.Panel.__init__(
            self, parent, -1, size=(100, 100), style=wx.NO_FULL_REPAINT_ON_RESIZE
        )

        self.parent = parent

        self.documents = documents
        self.currentDocument = None
        self.currentTmpSpectrum = None
        self.currentTmpSpectrumFlip = False
        self.currentTmpSpectrumStyle = {}
        self.currentNotationMarks = None
        self.currentTool = "ruler"
        self.canvasPropertiesDlg = None

        # m/z of the current document's peaks, for snapping the difference
        # ruler; rebuilt whenever the peaklist it was made from changes
        self._peakMzs = None
        self._peakMzsKey = None

        # init container
        self.container = mspy.plot.container([])
        obj = mspy.plot.points([], showInGel=False)
        self.container.append(obj)
        obj = mspy.plot.points([], showInGel=False)
        self.container.append(obj)

        # make GUI
        self.makeGUI()

        # select default tool
        self.setCurrentTool(self.currentTool)

    # ----

    def makeGUI(self):
        """Make GUI elements."""

        # init spectrum canvas
        self.makeSpectrumCanvas()

        # init toolbar
        toolbar = self.makeToolbar()

        # pack gui elements
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.spectrumCanvas, 1, wx.EXPAND)
        sizer.Add(toolbar, 0, wx.EXPAND)

        # fit layout
        sizer.Fit(self)
        self.SetSizer(sizer)

    # ----

    def makeSpectrumCanvas(self):
        """Make plot canvas and set defalt parameters."""

        # init canvas
        self.spectrumCanvas = mspy.plot.canvas(self, style=mwx.PLOTCANVAS_STYLE_PANEL)
        self.spectrumCanvas.draw(self.container)

        # set default params
        applyCanvasConfig(self.spectrumCanvas)
        self.spectrumCanvas.setProperties(showCurXPos=True)
        self.spectrumCanvas.setProperties(showCurYPos=True)
        self.spectrumCanvas.setProperties(showCurCharge=True)
        self.spectrumCanvas.setProperties(
            showCurImage=config.spectrum["showCursorImage"]
        )
        self.spectrumCanvas.setProperties(zoomAxis="x")
        self.spectrumCanvas.setProperties(
            reverseScrolling=config.main["reverseScrolling"]
        )
        self.spectrumCanvas.setProperties(
            rulerColour=tuple(config.differenceRuler["colour"])
        )
        self.spectrumCanvas.setSnapFunction(self.getSnapCandidates)
        self.spectrumCanvas.setRulerLabelFunction(self.getRulerText)
        self.spectrumCanvas.setRulerSeriesFunction(self.getRulerSeriesText)
        self.spectrumCanvas.setRulerPlacedFunction(self.getRulerObstacles)
        self.spectrumCanvas.setRulerLabelBoxesFunction(
            lambda: getattr(self.container, "labelBoxes", [])
        )
        self.spectrumCanvas.setRulerGrabFunction(self.grabRuler)

        # set events
        self.spectrumCanvas.Bind(wx.EVT_MOTION, self.onCanvasMMotion)
        self.spectrumCanvas.Bind(wx.EVT_MOUSEWHEEL, self.onCanvasMScroll)
        self.spectrumCanvas.Bind(wx.EVT_LEFT_UP, self.onCanvasLMU)
        self.spectrumCanvas.Bind(wx.EVT_RIGHT_UP, self.onCanvasRMU)
        self.spectrumCanvas.Bind(wx.EVT_LEFT_DCLICK, self.onCanvasLDClick)
        self.spectrumCanvas.Bind(wx.EVT_KEY_DOWN, self.onCanvasKey)

        # set DnD
        dropTarget = fileDropTarget(self.parent.onDocumentDropped)
        self.spectrumCanvas.SetDropTarget(dropTarget)

    # ----

    def makeToolbar(self):
        """Make bottom toolbar."""

        # init toolbar panel (bgrPanel drops the sprite for a flat fill in dark
        # mode itself, and can swap between the two on a live theme switch)
        panel = mwx.bgrPanel(
            self, -1, images.lib["bgrBottombar"], size=(-1, mwx.BOTTOMBAR_HEIGHT)
        )

        # make canvas toolset
        image = (images.lib["spectrumLabelsOff"], images.lib["spectrumLabelsOn"])[
            config.spectrum["showLabels"]
        ]
        self.showLabels_butt = mwx.makeBitmapButton(
            panel,
            ID_viewLabels,
            image,
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.showLabels_butt.SetToolTip(wx.ToolTip("Show / hide labels"))
        self.showLabels_butt.Bind(wx.EVT_BUTTON, self.parent.onView)

        image = (images.lib["spectrumTicksOff"], images.lib["spectrumTicksOn"])[
            config.spectrum["showTicks"]
        ]
        self.showTicks_butt = mwx.makeBitmapButton(
            panel,
            ID_viewTicks,
            image,
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.showTicks_butt.SetToolTip(wx.ToolTip("Show / hide ticks"))
        self.showTicks_butt.Bind(wx.EVT_BUTTON, self.parent.onView)

        image = (images.lib["spectrumNotationsOff"], images.lib["spectrumNotationsOn"])[
            config.spectrum["showNotations"]
        ]
        self.showNotations_butt = mwx.makeBitmapButton(
            panel,
            ID_viewNotations,
            image,
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.showNotations_butt.SetToolTip(wx.ToolTip("Show / hide notations"))
        self.showNotations_butt.Bind(wx.EVT_BUTTON, self.parent.onView)

        image = (images.lib["spectrumDiffLabelsOff"], images.lib["spectrumDiffLabelsOn"])[
            bool(config.differenceRuler["show"])
        ]
        self.showDiffLabels_butt = mwx.makeBitmapButton(
            panel,
            ID_viewDiffLabels,
            image,
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.showDiffLabels_butt.SetToolTip(wx.ToolTip("Show / hide difference labels"))
        self.showDiffLabels_butt.Bind(wx.EVT_BUTTON, self.parent.onView)

        image = (
            images.lib["spectrumLabelAngleOff"],
            images.lib["spectrumLabelAngleOn"],
        )[bool(config.spectrum["labelAngle"])]
        self.labelAngle_butt = mwx.makeBitmapButton(
            panel,
            ID_viewLabelAngle,
            image,
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.labelAngle_butt.SetToolTip(wx.ToolTip("Labels orientation"))
        self.labelAngle_butt.Bind(wx.EVT_BUTTON, self.parent.onView)

        image = (images.lib["spectrumPosBarsOff"], images.lib["spectrumPosBarsOn"])[
            config.spectrum["showPosBars"]
        ]
        self.showPosBars_butt = mwx.makeBitmapButton(
            panel,
            ID_viewPosBars,
            image,
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.showPosBars_butt.SetToolTip(wx.ToolTip("Show / hide position bars"))
        self.showPosBars_butt.Bind(wx.EVT_BUTTON, self.parent.onView)

        image = (images.lib["spectrumGelOff"], images.lib["spectrumGelOn"])[
            config.spectrum["showGel"]
        ]
        self.showGel_butt = mwx.makeBitmapButton(
            panel,
            ID_viewGel,
            image,
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.showGel_butt.SetToolTip(wx.ToolTip("Show / hide gel"))
        self.showGel_butt.Bind(wx.EVT_BUTTON, self.parent.onView)

        image = (images.lib["spectrumTrackerOff"], images.lib["spectrumTrackerOn"])[
            config.spectrum["showTracker"]
        ]
        self.showTracker_butt = mwx.makeBitmapButton(
            panel,
            ID_viewTracker,
            image,
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.showTracker_butt.SetToolTip(wx.ToolTip("Show / hide cursor tracker"))
        self.showTracker_butt.Bind(wx.EVT_BUTTON, self.parent.onView)

        image = (images.lib["spectrumAutoscaleOff"], images.lib["spectrumAutoscaleOn"])[
            config.spectrum["autoscale"]
        ]
        self.autoscale_butt = mwx.makeBitmapButton(
            panel,
            ID_viewAutoscale,
            image,
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.autoscale_butt.SetToolTip(wx.ToolTip("Autoscale intensity"))
        self.autoscale_butt.Bind(wx.EVT_BUTTON, self.parent.onView)

        image = (images.lib["spectrumNormalizeOff"], images.lib["spectrumNormalizeOn"])[
            config.spectrum["normalize"]
        ]
        self.normalize_butt = mwx.makeBitmapButton(
            panel,
            ID_viewNormalize,
            image,
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.normalize_butt.SetToolTip(wx.ToolTip("Normalize intensity"))
        self.normalize_butt.Bind(wx.EVT_BUTTON, self.parent.onView)

        # make processing toolset
        self.toolsRuler_butt = mwx.makeBitmapButton(
            panel,
            ID_toolsRuler,
            images.lib["spectrumRulerOff"],
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.toolsRuler_butt.SetToolTip(wx.ToolTip("Spectrum ruler"))
        self.toolsRuler_butt.Bind(wx.EVT_BUTTON, self.parent.onToolsSpectrum)

        self.toolsDiffRuler_butt = mwx.makeBitmapButton(
            panel,
            ID_toolsDiffRuler,
            images.lib["spectrumDiffRulerOff"],
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.toolsDiffRuler_butt.SetToolTip(
            wx.ToolTip(
                "Label difference between peaks\n"
                "Right-click for options"
            )
        )
        self.toolsDiffRuler_butt.Bind(wx.EVT_BUTTON, self.parent.onToolsSpectrum)
        self.toolsDiffRuler_butt.Bind(wx.EVT_RIGHT_UP, self.onDiffRulerMenu)

        self.toolsLabelPeak_butt = mwx.makeBitmapButton(
            panel,
            ID_toolsLabelPeak,
            images.lib["spectrumLabelPeakOff"],
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.toolsLabelPeak_butt.SetToolTip(
            wx.ToolTip(
                "Label peak\n"
                "Shift-drag to label the highest peak in the range in all "
                "visible spectra"
            )
        )
        self.toolsLabelPeak_butt.Bind(wx.EVT_BUTTON, self.parent.onToolsSpectrum)

        self.toolsLabelPoint_butt = mwx.makeBitmapButton(
            panel,
            ID_toolsLabelPoint,
            images.lib["spectrumLabelPointOff"],
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.toolsLabelPoint_butt.SetToolTip(wx.ToolTip("Label point"))
        self.toolsLabelPoint_butt.Bind(wx.EVT_BUTTON, self.parent.onToolsSpectrum)

        self.toolsLabelEnvelope_butt = mwx.makeBitmapButton(
            panel,
            ID_toolsLabelEnvelope,
            images.lib["spectrumLabelEnvelopeOff"],
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.toolsLabelEnvelope_butt.SetToolTip(wx.ToolTip("Label envelope"))
        self.toolsLabelEnvelope_butt.Bind(wx.EVT_BUTTON, self.parent.onToolsSpectrum)

        self.toolsDeleteLabel_butt = mwx.makeBitmapButton(
            panel,
            ID_toolsDeleteLabel,
            images.lib["spectrumDeleteLabelOff"],
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.toolsDeleteLabel_butt.SetToolTip(wx.ToolTip("Delete label"))
        self.toolsDeleteLabel_butt.Bind(wx.EVT_BUTTON, self.parent.onToolsSpectrum)

        self.toolsOffset_butt = mwx.makeBitmapButton(
            panel,
            ID_toolsOffset,
            images.lib["spectrumOffsetOff"],
            size=(mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.toolsOffset_butt.SetToolTip(wx.ToolTip("Offset spectrum"))
        self.toolsOffset_butt.Bind(wx.EVT_BUTTON, self.parent.onToolsSpectrum)

        # make cursor info
        self.cursorInfo = wx.StaticText(panel, -1, "")
        self.cursorInfo.SetFont(wx.SMALL_FONT)
        self.cursorInfo.Bind(wx.EVT_RIGHT_UP, self.onCursorInfoRMU)
        self._lastCursorLabel = ""

        # pack elements
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.AddSpacer(mwx.BOTTOMBAR_LSPACE)
        sizer.Add(self.showLabels_butt, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(
            self.showTicks_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.showNotations_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.showDiffLabels_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.labelAngle_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.showPosBars_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.showGel_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.showTracker_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.autoscale_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.normalize_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.AddSpacer(20)
        sizer.Add(
            self.toolsRuler_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.toolsDiffRuler_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.toolsLabelPeak_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.toolsLabelPoint_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.toolsLabelEnvelope_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.toolsDeleteLabel_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.toolsOffset_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.AddSpacer(20)
        sizer.Add(self.cursorInfo, 0, wx.ALIGN_CENTER_VERTICAL, 0)
        sizer.AddSpacer(mwx.BOTTOMBAR_RSPACE)

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        mainSizer.Add(sizer, 1, wx.EXPAND)

        panel.SetSizer(mainSizer)
        mainSizer.Fit(panel)

        return panel

    # ----

    def onCanvasMMotion(self, evt):
        """Update cursor info on mouse motion."""

        # update cursor
        self.spectrumCanvas.onMMotion(evt)
        self.updateCursorInfo()

    # ----

    def onCanvasMScroll(self, evt):
        """Update cursor info on mouse scroll."""

        # update cursor
        self.spectrumCanvas.onMScroll(evt)
        self.updateCursorInfo()

    # ----

    def onCanvasLMU(self, evt):
        """Process selected mouse function."""

        # check document
        if self.currentDocument is None:
            evt.Skip()
            if self.currentTool not in ("ruler"):
                wx.Bell()
            return

        # get cursor positions
        selection = self.spectrumCanvas.getSelectionBox()
        # keep the raw (canvas-space) selection box: labelling a peak in every
        # visible spectrum converts the x range per document using each
        # document's own offset, rather than only the current document's like
        # the single-document branches below
        rawSelection = selection
        position = self.spectrumCanvas.getCursorPosition()
        distance = self.spectrumCanvas.getDistance()
        isotopes = self.spectrumCanvas.getIsotopes()
        charge = self.spectrumCanvas.getCharge()
        ruler = self.spectrumCanvas.getRuler()
        rulerEdit = self.spectrumCanvas.getRulerEdit()
        rulerHeight = self.spectrumCanvas.getRulerBarHeight()
        self.spectrumCanvas.endRulerEdit()

        # sent event back to canvas
        self.spectrumCanvas.onLMU(evt)

        # convert selection for flipped documents
        if selection and self.documents[self.currentDocument].flipped:
            y1 = -1 * selection[1]
            y2 = -1 * selection[3]
            selection = (selection[0], y2, selection[2], y1)

        # convert normalized selection to real values
        if selection and config.spectrum["normalize"]:
            f = self.documents[self.currentDocument].spectrum.normalization()
            y1 = selection[1] * f
            y2 = selection[3] * f
            selection = (selection[0], y1, selection[2], y2)

        # convert selection for offset documents
        if selection and not config.spectrum["normalize"]:
            x1 = selection[0] - self.documents[self.currentDocument].offset[0]
            x2 = selection[2] - self.documents[self.currentDocument].offset[0]
            y1 = selection[1] - self.documents[self.currentDocument].offset[1]
            y2 = selection[3] - self.documents[self.currentDocument].offset[1]
            selection = (x1, y1, x2, y2)

        # label peak; with Shift, in every visible spectrum
        if self.currentTool == "labelpeak" and selection and evt.ShiftDown():
            self.labelPeakMulti(rawSelection)
        elif self.currentTool == "labelpeak" and selection:
            self.labelPeak(selection)

        # move an end of a difference ruler (with Shift, making it a series)
        elif self.currentTool == "diffruler" and ruler and rulerEdit is not None:
            height = None
            if rulerHeight is not None:
                height = self._toReal((0, rulerHeight))[1]
            if not (evt.ShiftDown() and self.addRulerSeries(*ruler, height=height, replace=rulerEdit)):
                self.moveRuler(rulerEdit, *ruler, height=height)

        # lift or lower a difference ruler, or show it again where it was
        elif self.currentTool == "diffruler" and rulerEdit is not None:
            if rulerHeight is not None:
                self.setRulerHeight(rulerEdit, self._toReal((0, rulerHeight))[1])
            else:
                self.refresh(keepScale=True)

        # add difference ruler, its bar where it was drawn; with Shift, label
        # every step of a series between the two peaks
        elif self.currentTool == "diffruler" and ruler:
            height = None
            if rulerHeight is not None:
                height = self._toReal((0, rulerHeight))[1]
            if not (evt.ShiftDown() and self.addRulerSeries(*ruler, height=height)):
                self.addRuler(*ruler, height=height)

        # label point
        elif self.currentTool == "labelpoint" and position:
            self.labelPoint(position[0])

        # label isotopes
        elif self.currentTool == "labelenvelope" and isotopes:
            self.labelEnvelope(isotopes, charge)

        # delete peaks
        elif self.currentTool == "deletelabel" and selection:
            self.deleteLabel(selection)

        # offset spectrum
        elif self.currentTool == "offset" and distance and distance != [0, 0]:
            if not config.spectrum["normalize"]:
                if self.documents[self.currentDocument].flipped:
                    self.documents[self.currentDocument].offset[1] -= distance[1]
                else:
                    self.documents[self.currentDocument].offset[1] += distance[1]
                self.updateSpectrumProperties(self.currentDocument)
            else:
                wx.Bell()

        else:
            evt.Skip()

    # ----

    def onCanvasRMU(self, evt):
        """Show the difference ruler menu on a right click (not a zoom drag)."""

        start = self.spectrumCanvas.draggingStart
        clicked = (
            self.currentTool == "diffruler"
            and self.spectrumCanvas.mouseEvent in ("zoom", False)
            and start
            and abs(evt.GetPosition()[0] - start[2]) < 3
            and abs(evt.GetPosition()[1] - start[3]) < 3
            and self.spectrumCanvas.getCursorLocation() == "plot"
        )

        # sent event back to canvas
        self.spectrumCanvas.onRMU(evt)

        if not clicked:
            return

        hit = self.rulerAt(*evt.GetPosition())
        if hit is None:
            self.onDiffRulerMenu()
        else:
            self.onRulerMenu(hit[0])

    # ----

    def onCanvasProperties(self, evt=None):
        """Show canvas properties dialog."""

        # reuse an already-open dialog rather than stacking a second one
        dlg = self.canvasPropertiesDlg
        if dlg:
            dlg.Raise()
            return

        # show modeless so the user can still pan/zoom/move the spectrum while
        # the dialog is open (ShowModal would block the whole main window)
        self.canvasPropertiesDlg = dlgCanvasProperties(
            self.parent,
            self.updateCanvasProperties,
            onCloseFn=self._onCanvasPropertiesClosed,
        )
        self.canvasPropertiesDlg.Show()

    # ----

    def _onCanvasPropertiesClosed(self):
        """Clear the canvas-properties dialog reference once it is closed."""
        self.canvasPropertiesDlg = None

    # ----

    def onCursorInfoRMU(self, evt):
        """Set items to show in cursor info."""

        # difference ruler has its own options
        if self.currentTool == "diffruler":
            self.onDiffRulerMenu()
            return

        # only while active spectrum ruler
        if self.currentTool != "ruler":
            return

        # popup menu
        menu = wx.Menu()
        menu.Append(ID_viewSpectrumRulerMz, "m/z", "", wx.ITEM_CHECK)
        menu.Append(ID_viewSpectrumRulerDist, "Distance", "", wx.ITEM_CHECK)
        menu.Append(ID_viewSpectrumRulerPpm, "ppm", "", wx.ITEM_CHECK)
        menu.Append(ID_viewSpectrumRulerZ, "Charge", "", wx.ITEM_CHECK)
        menu.Append(ID_viewSpectrumRulerCursorMass, "Mass (c)", "", wx.ITEM_CHECK)
        menu.Append(ID_viewSpectrumRulerParentMass, "Mass (p)", "", wx.ITEM_CHECK)
        menu.Append(ID_viewSpectrumRulerArea, "Area", "", wx.ITEM_CHECK)

        # set values
        menu.Check(ID_viewSpectrumRulerMz, bool("mz" in config.main["cursorInfo"]))
        menu.Check(ID_viewSpectrumRulerDist, bool("dist" in config.main["cursorInfo"]))
        menu.Check(ID_viewSpectrumRulerPpm, bool("ppm" in config.main["cursorInfo"]))
        menu.Check(ID_viewSpectrumRulerZ, bool("z" in config.main["cursorInfo"]))
        menu.Check(
            ID_viewSpectrumRulerCursorMass, bool("cmass" in config.main["cursorInfo"])
        )
        menu.Check(
            ID_viewSpectrumRulerParentMass, bool("pmass" in config.main["cursorInfo"])
        )
        menu.Check(ID_viewSpectrumRulerArea, bool("area" in config.main["cursorInfo"]))

        # set events
        self.Bind(
            wx.EVT_MENU, self.parent.onViewSpectrumRuler, id=ID_viewSpectrumRulerMz
        )
        self.Bind(
            wx.EVT_MENU, self.parent.onViewSpectrumRuler, id=ID_viewSpectrumRulerDist
        )
        self.Bind(
            wx.EVT_MENU, self.parent.onViewSpectrumRuler, id=ID_viewSpectrumRulerPpm
        )
        self.Bind(
            wx.EVT_MENU, self.parent.onViewSpectrumRuler, id=ID_viewSpectrumRulerZ
        )
        self.Bind(
            wx.EVT_MENU,
            self.parent.onViewSpectrumRuler,
            id=ID_viewSpectrumRulerCursorMass,
        )
        self.Bind(
            wx.EVT_MENU,
            self.parent.onViewSpectrumRuler,
            id=ID_viewSpectrumRulerParentMass,
        )
        self.Bind(
            wx.EVT_MENU, self.parent.onViewSpectrumRuler, id=ID_viewSpectrumRulerArea
        )

        self.PopupMenu(menu)
        menu.Destroy()

    # ----

    def setCurrentTool(self, tool):
        """Slect spectrum tool."""

        # set current tool
        self.currentTool = tool

        # set icons off
        self.toolsRuler_butt.SetBitmapLabel(images.lib["spectrumRulerOff"])
        self.toolsDiffRuler_butt.SetBitmapLabel(images.lib["spectrumDiffRulerOff"])
        self.toolsLabelPeak_butt.SetBitmapLabel(images.lib["spectrumLabelPeakOff"])
        self.toolsLabelPoint_butt.SetBitmapLabel(images.lib["spectrumLabelPointOff"])
        self.toolsLabelEnvelope_butt.SetBitmapLabel(
            images.lib["spectrumLabelEnvelopeOff"]
        )
        self.toolsDeleteLabel_butt.SetBitmapLabel(images.lib["spectrumDeleteLabelOff"])
        self.toolsOffset_butt.SetBitmapLabel(images.lib["spectrumOffsetOff"])

        # set cursor tracker
        cursorTracker = None
        if config.spectrum["showTracker"]:
            cursorTracker = "cross"

        # default cursor pair (normal, tracker); overridden per tool below
        cursor = (wx.Cursor(wx.CURSOR_ARROW), wx.Cursor(wx.CURSOR_ARROW))

        # set tool
        if tool == "ruler":
            self.toolsRuler_butt.SetBitmapLabel(images.lib["spectrumRulerOn"])
            self.spectrumCanvas.setMFunction(cursorTracker)
            self.spectrumCanvas.setLMBFunction("xDistance")
            cursor = (wx.Cursor(wx.CURSOR_ARROW), images.lib["cursorsCrossMeasure"])

        elif tool == "diffruler":
            self.toolsDiffRuler_butt.SetBitmapLabel(
                images.lib["spectrumDiffRulerOn"]
            )
            self.spectrumCanvas.setMFunction(
                "crosssnap" if cursorTracker else "peaksnap"
            )
            self.spectrumCanvas.setLMBFunction("peakRuler")
            cursor = (wx.Cursor(wx.CURSOR_ARROW), images.lib["cursorsCrossMeasure"])

        elif tool == "labelpeak":
            self.toolsLabelPeak_butt.SetBitmapLabel(images.lib["spectrumLabelPeakOn"])
            self.spectrumCanvas.setMFunction(None)
            self.spectrumCanvas.setLMBFunction("range")
            cursor = (images.lib["cursorsArrowPeak"], images.lib["cursorsArrowPeak"])

        elif tool == "labelpoint":
            self.toolsLabelPoint_butt.SetBitmapLabel(images.lib["spectrumLabelPointOn"])
            self.spectrumCanvas.setMFunction(cursorTracker)
            self.spectrumCanvas.setLMBFunction("point")
            cursor = (images.lib["cursorsArrowPoint"], images.lib["cursorsCrossPoint"])

        elif tool == "labelenvelope":
            self.toolsLabelEnvelope_butt.SetBitmapLabel(
                images.lib["spectrumLabelEnvelopeOn"]
            )
            self.spectrumCanvas.setMFunction("isotoperuler")
            self.spectrumCanvas.setLMBFunction("isotopes")
            cursor = (images.lib["cursorsCrossPeak"], images.lib["cursorsCrossPeak"])

        elif tool == "deletelabel":
            self.toolsDeleteLabel_butt.SetBitmapLabel(
                images.lib["spectrumDeleteLabelOn"]
            )
            self.spectrumCanvas.setMFunction(None)
            self.spectrumCanvas.setLMBFunction("rectangle")
            cursor = (
                images.lib["cursorsArrowDelete"],
                images.lib["cursorsArrowDelete"],
            )

        elif tool == "offset":
            self.toolsOffset_butt.SetBitmapLabel(images.lib["spectrumOffsetOn"])
            self.spectrumCanvas.setMFunction(cursorTracker)
            self.spectrumCanvas.setLMBFunction("yDistance")
            cursor = (
                images.lib["cursorsArrowOffset"],
                images.lib["cursorsCrossOffset"],
            )

        # set cursor
        self.spectrumCanvas.setCursorImage(cursor[bool(config.spectrum["showTracker"])])

    # ----

    def setSpectrumProperties(self, docIndex):
        """Set spectrum properties."""

        # check document
        if docIndex is None:
            return

        applySpectrumConfig(
            self.container[docIndex + 2],
            self.documents[docIndex],
            current=(docIndex == self.currentDocument),
        )

    # ----

    def setCanvasRange(self, xAxis=None, yAxis=None):
        """Set canvas range."""
        self.spectrumCanvas.zoom(xAxis, yAxis)

    # ----

    def updateCanvasProperties(self, ID=None, refresh=True):
        """Update canvas properties."""

        # update button image
        if ID is not None:
            if ID == ID_viewLabels:
                image = (
                    images.lib["spectrumLabelsOff"],
                    images.lib["spectrumLabelsOn"],
                )[bool(config.spectrum["showLabels"])]
                self.showLabels_butt.SetBitmapLabel(image)
            elif ID == ID_viewTicks:
                image = (images.lib["spectrumTicksOff"], images.lib["spectrumTicksOn"])[
                    bool(config.spectrum["showTicks"])
                ]
                self.showTicks_butt.SetBitmapLabel(image)
            elif ID == ID_viewNotations:
                image = (
                    images.lib["spectrumNotationsOff"],
                    images.lib["spectrumNotationsOn"],
                )[bool(config.spectrum["showNotations"])]
                self.showNotations_butt.SetBitmapLabel(image)
            elif ID == ID_viewDiffLabels:
                image = (
                    images.lib["spectrumDiffLabelsOff"],
                    images.lib["spectrumDiffLabelsOn"],
                )[bool(config.differenceRuler["show"])]
                self.showDiffLabels_butt.SetBitmapLabel(image)
            elif ID == ID_viewLabelAngle:
                image = (
                    images.lib["spectrumLabelAngleOff"],
                    images.lib["spectrumLabelAngleOn"],
                )[bool(config.spectrum["labelAngle"])]
                self.labelAngle_butt.SetBitmapLabel(image)
            elif ID == ID_viewPosBars:
                image = (
                    images.lib["spectrumPosBarsOff"],
                    images.lib["spectrumPosBarsOn"],
                )[bool(config.spectrum["showPosBars"])]
                self.showPosBars_butt.SetBitmapLabel(image)
            elif ID == ID_viewGel:
                image = (images.lib["spectrumGelOff"], images.lib["spectrumGelOn"])[
                    bool(config.spectrum["showGel"])
                ]
                self.showGel_butt.SetBitmapLabel(image)
            elif ID == ID_viewTracker:
                image = (
                    images.lib["spectrumTrackerOff"],
                    images.lib["spectrumTrackerOn"],
                )[bool(config.spectrum["showTracker"])]
                self.showTracker_butt.SetBitmapLabel(image)
            elif ID == ID_viewAutoscale:
                image = (
                    images.lib["spectrumAutoscaleOff"],
                    images.lib["spectrumAutoscaleOn"],
                )[bool(config.spectrum["autoscale"])]
                self.autoscale_butt.SetBitmapLabel(image)
            elif ID == ID_viewNormalize:
                image = (
                    images.lib["spectrumNormalizeOff"],
                    images.lib["spectrumNormalizeOn"],
                )[bool(config.spectrum["normalize"])]
                self.normalize_butt.SetBitmapLabel(image)

        # set canvas properties
        applyCanvasConfig(self.spectrumCanvas)

        # set cursor tracker according to current tool
        self.setCurrentTool(self.currentTool)

        # set properties for documents
        for docIndex in range(len(self.documents)):
            self.setSpectrumProperties(docIndex)

        # update tmp spectra
        self.updateNotationMarks(self.currentNotationMarks, refresh=False)
        self.restoreTmpSpectrum()

        # redraw plot (showing or hiding the labels changes no intensities)
        if refresh:
            self.refresh(keepScale=ID == ID_viewDiffLabels)

    # ----

    def updateCursorInfo(self):
        """Update cursor info on MS scan canvas"""

        label = ""

        # get spectrum polarity
        polarity = 1
        if (
            self.currentDocument is not None
            and self.documents[self.currentDocument].spectrum.polarity == -1
        ):
            polarity = -1
            return

        # get baseline window (for area calculation)
        baselineWindow = 1.0
        if config.processing["peakpicking"]["baseline"]:
            baselineWindow = 1.0 / config.processing["baseline"]["precision"]

        # get basic values
        position = self.spectrumCanvas.getCursorPosition()
        distance = self.spectrumCanvas.getDistance()

        # format numbers
        mzFormat = "%0." + repr(config.main["mzDigits"]) + "f"
        intFormat = "%0." + repr(config.main["intDigits"]) + "f"
        distFormat = "%0." + repr(config.main["mzDigits"]) + "f"
        ppmFormat = "%0." + repr(config.main["ppmDigits"]) + "f"
        areaFormat = "%0." + repr(config.main["intDigits"]) + "f"
        chargeFormat = "%0." + repr(config.main["chargeDigits"]) + "f"

        if position and abs(position[1]) > 10000:
            intFormat = "%.2e"

        # offset dragging
        if self.currentTool == "offset" and distance and position:
            format = "a.i.: %s   dist: %s" % (intFormat, intFormat)
            label += format % (position[1], distance[1])

        # isotope ruler
        elif self.currentTool == "labelenvelope" and position:
            charge = self.spectrumCanvas.getCharge()
            mass = mspy.mz(position[0], charge=0, currentCharge=charge * polarity)
            format = "m/z: %s   z: %s   mass: %s" % (mzFormat, "%d", mzFormat)
            label = format % (position[0], charge * polarity, mass)

        # difference ruler
        elif self.currentTool == "diffruler" and self.spectrumCanvas.getRuler():
            start, end = self.spectrumCanvas.getRuler()
            diff, charge, matches = self.getRulerMatch(start, end)
            mzs = (self._toReal(start[:2])[0], self._toReal(end[:2])[0])
            label = "dist: %s   " % (distFormat % diff)
            if abs(charge) > 1:
                label += "z: %d   " % charge
            series = None
            if self.spectrumCanvas.rulerShift:
                series = self.getRulerSeriesMatch(start, end)
            if series is not None:
                name, seriesCharge, theoretical = series
                error = diff * max(1, abs(seriesCharge)) - theoretical
                if config.differenceRuler["labelShort"]:
                    name = differences.shortenNames(name)
                label += "series: %s (%s)" % (
                    name,
                    differences.errorText(
                        error,
                        seriesCharge,
                        config.differenceRuler["units"],
                        mzs,
                        config.main["mzDigits"],
                        config.main["ppmDigits"],
                    ),
                )
            elif self.spectrumCanvas.rulerShift:
                label += "no series within %s" % self._rulerToleranceText()
            elif matches:
                short = differences.shortNames() if config.differenceRuler["labelShort"] else {}
                label += "match: " + ",  ".join(
                    "%s (error %s)"
                    % (
                        differences.shortenNames(name, short),
                        differences.errorText(
                            error,
                            charge,
                            config.differenceRuler["units"],
                            mzs,
                            config.main["mzDigits"],
                            config.main["ppmDigits"],
                        ),
                    )
                    for name, error, _listName, _theoretical in matches[:3]
                )
            else:
                label += "no match within %s" % self._rulerToleranceText()
            if not self.spectrumCanvas.rulerShift:
                label += "   (Shift: series)"

        # distance measurement
        elif distance and position:

            # get charge and mass from distance
            if distance[0] != 0 and abs(distance[0]) <= 2:
                charge = abs(1 / distance[0])
                cmass = mspy.mz(position[0], 0, round(charge) * polarity)
                pmass = mspy.mz(position[0] - distance[0], 0, round(charge) * polarity)
            elif distance[0] > 10:
                charge = abs(((position[0] - distance[0]) - 1.00728) / distance[0])
                cmass = mspy.mz(position[0], 0, round(charge) * polarity)
                pmass = mspy.mz(
                    position[0] - distance[0], 0, round(charge + 1) * polarity
                )
            elif distance[0] < -10:
                charge = abs((position[0] - 1.00728) / distance[0])
                cmass = mspy.mz(position[0], 0, round(charge + 1) * polarity)
                pmass = mspy.mz(position[0] - distance[0], 0, round(charge) * polarity)
            else:
                charge = 0
                cmass = 0
                pmass = 0

            if "mz" in config.main["cursorInfo"]:
                format = "m/z: %s   " % mzFormat
                label += format % position[0]

            if "dist" in config.main["cursorInfo"]:
                format = "dist: %s   " % distFormat
                label += format % distance[0]

            if "ppm" in config.main["cursorInfo"]:
                format = "ppm: %s   " % ppmFormat
                label += format % (1e6 * distance[0] / position[0])

            if "z" in config.main["cursorInfo"] and charge:
                if abs(distance[0]) > 10:
                    format = "z: %s/%s   " % (chargeFormat, chargeFormat)
                    label += format % ((charge + 1) * polarity, charge * polarity)
                else:
                    format = "z: %%d (%s)   " % chargeFormat
                    label += format % (round(charge * polarity), charge * polarity)

            cmass_value = cmass[0] if isinstance(cmass, (tuple, list)) else cmass
            pmass_value = pmass[0] if isinstance(pmass, (tuple, list)) else pmass
            try:
                cmass_value = float(cmass_value)
            except Exception:
                cmass_value = 0.0
            try:
                pmass_value = float(pmass_value)
            except Exception:
                pmass_value = 0.0

            if "cmass" in config.main["cursorInfo"] and cmass_value > 0:
                format = "mass (c): %s   " % mzFormat
                label += format % cmass_value

            if "pmass" in config.main["cursorInfo"] and pmass_value > 0:
                format = "mass (p): %s   " % mzFormat
                label += format % pmass_value

            if "area" in config.main["cursorInfo"] and self.currentDocument is not None:
                area = self.documents[self.currentDocument].spectrum.area(
                    minX=position[0] - distance[0],
                    maxX=position[0],
                    baselineWindow=baselineWindow,
                    baselineOffset=config.processing["baseline"]["offset"],
                )
                format = "area: %s   " % areaFormat
                label += format % area

        # no specific function
        elif position:
            format = "m/z: %s   a.i.: %s" % (mzFormat, intFormat)
            label = format % (position[0], position[1])

        # ensure some label size to enable popup menu
        if len(label) < 100:
            label += " " * (100 - len(label))

        # show info (skip redundant SetLabel calls to avoid unnecessary repaints)
        if label != self._lastCursorLabel:
            self._lastCursorLabel = label
            self.cursorInfo.SetLabel(label)

    # ----

    def updateTmpSpectrum(
        self,
        points,
        flipped=False,
        refresh=True,
        fillUnder=False,
        fillUnderAlpha=70,
        showOutline=True,
    ):
        """Set new data to tmp spectrum."""

        self.currentTmpSpectrum = points
        self.currentTmpSpectrumFlip = flipped
        self.currentTmpSpectrumStyle = {
            "fillUnder": fillUnder,
            "fillUnderAlpha": fillUnderAlpha,
            "showOutline": showOutline,
        }

        # check spectrum
        if points is None:
            points = []

        # snap to current spectrum
        normalization = None
        xOffset = 0
        yOffset = 0
        if self.currentDocument is not None and len(points):

            # get normalization
            if config.spectrum["normalize"]:
                normalization = self.documents[
                    self.currentDocument
                ].spectrum.normalization()

            # offset points
            else:
                xOffset = self.documents[self.currentDocument].offset[0]
                yOffset = self.documents[self.currentDocument].offset[1]

            # flip points
            if flipped:
                flipped = not self.documents[self.currentDocument].flipped
            else:
                flipped = self.documents[self.currentDocument].flipped

        # make tmp spectrum
        obj = mspy.plot.points(
            points=points,
            normalized=config.spectrum["normalize"],
            flipped=flipped,
            xOffset=xOffset,
            yOffset=yOffset,
            showInGel=False,
            showLines=showOutline,
            showPoints=False,
            fillUnder=fillUnder,
            fillUnderAlpha=fillUnderAlpha,
            exactFit=True,
            pointColour=config.spectrum["tmpSpectrumColour"],
            lineColour=config.spectrum["tmpSpectrumColour"],
        )

        # set normalization
        if normalization:
            obj.setNormalization(normalization)

        # add to container
        self.container[0] = obj

        # redraw plot
        if refresh:
            self.refresh()

    # ----

    def restoreTmpSpectrum(self):
        """Rebuild the tmp spectrum after a redraw, keeping how it was drawn."""

        self.updateTmpSpectrum(
            self.currentTmpSpectrum,
            flipped=self.currentTmpSpectrumFlip,
            refresh=False,
            **self.currentTmpSpectrumStyle,
        )

    # ----

    def updateNotationMarks(self, notations, refresh=True):
        """Set new data to notation marks."""

        self.currentNotationMarks = notations

        # check spectrum and view option
        if notations is None or not config.spectrum["showNotations"]:
            notations = []

        # snap data to current spectrum
        normalization = None
        flipped = False
        xOffset = 0
        yOffset = 0
        if self.currentDocument is not None and len(notations):

            # normalize points
            if config.spectrum["normalize"]:
                normalization = self.documents[
                    self.currentDocument
                ].spectrum.normalization()

            # offset points
            else:
                xOffset = self.documents[self.currentDocument].offset[0]
                yOffset = self.documents[self.currentDocument].offset[1]

            # flip points
            flipped = self.documents[self.currentDocument].flipped

        # add points to container
        labelFont = wx.Font(
            config.spectrum["labelFontSize"],
            wx.SWISS,
            wx.FONTSTYLE_NORMAL,
            wx.FONTWEIGHT_NORMAL,
            0,
        )
        obj = mspy.plot.annotations(
            points=notations,
            normalized=config.spectrum["normalize"],
            flipped=flipped,
            xOffset=xOffset,
            yOffset=yOffset,
            exactFit=True,
            showInGel=False,
            showPoints=config.spectrum["notationMarks"],
            showLabels=config.spectrum["notationLabels"],
            showXPos=config.spectrum["notationMZ"],
            xPosDigits=config.main["mzDigits"],
            pointColour=config.spectrum["notationMarksColour"],
            labelAngle=config.spectrum["labelAngle"],
            labelBgr=config.spectrum["labelBgr"],
            labelFont=labelFont,
            labelMaxLength=config.spectrum["notationMaxLength"],
        )

        # set normalization
        if normalization:
            obj.setNormalization(normalization)

        # add to container
        self.container[1] = obj

        # redraw plot
        if refresh:
            self.refresh()

    # ----

    def updateSpectrum(self, docIndex, refresh=True):
        """Reload spectrum data."""

        # make spectrum
        docData = self.documents[docIndex]
        spectrum = mspy.plot.spectrum(docData.spectrum)

        # peaks may have been moved in place (e.g. by calibration)
        self._peakMzsKey = None

        # update container
        self.container[docIndex + 2] = spectrum

        # set spectrum properties
        self.setSpectrumProperties(docIndex)

        # redraw plot
        if refresh:
            self.refresh()

    # ----

    def updateSpectrumProperties(self, docIndex, refresh=True, keepScale=False):
        """Update all spectrum properties.

        keepScale redraws without autoscaling the intensity, for changes that
        only touch what is drawn over the spectrum (difference labels).
        """

        # update spectrum properties
        self.setSpectrumProperties(docIndex)

        # update tmp spectra
        self.updateNotationMarks(self.currentNotationMarks, refresh=False)
        self.restoreTmpSpectrum()

        # redraw plot
        if refresh:
            self.refresh(keepScale=keepScale)

    # ----

    def selectSpectrum(self, docIndex, refresh=True):
        """Set document as active."""

        # hide labels on last active document
        if self.currentDocument is not None:
            self.container[self.currentDocument + 2].setProperties(
                showLabels=(
                    config.spectrum["showLabels"] and config.spectrum["showAllLabels"]
                )
            )
            self.container[self.currentDocument + 2].setProperties(
                tickColour=self.documents[self.currentDocument].colour
            )

        # set current document
        self.currentDocument = docIndex
        if self.currentDocument is not None:
            self.spectrumCanvas.setCurrentObject(self.currentDocument + 2)
            self.container[self.currentDocument + 2].setProperties(
                showLabels=config.spectrum["showLabels"]
            )
            self.container[self.currentDocument + 2].setProperties(
                tickColour=config.spectrum["tickColour"]
            )
        else:
            self.spectrumCanvas.setCurrentObject(None)

        # update tmp spectra
        self.updateTmpSpectrum(None, refresh=False)
        self.updateNotationMarks(None, refresh=False)

        # redraw plot
        if refresh:
            self.refresh()

    # ----

    def appendLastSpectrum(self, refresh=True):
        """Append new spectrum to container."""

        # get document
        docIndex = len(self.documents) - 1
        docData = self.documents[docIndex]

        # append spectrum
        spectrum = mspy.plot.spectrum(docData.spectrum)
        self.container.append(spectrum)

        # set spectrum properties
        self.setSpectrumProperties(docIndex)

        # redraw plot
        if refresh:
            self.refresh(fullsize=True)

    # ----

    def moveSpectrum(self, fromIndex, toIndex, refresh=True):
        """Move spectrum within the container to follow reordered documents."""

        # move spectrum (the first two objects are the tmp spectrum and marks)
        spectrum = self.container[fromIndex + 2]
        del self.container[fromIndex + 2]
        self.container.insert(toIndex + 2, spectrum)

        # keep the current object pointing to the same document
        if self.currentDocument is not None:
            self.currentDocument = mwx.shiftIndex(
                self.currentDocument, fromIndex, toIndex
            )
            self.spectrumCanvas.setCurrentObject(self.currentDocument + 2)

        # redraw plot
        if refresh:
            self.refresh()

    # ----

    def deleteSpectrum(self, docIndex, refresh=True):
        """Remove selected spectrum from container."""

        # remove spectrum
        del self.container[docIndex + 2]

        # set current document
        if docIndex == self.currentDocument:
            self.currentDocument = None
            self.spectrumCanvas.setCurrentObject(None)
            self.updateTmpSpectrum(None, refresh=False)
            self.updateNotationMarks(None, refresh=False)

        # redraw plot
        if refresh:
            self.refresh()

    # ----

    def highlightPoints(self, points, anchor=None):
        """Highlight specified points in the spectrum.

        If anchor is given (a m/z value, typically the labelled monoisotopic
        peak), the view is centred on it rather than on the middle of points.
        """
        self.spectrumCanvas.highlightXPoints(points, anchor=anchor)

    # ----

    def labelPeak(self, selection):
        """Label peak in selection."""

        # check document
        if (
            self.currentDocument is None
            or not self.documents[self.currentDocument].spectrum.hasprofile()
        ):
            return

        # get baseline window
        baselineWindow = 1.0
        if config.processing["peakpicking"]["baseline"]:
            baselineWindow = 1.0 / config.processing["baseline"]["precision"]

        # get baseline
        baseline = self.documents[self.currentDocument].spectrum.baseline(
            window=baselineWindow, offset=config.processing["baseline"]["offset"]
        )

        # label peak
        peak = mspy.labelpeak(
            signal=self.documents[self.currentDocument].spectrum.profile,
            minX=selection[0],
            maxX=selection[2],
            pickingHeight=config.processing["peakpicking"]["pickingHeight"],
            baseline=baseline,
        )

        if peak:

            # set as monoisotopic
            if config.processing["deisotoping"]["setAsMonoisotopic"]:
                peak.setisotope(0)

            # update document
            self.documents[self.currentDocument].backup(("spectrum"))
            self.documents[self.currentDocument].spectrum.peaklist.append(peak)

            self.parent.onDocumentChanged(items=("spectrum"))

    # ----

    def labelPeakMulti(self, rawSelection):
        """Label the highest peak within the selected range in every visible spectrum.

        rawSelection is the selection box in canvas (display) coordinates; the x
        range is converted back to real m/z per document using that document's own
        horizontal offset, so the same peak is labelled across overlaid spectra.
        """

        # baseline window is the same for every document
        baselineWindow = 1.0
        if config.processing["peakpicking"]["baseline"]:
            baselineWindow = 1.0 / config.processing["baseline"]["precision"]

        # label the apex peak in each visible spectrum that has profile data
        changed = []
        for docIndex, docData in enumerate(self.documents):
            if not docData.visible or not docData.spectrum.hasprofile():
                continue

            # convert the canvas x range to this document's real m/z (offsets are
            # ignored while normalized, matching the single-document conversion)
            if config.spectrum["normalize"]:
                minX, maxX = rawSelection[0], rawSelection[2]
            else:
                minX = rawSelection[0] - docData.offset[0]
                maxX = rawSelection[2] - docData.offset[0]

            baseline = docData.spectrum.baseline(
                window=baselineWindow, offset=config.processing["baseline"]["offset"]
            )

            peak = mspy.labelpeak(
                signal=docData.spectrum.profile,
                minX=minX,
                maxX=maxX,
                pickingHeight=config.processing["peakpicking"]["pickingHeight"],
                baseline=baseline,
            )
            if not peak:
                continue

            # set as monoisotopic
            if config.processing["deisotoping"]["setAsMonoisotopic"]:
                peak.setisotope(0)

            # update document
            docData.backup(("spectrum"))
            docData.spectrum.peaklist.append(peak)
            changed.append(docIndex)

        # update gui
        if changed:
            self.parent.onDocumentChangedMulti(indexes=changed, items=("spectrum",))
            self.refresh()
        else:
            wx.Bell()

    # ----

    def labelPoint(self, mz):
        """Label point at position."""

        # check document
        if (
            self.currentDocument is None
            or not self.documents[self.currentDocument].spectrum.hasprofile()
        ):
            return

        # get baseline window
        baselineWindow = 1.0
        if config.processing["peakpicking"]["baseline"]:
            baselineWindow = 1.0 / config.processing["baseline"]["precision"]

        # get baseline
        baseline = self.documents[self.currentDocument].spectrum.baseline(
            window=baselineWindow, offset=config.processing["baseline"]["offset"]
        )

        # label point
        peak = mspy.labelpoint(
            signal=self.documents[self.currentDocument].spectrum.profile,
            mz=mz,
            baseline=baseline,
        )

        if peak:

            # set as monoisotopic
            if config.processing["deisotoping"]["setAsMonoisotopic"]:
                peak.setisotope(0)

            # update document
            self.documents[self.currentDocument].backup(("spectrum"))
            self.documents[self.currentDocument].spectrum.peaklist.append(peak)

            self.parent.onDocumentChanged(items=("spectrum"))

    # ----

    def labelEnvelope(self, isotopes, charge):
        """Label isotopes."""

        # check document
        if (
            self.currentDocument is None
            or not self.documents[self.currentDocument].spectrum.hasprofile()
        ):
            return

        # get baseline window
        baselineWindow = 1.0
        if config.processing["peakpicking"]["baseline"]:
            baselineWindow = 1.0 / config.processing["baseline"]["precision"]

        # get baseline
        baseline = self.documents[self.currentDocument].spectrum.baseline(
            window=baselineWindow, offset=config.processing["baseline"]["offset"]
        )

        # label isotopes
        peaks = []
        buff = []
        for isotope in isotopes:
            peak = mspy.labelpeak(
                signal=self.documents[self.currentDocument].spectrum.profile,
                mz=isotope,
                pickingHeight=config.processing["peakpicking"]["pickingHeight"],
                baseline=baseline,
            )
            if peak and peak.mz not in buff:
                peaks.append(peak)
                buff.append(peak.mz)

        # check peaks
        if not peaks:
            return

        # backup document
        self.documents[self.currentDocument].backup(("spectrum"))

        # get polarity
        polarity = 1
        if self.documents[self.currentDocument].spectrum.polarity == -1:
            polarity = -1

        # Manually assemble exactly ONE envelope from the picked isotopes
        spectrum = self.documents[self.currentDocument].spectrum

        defaultFwhm = 0.1
        if spectrum.peaklist.basepeak and spectrum.peaklist.basepeak.fwhm:
            defaultFwhm = spectrum.peaklist.basepeak.fwhm

        cluster = sorted(peaks, key=lambda p: p.mz)
        for x, peak in enumerate(cluster):
            peak.charge = charge * polarity
            peak.isotope = x

        averagineType = config.processing["peakpicking"].get("averagineType", "protein")
        areas, shapes = mspy.mod_peakpicking._fit_envelope_areas_shaped(
            [cluster],
            spectrum.profile,
            defaultFwhm,
            nonIdeality=config.processing["deisotoping"]["envelopeNonIdeality"],
            averagineType=averagineType,
        )
        area_val = max(0.0, float(areas[0])) if areas else 0.0

        # use the exact shape the area fit used, so the drawn envelope matches
        isotopes_data = shapes[0] if shapes else []
        envelope_data = {
            "area": area_val,
            "fwhm": float(mspy.mod_peakpicking._cluster_fwhm(cluster, defaultFwhm)),
            "shape": "gaussian",
            "isotopes": isotopes_data,
        }

        labeled_peaks = mspy.labelenvelope(
            cluster,
            charge=charge * polarity,
            label=config.processing["deisotoping"]["labelEnvelope"],
            intensity=config.processing["deisotoping"]["envelopeIntensity"],
            averagineType=averagineType,
        )

        for peak in labeled_peaks:
            import copy
            if not hasattr(peak, "attributes"):
                peak.attributes = {}
            peak.attributes["envelope"] = copy.deepcopy(envelope_data)

            if config.processing["deisotoping"]["labelEnvelope"] == "isotopes":
                groupname = spectrum.peaklist.groupname()
                peak.setgroup(groupname)

            spectrum.peaklist.append(peak)

        if hasattr(self.parent, "peaklistPanel") and hasattr(
            self.parent.peaklistPanel, "_recalculateNeighborhoodEnvelopes"
        ):
            self.parent.peaklistPanel._recalculateNeighborhoodEnvelopes([cluster[0].mz])

        # update gui
        self.parent.onDocumentChanged(items=("spectrum"))

    # ----

    def deleteLabel(self, selection):
        """Delete all labels and difference rulers within selection."""

        # check document
        if self.currentDocument is None:
            return

        docData = self.documents[self.currentDocument]

        # remove peaks
        indexes = []
        deleted_mzs = []
        for x, peak in enumerate(docData.spectrum.peaklist):
            if (selection[0] < peak.mz < selection[2]) and (
                selection[1] < peak.ai < selection[3]
            ):
                indexes.append(x)
                deleted_mzs.append(peak.mz)

        # remove rulers whose middle is within the selection and whose bar
        # (put at its own height, else drawn just above the taller of its two
        # peaks) the selection reaches
        rulers = [
            ruler
            for ruler in docData.rulers
            if selection[0] < (ruler.mz1 + ruler.mz2) / 2 < selection[2]
            and (
                selection[1] <= ruler.height <= selection[3]
                if ruler.height is not None
                else selection[3] >= max(ruler.ai1, ruler.ai2)
            )
        ]

        # update document
        items = ()
        if indexes:
            items += ("spectrum",)
        if rulers:
            items += ("rulers",)
        if not items:
            return

        docData.backup(items)
        if indexes:
            docData.spectrum.peaklist.delete(indexes)
            self.parent.peaklistPanel._recalculateNeighborhoodEnvelopes(deleted_mzs)
        if rulers:
            docData.rulers[:] = [r for r in docData.rulers if r not in rulers]
        self.parent.onDocumentChanged(items=items)

    # ----

    def getSnapCandidates(self, x, tolerance):
        """Peaks of the current document a difference ruler can snap to.

        x and the returned (x, y) points are in plot coordinates, i.e. with the
        document's offset, normalization and flipping applied.
        """

        if self.currentDocument is None:
            return []

        docData = self.documents[self.currentDocument]
        if not docData.visible:
            return []

        mz = self._toReal((x, 0))[0]
        peaklist = docData.spectrum.peaklist
        mzs = self._getPeakMzs()
        first = bisect.bisect_left(mzs, mz - tolerance)
        last = bisect.bisect_right(mzs, mz + tolerance)

        norm = None
        if config.spectrum["normalize"] and last > first:
            norm = docData.spectrum.normalization()

        return [
            self._toDisplay(peaklist[i].mz, peaklist[i].ai, norm)
            for i in range(first, last)
        ]

    # ----

    def getRulerObstacles(self):
        """Boxes the current document's drawn difference labels take."""

        if self.currentDocument is None:
            return []
        obj = self.container[self.currentDocument + 2]
        return mspy.plot.rulerObstacles(
            getattr(obj, "rulerGeometry", []), self.spectrumCanvas.printerScale
        )

    # ----

    def getRulerMatch(self, start, end):
        """Difference, charge and matches of a ruler between two canvas points.

        start and end are (x, y, snapped) as the canvas gives them. The charge
        comes from the peaks the ends sit on (see differences.rulerCharge).
        """

        mz1 = self._toReal(start[:2])[0]
        mz2 = self._toReal(end[:2])[0]
        diff = abs(mz2 - mz1)

        charges = []
        for point, mz in ((start, mz1), (end, mz2)):
            peak = self._peakAt(mz) if point[2] else None
            charges.append(peak.charge if peak is not None else None)
        charge = differences.rulerCharge(*charges)

        return diff, charge, matchRuler(diff, charge, (mz1, mz2))

    # ----

    def getRulerText(self, start, end):
        """Text over the difference ruler being dragged."""

        diff, charge, matches = self.getRulerMatch(start, end)
        mzs = (self._toReal(start[:2])[0], self._toReal(end[:2])[0])
        return rulerText(
            differences.matchNames(matches),
            diff,
            charge,
            matches[0][3] if matches else None,
            mzs,
        )

    # ----

    def addRuler(self, start, end, height=None):
        """Add a difference ruler between two canvas points to the document.

        height is the intensity to put its bar at, None to place it itself.
        """

        # check document
        if self.currentDocument is None:
            return

        # a click, or a drag too short to mean anything, is not a ruler
        x1 = self.spectrumCanvas.positionUserToScreen(start[:2])[0]
        x2 = self.spectrumCanvas.positionUserToScreen(end[:2])[0]
        if abs(x2 - x1) < 3:
            return

        docData = self.documents[self.currentDocument]
        ruler = self._makeRuler(
            start, end, scanID=docData.currentScanID if docData.islcms() else None
        )
        if height is not None:
            ruler.height = float(height)

        docData.backup(("rulers",))
        docData.rulers.append(ruler)
        self.parent.onDocumentChanged(items=("rulers",))

    # ----

    def _rulerSeries(self, start, end):
        """Series between two canvas points, both on a peak (see findSeries).

        Returns (path of peak indexes, charge), or None when the ends are not
        on two peaks or no chain of matching steps of at least
        MIN_SERIES_STEP joins them. The last one found is remembered, as it
        is asked for on every move of a drag.
        """

        if self.currentDocument is None or not (start[2] and end[2]):
            return None

        mz1 = self._toReal(start[:2])[0]
        mz2 = self._toReal(end[:2])[0]
        peak1 = self._peakAt(mz1)
        peak2 = self._peakAt(mz2)
        if peak1 is None or peak2 is None or peak1 is peak2:
            return None
        if peak2.mz < peak1.mz:
            peak1, peak2 = peak2, peak1

        docData = self.documents[self.currentDocument]
        peaklist = docData.spectrum.peaklist
        settings = config.differenceRuler
        key = (
            id(peaklist),
            len(peaklist),
            peak1.mz,
            peak2.mz,
            tuple(settings["lists"]),
            settings["tolerance"],
            settings["massType"],
            settings["units"],
        )
        if getattr(self, "_rulerSeriesCache", (None,))[0] == key:
            return self._rulerSeriesCache[1]

        charge = differences.rulerCharge(peak1.charge, peak2.charge)
        path = differences.findSeries(
            self._getPeakMzs(),
            [peak.ai for peak in peaklist],
            self._peakIndex(peak1.mz),
            self._peakIndex(peak2.mz),
            differences.entries(settings["lists"], pairs=False),
            settings["tolerance"],
            settings["massType"],
            charge,
            settings["units"],
            minStep=differences.MIN_SERIES_STEP,
        )
        result = None if path is None else (path, charge)
        self._rulerSeriesCache = (key, result)
        return result

    # ----

    def getRulerSeriesMatch(self, start, end):
        """What the series between two canvas points is, for Shift.

        Returns (name, charge, theoretical): name is that of the chain of
        steps through the peaks in between (e.g. 2\u00d7Hex + HexNAc), which
        is labelled step by step once dropped, else what the difference
        matches as a whole (as without Shift); theoretical the neutral mass it
        stands for. None when it is neither.
        """

        if self.currentDocument is None:
            return None

        series = self._rulerSeries(start, end)
        if series is not None:
            path, charge = series
            peaklist = self.documents[self.currentDocument].spectrum.peaklist
            names = []
            theoretical = 0.0
            for i, j in zip(path[:-1], path[1:], strict=True):
                a, b = peaklist[i], peaklist[j]
                matches = matchRuler(b.mz - a.mz, charge, (a.mz, b.mz))
                names.append(matches[0][0] if matches else "?")
                theoretical += matches[0][3] if matches else 0.0
            return differences.seriesName(names), charge, theoretical

        _diff, charge, matches = self.getRulerMatch(start, end)
        if matches:
            return differences.matchNames(matches), charge, matches[0][3]
        return None

    # ----

    def getRulerSeriesText(self, start, end):
        """Text over a ruler dragged with Shift (see getRulerSeriesMatch)."""

        found = self.getRulerSeriesMatch(start, end)
        if found is None:
            return None
        name, charge, theoretical = found
        mzs = (self._toReal(start[:2])[0], self._toReal(end[:2])[0])
        return rulerText(name, abs(mzs[1] - mzs[0]), charge, theoretical, mzs)

    # ----

    def addRulerSeries(self, start, end, height=None, replace=None):
        """Label a series between two canvas points (with Shift).

        Every step of a chain of matching steps through the peaks in between
        (see findSeries) gets its own label, its bar over its taller peak.
        replace is the index of a label the series takes the place of, as one
        undoable step. Returns False, adding nothing, without such a chain.
        """

        if self.currentDocument is None:
            return False

        docData = self.documents[self.currentDocument]
        scanID = docData.currentScanID if docData.islcms() else None
        rulers = []

        series = self._rulerSeries(start, end)
        if series is not None:
            path, charge = series
            peaklist = docData.spectrum.peaklist
            canvas = self.spectrumCanvas
            for i, j in zip(path[:-1], path[1:], strict=True):
                a, b = peaklist[i], peaklist[j]
                matches = matchRuler(b.mz - a.mz, charge, (a.mz, b.mz))

                # each step's bar just over its taller peak
                taller = a if a.ai >= b.ai else b
                barY = canvas.rulerBarOver(self._toDisplay(taller.mz, taller.ai))
                barHeight = self._toReal(canvas.positionScreenToUser((0, barY)))[1]
                rulers.append(
                    doc.ruler(
                        a.mz,
                        a.ai,
                        b.mz,
                        b.ai,
                        label=differences.matchNames(matches),
                        charge=charge,
                        scanID=scanID,
                        theoretical=matches[0][3] if matches else None,
                        height=barHeight,
                    )
                )

        else:
            return False

        docData.backup(("rulers",))
        if replace is not None and 0 <= replace < len(docData.rulers):
            docData.rulers[replace : replace + 1] = rulers
        else:
            docData.rulers.extend(rulers)
        self.parent.onDocumentChanged(items=("rulers",))
        return True

    # ----

    def _peakIndex(self, mz):
        """Index of the current document's peak at this m/z (to rounding)."""

        mzs = self._getPeakMzs()
        return bisect.bisect_left(mzs, mz - 1e-6)

    # ----

    def _makeRuler(self, start, end, scanID=None):
        """Matched difference ruler between two canvas points."""

        mz1, ai1 = self._toReal(start[:2])
        mz2, ai2 = self._toReal(end[:2])
        diff, charge, matches = self.getRulerMatch(start, end)

        return doc.ruler(
            mz1,
            ai1,
            mz2,
            ai2,
            label=differences.matchNames(matches),
            charge=charge,
            scanID=scanID,
            theoretical=matches[0][3] if matches else None,
        )

    # ----

    def rulerAt(self, x, y):
        """Current document's ruler drawn at a screen position, as (index, part).

        part is 1 or 2 for the left or right end's lead, 0 for the bar.
        """

        if self.currentDocument is None:
            return None
        docData = self.documents[self.currentDocument]
        if not docData.visible or not config.differenceRuler["show"]:
            return None

        hit = self.container[self.currentDocument + 2].rulerAt(
            x, y, 5 * self.spectrumCanvas.printerScale["drawings"]
        )
        if hit is None or not 0 <= hit[0] < len(docData.rulers):
            return None
        return hit

    # ----

    def grabRuler(self, x, y):
        """Ruler a press at a screen position picks up (see the canvas).

        Returns (plot object, ruler index, part, ends, text, apexes): part is
        1 or 2 for the left or right end, 0 for the bar; ends are the two peak
        tops, left first, and apexes a function listing the tops of the peaks
        the ruler spans (which the bar snaps to), in plot coordinates. None
        when the press misses.
        """

        hit = self.rulerAt(x, y)
        if hit is None:
            return None

        docIndex = self.currentDocument
        if docIndex is None:
            return None
        ruler = self.documents[docIndex].rulers[hit[0]]
        obj = self.container[docIndex + 2]

        # the ends where the label draws them
        ends = []
        for mz, ai in ((ruler.mz1, ruler.ai1), (ruler.mz2, ruler.ai2)):
            ends.append(self._toDisplay(mz, obj.rulerEndIntensity(mz, ai)))
        ends.sort(key=lambda point: self.spectrumCanvas.positionUserToScreen(point)[0])

        text = labelText(ruler)

        def apexes():
            peaklist = self.documents[self.currentDocument].spectrum.peaklist
            mzs = self._getPeakMzs()
            first = bisect.bisect_left(mzs, ruler.mz1 - 1e-6)
            last = bisect.bisect_right(mzs, ruler.mz2 + 1e-6)
            norm = None
            if config.spectrum["normalize"] and last > first:
                norm = self.documents[self.currentDocument].spectrum.normalization()
            return [
                self._toDisplay(peaklist[i].mz, peaklist[i].ai, norm)
                for i in range(first, last)
            ]

        return (
            obj,
            hit[0],
            hit[1],
            ends,
            text,
            apexes,
        )

    # ----

    def setRulerHeight(self, index, height):
        """Put a difference ruler's bar at an intensity, or back (None)."""

        docData = self.documents[self.currentDocument]
        if not 0 <= index < len(docData.rulers):
            return

        docData.backup(("rulers",))
        docData.rulers[index].height = None if height is None else float(height)
        self.parent.onDocumentChanged(items=("rulers",))

    # ----

    def moveRuler(self, index, start, end, height=None):
        """Put a difference ruler whose end was dragged between new points.

        height is the intensity its bar is at now, if it was drawn somewhere.
        """

        docData = self.documents[self.currentDocument]
        if not 0 <= index < len(docData.rulers):
            return

        # dropped back on its other end: nothing to measure, leave it be
        x1 = self.spectrumCanvas.positionUserToScreen(start[:2])[0]
        x2 = self.spectrumCanvas.positionUserToScreen(end[:2])[0]
        if abs(x2 - x1) < 3:
            self.parent.onDocumentChanged(items=("rulers",))
            return

        old = docData.rulers[index]
        ruler = self._makeRuler(start, end, scanID=old.scanID)
        ruler.height = old.height if height is None else float(height)
        ruler.note = old.note
        docData.backup(("rulers",))
        docData.rulers[index] = ruler
        self.parent.onDocumentChanged(items=("rulers",))

    # ----

    def showRuler(self, index):
        """Zoom the spectrum to a difference label of the current document."""

        docData = self.documents[self.currentDocument]
        if not 0 <= index < len(docData.rulers):
            return

        ruler = docData.rulers[index]
        margin = max(ruler.diff * 0.25, 1.0)
        x1 = self._toDisplay(ruler.mz1 - margin, 0)[0]
        x2 = self._toDisplay(ruler.mz2 + margin, 0)[0]
        self.setCanvasRange(xAxis=(min(x1, x2), max(x1, x2)))
        self.highlightPoints([ruler.mz1, ruler.mz2])

    # ----

    def deleteRuler(self, index):
        """Delete one difference ruler of the current document."""

        docData = self.documents[self.currentDocument]
        if not 0 <= index < len(docData.rulers):
            return

        docData.backup(("rulers",))
        del docData.rulers[index]
        self.parent.onDocumentChanged(items=("rulers",))

    # ----

    def rematchRuler(self, ruler):
        """Label a ruler again with the current settings."""

        peak1 = self._peakAt(ruler.mz1)
        peak2 = self._peakAt(ruler.mz2)
        if peak1 is not None or peak2 is not None:
            ruler.charge = differences.rulerCharge(
                peak1.charge if peak1 is not None else None,
                peak2.charge if peak2 is not None else None,
            )
        matches = matchRuler(ruler.diff, ruler.charge, (ruler.mz1, ruler.mz2))

        # a match the user picked stays while it still matches
        if ruler.picked:
            for match in matches:
                if match[0] == ruler.label:
                    ruler.theoretical = match[3]
                    return
            ruler.picked = False

        ruler.label = differences.matchNames(matches)
        ruler.theoretical = matches[0][3] if matches else None

    # ----

    def _changeRuler(self, index, **values):
        """Set attributes of one difference label, as one undoable step."""

        docData = self.documents[self.currentDocument]
        if not 0 <= index < len(docData.rulers):
            return

        docData.backup(("rulers",))
        for name, value in values.items():
            setattr(docData.rulers[index], name, value)
        self.parent.onDocumentChanged(items=("rulers",))

    # ----

    def editRulerText(self, index):
        """Let the user write the text a difference label shows."""

        ruler = self.documents[self.currentDocument].rulers[index]
        dlg = wx.TextEntryDialog(
            self,
            "Text to show instead of the automatic one (empty: automatic).\n"
            "These are filled in from the label: {name} the match, {diff} the\n"
            "measured difference, {mass} the same as a neutral mass, {theo} the\n"
            "match's theoretical mass, {error} measured minus theoretical.",
            "Label Text",
            ruler.note or labelText(ruler),
        )
        if dlg.ShowModal() == wx.ID_OK:
            note = dlg.GetValue().strip()
            dlg.Destroy()
            if note == labelText(ruler) and not ruler.note:
                return
            self._changeRuler(index, note=note or None)
        else:
            dlg.Destroy()

    # ----

    def onCanvasKey(self, evt):
        """Delete the difference label under the cursor, else the canvas keys."""

        key = evt.GetKeyCode()
        canvas = self.spectrumCanvas
        if (
            self.currentTool == "diffruler"
            and key in (wx.WXK_DELETE, wx.WXK_BACK)
            and not canvas.mouseEvent
        ):
            hit = self.rulerAt(canvas.cursorPosition[2], canvas.cursorPosition[3])
            if hit is None:
                wx.Bell()
            else:
                self.deleteRuler(hit[0])
            return

        canvas.onChar(evt)

    # ----

    def onCanvasLDClick(self, evt):
        """Edit the text of a difference label double-clicked, else reset view."""

        if self.currentTool == "diffruler":

            # the second press may have picked the label up to drag it, which
            # hides it from the hit test
            index = self.spectrumCanvas.getRulerEdit()
            if index is not None:
                self.spectrumCanvas.escMouseEvents()
            else:
                hit = self.rulerAt(*evt.GetPosition())
                index = hit[0] if hit is not None else None

            if index is not None:
                self.editRulerText(index)
                return

        self.spectrumCanvas.onLMDC(evt)

    # ----

    def onRulerMenu(self, index):
        """Show what can be done with one difference label."""

        docData = self.documents[self.currentDocument]
        ruler = docData.rulers[index]
        mzs = (ruler.mz1, ruler.mz2)

        def rematch():
            docData.backup(("rulers",))
            ruler.picked = False
            self.rematchRuler(ruler)
            self.parent.onDocumentChanged(items=("rulers",))

        menu = wx.Menu()
        handlers = {}

        def append(target, label, handler, kind=wx.ITEM_NORMAL, checked=False):
            itemID = wx.NewIdRef()
            item = target.Append(itemID, label, "", kind)
            if kind != wx.ITEM_NORMAL:
                item.Check(checked)
            handlers[int(itemID)] = handler

        title = menu.Append(
            wx.ID_ANY,
            "%s  (%s - %s)"
            % (
                labelText(ruler),
                "%0.*f" % (config.main["mzDigits"], ruler.mz1),
                "%0.*f" % (config.main["mzDigits"], ruler.mz2),
            ),
        )
        title.Enable(False)
        menu.AppendSeparator()

        # choose among several matches
        matches = matchRuler(ruler.diff, ruler.charge, mzs)
        names = []
        for match in matches:
            if match[0] not in [item[0] for item in names]:
                names.append(match)
        if len(names) > 1:
            submenu = wx.Menu()
            append(
                submenu,
                "All (%s)" % differences.matchNames(matches),
                lambda: self._changeRuler(
                    index,
                    label=differences.matchNames(matches),
                    theoretical=matches[0][3],
                    picked=False,
                ),
                wx.ITEM_RADIO,
                not ruler.picked,
            )
            for name, error, _listName, theoretical in names:
                append(
                    submenu,
                    self._matchDescription(name, error, theoretical, ruler.charge, mzs),
                    lambda name=name, theoretical=theoretical: self._changeRuler(
                        index, label=name, theoretical=theoretical, picked=True
                    ),
                    wx.ITEM_RADIO,
                    ruler.picked and ruler.label == name,
                )
            menu.AppendSubMenu(submenu, "Show Match")

        append(menu, "Edit Text...", lambda: self.editRulerText(index))
        if ruler.note:
            append(menu, "Automatic Text", lambda: self._changeRuler(index, note=None))
        if sum(1 for other in docData.rulers if other.note) > 1:
            append(menu, "Automatic Text for All Labels", self.resetRulerNotes)
        append(menu, "Colour...", lambda: self.pickRulerColour(index))
        if ruler.colour:
            append(menu, "Default Colour", lambda: self._changeRuler(index, colour=None))
        append(menu, "Match Again", rematch)
        if ruler.height is not None:
            append(menu, "Reset Height", lambda: self.setRulerHeight(index, None))
        append(menu, "Delete Label", lambda: self.deleteRuler(index))
        menu.AppendSeparator()
        append(menu, "Delete All Difference Labels", self.parent.onDocumentRulersDelete)
        menu.AppendSeparator()
        append(menu, "Difference Label Settings...", self.onDiffRulerSettings)

        def onMenu(evt):
            handler = handlers.get(evt.GetId())
            if handler is not None:
                handler()

        menu.Bind(wx.EVT_MENU, onMenu)
        self.PopupMenu(menu)
        menu.Destroy()

    # ----

    def _matchDescription(self, name, error, theoretical, charge, mzs):
        """A match as the Show Match menu lists it: its name, the theoretical
        (neutral) mass difference it stands for, and how far the measured one
        is from it."""

        if config.differenceRuler["labelShort"]:
            short = differences.shortenNames(name)
            if short != name:
                name = "%s (%s)" % (short, name)
        return "%s   expected %0.*f, error %s" % (
            name,
            config.main["mzDigits"],
            theoretical,
            differences.errorText(
                error,
                charge,
                config.differenceRuler["units"],
                mzs,
                config.main["mzDigits"],
                config.main["ppmDigits"],
            ),
        )

    # ----

    def resetRulerNotes(self, evt=None):
        """Give every label of the current document its automatic text back."""

        if self.currentDocument is None:
            return
        docData = self.documents[self.currentDocument]
        count = sum(1 for ruler in docData.rulers if ruler.note)
        if not count:
            wx.Bell()
            return

        # own texts are typed by hand; make sure this was meant
        title = "Replace the text you typed on %s?" % (
            "1 label" if count == 1 else "%d labels" % count
        )
        message = (
            "They will show what they matched instead. Undo brings the texts back."
        )
        buttons = [
            (wx.ID_CANCEL, "Cancel", 80, True, 15),
            (wx.ID_OK, "Replace", 80, False, 0),
        ]
        dlg = mwx.dlgMessage(self, title, message, buttons)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        dlg.Destroy()

        docData.backup(("rulers",))
        for ruler in docData.rulers:
            ruler.note = None
        self.parent.onDocumentChanged(items=("rulers",))

    # ----

    def pickRulerColour(self, index):
        """Let the user choose the colour of one difference label."""

        ruler = self.documents[self.currentDocument].rulers[index]
        colour = wx.GetColourFromUser(
            self,
            wx.Colour(*(ruler.colour or config.differenceRuler["colour"])),
            "Label Colour",
        )
        if not colour.IsOk():
            return
        self._changeRuler(index, colour=(colour.Red(), colour.Green(), colour.Blue()))

    # ----

    def rematchRulers(self, evt=None):
        """Label the current document's rulers again with the current settings."""

        if self.currentDocument is None or not self.documents[self.currentDocument].rulers:
            wx.Bell()
            return

        docData = self.documents[self.currentDocument]
        docData.backup(("rulers",))
        for ruler in docData.rulers:
            self.rematchRuler(ruler)

        self.parent.onDocumentChanged(items=("rulers",))

    # ----

    def _rulerToleranceText(self):
        """Matching tolerance as shown to the user, e.g. "±100 ppm"."""

        return "\u00b1%g %s" % (
            config.differenceRuler["tolerance"],
            config.differenceRuler["units"],
        )

    # ----

    def onDiffRulerMenu(self, evt=None):
        """Show difference ruler options."""

        menu = wx.Menu()
        handlers = {}

        def append(
            label, handler, kind=wx.ITEM_NORMAL, checked=False, enabled=True, menu=menu
        ):
            itemID = wx.NewIdRef()
            item = menu.Append(itemID, label, "", kind)
            if kind != wx.ITEM_NORMAL:
                item.Check(checked)
            item.Enable(enabled)
            handlers[int(itemID)] = handler

        # difference lists
        header = menu.Append(
            wx.ID_ANY, "Match Within %s:" % self._rulerToleranceText()
        )
        header.Enable(False)
        enabled = config.differenceRuler["lists"]
        for name in differences.availableLists():
            append(
                "    " + name,
                lambda name=name: self._toggleRulerList(name),
                wx.ITEM_CHECK,
                name in enabled,
            )

        # matching options
        menu.AppendSeparator()
        massType = config.differenceRuler["massType"]
        append(
            "Monoisotopic Masses",
            lambda: self._setRulerOption("massType", 0),
            wx.ITEM_RADIO,
            not massType,
        )
        append(
            "Average Masses",
            lambda: self._setRulerOption("massType", 1),
            wx.ITEM_RADIO,
            bool(massType),
        )

        # what a matched label's text shows, the same switches as in Settings
        textMenu = wx.Menu()
        named = bool(config.differenceRuler["labelName"])
        for key, label, needsName in RULER_TEXT_PARTS:
            append(
                label,
                lambda key=key: self._setRulerOption(
                    key, int(not config.differenceRuler[key])
                ),
                wx.ITEM_CHECK,
                bool(config.differenceRuler[key]),
                enabled=named or not needsName,
                menu=textMenu,
            )
        menu.AppendSubMenu(textMenu, "Matched Label Text")
        append(
            "Settings...",
            self.onDiffRulerSettings,
        )

        # rulers of the current document
        hasRulers = (
            self.currentDocument is not None
            and bool(self.documents[self.currentDocument].rulers)
        )
        menu.AppendSeparator()
        append("Match All Labels Again", self.rematchRulers, enabled=hasRulers)
        append(
            "Automatic Text for All Labels",
            self.resetRulerNotes,
            enabled=hasRulers
            and any(ruler.note for ruler in self.documents[self.currentDocument].rulers),
        )
        append(
            "Delete All Difference Labels", self.parent.onDocumentRulersDelete, enabled=hasRulers
        )
        menu.AppendSeparator()
        append("Edit Difference Lists...", self.parent.onLibraryDifferences)

        def onMenu(evt):
            handler = handlers.get(evt.GetId())
            if handler is not None:
                handler()

        menu.Bind(wx.EVT_MENU, onMenu)
        textMenu.Bind(wx.EVT_MENU, onMenu)
        self.PopupMenu(menu)
        menu.Destroy()

    # ----

    def _toggleRulerList(self, name):
        """Match the difference ruler against a list, or stop doing so."""

        lists = list(config.differenceRuler["lists"])
        if name in lists:
            lists.remove(name)
        else:
            lists.append(name)
        config.differenceRuler["lists"] = lists

    # ----

    def _setRulerOption(self, key, value):
        """Set a difference ruler option and redraw the rulers."""

        config.differenceRuler[key] = value
        self.updateCanvasProperties()

    # ----

    def onDiffRulerSettings(self, evt=None):
        """Show the difference ruler settings."""

        hasRulers = self.currentDocument is not None and bool(
            self.documents[self.currentDocument].rulers
        )
        dlg = dlgDiffRulerSettings(self.parent, hasRulers)
        if dlg.ShowModal() == wx.ID_OK:
            rematch = dlg.rematch
            dlg.Destroy()
            if rematch and self.currentDocument is not None:
                if self.documents[self.currentDocument].rulers:
                    self.rematchRulers()
            self.updateCanvasProperties()
        else:
            dlg.Destroy()

    # ----

    def _toReal(self, point):
        """Convert a canvas point to the current document's m/z and intensity;
        with no document selected, the canvas values themselves."""

        x, y = point
        if self.currentDocument is None:
            return x, y
        docData = self.documents[self.currentDocument]

        if docData.flipped:
            y = -y
        if config.spectrum["normalize"]:
            y *= docData.spectrum.normalization()
        else:
            x -= docData.offset[0]
            y -= docData.offset[1]

        return x, y

    # ----

    def _toDisplay(self, mz, ai, norm=None):
        """Convert the current document's m/z and intensity to a canvas point.

        norm is the document's normalization, when the caller already has it.
        """

        docData = self.documents[self.currentDocument]

        if config.spectrum["normalize"]:
            ai /= norm or docData.spectrum.normalization()
        else:
            mz += docData.offset[0]
            ai += docData.offset[1]
        if docData.flipped:
            ai = -ai

        return mz, ai

    # ----

    def _getPeakMzs(self):
        """Sorted m/z of the current document's peaks."""

        peaklist = self.documents[self.currentDocument].spectrum.peaklist
        key = (id(peaklist), len(peaklist), self.currentDocument)
        mzs = self._peakMzs
        if key != self._peakMzsKey or mzs is None:
            mzs = self._peakMzs = [peak.mz for peak in peaklist]
            self._peakMzsKey = key
        return mzs

    # ----

    def _peakAt(self, mz):
        """The current document's peak at this m/z (to rounding), if any."""

        if self.currentDocument is None:
            return None
        peaklist = self.documents[self.currentDocument].spectrum.peaklist
        mzs = self._getPeakMzs()
        i = bisect.bisect_left(mzs, mz - 1e-6)
        if i < len(mzs) and abs(mzs[i] - mz) <= 1e-6:
            return peaklist[i]
        return None

    # ----

    def refresh(self, fullsize=False, keepScale=False):
        """Redraw spectrum (keepScale: without autoscaling the intensity)."""

        # check for flipped documents and update canvas symmetry
        self.spectrumCanvas.setProperties(ySymmetry=False)
        for docData in self.documents:
            if docData.visible and docData.flipped:
                self.spectrumCanvas.setProperties(ySymmetry=True)
                break

        # redraw canvas
        self.spectrumCanvas.refresh(fullsize=fullsize, keepScale=keepScale)

    # ----

    def getBitmap(self, width, height, printerScale):
        """Get spectrum image."""
        return self.spectrumCanvas.getBitmap(width, height, printerScale)

    # ----

    def getSVG(self, path, width, height, printerScale, dpi=72):
        """Export spectrum image as SVG."""
        return self.spectrumCanvas.getSVG(path, width, height, printerScale, dpi)

    # ----

    def getCurrentBitmap(self):
        """Get currently rendered spectrum image."""
        return self.spectrumCanvas.getCurrentBitmap()

    # ----

    def getPrintout(self, filterSize, title):
        """Get spectrum printout."""
        return self.spectrumCanvas.getPrintout(filterSize, title)

    # ----

    def getCurrentRange(self):
        """Get current X range."""
        return self.spectrumCanvas.getCurrentXRange()

    # ----

    def getCurrentYRange(self):
        """Get current Y range."""
        return self.spectrumCanvas.getCurrentYRange()

    # ----


class dlgCanvasProperties(wx.Dialog):
    """Set canvas properties."""

    def __init__(self, parent, onChangeFn, onCloseFn=None):

        # initialize document frame
        wx.Dialog.__init__(
            self,
            parent,
            -1,
            "Canvas Properties",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.STAY_ON_TOP,
        )
        self.onChangeFn = onChangeFn
        self.onCloseFn = onCloseFn

        # Every pixel of slider travel raises a scroll event, and each one used
        # to trigger a full canvas redraw. On a large spectrum the redraws
        # cannot keep up with the events and the backlog starves the main loop,
        # so they are coalesced to whatever rate the canvas can actually
        # sustain.
        self.updateThrottle = mwx.throttler(self, self.onChangeFn)

        # destroy on close (shown modeless) and let the owner drop its reference
        self.Bind(wx.EVT_CLOSE, self.onClose)

        # make GUI
        sizer = self.makeGUI()

        # fit layout
        self.Layout()
        sizer.Fit(self)
        self.SetSizer(sizer)
        self.SetMinSize(self.GetSize())
        # start about twice as wide so the sliders have room; the fitted width
        # above stays the minimum, so the user can still shrink it back
        width, height = self.GetSize()
        self.SetSize(wx.Size(width * 2, height))
        # apply dark mode
        mwx.applyDarkMode(self)
        self.CentreOnParent()

    # ----

    def makeGUI(self):
        """Make GUI elements."""

        # make canvas params
        mzDigits_label = wx.StaticText(self, -1, "m/z precision:")
        self.mzDigits_slider = wx.Slider(
            self,
            -1,
            config.main["mzDigits"],
            0,
            6,
            size=(150, -1),
            style=mwx.SLIDER_STYLE,
        )
        self.mzDigits_slider.SetTick(1)
        self.mzDigits_slider.SetTickFreq(1)
        self.mzDigits_slider.Bind(wx.EVT_SCROLL, self.onChange)

        intDigits_label = wx.StaticText(self, -1, "Intensity precision:")
        self.intDigits_slider = wx.Slider(
            self,
            -1,
            config.main["intDigits"],
            0,
            6,
            size=(150, -1),
            style=mwx.SLIDER_STYLE,
        )
        self.intDigits_slider.SetTick(1)
        self.intDigits_slider.SetTickFreq(1)
        self.intDigits_slider.Bind(wx.EVT_SCROLL, self.onChange)

        posBarSize_label = wx.StaticText(self, -1, "Bars height:")
        self.posBarSize_slider = wx.Slider(
            self,
            -1,
            config.spectrum["posBarSize"],
            5,
            20,
            size=(150, -1),
            style=mwx.SLIDER_STYLE,
        )
        self.intDigits_slider.SetTick(1)
        self.posBarSize_slider.SetTickFreq(5)
        self.posBarSize_slider.Bind(wx.EVT_SCROLL, self.onChange)

        gelHeight_label = wx.StaticText(self, -1, "Gel height:")
        self.gelHeight_slider = wx.Slider(
            self,
            -1,
            config.spectrum["gelHeight"],
            10,
            50,
            size=(150, -1),
            style=mwx.SLIDER_STYLE,
        )
        self.intDigits_slider.SetTick(1)
        self.gelHeight_slider.SetTickFreq(5)
        self.gelHeight_slider.Bind(wx.EVT_SCROLL, self.onChange)

        axisFontSize_label = wx.StaticText(self, -1, "Canvas font size:")
        self.axisFontSize_slider = wx.Slider(
            self,
            -1,
            config.spectrum["axisFontSize"],
            5,
            15,
            size=(150, -1),
            style=mwx.SLIDER_STYLE,
        )
        self.intDigits_slider.SetTick(1)
        self.axisFontSize_slider.SetTickFreq(2)
        self.axisFontSize_slider.Bind(wx.EVT_SCROLL, self.onChange)

        labelFontSize_label = wx.StaticText(self, -1, "Label font size:")
        self.labelFontSize_slider = wx.Slider(
            self,
            -1,
            config.spectrum["labelFontSize"],
            5,
            15,
            size=(150, -1),
            style=mwx.SLIDER_STYLE,
        )
        self.intDigits_slider.SetTick(1)
        self.labelFontSize_slider.SetTickFreq(2)
        self.labelFontSize_slider.Bind(wx.EVT_SCROLL, self.onChange)

        notationMaxLength_label = wx.StaticText(self, -1, "Notation length:")
        self.notationMaxLength_slider = wx.Slider(
            self,
            -1,
            config.spectrum["notationMaxLength"],
            1,
            100,
            size=(150, -1),
            style=mwx.SLIDER_STYLE,
        )
        self.intDigits_slider.SetTick(1)
        self.notationMaxLength_slider.SetTickFreq(10)
        self.notationMaxLength_slider.Bind(wx.EVT_SCROLL, self.onChange)

        # spectrum drawing quality: higher = better (more detail), lower = faster.
        # The 0-100 slider maps onto the canvas filterSize (5 = coarsest .. 1 =
        # finest). A plain caption keeps it consistent with the other rulers,
        # whose native SL_LABELS already show the current value -- a second,
        # differently-scaled readout would only be confusing.
        quality_label = wx.StaticText(self, -1, "Spectrum quality:")
        self.quality_slider = wx.Slider(
            self,
            -1,
            self._filterSizeToSlider(config.spectrum.get("filterSize", 1.0)),
            0,
            100,
            size=(150, -1),
            style=mwx.SLIDER_STYLE,
        )
        self.quality_slider.SetTickFreq(10)
        self.quality_slider.Bind(wx.EVT_SCROLL, self.onChange)

        # pack elements
        grid = wx.GridBagSizer(mwx.GRIDBAG_VSPACE, mwx.GRIDBAG_HSPACE)
        grid.Add(mzDigits_label, (0, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.mzDigits_slider, (0, 1), flag=wx.EXPAND)
        grid.Add(
            intDigits_label, (1, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
        )
        grid.Add(self.intDigits_slider, (1, 1), flag=wx.EXPAND)
        grid.Add(
            posBarSize_label, (2, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
        )
        grid.Add(self.posBarSize_slider, (2, 1), flag=wx.EXPAND)
        grid.Add(
            gelHeight_label, (3, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
        )
        grid.Add(self.gelHeight_slider, (3, 1), flag=wx.EXPAND)
        grid.Add(
            axisFontSize_label, (4, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
        )
        grid.Add(self.axisFontSize_slider, (4, 1), flag=wx.EXPAND)
        grid.Add(
            labelFontSize_label, (5, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
        )
        grid.Add(self.labelFontSize_slider, (5, 1), flag=wx.EXPAND)
        grid.Add(
            notationMaxLength_label,
            (6, 0),
            flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL,
        )
        grid.Add(self.notationMaxLength_slider, (6, 1), flag=wx.EXPAND)
        grid.Add(
            quality_label, (7, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
        )
        grid.Add(self.quality_slider, (7, 1), flag=wx.EXPAND)
        grid.AddGrowableCol(1)

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        mainSizer.Add(grid, 0, wx.EXPAND | wx.ALL, mwx.PANEL_SPACE_MAIN)

        return mainSizer

    # ----

    def _filterSizeToSlider(self, filterSize):
        """Map a stored filterSize (5=coarsest .. 1=finest) to 0-100 quality."""
        return max(0, min(100, int(round((5.0 - float(filterSize)) / 4.0 * 100))))

    # ----

    def _sliderToFilterSize(self, sliderValue):
        """Map a 0-100 quality-slider position to a stored filterSize (5 .. 1)."""
        return round(5.0 - (sliderValue / 100.0) * 4.0, 2)

    # ----

    def onChange(self, evt):
        """Set parameter and update canvas while scrolling."""

        # get canvas params
        config.main["mzDigits"] = self.mzDigits_slider.GetValue()
        config.main["intDigits"] = self.intDigits_slider.GetValue()
        config.spectrum["posBarSize"] = self.posBarSize_slider.GetValue()
        config.spectrum["gelHeight"] = self.gelHeight_slider.GetValue()
        config.spectrum["axisFontSize"] = self.axisFontSize_slider.GetValue()
        config.spectrum["labelFontSize"] = self.labelFontSize_slider.GetValue()
        config.spectrum["notationMaxLength"] = self.notationMaxLength_slider.GetValue()
        config.spectrum["filterSize"] = self._sliderToFilterSize(
            self.quality_slider.GetValue()
        )

        # set params to canvas and update; the last event of a drag is the one
        # the user is waiting on, so it skips the queue
        if evt is not None and evt.GetEventType() in (
            wx.wxEVT_SCROLL_THUMBRELEASE,
            wx.wxEVT_SCROLL_CHANGED,
        ):
            self.updateThrottle.flush()
        else:
            self.updateThrottle.request()

    # ----

    def onClose(self, evt):
        """Notify the owner and destroy the (modeless) dialog."""

        self.updateThrottle.stop()

        if self.onCloseFn is not None:
            self.onCloseFn()
        self.Destroy()

    # ----


class dlgViewRange(wx.Dialog):
    """Set canvas view range."""

    def __init__(self, parent, data):

        # initialize document frame
        wx.Dialog.__init__(
            self, parent, -1, "Mass Range", style=wx.DEFAULT_DIALOG_STYLE
        )

        self.parent = parent
        self.data = data

        # make GUI
        sizer = self.makeGUI()

        # fit layout
        self.Layout()
        sizer.Fit(self)
        self.SetSizer(sizer)
        self.Centre()

    # ----

    def makeGUI(self):
        """Make GUI elements."""

        staticSizer = mwx.staticBoxSizer(self, "", wx.HORIZONTAL)

        # make elements
        minX_label = wx.StaticText(self, -1, "Min:", style=wx.ALIGN_RIGHT)
        self.minX_value = wx.TextCtrl(
            self,
            -1,
            str(self.data[0]),
            size=(100, -1),
            style=wx.TE_PROCESS_ENTER,
            validator=mwx.validator("float"),
        )
        self.minX_value.Bind(wx.EVT_TEXT_ENTER, self.onOK)

        maxX_label = wx.StaticText(self, -1, "Max:", style=wx.ALIGN_RIGHT)
        self.maxX_value = wx.TextCtrl(
            self,
            -1,
            str(self.data[1]),
            size=(100, -1),
            style=wx.TE_PROCESS_ENTER,
            validator=mwx.validator("float"),
        )
        self.maxX_value.Bind(wx.EVT_TEXT_ENTER, self.onOK)

        cancel_butt = wx.Button(self, wx.ID_CANCEL, "Cancel")
        ok_butt = wx.Button(self, wx.ID_OK, "OK")
        ok_butt.Bind(wx.EVT_BUTTON, self.onOK)
        ok_butt.SetDefault()

        # pack elements
        staticSizer.Add(minX_label, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)
        staticSizer.Add(
            self.minX_value,
            1,
            wx.TOP | wx.RIGHT | wx.BOTTOM | wx.ALIGN_CENTER_VERTICAL,
            5,
        )
        staticSizer.Add(maxX_label, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)
        staticSizer.Add(
            self.maxX_value,
            1,
            wx.TOP | wx.RIGHT | wx.BOTTOM | wx.ALIGN_CENTER_VERTICAL,
            5,
        )

        buttSizer = wx.BoxSizer(wx.HORIZONTAL)
        buttSizer.Add(cancel_butt, 0, wx.RIGHT, 15)
        buttSizer.Add(ok_butt, 0)

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        mainSizer.Add(
            staticSizer, 0, wx.EXPAND | wx.CENTER | wx.ALL, mwx.PANEL_SPACE_MAIN
        )
        mainSizer.Add(
            buttSizer,
            0,
            wx.CENTER | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            mwx.PANEL_SPACE_MAIN,
        )

        return mainSizer

    # ----

    def onOK(self, evt=None):
        """Get values."""

        # get data
        try:
            minX = float(self.minX_value.GetValue())
            maxX = float(self.maxX_value.GetValue())
            if minX < maxX:
                self.data = (minX, maxX)
                self.EndModal(wx.ID_OK)
            else:
                wx.Bell()
        except Exception:
            wx.Bell()

    # ----


class dlgSpectrumOffset(wx.Dialog):
    """Set spectrum offset."""

    def __init__(self, parent, offset):
        wx.Dialog.__init__(
            self,
            parent,
            -1,
            "Spectrum offset",
            style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP,
        )

        self.parent = parent
        if isinstance(offset, (tuple, list)) and len(offset) > 1:
            self.offset = offset
        else:
            self.offset = [0, 0.0]

        # make GUI
        sizer = self.makeGUI()

        # fit layout
        sizer.Fit(self)
        self.SetSizer(sizer)
        self.SetMinSize(self.GetSize())
        self.Centre()

    # ----

    def makeGUI(self):
        """Make GUI elements."""

        staticSizer = mwx.staticBoxSizer(self, "", wx.VERTICAL)

        # make elements
        offset_label = wx.StaticText(self, -1, "Intensity offset:")
        offset_y = self.offset[1] if self.offset is not None else 0.0
        self.offset_value = wx.TextCtrl(
            self,
            -1,
            str(offset_y),
            size=(120, -1),
            style=wx.TE_PROCESS_ENTER,
            validator=mwx.validator("float"),
        )
        self.offset_value.Bind(wx.EVT_TEXT, self.onChange)
        self.offset_value.Bind(wx.EVT_TEXT_ENTER, self.onOffset)

        cancel_butt = wx.Button(self, wx.ID_CANCEL, "Cancel")
        offset_butt = wx.Button(self, wx.ID_OK, "Offset")
        offset_butt.Bind(wx.EVT_BUTTON, self.onOffset)
        offset_butt.SetDefault()

        # pack elements
        grid = wx.GridBagSizer(mwx.GRIDBAG_VSPACE, mwx.GRIDBAG_HSPACE)
        grid.Add(offset_label, (0, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.offset_value, (0, 1))
        staticSizer.Add(grid, 0, wx.ALL, 5)

        buttSizer = wx.BoxSizer(wx.HORIZONTAL)
        buttSizer.Add(cancel_butt, 0, wx.RIGHT, 15)
        buttSizer.Add(offset_butt, 0)

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        mainSizer.Add(staticSizer, 0, wx.CENTER | wx.ALL, mwx.PANEL_SPACE_MAIN)
        mainSizer.Add(
            buttSizer,
            0,
            wx.CENTER | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            mwx.PANEL_SPACE_MAIN,
        )

        return mainSizer

    # ----

    def onChange(self, evt):
        """Check data."""

        # get data
        try:
            self.offset = [0, float(self.offset_value.GetValue())]
        except Exception:
            self.offset = None

    # ----

    def onOffset(self, evt):
        """Offset."""

        # check value and end
        if self.offset is not None:
            self.EndModal(wx.ID_OK)
        else:
            wx.Bell()

    # ----

    def getData(self):
        """Return values."""
        return self.offset

    # ----


# the parts a matched difference label's text can show, as (setting, label,
# whether it only applies with the name shown); the label menu and the
# settings dialog offer the same switches under the same words
RULER_TEXT_PARTS = (
    ("labelName", "Name", False),
    ("labelAllNames", "All matching names, not only the closest", True),
    ("labelShort", "Short names (e.g. Ac for Acetylation)", True),
    ("labelCharge", "Charge (when above 1)", True),
    ("labelDiff", "Difference", False),
    ("labelError", "Error (observed - theoretical, in tolerance units)", False),
)


class dlgDiffRulerSettings(wx.Dialog):
    """Set what the difference ruler matches and how it labels rulers."""

    # an example ruler for the label preview: a lysine step at 2+, 1.2 mDa off,
    # which glutamine (0.036 Da lighter) also matches at a loose tolerance
    PREVIEW = {
        "names": "Phosphorylation / Sulfation",
        "short": {"Phosphorylation": "Phos", "Sulfation": "Sulf"},
        "charge": 2,
        "theoretical": 79.96633,
        "diff": (79.96633 + 0.0012) / 2,
        "mzs": (736.0, 776.0),
    }

    def __init__(self, parent, hasRulers=False):
        wx.Dialog.__init__(
            self,
            parent,
            -1,
            "Difference Label Settings",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        self.parent = parent
        self.hasRulers = hasRulers
        self.rematch = False

        # make GUI
        sizer = self.makeGUI()
        self.setData()
        self.updatePreview()

        # fit layout
        self.Layout()
        sizer.Fit(self)
        self.SetSizer(sizer)
        self.SetMinSize(self.GetSize())

        # apply dark mode
        mwx.applyDarkMode(self)
        self.CentreOnParent()

    # ----

    def makeGUI(self):
        """Make GUI elements."""

        # lists
        listsBox = mwx.staticBoxSizer(self, "Match against", wx.VERTICAL)
        self.lists_check = wx.CheckListBox(self, -1, size=wx.Size(260, 150))
        editLists_butt = wx.Button(self, -1, "Edit Lists...")
        editLists_butt.Bind(wx.EVT_BUTTON, self.onEditLists)
        listsBox.Add(self.lists_check, 1, wx.EXPAND | wx.ALL, 5)
        listsBox.Add(editLists_butt, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # matching
        matchBox = mwx.staticBoxSizer(self, "Matching", wx.VERTICAL)
        massType_label = wx.StaticText(self, -1, "Masses:")
        self.massTypeMo_radio = wx.RadioButton(self, -1, "Monoisotopic", style=wx.RB_GROUP)
        self.massTypeAv_radio = wx.RadioButton(self, -1, "Average")

        tolerance_label = wx.StaticText(self, -1, "Tolerance:")
        self.tolerance_value = wx.TextCtrl(
            self, -1, "", size=wx.Size(80, -1), validator=mwx.validator("floatPos")
        )
        self.tolerance_value.Bind(wx.EVT_TEXT, self.updatePreview)
        self.units_choice = wx.Choice(self, -1, choices=["Da", "ppm"])
        mwx.fitChoice(self.units_choice)
        self.units_choice.Bind(wx.EVT_CHOICE, self.updatePreview)
        self.tolerance_help = wx.StaticText(self, -1, "")
        self.tolerance_help.SetFont(wx.SMALL_FONT)

        grid = wx.GridBagSizer(mwx.GRIDBAG_VSPACE, mwx.GRIDBAG_HSPACE)
        grid.Add(massType_label, (0, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.massTypeMo_radio, (0, 1), flag=wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.massTypeAv_radio, (0, 2), flag=wx.ALIGN_CENTER_VERTICAL)
        grid.Add(tolerance_label, (1, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.tolerance_value, (1, 1), flag=wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.units_choice, (1, 2), flag=wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.tolerance_help, (2, 1), (1, 2))
        matchBox.Add(grid, 0, wx.ALL, 5)

        # label
        labelBox = mwx.staticBoxSizer(self, "Matched label text", wx.VERTICAL)
        text = {key: label for key, label, needsName in RULER_TEXT_PARTS}
        self.labelName_check = wx.CheckBox(self, -1, text["labelName"])
        self.labelAllNames_check = wx.CheckBox(self, -1, text["labelAllNames"])
        self.labelShort_check = wx.CheckBox(self, -1, text["labelShort"])
        self.labelCharge_check = wx.CheckBox(self, -1, text["labelCharge"])
        self.labelDiff_check = wx.CheckBox(self, -1, text["labelDiff"])
        self.labelError_check = wx.CheckBox(self, -1, text["labelError"])
        for check in (
            self.labelName_check,
            self.labelAllNames_check,
            self.labelShort_check,
            self.labelCharge_check,
            self.labelDiff_check,
            self.labelError_check,
        ):
            check.Bind(wx.EVT_CHECKBOX, self.updatePreview)

        unmatched_label = wx.StaticText(self, -1, "Unmatched labels show the difference.")
        unmatched_label.SetFont(wx.SMALL_FONT)
        colour_label = wx.StaticText(self, -1, "Colour:")
        self.colour_picker = wx.ColourPickerCtrl(
            self, -1, wx.Colour(*config.differenceRuler["colour"])
        )
        self.colour_picker.Bind(wx.EVT_COLOURPICKER_CHANGED, self.updatePreview)
        preview_label = wx.StaticText(self, -1, "Example:")
        self.preview_text = wx.StaticText(self, -1, "")

        preview = wx.BoxSizer(wx.HORIZONTAL)
        preview.Add(colour_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        preview.Add(self.colour_picker, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 15)
        preview.Add(preview_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        preview.Add(self.preview_text, 1, wx.ALIGN_CENTER_VERTICAL)

        labelBox.Add(self.labelName_check, 0, wx.ALL, 3)
        labelBox.Add(self.labelAllNames_check, 0, wx.LEFT, 25)
        labelBox.Add(self.labelShort_check, 0, wx.LEFT, 25)
        labelBox.Add(self.labelCharge_check, 0, wx.LEFT | wx.TOP, 3)
        labelBox.Add(self.labelDiff_check, 0, wx.LEFT | wx.TOP, 3)
        labelBox.Add(self.labelError_check, 0, wx.LEFT | wx.TOP, 3)
        labelBox.Add(unmatched_label, 0, wx.ALL, 3)
        labelBox.Add(preview, 0, wx.EXPAND | wx.ALL, 5)

        # rematch + buttons
        self.rematch_check = wx.CheckBox(
            self, -1, "Match the current document's labels again"
        )
        self.rematch_check.SetToolTip(
            wx.ToolTip(
                "Otherwise labels keep the matches they were made with; the text "
                "and colour apply to all of them anyway."
            )
        )
        self.rematch_check.SetValue(self.hasRulers)
        self.rematch_check.Enable(self.hasRulers)
        cancel_butt = wx.Button(self, wx.ID_CANCEL, "Cancel")
        ok_butt = wx.Button(self, wx.ID_OK, "OK")
        ok_butt.Bind(wx.EVT_BUTTON, self.onOK)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(cancel_butt, 0, wx.RIGHT, 15)
        buttons.Add(ok_butt, 0)

        right = wx.BoxSizer(wx.VERTICAL)
        right.Add(matchBox, 0, wx.EXPAND)
        right.AddSpacer(mwx.PANEL_SPACE_MAIN)
        right.Add(labelBox, 1, wx.EXPAND)

        columns = wx.BoxSizer(wx.HORIZONTAL)
        columns.Add(listsBox, 0, wx.EXPAND | wx.RIGHT, mwx.PANEL_SPACE_MAIN)
        columns.Add(right, 1, wx.EXPAND)

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        mainSizer.Add(columns, 1, wx.EXPAND | wx.ALL, mwx.PANEL_SPACE_MAIN)
        mainSizer.Add(self.rematch_check, 0, wx.LEFT | wx.RIGHT, mwx.PANEL_SPACE_MAIN)
        mainSizer.Add(buttons, 0, wx.CENTER | wx.ALL, mwx.PANEL_SPACE_MAIN)

        return mainSizer

    # ----

    def setData(self):
        """Show the current settings."""

        settings = config.differenceRuler
        self.updateLists(settings["lists"])
        self.massTypeAv_radio.SetValue(bool(settings["massType"]))
        self.massTypeMo_radio.SetValue(not settings["massType"])
        self.tolerance_value.ChangeValue(str(settings["tolerance"]))
        self.units_choice.SetStringSelection(settings["units"])
        self.labelName_check.SetValue(bool(settings["labelName"]))
        self.labelAllNames_check.SetValue(bool(settings["labelAllNames"]))
        self.labelShort_check.SetValue(bool(settings["labelShort"]))
        self.labelCharge_check.SetValue(bool(settings["labelCharge"]))
        self.labelDiff_check.SetValue(bool(settings["labelDiff"]))
        self.labelError_check.SetValue(bool(settings["labelError"]))

    # ----

    def updateLists(self, checked):
        """Fill the list of difference lists, ticking the checked ones."""

        names = differences.availableLists()
        self.lists_check.Set(names)
        for i, name in enumerate(names):
            self.lists_check.Check(i, name in checked)

    # ----

    def getLabelOptions(self):
        """Label options as ticked."""

        return {
            "labelName": int(self.labelName_check.GetValue()),
            "labelAllNames": int(self.labelAllNames_check.GetValue()),
            "labelShort": int(self.labelShort_check.GetValue()),
            "labelCharge": int(self.labelCharge_check.GetValue()),
            "labelDiff": int(self.labelDiff_check.GetValue()),
            "labelError": int(self.labelError_check.GetValue()),
        }

    # ----

    def updatePreview(self, evt=None):
        """Show how a matched ruler would be labelled."""

        self.labelAllNames_check.Enable(self.labelName_check.GetValue())
        self.labelShort_check.Enable(self.labelName_check.GetValue())
        self.labelCharge_check.Enable(self.labelName_check.GetValue())

        if self.units_choice.GetStringSelection() == "ppm":
            self.tolerance_help.SetLabel("At each of the two peaks' m/z.")
        else:
            self.tolerance_help.SetLabel("")
        self.preview_text.SetForegroundColour(self.colour_picker.GetColour())

        example = self.PREVIEW
        names = example["names"]
        if self.labelShort_check.GetValue():
            names = differences.shortenNames(names, {**example["short"], **differences.shortNames()})
        text = differences.rulerText(
            names,
            example["diff"],
            example["charge"],
            example["theoretical"],
            example["mzs"],
            options=self.getLabelOptions(),
            units=self.units_choice.GetStringSelection() or "Da",
            digits=config.main["mzDigits"],
            ppmDigits=config.main["ppmDigits"],
        )
        self.preview_text.SetLabel(text)
        self.Layout()

    # ----

    def onEditLists(self, evt):
        """Edit the mass differences library, keeping the ticks."""

        checked = list(self.lists_check.GetCheckedStrings())
        self.parent.onLibraryDifferences()
        self.updateLists(checked)

    # ----

    def onOK(self, evt):
        """Store the settings."""

        try:
            tolerance = float(self.tolerance_value.GetValue())
        except ValueError:
            tolerance = 0
        if tolerance <= 0:
            wx.Bell()
            self.tolerance_value.SetFocus()
            return

        settings = config.differenceRuler
        settings["lists"] = list(self.lists_check.GetCheckedStrings())
        settings["massType"] = int(self.massTypeAv_radio.GetValue())
        settings["tolerance"] = tolerance
        settings["units"] = self.units_choice.GetStringSelection() or "Da"
        for key, value in self.getLabelOptions().items():
            settings[key] = value
        colour = self.colour_picker.GetColour()
        settings["colour"] = [colour.Red(), colour.Green(), colour.Blue()]

        self.rematch = self.rematch_check.GetValue()
        self.EndModal(wx.ID_OK)

    # ----


class fileDropTarget(wx.FileDropTarget):
    """Generic drop target for files."""

    def __init__(self, fn):
        wx.FileDropTarget.__init__(self)
        self.fn = fn

    # ----

    def OnDropFiles(self, x, y, filenames):
        """Open dropped files."""
        self.fn(paths=filenames)
        return True

    # ----
