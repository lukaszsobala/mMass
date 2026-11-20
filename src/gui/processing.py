"""Spectrum processing steps shared by the Processing panel and mmass process.

Every function takes the processing settings as an argument, shaped like
config.processing, so the command line can run with a changed copy of them
without touching the user's configuration.
"""

import copy

import numpy

import mspy


# THE BASELINE PEAKS ARE MEASURED FROM
#
# Every measurement -- picked peak heights and S/N, the labelling tools, the
# ruler area, envelope fitting -- reads the baseline at its TRUE local level,
# smoothed as the baseline panel's precision says. The panel's relative offset
# is not a property of the data but a choice about the PROFILE: how far below
# the baseline "Subtract Baseline" cuts, so some noise stays visible above zero.
# Keeping it out of the measurements means a spectrum subtracted at any offset,
# or not at all, gives the same heights, and the offset never has to be changed
# back just to pick peaks.
MEASUREMENT_BASELINE_OFFSET = 0.0


def baselineWindow(settings):
    """Noise window of the baseline (relative), from the baseline panel's precision."""

    return 1.0 / settings["baseline"]["precision"]


def measurementBaseline(scan, settings):
    """The baseline peaks in `scan` are measured from (see above)."""

    return scan.baseline(
        window=baselineWindow(settings), offset=MEASUREMENT_BASELINE_OFFSET
    )


# NOTATIONS FOLLOW THE SPECTRUM
#
# Annotations, sequence matches and difference rulers mark places in the
# spectrum: an m/z, and the intensity their label stands at. No processing step
# deletes them (only cropping drops those outside the range kept). A step that
# moves the m/z axis -- calibration -- moves them along, and one that changes
# intensities carries them as mspy carries the peaks it keeps (preservePeaks):
# the baseline is taken off them, smoothing and combining read the new profile
# under them, and normalizing, multiplying and square-rooting apply to them as
# to the profile. Otherwise a label would hang where the peak used to stand --
# far off the plot after normalizing -- and its reported intensity be stale.


def _notationsOn(document, scan):
    """(points, rulers): the annotations and sequence matches, and the
    difference rulers, drawn on scan -- one of the document's spectra."""

    if document is None:
        return [], []
    shown = scan is document.spectrum
    points = []
    if shown:
        points = list(document.annotations)
        for sequence in document.sequences:
            points += sequence.matches
        key = document.shownScanKey()
    else:
        key = next((k for k, v in document.scanCache.items() if v is scan), None)
        if key is None:
            return points, []
    rulers = [
        ruler
        for ruler in document.rulers
        if ruler.scanID == key or (shown and ruler.scanID is None)
    ]
    return points, rulers


def carryNotations(document, scan, intensity, height=None):
    """Carry the notations drawn on scan through a change of its intensities.

    intensity(mz, ai, base) takes and returns numpy arrays: the new label
    intensities and baselines at those m/z. height(value) changes a ruler's
    hand-set bar height, which is left alone without it.
    """

    points, rulers = _notationsOn(document, scan)
    if points:
        mz = numpy.array([p.mz for p in points], dtype=float)
        ai = numpy.array([p.ai for p in points], dtype=float)
        base = numpy.array([p.base for p in points], dtype=float)
        ai, base = intensity(mz, ai, base)
        for point, a, b in zip(points, ai, base, strict=True):
            point.ai = float(a)
            point.base = float(b)
    if rulers:
        mz = numpy.array([r.mz1 for r in rulers] + [r.mz2 for r in rulers], dtype=float)
        ai = numpy.array([r.ai1 for r in rulers] + [r.ai2 for r in rulers], dtype=float)
        ai, _base = intensity(mz, ai, numpy.zeros(len(mz)))
        for i, ruler in enumerate(rulers):
            ruler.ai1 = float(ai[i])
            ruler.ai2 = float(ai[i + len(rulers)])
            if height is not None and ruler.height is not None:
                ruler.height = float(height(ruler.height))


def _scaled(fn):
    """An intensity change applying fn to every intensity alike."""

    return lambda mz, ai, base: (fn(ai), fn(base)), fn


def _readFrom(profile):
    """An intensity change reading the label heights off the new profile."""

    def intensity(mz, ai, base):
        return numpy.interp(mz, profile[:, 0], profile[:, 1]), base

    return intensity


