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

# pyright: reportWildcardImportFromLibrary=false

# load libs
import functools
import os.path
import time
import wx
from . import display_scale

# load modules
from . import ids as _ids
from . import images
from . import config
from .mixins import MakeModalMixin
import mspy

_name = ""
for _name in dir(_ids):
    if _name.startswith(("HK_", "ID_")):
        globals()[_name] = getattr(_ids, _name)

del _name


_WX_DASH_SHORT = getattr(wx, "PENSTYLE_SHORT_DASH", getattr(wx, "SHORT_DASH", 2))
_WX_DASH_DOT = getattr(wx, "PENSTYLE_DOT", getattr(wx, "DOT", 3))

# GUI CONSTANTS
# -------------

SMALL_FONT_SIZE = 8
NORMAL_FONT_SIZE = 9
SASH_COLOUR = None
SASH_SIZE = 3
GRIPPER_SIZE = 10
PANEL_SPACE_MAIN = 10
GRIDBAG_VSPACE = 7
GRIDBAG_HSPACE = 5

GAUGE_HEIGHT = 15
GAUGE_SPACE = 10

MAIN_TOOLBAR_TOOLSIZE = (22, 22)
MAIN_TOOLBAR_STYLE = wx.TB_FLAT | wx.TB_NODIVIDER | wx.TB_HORIZONTAL

TOOLBAR_HEIGHT = 36
TOOLBAR_LSPACE = 0
TOOLBAR_RSPACE = 10
TOOLBAR_TOOLSIZE = (-1, -1)
CONTROLBAR_HEIGHT = 32
CONTROLBAR_DOUBLE_HEIGHT = 61
CONTROLBAR_LSPACE = 10
CONTROLBAR_RSPACE = 10
BOTTOMBAR_HEIGHT = 22
BOTTOMBAR_LSPACE = 0
BOTTOMBAR_RSPACE = 0
BOTTOMBAR_TOOLSIZE = (-1, -1)
SMALL_CHOICE_HEIGHT = -1
SMALL_BUTTON_HEIGHT = 22
SMALL_TEXTCTRL_HEIGHT = -1
SMALL_SEARCH_HEIGHT = -1
BUTTON_SIZE_CORRECTION = 0

CHOICE_HEIGHT = -1

LISTCTRL_STYLE_SINGLE = (
    wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_VRULES | wx.LC_HRULES | wx.SUNKEN_BORDER
)
LISTCTRL_STYLE_MULTI = wx.LC_REPORT | wx.LC_VRULES | wx.LC_HRULES | wx.SUNKEN_BORDER
LISTCTRL_NO_SPACE = 0
LISTCTRL_SPACE = 0
LISTCTRL_ALTCOLOUR = None
LISTCTRL_SORT = 1

DOCTREE_COLOUR = (255, 255, 255)
# Dark counterpart, kept in step with the _DARK_BG the peak list and the plot
# canvas use so the left-hand column reads as one surface.  Set explicitly
# rather than left to the toolkit because panel_documents bakes the tree
# background into its document bullet bitmaps.
DOCTREE_DARK_COLOUR = (30, 30, 30)
DOCTREE_BULLETSIZE = 5
DOCTREE_STYLE = wx.TR_DEFAULT_STYLE | wx.TR_HAS_BUTTONS

PLOTCANVAS_STYLE_PANEL = wx.SUNKEN_BORDER
PLOTCANVAS_STYLE_DIALOG = wx.SUNKEN_BORDER

GRID_STYLE = wx.SUNKEN_BORDER
SLIDER_STYLE = wx.SL_HORIZONTAL | wx.SL_AUTOTICKS | wx.SL_LABELS
SEQUENCE_FONT_SIZE = 10
PERIODIC_TABLE_GRID = (2, 2)
PERIODIC_TABLE_FONT_SIZE = 14
DASHED_LINE = _WX_DASH_SHORT
SCROLL_DIRECTION = 1


# set mac
if wx.Platform == "__WXMAC__":
    SMALL_FONT_SIZE = 11
    NORMAL_FONT_SIZE = 12
    SASH_COLOUR = (111, 111, 111)
    SASH_SIZE = 1
    GRIPPER_SIZE = 8
    PANEL_SPACE_MAIN = 20
    GRIDBAG_VSPACE = 10
    GRIDBAG_HSPACE = 5

    GAUGE_HEIGHT = 11
    GAUGE_SPACE = 15

    MAIN_TOOLBAR_TOOLSIZE = (32, 23)
    MAIN_TOOLBAR_STYLE = wx.TB_FLAT | wx.TB_NODIVIDER | wx.TB_HORIZONTAL | wx.TB_TEXT

    # The control/bottom bars are segmented-control sprites sliced into 29x22
    # cells: each cell carries its divider on its RIGHT edge, so a cell's left
    # border is supplied by the previous cell's right edge -- they only look
    # right when the cells abut pixel-perfectly. Pin the buttons to the exact
    # 29x22 art size (a borderless wx.BitmapButton otherwise pads to 37x30 on
    # wxOSX, and the 8px of chrome forces gaps that expose every non-first
    # cell's missing left border) and abut them with BUTTON_SIZE_CORRECTION = 0.
    TOOLBAR_TOOLSIZE = (29, 22)
    BOTTOMBAR_TOOLSIZE = (29, 22)

    TOOLBAR_HEIGHT = 38
    TOOLBAR_LSPACE = 15
    TOOLBAR_RSPACE = 15
    CONTROLBAR_LSPACE = 15
    CONTROLBAR_RSPACE = 15
    BOTTOMBAR_HEIGHT = 33
    BOTTOMBAR_LSPACE = 10
    BOTTOMBAR_RSPACE = 10
    SMALL_CHOICE_HEIGHT = 22
    SMALL_BUTTON_HEIGHT = -1
    SMALL_TEXTCTRL_HEIGHT = 18
    SMALL_SEARCH_HEIGHT = 22
    # Buttons are pinned to the exact art size above, so adjacent segmented
    # cells must touch with no extra margin for their baked borders to join.
    BUTTON_SIZE_CORRECTION = 0

    CHOICE_HEIGHT = 22

    LISTCTRL_STYLE_SINGLE = (
        wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_VRULES | wx.NO_BORDER
    )
    LISTCTRL_STYLE_MULTI = wx.LC_REPORT | wx.LC_VRULES | wx.NO_BORDER
    LISTCTRL_SPACE = 20
    LISTCTRL_ALTCOLOUR = wx.Colour(230, 240, 250)
    LISTCTRL_SORT = -1
    LISTCTRL_NO_SPACE = -3
    if config.main["macListCtrlGeneric"]:
        LISTCTRL_NO_SPACE = -2
        LISTCTRL_STYLE_SINGLE = (
            wx.LC_REPORT
            | wx.LC_SINGLE_SEL
            | wx.LC_VRULES
            | wx.LC_HRULES
            | wx.SIMPLE_BORDER
        )
        LISTCTRL_STYLE_MULTI = (
            wx.LC_REPORT | wx.LC_VRULES | wx.LC_HRULES | wx.SIMPLE_BORDER
        )
        LISTCTRL_ALTCOLOUR = None
        LISTCTRL_SORT = 1

    DOCTREE_COLOUR = (214, 221, 229)
    DOCTREE_BULLETSIZE = 4
    DOCTREE_STYLE = wx.TR_DEFAULT_STYLE | wx.TR_HAS_BUTTONS | wx.TR_HIDE_ROOT

    PLOTCANVAS_STYLE_PANEL = wx.NO_BORDER
    PLOTCANVAS_STYLE_DIALOG = wx.SIMPLE_BORDER

    GRID_STYLE = wx.NO_BORDER
    SEQUENCE_FONT_SIZE = 12
    PERIODIC_TABLE_GRID = (-3, -5)
    PERIODIC_TABLE_FONT_SIZE = 18


# set windows
elif wx.Platform == "__WXMSW__":
    SMALL_CHOICE_HEIGHT = 22
    SMALL_BUTTON_HEIGHT = 22
    SMALL_SEARCH_HEIGHT = 22

    DASHED_LINE = _WX_DASH_DOT

