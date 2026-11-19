"""Group spectra by similarity without the GUI (mmass cluster).

Documents are read with the same code the GUI opens them with (gui.doc);
the similarity and the groups come from mspy (mod_similarity, mod_grouping).
Results are written as CSV tables, Newick trees and a Markdown report; no
figures (they need the GUI's drawing code).

Nothing here may assign to gui.config.
"""

import csv
import datetime
import os
import sys

import numpy

import mspy
from mmass_app import cli

shown = cli.shown_path
COMMAND = cli.CLUSTER_COMMAND


class InputError(Exception):
    """An input that cannot be used."""


def error(message):
    print(f"mmass {COMMAND}: error: {message}", file=sys.stderr)


# READING
# -------


class Item:
    """One spectrum to group."""

    def __init__(self, scan, title, path):
        self.scan = scan
        self.title = title
        self.path = path
        self.label = title


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
            return [
                Item(document.scanCache[scanID], f"{document.title} [{scanID}]", path)
            ]
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
        if scanID is not None and len(scanIDs) > 1 and docType != "bruker":
            title = f"{title} [{scanID}]"
        items.append(Item(document.spectrum, title, path))
    return items


def unique_labels(items):
    """Give spectra of the same title distinct labels: the nearest folder
    level at which their paths differ, then a number."""

    titles = [item.title for item in items]
    for title in {t for t in titles if titles.count(t) > 1}:
        same = [item for item in items if item.title == title]
        parts = [os.path.dirname(item.path).split(os.sep)[::-1] for item in same]
        for level in range(max(len(p) for p in parts)):
            names = [p[level] if level < len(p) else "" for p in parts]
            if len(set(names)) > 1:
                for item, name in zip(same, names, strict=True):
                    if name:
                        item.label = f"{item.title} ({name})"
                break
    labels = [item.label for item in items]
    duplicated = {t for t in labels if labels.count(t) > 1}
    counter = {}
    for item in items:
        if item.label in duplicated:
            counter[item.label] = counter.get(item.label, 0) + 1
            item.label = f"{item.label} #{counter[item.label]}"


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
            else:
                items += read_input(path)
        except InputError as exc:
            error(f"{shown(path)}: {exc}")
            failed += 1
        except Exception as exc:
            error(f"{shown(path)}: it cannot be read: {exc!r}")
            failed += 1
    return items, failed


# WRITING
# -------


def _number(value, digits=4):
    return "" if value is None or not numpy.isfinite(value) else f"{value:.{digits}f}"


def write_matrix(path, labels, M):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([""] + labels)
        for label, row in zip(labels, M, strict=True):
            writer.writerow([label] + [_number(v) for v in row])


POLARITY = {1: "positive", -1: "negative", None: ""}


def group_rows(items, sim, grp):
    """Rows of groups.csv, in display order."""

    S = sim.similarity
    n = len(items)
    rows = []
    for i in grp.order:
        members = [j for j in range(n) if grp.groups[j] == grp.groups[i] and j != i]
        together = ""
        if grp.coMembership is not None and members:
            together = _number(float(numpy.mean(grp.coMembership[i, members])), 2)
        others = [j for j in range(n) if j != i and numpy.isfinite(S[i, j])]
        nearest = max(others, key=lambda j: S[i, j]) if others else None
        scan = items[i].scan
        rows.append(
            [
                grp.groups[i],
                items[i].label,
                POLARITY.get(scan.polarity, ""),
                _number(scan.precursorMZ) if scan.precursorMZ else "",
                together,
                items[nearest].label if nearest is not None else "",
                _number(S[i, nearest], 3) if nearest is not None else "",
                items[i].path,
            ]
        )
    return rows


def _features_table(feats, axis):
    rows = feats[axis]
    if not rows:
        return []
    head = "m/z" if axis == "mz" else "loss (Da)"
    lines = [
        f"| {head} | members with signal | others with signal | note |",
        "|---|---|---|---|",
    ]
    for f in rows:
        pos = f["positions"]
        text = f"{f['position']:.2f}"
        if len(pos) > 1:
            text += f" ({pos[0]:.2f}–{pos[-1]:.2f}, {len(pos)} peaks)"
        others = "—" if f["others"] is None else f"{f['others']}/{f['othersCovered']}"
        note = f"= m/z {f['mirror']:.2f} above" if f.get("mirror") is not None else ""
        lines.append(f"| {text} | {f['members']}/{f['covered']} | {others} | {note} |")
    return lines + [""]


