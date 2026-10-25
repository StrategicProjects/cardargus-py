"""Embedding external SVG logos/icons (ported from R/logos.R)."""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple, Union

from ._svgparse import root_svg_tag, svg_dims, svg_geometry

__all__ = ["load_svg_for_embed", "create_logo_row", "resolve_svg_source", "EmbeddedSvg", "LogoRow"]

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


MAX_SVG_FILE_BYTES = 16 * 1024 * 1024

# Prolog allowed before the root element of SVG *markup*: BOM, whitespace, an
# XML declaration, comments and a DOCTYPE (without an internal subset).
_PROLOG_RE = re.compile(
    r"""\A\ufeff?(?:\s+|<\?xml\b[^>]*\?>|<!--.*?-->|<!DOCTYPE\s[^>\[]*>)*""",
    re.DOTALL | re.IGNORECASE,
)


def _starts_with_svg_root(text: str) -> bool:
    """``True`` if *text*'s first element (after the prolog) is ``<svg``."""
    rest = text[_PROLOG_RE.match(text).end() :]  # type: ignore[union-attr]
    return re.match(r"<svg[\s>/]", rest) is not None


def _read_svg_file(path: Path) -> str:
    """Read an SVG file after checking it exists, is small and is really SVG."""
    if not path.is_file():
        raise ValueError(f"SVG file not found: {path}")
    if path.stat().st_size > MAX_SVG_FILE_BYTES:
        raise ValueError(f"SVG file is too large (> {MAX_SVG_FILE_BYTES} bytes): {path}")
    raw = path.read_text(encoding="utf-8", errors="replace")
    if not _starts_with_svg_root(raw):
        raise ValueError(f"File does not contain an SVG document (root element is not <svg>): {path}")
    # Like R's readLines() + paste(collapse = "\n"): normalize EOLs, drop the final newline.
    lines = re.split(r"\r?\n", raw)
    if lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def resolve_svg_source(src: object, *, arg: str = "svg") -> tuple[str, Path | None]:
    """Decide whether *src* is raw SVG markup or an SVG file, and return its markup.

    Resolution order (no other input is ever read from disk):

    1. ``os.PathLike`` (e.g. :class:`pathlib.Path`): always a file.
    2. ``str`` whose content starts with ``<svg`` after ``lstrip()`` (an XML
       declaration, comments or a DOCTYPE may precede it): raw markup, used
       as-is. Markup is embedded verbatim, so it must come from a trusted
       source.
    3. ``str`` ending in ``.svg`` (case-insensitive): a file path.
    4. Anything else: ``ValueError``.

    A file must exist, be at most 16 MiB and have ``<svg`` as its root
    element; otherwise ``ValueError`` is raised before anything is embedded.

    Returns:
        ``(markup, path)`` where *path* is ``None`` for raw markup.
    """
    if isinstance(src, os.PathLike):
        path = Path(src)
        return _read_svg_file(path), path
    if isinstance(src, str):
        stripped = src.lstrip()
        if stripped.startswith("<") and _starts_with_svg_root(stripped):
            return src, None
        candidate = stripped.rstrip()
        if candidate.lower().endswith(".svg") and "<" not in candidate and "\n" not in candidate:
            path = Path(candidate)
            return _read_svg_file(path), path
    raise ValueError(
        f"`{arg}` must be raw SVG markup starting with '<svg', a path to an existing "
        f"'.svg' file, or an os.PathLike; got {src!r:.80}."
    )


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
        ValueError: If the file does not exist, is too large, or its root
            element is not ``<svg>``.
    """
    svg = _read_svg_file(Path(svg_path))
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

    Each logo is raw SVG markup or an SVG file, resolved by
    :func:`resolve_svg_source`; all are scaled to *target_height*.

    Raises:
        ValueError: For a logo that is neither SVG markup nor a valid SVG file.
    """
    if isinstance(logos, (str, os.PathLike)):
        logos = [logos]
    if not logos:
        return LogoRow("", 0.0, 0.0)

    processed: list[EmbeddedSvg] = []
    total_width = 0.0
    for logo in logos:
        markup, path = resolve_svg_source(logo, arg="logos")
        if path is not None:
            item = embed_svg_string(markup, target_height=target_height)
        else:
            item = _resize_raw_svg(markup, target_height)
        total_width += item.width + (spacing if processed else 0)
        processed.append(item)

    start_x = card_width - x_offset - total_width
    x = start_x
    parts = []
    for item in processed:
        parts.append(f'<g transform="translate({x:.0f}, {y_offset:.0f})">{item.svg_content}</g>')
        x += item.width + spacing
    return LogoRow("\n".join(parts), total_width, start_x)
