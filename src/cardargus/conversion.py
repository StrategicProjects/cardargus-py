"""Saving cards as self-contained SVG files (ported from R/conversion.R + R/fonts.R).

Only the SVG path of the R pipeline is ported: no PNG/PDF/Chrome rendering.
"""

from __future__ import annotations

import base64
import os
import re
import warnings
from pathlib import Path

from . import fonts as _fonts
from ._svgparse import svg_font_families, svg_text_content

__all__ = ["save_svg", "sanitize_svg", "embed_svg_fonts", "prepare_svg"]

_MIME_FORMAT = {
    "woff2": ("font/woff2", "woff2"),
    "ttf": ("font/ttf", "truetype"),
    "woff": ("font/woff", "woff"),
    "otf": ("font/otf", "opentype"),
}


def sanitize_svg(svg: str) -> str:
    """Remove editor metadata and Google Fonts ``@import`` rules.

    Inkscape/Sodipodi nodes and attributes (which break strict parsers when
    their namespaces are undeclared) and ``<metadata>`` blocks are dropped.
    The ``@import`` of Google Fonts is removed because the fonts are embedded
    instead (and offline renderers cannot fetch it anyway).
    """
    s = str(svg)
    s = re.sub(r"<sodipodi:namedview[^>]*?/\s*>", "", s)
    s = re.sub(r"<sodipodi:namedview[\s\S]*?</sodipodi:namedview\s*>", "", s)
    s = re.sub(r"<inkscape:page[^>]*?/\s*>", "", s)
    s = re.sub(r"<inkscape:page[\s\S]*?</inkscape:page\s*>", "", s)
    s = re.sub(r"<metadata[\s\S]*?</metadata\s*>", "", s)
    s = re.sub(r'\s+sodipodi:[a-zA-Z0-9_.-]+\s*=\s*"[^"]*"', "", s)
    s = re.sub(r'\s+inkscape:[a-zA-Z0-9_.-]+\s*=\s*"[^"]*"', "", s)
    s = re.sub(r"""@import\s+url\(["'][^"']*googleapis[^"']*["']\)\s*;?""", "", s)
    s = re.sub(r"@import\s+url\([^)]*googleapis[^)]*\)\s*;?", "", s)
    s = re.sub(r"""@import\s+url\(["'][^"']*fonts\.google[^"']*["']\)\s*;?""", "", s)
    s = re.sub(r"@import[^;]*google[^;]*;", "", s)
    return s


def embed_svg_fonts(svg: str, font_family: str, font_path: str | os.PathLike[str] | None) -> str:
    """Embed *font_path* as a base64 ``@font-face`` rule for *font_family*.

    Existing ``@font-face`` rules for the same family are replaced. The rule is
    inserted at the top of the first ``<style>`` element (created inside
    ``<defs>`` if needed). Returns *svg* unchanged if the file is missing.
    """
    if font_path is None or not Path(font_path).is_file():
        return svg
    fam = re.escape(font_family)
    s = re.sub(r'@font-face\s*\{[^}]*font-family\s*:\s*"' + fam + r'"[^}]*\}', "", svg)
    s = re.sub(r"@font-face\s*\{[^}]*font-family\s*:\s*'" + fam + r"'[^}]*\}", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)

    path = Path(font_path)
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    mime, fmt = _MIME_FORMAT.get(path.suffix.lstrip(".").lower(), _MIME_FORMAT["woff2"])
    css = (
        f'@font-face{{font-family:"{font_family}";src:url("data:{mime};base64,{b64}") '
        f'format("{fmt}");font-weight:100 900;font-style:normal;}}'
    )

    def _after(pattern: str, insert: str) -> str | None:
        m = re.search(pattern, s)
        if m is None:
            return None
        return s[: m.end()] + insert + s[m.end() :]

    for pattern, insert in (
        (r"<style[^>]*>", f"\n{css}\n"),
        (r"<defs>", f"\n<style>\n{css}\n</style>\n"),
        (r"<defs[^>]*>", f"\n<style>\n{css}\n</style>\n"),
        (r"<svg[^>]*>", f"\n<defs><style>\n{css}\n</style></defs>\n"),
    ):
        out = _after(pattern, insert)
        if out is not None:
            return out
    return s


def prepare_svg(svg: str, subset_fonts: bool = False) -> str:
    """Sanitize *svg* and embed every font family it references.

    With ``subset_fonts=True`` each embedded font is a local fontTools subset
    covering only the characters present in the SVG text (cached per
    character set); if subsetting fails the full font is embedded.
    """
    s = sanitize_svg(svg)
    families = svg_font_families(s)
    if not families:
        return s

    charset = _fonts.font_subset_charset(svg_text_content(s)) if subset_fonts else None
    for fam in families:
        path = None
        if charset:
            path = _fonts.subset_font(fam, charset)
            if path is None and _fonts.ensure_font(fam) is not None:
                warnings.warn(
                    f"Could not build a subset of font {fam!r}; embedding the full font.",
                    stacklevel=3,
                )
        if path is None:
            path = _fonts.ensure_font(fam)
        if path is None:
            warnings.warn(
                f"Font {fam!r} could not be embedded; renderers may use a fallback font.",
                stacklevel=3,
            )
            continue
        s = embed_svg_fonts(s, fam, path)
    return s


def save_svg(svg: str, path: str | os.PathLike[str], subset_fonts: bool = False) -> Path:
    """Save a card as a self-contained SVG file.

    Before writing, the SVG is sanitized and the fonts it references are
    embedded as base64 WOFF2 ``@font-face`` rules (downloaded from Google
    Fonts into the cache on first use).

    Args:
        svg: SVG string, e.g. from :func:`cardargus.svg_card`.
        path: Output file path (parent directories are created).
        subset_fonts: Embed only the glyphs used by the card text (much
            smaller files). Subsetting is done locally with fontTools.

    Returns:
        The output path.
    """
    out = Path(path)
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    content = prepare_svg(svg, subset_fonts=subset_fonts)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
        fh.write("\n")
    return out
