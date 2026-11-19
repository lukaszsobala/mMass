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

"""Similarity of whole spectra, corrected for their m/z range.

A plain spectral similarity groups spectra by m/z range: a fragment spectrum
only has fragments below its precursor, heavier precursors have a higher
chemical-noise baseline, and ions every spectrum shares make everything look
alike.  The similarity computed here corrects for this in four steps:

1. Baseline and noise.  A rolling opening (minimum, then maximum) is the
   baseline; signal is kept only above `snr` times the local noise (a rolling
   median of what is left).
2. Shared range, two axes.  A pair is compared only where both spectra have
   data: on the m/z axis up to the lighter precursor minus the isolation
   window, and for fragment spectra also on the neutral-loss axis
   (precursor - m/z).  The two axes are concatenated, so shared fragment ions
   and shared losses both count.
3. Rarity weighting.  Each position is weighted 1 + ln((1 + spectra covering
   it) / (1 + spectra with signal there)), so ions that every spectrum has
   count less.
4. Chance correction.  The similarity expected by chance is that of one
   spectrum against the other slid by lagMin..lagMax Da (as in SEQUEST's
   XCorr).  The result is S = (cos - chance) / (1 - chance): 1 = identical,
   0 = no more alike than chance for the pair's range and peak density.

Spectra of different polarity are not compared (their similarity is NaN)
unless neutralMass is set, which moves every spectrum to neutral mass with the
given adducts.  Comparing polarities directly assumes one ion type per
polarity for the whole spectrum.

The per-block sums kept in the result let mod_grouping resample 10-Da blocks
for a bootstrap without recomputing the vectors.
"""

import math

import numpy

__all__ = [
    "similarityparams",
    "similaritymatrix",
    "bootstrapmatrices",
    "sharedfeatures",
    "rangedependence",
    "ADDUCTS_POSITIVE",
    "ADDUCTS_NEGATIVE",
]


# m/z of [M+X]+ minus M, and of the negative ions minus M
ADDUCTS_POSITIVE = {"H": 1.007276, "Na": 22.989218, "K": 38.963158, "NH4": 18.033823}
ADDUCTS_NEGATIVE = {"H": -1.007276, "Cl": 34.969402, "HCOO": 44.998201}


def similarityparams(**overrides):
    """Default parameters, updated with `overrides`."""

    params = {
        "source": "profile",  # 'profile' or 'peaks' (the peak list)
        "axes": "both",  # 'both', 'mz' or 'loss' (loss axis needs a precursor)
        "binWidth": 0.1,  # grid step, Da
        "tolerance": 0.2,  # Gaussian sigma for m/z tolerance, Da
        "minMZ": 50.0,  # low-mass limit
        "isolation": 6.0,  # half-width excluded around the precursor, Da
        "baselineWindow": 5.0,  # width of the baseline opening, Da
        "noiseWindow": 25.0,  # width of the noise median, Da
        "snr": 5.0,  # keep signal above snr x local noise
        "transform": "sqrt",  # 'sqrt', 'log' or 'none'
        "weighting": "rarity",  # 'rarity' or 'none'
        "lagMin": 5.0,  # chance level from lags lagMin..lagMax Da
        "lagMax": 75.0,
        "chanceCorrection": True,
        "blockSize": 10.0,  # bootstrap block, Da
        "neutralMass": False,  # compare polarities on neutral mass
        "posAdduct": "Na",
        "negAdduct": "H",
    }
    unknown = set(overrides) - set(params)
    if unknown:
        raise ValueError(
            "Unknown similarity parameter(s): %s" % ", ".join(sorted(unknown))
        )
    params.update(overrides)
    if params["source"] not in ("profile", "peaks"):
        raise ValueError("source must be 'profile' or 'peaks'")
    if params["axes"] not in ("both", "mz", "loss"):
        raise ValueError("axes must be 'both', 'mz' or 'loss'")
    if params["transform"] not in ("sqrt", "log", "none"):
        raise ValueError("transform must be 'sqrt', 'log' or 'none'")
    if params["weighting"] not in ("rarity", "none"):
        raise ValueError("weighting must be 'rarity' or 'none'")
    if params["posAdduct"] not in ADDUCTS_POSITIVE:
        raise ValueError("posAdduct must be one of %s" % ", ".join(ADDUCTS_POSITIVE))
    if params["negAdduct"] not in ADDUCTS_NEGATIVE:
        raise ValueError("negAdduct must be one of %s" % ", ".join(ADDUCTS_NEGATIVE))
    return params


