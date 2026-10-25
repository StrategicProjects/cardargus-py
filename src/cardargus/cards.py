"""SVG card generation (ported from R/cards.R)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from typing import Any

from ._svgparse import svg_dimension
from .badges import create_badge, css_gradient_to_svg, is_gradient
from .fonts import str_metrics
from .icons import icon_house
from .logos import create_logo_row, embed_svg_string, resolve_svg_source
from .themes import CardTheme, card_theme
from .utils import (
    as_character,
    escape_xml,
    fmt_num,
    generate_id,
    validate_color,
    validate_font_family,
    wrap_text,
)

__all__ = ["svg_card"]

# Built-in defaults of the themable arguments (same as R's svg_card()).
_DEFAULTS: dict[str, Any] = {
    "bg_color": "#fab255",
    "font": "Jost",
    "title_color": "white",
    "label_color": "white",
    "value_bg_color": "#f8f8ff",
    "value_text_color": "#212529",
    "value_border_color": "#dee2e6",
    "footer_color": "white",
}

ICON_SLOT_WIDTH = 55
ICON_DEFAULT_HEIGHT = 56
ICON_MAX_WIDTH = 50


def _resolve_icon(with_icon: Any) -> tuple[str, float] | None:
    """Return ``(svg, height)`` for a field's ``with_icon`` value, or ``None``.

    ``True`` gives the house icon, ``None``/``False`` no icon; anything else is
    resolved by :func:`cardargus.logos.resolve_svg_source` (raw ``<svg``
    markup, a ``.svg`` path, or an ``os.PathLike``) and invalid input raises
    ``ValueError``.
    """
    if with_icon is None or with_icon is False:
        return None
    if with_icon is True:
        return icon_house(50, 56), ICON_DEFAULT_HEIGHT
    markup, path = resolve_svg_source(with_icon, arg="with_icon")
    if path is not None:
        # Fit an external file into the 50 x 56 icon box (R only accepts raw SVG here).
        probe = embed_svg_string(markup, target_height=ICON_DEFAULT_HEIGHT)
        if probe.width > ICON_MAX_WIDTH:
            probe = embed_svg_string(
                markup, target_height=ICON_DEFAULT_HEIGHT * ICON_MAX_WIDTH / probe.width
            )
        return probe.svg_content, probe.height
    h = svg_dimension(markup, "height", prefer="attr")
    return markup, (h if h is not None else ICON_DEFAULT_HEIGHT)


def _uniquify_badge_ids(svg: str, i: int) -> str:
    svg = re.sub(r'id="s([^"]+)"', lambda m: f'id="s{m.group(1)}_{i}"', svg)
    svg = re.sub(r'id="r([^"]+)"', lambda m: f'id="r{m.group(1)}_{i}"', svg)
    svg = re.sub(r'#s([^")]+)', lambda m: f"#s{m.group(1)}_{i}", svg)
    svg = re.sub(r'#r([^")]+)', lambda m: f"#r{m.group(1)}_{i}", svg)
    return svg


def _strip_outer_svg(svg: str) -> str:
    svg = re.sub(r"<\?xml[^>]*\?>", "", svg)
    svg = re.sub(r"<svg[^>]*>", "", svg)
    return svg.replace("</svg>", "")


def _as_rows(fields: Sequence[Any] | None) -> list[list[Mapping[str, Any]]]:
    rows: list[list[Mapping[str, Any]]] = []
    for row in fields or []:
        if isinstance(row, Mapping):
            rows.append([row])
        else:
            rows.append(list(row))
    return rows


def _as_list(x: Any) -> list[Any]:
    if x is None:
        return []
    if isinstance(x, (str, os.PathLike)):
        return [x]
    return list(x)


def svg_card(
    title: str = "FAR",
    badges_data: Sequence[Mapping[str, Any]] | None = None,
    fields: Sequence[Sequence[Mapping[str, Any]]] | None = None,
    *,
    theme: str | CardTheme | None = None,
    alt: str | None = None,
    bg_color: str | None = None,
    width: float = 500,
    padding: float = 20,
    corner_radius: float = 8,
    font: str | None = None,
    title_fontsize: float = 16,
    title_color: str | None = None,
    label_fontsize: float = 11,
    value_fontsize: float = 11,
    label_color: str | None = None,
    value_bg_color: str | None = None,
    value_text_color: str | None = None,
    value_border_color: str | None = None,
    logos: Sequence[str | os.PathLike[str]] | None = None,
    logos_height: float = 40,
    bottom_logos: Sequence[str | os.PathLike[str]] | None = None,
    bottom_logos_height: float = 30,
    footer: str | None = None,
    gap_to_footer: float = 6,
    footer_row_padding_bottom: float = 6,
    footer_fontsize: float = 8,
    footer_color: str | None = None,
    uniform_row_height: bool = True,
) -> str:
    """Create an information card as a self-contained SVG string.

    Args:
        title: Card title, also embedded as the SVG ``<title>``.
        badges_data: Badges shown under the title: dicts with ``label``,
            ``value`` and optional ``color`` (default ``"white"``).
        fields: Rows of fields. Each row is a list of dicts with ``label``,
            ``value`` and optional ``with_icon`` (only honored on the *first*
            field of a row): ``True`` for the house icon, ``False``/``None``
            for none, or raw SVG markup / a path to an ``.svg`` file.
        theme: Preset name (see :func:`cardargus.card_themes`) or a
            :class:`cardargus.CardTheme`. It supplies defaults for
            ``bg_color``, ``font``, ``title_color``, ``label_color``,
            ``value_bg_color``, ``value_text_color``, ``value_border_color``
            and ``footer_color``; arguments passed explicitly always win.
        alt: Optional alternative text, embedded as ``<desc>`` for screen readers.
        bg_color: Solid color or CSS ``linear-gradient(...)``. Default ``"#fab255"``.
        width: Card width in pixels.
        padding: Inner padding.
        corner_radius: Corner radius of the card.
        font: Font family (Google Font). Default ``"Jost"``.
        title_fontsize: Title font size.
        title_color: Title color. Default ``"white"``.
        label_fontsize: Field label font size.
        value_fontsize: Field value (and badge) font size.
        label_color: Field label color. Default ``"white"``.
        value_bg_color: Value box fill. Default ``"#f8f8ff"``.
        value_text_color: Value text color. Default ``"#212529"``.
        value_border_color: Value box border. Default ``"#dee2e6"``.
        logos: SVG strings or file paths shown at the top right.
        logos_height: Height of the top-right logos.
        bottom_logos: SVG strings or file paths shown on the footer row (right).
        bottom_logos_height: Height of the footer logos.
        footer: Footer text (e.g. an update timestamp).
        gap_to_footer: Distance between the last field row and the footer row.
        footer_row_padding_bottom: Padding under the footer row.
        footer_fontsize: Footer font size.
        footer_color: Footer text color. Default ``"white"``.
        uniform_row_height: Give every value box in a row the same height.

    Returns:
        The SVG document as a string.

    Raises:
        ValueError: For an unknown theme, an invalid color (colors must be
            hex, named, or -- for ``bg_color`` -- a ``linear-gradient(...)``),
            an invalid font family name, or an icon/logo that is neither SVG
            markup nor a valid ``.svg`` file (see
            :func:`cardargus.logos.resolve_svg_source`).

    Note:
        Text (title, labels, values, footer, alt) is XML-escaped. Raw SVG
        markup passed as ``with_icon``/``logos`` is embedded verbatim and must
        come from a trusted source.
    """
    # ===== THEME SUPPORT =====
    explicit = {
        "bg_color": bg_color,
        "font": font,
        "title_color": title_color,
        "label_color": label_color,
        "value_bg_color": value_bg_color,
        "value_text_color": value_text_color,
        "value_border_color": value_border_color,
        "footer_color": footer_color,
    }
    th = None
    if theme is not None:
        th = theme if isinstance(theme, CardTheme) else card_theme(theme)
    resolved: dict[str, Any] = {}
    for key, value in explicit.items():
        if value is not None:
            resolved[key] = value
        elif th is not None and getattr(th, key) is not None:
            resolved[key] = getattr(th, key)
        else:
            resolved[key] = _DEFAULTS[key]
    # User values land in SVG attributes and in <style>: validate them all.
    for key, value in resolved.items():
        if key == "font":
            validate_font_family(value, arg="font")
        else:
            validate_color(value, arg=key, allow_gradient=(key == "bg_color"))
    bg_color = resolved["bg_color"]
    font = resolved["font"]
    title_color = resolved["title_color"]
    label_color = resolved["label_color"]
    value_bg_color = resolved["value_bg_color"]
    value_text_color = resolved["value_text_color"]
    value_border_color = resolved["value_border_color"]
    footer_color = resolved["footer_color"]
    assert isinstance(font, str)

    badges = list(badges_data or [])
    rows = _as_rows(fields)
    top_logos = _as_list(logos)
    foot_logos = _as_list(bottom_logos)

    card_id = generate_id(title, bg_color, fmt_num(width))

    # ===== GRADIENT BACKGROUND =====
    if is_gradient(bg_color):
        bg_grad_id = f"bg_grad_{card_id}"
        bg_gradient_def = css_gradient_to_svg(bg_color, id=bg_grad_id)
        bg_fill = f"url(#{bg_grad_id})"
    else:
        bg_gradient_def = ""
        bg_fill = bg_color

    content_width = width - 2 * padding
    current_y: float = padding
    elements: list[str] = []
    W, R = fmt_num(width), fmt_num(corner_radius)

    # ===== DEFS (styles, clip path, gradient) =====
    defs = f"""
    <defs>
      <style>
        @import url("https://fonts.googleapis.com/css2?family={font.replace(" ", "+")}:wght@400;500;600;700&amp;display=swap");
        .card-title {{ font-family: "{font}", sans-serif; font-weight: 700; font-size: {fmt_num(title_fontsize)}px; fill: {title_color}; }}
        .field-label {{ font-family: "{font}", sans-serif; font-weight: 600; font-size: {fmt_num(label_fontsize)}px; fill: {label_color}; }}
        .field-value {{ font-family: "{font}", sans-serif; font-weight: 400; font-size: {fmt_num(value_fontsize)}px; fill: {value_text_color}; }}
        .footer-text {{ font-family: "{font}", sans-serif; font-style: italic; font-size: {fmt_num(footer_fontsize)}px; fill: {footer_color}; opacity: 0.8; }}
      </style>
      <clipPath id="card-clip-{card_id}">
        <rect width="{W}" rx="{R}" ry="{R}"/>
      </clipPath>
      {bg_gradient_def}
    </defs>"""

    # ===== TITLE =====
    has_top_logos = len(top_logos) > 0
    title_block_h = title_fontsize * 1.2
    header_height = max(title_block_h, logos_height if has_top_logos else title_block_h)
    if has_top_logos:
        title_y = current_y + header_height / 2
        title_baseline = "middle"
    else:
        title_y = current_y + title_fontsize
        title_baseline = "alphabetic"
    elements.append(
        f'<text x="{fmt_num(padding)}" y="{title_y:.1f}" class="card-title" '
        f'dominant-baseline="{title_baseline}">{escape_xml(title)}</text>'
    )
    current_y += header_height + 15

    # ===== BADGES (uniform height) =====
    if badges:
        badge_x: float = padding
        badge_y = current_y
        max_badge_height = 0.0
        for badge in badges:
            ml = str_metrics(as_character(badge.get("label")), font, value_fontsize)
            mv = str_metrics(as_character(badge.get("value")), font, value_fontsize)
            badge_h = max(ml.ascent + ml.descent, mv.ascent + mv.descent) * 2
            max_badge_height = max(max_badge_height, badge_h)

        for i, badge in enumerate(badges, start=1):
            color = badge.get("color") or "white"
            result = create_badge(
                label=badge.get("label"),
                value=badge.get("value"),
                color=color,
                font=font,
                fontsize=value_fontsize,
                style="",
                shadow_offset=1,
                height=max_badge_height / 2,  # create_badge doubles it
                as_string=False,
            )
            assert not isinstance(result, str)
            inner = _strip_outer_svg(_uniquify_badge_ids(result.svg, i))
            elements.append(f'<g transform="translate({badge_x:.1f}, {badge_y:.1f})">{inner}</g>')
            badge_x += result.width + 4
        current_y += max_badge_height + 15

    # ===== FIELDS =====
    row_spacing = 12
    field_spacing = 10
    value_box_padding_x = 10
    value_box_padding_y = 8
    value_box_radius = 4

    for row in rows:
        if not row:
            continue
        num_fields = len(row)
        available_width = content_width - (num_fields - 1) * field_spacing

        icon = _resolve_icon(row[0].get("with_icon"))
        has_icon = icon is not None
        icon_width = ICON_SLOT_WIDTH if has_icon else 0

        if has_icon and num_fields == 1:
            field_widths = [content_width - icon_width - field_spacing]
        else:
            field_widths = [available_width / num_fields] * num_fields
            if has_icon:
                field_widths[0] -= icon_width + field_spacing

        row_height = 0.0
        field_data = []
        for field, fw in zip(row, field_widths):
            wrapped = wrap_text(field.get("value"), fw - 2 * value_box_padding_x, font, value_fontsize)
            field_height = label_fontsize + 4 + wrapped.height + 2 * value_box_padding_y
            row_height = max(row_height, field_height)
            field_data.append((field, fw, wrapped))

        field_x: float = padding
        if icon is not None:
            icon_svg, icon_height = icon
            icon_y = current_y + (row_height - icon_height) / 2
            elements.append(f'<g transform="translate({field_x:.1f}, {icon_y:.1f})">{icon_svg}</g>')
            field_x += icon_width + field_spacing

        for i, (field, fw, wrapped) in enumerate(field_data):
            if i > 0:
                field_x += field_data[i - 1][1] + field_spacing

            elements.append(
                f'<text x="{field_x:.1f}" y="{current_y + label_fontsize:.1f}" '
                f'class="field-label">{escape_xml(field.get("label"))}</text>'
            )

            box_y = current_y + label_fontsize + 4
            if uniform_row_height:
                box_height = row_height - (label_fontsize + 4)
            else:
                box_height = wrapped.height + 2 * value_box_padding_y
            elements.append(
                f'<rect x="{field_x:.1f}" y="{box_y:.1f}" width="{fw:.1f}" height="{box_height:.1f}" '
                f'rx="{value_box_radius}" fill="{value_bg_color}" stroke="{value_border_color}" '
                f'stroke-width="1"/>'
            )

            if uniform_row_height:
                text_block_h = len(wrapped.lines) * wrapped.line_height
                extra = max(0.0, box_height - 2 * value_box_padding_y - text_block_h)
                text_y = box_y + value_box_padding_y + extra / 2 + value_fontsize * 0.85
            else:
                text_y = box_y + value_box_padding_y + value_fontsize * 0.85
            for line in wrapped.lines:
                elements.append(
                    f'<text x="{field_x + value_box_padding_x:.1f}" y="{text_y:.1f}" '
                    f'class="field-value">{escape_xml(line)}</text>'
                )
                text_y += wrapped.line_height

        current_y += row_height + row_spacing

    # ===== FINAL HEIGHT (depends on the footer row) =====
    footer_present = footer is not None or len(foot_logos) > 0
    has_bottom_logos = len(foot_logos) > 0
    footer_row_height = max(footer_fontsize, bottom_logos_height if has_bottom_logos else 0)
    if footer_present:
        final_height = current_y + gap_to_footer + footer_row_height + footer_row_padding_bottom
    else:
        final_height = current_y + padding

    # ===== TOP-RIGHT LOGOS =====
    top_logos_svg = ""
    if has_top_logos:
        top_logos_svg = create_logo_row(
            top_logos,
            target_height=logos_height,
            spacing=10,
            card_width=width,
            x_offset=padding,
            y_offset=padding,
        ).svg_content

    # ===== FOOTER (text left, logos right, anchored to the bottom) =====
    footer_elements: list[str] = []
    if footer_present:
        footer_row_y_top = final_height - footer_row_padding_bottom - footer_row_height
        footer_row_y_bottom = footer_row_y_top + footer_row_height
        if footer is not None:
            if has_bottom_logos:
                footer_y = footer_row_y_top + footer_row_height / 2
                footer_baseline = "middle"
            else:
                footer_y = footer_row_y_bottom - 2
                footer_baseline = "alphabetic"
            footer_elements.append(
                f'<text x="{fmt_num(padding)}" y="{footer_y:.1f}" class="footer-text" '
                f'dominant-baseline="{footer_baseline}">{escape_xml(footer)}</text>'
            )
        if has_bottom_logos:
            logos_y = final_height - footer_row_padding_bottom - bottom_logos_height
            footer_elements.append(
                create_logo_row(
                    foot_logos,
                    target_height=bottom_logos_height,
                    spacing=10,
                    card_width=width,
                    x_offset=padding,
                    y_offset=logos_y,
                ).svg_content
            )

    # ===== ACCESSIBILITY (<title>/<desc> + WAI-ARIA) =====
    a11y_title_id = f"cardtitle-{card_id}"
    a11y_ids = a11y_title_id
    a11y_nodes = f'<title id="{a11y_title_id}">{escape_xml(title)}</title>'
    if isinstance(alt, str) and alt:
        a11y_desc_id = f"carddesc-{card_id}"
        a11y_ids += f" {a11y_desc_id}"
        a11y_nodes += f'\n  <desc id="{a11y_desc_id}">{escape_xml(alt)}</desc>'

    # ===== ASSEMBLE =====
    H = str(round(final_height))
    body = "\n  ".join(elements + footer_elements)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="{a11y_ids}">
  {a11y_nodes}
  {defs}
  <!-- Background -->
  <rect width="{W}" height="{H}" rx="{R}" fill="{bg_fill}"/>
  <!-- Content -->
  {body}
  <!-- Top-right logos -->
  {top_logos_svg}
</svg>"""
