"""Font cache, metrics, subsetting and save_svg (offline; mirrors test-fonts.R)."""

from __future__ import annotations

import base64
import io
import re
import warnings

import pytest
from fontTools.ttLib import TTFont

from cardargus import fonts, font_available, font_cache_dir, list_fonts, register_font, save_svg, svg_card
from cardargus.conversion import embed_svg_fonts, sanitize_svg
from cardargus._svgparse import svg_font_families, svg_text_content
from cardargus.fonts import font_cache_path, font_subset_charset, str_metrics
from conftest import build_test_font, parse


# ---- charset normalization and cache keys --------------------------------


def test_charset_normalization():
    assert font_subset_charset("baa") == "ab"
    assert font_subset_charset("CAIARA II") == font_subset_charset("IRA CAI A")
    assert font_subset_charset(None) is None
    assert font_subset_charset("") is None
    assert font_subset_charset(["ab", "bc"]) == "abc"
    assert font_subset_charset("õa") == "aõ"  # sorted by code point


def test_cache_path_separates_subsets():
    full = font_cache_path("Jost")
    sub1 = font_cache_path("Jost", text="abc")
    sub2 = font_cache_path("Jost", text="abd")
    assert full.name == "Jost.woff2"
    assert sub1 != full and sub1 != sub2
    assert re.fullmatch(r"Jost_sub[0-9a-f]{10}\.woff2", sub1.name)
    assert sub1 == font_cache_path("Jost", text="abc")  # deterministic
    assert font_cache_path("Jost", text=None) == full
    assert font_cache_path("Open Sans").name == "Open_Sans.woff2"
    # Same glyph set -> same cache file
    assert font_cache_path("Jost", font_subset_charset("CAIARA")) == font_cache_path(
        "Jost", font_subset_charset("ARCAI")
    )


def test_cache_dir_honors_env(isolated_env):
    assert font_cache_dir() == isolated_env


# ---- registration ----------------------------------------------------------


def test_register_font_derives_family(tmp_path):
    src = build_test_font(tmp_path / "MyFont-SemiBold.ttf")
    out = register_font(src)
    assert out.name == "MyFont.ttf"
    assert font_available("MyFont")
    assert "MyFont" in list_fonts()
    assert register_font(src, family="Other Name").name == "Other_Name.ttf"