# ARRAY HELPERS (numpy only, mMass does not depend on scipy)
# -------------


def _sliding(x, w, func):
    """Centred running min/max over w points (w odd), mirrored at the ends."""

    half = w // 2
    padded = numpy.pad(x, half, mode="symmetric")
    windows = numpy.lib.stride_tricks.sliding_window_view(padded, w)
    return func(windows, axis=1)


def _runningmin(x, w):
    return _sliding(x, w | 1, numpy.min)


def _runningmax(x, w):
    return _sliding(x, w | 1, numpy.max)


def _runningmean(x, w):
    """Centred moving average over w points (w odd), mirrored at the ends."""

    w |= 1
    half = w // 2
    padded = numpy.pad(x, half, mode="symmetric")
    c = numpy.concatenate(([0.0], numpy.cumsum(padded)))
    return (c[w:] - c[:-w]) / w


def _runningmedian(x, w, step):
    """Running median over w points, evaluated every `step` points and
    interpolated in between (the noise level changes slowly)."""

    n = len(x)
    if n == 0:
        return x.copy()
    half = w // 2
    centres = numpy.arange(0, n, max(1, step))
    if centres[-1] != n - 1:
        centres = numpy.append(centres, n - 1)
    values = numpy.empty(len(centres))
    for k, c in enumerate(centres):
        values[k] = numpy.median(x[max(0, c - half) : c + half + 1])
    return numpy.interp(numpy.arange(n), centres, values)


def _gaussian(x, sigma):
    """Gaussian smoothing, zero outside (sigma in points)."""

    if sigma <= 0:
        return x.copy()
    radius = int(4.0 * sigma + 0.5)
    t = numpy.arange(-radius, radius + 1)
    kernel = numpy.exp(-0.5 * (t / sigma) ** 2)
    kernel /= kernel.sum()
    return numpy.convolve(x, kernel, mode="same")


def _lagsmear(v, kmin, kmax):
    """Mean of v(b + t) over lags kmin <= |t| <= kmax (zero outside v)."""

    n = len(v)
    c = numpy.concatenate(([0.0], numpy.cumsum(v)))
    b = numpy.arange(n)

    def window(lo, hi):  # sum of v[lo..hi], clipped to the array
        lo = numpy.clip(lo, 0, n)
        hi = numpy.clip(hi + 1, 0, n)
        return c[hi] - c[lo]

    total = window(b + kmin, b + kmax) + window(b - kmax, b - kmin)
    return total / (2 * (kmax - kmin + 1))


def _resamplemax(mz, y, binWidth, n):
    """Maximum intensity per bin; empty bins inside the data are interpolated."""

    idx = numpy.floor(mz / binWidth).astype(int)
    keep = (idx >= 0) & (idx < n)
    idx, y = idx[keep], y[keep]
    out = numpy.zeros(n)
    if not len(idx):
        return out
    numpy.maximum.at(out, idx, y)
    counts = numpy.bincount(idx, minlength=n)
    lo, hi = idx.min(), idx.max()
    inside = numpy.arange(lo, hi + 1)
    filled = counts[lo : hi + 1] > 0
    if not filled.all():
        out[inside[~filled]] = numpy.interp(
            inside[~filled], inside[filled], out[inside[filled]]
        )
    return out


def _ranks(x):
    """Ranks with ties averaged."""

    order = numpy.argsort(x, kind="mergesort")
    ranks = numpy.empty(len(x))
    ranks[order] = numpy.arange(len(x))
    sx = x[order]
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and sx[j + 1] == sx[i]:
            j += 1
        if j > i:
            ranks[order[i : j + 1]] = 0.5 * (i + j)
        i = j + 1
    return ranks


def _spearman(x, y):
    if len(x) < 4:
        return float("nan")
    rx, ry = _ranks(numpy.asarray(x, float)), _ranks(numpy.asarray(y, float))
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(numpy.corrcoef(rx, ry)[0, 1])


# PREPARATION
# -----------


class _prepared:
    """Vectors of one spectrum on the common grid."""

    __slots__ = (
        "scan",
        "polarity",
        "precursor",
        "signal",
        "mzVector",
        "mzPresent",
        "mzRange",
        "lossVector",
        "lossPresent",
        "lossRange",
        "end",
    )


