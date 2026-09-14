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
import sys
import struct
import base64
import zlib
import copy
import xml.dom.minidom
import os.path
import re
import time
import numpy
import wx
from typing import Any

# load modules
from . import config
from . import session
import mspy

# DOCUMENT STRUCTURE
# ------------------

# scan metadata stored for every scan of an LC-MS run in .msd files, with the
# type each value is read back as
MSD_SCAN_ATTRIBUTES = {
    "scanNumber": int,
    "parentScanNumber": int,
    "msLevel": int,
    "polarity": int,
    "retentionTime": float,
    "lowMZ": float,
    "highMZ": float,
    "basePeakMZ": float,
    "basePeakIntensity": float,
    "totIonCurrent": float,
    "precursorMZ": float,
    "precursorIntensity": float,
    "precursorCharge": int,
    "pointsCount": int,
    "spectrumType": str,
    "filterString": str,
    "instrumentConfigurationRef": str,
    "title": str,
}


def makeChromatograms(scanlist):
    """Build TIC/BPC traces (MS1 only, retention time in minutes) from a scan index.

    Returns {"traces": [{"label", "tic", "bpc"}, ...]}, one trace per way the MS1
    scans were acquired (see mspy.acquisitionkey). A run that interleaves two
    kinds of full scan -- an Orbitrap and an ion trap one, say -- would otherwise
    alternate between their very different ion currents in a single trace, which
    draws as a zigzag. The label names the acquisition ("FTMS", "ITMS", ...) and
    is empty when the run has only one.
    """

    groups = {}
    for _scanID, meta in scanlist.items():
        if meta.get("msLevel") not in (None, 1):
            continue
        rt = meta.get("retentionTime")
        if rt is None:
            continue
        key = mspy.acquisitionkey(meta)
        if key not in groups:
            groups[key] = {"tic": [], "bpc": [], "filterString": meta.get("filterString")}
        group = groups[key]
        if meta.get("totIonCurrent") is not None:
            group["tic"].append((rt / 60.0, meta["totIonCurrent"]))
        if meta.get("basePeakIntensity") is not None:
            group["bpc"].append((rt / 60.0, meta["basePeakIntensity"]))

    labels = _acquisitionLabels(list(groups))

    traces = []
    for key, group in groups.items():
        traces.append(
            {
                "label": labels[key] if len(groups) > 1 else "",
                "tic": sorted(group["tic"]),
                "bpc": sorted(group["bpc"]),
            }
        )

    return {"traces": traces}


def _acquisitionLabels(keys):
    """Short names telling acquisition keys apart in a chromatogram legend.

    The analyser token of the filter string ("FTMS + p ESI Full ms [...]" ->
    "FTMS") when that alone tells the keys apart, then the whole filter string
    (or instrument configuration), then that with the polarity added.
    """

    def _polarity(key):
        return {1: "+", -1: "-"}.get(key[1], "")

    candidates = (
        lambda key: key[2].split(" ")[0],
        lambda key: key[2],
        lambda key: ("%s %s" % (key[2], _polarity(key))).strip(),
    )
    labels = {}
    for name in candidates:
        labels = {key: name(key) for key in keys}
        if len(set(labels.values())) == len(keys):
            break
    return labels