def test_register_font_validation(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        register_font(tmp_path / "missing.ttf")
    bad = tmp_path / "font.txt"
    bad.write_text("x")
    with pytest.raises(ValueError, match="Unsupported"):
        register_font(bad)


# ---- metrics ----------------------------------------------------------------


def test_exact_metrics_from_font(test_font):
    m = str_metrics("Hg", test_font, 10)
    assert m.width == pytest.approx(10.0)  # 2 x 500 units at 10 px / 1000
    assert m.ascent == pytest.approx(7.0)
    assert m.descent == pytest.approx(2.0)
    m = str_metrics("ab", test_font, 10)
    assert m.descent == pytest.approx(0.0)
    assert str_metrics("", test_font, 10) == (0.0, 0.0, 0.0)
    assert str_metrics(" ", test_font, 10).ascent == 0.0  # space has no ink


def test_unmapped_chars_use_heuristic_advance(test_font):
    assert str_metrics("ж", test_font, 10).width == pytest.approx(5.5)


def test_offline_heuristic_and_single_warning():
    fonts._clear_metrics_cache()
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        m1 = str_metrics("abcd", "NotCachedFamily", 10)
        str_metrics("efgh", "NotCachedFamily", 10)
    assert m1.width == pytest.approx(22.0)
    assert m1.ascent == pytest.approx(7.5) and m1.descent == pytest.approx(2.0)
    assert sum(issubclass(w.category, fonts.FontFallbackWarning) for w in rec) == 1


def test_no_download_when_offline(monkeypatch):
    def boom(*a, **k):  # pragma: no cover - must not be called
        raise AssertionError("network access attempted")

    monkeypatch.setattr(fonts, "_http_get", boom)
    assert fonts.download_google_font("Jost") is None
    assert fonts.ensure_font("Jost") is None


# ---- Google Fonts CSS parsing (no network) ---------------------------------

GOOGLE_CSS = """
/* cyrillic */
@font-face {
  font-family: 'Jost';
  src: url(https://fonts.gstatic.com/s/jost/v20/cyr.woff2) format('woff2');
  unicode-range: U+0301, U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116;
}
/* latin */
@font-face {
  font-family: 'Jost';
  src: url(https://fonts.gstatic.com/s/jost/v20/latin.woff2) format('woff2');
  unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+2000-206F;
}
"""


def test_css_parsing_picks_latin_block():
    faces = fonts._parse_font_faces(GOOGLE_CSS)
    assert [f.url.rsplit("/", 1)[1] for f in faces] == ["cyr.woff2", "latin.woff2"]
    assert fonts._pick_face(faces, "woff2").url.endswith("latin.woff2")


def test_css_parsing_extensionless_kit_url():
    css = "@font-face { src: url(https://fonts.gstatic.com/l/font?kit=abc&skey=1) format('woff2'); }"
    face = fonts._pick_face(fonts._parse_font_faces(css), "woff2")
    assert face.url == "https://fonts.gstatic.com/l/font?kit=abc&skey=1"


def test_download_with_mocked_http(monkeypatch, tmp_path):
    font_bytes = build_test_font(tmp_path / "x.ttf").read_bytes()
    woff2 = io.BytesIO()
    f = TTFont(io.BytesIO(font_bytes))
    f.flavor = "woff2"
    f.save(woff2)

    calls = []

    def fake_get(url, ua, timeout=15.0):
        calls.append((url, ua))
        if "googleapis" in url:
            return GOOGLE_CSS.encode()
        assert url.endswith("latin.woff2")
        return woff2.getvalue()

    monkeypatch.setenv("CARDARGUS_OFFLINE", "0")
    monkeypatch.setattr(fonts, "_http_get", fake_get)
    path = fonts.download_google_font("Jost")
    assert path is not None and path.name == "Jost.woff2"
    assert "Chrome" in calls[0][1]
    assert "family=Jost:wght@400" in calls[0][0]


# ---- subsetting and save_svg ------------------------------------------------


def _embedded_font(svg: str) -> TTFont:
    b64 = re.search(r'base64,([A-Za-z0-9+/=]+)"', svg).group(1)
    return TTFont(io.BytesIO(base64.b64decode(b64)))


def test_save_svg_embeds_full_font(test_font, tmp_path):
    svg = svg_card("Ab", font=test_font, footer="cd")
    out = save_svg(svg, tmp_path / "sub" / "card.svg")
    content = out.read_text(encoding="utf-8")
    assert content.endswith("</svg>\n")
    assert "@import" not in content
    assert '@font-face{font-family:"TestSans";src:url("data:font/ttf;base64,' in content
    assert 'format("truetype")' in content
    parse(content)
    assert len(_embedded_font(content).getGlyphOrder()) > 60


def test_save_svg_subsets_locally(test_font, tmp_path):
    svg = svg_card("CAIARA", [{"label": "UH", "value": "192"}], font=test_font)
    out = save_svg(svg, tmp_path / "card.svg", subset_fonts=True)
    content = out.read_text(encoding="utf-8")
    assert "data:font/woff2;base64," in content and 'format("woff2")' in content
    font = _embedded_font(content)
    assert font.flavor == "woff2"
    cmap = set(font.getBestCmap())
    expected = set(map(ord, svg_text_content(svg)))
    assert expected <= cmap
    assert ord("z") not in cmap  # unused glyphs were dropped
    # Cached per normalized charset and reused
    sub = font_cache_path(test_font, font_subset_charset(svg_text_content(svg)))
    assert sub.is_file()
    mtime = sub.stat().st_mtime_ns
    save_svg(svg, tmp_path / "again.svg", subset_fonts=True)
    assert sub.stat().st_mtime_ns == mtime


def test_save_svg_warns_when_font_missing(tmp_path):
    svg = svg_card("A", font="Unavailable Font")
    with pytest.warns(UserWarning, match="could not be embedded"):
        out = save_svg(svg, tmp_path / "c.svg")
    assert "@font-face" not in out.read_text(encoding="utf-8")


def test_embed_replaces_existing_rule(test_font, tmp_path):
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><defs><style>@font-face{font-family:"TestSans";src:url(x)}</style></defs></svg>'
    path = font_cache_dir() / "TestSans.ttf"
    out = embed_svg_fonts(svg, "TestSans", path)
    assert out.count("@font-face") == 1 and "url(x)" not in out
    bare = embed_svg_fonts('<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>', "TestSans", path)
    assert "<defs><style>" in bare
    assert embed_svg_fonts(svg, "TestSans", tmp_path / "nope.ttf") == svg


def test_font_detection_and_text_content():
    svg = svg_card("Título &amp;", [{"label": "UH", "value": "1"}], footer="f")
    assert svg_font_families(svg) == ["Jost"]
    assert svg_font_families('<text font-family="Arial, sans-serif">x</text>') == ["Arial"]
    text = svg_text_content(svg)
    assert "Título &amp;" in text and "UH" in text and ".card-title" not in text


def test_sanitize_removes_editor_metadata_and_imports():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" sodipodi:docname="x" inkscape:version="1">'
           '<sodipodi:namedview id="n"/><metadata>m</metadata>'
           '<style>@import url("https://fonts.googleapis.com/css2?family=Jost&amp;display=swap");</style></svg>')
    out = sanitize_svg(svg)
    assert "sodipodi" not in out and "inkscape" not in out and "metadata" not in out
    assert "@import" not in out


