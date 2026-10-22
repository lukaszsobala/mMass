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

"""Aligned peak table shared by all documents in the Compare Peak Lists tool.

The comparison panel already groups peaks across documents; this module turns
those groups into one wide table -- a row per group, a fixed block of columns
per document -- which is the shape wanted for downstream statistics outside
mMass.

Deliberately free of wxPython and of gui.config so it can be unit tested
headlessly: everything it needs arrives as arguments.
"""

# ALIGNED PEAK TABLE
# ------------------


# Summary columns, in the order they are written. They describe the m/z of the
# peaks that ended up on the row, not the peaks' intensities, because the m/z
# spread is what tells the user whether a group is really one peak.
STAT_COLUMNS = [
    ("id", "Group ID"),
    ("median", "Median m/z"),
    ("mean", "Mean m/z"),
    ("min", "Lowest m/z"),
    ("max", "Highest m/z"),
    ("range", "Highest - lowest"),
    ("rangeppm", "Highest - lowest (ppm)"),
    ("count", "Documents in group"),
    ("duplicate", "Duplicate flag"),
]

# Per-document columns, in the order they are written inside each document
# block. A column a peak cannot supply (a notation has no s/n, a peak with no
# envelope has no envelope area) is left empty rather than zero, so an empty
# cell always means "not measured" and never "measured as nothing".
PEAK_COLUMNS = [
    ("mz", "m/z"),
    ("ppm", "m/z error vs group (ppm)"),
    ("ai", "a.i."),
    ("base", "Baseline"),
    ("int", "Intensity"),
    ("rel", "Relative intensity"),
    ("sn", "s/n"),
    ("z", "Charge"),
    ("mass", "Mass"),
    ("fwhm", "FWHM"),
    ("resol", "Resolution"),
    ("envarea", "Envelope area"),
    ("envint", "Envelope int. sum"),
    ("group", "Peak group"),
    ("label", "Label"),
    ("theoretical", "Theoretical m/z"),
]

STAT_KEYS = [key for key, _label in STAT_COLUMNS]
PEAK_KEYS = [key for key, _label in PEAK_COLUMNS]

STAT_LABELS = dict(STAT_COLUMNS)
PEAK_LABELS = dict(PEAK_COLUMNS)

# defaults chosen to match the columns the alignment is usually read with
DEFAULT_STATS = ["id", "median", "mean", "min", "max", "range", "count", "duplicate"]
DEFAULT_COLUMNS = ["mz", "ppm", "int", "sn", "fwhm", "resol", "envarea", "envint"]

# how extra peaks a single document contributes to one group are handled:
# on rows of their own, dropped (only the most intense stays), or added up
# into the one peak that represents the document
DUPLICATES_ROWS = "rows"
DUPLICATES_IGNORE = "ignore"
DUPLICATES_SUM = "sum"

# columns that make sense to add up when several peaks stand in for one;
# everything else (m/z, s/n, width...) is taken from the most intense peak
ADDITIVE_COLUMNS = ("ai", "base", "int", "rel", "envarea", "envint")

DUPLICATE_FLAG = "duplicate"

# how the table is laid out:
#   document -- a block of columns per document: A_mz A_int B_mz B_int
#   column   -- a block of documents per column: mz_A mz_B int_A int_B
#   long     -- one row per peak, with a Document column; the shape that
#               R/pandas want for plotting and statistics
LAYOUT_DOCUMENT = "document"
LAYOUT_COLUMN = "column"
LAYOUT_LONG = "long"

DOCUMENT_COLUMN = "Document"

# separates a document's name from a column's name in a header; neither is
# likely to contain it, and it reads the same whichever comes first
NAME_SEPARATOR = " | "


def peakIntensity(peak):
    """How intense a peak counts as, for picking one peak out of several.

    Envelope area first: where a peak carries a fitted envelope, the area is
    the measure of the whole isotopic distribution, and comparing an envelope's
    monoisotopic a.i. against a plain peak's a.i. would be comparing a part
    against a whole.
    """

    envelope = getattr(peak, "attributes", None)
    if envelope:
        envelope = envelope.get("envelope")
        if envelope:
            area = envelope.get("area")
            if area and area > 0:
                return float(area)

    ai = getattr(peak, "ai", 0.0) or 0.0
    base = getattr(peak, "base", 0.0) or 0.0

    return max(0.0, float(ai) - float(base))