# set gtk
elif wx.Platform == "__WXGTK__":
    SMALL_FONT_SIZE = 10
    NORMAL_FONT_SIZE = 11
    SASH_SIZE = 6

    TOOLBAR_TOOLSIZE = (32, 26)
    BOTTOMBAR_HEIGHT = 28
    BOTTOMBAR_TOOLSIZE = (32, 26)
    SMALL_CHOICE_HEIGHT = 25
    SMALL_BUTTON_HEIGHT = 25
    SMALL_TEXTCTRL_HEIGHT = 25
    SMALL_SEARCH_HEIGHT = 25

    DOCTREE_BULLETSIZE = 4
    DOCTREE_STYLE = (
        wx.TR_DEFAULT_STYLE | wx.TR_HAS_BUTTONS | wx.TR_HIDE_ROOT | wx.SUNKEN_BORDER
    )

    PERIODIC_TABLE_GRID = (-7, -7)


UI_SCALE = display_scale.get_ui_scale()


def _scale_int(value):
    return display_scale.scale_metric(value, UI_SCALE)


def _scale_pair(pair):
    return (_scale_int(pair[0]), _scale_int(pair[1]))


if UI_SCALE != 1.0:
    # NOTE: font point sizes are deliberately NOT scaled by UI_SCALE. The
    # toolkit already renders point sizes at the system DPI, so multiplying
    # them here double-scales fonts (canvas labels, progress dialogs, lists)
    # on HiDPI displays. UI_SCALE only compensates pixel-based metrics below.
    SASH_SIZE = _scale_int(SASH_SIZE)
    GRIPPER_SIZE = _scale_int(GRIPPER_SIZE)
    PANEL_SPACE_MAIN = _scale_int(PANEL_SPACE_MAIN)
    GRIDBAG_VSPACE = _scale_int(GRIDBAG_VSPACE)
    GRIDBAG_HSPACE = _scale_int(GRIDBAG_HSPACE)

    GAUGE_HEIGHT = _scale_int(GAUGE_HEIGHT)
    GAUGE_SPACE = _scale_int(GAUGE_SPACE)

    MAIN_TOOLBAR_TOOLSIZE = _scale_pair(MAIN_TOOLBAR_TOOLSIZE)

    TOOLBAR_HEIGHT = _scale_int(TOOLBAR_HEIGHT)
    TOOLBAR_LSPACE = _scale_int(TOOLBAR_LSPACE)
    TOOLBAR_RSPACE = _scale_int(TOOLBAR_RSPACE)
    TOOLBAR_TOOLSIZE = _scale_pair(TOOLBAR_TOOLSIZE)
    CONTROLBAR_HEIGHT = _scale_int(CONTROLBAR_HEIGHT)
    CONTROLBAR_DOUBLE_HEIGHT = _scale_int(CONTROLBAR_DOUBLE_HEIGHT)
    CONTROLBAR_LSPACE = _scale_int(CONTROLBAR_LSPACE)
    CONTROLBAR_RSPACE = _scale_int(CONTROLBAR_RSPACE)
    BOTTOMBAR_HEIGHT = _scale_int(BOTTOMBAR_HEIGHT)
    BOTTOMBAR_LSPACE = _scale_int(BOTTOMBAR_LSPACE)
    BOTTOMBAR_RSPACE = _scale_int(BOTTOMBAR_RSPACE)
    BOTTOMBAR_TOOLSIZE = _scale_pair(BOTTOMBAR_TOOLSIZE)
    SMALL_CHOICE_HEIGHT = _scale_int(SMALL_CHOICE_HEIGHT)
    SMALL_BUTTON_HEIGHT = _scale_int(SMALL_BUTTON_HEIGHT)
    SMALL_TEXTCTRL_HEIGHT = _scale_int(SMALL_TEXTCTRL_HEIGHT)
    SMALL_SEARCH_HEIGHT = _scale_int(SMALL_SEARCH_HEIGHT)
    BUTTON_SIZE_CORRECTION = _scale_int(BUTTON_SIZE_CORRECTION)
    CHOICE_HEIGHT = _scale_int(CHOICE_HEIGHT)

    LISTCTRL_NO_SPACE = _scale_int(LISTCTRL_NO_SPACE)
    LISTCTRL_SPACE = _scale_int(LISTCTRL_SPACE)
    DOCTREE_BULLETSIZE = _scale_int(DOCTREE_BULLETSIZE)
    PERIODIC_TABLE_GRID = _scale_pair(PERIODIC_TABLE_GRID)
    # SEQUENCE_FONT_SIZE / PERIODIC_TABLE_FONT_SIZE intentionally left unscaled
    # (see the font-size note above).


# breathing room on each side of a centred text column in a grid
GRID_CELL_PADDING = 6


def gridRowHeight(window, font, padding=6, minimum=19):
    """A grid row height that actually fits the given font.

    Grid row heights used to be a hardcoded 19 px. Raw pixel metrics like that
    are not DPI-scaled (see the UI_SCALE note above) while the point-sized cell
    font is scaled by the toolkit, so on Linux/HiDPI the text ended up taller
    than its row and was clipped by the row edge. Measuring the font keeps the
    two in step.
    """

    try:
        dc = wx.ClientDC(window)
    except Exception:
        dc = wx.MemoryDC(wx.Bitmap(1, 1))

    dc.SetFont(font)
    height = dc.GetCharHeight()

    return max(minimum, height + padding)


def cmp(a, b):
    if a == b:
        return 0
    elif a is None:
        return -1
    elif b is None:
        return 1
    else:
        try:
            return (float(a) > float(b)) - (float(a) < float(b))
        except (TypeError, ValueError):
            try:
                return (a > b) - (a < b)
            except TypeError:
                return (str(a) > str(b)) - (str(a) < str(b))


def shiftIndex(index, fromIndex, toIndex):
    """Get new position of an item after another item was moved in a list."""

    if index == fromIndex:
        return toIndex
    elif fromIndex < index <= toIndex:
        return index - 1
    elif toIndex <= index < fromIndex:
        return index + 1
    else:
        return index


def _isBrukerFID(path):
    """Tell whether a path is a Bruker acquisition rather than a stray 'fid'.

    The name alone is what makes mMass read a file as Bruker data, but the
    dataset folder is only worth walking up to when the tree really is one:
    every acquisition keeps its parameters in an acqu file beside the fid.
    """

    if os.path.basename(path).lower() != "fid":
        return False

    return os.path.exists(os.path.join(os.path.dirname(path), "acqu"))


def _brukerDatasetDir(path):
    """Get the dataset folder for Bruker data opened at path, else "".

    The path may be a fid, the dataset folder itself, or a folder holding
    several datasets. In the last case any one of them answers the question
    being asked, since they are all siblings inside that folder.
    """

    if os.path.isdir(path):
        fids = mspy.findFIDs(path)
        return mspy.datasetDir(fids[0]) if fids else ""

    if _isBrukerFID(path):
        return mspy.datasetDir(path)

    return ""


def saveDialogDir(documentPath="", fallbackDir=""):
    """Pick the initial directory for a save/export file dialog.

    Prefer the folder the document itself lives in, so that "Save As" and
    exports default next to the source file rather than re-using one shared
    last-used directory for every document. Fall back to the last-used
    directory, and finally to "" so the dialog opens at its own default.

    Bruker data is not a file but a folder tree, and a dataset is treated as
    though it were one file however many spots it holds: results go BESIDE the
    dataset folder. That one rule covers all three ways of opening it - a fid
    on its own, its dataset folder, or a folder holding several datasets, in
    which case beside the datasets means inside the folder that holds them.
    """

    candidates = []
    if documentPath:
        dataset = _brukerDatasetDir(documentPath)
        if dataset:
            parent = os.path.dirname(dataset)
            # an unusually shallow tree can leave nothing useful above the
            # dataset - no 'beside' to save to, or the filesystem root
            if parent and parent != dataset and parent != os.path.dirname(parent):
                candidates.append(parent)

        if os.path.isdir(documentPath):
            candidates.append(documentPath)
        else:
            candidates.append(os.path.dirname(documentPath))
    candidates.append(fallbackDir)

    for candidate in candidates:
        if candidate and os.path.isdir(candidate):
            return candidate

    return ""


# RUN AFTER APP INIT
# ------------------


