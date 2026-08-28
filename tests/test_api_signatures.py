"""Contract tests between the GUI call sites and the mspy API.

The GUI and mspy are separate layers with no type checking between them, so a
parameter added to one end of the envelope pipeline and not threaded through the
other is invisible until the feature is exercised in the running app -- where it
surfaces as a TypeError inside a worker thread, which the app swallows into a
traceback on stderr while the operation silently does nothing.

That is exactly how ``refinePattern`` broke "Find Peaks": it was added to
``relabelenvelopes`` and to ``peaklist.labelenvelopes``, and the GUI passed it --
but ``scan.labelenvelopes``, the wrapper the peak-picking path actually calls, had
not been updated. Peaks came out neither deisotoped nor converted to envelopes.

These tests read the GUI sources with ``ast`` (no wxPython import, so they run
headless) and check every keyword against the real signatures.
"""

import ast
import inspect
import os

import pytest

import mspy
from mspy import mod_peakpicking as mpp


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GUI_DIR = os.path.join(_REPO_ROOT, "src", "gui")

# The mspy classes the GUI drives. A method name defined on more than one of them
# must accept the GUI's keywords on ALL of them: the call site is written against
# whichever object it holds, and `scan` and `peaklist` are used interchangeably
# across the processing panel.
_API_CLASSES = {"scan": mspy.scan, "peaklist": mspy.peaklist}

# The processing-pipeline methods this check covers. Deliberately an explicit list
# rather than "every mspy method name": several of these names also exist as
# module-level mspy functions with different signatures (mspy.smooth, mspy.labelpeak)
# and some collide with builtins (list.sort(key=...)), so matching on the bare name
# alone produces noise. These are the calls that carry the envelope/deisotoping
# parameters -- the ones that actually drift.
_PIPELINE_API = frozenset({
    "labelenvelopes",
    "deisotope",
    "labelscan",
    "remisotopes",
    "remuncharged",
    "remshoulders",
    "deconvolute",
})


def _unaccepted(func, keywords):
    """Which of ``keywords`` this callable would reject."""

    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):  # pragma: no cover - builtins
        return set()
    parameters = signature.parameters
    if any(p.kind is p.VAR_KEYWORD for p in parameters.values()):
        return set()
    accepted = {
        name for name, p in parameters.items()
        if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    }
    return set(keywords) - accepted


def _api_methods():
    """{method name: [(label, callable), ...]} for the mspy objects the GUI drives."""

    table = {}
    for owner, cls in _API_CLASSES.items():
        for name, attribute in vars(cls).items():
            if name.startswith("_") or not callable(attribute):
                continue
            table.setdefault(name, []).append(("mspy.%s.%s" % (owner, name), attribute))
    return table


def _gui_calls():
    """Every ``<receiver>.<name>(...)`` in the GUI sources, with its keywords."""

    calls = []
    for entry in sorted(os.listdir(_GUI_DIR)):
        if not entry.endswith(".py"):
            continue
        path = os.path.join(_GUI_DIR, entry)
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            keywords = {kw.arg for kw in node.keywords if kw.arg is not None}
            if not keywords:
                continue
            receiver = node.func.value
            receiver = receiver.id if isinstance(receiver, ast.Name) else None
            calls.append((entry, node.lineno, receiver, node.func.attr, keywords))
    return calls


def test_gui_keywords_are_accepted_by_every_mspy_object_defining_them():
    """A keyword the GUI passes must be accepted wherever that method is defined.

    ``scan.labelenvelopes`` and ``peaklist.labelenvelopes`` are both driven from the
    processing panel, so a parameter threaded into one and not the other breaks
    whichever path happens to call the other one.
    """

    methods = _api_methods()
    failures = []
    for filename, lineno, receiver, name, keywords in _gui_calls():
        if name not in _PIPELINE_API or receiver == "mspy":
            continue
        candidates = methods.get(name, ())
        assert candidates, "%s is not an mspy method any more -- update _PIPELINE_API" % name
        for label, func in candidates:
            missing = _unaccepted(func, keywords)
            if missing:
                failures.append(
                    "%s:%d passes %s to %s, which does not accept %s"
                    % (filename, lineno, sorted(keywords), label, sorted(missing))
                )
    assert not failures, "GUI/mspy signature drift:\n  " + "\n  ".join(failures)


def test_gui_keywords_are_accepted_by_mspy_module_functions():
    """Same check for the module-level helpers the GUI calls as ``mspy.<name>(...)``."""

    failures = []
    for filename, lineno, receiver, name, keywords in _gui_calls():
        if receiver != "mspy":
            continue
        func = getattr(mspy, name, None)
        if func is None or not callable(func):
            continue
        missing = _unaccepted(func, keywords)
        if missing:
            failures.append(
                "%s:%d passes %s to mspy.%s, which does not accept %s"
                % (filename, lineno, sorted(keywords), name, sorted(missing))
            )
    assert not failures, "GUI/mspy signature drift:\n  " + "\n  ".join(failures)


def test_envelope_parameters_reach_the_fit_from_every_wrapper():
    """Every knob of the envelope fit stays reachable through the whole chain.

    ``scan.labelenvelopes`` -> ``peaklist.labelenvelopes`` -> ``relabelenvelopes``.
    A parameter added at the bottom and not forwarded is unreachable from the app
    even when nothing raises, so the setting silently does nothing.
    """

    def names(func):
        return {
            name for name, p in inspect.signature(func).parameters.items()
            if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY) and name != "self"
        }

    bottom = names(mpp.relabelenvelopes) - {"peaklist"}
    middle = names(mspy.peaklist.labelenvelopes)
    # `scan` supplies these two itself, from its own profile
    top = names(mspy.scan.labelenvelopes) | {"signal", "defaultFwhm"}

    assert bottom <= middle, "not forwarded by peaklist.labelenvelopes: %s" % sorted(
        bottom - middle
    )
    assert middle <= top, "not forwarded by scan.labelenvelopes: %s" % sorted(
        middle - top
    )


def test_recalc_helper_reads_every_envelope_param_the_gui_builds():
    """Every key ``panel_peaklist._envelopeParams`` builds is read by the helper.

    The convert/recalc path passes a plain dict rather than keywords, so a typo or
    a forgotten key cannot raise -- the helper just silently falls back to its
    default. Checked by reading the helper's source for each key name.
    """

    source = inspect.getsource(mpp.recalculate_neighborhood_envelopes)
    built = {
        "massTolerance", "isotopeShift", "maxCharge", "intTolerance",
        "labelEnvelope", "envelopeIntensity", "envelopeNonIdeality",
        "envelopeRefinePattern", "averagineType", "seedCharge",
    }
    unread = {key for key in built if '"%s"' % key not in source}
    assert not unread, "recalculate_neighborhood_envelopes ignores: %s" % sorted(unread)
