"""Utility functions: XML escaping, color lightness, number compression, wrapping."""

from __future__ import annotations

import itertools
import math
import re
import zlib
from collections.abc import Sequence
from numbers import Real
from typing import Any, NamedTuple, overload

from ._colors import lookup_named_color
from .fonts import text_width

__all__ = [
    "escape_xml",
    "is_light_color",
    "compress_number",
    "wrap_text",
    "WrappedText",
    "validate_color",
    "validate_font_family",
]


def _is_missing(x: Any) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def as_character(x: Any) -> str:
    """Convert a scalar to text the way R's ``as.character()`` does.

    Integral floats lose their trailing ``.0`` (``192.0`` -> ``"192"``) and
    other floats use 15 significant digits; ``None``/NaN become ``""``.
    """
    if _is_missing(x):
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, bool):
        return "TRUE" if x else "FALSE"
    if isinstance(x, Real) and not isinstance(x, int):
        xf = float(x)
        if math.isfinite(xf) and xf.is_integer() and abs(xf) < 1e15:
            return str(int(xf))
        return format(xf, ".15g")
    return str(x)


def fmt_num(x: float) -> str:
    """Format a number for an SVG attribute: integral values without decimals."""
    xf = float(x)
    if xf.is_integer():
        return str(int(xf))
    return format(xf, ".15g")


# ---------------------------------------------------------------------------
# XML escaping
# ---------------------------------------------------------------------------


def _escape_one(text: Any) -> str:
    s = as_character(text)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("'", "&apos;")
        .replace('"', "&quot;")
    )


@overload
def escape_xml(text: list[Any] | tuple[Any, ...]) -> list[str]: ...
@overload
def escape_xml(text: Any) -> str: ...


def escape_xml(text: Any) -> str | list[str]:
    """Escape the five XML special characters (``& < > ' "``).

    ``None`` and NaN become ``""``. Lists/tuples are escaped element-wise (R's
    vectorized behavior) and return a list; an empty list returns ``""``.
    """
    if isinstance(text, (list, tuple)):
        if len(text) == 0:
            return ""
        return [_escape_one(t) for t in text]
    return _escape_one(text)


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

_HEX_PAIR = re.compile(r"[0-9A-Fa-f]{2}")


def color_to_rgb(color: str) -> tuple[int, int, int]:
    """Resolve a hex (``#rgb``, ``#rrggbb``, ``#rrggbbaa``) or named color to RGB.

    Raises:
        ValueError: If *color* is not a non-empty string or cannot be parsed.
    """
    if not isinstance(color, str) or not color:
        raise ValueError("`color` must be a single non-empty color string.")
    if color.startswith("#"):
        hx = color[1:]
        if len(hx) == 3:
            hx = "".join(c * 2 for c in hx)
        parts = [hx[0:2], hx[2:4], hx[4:6]]
        if not all(_HEX_PAIR.fullmatch(p) for p in parts):
            raise ValueError(f"`color` is not a valid hex color: {color!r}.")
        r, g, b = (int(p, 16) for p in parts)
        return r, g, b
    rgb = lookup_named_color(color)
    if rgb is None:
        raise ValueError(f"`color` is not a valid color: {color!r}.")
    return rgb


_HEX_COLOR_RE = re.compile(r"#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})")
# A CSS linear-gradient() made only of the tokens css_gradient_to_svg()
# understands: angles, "to <side>" keywords, hex stops, percentages, commas.
_GRADIENT_ARGS_RE = re.compile(r"[#0-9A-Za-z%.,\s-]*")
_GRADIENT_RE = re.compile(r"\s*linear-gradient\((.*)\)\s*", re.IGNORECASE | re.DOTALL)
_FONT_FAMILY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,99}")


def validate_color(
    color: Any,
    *,
    arg: str = "color",
    allow_gradient: bool = False,
    allow_none: bool = False,
) -> str:
    """Return *color* if it is a safe color value, else raise ``ValueError``.

    Accepted: ``#rgb``, ``#rgba``, ``#rrggbb``, ``#rrggbbaa``, a CSS/R named
    color (see :mod:`cardargus._colors`), optionally ``"none"``, and
    optionally a ``linear-gradient(...)`` whose arguments contain only
    angles, direction keywords, hex stops and percentages. Validation keeps
    user input from injecting markup into SVG attributes or ``<style>``.
    """
    if not isinstance(color, str) or not color:
        raise ValueError(f"`{arg}` must be a non-empty color string, not {color!r}.")
    if _HEX_COLOR_RE.fullmatch(color):
        return color
    if allow_none and color.lower() == "none":
        return color
    if lookup_named_color(color) is not None and re.fullmatch(r"[A-Za-z0-9 ]+", color):
        return color
    if allow_gradient:
        m = _GRADIENT_RE.fullmatch(color)
        if m and _GRADIENT_ARGS_RE.fullmatch(m.group(1)):
            return color
    kinds = "a hex color or a named color"
    if allow_gradient:
        kinds += ", or a CSS linear-gradient(...)"
    raise ValueError(f"`{arg}` must be {kinds}; got {color!r}.")