def recalibrateNotations(document, fn, params):
    """Move the notations drawn on the spectrum shown by a calibration."""

    points, rulers = _notationsOn(document, document.spectrum)
    for point in points:
        point.mz = fn(params, point.mz)
    for ruler in rulers:
        ruler.mz1 = float(fn(params, ruler.mz1))
        ruler.mz2 = float(fn(params, ruler.mz2))


def cropDocument(document, lowMass, highMass):
    """Crop a document's spectrum and the notations outside the range."""

    document.spectrum.crop(lowMass, highMass)
    cropNotations(document, lowMass, highMass)


def cropNotations(document, lowMass, highMass):
    """Remove a document's notations outside an m/z range."""

    document.annotations[:] = [
        annotation
        for annotation in document.annotations
        if lowMass <= annotation.mz <= highMass
    ]
    for sequence in document.sequences:
        sequence.matches[:] = [
            match for match in sequence.matches if lowMass <= match.mz <= highMass
        ]
    document.rulers[:] = [
        ruler
        for ruler in document.rulers
        if lowMass <= ruler.mz1 and ruler.mz2 <= highMass
    ]


# math operations of the Processing panel that need no other spectrum
SINGLE_SPECTRUM_MATH = ("normalize", "multiply", "squareroot")


def _signedRoot(values):
    """Square root keeping the sign, as mspy takes it of peaks."""

    return numpy.sign(values) * numpy.sqrt(numpy.abs(values))


def mathScan(scan, operation, settings, document=None):
    """Apply a single-spectrum math operation to a scan's profile and peaks,
    and to the notations of document drawn on it."""

    if operation == "normalize":
        factor = scan.normalization()
        scan.normalize()
        intensity, height = _scaled(lambda values: values / factor)
    elif operation == "multiply":
        y = settings["math"]["multiplier"]
        scan.multiply(y=y)
        intensity, height = _scaled(lambda values: values * y)
    elif operation == "squareroot":
        scan.squareroot(preservePeaks=bool(settings["math"]["preservePeaks"]))
        intensity, height = _scaled(_signedRoot)
    else:
        raise ValueError(f"{operation} needs more than one spectrum")
    carryNotations(document, scan, intensity, height)


# math operations of the Processing panel that take a second spectrum
PAIR_MATH = ("combine", "overlay", "subtract")


def mathPair(scan, operation, other, preservePeaks, document=None):
    """Combine, overlay or subtract another spectrum, carrying the notations
    of document drawn on scan."""

    if operation not in PAIR_MATH:
        raise ValueError(f"{operation} takes no second spectrum")
    getattr(scan, operation)(other, preservePeaks=preservePeaks)
    if scan.hasprofile():
        carryNotations(document, scan, _readFrom(scan.profile))


def combineSpectra(scans, average=True):
    """Average or sum whole spectra, e.g. those of the visible documents.

    The same combining as for the scans under a chromatogram range
    (mspy.combinescans), minus alignment and the sampling check, as the user
    chose these spectra: an average divides each m/z by the spectra covering
    it, and centroided spectra are merged peak by peak. Returns (combined scan,
    indexes of the scans used), or (None, []) when no scan has data.
    """

    return mspy.combinescans(scans, average=average, align=False, sampling=False)


def peakSticks(peaklist):
    """Peaks as points of one line, rising from zero to each peak and back."""

    if not len(peaklist):
        return numpy.array([])

    points = numpy.zeros((3 * len(peaklist), 2))
    points[:, 0] = numpy.repeat([peak.mz for peak in peaklist], 3)
    points[1::3, 1] = [peak.ai for peak in peaklist]
    return points


def previewPoints(scan):
    """Points to preview a spectrum by: its profile, or its peaks as sticks
    when it has none (centroided data)."""

    if scan.hasprofile():
        return scan.profile
    return peakSticks(scan.peaklist)


def previewPair(operation, scanA, scanB):
    """Preview points of Combine A+B, Overlay A,B or Subtract B, as applying
    them would give; centroided spectra are combined peak by peak."""

    if operation == "combine" and not (scanA.hasprofile() or scanB.hasprofile()):
        merged = mspy.mergecentroids([scanA.peaklist, scanB.peaklist], average=False)
        return peakSticks(merged)

    signal = {"combine": mspy.combine, "overlay": mspy.overlay, "subtract": mspy.subtract}
    return signal[operation](scanA.profile, scanB.profile)


