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

"""Groups and trees from a spectrum similarity matrix.

Groups are communities of a spectral network, as in MS/MS molecular
networking: an edge joins two spectra when their corrected similarity is at
least `edge` (default 0.2) and each is among the other's top-K neighbours
(default 3); communities maximise modularity (Louvain).  A spectrum without
edges stays on its own.

A fixed threshold works across data sets because the similarity is already
chance-corrected (0 = as alike as chance).  The alternative edge='auto'
(median + 2 robust SD of the pairs, per polarity) assumes that most pairs are
unrelated: it suited LIFT fragment spectra of many precursors but put the
threshold above nearly every pair in MS1 glycan profiles, where all samples
share most glycans.  Of the settings tried, 0.2 with top-3 recovered all
same-precursor pairs in the lipid data and separated the species in the
positive glycan spectra.

A tree (UPGMA, average linkage) is built for display, one per set of
spectra linked by a chain of compared pairs.  Spectra of different polarity
are not compared directly, but a spectrum of unknown polarity can link both
into one tree; clusters with no compared pair between them join at
UNMEASURED.

Confidence comes from a bootstrap over blocks of the m/z and loss axes
(mod_similarity.bootstrapmatrices): for every pair, the share of replicates in
which both fall in the same community (co-membership), and for every clade
of the tree, the share of replicate trees that contain it.

On the tick-lipid LIFT data the network grouping was the most robust to
parameter changes of the methods tried (UPGMA, neighbour joining, network);
neighbour joining was the least stable.
"""

import numpy

from . import mod_similarity

__all__ = [
    "UNMEASURED",
    "upgma",
    "treeorder",
    "measuredjoins",
    "clades",
    "newick",
    "backgroundthreshold",
    "spectralnetwork",
    "louvain",
    "adjustedrand",
    "groupspectra",
]


# TREES
# -----


# distance at which clusters without a single measured pair between them are
# joined: similarity -1, the bottom of the scale
UNMEASURED = 2.0


def upgma(S):
    """Average-linkage tree from a similarity matrix.

    Distances are 1 - S.  The distance between two clusters is the mean over
    the pairs between them that were measured (NaN = not measured), so a
    missing pair does not count as any particular distance; clusters with no
    measured pair between them join at UNMEASURED.  With every pair measured
    this is plain UPGMA.  Returns a linkage matrix in the scipy layout:
    rows (a, b, distance, size), new clusters numbered from n upwards.
    """

    S = numpy.asarray(S, float)
    n = len(S)
    D = 1.0 - S
    D = 0.5 * (D + D.T)
    measured = numpy.isfinite(D)
    numpy.fill_diagonal(measured, False)
    total = numpy.where(measured, D, 0.0)
    count = measured.astype(float)
    active = list(range(n))
    ids = list(range(n))
    size = [1] * n
    Z = []

    def distances():
        with numpy.errstate(invalid="ignore", divide="ignore"):
            M = numpy.where(count > 0, total / numpy.maximum(count, 1), UNMEASURED)
        numpy.fill_diagonal(M, numpy.inf)
        return M

    M = distances()
    for step in range(n - 1):
        sub = M[numpy.ix_(active, active)]
        k = int(numpy.argmin(sub))
        a, b = divmod(k, len(active))
        ia, ib = active[a], active[b]
        d = float(M[ia, ib])
        na, nb = size[ia], size[ib]
        lo, hi = sorted((ids[ia], ids[ib]))
        Z.append((lo, hi, d, na + nb))
        # merge ib into ia: sums and counts of the measured pairs add up
        total[ia, :] += total[ib, :]
        total[:, ia] = total[ia, :]
        count[ia, :] += count[ib, :]
        count[:, ia] = count[ia, :]
        total[ia, ia] = count[ia, ia] = 0.0
        size[ia] = na + nb
        ids[ia] = n + step
        active.remove(ib)
        # only the merged cluster's distances changed (ib is no longer active)
        with numpy.errstate(invalid="ignore", divide="ignore"):
            row = numpy.where(
                count[ia] > 0, total[ia] / numpy.maximum(count[ia], 1), UNMEASURED
            )
        M[ia, :] = row
        M[:, ia] = row
        M[ia, ia] = numpy.inf
    return numpy.array(Z, float).reshape(-1, 4)


