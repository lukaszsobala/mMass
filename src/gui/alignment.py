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
    ("group", "Group"),
    ("label", "Label"),
    ("theoretical", "Theoretical m/z"),
]

STAT_KEYS = [key for key, _label in STAT_COLUMNS]
PEAK_KEYS = [key for key, _label in PEAK_COLUMNS]

# defaults chosen to match the columns the alignment is usually read with
DEFAULT_STATS = ["median", "mean", "min", "max", "range", "count", "duplicate"]
DEFAULT_COLUMNS = ["mz", "int", "sn", "fwhm", "resol", "envarea", "envint"]

# how extra peaks a single document contributes to one group are written out
DUPLICATES_ROWS = "rows"
DUPLICATES_IGNORE = "ignore"

DUPLICATE_FLAG = "duplicate"


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


def peakValue(peak, column, mz=None):
    """One cell for a peak, or None where the peak cannot supply that column.

    ``mz`` is the value the alignment was done on, which is the theoretical m/z
    when comparing theoretical notations; passing it keeps the m/z column and
    the summary columns describing the same number.
    """

    if column == "mz":
        return mz if mz is not None else getattr(peak, "mz", None)

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


def _statValue(column, mzs, count, flag):
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


def buildAlignmentTable(
    groups,
    titles,
    statColumns=None,
    peakColumns=None,
    duplicates=DUPLICATES_ROWS,
):
    """Turn groups of matched peaks into one wide table.

    ``groups`` is a sequence of groups, each group a sequence of
    ``(documentIndex, mz, peak)`` for the peaks that were matched together.
    ``titles`` names every document, including any that contributed no peak at
    all -- those still get their block of (empty) columns, so all exports of a
    given set of documents have the same shape.

    Returns ``(header, rows)``; a cell no peak could supply is None.
    """

    statColumns = _selectColumns(
        DEFAULT_STATS if statColumns is None else statColumns, STAT_KEYS
    )
    peakColumns = _selectColumns(
        DEFAULT_COLUMNS if peakColumns is None else peakColumns, PEAK_KEYS
    )

    names = uniqueNames(titles)

    header = list(statColumns)
    for name in names:
        for column in peakColumns:
            header.append("%s_%s" % (name, column))

    def buildRow(entries, flag):
        """One output row from documentIndex -> (mz, peak)."""

        mzs = [mz for mz, _peak in entries.values()]

        row = [
            _statValue(column, mzs, len(entries), flag) for column in statColumns
        ]

        for index in range(len(names)):
            entry = entries.get(index)
            if entry is None:
                row.extend([None] * len(peakColumns))
                continue
            mz, peak = entry
            row.extend(peakValue(peak, column, mz=mz) for column in peakColumns)

        return row

    rows = []

    # an empty group has no m/z to sort or summarise by, and no row to write
    groups = [group for group in groups if group]

    for group in sorted(groups, key=lambda group: _mean([mz for _i, mz, _p in group])):

        # split the group by document: a document may well have put more than
        # one peak into it, and only one of them can hold that document's block
        byDocument = {}
        for index, mz, peak in group:
            byDocument.setdefault(index, []).append((mz, peak))

        primary = {}
        below = []
        above = []

        for index, entries in byDocument.items():

            best = max(entries, key=lambda entry: peakIntensity(entry[1]))
            primary[index] = best

            if duplicates != DUPLICATES_ROWS:
                continue

            for entry in entries:
                if entry is best:
                    continue
                # a duplicate keeps its place relative to the peak it doubles,
                # so that reading the table top to bottom is still reading it
                # in m/z order
                if entry[0] < best[0]:
                    below.append((index, entry))
                else:
                    above.append((index, entry))

        for index, entry in sorted(below, key=lambda item: item[1][0]):
            rows.append(buildRow({index: entry}, DUPLICATE_FLAG))

        rows.append(buildRow(primary, ""))

        for index, entry in sorted(above, key=lambda item: item[1][0]):
            rows.append(buildRow({index: entry}, DUPLICATE_FLAG))

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


def formatTable(header, rows, separator="\t", floatFormat=FLOAT_FORMAT):
    """The table as text, one line per row, header first."""

    lines = [
        separator.join(
            formatValue(value, floatFormat, separator) for value in header
        )
    ]

    for row in rows:
        lines.append(
            separator.join(
                formatValue(value, floatFormat, separator) for value in row
            )
        )

    return "\n".join(lines) + "\n"
