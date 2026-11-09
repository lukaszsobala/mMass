"""Undo history of documents.

A document keeps a history of steps: each step holds the state that the parts
it names (the spectrum, annotations, difference labels, ...) had before an
edit, so undoing it puts them back. Each part is stored whole, never as a
difference, so a step can be dropped -- or a part of it -- without breaking
the steps around it.

The histories of all open documents share a memory budget: the oldest steps
are dropped first once they pass it. Profiles that did not change between
steps (most edits change only peaks or labels) are stored once.

No wx here: this is tested without a display.
"""

import itertools
import pickle
import weakref

import numpy

# parts of a document a step can hold
ITEMS = ("spectrum", "annotations", "sequences", "notations", "rulers", "doctitle", "info")

# parts that belong to the whole document rather than to the scan shown
DOCUMENT_ITEMS = frozenset(("annotations", "sequences", "notations", "doctitle", "info"))

# what a step stores for each part: notations are the annotations and the
# matches of the sequences, the title is a part of the information
STATE_KEYS = {
    "spectrum": ("spectrum",),
    "annotations": ("annotations",),
    "sequences": ("sequences",),
    "notations": ("annotations", "matches"),
    "rulers": ("rulers",),
    "doctitle": ("info",),
    "info": ("info",),
}

# limits of config.main["undoSteps"] and ["undoMemory"] (MB), and defaults;
# the memory is set in whole MEMORY_STEPs
DEFAULT_STEPS = 100
DEFAULT_MEMORY = 1024
STEPS_RANGE = (1, 200)
MEMORY_RANGE = (256, 4096)
MEMORY_STEP = 256

# what Undo and Redo say when a step was recorded without a name
DEFAULT_LABELS = {
    "spectrum": "Spectrum Edit",
    "annotations": "Annotation Edit",
    "sequences": "Sequence Edit",
    "notations": "Notation Edit",
    "rulers": "Difference Label Edit",
    "doctitle": "Rename",
    "info": "Document Information",
}

# profiles a new step looks through for an unchanged copy to share
SHARED_PROFILE_CANDIDATES = 4

# Python objects take a few times the size of their pickle
PICKLE_SIZE_FACTOR = 3

# order the steps of all documents were recorded in
_serials = itertools.count()

# every history, for the shared memory budget
_histories = weakref.WeakSet()


def normalizeItems(items):
    """The parts a backup names, as a tuple of ITEMS.

    Callers pass a tuple, or a single name -- often written ("spectrum"),
    which is a string, not a tuple.
    """

    if not items:
        return ()
    if isinstance(items, str):
        items = (items,)
    return tuple(name for name in ITEMS if name in items)


def defaultLabel(items):
    """A name for a step recorded without one."""

    for name in ("spectrum", "rulers", "notations", "annotations", "sequences", "info", "doctitle"):
        if name in items:
            return DEFAULT_LABELS[name]
    return "Edit"


def profileOf(state):
    """The profile array of a stored spectrum, or None."""

    spectrum = state.get("spectrum")
    profile = getattr(spectrum, "profile", None)
    if isinstance(profile, numpy.ndarray) and profile.size:
        return profile
    return None