def _spectrumdata(scan, shift):
    profile = scan.profile
    if profile is not None and len(profile):
        mz = numpy.asarray(profile[:, 0], float) + shift
        it = numpy.asarray(profile[:, 1], float)
        order = numpy.argsort(mz)
        mz, it = mz[order], it[order]
    else:
        mz = it = numpy.zeros(0)
    peaks = [(p.mz + shift, max(p.intensity, 0.0)) for p in scan.peaklist]
    return mz, it, numpy.array(peaks, float).reshape(-1, 2)


def _clean(raw, params):
    """Baseline-free signal above the local noise, and the data limits."""

    nz = numpy.nonzero(raw)[0]
    if not len(nz):
        return numpy.zeros(len(raw)), 0, 0
    first, last = nz[0], nz[-1]
    binw = params["binWidth"]
    w = max(3, int(round(params["baselineWindow"] / binw)))
    base = _runningmean(_runningmax(_runningmin(raw, w), w), w)
    resid = numpy.clip(raw - base, 0, None)
    nw = max(5, int(round(params["noiseWindow"] / binw)))
    noise = _runningmedian(resid, nw, max(1, int(round(1.0 / binw))))
    sig = numpy.clip(resid - params["snr"] * noise, 0, None)
    sig[:first] = 0
    sig[last + 1 :] = 0
    return sig, first, last


def _transform(x, how):
    if how == "sqrt":
        return numpy.sqrt(x)
    if how == "log":
        return numpy.log1p(x)
    return x


def _shift(scan, params):
    if not params["neutralMass"]:
        return 0.0
    if scan.polarity is not None and scan.polarity > 0:
        return -ADDUCTS_POSITIVE[params["posAdduct"]]
    if scan.polarity is not None and scan.polarity < 0:
        return -ADDUCTS_NEGATIVE[params["negAdduct"]]
    raise ValueError(
        "neutralMass needs the polarity of every spectrum (missing in '%s')"
        % scan.title
    )


def _prepare(scans, params):
    shifts = [_shift(s, params) for s in scans]
    data = [_spectrumdata(s, d) for s, d in zip(scans, shifts, strict=True)]
    top = 0.0
    for s, d, (mz, _, pk) in zip(scans, shifts, data, strict=True):
        if s.precursorMZ:
            top = max(top, s.precursorMZ + d)
        elif len(mz):
            top = max(top, mz[-1])
        elif len(pk):
            top = max(top, pk[:, 0].max())
    binw = params["binWidth"]
    n = int(math.ceil((top + 10) / binw)) + 1
    grid = numpy.arange(n) * binw + binw / 2
    sigma = params["tolerance"] / binw
    dil = max(1, int(round(2 * params["tolerance"] / binw)) | 1)

    out = []
    for s, d, (mz, it, pk) in zip(scans, shifts, data, strict=True):
        raw = _resamplemax(mz, it, binw, n)
        prof, first, last = _clean(raw, params)
        if params["source"] == "peaks":
            sig = numpy.zeros(n)
            if len(pk):
                idx = numpy.floor(pk[:, 0] / binw).astype(int)
                ok = (idx >= 0) & (idx < n)
                numpy.maximum.at(sig, idx[ok], pk[ok, 1])
            if not len(mz) and len(pk):
                first = int(pk[:, 0].min() / binw)
                last = int(pk[:, 0].max() / binw)
        else:
            sig = prof
        t = _transform(sig, params["transform"])
        p = _prepared()
        p.scan = s
        p.polarity = s.polarity
        p.precursor = (s.precursorMZ + d) if s.precursorMZ else None
        p.signal = sig
        lo = max(
            params["minMZ"], grid[first] + 1.0 if last > first else params["minMZ"]
        )
        hi = (p.precursor - params["isolation"]) if p.precursor else grid[last]
        p.end = p.precursor if p.precursor else grid[last]
        if params["axes"] == "loss":
            p.mzRange = (0.0, 0.0)
            p.mzVector = numpy.zeros(n)
            p.mzPresent = numpy.zeros(n, bool)
        else:
            p.mzRange = (lo, hi)
            valid = (grid >= lo) & (grid <= hi)
            p.mzVector = _gaussian(t, sigma) * valid
            p.mzPresent = (_runningmax(t, dil) > 0) & valid
        if p.precursor and params["axes"] in ("both", "loss"):
            lt = numpy.interp(p.precursor - grid, grid, t, left=0, right=0)
            valid = (grid >= params["isolation"]) & (grid <= p.precursor - lo)
            p.lossVector = _gaussian(lt, sigma) * valid
            p.lossPresent = (_runningmax(lt, dil) > 0) & valid
            p.lossRange = (params["isolation"], p.precursor - lo)
        else:
            p.lossVector = numpy.zeros(n)
            p.lossPresent = numpy.zeros(n, bool)
            p.lossRange = (0.0, 0.0)
        out.append(p)
    return grid, out


