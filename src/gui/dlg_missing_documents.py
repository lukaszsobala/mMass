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

# MISSING DOCUMENTS DIALOG
# ------------------------


class dlgMissingDocuments(wx.Dialog):
    """Report session documents that could not be found.

    A session only references its documents by path, so files can be moved,
    renamed or sit on an unmounted volume by the time it is reopened. Restoring
    keeps whatever is still available and this dialog reports the rest, so the
    user can see exactly which spectra are absent instead of losing the whole
    session to an error.
    """

    def __init__(self, parent, documents, restored=0):
        wx.Dialog.__init__(
            self,
            parent,
            -1,
            "Missing Documents",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        self.documents = documents
        self.restored = restored

        # make GUI
        sizer = self.makeGUI()

        # show data
        self.updateDocumentList()

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

        # make title
        count = len(self.documents)
        title = "%d document%s from this session could not be found." % (
            count,
            ("", "s")[count != 1],
        )
        title_label = wx.StaticText(self, -1, title)
        title_label.SetFont(
            wx.Font(
                mwx.NORMAL_FONT_SIZE,
                wx.FONTFAMILY_SWISS,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_BOLD,
            )
        )

        # make message
        if self.restored:
            message = (
                "The remaining %d document%s %s been opened. Missing documents\n"
                "were probably moved, renamed or deleted."
                % (
                    self.restored,
                    ("", "s")[self.restored != 1],
                    ("has", "have")[self.restored != 1],
                )
            )
        else:
            message = (
                "None of the documents in this session could be opened. They were\n"
                "probably moved, renamed or deleted."
            )
        message_label = wx.StaticText(self, -1, message)
        message_label.SetFont(wx.SMALL_FONT)

        # make document list and buttons
        self.makeDocumentList()
        buttons = self.makeButtons()

        # pack elements
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(title_label, 0, wx.ALIGN_LEFT | wx.TOP | wx.LEFT | wx.RIGHT,
                  mwx.PANEL_SPACE_MAIN)
        sizer.Add(
            message_label,
            0,
            wx.ALIGN_LEFT | wx.TOP | wx.LEFT | wx.RIGHT,
            mwx.PANEL_SPACE_MAIN,
        )
        sizer.Add(
            self.documentList,
            1,
            wx.EXPAND | wx.TOP | wx.LEFT | wx.RIGHT,
            mwx.PANEL_SPACE_MAIN,
        )
        sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, mwx.PANEL_SPACE_MAIN)

        return sizer

    # ----

    def makeButtons(self):
        """Make buttons."""

        copy_butt = wx.Button(self, -1, "Copy List")
        copy_butt.Bind(wx.EVT_BUTTON, self.onCopy)

        ok_butt = wx.Button(self, wx.ID_OK, "OK")
        ok_butt.SetDefault()

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(copy_butt, 0, wx.RIGHT, 15)
        sizer.Add(ok_butt, 0)

        return sizer

    # ----

    def makeDocumentList(self):
        """Make list for missing documents."""

        # init list
        self.documentList = mwx.sortListCtrl(
            self,
            -1,
            size=wx.Size(550, 200),
            style=mwx.LISTCTRL_STYLE_MULTI,
        )
        self.documentList.SetFont(wx.SMALL_FONT)
        self.documentList.setAltColour(mwx.LISTCTRL_ALTCOLOUR)

        # make columns
        self.documentList.InsertColumn(0, "document", wx.LIST_FORMAT_LEFT)
        self.documentList.InsertColumn(1, "expected location", wx.LIST_FORMAT_LEFT)

        # set column widths
        for col, width in enumerate((150, 395)):
            self.documentList.SetColumnWidth(col, width)

    # ----

    def updateDocumentList(self):
        """Set data to document list."""

        # set data map so sorting and clipboard export see the same values
        dataMap = [
            (entry.get("title", ""), entry.get("path", "")) for entry in self.documents
        ]
        self.documentList.setDataMap(dataMap)

        # add data
        for row, item in enumerate(dataMap):
            self.documentList.InsertItem(row, item[0])
            self.documentList.SetItem(row, 1, item[1])
            self.documentList.SetItemData(row, row)

    # ----

    def onCopy(self, evt):
        """Copy the whole list to clipboard."""
        self.documentList.copyToClipboard()

    # ----
