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
from .ids import (
    ID_peaklistAnnotate,
    ID_peaklistConvertAllToEnvelopes,
    ID_peaklistConvertToEnvelopes,
    ID_peaklistSendToMassToFormula,
    ID_viewPeaklistColumnAi,
    ID_viewPeaklistColumnBase,
    ID_viewPeaklistColumnEnvArea,
    ID_viewPeaklistColumnEnvInt,
    ID_viewPeaklistColumnFwhm,
    ID_viewPeaklistColumnGroup,
    ID_viewPeaklistColumnInt,
    ID_viewPeaklistColumnMass,
    ID_viewPeaklistColumnMz,
    ID_viewPeaklistColumnRel,
    ID_viewPeaklistColumnResol,
    ID_viewPeaklistColumnSn,
    ID_viewPeaklistColumnZ,
)
from . import mwx
from . import images
from . import config
from . import display_scale
import mspy
from . import doc

from .dlg_notation import dlgNotation

# PEAKLIST PANEL
# --------------


class panelPeaklist(wx.Panel):
    """Make peaklist panel."""

    def __init__(self, parent):
        panelWidth = display_scale.scale_metric(150, display_scale.get_ui_scale())
        wx.Panel.__init__(
            self,
            parent,
            -1,
            size=wx.Size(panelWidth, -1),
            style=wx.NO_FULL_REPAINT_ON_RESIZE,
        )

        self.parent = parent

        self.currentDocument = None
        self.peakListMap = None
        self.selectedPeak = None
        # m/z of the currently selected peak, tracked independently of the row
        # index so the selection (and its drawn envelope) can be restored after
        # the list is rebuilt -- e.g. on undo/redo or any recalculation, where
        # the peaklist is replaced and the old index no longer points anywhere.
        self._selectedMz = None
        self._ignore_selection_events = False

        # make GUI
        self.makeGUI()

    # ----

    def makeGUI(self):
        """Make GUI elements."""

        # make peaklist list
        self.makePeakList()

        # init editing panel
        editor = self.makeEditor()

        # init lower toolbar
        toolbar = self.makeToolbar()

        # pack gui elements
        self.mainSizer = wx.BoxSizer(wx.VERTICAL)
        self.mainSizer.Add(self.peakList, 1, wx.EXPAND | wx.ALL, mwx.LISTCTRL_NO_SPACE)
        self.mainSizer.Add(editor, 0, wx.EXPAND)
        self.mainSizer.Add(toolbar, 0, wx.EXPAND)

        # hide peak editor
        self.mainSizer.Hide(1)

        # show the current averagine model
        self.updateAveragineInfo()

        # fit layout
        self.mainSizer.Fit(self)
        self.SetSizer(self.mainSizer)

        # recolour static labels / inputs for the current theme (wxMSW does not
        # inherit the parent colours the way GTK does)
        mwx.applyThemeToWindow(self)

    # ----

    def makeToolbar(self):
        """Make bottom toolbar."""

        # init toolbar panel (bgrPanel drops the sprite for a flat fill in dark
        # mode itself, and can swap between the two on a live theme switch)
        panel = mwx.bgrPanel(
            self,
            -1,
            images.lib["bgrBottombar"],
            size=wx.Size(-1, mwx.BOTTOMBAR_HEIGHT),
        )

        self.addPeak_butt = mwx.makeBitmapButton(
            panel,
            -1,
            images.lib["peaklistAdd"],
            size=wx.Size(*mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.addPeak_butt.SetToolTip(wx.ToolTip("Add peak manually..."))
        self.addPeak_butt.Bind(wx.EVT_BUTTON, self.onAdd)

        self.deletePeak_butt = mwx.makeBitmapButton(
            panel,
            -1,
            images.lib["peaklistDelete"],
            size=wx.Size(*mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.deletePeak_butt.SetToolTip(wx.ToolTip("Remove peaks..."))
        self.deletePeak_butt.Bind(wx.EVT_BUTTON, self.onDelete)

        self.annotatePeak_butt = mwx.makeBitmapButton(
            panel,
            -1,
            images.lib["peaklistAnnotate"],
            size=wx.Size(*mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.annotatePeak_butt.SetToolTip(wx.ToolTip("Annotate peak..."))
        self.annotatePeak_butt.Bind(wx.EVT_BUTTON, self.onAnnotate)

        self.editPeak_butt = mwx.makeBitmapButton(
            panel,
            -1,
            images.lib["peaklistEditorOff"],
            size=wx.Size(*mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.editPeak_butt.SetToolTip(wx.ToolTip("Show / hide peak editor"))
        self.editPeak_butt.Bind(wx.EVT_BUTTON, self.onEdit)

        self.peaksCount = wx.StaticText(panel, -1, "")
        self.peaksCount.SetFont(wx.SMALL_FONT)

        # tells the user which averagine model peak picking / envelope fitting
        # is currently using (set in Processing -> Peak Picking)
        self.averagineInfo = wx.StaticText(panel, -1, "")
        self.averagineInfo.SetFont(wx.SMALL_FONT)

        # pack elements
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.AddSpacer(mwx.BOTTOMBAR_LSPACE)
        sizer.Add(self.addPeak_butt, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(
            self.deletePeak_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.annotatePeak_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.Add(
            self.editPeak_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.AddSpacer(10)
        sizer.Add(self.peaksCount, 0, wx.ALIGN_CENTER_VERTICAL, 0)
        sizer.AddStretchSpacer()
        sizer.Add(self.averagineInfo, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        sizer.AddSpacer(mwx.BOTTOMBAR_RSPACE)

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        mainSizer.Add(sizer, 1, wx.EXPAND)

        panel.SetSizer(mainSizer)
        mainSizer.Fit(panel)

        return panel

    # ----

    def updateAveragineInfo(self):
        """Show the averagine model currently used for picking and envelopes."""

        labels = {
            "protein": ("Prot", "Protein"),
            "carbohydrate": ("Carb", "Carbohydrate"),
            "lipid": ("Lipid", "Lipid"),
        }
        model = config.processing["peakpicking"].get("averagineType", "protein")
        short, full = labels.get(model, labels["protein"])

        self.averagineInfo.SetLabel(short)
        self.averagineInfo.SetToolTip(
            wx.ToolTip(
                "Averagine model in use: %s\n"
                "(change it in Processing -> Peak Picking)" % full
            )
        )
        self.averagineInfo.GetContainingSizer().Layout()

    # ----

    def makePeakList(self):
        """Make peaklist list."""

        # init peaklist (initial width scales with the UI so the responsive
        # column widths fit without forcing a horizontal scrollbar)
        listWidth = display_scale.scale_metric(201, display_scale.get_ui_scale())
        self.peakList = mwx.sortListCtrl(
            self, -1, size=wx.Size(listWidth, -1), style=mwx.LISTCTRL_STYLE_MULTI
        )
        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        font.SetPointSize(font.GetPointSize() - 2)
        self.peakList.SetFont(font)
        self.peakList.setSecondarySortColumn(0)
        self.peakList.setAltColour(mwx.LISTCTRL_ALTCOLOUR)

        self.peakList.applyTheme()

        # set events
        self.peakList.Bind(wx.EVT_LIST_COL_RIGHT_CLICK, self.onColumnRMU)
        self.peakList.Bind(wx.EVT_LIST_ITEM_SELECTED, self.onItemSelected)
        self.peakList.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.onItemActivated)
        self.peakList.Bind(wx.EVT_KEY_DOWN, self.onListKey)

        if wx.Platform == "__WXMAC__":
            self.peakList.Bind(wx.EVT_RIGHT_UP, self.onItemRMU)
        else:
            self.peakList.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.onItemRMU)

        # make columns
        self.makePeakListColumns()

        # set DnD
        dropTarget = fileDropTarget(self.parent.onDocumentDropped)
        self.peakList.SetDropTarget(dropTarget)

    # ----

    def makePeakListColumns(self):
        """Make peaklist columns according to config."""

        # delete current columns
        self.peakList.deleteColumns()

        # add new columns
        x = 0
        for column in config.main["peaklistColumns"]:

            if column == "mz":
                self.peakList.InsertColumn(x, "m/z", wx.LIST_FORMAT_RIGHT)
                x += 1

            elif column == "ai":
                self.peakList.InsertColumn(x, "a.i.", wx.LIST_FORMAT_RIGHT)
                x += 1

            elif column == "int":
                self.peakList.InsertColumn(x, "int.", wx.LIST_FORMAT_RIGHT)
                x += 1

            elif column == "envarea":
                self.peakList.InsertColumn(x, "env. area", wx.LIST_FORMAT_RIGHT)
                x += 1

            elif column == "envint":
                self.peakList.InsertColumn(x, "sum. env. int.", wx.LIST_FORMAT_RIGHT)
                x += 1

            elif column == "base":
                self.peakList.InsertColumn(x, "base", wx.LIST_FORMAT_RIGHT)
                x += 1

            elif column == "rel":
                self.peakList.InsertColumn(x, "r. int.", wx.LIST_FORMAT_RIGHT)
                x += 1

            elif column == "sn":
                self.peakList.InsertColumn(x, "s/n", wx.LIST_FORMAT_RIGHT)
                x += 1

            elif column == "z":
                self.peakList.InsertColumn(x, "z", wx.LIST_FORMAT_RIGHT)
                x += 1

            elif column == "mass":
                self.peakList.InsertColumn(x, "mass", wx.LIST_FORMAT_RIGHT)
                x += 1

            elif column == "fwhm":
                self.peakList.InsertColumn(x, "fwhm", wx.LIST_FORMAT_RIGHT)
                x += 1

            elif column == "resol":
                self.peakList.InsertColumn(x, "resol.", wx.LIST_FORMAT_RIGHT)
                x += 1

            elif column == "group":
                self.peakList.InsertColumn(x, "group", wx.LIST_FORMAT_LEFT)
                x += 1

            else:
                continue

        self._autosizePeakListColumns()

    # ----

    def makeEditor(self):
        """Make panel for peak editing."""

        # init panel
        panel = mwx.bgrPanel(self, -1, images.lib["bgrPeakEditor"])

        # make elements
        peakMz_label = wx.StaticText(panel, -1, "m/z:")
        self.peakMz_value = wx.TextCtrl(
            panel,
            -1,
            "",
            size=wx.Size(80, mwx.SMALL_TEXTCTRL_HEIGHT),
            validator=mwx.validator("floatPos"),
        )
        peakMz_label.SetFont(wx.SMALL_FONT)
        self.peakMz_value.SetFont(wx.SMALL_FONT)

        peakAi_label = wx.StaticText(panel, -1, "a.i.:")
        self.peakAi_value = wx.TextCtrl(
            panel,
            -1,
            "",
            size=wx.Size(80, mwx.SMALL_TEXTCTRL_HEIGHT),
            validator=mwx.validator("floatPos"),
        )
        peakAi_label.SetFont(wx.SMALL_FONT)
        self.peakAi_value.SetFont(wx.SMALL_FONT)

        peakBase_label = wx.StaticText(panel, -1, "base:")
        self.peakBase_value = wx.TextCtrl(
            panel,
            -1,
            "",
            size=wx.Size(80, mwx.SMALL_TEXTCTRL_HEIGHT),
            style=wx.TE_PROCESS_ENTER,
            validator=mwx.validator("floatPos"),
        )
        peakBase_label.SetFont(wx.SMALL_FONT)
        self.peakBase_value.SetFont(wx.SMALL_FONT)

        peakSN_label = wx.StaticText(panel, -1, "s/n:")
        self.peakSN_value = wx.TextCtrl(
            panel,
            -1,
            "",
            size=wx.Size(80, mwx.SMALL_TEXTCTRL_HEIGHT),
            validator=mwx.validator("floatPos"),
        )
        peakSN_label.SetFont(wx.SMALL_FONT)
        self.peakSN_value.SetFont(wx.SMALL_FONT)

        peakCharge_label = wx.StaticText(panel, -1, "charge:")
        self.peakCharge_value = wx.TextCtrl(
            panel,
            -1,
            "",
            size=wx.Size(80, mwx.SMALL_TEXTCTRL_HEIGHT),
            validator=mwx.validator("int"),
        )
        peakCharge_label.SetFont(wx.SMALL_FONT)
        self.peakCharge_value.SetFont(wx.SMALL_FONT)

        peakFwhm_label = wx.StaticText(panel, -1, "fwhm:")
        self.peakFwhm_value = wx.TextCtrl(
            panel,
            -1,
            "",
            size=wx.Size(80, mwx.SMALL_TEXTCTRL_HEIGHT),
            style=wx.TE_PROCESS_ENTER,
            validator=mwx.validator("floatPos"),
        )
        peakFwhm_label.SetFont(wx.SMALL_FONT)
        self.peakFwhm_value.SetFont(wx.SMALL_FONT)

        self.peakFwhmLock_check = wx.CheckBox(panel, -1, "lock")
        self.peakFwhmLock_check.SetFont(wx.SMALL_FONT)
        self.peakFwhmLock_check.SetToolTip(wx.ToolTip(
            "Lock this FWHM: keep the manual width when envelope areas are "
            "recalculated instead of re-measuring it from the profile. "
            "Unlock to let the width be measured again."
        ))

        peakGroup_label = wx.StaticText(panel, -1, "group:")
        self.peakGroup_value = wx.TextCtrl(
            panel,
            -1,
            "",
            size=wx.Size(80, mwx.SMALL_TEXTCTRL_HEIGHT),
            style=wx.TE_PROCESS_ENTER,
        )
        peakGroup_label.SetFont(wx.SMALL_FONT)
        self.peakGroup_value.SetFont(wx.SMALL_FONT)

        self.peakMonoisotopic_check = wx.CheckBox(panel, -1, "monoisotopic")
        self.peakMonoisotopic_check.SetValue(True)
        self.peakMonoisotopic_check.SetFont(wx.SMALL_FONT)

        self.peakAdd_butt = wx.Button(
            panel, -1, "Add", size=wx.Size(-1, mwx.SMALL_BUTTON_HEIGHT)
        )
        self.peakAdd_butt.Bind(wx.EVT_BUTTON, self.onAddPeak)

        self.peakReplace_butt = wx.Button(
            panel, -1, "Update", size=wx.Size(-1, mwx.SMALL_BUTTON_HEIGHT)
        )
        self.peakReplace_butt.Bind(wx.EVT_BUTTON, self.onReplacePeak)
        self.peakReplace_butt.Enable(False)

        # pack elements
        grid = wx.GridBagSizer(mwx.GRIDBAG_VSPACE, mwx.GRIDBAG_HSPACE)
        grid.Add(peakMz_label, (0, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.peakMz_value, (0, 1), flag=wx.EXPAND)
        grid.Add(peakAi_label, (1, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.peakAi_value, (1, 1), flag=wx.EXPAND)
        grid.Add(peakBase_label, (2, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.peakBase_value, (2, 1), flag=wx.EXPAND)
        grid.Add(peakSN_label, (3, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.peakSN_value, (3, 1), flag=wx.EXPAND)
        grid.Add(
            peakCharge_label, (4, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
        )
        grid.Add(self.peakCharge_value, (4, 1), flag=wx.EXPAND)
        grid.Add(peakFwhm_label, (5, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.peakFwhm_value, (5, 1), flag=wx.EXPAND)
        grid.Add(
            self.peakFwhmLock_check, (5, 2), flag=wx.ALIGN_LEFT | wx.ALIGN_CENTER_VERTICAL
        )
        grid.Add(
            peakGroup_label, (6, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
        )
        grid.Add(self.peakGroup_value, (6, 1), flag=wx.EXPAND)
        grid.Add(
            self.peakMonoisotopic_check,
            (7, 1),
            flag=wx.ALIGN_LEFT | wx.ALIGN_CENTER_VERTICAL,
        )
        grid.AddGrowableCol(1)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(self.peakAdd_butt, 0, wx.RIGHT, 10)
        buttons.Add(self.peakReplace_butt, 0)

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        mainSizer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        mainSizer.Add(buttons, 0, wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT | wx.BOTTOM, 10)

        # fit layout
        mainSizer.Fit(panel)
        panel.SetSizer(mainSizer)

        return panel

    # ----

    def _showPeakEditor(self):
        """Show the peak editor.

        The editor is a tall, fixed-height panel that does not fit when the
        peak list is docked at the bottom, so make sure we are in a layout
        with the list docked on the (tall) right-hand side first."""

        self.parent.ensurePeaklistEditorLayout()
        self.editPeak_butt.SetBitmapLabel(images.lib["peaklistEditorOn"])
        self.mainSizer.Show(1)
        self.Layout()

    # ----

    def _hidePeakEditor(self):
        """Hide the peak editor."""

        self.editPeak_butt.SetBitmapLabel(images.lib["peaklistEditorOff"])
        self.mainSizer.Hide(1)
        self.Layout()

    # ----

    def onItemSelected(self, evt):
        """Highlight selected peak in the spectrum and refresh peak editor."""

        evt.Skip()

        if getattr(self, '_ignore_selection_events', False):
            return

        # get selected peak
        document = self.currentDocument
        if document is None:
            return

        self.selectedPeak = evt.GetData()
        peak = document.spectrum.peaklist[self.selectedPeak]

        # highlight point in the spectrum
        selected = self.peakList.getSelected()
        if len(selected) == 1:
            self._selectedMz = peak.mz
            self._renderEnvelope(peak)
        else:
            self._selectedMz = None
            self.parent.updateTmpSpectrum(None)

        # show current peak in editing panel
        self.updatePeakEditor(peak)

    # ----

    def _renderEnvelope(self, peak):
        """Draw the envelope profile overlay (or just the mass point) for a peak.

        Always replaces whatever overlay was shown before, so a stale envelope
        from a previous selection or a pre-recalculation state can never linger.
        """

        envelope = self._getEnvelopeData(peak)
        if envelope:
            profile = mspy.envelopeprofile(envelope, points=40)
            if len(profile):
                self.parent.updateTmpSpectrum(
                    profile,
                    fillUnder=True,
                    fillUnderAlpha=115,
                    showOutline=False,
                )
                # centre the view on the labelled (monoisotopic) peak, not on
                # the middle of the envelope, so the isotopes trail off to the
                # right and the view only widens if they do not fit
                self.parent.updateMassPoints(
                    [x[0] for x in envelope["isotopes"]], anchor=peak.mz
                )
                return

        self.parent.updateTmpSpectrum(None)
        self.parent.updateMassPoints([peak.mz])

    # ----

    def _getEnvelopeData(self, peak):
        """Get envelope metadata for selected peak if available."""

        document = self.currentDocument
        if document is None:
            return None

        envelope = peak.attributes.get("envelope")
        if envelope and envelope.get("isotopes"):
            return envelope

        # try to infer from grouped isotope labels
        if peak.group:
            isotopes = [
                p
                for p in document.spectrum.peaklist
                if p.group == peak.group and p.charge == peak.charge
            ]
            if len(isotopes) > 1:
                isotopes.sort(key=lambda p: p.mz)
                total = sum([max(0.0, p.intensity) for p in isotopes])
                if total > 0.0:
                    weights = [max(0.0, p.intensity) / total for p in isotopes]
                else:
                    weights = [1.0 / len(isotopes)] * len(isotopes)
                fwhmValues = [p.fwhm for p in isotopes if p.fwhm]
                fwhm = 0.1
                if fwhmValues:
                    fwhm = sum(fwhmValues) / float(len(fwhmValues))
                sigma = fwhm / (2.0 * (2.0 * 0.69314718056) ** 0.5)
                area = total * sigma * (2.0 * 3.14159265359) ** 0.5
                return {
                    "area": area,
                    "fwhm": fwhm,
                    "shape": "gaussian",
                    "isotopes": [(p.mz, weights[i]) for i, p in enumerate(isotopes)],
                }

        return None

    # ----

    def onItemActivated(self, evt):
        """Create annotation for activated peak."""
        self.onAnnotate()

    # ----

    def onItemRMU(self, evt):
        """Show item pop-up menu."""

        evt.Skip()

        # check document and selected peak
        if self.currentDocument is None or (
            self.selectedPeak is None and not self.peakList.getSelected()
        ):
            return

        # popup menu
        menu = wx.Menu()
        menu.Append(ID_peaklistAnnotate, "Annotate Peak...", "")
        menu.AppendSeparator()
        menu.Append(ID_peaklistSendToMassToFormula, "Send to Mass to Formula...", "")
        menu.Append(ID_peaklistConvertToEnvelopes, "Convert to Envelopes", "")
        menu.Append(
            ID_peaklistConvertAllToEnvelopes,
            "Convert All to Envelopes\tCtrl+Shift+A",
            "",
        )

        # bind events
        self.Bind(wx.EVT_MENU, self.onAnnotate, id=ID_peaklistAnnotate)
        self.Bind(
            wx.EVT_MENU, self.onSendToMassToFormula, id=ID_peaklistSendToMassToFormula
        )
        self.Bind(
            wx.EVT_MENU,
            self.convertSelectedPeaksToEnvelopes,
            id=ID_peaklistConvertToEnvelopes,
        )
        self.Bind(
            wx.EVT_MENU,
            self.convertAllPeaksToEnvelopes,
            id=ID_peaklistConvertAllToEnvelopes,
        )

        # show menu
        self.PopupMenu(menu)
        menu.Destroy()

    # ----

    def onColumnRMU(self, evt):
        """Show column popup menu."""

        menu = wx.Menu()
        menu.Append(ID_viewPeaklistColumnMz, "m/z", "", wx.ITEM_CHECK)
        menu.Append(ID_viewPeaklistColumnAi, "a.i", "", wx.ITEM_CHECK)
        menu.Append(ID_viewPeaklistColumnInt, "Intensity", "", wx.ITEM_CHECK)
        menu.Append(ID_viewPeaklistColumnBase, "Baseline", "", wx.ITEM_CHECK)
        menu.Append(ID_viewPeaklistColumnRel, "Rel. Intensity", "", wx.ITEM_CHECK)
        menu.Append(ID_viewPeaklistColumnSn, "s/n", "", wx.ITEM_CHECK)
        menu.Append(ID_viewPeaklistColumnZ, "Charge", "", wx.ITEM_CHECK)
        menu.Append(ID_viewPeaklistColumnMass, "Mass", "", wx.ITEM_CHECK)
        menu.Append(ID_viewPeaklistColumnEnvArea, "Env. Area", "", wx.ITEM_CHECK)
        menu.Append(
            ID_viewPeaklistColumnEnvInt, "Summed Env. Intensity", "", wx.ITEM_CHECK
        )
        menu.Append(ID_viewPeaklistColumnFwhm, "FWHM", "", wx.ITEM_CHECK)
        menu.Append(ID_viewPeaklistColumnResol, "Resolution", "", wx.ITEM_CHECK)
        menu.Append(ID_viewPeaklistColumnGroup, "Group", "", wx.ITEM_CHECK)

        menu.Check(
            ID_viewPeaklistColumnMz, bool("mz" in config.main["peaklistColumns"])
        )
        menu.Check(
            ID_viewPeaklistColumnAi, bool("ai" in config.main["peaklistColumns"])
        )
        menu.Check(
            ID_viewPeaklistColumnInt, bool("int" in config.main["peaklistColumns"])
        )
        menu.Check(
            ID_viewPeaklistColumnBase, bool("base" in config.main["peaklistColumns"])
        )
        menu.Check(
            ID_viewPeaklistColumnRel, bool("rel" in config.main["peaklistColumns"])
        )
        menu.Check(
            ID_viewPeaklistColumnSn, bool("sn" in config.main["peaklistColumns"])
        )
        menu.Check(ID_viewPeaklistColumnZ, bool("z" in config.main["peaklistColumns"]))
        menu.Check(
            ID_viewPeaklistColumnMass, bool("mass" in config.main["peaklistColumns"])
        )
        menu.Check(
            ID_viewPeaklistColumnEnvArea,
            bool("envarea" in config.main["peaklistColumns"]),
        )
        menu.Check(
            ID_viewPeaklistColumnEnvInt,
            bool("envint" in config.main["peaklistColumns"]),
        )
        menu.Check(
            ID_viewPeaklistColumnFwhm, bool("fwhm" in config.main["peaklistColumns"])
        )
        menu.Check(
            ID_viewPeaklistColumnResol, bool("resol" in config.main["peaklistColumns"])
        )
        menu.Check(
            ID_viewPeaklistColumnGroup, bool("group" in config.main["peaklistColumns"])
        )

        self.Bind(
            wx.EVT_MENU, self.parent.onViewPeaklistColumns, id=ID_viewPeaklistColumnMz
        )
        self.Bind(
            wx.EVT_MENU, self.parent.onViewPeaklistColumns, id=ID_viewPeaklistColumnAi
        )
        self.Bind(
            wx.EVT_MENU, self.parent.onViewPeaklistColumns, id=ID_viewPeaklistColumnInt
        )
        self.Bind(
            wx.EVT_MENU, self.parent.onViewPeaklistColumns, id=ID_viewPeaklistColumnBase
        )
        self.Bind(
            wx.EVT_MENU, self.parent.onViewPeaklistColumns, id=ID_viewPeaklistColumnRel
        )
        self.Bind(
            wx.EVT_MENU, self.parent.onViewPeaklistColumns, id=ID_viewPeaklistColumnSn
        )
        self.Bind(
            wx.EVT_MENU, self.parent.onViewPeaklistColumns, id=ID_viewPeaklistColumnZ
        )
        self.Bind(
            wx.EVT_MENU, self.parent.onViewPeaklistColumns, id=ID_viewPeaklistColumnMass
        )
        self.Bind(
            wx.EVT_MENU,
            self.parent.onViewPeaklistColumns,
            id=ID_viewPeaklistColumnEnvArea,
        )
        self.Bind(
            wx.EVT_MENU,
            self.parent.onViewPeaklistColumns,
            id=ID_viewPeaklistColumnEnvInt,
        )
        self.Bind(
            wx.EVT_MENU, self.parent.onViewPeaklistColumns, id=ID_viewPeaklistColumnFwhm
        )
        self.Bind(
            wx.EVT_MENU,
            self.parent.onViewPeaklistColumns,
            id=ID_viewPeaklistColumnResol,
        )
        self.Bind(
            wx.EVT_MENU,
            self.parent.onViewPeaklistColumns,
            id=ID_viewPeaklistColumnGroup,
        )

        self.PopupMenu(menu)
        menu.Destroy()

    # ----

    def onListKey(self, evt):
        """Key pressed."""

        # get key
        key = evt.GetKeyCode()

        # select all -- plain Ctrl+A only. Ctrl+SHIFT+A must NOT be swallowed here:
        # it is "Convert All to Envelopes", a global accelerator on the main frame
        # (frame accelerator table). This branch consumes the event (no evt.Skip()),
        # so without the Shift guard Ctrl+Shift+A selected-all whenever the list had
        # focus and the accelerator never fired -- the "only selects all" bug.
        if key == 65 and evt.CmdDown() and not evt.ShiftDown():
            for x in range(self.peakList.GetItemCount()):
                self.peakList.SetItemState(
                    x, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED
                )

        # copy
        elif key == 67 and evt.CmdDown():
            self.copyToClipboard()

        # delete
        elif key == wx.WXK_DELETE or (key == wx.WXK_BACK and evt.CmdDown()):
            self.onDeleteSelected()

        # other keys
        else:
            evt.Skip()

    # ----

    def onAdd(self, evt):
        """Plus button pressed."""

        # check document
        if self.currentDocument is None:
            wx.Bell()
            return

        # empty data in peak editor
        self.updatePeakEditor(None)

        # show editing panel if not shown
        if not self.mainSizer.IsShown(1):
            self._showPeakEditor()

    # ----

    def onDelete(self, evt):
        """Minus button pressed."""

        # check document
        if self.currentDocument is None:
            wx.Bell()
            return

        # popup menu
        menuDeleteSelectedID = wx.NewId()
        menuDeleteByThresholdID = wx.NewId()
        menuDeleteAllID = wx.NewId()

        menu = wx.Menu()
        menu.Append(menuDeleteSelectedID, "Delete Selected")
        menu.Append(menuDeleteByThresholdID, "Delete by Threshold...")
        menu.AppendSeparator()
        menu.Append(menuDeleteAllID, "Delete All")

        self.Bind(wx.EVT_MENU, self.onDeleteSelected, id=menuDeleteSelectedID)
        self.Bind(wx.EVT_MENU, self.onDeleteByThreshold, id=menuDeleteByThresholdID)
        self.Bind(wx.EVT_MENU, self.onDeleteAll, id=menuDeleteAllID)

        self.PopupMenu(menu)
        menu.Destroy()

    # ----

    def onAnnotate(self, evt=None):
        """Annotate selected peak."""

        # check document and selected peak
        if self.currentDocument is None or self.selectedPeak is None:
            wx.Bell()
            return

        # make annotation
        peak = self.currentDocument.spectrum.peaklist[self.selectedPeak]
        annot = doc.annotation(
            label="", mz=peak.mz, ai=peak.ai, base=peak.base, charge=peak.charge
        )

        # get annotation label
        dlg = dlgNotation(self.parent, annot, button="Add")
        if dlg.ShowModal() == wx.ID_OK:
            dlg.Destroy()
        else:
            dlg.Destroy()
            return

        # add annotation
        self.currentDocument.backup(("annotations"))
        self.currentDocument.annotations.append(annot)
        self.currentDocument.sortAnnotations()
        self.parent.onDocumentChanged(items=("annotations"))

    # ----

    def onEdit(self, evt):
        """Show / hide peak editing panel."""

        # hide peak editing panel
        if self.mainSizer.IsShown(1):
            self._hidePeakEditor()

        # show peak editing panel
        else:
            self._showPeakEditor()

    # ----

    def onDeleteSelected(self, evt=None):
        """Delete selected peaks."""

        # check document
        if self.currentDocument is None:
            wx.Bell()
            return

        # get selected peaks
        selected_rows = self.peakList.getSelected()
        if not selected_rows:
            return

        indexes = []
        for item in selected_rows:
            indexes.append(self.peakList.GetItemData(item))

        # update data
        self.currentDocument.backup(("spectrum"))

        peaklist = self.currentDocument.spectrum.peaklist
        deleted_mzs = [peaklist[i].mz for i in indexes]

        self.currentDocument.spectrum.peaklist.delete(indexes)

        # recalculate local envelope areas for remaining overlapping clusters
        self._recalculateNeighborhoodEnvelopes(deleted_mzs)

        self.parent.onDocumentChanged(items=("spectrum"))

    def _envelopeParams(self, seedCharge=1):
        """Build the plain parameter dict for the pure envelope recalc helper."""

        d = config.processing["deisotoping"]
        return {
            "massTolerance": d["massTolerance"],
            "isotopeShift": d["isotopeShift"],
            "maxCharge": d["maxCharge"],
            "intTolerance": d["intTolerance"],
            "labelEnvelope": d["labelEnvelope"],
            "envelopeIntensity": d["envelopeIntensity"],
            "envelopeNonIdeality": d["envelopeNonIdeality"],
            "averagineType": config.processing["peakpicking"].get(
                "averagineType", "protein"
            ),
            "seedCharge": seedCharge,
        }

    def _recalculateNeighborhoodEnvelopes(
        self, mzs, document=None, selectedOnly=False, respectFwhm=False,
    ):
        """Recalculate NNLS areas for envelopes in the neighborhood of edited peaks.

        Only ENVELOPES are recalculated. Plain peaks around the edit are never
        converted, absorbed or relabelled -- they only take part in the joint area
        fit so the envelopes cannot over-claim their signal. A peak becomes an
        envelope solely through the explicit "convert to envelopes" action.

        selectedOnly (bool) - when True, only the given peaks and the existing
            envelopes they overlap are re-fit (used for a FWHM edit / lock toggle,
            which must not re-deisotope the surrounding neighbourhood). When False
            (the auto-recalc after a delete / charge change) the envelopes in the
            margin-window neighbourhood are re-fit as a whole.
        respectFwhm (bool) - when True the current FWHM of every peak in the fit is
            kept as-is (not re-measured), so a directly typed width takes effect.
        """
        if not mzs:
            return

        targetDocument = document or self.currentDocument
        if targetDocument is None:
            return

        # We assume edited peaks retain their existing charges, so seedCharge = 1
        # is just a fallback for any peak that has no charge assigned.
        spectrum = targetDocument.spectrum
        spectrum.peaklist = mspy.recalculate_neighborhood_envelopes(
            spectrum.peaklist,
            spectrum.profile,
            mzs,
            self._envelopeParams(seedCharge=1),
            selectedOnly=selectedOnly,
            respectFwhm=respectFwhm,
        )

    # ----

    # ---

    def onDeleteByThreshold(self, evt=None):
        """Delete peaks by selected threshold."""

        # check document
        if self.currentDocument is None:
            wx.Bell()
            return

        # show threshold dialog
        dlg = dlgThreshold(self.parent)
        if dlg.ShowModal() == wx.ID_OK:
            threshold, thresholdType = dlg.getData()
            dlg.Destroy()

            if threshold is None:
                return

            indexes = []

            # use m/z
            if thresholdType == "m/z":
                for i, peak in enumerate(self.currentDocument.spectrum.peaklist):
                    if peak.mz < threshold:
                        indexes.append(i)

            # use a.i.
            elif thresholdType == "a.i.":
                for i, peak in enumerate(self.currentDocument.spectrum.peaklist):
                    if peak.ai < threshold:
                        indexes.append(i)

            # use intensity
            if thresholdType == "Intensity":
                for i, peak in enumerate(self.currentDocument.spectrum.peaklist):
                    if peak.intensity < threshold:
                        indexes.append(i)

            # use relative intensity
            elif thresholdType == "Relative Intensity":
                threshold /= 100
                for i, peak in enumerate(self.currentDocument.spectrum.peaklist):
                    if peak.ri < threshold:
                        indexes.append(i)

            # use s/n
            elif thresholdType == "s/n":
                for i, peak in enumerate(self.currentDocument.spectrum.peaklist):
                    if peak.sn is not None and peak.sn < threshold:
                        indexes.append(i)

            # delete peaks
            if indexes:
                self.currentDocument.backup(("spectrum"))

                peaklist = self.currentDocument.spectrum.peaklist
                deleted_mzs = [peaklist[i].mz for i in indexes]

                self.currentDocument.spectrum.peaklist.delete(indexes)

                self._recalculateNeighborhoodEnvelopes(deleted_mzs)

                self.parent.onDocumentChanged(items=("spectrum"))

        else:
            dlg.Destroy()
            return

    # ----

    def onDeleteAll(self, evt=None):
        """Delete all peaks."""

        # check document
        if self.currentDocument is None:
            wx.Bell()
            return

        # empty peaklist
        self.currentDocument.backup(("spectrum"))
        self.currentDocument.spectrum.peaklist.empty()
        self.parent.onDocumentChanged(items=("spectrum"))

    # ----

    def onAddPeak(self, evt):
        """Get peak data and add peak."""

        # check document
        document = self.currentDocument
        if document is None:
            wx.Bell()
            return

        # add new peak
        peak = self.getPeakEditorData()
        if peak:
            document.backup(("spectrum"))
            document.spectrum.peaklist.append(peak)

            self.parent.onDocumentChanged(items=("spectrum"))

        # set focus to mz
        self.peakMz_value.SetFocus()

    # ----

    def onReplacePeak(self, evt):
        """Get peak data and refresh current peak."""

        # check selection
        if self.selectedPeak is None:
            wx.Bell()
            return

        document = self.currentDocument
        if document is None:
            wx.Bell()
            return

        # set new data to peak
        original_peak = document.spectrum.peaklist[self.selectedPeak]
        peak = self.getPeakEditorData(original_peak=original_peak)
        if peak:
            document.backup(("spectrum"))

            # apply the FWHM lock state from the editor before storing the peak
            lock = self.peakFwhmLock_check.GetValue()
            if hasattr(peak, "attributes"):
                if lock:
                    peak.attributes["_fwhmLocked"] = True
                else:
                    peak.attributes.pop("_fwhmLocked", None)

            document.spectrum.peaklist[self.selectedPeak] = peak

            wasLocked = bool(getattr(original_peak, "attributes", {}).get("_fwhmLocked"))
            fwhmChanged = original_peak.fwhm != peak.fwhm
            lockChanged = wasLocked != bool(lock)
            isEnvelope = bool(getattr(peak, "attributes", {}).get("envelope"))

            # keep the edited peak selected after the list is rebuilt (an Update is
            # an explicit action on it, so it should not deselect)
            keepMz = peak.mz
            recomputed = False

            if original_peak.charge != peak.charge:
                # The stored envelope's isotope positions encode the old
                # charge's spacing (1/charge). Drop the positions so the
                # envelope is re-modeled from the profile at the new charge
                # instead of being rebuilt verbatim from the stale ones -- but
                # KEEP the envelope itself, otherwise the peak looks plain to
                # the recalc (which only ever touches envelopes) and would
                # silently stop being an envelope. Without a charge, or on a
                # non-monoisotopic peak, there is no envelope to model, so the
                # stale one is dropped for good.
                env = getattr(peak, "attributes", {}).get("envelope")
                if isinstance(env, dict):
                    if peak.charge and peak.isotope in (None, 0):
                        env = dict(env)
                        env["isotopes"] = []
                        peak.attributes["envelope"] = env
                    else:
                        peak.attributes.pop("envelope", None)
                # a plain peak is never converted here: this only re-apportions
                # the areas of envelopes that already exist around the edit
                self._recalculateNeighborhoodEnvelopes([original_peak.mz, peak.mz])
                recomputed = True
            elif isEnvelope and (fwhmChanged or lockChanged):
                # A FWHM edit (or lock toggle) changes the envelope area (area
                # scales with peak width). Re-fit this envelope and any it overlaps,
                # applying the typed width THIS time (respectFwhm) regardless of the
                # lock. The lock only governs later auto-recalcs triggered by other
                # peaks: locked keeps this width, unlocked lets it be re-measured.
                self._recalculateNeighborhoodEnvelopes(
                    [peak.mz], selectedOnly=True, respectFwhm=True
                )
                recomputed = True

            self.parent.onDocumentChanged(items=("spectrum"))

            # the recompute replaces the peaklist and the rebuild clears the
            # selection; restore it (by m/z) so the edited peak stays selected
            if recomputed:
                self._selectedMz = keepMz
                self.restoreEnvelopeSelection()

    # ----

    def onSendToMassToFormula(self, evt=None):
        """Send selected peak to mass to formula tool."""

        # check document and selected peak
        if self.currentDocument is None or self.selectedPeak is None:
            wx.Bell()
            return

        # get peak data
        peak = self.currentDocument.spectrum.peaklist[self.selectedPeak]

        # send peak to mass to formula tool
        self.parent.onToolsMassToFormula(mass=peak.mz, charge=peak.charge)

    # ----

    def setData(self, document):
        """Set new document."""

        # switching documents: drop the remembered selection so it is not
        # carried over (by m/z) onto an unrelated peak in the new document
        if document is not self.currentDocument:
            self._selectedMz = None

        # set new data
        self.currentDocument = document

        # update peaklist
        self.updatePeakList()

    # ----

    def updatePeaklistColumns(self):
        """Set new peaklist columns and update."""

        self.makePeakListColumns()
        self.Layout()
        self.updatePeakList()

    # ----

    def updatePeakList(self):
        """Refresh peaklist."""

        self._ignore_selection_events = True

        top_item = self.peakList.GetTopItem() if self.peakList.GetItemCount() > 0 else 0

        # clear previous data
        self.peakList.DeleteAllItems()
        self.selectedPeak = None
        self.updatePeakEditor(None)

        # Drop any drawn envelope: the rebuilt list has no selection, so a
        # profile left over from before the rebuild (a now-recalculated or
        # deleted envelope) must not stay on screen. We do NOT re-select here --
        # that would yank the user back to the old envelope whenever they edit
        # or label a peak elsewhere. Undo/redo restores the selection explicitly
        # (see restoreEnvelopeSelection), which is the only place it is wanted.
        self.parent.updateTmpSpectrum(None)

        # The isotope arrows are a second, independent overlay drawn straight
        # into the canvas buffer and they survive a redraw, so clearing only the
        # profile leaves the old envelope's arrows behind as an after-image
        # (pointing at isotopes that were just re-fit or deleted). Drop them too;
        # whoever re-selects a peak afterwards (incl. restoreEnvelopeSelection)
        # draws them again from the fresh data.
        self.parent.updateMassPoints(None)

        # check data
        if not self.currentDocument:
            self.peaksCount.SetLabel("")
            self.peakListMap = None
            self.peakList.setDataMap(None)
            self._selectedMz = None
            self._ignore_selection_events = False
            return

        # update peaks count
        count = "%d" % len(self.currentDocument.spectrum.peaklist)
        if count != "0":
            self.peaksCount.SetLabel(count)
        else:
            self.peaksCount.SetLabel("")

        # set new data map
        self.peakListMap = []
        for peak in self.currentDocument.spectrum.peaklist:
            row = []
            for column in config.main["peaklistColumns"]:
                if column == "mz":
                    row.append(peak.mz)
                elif column == "ai":
                    row.append(peak.ai)
                elif column == "int":
                    row.append(peak.intensity)
                elif column == "envarea":
                    envelope = peak.attributes.get("envelope", {})
                    row.append(envelope.get("area"))
                elif column == "envint":
                    envelope = peak.attributes.get("envelope", {})
                    row.append(envelope.get("sumint"))
                elif column == "base":
                    row.append(peak.base)
                elif column == "rel":
                    row.append(peak.ri * 100)
                elif column == "sn":
                    row.append(peak.sn)
                elif column == "z":
                    row.append(peak.charge)
                elif column == "mass":
                    row.append(peak.mass())
                elif column == "fwhm":
                    row.append(peak.fwhm)
                elif column == "resol":
                    row.append(peak.resolution)
                elif column == "group":
                    row.append(peak.group)
                else:
                    continue

            self.peakListMap.append((row))

        self.peakList.setDataMap(self.peakListMap)

        # add new data
        for row, item in enumerate(self.peakListMap):
            self.updatePeakListItem(row, item, insert=True)
            self.peakList.SetItemData(row, row)

        # sort data
        self.peakList.sort()
        self._autosizePeakListColumns()

        # restore scroll position
        if len(self.currentDocument.spectrum.peaklist) > 0:
            if top_item > 0 and top_item < self.peakList.GetItemCount():
                self.peakList.EnsureVisible(self.peakList.GetItemCount() - 1)
                self.peakList.EnsureVisible(top_item)
            else:
                self.peakList.EnsureVisible(0)

        wx.CallAfter(lambda: setattr(self, '_ignore_selection_events', False))

    # ----

    def restoreEnvelopeSelection(self):
        """Re-select the previously selected peak and redraw its envelope.

        Called after undo/redo, where the spectrum is replaced and the list is
        rebuilt with no selection. We deliberately restore the selection (and
        bring it into view) only here -- an undo/redo is an explicit action on
        that peak -- and never on ordinary edits, so labeling or editing a peak
        elsewhere does not yank the user back to the old envelope.

        Matching is by m/z, since row indices are not stable across a rebuild.
        If the peak no longer exists (removed or merged) the overlay is left
        cleared.
        """

        if self.currentDocument is None or self._selectedMz is None:
            return

        peaklist = self.currentDocument.spectrum.peaklist
        if not len(peaklist):
            return

        # nearest peak by m/z; reject if it is not essentially the same peak
        targetMz = self._selectedMz
        bestIndex = min(
            range(len(peaklist)), key=lambda i: abs(peaklist[i].mz - targetMz)
        )
        if abs(peaklist[bestIndex].mz - targetMz) > 0.1:
            return

        # map the peaklist index back to its (sorted) display row
        row = -1
        for r in range(self.peakList.GetItemCount()):
            if self.peakList.GetItemData(r) == bestIndex:
                row = r
                break
        if row == -1:
            return

        peak = peaklist[bestIndex]
        self.selectedPeak = bestIndex
        self._selectedMz = peak.mz
        # selection events may be suppressed during the rebuild, so draw directly
        self.peakList.Select(row)
        self.peakList.Focus(row)
        self.peakList.EnsureVisible(row)
        self._renderEnvelope(peak)
        self.updatePeakEditor(peak)

    # ----

    def _autosizePeakListColumns(self):
        """Autosize every column to fit its content and header.

        This mirrors the native "double-click the column border" behaviour
        (wx.LIST_AUTOSIZE) rather than imposing any hardcoded width, so the
        columns always shrink/grow to exactly fit the data. Users can still
        drag a column to a custom width; it resets to the fitted width on the
        next peaklist refresh.
        """

        columnCount = self.peakList.GetColumnCount()
        if columnCount == 0:
            return

        hasRows = self.peakList.GetItemCount() > 0

        if hasRows:
            # Pure content autosize, identical to double-clicking the column
            # border. No header floor or padding, otherwise a later double-click
            # would shrink the column further than this and the two would
            # disagree.
            for colIndex in range(columnCount):
                self.peakList.SetColumnWidth(colIndex, wx.LIST_AUTOSIZE)
            return

        # No rows: wx.LIST_AUTOSIZE collapses to nothing, so fit the header
        # text instead. Measure it ourselves rather than via
        # wx.LIST_AUTOSIZE_USEHEADER, which on wxMSW stretches the *last* column
        # to fill the remaining list width.
        dc = wx.ScreenDC()
        dc.SetFont(self.peakList.GetFont())
        padding = dc.GetTextExtent("MM")[0]
        for colIndex in range(columnCount):
            headerText = self.peakList.GetColumn(colIndex).GetText()
            self.peakList.SetColumnWidth(
                colIndex, dc.GetTextExtent(headerText)[0] + padding
            )

    # ----

    def updatePeakListItem(self, row, item, insert=False):
        """Refresh item data in the list."""

        # set formats
        mzFormat = "%0." + repr(config.main["mzDigits"]) + "f"
        intFormat = "%0." + repr(config.main["intDigits"]) + "f"
        fwhmFormat = "%0." + repr(max(config.main["mzDigits"], 3)) + "f"

        # insert data
        x = 0
        for column in config.main["peaklistColumns"]:

            # get data
            data = ""

            if column == "mz":
                data = mzFormat % (item[x])

            elif column == "ai":
                data = intFormat % (item[x])

            elif column == "int":
                data = intFormat % (item[x])

            elif column == "envarea":
                if item[x] is not None:
                    data = intFormat % (item[x])

            elif column == "envint":
                if item[x] is not None:
                    data = intFormat % (item[x])

            elif column == "base":
                data = intFormat % (item[x])

            elif column == "rel":
                if item[x]:
                    data = "%0.2f" % (item[x])

            elif column == "sn":
                if item[x] is not None:
                    data = "%0.1f" % (item[x])

            elif column == "z":
                if item[x] is not None:
                    data = str(item[x])

            elif column == "mass":
                if item[x]:
                    data = mzFormat % (item[x])

            elif column == "fwhm":
                if item[x]:
                    data = fwhmFormat % (item[x])

            elif column == "resol":
                if item[x]:
                    data = "%0.0f" % (item[x])

            elif column == "group":
                if item[x] is not None:
                    data = str(item[x])

            else:
                continue

            # add data
            if x == 0 and insert:
                self.peakList.InsertItem(row, data)
            else:
                self.peakList.SetItem(row, x, data)

            x += 1

    # ----

    def updatePeakEditor(self, peak=None):
        """Refresh peak editing panel."""

        # empty data
        self.peakMz_value.SetValue("")
        self.peakAi_value.SetValue("")
        self.peakBase_value.SetValue("")
        self.peakSN_value.SetValue("")
        self.peakCharge_value.SetValue("")
        self.peakFwhm_value.SetValue("")
        self.peakFwhmLock_check.SetValue(False)
        self.peakGroup_value.SetValue("")
        self.peakMonoisotopic_check.SetValue(True)
        self.peakReplace_butt.Enable(False)

        # set peak data
        if peak:
            self.peakMz_value.SetValue(str(round(peak.mz, 6)))
            self.peakAi_value.SetValue(str(peak.ai))
            self.peakBase_value.SetValue(str(peak.base))
            if peak.sn:
                self.peakSN_value.SetValue(str(round(peak.sn, 3)))
            if peak.charge:
                self.peakCharge_value.SetValue(str(peak.charge))
            if peak.fwhm:
                self.peakFwhm_value.SetValue(str(round(peak.fwhm, 6)))
            self.peakFwhmLock_check.SetValue(
                bool(getattr(peak, "attributes", {}).get("_fwhmLocked"))
            )
            if peak.group:
                self.peakGroup_value.SetValue(str(peak.group))
            if peak.isotope == 0:
                self.peakMonoisotopic_check.SetValue(True)
            else:
                self.peakMonoisotopic_check.SetValue(False)
            self.peakReplace_butt.Enable(True)

    # ----

    def getPeakEditorData(self, original_peak=None):
        """Get data of edited peak."""

        try:
            # get data
            mz = self.peakMz_value.GetValue()
            ai = self.peakAi_value.GetValue()
            base = self.peakBase_value.GetValue()
            sn = self.peakSN_value.GetValue()
            charge = self.peakCharge_value.GetValue()
            fwhm = self.peakFwhm_value.GetValue()
            group = self.peakGroup_value.GetValue()
            monoisotope = self.peakMonoisotopic_check.GetValue()

            # format data
            mz = float(mz)
            ai = float(ai)

            if ai == 0:
                raise ValueError

            if base:
                base = float(base)
            else:
                base = 0.0

            if sn:
                sn = float(sn)
            else:
                sn = None

            if charge:
                charge = int(charge)
            else:
                charge = None

            if fwhm:
                fwhm = float(fwhm)
            else:
                fwhm = None

            if not group:
                group = ""

            if monoisotope:
                isotope = 0
            else:
                isotope = None

            # make peak
            peak = mspy.peak(
                mz=mz,
                ai=ai,
                base=base,
                sn=sn,
                charge=charge,
                isotope=isotope,
                fwhm=fwhm,
                group=group,
            )
            if original_peak:
                peak.attributes = getattr(original_peak, 'attributes', {}).copy()
            return peak

        except Exception:
            wx.Bell()
            return False

    # ----

    def getSelectedPeaks(self):
        """Get selected peaks."""

        # get peaklist
        document = self.currentDocument
        if document is None:
            return []

        peaklist = []
        for item in self.peakList.getSelected():
            peak = document.spectrum.peaklist[self.peakList.GetItemData(item)]
            peaklist.append(peak)

        return peaklist

    # ----

    def convertSelectedPeaksToEnvelopes(self, evt=None):
        """Recalculate selected peak neighborhood into envelope labels."""

        if self.currentDocument is None:
            wx.Bell()
            return

        peaks = self.getSelectedPeaks()
        if not peaks and self.selectedPeak is not None:
            peaks = [self.currentDocument.spectrum.peaklist[self.selectedPeak]]
        if not peaks:
            wx.Bell()
            return

        seedCharge = self._getConvertEnvelopeCharge(peaks)

        spectrum = self.currentDocument.spectrum
        mzs = [peak.mz for peak in peaks]

        result = mspy.recalculate_neighborhood_envelopes(
            spectrum.peaklist,
            spectrum.profile,
            mzs,
            self._envelopeParams(seedCharge=seedCharge),
            selectedOnly=True,
        )

        # identity means the helper found no peaks in the neighborhood -> no-op
        if result is spectrum.peaklist:
            wx.Bell()
            return

        self.currentDocument.backup(("spectrum"))
        spectrum.peaklist = result
        self.parent.onDocumentChanged(items=("spectrum"))

    # ----

    def convertAllPeaksToEnvelopes(self, evt=None):
        """Recalculate the whole peak list into envelope labels at once.

        Runs the joint overlap-aware fit over every labelled peak and envelope in
        one pass, so the result does not depend on the order the peaks were
        converted in (unlike converting them one at a time). This is the
        order-independent reference behaviour; the per-selection action just
        applies it to a subset.
        """

        if self.currentDocument is None:
            wx.Bell()
            return

        spectrum = self.currentDocument.spectrum
        peaks = list(spectrum.peaklist)
        if not peaks:
            wx.Bell()
            return

        seedCharge = self._getConvertEnvelopeCharge(peaks)
        mzs = [peak.mz for peak in peaks]

        result = mspy.recalculate_neighborhood_envelopes(
            spectrum.peaklist,
            spectrum.profile,
            mzs,
            self._envelopeParams(seedCharge=seedCharge),
            selectedOnly=True,
        )

        # identity means the helper found nothing to do -> no-op
        if result is spectrum.peaklist:
            wx.Bell()
            return

        self.currentDocument.backup(("spectrum"))
        spectrum.peaklist = result
        self.parent.onDocumentChanged(items=("spectrum"))

    # ----

    def _getConvertEnvelopeCharge(self, peaks):
        """Get user-specified charge for envelope conversion, defaulting to 1."""

        # Prefer the selected peak charge so conversion respects user-edited values.
        for peak in peaks:
            if peak.charge:
                return int(peak.charge)

        charge = self.peakCharge_value.GetValue().strip()
        if charge:
            try:
                value = int(charge)
                if value:
                    return value
            except Exception:
                pass

        return 1

    # ----

    def copyToClipboard(self):
        """Copy current selection to clipboard."""

        # get selected
        selection = self.peakList.getSelected()
        if not selection:
            return

        document = self.currentDocument
        if document is None:
            return

        # show copy dialog
        dlg = dlgCopy(self.parent)
        if dlg.ShowModal() == wx.ID_OK:
            dlg.getData()
            dlg.Destroy()

            # export data
            buff = ""
            for row in selection:
                peak = document.spectrum.peaklist[self.peakList.GetItemData(row)]

                line = ""
                if "mz" in config.export["peaklistColumns"]:
                    line += str(peak.mz) + "\t"
                if "ai" in config.export["peaklistColumns"]:
                    line += str(peak.ai) + "\t"
                if "base" in config.export["peaklistColumns"]:
                    line += str(peak.base) + "\t"
                if "int" in config.export["peaklistColumns"]:
                    line += str(peak.intensity) + "\t"
                if "rel" in config.export["peaklistColumns"]:
                    line += str(peak.ri * 100) + "\t"
                if "sn" in config.export["peaklistColumns"]:
                    line += str(peak.sn) + "\t"
                if "z" in config.export["peaklistColumns"]:
                    line += str(peak.charge) + "\t"
                if "mass" in config.export["peaklistColumns"]:
                    line += str(peak.mass()) + "\t"
                if "fwhm" in config.export["peaklistColumns"]:
                    line += str(peak.fwhm) + "\t"
                if "resol" in config.export["peaklistColumns"]:
                    line += str(peak.resolution) + "\t"
                if "envarea" in config.export["peaklistColumns"]:
                    value = ""
                    envelope = peak.attributes.get("envelope")
                    if isinstance(envelope, dict) and "area" in envelope:
                        value = str(envelope["area"])
                    line += value + "\t"
                if "envint" in config.export["peaklistColumns"]:
                    value = ""
                    envelope = peak.attributes.get("envelope")
                    if isinstance(envelope, dict) and "sumint" in envelope:
                        value = str(envelope["sumint"])
                    line += value + "\t"
                if "group" in config.export["peaklistColumns"]:
                    line += str(peak.group) + "\t"
                buff += "%s\n" % (line.rstrip())

            # make text object for data
            obj = wx.TextDataObject()
            obj.SetText(buff.rstrip())

            # paste to clipboard
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(obj)
                wx.TheClipboard.Close()

        else:
            dlg.Destroy()

    # ----


class dlgThreshold(wx.Dialog):
    """Set threshold."""

    def __init__(self, parent):
        wx.Dialog.__init__(
            self,
            parent,
            -1,
            "Delete by Threshold",
            style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP,
        )

        self.parent = parent
        self.threshold = None

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

        staticSizer = wx.StaticBoxSizer(wx.StaticBox(self, -1, ""), wx.VERTICAL)

        # make elements
        threshold_label = wx.StaticText(self, -1, "Minimal value:")
        self.threshold_value = wx.TextCtrl(
            self, -1, "", size=wx.Size(150, -1), validator=mwx.validator("floatPos")
        )
        self.threshold_value.Bind(wx.EVT_TEXT, self.onChange)

        thresholdType_label = wx.StaticText(self, -1, "Threshold type:")
        choices = ["m/z", "a.i.", "Intensity", "Relative Intensity", "s/n"]
        self.thresholdType_choice = wx.Choice(
            self, -1, choices=choices, size=wx.Size(150, mwx.CHOICE_HEIGHT)
        )
        mwx.fitChoice(self.thresholdType_choice)
        self.thresholdType_choice.Select(0)

        cancel_butt = wx.Button(self, wx.ID_CANCEL, "Cancel")
        delete_butt = wx.Button(self, wx.ID_OK, "Delete")
        delete_butt.Bind(wx.EVT_BUTTON, self.onDelete)
        delete_butt.SetDefault()

        # pack elements
        grid = wx.GridBagSizer(mwx.GRIDBAG_VSPACE, mwx.GRIDBAG_HSPACE)
        grid.Add(
            threshold_label, (0, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
        )
        grid.Add(self.threshold_value, (0, 1))
        grid.Add(
            thresholdType_label, (1, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
        )
        grid.Add(self.thresholdType_choice, (1, 1))

        staticSizer.Add(grid, 0, wx.ALL, 5)

        buttSizer = wx.BoxSizer(wx.HORIZONTAL)
        buttSizer.Add(cancel_butt, 0, wx.RIGHT, 15)
        buttSizer.Add(delete_butt, 0)

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
            self.threshold = float(self.threshold_value.GetValue())
        except (TypeError, ValueError):
            self.threshold = None

    # ----

    def onDelete(self, evt):
        """Delete."""

        # check value and end
        if self.threshold is not None:
            self.EndModal(wx.ID_OK)
        else:
            wx.Bell()

    # ----

    def getData(self):
        """Return values."""
        return self.threshold, self.thresholdType_choice.GetStringSelection()

    # ----


class dlgCopy(wx.Dialog):
    """Set coumns to copy."""

    def __init__(self, parent):
        wx.Dialog.__init__(
            self,
            parent,
            -1,
            "Select Columns to Copy",
            style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP,
        )

        self.parent = parent

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

        staticSizer = wx.StaticBoxSizer(wx.StaticBox(self, -1, ""), wx.VERTICAL)

        # make elements
        self.peaklistColumnMz_check = wx.CheckBox(self, -1, "m/z")
        self.peaklistColumnMz_check.SetValue(
            config.export["peaklistColumns"].count("mz")
        )

        self.peaklistColumnAi_check = wx.CheckBox(self, -1, "a.i.")
        self.peaklistColumnAi_check.SetValue(
            config.export["peaklistColumns"].count("ai")
        )

        self.peaklistColumnBase_check = wx.CheckBox(self, -1, "Baseline")
        self.peaklistColumnBase_check.SetValue(
            config.export["peaklistColumns"].count("base")
        )

        self.peaklistColumnInt_check = wx.CheckBox(self, -1, "Intensity")
        self.peaklistColumnInt_check.SetValue(
            config.export["peaklistColumns"].count("int")
        )

        self.peaklistColumnRel_check = wx.CheckBox(self, -1, "Relative intensity")
        self.peaklistColumnRel_check.SetValue(
            config.export["peaklistColumns"].count("rel")
        )

        self.peaklistColumnSn_check = wx.CheckBox(self, -1, "s/n")
        self.peaklistColumnSn_check.SetValue(
            config.export["peaklistColumns"].count("sn")
        )

        self.peaklistColumnZ_check = wx.CheckBox(self, -1, "Charge")
        self.peaklistColumnZ_check.SetValue(config.export["peaklistColumns"].count("z"))

        self.peaklistColumnMass_check = wx.CheckBox(self, -1, "Mass")
        self.peaklistColumnMass_check.SetValue(
            config.export["peaklistColumns"].count("mass")
        )

        self.peaklistColumnFwhm_check = wx.CheckBox(self, -1, "FWHM")
        self.peaklistColumnFwhm_check.SetValue(
            config.export["peaklistColumns"].count("fwhm")
        )

        self.peaklistColumnResol_check = wx.CheckBox(self, -1, "Resolution")
        self.peaklistColumnResol_check.SetValue(
            config.export["peaklistColumns"].count("resol")
        )

        self.peaklistColumnEnvArea_check = wx.CheckBox(self, -1, "Env. Area")
        self.peaklistColumnEnvArea_check.SetValue(
            config.export["peaklistColumns"].count("envarea")
        )

        self.peaklistColumnEnvInt_check = wx.CheckBox(self, -1, "Summed Env. Int.")
        self.peaklistColumnEnvInt_check.SetValue(
            config.export["peaklistColumns"].count("envint")
        )

        self.peaklistColumnGroup_check = wx.CheckBox(self, -1, "Group")
        self.peaklistColumnGroup_check.SetValue(
            config.export["peaklistColumns"].count("group")
        )

        cancel_butt = wx.Button(self, wx.ID_CANCEL, "Cancel")
        copy_butt = wx.Button(self, wx.ID_OK, "Copy")
        copy_butt.SetDefault()

        # pack elements
        grid = wx.GridBagSizer(mwx.GRIDBAG_VSPACE, mwx.GRIDBAG_HSPACE)
        grid.Add(self.peaklistColumnMz_check, (0, 0))
        grid.Add(self.peaklistColumnAi_check, (1, 0))
        grid.Add(self.peaklistColumnBase_check, (2, 0))
        grid.Add(self.peaklistColumnInt_check, (3, 0))
        grid.Add(self.peaklistColumnRel_check, (4, 0))
        grid.Add(self.peaklistColumnSn_check, (5, 0))
        grid.Add(self.peaklistColumnZ_check, (0, 2))
        grid.Add(self.peaklistColumnMass_check, (1, 2))
        grid.Add(self.peaklistColumnFwhm_check, (2, 2))
        grid.Add(self.peaklistColumnResol_check, (3, 2))
        grid.Add(self.peaklistColumnEnvArea_check, (4, 2))
        grid.Add(self.peaklistColumnGroup_check, (5, 2))
        grid.Add(self.peaklistColumnEnvInt_check, (6, 0))

        staticSizer.Add(grid, 0, wx.ALL, 5)

        buttSizer = wx.BoxSizer(wx.HORIZONTAL)
        buttSizer.Add(cancel_butt, 0, wx.RIGHT, 15)
        buttSizer.Add(copy_butt, 0)

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

    def getData(self):
        """Set selected columns to export presets."""

        # get data
        config.export["peaklistColumns"] = []
        if self.peaklistColumnMz_check.IsChecked():
            config.export["peaklistColumns"].append("mz")
        if self.peaklistColumnAi_check.IsChecked():
            config.export["peaklistColumns"].append("ai")
        if self.peaklistColumnBase_check.IsChecked():
            config.export["peaklistColumns"].append("base")
        if self.peaklistColumnInt_check.IsChecked():
            config.export["peaklistColumns"].append("int")
        if self.peaklistColumnRel_check.IsChecked():
            config.export["peaklistColumns"].append("rel")
        if self.peaklistColumnZ_check.IsChecked():
            config.export["peaklistColumns"].append("z")
        if self.peaklistColumnMass_check.IsChecked():
            config.export["peaklistColumns"].append("mass")
        if self.peaklistColumnSn_check.IsChecked():
            config.export["peaklistColumns"].append("sn")
        if self.peaklistColumnFwhm_check.IsChecked():
            config.export["peaklistColumns"].append("fwhm")
        if self.peaklistColumnResol_check.IsChecked():
            config.export["peaklistColumns"].append("resol")
        if self.peaklistColumnEnvArea_check.IsChecked():
            config.export["peaklistColumns"].append("envarea")
        if self.peaklistColumnEnvInt_check.IsChecked():
            config.export["peaklistColumns"].append("envint")
        if self.peaklistColumnGroup_check.IsChecked():
            config.export["peaklistColumns"].append("group")

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
