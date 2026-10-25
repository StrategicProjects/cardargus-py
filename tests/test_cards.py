"""Structural tests for svg_card() (mirrors tests/testthat/test-cards.R)."""

from __future__ import annotations

import re

import pytest

from cardargus import card_theme, create_sparkline, icon_building, svg_card
from conftest import SVG_NS, all_text, find_all, parse

SAMPLE_FIELDS = [[{"label": "Empreendimento", "value": "CAIARA II", "with_icon": True}]]
SAMPLE_BADGES = [
    {"label": "UH", "value": "192"},
    {"label": "Recurso", "value": "36,4 milhões"},
]


def test_well_formed_with_expected_content():
    svg = svg_card("FAR", SAMPLE_BADGES, SAMPLE_FIELDS, footer="Atualizado em 2026-10-25")
    assert svg.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    root = parse(svg)
    assert root.tag == f"{SVG_NS}svg"
    assert root.get("width") == "500"
    assert root.get("viewBox") == f"0 0 500 {root.get('height')}"
    txt = all_text(root)
    for s in ("FAR", "CAIARA II", "Empreendimento", "Atualizado em 2026-10-25", "36,4 milhões"):
        assert s in txt


def test_css_classes_and_defs_structure():
    svg = svg_card("FAR", SAMPLE_BADGES, SAMPLE_FIELDS, footer="nota")
    root = parse(svg)
    classes = {e.get("class") for e in find_all(root, "text") if e.get("class")}
    assert {"card-title", "field-label", "field-value", "footer-text"} <= classes
    style = find_all(root, "style")[0].text
    assert "@import url(" in style and "family=Jost:wght@400;500;600;700&display=swap" in style
    for cls in (".card-title", ".field-label", ".field-value", ".footer-text"):
        assert cls in style
    clip = find_all(root, "clipPath")[0]
    assert clip.get("id").startswith("card-clip-")
    # Element order: title, desc?, defs, background rect, content
    children = [c.tag.replace(SVG_NS, "") for c in root]
    assert children[:4] == ["title", "defs", "rect", "text"]


def test_accessibility_nodes():
    svg = svg_card("FAR", alt="Resumo do programa FAR")
    root = parse(svg)
    assert root.get("role") == "img"
    title = root.find(f"{SVG_NS}title")
    desc = root.find(f"{SVG_NS}desc")
    assert title.text == "FAR"
    assert desc.text == "Resumo do programa FAR"
    assert set(root.get("aria-labelledby").split(" ")) == {title.get("id"), desc.get("id")}
    assert title.get("id").startswith("cardtitle-") and desc.get("id").startswith("carddesc-")


def test_no_desc_without_alt():
    for alt in (None, ""):
        root = parse(svg_card("FNHIS", alt=alt))
        assert root.find(f"{SVG_NS}title").text == "FNHIS"
        assert find_all(root, "desc") == []
        assert " " not in root.get("aria-labelledby")


def test_escapes_user_text():
    svg = svg_card(
        "A & B <teste>",
        [{"label": "a<b", "value": "\"q\""}],
        [[{"label": "L'abel", "value": "x > y"}]],
        footer='"foo"',
        alt="<desc> & co",
    )
    root = parse(svg)  # would fail to parse if unescaped
    txt = all_text(root)
    for s in ("A & B <teste>", "x > y", "L'abel", '"foo"', "<desc> & co", "a<b"):
        assert s in txt


def test_gradient_background_def():
    svg = svg_card("MCMV", bg_color="linear-gradient(to right, #1a5a3a, #2e7d32)")
    root = parse(svg)
    grads = find_all(root, "linearGradient")
    assert grads and grads[0].get("id").startswith("bg_grad_")
    assert grads[0].get("x2") == "100%"
    stops = [s.get("stop-color") for s in grads[0]]
    assert stops == ["#1a5a3a", "#2e7d32"]
    bg = root.find(f"{SVG_NS}rect")
    assert bg.get("fill") == f"url(#{grads[0].get('id')})"


def test_theme_applies_and_explicit_args_win():
    th = card_theme("dark")
    svg = svg_card("FAR", None, SAMPLE_FIELDS, theme="dark")
    assert f'fill="{th.bg_color}"' in svg
    assert f'fill="{th.value_bg_color}"' in svg
    assert f'stroke="{th.value_border_color}"' in svg
    assert f"fill: {th.title_color}" in svg

    svg2 = svg_card("FAR", None, SAMPLE_FIELDS, theme="dark", bg_color="#123456",
                    value_border_color="#ff0000", title_color="#00ff00")
    assert 'fill="#123456"' in svg2
    assert f'fill="{th.bg_color}"' not in svg2
    assert 'stroke="#ff0000"' in svg2
    assert "fill: #00ff00" in svg2
    # Untouched components still come from the theme
    assert f'fill="{th.value_bg_color}"' in svg2


def test_theme_object_and_font():
    my = card_theme("ocean", footer_color="#cceeff", font="Roboto")
    svg = svg_card("FAR", theme=my, footer="nota")
    assert "fill: #cceeff" in svg
    assert 'font-family: "Roboto"' in svg
    # Explicit font beats the theme font
    assert 'font-family: "Lato"' in svg_card("FAR", theme=my, font="Lato")


def test_defaults_without_theme():
    svg = svg_card("FAR", None, SAMPLE_FIELDS)
    assert 'fill="#fab255"' in svg
    assert 'fill="#f8f8ff"' in svg and 'stroke="#dee2e6"' in svg
    assert 'font-family: "Jost"' in svg


