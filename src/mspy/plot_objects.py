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
import copy

# load modules
from . import mod_signal
from . import calculations


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
            winreg = __import__("winreg")
            open_key = winreg.OpenKey
            query_value_ex = winreg.QueryValueEx
            hkey_current_user = winreg.HKEY_CURRENT_USER

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with open_key(hkey_current_user, key_path) as key:
                value, _ = query_value_ex(key, "AppsUseLightTheme")
                return int(value) == 0
        except Exception:
            pass

    # Fallback: infer from current window background colour.
    # wx.SystemSettings may require an active wx.App; fail safely during import.
    try:
        bg = wx.SystemSettings.GetColour(int(wx.SYS_COLOUR_WINDOW))
        luminance = 0.299 * bg.Red() + 0.587 * bg.Green() + 0.114 * bg.Blue()
        return luminance < 128
    except Exception:
        return False


_DARK_MODE = None

# wxPython classic constants are missing in modern stubs; keep runtime compatibility.
_WX_PENSTYLE_SOLID = getattr(wx, "PENSTYLE_SOLID", getattr(wx, "SOLID", 100))
_WX_BRUSHSTYLE_SOLID = getattr(wx, "BRUSHSTYLE_SOLID", getattr(wx, "SOLID", 100))
_WX_BRUSHSTYLE_TRANSPARENT = getattr(
    wx, "BRUSHSTYLE_TRANSPARENT", getattr(wx, "TRANSPARENT", 0)
)
_WX_FONTFAMILY_SWISS = getattr(
    wx, "FONTFAMILY_SWISS", getattr(wx, "SWISS", 74)
)


def _is_dark_mode_cached():
    """Return dark-mode state, caching once it can be safely resolved."""

    global _DARK_MODE
    if _DARK_MODE is not None:
        return _DARK_MODE

    # Defer evaluation until wx.App exists to avoid import-time crashes.
    if wx.GetApp() is None:
        return False

    _DARK_MODE = _is_dark_mode()
    return _DARK_MODE


def invalidate_dark_mode_cache():
    """Forget the cached dark-mode state.

    The cache above is resolved once and then kept for the process lifetime,
    which is what stops the plot from following a light/dark switch made while
    the app is running.  The canvas calls this from its wxEVT_SYS_COLOUR_CHANGED
    handler so the next redraw asks the system again.
    """

    global _DARK_MODE
    _DARK_MODE = None


def force_dark_mode(dark):
    """Draw plot objects for the given theme instead of the system's.

    For images made outside the GUI, which choose their own background.
    """

    global _DARK_MODE
    _DARK_MODE = bool(dark)


def apply_theme_label_colours(properties):
    """Set a plot object's label colours for the current system theme.

    The labels are drawn on an opaque badge, so both the text and its backing
    have to flip with the theme.  Kept out of the objects themselves because
    both the annotation and the spectrum object need exactly this, and because
    a live light/dark switch has to be able to redo it on objects that were
    built under the previous theme (see plot_canvas.onSysColourChanged).
    """

    if _is_dark_mode_cached():
        properties["labelColour"] = (220, 220, 220)
        properties["labelBgrColour"] = (30, 30, 30)
    else:
        properties["labelColour"] = (0, 0, 0)
        properties["labelBgrColour"] = (255, 255, 255)


# MAIN PLOT OBJECTS
# -----------------


class container:
    """Container to hold plot objects."""

    def __init__(self, objects):
        self.objects = objects

    # ----

    def applyThemeColours(self):
        """Re-theme every object that draws colours of its own."""

        for obj in self.objects:
            apply = getattr(obj, "applyThemeColours", None)
            if apply is not None:
                apply()

    # ----

    def __additem__(self, obj):
        self.objects.append(obj)

    # ----

    def __delitem__(self, index):
        del self.objects[index]

    # ----

    def __setitem__(self, index, obj):
        self.objects[index] = obj

    # ----

    def __getitem__(self, index):
        return self.objects[index]

    # ----

    def __len__(self):
        return len(self.objects)

    # ----

    def getBoundingBox(self, minX=None, maxX=None, absolute=False):
        """Get bounding box coverring all visible objects."""

        # init values if no data in objects
        rect = [numpy.array([0, 0]), numpy.array([1, 1])]

        # get bouding boxes from objects
        have = False
        for obj in self.objects:
            if obj.properties["visible"]:
                oRect = obj.getBoundingBox(minX, maxX, absolute)

                if not oRect or not numpy.all(numpy.isfinite(oRect)):
                    continue
                elif have and oRect:
                    rect[0] = numpy.minimum(rect[0], oRect[0])
                    rect[1] = numpy.maximum(rect[1], oRect[1])
                elif oRect:
                    rect = oRect
                    have = True

        # check scale
        if rect[0][0] == rect[1][0]:
            rect[0][0] -= 0.5
            rect[1][0] += 0.5
        if rect[0][1] == rect[1][1]:
            rect[1][1] += 0.5

        return rect

    # ----

    def getLegend(self):
        """Get a list of legend names."""

        # get names
        names = []
        for obj in self.objects:
            if obj.properties["visible"]:
                legend = obj.getLegend()
                if legend and legend[0] != "":
                    names.append(obj.getLegend())

        return names

    # ----

    def getPoint(self, obj, xPos, coord="screen"):
        """Get interpolated Y position for given X."""
        return self.objects[obj].getPoint(xPos, coord)

    # ----

    def countGels(self):
        """Get number of visible gels."""

        count = 0
        for obj in self.objects:
            if obj.properties["visible"] and obj.properties["showInGel"]:
                count += 1

        return max(count, 1)

    # ----

    def cropPoints(self, minX, maxX):
        """Crop points in all visible objects to selected X range."""

        for obj in self.objects:
            if obj.properties["visible"]:
                obj.cropPoints(minX, maxX)

    # ----

    def scaleAndShift(self, scale, shift, filterSize=None):
        """Scale and shift all visible objects."""

        for obj in self.objects:
            if obj.properties["visible"]:
                obj.scaleAndShift(scale, shift, filterSize)

    # ----

    def filterPoints(self, filterSize):
        """Filter points in all visible objects."""

        for obj in self.objects:
            if obj.properties["visible"]:
                obj.filterPoints(filterSize)

    # ----

    def draw(self, dc, printerScale, overlapLabels, reverse):
        """Draw all visible objects."""

        # draw in reverse order
        if reverse:
            self.objects.reverse()

        # draw objects
        for obj in self.objects:
            if obj.properties["visible"]:
                obj.draw(dc, printerScale)

        # place the objects' labels, then what goes over them (difference
        # rulers), which keeps its text off them where it can; text that
        # cannot is drawn first, under the labels
        labels = self.planLabels(dc, printerScale, overlapLabels)
        overlays = []
        for obj in self.objects:
            if obj.properties["visible"] and hasattr(obj, "layoutOverlays"):
                overlays.append((obj, obj.layoutOverlays(dc, printerScale, self.labelBoxes)))
        for obj, layouts in overlays:
            obj.paintOverlays(dc, printerScale, layouts, "under")
        self.paintLabels(dc, printerScale, labels)
        for obj, layouts in overlays:
            obj.paintOverlays(dc, printerScale, layouts, "over")

        # reverse back order
        if reverse:
            self.objects.reverse()

    # ----

    def drawLabels(self, dc, printerScale, overlapLabels):
        """Draw labels for all visible objects."""

        self.paintLabels(dc, printerScale, self.planLabels(dc, printerScale, overlapLabels))

    # ----

    def planLabels(self, dc, printerScale, overlapLabels):
        """Labels of all visible objects that get drawn, strongest first.

        Unless overlapLabels, a label that would land on one already placed
        is left out. The boxes of those placed, as (left, top, right, bottom)
        on screen, are kept in labelBoxes.
        """

        self.labelBoxes = []

        # get labels from objects
        annots = []
        labels = []
        for obj in self.objects:
            if obj.properties["visible"] and isinstance(obj, annotations):
                annots += obj.makeLabels(dc, printerScale)
            elif obj.properties["visible"]:
                labels += obj.makeLabels(dc, printerScale)

        # sort labels
        annots.sort(key=lambda x: x[0], reverse=True)
        labels.sort(key=lambda x: x[0], reverse=True)
        labels = annots + labels

        # check free space
        placed = []
        occupied = []
        for label in labels:
            textCoords = label[2]

            # check limits
            if textCoords is None or abs(textCoords[1]) > 10000000:
                continue

            if overlapLabels or self._checkFreeSpace(textCoords, occupied):
                placed.append(label)
                occupied.append(textCoords)
                x1, y1, x2, y2 = textCoords
                self.labelBoxes.append((min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)))

        return placed

    # ----

    def paintLabels(self, dc, printerScale, labels):
        """Draw labels placed by planLabels."""

        # check labels
        if not labels:
            return

        # preset font by first label
        font = labels[0][3]["labelFont"]
        colour = labels[0][3]["labelColour"]
        bgr = labels[0][3]["labelBgr"]
        bgrColour = labels[0][3]["labelBgrColour"]

        scaledFont = _scaleFont(font, printerScale["fonts"])
        dc.SetFont(scaledFont)
        dc.SetTextForeground(colour)
        dc.SetTextBackground(bgrColour)

        if bgr:
            dc.SetBackgroundMode(_WX_BRUSHSTYLE_SOLID)

        # The badge cache only applies to the on-screen buffer; an SVG or
        # printer DC has to keep its labels as real text. Everything that can
        # change how a badge looks goes into the key, which is rebuilt only
        # when one of those actually changes -- per label it is a tuple concat.
        cacheable = isinstance(dc, wx.MemoryDC)
        scale = dc.GetContentScaleFactor() if cacheable else 1.0

        def keyBase():
            if not cacheable or not bgr:
                return None
            return (
                scaledFont.GetNativeFontInfoDesc(),
                tuple(colour),
                tuple(bgrColour),
                scale,
            )

        badgeBase = keyBase()

        # draw labels
        for label in labels:
            text = label[1]
            textCoords = label[2]
            properties = label[3]

            # check pen
            if properties["labelFont"] != font:
                font = properties["labelFont"]
                scaledFont = _scaleFont(font, printerScale["fonts"])
                dc.SetFont(scaledFont)
                badgeBase = keyBase()

            if properties["labelColour"] != colour:
                colour = properties["labelColour"]
                dc.SetTextForeground(colour)
                badgeBase = keyBase()

            # if properties['labelBgrColour'] != bgrColour:
            #    bgrColour = properties['labelBgrColour']
            #    dc.SetTextBackground(bgrColour)

            if properties["labelBgr"] != bgr:
                bgr = properties["labelBgr"]
                if bgr:
                    dc.SetBackgroundMode(_WX_BRUSHSTYLE_SOLID)
                else:
                    dc.SetBackgroundMode(_WX_BRUSHSTYLE_TRANSPARENT)
                badgeBase = keyBase()

            # set angle
            angle = properties["labelAngle"]
            if angle == 90 and properties["flipped"]:
                angle = -90

            # draw label
            badge = None
            if badgeBase is not None and angle in _LABEL_ANGLES:
                badge = badgeBase + (angle,)

            _drawLabel(
                dc,
                badge,
                text,
                int(textCoords[0]),
                int(textCoords[1]),
                angle,
                scaledFont,
                colour,
                bgrColour,
                scale,
            )

        dc.SetBackgroundMode(_WX_BRUSHSTYLE_TRANSPARENT)

    # ----

    def drawGel(self, dc, gelCoords, gelHeight, printerScale):
        """Draw gel for all allowed objects."""

        # draw objects
        for obj in self.objects:
            if obj.properties["visible"] and obj.properties["showInGel"]:
                obj.drawGel(dc, gelCoords, gelHeight, printerScale)
                gelCoords[0] += gelHeight

    # ----

    def append(self, obj):
        self.objects.append(obj)

    # ----

    def insert(self, index, obj):
        self.objects.insert(index, obj)

    # ----

    def empty(self):
        del self.objects[:]

    # ----

    def _checkFreeSpace(self, coords, occupied):
        """Check free space for label."""

        curX1, curY1, curX2, curY2 = coords

        # check occupied space
        for occX1, occY1, occX2, occY2 in occupied:
            if (curX1 < curX2) and (
                (occX1 <= curX1 <= occX2)
                or (occX1 <= curX2 <= occX2)
                or (curX1 <= occX1 and curX2 >= occX2)
            ):
                if (
                    (occY2 <= curY1 <= occY1)
                    or (occY2 <= curY2 <= occY1)
                    or (curY1 >= occY1 and curY2 <= occY2)
                ):
                    return False
            elif (curX1 > curX2) and (
                (occX2 <= curX1 <= occX1)
                or (occX2 <= curX2 <= occX1)
                or (curX1 <= occX2 and curX2 >= occX1)
            ):
                if (
                    (occY1 <= curY1 <= occY2)
                    or (occY1 <= curY2 <= occY2)
                    or (curY1 >= occY2 and curY2 <= occY1)
                ):
                    return False

        return True

    # ----


