"""Injection hardening: attribute values and SVG source resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from cardargus import (
    create_badge,
    create_logo_row,
    create_sparkline,
    icon_house,
    icon_money,
    load_svg_for_embed,
    svg_card,
)
from cardargus.logos import resolve_svg_source
from cardargus.utils import validate_color, validate_font_family
from conftest import parse

INJECTIONS = [
    '#fff" onload="alert(1)',
    "red; } </style><script>alert(1)</script>",
    "url(javascript:alert(1))",
    "linear-gradient(#fff, #000)\" onclick=\"x",
    "linear-gradient(<script>)",
    "#ggg",
    "",
    None,
    42,
]


# ---- colors ----------------------------------------------------------------


@pytest.mark.parametrize("ok", ["#fff", "#FFFA", "#fab255", "#fab25580", "white", "RebeccaPurple"])
def test_validate_color_accepts(ok):
    assert validate_color(ok) == ok


def test_validate_color_gradients():
    g = "linear-gradient(135deg, #667eea, #764ba2)"
    assert validate_color(g, allow_gradient=True) == g
    assert validate_color("linear-gradient(to right, #1a5a3a 0%, #2e7d32 100%)", allow_gradient=True)
    with pytest.raises(ValueError):
        validate_color(g)  # gradients only where supported
    with pytest.raises(ValueError):
        validate_color("radial-gradient(#fff, #000)", allow_gradient=True)
    assert validate_color("none", allow_none=True) == "none"
    with pytest.raises(ValueError):
        validate_color("none")


@pytest.mark.parametrize("bad", INJECTIONS)
def test_validate_color_rejects(bad):
    with pytest.raises(ValueError):
        validate_color(bad, allow_gradient=True)


@pytest.mark.parametrize(
    "arg",
    ["bg_color", "title_color", "label_color", "value_bg_color", "value_text_color",
     "value_border_color", "footer_color"],
)
def test_svg_card_rejects_injected_colors(arg):
    with pytest.raises(ValueError, match=arg):
        svg_card("A", fields=[[{"label": "l", "value": "v"}]], **{arg: '#fff" onload="alert(1)'})


def test_svg_card_rejects_bad_font():
    for bad in ('Jost", sans-serif; } </style><script>', "Jost<", "", "x" * 200):
        with pytest.raises(ValueError, match="font"):
            svg_card("A", font=bad)
    assert validate_font_family("Open Sans") == "Open Sans"
    assert validate_font_family("M PLUS 1p") == "M PLUS 1p"


def test_badge_color_and_font_validated():
    with pytest.raises(ValueError):
        create_badge("a", "b", '#fff" onmouseover="x')
    with pytest.raises(ValueError):
        create_badge("a", "b", "white", font='Jost" onload="x')
    with pytest.raises(ValueError):
        svg_card("A", [{"label": "a", "value": "b", "color": "red\"/><script>"}])


def test_badge_style_and_class_are_escaped():
    b = create_badge("a", "b", style='x" onload="evil', css_class='c"><script>')
    root = parse(b)
    assert root.get("style") == 'x" onload="evil'
    assert root.get("class") == 'c"><script>'
    assert "onload" not in root.attrib


def test_sparkline_and_icon_colors_validated():
    with pytest.raises(ValueError):
        create_sparkline([1, 2], color='white" onload="x')
    with pytest.raises(ValueError):
        create_sparkline([1, 2], stroke_width='2" onload="x')  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        icon_house(stroke_color='white"/><script>')
    with pytest.raises(ValueError):
        icon_money(fill="</svg>")
    assert 'fill="none"' in icon_house()


def test_text_injection_stays_text():
    payload = '"/><script>alert(1)</script>'
    svg = svg_card(payload, [{"label": payload, "value": payload}],
                   [[{"label": payload, "value": payload}]], footer=payload, alt=payload)
    root = parse(svg)
    assert not any(el.tag.endswith("script") for el in root.iter())


# ---- SVG source resolution ---------------------------------------------------


@pytest.fixture
def svg_file(tmp_path: Path) -> Path:
    p = tmp_path / "logo.svg"
    p.write_text('<?xml version="1.0"?>\n<!-- c -->\n<svg xmlns="http://www.w3.org/2000/svg" '
                 'width="20" height="10"><rect width="20" height="10"/></svg>\n')
    return p


def test_markup_is_never_read_from_disk():
    markup = '  <svg xmlns="http://www.w3.org/2000/svg" width="5" height="5"/>'
    assert resolve_svg_source(markup) == (markup, None)
    decl = '<?xml version="1.0"?><svg width="1" height="1"/>'
    assert resolve_svg_source(decl)[1] is None


def test_svg_paths_are_files(svg_file):
    for src in (svg_file, str(svg_file), f"  {svg_file}  "):
        markup, path = resolve_svg_source(src)
        assert path == svg_file
        assert "<rect" in markup and not markup.endswith("\n")


@pytest.mark.parametrize("bad", ["/etc/passwd", "~/.ssh/id_rsa", "notes.txt", "hello", "", 3, None, b"<svg/>"])
def test_other_inputs_rejected(bad):
    with pytest.raises(ValueError):
        resolve_svg_source(bad)


def test_non_svg_content_rejected(tmp_path):
    fake = tmp_path / "secret.svg"
    fake.write_text("root:x:0:0:root:/root:/bin/bash\n")
    with pytest.raises(ValueError, match="root element"):
        resolve_svg_source(fake)
    with pytest.raises(ValueError, match="root element"):
        resolve_svg_source(str(fake))
    html = tmp_path / "page.svg"
    html.write_text("<html><svg/></html>")
    with pytest.raises(ValueError, match="root element"):
        load_svg_for_embed(html)
    with pytest.raises(ValueError, match="not found"):
        resolve_svg_source(str(tmp_path / "missing.svg"))
    # PathLike is always treated as a file, whatever its extension
    txt = tmp_path / "logo.txt"
    txt.write_text("not svg")
    with pytest.raises(ValueError, match="root element"):
        resolve_svg_source(txt)


def test_with_icon_and_logos_use_resolution(svg_file, tmp_path):
    fields = lambda icon: [[{"label": "l", "value": "v", "with_icon": icon}]]  # noqa: E731
    assert "<rect" in svg_card("A", fields=fields(svg_file))
    with pytest.raises(ValueError, match="with_icon"):
        svg_card("A", fields=fields("/etc/passwd"))
    with pytest.raises(ValueError, match="with_icon"):
        svg_card("A", fields=fields("just some text"))
    with pytest.raises(ValueError, match="logos"):
        svg_card("A", logos=["/etc/hosts"])
    with pytest.raises(ValueError, match="logos"):
        create_logo_row(["plain text"])
    bad = tmp_path / "bad.svg"
    bad.write_text("SECRET")
    with pytest.raises(ValueError):
        svg_card("A", bottom_logos=[str(bad)], footer="x")