def appInit():
    """Run after application initialize."""

    # set MAC
    if wx.Platform == "__WXMAC__":
        wx.SystemOptions.SetOption(
            "mac.listctrl.always_use_generic", config.main["macListCtrlGeneric"]
        )
        wx.ToolTip.SetDelay(1500)
        if config.main["reverseScrolling"]:
            global SCROLL_DIRECTION
            SCROLL_DIRECTION = -1

    # set WIN
    elif wx.Platform == "__WXMSW__":
        wx.SMALL_FONT.SetPointSize(SMALL_FONT_SIZE)

        if images.is_dark_mode():
            # wxWidgets 3.3+ drives MSW dark mode itself: it sets the preferred
            # app mode, flushes the menu themes and dark-renders the menu bar,
            # native toolbars and window frames -- none of which honour a plain
            # SetBackgroundColour(). DarkMode_Auto follows the system setting,
            # which we have just established is dark.
            app = wx.GetApp()
            # MSW-only method, absent from the cross-platform wx stubs.
            enableDarkMode = getattr(app, "MSWEnableDarkMode", None)
            if enableDarkMode is not None:
                enableDarkMode()

    # set GTK
    elif wx.Platform == "__WXGTK__":
        wx.SMALL_FONT.SetPointSize(SMALL_FONT_SIZE)


# ----


_DARK_BG = wx.Colour(30, 30, 30)
_DARK_FG = wx.Colour(220, 220, 220)


def _setHwndTheme(hwnd, theme, sub_id=None):
    """Best-effort: assign a native visual-styles theme class to a raw HWND.

    Pass empty strings for both *theme* and *sub_id* to instead *disable* visual
    styles on the control, which makes it honour the colours wx paints (e.g. a
    list header's SetHeaderAttr background, which the themed header ignores).

    Requires the app to be in dark mode, which appInit() arranges at startup
    via wxApp.MSWEnableDarkMode().
    No-op on any failure.
    """

    try:
        import ctypes

        if not hwnd:
            return

        windll = getattr(ctypes, "WinDLL", None)
        if windll is None:
            return
        uxtheme = windll("uxtheme", use_last_error=True)

        set_window_theme = uxtheme.SetWindowTheme
        set_window_theme.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
        ]
        set_window_theme.restype = ctypes.c_long  # HRESULT
        set_window_theme(ctypes.c_void_p(hwnd), theme, sub_id)
    except Exception:
        pass


def _rgb(r, g, b):
    """Pack an (r, g, b) triple into a Win32 COLORREF (0x00BBGGRR)."""
    return r | (g << 8) | (b << 16)


# Header colours (kept close to the list/header attr palette).
_HDR_BG = _rgb(45, 45, 45)
_HDR_FG = _rgb(220, 220, 220)
_HDR_SEP = _rgb(70, 70, 70)

# Keep owner-draw callbacks alive for the process lifetime (ctypes callbacks must
# not be garbage-collected while Windows can still invoke them).
_header_subclass_procs = []


def _darkenWindowsListHeader(listctrl):
    """Best-effort: owner-draw the native list header dark on wxMSW.

    The header is a separate SysHeader32 child window.  Neither a "DarkMode_*"
    theme class nor wx's SetHeaderAttr fully darkens it: a themed header keeps a
    light fill, and an un-themed one only paints colour *behind the text*, so the
    rest of each cell stays light.  The only reliable fix is to take over its
    painting -- subclass the header and draw every cell (background, label,
    separator) ourselves in WM_PAINT.  No-op off Windows or on any failure; on
    failure it falls back to disabling the header's visual styles (partial dark).
    """

    if wx.Platform != "__WXMSW__":
        return
    if getattr(listctrl, "_headerDarkened", False):
        return

    try:
        import ctypes

        c_void_p = ctypes.c_void_p
        c_uint = ctypes.c_uint
        c_int = ctypes.c_int
        c_ssize_t = ctypes.c_ssize_t
        c_size_t = ctypes.c_size_t

        windll = getattr(ctypes, "WinDLL", None)
        winfunctype = getattr(ctypes, "WINFUNCTYPE", None)
        if windll is None or winfunctype is None:
            return

        user32 = windll("user32", use_last_error=True)
        gdi32 = windll("gdi32", use_last_error=True)
        comctl32 = windll("comctl32", use_last_error=True)

        # Locate the header child of the list control.
        send = user32.SendMessageW
        send.restype = c_ssize_t
        send.argtypes = [c_void_p, c_uint, c_size_t, c_void_p]
        LVM_GETHEADER = 0x1000 + 31
        header = send(listctrl.GetHandle(), LVM_GETHEADER, 0, None)
        if not header:
            return

        # ctypes structures (basic types only, so the module stays importable off
        # Windows -- this code only ever runs under __WXMSW__).
        class _RECT(ctypes.Structure):
            _fields_ = [
                ("left", c_int),
                ("top", c_int),
                ("right", c_int),
                ("bottom", c_int),
            ]

        class _PAINTSTRUCT(ctypes.Structure):
            _fields_ = [
                ("hdc", c_void_p),
                ("fErase", c_int),
                ("rcPaint", _RECT),
                ("fRestore", c_int),
                ("fIncUpdate", c_int),
                ("rgbReserved", ctypes.c_byte * 32),
            ]

        class _HDITEM(ctypes.Structure):
            _fields_ = [
                ("mask", c_uint),
                ("cxy", c_int),
                ("pszText", ctypes.c_wchar_p),
                ("hbm", c_void_p),
                ("cchTextMax", c_int),
                ("fmt", c_int),
                ("lParam", c_ssize_t),
                ("iImage", c_int),
                ("iOrder", c_int),
                ("type", c_uint),
                ("pvFilter", c_void_p),
                ("state", c_uint),
            ]

        # GDI / user32 signatures (set so handles are not truncated on Win64).
        gdi32.CreateSolidBrush.restype = c_void_p
        gdi32.CreateSolidBrush.argtypes = [c_uint]
        gdi32.DeleteObject.argtypes = [c_void_p]
        gdi32.SelectObject.restype = c_void_p
        gdi32.SelectObject.argtypes = [c_void_p, c_void_p]
        gdi32.SetBkMode.argtypes = [c_void_p, c_int]
        gdi32.SetTextColor.argtypes = [c_void_p, c_uint]
        user32.BeginPaint.restype = c_void_p
        user32.BeginPaint.argtypes = [c_void_p, c_void_p]
        user32.EndPaint.argtypes = [c_void_p, c_void_p]
        user32.GetClientRect.argtypes = [c_void_p, c_void_p]
        user32.FillRect.argtypes = [c_void_p, c_void_p, c_void_p]
        user32.DrawTextW.argtypes = [c_void_p, ctypes.c_wchar_p, c_int, c_void_p, c_uint]
        user32.InvalidateRect.argtypes = [c_void_p, c_void_p, c_int]

        comctl32.DefSubclassProc.restype = c_ssize_t
        comctl32.DefSubclassProc.argtypes = [c_void_p, c_uint, c_size_t, c_ssize_t]
        comctl32.SetWindowSubclass.restype = c_int
        comctl32.RemoveWindowSubclass.restype = c_int

        WM_PAINT = 0x000F
        WM_NCDESTROY = 0x0082
        WM_GETFONT = 0x0031
        HDM_GETITEMCOUNT = 0x1200
        HDM_GETITEMRECT = 0x1200 + 7
        HDM_GETITEMW = 0x1200 + 11
        HDI_TEXT = 0x0002
        HDI_FORMAT = 0x0004
        HDF_JUSTIFY = 0x0003  # mask: 0 left, 1 right, 2 centre
        DT_NOPREFIX = 0x0800
        DT_SINGLELINE = 0x0020
        DT_VCENTER = 0x0004
        DT_RIGHT = 0x0002
        DT_CENTER = 0x0001
        DT_END_ELLIPSIS = 0x8000
        SUBCLASS_ID = 1

        SUBCLASSPROC = winfunctype(
            c_ssize_t, c_void_p, c_uint, c_size_t, c_ssize_t, c_size_t, c_size_t
        )

        def _paint(hwnd):
            ps = _PAINTSTRUCT()
            hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
            try:
                rc = _RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rc))
                bg = gdi32.CreateSolidBrush(_HDR_BG)
                user32.FillRect(hdc, ctypes.byref(rc), bg)
                gdi32.DeleteObject(bg)

                hfont = send(hwnd, WM_GETFONT, 0, None)
                old_font = (
                    gdi32.SelectObject(hdc, c_void_p(hfont)) if hfont else None
                )
                gdi32.SetBkMode(hdc, 1)  # TRANSPARENT
                gdi32.SetTextColor(hdc, _HDR_FG)

                sep = gdi32.CreateSolidBrush(_HDR_SEP)
                count = send(hwnd, HDM_GETITEMCOUNT, 0, None)
                for i in range(max(0, int(count))):
                    item_rc = _RECT()
                    send(hwnd, HDM_GETITEMRECT, i, ctypes.byref(item_rc))

                    buf = ctypes.create_unicode_buffer(260)
                    hdi = _HDITEM()
                    hdi.mask = HDI_TEXT | HDI_FORMAT
                    hdi.pszText = ctypes.cast(buf, ctypes.c_wchar_p)
                    hdi.cchTextMax = 260
                    send(hwnd, HDM_GETITEMW, i, ctypes.byref(hdi))

                    # 1px separator on the right edge of each cell.
                    sep_rc = _RECT()
                    sep_rc.left = item_rc.right - 1
                    sep_rc.top = item_rc.top
                    sep_rc.right = item_rc.right
                    sep_rc.bottom = item_rc.bottom
                    user32.FillRect(hdc, ctypes.byref(sep_rc), sep)

                    txt_rc = _RECT()
                    txt_rc.left = item_rc.left + 6
                    txt_rc.top = item_rc.top
                    txt_rc.right = item_rc.right - 6
                    txt_rc.bottom = item_rc.bottom
                    flags = (
                        DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX
                    )
                    justify = hdi.fmt & HDF_JUSTIFY
                    if justify == 1:
                        flags |= DT_RIGHT
                    elif justify == 2:
                        flags |= DT_CENTER
                    user32.DrawTextW(hdc, buf, -1, ctypes.byref(txt_rc), flags)
                gdi32.DeleteObject(sep)
                if old_font:
                    gdi32.SelectObject(hdc, old_font)
            finally:
                user32.EndPaint(hwnd, ctypes.byref(ps))

        def _proc(hwnd, msg, wparam, lparam, uid, refdata):
            try:
                if msg == WM_PAINT:
                    _paint(hwnd)
                    return 0
                if msg == WM_NCDESTROY:
                    comctl32.RemoveWindowSubclass(
                        c_void_p(hwnd), subclass_proc, SUBCLASS_ID
                    )
            except Exception:
                pass
            return comctl32.DefSubclassProc(c_void_p(hwnd), msg, wparam, lparam)

        subclass_proc = SUBCLASSPROC(_proc)
        comctl32.SetWindowSubclass.argtypes = [
            c_void_p,
            SUBCLASSPROC,
            c_size_t,
            c_size_t,
        ]
        if comctl32.SetWindowSubclass(
            c_void_p(header), subclass_proc, SUBCLASS_ID, 0
        ):
            # Keep the callback (and the list's reference) alive.
            _header_subclass_procs.append(subclass_proc)
            listctrl._headerSubclassProc = subclass_proc
            listctrl._headerDarkened = True
            user32.InvalidateRect(c_void_p(header), None, 1)
        else:
            # Subclassing unavailable: at least disable the light visual style so
            # the SetHeaderAttr colour paints behind the labels (partial dark).
            _setHwndTheme(header, "", "")
    except Exception:
        pass