class annotations:
    """Base class for annotations drawing."""

    def __init__(self, points, **attr):

        # set default params
        self.properties = {
            "visible": True,
            "flipped": False,
            "xOffset": 0,
            "yOffset": 0,
            "normalized": False,
            "showInGel": False,
            "exactFit": False,
            "showPoints": True,
            "showLabels": True,
            "showXPos": True,
            "pointColour": (0, 0, 255),
            "pointSize": 3,
            "labelAngle": 90,
            "labelBgr": True,
            "labelColour": (0, 0, 0),
            "labelBgrColour": (255, 255, 255),
            "labelFont": wx.Font(
                10,
                _WX_FONTFAMILY_SWISS,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_NORMAL,
                False,
            ),
            "labelMaxLength": 20,
            "xPosDigits": 2,
        }

        self.currentScale = (1.0, 1.0)
        self.currentShift = (0.0, 0.0)
        self.normalization = 1.0

        # get new attributes
        for name, value in list(attr.items()):
            self.properties[name] = value

        # convert points to array
        self.points = numpy.array([[p[0], p[1]] for p in points])
        self.applyThemeColours()

        self.pointsCropped = self.points
        self.pointsScaled = self.pointsCropped
        if len(self.points):
            self.pointsBox = (
                numpy.array([numpy.min(self.points[:, 0]), numpy.min(self.points[:, 1])]),
                numpy.array([numpy.max(self.points[:, 0]), numpy.max(self.points[:, 1])]),
            )

        # get labels
        self.labels = [""] * len(points)
        for x, point in enumerate(points):
            if len(point) > 2:
                self.labels[x] = point[2]
        self.labelsCropped = self.labels

        # calculate normalization
        self._normalization()

    # ----

    def applyThemeColours(self):
        """Set the label colours for the current system theme.

        Called at construction and again whenever the system switches between
        light and dark, so labels drawn under the previous theme are not left
        as dark text on a dark badge (or the reverse).
        """

        apply_theme_label_colours(self.properties)

    # ----

    def setProperties(self, **attr):
        """Set object properties."""

        for name, value in list(attr.items()):
            self.properties[name] = value

    # ----

    def setNormalization(self, value):
        """Force specified normalization to be used insted of calculated one."""

        value = float(value)
        if value == 0.0:
            value = 1.0

        self.normalization = value

    # ----

    def getBoundingBox(self, minX=None, maxX=None, absolute=False):
        """Get bounding box for whole data or X selection"""

        # use relevant data
        if minX is not None and maxX is not None:
            self.cropPoints(minX, maxX)
            data = self.pointsCropped
        else:
            data = self.points

        # check data
        if not len(data):
            return False

        # get range
        if minX is not None and maxX is not None:
            minXY = numpy.array([numpy.min(data[:, 0]), numpy.min(data[:, 1])])
            maxXY = numpy.array([numpy.max(data[:, 0]), numpy.max(data[:, 1])])
        else:
            minXY = [self.pointsBox[0][0], self.pointsBox[0][1]]
            maxXY = [self.pointsBox[1][0], self.pointsBox[1][1]]

        # extend values slightly to fit data
        if not absolute and not self.properties["exactFit"]:
            xExtend = (maxXY[0] - minXY[0]) * 0.05
            yExtend = (maxXY[1] - minXY[1]) * 0.05
            minXY[0] -= xExtend
            maxXY[0] += xExtend
            minXY[1] -= yExtend
            maxXY[1] += yExtend

        # extend values to fit labels
        elif not absolute:
            if self.properties["showLabels"] and self.properties["labelAngle"] == 0:
                maxXY[1] += (maxXY[1] - minXY[1]) * 0.2
            elif self.properties["showLabels"] and self.properties["labelAngle"] == 90:
                maxXY[1] += (maxXY[1] - minXY[1]) * 0.4
            else:
                maxXY[1] += (maxXY[1] - minXY[1]) * 0.05

        # apply normalization
        if self.properties["normalized"]:
            minXY[1] = minXY[1] / self.normalization
            maxXY[1] = maxXY[1] / self.normalization

        # apply offset
        minXY[0] += self.properties["xOffset"]
        minXY[1] += self.properties["yOffset"]
        maxXY[0] += self.properties["xOffset"]
        maxXY[1] += self.properties["yOffset"]

        # apply flipping
        if self.properties["flipped"]:
            minY = -1 * maxXY[1]
            maxY = -1 * minXY[1]
            minXY[1] = minY
            maxXY[1] = maxY

        return [minXY, maxXY]

    # ----

    def getLegend(self):
        """Get legend."""
        return None

    # ----

    def cropPoints(self, minX, maxX):
        """Crop points to selected X range."""

        # apply offset
        minX -= self.properties["xOffset"]
        maxX -= self.properties["xOffset"]

        # get indexes of points in selection
        i1 = mod_signal.locate(self.points, minX)
        i2 = mod_signal.locate(self.points, maxX)

        # crop data
        self.pointsCropped = self.points[i1:i2]
        self.labelsCropped = self.labels[i1:i2]

    # ----

    def scaleAndShift(self, scale, shift, filterSize=None):
        """Scale and shift points to screen coordinations."""

        self.pointsScaled = self.pointsCropped

        xScale = scale[0]
        yScale = scale[1]
        xShift = shift[0]
        yShift = shift[1]

        # apply flipping
        if self.properties["flipped"]:
            yScale *= -1

        # apply normalization
        if self.properties["normalized"]:
            yScale /= self.normalization

        # apply offset
        xShift += self.properties["xOffset"] * xScale
        yShift += self.properties["yOffset"] * yScale

        # recalculate data
        self.pointsScaled = _scaleAndShift(
            self.pointsCropped, xScale, yScale, xShift, yShift
        )

        self.currentScale = scale
        self.currentShift = shift

    # ----

    def filterPoints(self, filterSize):
        """Filter points for printing and exporting"""
        pass

    # ----

    def draw(self, dc, printerScale):
        """Draw object."""

        # check data
        if not len(self.pointsScaled):
            return

        # draw points
        if self.properties["showPoints"]:
            pencolour = [max(x - 70, 0) for x in self.properties["pointColour"]]
            pen = wx.Pen(
                wx.Colour(*pencolour),
                int(printerScale["drawings"]),
                _WX_PENSTYLE_SOLID,
            )
            brush = wx.Brush(self.properties["pointColour"], _WX_BRUSHSTYLE_SOLID)
            dc.SetPen(pen)
            dc.SetBrush(brush)
            import numpy
            radius = int(self.properties["pointSize"] * printerScale["drawings"])
            diameter = max(1, radius * 2)
            ellipses = numpy.empty((len(self.pointsScaled), 4), dtype=numpy.int32)
            ellipses[:, 0] = self.pointsScaled[:, 0] - radius
            ellipses[:, 1] = self.pointsScaled[:, 1] - radius
            ellipses[:, 2] = diameter
            ellipses[:, 3] = diameter
            dc.DrawEllipseList(ellipses)

    # ----

    def drawGel(self, dc, gelCoords, gelHeight, printerScale):
        """Draw gel."""
        pass

    # ----

    def makeLabels(self, dc, printerScale):
        """Get object labels."""

        # check labels
        if not self.properties["showLabels"] or not self.labelsCropped:
            return []

        # set font
        dc.SetFont(_scaleFont(self.properties["labelFont"], printerScale["fonts"]))

        # prepare labels
        labels = []
        format = "%0." + repr(self.properties["xPosDigits"]) + "f - "
        for x, label in enumerate(self.labelsCropped):

            # check max length
            if len(label) > self.properties["labelMaxLength"]:
                label = label[: self.properties["labelMaxLength"]] + "..."

            # add X position
            if self.properties["showXPos"]:
                label = (format % self.pointsCropped[x][0]) + label

            # get position
            xPos = self.pointsScaled[x][0]
            yPos = self.pointsScaled[x][1]

            # get text position
            textSize = dc.GetTextExtent(label)
            textCoords = None
            if self.properties["labelAngle"] == 90:
                if self.properties["flipped"]:
                    textXPos = xPos + textSize[1] * 0.5
                    textYPos = yPos + 5 * printerScale["drawings"]
                    textCoords = (
                        textXPos,
                        textYPos,
                        textXPos - textSize[1],
                        textYPos + textSize[0],
                    )
                else:
                    textXPos = xPos - textSize[1] * 0.5
                    textYPos = yPos - 5 * printerScale["drawings"]
                    textCoords = (
                        textXPos,
                        textYPos,
                        textXPos + textSize[1],
                        textYPos - textSize[0],
                    )

            elif self.properties["labelAngle"] == 0:
                if self.properties["flipped"]:
                    textXPos = xPos - textSize[0] * 0.5
                    textYPos = yPos + 4 * printerScale["drawings"]
                    textCoords = (
                        textXPos,
                        textYPos,
                        textXPos + textSize[0],
                        textYPos - textSize[1],
                    )
                else:
                    textXPos = xPos - textSize[0] * 0.5
                    textYPos = yPos - textSize[1] - 4 * printerScale["drawings"]
                    textCoords = (
                        textXPos,
                        textYPos,
                        textXPos + textSize[0],
                        textYPos - textSize[1],
                    )

            # add label and sort by intensity
            labels.append(
                (self.pointsCropped[x][1], label, textCoords, self.properties)
            )

        return labels

    # ----

    def _normalization(self):
        """Calculate normalization constants."""

        normalization = 1.0

        # calc normalization
        if len(self.points):
            normalization = self.pointsBox[1][1] / 100.0

        # check value
        if normalization == 0.0:
            normalization = 1.0

        # set value
        self.normalization = normalization

    # ----


