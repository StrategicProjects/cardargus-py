"""Lightweight SVG parsing helpers (ported from R/xml_utils.R).

The R package reads geometry and fonts with ``xml2`` and falls back to regular
expressions. cardargus for Python keeps the runtime dependency-free (no XML
parser is needed): the root ``<svg>`` start tag is located and its attributes
parsed with a tolerant regex that supports single/double quotes, any attribute
order and multi-line tags. Editor SVGs with undeclared namespace prefixes,
which strict XML parsers reject, are handled the same way.
"""

from __future__ import annotations

import html
import re
from typing import NamedTuple

_XML_DECL_RE = re.compile(r"<\?xml[^>]*\?>", re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_SVG_START_RE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(r"""([^\s=/<>"']+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_NUM_RE = re.compile(r"[0-9.]+")


def root_svg_tag(svg: str) -> re.Match[str] | None:
    """Return the match of the first (root) ``<svg ...>`` start tag."""
    cleaned = _COMMENT_RE.sub(lambda m: " " * len(m.group(0)), svg)
    return _SVG_START_RE.search(cleaned)


def root_svg_attrs(svg: str) -> dict[str, str]:
    """Attributes of the root ``<svg>`` element (empty dict if none)."""
    m = root_svg_tag(svg)
    if m is None:
        return {}
    attrs: dict[str, str] = {}
    for am in _ATTR_RE.finditer(m.group(0)[4:]):
        value = am.group(2) if am.group(2) is not None else am.group(3)
        attrs.setdefault(am.group(1), value)
    return attrs


def num_lead(x: str | None) -> float | None:
    """Leading number of a dimension string (``"40px"`` -> ``40.0``)."""
    if not x:
        return None
    m = _NUM_RE.search(x)
    if m is None:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def parse_viewbox(vb: str | None) -> tuple[float | None, float | None]:
    """Width/height of a ``"minx miny width height"`` viewBox."""
    if not vb or not vb.strip():
        return None, None
    try:
        parts = [float(p) for p in re.split(r"[ ,]+", vb.strip())]
    except ValueError:
        return None, None
    if len(parts) == 4:
        return parts[2], parts[3]
    return None, None


class SvgGeometry(NamedTuple):
    attr_w: float | None
    attr_h: float | None
    vb_w: float | None
    vb_h: float | None


def svg_geometry(svg: str) -> SvgGeometry:
    """Root width/height attributes and viewBox size (any may be ``None``)."""
    attrs = root_svg_attrs(svg)
    vb_w, vb_h = parse_viewbox(attrs.get("viewBox"))
    return SvgGeometry(num_lead(attrs.get("width")), num_lead(attrs.get("height")), vb_w, vb_h)


def svg_dimension(svg: str, attr: str, prefer: str = "attr") -> float | None:
    """One root dimension, trying the attribute or the viewBox first."""
    g = svg_geometry(svg)
    from_attr = g.attr_w if attr == "width" else g.attr_h
    from_vb = g.vb_w if attr == "width" else g.vb_h
    order = (from_attr, from_vb) if prefer == "attr" else (from_vb, from_attr)
    for val in order:
        if val is not None:
            return val
    return None


def svg_dims(svg: str, prefer: str = "attr") -> tuple[float | None, float | None]:
    return svg_dimension(svg, "width", prefer), svg_dimension(svg, "height", prefer)


# ---------------------------------------------------------------------------
# Fonts and text
# ---------------------------------------------------------------------------

_CSS_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;}{]+)")
_ATTR_FAMILY_RE = re.compile(r"""font-family\s*=\s*(?:"([^"]+)"|'([^']+)')""")
_GENERIC_FAMILIES = {"sans-serif", "serif", "monospace", "cursive", "fantasy", "system-ui"}


def normalize_font_families(families: list[str]) -> list[str]:
    """First family of each declaration, unquoted, deduplicated, no generics."""
    out: list[str] = []
    for value in families:
        first = value.split(",", 1)[0].strip()
        first = first.replace('"', "").replace("'", "").strip()
        if first and first not in out and first.lower() not in _GENERIC_FAMILIES:
            out.append(first)
    return out


def svg_font_families(svg: str) -> list[str]:
    """Font families referenced by CSS ``font-family:`` or ``font-family=""``."""
    families = [m.group(1) for m in _CSS_FAMILY_RE.finditer(svg)]
    families += [a or b for a, b in _ATTR_FAMILY_RE.findall(svg)]
    return normalize_font_families(families)


_STYLE_BLOCK_RE = re.compile(r"<style[\s\S]*?</style\s*>", re.IGNORECASE)
_SCRIPT_BLOCK_RE = re.compile(r"<script[\s\S]*?</script\s*>", re.IGNORECASE)
_TEXT_NODE_RE = re.compile(r"<(text|tspan|textPath)\b[^>]*>([^<]*)")


def svg_text_content(svg: str) -> str:
    """Visible text of ``<text>``, ``<tspan>`` and ``<textPath>`` elements."""
    s = _STYLE_BLOCK_RE.sub("", svg)
    s = _SCRIPT_BLOCK_RE.sub("", s)
    s = _COMMENT_RE.sub("", s)
    return html.unescape("".join(m.group(2) for m in _TEXT_NODE_RE.finditer(s)))


def strip_xml_declaration(svg: str) -> str:
    return _XML_DECL_RE.sub("", svg)