# ---- latin-ext coverage upgrade (R package issue #29) -----------------------

CSS2_WITH_LATIN_EXT = """
/* latin-ext */
@font-face {
  font-family: 'Upfam';
  src: url(https://fonts.gstatic.com/s/upfam/latin-ext.woff2) format('woff2');
  unicode-range: U+0100-024F, U+1E00-1EFF;
}
/* latin */
@font-face {
  font-family: 'Upfam';
  src: url(https://fonts.gstatic.com/s/upfam/latin.woff2) format('woff2');
  unicode-range: U+0000-00FF, U+0131, U+2000-206F;
}
"""

MERGED_CSS = """
@font-face {
  font-family: 'Upfam';
  src: url(https://fonts.gstatic.com/s/upfam/merged.ttf) format('truetype');
}
"""

EXTENDED_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz Łódź"


def _seed_partial_latin_font(tmp_path, family="Upfam"):
    """Cache a latin-only woff2 with CSS-API provenance, as 'downloaded'."""
    ttf = build_test_font(tmp_path / "latin.ttf", family=family)
    f = TTFont(str(ttf))
    f.flavor = "woff2"
    buf = io.BytesIO()
    f.save(buf)
    dest = font_cache_dir() / f"{family}.woff2"
    dest.write_bytes(buf.getvalue())
    fonts._write_provenance(dest, ["latin"])
    return dest


def _merged_ttf_bytes(tmp_path, family="Upfam"):
    return build_test_font(tmp_path / "merged.ttf", family=family, chars=EXTENDED_CHARS).read_bytes()


def _upgrade_http_mock(monkeypatch, tmp_path, calls):
    merged = _merged_ttf_bytes(tmp_path)

    def fake_get(url, ua, timeout=15.0):
        calls.append(url)
        if "css2?family=Upfam" in url:
            assert "Chrome" in ua
            return CSS2_WITH_LATIN_EXT.encode()
        if "css?family=Upfam" in url and "subset=" in url:
            assert ua == fonts.PLAIN_USER_AGENT
            assert "subset=latin,latin-ext" in url
            return MERGED_CSS.encode()
        if url.endswith("merged.ttf"):
            return merged
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setenv("CARDARGUS_OFFLINE", "0")
    monkeypatch.setattr(fonts, "_http_get", fake_get)


def test_parse_font_faces_captures_subset_names():
    faces = fonts._parse_font_faces(GOOGLE_CSS)
    assert [f.subset for f in faces] == ["cyrillic", "latin"]
    assert fonts._parse_font_faces(MERGED_CSS)[0].subset is None


def test_download_writes_provenance_sidecar(monkeypatch, tmp_path):
    font_bytes = build_test_font(tmp_path / "x.ttf").read_bytes()
    woff2 = io.BytesIO()
    f = TTFont(io.BytesIO(font_bytes))
    f.flavor = "woff2"
    f.save(woff2)

    def fake_get(url, ua, timeout=15.0):
        if "googleapis" in url:
            return GOOGLE_CSS.encode()
        return woff2.getvalue()

    monkeypatch.setenv("CARDARGUS_OFFLINE", "0")
    monkeypatch.setattr(fonts, "_http_get", fake_get)
    path = fonts.download_google_font("Jost")
    assert fonts._read_provenance(path) == ["latin"]


def test_ensure_font_for_text_leaves_fonts_without_sidecar_alone(test_font, monkeypatch):
    # Local fonts (register_font) have no .gsubsets sidecar: never touched,
    # never any network, even online and with unmapped characters.
    monkeypatch.setenv("CARDARGUS_OFFLINE", "0")

    def boom(*a, **k):  # pragma: no cover - must not be called
        raise AssertionError("network access attempted")

    monkeypatch.setattr(fonts, "_http_get", boom)
    before = fonts.ensure_font("TestSans")
    assert fonts._read_provenance(before) is None
    after = fonts.ensure_font_for_text("TestSans", "Łódź")
    assert after == before