class points:
    """Base class for polypoints and polylines drawing."""

    def __init__(self, points, **attr):

        # set default params
        self.properties = {
            "legend": "",
            "visible": True,
            "flipped": False,
            "xOffset": 0,
            "yOffset": 0,
            "normalized": False,
            "showInGel": False,
            "exactFit": False,
            "showPoints": True,
            "pointColour": (0, 0, 255),
            "pointSize": 3,
            "fillPoints": True,
            "showLines": True,
            "lineColour": (0, 0, 255),
            "lineWidth": 1,
            "lineStyle": _WX_PENSTYLE_SOLID,
            "fillUnder": False,
            "fillUnderAlpha": 60,
            "xOffsetDigits": 2,
            "yOffsetDigits": 0,
        }

        self.currentScale = (1.0, 1.0)
        self.currentShift = (0.0, 0.0)
        self.normalization = 1.0

        # get new attributes
        for name, value in list(attr.items()):
            self.properties[name] = value

        # convert points to array
        self.points = numpy.array(points)
        self.cropped = self.points
        self.scaled = self.cropped
        if len(self.points):
            self.pointsBox = (
                numpy.array([numpy.min(self.points[:, 0]), numpy.min(self.points[:, 1])]),
                numpy.array([numpy.max(self.points[:, 0]), numpy.max(self.points[:, 1])]),
            )

        # calculate normalization
        self._normalization()

    # ----

    def setProperties(self, **attr):
        """Set object properties."""

        for name, value in list(attr.items()):
            self.properties[name] = value

    # ----

    def setNormalization(self, value):
        """Force specified normalization to be used insted of calculated one."""

        value = float(value)
        if value == 0.0:
            value = 1.0

        self.normalization = value

    # ----

    def getBoundingBox(self, minX=None, maxX=None, absolute=False):
        """Get bounding box for whole data or X selection"""

        # use relevant data
        if minX is not None and maxX is not None:
            self.cropPoints(minX, maxX)
            data = self.cropped
        else:
            data = self.points

        # check data
        if not len(data):
            return False

        # get range
        if minX is not None and maxX is not None:
            minXY = numpy.array([numpy.min(data[:, 0]), numpy.min(data[:, 1])])
            maxXY = numpy.array([numpy.max(data[:, 0]), numpy.max(data[:, 1])])
        else:
            minXY = [self.pointsBox[0][0], self.pointsBox[0][1]]
            maxXY = [self.pointsBox[1][0], self.pointsBox[1][1]]

        # extend values slightly to fit data
        if not absolute and not self.properties["exactFit"]:
            xExtend = (maxXY[0] - minXY[0]) * 0.05
            yExtend = (maxXY[1] - minXY[1]) * 0.05
            minXY[0] -= xExtend
            maxXY[0] += xExtend
            minXY[1] -= yExtend
            maxXY[1] += yExtend

        # apply normalization
        if self.properties["normalized"]:
            minXY[1] = minXY[1] / self.normalization
            maxXY[1] = maxXY[1] / self.normalization

        # apply offset
        minXY[0] += self.properties["xOffset"]
        minXY[1] += self.properties["yOffset"]
        maxXY[0] += self.properties["xOffset"]
        maxXY[1] += self.properties["yOffset"]

        # apply flipping
        if self.properties["flipped"]:
            minY = -1 * maxXY[1]
            maxY = -1 * minXY[1]
            minXY[1] = minY
            maxXY[1] = maxY

        return [minXY, maxXY]

    # ----

    def getLegend(self):
        """Get legend."""

        # get legend
        legend = self.properties["legend"]
        offset = ""

        # add current offset
        if not self.properties["normalized"]:
            if self.properties["xOffset"]:
                format = " X%0." + repr(self.properties["xOffsetDigits"]) + "f"
                offset += format % self.properties["xOffset"]
            if self.properties["yOffset"]:
                format = " Y%0." + repr(self.properties["yOffsetDigits"]) + "f"
                offset += format % self.properties["yOffset"]
            if legend and offset:
                legend += " (Offset%s)" % offset

        # set colour
        if self.properties["showPoints"]:
            return (legend, self.properties["pointColour"])
        else:
            return (legend, self.properties["lineColour"])

    # ----

    def cropPoints(self, minX, maxX):
        """Crop points to selected X range."""

        # apply offset
        minX -= self.properties["xOffset"]
        maxX -= self.properties["xOffset"]

        # crop line
        if self.properties["showLines"]:
            self.cropped = mod_signal.crop(self.points, minX, maxX)

        # crop points
        else:
            i1 = mod_signal.locate(self.points, minX)
            i2 = mod_signal.locate(self.points, maxX)
            self.cropped = self.points[i1:i2]

    # ----

    def scaleAndShift(self, scale, shift, filterSize=None):
        """Scale and shift points to screen coordinations."""

        self.scaled = self.cropped

        xScale = scale[0]
        yScale = scale[1]
        xShift = shift[0]
        yShift = shift[1]

        # apply flipping
        if self.properties["flipped"]:
            yScale *= -1

        # apply normalization
        if self.properties["normalized"]:
            yScale /= self.normalization

        # apply offset
        xShift += self.properties["xOffset"] * xScale
        yShift += self.properties["yOffset"] * yScale

        # filter and scale data
        if filterSize and len(self.cropped) and self.properties.get("showLines", True):
            data_res = filterSize / abs(xScale)
            filtered = calculations.signal_filter(self.cropped, data_res)
            self.scaled = _scaleAndShift(filtered, xScale, yScale, xShift, yShift)
        elif len(self.cropped):
            self.scaled = _scaleAndShift(self.cropped, xScale, yScale, xShift, yShift)
        else:
            self.scaled = numpy.array([])

        self.currentScale = scale
        self.currentShift = shift

    # ----

    def filterPoints(self, filterSize):
        """Filter points for printing and exporting"""
        # Intentionally empty: LOD decimation applied pre-scaling inside scaleAndShift
        pass

    # ----

    def draw(self, dc, printerScale):
        """Draw object."""

        # check data
        if not len(self.scaled):
            return

        # draw shaded area under profile when requested
        if self.properties.get("fillUnder") and len(self.scaled) > 1:
                yScale = self.currentScale[1]
                if self.properties["flipped"]:
                    yScale *= -1
                if self.properties["normalized"]:
                    yScale /= self.normalization
                baseline = int(
                    round(self.currentShift[1] + self.properties["yOffset"] * yScale)
                )

                colour = self.properties["lineColour"]
                if isinstance(colour, wx.Colour):
                    fillColour = wx.Colour(
                        colour.Red(),
                        colour.Green(),
                        colour.Blue(),
                        int(self.properties.get("fillUnderAlpha", 60)),
                    )
                else:
                    fillColour = wx.Colour(
                        int(colour[0]),
                        int(colour[1]),
                        int(colour[2]),
                        int(self.properties.get("fillUnderAlpha", 60)),
                    )

                polygon = numpy.empty((len(self.scaled) + 2, 2), dtype=numpy.int32)
                polygon[0] = (self.scaled[0][0], baseline)
                polygon[1:-1] = self.scaled
                polygon[-1] = (self.scaled[-1][0], baseline)

                drawDc = dc
                fillBrush = wx.Brush(fillColour, _WX_BRUSHSTYLE_SOLID)
                try:
                    drawDc = wx.GCDC(dc)
                except Exception:
                    # Fallback when alpha-capable DC is unavailable.
                    # Keep the shading visible using a lighter opaque tint.
                    colour = self.properties["lineColour"]
                    if isinstance(colour, wx.Colour):
                        fillBrush = wx.Brush(
                            wx.Colour(
                                min(255, int(0.70 * colour.Red() + 0.30 * 255)),
                                min(255, int(0.70 * colour.Green() + 0.30 * 255)),
                                min(255, int(0.70 * colour.Blue() + 0.30 * 255)),
                            ),
                            _WX_BRUSHSTYLE_SOLID,
                        )
                    else:
                        fillBrush = wx.Brush(
                            wx.Colour(
                                min(255, int(0.70 * int(colour[0]) + 0.30 * 255)),
                                min(255, int(0.70 * int(colour[1]) + 0.30 * 255)),
                                min(255, int(0.70 * int(colour[2]) + 0.30 * 255)),
                            ),
                            _WX_BRUSHSTYLE_SOLID,
                        )

                drawDc.SetPen(wx.TRANSPARENT_PEN)
                drawDc.SetBrush(fillBrush)
                drawDc.DrawPolygon(polygon)

        # draw lines
        if self.properties["showLines"] and len(self.scaled) > 1:

            pen = wx.Pen(
                self.properties["lineColour"],
                int(self.properties["lineWidth"] * printerScale["drawings"]),
                self.properties["lineStyle"],
            )
            brush = wx.Brush(self.properties["lineColour"], _WX_BRUSHSTYLE_SOLID)

            dc.SetPen(pen)
            dc.SetBrush(brush)
            if len(self.scaled) > 0:
                dc.DrawLines(self.scaled)

        # draw points
        if self.properties["showPoints"]:

            if self.properties["fillPoints"]:
                pencolour = [max(x - 70, 0) for x in self.properties["pointColour"]]
                pen = wx.Pen(
                    wx.Colour(*pencolour),
                    int(self.properties["lineWidth"] * printerScale["drawings"]),
                    _WX_PENSTYLE_SOLID,
                )
                brush = wx.Brush(
                    self.properties["pointColour"], _WX_BRUSHSTYLE_SOLID
                )
            else:
                pencolour = self.properties["pointColour"]
                pen = wx.Pen(
                    pencolour,
                    int(self.properties["lineWidth"] * printerScale["drawings"]),
                    _WX_PENSTYLE_SOLID,
                )
                brush = wx.TRANSPARENT_BRUSH

            dc.SetPen(pen)
            dc.SetBrush(brush)
            radius = int(self.properties["pointSize"] * printerScale["drawings"])
            diameter = max(1, radius * 2)
            ellipses = numpy.empty((len(self.scaled), 4), dtype=numpy.int32)
            ellipses[:, 0] = self.scaled[:, 0] - radius
            ellipses[:, 1] = self.scaled[:, 1] - radius
            ellipses[:, 2] = diameter
            ellipses[:, 3] = diameter
            dc.DrawEllipseList(ellipses)

    # ----

    def drawGel(self, dc, gelCoords, gelHeight, printerScale):
        """Draw gel."""
        pass

    # ----

    def makeLabels(self, dc, printerScale):
        """Get object labels."""
        return []

    # ----

    def _normalization(self):
        """Calculate normalization constants."""

        normalization = 1.0

        # calc normalization
        if len(self.points):
            normalization = self.pointsBox[1][1] / 100.0

        # check value
        if normalization == 0.0:
            normalization = 1.0

        # set value
        self.normalization = normalization

    # ----


