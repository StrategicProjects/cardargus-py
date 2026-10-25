"""Mirrors tests/testthat/test-badges.R."""

from __future__ import annotations

from cardargus import Badge, create_badge, css_gradient_to_svg
from conftest import SVG_NS, all_text, find_all, parse


def test_gradient_direction_keywords():
    out = css_gradient_to_svg("linear-gradient(to right, #1a5a3a, #2e7d32)")
    assert out.startswith('<linearGradient id="grad"')
    assert 'x1="0%"' in out and 'x2="100%"' in out
    assert "#1a5a3a" in out and "#2e7d32" in out


def test_gradient_keywords_and_default():
    assert 'x1="100%" y1="0%" x2="0%" y2="0%"' in css_gradient_to_svg("linear-gradient(to left, #a, #b)")
    assert 'x1="0%" y1="100%" x2="0%" y2="0%"' in css_gradient_to_svg("linear-gradient(to top, #abc)")
    assert 'x1="0%" y1="0%" x2="0%" y2="100%"' in css_gradient_to_svg("linear-gradient(#abc, #def)")


def test_gradient_angles_match_r():
    out = css_gradient_to_svg("linear-gradient(135deg, #667eea, #764ba2)", id="g")
    assert out == ('<linearGradient id="g" x1="15%" y1="15%" x2="85%" y2="85%">'
                   '<stop offset="0%" stop-color="#667eea"/><stop offset="100%" stop-color="#764ba2"/>'
                   "</linearGradient>")
    three = css_gradient_to_svg("linear-gradient(45deg, #abc, #123456, #fff)")
    assert 'offset="50%" stop-color="#123456"' in three


def test_single_color_and_no_color():
    out = css_gradient_to_svg("linear-gradient(to right, #abcdef)")
    assert out.count("#abcdef") == 2 and "#000000" not in out
    out = css_gradient_to_svg("linear-gradient(to right)")
    assert "#ffffff" in out and "#000000" in out


def test_badge_gradient_colors():
    b1 = create_badge("Test", "OK", "linear-gradient(to right, #4CAF50)")
    assert "#4CAF50" in b1
    b2 = create_badge("Test", "OK", "linear-gradient(135deg, #1a5a3a, #2e7d32)")
    root = parse(b2)
    grad = find_all(root, "linearGradient")
    assert any(g.get("id", "").startswith("grad_") for g in grad)
    assert "#2e7d32" in b2


def test_badge_solid_structure():
    b = create_badge("UH", "192", "white")
    root = parse(b)
    assert root.tag == f"{SVG_NS}svg"
    assert root.get("role") == "img" and root.get("aria-label") == "UH: 192"
    assert root.find(f"{SVG_NS}title").text == "UH: 192"
    texts = find_all(root, "text")
    assert len(texts) == 4
    # Light value background -> dark text (#333) with a light shadow
    assert texts[3].get("fill") == "#333" and texts[2].get("fill") == "#ccc"
    dark = parse(create_badge("UH", "192", "#123456"))
    assert find_all(dark, "text")[3].get("fill") == "#fff"


def test_badge_as_object_and_height(test_font):
    res = create_badge("AB", "CD", font=test_font, fontsize=10, as_string=False)
    assert isinstance(res, Badge)
    # 2 chars * 5 px + 2*5 padding = 20; value adds 2*2 extra padding = 24
    assert (res.width, res.height) == (44, 14)  # ink 0.7 em = 7 px, doubled
    forced = create_badge("AB", "CD", font=test_font, height=12, as_string=False)
    assert forced.height == 24


def test_badge_escapes_text():
    b = create_badge("a<b", "x & \"y\"")
    root = parse(b)
    assert "a<b" in all_text(root) and 'x & "y"' in all_text(root)