def subtractBaseline(scan, settings, document=None):
    """Subtract the baseline from a scan's profile, and from the notations of
    document drawn on it."""

    window = baselineWindow(settings)
    offset = settings["baseline"]["offset"]
    allowNegative = settings["baseline"]["allowNegative"]
    baseline = scan.baseline(window=window, offset=offset)  # kept for subbase
    scan.subbase(
        window=window,
        offset=offset,
        allowNegative=allowNegative,
        preservePeaks=bool(settings["baseline"]["preservePeaks"]),
    )

    def intensity(mz, ai, base):
        level = numpy.interp(mz, baseline[:, 0], baseline[:, 1])
        ai = ai - level
        if not allowNegative:
            ai = numpy.maximum(ai, 0.0)
        return ai, numpy.maximum(base - level, 0.0)

    if len(baseline):
        carryNotations(document, scan, intensity)


def smoothScan(scan, settings, document=None):
    """Smooth a scan's profile, carrying the notations of document drawn on it."""

    scan.smooth(
        method=settings["smoothing"]["method"],
        window=settings["smoothing"]["windowSize"],
        cycles=int(settings["smoothing"]["cycles"]),
        preservePeaks=bool(settings["smoothing"]["preservePeaks"]),
    )
    if scan.hasprofile():
        carryNotations(document, scan, _readFrom(scan.profile))


def _labelEnvelopes(scan, settings):
    """Turn deisotoped peaks into envelopes, as "Convert to Envelopes" does.

    Each deisotoped seed becomes its own clean single-species envelope:
    overlapping neighbours are never absorbed or fused into an irregular merged
    grid, and the joint fit apportions shared signal. Deisotoping itself is
    unchanged, so this does not produce a peak per isotope.
    """

    deisotoping = settings["deisotoping"]
    scan.labelenvelopes(
        label=deisotoping["labelEnvelope"],
        intensity=deisotoping["envelopeIntensity"],
        mzTolerance=deisotoping["massTolerance"],
        isotopeShift=deisotoping["isotopeShift"],
        nonIdeality=deisotoping.get("envelopeNonIdeality"),
        averagineType=settings["peakpicking"]["averagineType"],
        refinePattern=bool(deisotoping.get("envelopeRefinePattern", 1)),
        preserveSeeds=True,
        relaxed=True,
    )


def signedCharge(charge, polarity):
    """A charge with the sign of the scan's polarity.

    Charges are signed: negative in negative mode, so that the neutral mass of
    a peak comes out right ([M-H]- rather than [M+H]+). A known polarity
    decides the sign; without one the charge is kept as given (a negative
    max. charge typed by hand for a spectrum of unknown polarity).
    """

    if polarity in (1, -1) and charge:
        return abs(charge) * polarity
    return charge


def polarityCorrected(peaklist, polarity):
    """The peak list with every charge of the wrong sign for the polarity
    corrected (e.g. envelopes labelled +1 in a negative-mode spectrum before
    the charges were signed).

    A new peak list whose corrected peaks are copies, so the document's peaks
    stay as they are until the result is applied (and the undo step taken);
    the same object when nothing needs correcting.
    """

    if polarity not in (1, -1):
        return peaklist
    wrong = [
        i
        for i, peak in enumerate(peaklist)
        if peak.charge and signedCharge(peak.charge, polarity) != peak.charge
    ]
    if not wrong:
        return peaklist

    peaks = list(peaklist)
    for i in wrong:
        peak = copy.deepcopy(peaks[i])
        peak.setcharge(signedCharge(peak.charge, polarity))
        peaks[i] = peak
    return mspy.peaklist(peaks)


def deisotopeScan(scan, settings):
    """Find isotopes and charges of a scan's peaks."""

    deisotoping = settings["deisotoping"]
    scan.deisotope(
        maxCharge=signedCharge(deisotoping["maxCharge"], scan.polarity),
        mzTolerance=deisotoping["massTolerance"],
        intTolerance=deisotoping["intTolerance"],
        isotopeShift=deisotoping["isotopeShift"],
        averagineType=settings["peakpicking"]["averagineType"],
    )

    if deisotoping.get("convertToEnvelopes"):
        _labelEnvelopes(scan, settings)

    if deisotoping["removeIsotopes"]:
        scan.remisotopes()

    if deisotoping["removeUnknown"]:
        scan.remuncharged()


