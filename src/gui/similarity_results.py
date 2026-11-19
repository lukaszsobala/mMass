# -------------------------------------------------------------------------
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

"""Spectrum similarity results as files: tables, trees and a report.

Shared by the Spectrum Similarity tool's Export and by `mmass cluster`, so
both write the same files.  Free of wxPython and of gui.config: everything
arrives as arguments.
"""

import csv
import datetime
import os
import contextlib
import errno
import shutil
import sys
import tempfile
import time

import numpy

import mspy

# the files write_results() writes
OUTPUTS = (
    "REPORT.md",
    "groups.csv",
    "similarity.csv",
    "similarity_cosine.csv",
    "co_membership.csv",
    "trees.nwk",
)

POLARITY = {1: "positive", -1: "negative", None: ""}


class Item:
    """One spectrum to compare."""

    def __init__(self, scan, title, path):
        self.scan = scan
        self.title = title
        self.path = path
        self.label = title


def unique_labels(items):
    """Give spectra of the same title distinct labels: the nearest folder
    level at which their paths differ, then a number."""

    for item in items:
        item.label = item.title
    titles = [item.title for item in items]
    for title in {t for t in titles if titles.count(t) > 1}:
        same = [item for item in items if item.title == title]
        parts = [os.path.dirname(item.path or "").split(os.sep)[::-1] for item in same]
        for level in range(max(len(p) for p in parts)):
            names = [p[level] if level < len(p) else "" for p in parts]
            if len(set(names)) > 1:
                for item, name in zip(same, names, strict=True):
                    if name:
                        item.label = f"{item.title} ({name})"
                break
    # what is still not unique gets a number no other label already has
    labels = [item.label for item in items]
    duplicated = {t for t in labels if labels.count(t) > 1}
    taken = {t for t in labels if t not in duplicated}
    for item in items:
        if item.label in duplicated:
            k = 1
            while f"{item.label} #{k}" in taken:
                k += 1
            item.label = f"{item.label} #{k}"
            taken.add(item.label)


def text(value):
    """A text cell for a spreadsheet: a value that would start a formula
    there (=, +, -, @, tab, CR) is kept as text with a leading apostrophe."""

    value = str(value)
    if value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def number(value, digits=4):
    """A finite number as text, else an empty string."""

    if value is None or not numpy.isfinite(value):
        return ""
    return f"{value:.{digits}f}"


def write_matrix(path, labels, M):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([""] + [text(label) for label in labels])
        for label, row in zip(labels, M, strict=True):
            writer.writerow([text(label)] + [number(v) for v in row])


def nearest(sim, i):
    """The spectrum most similar to spectrum i, or None."""

    S = sim.similarity
    others = [j for j in range(len(S)) if j != i and numpy.isfinite(S[i, j])]
    return max(others, key=lambda j: S[i, j]) if others else None


def together(grp, i):
    """Mean share of replicates spectrum i spends with the rest of its group
    (None without bootstrap or for a single spectrum)."""

    if grp.coMembership is None:
        return None
    members = [j for j in range(len(grp.groups)) if grp.groups[j] == grp.groups[i]]
    members.remove(i)
    if not members:
        return None
    return float(numpy.mean(grp.coMembership[i, members]))


def group_summary(sim, grp, members):
    """(mean similarity, mean co-membership, weakest pair co-membership) of a
    group; the last two are None without bootstrap."""

    S = sim.similarity
    within = [S[a, b] for a in members for b in members if a < b]
    mean = float(numpy.nanmean(within)) if within else float("nan")
    if grp.coMembership is None or not within:
        return mean, None, None
    pairs = [grp.coMembership[a, b] for a in members for b in members if a < b]
    return mean, float(numpy.mean(pairs)), float(min(pairs))


def groups_in_order(grp):
    """[(group number, members in display order)], in group number order."""

    out = []
    for c in sorted(set(grp.groups.tolist())):
        out.append((c, [i for i in grp.order if grp.groups[i] == c]))
    return out


def group_rows(items, sim, grp):
    """Rows of groups.csv, in display order."""

    S = sim.similarity
    rows = []
    for i in grp.order:
        share = together(grp, i)
        near = nearest(sim, i)
        scan = items[i].scan
        rows.append(
            [
                grp.groups[i],
                text(items[i].label),
                POLARITY.get(scan.polarity, ""),
                number(scan.precursorMZ) if scan.precursorMZ else "",
                number(share, 2) if share is not None else "",
                text(items[near].label) if near is not None else "",
                number(S[i, near], 3) if near is not None else "",
                text(items[i].path),
            ]
        )
    return rows


def feature_text(feature):
    """One shared m/z or loss as text: its position, and the range when
    neighbours (e.g. isotopes) were merged into it."""

    pos = feature["positions"]
    text = f"{feature['position']:.2f}"
    if len(pos) > 1:
        text += f" ({pos[0]:.2f}–{pos[-1]:.2f}, {len(pos)} peaks)"
    return text


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
        others = "—" if f["others"] is None else f"{f['others']}/{f['othersCovered']}"
        note = f"= m/z {f['mirror']:.2f} above" if f.get("mirror") is not None else ""
        lines.append(
            f"| {feature_text(f)} | {f['members']}/{f['covered']} | {others} | {note} |"
        )
    return lines + [""]