def _undarkenWindowsListHeader(listctrl):
    """Undo _darkenWindowsListHeader so the header paints itself again.

    Needed only when the system switches back to light while the app is
    running: the owner-draw subclass installed above paints dark
    unconditionally, so it has to come off rather than be recoloured.  No-op
    off Windows, on a list that was never darkened, or on any failure.
    """

    if wx.Platform != "__WXMSW__":
        return

    subclass_proc = getattr(listctrl, "_headerSubclassProc", None)
    if subclass_proc is None:
        listctrl._headerDarkened = False
        return

    try:
        import ctypes

        c_void_p = ctypes.c_void_p
        c_uint = ctypes.c_uint
        c_int = ctypes.c_int
        c_ssize_t = ctypes.c_ssize_t
        c_size_t = ctypes.c_size_t

        windll = getattr(ctypes, "WinDLL", None)
        if windll is None:
            return

        user32 = windll("user32", use_last_error=True)
        comctl32 = windll("comctl32", use_last_error=True)

        send = user32.SendMessageW
        send.restype = c_ssize_t
        send.argtypes = [c_void_p, c_uint, c_size_t, c_void_p]
        LVM_GETHEADER = 0x1000 + 31
        SUBCLASS_ID = 1

        header = send(listctrl.GetHandle(), LVM_GETHEADER, 0, None)
        if not header:
            return

        comctl32.RemoveWindowSubclass.restype = c_int
        comctl32.RemoveWindowSubclass.argtypes = [
            c_void_p,
            type(subclass_proc),
            c_size_t,
        ]
        comctl32.RemoveWindowSubclass(
            c_void_p(header), subclass_proc, SUBCLASS_ID
        )

        # Restore the native visual style in case the subclass never took and
        # _darkenWindowsListHeader fell back to switching it off.
        _setHwndTheme(header, "Header", None)

        user32.InvalidateRect.argtypes = [c_void_p, c_void_p, c_int]
        user32.InvalidateRect(c_void_p(header), None, 1)
    except Exception:
        pass
    finally:
        try:
            _header_subclass_procs.remove(subclass_proc)
        except ValueError:
            pass
        listctrl._headerSubclassProc = None
        listctrl._headerDarkened = False


def applyThemeToWindow(window, notify=False):
    """Apply the app's own theme colours to *window* and all its children.

    wxWidgets 3.3 themes every standard control by itself once
    wxApp.MSWEnableDarkMode() has run (see appInit()), so all that is left here
    is the drawing wx cannot know about: the alternating row colours a
    sortListCtrl paints from its own item attributes and the image-tiled
    controlbars.  Call after the window's GUI has been fully constructed.

    With *notify* set, each window that defines an ``onThemeChanged()`` hook is
    asked to re-theme whatever only it knows about (grid cells, generated
    bullet bitmaps, ...).  That is reserved for a live light/dark switch: at
    construction time the panel has just drawn itself in the right colours
    anyway, and re-running the hook there would repopulate it for nothing.
    """

    def _recurse(w):
        if isinstance(w, (sortListCtrl, bgrPanel)):
            w.applyTheme()
        if notify:
            hook = getattr(w, "onThemeChanged", None)
            if callable(hook):
                # One panel with a broken hook must not leave every window
                # after it in the walk stranded in the old theme.
                try:
                    hook()
                except Exception:
                    pass
        for child in w.GetChildren():
            # a tool frame is a child of the main frame but is themed as a
            # top-level window in its own right, so it is not descended into
            # here (see refreshTheme)
            if not isinstance(child, wx.TopLevelWindow):
                _recurse(child)

    _recurse(window)
    window.Refresh()


def applyDarkMode(window):
    """Apply the current theme to a freshly built top-level *window*.

    Kept as the single entry point every tool frame and dialog calls, even
    though wxWidgets 3.3 now does the bulk of the work itself.
    """
    applyThemeToWindow(window)


def invertColour(colour):
    """Return the photographic negative of an RGB (or RGBA) colour.

    Any alpha component is carried through untouched, and the sequence type is
    preserved so a document's colour stays the list the rest of the code
    expects.
    """

    inverted = [255 - int(component) for component in colour[:3]]
    inverted.extend(colour[3:])

    if isinstance(colour, tuple):
        return tuple(inverted)

    return inverted


def readableOn(colour):
    """Black or white, whichever stays readable on the given background.

    Used instead of a fixed text colour wherever a cell carries a colour of its
    own (a match highlight, a document colour), so the same cell works in both
    themes and no highlight can end up light-on-light.
    """

    if not isinstance(colour, wx.Colour):
        colour = wx.Colour(*colour)

    if not colour.IsOk():
        return wx.BLACK

    luminance = 0.299 * colour.Red() + 0.587 * colour.Green() + 0.114 * colour.Blue()

    return wx.BLACK if luminance > 140 else wx.WHITE


def themedPlotColour(colour):
    """Adapt a plot content *colour*, chosen for a white canvas, to the theme.

    Dark mode inverts it so it keeps the same contrast against the dark canvas.
    Since the inversion is its own opposite, a colour already stored in its
    dark form inverts straight back to the light one, which is what lets a live
    switch flip the documents' colours in either direction (see
    mainFrame.onThemeChanged).
    """

    if images.is_dark_mode():
        return invertColour(colour)

    return colour