def _envelope(peak):
    """Envelope dict of a peak, or an empty one for anything without."""

    attributes = getattr(peak, "attributes", None)
    if not attributes:
        return {}

    return attributes.get("envelope") or {}


def peakValue(peak, column, mz=None, reference=None):
    """One cell for a peak, or None where the peak cannot supply that column.

    ``mz`` is the value the alignment was done on, which is the theoretical m/z
    when comparing theoretical notations; passing it keeps the m/z column and
    the summary columns describing the same number. ``reference`` is the m/z
    of the whole group, which the ppm error is measured against.
    """

    if column == "mz":
        return mz if mz is not None else getattr(peak, "mz", None)

    if column == "ppm":
        if mz is None:
            mz = getattr(peak, "mz", None)
        if mz is None or not reference:
            return None
        return (mz - reference) / reference * 1e6

    if column == "ai":
        return getattr(peak, "ai", None)

    if column == "base":
        return getattr(peak, "base", None)

    if column == "int":
        intensity = getattr(peak, "intensity", None)
        if intensity is not None:
            return intensity
        ai = getattr(peak, "ai", None)
        if ai is None:
            return None
        return ai - (getattr(peak, "base", 0.0) or 0.0)

    if column == "rel":
        ri = getattr(peak, "ri", None)
        return None if ri is None else ri * 100

    if column == "sn":
        return getattr(peak, "sn", None)

    if column == "z":
        return getattr(peak, "charge", None)

    if column == "mass":
        mass = getattr(peak, "mass", None)
        if not callable(mass):
            return None
        return mass()

    if column == "fwhm":
        return getattr(peak, "fwhm", None)

    if column == "resol":
        return getattr(peak, "resolution", None)

    if column == "envarea":
        return _envelope(peak).get("area")

    if column == "envint":
        return _envelope(peak).get("sumint")

    if column == "group":
        return getattr(peak, "group", None) or None

    if column == "label":
        return getattr(peak, "label", None) or None

    if column == "theoretical":
        return getattr(peak, "theoretical", None)

    return None


def uniqueNames(titles, fallback="document"):
    """Column-name stem per document, distinct even when two share a title.

    Two documents with the same title would otherwise produce two identical
    blocks of column names, which silently ruins the table for whoever reads it
    by name.
    """

    names = []
    used = {}

    for index, title in enumerate(titles):

        name = "".join(
            " " if character in "\t\r\n" else character
            for character in str(title or "")
        ).strip()

        if not name:
            name = "%s%d" % (fallback, index + 1)

        count = used.get(name, 0)
        used[name] = count + 1
        if count:
            name = "%s(%d)" % (name, count + 1)

        names.append(name)

    return names


def _median(values):
    """Median without pulling in a dependency for one number."""

    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2

    if count % 2:
        return ordered[middle]

    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _mean(values):
    return sum(values) / float(len(values))


def _statValue(column, mzs, count, flag, groupId):
    """One summary cell for a row built from the given m/z values."""

    if column == "median":
        return _median(mzs)
    if column == "mean":
        return _mean(mzs)
    if column == "min":
        return min(mzs)
    if column == "max":
        return max(mzs)
    if column == "range":
        return max(mzs) - min(mzs)
    if column == "rangeppm":
        mean = _mean(mzs)
        if not mean:
            return None
        return (max(mzs) - min(mzs)) / mean * 1e6
    if column == "count":
        return count
    if column == "id":
        return groupId
    if column == "duplicate":
        return flag

    return None


def _selectColumns(requested, canonical):
    """Requested columns, reduced to known ones and put in canonical order.

    The order of the table must not depend on the order the caller happens to
    tick the boxes in, or two exports of the same data would not line up.
    """

    requested = set(requested or [])

    return [key for key in canonical if key in requested]


