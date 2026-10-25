"""Inline mini-charts (sparklines) for cards (ported from R/sparklines.R)."""

from __future__ import annotations

import math
from collections.abc import Iterable
from numbers import Real
from typing import Literal

__all__ = ["create_sparkline"]

SparklineType = Literal["line", "area", "bar"]
_TYPES = ("line", "area", "bar")


def _validate_values(values: Iterable[float] | None) -> list[float]:
    msg = "`values` must be a non-empty numeric sequence without missing values."
    if values is None or isinstance(values, (str, bytes)):
        raise ValueError(msg)
    if isinstance(values, Real) and not isinstance(values, bool):
        values = [values]
    try:
        items = list(values)
    except TypeError:
        raise ValueError(msg) from None
    if not items:
        raise ValueError(msg)
    out: list[float] = []
    for v in items:
        if v is None or isinstance(v, bool) or not isinstance(v, Real):
            raise ValueError(msg)
        fv = float(v)
        if math.isnan(fv):
            raise ValueError(msg)
        out.append(fv)
    return out


def _positive(x: object) -> bool:
    return isinstance(x, Real) and not isinstance(x, bool) and not math.isnan(float(x)) and x > 0


def create_sparkline(
    values: Iterable[float],
    width: float = 120,
    height: float = 36,
    color: str = "white",
    type: SparklineType = "line",  # noqa: A002 - mirrors the R argument name
    stroke_width: float = 2,
    fill_opacity: float = 0.3,
    show_last_point: bool = True,
    padding: float = 3,
) -> str:
    """Create a small standalone SVG line, area or bar chart.

    The result can be used anywhere :func:`cardargus.svg_card` accepts raw
    SVG, e.g. as a field's ``with_icon``.

    Args:
        values: Numeric series (no missing values). Line and area sparklines
            need at least 2 points; bars need at least 1.
        width: Total width in pixels.
        height: Total height in pixels.
        color: Stroke/fill color.
        type: ``"line"`` (default), ``"area"`` or ``"bar"``.
        stroke_width: Line thickness (line/area).
        fill_opacity: Fill opacity of the area (``"area"``) and the bars (``"bar"``).
        show_last_point: Draw a dot on the last point (line/area).
        padding: Inner padding so strokes and dots are not clipped.

    Returns:
        An ``<svg>`` string with ``aria-hidden="true"``.

    Raises:
        ValueError: For invalid values, too few points, an unknown type or
            non-positive dimensions.
    """
    if type not in _TYPES:
        raise ValueError(f"`type` must be one of {', '.join(map(repr, _TYPES))}, not {type!r}.")
    vals = _validate_values(values)
    min_points = 1 if type == "bar" else 2
    if len(vals) < min_points:
        plural = "s" if min_points > 1 else ""
        raise ValueError(f"A {type!r} sparkline needs at least {min_points} value{plural}.")
    if not (_positive(width) and _positive(height)):
        raise ValueError("`width` and `height` must be positive numbers.")

    n = len(vals)
    inner_w = width - 2 * padding
    inner_h = height - 2 * padding
    baseline_y = height - padding

    header = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" aria-hidden="true">'
    )

    if type == "bar":
        # Bars scale from zero (or from the minimum, if there are negatives).
        lo = min(0.0, min(vals))
        hi = max(max(vals), 0.0)
        span = hi - lo
        slot_w = inner_w / n
        bar_w = slot_w * 0.75
        rects = []
        for i, v in enumerate(vals):
            h = 1.0 if span == 0 else inner_h * (v - lo) / span
            h = max(h, 1.0)  # a zero bar still shows as a sliver
            x = padding + i * slot_w + (slot_w - bar_w) / 2
            rects.append(
                f'<rect x="{x:.2f}" y="{baseline_y - h:.2f}" width="{bar_w:.2f}" '
                f'height="{h:.2f}" fill="{color}" fill-opacity="{fill_opacity:.2f}"/>'
            )
        return header + "".join(rects) + "</svg>"

    # Line / area: evenly spaced points, y inverted (SVG grows downwards).
    lo, hi = min(vals), max(vals)
    span = hi - lo
    xs = [padding + inner_w * i / (n - 1) for i in range(n)]
    ys = [height / 2] * n if span == 0 else [padding + inner_h * (hi - v) / span for v in vals]
    points = " ".join(f"{x:.2f},{y:.2f}" for x, y in zip(xs, ys))

    parts: list[str] = []
    if type == "area":
        area_points = f"{points} {xs[-1]:.2f},{baseline_y:.2f} {xs[0]:.2f},{baseline_y:.2f}"
        parts.append(
            f'<polygon points="{area_points}" fill="{color}" '
            f'fill-opacity="{fill_opacity:.2f}" stroke="none"/>'
        )
    parts.append(
        f'<polyline points="{points}" fill="none" stroke="{color}" '
        f'stroke-width="{stroke_width:.2f}" stroke-linecap="round" stroke-linejoin="round"/>'
    )
    if show_last_point:
        parts.append(
            f'<circle cx="{xs[-1]:.2f}" cy="{ys[-1]:.2f}" r="{stroke_width * 1.5:.2f}" fill="{color}"/>'
        )
    return header + "".join(parts) + "</svg>"