class spectrum:
    """Base class for spectrum drawing."""

    def __init__(self, scan, **attr):

        # set default params
        self.properties = {
            "legend": "",
            "visible": True,
            "flipped": False,
            "xOffset": 0,
            "yOffset": 0,
            "normalized": False,
            "showInGel": True,
            "showSpectrum": True,
            "showPoints": True,
            "showLabels": True,
            "showIsotopicLabels": True,
            "showTicks": True,
            "showGelLegend": True,
            "spectrumColour": (0, 0, 255),
            "spectrumWidth": 1,
            "spectrumStyle": _WX_PENSTYLE_SOLID,
            "labelAngle": 90,
            "labelDigits": 2,
            "labelCharge": False,
            "labelGroup": False,
            "labelBgr": True,
            "labelColour": (0, 0, 0),
            "labelBgrColour": (255, 255, 255),
            "labelFont": wx.Font(
                10,
                _WX_FONTFAMILY_SWISS,
                wx.FONTSTYLE_NORMAL,
                wx.FONTWEIGHT_NORMAL,
                False,
            ),
            "tickColour": (200, 200, 200),
            "isotopeColour": None,
            "msmsColour": None,
            "tickWidth": 1,
            "tickStyle": _WX_PENSTYLE_SOLID,
            "xOffsetDigits": 2,
            "yOffsetDigits": 0,
            # difference rulers as (mz1, ai1, mz2, ai2, text[, key[, height]])
            # in real units; the key is handed back by rulerAt() and names the
            # ruler to leave out while it is being edited (hiddenRuler), and
            # height is the intensity to put the bar at (None: just above the
            # peaks, clear of the other rulers)
            "rulers": [],
            "showRulers": True,
            "hiddenRuler": None,
            "rulerColour": (230, 120, 0),
        }

        self.currentScale = (1.0, 1.0)
        self.currentShift = (0.0, 0.0)
        self.currentTransform = None
        self.normalization = 1.0

        # get new attributes
        for name, value in list(attr.items()):
            self.properties[name] = value

        # convert spectrum points to array
        self.spectrumPoints = numpy.array(scan.profile)
        self.applyThemeColours()

        self.spectrumCropped = self.spectrumPoints
        self.spectrumScaled = self.spectrumCropped
        if len(self.spectrumPoints):
            self.spectrumBox = (
                numpy.array([numpy.min(self.spectrumPoints[:, 0]), numpy.min(self.spectrumPoints[:, 1])]),
                numpy.array([numpy.max(self.spectrumPoints[:, 0]), numpy.max(self.spectrumPoints[:, 1])]),
            )

        # convert peaklist points to array
        self.peaklist = copy.deepcopy(scan.peaklist)
        self.peaklistPoints = numpy.array(
            [[peak.mz, peak.ai, peak.base] for peak in scan.peaklist]
        )
        self.peaklistCropped = self.peaklistPoints
        self.peaklistScaled = self.peaklistCropped
        self.peaklistCroppedPeaks = self.peaklist[:]
        if len(self.peaklistPoints):
            self.peaklistBox = (
                numpy.array([numpy.min(self.peaklistPoints[:, 0]), numpy.min(self.peaklistPoints[:, 1]), numpy.min(self.peaklistPoints[:, 2])]),
                numpy.array([numpy.max(self.peaklistPoints[:, 0]), numpy.max(self.peaklistPoints[:, 1]), numpy.max(self.peaklistPoints[:, 2])]),
            )

        # calculate normalization
        self._normalization()

    # ----

    def applyThemeColours(self):
        """Set the label colours for the current system theme.

        Called at construction and again whenever the system switches between
        light and dark, so labels drawn under the previous theme are not left
        as dark text on a dark badge (or the reverse).
        """

        apply_theme_label_colours(self.properties)

    # ----

    def setProperties(self, **attr):
        """Set object properties."""

        for name, value in list(attr.items()):
            self.properties[name] = value

    # ----

    def setNormalization(self, value):
        """Force specified normalization to be used insted of calculated one."""

        value = float(value)
        if value == 0.0:
            value = 1.0

        self.normalization = value

    # ----

    def getBoundingBox(self, minX=None, maxX=None, absolute=False):
        """Get bounding box for whole data or X selection."""

        spectrumBox = None
        peaklistBox = None

        # use relevant data
        if minX is not None and maxX is not None:
            self.cropPoints(minX, maxX)
            spectrumData = self.spectrumCropped
            peaklistData = self.peaklistCropped
        else:
            spectrumData = self.spectrumPoints
            peaklistData = self.peaklistPoints

        # calculate bounding box for spectrum
        if len(spectrumData) and self.properties["showSpectrum"]:
            if minX is not None and maxX is not None:
                minXY = numpy.array([numpy.min(spectrumData[:, 0]), numpy.min(spectrumData[:, 1])])
                maxXY = numpy.array([numpy.max(spectrumData[:, 0]), numpy.max(spectrumData[:, 1])])
            else:
                minXY = [self.spectrumBox[0][0], self.spectrumBox[0][1]]
                maxXY = [self.spectrumBox[1][0], self.spectrumBox[1][1]]

            if not absolute:
                maxXY[1] += (maxXY[1] - minXY[1]) * 0.05

            spectrumBox = [minXY, maxXY]

        # calculate bounding box for peaklist
        if len(peaklistData) and (
            self.properties["showSpectrum"]
            or self.properties["showLabels"]
            or self.properties["showTicks"]
        ):
            if minX is not None and maxX is not None:
                minXY = numpy.array([numpy.min(peaklistData[:, 0]), numpy.min(peaklistData[:, 1]), numpy.min(peaklistData[:, 2])])
                maxXY = numpy.array([numpy.max(peaklistData[:, 0]), numpy.max(peaklistData[:, 1]), numpy.max(peaklistData[:, 2])])
            else:
                minXY = [
                    self.peaklistBox[0][0],
                    self.peaklistBox[0][1],
                    self.peaklistBox[0][2],
                ]
                maxXY = [
                    self.peaklistBox[1][0],
                    self.peaklistBox[1][1],
                    self.peaklistBox[1][2],
                ]

            minXY = [minXY[0], min(minXY[1:])]
            maxXY = [maxXY[0], max(maxXY[1:])]

            # extend values to fit labels
            if not absolute:
                xExtend = (maxXY[0] - minXY[0]) * 0.02
                minXY[0] -= xExtend
                maxXY[0] += xExtend

                if self.properties["showLabels"] and self.properties["labelAngle"] == 0:
                    maxXY[1] += (maxXY[1] - minXY[1]) * 0.2
                elif (
                    self.properties["showLabels"]
                    and self.properties["labelAngle"] == 90
                ):
                    maxXY[1] += (maxXY[1] - minXY[1]) * 0.4
                else:
                    maxXY[1] += (maxXY[1] - minXY[1]) * 0.05

            peaklistBox = [minXY, maxXY]

        # use both
        if spectrumBox and peaklistBox:
            minXY, maxXY = [
                numpy.minimum(spectrumBox[0], peaklistBox[0]),
                numpy.maximum(spectrumBox[1], peaklistBox[1]),
            ]
        elif spectrumBox:
            minXY, maxXY = spectrumBox
        elif peaklistBox:
            minXY, maxXY = peaklistBox
        else:
            return False

        # apply normalization
        if self.properties["normalized"]:
            minXY[1] = minXY[1] / self.normalization
            maxXY[1] = maxXY[1] / self.normalization

        # apply offset
        if not self.properties["normalized"]:
            minXY[0] += self.properties["xOffset"]
            minXY[1] += self.properties["yOffset"]
            maxXY[0] += self.properties["xOffset"]
            maxXY[1] += self.properties["yOffset"]

        # apply flipping
        if self.properties["flipped"]:
            minY = -1 * maxXY[1]
            maxY = -1 * minXY[1]
            minXY[1] = minY
            maxXY[1] = maxY

        return [minXY, maxXY]

    # ----

    def getLegend(self):
        """Get legend."""

        # get legend
        legend = self.properties["legend"]
        offset = ""

        # add current offset
        if not self.properties["normalized"]:
            if self.properties["xOffset"]:
                format = " X%0." + repr(self.properties["xOffsetDigits"]) + "f"
                offset += format % self.properties["xOffset"]
            if self.properties["yOffset"]:
                format = " Y%0." + repr(self.properties["yOffsetDigits"]) + "f"
                offset += format % self.properties["yOffset"]
            if legend and offset:
                legend += " (Offset%s)" % offset

        # set colour
        if len(self.spectrumPoints) and self.properties["showSpectrum"]:
            return (legend, self.properties["spectrumColour"])
        else:
            return (legend, self.properties["tickColour"])

    # ----

    def getPoint(self, xPos, coord="screen"):
        """Get interpolated Y position for given X."""

        # get relevant data
        if coord == "user":
            points = self.spectrumCropped
        else:
            points = self.spectrumScaled

        # check data
        if not len(points):
            return None

        # get xPos index
        index = mod_signal.locate(points, xPos)
        if index == 0 or index == len(points):
            return None

        # get yPos
        yPos = mod_signal.interpolate(points[index - 1], points[index], x=xPos)

        return [xPos, yPos]

    # ----

    def cropPoints(self, minX, maxX):
        """Crop points to selected X range."""

        # apply offset
        minX -= self.properties["xOffset"]
        maxX -= self.properties["xOffset"]

        # crop spectrum data
        if self.properties["showSpectrum"]:
            self.spectrumCropped = mod_signal.crop(self.spectrumPoints, minX, maxX)

        # crop peaklist data
        if (
            self.properties["showSpectrum"]
            or self.properties["showLabels"]
            or self.properties["showTicks"]
        ):
            i1 = mod_signal.locate(self.peaklistPoints, minX)
            i2 = mod_signal.locate(self.peaklistPoints, maxX)
            self.peaklistCropped = self.peaklistPoints[i1:i2]
            self.peaklistCroppedPeaks = self.peaklist[i1:i2]

    # ----

    def scaleAndShift(self, scale, shift, filterSize=None):
        """Scale and shift points to screen coordinations."""

        self.spectrumScaled = self.spectrumCropped
        self.peaklistScaled = self.peaklistCropped

        xScale = scale[0]
        yScale = scale[1]
        xShift = shift[0]
        yShift = shift[1]

        # apply flipping
        if self.properties["flipped"]:
            yScale *= -1

        # apply normalization
        if self.properties["normalized"]:
            yScale /= self.normalization

        # apply offset
        if not self.properties["normalized"]:
            xShift += self.properties["xOffset"] * xScale
            yShift += self.properties["yOffset"] * yScale

        # remember the data-to-screen mapping for the overlays
        self.currentTransform = (xScale, yScale, xShift, yShift)

        # filter and scale spectrum data
        if filterSize and len(self.spectrumCropped) and self.properties["showSpectrum"]:
            data_res = filterSize / abs(xScale)
            filtered = calculations.signal_filter(self.spectrumCropped, data_res)
            self.spectrumScaled = _scaleAndShift(
                filtered, xScale, yScale, xShift, yShift
            )
        elif len(self.spectrumCropped):
            self.spectrumScaled = _scaleAndShift(
                self.spectrumCropped, xScale, yScale, xShift, yShift
            )
        else:
            self.spectrumScaled = numpy.array([])

        # scale and shift peaklist data
        if len(self.peaklistCropped):
            if filterSize and (
                self.properties.get("showLabels", True)
                or self.properties.get("showTicks", True)
            ):
                data_res = filterSize / abs(xScale)
                keep_idx = calculations.peaklist_filter_indices(
                    self.peaklistCropped, data_res
                )

                # We need to filter BOTH the numpy array and the python list representing the data model
                self.peaklistCropped = self.peaklistCropped[keep_idx]
                self.peaklistCroppedPeaks = [
                    self.peaklistCroppedPeaks[i] for i in keep_idx
                ]

            self.peaklistScaled = numpy.array(
                (xScale, yScale, yScale)
            ) * self.peaklistCropped + numpy.array((xShift, yShift, yShift))

        self.currentScale = scale
        self.currentShift = shift

    # ----

    def filterPoints(self, filterSize):
        """Filter spectrum points invisible in current resolution."""
        # Intentionally empty: LOD decimation applied pre-scaling inside scaleAndShift
        pass

    # ----

    def draw(self, dc, printerScale):
        """Draw object."""

        # draw line spectrum
        if len(self.spectrumScaled) > 2 and self.properties["showSpectrum"]:
            self._drawSpectrum(dc, printerScale)
        # draw peaklist ticks
        if len(self.peaklistScaled) and (
            self.properties["showTicks"] or not len(self.spectrumPoints)
        ):
            self._drawPeaklist(dc, printerScale)

    # ----

    def drawGel(self, dc, gelCoords, gelHeight, printerScale):
        """Draw gel."""

        # draw line spectrum gel
        if len(self.spectrumScaled) > 2 and self.properties["showSpectrum"]:
            self._drawSpectrumGel(dc, gelCoords, gelHeight, printerScale)

        # draw peaklist gel
        elif len(self.peaklistScaled) and (
            self.properties["showSpectrum"]
            or self.properties["showLabels"]
            or self.properties["showTicks"]
        ):
            self._drawPeaklistGel(dc, gelCoords, gelHeight, printerScale)

        # draw gel legend
        self._drawGelLegend(dc, gelCoords, gelHeight, printerScale)

    # ----

    def makeLabels(self, dc, printerScale):
        """Get object labels."""

        # check labels
        if not self.properties["showLabels"] or not len(self.peaklistScaled):
            return []

        # set font
        labelFont = _scaleFont(self.properties["labelFont"], printerScale["fonts"])
        dc.SetFont(labelFont)
        deviceKey = (
            type(dc).__name__,
            dc.GetPPI().Get(),
            labelFont.GetNativeFontInfoDesc(),
        )

        # Everything constant is hoisted out of the loop below: on a dense
        # peaklist it runs once per visible peak on every frame, and the
        # repeated dict lookups and wx.Size indexing cost more than the work.
        properties = self.properties
        showIsotopicLabels = properties["showIsotopicLabels"]
        labelCharge = properties["labelCharge"]
        labelGroup = properties["labelGroup"]
        labelAngle = properties["labelAngle"]
        flipped = properties["flipped"]
        angledOffset = 5 * printerScale["drawings"]
        flatOffset = 4 * printerScale["drawings"]
        peaks = self.peaklistCroppedPeaks

        # prepare labels
        labels = []
        format = "%0." + repr(properties["labelDigits"]) + "f"
        for x, peak in enumerate(self.peaklistScaled):
            source = peaks[x]

            # skip isotopes
            if not showIsotopicLabels and source.isotope != 0:
                continue

            # get position
            xPos = peak[0]
            yPos = peak[1]

            # get label
            label = format % source.mz

            # add charge to label
            if labelCharge and source.charge is not None:
                label += " (%d)" % source.charge

            # add group to label
            if labelGroup and source.group:
                label += " [%s]" % source.group

            # get text position
            textWidth, textHeight = _textExtent(dc, deviceKey, label)
            textCoords = None
            if labelAngle == 90:
                if flipped:
                    textXPos = xPos + textHeight * 0.5
                    textYPos = yPos + angledOffset
                    textCoords = (
                        textXPos,
                        textYPos,
                        textXPos - textHeight,
                        textYPos + textWidth,
                    )
                else:
                    textXPos = xPos - textHeight * 0.5
                    textYPos = yPos - angledOffset
                    textCoords = (
                        textXPos,
                        textYPos,
                        textXPos + textHeight,
                        textYPos - textWidth,
                    )

            elif labelAngle == 0:
                if flipped:
                    textXPos = xPos - textWidth * 0.5
                    textYPos = yPos + flatOffset
                    textCoords = (
                        textXPos,
                        textYPos,
                        textXPos + textWidth,
                        textYPos - textHeight,
                    )
                else:
                    textXPos = xPos - textWidth * 0.5
                    textYPos = yPos - textHeight - flatOffset
                    textCoords = (
                        textXPos,
                        textYPos,
                        textXPos + textWidth,
                        textYPos - textHeight,
                    )

            # add label and sort by intensity
            labels.append((source.ai, label, textCoords, properties))

        return labels

    # ----

    def drawOverlays(self, dc, printerScale, labelBoxes=()):
        """Draw difference rulers over the spectrum and its labels."""

        layouts = self.layoutOverlays(dc, printerScale, labelBoxes)
        self.paintOverlays(dc, printerScale, layouts, "under")
        self.paintOverlays(dc, printerScale, layouts, "over")

    # ----

    def layoutOverlays(self, dc, printerScale, labelBoxes=()):
        """Lay out the difference rulers, their texts off each other and, where
        they can be, off the peak labels (labelBoxes, see spreadRulerTexts).
        Returns [(key, layout)] for paintOverlays.
        """

        self.rulerGeometry = []
        rulers = self.properties["rulers"]
        if not rulers or not self.properties["showRulers"]:
            return []
        if self.currentTransform is None:
            return []

        xScale, yScale, xShift, yShift = self.currentTransform
        font = _scaleFont(self.properties["labelFont"], printerScale["fonts"])
        hidden = self.properties["hiddenRuler"]

        # rulers put at a height by hand first, so the others stack clear of
        # them; then their texts yield to each other, all together
        placed = []
        layouts = []

        def order(entry):
            item = entry[1]
            return (len(item) < 7 or item[6] is None, min(item[0], item[2]))

        for index, item in sorted(enumerate(rulers), key=order):
            mz1, ai1, mz2, ai2, text = item[:5]
            key = item[5] if len(item) > 5 else index
            height = item[6] if len(item) > 6 else None
            if hidden is not None and key == hidden:
                continue
            ai1 = self.rulerEndIntensity(mz1, ai1)
            ai2 = self.rulerEndIntensity(mz2, ai2)
            x1 = _clampScreen(mz1 * xScale + xShift)
            x2 = _clampScreen(mz2 * xScale + xShift)
            y1 = _clampScreen(ai1 * yScale + yShift)
            y2 = _clampScreen(ai2 * yScale + yShift)

            layout = rulerLayout(
                dc,
                x1,
                y1,
                x2,
                y2,
                text,
                font,
                printerScale,
                flipped=self.properties["flipped"],
                placed=placed,
                yBar=None if height is None else _clampScreen(height * yScale + yShift),
            )
            placed.append(layout["bar"])
            if text:
                placed.append(layout["textBox"])
            layouts.append((key, layout))

        spreadRulerTexts([layout for _key, layout in layouts], labels=labelBoxes)
        self.rulersUnderLabels = [key for key, layout in layouts if layout.get("underLabels")]
        return layouts

    # ----

    def paintOverlays(self, dc, printerScale, layouts, part="all"):
        """Draw rulers laid out by layoutOverlays: the texts that give way to
        the peak labels ("under", drawn before them) or the rest ("over").
        """

        if part != "under":
            self.rulerGeometry = []
        for key, layout in layouts:
            geometry = paintRuler(
                dc,
                layout,
                self.properties["rulerColour"],
                self.properties["labelBgrColour"],
                self.properties["labelBgr"],
                printerScale,
                part,
            )
            if part != "under":
                self.rulerGeometry.append((key, geometry))

    # ----

    def rulerAt(self, x, y, tolerance=5):
        """Ruler drawn under a screen position, as (key, part) or None.

        Only the bar itself is picked up, neither its text (which may sit
        over another ruler's bar) nor its dotted leads: part is 1 or 2 for the
        lower or higher m/z end of the bar (its arrowhead and end tick, the
        end to drag), or 0 for the rest of it. Of several ends within reach,
        the nearest is taken; of two ends at the same place, the one of the
        ruler on the cursor's side of it. An end within reach wins over any
        bar; of several bars, the nearest.
        """

        best = None
        geometry = list(reversed(getattr(self, "rulerGeometry", [])))
        for order, (key, (x1, _y1, x2, _y2, yBar, _box)) in enumerate(geometry):

            # the grip at each end of the bar reaches a little way in, but no
            # further than a third of a short bar
            grip = min(2 * tolerance, abs(x2 - x1) / 3.0)
            for part, endX, otherX in ((1, x1, x2), (2, x2, x1)):
                inward = 1 if otherX >= endX else -1
                along = (x - endX) * inward
                if not -tolerance <= along <= grip:
                    continue
                dy = abs(y - yBar)
                if dy > tolerance:
                    continue
                dx = max(0.0, -along)
                side = 0 if along > 0 else 1
                score = (0, (dx * dx + dy * dy) ** 0.5, side, order)
                if best is None or score < best[0]:
                    best = (score, key, part)

            dx = max(0.0, min(x1, x2) - x, x - max(x1, x2))
            dy = abs(y - yBar)
            if dx <= tolerance and dy <= tolerance:
                score = (1, (dx * dx + dy * dy) ** 0.5, 0, order)
                if best is None or score < best[0]:
                    best = (score, key, 0)

        if best is None:
            return None
        return best[1], best[2]

    # ----

    def rulerEndIntensity(self, mz, ai):
        """Current intensity at a ruler end.

        A ruler keeps the intensity it was drawn at, but smoothing, baseline
        subtraction or a math operation can change it later: the peak still
        sitting at that m/z has the current value. An end on no peak stays
        where it was put, as it was drawn while being dragged.
        """

        points = self.peaklistPoints
        if len(points):
            i = mod_signal.locate(points, mz)
            for j in (i - 1, i):
                if 0 <= j < len(points) and abs(points[j][0] - mz) <= max(1e-4, mz * 1e-6):
                    return points[j][1]

        return ai

    # ----

    def _drawSpectrum(self, dc, printerScale):
        """Draw spectrum lines."""

        colour = self.properties["spectrumColour"]
        style = self.properties["spectrumStyle"]
        # Proportional line width (e.g. 2 at 200% UI scale, or thicker for
        # printing/exporting where printerScale["drawings"] is larger).
        width = max(
            1, int(round(self.properties["spectrumWidth"] * printerScale["drawings"]))
        )

        dc.SetBrush(wx.Brush(colour, _WX_BRUSHSTYLE_SOLID))

        # When exporting to SVG the platform-specific fast paths below (multi-pass
        # strokes on MSW, per-segment DrawLineList on GTK) exist only to keep
        # interactive panning smooth; in a vector file they would bloat the
        # output into thousands of separate path elements. Draw the profile as a
        # single polyline instead so it becomes one editable object.
        is_vector = isinstance(dc, wx.SVGFileDC)

        # draw lines
        if len(self.spectrumScaled) > 0:
            # On screen, vertices landing on pixels the trace already covers can
            # be dropped: the curve reaches the toolkit with a fraction of the
            # points and looks the same. This is not platform-specific -- every
            # backend pays per vertex -- but it must not touch a vector file,
            # where the exported curve has to keep every point it was given.
            dense = not is_vector and len(self.spectrumScaled) > 1500
            points = (
                _compress_screen_polyline(self.spectrumScaled)
                if dense
                else self.spectrumScaled
            )

            if len(points) < 2:
                pass
            elif not is_vector and wx.Platform == "__WXMSW__" and width > 1:
                # On wxMSW a pen width >= 2 forces GDI onto its slow
                # geometric-pen path (joins/caps computed per vertex), which
                # makes panning/zooming a dense spectrum extremely sluggish.
                # Build the heavier line from several fast 1px cosmetic strokes
                # offset by a pixel: an N-pixel line is N*N cheap passes, still
                # far quicker than one wide geometric stroke.
                dc.SetPen(wx.Pen(colour, 1, style))
                lo = -(width // 2)
                for dx in range(lo, lo + width):
                    for dy in range(lo, lo + width):
                        dc.DrawLines(points, dx, dy)
            elif dense and wx.Platform == "__WXGTK__":
                # wxGTK can stutter on highly jagged, dense polylines because
                # join-heavy path stroking is expensive. DrawLineList renders
                # the same curve as independent segments and is smoother there.
                dc.SetPen(wx.Pen(colour, width, style))
                segments = numpy.empty((len(points) - 1, 4), dtype=numpy.int32)
                segments[:, 0] = points[:-1, 0]
                segments[:, 1] = points[:-1, 1]
                segments[:, 2] = points[1:, 0]
                segments[:, 3] = points[1:, 1]
                dc.DrawLineList(segments)
            else:
                dc.SetPen(wx.Pen(colour, width, style))
                dc.DrawLines(points)

        # set pen for points
        dc.SetPen(wx.Pen(colour, width, _WX_PENSTYLE_SOLID))

        # draw points if it makes sense
        count = len(self.spectrumScaled)
        if (
            self.properties["showPoints"]
            and count > 2
            and (self.spectrumScaled[2][0] - self.spectrumScaled[1][0])
            > (6 * printerScale["drawings"])
            and ((self.spectrumScaled[-1][0] - self.spectrumScaled[0][0]) / count)
            > (6 * printerScale["drawings"])
        ):
            radius = int(2 * printerScale["drawings"])
            diameter = max(1, radius * 2)
            ellipses = numpy.empty((len(self.spectrumScaled), 4), dtype=numpy.int32)
            ellipses[:, 0] = self.spectrumScaled[:, 0] - radius
            ellipses[:, 1] = self.spectrumScaled[:, 1] - radius
            ellipses[:, 2] = diameter
            ellipses[:, 3] = diameter
            dc.DrawEllipseList(ellipses)

    # ----

    def _drawSpectrumGel(self, dc, gelCoords, gelHeight, printerScale):
        """Draw spectrum gel."""

        # get plot coordinates
        gelY1, plotX1, plotY1, plotX2, plotY2, zeroY = gelCoords

        # Reference scale = the largest absolute intensity on display, i.e. the
        # screen distance from the zero line to whichever axis extreme (top peak
        # or bottom trough) is farther from it. Peaks (grayscale) and troughs
        # (red) share this one scale, so the most intense feature -- of either
        # sign -- saturates and everything else is proportional. Reading it from
        # the axis extents (not the data) keeps the gel responsive to Y-zoom.
        scale = max(zeroY - plotY1, plotY2 - zeroY)
        if scale <= 0:
            return False

        pixel_step = max(1, int(round(printerScale["drawings"])))

        # Compute gel stripes in vectorized form from spectrum points.
        # This reduces drag-time cost from O(number_of_points) Python loops
        # to O(number_of_screen_columns) draw operations.
        runs = _build_gel_runs(
            self.spectrumScaled,
            zeroY,
            scale,
            self.properties["flipped"],
            pixel_step,
            plotX1,
            plotX2,
            dark_mode=_is_dark_mode_cached(),
            fill_gaps=True,
        )
        if not runs:
            return False

        # init brush
        dc.SetPen(wx.TRANSPARENT_PEN)
        brush = wx.Brush(
            wx.Colour(0, 0, 0)
            if _is_dark_mode_cached()
            else wx.Colour(255, 255, 255),
            _WX_BRUSHSTYLE_SOLID,
        )
        dc.SetBrush(brush)

        for x_start, width, r, g, b in runs:
            brush.SetColour(wx.Colour(int(r), int(g), int(b)))
            dc.SetBrush(brush)
            dc.DrawRectangle(int(x_start), int(gelY1), int(width), int(gelHeight))

    # ----

    def _drawPeaklist(self, dc, printerScale):
        """Draw peaklist ticks."""

        # set pen params
        peakPen = wx.Pen(
            self.properties["tickColour"],
            int(self.properties["tickWidth"] * printerScale["drawings"]),
            self.properties["tickStyle"],
        )
        isotopePen = wx.Pen(
            self.properties["tickColour"],
            int(self.properties["tickWidth"] * printerScale["drawings"]),
            self.properties["tickStyle"],
        )
        peakBrush = wx.Brush(self.properties["tickColour"], _WX_BRUSHSTYLE_SOLID)
        msmsBrush = wx.Brush(self.properties["tickColour"], _WX_BRUSHSTYLE_SOLID)

        if self.properties["isotopeColour"]:
            isotopePen.SetColour(self.properties["isotopeColour"])
        if self.properties["msmsColour"]:
            msmsBrush.SetColour(self.properties["msmsColour"])

        # Ticks are drawn in batches rather than one wx call per peak: a dense
        # peaklist puts thousands of them on screen and the per-call overhead
        # dominated the redraw. Peaks whose coordinates do not fit a device
        # integer are dropped, exactly as the per-peak OverflowError guard did.
        scaled = self.peaklistScaled
        capHalf = 3 * printerScale["drawings"]
        markSize = int(printerScale["drawings"])
        markWidth = int(3 * printerScale["drawings"])

        xs = scaled[:, 0]
        tops = scaled[:, 1]
        bases = scaled[:, 2]

        limit = 2 ** 31 - 1 - capHalf
        drawable = (
            numpy.isfinite(xs)
            & numpy.isfinite(tops)
            & numpy.isfinite(bases)
            & (numpy.abs(xs) < limit)
            & (numpy.abs(tops) < limit)
            & (numpy.abs(bases) < limit)
        )

        isotope = numpy.fromiter(
            (peak.isotope != 0 for peak in self.peaklistCroppedPeaks),
            dtype=bool,
            count=len(scaled),
        )

        def _ticks(mask):
            """Stem and cap segments for the selected peaks."""

            x = xs[mask].astype(numpy.int32)
            top = tops[mask].astype(numpy.int32)
            base = bases[mask].astype(numpy.int32)

            segments = numpy.empty((2 * len(x), 4), dtype=numpy.int32)
            segments[: len(x), 0] = x
            segments[: len(x), 1] = base
            segments[: len(x), 2] = x
            segments[: len(x), 3] = top
            segments[len(x) :, 0] = (xs[mask] - capHalf).astype(numpy.int32)
            segments[len(x) :, 1] = base
            segments[len(x) :, 2] = (xs[mask] + capHalf).astype(numpy.int32)
            segments[len(x) :, 3] = base
            return segments, x, top

        # draw isotopes
        dc.SetPen(isotopePen)
        mask = drawable & isotope
        if numpy.any(mask):
            dc.DrawLineList(_ticks(mask)[0])

        # draw peaks
        dc.SetPen(peakPen)
        dc.SetBrush(peakBrush)
        mask = drawable & ~isotope
        if numpy.any(mask):
            segments, x, top = _ticks(mask)
            dc.DrawLineList(segments)

            marks = numpy.empty((len(x), 4), dtype=numpy.int32)
            marks[:, 0] = x - markSize
            marks[:, 1] = top - markSize
            marks[:, 2] = markWidth
            marks[:, 3] = markWidth
            dc.DrawRectangleList(marks, pens=peakPen, brushes=peakBrush)

        # draw fragmentation mark
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(msmsBrush)
        for x, peak in enumerate(self.peaklistScaled):
            if self.peaklistCroppedPeaks[x].childScanNumber is not None:
                try:
                    dc.DrawCircle(
                        int(int(peak[0])),
                        int(int(peak[1])),
                        int(int(3 * printerScale["drawings"])),
                    )
                except OverflowError:
                    pass

    # ----

    def _drawPeaklistGel(self, dc, gelCoords, gelHeight, printerScale):
        """Draw peaklist gel."""

        # get plot coordinates
        gelY1, plotX1, plotY1, plotX2, plotY2, zeroY = gelCoords

        # Reference scale = largest absolute intensity on display (see
        # _drawSpectrumGel).
        scale = max(zeroY - plotY1, plotY2 - zeroY)
        if scale <= 0:
            return False

        pixel_step = max(1, int(round(printerScale["drawings"])))

        runs = _build_gel_runs(
            self.peaklistScaled,
            zeroY,
            scale,
            self.properties["flipped"],
            pixel_step,
            plotX1,
            plotX2,
            dark_mode=_is_dark_mode_cached(),
        )
        if not runs:
            return False

        # init brush
        dc.SetPen(wx.TRANSPARENT_PEN)
        brush = wx.Brush(
            wx.Colour(0, 0, 0)
            if _is_dark_mode_cached()
            else wx.Colour(255, 255, 255),
            _WX_BRUSHSTYLE_SOLID,
        )
        dc.SetBrush(brush)

        for x_start, width, r, g, b in runs:
            brush.SetColour(wx.Colour(int(r), int(g), int(b)))
            dc.SetBrush(brush)
            dc.DrawRectangle(int(x_start), int(gelY1), int(width), int(gelHeight))

    # ----

    def _drawGelLegend(self, dc, gelCoords, gelHeight, printerScale):
        """docstring for _drawGelLegend"""

        # get plot coordinates
        gelY1, plotX1, plotY1, plotX2, plotY2, zeroY = gelCoords

        # get colour
        if len(self.spectrumPoints) and self.properties["showSpectrum"]:
            colour = self.properties["spectrumColour"]
        else:
            colour = self.properties["tickColour"]

        # set dc
        pencolour = [max(i - 70, 0) for i in colour]
        pen = wx.Pen(
            wx.Colour(*pencolour),
            int(printerScale["drawings"]),
            _WX_PENSTYLE_SOLID,
        )
        dc.SetPen(pen)
        dc.SetTextForeground(colour)
        dc.SetBrush(wx.Brush(colour, _WX_BRUSHSTYLE_SOLID))

        # draw legend circle
        x = plotX2 - 9 * printerScale["drawings"]
        y = gelY1 + (gelHeight) / 2
        dc.DrawCircle(int(int(x)), int(int(y)), int(int(3 * printerScale["drawings"])))

        # draw legend text
        if self.properties["showGelLegend"] and self.properties["legend"]:
            textSize = dc.GetTextExtent(self.properties["legend"])
            x = plotX2 - textSize[0] - 17 * printerScale["drawings"]
            y = gelY1 + gelHeight / 2 - textSize[1] / 2
            dc.DrawText(self.properties["legend"], int(x), int(y))

    # ----

    def _normalization(self):
        """Calculate normalization constants."""

        normalization = 0.0

        # get range from points and peaklist
        if len(self.spectrumPoints) and len(self.peaklistPoints):
            spectrumMinXY, spectrumMaxXY = self.spectrumBox
            peaklistMinXY, peaklistMaxXY = self.peaklistBox
            normalization = max(spectrumMaxXY[1], peaklistMaxXY[1]) / 100.0

        # get range from points only
        elif len(self.spectrumPoints):
            minXY, maxXY = self.spectrumBox
            normalization = maxXY[1] / 100.0

        # get range from peaklist only
        elif len(self.peaklistPoints):
            minXY, maxXY = self.peaklistBox
            normalization = maxXY[1] / 100.0

        # check value
        if normalization == 0.0:
            normalization = 1.0

        # set value
        self.normalization = normalization

    # ----


# HELPERS
# -------


def _clampScreen(value):
    """Keep a screen coordinate within what a device context can take."""

    return min(max(float(value), -1e6), 1e6)


def drawRuler(
    dc,
    x1,
    y1,
    x2,
    y2,
    text,
    colour,
    font,
    bgrColour,
    labelBgr=True,
    printerScale=None,
    flipped=False,
    placed=None,
    yBar=None,
    labels=None,
):
    """Draw a difference ruler between two peak tops, in screen coordinates.

    The bar sits just above the taller of the two peaks (below, for a flipped
    spectrum), with its text over the middle. When placed -- a list of the
    boxes other rulers already took, their bars and texts -- is given, the
    ruler is lifted until it no longer collides with them; a bar put at a
    given height (yBar) stays there, but its text still moves off them (see
    spreadRulerTexts), and the boxes of its bar and text are added to placed.
    Its text also keeps off the peak labels' boxes (labels) where it can.
    Rulers drawn together are better laid out together, see rulerLayout.
    Returns (x1, y1, x2, y2, yBar, box) as drawn, ends ordered left to right,
    box being the text's (the bar's without text).
    """

    layout = rulerLayout(dc, x1, y1, x2, y2, text, font, printerScale, flipped, placed, yBar)
    if placed is not None or labels:
        spreadRulerTexts([layout], placed or (), labels or ())
    if placed is not None:
        placed.append(layout["bar"])
        if text:
            placed.append(rulerTextBox(layout))
    return paintRuler(dc, layout, colour, bgrColour, labelBgr, printerScale)


# how far (in pixels, before scaling) over the taller of its peaks a ruler's
# bar is put when placed by itself or started from a peak: right at its top
RULER_GAP = 0


def rulerLayout(dc, x1, y1, x2, y2, text, font, printerScale=None, flipped=False, placed=None, yBar=None):
    """Where a difference ruler goes, before it is drawn (see drawRuler).

    placed lifts a ruler without a height of its own clear of the boxes
    other rulers took, its text where it would sit over the bar. Returns a
    layout for spreadRulerTexts and paintRuler.
    """

    scale = printerScale["drawings"] if printerScale else 1.0
    gap = RULER_GAP * scale
    tick = 4 * scale
    away = 1 if flipped else -1

    if x2 < x1:
        x1, y1, x2, y2 = x2, y2, x1, y1

    dc.SetFont(font)
    textWidth, textHeight = dc.GetTextExtent(text) if text else (0, 0)
    step = textHeight + 3 * tick
    mid = (x1 + x2) / 2.0
    textX = mid - textWidth / 2.0
    near = min(y1, y2) if not flipped else max(y1, y2)

    def textBoxOver(bar):
        top = bar - tick - textHeight if not flipped else bar + tick
        return (textX, top, textX + textWidth, top + textHeight)

    # lift above the rulers already drawn
    fixed = yBar
    level = 0
    while True:
        yBar = fixed if fixed is not None else near + away * (gap + level * step)
        textBox = textBoxOver(yBar)
        box = (
            min(x1, textBox[0]),
            min(yBar - tick, textBox[1]),
            max(x2, textBox[2]),
            max(yBar + tick, textBox[3]),
        )
        if fixed is not None or placed is None or level >= 10 or not any(_overlaps(box, other) for other in placed):
            break
        level += 1

    return {
        "ends": (x1, y1, x2, y2),
        "yBar": yBar,
        "mid": mid,
        "text": text,
        "font": font,
        "textBox": textBox,
        "bar": (x1, yBar - tick, x2, yBar + tick),
        "flipped": flipped,
        "offset": (0.0, 0.0),
    }


def rulerTextBox(layout):
    """Box of a laid out ruler's text, where spreadRulerTexts moved it."""

    dx, dy = layout["offset"]
    left, top, right, bottom = layout["textBox"]
    return (left + dx, top + dy, right + dx, bottom + dy)


# how far a text yielding to another moves at a time, as a share of its
# height (up or down), at what angle from the bar, and how much room, again
# as a share of its height, two texts are to leave between them
_YIELD_STEP = 0.25
_YIELD_ANGLE = 60.0
_YIELD_ROOM = 1.0


def spreadRulerTexts(layouts, obstacles=(), labels=()):
    """Move ruler texts off each other and off other rulers' bars.

    The bars stay where they are. Two texts that overlap both yield, alike:
    they move away from their bars (up, or down for a flipped spectrum) and
    apart, the left one at 120 degrees from the bar and the right one at 60,
    a step at a time until clear. A text moved one way keeps going that way,
    and one that meets another already moving towards it waits while that
    one gets out of its way, so texts yielding to different neighbours do
    not run into each other. Texts that yield leave room between them, of
    about their height. A text over another ruler's bar, or over one of
    the obstacles (boxes that do not move, e.g. rulers drawn already), moves
    away from it alone. Then a text on a peak label (labels, their boxes)
    moves on, mostly further away from its bar and a little sideways, to
    where it covers none and runs into nothing else; where there is no such
    place near, the labels win: the layout is marked underLabels, for the
    text to be drawn under them. Sets each layout's offset.
    """

    texts = [i for i, layout in enumerate(layouts) if layout["text"]]
    if not texts:
        return

    rise = [
        max(3.0, _YIELD_STEP * (layouts[i]["textBox"][3] - layouts[i]["textBox"][1]))
        for i in range(len(layouts))
    ]
    run = [value / numpy.tan(numpy.radians(_YIELD_ANGLE)) for value in rise]
    room = [
        _YIELD_ROOM * (layout["textBox"][3] - layout["textBox"][1]) / 2.0 for layout in layouts
    ]
    away = [1 if layout["flipped"] else -1 for layout in layouts]
    steps = [0] * len(layouts)
    sides: list[int | None] = [None] * len(layouts)

    def centre(box):
        return (box[0] + box[2]) / 2.0

    def boxOf(i):
        side = sides[i] or 0
        layouts[i]["offset"] = (side * steps[i] * run[i], away[i] * steps[i] * rise[i])
        return rulerTextBox(layouts[i])

    for _round in range(40):
        boxes = {i: boxOf(i) for i in texts}
        moving = set()

        # texts on each other, or closer side by side than the room they are
        # to leave between them
        pairs = []
        for a in range(len(texts)):
            for b in range(a + 1, len(texts)):
                i, j = texts[a], texts[b]
                if _overlaps(_widened(boxes[i], room[i]), _widened(boxes[j], room[j])):
                    if centre(layouts[i]["textBox"]) <= centre(layouts[j]["textBox"]):
                        pairs.append((i, j))
                    else:
                        pairs.append((j, i))

        # a group of them fans out: the left half to the left, the right half
        # to the right, one in the middle straight on
        group = {i: i for i in texts}
        for i, j in pairs:
            group[_groupRoot(group, i)] = _groupRoot(group, j)
        members = {}
        for i in {k for pair in pairs for k in pair}:
            members.setdefault(_groupRoot(group, i), []).append(i)
        for crowd in members.values():
            crowd.sort(key=lambda k: (centre(layouts[k]["textBox"]), k))
            middle = (len(crowd) - 1) / 2.0
            for rank, k in enumerate(crowd):
                if sides[k] is None:
                    sides[k] = -1 if rank < middle else 1 if rank > middle else 0

        # both of two on each other yield, apart
        for left, right in pairs:
            leftGoes = sides[left] <= 0
            rightGoes = sides[right] >= 0
            if leftGoes:
                moving.add(left)
            if rightGoes:
                moving.add(right)
            if not (leftGoes or rightGoes):
                moving.update((left, right))

        # texts on other rulers' bars or on what does not move: they alone
        for i in texts:
            others = [layout["bar"] for k, layout in enumerate(layouts) if k != i]
            for other in [*others, *obstacles]:
                if _overlaps(boxes[i], other):
                    if sides[i] is None:
                        mine, theirs = centre(layouts[i]["textBox"]), centre(other)
                        sides[i] = -1 if mine < theirs else 1 if mine > theirs else 0
                    moving.add(i)
                    break

        if not moving:
            break
        for i in moving:
            steps[i] += 1

    for i in texts:
        boxOf(i)
    _clearRulerTextsOfLabels(layouts, texts, obstacles, labels)


# where a ruler text on a peak label looks for a clear place: how far away
# from its bar, and to either side, in text heights, and what a step sideways
# costs against one away from the bar
_CLEAR_AWAY = 12.0
_CLEAR_SIDEWAYS = 2.0
_CLEAR_SIDEWAYS_COST = 2.0


def _clearRulerTextsOfLabels(layouts, texts, obstacles, labels):
    """Move ruler texts off peak labels (see spreadRulerTexts).

    A text on a label is moved to the nearest place clear of every label and
    of everything else drawn, mostly away from its bar (up, or down for a
    flipped spectrum), where the labels end, and a little sideways (away
    from the nearest label first) only as far as it helps, never at a lower
    angle than _YIELD_ANGLE; a step sideways counts as _CLEAR_SIDEWAYS_COST
    steps away. It stays on the screen.
    """

    boxes = numpy.asarray(list(labels), dtype=float).reshape((-1, 4))
    boxes = boxes[numpy.isfinite(boxes).all(axis=1)] if len(boxes) else boxes
    if not len(boxes):
        return

    def hits(box, among):
        return (
            (among[:, 0] < box[2]) & (box[0] < among[:, 2]) & (among[:, 1] < box[3]) & (box[1] < among[:, 3])
        )

    finals = {i: rulerTextBox(layouts[i]) for i in texts}
    for i in texts:
        box = finals[i]
        covered = boxes[hits(box, boxes)]
        if not len(covered):
            continue

        height = box[3] - box[1]
        stride = max(2.0, height / 2.0)
        away = 1 if layouts[i]["flipped"] else -1
        steps = int(_CLEAR_AWAY * height / stride)
        sideSteps = int(_CLEAR_SIDEWAYS * height / stride)

        # the labels and everything else around where it may go
        region = (
            box[0] - sideSteps * stride,
            min(box[1], box[1] + away * steps * stride),
            box[2] + sideSteps * stride,
            max(box[3], box[3] + away * steps * stride),
        )
        near = boxes[hits(region, boxes)]
        others = [finals[k] for k in texts if k != i]
        others += [layout["bar"] for k, layout in enumerate(layouts) if k != i]
        others += list(obstacles)
        others = [other for other in others if _overlaps(region, other)]

        # sideways, away from the nearest label first
        centre = (box[0] + box[2]) / 2.0
        closest = covered[numpy.argmin(numpy.abs((covered[:, 0] + covered[:, 2]) / 2.0 - centre))]
        first = 1 if centre >= (closest[0] + closest[2]) / 2.0 else -1

        # a move sideways rises at least as steeply as texts yielding to
        # each other do, so a text never just slides along beside its bar
        steepness = numpy.tan(numpy.radians(_YIELD_ANGLE))
        candidates = []
        for up in range(steps + 1):
            for side in range(sideSteps + 1):
                if side and up < side * steepness:
                    continue
                for sign in ((first, -first) if side else (0,)):
                    candidates.append((up + _CLEAR_SIDEWAYS_COST * side, side, sign != first, up, sign * side))
        candidates.sort()

        found = None
        for _cost, _side, _second, up, side in candidates:
            if not up and not side:
                continue
            dx = side * stride
            dy = away * up * stride
            moved = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
            if moved[1] < 0:
                continue
            if hits(moved, near).any():
                continue
            if any(_overlaps(moved, other) for other in others):
                continue
            found = (dx, dy)
            break

        if found is None:
            layouts[i]["underLabels"] = True
            continue
        dx, dy = layouts[i]["offset"]
        layouts[i]["offset"] = (dx + found[0], dy + found[1])
        finals[i] = rulerTextBox(layouts[i])


def _widened(box, margin):
    """A box made wider by margin on either side."""

    return (box[0] - margin, box[1], box[2] + margin, box[3])


def _groupRoot(group, i):
    """The item standing for the group i is in (union-find, halving paths)."""

    while group[i] != i:
        group[i] = group[group[i]]
        i = group[i]
    return i


def paintRuler(dc, layout, colour, bgrColour, labelBgr=True, printerScale=None, part="all"):
    """Draw a laid out ruler (see rulerLayout). Returns its geometry as
    drawRuler does.

    part is "all", or, for a ruler drawn with the peak labels: "under", its
    text if it is to go under them (underLabels), else nothing; "over" the
    rest.
    """

    scale = printerScale["drawings"] if printerScale else 1.0
    tick = 4 * scale
    head = 4 * scale
    x1, y1, x2, y2 = layout["ends"]
    yBar = layout["yBar"]
    text = layout["text"]
    box = rulerTextBox(layout) if text else layout["bar"]

    width = max(1, int(round(scale)))
    under = bool(layout.get("underLabels"))
    drawText = bool(text) and (part == "all" or (part == "under") == under)
    if part == "under":
        if drawText:
            _paintRulerText(dc, layout, box, colour, bgrColour, labelBgr, width)
        return (x1, y1, x2, y2, yBar, box)

    dc.SetPen(wx.Pen(colour, width, _WX_PENSTYLE_SOLID))
    dc.SetBrush(wx.Brush(colour, _WX_BRUSHSTYLE_SOLID))

    # bar with arrowheads pointing at the peaks
    dc.DrawLine(int(x1), int(yBar), int(x2), int(yBar))
    if x2 - x1 > 3 * head:
        dc.DrawPolygon(
            [
                wx.Point(int(x1), int(yBar)),
                wx.Point(int(x1 + head * 1.5), int(yBar - head)),
                wx.Point(int(x1 + head * 1.5), int(yBar + head)),
            ]
        )
        dc.DrawPolygon(
            [
                wx.Point(int(x2), int(yBar)),
                wx.Point(int(x2 - head * 1.5), int(yBar - head)),
                wx.Point(int(x2 - head * 1.5), int(yBar + head)),
            ]
        )

    # end ticks, and dotted leads down (up) to both peak tops
    dc.DrawLine(int(x1), int(yBar - tick), int(x1), int(yBar + tick))
    dc.DrawLine(int(x2), int(yBar - tick), int(x2), int(yBar + tick))
    dc.SetPen(wx.Pen(colour, width, wx.PENSTYLE_DOT))
    dc.DrawLine(int(x1), int(yBar), int(x1), int(y1))
    dc.DrawLine(int(x2), int(yBar), int(x2), int(y2))

    if drawText:
        _paintRulerText(dc, layout, box, colour, bgrColour, labelBgr, width)

    return (x1, y1, x2, y2, yBar, box)


def _paintRulerText(dc, layout, box, colour, bgrColour, labelBgr, width):
    """Draw a ruler's text, joined to the middle of the bar by a dotted line
    when it had to move."""

    if layout["offset"] != (0.0, 0.0):
        edge = box[3] if not layout["flipped"] else box[1]
        dc.SetPen(wx.Pen(colour, width, wx.PENSTYLE_DOT))
        dc.DrawLine(int(layout["mid"]), int(layout["yBar"]), int((box[0] + box[2]) / 2.0), int(edge))
    dc.SetFont(layout["font"])
    if labelBgr:
        dc.SetBackgroundMode(_WX_BRUSHSTYLE_SOLID)
        dc.SetTextBackground(bgrColour)
    else:
        dc.SetBackgroundMode(_WX_BRUSHSTYLE_TRANSPARENT)
    dc.SetTextForeground(colour)
    dc.DrawText(layout["text"], int(box[0]), int(box[1]))
    dc.SetBackgroundMode(_WX_BRUSHSTYLE_TRANSPARENT)


def rulerObstacles(geometry, printerScale=None):
    """Boxes drawn rulers take, as drawRuler's placed wants them.

    geometry is what drawRuler returned for each, as a plot object keeps it
    (rulerGeometry): [(key, (x1, y1, x2, y2, yBar, box))].
    """

    scale = printerScale["drawings"] if printerScale else 1.0
    tick = 4 * scale
    boxes = []
    for _key, (x1, _y1, x2, _y2, yBar, box) in geometry:
        boxes.append((x1, yBar - tick, x2, yBar + tick))
        boxes.append(box)
    return boxes


def _overlaps(a, b):
    """Whether two (x1, y1, x2, y2) boxes overlap."""

    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]