def envelopeParams(settings, seedCharge=1, polarity=None):
    """The parameters mspy.recalculate_neighborhood_envelopes takes, the
    charges signed for the scan's polarity."""

    deisotoping = settings["deisotoping"]
    return {
        "massTolerance": deisotoping["massTolerance"],
        "isotopeShift": deisotoping["isotopeShift"],
        "maxCharge": signedCharge(deisotoping["maxCharge"], polarity),
        "intTolerance": deisotoping["intTolerance"],
        "labelEnvelope": deisotoping["labelEnvelope"],
        "envelopeIntensity": deisotoping["envelopeIntensity"],
        "envelopeNonIdeality": deisotoping["envelopeNonIdeality"],
        "envelopeRefinePattern": deisotoping.get("envelopeRefinePattern", 1),
        "averagineType": settings["peakpicking"].get("averagineType", "protein"),
        "seedCharge": signedCharge(seedCharge, polarity),
    }


def seedCharge(peaks, typed=None, polarity=None):
    """The charge "Convert to Envelopes" gives peaks that have none.

    The first charged peak's charge, else a charge typed in the peak editor
    (typed, as text), else 1 -- the last two signed for the polarity.
    """

    for peak in peaks:
        if peak.charge:
            return int(peak.charge)
    try:
        value = int(typed.strip()) if typed else 0
    except ValueError:
        value = 0
    return signedCharge(value or 1, polarity)


def convertToEnvelopes(peaklist, profile, settings, charge=None, polarity=None):
    """Every peak of a peak list as an envelope, as "Convert All to Envelopes"
    gives them; envelopes already there are refitted.

    Returns a new peak list, or the same object when there is nothing to do.
    charge is the seed charge, by default seedCharge(peaklist); polarity is
    the scan's, which signs the charges -- those of peaks and envelopes
    labelled with the wrong sign are corrected (see polarityCorrected).
    """

    if not len(peaklist):
        return peaklist
    corrected = polarityCorrected(peaklist, polarity)
    peaks = list(corrected)
    if charge is None:
        charge = seedCharge(peaks, polarity=polarity)
    return mspy.recalculate_neighborhood_envelopes(
        corrected,
        profile,
        [peak.mz for peak in peaks],
        envelopeParams(settings, seedCharge=charge, polarity=polarity),
        selectedOnly=True,
    )


def convertScanToEnvelopes(scan, settings):
    """convertToEnvelopes on a scan, in place."""

    scan.peaklist = convertToEnvelopes(
        scan.peaklist, scan.profile, settings, polarity=scan.polarity
    )


def envelopeJobs(documents, current=None, typed=None):
    """What "Convert All to Envelopes in All Documents" fits.

    [(index, document, peaklist, charge)] for every document with peaks. The
    charge typed in the peak editor (typed) belongs to the current document
    only.
    """

    jobs = []
    for index, document in enumerate(documents):
        peaklist = document.spectrum.peaklist
        if len(peaklist):
            charge = seedCharge(
                peaklist,
                typed if document is current else None,
                document.spectrum.polarity,
            )
            jobs.append((index, document, peaklist, charge))
    return jobs


def fitEnvelopeJobs(jobs, settings, progress=None):
    """Run convertToEnvelopes for each of envelopeJobs(), changing nothing.

    Returns ({index: new peak list}, [(title, error)]): documents with nothing
    to do are left out, and one that fails is reported while the others go on.
    progress, a dict, counts the finished jobs under "done".
    """

    import traceback

    results = {}
    failures = []
    for index, document, peaklist, charge in jobs:
        try:
            result = convertToEnvelopes(
                peaklist,
                document.spectrum.profile,
                settings,
                charge,
                polarity=document.spectrum.polarity,
            )
            if result is not peaklist:
                results[index] = result
        except Exception as error:
            traceback.print_exc()
            failures.append((document.title, error))
        finally:
            if progress is not None:
                progress["done"] = progress.get("done", 0) + 1
    return results, failures