def validate_font_family(font: Any, *, arg: str = "font") -> str:
    """Return *font* if it is a plausible font family name, else raise ``ValueError``.

    Letters, digits, spaces, ``_``, ``.`` and ``-`` only (every Google Fonts
    family qualifies), so the name is safe in CSS, attributes and URLs.
    """
    if not isinstance(font, str) or not _FONT_FAMILY_RE.fullmatch(font):
        raise ValueError(
            f"`{arg}` must be a font family name (letters, digits, spaces, '_', '.', '-'); got {font!r}."
        )
    return font


def is_light_color(color: str) -> bool:
    """Return ``True`` if *color* is light (perceived luminance > 0.5).

    Luminance is ``(0.299 R + 0.587 G + 0.114 B) / 255``. Accepts hex colors
    and CSS/R named colors.

    Raises:
        ValueError: For ``None``, empty strings, non-strings, sequences or
            unparseable colors.
    """
    r, g, b = color_to_rgb(color)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.5


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


def compress_number(x: Any, digits: int = 1) -> str:
    """Abbreviate a number in Brazilian Portuguese (``36400000`` -> ``"36,4 milhões"``).

    Suffixes are ``" mil"`` (>= 1e3), ``" milhões"`` (>= 1e6) and
    ``" bilhões"`` (>= 1e9); the decimal mark is a comma and the thousands
    separator a dot. ``0`` gives ``"0,0"``. Missing or non-scalar input
    (``None``, NaN, lists/tuples) gives ``"S/I"`` ("sem informação").

    Raises:
        TypeError: If *x* is a non-numeric scalar (e.g. a string).
    """
    if x is None or isinstance(x, (list, tuple, set, dict)):
        return "S/I"
    if isinstance(x, Sequence) and not isinstance(x, str):
        return "S/I"
    if isinstance(x, str) or not isinstance(x, Real):
        raise TypeError(f"`x` must be numeric, not {type(x).__name__}.")
    xf = float(x)
    if math.isnan(xf):
        return "S/I"
    if xf == 0:
        return "0,0"

    ax = abs(xf)
    if ax >= 1e9:
        value, suffix = round(xf / 1e9, digits), " bilhões"
    elif ax >= 1e6:
        value, suffix = round(xf / 1e6, digits), " milhões"
    elif ax >= 1e3:
        value, suffix = round(xf / 1e3, digits), " mil"
    else:
        value, suffix = round(xf, digits), ""

    value = value + 0.0  # normalize -0.0
    formatted = f"{value:,.{max(digits, 0)}f}"
    formatted = formatted.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return formatted.strip() + suffix


# ---------------------------------------------------------------------------
# Ids
# ---------------------------------------------------------------------------

_id_counter = itertools.count(1)


def generate_id(*parts: Any) -> str:
    """Deterministic, unique-per-call id: CRC32 of the parts plus a session counter."""
    n = next(_id_counter)
    payload = "_".join([*(as_character(p) for p in parts), str(n)])
    return f"{zlib.crc32(payload.encode('utf-8')):08x}"


def _reset_id_counter(start: int = 1) -> None:
    """Reset the id counter (for reproducible output in tests)."""
    global _id_counter
    _id_counter = itertools.count(start)


# ---------------------------------------------------------------------------
# Text wrapping
# ---------------------------------------------------------------------------


class WrappedText(NamedTuple):
    """Result of :func:`wrap_text`."""

    lines: list[str]
    height: float
    line_height: float


def wrap_text(text: Any, max_width: float, font: str = "Jost", fontsize: float = 12) -> WrappedText:
    """Greedily wrap *text* by words so each line fits *max_width* pixels.

    A word longer than *max_width* gets a line of its own (it is never
    broken). Line height is ``1.3 * fontsize``; empty text yields a single
    empty line of height ``1.2 * fontsize``.
    """
    s = as_character(text)
    if s == "":
        return WrappedText([""], fontsize * 1.2, fontsize * 1.2)

    words = s.split(" ")
    if len(words) > 1 and words[-1] == "":
        words = words[:-1]  # R's strsplit() drops one trailing empty field
    lines: list[str] = []
    current = ""
    for word in words:
        test_line = word if current == "" else f"{current} {word}"
        if text_width(test_line, font, fontsize) <= max_width:
            current = test_line
        else:
            if current != "":
                lines.append(current)
            current = word
    if current != "":
        lines.append(current)

    line_height = fontsize * 1.3
    return WrappedText(lines, len(lines) * line_height, line_height)
