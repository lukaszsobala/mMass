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
from . import alignment

# how much of the table the preview shows
PREVIEW_GROUPS = 12
PREVIEW_ROWS = 8

# ALIGNED TABLE EXPORT DIALOG
# ---------------------------


# how the separator is stored in config, and how it is shown
SEPARATORS = [
    ("tab", "Tab", "\t"),
    (",", "Comma", ","),
    (";", "Semicolon", ";"),
]

DUPLICATES = [
    (alignment.DUPLICATES_ROWS, "Put on their own rows"),
    (alignment.DUPLICATES_IGNORE, "Keep the most intense only"),
    (alignment.DUPLICATES_SUM, "Add up intensities"),
]

LAYOUTS = [
    (alignment.LAYOUT_COLUMN, "Wide, documents grouped by column"),
    (alignment.LAYOUT_DOCUMENT, "Wide, columns grouped by document"),
    (alignment.LAYOUT_LONG, "Long, one row per peak"),
]


class dlgExportAlignment(wx.Dialog):
    """Pick the columns of the aligned peak table, and where to put it."""

    def __init__(self, parent, groups, titles):

        wx.Dialog.__init__(
            self,
            parent,
            -1,
            "Export Alignment",
            style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP,
        )

        self.groups = groups
        self.titles = titles

        # the top of the table is all the preview shows, so that is all it
        # builds, however many groups there are
        self.previewGroups = alignment.firstGroups(groups, PREVIEW_GROUPS)

        # set by the accept buttons, read by the caller
        self.destination = None

        self.statChecks = {}
        self.peakChecks = {}

        # make GUI
        sizer = self.makeGUI()

        # fit layout
        self.Layout()
        sizer.Fit(self)
        self.SetSizer(sizer)
        self.SetMinSize(self.GetSize())

        # apply dark mode
        mwx.applyDarkMode(self)

        self.Centre()

    # ----

    def makeGUI(self):
        """Make GUI elements."""

        summary = wx.StaticText(
            self,
            -1,
            "%d group(s) of peaks across %d document(s)."
            % (len(self.groups), len(self.titles)),
        )

        stats = self.makeColumnBox(
            "Summary columns",
            alignment.STAT_COLUMNS,
            config.comparePeaklists["alignmentStats"],
            self.statChecks,
            rows=3,
        )

        columns = self.makeColumnBox(
            "Columns for each document",
            alignment.PEAK_COLUMNS,
            config.comparePeaklists["alignmentColumns"],
            self.peakChecks,
            rows=6,
        )

        options = self.makeOptions()
        preview = self.makePreview()
        buttons = self.makeButtons()

        # pack elements
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(
            summary, 0, wx.LEFT | wx.RIGHT | wx.TOP, mwx.PANEL_SPACE_MAIN
        )
        sizer.Add(
            stats,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            mwx.PANEL_SPACE_MAIN,
        )
        sizer.Add(
            columns,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            mwx.PANEL_SPACE_MAIN,
        )
        sizer.Add(
            options, 0, wx.LEFT | wx.RIGHT | wx.TOP, mwx.PANEL_SPACE_MAIN
        )
        sizer.Add(
            preview,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
            mwx.PANEL_SPACE_MAIN,
        )
        sizer.Add(buttons, 0, wx.CENTER | wx.ALL, mwx.PANEL_SPACE_MAIN)

        return sizer

    # ----

    def makeColumnBox(self, label, definitions, selected, store, rows):
        """A boxed block of checkboxes, one per available column."""

        sizer = mwx.staticBoxSizer(self, label, wx.VERTICAL)

        grid = wx.GridBagSizer(mwx.GRIDBAG_VSPACE, mwx.GRIDBAG_HSPACE)

        for index, (key, title) in enumerate(definitions):
            check = wx.CheckBox(self, -1, title)
            check.SetValue(key in selected)
            store[key] = check
            # fill column by column, so reading down a column follows the
            # order the columns are actually written in
            grid.Add(check, (index % rows, index // rows))

        sizer.Add(grid, 0, wx.ALL, mwx.PANEL_SPACE_MAIN // 2)

        return sizer

    # ----

    def makeOptions(self):
        """Duplicate handling and separator."""

        layout_label = wx.StaticText(self, -1, "Layout:")
        self.layout_choice = wx.Choice(
            self,
            -1,
            choices=[title for _key, title in LAYOUTS],
            size=wx.Size(200, mwx.CHOICE_HEIGHT),
        )
        mwx.fitChoice(self.layout_choice)
        self.layout_choice.Select(
            self.indexOf(
                [key for key, _title in LAYOUTS],
                config.comparePeaklists["alignmentLayout"],
            )
        )

        self.header_check = wx.CheckBox(self, -1, "Two-row header")
        self.header_check.SetValue(
            bool(config.comparePeaklists["alignmentTwoRowHeader"])
        )
        self.header_check.SetToolTip(
            "Name of the block above, name of the column below."
        )

        duplicates_label = wx.StaticText(self, -1, "Duplicate peaks:")
        self.duplicates_choice = wx.Choice(
            self,
            -1,
            choices=[title for _key, title in DUPLICATES],
            size=wx.Size(200, mwx.CHOICE_HEIGHT),
        )
        mwx.fitChoice(self.duplicates_choice)
        self.duplicates_choice.Select(
            self.indexOf(
                [key for key, _title in DUPLICATES],
                config.comparePeaklists["alignmentDuplicates"],
            )
        )

        separator_label = wx.StaticText(self, -1, "Separator:")
        self.separator_choice = wx.Choice(
            self,
            -1,
            choices=[title for _key, title, _value in SEPARATORS],
            size=wx.Size(200, mwx.CHOICE_HEIGHT),
        )
        mwx.fitChoice(self.separator_choice)
        self.separator_choice.Select(
            self.indexOf(
                [key for key, _title, _value in SEPARATORS],
                config.comparePeaklists["alignmentSeparator"],
            )
        )

        grid = wx.GridBagSizer(mwx.GRIDBAG_VSPACE, mwx.GRIDBAG_HSPACE)
        grid.Add(
            layout_label,
            (0, 0),
            flag=wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT,
        )
        grid.Add(self.layout_choice, (0, 1))
        grid.Add(
            duplicates_label,
            (1, 0),
            flag=wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT,
        )
        grid.Add(self.duplicates_choice, (1, 1))
        grid.Add(
            separator_label,
            (2, 0),
            flag=wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT,
        )
        grid.Add(self.separator_choice, (2, 1))
        grid.Add(self.header_check, (2, 2), flag=wx.ALIGN_CENTER_VERTICAL)

        return grid

    # ----

    def makePreview(self):
        """The top of the table as it would be written."""

        sizer = mwx.staticBoxSizer(self, "Preview", wx.VERTICAL)

        self.preview_list = wx.ListCtrl(
            self,
            -1,
            size=wx.Size(560, 170),
            style=wx.LC_REPORT | wx.LC_HRULES | wx.LC_VRULES | wx.BORDER_THEME,
        )
        sizer.Add(self.preview_list, 1, wx.EXPAND | wx.ALL, mwx.PANEL_SPACE_MAIN // 2)

        # whatever changes the table changes the preview
        for check in list(self.statChecks.values()) + list(self.peakChecks.values()):
            check.Bind(wx.EVT_CHECKBOX, self.onPreview)
        self.layout_choice.Bind(wx.EVT_CHOICE, self.onPreview)
        self.duplicates_choice.Bind(wx.EVT_CHOICE, self.onPreview)
        self.header_check.Bind(wx.EVT_CHECKBOX, self.onPreview)

        self.updatePreview()

        return sizer

    # ----

    def onPreview(self, evt):
        """Redraw the preview after a change of columns or options."""

        self.updatePreview()

    # ----

    def updatePreview(self):
        """Fill the preview with the first rows of the table."""

        stats, columns, duplicates, layout, twoRow = self.readParams()

        # the long layout has no blocks to name
        self.header_check.Enable(layout != alignment.LAYOUT_LONG)

        header, rows = alignment.buildAlignmentTable(
            self.previewGroups,
            self.titles,
            statColumns=stats,
            peakColumns=columns,
            duplicates=duplicates,
            layout=layout,
            twoRowHeader=twoRow,
        )

        # a list can only head its columns with one row, so a second header
        # row goes in as the first line
        headings = alignment.headerRows(header)
        header = headings[0]
        rows = headings[1:] + rows

        control = self.preview_list

        control.Freeze()
        control.ClearAll()

        for index, title in enumerate(header):
            control.InsertColumn(index, title)

        for number, row in enumerate(rows[:PREVIEW_ROWS]):
            cells = [alignment.formatValue(value) for value in row]
            if not cells:
                break
            control.InsertItem(number, cells[0])
            for index, cell in enumerate(cells[1:], 1):
                control.SetItem(number, index, cell)

        for index in range(len(header)):
            control.SetColumnWidth(index, wx.LIST_AUTOSIZE_USEHEADER)
            # a header wider than its numbers is what sets the width; cap it
            # so one long document title cannot push the rest off the screen
            if control.GetColumnWidth(index) < 60:
                control.SetColumnWidth(index, 60)

        control.Thaw()

    # ----

    def makeButtons(self):
        """Make buttons."""

        cancel_butt = wx.Button(self, wx.ID_CANCEL, "Cancel")

        clipboard_butt = wx.Button(self, -1, "Copy to Clipboard")
        clipboard_butt.Bind(wx.EVT_BUTTON, self.onClipboard)

        save_butt = wx.Button(self, wx.ID_OK, "Save to File...")
        save_butt.Bind(wx.EVT_BUTTON, self.onSave)
        save_butt.SetDefault()

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(cancel_butt, 0, wx.RIGHT, 15)
        sizer.Add(clipboard_butt, 0, wx.RIGHT, 15)
        sizer.Add(save_butt, 0)

        return sizer

    # ----

    @staticmethod
    def indexOf(keys, value):
        """Position of a stored value, falling back to the first choice."""

        try:
            return keys.index(value)
        except ValueError:
            return 0

    # ----

    def onClipboard(self, evt):
        """Accept, writing the table to the clipboard."""

        self.accept("clipboard")

    # ----

    def onSave(self, evt):
        """Accept, writing the table to a file."""

        self.accept("file")

    # ----

    def accept(self, destination):
        """Store the choices and close, unless nothing would be written."""

        if not self.getParams():
            wx.Bell()
            return

        self.destination = destination
        self.EndModal(wx.ID_OK)

    # ----

    def readParams(self):
        """Columns and options as they stand in the dialog right now."""

        stats = [
            key for key, check in self.statChecks.items() if check.GetValue()
        ]
        columns = [
            key for key, check in self.peakChecks.items() if check.GetValue()
        ]

        duplicates = DUPLICATES[self.duplicates_choice.GetSelection()][0]
        layout = LAYOUTS[self.layout_choice.GetSelection()][0]

        return stats, columns, duplicates, layout, self.header_check.GetValue()

    # ----

    def getParams(self):
        """Get all params from dialog."""

        stats, columns, duplicates, layout, twoRow = self.readParams()

        # a table of nothing but empty lines is never what was meant
        if not stats and not columns:
            return False

        config.comparePeaklists["alignmentStats"] = stats
        config.comparePeaklists["alignmentColumns"] = columns
        config.comparePeaklists["alignmentLayout"] = layout
        config.comparePeaklists["alignmentDuplicates"] = duplicates
        config.comparePeaklists["alignmentTwoRowHeader"] = int(twoRow)

        config.comparePeaklists["alignmentSeparator"] = SEPARATORS[
            self.separator_choice.GetSelection()
        ][0]

        return True

    # ----


def separatorValue(key):
    """The character stored under a separator config value."""

    for stored, _title, value in SEPARATORS:
        if stored == key:
            return value

    return "\t"