def _splitByDocument(group, duplicates):
    """Peaks of one group by document: {index: (best, extras)}.

    Each peak travels as ``(mz, peak, members)``, ``members`` being the peaks
    it stands for -- more than itself only when duplicates are added up. A
    document may well have put several peaks into one group, and only the most
    intense can hold that document's place in the row.
    """

    byDocument = {}
    for index, mz, peak in group:
        byDocument.setdefault(index, []).append((mz, peak))

    result = {}

    for index, entries in byDocument.items():

        best = max(entries, key=lambda entry: peakIntensity(entry[1]))

        if duplicates == DUPLICATES_SUM:
            result[index] = ((best[0], best[1], [peak for _mz, peak in entries]), [])
            continue

        extras = []
        if duplicates == DUPLICATES_ROWS:
            extras = [
                (entry[0], entry[1], [entry[1]])
                for entry in entries
                if entry is not best
            ]

        result[index] = ((best[0], best[1], [best[1]]), extras)

    return result


def _cell(entry, column, reference):
    """One cell for a (mz, peak, members) entry."""

    mz, peak, members = entry

    if len(members) > 1 and column in ADDITIVE_COLUMNS:
        values = [peakValue(member, column) for member in members]
        values = [value for value in values if value is not None]
        return sum(values) if values else None

    return peakValue(peak, column, mz=mz, reference=reference)


def firstGroups(groups, count):
    """The ``count`` lowest-m/z groups, for a preview that need not build it all.

    They are the groups that would come first in the table, so a table built
    from them is that table's top, numbered the same way.
    """

    groups = [group for group in groups if group]

    def meanMz(group):
        return _mean([mz for _index, mz, _peak in group])

    return sorted(groups, key=meanMz)[:count]


