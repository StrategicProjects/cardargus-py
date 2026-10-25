"""Font cache, Google Fonts download, text metrics and local glyph subsetting.

Fonts are cached under :func:`font_cache_dir` (``platformdirs`` user cache
directory, overridable with the ``CARDARGUS_CACHE_DIR`` environment variable)
using the same naming scheme as the R package: ``<Family>.woff2`` for the full
font and ``<Family>_sub<hash>.woff2`` for glyph subsets.

Text metrics
------------
The R package measures text with ``gdtools::str_metrics()`` (Cairo). Its
results are reproduced exactly with fontTools: the *width* is the sum of the
glyph advance widths (no kerning) and *ascent*/*descent* are the ink extents
of the string (max glyph ``yMax`` / negated min glyph ``yMin``), all scaled by
``fontsize / unitsPerEm``.

When the font is not cached and cannot be downloaded (offline, or
``CARDARGUS_OFFLINE=1``), a heuristic is used instead so card generation never
fails: every character advances ``0.55 * fontsize``, and a non-empty string
has ascent ``0.75 * fontsize`` and descent ``0.2 * fontsize``. A
:class:`FontFallbackWarning` is emitted once per family in that case.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import warnings
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import NamedTuple

from platformdirs import user_cache_dir

__all__ = [
    "FontFallbackWarning",
    "TextMetrics",
    "font_cache_dir",
    "font_cache_path",
    "font_available",
    "list_fonts",
    "install_fonts",
    "register_font",
    "str_metrics",
    "text_width",
    "text_height",
]

FONT_EXTENSIONS: tuple[str, ...] = ("woff2", "ttf", "woff", "otf")

#: User-Agent that makes the Google Fonts CSS2 API answer with WOFF2 sources.
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
#: A non-browser User-Agent: Google answers with a single full TrueType file.
PLAIN_USER_AGENT = "cardargus-python"

CONNECT_TIMEOUT = 15.0

# Heuristic metrics (fraction of the font size) used when no font is available.
HEURISTIC_ADVANCE = 0.55
HEURISTIC_ASCENT = 0.75
HEURISTIC_DESCENT = 0.2


class FontFallbackWarning(UserWarning):
    """Emitted when a font is unavailable and approximate metrics are used."""


class TextMetrics(NamedTuple):
    """Width, ascent and descent of a string, in pixels."""

    width: float
    ascent: float
    descent: float


# ---------------------------------------------------------------------------
# Cache layout
# ---------------------------------------------------------------------------


def font_cache_dir() -> Path:
    """Return (and create) the directory where cardargus caches font files.

    Defaults to ``platformdirs.user_cache_dir("cardargus")``; set the
    ``CARDARGUS_CACHE_DIR`` environment variable to use another location.
    """
    override = os.environ.get("CARDARGUS_CACHE_DIR")
    path = Path(override) if override else Path(user_cache_dir("cardargus"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _family_key(family: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", family)


def font_subset_charset(text: str | Iterable[str] | None) -> str | None:
    """Normalize text into a stable character set for font subsetting.

    The input is concatenated, deduplicated and sorted by code point, so two
    texts that use the same glyphs map to the same subset (and the same cache
    file) regardless of character order or repetition.

    Returns ``None`` when there is no usable text.
    """
    if text is None:
        return None
    if not isinstance(text, str):
        text = "".join(str(t) for t in text if t is not None)
    if not text:
        return None
    return "".join(sorted(set(text)))


def font_cache_path(family: str, text: str | None = None) -> Path:
    """Path of the cached WOFF2 file for *family* (or one of its subsets).

    Args:
        family: Font family name.
        text: Optional normalized character set (see
            :func:`font_subset_charset`). When given, the file name gets a
            stable ``_sub<hash>`` suffix so each subset is cached separately
            from the full font.
    """
    key = _family_key(family)
    if text:
        key += "_sub" + hashlib.md5(text.encode("utf-8")).hexdigest()[:10]
    return font_cache_dir() / f"{key}.woff2"


def _cached_full_font(family: str) -> Path | None:
    cache = font_cache_dir()
    key = _family_key(family)
    for ext in FONT_EXTENSIONS:
        candidate = cache / f"{key}.{ext}"
        if candidate.is_file():
            return candidate
    return None


def font_available(family: str) -> bool:
    """Return ``True`` if a full font file for *family* is cached."""
    return _cached_full_font(family) is not None


def list_fonts() -> list[str]:
    """List the cache keys of all cached fonts (full fonts and subsets)."""
    names = {
        p.stem
        for p in font_cache_dir().iterdir()
        if p.is_file() and p.suffix.lstrip(".").lower() in FONT_EXTENSIONS
    }
    return sorted(names)


# ---------------------------------------------------------------------------
# Downloading from Google Fonts
# ---------------------------------------------------------------------------


def _downloads_enabled() -> bool:
    return os.environ.get("CARDARGUS_OFFLINE", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }


def _http_get(url: str, user_agent: str, timeout: float = CONNECT_TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        status = getattr(resp, "status", 200)
        if status != 200:
            raise OSError(f"HTTP {status} for {url}")
        return resp.read()


class _FontFace(NamedTuple):
    url: str
    fmt: str
    unicode_range: str | None


_FONT_FACE_RE = re.compile(r"@font-face\s*\{([^}]*)\}", re.IGNORECASE)
_SRC_RE = re.compile(
    r"""url\(\s*['"]?([^)'"]+)['"]?\s*\)\s*format\(\s*['"]([^'"]+)['"]\s*\)""",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(r"unicode-range\s*:\s*([^;]+)", re.IGNORECASE)


def _parse_font_faces(css: str) -> list[_FontFace]:
    """Extract ``(url, format, unicode-range)`` for every ``@font-face`` block.

    Matching is done on ``format('...')`` rather than on the URL extension:
    Google serves some files (``/l/font?kit=...``) from extensionless URLs.
    """
    faces: list[_FontFace] = []
    for block in _FONT_FACE_RE.findall(css):
        rng = _RANGE_RE.search(block)
        for url, fmt in _SRC_RE.findall(block):
            faces.append(
                _FontFace(url.strip(), fmt.strip().lower(), rng.group(1).strip() if rng else None)
            )
    return faces


def _range_contains(unicode_range: str | None, codepoint: int) -> bool:
    if unicode_range is None:
        return True
    for part in unicode_range.split(","):
        part = part.strip().upper().removeprefix("U+")
        if not part:
            continue
        try:
            if "-" in part:
                lo, hi = part.split("-", 1)
                if int(lo, 16) <= codepoint <= int(hi, 16):
                    return True
            elif "?" in part:
                lo = int(part.replace("?", "0"), 16)
                hi = int(part.replace("?", "F"), 16)
                if lo <= codepoint <= hi:
                    return True
            elif int(part, 16) == codepoint:
                return True
        except ValueError:
            continue
    return False


def _pick_face(faces: Sequence[_FontFace], fmt: str) -> _FontFace | None:
    """Choose the block covering basic Latin (Google splits fonts by script)."""
    candidates = [f for f in faces if f.fmt == fmt]
    if not candidates:
        return None
    for face in candidates:
        if _range_contains(face.unicode_range, ord("A")):
            return face
    return candidates[-1]


def _valid_font_bytes(data: bytes) -> bool:
    """Accept only data that fontTools can open as a font (not an HTML error page)."""
    if data[:4] not in (b"wOF2", b"wOFF", b"\x00\x01\x00\x00", b"OTTO", b"true"):
        return False
    try:
        import io

        from fontTools.ttLib import TTFont

        TTFont(io.BytesIO(data), lazy=True)["head"]
    except Exception:  # noqa: BLE001
        return False
    return True


def _write_atomic(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o644)  # mkstemp creates 0600 files
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def download_google_font(family: str, weight: str | int = "400") -> Path | None:
    """Download the full *family* from Google Fonts into the cache.

    The CSS2 API is queried with a Chrome User-Agent so it answers with WOFF2
    sources; Google splits a family into per-script ``unicode-range`` blocks,
    and the block covering Latin is kept. If no WOFF2 source is found, the
    full TrueType file (served to non-browser clients) is cached instead.

    Returns the cached path, or ``None`` on failure (never raises for network
    errors).
    """
    if not _downloads_enabled():
        return None

    fam = urllib.parse.quote_plus(family)
    css_urls = [
        f"https://fonts.googleapis.com/css2?family={fam}:wght@{weight}&display=swap",
        f"https://fonts.googleapis.com/css2?family={fam}&display=swap",
        f"https://fonts.googleapis.com/css?family={fam}:{weight}&display=swap",
        f"https://fonts.googleapis.com/css?family={fam}&display=swap",
    ]
    key = _family_key(family)

    for fmt, ext, ua in (("woff2", "woff2", CHROME_USER_AGENT), ("truetype", "ttf", PLAIN_USER_AGENT)):
        dest = font_cache_dir() / f"{key}.{ext}"
        for css_url in css_urls:
            try:
                css = _http_get(css_url, ua).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 - any network/HTTP error: try next URL
                continue
            face = _pick_face(_parse_font_faces(css), fmt)
            if face is None:
                continue
            try:
                data = _http_get(face.url, ua, timeout=60.0)
            except Exception:  # noqa: BLE001
                continue
            if _valid_font_bytes(data):
                _write_atomic(dest, data)
                return dest
    return None


_FAILED_FAMILIES: set[str] = set()


def ensure_font(family: str, download: bool = True) -> Path | None:
    """Return the cached full font for *family*, downloading it if needed.

    Failed downloads are remembered for the rest of the process so repeated
    calls do not repeatedly hit the network.
    """
    cached = _cached_full_font(family)
    if cached is not None:
        return cached
    if not download or family in _FAILED_FAMILIES:
        return None
    path = download_google_font(family)
    if path is None:
        _FAILED_FAMILIES.add(family)
    return path


def install_fonts(
    fonts: Iterable[str] = ("Jost", "Montserrat", "Roboto", "Open Sans"),
    verbose: bool = True,
) -> dict[str, bool]:
    """Pre-download Google Fonts into the cache for offline use.

    Args:
        fonts: Google Font family names.
        verbose: Print progress to stderr.

    Returns:
        Mapping family -> ``True`` if the font is now cached.
    """
    if isinstance(fonts, str):
        fonts = [fonts]
    results: dict[str, bool] = {}
    for fam in fonts:
        _FAILED_FAMILIES.discard(fam)
        cached = _cached_full_font(fam)
        path = cached or download_google_font(fam)
        if path is not None:
            _clear_metrics_cache()
        results[fam] = path is not None
        if verbose:
            if path is None:
                print(f"x {fam} - could not download (check internet connection)", file=sys.stderr)
            else:
                state = "cached" if cached else "downloaded"
                print(f"v {fam} ({path.suffix.lstrip('.').upper()}, {state})", file=sys.stderr)
    if verbose:
        ok = sum(results.values())
        print(f"Fonts available: {ok}/{len(results)} - cache: {font_cache_dir()}", file=sys.stderr)
    return results


_WEIGHT_SUFFIX_RE = re.compile(
    r"-?(Regular|Bold|Italic|Light|Medium|SemiBold|ExtraBold|Black|Thin).*$",
    re.IGNORECASE,
)


def register_font(path: str | os.PathLike[str], family: str | None = None) -> Path:
    """Copy a local font file (TTF, WOFF2, WOFF or OTF) into the cache.

    Args:
        path: Path to the font file.
        family: Family name to register it under. Defaults to the file name
            without extension and without weight/style suffixes
            (``"Jost-Regular.ttf"`` -> ``"Jost"``).

    Returns:
        Path of the cached copy.

    Raises:
        ValueError: If the file does not exist or has an unsupported format.
    """
    src = Path(path)
    if not src.is_file():
        raise ValueError(f"Font file not found: {src}")
    ext = src.suffix.lstrip(".").lower()
    if ext not in FONT_EXTENSIONS:
        raise ValueError("Unsupported font format. Use TTF, WOFF2, WOFF, or OTF files.")
    if family is None:
        family = _WEIGHT_SUFFIX_RE.sub("", src.stem) or src.stem
    key = _family_key(family)
    out = font_cache_dir() / f"{key}.{ext}"
    # A family has a single full font in the cache; drop other formats.
    for other in FONT_EXTENSIONS:
        if other != ext:
            (font_cache_dir() / f"{key}.{other}").unlink(missing_ok=True)
    shutil.copyfile(src, out)
    _FAILED_FAMILIES.discard(family)
    _clear_metrics_cache()
    return out


# ---------------------------------------------------------------------------
# Local subsetting (fontTools.subset)
# ---------------------------------------------------------------------------


def subset_font(family: str, charset: str, download: bool = True) -> Path | None:
    """Return a cached WOFF2 subset of *family* covering *charset*.

    The subset is produced locally from the cached full font with
    ``fontTools.subset`` and cached under :func:`font_cache_path` keyed by the
    normalized character set. Returns ``None`` if the full font is unavailable
    or subsetting fails.
    """
    charset = font_subset_charset(charset) or ""
    if not charset:
        return None
    out = font_cache_path(family, charset)
    if out.is_file():
        return out
    full = ensure_font(family, download=download)
    if full is None:
        return None
    try:
        from fontTools import subset as ft_subset
        from fontTools.ttLib import TTFont

        options = ft_subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["*"]
        options.name_IDs = ["*"]
        options.name_languages = ["*"]
        options.notdef_outline = True
        options.glyph_names = False
        font = TTFont(str(full))
        subsetter = ft_subset.Subsetter(options=options)
        subsetter.populate(text=charset)
        subsetter.subset(font)
        font.flavor = "woff2"
        tmp = out.with_name(f".tmp-{os.getpid()}-{out.name}")
        font.save(str(tmp))
        os.replace(tmp, out)
        return out
    except Exception as exc:  # noqa: BLE001 - corrupt font, missing brotli, ...
        warnings.warn(f"Could not subset font {family!r}: {exc}", stacklevel=2)
        return None


# ---------------------------------------------------------------------------
# Text metrics
# ---------------------------------------------------------------------------


class _FontMeasurer:
    """Per-font cache of advance widths and glyph ink bounds (font units)."""

    def __init__(self, path: Path) -> None:
        from fontTools.ttLib import TTFont

        font = TTFont(str(path), lazy=True)
        self.upm = float(font["head"].unitsPerEm)
        self._cmap = font.getBestCmap() or {}
        self._hmtx = font["hmtx"]
        self._glyphset = font.getGlyphSet()
        self._font = font
        self._cache: dict[str, tuple[float, float | None, float | None]] = {}

    def char(self, ch: str) -> tuple[float, float | None, float | None] | None:
        """Return ``(advance, yMin, yMax)`` in font units, or ``None`` if unmapped."""
        hit = self._cache.get(ch)
        if hit is not None:
            return hit
        gname = self._cmap.get(ord(ch))
        if gname is None:
            return None
        from fontTools.pens.boundsPen import BoundsPen

        advance = float(self._hmtx[gname][0])
        pen = BoundsPen(self._glyphset)
        self._glyphset[gname].draw(pen)
        ymin = ymax = None
        if pen.bounds is not None:
            ymin, ymax = float(pen.bounds[1]), float(pen.bounds[3])
        hit = (advance, ymin, ymax)
        self._cache[ch] = hit
        return hit


_MEASURERS: dict[str, _FontMeasurer | None] = {}
_WARNED: set[str] = set()


def _clear_metrics_cache() -> None:
    _MEASURERS.clear()
    _WARNED.clear()


def _measurer(family: str) -> _FontMeasurer | None:
    if family in _MEASURERS:
        return _MEASURERS[family]
    path = ensure_font(family)
    measurer: _FontMeasurer | None = None
    if path is not None:
        try:
            measurer = _FontMeasurer(path)
        except Exception:  # noqa: BLE001 - unreadable font: fall back
            measurer = None
    if measurer is None and family not in _WARNED:
        _WARNED.add(family)
        warnings.warn(
            f"Font {family!r} is not available (not cached and could not be "
            f"downloaded); using approximate text metrics. Run "
            f"cardargus.install_fonts([{family!r}]) or register_font() for exact layout.",
            FontFallbackWarning,
            stacklevel=3,
        )
    _MEASURERS[family] = measurer
    return measurer


def str_metrics(text: str, font: str = "Jost", fontsize: float = 12) -> TextMetrics:
    """Measure *text* like ``gdtools::str_metrics()``.

    Returns the advance width and the ink ascent/descent of the string in
    pixels (see the module docstring for the offline heuristic).
    """
    text = "" if text is None else str(text)
    if not text:
        return TextMetrics(0.0, 0.0, 0.0)
    m = _measurer(font)
    if m is None:
        return TextMetrics(
            HEURISTIC_ADVANCE * fontsize * len(text),
            HEURISTIC_ASCENT * fontsize,
            HEURISTIC_DESCENT * fontsize,
        )
    scale = fontsize / m.upm
    width = 0.0
    ymin: float | None = None
    ymax: float | None = None
    for ch in text:
        info = m.char(ch)
        if info is None:
            width += HEURISTIC_ADVANCE * m.upm
            continue
        adv, lo, hi = info
        width += adv
        if lo is not None and hi is not None:
            ymin = lo if ymin is None else min(ymin, lo)
            ymax = hi if ymax is None else max(ymax, hi)
    ascent = (ymax or 0.0) * scale
    descent = -(ymin or 0.0) * scale
    return TextMetrics(width * scale, ascent, descent)


def text_width(text: str | None, font: str = "Jost", fontsize: float = 12) -> float:
    """Width of *text* in pixels (``0`` for empty/``None``)."""
    if text is None or text == "":
        return 0.0
    return str_metrics(text, font, fontsize).width


def text_height(text: str | None, font: str = "Jost", fontsize: float = 12) -> float:
    """Ink height (ascent + descent) of *text*; *fontsize* for empty text."""
    if text is None or text == "":
        return float(fontsize)
    m = str_metrics(text, font, fontsize)
    return m.ascent + m.descent