def test_ensure_font_for_text_is_noop_when_covered(monkeypatch, tmp_path):
    dest = _seed_partial_latin_font(tmp_path)

    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("network access attempted")

    monkeypatch.setenv("CARDARGUS_OFFLINE", "0")
    monkeypatch.setattr(fonts, "_http_get", boom)
    # All chars inside the cached cmap: no upgrade, no network.
    assert fonts.ensure_font_for_text("Upfam", "Educacao") == dest


def test_ensure_font_for_text_upgrades_partial_block(monkeypatch, tmp_path):
    dest = _seed_partial_latin_font(tmp_path)
    # Stale derived subset must be dropped by the upgrade.
    stale_sub = font_cache_dir() / "Upfam_sub0123456789.woff2"
    stale_sub.write_bytes(dest.read_bytes())

    calls: list[str] = []
    _upgrade_http_mock(monkeypatch, tmp_path, calls)

    path = fonts.ensure_font_for_text("Upfam", "Łódź")
    assert path is not None and path.name == "Upfam.ttf"
    assert not dest.exists()
    assert not fonts._provenance_sidecar(dest).exists()
    assert not stale_sub.exists()
    assert fonts._read_provenance(path) == ["latin", "latin-ext"]
    assert ord("Ł") in TTFont(str(path), lazy=True).getBestCmap()

    # Second call: covered by the upgraded cmap, no further network.
    n = len(calls)
    assert fonts.ensure_font_for_text("Upfam", "Łódź") == path
    assert len(calls) == n


def test_ensure_font_for_text_glyphs_the_family_lacks(monkeypatch, tmp_path):
    dest = _seed_partial_latin_font(tmp_path)
    calls: list[str] = []
    _upgrade_http_mock(monkeypatch, tmp_path, calls)

    # Cyrillic is not among the family's CSS2 blocks: keep the cached file.
    assert fonts.ensure_font_for_text("Upfam", "Д") == dest
    # And the failed attempt is memoized (css2 fetched exactly once).
    fonts.ensure_font_for_text("Upfam", "Д")
    assert calls.count("https://fonts.googleapis.com/css2?family=Upfam:wght@400&display=swap") == 1


def test_str_metrics_upgrade_gives_exact_metrics(monkeypatch, tmp_path):
    _seed_partial_latin_font(tmp_path)
    calls: list[str] = []
    _upgrade_http_mock(monkeypatch, tmp_path, calls)

    m = str_metrics("Ł", font="Upfam", fontsize=10)
    # Exact: advance 500 on a 1000 em -> 5.0. The heuristic would give 5.5.
    assert m.width == pytest.approx(5.0)


def test_register_font_clears_provenance_and_stale_subsets(tmp_path):
    dest = _seed_partial_latin_font(tmp_path, family="TestSans")
    stale_sub = font_cache_dir() / "TestSans_sub0123456789.woff2"
    stale_sub.write_bytes(dest.read_bytes())

    src = build_test_font(tmp_path / "TestSans-Regular.ttf")
    out = register_font(src)
    assert out.name == "TestSans.ttf"
    assert not dest.exists()
    assert not fonts._provenance_sidecar(dest).exists()
    assert fonts._read_provenance(out) is None
    assert not stale_sub.exists()


def test_save_svg_upgrades_embedded_font(monkeypatch, tmp_path):
    _seed_partial_latin_font(tmp_path)
    calls: list[str] = []
    _upgrade_http_mock(monkeypatch, tmp_path, calls)

    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg'>"
        "<text font-family='Upfam'>Łódź</text></svg>"
    )
    out = save_svg(svg, tmp_path / "card.svg")
    embedded = _embedded_font(out.read_text(encoding="utf-8"))
    assert ord("Ł") in embedded.getBestCmap()


def test_subset_font_does_not_cache_poisoned_subsets(monkeypatch, tmp_path):
    # Upgrade impossible (network down): subset_font must NOT cache a subset
    # missing the glyphs; once the network is back, the subset covers them.
    dest = _seed_partial_latin_font(tmp_path)

    def down(*a, **k):
        raise OSError("network down")

    monkeypatch.setenv("CARDARGUS_OFFLINE", "0")
    monkeypatch.setattr(fonts, "_http_get", down)
    charset = fonts.font_subset_charset("Łód")
    assert fonts.subset_font("Upfam", charset) is None
    assert not fonts.font_cache_path("Upfam", charset).is_file()

    # Network restored (fresh process simulated by clearing module state).
    fonts._FAMILY_BLOCKS.clear()
    fonts._UPGRADE_ATTEMPTED.clear()
    calls: list[str] = []
    _upgrade_http_mock(monkeypatch, tmp_path, calls)
    sub = fonts.subset_font("Upfam", charset)
    assert sub is not None
    assert ord("Ł") in TTFont(str(sub), lazy=True).getBestCmap()


