"""Shields.io-style SVG badges and CSS gradient parsing (ported from R/badges.R)."""

from __future__ import annotations

import math
import re
from typing import Any, NamedTuple

from .fonts import str_metrics
from .utils import (
    as_character,
    escape_xml,
    fmt_num,
    generate_id,
    is_light_color,
    validate_color,
    validate_font_family,
)

__all__ = ["create_badge", "Badge", "css_gradient_to_svg", "is_gradient"]

_HEX_RE = re.compile(r"#[0-9A-Fa-f]{3,8}")
_ANGLE_RE = re.compile(r"(\d+)deg")
_GRADIENT_RE = re.compile(r"gradient\(", re.IGNORECASE)


class Badge(NamedTuple):
    """A badge SVG plus its rounded pixel size (``create_badge(as_string=False)``)."""

    svg: str
    width: int
    height: int


def is_gradient(color: str) -> bool:
    """``True`` if *color* is a CSS ``*-gradient(...)`` expression."""
    return bool(_GRADIENT_RE.search(color or ""))


def css_gradient_to_svg(css_gradient: str, id: str = "grad") -> str:  # noqa: A002
    """Convert a CSS ``linear-gradient(...)`` into an SVG ``<linearGradient>``.

    Supports angles (``135deg``) and the ``to right|left|bottom|top``
    keywords (default: top to bottom). Hex color stops are spread evenly;
    a single color yields a solid gradient, and no color falls back to
    white -> black.
    """
    angle = _ANGLE_RE.search(css_gradient)
    low = css_gradient.lower()
    if angle:
        rad = (float(angle.group(1)) - 90) * math.pi / 180
        x1 = f"{50 - 50 * math.cos(rad):.0f}%"
        y1 = f"{50 - 50 * math.sin(rad):.0f}%"
        x2 = f"{50 + 50 * math.cos(rad):.0f}%"
        y2 = f"{50 + 50 * math.sin(rad):.0f}%"
    elif "to right" in low:
        x1, y1, x2, y2 = "0%", "0%", "100%", "0%"
    elif "to left" in low:
        x1, y1, x2, y2 = "100%", "0%", "0%", "0%"
    elif "to bottom" in low:
        x1, y1, x2, y2 = "0%", "0%", "0%", "100%"
    elif "to top" in low:
        x1, y1, x2, y2 = "0%", "100%", "0%", "0%"
    else:
        x1, y1, x2, y2 = "0%", "0%", "0%", "100%"

    colors = _HEX_RE.findall(css_gradient)
    if not colors:
        colors = ["#ffffff", "#000000"]
    elif len(colors) == 1:
        colors = [colors[0], colors[0]]

    stops = "".join(
        f'<stop offset="{round(i / (len(colors) - 1) * 100)}%" stop-color="{c}"/>'
        for i, c in enumerate(colors)
    )
    return f'<linearGradient id="{id}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">{stops}</linearGradient>'


def _bg_is_light(color: str) -> bool:
    if is_gradient(color):
        hexes = _HEX_RE.findall(color)
        return is_light_color(hexes[0]) if hexes else False
    return is_light_color(color)