def _weights(grid, prepared, params):
    weights = {}
    for axis in ("mz", "loss"):
        covered = numpy.zeros(len(grid))
        present = numpy.zeros(len(grid))
        for p in prepared:
            lo, hi = getattr(p, axis + "Range")
            covered += (grid >= lo) & (grid <= hi)
            present += getattr(p, axis + "Present")
        if params["weighting"] == "none":
            weights[axis] = numpy.ones(len(grid))
        else:
            weights[axis] = 1.0 + numpy.log((1.0 + covered) / (1.0 + present))
    return weights


def _comparable(a, b, params):
    if params["neutralMass"] or a is None or b is None:
        return True
    return (a > 0) == (b > 0)


# SIMILARITY
# ----------


class similarityresult:
    """Result of similaritymatrix().

    similarity - corrected similarity S (n x n; NaN where not compared)
    cosine - shared-range, weighted cosine before chance correction
    chance - chance level of each pair
    comparable - True where a pair was compared
    labels - spectrum titles
    """

    def __init__(self):
        self.similarity: numpy.ndarray = numpy.zeros((0, 0))
        self.cosine: numpy.ndarray = numpy.zeros((0, 0))
        self.chance: numpy.ndarray = numpy.zeros((0, 0))
        self.comparable: numpy.ndarray = numpy.zeros((0, 0), bool)
        self.labels: list[str] = []
        self.params: dict = {}
        self.grid: numpy.ndarray = numpy.zeros(0)
        self.prepared: list[_prepared] = []
        # (i, j) index arrays of the compared pairs
        self.pairs: tuple[numpy.ndarray, numpy.ndarray] = (
            numpy.zeros(0, int),
            numpy.zeros(0, int),
        )
        # pairs x 7 x blocks, for the bootstrap
        self.blockSums: numpy.ndarray = numpy.zeros((0, 7, 1))


def _scores(sums, chanceCorrection):
    """Cosine, chance and corrected similarity from summed pair statistics."""

    xy, xx, yy, xys, ys2, yxs, xs2 = [sums[..., k] for k in range(7)]
    with numpy.errstate(invalid="ignore", divide="ignore"):
        cos = numpy.nan_to_num(xy / numpy.sqrt(xx * yy))
        e1 = numpy.nan_to_num(xys / numpy.sqrt(xx * ys2))
        e2 = numpy.nan_to_num(yxs / numpy.sqrt(yy * xs2))
    chance = 0.5 * (e1 + e2)
    if not chanceCorrection:
        return cos, chance, cos
    return cos, chance, (cos - chance) / numpy.clip(1 - chance, 1e-6, None)