def applyEnvelopeResults(documents, jobs, results, changed):
    """Give each document its new peak list, each change undoable on its own.

    A result goes only to the peak list it was fitted from, in a document
    still at its place. The indexes of changed documents are appended to
    changed as they change.
    """

    for index, document, peaklist, _charge in jobs:
        if (
            index in results
            and index < len(documents)
            and documents[index] is document
            and document.spectrum.peaklist is peaklist
        ):
            document.backup(("spectrum"), label="Convert All to Envelopes")
            document.spectrum.peaklist = results[index]
            changed.append(index)


def pickPeaks(scan, settings):
    """Run the configured peak-picking pipeline on one scan, in place."""

    # nothing to do without profile data
    if not scan.hasprofile():
        return

    peakpicking = settings["peakpicking"]

    # Peaks are picked on the profile as it is. Smoothing a copy just for picking
    # measured the widths -- and so the envelope areas fitted with them -- on a
    # different signal than the areas themselves (+13 to +24 % area); to pick on
    # smoothed data, smooth the profile (Smoothing panel) and every step sees it.
    scan.labelscan(
        pickingHeight=peakpicking["pickingHeight"],
        absThreshold=peakpicking["absIntThreshold"],
        relThreshold=peakpicking["relIntThreshold"],
        snThreshold=peakpicking["snThreshold"],
        baselineWindow=baselineWindow(settings),
        baselineOffset=MEASUREMENT_BASELINE_OFFSET,
    )

    # remove shoulder peaks
    if peakpicking["removeShoulders"]:
        scan.remshoulders(window=2.5, relThreshold=0.05, fwhm=0.01)

    # find isotopes and calculate charges
    if peakpicking["deisotoping"]:
        deisotopeScan(scan, settings)


def labelPooled(scan, features, settings, alignment=0.0, guide=None):
    """Label peaks found in pooled scans in one scan of the run, in place."""

    # nothing to do without profile data
    if not scan.hasprofile():
        return

    # same baseline as picking uses
    deisotoping = settings["deisotoping"]
    scan.labelpooled(
        features,
        snThreshold=settings["peakpicking"]["poolSnThreshold"],
        baselineWindow=baselineWindow(settings),
        baselineOffset=MEASUREMENT_BASELINE_OFFSET,
        label=deisotoping["labelEnvelope"],
        intensity=deisotoping["envelopeIntensity"],
        nonIdeality=deisotoping.get("envelopeNonIdeality"),
        averagineType=settings["peakpicking"]["averagineType"],
        refinePattern=bool(deisotoping.get("envelopeRefinePattern", 1)),
        alignment=alignment,
        guide=guide,
    )


def isPooled(settings):
    """Whether the settings find the peaks of LC-MS runs in pooled scans."""

    return settings["peakpicking"]["poolScans"] in ("run", "window")


