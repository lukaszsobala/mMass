"""Group spectra by similarity without the GUI (mmass cluster).

Documents are read with the same code the GUI opens them with (gui.doc);
the similarity and the groups come from mspy (mod_similarity, mod_grouping).
Results are written as CSV tables, Newick trees and a Markdown report; no
figures (they need the GUI's drawing code).

Nothing here may assign to gui.config.
"""

import os
import sys

import numpy

import mspy
from gui import similarity_results as results
from gui.similarity_results import Item, unique_labels
from mmass_app import cli

shown = cli.shown_path
COMMAND = cli.CLUSTER_COMMAND


class InputError(Exception):
    """An input that cannot be used."""


def error(message):
    print(f"mmass {COMMAND}: error: {message}", file=sys.stderr)


# READING
# -------


def _session_documents(path, includeHidden):
    """(path, scanID) of the documents a session lists."""

    from gui import session

    try:
        data = session.parseSession(path)
    except (OSError, ValueError) as exc:
        raise InputError(f"the session cannot be read ({exc})") from None
    folder = os.path.dirname(path)
    out, missing, hidden = [], [], 0
    for entry in data["documents"]:
        if not entry["visible"] and not includeHidden:
            hidden += 1
            continue
        found = session.resolveDocumentPath(entry["path"], folder)
        if found is None:
            missing.append(entry["path"])
            continue
        out.append((found, entry["scan"]))
    if hidden:
        cli.warn(
            f"{shown(path)}: {hidden} hidden document(s) left out (--include-hidden uses them)",
            f"mmass {COMMAND}",
        )
    return out, missing


def _scan_key(scanlist, scanArg):
    for scanID in scanlist:
        if str(scanID) == str(scanArg):
            return scanID
    raise InputError(f"it has no scan {scanArg}")


def read_input(path, scanArg=None):
    """The spectra an input contributes, as Items."""

    from gui import doc

    docType = doc.documentType(path)
    if docType == "FASTA":
        raise InputError("a FASTA file holds sequences, not spectra")
    if not docType:
        if os.path.isdir(path):
            raise InputError("no Bruker fid data found in this folder")
        raise InputError("the document format is not recognised")
    unreadable = InputError("the document is damaged or contains no data")

    if docType in ("mSD", "XY"):
        document = doc.readDocument(path, docType)
        if document is None:
            raise unreadable
        if document.islcms():
            if scanArg is None:
                raise InputError(
                    "it is an LC-MS run; name one of its scans through a session, "
                    "clustering a whole run is not supported"
                )
            scanID = _scan_key(document.scanCache or document.scanlist, scanArg)
            if document.currentScanID is not None:
                document.scanCache[document.currentScanID] = document.spectrum
            if scanID not in document.scanCache:
                raise InputError(f"scan {scanID} was not saved in it")
            _check_data(document.scanCache[scanID])
            return [
                Item(document.scanCache[scanID], f"{document.title} [{scanID}]", path)
            ]
        _check_data(document.spectrum)
        return [Item(document.spectrum, document.title, path)]

    parser = doc.makeScanParser(path, docType)
    if parser is None:
        raise unreadable
    scanlist = parser.scanlist()
    if not isinstance(scanlist, dict) or not scanlist:
        raise unreadable

    if scanArg is not None:
        scanIDs = [_scan_key(scanlist, scanArg)]
    elif len(scanlist) == 1:
        scanIDs = [None]
    elif docType in doc.RUN_FORMATS:
        raise InputError(
            f"it is an LC-MS run of {len(scanlist)} scans; name one through a "
            "session, clustering a whole run is not supported"
        )
    else:
        scanIDs = list(scanlist)

    items = []
    for scanID in scanIDs:
        document = doc.readDocument(path, docType, scanID)
        if document is None:
            raise InputError(
                f"scan {scanID} cannot be read"
                if scanID is not None
                else "the document cannot be read"
            )
        title = document.title or os.path.splitext(os.path.basename(path))[0]
        # the reader names the scan itself, except scan 0 and Bruker data
        if (
            scanID is not None
            and len(scanIDs) > 1
            and docType != "bruker"
            and not title.endswith(f" [{scanID}]")
        ):
            title = f"{title} [{scanID}]"
        items.append(Item(document.spectrum, title, path))
    for item in items:
        _check_data(item.scan, len(items) > 1 and item.title)
    return items


def _check_data(scan, name=None):
    """Refuse a spectrum with neither profile nor peaks: it would score as
    unlike everything instead of being reported."""

    hasProfile = scan.profile is not None and len(scan.profile) > 0
    if not hasProfile and not len(scan.peaklist):
        where = f" ({name})" if name else ""
        raise InputError(f"the spectrum{where} contains no data points or peaks")


def collect(options):
    """Read every input; return (items, failed inputs)."""

    items, failed = [], 0
    for path in options.inputs:
        try:
            if path.lower().endswith(cli.SESSION_EXTENSION):
                documents, missing = _session_documents(path, options.includeHidden)
                for gone in missing:
                    error(f"{shown(path)}: {gone} cannot be found")
                    failed += 1
                for docPath, scanArg in documents:
                    try:
                        items += read_input(docPath, scanArg)
                    except InputError as exc:
                        error(f"{shown(docPath)}: {exc}")
                        failed += 1
                    except Exception as exc:
                        # one unreadable document must not stop the rest
                        error(f"{shown(docPath)}: it cannot be read: {exc!r}")
                        failed += 1
            else:
                items += read_input(path)
        except InputError as exc:
            error(f"{shown(path)}: {exc}")
            failed += 1
        except Exception as exc:
            error(f"{shown(path)}: it cannot be read: {exc!r}")
            failed += 1
    return items, failed


def outputs_in_the_way(options):
    return results.outputs_in_the_way(options.outputDir)


# RUN
# ---


def run(options):
    """Group the inputs' spectra and write the results; return the exit status."""

    if not options.overwrite:
        existing = outputs_in_the_way(options)
        if existing:
            error(
                f"{shown(options.outputDir)} already holds {', '.join(existing)} "
                "(use --overwrite to replace them)"
            )
            return 2

    items, failed = collect(options)
    if len(items) < 2:
        error(f"{len(items)} spectra could be read; at least two are needed")
        return 1
    unique_labels(items)
    scans = []
    for item in items:
        item.scan.title = item.label
        scans.append(item.scan)

    try:
        sim = mspy.similaritymatrix(
            scans,
            blocks=options.grouping["replicates"] > 0,  # only the bootstrap needs them
            **options.similarity,
        )
    except ValueError as exc:
        error(str(exc))
        return 1
    grp = mspy.groupspectra(sim, **options.grouping)
    out = options.outputDir
    results.write_results(
        out,
        items,
        sim,
        grp,
        options.similarity,
        options.grouping,
        failed,
        source=f"mmass {COMMAND}",
    )

    sizes = numpy.bincount(grp.groups)
    multi = int((sizes > 1).sum())
    print(
        f"{len(items)} spectra: {multi} group(s) of more than one, "
        f"{int((sizes == 1).sum())} ungrouped -> {shown(out)}"
    )
    return 1 if failed else 0