def create_badge(
    label: Any,
    value: Any,
    color: str = "white",
    font: str = "Jost",
    style: str = "margin:2px;",
    fontsize: float = 11,
    horiz_padding: float = 5,
    extra_right_pad: float = 2,
    css_class: str = "",
    shadow_offset: float = 2,
    corner_radius: float = 3,
    height: float | None = None,
    as_string: bool = True,
) -> str | Badge:
    """Create a shields.io-style badge with a dark label and a colored value.

    Args:
        label: Left-side text.
        value: Right-side text.
        color: Value background: any color or a CSS ``linear-gradient(...)``.
            Text color (dark/light) is picked from its lightness.
        font: Font family (also used to measure the text).
        style: Inline CSS for the root ``<svg>``.
        fontsize: Font size in pixels.
        horiz_padding: Horizontal padding on each side of each text.
        extra_right_pad: Extra padding on both sides of the value.
        css_class: CSS class of the root ``<svg>`` (R's ``class``).
        shadow_offset: Offset of the text shadow in pixels.
        corner_radius: Corner radius.
        height: Half of the badge height; defaults to the ink height of the
            taller text (the badge is twice as tall as the text).
        as_string: Return only the SVG string (default) or a :class:`Badge`.

    Raises:
        ValueError: If *color* is not a hex/named color or a
            ``linear-gradient(...)``, or *font* is not a valid family name.
    """
    color = validate_color(color, arg="color", allow_gradient=True)
    font = validate_font_family(font)
    style_attr = escape_xml(style)
    class_attr = escape_xml(css_class)
    label_s = as_character(label)
    value_s = as_character(value)
    id_suffix = generate_id(label_s, value_s, color)

    ml = str_metrics(label_s, font, fontsize)
    mv = str_metrics(value_s, font, fontsize)

    left_width = ml.width + 2 * horiz_padding
    right_width = mv.width + 2 * horiz_padding + 2 * extra_right_pad
    total_width = left_width + right_width

    current_height = max(ml.ascent + ml.descent, mv.ascent + mv.descent)
    final_height = height * 2 if height is not None else current_height * 2

    left_text_x = horiz_padding + ml.width / 2
    right_text_x = left_width + horiz_padding + extra_right_pad + mv.width / 2
    text_y = final_height * 0.55

    if _bg_is_light(color):
        value_text_shadow, value_text_main = "#ccc", "#333"
    else:
        value_text_shadow, value_text_main = "#010101", "#fff"

    if is_gradient(color):
        grad_id = f"grad_{id_suffix}"
        fill_color = f"url(#{grad_id})"
        defs_block = f"<defs>\n{css_gradient_to_svg(color, id=grad_id)}\n</defs>"
    else:
        fill_color = color
        defs_block = ""

    tw, fh = round(total_width), round(final_height)
    lw, rw = round(left_width), round(right_width)
    el, ev = escape_xml(label_s), escape_xml(value_s)
    cr = fmt_num(corner_radius)
    so = shadow_offset

    svg = f"""<svg class="{class_attr}" style="{style_attr}" xmlns="http://www.w3.org/2000/svg" width="{tw}" height="{fh}" role="img" aria-label="{el}: {ev}">
      <title>{el}: {ev}</title>
      {defs_block}
      <linearGradient id="s{id_suffix}" x2="0" y2="100%">
        <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
        <stop offset="1" stop-opacity=".1"/>
      </linearGradient>
      <clipPath id="r{id_suffix}">
        <rect width="{tw}" height="{fh}" rx="{cr}" ry="{cr}" fill="#fff"/>
      </clipPath>
      <g clip-path="url(#r{id_suffix})">
        <rect width="{tw}" height="{fh}" fill="#555"/>
        <rect x="{lw}" width="{rw}" height="{fh}" fill="{fill_color}"/>
        <rect width="{tw}" height="{fh}" fill="url(#s{id_suffix})"/>
      </g>
      <g fill="#fff" text-anchor="middle" font-family="{font}" font-size="{fmt_num(fontsize)}" dominant-baseline="middle">
        <text x="{left_text_x + so:.1f}" y="{text_y + so:.1f}" fill="#010101" text-rendering="geometricPrecision" alignment-baseline="middle" fill-opacity=".3">{el}</text>
        <text x="{left_text_x:.1f}" y="{text_y:.1f}" text-rendering="geometricPrecision" alignment-baseline="middle" fill="#fff">{el}</text>
        <text x="{right_text_x + so:.1f}" y="{text_y + so:.1f}" text-rendering="geometricPrecision" alignment-baseline="middle" fill="{value_text_shadow}" fill-opacity=".3">{ev}</text>
        <text x="{right_text_x:.1f}" y="{text_y:.1f}" text-rendering="geometricPrecision" alignment-baseline="middle" fill="{value_text_main}">{ev}</text>
      </g>
    </svg>"""

    if as_string:
        return svg
    return Badge(svg, tw, fh)