def pickPeaksPooled(document, settings, loadScans, allScans=True):
    """Find peaks in an LC-MS run from pooled scans and label them per scan.

    Scans acquired the same way are pooled (the whole group, or a moving
    window of neighbours); the picking pipeline runs on the pooled spectrum
    and its peaks are labelled in each scan (see mspy.mod_pooling). A set of
    scans recording the same ions at a much lower resolution (an ion trap
    next to an Orbitrap) is labelled with the finer set's peaks instead of
    its own. With allScans False the pools are still built from the whole
    run, but only the current scan is labelled.

    loadScans(document, scanIDs) returns {scanID: scan or None}.
    """

    mode = settings["peakpicking"]["poolScans"]
    window = int(settings["peakpicking"]["poolWindow"])
    align = bool(settings["peakpicking"]["poolAlign"])

    scanlist = document.scanlist or {}
    groups = mspy.acquisitiongroups(scanlist)
    keys = [mspy.acquisitionkey(scanlist[group[0]]) for group in groups]

    # another acquisition of the same ions may guide the current scan's, so
    # without allScans the current scan's whole family is still needed
    def family(key):
        return (key[0], key[1], key[3])

    currentFamily = None
    for group, key in zip(groups, keys, strict=True):
        if document.currentScanID in group:
            currentFamily = family(key)

    # poolable sets of scans: acquisition groups split by sampling density
    sets = []
    for group, key in zip(groups, keys, strict=True):
        if not allScans and family(key) != currentFamily:
            continue

        loaded = loadScans(document, group)
        members = [
            (scanID, loaded[scanID])
            for scanID in group
            if loaded.get(scanID) is not None and loaded[scanID].hasprofile()
        ]

        # without acquisition metadata, scans of different resolution can
        # still share a group -- never average those
        for indexes in mspy.samplinggroups([scan for _id, scan in members]):
            sets.append((key, [members[i] for i in indexes]))

    guides = mspy.guidinggroups(
        [[scan for _id, scan in members] for _key, members in sets],
        [key for key, _members in sets],
    )

    # sets with a scan to label, and the sets guiding them
    needed = set()
    for index, (_key, members) in enumerate(sets):
        if allScans or any(scanID == document.currentScanID for scanID, _scan in members):
            needed.add(index)
            if guides[index] is not None:
                needed.add(guides[index])
    guiding = {guides[index] for index in needed if guides[index] is not None}

    # guides first: their peaks are what the sets they guide are labelled with
    picked = {}
    for index in sorted(needed, key=lambda i: guides[i] is not None):
        scans = [scan for _id, scan in sets[index][1]]
        targets = [
            allScans or scanID == document.currentScanID
            for scanID, _scan in sets[index][1]
        ]
        picked[index] = _pickPooledSet(
            scans,
            targets,
            settings,
            mode,
            window,
            align,
            reference=picked.get(guides[index]),
            keepPool=index in guiding,
        )


def _pickPooledSet(
    scans, targets, settings, mode, window, align, reference=None, keepPool=False
):
    """Pick one poolable set of scans and label its target scans.

    With a reference (what this function returned for a finer acquisition of
    the same ions) the set's scans are labelled with the reference's peaks,
    where the two can be matched. Returns what a guided set needs: the whole
    pool ("pool", only with keepPool), the peaks each scan is labelled from
    ("features") and the scans' retention times ("times").
    """

    single = len(scans) == 1

    # the whole pool: picked in "run" mode, matched against the reference
    whole = None
    offsets = [0.0] * len(scans)
    if single:
        whole = scans[0]
    elif mode != "window" or keepPool or reference is not None:
        whole = mspy.poolscans(scans, align=align)
        offsets = whole.attributes["alignment"]

    guide = None
    if reference is not None and reference.get("pool") is not None:
        guide = mspy.crossguide(reference["pool"], scans)

    # the set's own peaks, wherever the reference does not reach
    features: list = [None] * len(scans)
    if guide is None or whole is None or not mspy.guidecovers(guide, whole.profile):
        if single:
            pickPeaks(scans[0], settings)
            features[0] = scans[0].peaklist
        elif mode == "window":
            for index, pooled in mspy.poolwindows(scans, window, align=align):
                offsets[index] = pooled.attributes["offset"]
                if targets[index] or keepPool:
                    pickPeaks(pooled, settings)
                    features[index] = pooled.peaklist
        elif whole is not None:
            pickPeaks(whole, settings)
            features = [whole.peaklist] * len(scans)

    times = [scan.retentionTime for scan in scans]

    for index, scan in enumerate(scans):
        if not targets[index]:
            continue
        if guide is not None:
            labelPooled(
                scan,
                mspy.guidedfeatures(
                    guide,
                    _nearestFeatures(reference, scan.retentionTime),
                    features[index],
                ),
                settings,
                alignment=offsets[index],
                guide=mspy.scanguide(guide, index),
            )
        elif not single:
            labelPooled(scan, features[index], settings, alignment=offsets[index])

    return {
        "pool": whole if keepPool else None,
        "features": features,
        "times": times,
    }


def _nearestFeatures(reference, retentionTime):
    """Peaks of the reference scan closest in time (its pool's, in "run" mode)."""

    candidates = [
        (index, features)
        for index, features in enumerate(reference["features"])
        if features is not None
    ]
    if not candidates:
        return mspy.peaklist([])
    if retentionTime is None:
        return candidates[len(candidates) // 2][1]

    def distance(item):
        time = reference["times"][item[0]]
        return abs(time - retentionTime) if time is not None else float("inf")

    return min(candidates, key=distance)[1]