def report(items, sim, grp, similarity, grouping, failed=0, source="mMass"):
    """The Markdown report.

    similarity, grouping - the parameters passed to mspy.similaritymatrix
        and mspy.groupspectra
    """

    n = len(items)
    g = {
        "method": "network",
        "topK": 3,
        "cut": 0.3,
        "replicates": 0,
        **grouping,
    }
    lines = [
        "# Spectrum groups",
        "",
        f"{source}, {datetime.datetime.now():%Y-%m-%d %H:%M}. "
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
        + ", ".join(f"{k} {v}" for k, v in mspy.similarityparams(**similarity).items())
        + ".",
        "",
    ]
    polarity, apart = uncompared(sim)
    if polarity:
        lines += [
            "Spectra of different polarity were not compared (the neutral-mass "
            "option compares them).",
            "",
        ]
    if apart:
        lines += [
            f"{apart} pair(s) had no m/z range in common and were not compared.",
            "",
        ]
    if len([t for t in grp.trees if len(t[0]) > 1]) > 1:
        lines += [
            "Each tree holds spectra linked by a chain of compared pairs; spectra "
            "with no such chain between them are in separate trees. Within a tree, "
            "clusters with no compared pair between them join at similarity -1.",
            "",
        ]
    rho, rhoApart = mspy.rangedependence(sim)
    lines += [
        "Range dependence (Spearman rho of pair similarity against the ratio of the "
        "spectra's m/z ranges; 0 = none, negative = spectra of similar range look "
        f"more alike): {number(rho, 2) or '—'} for all pairs, "
        f"{number(rhoApart, 2) or '—'} for pairs whose ranges differ by more than 10 Da.",
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
    for c, members in groups_in_order(grp):
        if len(members) == 1:
            singles.append(members[0])
            continue
        mean, share, weakest = group_summary(sim, grp, members)
        head = f"## Group {c} ({len(members)} spectra, mean similarity {mean:.2f}"
        if share is not None and weakest is not None:
            head += (
                f"; together in {100 * share:.0f}% of replicates, "
                f"weakest pair {100 * weakest:.0f}%"
            )
        lines += [head + ")", ""]
        for i in members:
            extra = ""
            mine = together(grp, i)
            if mine is not None:
                extra = f" — together with the others in {100 * mine:.0f}%"
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
    ]
    if grp.coMembership is not None:
        lines.append("- co_membership.csv: share of bootstrap replicates in one group")
    lines += [
        "- trees.nwk: average-linkage trees (one per line), bootstrap support at "
        "the inner nodes",
        "",
    ]
    return "\n".join(lines)


def uncompared(sim):
    """(whether some pairs were left out for polarity, how many pairs of the
    same polarity had no m/z range in common)."""

    n = len(sim.similarity)
    neutral = sim.params.get("neutralMass", False)
    polarity, apart = False, 0
    pols = [p.polarity for p in sim.prepared]
    for i in range(n):
        for j in range(i + 1, n):
            if sim.comparable[i, j]:
                continue
            a, b = pols[i], pols[j]
            if not neutral and a is not None and b is not None and (a > 0) != (b > 0):
                polarity = True
            else:
                apart += 1
    return polarity, apart


def outputs_in_the_way(folder):
    """The result files already in folder."""

    return [name for name in OUTPUTS if os.path.exists(os.path.join(folder, name))]


class ResultsExist(OSError):
    """Results appeared in the folder of an export that may not replace them."""


class FolderBusy(OSError):
    """Another export is publishing into the same folder."""


# exports publishing into one folder take turns through this file
LOCK_NAME = ".similarity.lock"

# how long to wait for another export to finish publishing (seconds)
LOCK_WAIT = 10.0


def _trylock(fd):
    """Take an exclusive lock on fd without waiting; False if someone else
    holds it.  An OS lock (forwarded to NFS and SMB servers as a byte-range
    lock) is released by the kernel when its holder exits, so a crashed
    export leaves nothing to clean up."""

    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, PermissionError):
        return False
    except OSError as exc:
        # Windows reports a held lock as EDEADLOCK/EACCES
        if exc.errno in (errno.EACCES, errno.EAGAIN, getattr(errno, "EDEADLOCK", -1)):
            return False
        raise
    return True


