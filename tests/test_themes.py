"""Mirrors tests/testthat/test-themes.R."""

from __future__ import annotations

import dataclasses

import pytest

from cardargus import CardTheme, card_theme, card_themes
from cardargus.themes import THEME_COMPONENTS

EXPECTED = {
    "default": ("#fab255", "white", "white", "#f8f8ff", "#212529", "#dee2e6", "white"),
    "light": ("#f8f9fa", "#212529", "#495057", "#ffffff", "#212529", "#dee2e6", "#6c757d"),
    "dark": ("#1e1e2e", "#cdd6f4", "#a6adc8", "#313244", "#cdd6f4", "#45475a", "#7f849c"),
    "slate": ("linear-gradient(135deg, #334155, #0f172a)", "white", "#cbd5e1", "#1e293b",
              "#e2e8f0", "#475569", "#94a3b8"),
    "ocean": ("linear-gradient(135deg, #0284c7, #1e3a8a)", "white", "white", "#f0f9ff",
              "#0c4a6e", "#bae6fd", "white"),
    "forest": ("linear-gradient(to right, #1a5a3a, #2e7d32)", "white", "white", "#f1f8e9",
               "#1b5e20", "#c5e1a5", "white"),
    "sunset": ("linear-gradient(135deg, #f59e0b, #dc2626)", "white", "white", "#fff7ed",
               "#7c2d12", "#fed7aa", "white"),
    "violet": ("linear-gradient(135deg, #667eea, #764ba2)", "white", "white", "#f5f3ff",
               "#4c1d95", "#ddd6fe", "white"),
}


def test_lists_the_presets_in_r_order():
    assert card_themes() == list(EXPECTED)


@pytest.mark.parametrize("name", list(EXPECTED))
def test_preset_values_match_r(name):
    th = card_theme(name)
    assert isinstance(th, CardTheme)
    assert th.font is None
    got = (th.bg_color, th.title_color, th.label_color, th.value_bg_color,
           th.value_text_color, th.value_border_color, th.footer_color)
    assert got == EXPECTED[name]


def test_components_names():
    assert THEME_COMPONENTS == ("bg_color", "font", "title_color", "label_color", "value_bg_color",
                                "value_text_color", "value_border_color", "footer_color")


def test_named_overrides():
    th = card_theme("dark", bg_color="#000000", footer_color="red")
    assert th.bg_color == "#000000"
    assert th.footer_color == "red"
    assert th.value_bg_color == card_theme("dark").value_bg_color


def test_theme_object_as_base():
    base = card_theme("ocean", footer_color="#cceeff")
    th = card_theme(base, bg_color="#111111")
    assert th.footer_color == "#cceeff"
    assert th.bg_color == "#111111"
    assert base.bg_color != "#111111"  # immutable


def test_validation():
    with pytest.raises(ValueError, match="Unknown theme"):
        card_theme("naoexiste")
    with pytest.raises(ValueError, match="single theme name"):
        card_theme(42)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Unknown theme component"):
        card_theme("dark", not_a_component="x")
    with pytest.raises(ValueError):
        card_theme("dark", bg_color="red; } </style><script>")
    with pytest.raises(dataclasses.FrozenInstanceError):
        card_theme("dark").bg_color = "#fff"  # type: ignore[misc]


def test_case_insensitive():
    assert card_theme("Dark") == card_theme("dark")