# Measured text extents, keyed by output device, font and string. A dense
# peaklist asks for a thousand of them per frame and, while the view sits
# still, hands back the very same labels frame after frame, so measuring each
# one once pays for itself many times over. The device and font are part of the
# key so an export or a printout never reuses screen metrics.
_TEXT_EXTENT_LIMIT = 20000
_textExtents = {}


def _textExtent(dc, deviceKey, text):
    """Width and height of *text* on *dc*, remembered between frames."""

    key = (deviceKey, text)
    extent = _textExtents.get(key)
    if extent is None:
        if len(_textExtents) > _TEXT_EXTENT_LIMIT:
            _textExtents.clear()
        extent = _textExtents[key] = dc.GetTextExtent(text).Get()

    return extent


# ----


# Pre-rendered label badges, keyed by everything that can change how one looks.
# wxDC.DrawRotatedText builds a rotated font on every call -- on wxMSW that is
# a CreateFontIndirect/DeleteObject pair per label -- and a dense spectrum
# draws hundreds of the same handful of labels frame after frame. Painting each
# one once into a small bitmap and blitting it thereafter measures about twenty
# times faster, and the badge is opaque so the blit is an exact substitute.
_LABEL_BITMAP_LIMIT = 4000
_labelBitmaps = {}

# offset of the badge's top-left corner from the anchor wxDC.DrawRotatedText
# rotates about, and the anchor to use when painting the badge, both as
# multiples of the unrotated text width and height
_LABEL_ANGLES = {
    #        badge size    top-left offset      anchor within badge
    0: (lambda w, h: (w, h), lambda w, h: (0, 0), lambda w, h: (0, 0)),
    90: (lambda w, h: (h, w), lambda w, h: (0, -w), lambda w, h: (0, w)),
    -90: (lambda w, h: (h, w), lambda w, h: (-h, 0), lambda w, h: (h, 0)),
}


