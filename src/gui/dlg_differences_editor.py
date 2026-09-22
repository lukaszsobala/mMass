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
import json

# load modules
from .ids import *
from . import mwx
from . import libs
from . import differences
from .dlg_references_editor import dlgGroupName, dlgSelectItemsToImport
import mspy

# MASS DIFFERENCES EDITOR
# -----------------------


class dlgDifferencesEditor(wx.Dialog):
    """Edit mass differences library."""

    def __init__(self, parent):
        wx.Dialog.__init__(
            self,
            parent,
            -1,
            "Mass Differences Library",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        self.group = None
        self.builtin = None
        self.itemsMap = []

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

        # show data, opening on the first of the user's own lists
        self.updateGroups()
        self.groupName_choice.Select(len(differences.BUILTIN) if libs.differences else 0)
        self.onGroupSelected()

    # ----

    def makeGUI(self):
        """Make GUI elements."""

        # make GUI elements
        groups = self.makeGroupEditor()
        self.makeItemsList()
        editor = self.makeItemEditor()

        # pack elements
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(groups, 0, wx.EXPAND | wx.ALL, mwx.PANEL_SPACE_MAIN)
        sizer.Add(self.itemsList, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, mwx.LISTCTRL_SPACE)
        sizer.Add(editor, 0, wx.EXPAND | wx.CENTER | wx.ALL, mwx.PANEL_SPACE_MAIN)

        return sizer

    # ----

    def makeGroupEditor(self):
        """Make group editor."""

        # make elements
        self.groupName_choice = wx.Choice(
            self, -1, size=wx.Size(-1, mwx.CHOICE_HEIGHT)
        )
        self.groupName_choice.Bind(wx.EVT_CHOICE, self.onGroupSelected)

        groupImport_butt = wx.Button(self, -1, "Import")
        groupImport_butt.Bind(wx.EVT_BUTTON, self.onImport)

        groupNew_butt = wx.Button(self, -1, "New")
        groupNew_butt.Bind(wx.EVT_BUTTON, self.onAddGroup)

        self.groupRename_butt = groupRename_butt = wx.Button(self, -1, "Rename")
        groupRename_butt.Bind(wx.EVT_BUTTON, self.onRenameGroup)

        self.groupDelete_butt = groupDelete_butt = wx.Button(self, -1, "Delete")
        groupDelete_butt.Bind(wx.EVT_BUTTON, self.onDeleteGroup)

        # pack elements
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.groupName_choice, 1, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 30)
        sizer.Add(groupImport_butt, 0, wx.RIGHT, 15)
        sizer.Add(groupNew_butt, 0, wx.RIGHT, 15)
        sizer.Add(groupRename_butt, 0, wx.RIGHT, 15)
        sizer.Add(groupDelete_butt, 0)

        return sizer

    # ----

    def makeItemsList(self):
        """Make list for items."""

        # init list
        self.itemsList = mwx.sortListCtrl(
            self, -1, size=wx.Size(601, 250), style=mwx.LISTCTRL_STYLE_MULTI
        )
        self.itemsList.SetFont(wx.SMALL_FONT)
        self.itemsList.setAltColour(mwx.LISTCTRL_ALTCOLOUR)

        # set events
        self.itemsList.Bind(wx.EVT_LIST_ITEM_SELECTED, self.onItemSelected)

        # make columns
        # in the order of an entry's fields, which the list sorts by
        self.itemsList.InsertColumn(0, "name", wx.LIST_FORMAT_LEFT)
        self.itemsList.InsertColumn(1, "mo. mass", wx.LIST_FORMAT_RIGHT)
        self.itemsList.InsertColumn(2, "av. mass", wx.LIST_FORMAT_RIGHT)
        self.itemsList.InsertColumn(3, "short", wx.LIST_FORMAT_LEFT)

        # set column widths
        for col, width in enumerate((250, 120, 120, 90)):
            self.itemsList.SetColumnWidth(col, width)

    # ----

    def makeItemEditor(self):
        """Make items editor."""

        mainSizer = mwx.staticBoxSizer(self, "", wx.VERTICAL)

        # make elements
        itemName_label = wx.StaticText(self, -1, "Name:")
        self.itemName_value = wx.TextCtrl(self, -1, "", size=wx.Size(280, -1))

        itemShort_label = wx.StaticText(self, -1, "Short:")
        self.itemShort_value = wx.TextCtrl(self, -1, "", size=wx.Size(120, -1))
        self.itemShort_value.SetToolTip(
            wx.ToolTip(
                "Optional. What labels show instead of the name when short names "
                "are on (e.g. Ac for Acetylation)."
            )
        )

        itemFormula_label = wx.StaticText(self, -1, "Formula:")
        self.itemFormula_value = wx.TextCtrl(
            self, -1, "", size=wx.Size(280, -1), style=wx.TE_PROCESS_ENTER
        )
        self.itemFormula_value.SetToolTip(
            wx.ToolTip(
                "Optional. Type a formula (e.g. HPO3) and press Enter to fill in "
                "the masses; use gain and loss parts for a net change "
                "(e.g. O - NH for deamidation)."
            )
        )
        self.itemFormula_value.Bind(wx.EVT_TEXT_ENTER, self.onFormula)

        itemMoMass_label = wx.StaticText(self, -1, "Mo. mass:")
        self.itemMoMass_value = wx.TextCtrl(
            self, -1, "", size=wx.Size(120, -1), validator=mwx.validator("float")
        )

        itemAvMass_label = wx.StaticText(self, -1, "Av. mass:")
        self.itemAvMass_value = wx.TextCtrl(
            self, -1, "", size=wx.Size(120, -1), validator=mwx.validator("float")
        )
        self.itemAvMass_value.SetToolTip(
            wx.ToolTip("Leave empty to use the monoisotopic mass.")
        )

        # buttons
        add_butt = mwx.makeButton(self, -1, "Add", 80)
        add_butt.Bind(wx.EVT_BUTTON, self.onAddItem)

        replace_butt = mwx.makeButton(self, -1, "Replace", 80)
        replace_butt.Bind(wx.EVT_BUTTON, self.onReplaceItem)

        delete_butt = mwx.makeButton(self, -1, "Delete", 80)
        delete_butt.Bind(wx.EVT_BUTTON, self.onDeleteItem)

        # pack elements
        grid = wx.GridBagSizer(mwx.GRIDBAG_VSPACE, mwx.GRIDBAG_HSPACE)

        grid.Add(itemName_label, (0, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.itemName_value, (0, 1))
        grid.Add(itemShort_label, (0, 2), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.itemShort_value, (0, 3))
        grid.Add(
            itemFormula_label, (1, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
        )
        grid.Add(self.itemFormula_value, (1, 1), (1, 3), flag=wx.EXPAND)
        grid.Add(
            itemMoMass_label, (2, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
        )
        grid.Add(self.itemMoMass_value, (2, 1))
        grid.Add(
            itemAvMass_label, (2, 2), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
        )
        grid.Add(self.itemAvMass_value, (2, 3))

        grid.Add(add_butt, (0, 5), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(replace_butt, (1, 5), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
        grid.Add(delete_butt, (2, 5), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)

        self.builtin_label = wx.StaticText(self, -1, "")
        self.builtin_label.SetFont(wx.SMALL_FONT)
        self.editorControls = (
            self.itemName_value,
            self.itemShort_value,
            self.itemFormula_value,
            self.itemMoMass_value,
            self.itemAvMass_value,
            add_butt,
            replace_butt,
            delete_butt,
            self.groupRename_butt,
            self.groupDelete_butt,
        )

        mainSizer.Add(self.builtin_label, 0, wx.ALIGN_CENTER | wx.TOP, 5)
        mainSizer.Add(grid, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        return mainSizer

    # ----

    def onGroupSelected(self, evt=None):
        """Update items for selected group."""

        # get selected group; the built-in lists are shown but not edited
        index = self.groupName_choice.GetSelection()
        self.builtin = None
        self.group = None
        if 0 <= index < len(differences.BUILTIN):
            self.builtin = differences.BUILTIN[index]
        elif index != wx.NOT_FOUND:
            self.group = self.groupName_choice.GetString(index)

        # update gui
        self.updateItemsList()
        self.clearEditor()
        for control in self.editorControls:
            control.Enable(self.builtin is None)
        if self.builtin in (differences.AMINOACIDS, differences.DIPEPTIDES):
            self.builtin_label.SetLabel(
                "Built-in list, made from Libraries > Monomers; it is edited there."
            )
        elif self.builtin:
            self.builtin_label.SetLabel(
                "Built-in list of residue masses; it cannot be edited."
            )
        self.builtin_label.Show(self.builtin is not None)
        self.Layout()

    # ----

    def onItemSelected(self, evt):
        """Update item editor with selected item."""

        # get selected item
        item = self.itemsMap[evt.GetData()]
        name, mono, avg = item[:3]

        # update item editor
        self.itemName_value.SetValue(name)
        self.itemShort_value.SetValue(item[3] if len(item) > 3 else "")
        self.itemFormula_value.SetValue("")
        self.itemMoMass_value.SetValue(str(mono))
        self.itemAvMass_value.SetValue(str(avg))

    # ----

    def onFormula(self, evt=None):
        """Fill in the masses from the formula."""

        masses = formulaMasses(self.itemFormula_value.GetValue())
        if masses is None:
            wx.Bell()
            return

        self.itemMoMass_value.SetValue(str(round(masses[0], 6)))
        self.itemAvMass_value.SetValue(str(round(masses[1], 6)))

    # ----

    def onImport(self, evt):
        """Import groups from a mass differences library file."""

        # show open file dialog
        wildcard = "Library files|*.json;*.JSON"
        dlg = wx.FileDialog(
            self,
            "Import Library",
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            dlg.Destroy()
        else:
            dlg.Destroy()
            return

        # read data
        importedItems = self.readLibrary(path)
        if importedItems is False:
            wx.Bell()
            dlg = mwx.dlgMessage(
                self,
                title="Unrecognized library format.",
                message="Specified file is not a valid mass differences library.",
            )
            dlg.ShowModal()
            dlg.Destroy()
            return
        elif importedItems == {}:
            wx.Bell()
            dlg = mwx.dlgMessage(
                self,
                title="No data to import.",
                message="Specified library contains no data.",
            )
            dlg.ShowModal()
            dlg.Destroy()
            return

        # select groups to import
        dlg = dlgSelectItemsToImport(self, importedItems, countLabel="differences")
        if dlg.ShowModal() == wx.ID_OK:
            selected = dlg.selected or []
            dlg.Destroy()
        else:
            dlg.Destroy()
            return

        # check same items
        selectAfter = None
        replaceAll = False
        for item in selected:
            if item in differences.BUILTIN:
                continue
            if replaceAll or item not in libs.differences:
                libs.differences[item] = importedItems[item]
                selectAfter = item
            else:
                title = (
                    'Group entitled "%s"\nis already in you library. Do you want to replace it?'
                    % item
                )
                message = "All differences within this group will be lost."
                buttons = [
                    (ID_dlgReplaceAll, "Replace All", 120, False, 40),
                    (ID_dlgSkip, "Skip", 80, False, 15),
                    (ID_dlgReplace, "Replace", 80, True, 0),
                ]
                dlg = mwx.dlgMessage(self, title, message, buttons)
                ID = dlg.ShowModal()
                dlg.Destroy()
                if ID == ID_dlgSkip:
                    continue
                elif ID == ID_dlgReplaceAll:
                    replaceAll = True
                    libs.differences[item] = importedItems[item]
                    selectAfter = item
                elif ID == ID_dlgReplace:
                    libs.differences[item] = importedItems[item]
                    selectAfter = item

        # update gui
        self.updateGroups()
        if selectAfter:
            self.groupName_choice.SetStringSelection(selectAfter)
        self.onGroupSelected()

    # ----

    def onAddGroup(self, evt):
        """Add new group."""

        # get group name
        name = self.askGroupName()
        if not name:
            return

        # add group
        libs.differences[name] = []

        # update gui
        self.updateGroups()
        self.groupName_choice.SetStringSelection(name)
        self.onGroupSelected()

    # ----

    def onRenameGroup(self, evt):
        """Rename selected group."""

        # check group
        if not self.group:
            wx.Bell()
            return

        # get group name
        name = self.askGroupName(self.group)
        if not name or name == self.group:
            return

        # rename group
        libs.differences[name] = libs.differences.pop(self.group)

        # update gui
        self.updateGroups()
        self.groupName_choice.SetStringSelection(name)
        self.onGroupSelected()

    # ----

    def onDeleteGroup(self, evt):
        """Delete selected group."""

        # check group
        if not self.group:
            wx.Bell()
            return

        # delete selected group
        title = "Do you really want to delete selected group?"
        message = "All differences within the group will be lost."
        buttons = [
            (wx.ID_CANCEL, "Cancel", 80, False, 15),
            (wx.ID_OK, "Delete", 80, True, 0),
        ]
        dlg = mwx.dlgMessage(self, title, message, buttons)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        dlg.Destroy()

        # remove group
        del libs.differences[self.group]

        # update gui
        self.updateGroups()
        self.groupName_choice.Select(len(differences.BUILTIN) if libs.differences else 0)
        self.onGroupSelected()

    # ----

    def onAddItem(self, evt):
        """Add item."""

        # check group
        if not self.group:
            wx.Bell()
            return

        # get item data
        itemData = self.getItemData()
        if not itemData:
            return

        # add item
        libs.differences[self.group].append(itemData)

        # update gui
        self.updateItemsList()
        self.clearEditor()

    # ----

    def onReplaceItem(self, evt):
        """Replace the selected item with the editor's values."""

        # check group and selection
        selected = self.itemsList.getSelected()
        if not self.group or len(selected) != 1:
            wx.Bell()
            return

        # get item data
        itemData = self.getItemData()
        if not itemData:
            return

        # replace item
        index = self.itemsList.GetItemData(selected[0])
        libs.differences[self.group][index] = itemData

        # update gui
        self.updateItemsList()
        self.clearEditor()

    # ----

    def onDeleteItem(self, evt):
        """Remove selected items."""

        # check group and selection
        selected = self.itemsList.getSelected()
        if not self.group or not selected:
            wx.Bell()
            return

        # delete?
        title = "Do you really want to delete selected differences?"
        message = "Difference definitions will be lost."
        buttons = [
            (wx.ID_CANCEL, "Cancel", 80, False, 15),
            (wx.ID_OK, "Delete", 80, True, 0),
        ]
        dlg = mwx.dlgMessage(self, title, message, buttons)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        dlg.Destroy()

        # delete items
        indexes = [self.itemsList.GetItemData(i) for i in selected]
        for i in sorted(indexes, reverse=True):
            del libs.differences[self.group][i]

        # update gui
        self.updateItemsList()
        self.clearEditor()

    # ----

    def askGroupName(self, name=""):
        """Ask for a group name that is not taken yet."""

        dlg = dlgGroupName(self, name)
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return None
        newName = dlg.name.strip()
        dlg.Destroy()

        # check group name (the built-in lists share the namespace)
        if newName != name and (
            newName in libs.differences or newName in differences.BUILTIN
        ):
            wx.Bell()
            dlg = mwx.dlgMessage(
                self,
                title="Group with the same name already exists.",
                message="Type a different name.",
            )
            dlg.ShowModal()
            dlg.Destroy()
            return None

        return newName

    # ----

    def updateGroups(self):
        """Update groups combo."""

        self.groupName_choice.Clear()
        for name in differences.BUILTIN:
            self.groupName_choice.Append("%s (built-in)" % name)
        for choice in sorted(libs.differences.keys()):
            self.groupName_choice.Append(choice)

    # ----

    def updateItemsList(self):
        """Update items list."""

        # clear previous data and set new
        if self.builtin:
            self.itemsMap = [
                (name, mono, avg, "")
                for name, (mono, avg) in differences.getList(self.builtin).items()
            ]
        else:
            self.itemsMap = libs.differences[self.group] if self.group else []
        self.itemsList.DeleteAllItems()
        self.itemsList.setDataMap(self.itemsMap)

        # add new data
        for row, item in enumerate(self.itemsMap):
            self.itemsList.InsertItem(row, item[0])
            self.itemsList.SetItem(row, 1, "%.6f" % item[1])
            self.itemsList.SetItem(row, 2, "%.6f" % item[2])
            self.itemsList.SetItem(row, 3, item[3] if len(item) > 3 else "")
            self.itemsList.SetItemData(row, row)

        # sort
        if self.itemsMap:
            self.itemsList.sort()

    # ----

    def clearEditor(self):
        """Clear item editor."""

        self.itemName_value.SetValue("")
        self.itemShort_value.SetValue("")
        self.itemFormula_value.SetValue("")
        self.itemMoMass_value.SetValue("")
        self.itemAvMass_value.SetValue("")

    # ----

    def getItemData(self):
        """Get formated item data."""

        # get data
        name = self.itemName_value.GetValue().strip()
        mono = self.itemMoMass_value.GetValue().strip()
        avg = self.itemAvMass_value.GetValue().strip()

        # fill masses from formula if not given
        if not mono and self.itemFormula_value.GetValue().strip():
            self.onFormula()
            mono = self.itemMoMass_value.GetValue().strip()
            avg = self.itemAvMass_value.GetValue().strip()

        # check values
        if not name or not mono:
            wx.Bell()
            return False

        try:
            mono = float(mono)
            avg = float(avg) if avg else mono
        except ValueError:
            wx.Bell()
            return False

        return (name, mono, avg, self.itemShort_value.GetValue().strip())

    # ----

    def readLibrary(self, path):
        """Read a JSON mass differences library."""

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            groups = data["differences"]
        except Exception:
            return False

        if not isinstance(groups, dict):
            return False

        container = libs.parseDifferences(groups)
        version = data.get("schemaVersion", 1) if isinstance(data, dict) else 1
        if not isinstance(version, int) or version < libs.DIFFERENCES_SCHEMA:
            libs.migrateDifferences(container)
        return container

    # ----


def formulaMasses(text):
    """(mono, avg) of a formula, or of "gain - loss"; None if it is invalid."""

    parts = [part.strip() for part in text.split(" - ")]
    if not parts[0] or len(parts) > 2:
        return None

    try:
        gain = mspy.compound(parts[0])
        gainMo, gainAv = gain.mass(0), gain.mass(1)
        lossMo = lossAv = 0.0
        if len(parts) > 1:
            loss = mspy.compound(parts[1])
            lossMo, lossAv = loss.mass(0), loss.mass(1)
    except Exception:
        return None

    return (gainMo - lossMo, gainAv - lossAv)