def applyGridTheme(grid):
    """Colour a wx.grid.Grid for the current system theme.

    wxGrid paints its cells and labels itself and takes no notice of the system
    colours, so both themes have to be spelled out.  Only the defaults are set:
    cells given a colour of their own when the grid was filled (a document
    colour, a match highlight) keep it.
    """

    if images.is_dark_mode():
        cell_bg = wx.Colour(30, 30, 30)
        cell_fg = wx.Colour(220, 220, 220)
        label_bg = wx.Colour(45, 45, 45)
        grid_line = wx.Colour(70, 70, 70)
    else:
        cell_bg = wx.WHITE
        cell_fg = wx.BLACK
        label_bg = wx.Colour(245, 245, 245)
        grid_line = wx.Colour(220, 220, 220)

    grid.SetLabelBackgroundColour(label_bg)
    grid.SetLabelTextColour(cell_fg)
    grid.SetDefaultCellBackgroundColour(cell_bg)
    grid.SetDefaultCellTextColour(cell_fg)
    grid.EnableGridLines(True)
    grid.SetGridLineColour(grid_line)


# Theme the app was last seen in, so that the stream of
# wxEVT_SYS_COLOUR_CHANGED events GTK emits for unrelated style changes does
# not trigger a full (and visible) rebuild every time.
_currentDarkMode = None


def watchThemeChanges(window):
    """Make *window* the app's watchdog for live light/dark switches.

    wx delivers wxEVT_SYS_COLOUR_CHANGED to the top-level windows and on down
    through their children, so binding the main frame alone is enough to hear
    about the switch; refreshTheme() then re-themes every window in the app.
    """

    global _currentDarkMode

    _currentDarkMode = images.is_dark_mode()
    window.Bind(wx.EVT_SYS_COLOUR_CHANGED, _onSysColourChanged)


def _onSysColourChanged(evt):
    """Rebuild the app's theme if the light/dark setting actually flipped."""

    global _currentDarkMode

    evt.Skip()

    dark = images.is_dark_mode()
    if dark == _currentDarkMode:
        return

    _currentDarkMode = dark
    refreshTheme()


def _logicalSize(bitmap):
    """A bitmap's size in logical (unscaled) units.

    On wxMSW the icons are HiDPI-tagged (see images._scale_bitmap), so a 2x
    icon measures 44x44 pixels but only 22x22 logical units.  Bucketing the
    index by the logical size is what lets a widget's bitmap and the images.lib
    bitmap it came from meet even when one of them has been resolved out of a
    wxBitmapBundle at a different pixel density (see _bundleKey).
    """

    try:
        scale = bitmap.GetScaleFactor()
    except Exception:
        scale = 1.0

    if not scale:
        scale = 1.0

    return (round(bitmap.GetWidth() / scale), round(bitmap.GetHeight() / scale))


def _bitmapIndex(items):
    """Index (key, bitmap) pairs by logical size for _bitmapKey lookups."""

    index = {}
    for key, value in items:
        if isinstance(value, wx.Bitmap) and value.IsOk():
            index.setdefault(_logicalSize(value), []).append((key, value))

    return index


def _bitmapKey(index, bitmap):
    """Return the images.lib key *bitmap* was taken from, or None.

    wx.Bitmap copies share their reference-counted data, so IsSameAs() still
    recognises the bitmap a widget was handed even though GetBitmap() returns a
    fresh Python wrapper each time.  The index buckets by size first so that
    each lookup only compares against bitmaps that could possibly match.
    """

    if not isinstance(bitmap, wx.Bitmap) or not bitmap.IsOk():
        return None

    for key, candidate in index.get(_logicalSize(bitmap), ()):
        if bitmap.IsSameAs(candidate):
            return key

    return None


def _bundleKey(index, bundle):
    """Return the images.lib key *bundle* was built from, or None.

    Widgets that store their icon as a wxBitmapBundle cannot be matched by
    _bitmapKey: asking such a bundle for a plain bitmap resolves it at the
    bundle's default (logical) size, which on wxMSW means the HiDPI-tagged icon
    is *rescaled* into a brand new bitmap -- a different size and different
    reference-counted data from the images.lib entry it was made from, so no
    identity test can ever match it.  Asking the bundle for its own source size
    instead hands the original bitmap straight back, which does match.
    """

    if bundle is None or not bundle.IsOk():
        return None

    for key, candidate in index.get(tuple(bundle.GetDefaultSize()), ()):
        if bundle.GetBitmap(candidate.GetSize()).IsSameAs(candidate):
            return key

    return None


def _reloadBitmaps(window, index):
    """Swap every bitmap taken from images.lib for its rebuilt version.

    *index* maps the pre-reload bitmaps back to their images.lib keys (see
    images.reloadImages), which is what lets this walk work without every call
    site having to remember which icon it asked for.
    """

    def _rebuilt(bitmap, bundle=None):
        key = _bitmapKey(index, bitmap)
        if key is None:
            key = _bundleKey(index, bundle)
        return images.lib.get(key) if key is not None else None

    def _recurse(w):
        if isinstance(w, wx.ToolBar):
            for pos in range(w.GetToolsCount()):
                tool = w.GetToolByPos(pos)
                if tool is None:
                    continue
                # a tool keeps its icon as a bundle, so the plain bitmap alone
                # does not identify it -- see _bundleKey
                getBundle = getattr(tool, "GetNormalBitmapBundle", None)
                bitmap = _rebuilt(
                    tool.GetNormalBitmap(),
                    getBundle() if getBundle is not None else None,
                )
                if bitmap is not None:
                    w.SetToolNormalBitmap(tool.GetId(), bitmap)
        elif isinstance(w, wx.StaticBitmap):
            bitmap = _rebuilt(w.GetBitmap())
            if bitmap is not None:
                w.SetBitmap(bitmap)
        elif isinstance(w, wx.AnyButton):
            bitmap = _rebuilt(w.GetBitmapLabel())
            if bitmap is not None:
                w.SetBitmapLabel(bitmap)

        # A bgrPanel tiles its background bitmap itself, so it holds the only
        # reference wx knows nothing about.
        if isinstance(w, bgrPanel):
            bitmap = _rebuilt(w.image)
            if bitmap is not None:
                w.image = bitmap

        for child in w.GetChildren():
            # child tool frames come round again as top-level windows
            if not isinstance(child, wx.TopLevelWindow):
                _recurse(child)

    _recurse(window)


def refreshTheme():
    """Re-theme the whole app after the system switched between light and dark.

    The icons are baked for one theme (see images.reloadImages), so they are
    built again and every widget still displaying an old one is handed its
    replacement; then each window re-applies the colours it paints itself.
    """

    # Each plot canvas re-themes itself from its own wxEVT_SYS_COLOUR_CHANGED
    # handler, but plot_objects caches the dark-mode flag for the process
    # lifetime, so drop it here too: anything built during this rebuild has to
    # see the new theme regardless of which handler ran first.
    try:
        from mspy import plot_objects

        plot_objects.invalidate_dark_mode_cache()
    except Exception:
        pass

    index = _bitmapIndex(images.reloadImages())

    # (the wxPython stub wrongly declares this module function as a method)
    windows = list(wx.GetTopLevelWindows())  # type: ignore[call-arg]

    # The main frame owns the document colours, which it flips in its own
    # onThemeChanged hook; every tool window that draws with them has to be
    # re-themed after that, so it goes first (sort is stable, so the rest keep
    # their order).
    # (GetTopWindow lives on wx.App, which the stubs do not narrow GetApp to)
    getTopWindow = getattr(wx.GetApp(), "GetTopWindow", None)
    topWindow = getTopWindow() if getTopWindow is not None else None
    windows.sort(key=lambda window: window is not topWindow)

    for window in windows:
        try:
            _reloadBitmaps(window, index)
            applyThemeToWindow(window, notify=True)
            window.Layout()
        except RuntimeError:
            # Window deleted on the C++ side while the walk was running.
            continue


