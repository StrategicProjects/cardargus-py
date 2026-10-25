"""Mirrors tests/testthat/test-utils.R."""

from __future__ import annotations

import math

import pytest

from cardargus import compress_number, escape_xml, is_light_color
from cardargus.utils import _reset_id_counter, as_character, generate_id, wrap_text


class TestCompressNumber:
    def test_brazilian_locale_and_suffixes(self):
        assert compress_number(0) == "0,0"
        assert compress_number(999) == "999,0"
        assert "milh" in compress_number(1234567)
        assert compress_number(36400000) == "36,4 milhões"
        assert "bilh" in compress_number(2.5e9)
        assert compress_number(1500) == "1,5 mil"

    def test_exact_values_match_r(self):
        # Values checked against the R implementation.
        assert compress_number(-1500) == "-1,5 mil"
        assert compress_number(1.5e12) == "1.500,0 bilhões"
        assert compress_number(0.04) == "0,0"
        assert compress_number(-0.04) == "0,0"  # no "-0,0"
        assert compress_number(12345678, 2) == "12,35 milhões"
        assert compress_number(36400000, 0) == "36 milhões"
        assert compress_number(2.5e9) == "2,5 bilhões"

    def test_missing_and_non_scalar(self):
        assert compress_number(None) == "S/I"
        assert compress_number(float("nan")) == "S/I"
        assert compress_number(math.nan) == "S/I"
        # Non-scalar input must not error (R issue #2)
        assert compress_number([1500, 2e6]) == "S/I"
        assert compress_number((1,)) == "S/I"

    def test_non_numeric_raises(self):
        with pytest.raises(TypeError):
            compress_number("abc")


class TestIsLightColor:
    def test_hex_and_named(self):
        assert is_light_color("#FFFFFF") is True
        assert is_light_color("#000000") is False
        assert is_light_color("#FFF") is True  # 3-digit shorthand
        assert is_light_color("white") is True
        assert is_light_color("black") is False
        assert is_light_color("White") is True  # case-insensitive like R
        assert is_light_color("#fab255") is True
        assert is_light_color("#1e1e2e") is False

    def test_r_gray_ramp(self):
        # R: col2rgb("gray50") is 127 -> dark; gray51 is 130 -> light.
        assert is_light_color("gray50") is False
        assert is_light_color("grey51") is True

    def test_rgba_hex_uses_rgb(self):
        assert is_light_color("#ffffff00") is True

    @pytest.mark.parametrize("bad", [None, "", float("nan"), "#GGGGGG", ["#fff", "#000"], "#12", 42])
    def test_rejects_invalid_input(self, bad):
        with pytest.raises(ValueError):
            is_light_color(bad)

    def test_unknown_name_message(self):
        with pytest.raises(ValueError, match="valid color"):
            is_light_color("notacolor")


class TestEscapeXml:
    def test_escapes_special_characters(self):
        assert escape_xml("a & b < c > d") == "a &amp; b &lt; c &gt; d"
        assert escape_xml("\"x\" 'y'") == "&quot;x&quot; &apos;y&apos;"

    def test_missing(self):
        assert escape_xml(None) == ""
        assert escape_xml(float("nan")) == ""
        assert escape_xml([]) == ""

    def test_vectorized(self):
        assert escape_xml(["a&b", None]) == ["a&amp;b", ""]

    def test_numbers_like_as_character(self):
        assert escape_xml(192) == "192"
        assert escape_xml(192.0) == "192"
        assert escape_xml(36.4) == "36.4"
        assert as_character(True) == "TRUE"


class TestGenerateId:
    def test_deterministic_and_unique(self):
        _reset_id_counter()
        a1 = generate_id("x", "y")
        a2 = generate_id("x", "y")
        assert a1 != a2  # unique across calls
        _reset_id_counter()
        assert generate_id("x", "y") == a1  # reproducible from the same counter
        assert len(a1) == 8 and int(a1, 16) >= 0


class TestWrapText:
    def test_empty(self):
        w = wrap_text("", 100, "Jost", 10)
        assert w.lines == [""]
        assert w.height == pytest.approx(12)
        assert w.line_height == pytest.approx(12)
        assert wrap_text(None, 100).lines == [""]

    def test_greedy_wrapping_with_exact_metrics(self, test_font):
        # Test font: every glyph advances 0.5 em -> 5 px at 10 px.
        w = wrap_text("aa bb cc", 25, test_font, 10)  # "aa bb" = 5 chars = 25 px
        assert w.lines == ["aa bb", "cc"]
        assert w.line_height == pytest.approx(13)
        assert w.height == pytest.approx(26)

    def test_long_word_gets_own_line(self, test_font):
        w = wrap_text("a verylongword b", 20, test_font, 10)
        assert w.lines == ["a", "verylongword", "b"]

    def test_heuristic_fallback_never_crashes(self):
        w = wrap_text("palavra " * 20, 50, "NoSuchFontFamily", 11)
        assert len(w.lines) > 1