class document:
    """Document object definition."""

    def __init__(self):

        self.format: str = "mSD"
        self.title: str = ""
        self.path: str = ""

        self.date: str = ""
        self.operator: str = ""
        self.contact: str = ""
        self.institution: str = ""
        self.instrument: str = ""
        self.notes: str = ""

        self.spectrum: Any = mspy.scan()
        self.annotations = []
        self.sequences = []

        # LC-MS / chromatogram support
        # When a multi-scan file is opened as a single browsable run, the
        # document keeps the whole scan index plus a cache of already-loaded
        # scans so navigating the chromatogram restores each scan (and any
        # peaks picked on it). 'spectrum' always mirrors the current scan.
        self.scanlist: Any = None  # {scanNumber: metadata dict} or None
        self.scanCache: dict[Any, Any] = {}  # {scanNumber: mspy.scan}
        self.currentScanID: Any = None  # scanNumber currently shown
        # {"traces": [{"label": str, "tic": [(rt, ai)..], "bpc": [..]}, ..]}
        self.chromatograms: dict[str, list] = {}
        # (path, format) of the raw file scans not yet in scanCache are read
        # from; None once every scan is held in the document (e.g. a run
        # reopened from .msd)
        self.scanSource: Any = None

        self.colour = (0, 0, 255)
        self.style = wx.SOLID  # type: ignore[attr-defined]
        self.dirty = False
        self.visible = True
        self.flipped = False
        self.offset = [0, 0]

        # undo buffers
        self.undo = None
        self.redo = None
        self._spectrumBuff: Any = None
        self._annotationsBuff: Any = None
        self._sequencesBuff: Any = None
        self._infoBuff: dict[str, Any] | None = None

        # redo buffers
        self._redoSpectrumBuff: Any = None
        self._redoAnnotationsBuff: Any = None
        self._redoSequencesBuff: Any = None
        self._redoInfoBuff: dict[str, Any] | None = None

    # ----

    def islcms(self):
        """Return True if this document is a browsable multi-scan LC-MS run."""
        return bool(self.scanlist) and len(self.scanlist) > 1

    # ----

    def backup(self, items=None):
        """Backup current state for undo."""

        self.undo = items
        self.redo = None

        # delete old
        self._spectrumBuff = None
        self._annotationsBuff = None
        self._sequencesBuff = None
        self._infoBuff = None
        self._redoSpectrumBuff = None
        self._redoAnnotationsBuff = None
        self._redoSequencesBuff = None
        self._redoInfoBuff = None

        if not items:
            return

        # store data
        if "spectrum" in items:
            self._spectrumBuff = copy.deepcopy(self.spectrum)
        if "annotations" in items:
            self._annotationsBuff = copy.deepcopy(self.annotations)
        if "sequences" in items:
            self._sequencesBuff = copy.deepcopy(self.sequences)
        if "notations" in items:
            self._annotationsBuff = copy.deepcopy(self.annotations)
            self._sequencesBuff = copy.deepcopy(self.sequences)
        if "doctitle" in items:
            self._infoBuff = {"title": self.title}
        if "info" in items:
            self._infoBuff = {
                "title": self.title,
                "date": self.date,
                "operator": self.operator,
                "contact": self.contact,
                "institution": self.institution,
                "instrument": self.instrument,
                "notes": self.notes,
                "scanNumber": self.spectrum.scanNumber,
                "retentionTime": self.spectrum.retentionTime,
                "msLevel": self.spectrum.msLevel,
                "precursorMZ": self.spectrum.precursorMZ,
                "precursorCharge": self.spectrum.precursorCharge,
                "polarity": self.spectrum.polarity,
            }

    # ----

    def restore(self):
        """Revert to last stored state."""

        # check undo
        if not self.undo:
            return False

        # backup current state for redo
        items = self.undo
        self.redo = items
        self._redoSpectrumBuff = None
        self._redoAnnotationsBuff = None
        self._redoSequencesBuff = None
        self._redoInfoBuff = None
        if "spectrum" in items:
            self._redoSpectrumBuff = copy.deepcopy(self.spectrum)
        if "annotations" in items:
            self._redoAnnotationsBuff = copy.deepcopy(self.annotations)
        if "sequences" in items:
            self._redoSequencesBuff = copy.deepcopy(self.sequences)
        if "notations" in items:
            self._redoAnnotationsBuff = copy.deepcopy(self.annotations)
            self._redoSequencesBuff = copy.deepcopy(self.sequences)
        if "doctitle" in items:
            self._redoInfoBuff = {"title": self.title}
        if "info" in items:
            self._redoInfoBuff = {
                "title": self.title,
                "date": self.date,
                "operator": self.operator,
                "contact": self.contact,
                "institution": self.institution,
                "instrument": self.instrument,
                "notes": self.notes,
                "scanNumber": self.spectrum.scanNumber,
                "retentionTime": self.spectrum.retentionTime,
                "msLevel": self.spectrum.msLevel,
                "precursorMZ": self.spectrum.precursorMZ,
                "precursorCharge": self.spectrum.precursorCharge,
                "polarity": self.spectrum.polarity,
            }

        # revert data
        if "spectrum" in items:
            if self._spectrumBuff is not None:
                self.spectrum = self._spectrumBuff
        if "annotations" in items:
            if self._annotationsBuff is not None:
                self.annotations[:] = self._annotationsBuff[:]
        if "sequences" in items:
            if self._sequencesBuff is not None:
                self.sequences[:] = self._sequencesBuff[:]
        if "notations" in items:
            if self._annotationsBuff is not None and self._sequencesBuff is not None:
                self.annotations[:] = self._annotationsBuff[:]
                for x in range(len(self.sequences)):
                    self.sequences[x].matches[:] = self._sequencesBuff[x].matches[:]
        if "doctitle" in items:
            if self._infoBuff is not None:
                self.title = self._infoBuff["title"]
        if "info" in items:
            if self._infoBuff is not None:
                info = self._infoBuff
                self.title = info["title"]
                self.date = info["date"]
                self.operator = info["operator"]
                self.contact = info["contact"]
                self.institution = info["institution"]
                self.instrument = info["instrument"]
                self.notes = info["notes"]
                self.spectrum.scanNumber = info["scanNumber"]
                self.spectrum.retentionTime = info["retentionTime"]
                self.spectrum.msLevel = info["msLevel"]
                self.spectrum.precursorMZ = info["precursorMZ"]
                self.spectrum.precursorCharge = info["precursorCharge"]
                self.spectrum.polarity = info["polarity"]

        # clear buffers
        self.undo = None
        self._spectrumBuff = None
        self._annotationsBuff = None
        self._sequencesBuff = None
        self._infoBuff = None

        return items

    # ----

    def forward(self):
        """Re-apply last undone state."""

        # check redo
        if not self.redo:
            return False

        # backup current state for undo
        items = self.redo
        self.undo = items
        self._spectrumBuff = None
        self._annotationsBuff = None
        self._sequencesBuff = None
        self._infoBuff = None
        if "spectrum" in items:
            self._spectrumBuff = copy.deepcopy(self.spectrum)
        if "annotations" in items:
            self._annotationsBuff = copy.deepcopy(self.annotations)
        if "sequences" in items:
            self._sequencesBuff = copy.deepcopy(self.sequences)
        if "notations" in items:
            self._annotationsBuff = copy.deepcopy(self.annotations)
            self._sequencesBuff = copy.deepcopy(self.sequences)
        if "doctitle" in items:
            self._infoBuff = {"title": self.title}
        if "info" in items:
            self._infoBuff = {
                "title": self.title,
                "date": self.date,
                "operator": self.operator,
                "contact": self.contact,
                "institution": self.institution,
                "instrument": self.instrument,
                "notes": self.notes,
                "scanNumber": self.spectrum.scanNumber,
                "retentionTime": self.spectrum.retentionTime,
                "msLevel": self.spectrum.msLevel,
                "precursorMZ": self.spectrum.precursorMZ,
                "precursorCharge": self.spectrum.precursorCharge,
                "polarity": self.spectrum.polarity,
            }

        # restore redone data
        if "spectrum" in items:
            if self._redoSpectrumBuff is not None:
                self.spectrum = self._redoSpectrumBuff
        if "annotations" in items:
            if self._redoAnnotationsBuff is not None:
                self.annotations[:] = self._redoAnnotationsBuff[:]
        if "sequences" in items:
            if self._redoSequencesBuff is not None:
                self.sequences[:] = self._redoSequencesBuff[:]
        if "notations" in items:
            if self._redoAnnotationsBuff is not None and self._redoSequencesBuff is not None:
                self.annotations[:] = self._redoAnnotationsBuff[:]
                for x in range(len(self.sequences)):
                    self.sequences[x].matches[:] = self._redoSequencesBuff[x].matches[:]
        if "doctitle" in items:
            if self._redoInfoBuff is not None:
                self.title = self._redoInfoBuff["title"]
        if "info" in items:
            if self._redoInfoBuff is not None:
                info = self._redoInfoBuff
                self.title = info["title"]
                self.date = info["date"]
                self.operator = info["operator"]
                self.contact = info["contact"]
                self.institution = info["institution"]
                self.instrument = info["instrument"]
                self.notes = info["notes"]
                self.spectrum.scanNumber = info["scanNumber"]
                self.spectrum.retentionTime = info["retentionTime"]
                self.spectrum.msLevel = info["msLevel"]
                self.spectrum.precursorMZ = info["precursorMZ"]
                self.spectrum.precursorCharge = info["precursorCharge"]
                self.spectrum.polarity = info["polarity"]

        # clear redo buffers
        self.redo = None
        self._redoSpectrumBuff = None
        self._redoAnnotationsBuff = None
        self._redoSequencesBuff = None
        self._redoInfoBuff = None

        return items

    # ----

    def sortAnnotations(self):
        """Sort annotations by m/z."""

        buff = []
        for item in self.annotations:
            buff.append((item.mz, item))
        buff.sort(key=lambda x: x[0])

        # remove formula duplicates
        # formulas = []
        # del self.annotations[:]
        # for item in buff:
        #    if not item[1].formula in formulas:
        #        self.annotations.append(item[1])
        #        formulas.append(item[1].formula)

        del self.annotations[:]
        for item in buff:
            self.annotations.append(item[1])

    # ----

    def sortSequences(self):
        """Sort sequences by titles."""

        # get sequences
        sequences = []
        for sequence in self.sequences:
            sequences.append((sequence.title, sequence))
        sequences.sort(key=lambda x: x[0])

        # update document
        del self.sequences[:]
        for _title, sequence in sequences:
            self.sequences.append(sequence)

    # ----

    def sortSequenceMatches(self):
        """Sort sequence matches by m/z."""

        for sequence in self.sequences:

            buff = []
            for item in sequence.matches:
                buff.append((item.mz, item))
            buff.sort(key=lambda x: x[0])

            del sequence.matches[:]
            for item in buff:
                sequence.matches.append(item[1])

    # ----

    def msd(self):
        """Make mSD XML."""

        buff = '<?xml version="1.0" encoding="utf-8" ?>\n'
        buff += '<mSD version="2.2">\n\n'

        # format description
        buff += "  <description>\n"
        buff += "    <title>%s</title>\n" % self._escape(self.title)
        buff += '    <date value="%s" />\n' % self._escape(self.date)
        buff += '    <operator value="%s" />\n' % self._escape(self.operator)
        buff += '    <contact value="%s" />\n' % self._escape(self.contact)
        buff += '    <institution value="%s" />\n' % self._escape(self.institution)
        buff += '    <instrument value="%s" />\n' % self._escape(self.instrument)
        buff += "    <notes>%s</notes>\n" % self._escape(self.notes)
        buff += "  </description>\n\n"

        # format spectrum
        precision = config.main["dataPrecision"]
        endian = sys.byteorder
        points = self.spectrum.profile
        mzArray, intArray = self._convertSpectrum(points, precision)
        attributes = 'points="%s"' % len(points)
        if self.spectrum.scanNumber is not None:
            attributes += ' scanNumber="%s"' % self.spectrum.scanNumber
        if self.spectrum.msLevel is not None:
            attributes += ' msLevel="%s"' % self.spectrum.msLevel
        if self.spectrum.retentionTime is not None:
            attributes += ' retentionTime="%s"' % self.spectrum.retentionTime
        if self.spectrum.precursorMZ is not None:
            attributes += ' precursorMZ="%s"' % self.spectrum.precursorMZ
        if self.spectrum.precursorCharge is not None:
            attributes += ' precursorCharge="%s"' % self.spectrum.precursorCharge
        if self.spectrum.polarity is not None:
            attributes += ' polarity="%s"' % self.spectrum.polarity

        buff += "  <spectrum %s>\n" % attributes
        if len(points) > 0:
            buff += (
                '    <mzArray precision="%s" compression="zlib" endian="%s">%s</mzArray>\n'
                % (precision, endian, mzArray.decode("utf-8"))
            )
            buff += (
                '    <intArray precision="%s" compression="zlib" endian="%s">%s</intArray>\n'
                % (precision, endian, intArray.decode("utf-8"))
            )
        buff += "  </spectrum>\n\n"

        # format peaklist
        if len(self.spectrum.peaklist):
            buff += "  <peaklist>\n"
            buff += self._formatPeaks(self.spectrum.peaklist, "    ")
            buff += "  </peaklist>\n\n"

        # format annotations
        if len(self.annotations):
            buff += "  <annotations>\n"
            for annot in self.annotations:
                attributes = (
                    'peakMZ="%.6f" peakIntensity="%.6f" peakBaseline="%.6f"'
                    % (annot.mz, annot.ai, annot.base)
                )
                if annot.charge is not None:
                    attributes += ' charge="%d"' % annot.charge
                if annot.radical:
                    attributes += ' radical="1"'
                if annot.theoretical is not None:
                    attributes += ' calcMZ="%.6f"' % annot.theoretical
                if annot.formula is not None:
                    attributes += ' formula="%s"' % annot.formula
                buff += "    <annotation %s>%s</annotation>\n" % (
                    attributes,
                    self._escape(annot.label),
                )
            buff += "  </annotations>\n\n"

        # format sequences
        if len(self.sequences):
            buff += "  <sequences>\n\n"
            for index, sequence in enumerate(self.sequences):
                buff += '    <sequence index="%s">\n' % index
                buff += "      <title>%s</title>\n" % self._escape(sequence.title)
                buff += "      <accession>%s</accession>\n" % self._escape(
                    sequence.accession
                )

                attributes = 'type="%s"' % sequence.chainType
                if sequence.cyclic:
                    attributes += ' cyclic="1"'
                buff += "      <seq %s>%s</seq>\n" % (attributes, sequence.format("S"))

                # save monomers for custom sequences
                if sequence.chainType != "aminoacids":
                    buff += "      <monomers>\n"
                    savedMonomers = []
                    for abbr in sequence.chain:
                        if abbr not in savedMonomers:
                            savedMonomers.append(abbr)
                            formula = mspy.monomers[abbr].formula
                            buff += '        <monomer abbr="%s" formula="%s" />\n' % (
                                abbr,
                                formula,
                            )
                    buff += "      </monomers>\n"

                # format modifications
                if len(sequence.modifications):
                    buff += "      <modifications>\n"
                    for mod in sequence.modifications:
                        gainFormula = mspy.modifications[mod[0]].gainFormula
                        lossFormula = mspy.modifications[mod[0]].lossFormula
                        modtype = "fixed"
                        if mod[2] == "v":
                            modtype = "variable"
                        buff += (
                            '        <modification name="%s" position="%s" type="%s" gainFormula="%s" lossFormula="%s" />\n'
                            % (mod[0], mod[1], modtype, gainFormula, lossFormula)
                        )
                    buff += "      </modifications>\n"

                # format matches
                if len(sequence.matches):
                    buff += "      <matches>\n"
                    for match in sequence.matches:
                        attributes = (
                            'peakMZ="%.6f" peakIntensity="%.6f" peakBaseline="%.6f"'
                            % (match.mz, match.ai, match.base)
                        )
                        if match.charge is not None:
                            attributes += ' charge="%d"' % match.charge
                        if match.radical:
                            attributes += ' radical="1"'
                        if match.theoretical is not None:
                            attributes += ' calcMZ="%.6f"' % match.theoretical
                        if match.formula is not None:
                            attributes += ' formula="%s"' % match.formula
                        if match.sequenceRange is not None:
                            attributes += ' sequenceRange="%d-%d"' % tuple(
                                match.sequenceRange
                            )
                        if match.fragmentSerie is not None:
                            attributes += ' fragmentSerie="%s"' % match.fragmentSerie
                        if match.fragmentIndex is not None:
                            attributes += ' fragmentIndex="%s"' % match.fragmentIndex
                        buff += "        <match %s>%s</match>\n" % (
                            attributes,
                            self._escape(match.label),
                        )
                    buff += "      </matches>\n"

                buff += "    </sequence>\n\n"
            buff += "  </sequences>\n\n"

        # format chromatogram (all scans of an LC-MS run)
        if self.islcms():
            buff += self._formatChromatogram()

        buff += "</mSD>\n"

        return buff

    # ----

    def _formatPeaks(self, peaklist, indent):
        """Format peaks (with their envelopes) as mSD <peak> elements."""

        buff = ""
        for peak in peaklist:
            attributes = 'mz="%.6f" intensity="%.6f" baseline="%.6f"' % (
                peak.mz,
                peak.ai,
                peak.base,
            )
            if peak.sn is not None:
                attributes += ' sn="%.3f"' % peak.sn
            if peak.charge is not None:
                attributes += ' charge="%d"' % peak.charge
            if peak.isotope is not None:
                attributes += ' isotope="%d"' % peak.isotope
            if peak.fwhm is not None:
                attributes += ' fwhm="%.6f"' % peak.fwhm
            if peak.group:
                attributes += ' group="%s"' % self._escape(peak.group)
            if hasattr(peak, "attributes") and peak.attributes.get("_fwhmLocked"):
                attributes += ' fwhmLocked="1"'
            # the finer acquisition's m/z a guided peak was matched to
            if hasattr(peak, "attributes") and peak.attributes.get("referenceMz") is not None:
                attributes += ' referenceMz="%.6f"' % float(peak.attributes["referenceMz"])
            envelope = None
            if hasattr(peak, "attributes"):
                envelope = peak.attributes.get("envelope")

            if envelope and isinstance(envelope, dict):
                buff += "%s<peak %s>\n" % (indent, attributes)

                envAttributes = []
                area = envelope.get("area")
                if area is not None:
                    envAttributes.append('area="%.12g"' % float(area))
                sumint = envelope.get("sumint")
                if sumint is not None:
                    envAttributes.append('sumint="%.12g"' % float(sumint))
                fwhm = envelope.get("fwhm")
                if fwhm is not None:
                    envAttributes.append('fwhm="%.12g"' % float(fwhm))
                shape = envelope.get("shape")
                if shape is not None:
                    envAttributes.append('shape="%s"' % self._escape(str(shape)))
                # how many leading isotopes were real DETECTED peaks. The
                # isotope peaks themselves are consumed by the conversion, so
                # without this a reload can only fall back on the theoretical
                # extent -- which either drops a genuinely measured isotope or
                # keeps an over-long tail (see mod_peakpicking, "detected").
                detected = envelope.get("detected")
                if detected is not None:
                    envAttributes.append('detected="%d"' % int(detected))
                averagine = envelope.get("averagineType")
                if averagine is not None:
                    envAttributes.append(
                        'averagine="%s"' % self._escape(str(averagine))
                    )

                if envAttributes:
                    buff += "%s  <envelope %s>\n" % (indent, " ".join(envAttributes))
                else:
                    buff += "%s  <envelope>\n" % indent

                for isotope in envelope.get("isotopes", []):
                    try:
                        isoMZ = float(isotope[0])
                        isoIntensity = float(isotope[1])
                    except (TypeError, ValueError, IndexError):
                        continue
                    buff += '%s    <isotope mz="%.12g" intensity="%.12g" />\n' % (
                        indent,
                        isoMZ,
                        isoIntensity,
                    )

                buff += "%s  </envelope>\n" % indent
                buff += "%s</peak>\n" % indent
            else:
                buff += "%s<peak %s />\n" % (indent, attributes)

        return buff

    # ----

    def _formatChromatogram(self):
        """Format every scan of an LC-MS run as the mSD <chromatogram> element.

        Older readers look each mSD section up by tag name anywhere in the file,
        so nothing in here reuses <spectrum>, <peaklist>, <annotations> or
        <sequences>: a reader that does not know the element opens the file as
        the single scan stored in <spectrum> -- the one that was shown -- and
        skips the rest. That shown scan is not stored a second time; its <scan>
        entry carries metadata only.

        Every scan must already be loaded into scanCache.
        """

        precision = config.main["dataPrecision"]
        endian = sys.byteorder

        buff = '  <chromatogram scans="%d"' % len(self.scanlist)
        if self.currentScanID is not None:
            buff += ' currentScan="%s"' % self._escape(str(self.currentScanID))
        buff += ">\n"

        for scanID, meta in self.scanlist.items():
            attributes = 'id="%s"' % self._escape("" if scanID is None else str(scanID))
            for name in MSD_SCAN_ATTRIBUTES:
                value = meta.get(name)
                if value is None or value == "":
                    continue
                attributes += ' %s="%s"' % (name, self._escape(str(value)))

            scan = self.scanCache.get(scanID)
            if scanID == self.currentScanID:
                buff += "    <scan %s current=\"1\" />\n" % attributes
                continue
            if scan is None:
                buff += "    <scan %s missing=\"1\" />\n" % attributes
                continue

            buff += "    <scan %s>\n" % attributes
            if len(scan.profile):
                mzArray, intArray = self._convertSpectrum(scan.profile, precision)
                buff += (
                    '      <mzArray precision="%s" compression="zlib" endian="%s" points="%d">%s</mzArray>\n'
                    % (precision, endian, len(scan.profile), mzArray.decode("utf-8"))
                )
                buff += (
                    '      <intArray precision="%s" compression="zlib" endian="%s">%s</intArray>\n'
                    % (precision, endian, intArray.decode("utf-8"))
                )
            if len(scan.peaklist):
                buff += "      <scanPeaklist>\n"
                buff += self._formatPeaks(scan.peaklist, "        ")
                buff += "      </scanPeaklist>\n"
            buff += "    </scan>\n"

        buff += "  </chromatogram>\n\n"

        return buff

    # ----

    def report(self, image=None):
        """Get HTML report."""

        mzFormat = "%0." + repr(config.main["mzDigits"]) + "f"
        intFormat = "%0." + repr(config.main["intDigits"]) + "f"
        ppmFormat = "%0." + repr(config.main["ppmDigits"]) + "f"

        # add header
        buff = REPORT_HEADER

        # add basic file info
        scanNumber = ""
        retentionTime = ""
        msLevel = ""
        precursorMZ = ""
        polarity = "unknown"
        points = len(self.spectrum.profile)
        peaks = len(self.spectrum.peaklist)

        basePeak = self.spectrum.peaklist.basepeak
        if basePeak:
            basePeak = basePeak.intensity

        if self.spectrum.scanNumber is not None:
            scanNumber = self.spectrum.scanNumber
        if self.spectrum.retentionTime is not None:
            retentionTime = self.spectrum.retentionTime
        if self.spectrum.msLevel is not None:
            msLevel = self.spectrum.msLevel
        if self.spectrum.precursorMZ is not None:
            precursorMZ = self.spectrum.precursorMZ

        if self.spectrum.polarity == 1:
            polarity = "positive"
        elif self.spectrum.polarity == -1:
            polarity = "negative"

        buff += "  <h1>mMass Report: <span>%s</span></h1>\n" % self.title
        buff += '  <table id="tableMainInfo">\n'
        buff += "    <tbody>\n"
        buff += (
            "      <tr><th>Date</th><td>%s</td><th>Scan Number</th><td>%s</td></tr>\n"
            % (self.date, scanNumber)
        )
        buff += (
            "      <tr><th>Operator</th><td>%s</td><th>Retention Time</th><td>%s</td></tr>\n"
            % (self.operator, retentionTime)
        )
        buff += (
            "      <tr><th>Contact</th><td>%s</td><th>MS Level</th><td>%s</td></tr>\n"
            % (self.contact, msLevel)
        )
        buff += (
            "      <tr><th>Institution</th><td>%s</td><th>Precursor m/z</th><td>%s</td></tr>\n"
            % (self.institution, precursorMZ)
        )
        buff += (
            "      <tr><th>Instrument</th><td>%s</td><th>Polarity</th><td>%s</td></tr>\n"
            % (self.instrument, polarity)
        )
        buff += (
            "      <tr><th>&nbsp;</th><td>&nbsp;</td><th>Spectrum Points</th><td>%s</td></tr>\n"
            % (points)
        )
        buff += (
            "      <tr><th>&nbsp;</th><td>&nbsp;</td><th>Peak List</th><td>%s</td></tr>\n"
            % (peaks)
        )
        buff += "    </tbody>\n"
        buff += "  </table>\n"

        # show spectrum
        if image:
            mimeType = "image/svg+xml" if image.lower().endswith(".svg") else "image/png"
            with open(image, "rb") as image_handle:
                image_src = "data:%s;base64,%s" % (
                    mimeType,
                    base64.b64encode(image_handle.read()).decode("ascii"),
                )
            buff += (
                '  <div id="spectrum"><img src="%s" alt="Mass Spectrum" style="max-width: 100%%; height: auto;" /></div>\n'
                % image_src
            )

        # notes
        if self.notes:
            notes = self.notes.replace("\n", "<br />")
            buff += "  <h2>Notes</h2>\n"
            buff += '  <p id="notes">%s</p>\n' % notes

        # annotations
        if self.annotations:
            tableID = "tableAnnotations1"
            buff += "  <h2>Annotations</h2>\n"
            buff += '  <table id="tableAnnotations">\n'
            buff += "    <thead>\n"
            buff += "      <tr>\n"
            buff += (
                '        <th><a href="" onclick="return sortTable(\''
                + tableID
                + '\', 0);" title="Sort by">Meas.&nbsp;m/z</a></th>\n'
            )
            buff += (
                '        <th><a href="" onclick="return sortTable(\''
                + tableID
                + '\', 1);" title="Sort by">Calc.&nbsp;m/z</a></th>\n'
            )
            buff += (
                '        <th><a href="" onclick="return sortTable(\''
                + tableID
                + '\', 2);" title="Sort by">&delta;&nbsp;(Da)</a></th>\n'
            )
            buff += (
                '        <th><a href="" onclick="return sortTable(\''
                + tableID
                + '\', 3);" title="Sort by">&delta;&nbsp;(ppm)</a></th>\n'
            )
            buff += (
                '        <th><a href="" onclick="return sortTable(\''
                + tableID
                + '\', 4);" title="Sort by">Int.</a></th>\n'
            )
            buff += (
                '        <th><a href="" onclick="return sortTable(\''
                + tableID
                + '\', 5);" title="Sort by">Rel.&nbsp;Int.&nbsp;(%)</a></th>\n'
            )
            buff += (
                '        <th><a href="" onclick="return sortTable(\''
                + tableID
                + '\', 6);" title="Sort by">z</a></th>\n'
            )
            buff += (
                '        <th><a href="" onclick="return sortTable(\''
                + tableID
                + '\', 7);" title="Sort by">Annotation</a></th>\n'
            )
            buff += (
                '        <th><a href="" onclick="return sortTable(\''
                + tableID
                + '\', 8);" title="Sort by">Formula</a></th>\n'
            )
            buff += "      </tr>\n"
            buff += "    </thead>\n"
            buff += '    <tbody id="%s">\n' % tableID
            for annot in self.annotations:
                mz = mzFormat % annot.mz
                absIntensity = intFormat % (annot.ai - annot.base)
                relIntensity = ""
                theoretical = ""
                charge = ""
                deltaDa = ""
                deltaPpm = ""
                formula = ""
                label = self._replaceLabelIDs("compounds", annot.label)

                if basePeak:
                    relIntensity = "%0.2f" % (
                        ((annot.ai - annot.base) / basePeak) * 100
                    )
                if annot.theoretical:
                    theoretical = mzFormat % annot.theoretical
                    deltaDa = mzFormat % annot.delta("Da")
                    deltaPpm = ppmFormat % annot.delta("ppm")
                if annot.formula:
                    formula = annot.formula
                if annot.charge:
                    charge = annot.charge
                if annot.radical:
                    charge = str(annot.charge) + " &bull;"

                buff += (
                    '      <tr><td class="right nowrap">%s</td><td class="right nowrap">%s</td><td class="right nowrap">%s</td><td class="right nowrap">%s</td><td class="right nowrap">%s</td><td class="right nowrap">%s</td><td class="center nowrap">%s</td><td>%s</td><td class="nowrap">%s</td></tr>\n'
                    % (
                        mz,
                        theoretical,
                        deltaDa,
                        deltaPpm,
                        absIntensity,
                        relIntensity,
                        charge,
                        label,
                        formula,
                    )
                )
            buff += "    </tbody>\n"
            buff += "  </table>\n"

        # sequences
        if self.sequences:
            for x, sequence in enumerate(self.sequences):
                accession = self._replaceLabelIDs("sequences", sequence.accession)
                mass = sequence.mass()
                moMass = mzFormat % mass[0]
                avMass = mzFormat % mass[1]
                chain = self._formatSequence(sequence)
                coverage = self._getSequenceCoverage(sequence)
                matchedInt = self._getMatchedIntensity(
                    self.spectrum.peaklist, sequence.matches
                )
                tableID = "tableSequenceMatches%d" % x

                cyclic = ""
                if sequence.cyclic:
                    cyclic = " (Cyclic)"

                if accession:
                    buff += "  <h2>Sequence - <span>%s</span> - [%s]</h2>\n" % (
                        sequence.title,
                        accession,
                    )
                else:
                    buff += "  <h2>Sequence - <span>%s</span></h2>\n" % sequence.title

                buff += '  <table id="tableSequenceInfo">\n'
                buff += "    <thead>\n"
                buff += "      <tr><th>Accession</th><th>Length</th><th>Mo. Mass</th><th>Av. Mass</th><th>Coverage</th><th>Matched Int.</th></tr>\n"
                buff += "    </thead>\n"
                buff += "    <tbody>\n"
                buff += (
                    '      <tr><td class="right">%s</td><td class="right">%s%s</td><td class="right">%s</td><td class="right">%s</td><td class="right">%s</td><td class="right">%s</td></tr>\n'
                    % (
                        accession,
                        len(sequence),
                        cyclic,
                        moMass,
                        avMass,
                        coverage,
                        matchedInt,
                    )
                )
                buff += (
                    '      <tr><td colspan="6" class="sequence">%s</td></tr>\n' % chain
                )
                buff += "    </tbody>\n"
                buff += "  </table>\n"

                if sequence.modifications:
                    buff += '  <table id="tableSequenceModifications">\n'
                    buff += "    <thead>\n"
                    buff += "      <tr><th>Position</th><th>Modification</th><th>Type</th><th>Mo.&nbsp;Mass</th><th>Av.&nbsp;Mass</th><th>Formula</th></tr>\n"
                    buff += "    </thead>\n"
                    buff += "    <tbody>\n"
                    for mod in self._formatModifications(sequence):
                        buff += (
                            '      <tr><td class="nowrap">%s</td><td>%s</td><td>%s</td><td class="right nowrap">%s</td><td class="right nowrap">%s</td><td class="nowrap">%s</td></tr>\n'
                            % mod
                        )
                    buff += "    </tbody>\n"
                    buff += "  </table>\n"

                if sequence.matches:
                    buff += '  <table id="tableSequenceMatches">\n'
                    buff += "    <thead>\n"
                    buff += "      <tr>\n"
                    buff += (
                        '        <th><a href="" onclick="return sortTable(\''
                        + tableID
                        + '\', 0);" title="Sort by">Meas.&nbsp;m/z</a></th>\n'
                    )
                    buff += (
                        '        <th><a href="" onclick="return sortTable(\''
                        + tableID
                        + '\', 1);" title="Sort by">Calc.&nbsp;m/z</a></th>\n'
                    )
                    buff += (
                        '        <th><a href="" onclick="return sortTable(\''
                        + tableID
                        + '\', 2);" title="Sort by">&delta;&nbsp;(Da)</a></th>\n'
                    )
                    buff += (
                        '        <th><a href="" onclick="return sortTable(\''
                        + tableID
                        + '\', 3);" title="Sort by">&delta;&nbsp;(ppm)</a></th>\n'
                    )
                    buff += (
                        '        <th><a href="" onclick="return sortTable(\''
                        + tableID
                        + '\', 4);" title="Sort by">Rel.&nbsp;Int.&nbsp;(%)</a></th>\n'
                    )
                    buff += (
                        '        <th><a href="" onclick="return sortTable(\''
                        + tableID
                        + '\', 5);" title="Sort by">z</a></th>\n'
                    )
                    buff += (
                        '        <th><a href="" onclick="return sortTable(\''
                        + tableID
                        + '\', 6);" title="Sort by">Annotation</a></th>\n'
                    )
                    buff += (
                        '        <th><a href="" onclick="return sortTable(\''
                        + tableID
                        + '\', 7);" title="Sort by">Formula</a></th>\n'
                    )
                    buff += "      </tr>\n"
                    buff += "    </thead>\n"
                    buff += '    <tbody id="%s">\n' % tableID
                    for m in sequence.matches:
                        mz = mzFormat % m.mz
                        relIntensity = ""
                        theoretical = ""
                        charge = ""
                        deltaDa = ""
                        deltaPpm = ""
                        formula = ""

                        if basePeak:
                            relIntensity = "%0.2f" % (
                                ((m.ai - m.base) / basePeak) * 100
                            )
                        if m.theoretical:
                            theoretical = mzFormat % m.theoretical
                            deltaDa = mzFormat % m.delta("Da")
                            deltaPpm = ppmFormat % m.delta("ppm")
                        if m.formula:
                            formula = m.formula
                        if m.charge:
                            charge = m.charge
                        if m.radical:
                            charge = str(m.charge) + " &bull;"

                        buff += (
                            '      <tr><td class="right nowrap">%s</td><td class="right nowrap">%s</td><td class="right nowrap">%s</td><td class="right nowrap">%s</td><td class="right nowrap">%s</td><td class="center nowrap">%s</td><td>%s</td><td class="nowrap">%s</td></tr>\n'
                            % (
                                mz,
                                theoretical,
                                deltaDa,
                                deltaPpm,
                                relIntensity,
                                charge,
                                m.label,
                                formula,
                            )
                        )
                    buff += "    </tbody>\n"
                    buff += "  </table>\n"

        # add footer
        buff += '  <p id="footer">Generated by mMass &bull; Open Source Mass Spectrometry Tool &bull; <a href="https://github.com/lukaszsobala/mMass" title="mMass homepage">https://github.com/lukaszsobala/mMass</a></p>\n'
        buff += "</body>\n"
        buff += "</html>"

        return buff

    # ----

    def _escape(self, text):
        """Clear special characters such as <> etc."""

        text = text.strip()
        search = ("&", '"', "'", "<", ">")
        replace = ("&amp;", "&quot;", "&#39;", "&lt;", "&gt;")
        for x, item in enumerate(search):
            text = text.replace(item, replace[x])

        return text

    # ----

    def _convertSpectrum(self, spectrum, precision="f"):
        """Convert spectrum data to compressed binary format coded by base64."""

        # get precision
        if precision == 32:
            precision = "f"
        elif precision == 64:
            precision = "d"

        # convert data to binary
        if len(spectrum) > 0:
            arr = numpy.asarray(spectrum)
            mzArray = arr[:, 0].astype(precision).tobytes()
            intArray = arr[:, 1].astype(precision).tobytes()
        else:
            mzArray = b""
            intArray = b""

        # compress data by gz
        mzArray = zlib.compress(mzArray)
        intArray = zlib.compress(intArray)

        # convert to ascii by base64
        mzArray = base64.b64encode(mzArray)
        intArray = base64.b64encode(intArray)

        return mzArray, intArray

    # ----

    def _formatSequence(self, sequence):
        """Format sequence for report."""

        # get coverage
        coverage = len(sequence) * [0]
        for m in sequence.matches:
            if m.sequenceRange:
                for i in range(m.sequenceRange[0] - 1, m.sequenceRange[1]):
                    coverage[i] = 1

        # format sequence
        buff = ""
        for x, monomer in enumerate(sequence):
            attributes = ""

            if sequence.ismodified(x, True):
                attributes += "modified "
            if coverage[x]:
                attributes += "matched "

            if attributes:
                buff += '<span class="%s">%s</span>' % (attributes, monomer)
            else:
                buff += monomer

            if sequence.chainType != "aminoacids" and (x + 1) != len(sequence):
                buff += " | "
            elif not (x + 1) % 10:
                buff += " "

        return buff

    # ----

    def _formatModifications(self, sequence):
        """Format sequence modifications for report."""

        buff = []

        format = "%0." + repr(config.main["mzDigits"]) + "f"
        for mod in sequence.modifications:
            name = mod[0]

            # format position
            if isinstance(mod[1], int):
                position = "%s %s" % (sequence[mod[1]], mod[1] + 1)
            elif mod[1] == "nTerm":
                position = "N-terminus"
            elif mod[1] == "cTerm":
                position = "C-terminus"
            else:
                position = "All " + mod[1]

            # format type
            if mod[2] == "f":
                modtype = "fixed"
            else:
                modtype = "variable"

            # format masses
            modification: Any = mspy.modifications[name]
            mass = modification.mass
            massMo = format % mass[0]
            massAv = format % mass[1]

            # format formula
            formula = mspy.modifications[name].gainFormula
            if mspy.modifications[name].lossFormula:
                formula += " - " + mspy.modifications[name].lossFormula

            # append data
            buff.append((position, name, modtype, massMo, massAv, formula))

        return buff

    # ----

    def _getSequenceCoverage(self, sequence):
        """Get sequence coverage from matches."""

        # get ranges
        ranges = []
        for m in sequence.matches:
            if m.sequenceRange is not None:
                ranges.append(m.sequenceRange)

        # get coverage
        coverage = mspy.coverage(ranges, len(sequence))
        coverage = "%.1f " % coverage
        coverage += "%"

        return coverage

    # ----

    def _getMatchedIntensity(self, peaklist, matches):
        """Get total matched intensity."""

        # get total intensity
        totalInt = 0
        buff = {}
        for peak in peaklist:
            totalInt += peak.intensity
            buff[round(peak.mz, 6)] = peak.intensity

        # get matched intensity
        matchedInt = 0
        for item in matches:
            mz = round(item.mz, 6)
            if mz in buff:
                matchedInt += buff[mz]
                del buff[mz]

        # get percentage
        matched = "0.0"
        if totalInt:
            matched = "%.1f" % (100 * matchedInt / totalInt)
        matched += " %"

        return matched

    # ----

    def _replaceLabelIDs(self, section, label):
        """Replace IDs with links in annotations."""

        # replace IDs
        for name in config.replacements[section]:
            self._currentReplacement = (section, name)
            label = re.sub(
                config.replacements[section][name]["pattern"], self._replaceIDs, label
            )

        return label

    # ----

    def _replaceIDs(self, matchobj):
        """Replace IDs to links."""

        section, name = self._currentReplacement
        url = config.replacements[section][name]["url"] % matchobj.group(1)
        return '<a href="%s" title="More information...">%s</a>' % (
            url,
            matchobj.group(0),
        )

    # ----


