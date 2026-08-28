import numpy as np
from numba import njit, prange


def signal_interpolate_x(x1, y1, x2, y2, y):
    if x1 == x2:
        return x1
    a = (y2 - y1) / (x2 - x1)
    if a == 0:
        return (x1 + x2) / 2.0
    b = y1 - a * x1
    return (y - b) / a


def signal_interpolate_y(x1, y1, x2, y2, x):
    if y1 == y2:
        return y1
    a = (y2 - y1) / (x2 - x1)
    b = y1 - a * x1
    return a * x + b


def signal_locate_x(array, x):
    """Find index using binary search equivalent logic"""
    # Assuming array is a 2D array where array[:, 0] are X values
    return np.searchsorted(array[:, 0], x)


def signal_locate_max_y(array):
    return np.argmax(array[:, 1])


def signal_box(array):
    """Returns exactly what signal_box structure returned"""
    return {
        "minX": float(array[0, 0]),
        "maxX": float(array[-1, 0]),
        "minY": float(np.min(array[:, 1])),
        "maxY": float(np.max(array[:, 1])),
    }


def signal_crop(array, x1, x2):
    idx1 = np.searchsorted(array[:, 0], x1, side="left")
    idx2 = np.searchsorted(array[:, 0], x2, side="right")

    # Ensure there's at least one point outside the viewport on both sides for drawing lines
    if idx1 > 0:
        idx1 -= 1
    if idx2 < len(array):
        idx2 += 1

    return array[idx1:idx2]


def signal_offset(array, offsetX, offsetY):
    out = np.empty_like(array)
    out[:, 0] = array[:, 0] + offsetX
    out[:, 1] = array[:, 1] + offsetY
    return out


def signal_multiply(array, factorX, factorY):
    out = np.empty_like(array)
    out[:, 0] = array[:, 0] * factorX
    out[:, 1] = array[:, 1] * factorY
    return out


def signal_normalize(array):
    out = array.copy()
    max_y = np.max(out[:, 1])
    if max_y != 0.0:
        out[:, 1] = (out[:, 1] / max_y) * 100.0
    return out


