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

"""Mass difference lists shared by the difference ruler and Peak Differences.

A list is a named group of (name, monoisotopic mass, average mass) entries.
The built-in ones are made from mspy's own data; the user's own lists live in
the "differences" library (libs.differences), edited under Libraries.
"""

# load libs
import mspy

# BUILT-IN LISTS
# --------------

AMINOACIDS = "Amino acids"
DIPEPTIDES = "Dipeptides"
SUGARS = "Sugars"
PERMESUGARS = "PerMe-Sugars"

BUILTIN = (AMINOACIDS, DIPEPTIDES, SUGARS, PERMESUGARS)

# elemental formulas of residue (glycosidic) masses
SUGAR_FORMULAS = {
    "Hex": "C6H10O5",
    "dHex": "C6H10O4",
    "HexNAc": "C8H13NO5",
    "NeuAc": "C11H17NO8",
    "NeuGc": "C11H17NO9",
    "KDN": "C9H14O8",
    "HexA": "C6H8O6",
    "HexN": "C6H11NO4",
    "Pent": "C5H8O4",
}
PERMESUGAR_FORMULAS = {
    "Hex-PM": "C9H16O5",
    "dHex-PM": "C8H14O4",
    "HexNAc-PM": "C11H19NO5",
    "NeuAc-PM": "C16H27NO8",
    "NeuGc-PM": "C17H29NO9",
    "KDN-PM": "C14H24O8",
    "HexA-PM": "C9H14O6",
    "Pent-PM": "C7H12O4",
}

# The built-in lists depend on the monomer library, which the user can edit,
# so they are cached only until invalidate() is called after a library edit.
_builtinCache = None


def massPair(mass):
    """Normalize a mass into a (mono, avg) tuple."""

    if isinstance(mass, (tuple, list)) and len(mass) >= 2:
        return (float(mass[0]), float(mass[1]))
    if isinstance(mass, (tuple, list)) and len(mass) == 1:
        value = float(mass[0])
        return (value, value)
    if isinstance(mass, (tuple, list)) or mass is None:
        return (0.0, 0.0)
    value = float(mass)
    return (value, value)


def aminoacidMasses():
    """{abbr: (mono, avg)} of the standard amino acid residues."""

    masses = {}
    for abbr in mspy.monomers:
        if mspy.monomers[abbr].category == "_InternalAA":
            masses[abbr] = massPair(mspy.monomers[abbr].mass)
    return masses


def dipeptideMasses(aminoacids=None):
    """{label: (mono, avg)} of every amino acid pair, AB and BA merged."""

    if aminoacids is None:
        aminoacids = aminoacidMasses()

    masses = {}
    abbrs = list(aminoacids)
    for x in range(len(abbrs)):
        for y in range(x, len(abbrs)):
            aX = abbrs[x]
            aY = abbrs[y]
            massX = aminoacids[aX]
            massY = aminoacids[aY]
            if aX != aY:
                label = "%s%s/%s%s" % (aX, aY, aY, aX)
            else:
                label = aX + aY
            masses[label] = (massX[0] + massY[0], massX[1] + massY[1])

    return masses


def formulaMasses(formulas):
    """{name: (mono, avg)} for a {name: formula} map."""

    return {
        name: massPair(mspy.compound(formula).mass())
        for name, formula in formulas.items()
    }


def builtinLists():
    """{list name: {entry name: (mono, avg)}} of the built-in lists."""

    global _builtinCache
    if _builtinCache is None:
        aminoacids = aminoacidMasses()
        _builtinCache = {
            AMINOACIDS: aminoacids,
            DIPEPTIDES: dipeptideMasses(aminoacids),
            SUGARS: formulaMasses(SUGAR_FORMULAS),
            PERMESUGARS: formulaMasses(PERMESUGAR_FORMULAS),
        }
    return _builtinCache


def invalidate():
    """Forget the cached built-in lists (after the monomers are edited)."""

    global _builtinCache
    _builtinCache = None


# USER LISTS
# ----------


# gui.libs seeds and loads every library file when imported, which images made
# from the command line (they draw rulers through rulerText) have no need of,
# so it is only imported once a list is actually looked up.


def availableLists():
    """Names of every list, built-in ones first."""

    from . import libs

    return list(BUILTIN) + sorted(name for name in libs.differences if name not in BUILTIN)


def getList(name):
    """Entries of the named list, or {} when it no longer exists."""

    from . import libs

    if name in BUILTIN:
        return builtinLists()[name]
    items = libs.differences.get(name)
    if items is None:
        return {}
    return {entry: (mono, avg) for entry, mono, avg in items}


