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


def match(diff, candidates, tolerance, massType=0, charge=1):
    """Entries matching an m/z difference, best first.

    diff is an m/z difference between two peaks of the same charge; it is
    multiplied by that charge to get the neutral mass difference the entries
    are given in, and so is the m/z tolerance. candidates is the output of
    entries(). Returns [(name, error, list name)], error in Da.
    """

    charge = max(1, abs(int(charge or 1)))
    mass = abs(diff) * charge
    tolerance = tolerance * charge

    matches = []
    for name, mono, avg, listName in candidates:
        error = mass - (avg if massType else mono)
        if abs(error) <= tolerance:
            matches.append((name, error, listName))

    matches.sort(key=lambda item: abs(item[1]))
    return matches


def matchNames(matches, maxNames=3):
    """Names of the closest matches, as a ruler is labelled with them."""

    names = []
    for name, _error, _listName in matches:
        if name not in names:
            names.append(name)

    text = " / ".join(names[:maxNames])
    if len(names) > maxNames:
        text += " / ..."
    return text


def rulerText(names, diff, charge=1, showDiff=False, digits=4):
    """Text a difference ruler shows.

    An unmatched ruler (no names) shows the m/z difference itself; a matched one
    shows the names, followed by the difference when showDiff is set. A charge
    above one is added so a ruler across a multiply-charged series says which
    charge its match was computed for.
    """

    diffText = "%0.*f" % (digits, abs(diff))
    if not names:
        return diffText

    text = names
    charge = int(charge or 1)
    if abs(charge) > 1:
        text += " (%d%s)" % (abs(charge), "-" if charge < 0 else "+")

    if showDiff:
        text += "  %s" % diffText

    return text


def rulerCharge(charge1, charge2):
    """Charge a difference between two peaks is matched at.

    Both ends of a charge series carry the same charge; when only one end has
    been assigned one, it is taken for both. Ends with different charges are
    not one series, so their difference is matched as it is (charge 1).
    """

    if charge1 and charge2:
        return charge1 if charge1 == charge2 else 1
    return charge1 or charge2 or 1