def report(items, sim, grp, options, failed):
    """The Markdown report."""

    n = len(items)
    S = sim.similarity
    g = options.grouping
    s = options.similarity
    lines = [
        "# Spectrum groups",
        "",
        f"mmass {COMMAND}, {datetime.datetime.now():%Y-%m-%d %H:%M}. "
        f"{n} spectra"
        + (f"; {failed} input(s) could not be used" if failed else "")
        + ".",
        "",
    ]
    if g["method"] == "network":
        thresholds = sorted({round(t, 3) for t in grp.threshold if t is not None})
        lines.append(
            "Groups are communities of a spectral network: an edge joins two spectra "
            f"whose corrected similarity is at least {', '.join(f'{t:g}' for t in thresholds) or '—'} "
            f"and that are among each other's {g['topK']} most similar."
        )
    else:
        lines.append(f"Groups are the tree cut at corrected similarity {g['cut']:g}.")
    lines += [
        "",
        "Corrected similarity: 1 = identical, 0 = as alike as chance for the m/z "
        "range and peak density of the pair. Settings: "
        + ", ".join(f"{k} {v}" for k, v in s.items())
        + ".",
        "",
    ]
    if not sim.comparable.all():
        lines += [
            "Spectra of different polarity were not compared (use --neutral-mass "
            "to compare them on neutral mass); each polarity has its own tree.",
            "",
        ]
    rho, rhoApart = mspy.rangedependence(sim)
    lines += [
        "Range dependence (Spearman rho of pair similarity against the ratio of the "
        "spectra's m/z ranges; 0 = none, negative = spectra of similar range look "
        f"more alike): {_number(rho, 2) or '—'} for all pairs, "
        f"{_number(rhoApart, 2) or '—'} for pairs whose ranges differ by more than 10 Da.",
        "",
    ]
    if grp.stability is not None:
        lines += [
            f"Bootstrap: {g['replicates']} replicates. The grouping agrees with the "
            f"replicates' groupings at a mean adjusted Rand index of {grp.stability:.2f} "
            "(1 = always the same). For each group, 'together' is the share of "
            "replicates in which two members fall in one group.",
            "",
        ]

    singles = []
    # groups are numbered in display order
    for c in sorted(set(grp.groups.tolist())):
        members = [i for i in grp.order if grp.groups[i] == c]
        if len(members) == 1:
            singles.append(members[0])
            continue
        within = [S[a, b] for a in members for b in members if a < b]
        head = f"## Group {c} ({len(members)} spectra, mean similarity {numpy.nanmean(within):.2f}"
        if grp.coMembership is not None:
            pairs = [grp.coMembership[a, b] for a in members for b in members if a < b]
            head += f"; together in {100 * numpy.mean(pairs):.0f}% of replicates, weakest pair {100 * min(pairs):.0f}%"
        lines += [head + ")", ""]
        for i in members:
            extra = ""
            if grp.coMembership is not None:
                others = [j for j in members if j != i]
                extra = f" — together with the others in {100 * numpy.mean(grp.coMembership[i, others]):.0f}%"
            lines.append(f"- {items[i].label}{extra}")
        lines.append("")
        feats = mspy.sharedfeatures(sim, members)
        if feats["mz"] or feats["loss"]:
            lines += [
                "Shared signals (members with signal / members covering the position; "
                "others likewise):",
                "",
            ]
            lines += _features_table(feats, "mz")
            lines += _features_table(feats, "loss")
    if singles:
        lines += (
            ["## Not grouped", ""] + [f"- {items[i].label}" for i in singles] + [""]
        )
    lines += [
        "## Files",
        "",
        "- groups.csv: group, polarity, precursor, 'together', nearest spectrum",
        "- similarity.csv: corrected similarity (empty where not compared)",
        "- similarity_cosine.csv: shared-range cosine before the chance correction",
        "- co_membership.csv: share of bootstrap replicates in one group",
        "- trees.nwk: average-linkage trees (one per line, one per polarity), "
        "bootstrap support at the inner nodes",
        "",
    ]
    return "\n".join(lines)


def outputs_in_the_way(options):
    return [
        name
        for name in cli.CLUSTER_OUTPUTS
        if os.path.exists(os.path.join(options.outputDir, name))
    ]


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
        sim = mspy.similaritymatrix(scans, **options.similarity)
    except ValueError as exc:
        error(str(exc))
        return 1
    grp = mspy.groupspectra(sim, **options.grouping)
    labels = [item.label for item in items]

    os.makedirs(options.outputDir, exist_ok=True)
    out = options.outputDir
    write_matrix(os.path.join(out, "similarity.csv"), labels, sim.similarity)
    write_matrix(os.path.join(out, "similarity_cosine.csv"), labels, sim.cosine)
    path = os.path.join(out, "co_membership.csv")
    if grp.coMembership is not None:
        write_matrix(path, labels, grp.coMembership)
    elif os.path.exists(path):
        os.remove(path)  # a stale table from an earlier run would mislead
    with open(os.path.join(out, "groups.csv"), "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "group",
                "spectrum",
                "polarity",
                "precursor",
                "together",
                "nearest",
                "nearest_similarity",
                "file",
            ]
        )
        writer.writerows(group_rows(items, sim, grp))
    with open(os.path.join(out, "trees.nwk"), "w", encoding="utf-8") as fh:
        for comp, Z, support in grp.trees:
            if len(comp) > 1:
                fh.write(mspy.newick(Z, [labels[i] for i in comp], support) + "\n")
    with open(os.path.join(out, "REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write(report(items, sim, grp, options, failed))

    sizes = numpy.bincount(grp.groups)
    multi = int((sizes > 1).sum())
    print(
        f"{len(items)} spectra: {multi} group(s) of more than one, "
        f"{int((sizes == 1).sum())} ungrouped -> {shown(out)}"
    )
    return 1 if failed else 0