def _labelBadge(dc, key, text, angle, font, colour, bgrColour, scale):
    """Badge bitmap for *text* plus its offset from the anchor point.

    Painted once and remembered, so the hot path is a dict lookup and a blit --
    no text measuring, no font building.
    """

    badge = _labelBitmaps.get(key)
    if badge is not None:
        return badge

    textWidth, textHeight = dc.GetTextExtent(text)
    if textWidth <= 0 or textHeight <= 0:
        return None

    size, offset, anchor = _LABEL_ANGLES[angle]
    width, height = size(textWidth, textHeight)
    anchorX, anchorY = anchor(textWidth, textHeight)

    # matched to the destination so the blit stays 1:1 on HiDPI, where the plot
    # buffer holds device pixels but is drawn into in logical coordinates
    bitmap = wx.Bitmap()
    bitmap.CreateWithDIPSize(wx.Size(width, height), scale, depth=24)

    memory = wx.MemoryDC(bitmap)
    memory.SetBackground(wx.Brush(bgrColour, _WX_BRUSHSTYLE_SOLID))
    memory.Clear()
    memory.SetFont(font)
    memory.SetTextForeground(colour)
    memory.SetBackgroundMode(_WX_BRUSHSTYLE_TRANSPARENT)
    memory.DrawRotatedText(text, anchorX, anchorY, angle)
    memory.SelectObject(wx.NullBitmap)

    if len(_labelBitmaps) > _LABEL_BITMAP_LIMIT:
        _labelBitmaps.clear()

    offsetX, offsetY = offset(textWidth, textHeight)
    badge = _labelBitmaps[key] = (bitmap, offsetX, offsetY)

    return badge