def treeorder(Z):
    """Leaf order for drawing the tree (left to right)."""

    # an explicit stack: a tree of many alike spectra is a chain as deep as
    # the spectra are many, beyond Python's recursion limit
    n = len(Z) + 1
    order = []
    stack = [2 * n - 2]
    while stack:
        node = stack.pop()
        if node < n:
            order.append(node)
        else:
            a, b = int(Z[node - n, 0]), int(Z[node - n, 1])
            stack += [b, a]  # a comes off first: left to right
    return order


def measuredjoins(Z, S):
    """For each join of a linkage tree, whether any pair between its two
    sides was compared (finite in S). upgma joins the others at UNMEASURED,
    but a compared pair can score as low, so the height cannot tell."""

    finite = numpy.isfinite(numpy.asarray(S, float))
    n = len(Z) + 1
    members = [[i] for i in range(n)]
    out = []
    for a, b, _, _ in Z:
        left, right = members[int(a)], members[int(b)]
        out.append(bool(finite[numpy.ix_(left, right)].any()))
        members.append(left + right)
    return numpy.array(out, bool)


def clades(Z):
    """Leaf sets of the internal nodes, in linkage order."""

    n = len(Z) + 1
    members = [frozenset([i]) for i in range(n)]
    out = []
    for a, b, _, _ in Z:
        s = members[int(a)] | members[int(b)]
        members.append(s)
        out.append(s)
    return out


def newick(Z, labels, support=None):
    """Newick string of a linkage tree; support values label internal nodes."""

    n = len(labels)
    if n == 1:
        return _clean(labels[0]) + ";"

    # walked with an explicit stack of nodes and finished tokens, so deep trees
    # need no recursion and no subtree's text is held more than once
    Z = numpy.asarray(Z, float)
    height = [0.0] * n + [d / 2 for d in Z[:, 2]]
    tokens = []
    stack = [2 * n - 2]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            tokens.append(item)
            continue
        if item < n:
            tokens.append(_clean(labels[item]))
            continue
        k = item - n
        h = height[item]
        a, b = int(Z[k, 0]), int(Z[k, 1])
        lengths = [":%.4f" % (h if c < n else max(h - height[c], 0.0)) for c in (a, b)]
        sup = "%d" % round(100 * support[k]) if support is not None else ""
        stack += [")" + sup, lengths[1], b, ",", lengths[0], a, "("]
    return "".join(tokens) + ";"


def _clean(text):
    """A Newick label: as it is when safe, else quoted (quotes doubled), so
    distinct names stay distinct."""

    if text and not any(c in text for c in " (),:;[]'\t\n"):
        return text
    return "'%s'" % text.replace("'", "''")


# NETWORK
# -------


def backgroundthreshold(S, k=2.0):
    """Median + k robust SD of the compared pair similarities."""

    iu = numpy.triu_indices(len(S), 1)
    v = S[iu]
    v = v[numpy.isfinite(v)]
    if not len(v):
        return numpy.inf
    med = numpy.median(v)
    return float(med + k * 1.4826 * numpy.median(numpy.abs(v - med)))


def spectralnetwork(S, threshold, topK=3):
    """Edge weights: S where S >= threshold and both are in each other's top K."""

    n = len(S)
    T = numpy.where(numpy.isfinite(S), S, -numpy.inf)
    numpy.fill_diagonal(T, -numpy.inf)
    top = numpy.zeros((n, n), bool)
    for i in range(n):
        top[i, numpy.argsort(-T[i], kind="mergesort")[:topK]] = True
    keep = (T >= threshold) & top & top.T
    return numpy.where(keep, numpy.nan_to_num(S), 0.0)


def _modularity(W, comm, resolution):
    m2 = W.sum()
    if m2 == 0:
        return 0.0
    k = W.sum(1)
    same = comm[:, None] == comm[None, :]
    return float(((W - resolution * numpy.outer(k, k) / m2) * same).sum() / m2)


def louvain(W, seed=0, resolution=1.0, restarts=20):
    """Communities maximising modularity: best of several randomised Louvain
    runs (Blondel et al. 2008).  Returns a label per node (0, 1, ...)."""

    W = numpy.asarray(W, float)
    rng = numpy.random.default_rng(seed)
    best, bestQ = numpy.arange(len(W)), -numpy.inf
    for _ in range(max(1, restarts)):
        c = _louvainonce(W, rng, resolution)
        q = _modularity(W, c, resolution)
        if q > bestQ + 1e-12:
            best, bestQ = c, q
    return numpy.unique(best, return_inverse=True)[1]