# ANNOTATION OBJECT
# -----------------


class annotation:
    """Annotation object definition."""

    def __init__(
        self,
        label,
        mz,
        ai,
        base=0.0,
        charge=None,
        radical=None,
        theoretical=None,
        formula=None,
    ):

        self.label = label
        self.mz = mz
        self.ai = ai
        self.base = base
        self.charge = charge
        self.radical = radical
        self.theoretical = theoretical
        self.formula = formula
        self.peakIndex: int | None = None

    # ----

    def delta(self, units):
        """Get error in specified units."""

        if self.theoretical is not None:
            return mspy.delta(self.mz, self.theoretical, units)
        else:
            return None

    # ----


# SEQUENCE MATCH OBJECT
# ---------------------


class match:
    """Match object definition."""

    def __init__(
        self,
        label,
        mz,
        ai,
        base=0.0,
        charge=None,
        radical=None,
        theoretical=None,
        formula=None,
    ):

        self.label = label
        self.mz = mz
        self.ai = ai
        self.base = base
        self.charge = charge
        self.radical = radical
        self.theoretical = theoretical
        self.formula = formula

        self.peakIndex: int | None = None
        self.sequenceRange = None
        self.fragmentSerie = None
        self.fragmentIndex = None

    # ----

    def delta(self, units):
        """Get error in specified units."""

        if self.theoretical is not None:
            return mspy.delta(self.mz, self.theoretical, units)
        else:
            return None

    # ----


