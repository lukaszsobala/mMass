"""Guard that the deisotoping config keys the pipeline relies on still exist.

The envelope recalculation helper and its tests read a fixed set of keys from
config.processing["deisotoping"]. Their VALUES are user-tunable at runtime, so
this test only asserts the keys are present with compatible types -- catching a
rename or removal that would break the GUI wiring. It skips if gui.config can't
be imported (e.g. wxPython missing).
"""

import pytest

from .helpers import DEISOTOPING_KEYS


def test_deisotoping_keys_present_with_expected_types():
    try:
        from gui import config  # noqa: WPS433 (optional import)
    except Exception:
        pytest.skip("gui.config not importable in this environment")

    actual = config.processing["deisotoping"]
    for key, expected_type in DEISOTOPING_KEYS.items():
        assert key in actual, f"deisotoping config lost key: {key}"
        if expected_type is float:
            assert isinstance(actual[key], (int, float)), f"{key} not numeric"
        else:
            assert isinstance(actual[key], expected_type), (
                f"{key} expected {expected_type.__name__}, got {type(actual[key]).__name__}"
            )