def fitChoice(choice, min_width=None, extra_padding=35):
    """Fit wx.Choice control width to the longest available label."""

    best_width = 0
    dc = wx.ClientDC(choice)
    dc.SetFont(choice.GetFont())

    for i in range(choice.GetCount()):
        text_width, _ = dc.GetTextExtent(choice.GetString(i))
        best_width = max(best_width, text_width)

    best_width += int(extra_padding)
    if min_width is not None:
        best_width = max(best_width, int(min_width))

    _, current_height = choice.GetSize()
    best_height = choice.GetBestSize().GetHeight()
    if current_height <= 0:
        current_height = best_height
    else:
        # Never allow a forced small height to clip native choice text rendering.
        current_height = max(current_height, best_height)

    choice.SetMinSize(wx.Size(best_width, current_height))


# ----


# MODIFIED WX OBJECTS
# -------------------


class menuTipWindow(wx.PopupWindow):
    """Lightweight tooltip-style bubble shown next to the cursor."""

    def __init__(self, parent, text):
        wx.PopupWindow.__init__(self, parent, flags=wx.BORDER_SIMPLE)

        if images.is_dark_mode():
            bg = wx.Colour(60, 60, 60)
            fg = wx.Colour(230, 230, 230)
        else:
            bg = wx.Colour(255, 255, 225)
            fg = wx.Colour(0, 0, 0)

        self.SetBackgroundColour(bg)
        label = wx.StaticText(self, -1, text)
        label.SetBackgroundColour(bg)
        label.SetForegroundColour(fg)

        pad = max(1, _scale_int(4))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(label, 0, wx.ALL, pad)
        self.SetSizerAndFit(sizer)


class bgrPanel(wx.Panel):
    """Simple panel with image background.

    In dark mode the light background sprite is dropped for a flat dark fill.
    Both variants are driven from the same handlers rather than from a
    different set of bindings each, so that a live light/dark switch is just a
    call to applyTheme() -- see mwx.refreshTheme().
    """

    _DARK_BG = wx.Colour(30, 30, 30)

    def __init__(self, parent, id, image, size=(-1, -1)):
        wx.Panel.__init__(self, parent, id, size=size)
        self.SetMinSize(size)

        self.image = image
        self._dark_mode = None

        self.Bind(wx.EVT_SIZE, self._onSize)
        self.Bind(wx.EVT_PAINT, self._onPaint)

        self.applyTheme()

    # ----

    def applyTheme(self):
        """Follow the current system theme."""

        self._dark_mode = images.is_dark_mode()

        if self._dark_mode:
            self.SetBackgroundColour(self._DARK_BG)
            self.SetBackgroundStyle(wx.BG_STYLE_COLOUR)
        else:
            # the tiled sprite is painted over whatever is there, so the
            # background goes back to being erased by the toolkit
            self.SetBackgroundColour(wx.NullColour)
            self.SetBackgroundStyle(wx.BG_STYLE_ERASE)

        self._propagateBg()
        self.Refresh()

    # ----

    def _onSize(self, event):
        """Re-propagate the panel background to the children on resize."""
        event.Skip()
        self._propagateBg()

    def _propagateBg(self):
        """Match the BitmapButton children's background to the panel.

        wxGTK draws a borderless BitmapButton on its own background colour, so
        without this the buttons sit in light blocks on the dark bar.  In light
        mode they go back to inheriting, which lets the tiled sprite show
        through.
        """
        colour = self.GetBackgroundColour() if self._dark_mode else wx.NullColour
        for child in self.GetChildren():
            if isinstance(child, wx.BitmapButton):
                child.SetBackgroundColour(colour)

    # ----

    def _onPaint(self, event=None):

        # create paint surface
        dc = wx.PaintDC(self)

        # dark mode has no background sprite, just the flat fill; the DC still
        # has to be created (and the region validated) or MSW repaints forever
        if self._dark_mode:
            dc.SetBackground(wx.Brush(self.GetBackgroundColour(), wx.BRUSHSTYLE_SOLID))
            dc.Clear()
            return

        # tile/wallpaper the image across the canvas
        for x in range(0, self.GetSize()[0], self.image.GetWidth()):
            dc.DrawBitmap(self.image, x, 0, True)

    # ----


