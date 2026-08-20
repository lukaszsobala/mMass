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
from typing import Any

# load modules
from .ids import *
from . import mwx
from . import images
from . import config
from . import display_scale
import mspy
from . import doc

from .dlg_notation import dlgNotation

# DOCUMENTS PANEL
# --------------


class panelDocuments(wx.Panel):
    """Make documents panel."""

    def __init__(self, parent, documents):
        panelWidth = display_scale.scale_metric(150, display_scale.get_ui_scale())
        wx.Panel.__init__(
            self, parent, -1, size=wx.Size(panelWidth, -1), style=wx.NO_FULL_REPAINT_ON_RESIZE
        )

        self.parent = parent
        self.documents = documents
        self.documentTree: Any = None

        # document being dragged to a new position (index in self.documents)
        # and the gap it would be dropped into (0 is above the first document)
        self._draggedDocument = None
        self._dropPosition = None
        # selection events are suppressed while the tree is rebuilt internally
        self._skipSelectionEvents = False

        # make GUI
        self.makeGUI()

    # ----

    def makeGUI(self):
        """Make GUI elements."""

        # make documents tree
        self.makeDocumentTree()

        # init lower toolbar
        toolbar = self.makeToolbar()

        # pack gui elements
        self.mainSizer = wx.BoxSizer(wx.VERTICAL)
        self.mainSizer.Add(self.documentTree, 1, wx.EXPAND, 0)
        self.mainSizer.Add(toolbar, 0, wx.EXPAND)

        # fit layout
        self.mainSizer.Fit(self)
        self.SetSizer(self.mainSizer)

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

        self.add_butt = mwx.makeBitmapButton(
            panel,
            -1,
            images.lib["documentsAdd"],
            size=wx.Size(*mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.add_butt.SetToolTip(wx.ToolTip("Add..."))
        self.add_butt.Bind(wx.EVT_BUTTON, self.onAdd)

        self.delete_butt = mwx.makeBitmapButton(
            panel,
            -1,
            images.lib["documentsDelete"],
            size=wx.Size(*mwx.BOTTOMBAR_TOOLSIZE),
            style=wx.BORDER_NONE,
        )
        self.delete_butt.SetToolTip(wx.ToolTip("Remove..."))
        self.delete_butt.Bind(wx.EVT_BUTTON, self.onDelete)

        # pack elements
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.AddSpacer(mwx.BOTTOMBAR_LSPACE)
        sizer.Add(self.add_butt, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(
            self.delete_butt,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.LEFT,
            mwx.BUTTON_SIZE_CORRECTION,
        )
        sizer.AddSpacer(mwx.BOTTOMBAR_RSPACE)

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        mainSizer.Add(sizer, 1, wx.EXPAND)

        panel.SetSizer(mainSizer)
        mainSizer.Fit(panel)

        return panel

    # ----

    def makeDocumentTree(self):
        """Make documents tree."""

        # init tree
        self.documentTree = documentsTree(self, -1, size=wx.Size(175, -1))

        # bind events
        self.documentTree.Bind(wx.EVT_TREE_KEY_DOWN, self.onKey)
        self.documentTree.Bind(wx.EVT_LEFT_DOWN, self.onLMD)
        self.documentTree.Bind(wx.EVT_RIGHT_DOWN, self.onRMD)
        self.documentTree.Bind(wx.EVT_RIGHT_UP, self.onRMU)
        self.documentTree.Bind(wx.EVT_TREE_SEL_CHANGING, self.onItemSelecting)
        self.documentTree.Bind(wx.EVT_TREE_SEL_CHANGED, self.onItemSelected)
        self.documentTree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.onItemActivated)
        self.documentTree.Bind(wx.EVT_TREE_BEGIN_DRAG, self.onItemBeginDrag)
        self.documentTree.Bind(wx.EVT_MOTION, self.onTreeMotion)
        self.documentTree.Bind(wx.EVT_LEFT_UP, self.onTreeLMU)
        self.documentTree.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self.onTreeCaptureLost)

        # set DnD
        dropTarget = fileDropTarget(self.parent.onDocumentDropped)
        self.documentTree.SetDropTarget(dropTarget)

    # ----

    def onKey(self, evt):
        """Delete selected item."""

        # get key
        key = evt.GetKeyCode()
        keyEvt = evt.GetKeyEvent()

        # abandon dragging
        if key == wx.WXK_ESCAPE and self._draggedDocument is not None:
            self._endDrag()

        # move document within the list (the main frame has the same shortcuts
        # as accelerators, this only catches them while the tree has focus)
        elif key in (wx.WXK_PAGEUP, wx.WXK_PAGEDOWN) and keyEvt.CmdDown():
            self._moveSelectedDocument(-1 if key == wx.WXK_PAGEUP else 1)

        # delete
        elif key == wx.WXK_DELETE or (key == wx.WXK_BACK and keyEvt.CmdDown()):
            item = self.documentTree.GetSelection()
            itemType = self.documentTree.getItemType(item)

            # close document
            if itemType == "document":
                self.parent.onDocumentClose()

            # delete sequence
            elif itemType == "sequence":
                self.parent.onSequenceDelete()

            # delete annotation or sequence match
            elif itemType in ("annotation", "match"):
                self.onNotationDelete()

            else:
                wx.Bell()

        # other keys
        else:
            evt.Skip()

    # ----

    def onLMD(self, evt):
        """Enable / disable document."""

        # get item
        item, flags = self.documentTree.HitTest(evt.GetPosition())

        # document solo
        if (evt.AltDown() or evt.ControlDown()) and self.documentTree.getItemIndent(
            item
        ) == 1:
            docIndex = self._getDocumentIndex(item)
            self.parent.onDocumentSolo(docIndex)

        # enable / disable document
        elif (flags & wx.TREE_HITTEST_ONITEMICON) and self.documentTree.getItemIndent(
            item
        ) == 1:
            docIndex = self._getDocumentIndex(item)
            self.parent.onDocumentEnable(docIndex)

        # other
        else:
            evt.Skip()

    # ----

    def onRMD(self, evt):
        """Right mouse down."""

        if wx.Platform == "__WXMAC__":
            evt.Skip()

    # ----

    def onRMU(self, evt):
        """Show popup menu."""

        # get selected item
        item = self.documentTree.GetSelection()
        itemType = self.documentTree.getItemType(item)

        # check item
        if not itemType:
            return

        # get item data
        itemData = self.documentTree.GetItemData(item)

        # popup menu
        menu = wx.Menu()
        if itemType == "document":
            menu.Append(ID_sequenceNew, "Add Sequence...")
            menu.AppendSeparator()
            menu.Append(ID_documentInfo, "Notes and Information...")
            menu.Append(ID_documentNotationsDelete, "Delete All Notations")
            menu.AppendSeparator()
            menu.Append(ID_documentColour, "Change Colour...")
            style = wx.Menu()
            style.Append(ID_documentStyleSolid, "Solid", "", wx.ITEM_RADIO)
            style.Append(ID_documentStyleDot, "Dotted", "", wx.ITEM_RADIO)
            style.Append(ID_documentStyleDash, "Dashed", "", wx.ITEM_RADIO)
            style.Append(ID_documentStyleDotDash, "Dot and Dash", "", wx.ITEM_RADIO)
            menu.Append(ID_documentStyle, "Line Style", style)
            menu.AppendSeparator()
            menu.Append(ID_documentFlip, "Flip Spectrum")
            menu.Append(ID_documentOffset, "Offset Spectrum...")
            menu.Append(ID_documentClearOffset, "Clear Offset")
            menu.AppendSeparator()
            menu.Append(ID_documentMoveUp, "Move Up" + HK_documentMoveUp)
            menu.Append(ID_documentMoveDown, "Move Down" + HK_documentMoveDown)
            menu.AppendSeparator()
            menu.Append(ID_documentDuplicate, "Duplicate Document")
            menu.AppendSeparator()
            menu.Append(ID_documentClose, "Close Document")
            menu.Append(ID_documentCloseAll, "Close All Documents")

            if config.spectrum["normalize"]:
                menu.Enable(ID_documentOffset, False)
            if itemData.offset == [0, 0]:
                menu.Enable(ID_documentClearOffset, False)

            docIndex = self._getDocumentIndex(item)
            menu.Enable(ID_documentMoveUp, bool(docIndex))
            menu.Enable(
                ID_documentMoveDown,
                docIndex is not None and docIndex < len(self.documents) - 1,
            )

            if not itemData.spectrum.hasprofile():
                menu.Enable(ID_documentStyle, False)
            elif itemData.style == wx.PENSTYLE_DOT:
                style.Check(ID_documentStyleDot, True)
            elif itemData.style == wx.PENSTYLE_SHORT_DASH:
                style.Check(ID_documentStyleDash, True)
            elif itemData.style == wx.PENSTYLE_DOT_DASH:
                style.Check(ID_documentStyleDotDash, True)
            else:
                style.Check(ID_documentStyleSolid, True)

        elif itemType == "annotations":
            menu.Append(
                ID_documentAnnotationsCalibrateBy, "Calibrate by Annotations..."
            )
            menu.AppendSeparator()
            menu.Append(ID_documentAnnotationsDelete, "Delete All Annotations")

            if not itemData:
                menu.Enable(ID_documentAnnotationsDelete, False)
                menu.Enable(ID_documentAnnotationsCalibrateBy, False)

        elif itemType == "annotation":
            menu.Append(ID_documentAnnotationEdit, "Edit Annotation...")
            menu.AppendSeparator()
            menu.Append(
                ID_documentAnnotationSendToMassCalculator, "Show Isotopic Pattern..."
            )
            menu.Append(
                ID_documentAnnotationSendToMassToFormula, "Send to Mass to Formula..."
            )
            menu.Append(
                ID_documentAnnotationSendToEnvelopeFit, "Send to Envelope Fit..."
            )
            menu.AppendSeparator()
            menu.Append(
                ID_documentAnnotationsCalibrateBy, "Calibrate by Annotations..."
            )
            menu.AppendSeparator()
            menu.Append(ID_documentAnnotationDelete, "Delete Annotation")
            menu.Append(ID_documentAnnotationsDelete, "Delete All Annotations")

            if not itemData.formula:
                menu.Enable(ID_documentAnnotationSendToMassCalculator, False)
                menu.Enable(ID_documentAnnotationSendToEnvelopeFit, False)

        elif itemType == "sequence":
            menu.Append(ID_sequenceEditor, "Edit Sequence...")
            menu.Append(ID_sequenceModifications, "Edit Modifications...")
            menu.AppendSeparator()
            menu.Append(ID_sequenceDigest, "Digest Protein...")
            menu.Append(ID_sequenceFragment, "Fragment Peptide...")
            menu.Append(ID_sequenceSearch, "Mass Search...")
            menu.AppendSeparator()
            menu.Append(ID_sequenceSendToMassCalculator, "Show Isotopic Pattern...")
            menu.Append(ID_sequenceSendToEnvelopeFit, "Send to Envelope Fit...")
            menu.AppendSeparator()
            menu.Append(ID_sequenceMatchesCalibrateBy, "Calibrate by Matches...")
            menu.AppendSeparator()
            menu.Append(ID_sequenceMatchesDelete, "Delete All Matches")
            menu.Append(ID_sequenceDelete, "Delete Sequence")

            if not itemData.matches:
                menu.Enable(ID_sequenceMatchesCalibrateBy, False)
                menu.Enable(ID_sequenceMatchesDelete, False)

        elif itemType == "match":
            menu.Append(ID_sequenceMatchEdit, "Edit Match...")
            menu.AppendSeparator()
            menu.Append(
                ID_sequenceMatchSendToMassCalculator, "Show Isotopic Pattern..."
            )
            menu.Append(ID_sequenceMatchSendToEnvelopeFit, "Send to Envelope Fit...")
            menu.AppendSeparator()
            menu.Append(ID_sequenceMatchesCalibrateBy, "Calibrate by Matches...")
            menu.AppendSeparator()
            menu.Append(ID_sequenceMatchDelete, "Delete Sequence Match")
            menu.Append(ID_sequenceMatchesDelete, "Delete All Matches")

            if not itemData.formula:
                menu.Enable(ID_sequenceMatchSendToMassCalculator, False)
                menu.Enable(ID_sequenceMatchSendToEnvelopeFit, False)

        # bind events
        self.Bind(wx.EVT_MENU, self.parent.onDocumentInfo, id=ID_documentInfo)
        self.Bind(wx.EVT_MENU, self.parent.onDocumentColour, id=ID_documentColour)
        self.Bind(wx.EVT_MENU, self.parent.onDocumentStyle, id=ID_documentStyleSolid)
        self.Bind(wx.EVT_MENU, self.parent.onDocumentStyle, id=ID_documentStyleDot)
        self.Bind(wx.EVT_MENU, self.parent.onDocumentStyle, id=ID_documentStyleDash)
        self.Bind(wx.EVT_MENU, self.parent.onDocumentStyle, id=ID_documentStyleDotDash)
        self.Bind(wx.EVT_MENU, self.parent.onDocumentFlip, id=ID_documentFlip)
        self.Bind(wx.EVT_MENU, self.parent.onDocumentOffset, id=ID_documentOffset)
        self.Bind(wx.EVT_MENU, self.parent.onDocumentOffset, id=ID_documentClearOffset)
        self.Bind(
            wx.EVT_MENU,
            self.parent.onDocumentNotationsDelete,
            id=ID_documentNotationsDelete,
        )
        self.Bind(wx.EVT_MENU, self.parent.onDocumentDuplicate, id=ID_documentDuplicate)
        self.Bind(wx.EVT_MENU, self.onDocumentMoveUp, id=ID_documentMoveUp)
        self.Bind(wx.EVT_MENU, self.onDocumentMoveDown, id=ID_documentMoveDown)
        self.Bind(wx.EVT_MENU, self.parent.onDocumentClose, id=ID_documentClose)
        self.Bind(wx.EVT_MENU, self.parent.onDocumentCloseAll, id=ID_documentCloseAll)

        self.Bind(wx.EVT_MENU, self.onNotationEdit, id=ID_documentAnnotationEdit)
        self.Bind(
            wx.EVT_MENU,
            self.onSendToMassCalculator,
            id=ID_documentAnnotationSendToMassCalculator,
        )
        self.Bind(
            wx.EVT_MENU,
            self.onSendToMassToFormula,
            id=ID_documentAnnotationSendToMassToFormula,
        )
        self.Bind(
            wx.EVT_MENU,
            self.onSendToEnvelopeFit,
            id=ID_documentAnnotationSendToEnvelopeFit,
        )
        self.Bind(
            wx.EVT_MENU,
            self.parent.onDocumentAnnotationsCalibrateBy,
            id=ID_documentAnnotationsCalibrateBy,
        )
        self.Bind(wx.EVT_MENU, self.onNotationDelete, id=ID_documentAnnotationDelete)
        self.Bind(
            wx.EVT_MENU,
            self.parent.onDocumentAnnotationsDelete,
            id=ID_documentAnnotationsDelete,
        )

        self.Bind(wx.EVT_MENU, self.parent.onSequenceNew, id=ID_sequenceNew)
        self.Bind(wx.EVT_MENU, self.parent.onToolsSequence, id=ID_sequenceEditor)
        self.Bind(wx.EVT_MENU, self.parent.onToolsSequence, id=ID_sequenceModifications)
        self.Bind(wx.EVT_MENU, self.parent.onToolsSequence, id=ID_sequenceDigest)
        self.Bind(wx.EVT_MENU, self.parent.onToolsSequence, id=ID_sequenceFragment)
        self.Bind(wx.EVT_MENU, self.parent.onToolsSequence, id=ID_sequenceSearch)
        self.Bind(
            wx.EVT_MENU, self.onSendToMassCalculator, id=ID_sequenceSendToMassCalculator
        )
        self.Bind(
            wx.EVT_MENU, self.onSendToEnvelopeFit, id=ID_sequenceSendToEnvelopeFit
        )
        self.Bind(wx.EVT_MENU, self.parent.onSequenceDelete, id=ID_sequenceDelete)

        self.Bind(wx.EVT_MENU, self.onNotationEdit, id=ID_sequenceMatchEdit)
        self.Bind(
            wx.EVT_MENU,
            self.onSendToMassCalculator,
            id=ID_sequenceMatchSendToMassCalculator,
        )
        self.Bind(
            wx.EVT_MENU, self.onSendToEnvelopeFit, id=ID_sequenceMatchSendToEnvelopeFit
        )
        self.Bind(
            wx.EVT_MENU,
            self.parent.onSequenceMatchesCalibrateBy,
            id=ID_sequenceMatchesCalibrateBy,
        )
        self.Bind(wx.EVT_MENU, self.onNotationDelete, id=ID_sequenceMatchDelete)
        self.Bind(
            wx.EVT_MENU,
            self.parent.onSequenceMatchesDelete,
            id=ID_sequenceMatchesDelete,
        )

        self.PopupMenu(menu)
        menu.Destroy()

    # ----

    def onItemSelecting(self, evt):
        """Selecting item."""

        # ignore selection changes caused by rebuilding the tree
        if self._skipSelectionEvents:
            return

        # do not allow to select disabled documents
        item = evt.GetItem()
        if self.documentTree.getItemIndent(item):
            docIndex = self._getDocumentIndex(item)
            if not self.documents[docIndex].visible:
                wx.Bell()
                evt.Veto()

    # ----

    def onItemSelected(self, evt):
        """Selected item."""

        # ignore selection changes caused by rebuilding the tree
        if self._skipSelectionEvents:
            return

        # get item
        item = evt.GetItem()
        itemType = self.documentTree.getItemType(item)
        evt.Skip()

        # root or bad item selected
        if not itemType:
            self.documentTree.highlightDocument(None)
            self.parent.onDocumentSelected(None)
            self.parent.updateNotationMarks()
            return

        # select parent document
        docIndex = self._getDocumentIndex(item)
        self.documentTree.highlightDocument(item)
        self.parent.onDocumentSelected(docIndex)

        # select parent sequence
        seqIndex = self._getSequenceIndex(item)
        self.parent.onSequenceSelected(seqIndex)

        # update notation marks
        self.parent.updateNotationMarks()

        # highlight mass of selected match or annotation
        if itemType in ("annotation", "match"):
            matchData = self.documentTree.GetItemData(item)
            points = [matchData.mz]
            if matchData.theoretical is not None:
                points.append(matchData.theoretical)
            self.parent.updateMassPoints(points)

    # ----

    def onItemActivated(self, evt):
        """Activated item."""

        # get item
        item = evt.GetItem()
        itemType = self.documentTree.getItemType(item)

        # do not allow to activate disabled documents
        if itemType:
            docIndex = self._getDocumentIndex(item)
            if not self.documents[docIndex].visible:
                wx.Bell()
                return
        else:
            return

        # document info
        if itemType == "document":
            self.parent.onDocumentInfo()

        # sequence editing
        elif itemType == "sequence":
            self.parent.onToolsSequence()

        # edit annotation or sequence match
        elif itemType in ("annotation", "match"):
            self.onNotationEdit()

    # ----

    def onItemBeginDrag(self, evt):
        """Start dragging a document to a new position.

        The event is deliberately left vetoed: the tree's own dragging marks
        the item under the cursor with a border, which says nothing about
        where the document would land. The drag is run here instead, showing
        an insertion line between documents.
        """

        self._endDrag()

        # nothing to reorder
        if len(self.documents) < 2:
            return

        # only whole documents can be reordered, but grabbing any of their
        # items (annotation, sequence, ...) is taken as grabbing the document
        item = evt.GetItem()
        if not item or not item.IsOk():
            return

        docIndex = self._getDocumentIndex(item)
        if docIndex is None:
            return

        # take over the drag
        self._draggedDocument = docIndex
        if not self.documentTree.HasCapture():
            self.documentTree.CaptureMouse()
        self.documentTree.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self._updateDropLine(evt.GetPoint())

    # ----

    def onTreeMotion(self, evt):
        """Show where the dragged document would land."""

        if self._draggedDocument is None:
            evt.Skip()
            return

        self._updateDropLine(evt.GetPosition())

    # ----

    def onTreeLMU(self, evt):
        """Drop dragged document at the shown position."""

        if self._draggedDocument is None:
            evt.Skip()
            return

        # get and forget the drag
        fromIndex = self._draggedDocument
        insertAt = self._dropPosition
        self._endDrag()

        # move the document (the insertion point counts the dragged document
        # itself, which leaves its old position first)
        if insertAt is None:
            return
        toIndex = insertAt - 1 if insertAt > fromIndex else insertAt
        if toIndex != fromIndex:
            self.parent.onDocumentMove(fromIndex, toIndex)

    # ----

    def onTreeCaptureLost(self, evt):
        """Abandon the drag when the mouse capture is taken away."""
        self._endDrag()

    # ----

    def _endDrag(self):
        """Stop dragging and remove the insertion line."""

        self._draggedDocument = None
        self._dropPosition = None
        self.documentTree.hideDropLine()
        self.documentTree.SetCursor(wx.NullCursor)

        if self.documentTree.HasCapture():
            self.documentTree.ReleaseMouse()

    # ----

    def _updateDropLine(self, position):
        """Move the insertion line to the gap nearest to the cursor."""

        self._dropPosition = None

        # dragged out of the tree, so there is nowhere to drop
        if not position or not self.documentTree.GetClientRect().Contains(position):
            self.documentTree.hideDropLine()
            return

        # the document can be dropped into any gap between documents, from
        # above the first one to below the last one
        gaps = self._getDropGaps()
        if not gaps:
            self.documentTree.hideDropLine()
            return

        insertAt, y = min(gaps, key=lambda gap: abs(gap[1] - position.y))

        self._dropPosition = insertAt
        self.documentTree.showDropLine(y)

    # ----

    def _getDropGaps(self):
        """Get (insertion index, y position) for all gaps between documents."""

        tree = self.documentTree
        gaps = []
        if not self.documents:
            return gaps

        # a gap above every document
        for docIndex, docData in enumerate(self.documents):
            item = tree.getItemByData(docData)
            rect = tree.GetBoundingRect(item, textOnly=False) if item else None
            if rect:
                gaps.append((docIndex, rect.y))

        # and one below the last one, under whatever it has unfolded
        lastItem = tree.getItemByData(self.documents[-1])
        if lastItem:
            rect = tree.GetBoundingRect(tree.getLastShownItem(lastItem), textOnly=False)
            if rect:
                gaps.append((len(self.documents), rect.GetBottom() + 1))

        return gaps

    # ----

    def onDocumentMoveUp(self, evt=None):
        """Move selected document one position up."""
        self._moveSelectedDocument(-1)

    # ----

    def onDocumentMoveDown(self, evt=None):
        """Move selected document one position down."""
        self._moveSelectedDocument(1)

    # ----

    def _moveSelectedDocument(self, step):
        """Move currently selected document by given number of positions."""

        # get selected document
        item = self.documentTree.GetSelection()
        docIndex = None
        if item and item.IsOk():
            docIndex = self._getDocumentIndex(item)

        # move document
        if docIndex is None or not self.parent.onDocumentMove(
            docIndex, docIndex + step
        ):
            wx.Bell()

    # ----

    def moveDocument(self, docIndex):
        """Move tree item of the document now sitting at given index.

        The documents list is reordered first, this just makes the tree
        follow it.
        """

        docData = self.documents[docIndex]

        # remember selection so that reordering does not change it
        selectedData = None
        selected = self.documentTree.GetSelection()
        if selected and selected.IsOk():
            selectedData = self.documentTree.GetItemData(selected)

        # move the item and restore the selection without disturbing the panels
        self._skipSelectionEvents = True
        try:
            docItem = self.documentTree.moveDocument(docData, docIndex)
            if selectedData is not None:
                selectedItem = self.documentTree.getItemByData(selectedData)
                if selectedItem:
                    self.documentTree.SelectItem(selectedItem)
                    self.documentTree.highlightDocument(selectedItem)
        finally:
            self._skipSelectionEvents = False

        # keep the moved document in view
        if docItem:
            self.documentTree.EnsureVisible(docItem)

    # ----

    def onAdd(self, evt):
        """Add button pressed."""

        # get selected item
        item = self.documentTree.GetSelection()
        indent = self.documentTree.getItemIndent(item)

        # popup menu
        menu = wx.Menu()
        menu.Append(ID_sequenceNew, "New Sequence...")
        menu.AppendSeparator()
        menu.Append(ID_documentNew, "New Document")
        menu.Append(ID_documentNewFromClipboard, "New from Clipboard")
        menu.AppendSeparator()
        menu.Append(ID_documentOpen, "Open Document...")

        menu.Enable(ID_sequenceNew, bool(indent))

        # set events
        self.Bind(wx.EVT_MENU, self.parent.onSequenceNew, id=ID_sequenceNew)
        self.Bind(wx.EVT_MENU, self.parent.onDocumentNew, id=ID_documentNew)
        self.Bind(
            wx.EVT_MENU,
            self.parent.onDocumentNewFromClipboard,
            id=ID_documentNewFromClipboard,
        )
        self.Bind(wx.EVT_MENU, self.parent.onDocumentOpen, id=ID_documentOpen)

        self.PopupMenu(menu)
        menu.Destroy()

    # ----

    def onDelete(self, evt):
        """Delete button pressed."""

        # make menu
        menu = wx.Menu()
        menu.Append(ID_documentAnnotationDelete, "Delete Annotation")
        menu.Append(ID_documentAnnotationsDelete, "Delete All Annotations")
        menu.AppendSeparator()
        menu.Append(ID_sequenceDelete, "Delete Sequence")
        menu.Append(ID_sequenceMatchDelete, "Delete Sequence Match")
        menu.Append(ID_sequenceMatchesDelete, "Delete All Matches")
        menu.AppendSeparator()
        menu.Append(ID_documentNotationsDelete, "Delete All Notations")
        menu.AppendSeparator()
        menu.Append(ID_documentClose, "Close Document")
        menu.Append(ID_documentCloseAll, "Close All Documents")

        # disable items
        menu.Enable(ID_documentAnnotationDelete, False)
        menu.Enable(ID_documentAnnotationsDelete, False)
        menu.Enable(ID_sequenceDelete, False)
        menu.Enable(ID_sequenceMatchDelete, False)
        menu.Enable(ID_sequenceMatchesDelete, False)
        menu.Enable(ID_documentNotationsDelete, False)
        menu.Enable(ID_documentClose, False)
        menu.Enable(ID_documentCloseAll, bool(self.documents))

        # bind events
        self.Bind(wx.EVT_MENU, self.onNotationDelete, id=ID_documentAnnotationDelete)
        self.Bind(
            wx.EVT_MENU,
            self.parent.onDocumentAnnotationsDelete,
            id=ID_documentAnnotationsDelete,
        )

        self.Bind(wx.EVT_MENU, self.parent.onSequenceDelete, id=ID_sequenceDelete)
        self.Bind(wx.EVT_MENU, self.onNotationDelete, id=ID_sequenceMatchDelete)
        self.Bind(
            wx.EVT_MENU,
            self.parent.onSequenceMatchesDelete,
            id=ID_sequenceMatchesDelete,
        )

        self.Bind(
            wx.EVT_MENU,
            self.parent.onDocumentNotationsDelete,
            id=ID_documentNotationsDelete,
        )
        self.Bind(wx.EVT_MENU, self.parent.onDocumentClose, id=ID_documentClose)
        self.Bind(wx.EVT_MENU, self.parent.onDocumentCloseAll, id=ID_documentCloseAll)

        # get selected item
        item = self.documentTree.GetSelection()
        indent = self.documentTree.getItemIndent(item)
        if indent:

            itemType = self.documentTree.getItemType(item)
            docIndex = self._getDocumentIndex(item)
            seqIndex = self._getSequenceIndex(item)

            if self.documents[docIndex].annotations:
                menu.Enable(ID_documentAnnotationsDelete, True)
            if itemType == "annotation":
                menu.Enable(ID_documentAnnotationDelete, True)
                menu.Enable(ID_documentAnnotationsDelete, True)
            if itemType == "sequence":
                menu.Enable(ID_sequenceDelete, True)
            if (
                itemType == "sequence"
                and self.documents[docIndex].sequences[seqIndex].matches
            ):
                menu.Enable(ID_sequenceMatchesDelete, True)
            if itemType == "match":
                menu.Enable(ID_sequenceMatchDelete, True)
                menu.Enable(ID_sequenceMatchesDelete, True)
            if itemType is not None:
                menu.Enable(ID_documentNotationsDelete, True)
                menu.Enable(ID_documentClose, True)

        self.PopupMenu(menu)
        menu.Destroy()

    # ----

    def onNotationEdit(self, evt=None):
        """Edit selected annotation or sequence match."""

        # get selected item
        item = self.documentTree.GetSelection()
        itemType = self.documentTree.getItemType(item)
        itemData = self.documentTree.GetItemData(item)
        docIndex = self._getDocumentIndex(item)

        # backup editable data before mutation
        if itemType == "annotation":
            self.documents[docIndex].backup(("annotations"))
        elif itemType == "match":
            self.documents[docIndex].backup(("sequences"))

        # show dialog
        dlg = dlgNotation(self.parent, itemData, button="Update")
        if dlg.ShowModal() == wx.ID_OK:
            dlg.Destroy()

            if itemType == "annotation":
                self.parent.onDocumentChanged(items=("annotations"))
            elif itemType == "match":
                self.parent.onDocumentChanged(items=("matches"))

        else:
            dlg.Destroy()
            if itemType in ("annotation", "match"):
                self.documents[docIndex].backup(None)

    # ----

    def onNotationDelete(self, evt=None):
        """Delete selected annotation or sequence match."""

        # get index
        item = self.documentTree.GetSelection()
        itemType = self.documentTree.getItemType(item)

        # delete annotation
        if itemType == "annotation":
            annotIndex = self._getAnnotationIndex(item)
            if annotIndex is not None:
                self.parent.onDocumentAnnotationsDelete(annotIndex=annotIndex)

        # delete sequence match
        elif itemType == "match":
            matchIndex = self._getMatchIndex(item)
            if matchIndex is not None:
                self.parent.onSequenceMatchesDelete(matchIndex=matchIndex)

    # ----

    def onSendToMassCalculator(self, evt=None):
        """Send selected item to Mass Calculator panel."""

        # get selected item
        item = self.documentTree.GetSelection()
        itemType = self.documentTree.getItemType(item)
        itemData = self.documentTree.GetItemData(item)

        # send data to Mass Calculator
        if itemType == "sequence":
            self.parent.onToolsMassCalculator(formula=itemData.formula())
        elif itemType in ("annotation", "match"):
            if itemData.radical:
                self.parent.onToolsMassCalculator(
                    formula=itemData.formula,
                    charge=itemData.charge,
                    agentFormula="e",
                    agentCharge=-1,
                )
            else:
                self.parent.onToolsMassCalculator(
                    formula=itemData.formula,
                    charge=itemData.charge,
                    agentFormula="H",
                    agentCharge=1,
                )

    # ----

    def onSendToMassToFormula(self, evt=None):
        """Send selected item to Mass To Formula panel."""

        # get selected item
        item = self.documentTree.GetSelection()
        itemData = self.documentTree.GetItemData(item)

        # send data to Mass To Formula panel
        if itemData.radical:
            self.parent.onToolsMassToFormula(
                mass=itemData.mz, charge=itemData.charge, agentFormula="e"
            )
        else:
            self.parent.onToolsMassToFormula(
                mass=itemData.mz, charge=itemData.charge, agentFormula="H"
            )

    # ----

    def onSendToEnvelopeFit(self, evt=None):
        """Send selected item to envelope fit panel."""

        # get selected item
        item = self.documentTree.GetSelection()
        itemType = self.documentTree.getItemType(item)
        itemData = self.documentTree.GetItemData(item)

        # send data to envelope fit
        if itemType == "sequence":
            self.parent.onToolsEnvelopeFit(sequence=itemData)

        elif itemType == "annotation":
            self.parent.onToolsEnvelopeFit(
                formula=itemData.formula, charge=itemData.charge
            )

        elif itemType == "match":

            scale = None
            if (
                itemData.sequenceRange
                and config.envelopeFit["loss"] == "H"
                and config.envelopeFit["gain"] == "H{2}"
            ):
                scale = [0, itemData.sequenceRange[1] - itemData.sequenceRange[0]]

            self.parent.onToolsEnvelopeFit(
                formula=itemData.formula, charge=itemData.charge, scale=scale
            )

    # ----

    # DOCUMENT

    def selectDocument(self, docIndex):
        """Select document"""

        # deselect all documents
        if docIndex is None:
            self.documentTree.Unselect()
            self.parent.onDocumentSelected(None)
            return

        # get item
        docData = self.documents[docIndex]
        docItem = self.documentTree.getItemByData(docData)

        # select document
        self.documentTree.highlightDocument(docItem)
        self.documentTree.SelectItem(docItem)

    # ----

    def appendLastDocument(self):
        """Append document."""

        # get last document
        docData = self.documents[-1]

        # append to tree
        self.documentTree.appendDocument(docData)

    # ----

    def deleteDocument(self, docIndex):
        """Delete selected document."""

        # check document
        if docIndex is None:
            return

        # remove from tree
        self.documentTree.deleteItemByData(self.documents[docIndex])

    # ----

    def enableDocument(self, docIndex, enable):
        """Enable/disable selected document."""

        # check document
        if docIndex is None:
            return

        # get item
        docData = self.documents[docIndex]
        docItem = self.documentTree.getItemByData(docData)

        # update document
        self.documentTree.enableItemTree(docItem, enable)

    # ----

    def updateDocumentTitle(self, docIndex):
        """Update document title."""

        # check document
        if docIndex is None:
            return

        # get item
        docData = self.documents[docIndex]
        docItem = self.documentTree.getItemByData(docData)

        # get title
        title = docData.title
        if docData.dirty:
            title = "*" + title

        # update document title
        self.documentTree.SetItemText(docItem, title)

    # ----

    def updateDocumentColour(self, docIndex):
        """Update bullet of selected document."""

        # check document
        if docIndex is None:
            return

        # get document item
        docData = self.documents[docIndex]
        docItem = self.documentTree.getItemByData(docData)

        # update colour
        self.documentTree.updateDocumentColour(docItem)

    # ----

    def updateAnnotations(self, docIndex, expand=None):
        """Set new annotations for document."""

        # check document
        if docIndex is None:
            return

        # get item
        annotsData = self.documents[docIndex].annotations
        annotsItem = self.documentTree.getItemByData(annotsData)

        # expand parent
        if expand:
            parent = self.documentTree.GetItemParent(annotsItem)
            self.documentTree.Expand(parent)

        # get expand
        if not expand:
            expand = self.documentTree.IsExpanded(annotsItem)

        # remove old annotations
        self.documentTree.Collapse(annotsItem)
        self.documentTree.DeleteChildren(annotsItem)

        # add new annotations
        for annotData in annotsData:
            self.documentTree.appendNotation(annotsItem, annotData)

        # expand tree
        if expand:
            self.documentTree.Expand(annotsItem)

    # ----

    # SEQUENCE

    def selectSequence(self, docIndex, seqIndex):
        """Select sequence"""

        # check index
        if docIndex is None or seqIndex is None:
            return

        # get item
        seqData = self.documents[docIndex].sequences[seqIndex]
        seqItem = self.documentTree.getItemByData(seqData)

        # select sequence
        self.documentTree.SelectItem(seqItem)

    # ----

    def appendLastSequence(self, docIndex):
        """Append new sequence to the tree."""

        # check document
        if docIndex is None:
            return

        # get document item
        docData = self.documents[docIndex]
        docItem = self.documentTree.getItemByData(docData)

        # get last sequence
        seqData = docData.sequences[-1]

        # append to tree
        self.documentTree.appendSequence(docItem, seqData)

    # ----

    def deleteSequence(self, docIndex, seqIndex):
        """Delete selected sequence."""

        # check document
        if docIndex is None or seqIndex is None:
            return

        # collapse document first
        docData = self.documents[docIndex]
        docItem = self.documentTree.getItemByData(docData)
        self.documentTree.Collapse(docItem)

        # delete sequence
        seqData = self.documents[docIndex].sequences[seqIndex]
        self.documentTree.deleteItemByData(seqData)

        # expand tree
        self.documentTree.Expand(docItem)

    # ----

    def updateSequenceTitle(self, docIndex, seqIndex):
        """Set new label for sequence."""

        # check document
        if docIndex is None or seqIndex is None:
            return

        # get item
        seqData = self.documents[docIndex].sequences[seqIndex]
        seqItem = self.documentTree.getItemByData(seqData)

        # set new label
        self.documentTree.SetItemText(seqItem, seqData.title)

    # ----

    def updateSequenceMatches(self, docIndex, seqIndex, expand=False):
        """Set new matches for sequence."""

        # check document
        if docIndex is None or seqIndex is None:
            return

        # get item
        seqData = self.documents[docIndex].sequences[seqIndex]
        seqItem = self.documentTree.getItemByData(seqData)

        # expand parent
        if expand:
            parent = self.documentTree.GetItemParent(seqItem)
            self.documentTree.Expand(parent)

        # get expand
        if not expand:
            expand = self.documentTree.IsExpanded(seqItem)

        # remove old matches
        self.documentTree.Collapse(seqItem)
        self.documentTree.DeleteChildren(seqItem)

        # add new matches
        for matchData in seqData.matches:
            self.documentTree.appendNotation(seqItem, matchData)

        # expand tree
        if expand:
            self.documentTree.Expand(seqItem)

    # ----

    def updateSequences(self, docIndex):
        """Set new sequences for current document."""

        # check document
        if docIndex is None:
            return

        # collapse document first
        docData = self.documents[docIndex]
        docItem = self.documentTree.getItemByData(docData)
        expand = self.documentTree.IsExpanded(docItem)
        self.documentTree.Collapse(docItem)

        # delete sequences
        if docItem.IsOk() and self.documentTree.ItemHasChildren(docItem):
            items = []

            child, cookie = self.documentTree.GetFirstChild(docItem)
            while child.IsOk():
                if self.documentTree.getItemType(child) == "sequence":
                    items.append(child)
                child, cookie = self.documentTree.GetNextChild(docItem, cookie)

            for item in items:
                self.documentTree.Delete(item)

        # set new sequences
        for seqData in self.documents[docIndex].sequences:
            self.documentTree.appendSequence(docItem, seqData)

        # expand tree
        if expand:
            self.documentTree.Expand(docItem)

    # ----

    # UTILITIES

    def getSelectedItemType(self):
        """Get selected item type."""

        item = self.documentTree.GetSelection()
        itemType = self.documentTree.getItemType(item)

        return itemType

    # ----

    def _getDocumentIndex(self, item):
        """Get parent document index."""

        docItem = self.documentTree.getParentItem(item, 1)
        docData = self.documentTree.GetItemData(docItem)

        if docData in self.documents:
            return self.documents.index(docData)
        else:
            return None

    # ----

    def _getAnnotationIndex(self, item):
        """Get annotation index."""

        docIndex = self._getDocumentIndex(item)
        annotData = self.documentTree.GetItemData(item)

        if annotData in self.documents[docIndex].annotations:
            return self.documents[docIndex].annotations.index(annotData)
        else:
            return None

    # ----

    def _getSequenceIndex(self, item):
        """Get parent sequence index."""

        docIndex = self._getDocumentIndex(item)
        seqItem = self.documentTree.getParentItem(item, 2)
        seqData = self.documentTree.GetItemData(seqItem)

        if seqData in self.documents[docIndex].sequences:
            return self.documents[docIndex].sequences.index(seqData)
        else:
            return None

    # ----

    def _getMatchIndex(self, item):
        """Get match index."""

        docIndex = self._getDocumentIndex(item)
        seqIndex = self._getSequenceIndex(item)
        matchData = self.documentTree.GetItemData(item)

        if matchData in self.documents[docIndex].sequences[seqIndex].matches:
            return self.documents[docIndex].sequences[seqIndex].matches.index(matchData)
        else:
            return None

    # ----


class documentsTree(wx.TreeCtrl):
    """Documents tree."""

    def __init__(self, parent, id, size=(-1, -1), style=mwx.DOCTREE_STYLE):
        wx.TreeCtrl.__init__(self, parent, id, size=size, style=style)

        self.parent = parent

        # set font and colour
        # Derive from the system GUI font (as the peak list does) rather than the
        # UI-scaled wx.SMALL_FONT: on HiDPI the toolkit already scales point sizes,
        # so the extra UI_SCALE multiplier made the spectra list font oversized.
        font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        font.SetPointSize(font.GetPointSize() - 2)
        self.SetFont(font)
        self._applyThemeBackground()

        # init bullets
        self.bullets = wx.ImageList(13, 12)
        self.SetImageList(self.bullets)
        self._resetBullets()

        # add root
        root = self.AddRoot("Documents")
        self.SetItemImage(root, 0, wx.TreeItemIcon_Normal)

        # init insertion line shown while a document is dragged - a thin child
        # window rather than something drawn on the tree, so that it survives
        # the tree repainting itself under it
        self.dropLineHeight = max(
            2, display_scale.scale_metric(2, display_scale.get_ui_scale())
        )
        self.dropLineColour = self._themedDropLineColour()
        self.dropLine = wx.Window(self, -1, size=wx.Size(-1, self.dropLineHeight))
        self.dropLine.SetBackgroundColour(self.dropLineColour)
        # not every toolkit fills a bare window with its background colour
        self.dropLine.Bind(wx.EVT_PAINT, self._onDropLinePaint)
        self.dropLine.Hide()

    # ----

    def _themedDropLineColour(self):
        """Colour of the insertion line shown while a document is dragged."""

        if images.is_dark_mode():
            return wx.Colour(90, 160, 255)

        return wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)

    # ----

    def _applyThemeBackground(self):
        """Set the tree background for the current theme.

        Both themes name a colour explicitly, because _makeColourBullet bakes
        GetBackgroundColour() into every bullet bitmap: unless the tree is made
        to paint exactly the colour that read back, each bullet carries a
        square that does not match the row behind it.
        """

        if images.is_dark_mode():
            colour = wx.Colour(*mwx.DOCTREE_DARK_COLOUR)
        else:
            colour = wx.Colour(*mwx.DOCTREE_COLOUR)

        self.SetOwnBackgroundColour(colour)

    # ----

    def onThemeChanged(self):
        """Rebuild the bullets after a live light/dark switch.

        _makeColourBullet bakes the tree background into every document bullet
        (the bitmaps have no alpha), so on a switch they all carry a block of
        the old background and have to be drawn again.  Rebuilding the image
        list renumbers the per-document bullets, so each document is given its
        new index as well, and the item text colours -- also picked per theme --
        are re-applied on the way through.
        """

        self._applyThemeBackground()

        self.dropLineColour = self._themedDropLineColour()
        self.dropLine.SetBackgroundColour(self.dropLineColour)

        self._resetBullets()

        root = self.GetRootItem()
        if not root.IsOk():
            return

        # enableItem() clears the bold flag that marks the current document
        highlighted = None

        child, cookie = self.GetFirstChild(root)
        while child.IsOk():
            if self.IsBold(child):
                highlighted = child

            docData = self.GetItemData(child)
            if docData is not None:
                bullet = self._makeColourBullet(docData.colour, True)
                docData.bulletIndex = self.bullets.Add(bullet)
                self.enableItemTree(child, docData.visible)

            child, cookie = self.GetNextChild(root, cookie)

        if highlighted is not None:
            self.SetItemBold(highlighted, True)

    # ----

    def showDropLine(self, y):
        """Show the insertion line at given position."""

        width = self.GetClientSize().width
        top = max(0, y - self.dropLineHeight // 2)

        self.dropLine.SetSize(0, top, width, self.dropLineHeight)
        self.dropLine.Show()
        self.dropLine.Raise()

    # ----

    def hideDropLine(self):
        """Hide the insertion line."""
        self.dropLine.Hide()

    # ----

    def _onDropLinePaint(self, evt):
        """Paint the insertion line."""

        dc = wx.PaintDC(self.dropLine)
        dc.SetBackground(wx.Brush(self.dropLineColour, wx.BRUSHSTYLE_SOLID))
        dc.Clear()

    # ----

    def getLastShownItem(self, item):
        """Get last item displayed under given item, i.e. its bottom line."""

        while self.IsExpanded(item) and self.ItemHasChildren(item):
            item = self.GetLastChild(item)

        return item

    # ----

    def getItemIndent(self, item):
        """Get indent of selected item."""

        # check item
        if not item.IsOk():
            return False

        # get indent
        indent = 0
        root = self.GetRootItem()
        while item.IsOk():
            if item == root:
                return indent
            else:
                item = self.GetItemParent(item)
                indent += 1

    # ----

    def getItemType(self, item):
        """Get current item type."""

        # check item
        if not item.IsOk() or item is self.GetRootItem():
            return None

        # get item type
        data = self.GetItemData(item)
        if isinstance(data, doc.document):
            return "document"
        elif isinstance(data, list):
            return "annotations"
        elif isinstance(data, doc.annotation):
            return "annotation"
        elif isinstance(data, mspy.sequence):
            return "sequence"
        elif isinstance(data, doc.match):
            return "match"
        else:
            return None

    # ----

    def getItemByData(self, data, root=None, cookie=0):
        """Get item by its data."""

        # get root
        if root is None:
            root = self.GetRootItem()

        # check children
        if self.ItemHasChildren(root):
            firstchild, cookie = self.GetFirstChild(root)
            if self.GetItemData(firstchild) is data:
                return firstchild
            matchedItem = self.getItemByData(data, firstchild, cookie)
            if matchedItem:
                return matchedItem

        # check siblings
        child = self.GetNextSibling(root)
        if child and child.IsOk():
            if self.GetItemData(child) is data:
                return child
            matchedItem = self.getItemByData(data, child, cookie)
            if matchedItem:
                return matchedItem

        # no such item found
        return False

    # ----

    def getParentItem(self, item, level):
        """Get parent item for selected item and level."""

        # get item
        itemIndent = self.getItemIndent(item) or 0
        for _x in range(level, itemIndent):
            item = self.GetItemParent(item)

        return item

    # ----

    def enableItemTree(self, item, enable=True):
        """Enable/disable all children recursively."""

        # enable current item
        self.enableItem(item, enable)

        # enable children
        child, cookie = self.GetFirstChild(item)
        while child.IsOk():

            # enable item
            self.enableItem(child, enable)

            # check children
            if self.ItemHasChildren(child):
                self.enableItemTree(child, enable)

            # get next
            child, cookie = self.GetNextChild(item, cookie)

    # ---

    def enableItem(self, item, enable=True):
        """Enable document and all children."""

        # get item indent
        itemType = self.getItemType(item)
        if not itemType:
            return

        # set text colour
        if enable:
            self.SetItemTextColour(
                item,
                wx.Colour(220, 220, 220) if images.is_dark_mode() else wx.Colour(0, 0, 0),
            )
            self.SetItemBold(item, False)
        else:
            self.SetItemTextColour(
                item,
                wx.Colour(100, 100, 100)
                if images.is_dark_mode()
                else wx.Colour(150, 150, 150),
            )
            self.SetItemBold(item, False)

        # set document bullet
        if itemType == "document":
            if enable:
                self.SetItemImage(
                    item, self.GetItemData(item).bulletIndex, wx.TreeItemIcon_Normal
                )
            else:
                self.SetItemImage(item, 1, wx.TreeItemIcon_Normal)

        # set annotations bullet
        elif itemType == "annotations":
            if enable:
                self.SetItemImage(item, 2, wx.TreeItemIcon_Normal)
            else:
                self.SetItemImage(item, 3, wx.TreeItemIcon_Normal)

        # set sequence bullet
        elif itemType == "sequence":
            if enable:
                self.SetItemImage(item, 4, wx.TreeItemIcon_Normal)
            else:
                self.SetItemImage(item, 5, wx.TreeItemIcon_Normal)

        # set match / annotation bullet
        elif itemType == "match" or itemType == "annotation":
            if enable:
                self.SetItemImage(item, 6, wx.TreeItemIcon_Normal)
            else:
                self.SetItemImage(item, 7, wx.TreeItemIcon_Normal)

    # ----

    def appendDocument(self, docData, index=None):
        """Append document to tree, or insert it at given position."""

        # add bullet
        bullet = self._makeColourBullet(docData.colour, True)
        docData.bulletIndex = self.bullets.Add(bullet)

        # get title
        title = docData.title
        if docData.dirty:
            title = "*" + title

        # add document
        if index is None:
            docItem = self.AppendItem(self.GetRootItem(), title)
        else:
            docItem = self.InsertItem(self.GetRootItem(), index, title)
        self.SetItemImage(docItem, docData.bulletIndex, wx.TreeItemIcon_Normal)
        self.SetItemData(docItem, docData)

        # add annotations
        annotsItem = self.AppendItem(docItem, "Annotations")
        self.SetItemImage(annotsItem, 2, wx.TreeItemIcon_Normal)
        self.SetItemData(annotsItem, docData.annotations)
        for annotData in docData.annotations:
            self.appendNotation(annotsItem, annotData)

        # add sequences
        for seqData in docData.sequences:
            self.appendSequence(docItem, seqData)

        # enable/disable document and all children
        self.enableItemTree(docItem, docData.visible)

        return docItem

    # ----

    def appendSequence(self, item, seqData):
        """Append sequence to tree."""

        # add sequence
        seqItem = self.AppendItem(item, seqData.title)
        self.SetItemImage(seqItem, 4, wx.TreeItemIcon_Normal)
        self.SetItemData(seqItem, seqData)

        # add matches
        for matchData in seqData.matches:
            self.appendNotation(seqItem, matchData)

        return seqItem

    # ----

    def appendNotation(self, item, notationData):
        """Append notation to tree."""

        # get mz
        mz = round(notationData.mz, config.main["mzDigits"])

        # get error
        error = notationData.delta(config.main["errorUnits"])
        if error is not None and config.main["errorUnits"] == "ppm":
            error = round(error, config.main["ppmDigits"])
        elif error is not None:
            error = round(error, config.main["mzDigits"])

        # make label
        if error is not None:
            label = "%s (%s %s) %s" % (
                mz,
                error,
                config.main["errorUnits"],
                notationData.label,
            )
        else:
            label = "%s %s" % (mz, notationData.label)

        # add match
        notationItem = self.AppendItem(item, label)
        self.SetItemImage(notationItem, 6, wx.TreeItemIcon_Normal)
        self.SetItemData(notationItem, notationData)

        return notationItem

    # ----

    def deleteItemByData(self, data):
        """Delete item by data."""

        item = self.getItemByData(data)
        if item:
            self.Delete(item)

    # ----

    def moveDocument(self, docData, index):
        """Move document item to given position within the tree."""

        # get current item
        item = self.getItemByData(docData)
        if not item:
            return None

        # the tree cannot move items, so the whole document is rebuilt from
        # its data at the new position - only expansion has to be preserved
        expanded = self._getExpandedItems(item)
        self.Delete(item)
        docItem = self.appendDocument(docData, index=index)
        self._setExpandedItems(docItem, expanded)

        return docItem

    # ----

    def _getExpandedItems(self, item, expanded=None):
        """Get data of all expanded items in the branch."""

        if expanded is None:
            expanded = set()

        if self.ItemHasChildren(item) and self.IsExpanded(item):
            expanded.add(id(self.GetItemData(item)))

        child, cookie = self.GetFirstChild(item)
        while child.IsOk():
            self._getExpandedItems(child, expanded)
            child, cookie = self.GetNextChild(item, cookie)

        return expanded

    # ----

    def _setExpandedItems(self, item, expanded):
        """Expand items in the branch according to remembered data."""

        if self.ItemHasChildren(item) and id(self.GetItemData(item)) in expanded:
            self.Expand(item)

        child, cookie = self.GetFirstChild(item)
        while child.IsOk():
            self._setExpandedItems(child, expanded)
            child, cookie = self.GetNextChild(item, cookie)

    # ----

    def highlightDocument(self, item):
        """Highlight parent document."""

        # unbold all documents
        child, cookie = self.GetFirstChild(self.GetRootItem())
        while child.IsOk():
            self.SetItemBold(child, False)
            child, cookie = self.GetNextChild(self.GetRootItem(), cookie)

        # select parent document
        if item is not None:
            item = self.getParentItem(item, 1)
            self.SetItemBold(item, True)

    # ----

    def updateDocumentColour(self, item):
        """Set new bullet colour."""

        # add bullet
        item = self.getParentItem(item, 1)
        docData = self.GetItemData(item)

        bullet = self._makeColourBullet(docData.colour, True)
        docData.bulletIndex = self.bullets.Add(bullet)

        # set new bullet
        self.SetItemImage(item, docData.bulletIndex, wx.TreeItemIcon_Normal)

    # ----

    def _resetBullets(self):
        """Erase all bullets and make defaults."""

        self.bullets.RemoveAll()
        self.bullets.Add(images.lib["bulletsDocument"])
        self.bullets.Add(self._makeColourBullet((150, 150, 150), False))
        self.bullets.Add(images.lib["bulletsAnnotationsOn"])
        self.bullets.Add(images.lib["bulletsAnnotationsOff"])
        self.bullets.Add(images.lib["bulletsSequenceOn"])
        self.bullets.Add(images.lib["bulletsSequenceOff"])
        self.bullets.Add(images.lib["bulletsNotationOn"])
        self.bullets.Add(images.lib["bulletsNotationOff"])

    # ----

    def _makeColourBullet(self, colour, filled=True):
        """Make bullet bitmap with specified colour."""

        # create empty bitmap
        bitmap = wx.Bitmap(13, 12)
        dc = wx.MemoryDC()
        dc.SelectObject(bitmap)

        # clear background
        if wx.Platform != "__WXMAC__":
            dc.SetBackground(wx.Brush(self.GetBackgroundColour(), wx.BRUSHSTYLE_SOLID))
            dc.Clear()

        # set pen and brush
        if filled:
            pencolour = [max(x - 70, 0) for x in colour]
            dc.SetPen(wx.Pen(wx.Colour(*pencolour), 1, wx.PENSTYLE_SOLID))
            dc.SetBrush(wx.Brush(wx.Colour(*colour), wx.BRUSHSTYLE_SOLID))
        else:
            dc.SetPen(wx.Pen(wx.Colour(*colour), 1, wx.PENSTYLE_SOLID))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)

        # draw circle
        # Keep the circle inside the 13x12 image box while making it larger.
        radius = int(round(mwx.DOCTREE_BULLETSIZE * 1.33))
        radius = min(radius, 6)
        dc.DrawCircle(6, 6, radius)
        dc.SelectObject(wx.NullBitmap)

        return bitmap

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