def entries(names):
    """Flat [(entry name, mono, avg, list name)] of the named lists."""

    buff = []
    for listName in names:
        for name, (mono, avg) in getList(listName).items():
            buff.append((name, mono, avg, listName))
    return buff


# MATCHING
# --------


def ppmBase(mzs):
    """What a ppm tolerance or error of a difference is taken of.

    Each of the two peaks can be off by the ppm at its own m/z, and in the
    worst case the two errors run in opposite directions, so a difference can
    be off by that many ppm of the sum of both m/z values.
    """

    return sum(abs(mz) for mz in (mzs or ()))


def toleranceMz(tolerance, units="Da", mzs=None):
    """Tolerance of an m/z difference between peaks at mzs, in m/z."""

    if units == "ppm":
        return tolerance * 1e-6 * ppmBase(mzs)
    return tolerance


def match(diff, candidates, tolerance, massType=0, charge=1, units="Da", mzs=None):
    """Entries matching an m/z difference, best first.

    diff is an m/z difference between two peaks of the same charge; it is
    multiplied by that charge to get the neutral mass difference the entries
    are given in, and so is the tolerance. The tolerance is in Da, or in ppm
    applied at each of the two peaks' m/z (mzs, see ppmBase). candidates is the
    output of entries(). Returns [(name, error, list name, theoretical)], with
    error and theoretical as neutral masses in Da.
    """

    charge = max(1, abs(int(charge or 1)))
    mass = abs(diff) * charge
    tolerance = toleranceMz(tolerance, units, mzs) * charge

    matches = []
    for name, mono, avg, listName in candidates:
        theoretical = avg if massType else mono
        error = mass - theoretical
        if abs(error) <= tolerance:
            matches.append((name, error, listName, theoretical))

    matches.sort(key=lambda item: abs(item[1]))
    return matches


def matchNames(matches, maxNames=3):
    """Names of the closest matches, as a ruler is labelled with them."""

    names = []
    for item in matches:
        if item[0] not in names:
            names.append(item[0])

    text = " / ".join(names[:maxNames])
    if len(names) > maxNames:
        text += " / ..."
    return text


def errorText(error, charge=1, units="Da", mzs=None, digits=4, ppmDigits=1):
    """Observed minus theoretical difference, in Da or in ppm.

    ppm are on the same footing as a ppm tolerance (see ppmBase): the error
    each peak would have to carry, so a ruler matches exactly when this is
    within the tolerance.
    """

    base = ppmBase(mzs)
    if units == "ppm" and base:
        charge = max(1, abs(int(charge or 1)))
        return "%+0.*f ppm" % (ppmDigits, error / charge / base * 1e6)
    return "%+0.*f" % (digits, error)


# what a matched ruler's label shows unless told otherwise
LABEL_DEFAULTS = {
    "labelName": 1,
    "labelAllNames": 1,
    "labelCharge": 1,
    "labelDiff": 1,
    "labelError": 0,
}


def rulerText(
    names,
    diff,
    charge=1,
    theoretical=None,
    mzs=None,
    options=None,
    units="Da",
    digits=4,
    ppmDigits=1,
):
    """Text a difference ruler shows.

    An unmatched ruler (no names) shows the m/z difference itself. What a
    matched one shows is chosen by options (keys as in LABEL_DEFAULTS): the
    names of the closest or of all matches, the charge the match was made at
    when above one, the difference, and the observed minus theoretical error
    in the tolerance units. With every part switched off the names are shown,
    so a matched ruler never goes blank.
    """

    diffText = "%0.*f" % (digits, abs(diff))
    if not names:
        return diffText

    settings = dict(LABEL_DEFAULTS)
    settings.update(options or {})

    parts = []
    if settings["labelName"]:
        text = names if settings["labelAllNames"] else names.split(" / ")[0]
        charge = int(charge or 1)
        if settings["labelCharge"] and abs(charge) > 1:
            text += " (%d%s)" % (abs(charge), "-" if charge < 0 else "+")
        parts.append(text)
    if settings["labelDiff"]:
        parts.append(diffText)
    if settings["labelError"] and theoretical is not None:
        error = abs(diff) * max(1, abs(int(charge or 1))) - theoretical
        parts.append(errorText(error, charge, units, mzs, digits, ppmDigits))

    if not parts:
        return names
    return "  ".join(parts)


def rulerCharge(charge1, charge2):
    """Charge a difference between two peaks is matched at.

    Both ends of a charge series carry the same charge; when only one end has
    been assigned one, it is taken for both. Ends with different charges are
    not one series, so their difference is matched as it is (charge 1).
    """

    if charge1 and charge2:
        return charge1 if charge1 == charge2 else 1
    return charge1 or charge2 or 1


# SERIES
# ------