def _drawLabel(dc, badgeKey, text, x, y, angle, font, colour, bgrColour, scale):
    """Draw one peak label, through the badge cache when there is one.

    *badgeKey* is None for the cases the cache cannot stand in for: a
    transparent label (the badge has no mask), an angle other than flat or
    upright, and any device other than the screen buffer -- an SVG or printer
    DC has to keep its labels as text rather than as pasted pixels.
    """

    if badgeKey is not None:
        badge = _labelBadge(
            dc, badgeKey + (text,), text, angle, font, colour, bgrColour, scale
        )
        if badge is not None:
            bitmap, offsetX, offsetY = badge
            dc.DrawBitmap(bitmap, x + offsetX, y + offsetY, False)
            return

    dc.DrawRotatedText(text, x, y, angle)


# ----


def _scaleFont(font, scale):
    """Return a copy of font scaled linearly by scale.

    The print/export legibility boost is already folded into
    printerScale["fonts"] by the canvas (see _print_font_scale), so this must
    stay a pure linear scale or printed labels would be boosted twice.
    """

    # check printerScale
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


def _scaleAndShift(points, scaleX, scaleY, shiftX, shiftY):
    """Scale and shift signal points used by plot. New array is returned.
    points (numpy array) - data points
    scaleX (float) - x-axis scale
    scaleY (float) - y-axis scale
    shiftX (float) - x-axis shift
    shiftY (float) - y-axis shift
    """

    # check signal type
    if not isinstance(points, numpy.ndarray):
        raise TypeError("Signal points must be NumPy array!")
    if points.dtype.name != "float64":
        raise TypeError("Signal points must be float64!")

    # check signal data
    if len(points) == 0:
        return numpy.array([])

    # scale and shift signal
    return calculations.signal_rescale(
        points, float(scaleX), float(scaleY), float(shiftX), float(shiftY)
    )