def test_subset_font_rebuilds_a_poisoned_cached_subset(monkeypatch, tmp_path):
    # A poisoned subset cached by an older version (or a crashed run) is
    # detected via its cmap and rebuilt after the upgrade.
    dest = _seed_partial_latin_font(tmp_path)
    charset = fonts.font_subset_charset("Łód")
    poisoned = fonts.font_cache_path("Upfam", charset)
    poisoned.write_bytes(dest.read_bytes())  # latin-only bytes: no Ł

    calls: list[str] = []
    _upgrade_http_mock(monkeypatch, tmp_path, calls)
    sub = fonts.subset_font("Upfam", charset)
    assert sub == poisoned
    assert ord("Ł") in TTFont(str(sub), lazy=True).getBestCmap()


def test_subset_of_complete_font_with_missing_glyphs_stays_cached(test_font, monkeypatch):
    # A local font that genuinely lacks a glyph: the subset is still cached
    # and served (no rebuild churn, no network).
    monkeypatch.setenv("CARDARGUS_OFFLINE", "0")

    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("network access attempted")

    monkeypatch.setattr(fonts, "_http_get", boom)
    charset = fonts.font_subset_charset("AbŁ")
    first = fonts.subset_font("TestSans", charset)
    assert first is not None
    assert fonts.subset_font("TestSans", charset) == first


def test_prepare_svg_upgrades_only_the_family_that_needs_it(monkeypatch, tmp_path):
    from cardargus.conversion import prepare_svg

    _seed_partial_latin_font(tmp_path, family="Upfam")
    other = _seed_partial_latin_font(tmp_path, family="Other")

    calls: list[str] = []
    _upgrade_http_mock(monkeypatch, tmp_path, calls)

    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg'>"
        "<text font-family='Upfam'>Łódź</text>"
        "<text font-family='Other'>Hello</text></svg>"
    )
    prepare_svg(svg)
    # Upfam upgraded; Other untouched (small woff2 kept, zero network for it).
    assert (fonts.font_cache_dir() / "Upfam.ttf").is_file()
    assert other.is_file()
    assert not any("Other" in url for url in calls)


def test_transient_network_failure_is_retried(monkeypatch, tmp_path):
    dest = _seed_partial_latin_font(tmp_path)

    def down(*a, **k):
        raise OSError("network down")

    monkeypatch.setenv("CARDARGUS_OFFLINE", "0")
    monkeypatch.setattr(fonts, "_http_get", down)
    assert fonts.ensure_font_for_text("Upfam", "Ł") == dest

    # Same process, network back: the upgrade is NOT permanently disabled.
    calls: list[str] = []
    _upgrade_http_mock(monkeypatch, tmp_path, calls)
    path = fonts.ensure_font_for_text("Upfam", "Ł")
    assert path is not None and path.name == "Upfam.ttf"


def test_uncoverable_glyphs_fetch_css2_once_per_family(monkeypatch, tmp_path):
    _seed_partial_latin_font(tmp_path)
    calls: list[str] = []
    _upgrade_http_mock(monkeypatch, tmp_path, calls)

    # Three distinct Cyrillic texts: the CSS2 block table is per family,
    # so only one network round-trip happens.
    for txt in ("Д", "Ж", "Фа"):
        fonts.ensure_font_for_text("Upfam", txt)
    assert sum("css2" in url for url in calls) == 1


def test_numbered_cjk_slices_are_not_coverage(monkeypatch, tmp_path):
    dest = _seed_partial_latin_font(tmp_path)
    css2_cjk = """
/* [3] */
@font-face {
  font-family: 'Upfam';
  src: url(https://fonts.gstatic.com/s/upfam/slice3.woff2) format('woff2');
  unicode-range: U+4E00-4FFF;
}
"""

    def fake_get(url, ua, timeout=15.0):
        if "css2" in url:
            return css2_cjk.encode()
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setenv("CARDARGUS_OFFLINE", "0")
    monkeypatch.setattr(fonts, "_http_get", fake_get)
    # The legacy subset= endpoint cannot serve numbered slices: no download.
    assert fonts.ensure_font_for_text("Upfam", "中") == dest