def buildAlignmentTable(
    groups,
    titles,
    statColumns=None,
    peakColumns=None,
    duplicates=DUPLICATES_ROWS,
    layout=LAYOUT_DOCUMENT,
    twoRowHeader=False,
):
    """Turn groups of matched peaks into one table.

    ``groups`` is a sequence of groups, each group a sequence of
    ``(documentIndex, mz, peak)`` for the peaks that were matched together.
    ``titles`` names every document, including any that contributed no peak at
    all -- in the wide layouts those still get their (empty) columns, so all
    exports of a given set of documents have the same shape.

    Every group is numbered (``id`` summary column) in m/z order; the extra
    rows a duplicate peak gets carry the number of the group it belongs to.
    The ppm error of a peak is measured against the median m/z of the peaks
    that represent the group, so a duplicate shows how far it lies from where
    the group sits, not from itself.

    Returns ``(header, rows)``; a cell no peak could supply is None. In the
    long layout there is a row per peak and a document without a peak in a
    group has no row for it.

    ``header`` is one list of names. With ``twoRowHeader`` the wide layouts
    split every name over two rows instead -- the document above, the column
    below, in either wide layout, the summary columns having only the lower --
    and ``header`` is then a list of those two lists. Spelled out on every
    cell, not merged, so each column still says what it is on its own. The
    long layout has one header either way, there being a Document column
    instead.
    """

    statColumns = _selectColumns(
        DEFAULT_STATS if statColumns is None else statColumns, STAT_KEYS
    )
    peakColumns = _selectColumns(
        DEFAULT_COLUMNS if peakColumns is None else peakColumns, PEAK_KEYS
    )

    long = layout == LAYOUT_LONG
    names = uniqueNames(titles)

    if long:
        # a long table is of no use without telling which group a row is in
        statColumns = ["id"] + [key for key in statColumns if key != "id"]

    peakLabels = [PEAK_LABELS[key] for key in peakColumns]

    # header: the (upper, lower) pair of every column, the upper being the
    # document it belongs to
    columnNames = [("", STAT_LABELS[key]) for key in statColumns]

    if long:
        columnNames.insert(1, ("", DOCUMENT_COLUMN))
        columnNames.extend(("", label) for label in peakLabels)
    elif layout == LAYOUT_COLUMN:
        for label in peakLabels:
            for name in names:
                columnNames.append((name, label))
    else:
        for name in names:
            for label in peakLabels:
                columnNames.append((name, label))

    def flatName(upper, lower):
        return upper + NAME_SEPARATOR + lower if upper else lower

    if twoRowHeader and not long:
        header = [
            [upper for upper, _lower in columnNames],
            [lower for _upper, lower in columnNames],
        ]
    else:
        header = [flatName(upper, lower) for upper, lower in columnNames]

    def statCells(entries, count, flag, number, skip=()):
        mzs = [entry[0] for entry in entries]
        return [
            _statValue(key, mzs, count, flag, number)
            for key in statColumns
            if key not in skip
        ]

    def peakCells(entry, reference):
        return [_cell(entry, key, reference) for key in peakColumns]

    def wideRow(byDocument, flag, number, reference):
        """One output row from documentIndex -> entry."""

        row = statCells(list(byDocument.values()), len(byDocument), flag, number)

        blocks = [
            peakCells(byDocument[index], reference)
            if index in byDocument
            else [None] * len(peakColumns)
            for index in range(len(names))
        ]

        if layout == LAYOUT_COLUMN:
            for column in range(len(peakColumns)):
                row.extend(block[column] for block in blocks)
        else:
            for block in blocks:
                row.extend(block)

        return row

    rows = []

    # an empty group has no m/z to sort or summarise by, and no row to write
    groups = [group for group in groups if group]

    def meanMz(group):
        return _mean([mz for _index, mz, _peak in group])

    for number, group in enumerate(sorted(groups, key=meanMz), 1):

        byDocument = _splitByDocument(group, duplicates)

        primary = {index: best for index, (best, _extras) in byDocument.items()}
        reference = _median([entry[0] for entry in primary.values()])

        if long:

            for index in sorted(byDocument):

                best, extras = byDocument[index]
                entries = [(best, "")] + [(extra, DUPLICATE_FLAG) for extra in extras]

                for entry, flag in sorted(entries, key=lambda item: item[0][0]):
                    # the summary describes the group, so it is the same on
                    # every row of it; only the duplicate flag is the peak's
                    row = statCells(
                        list(primary.values()), len(primary), flag, number, ("id",)
                    )
                    rows.append(
                        [number, names[index]] + row + peakCells(entry, reference)
                    )

            continue

        below = []
        above = []

        for index, (best, extras) in byDocument.items():
            for extra in extras:
                # a duplicate keeps its place relative to the peak it doubles,
                # so that reading the table top to bottom is still reading it
                # in m/z order
                if extra[0] < best[0]:
                    below.append((index, extra))
                else:
                    above.append((index, extra))

        for index, entry in sorted(below, key=lambda item: item[1][0]):
            rows.append(wideRow({index: entry}, DUPLICATE_FLAG, number, reference))

        rows.append(wideRow(primary, "", number, reference))

        for index, entry in sorted(above, key=lambda item: item[1][0]):
            rows.append(wideRow({index: entry}, DUPLICATE_FLAG, number, reference))

    return header, rows


# 12 significant digits: still far past what any instrument resolves, but short
# enough that the binary noise of a subtraction (a 0.1 spread coming out as
# 0.0999999999999943) does not reach the page
FLOAT_FORMAT = "%.12g"


def formatValue(value, floatFormat=FLOAT_FORMAT, separator="\t"):
    """One cell as text, with anything that would break the table taken out."""

    if value is None:
        return ""

    if isinstance(value, bool):
        return "1" if value else "0"

    if isinstance(value, float):
        return floatFormat % value

    if isinstance(value, int):
        return "%d" % value

    text = str(value)
    for character in (separator, "\t", "\r", "\n"):
        text = text.replace(character, " ")

    return text


def headerRows(header):
    """The header as a list of rows, whether it is one row or several."""

    if header and isinstance(header[0], (list, tuple)):
        return [list(row) for row in header]

    return [list(header)]


def formatTable(header, rows, separator="\t", floatFormat=FLOAT_FORMAT):
    """The table as text, one line per row, header first."""

    lines = [
        separator.join(
            formatValue(value, floatFormat, separator) for value in row
        )
        for row in headerRows(header)
    ]

    for row in rows:
        lines.append(
            separator.join(
                formatValue(value, floatFormat, separator) for value in row
            )
        )

    return "\n".join(lines) + "\n"