def test_badges_are_inlined_with_unique_ids():
    root = parse(svg_card("FAR", SAMPLE_BADGES * 2))
    ids = [e.get("id") for e in root.iter() if e.get("id")]
    assert len(ids) == len(set(ids))
    groups = [g for g in root if g.tag == f"{SVG_NS}g" and g.find(f"{SVG_NS}clipPath") is not None]
    assert len(groups) == 4
    # Every url(#...) reference points to an id defined in the card
    svg = svg_card("X", SAMPLE_BADGES + [{"label": "G", "value": "g", "color": "linear-gradient(#abc, #def)"}])
    for ref in re.findall(r"url\(#([^)]+)\)", svg):
        assert f'id="{ref}"' in svg


def test_icon_variants():
    # True -> house icon (viewBox 0 0 572 564)
    assert 'viewBox="0 0 572 564"' in svg_card("A", fields=SAMPLE_FIELDS)
    # False / None -> no icon; field spans the full content width
    for flag in (False, None):
        root = parse(svg_card("A", fields=[[{"label": "L", "value": "V", "with_icon": flag}]]))
        rect = [r for r in find_all(root, "rect") if r.get("rx") == "4"][0]
        assert rect.get("x") == "20.0" and rect.get("width") == "460.0"
    # Custom markup (sparkline) -> embedded, field shifted by 55 + 10
    spark = create_sparkline([1, 3, 2], width=55, height=34)
    root = parse(svg_card("A", fields=[[{"label": "T", "value": "Alta", "with_icon": spark},
                                         {"label": "M", "value": "Recife"}]]))
    assert find_all(root, "polyline")
    boxes = [r for r in find_all(root, "rect") if r.get("rx") == "4"]
    assert boxes[0].get("x") == "85.0"
    # Icon only on the FIRST field of a row
    svg = svg_card("A", fields=[[{"label": "a", "value": "b"},
                                  {"label": "c", "value": "d", "with_icon": True}]])
    assert "572 564" not in svg


def test_icon_from_svg_file(tmp_path):
    p = tmp_path / "icon.svg"
    p.write_text(icon_building(100, 50))  # wide: must be fitted into 50 px
    for src in (p, str(p)):
        svg = svg_card("A", fields=[[{"label": "L", "value": "V", "with_icon": src}]])
        root = parse(svg)
        inner = [e for e in root.iter(f"{SVG_NS}svg") if e is not root][0]
        assert float(inner.get("width")) <= 50


def test_wrapping_makes_taller_boxes(test_font):
    short = parse(svg_card("A", fields=[[{"label": "L", "value": "curto"}]], font=test_font))
    long = parse(svg_card("A", fields=[[{"label": "L", "value": "palavra " * 40}]], font=test_font))
    assert int(long.get("height")) > int(short.get("height"))
    values = [t for t in find_all(long, "text") if t.get("class") == "field-value"]
    assert len(values) > 1


def test_uniform_row_height():
    fields = [[{"label": "a", "value": "x"}, {"label": "b", "value": "palavra " * 30}]]
    root = parse(svg_card("A", fields=fields))
    heights = {r.get("height") for r in find_all(root, "rect") if r.get("rx") == "4"}
    assert len(heights) == 1
    root = parse(svg_card("A", fields=fields, uniform_row_height=False))
    heights = {r.get("height") for r in find_all(root, "rect") if r.get("rx") == "4"}
    assert len(heights) == 2


def test_logos_and_footer_layout(tmp_path):
    logo = tmp_path / "logo.svg"
    logo.write_text('<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" '
                    'viewBox="0 0 200 100"><rect width="200" height="100"/></svg>\n')
    svg = svg_card("A", logos=[logo], bottom_logos=[str(logo)], footer="rodapé")
    root = parse(svg)
    footer = [t for t in find_all(root, "text") if t.get("class") == "footer-text"][0]
    assert footer.get("dominant-baseline") == "middle"
    title = [t for t in find_all(root, "text") if t.get("class") == "card-title"][0]
    assert title.get("dominant-baseline") == "middle"
    nested = [e for e in root.iter(f"{SVG_NS}svg") if e is not root]
    assert [(e.get("width"), e.get("height")) for e in nested] == [("60", "30"), ("80", "40")]  # footer logos precede top-right logos (R order)
    assert "<?xml" not in svg[10:]


def test_footer_without_logos_is_alphabetic():
    root = parse(svg_card("A", footer="x"))
    footer = [t for t in find_all(root, "text") if t.get("class") == "footer-text"][0]
    assert footer.get("dominant-baseline") == "alphabetic"


def test_layout_arithmetic_with_exact_metrics(test_font):
    # Header: padding 20 + title block 16 * 1.2 + 15; no footer: + padding 20.
    assert parse(svg_card("A", font=test_font)).get("height") == str(round(20 + 19.2 + 15 + 20))
    # Test-font ink height is 0.7 em = 7.7 px at 11 px -> badge 15.4 px + 15 gap.
    root = parse(svg_card("A", [{"label": "AB", "value": "CD"}], font=test_font))
    assert root.get("height") == str(round(74.2 + 15.4 + 15))
    badge = [g for g in root if g.tag == f"{SVG_NS}g"][0]
    assert badge.get("transform") == "translate(20.0, 54.2)"
    # Badge width: label 2*5.5 + 10, value 2*5.5 + 10 + 4 -> 21 + 25
    assert badge.find(f"{SVG_NS}clipPath")[0].get("width") == "46"


def test_ids_deterministic_after_counter_reset():
    from cardargus.utils import _reset_id_counter

    _reset_id_counter()
    a = svg_card("A", SAMPLE_BADGES)
    _reset_id_counter()
    assert svg_card("A", SAMPLE_BADGES) == a


def test_numeric_values_are_accepted():
    svg = svg_card("A", [{"label": "UH", "value": 192}], [[{"label": "N", "value": 3.5}]])
    txt = all_text(parse(svg))
    assert "192" in txt and "3.5" in txt
