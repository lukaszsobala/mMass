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
import base64
import hashlib
import re
import zlib
from xml.sax.saxutils import quoteattr

import numpy


# WRITE mzXML DATA
# ----------------


class writeMZXML:
    """Write spectrum data into an mzXML 3.2 document.

    The output is intended to round-trip with mspy.parseMZXML and to be readable
    by common third-party tools. Each document holds a single spectrum, written
    as profile data when available and as centroids (the peaklist) otherwise.
    """

    def __init__(self, scan, info=None, precision=64, compression=True, index=True):
        self.scan = scan
        self.info = info or {}
        self.precision = 64 if int(precision) == 64 else 32
        self.compression = bool(compression)
        self.index = bool(index)

    # ----

    def write(self, path):
        """Format data and save into a file."""

        buff = self.tostring()
        with open(path, "wb") as f:
            f.write(buff.encode("utf-8"))

    # ----

    def tostring(self):
        """Return mzXML document as a string.

        When indexing is enabled a scan byte-offset index, an indexOffset and a
        SHA-1 checksum are appended, so the integrity of the file can be verified.
        """

        prefix = '<?xml version="1.0" encoding="utf-8"?>\n'
        prefix += (
            '<mzXML xmlns="http://sashimi.sourceforge.net/schema_revision/mzXML_3.2"'
            ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
            ' xsi:schemaLocation="http://sashimi.sourceforge.net/schema_revision/mzXML_3.2'
            ' http://sashimi.sourceforge.net/schema_revision/mzXML_3.2/mzXML_idx_3.2.xsd">\n'
        )

        msRun = self._msRunString()

        # plain (non-indexed) mzXML
        if not self.index:
            return prefix + msRun + "</mzXML>\n"

        body = prefix + msRun
        bodyBytes = body.encode("utf-8")

        # byte offset of every <scan> element from the start of the file
        offsets = [
            (m.group(1).decode("utf-8"), m.start())
            for m in re.finditer(rb'<scan num="([^"]*)"', bodyBytes)
        ]

        # scan index (kept at column 0 so its byte offset needs no indent fix-up)
        indexBlock = '<index name="scan">\n'
        for scanID, offset in offsets:
            indexBlock += "  <offset id=%s>%d</offset>\n" % (
                quoteattr(scanID),
                offset,
            )
        indexBlock += "</index>\n"

        # byte offset of the <index> element
        indexOffset = len(bodyBytes)

        # checksum covers everything up to and including the <sha1> open tag
        preChecksum = (
            body
            + indexBlock
            + "<indexOffset>%d</indexOffset>\n" % indexOffset
            + "<sha1>"
        )
        checksum = hashlib.sha1(preChecksum.encode("utf-8")).hexdigest()

        return preChecksum + checksum + "</sha1>\n</mzXML>\n"

    # ----

    def _msRunString(self):
        """Return the msRun element (between the mzXML open and close tags)."""

        # main scan data and the optional peak-list extension
        points, spectrumType = self._mainData()
        peakPoints = self._extraPeakPoints()

        centroided = ' centroided="1"' if spectrumType == "discrete" else ""
        buff = '  <msRun scanCount="1">\n'

        # instrument metadata
        instrument = self.info.get("instrument", "")
        if instrument:
            buff += "    <msInstrument>\n"
            buff += '      <msModel category="msModel" value=%s/>\n' % quoteattr(
                instrument
            )
            buff += "    </msInstrument>\n"

        # data processing
        buff += "    <dataProcessing%s>\n" % centroided
        buff += '      <software type="conversion" name="mMass" version=""/>\n'
        buff += "    </dataProcessing>\n"

        # scan
        buff += self._scan(points, spectrumType, peakPoints)

        buff += "  </msRun>\n"

        return buff

    # ----

    def _scan(self, points, spectrumType, peakPoints=None):
        """Make scan block."""

        scan = self.scan
        scanNumber = scan.scanNumber if scan.scanNumber is not None else 1
        msLevel = scan.msLevel if scan.msLevel is not None else 1

        buff = '    <scan num="%s" msLevel="%d" peaksCount="%d"' % (
            scanNumber,
            msLevel,
            len(points),
        )

        # per-scan centroided flag
        buff += ' centroided="%d"' % (1 if spectrumType == "discrete" else 0)

        # polarity
        if scan.polarity == 1:
            buff += ' polarity="+"'
        elif scan.polarity == -1:
            buff += ' polarity="-"'

        # retention time (ISO 8601 duration, in seconds)
        if scan.retentionTime is not None:
            buff += ' retentionTime="PT%fS"' % float(scan.retentionTime)

        # spectrum statistics
        if len(points):
            buff += ' lowMz="%f" highMz="%f"' % (
                float(points[:, 0].min()),
                float(points[:, 0].max()),
            )
            baseIndex = int(points[:, 1].argmax())
            buff += ' basePeakMz="%f" basePeakIntensity="%f"' % (
                float(points[baseIndex, 0]),
                float(points[baseIndex, 1]),
            )
            buff += ' totIonCurrent="%f"' % float(points[:, 1].sum())

        buff += ">\n"

        # precursor
        if scan.precursorMZ is not None:
            buff += "      <precursorMz"
            if scan.precursorIntensity is not None:
                buff += ' precursorIntensity="%f"' % float(scan.precursorIntensity)
            else:
                buff += ' precursorIntensity="0"'
            if scan.precursorCharge is not None:
                buff += ' precursorCharge="%d"' % int(scan.precursorCharge)
            buff += ">%f</precursorMz>\n" % float(scan.precursorMZ)

        # peaks (main spectrum data)
        buff += self._peaks(points)

        # peak-list extension (peaks stored alongside a profile spectrum); the
        # custom contentType is ignored by third-party tools but read by mMass
        if peakPoints is not None and len(peakPoints):
            buff += self._peaks(peakPoints, contentType="mMass-peaklist")

        buff += "    </scan>\n"

        return buff

    # ----

    def _peaks(self, points, contentType="m/z-int"):
        """Make peaks block with interleaved m/z-intensity pairs."""

        encoded = self._encodePeaks(points)

        buff = "      <peaks"
        if self.compression:
            buff += ' compressionType="zlib"'
            # compressedLen is the byte length of the compressed (pre-base64) data
            buff += ' compressedLen="%d"' % self._compressedLen
        else:
            buff += ' compressionType="none"'
        buff += ' precision="%d" byteOrder="network"' % self.precision
        buff += ' contentType=%s pairOrder="m/z-int">' % quoteattr(contentType)
        buff += "%s</peaks>\n" % encoded

        return buff

    # ----

    def _mainData(self):
        """Return the main scan points and type.

        Profile data is used as the scan when present; otherwise the peak list
        is written as a centroided scan.
        """

        scan = self.scan

        if scan.hasprofile():
            return numpy.asarray(scan.profile, dtype=numpy.float64), "continuous"

        if scan.haspeaks():
            return self._peaklistPoints(), "discrete"

        return numpy.array([]).reshape(0, 2), "continuous"

    # ----

    def _extraPeakPoints(self):
        """Return the peak list to attach to a profile scan, or None.

        Only returned when both profile and peaks exist, so the peaks travel
        with the profile inside a single scan.
        """

        scan = self.scan
        if scan.hasprofile() and scan.haspeaks():
            return self._peaklistPoints()

        return None

    # ----

    def _peaklistPoints(self):
        """Return centroid points from the peak list.

        Peaks carrying an envelope (e.g. from charge-state deconvolution) are
        represented by a single peak compatible with mzML/mzXML: by default the
        monoisotopic (first, lowest-m/z) isotope of the envelope.
        """

        points = []
        for peak in self.scan.peaklist:
            point = self._envelopeMono(peak)
            if point is None:
                point = [peak.mz, peak.intensity]
            points.append(point)

        if not points:
            return numpy.array([]).reshape(0, 2)

        # sort by m/z (centroid lists are expected to be ordered)
        points = numpy.array(points, dtype=numpy.float64)
        return points[points[:, 0].argsort()]

    # ----

    def _envelopeMono(self, peak):
        """Return the monoisotopic [m/z, intensity] of a peak's envelope, if any.

        The monoisotopic peak is the lowest-m/z isotope of the envelope. Its m/z
        is taken from the stored isotopes, but the intensity is the peak's own
        absolute intensity (the stored isotope intensities are relative weights).
        Returns None when the peak carries no usable envelope isotopes.
        """

        envelope = None
        if hasattr(peak, "attributes"):
            envelope = peak.attributes.get("envelope")
        if not isinstance(envelope, dict):
            return None

        monoMz = None
        for isotope in envelope.get("isotopes", []):
            try:
                mz = float(isotope[0])
            except (TypeError, ValueError, IndexError):
                continue
            if monoMz is None or mz < monoMz:
                monoMz = mz

        if monoMz is None:
            return None

        return [monoMz, float(peak.intensity)]

    # ----

    def _encodePeaks(self, points):
        """Encode interleaved pairs as big-endian (network) base64 (optionally zlib)."""

        # interleave as [mz0, int0, mz1, int1, ...] in big-endian order
        dtype = ">f8" if self.precision == 64 else ">f4"
        flat = numpy.asarray(points, dtype=numpy.float64).reshape(-1)
        raw = flat.astype(dtype).tobytes()

        self._compressedLen = len(raw)
        if self.compression:
            raw = zlib.compress(raw)
            self._compressedLen = len(raw)

        return base64.b64encode(raw).decode("ascii")

    # ----
