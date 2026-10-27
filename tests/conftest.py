"""Shared fixtures. Tests never touch the network or the user's font cache."""

from __future__ import annotations

import warnings
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from cardargus import fonts
from cardargus.utils import _reset_id_counter

SVG_NS = "{http://www.w3.org/2000/svg}"

# Every glyph of the synthetic test font: 500 units wide, ink from 0 to 700
# (descending glyphs "gjpqy,": -200 to 500), on a 1000-unit em.
TEST_FONT_CHARS = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    " ,.&<>'\"-_:/()ãçêíõéá•"
)
TEST_FONT_DESCENDERS = set("gjpqy,")


def build_test_font(path: Path, family: str = "TestSans", chars: str | None = None) -> Path:
    """Write a tiny TrueType font with predictable metrics."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    chars = TEST_FONT_CHARS if chars is None else chars
    chars = "".join(dict.fromkeys(chars))
    names = [".notdef"] + [f"uni{ord(c):04X}" for c in chars]
    cmap = {ord(c): f"uni{ord(c):04X}" for c in chars}
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap(cmap)

    glyphs = {}
    metrics = {}
    for name in names:
        pen = TTGlyphPen(None)
        ch = chr(int(name[3:], 16)) if name.startswith("uni") else None
        if ch != " ":
            lo, hi = (-200, 500) if ch in TEST_FONT_DESCENDERS else (0, 700)
            pen.moveTo((50, lo))
            pen.lineTo((50, hi))
            pen.lineTo((450, hi))
            pen.lineTo((450, lo))
            pen.closePath()
        glyphs[name] = pen.glyph()
        metrics[name] = (500, 50)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=900, descent=-250)
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=900, sTypoDescender=-250, usWinAscent=900, usWinDescent=250)
    fb.setupPost()
    fb.save(str(path))
    return path


def _reset_font_state() -> None:
    fonts._clear_metrics_cache()
    fonts._FAILED_FAMILIES.clear()
    fonts._UPGRADE_ATTEMPTED.clear()


@pytest.fixture(autouse=True)
def isolated_env(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """Offline mode + a throwaway font cache for every test."""
    cache = tmp_path_factory.mktemp("font-cache")
    monkeypatch.setenv("CARDARGUS_CACHE_DIR", str(cache))
    monkeypatch.setenv("CARDARGUS_OFFLINE", "1")
    _reset_font_state()
    _reset_id_counter()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", fonts.FontFallbackWarning)
        yield cache
    _reset_font_state()


@pytest.fixture
def test_font(tmp_path: Path) -> str:
    """Register the synthetic font as family "TestSans" in the test cache."""
    src = build_test_font(tmp_path / "TestSans-Regular.ttf")
    fonts.register_font(src)
    return "TestSans"


def parse(svg: str) -> ET.Element:
    """Parse an SVG string (dropping the XML declaration) into its root element."""
    return ET.fromstring(svg.encode("utf-8"))


def find_all(root: ET.Element, tag: str) -> list[ET.Element]:
    return list(root.iter(f"{SVG_NS}{tag}"))


def all_text(root: ET.Element) -> str:
    return "".join(root.itertext())