def similaritymatrix(scans, **params):
    """Corrected similarity of every pair of scans (see the module docstring).

    scans (list of mspy.scan) - spectra; profile, peaklist, polarity and
        precursorMZ are used
    params - see similarityparams()
    """

    params = similarityparams(**params)
    n = len(scans)
    if n < 2:
        raise ValueError("At least two spectra are needed.")
    grid, prepared = _prepare(scans, params)
    weights = _weights(grid, prepared, params)
    binw = params["binWidth"]
    kmin = max(1, int(round(params["lagMin"] / binw)))
    kmax = max(kmin, int(round(params["lagMax"] / binw)))
    nb = int(math.ceil(len(grid) * binw / params["blockSize"])) + 1
    blocks = (grid / params["blockSize"]).astype(int)
    axes = [
        a
        for a in ("mz", "loss")
        if any(getattr(p, a + "Range")[1] > 0 for p in prepared)
    ]

    vecs, smear, smear2 = {}, {}, {}
    for axis in axes:
        V = [weights[axis] * getattr(p, axis + "Vector") for p in prepared]
        vecs[axis] = V
        smear[axis] = [_lagsmear(v, kmin, kmax) for v in V]
        smear2[axis] = [_lagsmear(v * v, kmin, kmax) for v in V]

    pi, pj = [], []
    sums = []
    for i in range(n):
        for j in range(i + 1, n):
            if not _comparable(prepared[i].polarity, prepared[j].polarity, params):
                continue
            acc = numpy.zeros((7, nb * len(axes)))
            for a_i, axis in enumerate(axes):
                lo = max(
                    getattr(prepared[i], axis + "Range")[0],
                    getattr(prepared[j], axis + "Range")[0],
                )
                hi = min(
                    getattr(prepared[i], axis + "Range")[1],
                    getattr(prepared[j], axis + "Range")[1],
                )
                if hi <= lo:
                    continue
                a = int(numpy.searchsorted(grid, lo))
                b = int(numpy.searchsorted(grid, hi, side="right"))
                x, y = vecs[axis][i][a:b], vecs[axis][j][a:b]
                xs, ys = smear[axis][i][a:b], smear[axis][j][a:b]
                xs2, ys2 = smear2[axis][i][a:b], smear2[axis][j][a:b]
                blk = blocks[a:b] + a_i * nb
                for k, val in enumerate(
                    (x * y, x * x, y * y, x * ys, ys2, y * xs, xs2)
                ):
                    acc[k] += numpy.bincount(blk, val, minlength=nb * len(axes))
            pi.append(i)
            pj.append(j)
            sums.append(acc)

    res = similarityresult()
    res.params = params
    res.grid = grid
    res.prepared = prepared
    res.labels = [s.title for s in scans]
    res.pairs = (numpy.array(pi, int), numpy.array(pj, int))
    res.blockSums = (
        numpy.array(sums).reshape(len(pi), 7, -1) if pi else numpy.zeros((0, 7, 1))
    )
    res.similarity = numpy.full((n, n), numpy.nan)
    res.cosine = numpy.full((n, n), numpy.nan)
    res.chance = numpy.full((n, n), numpy.nan)
    res.comparable = numpy.zeros((n, n), bool)
    if pi:
        cos, chance, corr = _scores(
            res.blockSums.sum(axis=-1), params["chanceCorrection"]
        )
        for M, v in ((res.similarity, corr), (res.cosine, cos), (res.chance, chance)):
            M[res.pairs] = v
            M[res.pairs[::-1]] = v
        res.comparable[res.pairs] = True
        res.comparable[res.pairs[::-1]] = True
    numpy.fill_diagonal(res.similarity, 1.0)
    numpy.fill_diagonal(res.cosine, 1.0)
    numpy.fill_diagonal(res.comparable, True)
    return res


def bootstrapmatrices(result, replicates, seed=1):
    """Yield similarity matrices recomputed from resampled blocks."""

    n = len(result.labels)
    sums = result.blockSums
    if not len(sums):
        return
    informative = numpy.nonzero(sums[:, 1, :].sum(axis=0) > 0)[0]
    rng = numpy.random.default_rng(seed)
    for _ in range(replicates):
        draw = rng.choice(informative, size=len(informative), replace=True)
        counts = numpy.bincount(draw, minlength=sums.shape[-1]).astype(float)
        _, _, corr = _scores(sums @ counts, result.params["chanceCorrection"])
        S = numpy.full((n, n), numpy.nan)
        S[result.pairs] = corr
        S[result.pairs[::-1]] = corr
        numpy.fill_diagonal(S, 1.0)
        yield S


def rangedependence(result, near=10.0):
    """Spearman rho of pair similarity against |log2| of the range ratio,
    for all compared pairs and for pairs whose ranges differ by > near Da."""

    ends = numpy.array([p.end for p in result.prepared], float)
    i, j = result.pairs
    if not len(i):
        return float("nan"), float("nan")
    with numpy.errstate(divide="ignore", invalid="ignore"):
        d = numpy.abs(numpy.log2(ends[i] / ends[j]))
    s = result.similarity[i, j]
    ok = numpy.isfinite(d) & numpy.isfinite(s)
    apart = ok & (numpy.abs(ends[i] - ends[j]) > near)
    return _spearman(d[ok], s[ok]), _spearman(d[apart], s[apart])


# SHARED FEATURES
# ---------------


