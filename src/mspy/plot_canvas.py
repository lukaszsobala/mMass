import time

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportGeneralTypeIssues=false, reportIndexIssue=false, reportOperatorIssue=false, reportOptionalSubscript=false

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
import numpy
from gui import display_scale


def _is_dark_mode():
    """Return True when the system colour theme has a dark window background."""

    # Ask wx first. Note that this deliberately does not use IsDark(): on MSW
    # that reports whether *this application* is in dark mode, which stays False
    # until wxApp.MSWEnableDarkMode() has been called, whereas IsSystemDark()
    # reports the system setting we actually want. Needs a live wx.App, so it is
    # unavailable when called during early module import -- hence the fallbacks.
    try:
        return bool(wx.SystemSettings.GetAppearance().IsSystemDark())
    except Exception:
        pass

    # Windows app theme setting is exposed in the registry.
    if wx.Platform == "__WXMSW__":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return int(value) == 0
        except Exception:
            pass

    # Fallback: infer from current window background colour.
    bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
    luminance = 0.299 * bg.Red() + 0.587 * bg.Green() + 0.114 * bg.Blue()
    return luminance < 128


# MAIN PLOT CANVAS OBJECT
# -----------------------


class canvas(wx.Window):
    """Plot canvas"""

    # extra room left beyond the outermost highlighted point when the view is
    # centred on an anchor (see ensureVisible)
    ANCHOR_MARGIN = 1.15

    def __init__(
        self, parent, id=-1, size=wx.DefaultSize, style=wx.DEFAULT_FRAME_STYLE, **attr
    ):
        wx.Window.__init__(self, parent, id, size=size, style=style)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        self.parent = parent
        self.SetBackgroundColour("white")

        # set default canvas params
        self.properties = {
            "isotopeDistance": 1.00287,
            "xLabel": "",
            "yLabel": "",
            "showGrid": True,
            "showMinorTicks": True,
            "showZero": False,
            "showLegend": False,
            "showXPosBar": False,
            "showYPosBar": False,
            "showGel": False,
            "showCurXPos": True,
            "showCurYPos": True,
            "showCurDistance": True,
            "showCurCharge": True,
            "showCurImage": False,
            "autoScaleY": True,
            "ySymmetry": False,
            "overlapLabels": True,
            "posBarSize": 6,
            "gelHeight": 13,
            "xPosDigits": 2,
            "yPosDigits": 0,
            "distanceDigits": 2,
            "xScrollFactor": 0.1,
            "xMoveFactor": 0.1,
            "xScaleFactor": 0.1,
            "yScaleFactor": 0.1,
            "maxZoom": 0.001,
            "zoomAxis": "xy",
            "checkLimits": True,
            "reverseScrolling": False,
            "reverseDrawing": False,
            "canvasColour": (255, 255, 255),
            "plotColour": (255, 255, 255),
            "axisColour": (0, 0, 0),
            "gridColour": (235, 235, 235),
            "highlightColour": (255, 0, 0),
            "zoomBoxColour": wx.TheColourDatabase.Find("sky blue"),
            "axisFont": wx.Font(
                10, wx.SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, 0
            ),
        }

        # apply the theme colours, then the caller's overrides on top
        self._callerProperties = dict(attr)
        self.applyThemeColours()

        # set default canvas params
        self.mouseFn = None
        self.mouseFnLMB = None
        self.mouseFnRMB = "zoom"
        self.mouseTracker = False

        self.currentObject = None
        self.currentCharge = 1
        self.currentIsotopes = []
        self.currentIsotopeLines = 0
        self.gelsCount = 0
        self.basePrinterScale = max(display_scale.get_ui_scale(), 1.0)
        # On-screen fonts are normally left at 1.0: the toolkit renders point
        # sizes at the system DPI, so scaling them by the UI factor (as the
        # drawings/pens are) would double-scale canvas labels. wxMSW is the
        # exception -- the canvas draws into an off-screen GDI buffer that is
        # NOT DPI-scaled, so its point-size fonts come out too small on HiDPI
        # and must track the drawing scale. GTK/cairo already device-scales the
        # buffer's text. Print/export paths override the font scale explicitly.
        if wx.Platform == "__WXMSW__":
            self.baseFontScale = self.basePrinterScale
        else:
            self.baseFontScale = 1.0
        self.printerScale = {
            "drawings": self.basePrinterScale,
            "fonts": self.baseFontScale,
        }
        self.viewMemory = [[], []]

        self.cursorPosition = [0, 0, 0, 0]
        self.cursorImage = wx.Cursor(wx.CURSOR_ARROW)
        self.draggingStart = False
        self.mouseEvent = False
        self.xPosBarBox = None
        self.yPosBarBox = None
        self.lastDraw = None
        self.pointScale = 1
        self.pointShift = 0
        self._last_draw_time = 0.0
        self._refresh_pending = False

        # set events
        self.Bind(wx.EVT_PAINT, self.onPaint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, self.onEraseBackground)
        self.Bind(wx.EVT_SIZE, self.onSize)
        self.Bind(wx.EVT_LEAVE_WINDOW, self.onLeave)
        self.Bind(wx.EVT_LEFT_DOWN, self.onLMD)
        self.Bind(wx.EVT_LEFT_UP, self.onLMU)
        self.Bind(wx.EVT_LEFT_DCLICK, self.onLMDC)
        self.Bind(wx.EVT_RIGHT_DOWN, self.onRMD)
        self.Bind(wx.EVT_RIGHT_UP, self.onRMU)
        self.Bind(wx.EVT_RIGHT_DCLICK, self.onRMDC)
        self.Bind(wx.EVT_MIDDLE_DOWN, self.onRMD)
        self.Bind(wx.EVT_MIDDLE_UP, self.onRMU)
        self.Bind(wx.EVT_MOTION, self.onMMotion)
        self.Bind(wx.EVT_MOUSEWHEEL, self.onMScroll)
        self.Bind(wx.EVT_KEY_DOWN, self.onChar)
        self.Bind(wx.EVT_SYS_COLOUR_CHANGED, self.onSysColourChanged)

        # initialize bitmap buffer and set initial size based on client size
        self.onSize(0)

    # ----

    def _contentScale(self):
        """Backend content-scale factor (2.0 on native Wayland @200%, else 1.0).

        GetContentScaleFactor reflects compositor surface scaling that wx/GTK
        applies transparently: on the native Wayland backend the whole window
        is rendered at this factor. It stays 1.0 on Windows and X11, where our
        own pixel scaling (see gui.display_scale) handles HiDPI instead, so the
        two mechanisms never compound.
        """

        try:
            scale = float(self.GetContentScaleFactor())
        except Exception:
            return 1.0
        return scale if scale and scale > 0 else 1.0

    # ----

    def _newOffscreenBitmap(self, width, height):
        """Create a 24-bit offscreen plot buffer at device resolution.

        When the backend reports a content scale > 1 (native Wayland), the
        buffer is allocated at device pixels via CreateWithDIPSize so the plot
        is drawn sharp instead of being rendered at logical resolution and then
        stretched up by the compositor. A wx.MemoryDC selecting the bitmap still
        works in logical coordinates, so all the pixel-based drawing code stays
        unchanged. At scale 1.0 (Windows, X11) this is an ordinary bitmap.

        24-bit RGB avoids alpha-channel artifacts on MSW where a transparent
        32-bit buffer can hide the full plot content.
        """

        scale = self._contentScale()
        bitmap = wx.Bitmap()
        bitmap.CreateWithDIPSize((width, height), scale, depth=24)
        return bitmap

    # ----

    def applyThemeColours(self):
        """Set the canvas colours for the current system theme.

        Called at construction and again whenever the system switches between
        light and dark, so the plot follows the theme without a restart.  The
        caller's own overrides go on last so they always win.
        """

        if _is_dark_mode():
            self.properties["canvasColour"] = (30, 30, 30)
            self.properties["plotColour"] = (30, 30, 30)
            self.properties["axisColour"] = (200, 200, 200)
            self.properties["gridColour"] = (60, 60, 60)
        else:
            self.properties["canvasColour"] = (255, 255, 255)
            self.properties["plotColour"] = (255, 255, 255)
            self.properties["axisColour"] = (0, 0, 0)
            self.properties["gridColour"] = (235, 235, 235)

        for name, value in self._callerProperties.items():
            self.properties[name] = value

        canvasColour = self.properties["canvasColour"]
        if not isinstance(canvasColour, wx.Colour):
            canvasColour = wx.Colour(*canvasColour)
        self.SetBackgroundColour(canvasColour)

    # ----

    def onSysColourChanged(self, evt):
        """Follow a light/dark switch made while the app is running."""

        evt.Skip()

        # plot_objects caches the dark-mode flag for the process lifetime, so it
        # has to be told the answer changed.  Imported here rather than at module
        # level because plot_objects is not otherwise a dependency of this module.
        try:
            from mspy import plot_objects

            plot_objects.invalidate_dark_mode_cache()
        except Exception:
            pass

        self.applyThemeColours()

        if self.lastDraw:
            # the plot objects bake their label colours in when they are built,
            # so the ones already on the canvas have to pick them again
            graphics = self.lastDraw[0]
            applyObjectColours = getattr(graphics, "applyThemeColours", None)
            if applyObjectColours is not None:
                applyObjectColours()

            # redraw with the new colours (same path as onSize)
            self.draw(
                graphics,
                self.getCurrentXRange(),
                self.getCurrentYRange(),
            )
        else:
            self.clear()

    # ----

    def onPaint(self, evt):
        """Repaint plot."""
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.properties["canvasColour"], wx.SOLID))
        dc.Clear()
        dc.DrawBitmap(self.plotBuffer, 0, 0)

    # ----

    def onEraseBackground(self, evt):
        """Suppress background erasing for buffered painting."""
        pass

    # ----

    def onSize(self, evt):
        """Repaint plot when size changed."""

        # get size
        width, height = self.GetClientSize()
        width = max(1, width)
        height = max(1, height)

        # make new offscreen bitmaps (device-resolution on HiDPI/Wayland)
        self.plotBuffer = self._newOffscreenBitmap(width, height)
        self.cleanPlotBuffer = self._newOffscreenBitmap(width, height)
        self.setSize()

        # redraw plot or clear area
        if self.lastDraw:

            # get current axis and x range
            minX, maxX = self.getCurrentXRange()
            minY, maxY = self.getCurrentYRange()
            rangeXmin, rangeXmax = self.getMaxXRange()

            # block oversizing
            if minX < rangeXmin:
                minX = rangeXmin
            if maxX > rangeXmax:
                maxX = rangeXmax
            if minX > maxX:
                minX = rangeXmin
                maxX = rangeXmax

            # draw plot
            self.draw(self.lastDraw[0], (minX, maxX), (minY, maxY))
        else:
            self.clear()

    # ----

    def onLeave(self, evt):
        """Escape mouse events when cursor leave out of the canvas."""

        dc = wx.MemoryDC(self.plotBuffer)
        wx.CallAfter(self.Refresh, False)
        self.quickRefresh(dc)

        # escape mouse events
        self.escMouseEvents()

        # set mouse cursor
        self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))

    # ----

    def onLMD(self, evt):
        """Change cursor style according to position and current mouse function."""

        # get focus
        if not self.FindFocus() == self:
            self.SetFocus()
            try:
                wx.GetApp().Yield()
            except Exception:
                pass

        # get cursor positions
        self.cursorPosition[0], self.cursorPosition[1] = self.getXY(evt)
        self.cursorPosition[2], self.cursorPosition[3] = evt.GetPosition()

        # escape if any mouse event set
        if self.mouseEvent:
            return

        dc = wx.MemoryDC(self.plotBuffer)
        wx.CallAfter(self.Refresh, False)
        self.quickRefresh(dc)

        # get starting coords for movement
        self.draggingStart = self.cursorPosition[:]
        location = self.getCursorLocation()
        posBar = self.getPosBarLocation()

        # navigate by clicking/dragging the position bars
        if posBar == "xPosBar":
            self.mouseEvent = "xPosBar"
            self.movePositionBar("x", dc=dc)

        elif posBar == "yPosBar":
            self.mouseEvent = "yPosBar"
            self.movePositionBar("y", dc=dc)

        # set zooming with Control (for one-button mouse)
        elif location == "plot" and evt.ControlDown():
            self.mouseEvent = "zoom"
            self.drawZoomBox(dc)

        # draw point tracker
        elif location == "plot" and self.mouseFnLMB == "point":
            self.mouseEvent = "point"
            self.drawPointTracker(dc)

        # draw isotope ruler
        elif location == "plot" and self.mouseFnLMB == "isotopes":
            self.mouseEvent = "isotopes"
            self.drawIsotopeRuler(dc)

        # draw selection rectangle
        elif location == "plot" and self.mouseFnLMB == "rectangle":
            self.mouseEvent = "rectangle"
            self.drawSelectionRect(dc)

        # draw selection range
        elif location == "plot" and self.mouseFnLMB == "range":
            self.mouseEvent = "range"
            self.drawSelectionRange(dc)

        # draw distance arrow
        elif location == "plot" and self.mouseFnLMB in ("xDistance", "yDistance"):
            self.mouseEvent = "distance"
            self.drawDistanceTracker(dc)

        # set axis dragging
        elif location == "xAxis":
            self.mouseEvent = "xShift"
        elif location == "yAxis":
            self.mouseEvent = "yShift"

        # not in area
        elif location == "blank":
            self.mouseEvent = "LOut"

    # ----

    def onLMU(self, evt):
        """Clear cursor."""

        # get focus
        if not self.FindFocus() == self:
            self.SetFocus()
            return

        dc = wx.MemoryDC(self.plotBuffer)
        wx.CallAfter(self.Refresh, False)
        self.quickRefresh(dc)

        # zoom plot
        if self.mouseEvent == "zoom":

            # clear zoombox

            # get zoom
            minX = min(self.draggingStart[0], self.cursorPosition[0])
            maxX = max(self.draggingStart[0], self.cursorPosition[0])
            minY = min(self.draggingStart[1], self.cursorPosition[1])
            maxY = max(self.draggingStart[1], self.cursorPosition[1])

            # apply zoom
            if self.properties["zoomAxis"] == "xy" and minX != maxX and minY != maxY:
                self.zoom(xAxis=(minX, maxX), yAxis=(minY, maxY), dc=dc)
            elif self.properties["zoomAxis"] == "x" and minX != maxX:
                self.zoom(xAxis=(minX, maxX), dc=dc)
            elif self.properties["zoomAxis"] == "y" and minY != maxY:
                self.zoom(yAxis=(minY, maxY), dc=dc)

        # remember zoom
        elif self.mouseEvent in ("xShift", "yShift", "xPosBar", "yPosBar"):
            self.rememberView()

        # set cursor positions
        self.cursorPosition[0], self.cursorPosition[1] = self.getXY(evt)
        self.cursorPosition[2], self.cursorPosition[3] = evt.GetPosition()

        # reset mouse event flag
        if self.mouseEvent in (
            "LOut",
            "zoom",
            "point",
            "isotopes",
            "rectangle",
            "range",
            "distance",
            "xShift",
            "yShift",
            "xPosBar",
            "yPosBar",
        ):
            self.mouseEvent = False

        # show point tracker
        if self.getCursorLocation() == "plot":
            self.drawMouseTracker(dc)

    # ----

    def onLMDC(self, evt):
        """Show full-axis plot on left-mouse double-click."""

        # set axis ranges according to cursor location
        location = self.getCursorLocation()
        if location == "plot":
            minX, maxX = self.getMaxXRange()
            minY, maxY = self.getMaxYRange()
        elif location == "xAxis":
            minX, maxX = self.getMaxXRange()
            if self.properties["autoScaleY"]:
                minY, maxY = self.getMaxYRange(minX, maxX)
            else:
                minY, maxY = self.getCurrentYRange()
        elif location == "yAxis":
            minX, maxX = self.getCurrentXRange()
            minY, maxY = self.getMaxYRange()
        else:
            return

        dc = wx.MemoryDC(self.plotBuffer)
        wx.CallAfter(self.Refresh, False)

        # redraw plot
        self.draw(self.lastDraw[0], (minX, maxX), (minY, maxY), dc)

        # remember new zoom
        self.rememberView((minX, maxX), (minY, maxY))

        # reset cursor positions
        self.cursorPosition[0], self.cursorPosition[1] = self.getXY(evt)
        self.cursorPosition[2], self.cursorPosition[3] = evt.GetPosition()

        # show point tracker
        if self.getCursorLocation() == "plot":
            self.drawMouseTracker(dc)

    # ----

    def onRMD(self, evt):
        """Change cursor style according to position and current mouse function."""

        # get focus
        if not self.FindFocus() == self:
            self.SetFocus()

        # get cursor positions
        self.cursorPosition[0], self.cursorPosition[1] = self.getXY(evt)
        self.cursorPosition[2], self.cursorPosition[3] = evt.GetPosition()

        # escape if any mouse event set
        if self.mouseEvent:
            return

        # get starting coords for movement
        self.draggingStart = self.cursorPosition[:]
        location = self.getCursorLocation()

        dc = wx.MemoryDC(self.plotBuffer)
        wx.CallAfter(self.Refresh, False)
        self.quickRefresh(dc)

        # draw zoom box and set event
        if location == "plot" and self.mouseFnRMB == "zoom":
            self.mouseEvent = "zoom"
            self.drawZoomBox(dc)

        # set event
        elif location == "xAxis":
            self.mouseEvent = "xScale"
        elif location == "yAxis":
            self.mouseEvent = "yScale"
        elif location == "blank":
            self.mouseEvent = "ROut"

    # ----

    def onRMU(self, evt):
        """Set new zoom and clear cursor."""

        # get focus
        if not self.FindFocus() == self:
            self.SetFocus()
            return

        dc = wx.MemoryDC(self.plotBuffer)
        wx.CallAfter(self.Refresh, False)
        self.quickRefresh(dc)

        # zoom dragging
        if self.mouseEvent == "zoom":

            # clear zoombox

            # get zoom
            minX = min(self.draggingStart[0], self.cursorPosition[0])
            maxX = max(self.draggingStart[0], self.cursorPosition[0])
            minY = min(self.draggingStart[1], self.cursorPosition[1])
            maxY = max(self.draggingStart[1], self.cursorPosition[1])

            # apply zoom
            if self.properties["zoomAxis"] == "xy" and minX != maxX and minY != maxY:
                self.zoom(xAxis=(minX, maxX), yAxis=(minY, maxY), dc=dc)
            elif self.properties["zoomAxis"] == "x" and minX != maxX:
                self.zoom(xAxis=(minX, maxX), dc=dc)
            elif self.properties["zoomAxis"] == "y" and minY != maxY:
                self.zoom(yAxis=(minY, maxY), dc=dc)

        # axis scaling
        elif self.mouseEvent in ("xScale", "yScale"):
            self.rememberView()

        # set new cursor positions
        self.cursorPosition[0], self.cursorPosition[1] = self.getXY(evt)
        self.cursorPosition[2], self.cursorPosition[3] = evt.GetPosition()

        # reset mouse event flag
        if self.mouseEvent in ("ROut", "zoom", "xScale", "yScale"):
            self.mouseEvent = False

        # show point tracker
        if self.getCursorLocation() == "plot":
            self.drawMouseTracker(dc)

    # ----

    def onRMDC(self, evt):
        """Show full plot on right-mouse double-click."""

        # set axis ranges according to cursor location
        if self.getCursorLocation() == "plot":
            minX, maxX = self.getMaxXRange()
            minY, maxY = self.getMaxYRange()
        else:
            return

        dc = wx.MemoryDC(self.plotBuffer)
        wx.CallAfter(self.Refresh, False)

        # redraw plot
        self.draw(self.lastDraw[0], (minX, maxX), (minY, maxY), dc)

        # remember new zoom
        self.rememberView((minX, maxX), (minY, maxY))

        # reset cursor positions
        self.cursorPosition[0], self.cursorPosition[1] = self.getXY(evt)
        self.cursorPosition[2], self.cursorPosition[3] = evt.GetPosition()

        # show point tracker
        if self.getCursorLocation() == "plot":
            self.drawMouseTracker(dc)

    # ----

    def onMMotion(self, evt):
        """Draw cursor on mouse motion."""

        # Always update cursor position so any eventual draw uses latest coords
        self.cursorPosition[0], self.cursorPosition[1] = self.getXY(evt)
        self.cursorPosition[2], self.cursorPosition[3] = evt.GetPosition()

        now = time.time()
        if self.mouseEvent in (
            "xShift",
            "yShift",
            "xScale",
            "yScale",
            "xPosBar",
            "yPosBar",
            "zoom",
            "range",
            "rectangle",
        ):
            # throttle expensive drag redraws to ~30 fps
            if now - self._last_draw_time < 0.03333:
                return
        elif not self.mouseEvent:
            # throttle cursor-tracker redraws to ~60 fps to prevent event-queue backlog
            if now - self._last_draw_time < 0.01667:
                return

        self._last_draw_time = now

        dc = wx.MemoryDC(self.plotBuffer)

        # These are the events that end in a full redraw of the whole buffer,
        # rather than an overlay drawn on top of the last one.
        immediate_paint = self.mouseEvent in (
            "xShift",
            "yShift",
            "xScale",
            "yScale",
            "xPosBar",
            "yPosBar",
        )
        redrawn = False

        # guard against stacking multiple pending Refresh calls
        # For heavy drag redraws use immediate paint to avoid frame starvation
        # when motion events flood the queue.
        if not immediate_paint and not self._refresh_pending:
            self._refresh_pending = True

            def _do_refresh(self=self):
                self._refresh_pending = False
                self.Refresh(False)

            wx.CallAfter(_do_refresh)

        # Restoring the clean buffer is what erases the previous overlay, so it
        # is only worth doing for the events that draw one. A full redraw opens
        # by clearing the buffer anyway, and blitting a screenful underneath it
        # first is a wasted copy on every frame of a drag.
        if not immediate_paint:
            self.quickRefresh(dc)

        # draw cursor tracker if no event
        if not self.mouseEvent:
            self.setCursorByLocation()
            if self.getCursorLocation() == "plot":
                self.drawMouseTracker(dc)

        # draw zoombox
        elif self.mouseEvent == "zoom":
            self.drawZoomBox(dc)

        # draw point tracker
        elif self.mouseEvent == "point":
            self.drawPointTracker(dc)

        # draw isotope ruler
        elif self.mouseEvent == "isotopes":
            self.drawIsotopeRuler(dc)

        # draw selection rectangle
        elif self.mouseEvent == "rectangle":
            self.drawSelectionRect(dc)

        # draw selection range
        elif self.mouseEvent == "range":
            self.drawSelectionRange(dc)

        # draw distance arrow
        elif self.mouseEvent == "distance":
            self.drawDistanceTracker(dc)

        # move x axis
        elif self.mouseEvent == "xShift":
            redrawn = self.shiftAxis("x", dc=dc)

        # move y axis
        elif self.mouseEvent == "yShift":
            redrawn = self.shiftAxis("y", dc=dc)

        # scale x axis
        elif self.mouseEvent == "xScale":
            redrawn = self.scaleAxis("x", dc=dc)

        # scale y axis
        elif self.mouseEvent == "yScale":
            redrawn = self.scaleAxis("y", dc=dc)

        # navigate via x position bar
        elif self.mouseEvent == "xPosBar":
            redrawn = self.movePositionBar("x", dc=dc)

        # navigate via y position bar
        elif self.mouseEvent == "yPosBar":
            redrawn = self.movePositionBar("y", dc=dc)

        # Deferred paint events can be starved by continuous motion events --
        # on GTK because motion outruns idle time, on MSW because WM_PAINT
        # ranks below mouse input in the message queue. Force the paint for
        # drag/axis-scale frames so users see intermediate frames while moving
        # the mouse.
        if immediate_paint:
            # The drag was refused (a limit reached, a bar not there): nothing
            # was drawn, so put the last clean frame back and let the overlay-
            # free buffer stand.
            if not redrawn:
                self.quickRefresh(dc)

            # The paint below runs synchronously and reads plotBuffer. wxMSW
            # cannot blit from a bitmap that is still selected into another DC
            # and hands back a blank one instead -- that is what used to make
            # the spectrum vanish mid-drag on Windows -- so release it first.
            dc.SelectObject(wx.NullBitmap)

            self.Refresh(False)
            self.Update()

    # ----

    def onMScroll(self, evt):
        """Process mouse scroll."""

        # escape if any mouse event set
        if self.mouseEvent:
            return

        dc = wx.MemoryDC(self.plotBuffer)
        wx.CallAfter(self.Refresh, False)
        self.quickRefresh(dc)

        # get scroll direction
        direction = 1
        if evt.GetWheelRotation() < 0:
            direction = -1
        if self.properties["reverseScrolling"]:
            direction *= -1

        # set new charge and count for isotope ruler
        if self.mouseFn == "isotoperuler" and evt.ShiftDown():
            if evt.AltDown() or evt.ControlDown():
                self.currentIsotopeLines = min(50, self.currentIsotopeLines + direction)
            else:
                self.currentCharge = max(1, self.currentCharge + direction)
                self.currentCharge = min(50, self.currentCharge)
            self.drawMouseTracker(dc)
            return

        # store cursor positions
        self.cursorPosition[0], self.cursorPosition[1] = self.getXY(evt)
        self.cursorPosition[2], self.cursorPosition[3] = evt.GetPosition()

        # get current axis and x range
        minX, maxX = self.getCurrentXRange()
        minY, maxY = self.getCurrentYRange()
        rangeXmin, rangeXmax = self.getMaxXRange()

        # scale x axis and center to current cursor position
        if evt.AltDown() or evt.ControlDown():
            cursorPos = self.getCursorPosition()
            if cursorPos:
                currX = cursorPos[0]
                minX -= (currX - minX) * self.properties["xScaleFactor"] * direction
                maxX += (maxX - currX) * self.properties["xScaleFactor"] * direction
            else:
                return

            # check limits
            if self.properties["checkLimits"]:
                if minX < rangeXmin:
                    minX = rangeXmin
                if maxX > rangeXmax:
                    maxX = rangeXmax

            # check max zoom
            if (maxX - minX) < self.properties["maxZoom"]:
                return

            # autoscale y axis
            if self.properties["autoScaleY"]:
                minY, maxY = self.getMaxYRange(minX, maxX)

        # scale y axis
        elif evt.ShiftDown() or self.getCursorLocation() == "yAxis":
            maxY += (minY - maxY) * self.properties["yScaleFactor"] * direction

            # check y symmetry
            if self.properties["ySymmetry"]:
                minY = -maxY

        # shift x axis
        else:
            shift = (minX - maxX) * self.properties["xScrollFactor"] * direction

            # check limits
            if self.properties["checkLimits"]:
                if minX + shift < rangeXmin:
                    shift = rangeXmin - minX
                elif maxX + shift > rangeXmax:
                    shift = rangeXmax - maxX

            minX += shift
            maxX += shift

            # autoscale y axis
            if self.properties["autoScaleY"]:
                minY, maxY = self.getMaxYRange(minX, maxX)

        # redraw plot
        self.draw(self.lastDraw[0], (minX, maxX), (minY, maxY), dc)

        # remember new zoom
        self.rememberView((minX, maxX), (minY, maxY))

        # store cursor positions
        self.cursorPosition[0], self.cursorPosition[1] = self.getXY(evt)
        self.cursorPosition[2], self.cursorPosition[3] = evt.GetPosition()

    # ----

    def onChar(self, evt):
        """Set zoom or position according to pressed key."""

        # get key
        key = evt.GetKeyCode()

        # escape current mouse events
        if key == wx.WXK_ESCAPE:
            self.escMouseEvents()
            return

        # stop if any mouse event set
        elif self.mouseEvent:
            return

        # get direction
        direction = 1
        if key in (wx.WXK_RIGHT, wx.WXK_UP, wx.WXK_PAGEDOWN):
            direction = -1

        # get current axis and x range
        minX, maxX = self.getCurrentXRange()
        minY, maxY = self.getCurrentYRange()
        rangeXmin, rangeXmax = self.getMaxXRange()
        rangeYmin, rangeYmax = self.getMaxYRange()

        # move/scale x axis by factor
        if key in (wx.WXK_LEFT, wx.WXK_RIGHT):

            # scale x axis
            if evt.AltDown():
                scale = (maxX - minX) * self.properties["xScaleFactor"] * direction
                minX -= scale
                maxX += scale

                # check limits
                if self.properties["checkLimits"]:
                    if minX < rangeXmin:
                        minX = rangeXmin
                    if maxX > rangeXmax:
                        maxX = rangeXmax

            # move x axis
            else:
                shift = (minX - maxX) * self.properties["xMoveFactor"] * direction

                # check limits
                if self.properties["checkLimits"]:
                    if minX + shift < rangeXmin:
                        shift = rangeXmin - minX
                    elif maxX + shift > rangeXmax:
                        shift = rangeXmax - maxX

                minX += shift
                maxX += shift

            # check max zoom
            if (maxX - minX) < self.properties["maxZoom"]:
                return

        # move x axis by page
        elif key in (wx.WXK_PAGEUP, wx.WXK_PAGEDOWN):
            shift = (minX - maxX) * 1 * direction

            # check limits
            if self.properties["checkLimits"]:
                if minX + shift < rangeXmin:
                    shift = rangeXmin - minX
                elif maxX + shift > rangeXmax:
                    shift = rangeXmax - maxX

            minX += shift
            maxX += shift

            # check max zoom
            if (maxX - minX) < self.properties["maxZoom"]:
                return

        # scale y axis
        elif key == wx.WXK_UP or key == wx.WXK_DOWN:
            maxY += (maxY - minY) * self.properties["yScaleFactor"] * direction

        # fullsize
        elif key == wx.WXK_HOME and evt.ControlDown():
            minX = rangeXmin
            maxX = rangeXmax
            minY = rangeYmin
            maxY = rangeYmax

        # go to plot start
        elif key == wx.WXK_HOME:
            diff = maxX - minX
            minX = rangeXmin
            maxX = rangeXmin + diff

        # go to plot end
        elif key == wx.WXK_END:
            diff = maxX - minX
            minX = rangeXmax - diff
            maxX = rangeXmax

        # go forth in zoom memory
        elif key == wx.WXK_BACK and evt.AltDown():
            if len(self.viewMemory[1]) > 0:
                self.viewMemory[0].append(self.viewMemory[1][-1])
                minX = self.viewMemory[1][-1][0][0]
                maxX = self.viewMemory[1][-1][0][1]
                minY = self.viewMemory[1][-1][1][0]
                maxY = self.viewMemory[1][-1][1][1]
                del self.viewMemory[1][-1]
            else:
                return

        # go back in zoom memory
        elif key == wx.WXK_BACK:
            if len(self.viewMemory[0]) > 1:
                self.viewMemory[1].append(self.viewMemory[0][-1])
                del self.viewMemory[0][-1]
                minX = self.viewMemory[0][-1][0][0]
                maxX = self.viewMemory[0][-1][0][1]
                minY = self.viewMemory[0][-1][1][0]
                maxY = self.viewMemory[0][-1][1][1]
            else:
                return

        else:
            evt.Skip()
            return

        # autoscale y axis
        if self.properties["autoScaleY"] and key in (
            wx.WXK_LEFT,
            wx.WXK_RIGHT,
            wx.WXK_END,
            wx.WXK_HOME,
            wx.WXK_PAGEUP,
            wx.WXK_PAGEDOWN,
        ):
            minY, maxY = self.getMaxYRange(minX, maxX)

        # redraw plot
        self.draw(self.lastDraw[0], (minX, maxX), (minY, maxY))

        # remember new zoom
        if key != wx.WXK_BACK:
            self.rememberView((minX, maxX), (minY, maxY))

    # ----

    def getPrintout(self, filterSize, title):
        """Get printout of current plot."""
        return printout(self, filterSize, title)

    # ----

    def getBitmap(self, width=None, height=None, printerScale=None):
        """Get current plot bitmap with selected size."""

        # get width/height if not set
        if not width or not height:
            width, height = self.GetClientSize()
        width = max(1, int(round(width)))
        height = max(1, int(round(height)))

        # create empty bitmap
        tmpBitmap = wx.Bitmap(width, height, 24)
        if hasattr(tmpBitmap, "SetScaleFactor"):
            tmpBitmap.SetScaleFactor(1.0)
        tmpDC = wx.MemoryDC()
        tmpDC.SelectObject(tmpBitmap)
        tmpDC.Clear()

        # On HiDPI systems the DC drawable size may differ from bitmap pixel size.
        # Use the DC size for plot geometry to prevent top-left quadrant clipping.
        drawWidth, drawHeight = tmpDC.GetSize()
        drawWidth = max(1, int(round(drawWidth)))
        drawHeight = max(1, int(round(drawHeight)))

        # rescale plot
        self.setSize(drawWidth, drawHeight)

        # thicken up pens and fonts
        if not printerScale:
            ratioW = float(drawWidth) / 750
            ratioH = float(drawHeight) / 750
            scale = max(min(ratioW, ratioH), 1)
            self.printerScale["drawings"] = scale
            self.printerScale["fonts"] = _print_font_scale(scale)
        else:
            self.printerScale["drawings"] = max(printerScale["drawings"], 1)
            self.printerScale["fonts"] = _print_font_scale(max(printerScale["fonts"], 1))

        # set filter size
        filterSize = max(self.printerScale["drawings"] * 0.5, 0.5)

        # draw plot
        self.drawOutside(tmpDC, filterSize)
        tmpDC.SelectObject(wx.NullBitmap)

        # rescale back to original
        self.setSize()
        self.printerScale["drawings"] = self.basePrinterScale
        self.printerScale["fonts"] = self.baseFontScale
        self.refresh()

        return tmpBitmap

    # ----

    def getSVG(self, path, width=None, height=None, printerScale=None, dpi=72):
        """Export current plot to a scalable vector graphics (SVG) file.

        Draws through a wx.SVGFileDC so the whole plot -- axis, labels, peaks,
        gel view and legend -- is recorded as vector primitives rather than
        rasterised pixels.
        """

        # get width/height if not set
        if not width or not height:
            width, height = self.GetClientSize()
        width = max(1, int(round(width)))
        height = max(1, int(round(height)))

        # create the SVG DC (the file is written as we draw and finalised
        # when the DC is deleted below)
        dc = wx.SVGFileDC(path, width, height, dpi)

        # rescale plot to the export size (SVGFileDC has no HiDPI scaling, so
        # the requested size is the drawing size)
        self.setSize(width, height)

        # thicken up pens and fonts
        if not printerScale:
            ratioW = float(width) / 750
            ratioH = float(height) / 750
            scale = max(min(ratioW, ratioH), 1)
            self.printerScale["drawings"] = scale
            self.printerScale["fonts"] = _print_font_scale(scale)
        else:
            self.printerScale["drawings"] = max(printerScale["drawings"], 1)
            self.printerScale["fonts"] = _print_font_scale(max(printerScale["fonts"], 1))

        # set filter size
        filterSize = max(self.printerScale["drawings"] * 0.5, 0.5)

        # draw plot
        self.drawOutside(dc, filterSize)

        # finalise and close the SVG file
        del dc

        # rescale back to original
        self.setSize()
        self.printerScale["drawings"] = self.basePrinterScale
        self.printerScale["fonts"] = self.baseFontScale
        self.refresh()

    # ----

    def getCurrentBitmap(self):
        """Get bitmap of the currently rendered plot buffer."""

        # On HiDPI/Wayland plotBuffer holds full device-resolution pixels (its
        # scale factor > 1). ConvertToImage yields all of them, so just return
        # the whole image as a plain scale-1.0 bitmap -- that is the sharp,
        # screen-equivalent rendering callers want. (Cropping to the logical
        # size here would return only the top-left quadrant of the plot.)
        image = self.plotBuffer.ConvertToImage()
        bitmap = image.ConvertToBitmap()
        if hasattr(bitmap, "SetScaleFactor"):
            bitmap.SetScaleFactor(1.0)
        return bitmap

    # ----

    def getXY(self, evt):
        """Get XY position in user values."""
        x, y = self.positionScreenToUser(evt.GetPosition())
        return x, y

    # ----

    def getCurrentXRange(self):
        """Get current X-axis range."""
        return self.lastDraw[1]

    # ----

    def getCurrentYRange(self):
        """Get current Y-axis range."""
        return self.lastDraw[2]

    # ----

    def getMaxXRange(self, absolute=False):
        """Get maximal X-axis range."""

        graphics = self.lastDraw[0]
        p1, p2 = graphics.getBoundingBox(absolute=absolute)
        return (p1[0], p2[0])

    # ----

    def getMaxYRange(self, minX=None, maxX=None, absolute=False):
        """Get maximal Y-axis range."""

        # get bounding box
        graphics = self.lastDraw[0]
        p1, p2 = graphics.getBoundingBox(minX, maxX, absolute)

        # check y symmetry
        if self.properties["ySymmetry"]:
            maxY = max(abs(p1[1]), abs(p2[1]))
            return (-maxY, maxY)
        else:
            return (p1[1], p2[1])

    # ----

    def getCursorLocation(self):
        """Locate cursor within the plot area."""

        # get plot width/height
        minX = self.plotCoords[0]
        minY = self.plotCoords[1]
        maxX = self.plotCoords[2]
        maxY = self.plotCoords[3]

        # get current position
        x = self.cursorPosition[2]
        y = self.cursorPosition[3]

        # locate cursor
        if minX < x < maxX and minY < y < maxY:
            return "plot"
        elif minX < x < maxX and y > minY:
            return "xAxis"
        elif minY < y < maxY and x < minX:
            return "yAxis"
        else:
            return "blank"

    # ----

    def getPosBarLocation(self):
        """Locate cursor within the X/Y position bars."""

        x = self.cursorPosition[2]
        y = self.cursorPosition[3]

        if self.properties["showXPosBar"] and self.xPosBarBox:
            bx, by, bw, bh = self.xPosBarBox
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return "xPosBar"

        if self.properties["showYPosBar"] and self.yPosBarBox:
            bx, by, bw, bh = self.yPosBarBox
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return "yPosBar"

        return None

    # ----

    def getCursorPosition(self):
        """Get cursor position in user coordinations."""

        # check position
        if self.getCursorLocation() != "plot":
            return False

        # return current position
        return self.cursorPosition[0], self.cursorPosition[1]

    # ----

    def getDistance(self):
        """Get current cursor distance."""

        # check event
        if self.mouseEvent != "distance":
            return False

        # get distance coord in user units
        x1 = self.draggingStart[0]
        y1 = self.draggingStart[1]
        x2 = self.cursorPosition[0]
        y2 = self.cursorPosition[1]

        # return distance
        return [x2 - x1, y2 - y1]

    # ----

    def getCharge(self):
        """Get current charge."""
        return self.currentCharge

    # ----

    def getIsotopes(self):
        """Get current isotopes."""

        # check event
        if self.mouseEvent != "isotopes":
            return False

        # check position
        if self.getCursorLocation() != "plot":
            return False

        # return current isotopes
        return self.currentIsotopes[:]

    # ----

    def getPoint(self, xPos=None, coord="screen"):
        """Get corresponding data point from current object and xPos."""

        # check current object
        if self.currentObject is None:
            return None

        # get corresponding point
        graphics = self.lastDraw[0]
        point = graphics.getPoint(self.currentObject, xPos, coord)

        return point

    # ----

    def getSelectionBox(self):
        """Get selection rectangle coordinations."""

        # check position
        if self.mouseEvent not in ("rectangle", "range"):
            return False

        # get coordinations
        x1 = min(self.draggingStart[0], self.cursorPosition[0])
        y1 = min(self.draggingStart[1], self.cursorPosition[1])
        x2 = max(self.draggingStart[0], self.cursorPosition[0])
        y2 = max(self.draggingStart[1], self.cursorPosition[1])

        return x1, y1, x2, y2

    # ----

    def setSize(self, width=None, height=None):
        """Set DC width and height."""

        # get size
        if width is None:
            width, height = self.GetClientSize()

        # set size
        self.plotBoxSize = numpy.array([width, height])
        x0 = 0.5 * (width - self.plotBoxSize[0])
        y0 = height - 0.5 * (height - self.plotBoxSize[1])
        self.plotBoxOrigin = numpy.array([x0, y0])

    # ----

    def setCurrentObject(self, value):
        """Set selected data object as main."""
        self.currentObject = value

    # ----

    def setPrinterScale(self, drawings=None, fonts=None):
        """Used to thicken lines and increase marker size for printouts."""

        if drawings is None:
            drawings = self.basePrinterScale
        if fonts is None:
            fonts = self.baseFontScale
        self.printerScale["drawings"] = drawings
        self.printerScale["fonts"] = fonts

    # ----

    def setProperties(self, **attr):
        """Set parameters for canvas."""

        for name, value in list(attr.items()):
            self.properties[name] = value

    # ----

    def setMFunction(self, fn=None):
        """Set cursor tracker style."""
        self.mouseFn = fn

    # ----

    def setLMBFunction(self, fn):
        """Set function for left mouse button."""
        self.mouseFnLMB = fn

    # ----

    def setRMBFunction(self, fn):
        """Set function for right mouse button."""
        self.mouseFnRMB = fn

    # ----

    def setCursorImage(self, cursor):
        """Set cursor image for main plot area."""
        self.cursorImage = cursor

    # ----

    def setCursorByLocation(self):
        """Set cursor-type according to location."""

        if self.getPosBarLocation() is not None:
            self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
            return

        location = self.getCursorLocation()
        if location == "xAxis":
            self.SetCursor(wx.Cursor(wx.CURSOR_SIZEWE))
        elif location == "yAxis":
            self.SetCursor(wx.Cursor(wx.CURSOR_SIZENS))
        elif location == "plot" and self.properties["showCurImage"]:
            self.SetCursor(self.cursorImage)
        elif location == "plot" and self.mouseFn:
            self.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
        else:
            self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))

    # ----

    def draw(
        self, graphics, xAxis=None, yAxis=None, dc=None, filterSize=None, adaptive=True
    ):
        """Draw axis and plot graphics."""

        if filterSize is None:
            filterSize = self.properties.get("filterSize", 1.0)

        # reset tracker
        self.mouseTracker = False

        own_dc = dc is None
        if dc is None:
            dc = wx.MemoryDC(self.plotBuffer)
            wx.CallAfter(self.Refresh, False)
        dc.SetBackground(wx.Brush(self.properties["canvasColour"], wx.SOLID))
        dc.Clear()

        # set dc font
        dc.SetFont(_scaleFont(self.properties["axisFont"], self.printerScale["fonts"]))

        # get number of visible spectra
        self.gelsCount = graphics.countGels()

        # get lower left and upper right corners of plot
        if xAxis is None or yAxis is None:
            p1, p2 = graphics.getBoundingBox()
            if xAxis is None:
                xAxis = (p1[0], p2[0])
            if yAxis is None:
                yAxis = (p1[1], p2[1])
            self.viewMemory[0] = [(xAxis, yAxis)]

        p1 = numpy.array([xAxis[0], yAxis[0]])
        p2 = numpy.array([xAxis[1], yAxis[1]])

        # save most recent values
        self.lastDraw = (graphics, xAxis, yAxis)

        # get axis ticks
        xAxisTicks = self.makeAxisTicks(xAxis[0], xAxis[1])
        yAxisTicks = self.makeAxisTicks(yAxis[0], yAxis[1])

        # get text extents for axis ticks
        xLeft = dc.GetTextExtent(xAxisTicks[0][1])
        xRight = dc.GetTextExtent(xAxisTicks[-1][1])
        yBottom = dc.GetTextExtent(yAxisTicks[0][1])
        yTop = dc.GetTextExtent(yAxisTicks[-1][1])
        xAxisTextExtent = (xRight[0], max(xLeft[1], xRight[1]))
        yAxisTextExtent = (max(yBottom[0], yTop[0]), max(yBottom[1], yTop[1]))

        # get text extents for axis labels
        xAxisLabelWH = dc.GetTextExtent(self.properties["xLabel"])
        yAxisLabelWH = dc.GetTextExtent(self.properties["yLabel"])

        # get room around graph area
        spaceLeft = (
            yAxisTextExtent[0] + yAxisLabelWH[1] + 15 * self.printerScale["drawings"]
        )
        spaceBottom = (
            xAxisTextExtent[1] + xAxisLabelWH[1] + 10 * self.printerScale["drawings"]
        )

        spaceTop = 15
        if self.properties["showXPosBar"]:
            spaceTop += self.properties["posBarSize"] + 6
        if self.properties["showGel"]:
            spaceTop += self.gelsCount * self.properties["gelHeight"] + 6 + 2
        spaceTop = spaceTop * self.printerScale["drawings"]

        spaceRight = xAxisTextExtent[0] / 1.5
        if self.properties["showYPosBar"]:
            spaceRight = max(
                xAxisTextExtent[0] / 1.5,
                (self.properties["posBarSize"] + 6 + 8) * self.printerScale["drawings"],
            )

        # get scaling and shifting
        textSizeScale = numpy.array([spaceRight + spaceLeft, spaceBottom + spaceTop])
        textSizeShift = numpy.array([spaceLeft, spaceBottom])
        scale = (self.plotBoxSize - textSizeScale) / (p2 - p1) * numpy.array((1, -1))
        shift = -p1 * scale + self.plotBoxOrigin + textSizeShift * numpy.array((1, -1))
        self.pointScale = scale
        self.pointShift = shift

        # remember axis coordinations
        x, y, width, height = self.pointToClientCoord(p1, p2)
        self.plotCoords = (x, y, x + width, y + height)

        # crop, recalculate and filter points
        graphics.cropPoints(p1[0], p2[0])

        graphics.scaleAndShift(scale, shift, filterSize)

        # draw axis labels
        xLabelPos = (
            self.plotBoxSize[0] - spaceRight - xAxisLabelWH[0],
            self.plotBoxOrigin[1] - xAxisLabelWH[1] - 3,
        )
        yLabelPos = (3, spaceTop + yAxisLabelWH[0])
        dc.SetTextForeground(self.properties["axisColour"])
        dc.DrawText(self.properties["xLabel"], int(xLabelPos[0]), int(xLabelPos[1]))
        dc.DrawRotatedText(
            self.properties["yLabel"], int(yLabelPos[0]), int(yLabelPos[1]), 90
        )

        # draw plot axis
        self.drawAxis(dc, xAxisTicks, yAxisTicks)

        # draw plot x position box
        if self.properties["showXPosBar"]:
            self.drawXPositionBar(dc, xAxis)
        else:
            self.xPosBarBox = None

        # draw plot y position box
        if self.properties["showYPosBar"]:
            self.drawYPositionBar(dc, yAxis)
        else:
            self.yPosBarBox = None

        # draw gel
        if self.properties["showGel"]:
            self.drawGelView(dc, graphics)

        # draw data
        dc.SetClippingRegion(int(x), int(y), int(width), int(height))
        graphics.draw(
            dc,
            printerScale=self.printerScale,
            overlapLabels=self.properties["overlapLabels"],
            reverse=self.properties["reverseDrawing"],
        )
        dc.DestroyClippingRegion()

        # draw legend
        if self.properties["showLegend"]:
            self.drawLegend(dc, graphics)

        # Always update the clean buffer from plotBuffer so that quickRefresh
        # (called on subsequent mouse events and on mouse-up) reflects the
        # latest drawn state. cleanPlotBuffer always reads from self.plotBuffer,
        # so this is correct even when dc is an off-screen export DC (in that
        # case plotBuffer was not touched by this draw call and its content is
        # unchanged from the previous on-screen draw).
        # MSW can return a blank sub-bitmap here when sourced from a bitmap
        # participating in active DC drawing, so it takes the robust route
        # through wx.Image. That round-trip unpacks and repacks every pixel and
        # costs several milliseconds a frame, which is worth avoiding on the
        # toolkits that copy the bitmap correctly.
        # Either way the copy drops the scale factor, so restore it -- otherwise
        # the clean buffer's logical size would mismatch plotBuffer and
        # quickRefresh would blit it at the wrong scale on HiDPI/Wayland.
        if wx.Platform == "__WXMSW__":
            self.cleanPlotBuffer = self.plotBuffer.ConvertToImage().ConvertToBitmap()
        else:
            self.cleanPlotBuffer = self.plotBuffer.GetSubBitmap(
                wx.Rect(0, 0, self.plotBuffer.GetWidth(), self.plotBuffer.GetHeight())
            )
        if hasattr(self.plotBuffer, "GetScaleFactor"):
            self.cleanPlotBuffer.SetScaleFactor(self.plotBuffer.GetScaleFactor())

        # Apply dynamic overlays (highlighted points etc.) only for live
        # on-screen draws. Off-screen export/print DCs must keep only the
        # rendered plot content.
        if own_dc:
            self.quickRefresh(dc)

    # ----

    def drawOutside(self, dc, filterSize):
        """Used for printing and exporting."""

        if self.lastDraw is not None:
            graphics, xAxis, yAxis = self.lastDraw
            self.draw(graphics, xAxis, yAxis, dc, filterSize=filterSize, adaptive=False)

    # ----

    def drawAxis(self, dc, xticks, yticks):
        """Draw plot axis."""

        # set pen
        penWidth = int(self.printerScale["drawings"])
        dc.SetPen(wx.Pen(self.properties["axisColour"], penWidth))
        dc.SetTextForeground(self.properties["axisColour"])

        # get plot coordinates
        plotX1, plotY1, plotX2, plotY2 = self.plotCoords
        plotX1 -= penWidth
        plotY1 -= penWidth
        plotX2 += penWidth
        plotY2 += penWidth

        # fill background
        dc.SetBrush(wx.Brush(self.properties["plotColour"], wx.SOLID))
        dc.DrawRectangle(
            int(plotX1), int(plotY1), int(plotX2 - plotX1), int(plotY2 - plotY1)
        )
        dc.SetBrush(wx.TRANSPARENT_BRUSH)

        # set length of tick marks
        tickLength = 5 * self.printerScale["drawings"]

        # x axis
        previous = 0
        for x, label, ttype in xticks:
            pt = self.pointScale * numpy.array([x, 1]) + self.pointShift

            # minor ticks
            if ttype == "minor":
                if self.properties["showMinorTicks"]:
                    dc.DrawLine(
                        int(pt[0]),
                        int(plotY2),
                        int(pt[0]),
                        int(plotY2 + tickLength / 2),
                    )
                continue

            # major ticks
            dc.DrawLine(int(pt[0]), int(plotY2), int(pt[0]), int(plotY2 + tickLength))
            extent = dc.GetTextExtent(label)
            ori = pt[0] - extent[0] / 2
            if ori > previous:
                dc.DrawText(label, int(ori), int(plotY2 + tickLength * 1.4))
                previous = ori + extent[0] + 10 * self.printerScale["drawings"]
            if self.properties["showGrid"]:
                dc.SetPen(wx.Pen(self.properties["gridColour"], penWidth))
                dc.SetTextForeground(self.properties["gridColour"])
                dc.DrawLine(int(pt[0]), int(plotY1), int(pt[0]), int(plotY2 - penWidth))
                dc.SetPen(wx.Pen(self.properties["axisColour"], penWidth))
                dc.SetTextForeground(self.properties["axisColour"])

        # y axis
        previous = plotY2 + dc.GetCharHeight()
        for y, label, ttype in yticks:
            pt = self.pointScale * numpy.array([1, y]) + self.pointShift

            # minor ticks
            if ttype == "minor":
                if self.properties["showMinorTicks"]:
                    dc.DrawLine(
                        int(plotX1 - penWidth),
                        int(pt[1]),
                        int(plotX1 - penWidth - tickLength / 2),
                        int(
                            pt[1],
                        ),
                    )
                continue

            # major ticks
            dc.DrawLine(
                int(plotX1 - penWidth),
                int(pt[1]),
                int(plotX1 - penWidth - tickLength),
                int(pt[1]),
            )
            extent = dc.GetTextExtent(label)
            ori = pt[1] - extent[1] / 2
            if ori + extent[1] < previous:
                dc.DrawText(
                    label,
                    int(plotX1 - penWidth - extent[0] - tickLength * 1.5),
                    int(ori),
                )
                previous = ori + 5 * self.printerScale["drawings"]
            if self.properties["showGrid"]:
                dc.SetPen(wx.Pen(self.properties["gridColour"], penWidth))
                dc.SetTextForeground(self.properties["gridColour"])
                dc.DrawLine(int(plotX1), int(pt[1]), int(plotX2 - penWidth), int(pt[1]))
                dc.SetPen(wx.Pen(self.properties["axisColour"], penWidth))
                dc.SetTextForeground(self.properties["axisColour"])

            # show zero line
            if self.properties["showZero"] and float(label) == 0:
                dc.SetPen(wx.Pen(self.properties["axisColour"], penWidth, wx.DOT))
                dc.DrawLine(int(plotX1), int(pt[1]), int(plotX2 - penWidth), int(pt[1]))
                dc.SetPen(wx.Pen(self.properties["axisColour"], penWidth))

        # draw plot outline
        dc.DrawRectangle(
            int(plotX1), int(plotY1), int(plotX2 - plotX1), int(plotY2 - plotY1)
        )

    # ----

    def drawLegend(self, dc, graphics):
        """Draw legend."""

        # get names
        names = graphics.getLegend()

        # set font
        dc.SetFont(_scaleFont(self.properties["axisFont"], self.printerScale["fonts"]))

        # draw legend
        y = self.plotCoords[1] + 5 * self.printerScale["drawings"]
        for name in names:

            # draw text
            x = (
                self.plotCoords[2]
                - dc.GetTextExtent(name[0])[0]
                - 17 * self.printerScale["drawings"]
            )
            dc.SetTextForeground(name[1])
            dc.DrawText(name[0], int(x), int(y))

            # draw circle
            x = self.plotCoords[2] - 9 * self.printerScale["drawings"]
            y += dc.GetTextExtent(name[0])[1] / 2

            pencolour = [max(i - 70, 0) for i in name[1]]
            pen = wx.Pen(pencolour, int(self.printerScale["drawings"]), wx.SOLID)
            brush = wx.Brush(name[1], wx.SOLID)
            dc.SetPen(pen)
            dc.SetBrush(brush)

            dc.DrawCircle(int(x), int(y), int(3 * self.printerScale["drawings"]))

            # set y for next name
            y += dc.GetTextExtent(name[0])[1] / 2 + 2 * self.printerScale["drawings"]

    # ----

    def drawXPositionBar(self, dc, xAxis):
        """Draw position bar."""

        # get plot coordinates
        x1, y1, x2, y2 = self.plotCoords
        x1 -= self.printerScale["drawings"]
        y1 = 14 * self.printerScale["drawings"]
        x2 += self.printerScale["drawings"]
        width = x2 - x1
        height = self.properties["posBarSize"] * self.printerScale["drawings"]

        # remember hit-test box for click/drag navigation
        self.xPosBarBox = (x1, y1, width, height)

        # get current position
        minX, maxX = self.getMaxXRange(absolute=True)
        x = x1 + (xAxis[0] - minX) * width / abs((maxX - minX))
        currWidth = width * (xAxis[1] - xAxis[0]) / (maxX - minX)
        currWidth = max(currWidth, 3 * self.printerScale["drawings"])

        # check limits
        if x < x1:
            currWidth -= x1 - x
            x = x1
        if x + currWidth > x2:
            currWidth -= currWidth - (x2 - x)
        if currWidth < 0:
            currWidth = 0

        # set pen
        penWidth = int(self.printerScale["drawings"])
        dc.SetPen(wx.Pen(self.properties["axisColour"], penWidth))

        # draw outline
        dc.SetBrush(wx.Brush(self.properties["plotColour"], wx.SOLID))
        dc.DrawRectangle(int(x1), int(y1), int(width), int(height))

        # draw position
        dc.SetBrush(wx.Brush(self.properties["axisColour"], wx.SOLID))
        dc.DrawRectangle(int(x), int(y1), int(currWidth), int(height))

        # draw outside arrows
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush((255, 0, 0), wx.SOLID))
        size = 6 * self.printerScale["drawings"]
        if xAxis[1] < minX:
            x = x1 - 2 * self.printerScale["drawings"]
            dc.DrawPolygon(
                [
                    (int(p[0]), int(p[1]))
                    for p in [(x, y1), (x, y1 + height), (x - size, y1 + height // 2)]
                ]
            )
        if xAxis[0] > maxX:
            x = x2 + 2 * self.printerScale["drawings"]
            dc.DrawPolygon(
                [
                    (int(p[0]), int(p[1]))
                    for p in [(x, y1), (x, y1 + height), (x + size, y1 + height // 2)]
                ]
            )

    # ----

    def drawYPositionBar(self, dc, yAxis):
        """Draw position bar."""

        # get plot coordinates
        x1, y1, x2, y2 = self.plotCoords
        x1 = x2 + (5 + 2) * self.printerScale["drawings"]
        y1 -= self.printerScale["drawings"]
        y2 += self.printerScale["drawings"]
        height = y2 - y1
        width = self.properties["posBarSize"] * self.printerScale["drawings"]

        # remember hit-test box for click/drag navigation
        self.yPosBarBox = (x1, y1, width, height)

        # get current position
        minY, maxY = self.getMaxYRange(absolute=True)
        y = y1 - (yAxis[1] - maxY) * height / abs((maxY - minY))
        currHeight = height * (yAxis[1] - yAxis[0]) / (maxY - minY)
        currHeight = max(currHeight, 3 * self.printerScale["drawings"])

        # check limits
        if y < y1:
            currHeight -= y1 - y
            y = y1
        if y > y2:
            currHeight -= y2 - y
            y = y2
        if y + currHeight > y2:
            currHeight -= currHeight - (y2 - y)
        if y + currHeight < y1:
            currHeight = 0

        # set pen
        penWidth = int(self.printerScale["drawings"])
        dc.SetPen(wx.Pen(self.properties["axisColour"], penWidth))

        # draw outline
        dc.SetBrush(wx.Brush(self.properties["plotColour"], wx.SOLID))
        dc.DrawRectangle(int(x1), int(y1), int(width), int(height))

        # draw position
        dc.SetBrush(wx.Brush(self.properties["axisColour"], wx.SOLID))
        dc.DrawRectangle(int(x1), int(y), int(width), int(currHeight))

        # draw outside arrows
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush((255, 0, 0), wx.SOLID))
        size = 6 * self.printerScale["drawings"]
        if yAxis[0] > maxY:
            y = y1 - 2 * self.printerScale["drawings"]
            dc.DrawPolygon(
                [
                    (int(p[0]), int(p[1]))
                    for p in [(x1, y), (x1 + width, y), (x1 + width // 2, y - size)]
                ]
            )
        if yAxis[1] < minY:
            y = y2 + 2 * self.printerScale["drawings"]
            dc.DrawPolygon(
                [
                    (int(p[0]), int(p[1]))
                    for p in [(x1, y), (x1 + width, y), (x1 + width // 2, y + size)]
                ]
            )

    # ----

    def drawGelView(self, dc, graphics):
        """Draw spectra gelview."""

        # set pen
        penWidth = int(self.printerScale["drawings"])

        # get plot coordinates
        plotX1, plotY1, plotX2, plotY2 = self.plotCoords
        zeroY = self.pointShift[1]

        # get coords
        width = plotX2 - plotX1
        height = (
            self.gelsCount
            * self.properties["gelHeight"]
            * self.printerScale["drawings"]
        )
        gelY1 = plotY1 - height - 8 * self.printerScale["drawings"]

        # set clipping area
        dc.SetClippingRegion(int(plotX1), int(gelY1), int(width), int(height))

        # draw background: use the gel colormap's "zero" colour (black in dark
        # mode, white in light mode) so areas with no data read as empty rather
        # than showing the lighter plot background, which would otherwise look
        # paler than genuinely low-intensity data.
        gelBackground = (
            wx.Colour(0, 0, 0) if _is_dark_mode() else wx.Colour(255, 255, 255)
        )
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(gelBackground, wx.SOLID))
        dc.DrawRectangle(int(plotX1), int(gelY1), int(width), int(height))

        # draw gels
        graphics.drawGel(
            dc,
            [gelY1, plotX1, plotY1, plotX2, plotY2, zeroY],
            self.properties["gelHeight"] * self.printerScale["drawings"],
            self.printerScale,
        )

        # remove the clipping area
        dc.DestroyClippingRegion()

        # draw outlines
        plotX1 -= penWidth
        gelY1 -= penWidth
        width += 2 * penWidth
        height += 2 * penWidth

        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.SetPen(wx.Pen(self.properties["axisColour"], penWidth))
        dc.DrawRectangle(int(plotX1), int(gelY1), int(width), int(height))

    # ----

    def drawMouseTracker(self, dc):
        """Draw selected mouse tracker."""

        # draw default cross tracker
        if self.mouseFn == "cross":
            self.drawCursorTracker(dc)

        # draw isotope ruler
        elif self.mouseFn == "isotoperuler":
            self.drawIsotopeRuler(dc)

        # no tracker set
        else:
            return

        # set current state
        self.mouseTracker = not self.mouseTracker

    # ----

    def drawCursorTracker(self, dc):
        """Draw cursor tracker"""

        # get plot coords
        x = self.cursorPosition[2]
        y = self.cursorPosition[3]
        minXPlot = self.plotCoords[0]
        maxXPlot = self.plotCoords[2]
        minYPlot = self.plotCoords[1]
        maxYPlot = self.plotCoords[3]
        minYGel = 0
        maxYGel = 0

        # get gel coords
        if self.properties["showGel"]:
            minYGel = minYPlot - (9 * self.printerScale["drawings"])
            maxYGel = minYGel - self.gelsCount * self.properties["gelHeight"]

        if wx.Platform == "__WXMAC__":
            maxXPlot -= 1
            maxYPlot -= 1
            maxYGel += 1

        # draw tracker lines (axisColour follows the dark/light theme)
        dc.SetPen(wx.Pen(self.properties["axisColour"], style=wx.PENSTYLE_SHORT_DASH))
        # dc.SetLogicalFunction(wx.INVERT)

        dc.DrawLine(int(x), int(minYPlot), int(x), int(maxYPlot))
        dc.DrawLine(int(minXPlot), int(y), int(maxXPlot), int(y))
        if self.properties["showGel"]:
            dc.DrawLine(int(x), int(minYGel), int(x), int(maxYGel))

        dc.SetLogicalFunction(wx.COPY)

        # draw position text
        if self.properties["showCurXPos"] or self.properties["showCurYPos"]:

            # get current x position
            xFormat = "%0." + repr(self.properties["xPosDigits"]) + "f"
            yFormat = "%0." + repr(self.properties["yPosDigits"]) + "f"
            xText = xFormat % (self.cursorPosition[0])
            if abs(self.cursorPosition[1]) > 10000:
                yFormat = "%.2e"
            yText = yFormat % (self.cursorPosition[1])

            # get text position
            dc.SetFont(_scaleFont(self.properties["axisFont"], self.printerScale["fonts"]))
            xTextSize = dc.GetTextExtent(xText)
            yTextSize = dc.GetTextExtent(yText)
            x += 5
            y1 = y - 2 * xTextSize[1] - 2
            y2 = y1 + xTextSize[1]

            # check limits for position
            xMax = max(xTextSize[0], yTextSize[0])
            if x + xMax > self.plotCoords[2]:
                x -= xMax + 10
            if y1 < self.plotCoords[1]:
                y1 += 2 * xTextSize[1] + 6
                y2 = y1 + xTextSize[1]

            # draw text
            if self.properties["showCurXPos"] and self.properties["showCurYPos"]:
                self.drawInvertedText(dc, xText, x, y1, self.properties["axisFont"])
                self.drawInvertedText(dc, yText, x, y2, self.properties["axisFont"])
            elif self.properties["showCurXPos"]:
                self.drawInvertedText(dc, xText, x, y1, self.properties["axisFont"])
            elif self.properties["showCurYPos"]:
                self.drawInvertedText(dc, yText, x, y1, self.properties["axisFont"])

    # ----

    def drawDistanceTracker(self, dc):
        """Draw distance tracker."""

        # check cursor position
        if self.getCursorLocation() != "plot":
            return

        # hide cursor
        self.SetCursor(wx.Cursor(wx.CURSOR_BLANK))

        # get screen coordinations
        x1 = self.draggingStart[2]
        y1 = self.draggingStart[3]
        x2 = self.cursorPosition[2]
        y2 = self.cursorPosition[3]

        minX = self.plotCoords[0]
        minY = self.plotCoords[1]
        maxX = self.plotCoords[2]
        maxY = self.plotCoords[3]

        # check limits
        x2 = min(x2, maxX - 1)
        x2 = max(x2, minX)
        y2 = min(y2, maxY - 1)
        y2 = max(y2, minY)

        if wx.Platform == "__WXMAC__":
            maxX -= 1
            maxY -= 1

        # draw tracker (axisColour follows the dark/light theme)
        # dc.SetLogicalFunction(wx.INVERT)
        dc.SetPen(wx.Pen(self.properties["axisColour"]))

        if self.mouseFnLMB == "xDistance":
            dc.DrawLine(int(x1), int(minY), int(x1), int(maxY))
            if x1 != x2:
                dc.DrawLine(int(x2), int(minY), int(x2), int(maxY))
                dc.DrawLine(int(x1), int(y2), int(x2), int(y2))

        elif self.mouseFnLMB == "yDistance":
            dc.DrawLine(int(minX), int(y1), int(maxX), int(y1))
            if y1 != y2:
                dc.DrawLine(int(minX), int(y2), int(maxX), int(y2))
                dc.DrawLine(int(x2), int(y1), int(x2), int(y2))

        dc.SetLogicalFunction(wx.COPY)

        # draw diff text
        if self.properties["showCurDistance"]:

            # set font
            dc.SetFont(_scaleFont(self.properties["axisFont"], self.printerScale["fonts"]))

            # get distance
            dist1 = self.positionScreenToUser((x1, y1))
            dist2 = self.positionScreenToUser((x2, y2))

            if self.mouseFnLMB == "xDistance":
                format = "%0." + repr(self.properties["xPosDigits"]) + "f"
                distance = format % (dist2[0] - dist1[0])
                textSize = dc.GetTextExtent(distance)
                x = x2 + 5
                y = y2 - textSize[1] - 2

            else:  # "yDistance" -- the only other mode this tracker is used in
                format = "%0." + repr(self.properties["yPosDigits"]) + "f"
                distance = format % (dist2[1] - dist1[1])
                textSize = dc.GetTextExtent(distance)
                x = x2 + 5
                y = y2 - textSize[1] - 2

            # check limits
            if x + textSize[0] > maxX:
                x = max(x1, x2) - textSize[0] - 5
            if y < minY:
                y = y2 + 2

            # draw text
            self.drawInvertedText(dc, distance, x, y, self.properties["axisFont"])

    # ----

    def drawPointTracker(self, dc):
        """Draw point tracker - follow the main plot"""

        # check cursor position
        if self.getCursorLocation() != "plot":
            return

        # check current object
        if self.currentObject is None:
            return

        # hide cursor
        self.SetCursor(wx.Cursor(wx.CURSOR_BLANK))

        # get X coordinations
        x = self.cursorPosition[2]
        y = self.cursorPosition[3]
        minY = self.plotCoords[1]
        maxY = self.plotCoords[3]

        # get Y value
        currentY = self.getPoint(x, coord="screen")

        # draw tracker lines (axisColour follows the dark/light theme)
        dc.SetPen(wx.Pen(self.properties["axisColour"]))
        # dc.SetLogicalFunction(wx.INVERT)
        if wx.Platform == "__WXMAC__":
            dc.DrawLine(int(x), int(minY), int(x), int(maxY - 1))
            if currentY:
                dc.DrawLine(int(x - 5), int(currentY[1]), int(x + 6), int(currentY[1]))
        else:
            if currentY:
                dc.DrawLine(int(x), int(minY), int(x), int(maxY))
                dc.DrawLine(int(x - 5), int(currentY[1]), int(x + 6), int(currentY[1]))
        dc.SetLogicalFunction(wx.COPY)

        # draw x position text
        if self.properties["showCurXPos"]:

            # get current x position
            format = "%0." + repr(self.properties["xPosDigits"]) + "f"
            text = format % (self.cursorPosition[0])

            # get text position
            dc.SetFont(_scaleFont(self.properties["axisFont"], self.printerScale["fonts"]))
            textSize = dc.GetTextExtent(text)
            x = x + 5
            y = y - textSize[1] - 2

            # check limits for position
            if x + textSize[0] > self.plotCoords[2]:
                x = x - textSize[0] - 10
            if y < self.plotCoords[1]:
                y = self.plotCoords[1]

            # draw text
            self.drawInvertedText(dc, text, x, y, self.properties["axisFont"])

    # ----

    def drawIsotopeRuler(self, dc):
        """Draw charge ruler."""

        # check cursor position
        if self.getCursorLocation() != "plot":
            return

        # get plot coords
        x = self.cursorPosition[2]
        y = self.cursorPosition[3]
        minXPlot = self.plotCoords[0]
        maxXPlot = self.plotCoords[2]
        minYPlot = self.plotCoords[1]
        maxYPlot = self.plotCoords[3]
        minYGel = 0
        maxYGel = 0

        # get gel coords
        if self.properties["showGel"]:
            minYGel = minYPlot - (9 * self.printerScale["drawings"])
            maxYGel = minYGel - self.gelsCount * self.properties["gelHeight"]

        if wx.Platform == "__WXMAC__":
            maxXPlot -= 1
            maxYPlot -= 1
            maxYGel += 1

        # calc isotopes
        isotopes = []
        self.currentIsotopes = []

        mz = self.cursorPosition[0]
        lines = max(3, int(mz / 300 * self.currentCharge / 2))
        if self.currentIsotopeLines < 0 and abs(self.currentIsotopeLines) >= lines:
            self.currentIsotopeLines = -1 * lines + 1
        lines += self.currentIsotopeLines

        diff = self.properties["isotopeDistance"] / self.currentCharge
        for _ in range(lines):
            self.currentIsotopes.append(mz)

            isotope = self.positionUserToScreen((mz, 0))[0]
            intensity = None
            if self.currentObject:
                point = self.getPoint(isotope, coord="screen")
                if point is not None:
                    intensity = min(point[1], maxYPlot - 5)
                    intensity = max(intensity, minYPlot + 5)

            if isotope < maxXPlot:
                isotopes.append((isotope, intensity))

            mz += diff

        # set pen (axisColour follows the dark/light theme)
        # dc.SetLogicalFunction(wx.INVERT)
        dc.SetPen(wx.Pen(self.properties["axisColour"]))

        # draw lines
        for i, isotope in enumerate(isotopes):
            if i == 0 or not isotope[1]:
                dc.DrawLine(
                    int(isotope[0]), int(minYPlot), int(isotope[0]), int(maxYPlot)
                )
            if self.properties["showGel"]:
                dc.DrawLine(
                    int(isotope[0]), int(minYGel), int(isotope[0]), int(maxYGel)
                )

        # draw circles
        if wx.Platform != "__WXMAC__":
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(self.properties["axisColour"]))
        for _i, isotope in enumerate(isotopes):
            if isotope[1]:
                dc.DrawCircle(int(isotope[0]), int(isotope[1]), int(4))

        dc.SetLogicalFunction(wx.COPY)

        # draw position text
        if self.properties["showCurCharge"]:
            chargeText = str(self.currentCharge)

            # get text position
            dc.SetFont(_scaleFont(self.properties["axisFont"], self.printerScale["fonts"]))
            textSize = dc.GetTextExtent(chargeText)
            x -= textSize[0] + 5
            y -= textSize[1] + 5

            # check limits
            if x < minXPlot:
                x += textSize[0] + 10
            if y < minYPlot:
                y += textSize[1] + 10

            # draw text
            self.drawInvertedText(dc, chargeText, x, y, self.properties["axisFont"])

    # ----

    def drawZoomBox(self, dc):
        """Draw zoom-box"""

        # get coordinations
        minX = self.draggingStart[2]
        minY = self.draggingStart[3]
        maxX = self.cursorPosition[2]
        maxY = self.cursorPosition[3]

        minXPlot = self.plotCoords[0]
        minYPlot = self.plotCoords[1]
        maxXPlot = self.plotCoords[2]
        maxYPlot = self.plotCoords[3]

        # check limits
        minX = min(minX, maxXPlot)
        minX = max(minX, minXPlot)
        minY = min(minY, maxYPlot)
        minY = max(minY, minYPlot)
        maxX = min(maxX, maxXPlot)
        maxX = max(maxX, minXPlot)
        maxY = min(maxY, maxYPlot)
        maxY = max(maxY, minYPlot)

        # get gel coords
        minYGel = maxYGel = 0
        if self.properties["showGel"]:
            minYGel = minYPlot - (8 * self.printerScale["drawings"])
            maxYGel = minYGel - self.gelsCount * self.properties["gelHeight"]

        # use DC with transparency (only needed for MSW)
        # try:
        try:
            dc = wx.GCDC(dc)
        except Exception as e:
            print("GCDC error:", e)

        # set canvas and pen (axisColour follows the dark/light theme)
        dc.SetPen(wx.Pen(self.properties["axisColour"]))
        c = self.properties["zoomBoxColour"]
        dc.SetBrush(wx.Brush(wx.Colour(c.Red(), c.Green(), c.Blue(), 80), wx.SOLID))
        dc.SetLogicalFunction(wx.COPY)

        # draw clasic zoom box
        if self.properties["zoomAxis"] == "xy":
            dc.DrawRectangle(int(minX), int(minY), int(maxX - minX), int(maxY - minY))

        # draw X-axis-zoom-only box
        elif self.properties["zoomAxis"] == "x":
            dc.DrawRectangle(
                int(minX), int(maxYPlot), int(maxX - minX), int(minYPlot - maxYPlot)
            )

        # draw Y-axis-only zoom box
        elif self.properties["zoomAxis"] == "y":
            dc.DrawRectangle(
                int(minXPlot), int(maxY), int(maxXPlot - minXPlot), int(minY - maxY)
            )

        # draw gellview zoombox
        if self.properties["showGel"] and self.properties["zoomAxis"] == "x":
            minYGel += self.printerScale["drawings"]
            maxYGel -= self.printerScale["drawings"]
            dc.DrawRectangle(
                int(minX), int(maxYGel), int(maxX - minX), int(minYGel - maxYGel)
            )

        # resset canvas and pen
        dc.SetLogicalFunction(wx.COPY)

    # ----

    def drawSelectionRect(self, dc):
        """Draw selection rectangle"""

        # get coordinations
        x1 = self.draggingStart[2]
        y1 = self.draggingStart[3]
        x2 = self.cursorPosition[2]
        y2 = self.cursorPosition[3]

        # check stop position limits
        if x2 < self.plotCoords[0]:
            x2 = self.plotCoords[0]
        elif x2 > self.plotCoords[2]:
            x2 = self.plotCoords[2] - 1
        if y2 < self.plotCoords[1]:
            y2 = self.plotCoords[1]
        elif y2 > self.plotCoords[3]:
            y2 = self.plotCoords[3] - 1

        # get width/height of zoom-box
        width = x2 - x1
        height = y2 - y1

        # draw tracker lines
        # dc.SetLogicalFunction(wx.INVERT)
        dc.SetPen(wx.Pen(self.properties["axisColour"]))
        dc.SetBrush(wx.Brush(wx.BLACK, wx.TRANSPARENT))
        dc.DrawRectangle(int(x1), int(y1), int(width), int(height))
        dc.SetLogicalFunction(wx.COPY)

    # ----

    def drawSelectionRange(self, dc):
        """Draw selection range line"""

        # get coordinations
        x1 = self.draggingStart[2]
        y1 = self.draggingStart[3]
        x2 = self.cursorPosition[2]

        # check stop position limits
        if x2 < self.plotCoords[0]:
            x2 = self.plotCoords[0]
        elif x2 > self.plotCoords[2]:
            x2 = self.plotCoords[2] - 1

        if x2 < x1:
            x1, x2 = x2, x1

        # draw tracker lines
        # dc.SetLogicalFunction(wx.INVERT)
        dc.SetPen(wx.Pen(self.properties["axisColour"]))
        dc.SetBrush(wx.Brush(wx.BLACK, wx.TRANSPARENT))
        if wx.Platform == "__WXMAC__":
            dc.DrawLine(int(x1), int(y1 - 3), int(x1), int(y1 + 3))
            dc.DrawLine(int(x1 + 1), int(y1), int(x2 - 1), int(y1))
            dc.DrawLine(int(x2), int(y1 - 3), int(x2), int(y1 + 3))
        else:
            dc.DrawLine(int(x1), int(y1 - 3), int(x1), int(y1 + 3))
            dc.DrawLine(int(x1 + 1), int(y1), int(x2), int(y1))
            dc.DrawLine(int(x2), int(y1 - 3), int(x2), int(y1 + 3))
        dc.SetLogicalFunction(wx.COPY)

    # ----

    def drawPointArrow(self, x, y, direction="up", dc=None):
        """Draw point arrow"""

        # check stop position limits
        if x < self.plotCoords[0]:
            x = self.plotCoords[0]
            direction = "left"
        elif x > self.plotCoords[2]:
            x = self.plotCoords[2] - 1
            direction = "right"

        # shift y position
        y += 1

        # set dc
        if dc is None:
            dc = wx.MemoryDC(self.plotBuffer)
            wx.CallAfter(self.Refresh, False)
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(self.properties["highlightColour"], wx.SOLID))

        # scale the arrow with the UI so it stays visible on HiDPI displays
        s = self.printerScale["drawings"]

        # draw arrow
        if direction == "up":
            dc.DrawPolygon(
                [
                    (int(p[0]), int(p[1]))
                    for p in [(x, y), (x - 3 * s, y + 7 * s), (x + 3 * s, y + 7 * s)]
                ]
            )
        elif direction == "down":
            dc.DrawPolygon(
                [
                    (int(p[0]), int(p[1]))
                    for p in [(x, y), (x - 3 * s, y - 7 * s), (x + 3 * s, y - 7 * s)]
                ]
            )
        elif direction == "left":
            dc.DrawPolygon(
                [
                    (int(p[0]), int(p[1]))
                    for p in [(x + 7 * s, y + 2 * s), (x, y + 5 * s), (x + 7 * s, y + 8 * s)]
                ]
            )
        elif direction == "right":
            dc.DrawPolygon(
                [
                    (int(p[0]), int(p[1]))
                    for p in [(x - 7 * s, y + 2 * s), (x, y + 5 * s), (x - 7 * s, y + 8 * s)]
                ]
            )

    # ----

    def drawInvertedText(self, dc, text, x, y, font):
        """Special function for drawing inverted text"""

        # draw normal text using the axis colour so it respects dark mode
        dc.SetTextForeground(self.properties["axisColour"])
        # Callers pass the unscaled axisFont; scale it like the axis labels so
        # tracker readouts (cursor m/z + intensity, distance, charge) track the
        # UI/DPI scale instead of staying tiny on HiDPI.
        dc.SetFont(_scaleFont(font, self.printerScale["fonts"]))
        dc.DrawText(text, int(x), int(y))

    # ----

    def refresh(self, fullsize=False):
        """Redraw plot with the same data and same scale or fullsize"""

        # get last ranges
        graphics = self.lastDraw[0]
        xAxis, yAxis = self.lastDraw[1], self.lastDraw[2]

        # check limits
        if self.properties["checkLimits"]:
            minX, maxX = self.getMaxXRange()
            if minX <= xAxis[0] <= maxX:
                minX = xAxis[0]
            if minX <= xAxis[1] <= maxX:
                maxX = xAxis[1]
            xAxis = (minX, maxX)

        # check Y symmetry
        if self.properties["ySymmetry"]:
            maxY = max(abs(yAxis[0]), abs(yAxis[1]))
            yAxis = (-1 * maxY, maxY)

        # redraw plot with the same scale
        if not fullsize:
            if self.properties["autoScaleY"]:
                yAxis = self.getMaxYRange(xAxis[0], xAxis[1])
            self.draw(graphics, xAxis, yAxis)

        # redraw plot with fullsize
        else:
            minXY, maxXY = graphics.getBoundingBox()
            xAxis = (minXY[0], maxXY[0])
            yAxis = (minXY[1], maxXY[1])

            # redraw
            self.draw(graphics, xAxis, yAxis)

            # remember new zoom
            self.rememberView(xAxis, yAxis)

    # ----

    def quickRefresh(self, dc):

        dc.DrawBitmap(self.cleanPlotBuffer, 0, 0)

        if getattr(self, "highlightedPoints", None):
            y = self.plotCoords[3]
            for point in self.highlightedPoints:
                x = self.positionUserToScreen((point, 0))[0]
                self.drawPointArrow(x, y, dc=dc)

    # ----

    def clear(self):
        """Clear plot window"""

        dc = wx.MemoryDC(self.plotBuffer)
        wx.CallAfter(self.Refresh, False)
        dc.SetBackground(wx.Brush(self.properties["canvasColour"], wx.SOLID))
        dc.Clear()
        self.lastDraw = None

    # ----

    def zoom(self, xAxis=None, yAxis=None, dc=None):
        """Zoom plot to selected range"""

        # set X axis
        if xAxis is None:
            xAxis = self.getCurrentXRange()
        elif self.properties["checkLimits"]:
            minX, maxX = self.getMaxXRange()
            minX = max(xAxis[0], minX)
            maxX = min(xAxis[1], maxX)
            xAxis = (minX, maxX)

            # check max zoom
            if (xAxis[1] - xAxis[0]) < self.properties["maxZoom"]:
                xAxis = self.getCurrentXRange()

        # set Y axis
        if yAxis is None:
            if self.properties["autoScaleY"]:
                yAxis = self.getMaxYRange(xAxis[0], xAxis[1])
            else:
                yAxis = self.getCurrentYRange()
        else:

            # check Y axis
            if yAxis[1] < yAxis[0]:
                yAxis = (yAxis[1], yAxis[0])

        # draw plot
        if xAxis is not None or yAxis is not None:
            self.draw(self.lastDraw[0], xAxis, yAxis, dc)
            self.rememberView(xAxis, yAxis)

    # ----

    def highlightXPoints(self, points, zoom=False, anchor=None):
        """Move plot to see selected X position and show pointarrow"""

        self.highlightedPoints = points

        # check points
        if not points:
            dc = wx.MemoryDC(self.plotBuffer)
            self.quickRefresh(dc)
            wx.CallAfter(self.Refresh, False)
            return

        # ensure visible
        self.ensureVisible(points, zoom, anchor)

        # quick refresh to draw point-arrow
        dc = wx.MemoryDC(self.plotBuffer)
        self.quickRefresh(dc)
        wx.CallAfter(self.Refresh, False)

    # ----

    def ensureVisible(self, points, zoom=False, anchor=None):
        """Move plot to see selected X position

        With an anchor (e.g. the labelled monoisotopic peak of an envelope) the
        view is centred on that anchor instead of on the middle of the point
        set, and only widens if the remaining points do not fit around it -- so
        an isotopic envelope stays pinned to its monoisotopic peak and zooms out
        just enough to show the isotopes trailing off to the right.
        """

        # check points
        if not points:
            return

        # get center
        minX = min(points)
        maxX = max(points)
        center = minX + (maxX - minX) / 2

        # set X range
        if zoom:
            minX = min(points) - center * zoom / 100
            maxX = max(points) + center * zoom / 100
        elif anchor is not None:
            xRange = self.getCurrentXRange()
            current_width = xRange[1] - xRange[0]

            # keep the anchor centred and widen symmetrically only as far as
            # needed to fit the outermost point (plus a small margin so it is
            # not drawn right at the edge)
            halfWidth = current_width / 2
            halfWidth = max(halfWidth, (maxX - anchor) * self.ANCHOR_MARGIN)
            halfWidth = max(halfWidth, (anchor - minX) * self.ANCHOR_MARGIN)

            minX = anchor - halfWidth
            maxX = anchor + halfWidth
        else:
            xRange = self.getCurrentXRange()
            current_width = xRange[1] - xRange[0]
            if max(points) - min(points) > current_width:
                minX = min(points) - current_width / 2
                maxX = max(points) + current_width / 2
            else:
                minX = center - current_width / 2
                maxX = center + current_width / 2

        # check overscaling
        xRangeMax = self.getMaxXRange()
        if minX < xRangeMax[0]:
            diff = xRangeMax[0] - minX
            minX = xRangeMax[0]
            maxX += diff
        if maxX > xRangeMax[1]:
            diff = maxX - xRangeMax[1]
            maxX = xRangeMax[1]
            minX -= diff
        if minX < xRangeMax[0]:
            minX = xRangeMax[0]
        if maxX > xRangeMax[1]:
            maxX = xRangeMax[1]

        # check errors
        if minX == maxX:
            minX, maxX = xRangeMax

        # autoscale Y axis
        if self.properties["autoScaleY"]:
            yRange = self.getMaxYRange(minX, maxX)
        else:
            yRange = self.getCurrentYRange()

        # redraw plot
        self.draw(self.lastDraw[0], (minX, maxX), (yRange[0], yRange[1]))

        # remember view
        self.rememberView((minX, maxX), (yRange[0], yRange[1]))

    # ----

    def makeAxisTicks(self, lower, upper):
        """Count axis ticks"""

        # calculate major ticks
        ideal = (upper - lower) / 7.0
        log = numpy.log10(ideal)
        power = numpy.floor(log)
        fraction = log - power
        factor = 1.0
        error = fraction
        multiples = [(3.0, numpy.log10(2.0)), (5.0, numpy.log10(5.0))]

        f = 1.0
        for f, lf in multiples:
            e = numpy.fabs(fraction - lf)
            if e < error:
                error = e
                factor = f
        majorGrid = factor * 10.0**power
        if factor == 1.0:
            factor = f

        # calculate minor ticks
        log = numpy.log10(majorGrid / 2.0)
        rnd = int(abs(numpy.floor(log)))
        minorGrid = round(majorGrid / factor, rnd)

        # set label format
        if power > 4 or power < -4:
            format = "%7.1e"
        elif power >= 0:
            digits = max(1, int(power))
            format = "%" + repr(digits) + ".0f"
        else:
            digits = -int(power)
            format = "%" + repr(digits + 2) + "." + repr(digits) + "f"

        # make ticks
        t = -majorGrid * numpy.floor(-lower / majorGrid) - 5 * minorGrid
        i = -5
        loop_guard = 0
        while t < lower and loop_guard < 1000:
            prev_t = t
            t = round(t + minorGrid, rnd)
            i += 1
            loop_guard += 1
            if t <= prev_t:
                break

        ticks = []
        loop_guard = 0
        while t <= upper and loop_guard < 1000:
            ttype = "minor"
            if i == 0 or (minorGrid > 0 and i == int(majorGrid / minorGrid)):
                ttype = "major"
                i = 0
            ticks.append((t, format % (t,), ttype))
            prev_t = t
            t += minorGrid
            i += 1
            loop_guard += 1
            if t <= prev_t:
                break

        return ticks

    # ----

    def escMouseEvents(self):
        """Escape any mouse events function."""

        # # clear zoombox
        # if self.mouseEvent == "zoom":
        #     self.drawZoomBox()

        # # clear point tracker
        # elif self.mouseEvent == "point":
        #     self.drawPointTracker()

        # # clear isotope ruler
        # elif self.mouseEvent == "isotopes":
        #     self.drawIsotopeRuler()

        # # clear selection rectangle
        # elif self.mouseEvent == "rectangle":
        #     self.drawSelectionRect()

        # # clear selection range
        # elif self.mouseEvent == "range":
        #     self.drawSelectionRange()

        # # clear distance arrow
        # elif self.mouseEvent == "distance":
        #     self.drawDistanceTracker()

        # reset mouse event flag
        self.mouseEvent = False

        # reset drgging start
        self.draggingStart = False

    # ----

    def shiftAxis(self, axis, dc=None):
        """Shift plot while dragging; True when the plot was redrawn."""

        # skip y shift symmetric
        if axis == "y" and self.properties["ySymmetry"]:
            return False

        # get coordionations
        minX, maxX = self.getCurrentXRange()
        minY, maxY = self.getCurrentYRange()
        rangeXmin, rangeXmax = self.getMaxXRange()
        rangeYmin, rangeYmax = self.getMaxYRange()

        # shift axis
        if axis == "x":
            shift = self.draggingStart[0] - self.cursorPosition[0]
            minX += shift
            maxX += shift
        elif axis == "y":
            shift = self.draggingStart[1] - self.cursorPosition[1]
            minY += shift
            maxY += shift

        # check limits
        if self.properties["checkLimits"]:
            if axis == "x" and (minX < rangeXmin or maxX > rangeXmax):
                return False
            if axis == "y" and (minY < rangeYmin or maxY > rangeYmax):
                return False

        # autoscale Y
        if self.properties["autoScaleY"] and axis == "x":
            minY, maxY = self.getMaxYRange(minX, maxX)

        # redraw plot
        self.draw(self.lastDraw[0], (minX, maxX), (minY, maxY), dc=dc)
        return True

    # ----

    def movePositionBar(self, axis, dc=None):
        """Follow a click/drag on the position bar; True when it redrew."""

        if axis == "x":
            if not self.xPosBarBox:
                return False
            bx, by, bw, bh = self.xPosBarBox
            rangeMin, rangeMax = self.getMaxXRange(absolute=True)
            if bw <= 0 or rangeMax == rangeMin:
                return False

            # map cursor along the bar to a target center position
            frac = (self.cursorPosition[2] - bx) / bw
            frac = min(max(frac, 0.0), 1.0)
            target = rangeMin + frac * (rangeMax - rangeMin)

            # keep the current window width, centered on the target
            minX, maxX = self.getCurrentXRange()
            half = (maxX - minX) / 2.0
            minX, maxX = target - half, target + half

            # clamp to data range, preserving width
            if minX < rangeMin:
                maxX += rangeMin - minX
                minX = rangeMin
            if maxX > rangeMax:
                minX -= maxX - rangeMax
                maxX = rangeMax
            minX = max(minX, rangeMin)
            maxX = min(maxX, rangeMax)

            # autoscale Y to the new window
            minY, maxY = self.getCurrentYRange()
            if self.properties["autoScaleY"]:
                minY, maxY = self.getMaxYRange(minX, maxX)

            self.draw(self.lastDraw[0], (minX, maxX), (minY, maxY), dc=dc)
            return True

        elif axis == "y":
            if not self.yPosBarBox or self.properties["ySymmetry"]:
                return False
            bx, by, bw, bh = self.yPosBarBox
            rangeMin, rangeMax = self.getMaxYRange(absolute=True)
            if bh <= 0 or rangeMax == rangeMin:
                return False

            # bar maps top -> maxY, bottom -> minY
            frac = (self.cursorPosition[3] - by) / bh
            frac = min(max(frac, 0.0), 1.0)
            target = rangeMax - frac * (rangeMax - rangeMin)

            # keep the current window height, centered on the target
            minY, maxY = self.getCurrentYRange()
            half = (maxY - minY) / 2.0
            minY, maxY = target - half, target + half

            # clamp to data range, preserving height
            if minY < rangeMin:
                maxY += rangeMin - minY
                minY = rangeMin
            if maxY > rangeMax:
                minY -= maxY - rangeMax
                maxY = rangeMax
            minY = max(minY, rangeMin)
            maxY = min(maxY, rangeMax)

            minX, maxX = self.getCurrentXRange()
            self.draw(self.lastDraw[0], (minX, maxX), (minY, maxY), dc=dc)
            return True

        return False

    # ----

    def scaleAxis(self, axis, dc=None):
        """Scale plot while dragging; True when the plot was redrawn."""

        # get coordination
        minX, maxX = self.getCurrentXRange()
        minY, maxY = self.getCurrentYRange()

        # scale x axis from its start
        if axis == "x":
            shift = self.draggingStart[0] - self.cursorPosition[0]
            maxX += shift

            # check max zoom
            if (maxX - minX) < self.properties["maxZoom"]:
                maxX = minX + self.properties["maxZoom"]

            # check limits
            if self.properties["checkLimits"]:
                rangeXmin, rangeXmax = self.getMaxXRange()
                if minX < rangeXmin:
                    minX = rangeXmin
                if maxX > rangeXmax:
                    maxX = rangeXmax

            # autoscale y
            if self.properties["autoScaleY"]:
                minY, maxY = self.getMaxYRange(minX, maxX)

        # scale y axis from its start
        elif axis == "y":
            shift = self.draggingStart[1] - self.cursorPosition[1]
            if self.properties["ySymmetry"] and self.draggingStart[1] < 0:
                minY += shift
                maxY -= shift
            elif self.properties["ySymmetry"]:
                minY -= shift
                maxY += shift
            else:
                maxY += shift

        # redraw plot
        self.draw(self.lastDraw[0], (minX, maxX), (minY, maxY), dc=dc)
        return True

    # ----

    def rememberView(self, xAxis=None, yAxis=None):
        """Remember current zoom."""

        # get axis
        if xAxis is None:
            xAxis = self.getCurrentXRange()
        if yAxis is None:
            yAxis = self.getCurrentYRange()

        # remember current zoom
        if not self.viewMemory[0] or self.viewMemory[0][-1] != (xAxis, yAxis):
            self.viewMemory[0].append((xAxis, yAxis))

        # check max memory length
        if len(self.viewMemory[0]) > 50:
            del self.viewMemory[0][0]

        # delete forth views
        self.viewMemory[1] = []

    # ----

    def positionUserToScreen(self, userPos):
        """Convert user position to screen coordinates"""

        userPos = numpy.array(userPos)
        x, y = userPos * self.pointScale + self.pointShift
        return x, y

    # ----

    def positionScreenToUser(self, screenPos):
        """Convert screen position to user coordinates"""

        screenPos = numpy.array(screenPos)
        x, y = (screenPos - self.pointShift) / self.pointScale
        return x, y

    # ----

    def pointToClientCoord(self, corner1, corner2):
        """Convert user coords to client screen coords x,y,width,height"""

        c1 = numpy.array(corner1)
        c2 = numpy.array(corner2)

        # convert to screen coords
        pt1 = c1 * self.pointScale + self.pointShift
        pt2 = c2 * self.pointScale + self.pointShift

        # make height and width positive
        pointUpperLeft = numpy.minimum(pt1, pt2)
        pointLowerRight = numpy.maximum(pt1, pt2)
        rectWidth, rectHeight = pointLowerRight - pointUpperLeft
        pointX, pointY = pointUpperLeft

        return round(pointX), round(pointY), round(rectWidth), round(rectHeight)

    # ----


class printout(wx.Printout):
    """Controls how the plot is made in printing and previewing."""

    def __init__(self, graph, filterSize, title="mMass Spectrum"):
        wx.Printout.__init__(self, title)
        self.graph = graph
        self.filterSize = filterSize

    # ----

    def HasPage(self, pageNum):
        if pageNum == 1:
            return True
        else:
            return False

    # ----

    def GetPageInfo(self):
        """Disable page numbers."""
        return (1, 1, 1, 1)

    # ----

    def OnPrintPage(self, pageNum):
        """Get and format data to print."""

        # get DC
        dc = self.GetDC()
        dcSize = dc.GetSize()

        # get page
        PPIPrinter = self.GetPPIPrinter()
        pageSize = self.GetPageSizePixels()

        # calculate offset and scale for dc
        pixLeft = PPIPrinter[0] / 25.4  # mm*(dots/in)/(mm/in)
        pixRight = PPIPrinter[0] / 25.4
        pixTop = PPIPrinter[1] / 25.4
        pixBottom = PPIPrinter[1] / 25.4

        plotAreaW = pageSize[0] - (pixLeft + pixRight)
        plotAreaH = pageSize[1] - (pixTop + pixBottom)

        # ratio offset and scale to screen size if preview
        if self.IsPreview():
            ratioW = float(dcSize[0]) / pageSize[0]
            ratioH = float(dcSize[1]) / pageSize[1]
            pixLeft *= ratioW
            pixTop *= ratioH
            plotAreaW *= ratioW
            plotAreaH *= ratioH
            self.filterSize = 1

        # rescale plot to page or preview plot area
        self.graph.setSize(plotAreaW, plotAreaH)

        # set offset and scale
        dc.SetDeviceOrigin(int(pixLeft), int(pixTop))

        # thicken up pens and fonts for printing
        ratioW = float(plotAreaW) / 900
        ratioH = float(plotAreaH) / 900
        scale = min(ratioW, ratioH)
        if not self.IsPreview():
            scale = max(scale, 2.5)
        self.graph.setPrinterScale(drawings=scale, fonts=_print_font_scale(scale))

        # print plot
        self.graph.drawOutside(dc, self.filterSize)

        # revert all back to original
        self.graph.setSize()
        self.graph.setPrinterScale()
        self.graph.refresh()

        return True

    # ----


# HEPLERS
# -------


# Legacy print/export legibility boost: when rendering to a printer or an
# exported bitmap the axis fonts were enlarged by this factor on top of the
# geometric scale. It must NOT be applied to on-screen UI scaling, or canvas
# fonts come out ~30% larger than the selected scale.
_PRINT_FONT_BOOST = 1.3


def _print_font_scale(scale):
    """Apply the print/export font legibility boost, but only when rescaling."""

    if scale == 1:
        return scale
    return scale * _PRINT_FONT_BOOST


def _scaleFont(font, scale):
    """Return a copy of font scaled linearly by scale."""

    # check scale
    if scale == 1:
        return font

    # get font
    pointSize = font.GetPointSize()
    family = font.GetFamily()
    style = font.GetStyle()
    weight = font.GetWeight()
    underline = font.GetUnderlined()
    faceName = font.GetFaceName()
    encoding = font.GetDefaultEncoding()

    # scale pointSize
    pointSize = int(round(pointSize * scale))

    # make print font
    printerFont = wx.Font(
        pointSize, family, style, weight, underline, faceName, encoding
    )

    return printerFont


# ----