class sortListCtrl(wx.ListCtrl):
    """ListCtrl with automatic sorter."""

    def __init__(
        self,
        parent,
        id=-1,
        pos=wx.DefaultPosition,
        size=wx.DefaultSize,
        style=wx.LC_REPORT,
    ):
        wx.ListCtrl.__init__(self, parent, id, pos, size, style)

        self._data: list[list[object]] | None = None
        self._currentColumn = 0
        self._currentDirection = LISTCTRL_SORT
        self._secondarySortColumn = None

        self._defaultColour = self.GetBackgroundColour()
        self._altColour = self.GetBackgroundColour()
        self._currentAttr = wx.ItemAttr()

        self._getItemTextFn = None
        self._getItemAttrFn = None

        # set events
        self.Bind(wx.EVT_LIST_COL_CLICK, self._onColClick, self)

    # ----

    def OnGetItemText(self, item, column):
        """Get text for selected cell."""

        if self._getItemTextFn is not None:
            return self._getItemTextFn(item, column)

        if self._data is None:
            return ""

        return str(self._data[item][column])

    # ----

    def OnGetItemAttr(self, item):
        """Get attributes for selected cell."""

        # get user defined attr
        attr = None
        if self._getItemAttrFn is not None:
            attr = self._getItemAttrFn(item)

        # set background colour
        if attr and attr.HasBackgroundColour():
            self._currentAttr.SetBackgroundColour(attr.GetBackgroundColour())
        elif item % 2:
            self._currentAttr.SetBackgroundColour(self._defaultColour)
        else:
            self._currentAttr.SetBackgroundColour(self._altColour)

        # set text colour
        if attr:
            self._currentAttr.SetTextColour(attr.GetTextColour())

        # set font
        if attr:
            self._currentAttr.SetFont(attr.GetFont())

        return self._currentAttr

    # ----

    def OnGetItemImage(self, item):
        return -1

    # ----

    def _onColClick(self, evt):
        """Sort data by this column."""

        # check data
        if not self._data:
            return

        # get selected column
        oldCol = self._currentColumn
        newCol = evt.GetColumn()

        # update direction flag
        if oldCol == newCol:
            direction = -1 * self._currentDirection
        else:
            direction = LISTCTRL_SORT

        # sort
        self._sort(newCol, direction)
        evt.Skip()

    # ----

    def _sort(self, col, direction):
        """Sort list."""

        # unselect all items
        self.unselectAll()

        # set new flags
        self._currentColumn = min(col, self.GetColumnCount() - 1)
        self._currentDirection = direction

        # sort data
        if self._data is None:
            return

        if self.IsVirtual():
            self._data.sort(key=functools.cmp_to_key(self._sortItems))
            self.Refresh()
        else:
            self.SortItems(self._sortData)
            self.updateItemsBackground()

    # ----

    def _sortData(self, item1, item2):
        """Sort data."""
        if self._data is None:
            return 0
        comp = self._sortItems(self._data[item1], self._data[item2])
        if comp == 0:
            return 1 if item1 > item2 else -1
        return comp

    # ----

    def _sortItems(self, item1, item2):
        """Sort items."""

        comp = cmp(item1[self._currentColumn], item2[self._currentColumn])
        if comp == 0 and self._secondarySortColumn is not None:
            comp = cmp(
                item1[self._secondarySortColumn], item2[self._secondarySortColumn]
            )

        return comp * self._currentDirection

    # ----

    def _columnSorter(self, key1, key2):
        """Sort data."""

        # check data
        if not self._data:
            return self._currentDirection

        # get values
        item1 = self._data[key1][self._currentColumn]
        item2 = self._data[key2][self._currentColumn]

        # compare values
        comp = cmp(item1, item2)
        if comp == 0 and self._secondarySortColumn is not None:
            item1 = self._data[key1][self._secondarySortColumn]
            item2 = self._data[key2][self._secondarySortColumn]
            comp = cmp(item1, item2)

        # set direction
        comp *= self._currentDirection

        return comp

    # ----

    def setItemTextFn(self, fn):
        """Set OnGetItemText callback."""
        self._getItemTextFn = fn

    # ----

    def setItemAttrFn(self, fn):
        """Set OnGetItemAttr callback."""
        self._getItemAttrFn = fn

    # ----

    def setSecondarySortColumn(self, col):
        """Set secondary column to sort by."""
        self._secondarySortColumn = col

    # ----

    def setDataMap(self, data):
        """Set data."""
        self._data = data

    # ----

    def setDefaultColour(self, colour):
        """Set default (odd-row) background colour."""

        if colour:
            self._defaultColour = colour
        else:
            self._defaultColour = self.GetBackgroundColour()

    # ----

    def setAltColour(self, colour):
        """Set alternate background colour."""

        if colour:
            self._altColour = colour
        else:
            self._altColour = self._defaultColour

    # ----

    def applyTheme(self):
        """Match the rows, text and column header to the current system theme.

        wxWidgets 3.3 themes the list control itself, but the alternating row
        colours are painted by this class from its own item attributes, so they
        still have to be told what light and dark look like.  Both directions
        are handled so that a live switch can simply call this again.
        """

        dark = images.is_dark_mode()

        # An attribute with no colours of its own leaves the header to the
        # platform, which is what light mode wants.
        header_attr = wx.ItemAttr()

        if dark:
            self.SetBackgroundColour(_DARK_BG)
            self.SetTextColour(_DARK_FG)
            self.setDefaultColour(_DARK_BG)
            self.setAltColour(wx.Colour(40, 40, 40))
            header_attr.SetBackgroundColour(wx.Colour(45, 45, 45))
            header_attr.SetTextColour(_DARK_FG)
        else:
            # Hand the colours back to the toolkit rather than naming the light
            # ones, so this does not depend on wx having already refreshed its
            # system-colour cache when the switch is handled.
            self.SetBackgroundColour(wx.NullColour)
            self.SetTextColour(wx.NullColour)
            # None means "whatever the control's own background is", which is
            # what the light theme wants everywhere the platform has no
            # alternating row colour of its own (LISTCTRL_ALTCOLOUR is only set
            # on wxOSX).
            self.setDefaultColour(None)
            self.setAltColour(LISTCTRL_ALTCOLOUR)

        try:
            self.SetHeaderAttr(header_attr)
        except Exception:
            pass

        # The native MSW header is a separate SysHeader32 child, drawn by hand
        # (see _darkenWindowsListHeader) rather than from the attr above.
        if dark:
            _darkenWindowsListHeader(self)
        else:
            _undarkenWindowsListHeader(self)

        # A virtual list gets its row colours from OnGetItemAttr on every
        # repaint; a real one keeps them per item and has to be told.  Forced,
        # because switching back to light leaves the rows carrying the dark
        # colours of the theme before it, which the usual skip would not clear.
        if not self.IsVirtual():
            self.updateItemsBackground(force=True)

        self.Refresh()

    # ----

    def getSelected(self):
        """Return indexes of selected items."""

        selected = []

        i = -1
        while True:
            i = self.GetNextItem(i, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
            if i == -1:
                break
            else:
                selected.append(i)

        selected.sort()
        return selected

    # ----

    def sort(self, col=None):
        """Sort by last or selected column."""

        # get column and direction
        direction = self._currentDirection
        if col is None:
            col = self._currentColumn
        else:
            if self._currentColumn != col:
                direction = LISTCTRL_SORT

        # sort
        self._sort(col, direction)

    # ----

    def deleteColumns(self):
        """Delete all columns."""

        self._currentColumn = 0
        while self.GetColumnCount():
            self.DeleteColumn(0)

    # ----

    def unselectAll(self):
        """Unselect all items."""

        i = -1
        while True:
            i = self.GetNextItem(i, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
            self.SetItemState(i, 0, wx.LIST_STATE_SELECTED)
            if i == -1:
                break

    # ----

    def updateItemsBackground(self, force=False):
        """Update item background colours.

        With both colours the same there is nothing to alternate and the rows
        can simply use the control's own background -- unless *force* is set,
        which is how a theme switch clears the colours the previous theme left
        on them.
        """

        # check colours
        if self._defaultColour == self._altColour and not force:
            return

        # update each row
        for row in range(self.GetItemCount()):
            if row % 2:
                self.SetItemBackgroundColour(row, self._altColour)
            else:
                self.SetItemBackgroundColour(row, self._defaultColour)

    # ----

    def copyToClipboard(self, selected=False):
        """Copy current data to clipboard."""

        buff = ""

        # get selected only
        if selected:
            for row in self.getSelected():
                line = ""
                for col in range(self.GetColumnCount()):
                    item = self.GetItem(row, col)
                    line += item.GetText() + "\t"
                buff += "%s\n" % (line.rstrip())

        # get all
        else:
            for row in range(self.GetItemCount()):
                line = ""
                for col in range(self.GetColumnCount()):
                    item = self.GetItem(row, col)
                    line += item.GetText() + "\t"
                buff += "%s\n" % (line.rstrip())

        # make text object for data
        obj = wx.TextDataObject()
        obj.SetText(buff.rstrip())

        # paste to clipboard
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(obj)
            wx.TheClipboard.Close()

    # ----


class scrollTextCtrl(wx.TextCtrl):
    """TextCtrl with scoll."""

    def __init__(
        self,
        parent,
        id=-1,
        value="",
        step=None,
        multiplier=None,
        digits=0,
        limits=(None, None),
        pos=wx.DefaultPosition,
        size=wx.DefaultSize,
        style=0,
        validator=wx.DefaultValidator,
    ):
        wx.TextCtrl.__init__(self, parent, id, value, pos, size, style, validator)

        self.Bind(wx.EVT_KEY_DOWN, self._onKey)
        if wx.Platform == "__WXMAC__":
            self.Bind(wx.EVT_MOUSEWHEEL, self._onScroll)

        self._digits = digits
        self._scrollStep = step
        self._scrollMultiplier = multiplier
        self._min = limits[0]
        self._max = limits[1]

    # ----

    def _onScroll(self, evt):
        """Increase or decrease value while scrolling."""

        # set new value
        self._setNewValue(evt.GetWheelRotation() * SCROLL_DIRECTION, evt.AltDown())

    # ----

    def _onKey(self, evt):
        """Use up and down keys."""

        # get key
        key = evt.GetKeyCode()

        # get direction
        if key == wx.WXK_UP:
            direction = 1
        elif key == wx.WXK_DOWN:
            direction = -1
        else:
            evt.Skip()
            return

        # set new value
        self._setNewValue(direction, evt.AltDown())

    # ----

    def _setNewValue(self, direction, precise):
        """Calculate and set new value."""

        # get and check current value
        old = self.GetValue()
        try:
            old = float(old)
        except Exception:
            wx.Bell()
            return

        # make new value
        if self._scrollStep:
            new = old + (self._scrollStep * direction)
        elif self._scrollMultiplier and precise:
            new = old + (old * self._scrollMultiplier * direction * 0.1)
        elif self._scrollMultiplier:
            new = old + (old * self._scrollMultiplier * direction)
        else:
            return

        # check limits
        if self._min is not None and new < self._min:
            new = self._min
        elif self._max is not None and new > self._max:
            new = self._max

        # format value
        if new > 10000 or new < -10000:
            format = "%0.1e"
        else:
            format = "%0." + repr(self._digits) + "f"
        new = format % new

        # set new value
        self.SetValue(new)

    # ----

    def setScrollStep(self, value):
        """Set scroll step."""
        self._scrollStep = value

    # ----

    def setScrollMultiplier(self, value):
        """Set scroll multiplier."""
        self._scrollMultiplier = value

    # ----

    def setMin(self, value):
        """Set minimum."""
        self._min = value

    # ----

    def setMax(self, value):
        """Set maximum."""
        self._max = value

    # ----

    def setDigits(self, value):
        """Set number of digits."""
        self._digits = value

    # ----


class formulaCtrl(wx.TextCtrl):
    """TextCtrl to molecular formulae."""

    def __init__(
        self,
        parent,
        id=-1,
        value="",
        pos=wx.DefaultPosition,
        size=wx.DefaultSize,
        style=0,
        validator=wx.DefaultValidator,
    ):
        wx.TextCtrl.__init__(self, parent, id, value, pos, size, style, validator)

        # Background restored once the formula parses again: the control's own
        # default, which wx already paints dark when the app is in dark mode.
        self._validColour = wx.NullColour

        self.Bind(wx.EVT_TEXT, self._onText)

    # ----

    def _onText(self, evt):
        """Check current formula."""
        evt.Skip()
        wx.CallAfter(self._checkFormula)

    # ----

    def _checkFormula(self):
        """Check current formula."""

        try:
            mspy.compound(self.GetValue())
            self.SetBackgroundColour(self._validColour)
        except Exception:
            self.SetBackgroundColour(wx.Colour(250, 100, 100))

        self.Refresh()

    # ----


class gauge(wx.Gauge):
    """Gauge."""

    def __init__(self, parent, id=-1, size=(-1, GAUGE_HEIGHT), style=wx.GA_HORIZONTAL):
        wx.Gauge.__init__(self, parent, id, size=wx.Size(*size), style=style)

    # ----

    def pulse(self):
        """Pulse gauge."""

        self.Pulse()
        try:
            wx.SafeYield()
        except Exception:
            pass
        time.sleep(0.05)

    # ----


class gaugePanel(wx.Dialog, MakeModalMixin):
    """Processing panel."""

    def __init__(self, parent, label, title="Progress..."):
        wx.Dialog.__init__(self, parent, -1, title, style=(wx.CAPTION | wx.STAY_ON_TOP))

        self.parent = parent
        self.label = label

        # make GUI
        panel = wx.Panel(self, -1)
        self.label = wx.StaticText(panel, -1, label)
        self.label.SetFont(wx.SMALL_FONT)
        self.gauge = wx.Gauge(panel, -1, size=wx.Size(250, GAUGE_HEIGHT))

        # pack elements
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.label, 0, wx.BOTTOM, 5)
        sizer.Add(self.gauge, 0, wx.EXPAND, 0)
        panel.SetSizer(sizer)

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        mainSizer.Add(panel, 0, wx.ALL, PANEL_SPACE_MAIN)

        self.Layout()
        mainSizer.Fit(self)
        self.SetSizer(mainSizer)
        try:
            wx.SafeYield()
        except Exception:
            pass

    # ----

    def setLabel(self, label):
        """Set new label."""

        self.label.SetLabel(label)
        try:
            wx.SafeYield()
        except Exception:
            pass

    # ----

    def pulse(self):
        """Pulse gauge."""

        self.gauge.Pulse()

        try:
            wx.SafeYield()
        except Exception:
            pass
        time.sleep(0.05)

    # ----

    def show(self):
        """Show panel."""

        self.Center()
        self.MakeModal(True)
        self.Show()

        try:
            wx.SafeYield()
        except Exception:
            pass

    # ----

    def close(self):
        """Hide panel"""

        self.MakeModal(False)
        self.Destroy()

    # ----


class validator(wx.PyValidator):
    """Text validator."""

    def __init__(self, flag):
        wx.Validator.__init__(self)
        self.flag = flag
        self.Bind(wx.EVT_CHAR, self.OnChar)

    # ----

    def Clone(self):
        return validator(self.flag)

    # ----

    def TransferToWindow(self):
        return True

    # ----

    def TransferFromWindow(self):
        return True

    # ----

    def OnChar(self, evt):
        key = evt.GetKeyCode()

        # define navigation keys
        navKeys = (
            wx.WXK_HOME,
            wx.WXK_LEFT,
            wx.WXK_UP,
            wx.WXK_END,
            wx.WXK_RIGHT,
            wx.WXK_DOWN,
            wx.WXK_NUMPAD_HOME,
            wx.WXK_NUMPAD_LEFT,
            wx.WXK_NUMPAD_UP,
            wx.WXK_NUMPAD_END,
            wx.WXK_NUMPAD_RIGHT,
            wx.WXK_NUMPAD_DOWN,
        )

        # navigation keys
        if key in navKeys or key < wx.WXK_SPACE or key == wx.WXK_DELETE:
            evt.Skip()
            return

        # copy
        elif key == 99 and evt.CmdDown():
            evt.Skip()
            return

        # paste
        elif key == 118 and evt.CmdDown():
            evt.Skip()
            return

        # illegal characters
        elif key > 255:
            return

        # int only
        elif self.flag == "int" and chr(key) in "-0123456789eE":
            evt.Skip()
            return

        # positive int only
        elif self.flag == "intPos" and chr(key) in "0123456789eE":
            evt.Skip()
            return

        # floats only
        elif self.flag == "float" and (chr(key) in "-0123456789.eE"):
            evt.Skip()
            return

        # positive floats only
        elif self.flag == "floatPos" and (chr(key) in "0123456789.eE"):
            evt.Skip()
            return

        # error
        else:
            wx.Bell()
            return

    # ----


class dlgMessage(wx.Dialog):
    """Base message dialog class."""

    def __init__(
        self,
        parent,
        title,
        message,
        buttons=None,
        style=wx.DEFAULT_DIALOG_STYLE,
    ):
        wx.Dialog.__init__(self, parent, -1, "", style=style)

        self.parent = parent
        self.title = title
        self.message = message
        self.buttons = buttons if buttons is not None else [(wx.ID_CANCEL, "OK", 80, True, 0)]

        # make GUI
        sizer = self.makeGUI()

        # fit layout
        self.Layout()
        sizer.Fit(self)
        self.SetSizer(sizer)
        self.SetMinSize(self.GetSize())
        self.Centre()

    # ----

    def makeGUI(self):
        """Make GUI elements."""

        # make icon
        icon = wx.StaticBitmap(self, -1, images.lib["iconDlg"])

        # make title
        title_label = wx.StaticText(self, -1, self.title)
        title_label.SetFont(
            wx.Font(
                NORMAL_FONT_SIZE,
                wx.FONTFAMILY_SWISS,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_BOLD,
            )
        )

        # make additional message
        message_label = wx.StaticText(self, -1, self.message)
        message_label.SetFont(wx.SMALL_FONT)

        # make buttons
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for item in self.buttons:
            button_butt = makeButton(self, item[0], item[1], item[2])
            button_butt.Bind(wx.EVT_BUTTON, self.onButton)
            buttons.Add(button_butt, 0, wx.RIGHT, display_scale.scale_metric(item[4], UI_SCALE))
            if item[3]:
                button_butt.SetDefault()
                button_butt.SetFocus()

        # pack elements
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(title_label, 0, wx.ALIGN_LEFT)
        sizer.Add(message_label, 0, wx.ALIGN_LEFT | wx.TOP, 10)
        sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.TOP, PANEL_SPACE_MAIN)

        mainSizer = wx.BoxSizer(wx.HORIZONTAL)
        mainSizer.Add(icon, 0, wx.TOP | wx.LEFT | wx.BOTTOM, PANEL_SPACE_MAIN)
        mainSizer.Add(
            sizer, 0, wx.ALIGN_BOTTOM | wx.ALIGN_LEFT | wx.ALL, PANEL_SPACE_MAIN
        )

        return mainSizer

    # ----

    def onButton(self, evt):
        """Return pressed button ID."""
        self.EndModal(evt.GetId())

    # ----