@njit
def _local_maxima_indices(y):
    """Indices of the local maxima of a 1-D array.

    Reproduces ``scipy.signal.find_peaks(y)`` called with no keyword arguments,
    which is all this module ever needed it for: a sample is a maximum when it
    is strictly higher than its two neighbours, a flat plateau counts once and
    reports its middle sample, and the first and last samples can never be
    maxima. Written out here so the Windows bundle does not have to carry the
    ~70 MB of SciPy for this one function.
    """

    n = len(y)
    out = np.empty(n // 2, np.int64)  # a maximum needs a gap: at most n//2 fit
    found = 0

    i = 1
    i_max = n - 1
    while i < i_max:
        if y[i - 1] < y[i]:
            # Walk over a plateau of equal samples, if there is one.
            ahead = i + 1
            while ahead < i_max and y[ahead] == y[i]:
                ahead += 1
            if y[ahead] < y[i]:
                out[found] = (i + ahead - 1) // 2
                found += 1
                i = ahead
        i += 1

    return out[:found]


def signal_local_maxima(array):
    return array[_local_maxima_indices(np.ascontiguousarray(array[:, 1]))].tolist()


def formula_composition(minimum, maximum, masses, loMass, hiMass, limit):
    elcount = len(minimum)
    results = []

    def generator(pos, current, current_mass):
        if pos == elcount:
            if loMass <= current_mass <= hiMass and len(results) < limit:
                results.append(list(current))
            return

        current[pos] = minimum[pos]
        while current[pos] <= maximum[pos]:
            if current_mass > hiMass or len(results) >= limit:
                break

            generator(pos + 1, current, current_mass)
            current_mass += masses[pos]
            current[pos] += 1

    current = [0] * elcount
    base_mass = sum(min_val * mass for min_val, mass in zip(minimum, masses, strict=True))
    generator(0, current, base_mass)

    if len(results) == 0:
        return None
    # Original C module returns an m_arrayi. Let's return a list of tuples or lists.
    # To match python side unpacking which expects tuples/lists.
    return tuple(tuple(r) for r in results)




@njit
def signal_intensity(array, x):
    idx = np.searchsorted(array[:, 0], x)
    if idx == 0 or idx == len(array):
        return 0.0
    x1, y1 = array[idx - 1, 0], array[idx - 1, 1]
    x2, y2 = array[idx, 0], array[idx, 1]
    if x1 == x2:
        return y1
    a = (y2 - y1) / (x2 - x1)
    b = y1 - a * x1
    return a * x + b


@njit
def signal_centroid(array, x, height):
    idx = np.searchsorted(array[:, 0], x)
    if idx == 0 or idx == len(array):
        return 0.0

    ileft = idx - 1
    while ileft > 0 and array[ileft, 1] > height:
        ileft -= 1

    iright = idx
    while iright < len(array) - 1 and array[iright, 1] > height:
        iright += 1

    if ileft == iright:
        return array[ileft, 0]

    # Simplified approximation of the centroid formula
    area = 0.0
    centroid = 0.0
    for i in range(ileft, iright):
        x1, y1 = array[i, 0], array[i, 1]
        x2, y2 = array[i + 1, 0], array[i + 1, 1]
        a = (x2 - x1) * (y1 + y2) / 2.0
        area += a
        centroid += a * (x1 + x2) / 2.0

    if area == 0:
        return array[idx, 0]
    return centroid / area


@njit
def _median1d(a):
    """Median of a 1-D array (Numba-friendly, avoids np.median dependency)."""
    b = np.sort(a)
    k = len(b)
    if k == 0:
        return 0.0
    if k % 2 == 1:
        return b[k // 2]
    return 0.5 * (b[k // 2 - 1] + b[k // 2])


@njit
def _flank_halfwidth(array, apex, apex_x, apex_h, level, direction):
    """Interpolated apex-to-`level` distance along one flank.

    Walks outward from `apex` in `direction` (+1 right, -1 left) to the first
    sample at or below `level`, then linearly interpolates the exact crossing.
    Returns 0.0 (an invalid sentinel) when the flank is obscured -- it climbs a
    higher-than-apex neighbour, or runs off the end of the array, before it
    crosses -- so an overlapping/merged side is dropped from the estimate.
    """
    n = len(array)
    prev_x = apex_x
    prev_y = apex_h
    i = apex + direction
    while 0 <= i < n:
        y = array[i, 1]
        x = array[i, 0]
        if y > apex_h * 1.01:
            return 0.0
        if y <= level:
            if prev_y == y:
                cross_x = x
            else:
                t = (prev_y - level) / (prev_y - y)
                cross_x = prev_x + t * (x - prev_x)
            d = cross_x - apex_x
            return d if d >= 0.0 else -d
        prev_x = x
        prev_y = y
        i += direction
    return 0.0


@njit
def signal_width(array, x, height):
    """Robust FWHM of the peak nearest `x`.

    Reading the width at the single half-maximum crossing is fragile: one noisy
    sample, the sampling grid, or a neighbour merging into one flank throws it
    off. Instead probe BOTH flanks at several relative heights and, assuming a
    locally Gaussian peak, convert each half-width into an implied sigma
    (half-width d at fraction f of the peak satisfies d = sigma*sqrt(-2 ln f)).
    The MEDIAN of all valid probes is returned as FWHM, so an overlapping
    neighbour -- which only inflates the low-level widths on the affected flank
    -- is rejected as an outlier instead of blowing up the width. `height` is the
    half-maximum the caller measured, which pins the baseline via
    height = base + 0.5*(apex - base).
    """
    n = len(array)
    idx = np.searchsorted(array[:, 0], x)
    if idx <= 0 or idx >= n:
        return 0.0

    # snap to the nearer of the two bracketing samples -> apex
    if abs(array[idx - 1, 0] - x) < abs(array[idx, 0] - x):
        idx = idx - 1
    apex_x = array[idx, 0]
    apex_h = array[idx, 1]

    # recover the baseline implied by the caller's half-max height
    base = 2.0 * height - apex_h
    if base < 0.0:
        base = 0.0
    span = apex_h - base
    if span <= 0.0:
        return 0.0

    # relative heights to probe, kept away from the apex and the baseline where
    # the Gaussian half-width -> sigma mapping is ill-conditioned
    fracs = (0.75, 0.65, 0.55, 0.45, 0.35, 0.25)
    nf = len(fracs)
    lest = np.empty(nf, dtype=np.float64)
    rest = np.empty(nf, dtype=np.float64)
    lm = 0
    rm = 0
    for fi in range(nf):
        f = fracs[fi]
        level = base + f * span
        denom = np.sqrt(-2.0 * np.log(f))  # d = sigma * sqrt(-2 ln f)
        dl = _flank_halfwidth(array, idx, apex_x, apex_h, level, -1)
        if dl > 0.0:
            lest[lm] = dl / denom
            lm += 1
        dr = _flank_halfwidth(array, idx, apex_x, apex_h, level, 1)
        if dr > 0.0:
            rest[rm] = dr / denom
            rm += 1

    if lm == 0 and rm == 0:
        return 0.0

    # Aggregate each flank separately (median over levels rejects per-flank
    # noise), then combine. When the two flanks disagree strongly one of them is
    # merged with a neighbour, so trust the narrower (clean) flank; otherwise the
    # peak is roughly symmetric and both flanks are averaged for a steadier value.
    if lm > 0 and rm > 0:
        sl = _median1d(lest[:lm])
        sr = _median1d(rest[:rm])
        lo = sl if sl < sr else sr
        hi = sr if sl < sr else sl
        # instrument peaks are near-symmetric at half-max, so >20% flank
        # disagreement means one side is merged with a neighbour -> trust the
        # narrower (clean) flank; otherwise average the two for a steadier value
        sigma = lo if hi > 1.2 * lo else 0.5 * (sl + sr)
    elif lm > 0:
        sigma = _median1d(lest[:lm])
    else:
        sigma = _median1d(rest[:rm])

    # FWHM = 2 * sqrt(2 ln 2) * sigma
    return 2.3548200450309493 * sigma


def signal_area(array):
    # a cropped-to-nothing signal arrives as an empty (or 1-D) array
    if array.ndim < 2 or len(array) < 2:
        return 0.0
    return float(np.trapezoid(array[:, 1], array[:, 0]))


def signal_combine(array1, array2):
    empty1 = array1.ndim < 2 or len(array1) == 0
    empty2 = array2.ndim < 2 or len(array2) == 0
    if empty1 and empty2:
        return np.empty((0, 2), dtype=np.float64)
    if empty1:
        return array2.copy()
    if empty2:
        return array1.copy()
    x_all = np.union1d(array1[:, 0], array2[:, 0])
    y1 = np.interp(x_all, array1[:, 0], array1[:, 1], left=0.0, right=0.0)
    y2 = np.interp(x_all, array2[:, 0], array2[:, 1], left=0.0, right=0.0)
    return np.column_stack((x_all, y1 + y2))


def signal_overlay(array1, array2):
    empty1 = array1.ndim < 2 or len(array1) == 0
    empty2 = array2.ndim < 2 or len(array2) == 0
    if empty1 and empty2:
        return np.empty((0, 2), dtype=np.float64)
    if empty1:
        return array2.copy()
    if empty2:
        return array1.copy()
    x_all = np.union1d(array1[:, 0], array2[:, 0])
    y1 = np.interp(x_all, array1[:, 0], array1[:, 1], left=0.0, right=0.0)
    y2 = np.interp(x_all, array2[:, 0], array2[:, 1], left=0.0, right=0.0)
    return np.column_stack((x_all, np.maximum(y1, y2)))


def signal_subtract(array1, array2):
    if array1.ndim < 2 or len(array1) == 0:
        return np.empty((0, 2), dtype=np.float64)
    if array2.ndim < 2 or len(array2) == 0:
        return array1.copy()
    out = array1.copy()
    y2_interp = np.interp(out[:, 0], array2[:, 0], array2[:, 1], left=0, right=0)
    out[:, 1] = out[:, 1] - y2_interp
    return out


def signal_subbase(array1, baseline, allowNegative=False):
    out = array1.copy()
    y_base = np.interp(out[:, 0], baseline[:, 0], baseline[:, 1], left=0, right=0)
    out[:, 1] = out[:, 1] - y_base
    if not allowNegative:
        out[:, 1] = np.clip(out[:, 1], 0, None)
    return out


@njit
def signal_filter(array, resol):
    n = len(array)
    if n == 0:
        return np.empty((0, 2), dtype=np.float64)

    buff = np.empty((n * 4, 2), dtype=np.float64)

    buff[0, 0] = array[0, 0]
    buff[0, 1] = array[0, 1]

    lastX = previousX = array[0, 0]
    minY = maxY = previousY = array[0, 1]
    minX = maxX = array[0, 0]
    count = 1

    for i in range(1, n):
        currentX = array[i, 0]
        currentY = array[i, 1]

        if (currentX - lastX) >= resol or i == n - 1:

            if minX <= maxX:
                if buff[count - 1, 0] != minX or buff[count - 1, 1] != minY:
                    buff[count, 0] = minX
                    buff[count, 1] = minY
                    count += 1
                if buff[count - 1, 0] != maxX or buff[count - 1, 1] != maxY:
                    buff[count, 0] = maxX
                    buff[count, 1] = maxY
                    count += 1
            else:
                if buff[count - 1, 0] != maxX or buff[count - 1, 1] != maxY:
                    buff[count, 0] = maxX
                    buff[count, 1] = maxY
                    count += 1
                if buff[count - 1, 0] != minX or buff[count - 1, 1] != minY:
                    buff[count, 0] = minX
                    buff[count, 1] = minY
                    count += 1

            # add last point in range
            if buff[count - 1, 0] != previousX or buff[count - 1, 1] != previousY:
                buff[count, 0] = previousX
                buff[count, 1] = previousY
                count += 1

            # add current point
            buff[count, 0] = currentX
            buff[count, 1] = currentY
            count += 1

            lastX = previousX = currentX
            minY = maxY = previousY = currentY
            minX = maxX = currentX
        else:
            if currentY < minY:
                minY = currentY
                minX = currentX
            if currentY > maxY:
                maxY = currentY
                maxX = currentX
            previousX = currentX
            previousY = currentY

    return buff[:count].copy()


@njit(cache=True, fastmath=True, parallel=True)
def signal_rescale(array, scaleX, scaleY, shiftX, shiftY):
    n = len(array)
    out = np.empty((n, 2), dtype=np.int32)
    for i in prange(n):
        out[i, 0] = int(round(array[i, 0] * scaleX + shiftX))
        out[i, 1] = int(round(array[i, 1] * scaleY + shiftY))
    return out


def signal_gaussian(x, minY, maxY, fwhm, points):
    minX = x - (5 * fwhm)
    maxX = x + (5 * fwhm)
    amplitude = maxY - minY

    f = (fwhm / 1.66) * (fwhm / 1.66)
    xs = np.linspace(minX, maxX, points)
    ys = minY + amplitude * np.exp(-((xs - x) ** 2) / f)

    return np.column_stack((xs, ys))


def signal_lorentzian(x, minY, maxY, fwhm, points):
    minX = x - (10 * fwhm)
    maxX = x + (10 * fwhm)
    amplitude = maxY - minY

    f = (fwhm / 2.0) * (fwhm / 2.0)
    xs = np.linspace(minX, maxX, points)
    ys = minY + amplitude / (1.0 + ((xs - x) ** 2) / f)

    return np.column_stack((xs, ys))


def signal_gausslorentzian(x, minY, maxY, fwhm, points):
    # Fast rough equivalent
    g = signal_gaussian(x, minY, maxY, fwhm, points)
    lor = signal_lorentzian(x, minY, maxY, fwhm, points)
    return np.column_stack((g[:, 0], 0.5 * g[:, 1] + 0.5 * lor[:, 1]))


@njit
def signal_profile_raster(p_peaks, points):
    minX = p_peaks[0, 0]
    maxX = p_peaks[0, 0]
    minFwhm = p_peaks[0, 2]
    maxFwhm = p_peaks[0, 2]

    n = len(p_peaks)
    for i in range(1, n):
        if p_peaks[i, 0] < minX:
            minX = p_peaks[i, 0]
        if p_peaks[i, 0] > maxX:
            maxX = p_peaks[i, 0]
        if p_peaks[i, 2] < minFwhm:
            minFwhm = p_peaks[i, 2]
        if p_peaks[i, 2] > maxFwhm:
            maxFwhm = p_peaks[i, 2]

    minX -= 5 * maxFwhm
    maxX += 5 * maxFwhm

    step = minFwhm / points
    size = int((maxX - minX) / step)
    if size <= 0:
        return np.empty(0, dtype=np.float64)

    if maxX - minX != 0:
        a = (maxFwhm / points - minFwhm / points) / (maxX - minX)
    else:
        a = 0.0
    b = minFwhm / points - a * minX

    buff = np.empty(size, dtype=np.float64)
    count = 0
    x = minX
    while x < maxX and count < size:
        buff[count] = x
        x += a * x + b
        count += 1

    return buff[:count].copy()


@njit
def signal_profile_to_raster(p_peaks, p_raster, noise, shape):
    if len(p_peaks) == 0 or len(p_raster) == 0:
        return np.empty((0, 2), dtype=np.float64)

    p_profile = np.empty((len(p_raster), 2), dtype=np.float64)
    for i in range(len(p_raster)):
        p_profile[i, 0] = p_raster[i]
        p_profile[i, 1] = 0.0

    for i in range(len(p_peaks)):
        mz = p_peaks[i, 0]
        intens = p_peaks[i, 1]
        fwhm = p_peaks[i, 2]

        if shape == 0:
            minX = mz - (5 * fwhm)
            maxX = mz + (5 * fwhm)
            idx1 = np.searchsorted(p_profile[:, 0], minX)
            idx2 = np.searchsorted(p_profile[:, 0], maxX)

            f = (fwhm / 1.66) * (fwhm / 1.66)
            for j in range(idx1, idx2):
                p_profile[j, 1] += intens * np.exp(-((p_profile[j, 0] - mz) ** 2) / f)

        elif shape == 1:
            minX = mz - (10 * fwhm)
            maxX = mz + (10 * fwhm)
            idx1 = np.searchsorted(p_profile[:, 0], minX)
            idx2 = np.searchsorted(p_profile[:, 0], maxX)

            f = (fwhm / 2.0) * (fwhm / 2.0)
            for j in range(idx1, idx2):
                p_profile[j, 1] += intens / (1.0 + ((p_profile[j, 0] - mz) ** 2) / f)

        elif shape == 2:
            minX = mz - (5 * fwhm)
            maxX = mz + (10 * fwhm)
            idx1 = np.searchsorted(p_profile[:, 0], minX)
            idx2 = np.searchsorted(p_profile[:, 0], maxX)

            f_g = (fwhm / 1.66) * (fwhm / 1.66)
            f_l = (fwhm / 2.0) * (fwhm / 2.0)
            for j in range(idx1, idx2):
                if p_profile[j, 0] < mz:
                    p_profile[j, 1] += intens * np.exp(
                        -((p_profile[j, 0] - mz) ** 2) / f_g
                    )
                else:
                    p_profile[j, 1] += intens / (
                        1.0 + ((p_profile[j, 0] - mz) ** 2) / f_l
                    )

    if noise != 0:
        for i in range(len(p_profile)):
            p_profile[i, 1] += noise * np.random.rand() - noise / 2

    return p_profile


def signal_profile(mpeaks, points, noise, shape):
    raster = signal_profile_raster(mpeaks, points)
    return signal_profile_to_raster(mpeaks, raster, noise, shape)


@njit
def peaklist_filter_indices(array, resol):
    n = len(array)
    if n == 0:
        return np.empty(0, dtype=np.int64)

    keep = np.empty(n, dtype=np.int64)
    count = 0

    lastX = array[0, 0]
    maxY = array[0, 1]
    maxIdx = 0

    for i in range(1, n):
        currentX = array[i, 0]
        currentY = array[i, 1]

        if (currentX - lastX) >= resol:
            keep[count] = maxIdx
            count += 1
            lastX = currentX
            maxY = currentY
            maxIdx = i
        else:
            if currentY > maxY:
                maxY = currentY
                maxIdx = i

    keep[count] = maxIdx
    count += 1

    return keep[:count].copy()
