"""Embedding external SVG logos/icons (ported from R/logos.R)."""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple, Union

from ._svgparse import root_svg_tag, svg_dims, svg_geometry

__all__ = ["load_svg_for_embed", "create_logo_row", "EmbeddedSvg", "LogoRow", "is_svg_file"]

SvgSource = Union[str, "os.PathLike[str]"]


class EmbeddedSvg(NamedTuple):
    """An SVG resized for embedding, with its final pixel size."""

    svg_content: str
    width: float
    height: float


class LogoRow(NamedTuple):
    """Positioned logo group(s) and their combined width."""

    svg_content: str
    total_width: float
    start_x: float


def is_svg_file(src: object) -> bool:
    """``True`` if *src* is a path (str or PathLike) to an existing file, not raw SVG markup."""
    if isinstance(src, os.PathLike):
        return Path(src).is_file()
    if not isinstance(src, str):
        return False
    s = src.strip()
    if not s or "<" in s or "\n" in s or len(s) > 4096:
        return False
    try:
        return Path(s).is_file()
    except (OSError, ValueError):
        return False


def _replace_root_tag(svg: str, new_tag: str) -> str:
    m = root_svg_tag(svg)
    if m is None:
        return svg
    return svg[: m.start()] + new_tag + svg[m.end() :]


def load_svg_for_embed(
    svg_path: SvgSource,
    target_height: float = 40,
    target_width: float | None = None,
) -> EmbeddedSvg:
    """Read an SVG file and resize it for embedding inside a card.

    The XML declaration, comments and Inkscape/Sodipodi metadata are removed;
    the root ``<svg>`` gets a ``viewBox`` (if missing) and new
    ``width``/``height`` attributes that keep the aspect ratio (unless
    *target_width* is given).

    Raises:
        ValueError: If the file does not exist.
    """
    path = Path(svg_path)
    if not path.is_file():
        raise ValueError(f"SVG file not found: {path}")
    svg = path.read_text(encoding="utf-8", errors="replace")
    return embed_svg_string(svg, target_height=target_height, target_width=target_width)


def embed_svg_string(
    svg: str, target_height: float = 40, target_width: float | None = None
) -> EmbeddedSvg:
    """Same processing as :func:`load_svg_for_embed`, for an SVG string."""
    svg = re.sub(r"<\?xml[^>]*\?>", "", svg)
    svg = re.sub(r"<!--[^>]*-->", "", svg)

    geom = svg_geometry(svg)
    has_viewbox = geom.vb_w is not None and geom.vb_h is not None
    if has_viewbox:
        orig_w, orig_h = geom.vb_w, geom.vb_h
    elif geom.attr_w is not None and geom.attr_h is not None:
        orig_w, orig_h = geom.attr_w, geom.attr_h
    else:
        orig_w, orig_h = 100.0, 100.0
    assert orig_w is not None and orig_h is not None

    aspect = orig_w / orig_h if orig_h else 1.0
    new_h = float(target_height)
    new_w = float(target_width) if target_width is not None else float(round(target_height * aspect))

    # Only the root <svg> start tag is rewritten (nested <svg>s are left alone).
    m = root_svg_tag(svg)
    if m is not None:
        tag = m.group(0)
        tag = re.sub(r"""\s+width\s*=\s*("[^"]*"|'[^']*')""", "", tag, count=1)
        tag = re.sub(r"""\s+height\s*=\s*("[^"]*"|'[^']*')""", "", tag, count=1)
        extra = f' width="{new_w:.0f}" height="{new_h:.0f}"'
        if not has_viewbox:
            extra += f' viewBox="0 0 {_num(orig_w)} {_num(orig_h)}"'
        tag = "<svg" + extra + tag[4:]
        svg = _replace_root_tag(svg, tag)

    # Editor namespaces cause trouble once embedded.
    svg = re.sub(r'xmlns:inkscape="[^"]*"', "", svg)
    svg = re.sub(r'xmlns:sodipodi="[^"]*"', "", svg)
    svg = re.sub(r'sodipodi:[a-z]+="[^"]*"', "", svg)
    svg = re.sub(r'inkscape:[a-z]+="[^"]*"', "", svg)
    svg = re.sub(r"\s+>", ">", svg)
    svg = re.sub(r"<svg\s+", "<svg ", svg)
    return EmbeddedSvg(svg, new_w, new_h)


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else format(x, ".15g")


def _resize_raw_svg(logo: str, target_height: float) -> EmbeddedSvg:
    """Resize raw SVG markup to *target_height*, keeping the aspect ratio."""
    w, h = svg_dims(logo, prefer="attr")
    if w is None or h is None or h == 0:
        return EmbeddedSvg(logo, float(target_height), float(target_height))
    new_w = float(round(target_height * (w / h)))
    m = root_svg_tag(logo)
    if m is not None:
        tag = m.group(0)
        tag = re.sub(r'width="[0-9.]+"', f'width="{new_w:.0f}"', tag, count=1)
        tag = re.sub(r'height="[0-9.]+"', f'height="{target_height:.0f}"', tag, count=1)
        logo = _replace_root_tag(logo, tag)
    return EmbeddedSvg(logo, new_w, float(target_height))


def create_logo_row(
    logos: Sequence[SvgSource],
    target_height: float = 40,
    spacing: float = 10,
    card_width: float = 500,
    x_offset: float = 20,
    y_offset: float = 20,
) -> LogoRow:
    """Lay out logos in a row, right-aligned at ``card_width - x_offset``.

    Each logo may be a path to an ``.svg`` file or raw SVG markup; all are
    scaled to *target_height*.
    """
    if isinstance(logos, (str, os.PathLike)):
        logos = [logos]
    if not logos:
        return LogoRow("", 0.0, 0.0)

    processed: list[EmbeddedSvg] = []
    total_width = 0.0
    for logo in logos:
        if is_svg_file(logo):
            item = load_svg_for_embed(logo, target_height=target_height)
        elif isinstance(logo, str):
            item = _resize_raw_svg(logo, target_height)
        else:
            raise ValueError(f"Logos must be SVG strings or file paths, not {type(logo).__name__}.")
        total_width += item.width + (spacing if processed else 0)
        processed.append(item)

    start_x = card_width - x_offset - total_width
    x = start_x
    parts = []
    for item in processed:
        parts.append(f'<g transform="translate({x:.0f}, {y_offset:.0f})">{item.svg_content}</g>')
        x += item.width + spacing
    return LogoRow("\n".join(parts), total_width, start_x)