def _unlock(fd):
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.lockf(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def _folderLock(folder):
    """Hold the folder's export lock while publishing (milliseconds).

    The lock file stays in the folder: removing it would let two exports
    lock different files.  It is created group-writable if the umask allows,
    so others sharing the folder can lock it too.  Where the filesystem
    supports no locking at all, or the lock file belongs to someone who has
    not shared it, publishing goes ahead unlocked (it still never replaces
    files without overwrite).
    """

    try:
        fd = os.open(os.path.join(folder, LOCK_NAME), os.O_CREAT | os.O_RDWR, 0o666)
    except PermissionError:
        yield
        return
    locked = False
    try:
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            try:
                locked = _trylock(fd)
            except OSError:
                break  # no locking here (e.g. ENOLCK): go ahead unlocked
            if locked:
                break
            if time.monotonic() > deadline:
                raise FolderBusy(f"another export is writing to {folder}")
            time.sleep(0.05)
        yield
    finally:
        try:
            if locked:
                _unlock(fd)
        finally:
            os.close(fd)


def write_results(
    folder, items, sim, grp, similarity, grouping, failed=0, source="mMass", overwrite=True
):
    """Write every file of OUTPUTS into folder (co_membership.csv only with
    a bootstrap; with overwrite, a stale one is removed).

    The files are written to a staging folder first, every destination is
    checked, and only then are they published, so a failure does not leave a
    mix of two runs behind.  Checking and publishing (and taking back) happen
    under the folder's export lock, so two exports into one folder cannot
    interleave.  Without overwrite nothing already there is replaced, not
    even results another run wrote meanwhile: each file is linked into place,
    which fails if it exists (ResultsExist; the files of this export
    published so far are taken back).
    """

    os.makedirs(folder, exist_ok=True)
    stage = tempfile.mkdtemp(prefix=".similarity-", dir=folder)
    try:
        _write_all(stage, items, sim, grp, similarity, grouping, failed, source)
        written = sorted(os.listdir(stage))
        stale = [name for name in OUTPUTS if name not in written] if overwrite else []
        with _folderLock(folder):
            for name in written + stale:
                target = os.path.join(folder, name)
                if os.path.isdir(target) or (
                    os.path.exists(target) and not os.access(target, os.W_OK)
                ):
                    raise OSError(f"{target} cannot be replaced")
                if not overwrite and os.path.lexists(target):
                    raise ResultsExist(f"{target} already exists")
            if overwrite:
                # a stale table from an earlier run would mislead: it goes too
                _publish_replacing(stage, folder, written, stale)
            else:
                _publish_new(stage, folder, written)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _publish_replacing(stage, folder, names, stale):
    """Move the staged files into folder in place of the earlier results.

    The earlier files are moved aside first and put back if any step fails,
    so the folder holds either the whole earlier set or the whole new one.
    If even putting them back fails, they are kept in a folder named in the
    error rather than deleted.
    """

    aside = tempfile.mkdtemp(prefix=".similarity-old-", dir=folder)
    moved, placed = [], []
    try:
        for name in names + stale:
            if os.path.lexists(os.path.join(folder, name)):
                os.replace(os.path.join(folder, name), os.path.join(aside, name))
                moved.append(name)
        for name in names:
            os.replace(os.path.join(stage, name), os.path.join(folder, name))
            placed.append(name)
    except OSError as exc:
        lost = []
        for name in placed:
            if name not in moved:
                try:
                    os.remove(os.path.join(folder, name))
                except OSError:
                    pass
        for name in moved:
            try:
                os.replace(os.path.join(aside, name), os.path.join(folder, name))
            except OSError:
                lost.append(name)
        if lost:
            raise OSError(
                f"publishing failed and {', '.join(lost)} could not be put back; "
                f"the earlier files are in {aside}"
            ) from exc
        shutil.rmtree(aside, ignore_errors=True)
        raise
    shutil.rmtree(aside, ignore_errors=True)


def _publish_new(stage, folder, names):
    """Move the staged files into folder without replacing anything there."""

    # (target, the file published there), to take back only our own files
    published = []
    try:
        for name in names:
            source, target = os.path.join(stage, name), os.path.join(folder, name)
            mine = os.stat(source)
            try:
                os.link(source, target)  # fails if target exists, atomically
            except FileExistsError:
                raise ResultsExist(f"{target} appeared during the export") from None
            except OSError:
                # no hard links here (e.g. some network shares): check just
                # before the move instead (the folder lock keeps other exports out)
                if os.path.lexists(target):
                    raise ResultsExist(f"{target} appeared during the export") from None
                os.replace(source, target)
            published.append((target, mine))
    except OSError:
        for path, mine in published:
            try:
                # a file someone else put there since is not ours to remove
                if os.path.samestat(os.stat(path), mine):
                    os.remove(path)
            except OSError:
                pass
        raise


def _write_all(folder, items, sim, grp, similarity, grouping, failed, source):
    labels = [item.label for item in items]
    write_matrix(os.path.join(folder, "similarity.csv"), labels, sim.similarity)
    write_matrix(os.path.join(folder, "similarity_cosine.csv"), labels, sim.cosine)
    if grp.coMembership is not None:
        write_matrix(os.path.join(folder, "co_membership.csv"), labels, grp.coMembership)
    with open(os.path.join(folder, "groups.csv"), "w", newline="", encoding="utf-8") as fh:
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
    with open(os.path.join(folder, "trees.nwk"), "w", encoding="utf-8") as fh:
        for comp, Z, support in grp.trees:
            if len(comp) > 1:
                fh.write(mspy.newick(Z, [labels[i] for i in comp], support) + "\n")
    with open(os.path.join(folder, "REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write(report(items, sim, grp, similarity, grouping, failed, source))