def _localmaxima(score, distance):
    """Indices of local maxima, at least `distance` points apart (taller first)."""

    if len(score) < 3:
        return []
    left = numpy.r_[-numpy.inf, score[:-1]]
    right = numpy.r_[score[1:], -numpy.inf]
    cand = numpy.nonzero((score > left) & (score >= right))[0]
    kept = []
    for k in cand[numpy.argsort(-score[cand], kind="mergesort")]:
        if all(abs(k - q) >= distance for q in kept):
            kept.append(int(k))
    return kept


def sharedfeatures(result, members, top=16, gap=1.35):
    """Fragment ions and neutral losses shared by `members`, rarer elsewhere.

    Returns {'mz': [...], 'loss': [...]}; each item is a dict with position,
    positions (merged neighbours closer than `gap` Da, e.g. isotopes), score,
    members/covered (members with signal / covering it), others/othersCovered,
    and for losses 'mirror' (the m/z it mirrors when all members share one
    precursor) or None.
    """

    members = list(members)
    grid = result.grid
    binw = result.params["binWidth"]
    n = len(result.prepared)
    others = [i for i in range(n) if i not in members]
    out = {"mz": [], "loss": []}
    for axis in ("mz", "loss"):
        vec, cov, pres = [], [], []
        for p in result.prepared:
            v = getattr(p, axis + "Vector")
            nv = numpy.linalg.norm(v)
            vec.append(v / nv if nv else v)
            lo, hi = getattr(p, axis + "Range")
            cov.append((grid >= lo) & (grid <= hi))
            pres.append(getattr(p, axis + "Present"))
        vec, cov, pres = numpy.array(vec), numpy.array(cov), numpy.array(pres)
        cin = cov[members].sum(0)
        minCov = max(2, int(math.ceil(0.5 * len(members))))
        with numpy.errstate(invalid="ignore", divide="ignore"):
            meanIn = numpy.where(
                cin > 0, vec[members].sum(0) / numpy.maximum(cin, 1), 0
            )
            fracIn = numpy.where(
                cin > 0, pres[members].sum(0) / numpy.maximum(cin, 1), 0
            )
            if others:
                cout = cov[others].sum(0)
                meanOut = numpy.where(
                    cout > 0, vec[others].sum(0) / numpy.maximum(cout, 1), 0
                )
                presOut = pres[others].sum(0)
            else:
                cout = numpy.zeros(len(grid))
                meanOut = numpy.zeros(len(grid))
                presOut = numpy.zeros(len(grid))
        score = (meanIn - meanOut) * (cin >= minCov)
        idx = [
            k
            for k in _localmaxima(score, max(1, int(round(0.6 / binw))))
            if fracIn[k] >= 0.5 and score[k] > 0
        ]
        idx = idx[:top]
        rows = []
        for k in sorted(idx, key=lambda k: grid[k]):
            a, b = max(0, k - 3), k + 4
            w = meanIn[a:b]
            pos = (
                float((grid[a:b] * w).sum() / w.sum())
                if w.sum() > 0
                else float(grid[k])
            )
            rows.append(
                {
                    "position": pos,
                    "score": float(score[k]),
                    "members": int(round(float(fracIn[k] * cin[k]))),
                    "covered": int(cin[k]),
                    "others": int(presOut[k]) if others and cout[k] > 0 else None,
                    "othersCovered": int(cout[k]) if others else 0,
                }
            )
        out[axis] = _groupfeatures(rows, gap)

    precs = [
        result.prepared[i].precursor for i in members if result.prepared[i].precursor
    ]
    for f in out["loss"]:
        f["mirror"] = None
    if precs and len(precs) == len(members) and max(precs) - min(precs) <= 1.0:
        P = float(numpy.mean(precs))
        for f in out["loss"]:
            for g in out["mz"]:
                if any(abs(P - f["position"] - x) <= 0.6 for x in g["positions"]):
                    f["mirror"] = g["position"]
                    break
    return out


def _groupfeatures(rows, gap):
    groups = []
    for r in rows:
        if groups and r["position"] - groups[-1][-1]["position"] <= gap:
            groups[-1].append(r)
        else:
            groups.append([r])
    out = []
    for g in groups:
        best = dict(max(g, key=lambda r: r["score"]))
        best["positions"] = [r["position"] for r in g]
        best["members"] = max(r["members"] for r in g)
        out.append(best)
    return out