# ----


def _filterPoints(points, resolution):
    """Filter signal points according to resolution. New array is returned.
    points (numpy array) - data points
    resolution (float) - resolution point size
    """

    # check signal type
    if not isinstance(points, numpy.ndarray):
        raise TypeError("Signal points must be NumPy array!")
    if points.dtype.name != "float64":
        raise TypeError("Signal points must be float64!")

    # check signal data
    if len(points) == 0:
        return numpy.array([])

    # filter signal
    return calculations.signal_filter(points, float(resolution))


# Heuristic for turning a sparse, zoomed-in profile gel back into a continuous
# band. A gap between two adjacent sampled columns is treated as real signal
# (and bridged with an interpolated shade) when it is no wider than this
# multiple of the typical column spacing; wider gaps are left at the background
# "zero" shade so genuinely missing data still reads as empty. The minimum
# guards the zoomed-out case where the typical spacing rounds down to one
# column and a 2-3px rounding gap should still be bridged.
_GEL_FILL_GAP_FACTOR = 4
_GEL_FILL_GAP_MIN = 4


# Gel columns are encoded as a single scalar in [0, 510] so the whole pipeline
# (per-column reduction, gap interpolation, run-length merging) stays 1-D:
#   0   == the tallest peak           -> solid (black in light, white in dark)
#   255 == the zero baseline / no data -> empty (white in light, black in dark)
#   510 == a trough as deep as the tallest peak -> saturated red
# The 255..510 half is the negative ramp: a virtual gel can't be "blacker than
# black", so below-zero signal is shown by reddening instead of darkening.
_GEL_ZERO = 255
_GEL_RED_MAX = 510


def _gel_values_to_rgb(values, dark_mode):
    """Map gel column values in [0, 510] onto (R, G, B) int arrays.

    Positive signal (0..255) is grayscale; negative signal (255..510) keeps the
    zero baseline's empty colour but mixes in progressively more red, reaching
    pure red (255, 0, 0) for a trough as deep as the tallest peak. Red is scaled
    to the tallest peak (the same reference as the grayscale), so a shallow
    trough stays only faintly red even when it is the most negative point.
    """

    values = numpy.clip(numpy.rint(values), 0, _GEL_RED_MAX).astype(numpy.int32)
    is_red = values > _GEL_ZERO
    red_amt = numpy.clip(values - _GEL_ZERO, 0, 255)
    gray = numpy.clip(values, 0, 255)

    if dark_mode:
        # Empty is black; redden up from black, darken peaks down to white.
        gray_shade = 255 - gray
        red = numpy.where(is_red, red_amt, gray_shade)
        green = numpy.where(is_red, 0, gray_shade)
    else:
        # Empty is white; redden by draining green/blue, darken peaks to black.
        gray_shade = gray
        red = numpy.where(is_red, 255, gray_shade)
        green = numpy.where(is_red, 255 - red_amt, gray_shade)
    blue = green

    return red.astype(numpy.int32), green.astype(numpy.int32), blue.astype(numpy.int32)


def _build_gel_runs(
    scaled_points,
    zero_y,
    scale,
    flipped,
    pixel_step,
    plot_x1,
    plot_x2,
    dark_mode,
    fill_gaps=False,
):
    """Build run-length encoded gel stripes as (x_start, width, r, g, b).

    Every visible column receives a colour so the gel paints its whole band and
    columns with no data take the background "zero" colour (white in light mode,
    black in dark mode) rather than letting the plot background show through.
    Below-zero (negative) signal is rendered as red rather than collapsed to
    empty (see ``_gel_values_to_rgb``).

    ``zero_y`` is the screen-y of the zero line and ``scale`` the screen distance
    from it to the largest absolute intensity on display; together they map each
    point's signed distance from zero onto the [0, 510] gel value.

    When ``fill_gaps`` is set, columns that fall in a normal-sized gap between
    sampled points are filled with a value linearly interpolated from their
    neighbours, so a sparse, zoomed-in profile reads as a continuous band
    instead of isolated vertical lines. Abnormally wide gaps (relative to the
    local sampling density) are left empty so truly missing data stays
    distinguishable.
    """

    if len(scaled_points) == 0 or scale <= 0:
        return []

    plot_x1 = int(plot_x1)
    plot_x2 = int(plot_x2)
    if plot_x2 <= plot_x1:
        return []

    x_values = numpy.rint(scaled_points[:, 0]).astype(numpy.int64)

    # Map screen-y to the [0, 510] gel value via signed distance from zero:
    # +scale (tallest peak) -> 0, 0 (zero line) -> 255, -scale (deepest trough)
    # -> 510. For flipped spectra the signal direction is mirrored about zero.
    signed = (zero_y - scaled_points[:, 1]) if not flipped else (
        scaled_points[:, 1] - zero_y
    )
    signal = 255.0 * (1.0 - signed / scale)
    signal = numpy.clip(signal, 0.0, float(_GEL_RED_MAX))

    # Quantize columns to drawing step so work scales with visible pixels, not
    # with the number of source data points. Keep the most prominent feature per
    # column -- the value farthest from the zero baseline -- so thin tall peaks
    # stay dark and deep troughs stay red even between samples.
    bins = (x_values // pixel_step).astype(numpy.int64)
    unique_bins, inverse = numpy.unique(bins, return_inverse=True)
    col_min = numpy.full(unique_bins.shape, numpy.inf)
    col_max = numpy.full(unique_bins.shape, -numpy.inf)
    numpy.minimum.at(col_min, inverse, signal)
    numpy.maximum.at(col_max, inverse, signal)
    use_max = numpy.abs(col_max - _GEL_ZERO) >= numpy.abs(col_min - _GEL_ZERO)
    sample = numpy.where(use_max, col_max, col_min)

    # Build a value for every visible column; 255 == background "zero".
    first_bin = plot_x1 // pixel_step
    last_bin = (plot_x2 - 1) // pixel_step
    grid_bins = numpy.arange(first_bin, last_bin + 1, dtype=numpy.int64)
    if len(grid_bins) == 0:
        return []

    values = numpy.full(grid_bins.shape, float(_GEL_ZERO))

    # Place the sampled columns onto the grid.
    offset = unique_bins - first_bin
    inside = (offset >= 0) & (offset < len(grid_bins))
    values[offset[inside]] = sample[inside]

    if fill_gaps and len(unique_bins) >= 2:
        gaps = numpy.diff(unique_bins)
        max_gap = max(_GEL_FILL_GAP_MIN, _GEL_FILL_GAP_FACTOR * numpy.median(gaps))

        # Linear interpolation across every column from the sampled points;
        # off-data columns become "zero" via left/right.
        interp = numpy.interp(
            grid_bins, unique_bins, sample, left=_GEL_ZERO, right=_GEL_ZERO
        )

        # Only keep the interpolated value where the bridged gap is narrow
        # enough to be real signal and the column is not itself a sample.
        seg = numpy.searchsorted(unique_bins, grid_bins, side="right") - 1
        within = (seg >= 0) & (seg < len(unique_bins) - 1)
        seg_clipped = numpy.clip(seg, 0, len(unique_bins) - 1)
        on_sample = grid_bins == unique_bins[seg_clipped]
        seg_gap = numpy.zeros(grid_bins.shape, dtype=numpy.int64)
        seg_gap[within] = gaps[seg[within]]
        fillable = within & (~on_sample) & (seg_gap <= max_gap)

        values[fillable] = interp[fillable]

    vq = numpy.clip(numpy.rint(values), 0, _GEL_RED_MAX).astype(numpy.int32)

    # Clip each column to the visible plot area.
    raw_start = grid_bins * pixel_step
    x_start = numpy.maximum(raw_start, plot_x1)
    x_end = numpy.minimum(raw_start + pixel_step, plot_x2)
    widths = x_end - x_start

    valid = widths > 0
    if not numpy.any(valid):
        return []
    x_start = x_start[valid]
    x_end = x_end[valid]
    vq = vq[valid]

    # Merge contiguous columns with identical values to minimize DC calls.
    change = numpy.ones(len(vq), dtype=bool)
    change[1:] = vq[1:] != vq[:-1]
    starts = numpy.where(change)[0]
    last_in_run = numpy.r_[starts[1:] - 1, len(vq) - 1]
    run_x = x_start[starts]
    run_w = x_end[last_in_run] - run_x
    run_r, run_g, run_b = _gel_values_to_rgb(vq[starts], dark_mode)

    return list(
        zip(
            run_x.tolist(),
            run_w.tolist(),
            run_r.tolist(),
            run_g.tolist(),
            run_b.tolist(),
            strict=True,
        )
    )


def _compress_screen_polyline(points):
    """Drop redundant vertices in integer screen-space polylines.

    This is intended for dense, noisy traces where many source points map to
    the same pixel columns during rendering.
    """

    if len(points) < 3:
        return points

    pts = points

    # 1) Remove exact consecutive duplicates.
    diffs = numpy.diff(pts, axis=0)
    keep = numpy.ones(len(pts), dtype=bool)
    keep[1:] = (diffs[:, 0] != 0) | (diffs[:, 1] != 0)
    pts = pts[keep]
    if len(pts) < 3:
        return pts

    # 2) For vertical runs (same x), keep only first/min/max/last points.
    #
    # Done without a per-run Python loop: a dense spectrum has one run per
    # occupied pixel column, so the loop used to run about a thousand times per
    # frame and dominated the redraw.  Runs of one or two points need no
    # special case -- their min and max are already the endpoints.
    x = pts[:, 0]
    run_starts = numpy.r_[0, numpy.where(x[1:] != x[:-1])[0] + 1]
    run_ends = numpy.r_[run_starts[1:] - 1, len(pts) - 1]

    ys = pts[:, 1]
    count = len(pts)
    # which run each point belongs to
    run_of = numpy.zeros(count, dtype=numpy.intp)
    run_of[run_starts[1:]] = 1
    numpy.cumsum(run_of, out=run_of)

    # first index at which each run attains its minimum, and its maximum
    indices = numpy.arange(count, dtype=numpy.intp)
    at_min = ys == numpy.minimum.reduceat(ys, run_starts)[run_of]
    at_max = ys == numpy.maximum.reduceat(ys, run_starts)[run_of]
    i_min = numpy.minimum.reduceat(numpy.where(at_min, indices, count), run_starts)
    i_max = numpy.minimum.reduceat(numpy.where(at_max, indices, count), run_starts)

    # the four keepers of every run, in order; runs are already in order, so
    # dropping repeats from the flattened result leaves exactly the sorted
    # unique index list
    keepers = numpy.stack((run_starts, i_min, i_max, run_ends), axis=1)
    keepers.sort(axis=1)
    keepers = keepers.ravel()
    unique = numpy.ones(len(keepers), dtype=bool)
    unique[1:] = keepers[1:] != keepers[:-1]

    pts = pts[keepers[unique]]
    if len(pts) < 3:
        return pts

    # 3) Remove collinear middle points that continue in the same direction.
    a = pts[:-2]
    b = pts[1:-1]
    c = pts[2:]

    ab = b - a
    bc = c - b
    cross = ab[:, 0] * bc[:, 1] - ab[:, 1] * bc[:, 0]
    same_dir = (ab[:, 0] * bc[:, 0] >= 0) & (ab[:, 1] * bc[:, 1] >= 0)

    keep_mid = ~((cross == 0) & same_dir)
    keep = numpy.ones(len(pts), dtype=bool)
    keep[1:-1] = keep_mid
    return pts[keep]


# ----
