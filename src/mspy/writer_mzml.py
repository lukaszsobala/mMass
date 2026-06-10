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


# WRITE mzML DATA
# ---------------


class writeMZML:
    """Write spectrum data into an mzML 1.1.0 document.

    The output is intended to round-trip with mspy.parseMZML and to be readable
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
        """Return mzML document as a string.

        When indexing is enabled the mzML element is wrapped in an indexedmzML
        envelope with a spectrum byte-offset index and a SHA-1 file checksum,
        so the integrity of the file can be verified.
        """

        # plain (non-indexed) mzML
        if not self.index:
            return '<?xml version="1.0" encoding="utf-8"?>\n' + self._mzmlString()

        # indexed mzML
        prefix = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<indexedmzML xmlns="http://psi.hupo.org/ms/mzml"'
            ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
            ' xsi:schemaLocation="http://psi.hupo.org/ms/mzml'
            ' http://psidev.info/files/ms/mzML/xsd/mzML1.1.2_idx.xsd">\n'
        )
        mzml = self._mzmlString()

        body = prefix + mzml
        bodyBytes = body.encode("utf-8")

        # byte offset of every <spectrum> element from the start of the file
        offsets = [
            (m.group(1).decode("utf-8"), m.start())
            for m in re.finditer(rb'<spectrum index="\d+" id="([^"]*)"', bodyBytes)
        ]

        # index list (kept at column 0 so its byte offset needs no indent fix-up)
        indexBlock = '<indexList count="1">\n'
        indexBlock += '  <index name="spectrum">\n'
        for idRef, offset in offsets:
            indexBlock += "    <offset idRef=%s>%d</offset>\n" % (
                quoteattr(idRef),
                offset,
            )
        indexBlock += "  </index>\n"
        indexBlock += "</indexList>\n"

        # byte offset of the <indexList> element
        indexListOffset = len(bodyBytes)

        # checksum covers everything up to and including the <fileChecksum> open tag
        preChecksum = (
            body
            + indexBlock
            + "<indexListOffset>%d</indexListOffset>\n" % indexListOffset
            + "<fileChecksum>"
        )
        checksum = hashlib.sha1(preChecksum.encode("utf-8")).hexdigest()

        return preChecksum + checksum + "</fileChecksum>\n</indexedmzML>\n"

    # ----

    def _mzmlString(self):
        """Return the mzML element (without the XML declaration)."""

        # main spectrum data and the optional peak-list extension
        points, spectrumType = self._mainData()
        peakPoints = self._extraPeakPoints()

        buff = (
            '<mzML xmlns="http://psi.hupo.org/ms/mzml"'
            ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
            ' xsi:schemaLocation="http://psi.hupo.org/ms/mzml'
            ' http://psidev.info/files/ms/mzML/xsd/mzML1.1.0.xsd"'
            ' version="1.1.0">\n'
        )

        # controlled vocabularies
        buff += '  <cvList count="2">\n'
        buff += (
            '    <cv id="MS" fullName="Proteomics Standards Initiative Mass'
            ' Spectrometry Ontology" version="4.1.0"'
            ' URI="https://raw.githubusercontent.com/HUPO-PSI/psi-ms-CV/master/psi-ms.obo"/>\n'
        )
        buff += (
            '    <cv id="UO" fullName="Unit Ontology" version="releases/2020-03-10"'
            ' URI="http://ontologies.berkeleybop.org/uo.obo"/>\n'
        )
        buff += "  </cvList>\n"

        # file description
        buff += self._fileDescription()

        # software
        buff += '  <softwareList count="1">\n'
        buff += '    <software id="mMass" version="">\n'
        buff += '      <cvParam cvRef="MS" accession="MS:1000799" name="custom unreleased software tool" value="mMass"/>\n'
        buff += "    </software>\n"
        buff += "  </softwareList>\n"

        # instrument configuration
        buff += '  <instrumentConfigurationList count="1">\n'
        buff += '    <instrumentConfiguration id="IC1">\n'
        instrument = self.info.get("instrument", "")
        if instrument:
            buff += (
                '      <cvParam cvRef="MS" accession="MS:1000169" name=%s value=""/>\n'
                % quoteattr(instrument)
            )
        buff += "    </instrumentConfiguration>\n"
        buff += "  </instrumentConfigurationList>\n"

        # data processing
        buff += '  <dataProcessingList count="1">\n'
        buff += '    <dataProcessing id="mMass_processing">\n'
        buff += '      <processingMethod order="0" softwareRef="mMass">\n'
        buff += '        <cvParam cvRef="MS" accession="MS:1000544" name="Conversion to mzML" value=""/>\n'
        buff += "      </processingMethod>\n"
        buff += "    </dataProcessing>\n"
        buff += "  </dataProcessingList>\n"

        # run
        runID = self.info.get("title", "") or "run1"
        buff += (
            '  <run id=%s defaultInstrumentConfigurationRef="IC1">\n'
            % quoteattr(self._makeID(runID))
        )
        buff += '    <spectrumList count="1" defaultDataProcessingRef="mMass_processing">\n'
        buff += self._spectrum(points, spectrumType, peakPoints)
        buff += "    </spectrumList>\n"
        buff += "  </run>\n"

        buff += "</mzML>\n"

        return buff

    # ----

    def _fileDescription(self):
        """Make fileDescription block with document metadata."""

        buff = "  <fileDescription>\n"
        buff += "    <fileContent>\n"
        buff += '      <cvParam cvRef="MS" accession="MS:1000294" name="mass spectrum" value=""/>\n'

        # store document title (read back by mspy.parseMZML)
        title = self.info.get("title", "")
        if title:
            buff += (
                '      <cvParam cvRef="MS" accession="MS:1000580" name=%s value=""/>\n'
                % quoteattr(title)
            )
        buff += "    </fileContent>\n"

        # contact information
        operator = self.info.get("operator", "")
        contact = self.info.get("contact", "")
        institution = self.info.get("institution", "")
        if operator or contact or institution:
            buff += "    <contact>\n"
            if operator:
                buff += (
                    '      <cvParam cvRef="MS" accession="MS:1000586" name="contact name" value=%s/>\n'
                    % quoteattr(operator)
                )
            if institution:
                buff += (
                    '      <cvParam cvRef="MS" accession="MS:1000590" name="contact affiliation" value=%s/>\n'
                    % quoteattr(institution)
                )
            if contact:
                buff += (
                    '      <cvParam cvRef="MS" accession="MS:1000589" name="contact email" value=%s/>\n'
                    % quoteattr(contact)
                )
            buff += "    </contact>\n"

        buff += "  </fileDescription>\n"

        return buff

    # ----

    def _spectrum(self, points, spectrumType, peakPoints=None):
        """Make spectrum block."""

        scan = self.scan
        scanNumber = scan.scanNumber if scan.scanNumber is not None else 1

        buff = (
            '      <spectrum index="0" id=%s defaultArrayLength="%d">\n'
            % (quoteattr("scan=%s" % scanNumber), len(points))
        )

        # spectrum type
        if spectrumType == "discrete":
            buff += '        <cvParam cvRef="MS" accession="MS:1000127" name="centroid spectrum" value=""/>\n'
        else:
            buff += '        <cvParam cvRef="MS" accession="MS:1000128" name="profile spectrum" value=""/>\n'

        # ms level
        msLevel = scan.msLevel if scan.msLevel is not None else 1
        buff += (
            '        <cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="%d"/>\n'
            % msLevel
        )

        # polarity
        if scan.polarity == 1:
            buff += '        <cvParam cvRef="MS" accession="MS:1000130" name="positive scan" value=""/>\n'
        elif scan.polarity == -1:
            buff += '        <cvParam cvRef="MS" accession="MS:1000129" name="negative scan" value=""/>\n'

        # spectrum statistics
        if len(points):
            buff += (
                '        <cvParam cvRef="MS" accession="MS:1000528" name="lowest observed m/z" value="%f"'
                ' unitCvRef="MS" unitAccession="MS:1000040" unitName="m/z"/>\n'
                % float(points[:, 0].min())
            )
            buff += (
                '        <cvParam cvRef="MS" accession="MS:1000527" name="highest observed m/z" value="%f"'
                ' unitCvRef="MS" unitAccession="MS:1000040" unitName="m/z"/>\n'
                % float(points[:, 0].max())
            )
            baseIndex = int(points[:, 1].argmax())
            buff += (
                '        <cvParam cvRef="MS" accession="MS:1000504" name="base peak m/z" value="%f"'
                ' unitCvRef="MS" unitAccession="MS:1000040" unitName="m/z"/>\n'
                % float(points[baseIndex, 0])
            )
            buff += (
                '        <cvParam cvRef="MS" accession="MS:1000505" name="base peak intensity" value="%f"'
                ' unitCvRef="MS" unitAccession="MS:1000131" unitName="number of detector counts"/>\n'
                % float(points[baseIndex, 1])
            )
            buff += (
                '        <cvParam cvRef="MS" accession="MS:1000285" name="total ion current" value="%f"/>\n'
                % float(points[:, 1].sum())
            )

        # scan (retention time)
        buff += '        <scanList count="1">\n'
        buff += '          <cvParam cvRef="MS" accession="MS:1000795" name="no combination" value=""/>\n'
        buff += "          <scan>\n"
        if scan.retentionTime is not None:
            buff += (
                '            <cvParam cvRef="MS" accession="MS:1000016" name="scan start time" value="%f"'
                ' unitCvRef="UO" unitAccession="UO:0000010" unitName="second"/>\n'
                % float(scan.retentionTime)
            )
        buff += "          </scan>\n"
        buff += "        </scanList>\n"

        # precursor
        if scan.precursorMZ is not None:
            buff += self._precursor()

        # binary data
        buff += self._binaryDataArrayList(points, peakPoints)

        buff += "      </spectrum>\n"

        return buff

    # ----

    def _precursor(self):
        """Make precursor block."""

        scan = self.scan

        buff = '        <precursorList count="1">\n'
        if scan.parentScanNumber is not None:
            buff += (
                "          <precursor spectrumRef=%s>\n"
                % quoteattr("scan=%s" % scan.parentScanNumber)
            )
        else:
            buff += "          <precursor>\n"
        buff += '            <selectedIonList count="1">\n'
        buff += "              <selectedIon>\n"
        buff += (
            '                <cvParam cvRef="MS" accession="MS:1000744" name="selected ion m/z" value="%f"'
            ' unitCvRef="MS" unitAccession="MS:1000040" unitName="m/z"/>\n'
            % float(scan.precursorMZ)
        )
        if scan.precursorCharge is not None:
            buff += (
                '                <cvParam cvRef="MS" accession="MS:1000041" name="charge state" value="%d"/>\n'
                % int(scan.precursorCharge)
            )
        if scan.precursorIntensity is not None:
            buff += (
                '                <cvParam cvRef="MS" accession="MS:1000042" name="intensity" value="%f"/>\n'
                % float(scan.precursorIntensity)
            )
        buff += "              </selectedIon>\n"
        buff += "            </selectedIonList>\n"
        buff += "          </precursor>\n"
        buff += "        </precursorList>\n"

        return buff

    # ----

    def _binaryDataArrayList(self, points, peakPoints=None):
        """Make binaryDataArrayList block.

        The main m/z and intensity arrays hold the spectrum data. When a peak
        list is attached to a profile spectrum it is stored as two additional
        (non-standard) arrays so the peaks travel with the profile in a single
        spectrum; third-party tools simply ignore the extra arrays.
        """

        hasPeaks = peakPoints is not None and len(peakPoints)
        count = 4 if hasPeaks else 2

        buff = '        <binaryDataArrayList count="%d">\n' % count
        buff += self._binaryDataArray(points[:, 0] if len(points) else [], "mz")
        buff += self._binaryDataArray(points[:, 1] if len(points) else [], "int")
        if hasPeaks:
            buff += self._binaryDataArray(peakPoints[:, 0], "peakmz", len(peakPoints))
            buff += self._binaryDataArray(peakPoints[:, 1], "peakint", len(peakPoints))
        buff += "        </binaryDataArrayList>\n"

        return buff

    # ----

    def _binaryDataArray(self, values, arrayType, arrayLength=None):
        """Make single binaryDataArray block."""

        encoded = self._encodeArray(values) if len(values) else ""

        if arrayLength is not None:
            buff = '          <binaryDataArray arrayLength="%d" encodedLength="%d">\n' % (
                arrayLength,
                len(encoded),
            )
        else:
            buff = '          <binaryDataArray encodedLength="%d">\n' % len(encoded)

        # precision
        if self.precision == 64:
            buff += '            <cvParam cvRef="MS" accession="MS:1000523" name="64-bit float" value=""/>\n'
        else:
            buff += '            <cvParam cvRef="MS" accession="MS:1000521" name="32-bit float" value=""/>\n'

        # compression
        if self.compression:
            buff += '            <cvParam cvRef="MS" accession="MS:1000574" name="zlib compression" value=""/>\n'
        else:
            buff += '            <cvParam cvRef="MS" accession="MS:1000576" name="no compression" value=""/>\n'

        # array type
        if arrayType == "mz":
            buff += (
                '            <cvParam cvRef="MS" accession="MS:1000514" name="m/z array" value=""'
                ' unitCvRef="MS" unitAccession="MS:1000040" unitName="m/z"/>\n'
            )
        elif arrayType == "int":
            buff += (
                '            <cvParam cvRef="MS" accession="MS:1000515" name="intensity array" value=""'
                ' unitCvRef="MS" unitAccession="MS:1000131" unitName="number of detector counts"/>\n'
            )
        elif arrayType == "peakmz":
            buff += (
                '            <cvParam cvRef="MS" accession="MS:1000786" name="non-standard data array"'
                ' value="mMass peak m/z array"'
                ' unitCvRef="MS" unitAccession="MS:1000040" unitName="m/z"/>\n'
            )
        else:
            buff += (
                '            <cvParam cvRef="MS" accession="MS:1000786" name="non-standard data array"'
                ' value="mMass peak intensity array"'
                ' unitCvRef="MS" unitAccession="MS:1000131" unitName="number of detector counts"/>\n'
            )

        buff += "            <binary>%s</binary>\n" % encoded
        buff += "          </binaryDataArray>\n"

        return buff

    # ----

    def _mainData(self):
        """Return the main spectrum points and type.

        Profile data is used as the spectrum when present; otherwise the peak
        list is written as a centroid spectrum.
        """

        scan = self.scan

        if scan.hasprofile():
            return numpy.asarray(scan.profile, dtype=numpy.float64), "continuous"

        if scan.haspeaks():
            return self._peaklistPoints(), "discrete"

        return numpy.array([]).reshape(0, 2), "continuous"

    # ----

    def _extraPeakPoints(self):
        """Return the peak list to attach to a profile spectrum, or None.

        Only returned when both profile and peaks exist, so the peaks travel
        with the profile inside a single spectrum.
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

    def _encodeArray(self, values):
        """Encode a numeric array as little-endian base64 (optionally zlib)."""

        dtype = "<f8" if self.precision == 64 else "<f4"
        raw = numpy.asarray(values, dtype=dtype).tobytes()
        if self.compression:
            raw = zlib.compress(raw)

        return base64.b64encode(raw).decode("ascii")

    # ----

    def _makeID(self, value):
        """Make a safe run id from a free-text value."""

        cleaned = "".join(c if (c.isalnum() or c in "._-") else "_" for c in value)
        return cleaned or "run1"

    # ----
