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
import xml.sax
from xml.sax.handler import ContentHandler
import xml.dom.minidom
import base64
import zlib
import struct
import re
import os.path
import numpy
from copy import deepcopy

# load objects
from . import obj_peak
from . import obj_peaklist
from . import obj_scan

# compile basic patterns
RETENTION_TIME_PATTERN = re.compile(r"^PT((\d*\.?\d*)M)?((\d*\.?\d*)S)?$")


# PARSE mzXML DATA
# ----------------


class parseMZXML:
    """Parse data from mzXML."""

    def __init__(self, path):
        self.path = path
        self._scans = None
        self._scanlist = None
        self._info = None

        # check path
        if not os.path.exists(path):
            raise IOError("File not found! --> " + self.path)

    # ----

    def load(self):
        """Load all scans into memory."""

        # init parser
        handler = runHandler()
        parser = xml.sax.make_parser()
        parser.setContentHandler(handler)

        # parse document
        try:
            with open(self.path, "rb") as document:
                parser.parse(document)
            self._scans = handler.data
        except xml.sax.SAXException:
            self._scans = False

        # make scanlist
        if self._scans:
            self._scanlist = deepcopy(self._scans)
            for scanNumber in self._scanlist:
                del self._scanlist[scanNumber]["points"]
                del self._scanlist[scanNumber]["byteOrder"]
                del self._scanlist[scanNumber]["compression"]
                del self._scanlist[scanNumber]["precision"]
                del self._scanlist[scanNumber]["peakPoints"]
                del self._scanlist[scanNumber]["peakByteOrder"]
                del self._scanlist[scanNumber]["peakCompression"]
                del self._scanlist[scanNumber]["peakPrecision"]

    # ----

    def info(self):
        """Get document info."""

        # get preloaded data if available
        if self._info:
            return self._info

        # init parser
        handler = infoHandler()
        parser = xml.sax.make_parser()
        parser.setContentHandler(handler)

        # parse document
        try:
            with open(self.path, "rb") as document:
                parser.parse(document)
        except stopParsing:
            self._info = handler.data
        except xml.sax.SAXException:
            self._info = False

        return self._info

    # ----

    def scanlist(self):
        """Get list of all scans in the document."""

        # use preloaded data if available
        if self._scanlist:
            return self._scanlist

        # init parser
        handler = scanlistHandler()
        parser = xml.sax.make_parser()
        parser.setContentHandler(handler)

        # parse document
        try:
            with open(self.path, "rb") as document:
                parser.parse(document)
            self._scanlist = handler.data
        except xml.sax.SAXException:
            self._scanlist = False

        return self._scanlist

    # ----

    def scan(self, scanID=None):
        """Get spectrum from document."""

        # use preloaded data if available
        if isinstance(self._scans, dict) and scanID in self._scans:
            data = self._scans[scanID]

        # parse file
        else:
            handler = scanHandler(scanID)
            parser = xml.sax.make_parser()
            parser.setContentHandler(handler)
            try:
                with open(self.path, "rb") as document:
                    parser.parse(document)
                data = handler.data
            except stopParsing:
                data = handler.data
            except xml.sax.SAXException:
                return False

        # check data
        if not data:
            return False

        # return scan
        return self._makeScan(data)

    # ----

    def _makeScan(self, scanData):
        """Make scan object from raw data."""

        # parse peaks
        points = self._parsePoints(scanData)
        if scanData["spectrumType"] == "discrete":
            peaks = [obj_peak.peak(p[0], p[1]) for p in points]
            scan = obj_scan.scan(peaklist=obj_peaklist.peaklist(peaks))
        else:
            scan = obj_scan.scan(profile=points)

            # attach the mMass peak-list extension (peaks stored with a profile)
            peakPoints = self._parsePeakPoints(scanData)
            if len(peakPoints):
                peaks = [obj_peak.peak(p[0], p[1]) for p in peakPoints]
                scan.setpeaklist(obj_peaklist.peaklist(peaks))

        # set metadata
        scan.title = scanData["title"]
        scan.scanNumber = scanData["scanNumber"]
        scan.parentScanNumber = scanData["parentScanNumber"]
        scan.msLevel = scanData["msLevel"]
        scan.polarity = scanData["polarity"]
        scan.retentionTime = scanData["retentionTime"]
        scan.totIonCurrent = scanData["totIonCurrent"]
        scan.basePeakMZ = scanData["basePeakMZ"]
        scan.basePeakIntensity = scanData["basePeakIntensity"]
        scan.precursorMZ = scanData["precursorMZ"]
        scan.precursorIntensity = scanData["precursorIntensity"]
        scan.precursorCharge = scanData["precursorCharge"]

        return scan

    # ----

    def _parsePoints(self, scanData):
        """Parse spectrum data."""

        # check data
        if not scanData["points"]:
            return []

        # decode interleaved pairs
        data = self._decodePeaks(
            scanData["points"],
            scanData["byteOrder"],
            scanData["compression"],
            scanData["precision"],
        )

        # format
        if scanData["spectrumType"] == "discrete":
            data = list(map(list, list(zip(data[::2], data[1::2], strict=False))))
        else:
            data = numpy.array(data)
            data.shape = (-1, 2)
            data = data.astype(numpy.float64)

        return data

    # ----

    def _parsePeakPoints(self, scanData):
        """Parse the mMass peak-list extension (interleaved m/z-intensity pairs)."""

        if not scanData.get("peakPoints"):
            return []

        data = self._decodePeaks(
            scanData["peakPoints"],
            scanData["peakByteOrder"],
            scanData["peakCompression"],
            scanData["peakPrecision"],
        )

        return list(map(list, list(zip(data[::2], data[1::2], strict=False))))

    # ----

    def _decodePeaks(self, encoded, byteOrder, compression, precision):
        """Decode a base64/zlib interleaved peaks blob into a flat array."""

        # get precision
        fmt = "d" if precision == 64 else "f"

        # get endian (mzXML defaults to network/big-endian)
        endian = "<" if byteOrder == "little" else ">"

        # decode and decompress
        data = base64.b64decode(encoded)
        if compression == "zlib":
            data = zlib.decompress(data)

        # convert from binary
        size = struct.calcsize(endian + fmt)
        return numpy.frombuffer(data[: (len(data) // size) * size], dtype=endian + fmt)

    # ----


class infoHandler(ContentHandler):
    """Get info data."""

    def __init__(self):

        self.data = {
            "title": "",
            "operator": "",
            "contact": "",
            "institution": "",
            "date": "",
            "instrument": "",
            "notes": "",
        }

    # ----

    def startElement(self, name, attrs):
        """Element started."""

        # get instrument
        if name == "msManufacturer":
            self.data["instrument"] += attrs.get("value", "") + " "
        elif name == "msModel":
            self.data["instrument"] += attrs.get("value", "") + " "
        elif name == "msIonisation":
            self.data["instrument"] += attrs.get("value", "") + " "
        elif name == "msMassAnalyzer":
            self.data["instrument"] += attrs.get("value", "") + " "

    # ----

    def endElement(self, name):
        """Element ended."""

        # stop parsing
        if name == "msInstrument":
            raise stopParsing()

    # ----


class scanlistHandler(ContentHandler):
    """Get list of all scans in the document."""

    def __init__(self):
        self.data = {}
        self.currentID = None
        self._isPrecursor = False
        self._scanHierarchy: list[int | None] = [None]
        self._spectrumType = "unknown"

    # ----

    def startElement(self, name, attrs):
        """Element started."""

        # get data type
        if name == "dataProcessing":
            centroided = attrs.get("centroided", "0")
            if centroided and centroided != "0":
                self._spectrumType = "discrete"

        # get scan data
        elif name == "scan":

            # get scan ID
            self.currentID = attrs.get("num", None)
            if self.currentID is not None:
                self.currentID = int(self.currentID)

            # add scan to hierarchy
            self._scanHierarchy.append(self.currentID)

            scan = {
                "title": "",
                "scanNumber": self.currentID,
                "parentScanNumber": self._scanHierarchy[-2],
                "msLevel": None,
                "pointsCount": None,
                "polarity": None,
                "retentionTime": None,
                "lowMZ": None,
                "highMZ": None,
                "basePeakMZ": None,
                "basePeakIntensity": None,
                "totIonCurrent": None,
                "precursorMZ": None,
                "precursorIntensity": None,
                "precursorCharge": None,
                "spectrumType": self._spectrumType,
            }

            # get ms level
            attribute = attrs.get("msLevel", "1")
            if attribute:
                scan["msLevel"] = int(attribute)

            # get number of points
            attribute = attrs.get("peaksCount", None)
            if attribute is not None:
                scan["pointsCount"] = int(attribute)

            # honor per-scan centroided flag (overrides the global default)
            attribute = attrs.get("centroided", None)
            if attribute is not None:
                if attribute in ("0", "false", "False"):
                    scan["spectrumType"] = "continuous"
                else:
                    scan["spectrumType"] = "discrete"

            # get polarity
            attribute = attrs.get("polarity", None)
            if attribute in ("positive", "Positive", "+"):
                scan["polarity"] = 1
            elif attribute in ("negative", "Negative", "-"):
                scan["polarity"] = -1

            # get scan retention time
            attribute = attrs.get("retentionTime", None)
            if attribute is not None:
                scan["retentionTime"] = _convertRetentionTime(attribute)

            # get low m/z
            attribute = attrs.get("lowMz", None)
            if attribute is not None:
                scan["lowMZ"] = float(attribute)

            # get high m/z
            attribute = attrs.get("highMz", None)
            if attribute is not None:
                scan["highMZ"] = float(attribute)

            # get base peak m/z
            attribute = attrs.get("basePeakMz", None)
            if attribute is not None:
                scan["basePeakMZ"] = float(attribute)

            # get base peak intensity
            attribute = attrs.get("basePeakIntensity", None)
            if attribute is not None:
                scan["basePeakIntensity"] = max(0.0, float(attribute))

            # get total ion current
            attribute = attrs.get("totIonCurrent", None)
            if attribute is not None:
                scan["totIonCurrent"] = max(0.0, float(attribute))

            # add scan
            self.data[self.currentID] = scan

        # get precursor data
        elif name == "precursorMz":
            self._isPrecursor = True
            self.data[self.currentID]["precursorMZ"] = ""

            # get precursor intensity
            attribute = attrs.get("precursorIntensity", None)
            if attribute is not None:
                self.data[self.currentID]["precursorIntensity"] = max(
                    0.0, float(attribute)
                )

            # get precursor charge
            attribute = attrs.get("precursorCharge", None)
            if attribute is not None:
                self.data[self.currentID]["precursorCharge"] = int(attribute)

    # ----

    def endElement(self, name):
        """Element ended."""

        # remove scan from hierarchy
        if name == "scan":
            del self._scanHierarchy[-1]
            self.currentID = self._scanHierarchy[-1]

        # stop reading precursor data
        elif name == "precursorMz":
            self._isPrecursor = False

            # get precursor m/z
            if self.data[self.currentID]["precursorMZ"]:
                self.data[self.currentID]["precursorMZ"] = float(
                    self.data[self.currentID]["precursorMZ"]
                )
            else:
                self.data[self.currentID]["precursorMZ"] = None

    # ----

    def characters(self, content):
        """Grab characters."""

        # get precursor mz
        if self._isPrecursor:
            self.data[self.currentID]["precursorMZ"] += content

    # ----


class scanHandler(ContentHandler):
    """Get scan data."""

    def __init__(self, scanID):
        self.data = {}
        self.scanID = scanID

        self._isMatch = False
        self._isPeaks = False
        self._isPeakList = False
        self._isPrecursor = False
        self._scanHierarchy: list[int | None] = [None]
        self._spectrumType = "unknown"

    # ----

    def startElement(self, name, attrs):
        """Element started."""

        # get data type
        if name == "dataProcessing":
            centroided = attrs.get("centroided", "0")
            if centroided and centroided != "0":
                self._spectrumType = "discrete"

        # get scan metadata
        elif name == "scan":
            self._isMatch = False

            # get scan ID
            scanID = attrs.get("num", None)
            if scanID is not None:
                scanID = int(scanID)

            # add scan to hierarchy
            self._scanHierarchy.append(scanID)

            # selected scan
            if self.scanID is None or self.scanID == scanID:
                self._isMatch = True

                self.data = {
                    "title": "",
                    "scanNumber": scanID,
                    "parentScanNumber": self._scanHierarchy[-2],
                    "msLevel": None,
                    "pointsCount": None,
                    "polarity": None,
                    "retentionTime": None,
                    "lowMZ": None,
                    "highMZ": None,
                    "basePeakMZ": None,
                    "basePeakIntensity": None,
                    "totIonCurrent": None,
                    "precursorMZ": None,
                    "precursorIntensity": None,
                    "precursorCharge": None,
                    "spectrumType": self._spectrumType,
                    "points": None,
                    "byteOrder": None,
                    "compression": None,
                    "precision": None,
                    "peakPoints": None,
                    "peakByteOrder": None,
                    "peakCompression": None,
                    "peakPrecision": None,
                }

                # get ms level
                attribute = attrs.get("msLevel", "1")
                if attribute:
                    self.data["msLevel"] = int(attribute)

                # get number of points
                attribute = attrs.get("peaksCount", None)
                if attribute is not None:
                    self.data["pointsCount"] = int(attribute)

                # honor per-scan centroided flag (overrides the global default)
                attribute = attrs.get("centroided", None)
                if attribute is not None:
                    if attribute in ("0", "false", "False"):
                        self.data["spectrumType"] = "continuous"
                    else:
                        self.data["spectrumType"] = "discrete"

                # get polarity
                attribute = attrs.get("polarity", None)
                if attribute in ("positive", "Positive", "+"):
                    self.data["polarity"] = 1
                elif attribute in ("negative", "Negative", "-"):
                    self.data["polarity"] = -1

                # get scan retention time
                attribute = attrs.get("retentionTime", None)
                if attribute is not None:
                    self.data["retentionTime"] = _convertRetentionTime(attribute)

                # get low m/z
                attribute = attrs.get("lowMz", None)
                if attribute is not None:
                    self.data["lowMZ"] = float(attribute)

                # get high m/z
                attribute = attrs.get("highMz", None)
                if attribute is not None:
                    self.data["highMZ"] = float(attribute)

                # get base peak m/z
                attribute = attrs.get("basePeakMz", None)
                if attribute is not None:
                    self.data["basePeakMZ"] = float(attribute)

                # get base peak intensity
                attribute = attrs.get("basePeakIntensity", None)
                if attribute is not None:
                    self.data["basePeakIntensity"] = max(0.0, float(attribute))

                # get total ion current
                attribute = attrs.get("totIonCurrent", None)
                if attribute is not None:
                    self.data["totIonCurrent"] = max(0.0, float(attribute))

        # get peaks data
        elif name == "peaks" and self._isMatch:
            self._isPeaks = True

            # the mMass peak-list extension is stored separately from the main
            # spectrum data so peaks travel with a profile in a single scan
            self._isPeakList = attrs.get("contentType", "") == "mMass-peaklist"
            keyPoints = "peakPoints" if self._isPeakList else "points"
            keyByteOrder = "peakByteOrder" if self._isPeakList else "byteOrder"
            keyCompression = "peakCompression" if self._isPeakList else "compression"
            keyPrecision = "peakPrecision" if self._isPeakList else "precision"

            self.data[keyPoints] = []

            # get byte order
            self.data[keyByteOrder] = attrs.get("byteOrder", "network")

            # get compression
            attribute = attrs.get("compressionType", None)
            if attribute and attribute != "none":
                self.data[keyCompression] = attribute

            # get precision
            attribute = attrs.get("precision", "32")
            if attribute:
                self.data[keyPrecision] = int(attribute)

        # get precursor data
        elif name == "precursorMz" and self._isMatch:
            self._isPrecursor = True
            self.data["precursorMZ"] = ""

            # get precursor intensity
            attribute = attrs.get("precursorIntensity", None)
            if attribute is not None:
                self.data["precursorIntensity"] = max(0.0, float(attribute))

            # get precursor charge
            attribute = attrs.get("precursorCharge", None)
            if attribute is not None:
                self.data["precursorCharge"] = int(attribute)

    # ----

    def endElement(self, name):
        """Element ended."""

        # stop parsing
        if name == "scan" and self._isMatch:
            raise stopParsing()

        # remove scan from hierarchy
        elif name == "scan":
            del self._scanHierarchy[-1]
            if self._scanHierarchy[-1] == self.scanID:
                self._isMatch = True

        # stop reading peaks data
        elif name == "peaks" and self._isMatch:
            self._isPeaks = False
            key = "peakPoints" if self._isPeakList else "points"
            self.data[key] = "".join(self.data[key])
            if not self.data[key]:
                self.data[key] = None
            self._isPeakList = False

        # stop reading precursor data
        elif name == "precursorMz" and self._isMatch:
            self._isPrecursor = False

            # get precursor m/z
            if self.data["precursorMZ"]:
                self.data["precursorMZ"] = float(self.data["precursorMZ"])
            else:
                self.data["precursorMZ"] = None

    # ----

    def characters(self, content):
        """Grab characters."""

        # get peaks (main spectrum data or the mMass peak-list extension)
        if self._isPeaks:
            key = "peakPoints" if self._isPeakList else "points"
            self.data[key].append(content)

        # get precursor
        if self._isPrecursor:
            self.data["precursorMZ"] += content

    # ----


class runHandler(ContentHandler):
    """Get whole run."""

    def __init__(self):
        self.data = {}
        self.currentID = None

        self._isPeaks = False
        self._isPeakList = False
        self._isPrecursor = False
        self._scanHierarchy: list[int | None] = [None]
        self._spectrumType = "unknown"

    # ----

    def startElement(self, name, attrs):
        """Element started."""

        # get data type
        if name == "dataProcessing":
            centroided = attrs.get("centroided", "0")
            if centroided and centroided != "0":
                self._spectrumType = "discrete"

        # get scan data
        elif name == "scan":

            # get scan ID
            self.currentID = attrs.get("num", None)
            if self.currentID is not None:
                self.currentID = int(self.currentID)

            # add scan to hierarchy
            self._scanHierarchy.append(self.currentID)

            scan = {
                "title": "",
                "scanNumber": self.currentID,
                "parentScanNumber": self._scanHierarchy[-2],
                "msLevel": None,
                "pointsCount": None,
                "polarity": None,
                "retentionTime": None,
                "lowMZ": None,
                "highMZ": None,
                "basePeakMZ": None,
                "basePeakIntensity": None,
                "totIonCurrent": None,
                "precursorMZ": None,
                "precursorIntensity": None,
                "precursorCharge": None,
                "spectrumType": self._spectrumType,
                "points": None,
                "byteOrder": None,
                "compression": None,
                "precision": None,
                "peakPoints": None,
                "peakByteOrder": None,
                "peakCompression": None,
                "peakPrecision": None,
            }

            # get ms level
            attribute = attrs.get("msLevel", "1")
            if attribute:
                scan["msLevel"] = int(attribute)

            # get number of points
            attribute = attrs.get("peaksCount", None)
            if attribute is not None:
                scan["pointsCount"] = int(attribute)

            # honor per-scan centroided flag (overrides the global default)
            attribute = attrs.get("centroided", None)
            if attribute is not None:
                if attribute in ("0", "false", "False"):
                    scan["spectrumType"] = "continuous"
                else:
                    scan["spectrumType"] = "discrete"

            # get polarity
            attribute = attrs.get("polarity", None)
            if attribute in ("positive", "Positive", "+"):
                scan["polarity"] = 1
            elif attribute in ("negative", "Negative", "-"):
                scan["polarity"] = -1

            # get scan retention time
            attribute = attrs.get("retentionTime", None)
            if attribute is not None:
                scan["retentionTime"] = _convertRetentionTime(attribute)

            # get low m/z
            attribute = attrs.get("lowMz", None)
            if attribute is not None:
                scan["lowMZ"] = float(attribute)

            # get high m/z
            attribute = attrs.get("highMz", None)
            if attribute is not None:
                scan["highMZ"] = float(attribute)

            # get base peak m/z
            attribute = attrs.get("basePeakMz", None)
            if attribute is not None:
                scan["basePeakMZ"] = float(attribute)

            # get base peak intensity
            attribute = attrs.get("basePeakIntensity", None)
            if attribute is not None:
                scan["basePeakIntensity"] = max(0.0, float(attribute))

            # get total ion current
            attribute = attrs.get("totIonCurrent", None)
            if attribute is not None:
                scan["totIonCurrent"] = max(0.0, float(attribute))

            # add scan
            self.data[self.currentID] = scan

        # get peaks data
        elif name == "peaks":
            self._isPeaks = True

            # the mMass peak-list extension is stored separately from the main
            # spectrum data so peaks travel with a profile in a single scan
            self._isPeakList = attrs.get("contentType", "") == "mMass-peaklist"
            keyPoints = "peakPoints" if self._isPeakList else "points"
            keyByteOrder = "peakByteOrder" if self._isPeakList else "byteOrder"
            keyCompression = "peakCompression" if self._isPeakList else "compression"
            keyPrecision = "peakPrecision" if self._isPeakList else "precision"

            self.data[self.currentID][keyPoints] = []

            # get byte order
            self.data[self.currentID][keyByteOrder] = attrs.get("byteOrder", "network")

            # get compression
            attribute = attrs.get("compressionType", None)
            if attribute and attribute != "none":
                self.data[self.currentID][keyCompression] = attribute

            # get precision
            attribute = attrs.get("precision", "32")
            if attribute:
                self.data[self.currentID][keyPrecision] = int(attribute)

        # get precursor data
        elif name == "precursorMz":
            self._isPrecursor = True
            self.data[self.currentID]["precursorMZ"] = ""

            # get precursor intensity
            attribute = attrs.get("precursorIntensity", None)
            if attribute is not None:
                self.data[self.currentID]["precursorIntensity"] = max(
                    0.0, float(attribute)
                )

            # get precursor charge
            attribute = attrs.get("precursorCharge", None)
            if attribute is not None:
                self.data[self.currentID]["precursorCharge"] = int(attribute)

    # ----

    def endElement(self, name):
        """Element ended."""

        # remove scan from hierarchy
        if name == "scan":
            del self._scanHierarchy[-1]
            self.currentID = self._scanHierarchy[-1]

        # stop reading peaks data
        elif name == "peaks":
            self._isPeaks = False
            key = "peakPoints" if self._isPeakList else "points"
            self.data[self.currentID][key] = "".join(self.data[self.currentID][key])
            if not self.data[self.currentID][key]:
                self.data[self.currentID][key] = None
            self._isPeakList = False

        # stop reading precursor data
        elif name == "precursorMz":
            self._isPrecursor = False

            # get precursor m/z
            if self.data[self.currentID]["precursorMZ"]:
                self.data[self.currentID]["precursorMZ"] = float(
                    self.data[self.currentID]["precursorMZ"]
                )
            else:
                self.data[self.currentID]["precursorMZ"] = None

    # ----

    def characters(self, content):
        """Grab characters."""

        # get peaks (main spectrum data or the mMass peak-list extension)
        if self._isPeaks:
            key = "peakPoints" if self._isPeakList else "points"
            self.data[self.currentID][key].append(content)

        # get precursor mz
        if self._isPrecursor:
            self.data[self.currentID]["precursorMZ"] += content

    # ----


class stopParsing(Exception):
    """Exeption to stop parsing XML data."""

    pass


def _convertRetentionTime(retention):
    """Convert retention time to seconds."""

    # match retention
    match = RETENTION_TIME_PATTERN.match(retention)
    if not match:
        return None

    # convert to seconds
    seconds = 0
    if match.group(2):
        seconds += float(match.group(2)) * 60
    if match.group(4):
        seconds += float(match.group(4))

    return seconds


# ----