# MSD FORMAT PARSER
# -----------------


class parseMSD:
    """Parse data from mSD files."""

    def __init__(self, path):

        self.path = path
        self.errors = []
        self._version = None
        self._parsedData: Any = None

        # init new document
        self.document = document()
        self.document.format = "mSD"
        self.document.path = path

    # ----

    def getDocument(self):
        """Get document."""

        self.errors = []

        # parse data
        if not self._parsedData:
            try:
                self._parsedData = xml.dom.minidom.parse(self.path)
                self._version = self._getVersion()
            except Exception:
                return False

        # get data
        if self._version == "1.0":
            self.handleDescription()
            self.handleSpectrum()
            self.handlePeaklist_10()
            self.handleSequences_10()
            dirName, fileName = os.path.split(self.path)
            self.document.title = fileName[:-4]
        else:
            self.handleDescription()
            self.handleSpectrum()
            self.handlePeaklist()
            self.handleAnnotations()
            self.handleSequences()
            self.handleChromatogram()

        return self.document

    # ----

    def getSequences(self):
        """Get list of available sequences."""

        self.errors = []

        # parse data
        if not self._parsedData:
            try:
                self._parsedData = xml.dom.minidom.parse(self.path)
                self._version = self._getVersion()
            except Exception:
                return False

        # set handler
        if self._version == "1.0":
            handler = self.handleSequence_10
        else:
            handler = self.handleSequence

        # get sequence
        data = []
        sequenceTags = self._parsedData.getElementsByTagName("sequence")
        if sequenceTags:
            for sequenceTag in sequenceTags:
                sequence = handler(sequenceTag)
                if sequence:
                    data.append(sequence)

        return data

    # ----

    # CURRENT HANDLERS

    def handleDescription(self):
        """Get document info."""

        # get description
        descriptionTags = self._parsedData.getElementsByTagName("description")
        if descriptionTags:

            titleTags = descriptionTags[0].getElementsByTagName("title")
            if titleTags:
                self.document.title = self._getNodeText(titleTags[0])

            dateTags = descriptionTags[0].getElementsByTagName("date")
            if dateTags:
                self.document.date = dateTags[0].getAttribute("value")

            operatorTags = descriptionTags[0].getElementsByTagName("operator")
            if operatorTags:
                self.document.operator = operatorTags[0].getAttribute("value")

            contactTags = descriptionTags[0].getElementsByTagName("contact")
            if contactTags:
                self.document.contact = contactTags[0].getAttribute("value")

            institutionTags = descriptionTags[0].getElementsByTagName("institution")
            if institutionTags:
                self.document.institution = institutionTags[0].getAttribute("value")

            instrumentTags = descriptionTags[0].getElementsByTagName("instrument")
            if instrumentTags:
                self.document.instrument = instrumentTags[0].getAttribute("value")

            notesTags = descriptionTags[0].getElementsByTagName("notes")
            if notesTags:
                self.document.notes = self._getNodeText(notesTags[0])

    # ----

    def handleSpectrum(self):
        """Get spectrum data."""

        # get spectrum
        spectrumTags = self._parsedData.getElementsByTagName("spectrum")
        if spectrumTags:

            # get metadata
            scanNumber = spectrumTags[0].getAttribute("scanNumber")
            if scanNumber:
                try:
                    self.document.spectrum.scanNumber = int(scanNumber)
                except ValueError:
                    pass

            msLevel = spectrumTags[0].getAttribute("msLevel")
            if msLevel:
                try:
                    self.document.spectrum.msLevel = int(msLevel)
                except ValueError:
                    pass

            retentionTime = spectrumTags[0].getAttribute("retentionTime")
            if retentionTime:
                try:
                    self.document.spectrum.retentionTime = float(retentionTime)
                except ValueError:
                    pass

            precursorMZ = spectrumTags[0].getAttribute("precursorMZ")
            if precursorMZ:
                try:
                    self.document.spectrum.precursorMZ = float(precursorMZ)
                except ValueError:
                    pass

            precursorCharge = spectrumTags[0].getAttribute("precursorCharge")
            if precursorCharge:
                try:
                    self.document.spectrum.precursorCharge = int(precursorCharge)
                except ValueError:
                    pass

            polarity = spectrumTags[0].getAttribute("polarity")
            if polarity:
                try:
                    self.document.spectrum.polarity = int(polarity)
                except ValueError:
                    pass

            # get mzArray
            mzData = None
            mzArrayTags = spectrumTags[0].getElementsByTagName("mzArray")
            if mzArrayTags:

                compression = False
                if mzArrayTags[0].hasAttribute("compression"):
                    compression = mzArrayTags[0].getAttribute("compression")

                precision = "f"
                if (
                    mzArrayTags[0].hasAttribute("precision")
                    and mzArrayTags[0].getAttribute("precision") == "64"
                ):
                    precision = "d"

                endian = "<"
                if mzArrayTags[0].getAttribute("endian") == "big":
                    endian = ">"

                mzData = self._getNodeText(mzArrayTags[0])
                mzData = self._convertDataPoints(mzData, compression, precision, endian)

            # get intArray
            intData = None
            intArrayTags = spectrumTags[0].getElementsByTagName("intArray")
            if intArrayTags:

                compression = False
                if intArrayTags[0].hasAttribute("compression"):
                    compression = intArrayTags[0].getAttribute("compression")

                precision = "f"
                if (
                    intArrayTags[0].hasAttribute("precision")
                    and intArrayTags[0].getAttribute("precision") == "64"
                ):
                    precision = "d"

                endian = "<"
                if intArrayTags[0].getAttribute("endian") == "big":
                    endian = ">"

                intData = self._getNodeText(intArrayTags[0])
                intData = self._convertDataPoints(
                    intData, compression, precision, endian
                )

            # mSD documents may store only a peaklist with an empty spectrum.
            # In such case, keep the profile empty and continue.
            if not mzArrayTags and not intArrayTags:
                return

            # check data
            if mzData is None or mzData is False:
                raise ValueError("mzData could not be handled")

            if intData is None or intData is False:
                raise ValueError("mzData could not be handled")

            if len(mzData) != len(intData):
                raise ValueError("m/z and intensity arrays have different lengths")

            # format data
            mzData = numpy.array(mzData)
            mzData.shape = (-1, 1)

            intData = numpy.array(intData)
            intData.shape = (-1, 1)

            points = numpy.concatenate((mzData, intData), axis=1)
            points = points.astype(numpy.float64)

            # add to spectrum
            self.document.spectrum.setprofile(points)

    # ----

    def handlePeaklist(self):
        """Get peaklist."""

        peaklist = []

        # get peaklist
        peaklistTags = self._parsedData.getElementsByTagName("peaklist")
        if peaklistTags:
            peaklist = self._parsePeaks(peaklistTags[0])

        # add peaklist to document
        peaklist = mspy.peaklist(peaklist)
        self.document.spectrum.setpeaklist(peaklist)

    # ----

    def _parsePeaks(self, peaklistTag):
        """Parse the <peak> elements (with their envelopes) of a peak list element."""

        peaklist = []

        # get peaks
        peakTags = peaklistTag.getElementsByTagName("peak")
        for peakTag in peakTags:

            # get data
            try:
                mz = float(peakTag.getAttribute("mz"))
                ai = float(peakTag.getAttribute("intensity"))

                base = 0.0
                sn = None
                charge = None
                isotope = None
                fwhm = None
                group = ""

                if peakTag.hasAttribute("baseline"):
                    base = float(peakTag.getAttribute("baseline"))
                if peakTag.hasAttribute("sn"):
                    sn = float(peakTag.getAttribute("sn"))
                if peakTag.hasAttribute("charge"):
                    charge = int(peakTag.getAttribute("charge"))
                if peakTag.hasAttribute("isotope"):
                    isotope = int(peakTag.getAttribute("isotope"))
                if peakTag.hasAttribute("fwhm"):
                    fwhm = float(peakTag.getAttribute("fwhm"))
                if peakTag.hasAttribute("group"):
                    group = peakTag.getAttribute("group")

            except ValueError:
                self.errors.append("Incorrect peak data.")
                continue

            # make peak
            peak = mspy.peak(
                mz=mz,
                ai=ai,
                base=base,
                sn=sn,
                charge=charge,
                isotope=isotope,
                fwhm=fwhm,
                group=group,
            )

            # Restore a user FWHM lock so a manually pinned width survives a
            # save/reload (see panel_peaklist's FWHM lock checkbox).
            if peakTag.getAttribute("fwhmLocked") in ("1", "true", "True"):
                peak.attributes["_fwhmLocked"] = True
            if peakTag.hasAttribute("referenceMz"):
                try:
                    peak.attributes["referenceMz"] = float(peakTag.getAttribute("referenceMz"))
                except ValueError:
                    pass

            # Restore optional envelope metadata saved in mSD.
            envelopeTags = peakTag.getElementsByTagName("envelope")
            if envelopeTags:
                envelopeTag = envelopeTags[0]
                envelope = {
                    "area": 0.0,
                    "sumint": 0.0,
                    "fwhm": fwhm if fwhm is not None else 0.1,
                    "shape": "gaussian",
                    "isotopes": [],
                }

                try:
                    if envelopeTag.hasAttribute("area"):
                        envelope["area"] = float(envelopeTag.getAttribute("area"))
                    if envelopeTag.hasAttribute("sumint"):
                        envelope["sumint"] = float(
                            envelopeTag.getAttribute("sumint")
                        )
                    if envelopeTag.hasAttribute("fwhm"):
                        envelope["fwhm"] = float(envelopeTag.getAttribute("fwhm"))
                except ValueError:
                    envelope = None

                if envelope is not None:
                    if envelopeTag.hasAttribute("shape"):
                        envelope["shape"] = envelopeTag.getAttribute("shape")
                    if envelopeTag.hasAttribute("averagine"):
                        envelope["averagineType"] = envelopeTag.getAttribute(
                            "averagine"
                        )
                    # absent for envelopes saved before the count existed:
                    # leaving the key out is what marks them as unverifiable,
                    # so they are measured against the theoretical extent
                    if envelopeTag.hasAttribute("detected"):
                        try:
                            envelope["detected"] = max(
                                1, int(envelopeTag.getAttribute("detected"))
                            )
                        except ValueError:
                            pass

                    isotopeTags = envelopeTag.getElementsByTagName("isotope")
                    for isotopeTag in isotopeTags:
                        try:
                            isoMZ = float(isotopeTag.getAttribute("mz"))
                            isoIntensity = float(isotopeTag.getAttribute("intensity"))
                        except ValueError:
                            continue
                        envelope["isotopes"].append((isoMZ, isoIntensity))

                    if envelope["isotopes"]:
                        peak.attributes["envelope"] = envelope

            peaklist.append(peak)

        return peaklist

    # ----

    def handleChromatogram(self):
        """Get all scans of an LC-MS run (the mSD <chromatogram> element)."""

        chromatogramTags = self._parsedData.getElementsByTagName("chromatogram")
        if not chromatogramTags:
            return

        scanlist = {}
        scanCache = {}
        currentID = None

        for scanTag in chromatogramTags[0].getElementsByTagName("scan"):

            # scan ID as the parsers use it (numeric scan numbers)
            scanID = self._convertScanID(scanTag.getAttribute("id"))

            meta = {}
            for name, kind in MSD_SCAN_ATTRIBUTES.items():
                meta[name] = None
                if scanTag.hasAttribute(name):
                    value = scanTag.getAttribute(name)
                    try:
                        meta[name] = kind(value)
                    except ValueError:
                        self.errors.append("Incorrect scan metadata.")
            if meta["title"] is None:
                meta["title"] = ""
            if meta["spectrumType"] is None:
                meta["spectrumType"] = "unknown"
            scanlist[scanID] = meta

            # the shown scan is the document's own spectrum
            if scanTag.getAttribute("current") in ("1", "true"):
                currentID = scanID
                continue
            if scanTag.getAttribute("missing") in ("1", "true"):
                continue

            scan = mspy.scan()
            profile = self._parseArrays(scanTag)
            if profile is not None:
                scan.setprofile(profile)
            peaklistTags = scanTag.getElementsByTagName("scanPeaklist")
            if peaklistTags:
                scan.setpeaklist(mspy.peaklist(self._parsePeaks(peaklistTags[0])))

            scan.title = meta["title"]
            scan.scanNumber = meta["scanNumber"]
            scan.parentScanNumber = meta["parentScanNumber"]
            scan.msLevel = meta["msLevel"]
            scan.polarity = meta["polarity"]
            scan.retentionTime = meta["retentionTime"]
            scan.totIonCurrent = meta["totIonCurrent"]
            scan.basePeakMZ = meta["basePeakMZ"]
            scan.basePeakIntensity = meta["basePeakIntensity"]
            scan.precursorMZ = meta["precursorMZ"]
            scan.precursorIntensity = meta["precursorIntensity"]
            scan.precursorCharge = meta["precursorCharge"]
            if meta["filterString"]:
                scan.attributes["filterString"] = meta["filterString"]

            scanCache[scanID] = scan

        if len(scanlist) < 2:
            return

        # the <chromatogram> attribute names the shown scan too
        if currentID is None and chromatogramTags[0].hasAttribute("currentScan"):
            currentID = self._convertScanID(chromatogramTags[0].getAttribute("currentScan"))
        if currentID not in scanlist:
            currentID = next(iter(scanlist))
        scanCache[currentID] = self.document.spectrum

        # <spectrum> holds only part of a scan's metadata; its <scan> entry the rest
        spectrum = self.document.spectrum
        meta = scanlist[currentID]
        for name in (
            "parentScanNumber",
            "totIonCurrent",
            "basePeakMZ",
            "basePeakIntensity",
            "precursorIntensity",
        ):
            if getattr(spectrum, name, None) is None and meta.get(name) is not None:
                setattr(spectrum, name, meta[name])
        if meta.get("filterString"):
            spectrum.attributes["filterString"] = meta["filterString"]

        self.document.scanlist = scanlist
        self.document.scanCache = scanCache
        self.document.currentScanID = currentID
        self.document.chromatograms = makeChromatograms(scanlist)
        self.document.scanSource = None

    # ----

    def _convertScanID(self, value):
        """Scan ID read from an mSD attribute (int when numeric, None when empty)."""

        if value == "":
            return None
        try:
            return int(value)
        except ValueError:
            return value

    # ----

    def _parseArrays(self, tag):
        """Profile points from the <mzArray>/<intArray> children of an element."""

        mzArrayTags = tag.getElementsByTagName("mzArray")
        intArrayTags = tag.getElementsByTagName("intArray")
        if not mzArrayTags or not intArrayTags:
            return None

        arrays = []
        for arrayTag in (mzArrayTags[0], intArrayTags[0]):
            compression = arrayTag.getAttribute("compression") or False
            precision = "d" if arrayTag.getAttribute("precision") == "64" else "f"
            endian = ">" if arrayTag.getAttribute("endian") == "big" else "<"
            data = self._getNodeText(arrayTag)
            arrays.append(
                self._convertDataPoints(data, compression, precision, endian)
            )

        if len(arrays[0]) != len(arrays[1]):
            self.errors.append("m/z and intensity arrays have different lengths")
            return None

        return numpy.column_stack(arrays).astype(numpy.float64)

    # ----

    def handleAnnotations(self):
        """Get annotations."""

        # get annotations
        annotationsTags = self._parsedData.getElementsByTagName("annotations")
        if annotationsTags:

            # get annotation
            annotationTags = annotationsTags[0].getElementsByTagName("annotation")
            for annotationTag in annotationTags:

                # get data
                try:
                    label = self._getNodeText(annotationTag)
                    mz = float(annotationTag.getAttribute("peakMZ"))
                    ai = 0.0
                    base = 0.0
                    charge = None
                    radical = None
                    theoretical = None
                    formula = None

                    if annotationTag.hasAttribute("peakIntensity"):
                        ai = float(annotationTag.getAttribute("peakIntensity"))
                    if annotationTag.hasAttribute("peakBaseline"):
                        base = float(annotationTag.getAttribute("peakBaseline"))
                    if annotationTag.hasAttribute("charge"):
                        charge = int(annotationTag.getAttribute("charge"))
                    if annotationTag.hasAttribute("radical"):
                        radical = int(annotationTag.getAttribute("radical"))
                    if annotationTag.hasAttribute("calcMZ"):
                        theoretical = float(annotationTag.getAttribute("calcMZ"))
                    if annotationTag.hasAttribute("formula"):
                        formula = annotationTag.getAttribute("formula")

                    annot = annotation(
                        label=label,
                        mz=mz,
                        ai=ai,
                        base=base,
                        charge=charge,
                        radical=radical,
                        theoretical=theoretical,
                        formula=formula,
                    )

                except ValueError:
                    self.errors.append("Incorrect annotation data.")
                    continue

                # append annotation
                self.document.annotations.append(annot)

            # sort annotations by mz
            self.document.sortAnnotations()

    # ----

    def handleSequences(self):
        """Get sequences."""

        # get sequences
        sequencesTags = self._parsedData.getElementsByTagName("sequences")
        if sequencesTags:
            sequenceTags = sequencesTags[0].getElementsByTagName("sequence")
            for sequenceTag in sequenceTags:
                sequence = self.handleSequence(sequenceTag)
                if sequence:
                    self.document.sequences.append(sequence)

    # ----

    def handleSequence(self, sequenceTag):
        """Get sequence."""

        # get title
        title = ""
        titleTags = sequenceTag.getElementsByTagName("title")
        if titleTags:
            title = self._getNodeText(titleTags[0])

        # get accession
        accession = ""
        accessionTags = sequenceTag.getElementsByTagName("accession")
        if accessionTags:
            accession = self._getNodeText(accessionTags[0])

        # get chain
        chain = ""
        chainType = "aminoacids"
        cyclic = False
        seqTags = sequenceTag.getElementsByTagName("seq")
        if seqTags:
            chain = self._getNodeText(seqTags[0])

            if seqTags[0].hasAttribute("type"):
                chainType = str(seqTags[0].getAttribute("type"))
            if seqTags[0].hasAttribute("cyclic"):
                try:
                    cyclic = bool(int(seqTags[0].getAttribute("cyclic")))
                except ValueError:
                    pass

        # get monomers
        monomerTags = sequenceTag.getElementsByTagName("monomer")
        for monomerTag in monomerTags:
            abbr = monomerTag.getAttribute("abbr")
            formula = monomerTag.getAttribute("formula")
            if abbr not in mspy.monomers:
                self._addMonomer(abbr, formula)

        # make sequence
        try:
            sequence: Any = mspy.sequence(
                chain,
                title=title,
                accession=accession,
                chainType=chainType,
                cyclic=cyclic,
            )
            sequence.matches = []
        except Exception:
            self.errors.append("Unknown monomers in sequence data.")
            return False

        # get modifications
        modificationTags = sequenceTag.getElementsByTagName("modification")
        for modificationTag in modificationTags:
            name = modificationTag.getAttribute("name")
            position = modificationTag.getAttribute("position")
            gainFormula = modificationTag.getAttribute("gainFormula")
            lossFormula = modificationTag.getAttribute("lossFormula")

            try:
                position = int(position)
            except Exception:
                pass

            modtype = "f"
            if modificationTag.getAttribute("type") == "variable":
                modtype = "v"

            if name in mspy.modifications:
                sequence.modify(name, position, modtype)
            else:
                if self._addModification(name, gainFormula, lossFormula):
                    sequence.modify(name, position, modtype)

        # get matches
        sequence.matches[:] = self.handleSequenceMatches(sequenceTag)

        return sequence

    # ----

    def handleSequenceMatches(self, sequenceTag):
        """Get sequence amtches."""

        # get matches
        matches = []
        matchTags = sequenceTag.getElementsByTagName("match")
        for matchTag in matchTags:
            try:
                label = self._getNodeText(matchTag)
                mz = float(matchTag.getAttribute("peakMZ"))

                ai = 0.0
                base = 0.0
                charge = None
                radical = None
                theoretical = None
                formula = None
                sequenceRange = None
                fragmentSerie = None
                fragmentIndex = None

                if matchTag.hasAttribute("peakIntensity"):
                    ai = float(matchTag.getAttribute("peakIntensity"))
                if matchTag.hasAttribute("peakBaseline"):
                    base = float(matchTag.getAttribute("peakBaseline"))
                if matchTag.hasAttribute("charge"):
                    charge = int(matchTag.getAttribute("charge"))
                if matchTag.hasAttribute("radical"):
                    radical = int(matchTag.getAttribute("radical"))
                if matchTag.hasAttribute("calcMZ"):
                    theoretical = float(matchTag.getAttribute("calcMZ"))
                if matchTag.hasAttribute("formula"):
                    formula = matchTag.getAttribute("formula")
                if matchTag.hasAttribute("sequenceRange"):
                    sequenceRange = [
                        int(x)
                        for x in matchTag.getAttribute("sequenceRange").split("-")
                    ]
                if matchTag.hasAttribute("fragmentSerie"):
                    fragmentSerie = matchTag.getAttribute("fragmentSerie")
                if matchTag.hasAttribute("fragmentIndex"):
                    fragmentIndex = int(matchTag.getAttribute("fragmentIndex"))

                m: Any = match(
                    label=label,
                    mz=mz,
                    ai=ai,
                    base=base,
                    charge=charge,
                    radical=radical,
                    theoretical=theoretical,
                    formula=formula,
                )
                m.sequenceRange = sequenceRange
                m.fragmentSerie = fragmentSerie
                m.fragmentIndex = fragmentIndex

                matches.append(m)

            except ValueError:
                self.errors.append("Incorrect sequence match data.")
                continue

        return matches

    # ----

    # OLDER VERSIONS

    def handlePeaklist_10(self):
        """Get peaklist from mSD version 1.0."""

        peaklist = []

        # get peaklist
        peaklistTags = self._parsedData.getElementsByTagName("peaklist")
        if peaklistTags:

            # get peaks
            peakTags = peaklistTags[0].getElementsByTagName("peak")
            for peakTag in peakTags:

                # get data
                try:
                    mz = float(peakTag.getAttribute("mass"))
                    ai = float(peakTag.getAttribute("intens"))
                    annot = peakTag.getAttribute("annots")
                except ValueError:
                    self.errors.append("Incorrect peak data.")
                    continue

                # make peak
                peak = mspy.peak(mz=mz, ai=ai)
                peaklist.append(peak)

                # make annotation
                if annot:
                    self.document.annotations.append(
                        annotation(label=annot, mz=mz, ai=ai)
                    )

        # add peaklist to document
        peaklist = mspy.peaklist(peaklist)
        self.document.spectrum.setpeaklist(peaklist)

    # ----

    def handleSequences_10(self):
        """Get sequences from mSD version 1.0."""

        # get sequences
        sequencesTags = self._parsedData.getElementsByTagName("sequences")
        if sequencesTags:
            sequenceTags = sequencesTags[0].getElementsByTagName("sequence")
            for sequenceTag in sequenceTags:
                sequence = self.handleSequence_10(sequenceTag)
                if sequence:
                    self.document.sequences.append(sequence)

    # ----

    def handleSequence_10(self, sequenceTag):
        """Get sequence from mSD version 1.0."""

        # get title
        title = ""
        titleTags = sequenceTag.getElementsByTagName("title")
        if titleTags:
            title = self._getNodeText(titleTags[0])

        # get sequence
        chain = ""
        seqTags = sequenceTag.getElementsByTagName("seq")
        if seqTags:
            chain = self._getNodeText(seqTags[0])

        # make sequence
        try:
            sequence: Any = mspy.sequence(chain, title=title)
            sequence.matches = []
        except Exception:
            self.errors.append("Unknown monomers in sequence data.")
            return False

        # get modifications
        modificationTags = sequenceTag.getElementsByTagName("modification")
        for modificationTag in modificationTags:
            name = modificationTag.getAttribute("name")
            amino = modificationTag.getAttribute("amino")
            position = modificationTag.getAttribute("position")
            gainFormula = modificationTag.getAttribute("gain")
            lossFormula = modificationTag.getAttribute("loss")

            if position:
                position = int(position) - 1
            else:
                position = amino

            if name in mspy.modifications:
                sequence.modify(name, position)
            else:
                if self._addModification(name, gainFormula, lossFormula):
                    sequence.modify(name, position)

        return sequence

    # ----

    # HELPERS

    def _convertDataPoints(self, data, compression, precision="f", endian="<"):
        """Convert spectrum data points."""

        # convert from base64
        data = base64.b64decode(data)

        # decompress
        if compression:
            data = zlib.decompress(data)

        # convert form binary
        data = numpy.frombuffer(data[: (len(data) // struct.calcsize(endian + precision)) * struct.calcsize(endian + precision)], dtype=endian + precision)

        return data

    # ----

    def _getVersion(self):
        """Get mSD format version."""

        # mSD document
        mSDTags = self._parsedData.getElementsByTagName("mSD")
        if mSDTags:
            return mSDTags[0].getAttribute("version")

        # mMassDoc document
        mMassDocTags = self._parsedData.getElementsByTagName("mMassDoc")
        if mMassDocTags:
            return mMassDocTags[0].getAttribute("version")

    # ----

    def _getNodeText(self, node):
        """Get text from node list."""

        # get text
        buff = ""
        for child in node.childNodes:
            if child.nodeType == child.TEXT_NODE:
                buff += child.data

        # replace back some characters
        search = ("&amp;", "&quot;", "&#39;", "&lt;", "&gt;")
        replace = ("&", '"', "'", "<", ">")
        for x, item in enumerate(search):
            buff = buff.replace(item, replace[x])

        return buff

    # ----

    def _addMonomer(self, abbr, formula, losses=None, name="", category=""):
        """Add monomer to library."""

        # check data
        if not abbr or not formula or not re.match(r"^[A-Za-z0-9\-_]*$", abbr):
            return False

        # add new monomer
        try:
            monomer = mspy.monomer(
                abbr=abbr, formula=formula, losses=losses, name=name, category=category
            )
            mspy.monomers[abbr] = monomer
            mspy.saveMonomers(config.getLibraryPath("monomers"))
            return True
        except Exception:
            return False

    # ----

    def _addModification(self, name, gainFormula, lossFormula, aminoSpecifity=""):
        """Add modification to library."""

        # check data
        if not name or not (gainFormula or lossFormula):
            return False

        # add new modification
        try:
            modification = mspy.modification(
                name=name,
                gainFormula=gainFormula,
                lossFormula=lossFormula,
                aminoSpecifity=aminoSpecifity,
            )
            mspy.modifications[name] = modification
            mspy.saveModifications(config.getLibraryPath("modifications"))
            return True
        except Exception:
            return False

    # ----


# READING DOCUMENTS
# -----------------

# multiscan formats opened as a single browsable LC-MS run
RUN_FORMATS = ("mzXML", "mzData", "mzML")


def documentType(path):
    """Get the type of document at path, or False if it is not recognised.

    Besides the spectrum formats this recognises "FASTA" sequences and
    "session" files, which are opened by their own code paths.
    """

    # get filename and extension
    fileName = os.path.split(path)[1]
    extension = os.path.splitext(fileName)[1].lower()
    fileName = fileName.lower()

    # get document type by filename or extension
    if extension == ".msd":
        return "mSD"
    elif fileName == "fid":
        return "bruker"
    elif extension == ".mzdata":
        return "mzData"
    elif extension == ".mzxml":
        return "mzXML"
    elif extension == ".mzml":
        return "mzML"
    elif extension == ".mgf":
        return "MGF"
    elif extension in (".xy", ".txt", ".asc"):
        return "XY"
    elif extension in (".fa", ".fsa", ".faa", ".fasta"):
        return "FASTA"
    elif extension == session.SESSION_EXTENSION:
        return "session"

    # a Bruker flex dataset is a directory tree of fid files
    elif os.path.isdir(path):
        if mspy.findFIDs(path):
            return "bruker"

    # get document type for xml files
    if extension == ".xml":
        with open(path, "r", errors="replace") as document:
            data = document.read(500)
        if "<mzData" in data:
            return "mzData"
        elif "<mzXML" in data:
            return "mzXML"
        elif "<mzML" in data:
            return "mzML"

    # unknown document type
    return False


def makeScanParser(path, docType):
    """Make an mspy parser for a document holding several scans."""

    if docType == "mzData":
        return mspy.parseMZDATA(path)
    elif docType == "mzXML":
        return mspy.parseMZXML(path)
    elif docType == "mzML":
        return mspy.parseMZML(path)
    elif docType == "MGF":
        return mspy.parseMGF(path)
    elif docType == "bruker":
        return mspy.parseBruker(path)
    return None


def initialScanID(scanlist):
    """Pick the scan first shown when a run is opened (TIC apex MS1)."""

    best = None
    bestTIC = None
    firstMS1 = None
    for scanID, meta in scanlist.items():
        if meta.get("msLevel") not in (None, 1):
            continue
        if firstMS1 is None:
            firstMS1 = scanID
        tic = meta.get("totIonCurrent")
        if tic is not None and (bestTIC is None or tic > bestTIC):
            bestTIC = tic
            best = scanID

    if best is not None:
        return best
    if firstMS1 is not None:
        return firstMS1
    # no MS1 scans at all - use the first scan available
    return next(iter(scanlist), None)


def _applyInfo(document, info):
    """Copy the description a parser reads into a document."""

    if isinstance(info, dict):
        document.title = info["title"]
        document.operator = info["operator"]
        document.contact = info["contact"]
        document.institution = info["institution"]
        document.date = info["date"]
        document.instrument = info["instrument"]
        document.notes = info["notes"]


def _titleFromPath(path):
    """Make a document title from its file name."""

    dirName, fileName = os.path.split(path)
    baseName = os.path.splitext(fileName)[0]
    if baseName.lower() == "analysis":
        return os.path.split(dirName)[1]
    return baseName


def readDocument(path, docType, scan=None):
    """Read one spectrum document, or the given scan of a multiscan one.

    Returns the document, or None if it cannot be read. Nothing here touches
    the GUI, so it is safe to call from worker threads.
    """

    # get data data
    spectrum = False
    if docType == "mSD":
        return parseMSD(path).getDocument() or None
    elif docType == "XY":
        parser = mspy.parseXY(path)
        spectrum = parser.scan()
    else:
        parser = makeScanParser(path, docType)
        if parser is None:
            return None
        spectrum = parser.scan(scan)

    # a scan object is falsy without profile data (len() counts profile
    # points), yet a centroided scan is a perfectly good document
    if spectrum is None or spectrum is False:
        return None

    # init document
    docData = document()
    docData.format = docType
    docData.path = path
    docData.spectrum = spectrum

    # get info
    if isinstance(parser, mspy.parseBruker):
        # a Bruker path can hold many acquisitions, each with its own
        # operator, instrument and date - ask for this one's
        _applyInfo(docData, parser.info(scan))
    else:
        _applyInfo(docData, parser.info())

    # set date if empty
    if not docData.date:
        docData.date = time.ctime(os.path.getctime(path))

    # set title if empty
    if not docData.title:
        if docData.spectrum.title != "":
            docData.title = docData.spectrum.title
        else:
            docData.title = _titleFromPath(path)

    # add scan number to title - a Bruker title already names the dataset
    # and the spot, which identifies the acquisition better than its index
    # in the tree does
    if scan and docType != "bruker":
        docData.title += " [%s]" % scan

    return docData


def readRun(path, docType, scanlist):
    """Read a multiscan run as a browsable LC-MS document.

    Only the initially shown scan is loaded; the rest are read on demand from
    the scan source. Returns None if the run cannot be read.
    """

    parser = makeScanParser(path, docType)
    if parser is None:
        return None

    initialID = initialScanID(scanlist)
    if initialID is None:
        return None

    spectrum = parser.scan(initialID)
    if spectrum is None or spectrum is False:
        return None

    # init document
    docData = document()
    docData.format = docType
    docData.path = path
    docData.spectrum = spectrum

    # attach chromatogram / scan index
    docData.scanlist = scanlist
    docData.chromatograms = makeChromatograms(scanlist)
    docData.currentScanID = initialID
    docData.scanCache = {initialID: spectrum}
    docData.scanSource = (path, docType)

    # get info
    _applyInfo(docData, parser.info())

    # set date and title if empty
    if not docData.date:
        docData.date = time.ctime(os.path.getctime(path))
    if not docData.title:
        docData.title = _titleFromPath(path)

    return docData


# PEAK LIST TEXT
# --------------


def _envelopeValue(peak, key):
    envelope = peak.attributes.get("envelope")
    if isinstance(envelope, dict):
        return envelope.get(key)
    return None


# peak list columns in the order the GUI exports them: {name: (header, value)}
PEAKLIST_COLUMNS = {
    "mz": ("m/z", lambda peak: peak.mz),
    "ai": ("a.i.", lambda peak: peak.ai),
    "base": ("base", lambda peak: peak.base),
    "int": ("int", lambda peak: peak.intensity),
    "rel": ("r.int.", lambda peak: peak.ri * 100),
    "sn": ("s/n", lambda peak: peak.sn),
    "z": ("z", lambda peak: peak.charge),
    "mass": ("mass", lambda peak: peak.mass()),
    "fwhm": ("fwhm", lambda peak: peak.fwhm),
    "resol": ("resol.", lambda peak: peak.resolution),
    "envarea": ("env. area", lambda peak: _envelopeValue(peak, "area")),
    "envint": ("sum. env. int.", lambda peak: _envelopeValue(peak, "sumint")),
    "group": ("group", lambda peak: peak.group),
}


def peaklistText(peaklist, columns, separator="\t", headers=False):
    """Format a peak list as text, one peak per line.

    Columns are PEAKLIST_COLUMNS names, written in the order given; values a
    peak does not have are left empty.
    """

    lines = []
    if headers:
        lines.append(separator.join(PEAKLIST_COLUMNS[name][0] for name in columns))

    for peak in peaklist:
        values = (PEAKLIST_COLUMNS[name][1](peak) for name in columns)
        lines.append(
            separator.join("" if value is None else str(value) for value in values)
        )

    return "".join(line.rstrip() + "\n" for line in lines)


# REPORT
# ------

REPORT_HEADER = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">

<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
<head>
  <meta http-equiv="content-type" content="text/html; charset=utf-8" />
  <meta name="author" content="Created by mMass - Open Source Mass Spectrometry Tool; https://github.com/lukaszsobala/mMass" />
  <title>mMass Report</title>
  <style type="text/css">
  <!--
    body{margin: 5%; font-size: 8.5pt; font-family: Arial, Verdana, Geneva, Helvetica, sans-serif;}
    h1{font-size: 1.5em; text-align: center; margin: 1em 0; border-bottom: 3px double #000;}
    h1 span{font-style: italic;}
    h2{font-size: 1.2em; text-align: left; margin: 2em 0 1em 0; border-bottom: 1px solid #000;}
    h2 span{font-style: italic;}
    table{border-collapse: collapse; margin: 1.5em auto; width: 100%; background-color: #fff;}
    thead{display: table-header-group;}
    th,td{font-size: .75em; border: 1px solid #aaa; padding: .3em; vertical-align: top; text-align: left;}
    html>body th, html>body td{font-size: .9em;}
    th{text-align: center; color: #000; background-color: #ccc;}
    th a{text-align: center; color: #000; background-color: #ccc; text-decoration: none;}
    #tableMainInfo th{text-align: right; width: 15%;}
    #tableMainInfo td{text-align: left;}
    #spectrum{text-align: center;}
    #footer{font-size: .8em; font-style: italic; text-align: center; color: #aaa; margin: 2em 0 1em 0; padding-top: 0.5em; border-top: 1px solid #000;}
    .left{text-align: left;}
    .right{text-align: right;}
    .center{text-align: center;}
    .nowrap{white-space:nowrap;}
    .sequence{font-size: 1.1em; font-family: monospace;}
    .modified{color: #f00; font-weight: bold;}
    .matched{text-decoration: underline;}
  -->
  </style>
  <script type="text/javascript">
    // This script was adapted from the original script by Mike Hall (www.brainjar.com)
    //<![CDATA[

    // for IE
    if (document.ELEMENT_NODE == null) {
      document.ELEMENT_NODE = 1;
      document.TEXT_NODE = 3;
    }

    // sort table
    function sortTable(id, col) {

      // get table
      var tblEl = document.getElementById(id);

      // init sorter
      if (tblEl.reverseSort == null) {
        tblEl.reverseSort = new Array();
      }

      // reverse sorting
      if (col == tblEl.lastColumn) {
        tblEl.reverseSort[col] = !tblEl.reverseSort[col];
      }

      // remember current column
      tblEl.lastColumn = col;

      // sort table
      var tmpEl;
      var i, j;
      var minVal, minIdx;
      var testVal;
      var cmp;

      for (i = 0; i < tblEl.rows.length - 1; i++) {
        minIdx = i;
        minVal = getTextValue(tblEl.rows[i].cells[col]);

        // walk in other rows
        for (j = i + 1; j < tblEl.rows.length; j++) {
          testVal = getTextValue(tblEl.rows[j].cells[col]);
          cmp = compareValues(minVal, testVal);

          // reverse sorting
          if (tblEl.reverseSort[col]) {
            cmp = -cmp;
          }

          // set new minimum
          if (cmp > 0) {
            minIdx = j;
            minVal = testVal;
          }
        }

        // move row before
        if (minIdx > i) {
          tmpEl = tblEl.removeChild(tblEl.rows[minIdx]);
          tblEl.insertBefore(tmpEl, tblEl.rows[i]);
        }
      }

      return false;
    }

    // get node text
    function getTextValue(el) {
      var i;
      var s;

      // concatenate values of text nodes
      s = "";
      for (i = 0; i < el.childNodes.length; i++) {
        if (el.childNodes[i].nodeType == document.TEXT_NODE) {
          s += el.childNodes[i].nodeValue;
        } else if (el.childNodes[i].nodeType == document.ELEMENT_NODE && el.childNodes[i].tagName == "BR") {
          s += " ";
        } else {
          s += getTextValue(el.childNodes[i]);
        }
      }

      return s;
    }

    // compare values
    function compareValues(v1, v2) {
      var f1, f2;

      // lowercase values
      v1 = v1.toLowerCase()
      v2 = v2.toLowerCase()

      // try to convert values to floats
      f1 = parseFloat(v1);
      f2 = parseFloat(v2);
      if (!isNaN(f1) && !isNaN(f2)) {
        v1 = f1;
        v2 = f2;
      }

      // compare values
      if (v1 == v2) {
        return 0;
      } else if (v1 > v2) {
        return 1;
      } else {
        return -1;
      }
    }

    //]]>
  </script>
</head>

<body>
"""