def approximateSize(value):
    """Rough memory size of a stored part, profile arrays left out."""

    if value is None:
        return 0
    if isinstance(value, numpy.ndarray):
        return int(value.nbytes)

    # arrays held by an object (a scan's baseline) are counted as they are,
    # and its profile not at all: memoryUsed counts each profile once
    arrays = {}
    if hasattr(value, "__dict__"):
        arrays = {
            name: item for name, item in vars(value).items() if isinstance(item, numpy.ndarray)
        }
    size = sum(item.nbytes for name, item in arrays.items() if name != "profile")
    for name in arrays:
        setattr(value, name, None)
    try:
        size += PICKLE_SIZE_FACTOR * len(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
    except Exception:
        size += 1024
    finally:
        for name, item in arrays.items():
            setattr(value, name, item)
    return size


class Step:
    """One undoable edit: the state of some parts of a document before it."""

    __slots__ = ("label", "items", "state", "serial", "size")

    def __init__(self, label, items, state):
        self.label = label
        self.items = tuple(items)
        self.state = state
        self.serial = next(_serials)
        self.size = sum(approximateSize(value) for value in state.values())

    def strip(self, names):
        """Forget the parts named; returns False when nothing is left."""

        if not any(name in names for name in self.items):
            return True
        self.items = tuple(name for name in self.items if name not in names)
        kept = {key for name in self.items for key in STATE_KEYS[name]}
        self.state = {key: value for key, value in self.state.items() if key in kept}
        self.size = sum(approximateSize(value) for value in self.state.values())
        return bool(self.items)


class History:
    """Undo and redo steps of one document, or of one scan of an LC-MS run.

    undoSteps[-1] is undone next and redoSteps[-1] redone next.
    """

    def __init__(self):
        self.undoSteps = []
        self.redoSteps = []
        # the last step recorded and the redo steps it replaced, until anything
        # else happens to the history (see discardLast)
        self._replaced = None
        _histories.add(self)

    def __bool__(self):
        return bool(self.undoSteps or self.redoSteps)

    def clear(self):
        del self.undoSteps[:]
        del self.redoSteps[:]
        self._replaced = None

    def record(self, step):
        """Add a new step; it makes the steps undone before it unreachable."""

        self._replaced = (step, self.redoSteps[:])
        self.undoSteps.append(step)
        del self.redoSteps[:]

    def discardLast(self):
        """Forget the step just recorded, for an edit that was cancelled, and
        bring back the redo steps it replaced."""

        if not self.undoSteps:
            return
        step = self.undoSteps.pop()
        if self._replaced is not None and self._replaced[0] is step:
            self.redoSteps[:] = self._replaced[1]
        self._replaced = None

    def popUndo(self):
        self._replaced = None
        return self.undoSteps.pop()

    def popRedo(self):
        self._replaced = None
        return self.redoSteps.pop()

    def strip(self, names):
        """Forget the parts named in every step, and the steps left empty."""

        self._replaced = None
        self.undoSteps[:] = [step for step in self.undoSteps if step.strip(names)]
        self.redoSteps[:] = [step for step in self.redoSteps if step.strip(names)]

    def steps(self):
        return self.undoSteps + self.redoSteps

    def sharedProfile(self, profile):
        """A stored profile equal to the one given, to share instead of copying."""

        if not isinstance(profile, numpy.ndarray) or not profile.size:
            return None
        seen = set()
        newestFirst = sorted(self.steps(), key=lambda step: step.serial, reverse=True)
        for step in newestFirst:
            stored = profileOf(step.state)
            if stored is None or id(stored) in seen:
                continue
            seen.add(id(stored))
            if stored is profile or (
                stored.shape == profile.shape
                and stored.dtype == profile.dtype
                and numpy.array_equal(stored, profile)
            ):
                return stored
            if len(seen) >= SHARED_PROFILE_CANDIDATES:
                break
        return None


def memoryUsed(histories=None):
    """Bytes the histories hold, each profile array counted once."""

    if histories is None:
        histories = list(_histories)
    total = 0
    arrays = {}
    for history in histories:
        for step in history.steps():
            total += step.size
            profile = profileOf(step.state)
            if profile is not None:
                arrays[id(profile)] = profile.nbytes
    return total + sum(arrays.values())


def trim(current, maxSteps, maxBytes):
    """Drop the oldest steps over the limits.

    No history keeps more than maxSteps undo steps; then the oldest steps of
    all histories are dropped until they fit in maxBytes, except the step just
    recorded in the current history.
    """

    maxSteps = max(1, int(maxSteps))
    for history in list(_histories):
        if len(history.undoSteps) > maxSteps:
            del history.undoSteps[: len(history.undoSteps) - maxSteps]
        if len(history.redoSteps) > maxSteps:
            del history.redoSteps[: len(history.redoSteps) - maxSteps]

    keep = current.undoSteps[-1] if current is not None and current.undoSteps else None
    while memoryUsed() > maxBytes:
        # the oldest step at the far end of any history
        candidates = []
        for history in list(_histories):
            for steps in (history.undoSteps, history.redoSteps):
                if steps and steps[0] is not keep:
                    candidates.append((steps[0].serial, steps))
        if not candidates:
            break
        _serial, steps = min(candidates, key=lambda candidate: candidate[0])
        del steps[0]