# HELPERS
# -------


def makeButton(parent, id, label, width=-1):
    """Create a button sized to fit its label and the UI scale.

    `width` is a design-width hint (in unscaled pixels); it is scaled by
    UI_SCALE but the button is never made narrower than its natural best width
    for the current font/DPI, so the label is not clipped on HiDPI displays.
    Pass width=-1 to size purely from the label.
    """

    button = wx.Button(parent, id, label)
    desired = display_scale.scale_metric(width, UI_SCALE)
    best = button.GetBestSize().width
    target = best if desired == -1 else max(desired, best)
    button.SetMinSize(wx.Size(target, -1))
    return button


def makeBitmapButton(parent, id=wx.ID_ANY, bitmap=wx.NullBitmap, *args, **kwargs):
    """Create a wx.BitmapButton from a bitmap.

    HiDPI sizing is handled at the source: images._scale_bitmap() tags scaled
    icons with the right scale factor on wxMSW so widgets render them at the
    correct logical size instead of re-upscaling by the monitor DPI. This
    wrapper just converts the bitmap to the wx.BitmapBundle that wx.BitmapButton
    expects (wx does this internally anyway) to satisfy the type checker.
    """

    bundle = (
        bitmap
        if isinstance(bitmap, wx.BitmapBundle)
        else wx.BitmapBundle.FromBitmap(bitmap)
    )
    return wx.BitmapButton(parent, id, bundle, *args, **kwargs)


def layout(parent, sizer):
    """Ensure correct panel layout - hack."""

    parent.SetMinSize((-1, -1))
    sizer.Fit(parent)
    parent.Layout()

    size = parent.GetSize()
    parent.SetSize((size[0] + 1, size[1] + 1))
    parent.SetSize(size)
    parent.SetMinSize(size)


# ----
