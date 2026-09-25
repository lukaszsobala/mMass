"""Spectrum processing steps shared by the Processing panel and mmass process.

Every function takes the processing settings as an argument, shaped like
config.processing, so the command line can run with a changed copy of them
without touching the user's configuration.
"""

import numpy

import mspy


def clearNotations(document):
    """Remove annotations and sequence matches, which processing invalidates."""

    del document.annotations[:]
    for sequence in document.sequences:
        del sequence.matches[:]


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


def mathScan(scan, operation, settings):
    """Apply a single-spectrum math operation to a scan's profile and peaks."""

    if operation == "normalize":
        scan.normalize()
    elif operation == "multiply":
        scan.multiply(y=settings["math"]["multiplier"])
    elif operation == "squareroot":
        scan.squareroot(preservePeaks=bool(settings["math"]["preservePeaks"]))
    else:
        raise ValueError(f"{operation} needs more than one spectrum")


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


def subtractBaseline(scan, settings):
    """Subtract the baseline from a scan's profile."""

    scan.subbase(
        window=(1.0 / settings["baseline"]["precision"]),
        offset=settings["baseline"]["offset"],
        allowNegative=settings["baseline"]["allowNegative"],
        preservePeaks=bool(settings["baseline"]["preservePeaks"]),
    )


def smoothScan(scan, settings):
    """Smooth a scan's profile."""

    scan.smooth(
        method=settings["smoothing"]["method"],
        window=settings["smoothing"]["windowSize"],
        cycles=int(settings["smoothing"]["cycles"]),
        preservePeaks=bool(settings["smoothing"]["preservePeaks"]),
    )


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


def deisotopeScan(scan, settings):
    """Find isotopes and charges of a scan's peaks."""

    deisotoping = settings["deisotoping"]
    scan.deisotope(
        maxCharge=deisotoping["maxCharge"],
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


def pickPeaks(scan, settings):
    """Run the configured peak-picking pipeline on one scan, in place."""

    # nothing to do without profile data
    if not scan.hasprofile():
        return

    peakpicking = settings["peakpicking"]

    # get baseline window
    baselineWindow = 1.0
    if peakpicking["baseline"]:
        baselineWindow = 1.0 / settings["baseline"]["precision"]

    # get smoothing method
    smoothMethod = None
    if peakpicking["smoothing"]:
        smoothMethod = settings["smoothing"]["method"]

    # label spectrum
    scan.labelscan(
        pickingHeight=peakpicking["pickingHeight"],
        absThreshold=peakpicking["absIntThreshold"],
        relThreshold=peakpicking["relIntThreshold"],
        snThreshold=peakpicking["snThreshold"],
        baselineWindow=baselineWindow,
        baselineOffset=settings["baseline"]["offset"],
        smoothMethod=smoothMethod,
        smoothWindow=settings["smoothing"]["windowSize"],
        smoothCycles=int(settings["smoothing"]["cycles"]),
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
    baselineWindow = 1.0
    if settings["peakpicking"]["baseline"]:
        baselineWindow = 1.0 / settings["baseline"]["precision"]

    deisotoping = settings["deisotoping"]
    scan.labelpooled(
        features,
        snThreshold=settings["peakpicking"]["poolSnThreshold"],
        baselineWindow=baselineWindow,
        baselineOffset=settings["baseline"]["offset"],
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
