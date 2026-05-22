"""Helpers for opt-in UI scaling in legacy pixel-based UI code."""

from __future__ import annotations

import os


def _parse_positive_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def get_ui_scale() -> float:
    """Get opt-in UI scale factor.

    Defaults to 1.0 to preserve current behavior.
    Set MMASS_UI_SCALE (for example 1.5 or 2.0) to enable scaling.
    """

    value = _parse_positive_float("MMASS_UI_SCALE")
    if value is None:
        return 1.0
    return max(0.5, min(4.0, value))


def scale_metric(value: int, scale: float) -> int:
    """Scale integer UI metrics, preserving -1 default-size sentinel."""

    if value == -1:
        return value
    return int(round(value * scale))