def _louvainonce(W, rng, resolution):
    n = len(W)
    m2 = W.sum()
    groups = [[i] for i in range(n)]
    if m2 == 0:
        return numpy.arange(n)
    A = W.copy()
    while True:
        N = len(A)
        k = A.sum(1)
        comm = numpy.arange(N)
        tot = k.copy()
        moved = False
        improved = True
        while improved:
            improved = False
            for i in rng.permutation(N):
                ci = comm[i]
                tot[ci] -= k[i]
                links = numpy.bincount(comm, weights=A[i], minlength=N)
                links[ci] -= A[i, i]
                gain = links - resolution * tot * k[i] / m2
                cands = numpy.unique(numpy.r_[comm[A[i] > 0], ci])
                bc = cands[numpy.argmax(gain[cands])]
                if gain[bc] <= gain[ci] + 1e-12:
                    bc = ci
                comm[i] = bc
                tot[bc] += k[i]
                if bc != ci:
                    improved = moved = True
        if not moved:
            break
        lab = numpy.unique(comm, return_inverse=True)[1]
        K = lab.max() + 1
        P = numpy.zeros((N, K))
        P[numpy.arange(N), lab] = 1
        A = P.T @ A @ P
        groups = [
            sum((groups[a] for a in range(N) if lab[a] == c), []) for c in range(K)
        ]
        if K == N:
            break
    out = numpy.empty(n, int)
    for c, g in enumerate(groups):
        out[g] = c
    return out


def adjustedrand(a, b):
    """Adjusted Rand index of two labellings (1 = same partition, 0 = chance)."""

    a = numpy.unique(numpy.asarray(a), return_inverse=True)[1]
    b = numpy.unique(numpy.asarray(b), return_inverse=True)[1]
    C = numpy.zeros((a.max() + 1, b.max() + 1))
    numpy.add.at(C, (a, b), 1)

    def comb(x):
        return x * (x - 1) / 2

    sa, sb, total = comb(C.sum(1)).sum(), comb(C.sum(0)).sum(), comb(len(a))
    expected = sa * sb / total if total else 0.0
    maximum = 0.5 * (sa + sb)
    if maximum == expected:
        return 1.0
    return float((comb(C).sum() - expected) / (maximum - expected))


# GROUPING
# --------


class groupingresult:
    """Result of groupspectra().

    groups - group number per spectrum: groups of several spectra are
        numbered 1, 2, ... in display order, then each single spectrum
    order - spectrum order for display (tree order, tree after tree)
    trees - list of (indices, linkage, clade support or None), one per set of
        comparable spectra
    coMembership - share of bootstrap replicates in which two spectra fall in
        the same group (None without bootstrap)
    edgeFrequency - share of replicates with each network edge (None ...)
    network - edge weights of the full-data network
    threshold - edge threshold of each set of comparable spectra (aligned
        with trees; None for a set of one)
    stability - mean adjusted Rand index of the grouping against the
        replicates' groupings (None without bootstrap)
    """

    def __init__(self):
        self.groups: numpy.ndarray = numpy.zeros(0, int)
        self.order: list[int] = []
        self.trees: list[tuple[list[int], numpy.ndarray, numpy.ndarray | None]] = []
        self.coMembership: numpy.ndarray | None = None
        self.edgeFrequency: numpy.ndarray | None = None
        self.network: numpy.ndarray = numpy.zeros((0, 0))
        self.threshold: list[float | None] = []
        self.stability: float | None = None
        self.method: str = "network"


def _components(C):
    """Sets of spectra connected by comparable pairs."""

    n = len(C)
    seen, out = set(), []
    for s in range(n):
        if s in seen:
            continue
        comp, stack = [], [s]
        seen.add(s)
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in numpy.nonzero(C[x])[0]:
                if int(y) not in seen:
                    seen.add(int(y))
                    stack.append(int(y))
        out.append(sorted(comp))
    return out


def _find(parent, x):
    """Root of x in a union-find forest (with path halving)."""

    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _treegroups(S, components, cut):
    labels = numpy.empty(len(S), int)
    nxt = 0
    for comp in components:
        if len(comp) == 1:
            labels[comp[0]] = nxt
            nxt += 1
            continue
        Z = upgma(S[numpy.ix_(comp, comp)])
        # cut: clusters whose merge distance <= 1 - cut
        parent = list(range(2 * len(comp) - 1))
        for k, (a, b, d, _) in enumerate(Z):
            if d <= 1 - cut:
                parent[_find(parent, int(a))] = len(comp) + k
                parent[_find(parent, int(b))] = len(comp) + k
        roots = {}
        for local, glob in enumerate(comp):
            r = _find(parent, local)
            if r not in roots:
                roots[r] = nxt
                nxt += 1
            labels[glob] = roots[r]
    return labels