def findSeries(
    mzs, ais, start, end, candidates, tolerance, massType=0, charge=1, units="Da", minStep=0
):
    """Chain of peaks from start to end whose every step matches an entry.

    mzs are the peaks' m/z in ascending order and ais their intensities;
    start < end are indexes into them, candidates the output of entries().
    Of all the chains through at least one peak in between, the one whose
    weakest peak in between is strongest is taken, so a ladder is followed
    through its peaks rather than through noise that happens to fit; of
    those, the one with the most steps. Steps under minStep (in m/z) are not
    taken, so a series is not stitched out of tiny differences that fit
    almost anywhere. Returns the list of indexes, from start to end, or None
    when there is no such chain.
    """

    import numpy

    if not 0 <= start < end < len(mzs):
        return None

    charge = max(1, abs(int(charge or 1)))
    masses = numpy.unique(
        numpy.array([(avg if massType else mono) for _n, mono, avg, _l in candidates], dtype=float)
    )
    masses = masses[masses > 0]
    if not len(masses):
        return None

    span = numpy.asarray(mzs[start : end + 1], dtype=float)
    steps = masses / charge
    steps = steps[steps >= minStep]
    if not len(steps):
        return None

    # every step between two peaks of the span that matches an entry
    edges = [[] for _ in range(len(span))]
    for i in range(len(span) - 1):
        targets = span[i] + steps
        if units == "ppm":
            limits = tolerance * 1e-6 * (span[i] + targets)
        else:
            limits = numpy.full(len(targets), float(tolerance))
        lower = numpy.searchsorted(span, targets - limits, side="left")
        upper = numpy.searchsorted(span, targets + limits, side="right")
        hits = upper > lower
        reached = set()
        for first, stop in zip(lower[hits], upper[hits], strict=True):
            reached.update(range(max(int(first), i + 1), int(stop)))
        edges[i] = sorted(reached)

    last = len(span) - 1
    heights = [ais[start + k] for k in range(len(span))]

    def longest(threshold):
        """Most steps from the first peak to the last through peaks >= threshold."""

        best: list[int | None] = [None] * len(span)
        back: list[int | None] = [None] * len(span)
        best[0] = 0
        for i in range(len(span)):
            steps = best[i]
            if steps is None:
                continue
            for j in edges[i]:
                if j != last and heights[j] < threshold:
                    continue
                reached = best[j]
                if reached is None or steps + 1 > reached:
                    best[j] = steps + 1
                    back[j] = i
        return best[last], back

    # the strongest weakest peak in between that still lets a chain through
    levels = sorted({heights[k] for k in range(1, last)}, reverse=True)
    lo, hi = 0, len(levels) - 1
    found = None
    while lo <= hi:
        mid = (lo + hi) // 2
        count, back = longest(levels[mid])
        if count is not None and count >= 2:
            found = back
            hi = mid - 1
        else:
            lo = mid + 1

    if found is None:
        return None

    path = [last]
    while path[-1] != 0:
        previous = found[path[-1]]
        if previous is None:
            return None
        path.append(previous)
    return [start + k for k in reversed(path)]


# smallest step (in m/z) a series or a multiple is made of: below it, some
# entry or other fits almost any difference
MIN_SERIES_STEP = 14.0


def matchMultiples(
    diff,
    candidates,
    tolerance,
    massType=0,
    charge=1,
    units="Da",
    mzs=None,
    minStep=MIN_SERIES_STEP,
    maxCount=50,
):
    """Entries an m/z difference is a whole multiple (two or more) of.

    As match(), but each name is written as the multiple, e.g. "3\u00d7Hex",
    and theoretical is the multiple's mass. Entries whose step is under
    minStep m/z are left out. Returns [(name, error, list name,
    theoretical)], best first.
    """

    charge = max(1, abs(int(charge or 1)))
    mass = abs(diff) * charge
    limit = toleranceMz(tolerance, units, mzs) * charge

    matches = []
    for name, mono, avg, listName in candidates:
        unit = avg if massType else mono
        if unit <= 0 or unit / charge < minStep:
            continue
        count = int(round(mass / unit))
        if not 2 <= count <= maxCount:
            continue
        theoretical = count * unit
        error = mass - theoretical
        if abs(error) <= limit:
            matches.append(("%d\u00d7%s" % (count, name), error, listName, theoretical))

    matches.sort(key=lambda item: abs(item[1]))
    return matches


def seriesName(names):
    """Name of a series from the names of its steps, e.g. "2\u00d7Hex + HexNAc".

    Steps named alike are counted together, in the order they first come.
    """

    counts = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    return " + ".join(
        name if count == 1 else "%d\u00d7%s" % (count, name) for name, count in counts.items()
    )
