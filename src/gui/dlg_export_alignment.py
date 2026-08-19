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
    (alignment.DUPLICATES_IGNORE, "Leave out"),
]


class dlgExportAlignment(wx.Dialog):
    """Pick the columns of the aligned peak table, and where to put it."""

    def __init__(self, parent, documents=0, groups=0):

        wx.Dialog.__init__(
            self,
            parent,
            -1,
            "Export Alignment",
            style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP,
        )

        self.documents = documents
        self.groups = groups

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
            % (self.groups, self.documents),
        )

        stats = self.makeColumnBox(
            "Summary columns",
            alignment.STAT_COLUMNS,
            config.comparePeaklists["alignmentStats"],
            self.statChecks,
            rows=4,
        )

        columns = self.makeColumnBox(
            "Columns for each document",
            alignment.PEAK_COLUMNS,
            config.comparePeaklists["alignmentColumns"],
            self.peakChecks,
            rows=5,
        )

        options = self.makeOptions()
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
        sizer.Add(buttons, 0, wx.CENTER | wx.ALL, mwx.PANEL_SPACE_MAIN)

        return sizer

    # ----

    def makeColumnBox(self, label, definitions, selected, store, rows):
        """A boxed block of checkboxes, one per available column."""

        box = wx.StaticBox(self, -1, label)
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

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

        duplicates_label = wx.StaticText(self, -1, "Duplicate peaks:")
        self.duplicates_choice = wx.Choice(
            self,
            -1,
            choices=[title for _key, title in DUPLICATES],
            size=wx.Size(200, mwx.CHOICE_HEIGHT),
        )
        # fitChoice sizes to the text alone, which on GTK comes out just short
        # of what the native control needs for its arrow
        mwx.fitChoice(
            self.duplicates_choice,
            min_width=self.duplicates_choice.GetBestSize().GetWidth(),
        )
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
        mwx.fitChoice(
            self.separator_choice,
            min_width=self.separator_choice.GetBestSize().GetWidth(),
        )
        self.separator_choice.Select(
            self.indexOf(
                [key for key, _title, _value in SEPARATORS],
                config.comparePeaklists["alignmentSeparator"],
            )
        )

        grid = wx.GridBagSizer(mwx.GRIDBAG_VSPACE, mwx.GRIDBAG_HSPACE)
        grid.Add(
            duplicates_label,
            (0, 0),
            flag=wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT,
        )
        grid.Add(self.duplicates_choice, (0, 1))
        grid.Add(
            separator_label,
            (1, 0),
            flag=wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT,
        )
        grid.Add(self.separator_choice, (1, 1))

        return grid

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

    def getParams(self):
        """Get all params from dialog."""

        stats = [
            key for key, check in self.statChecks.items() if check.GetValue()
        ]
        columns = [
            key for key, check in self.peakChecks.items() if check.GetValue()
        ]

        # a table of nothing but empty lines is never what was meant
        if not stats and not columns:
            return False

        config.comparePeaklists["alignmentStats"] = stats
        config.comparePeaklists["alignmentColumns"] = columns

        config.comparePeaklists["alignmentDuplicates"] = DUPLICATES[
            self.duplicates_choice.GetSelection()
        ][0]

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