def _network(S, components, edge, topK, minEdge):
    """Network edges, with the threshold set within each set of comparable
    spectra (polarities have different typical similarity levels)."""

    W = numpy.zeros_like(S)
    thresholds = []
    for comp in components:
        if len(comp) < 2:
            thresholds.append(None)
            continue
        sub = S[numpy.ix_(comp, comp)]
        thr = max(backgroundthreshold(sub), minEdge) if edge == "auto" else float(edge)
        W[numpy.ix_(comp, comp)] = spectralnetwork(sub, thr, topK)
        thresholds.append(thr)
    return W, thresholds


def _group(S, components, method, edge, topK, resolution, cut, seed, minEdge):
    W, thresholds = _network(S, components, edge, topK, minEdge)
    if method == "tree":
        return _treegroups(S, components, cut), W, thresholds
    return louvain(W, seed, resolution), W, thresholds


def groupspectra(
    similarity,
    method="network",
    edge=0.2,
    topK=3,
    resolution=1.0,
    cut=0.3,
    replicates=200,
    seed=1,
    minEdge=0.2,
    stopper=None,
):
    """Group spectra and build trees from a mod_similarity result.

    similarity (similarityresult) - from mod_similarity.similaritymatrix()
    method ('network' or 'tree') - network communities, or the tree cut at
        corrected similarity `cut`
    edge (float or 'auto') - network edge threshold on corrected similarity;
        'auto' = median + 2 robust SD of the pair similarities within each
        set of comparable spectra (e.g. each polarity), at least minEdge
    topK (int) - an edge needs both spectra in each other's top K
    resolution (float) - modularity resolution; higher = smaller groups
    replicates (int) - bootstrap replicates (0 = no bootstrap)
    seed (int) - random seed (bootstrap and Louvain)
    minEdge (float) - lowest threshold edge="auto" may choose
    stopper (callable or None) - called between replicates; may raise to stop
    """

    if method not in ("network", "tree"):
        raise ValueError("method must be 'network' or 'tree'")
    S = similarity.similarity
    n = len(S)
    components = _components(similarity.comparable)
    res = groupingresult()
    res.method = method
    labels, W, thr = _group(
        S, components, method, edge, topK, resolution, cut, seed, minEdge
    )
    res.network = W
    res.threshold = thr

    trees = []
    for comp in components:
        Z = upgma(S[numpy.ix_(comp, comp)]) if len(comp) > 1 else numpy.zeros((0, 4))
        trees.append([comp, Z, None])

    if replicates > 0:
        co = numpy.zeros((n, n))
        freq = numpy.zeros((n, n))
        hits = [numpy.zeros(len(Z)) for _, Z, _ in trees]
        aris = []
        done = 0
        for B in mod_similarity.bootstrapmatrices(similarity, replicates, seed):
            done += 1
            if stopper is not None:
                stopper()
            g, Wb, _ = _group(
                B, components, method, edge, topK, resolution, cut, seed, minEdge
            )
            co += g[:, None] == g[None, :]
            aris.append(adjustedrand(labels, g))
            freq += Wb > 0
            for t, (comp, Z, _) in enumerate(trees):
                if len(Z):
                    found = set(clades(upgma(B[numpy.ix_(comp, comp)])))
                    hits[t] += [c in found for c in clades(Z)]
        # nothing to resample (no compared pair): no bootstrap results
        if done:
            res.coMembership = co / done
            res.edgeFrequency = freq / done
            res.stability = float(numpy.mean(aris)) if aris else None
            for t in range(len(trees)):
                if len(trees[t][1]):
                    trees[t][2] = hits[t] / done

    # display order: tree after tree, larger sets first
    order = []
    for comp, Z, _ in sorted(trees, key=lambda t: -len(t[0])):
        order += [comp[k] for k in treeorder(Z)] if len(Z) else list(comp)
    res.order = order
    res.trees = [(comp, Z, sup) for comp, Z, sup in trees]

    # number groups of several spectra first, then single spectra, each in
    # display order
    sizes = numpy.bincount(labels)
    renumber = {}
    for single in (False, True):
        for i in order:
            if (sizes[labels[i]] == 1) == single:
                renumber.setdefault(labels[i], len(renumber) + 1)
    res.groups = numpy.array([renumber[c] for c in labels])
    return res
