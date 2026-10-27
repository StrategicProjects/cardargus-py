"""Font cache, Google Fonts download, text metrics and local glyph subsetting.

Fonts are cached under :func:`font_cache_dir` (``platformdirs`` user cache
directory, overridable with the ``CARDARGUS_CACHE_DIR`` environment variable)
using the same naming scheme as the R package: ``<Family>.woff2`` for the full
font and ``<Family>_sub<hash>.woff2`` for glyph subsets. A Google CSS-API
download only covers the *latin* subset; a ``.gsubsets`` sidecar records that
provenance, and the cache is upgraded in place to a merged TTF when text
needs more coverage (see :func:`ensure_font_for_text`).

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
#: A non-browser User-Agent: Google answers with a single TrueType file
#: covering the legacy ``subset=`` list (just *latin* when none is requested
#: -- the file is NOT the complete font).
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
    subset: str | None = None


_FONT_FACE_RE = re.compile(
    r"(?:/\*\s*(?P<subset>[^*]*?)\s*\*/\s*)?@font-face\s*\{(?P<body>[^}]*)\}",
    re.IGNORECASE,
)
_SRC_RE = re.compile(
    r"""url\(\s*['"]?([^)'"]+)['"]?\s*\)\s*format\(\s*['"]([^'"]+)['"]\s*\)""",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(r"unicode-range\s*:\s*([^;]+)", re.IGNORECASE)


def _parse_font_faces(css: str) -> list[_FontFace]:
    """Extract ``(url, format, unicode-range, subset)`` per ``@font-face`` block.

    Matching is done on ``format('...')`` rather than on the URL extension:
    Google serves some files (``/l/font?kit=...``) from extensionless URLs.
    The *subset* is the ``/* name */`` comment Google writes before each
    block (``latin``, ``latin-ext``, ``cyrillic``, ...), when present.
    """
    faces: list[_FontFace] = []
    for m in _FONT_FACE_RE.finditer(css):
        block = m.group("body")
        subset = m.group("subset") or None
        rng = _RANGE_RE.search(block)
        for url, fmt in _SRC_RE.findall(block):
            faces.append(
                _FontFace(
                    url.strip(),
                    fmt.strip().lower(),
                    rng.group(1).strip() if rng else None,
                    subset,
                )
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


# ---------------------------------------------------------------------------
# Provenance sidecars and coverage upgrades (R package issue #29)
#
# A "full" font downloaded from the Google CSS API only covers the default
# *latin* subset (Basic Latin + Latin-1). A ``<file>.gsubsets`` sidecar next
# to the cached file records which Google subsets it covers and doubles as
# PROVENANCE: only CSS-API downloads have one. Fonts added with
# :func:`register_font` have no sidecar and are treated as complete, so a
# Google download can never replace a user's local font. When text needs
# glyphs the cached file lacks (checked against the real ``cmap``), the font
# is upgraded in place to a single merged TTF from the legacy ``subset=``
# endpoint -- one file, so embedding, local subsetting and text metrics all
# see the same coverage.
# ---------------------------------------------------------------------------

_GSUBSETS_SUFFIX = ".gsubsets"


def _provenance_sidecar(path: Path) -> Path:
    return path.with_name(path.name + _GSUBSETS_SUFFIX)


def _read_provenance(path: Path) -> list[str] | None:
    """Google subsets the cached file covers, or ``None`` for a complete/local font."""
    try:
        raw = _provenance_sidecar(path).read_text(encoding="utf-8")
    except OSError:
        return None
    subsets = [s for s in (t.strip() for t in raw.split(",")) if s]
    return subsets or ["latin"]


def _write_provenance(path: Path, subsets: Sequence[str]) -> None:
    try:
        _provenance_sidecar(path).write_text(",".join(subsets) + "\n", encoding="utf-8")
    except OSError:
        pass


_GLYPH_SUBSET_RE_TMPL = r"_sub[0-9a-f]{10}\.woff2"


def _drop_glyph_subsets(family: str) -> None:
    """Delete cached ``_sub<hash>`` files (artifacts derived from the full font)."""
    pat = re.compile(re.escape(_family_key(family)) + _GLYPH_SUBSET_RE_TMPL)
    for p in font_cache_dir().iterdir():
        if pat.fullmatch(p.name):
            p.unlink(missing_ok=True)


#: cmap code points per font file, so repeated coverage checks do not reopen
#: (and, for WOFF2, re-decompress) the font. Cleared with the metrics cache.
_CMAPS: dict[str, frozenset[int]] = {}


def _cmap_codepoints(path: Path) -> frozenset[int] | None:
    key = str(path)
    hit = _CMAPS.get(key)
    if hit is None:
        try:
            from fontTools.ttLib import TTFont

            hit = frozenset(TTFont(key, lazy=True).getBestCmap() or {})
        except Exception:  # noqa: BLE001 - unreadable font
            return None
        _CMAPS[key] = hit
    return hit


def _unmapped_chars(path: Path, text: str) -> str:
    """Non-ASCII characters of *text* missing from the font's ``cmap``."""
    chars = sorted({ch for ch in text if ord(ch) > 0x7F})
    if not chars:
        return ""
    cmap = _cmap_codepoints(path)
    if cmap is None:
        return ""
    return "".join(ch for ch in chars if ord(ch) not in cmap)


#: Parsed CSS2 blocks per family (name + unicode-range). Only conclusive
#: answers are cached: a network failure is not recorded, so it is retried.
_FAMILY_BLOCKS: dict[str, list[_FontFace]] = {}

#: Google subset names look like "latin", "latin-ext", "vietnamese"; CJK
#: families use numbered slices ("[3]") the legacy subset= endpoint cannot
#: serve, so those are not considered coverage.
_SUBSET_NAME_RE = re.compile(r"[a-z][a-z-]*\Z")


def _family_css2_blocks(family: str) -> list[_FontFace] | None:
    """The family's named CSS2 blocks, cached per process; ``None`` = network failure."""
    if family in _FAMILY_BLOCKS:
        return _FAMILY_BLOCKS[family]
    fam = urllib.parse.quote_plus(family)
    url = f"https://fonts.googleapis.com/css2?family={fam}:wght@400&display=swap"
    try:
        css = _http_get(url, CHROME_USER_AGENT).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - transient: do not cache, retry later
        return None
    blocks = [
        face
        for face in _parse_font_faces(css)
        if face.subset is not None
        and face.unicode_range is not None
        and _SUBSET_NAME_RE.fullmatch(face.subset)
    ]
    _FAMILY_BLOCKS[family] = blocks
    return blocks


def _subsets_covering(family: str, chars: str) -> list[str] | None:
    """Google subset names whose ``unicode-range`` covers any of *chars*.

    Returns an empty list when the family has no block for those characters
    (the glyphs genuinely do not exist in the font) and ``None`` on network
    failure, so callers can retry transient failures later.
    """
    blocks = _family_css2_blocks(family)
    if blocks is None:
        return None
    names: list[str] = []
    for face in blocks:
        if face.subset in names:
            continue
        if any(_range_contains(face.unicode_range, ord(ch)) for ch in chars):
            names.append(face.subset)
    return names


def _forget_family(family: str) -> None:
    """Drop per-family download/upgrade memos so the next call tries again."""
    _FAILED_FAMILIES.discard(family)
    _FAMILY_BLOCKS.pop(family, None)
    for memo in [m for m in _UPGRADE_ATTEMPTED if m[0] == family]:
        _UPGRADE_ATTEMPTED.discard(memo)


def _download_merged_ttf(family: str, subsets: Sequence[str]) -> bytes | None:
    """Single TTF covering *subsets*, via the legacy ``subset=`` endpoint."""
    fam = urllib.parse.quote_plus(family)
    qs = ",".join(subsets)
    for css_url in (
        f"https://fonts.googleapis.com/css?family={fam}:400&subset={qs}",
        f"https://fonts.googleapis.com/css?family={fam}&subset={qs}",
    ):
        try:
            css = _http_get(css_url, PLAIN_USER_AGENT).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        face = _pick_face(_parse_font_faces(css), "truetype")
        url = face.url if face is not None else None
        if url is None:
            # Some legacy responses omit format(): fall back to any .ttf url.
            m = re.search(r"""url\(\s*['"]?([^)'"]+\.ttf)['"]?\s*\)""", css)
            url = m.group(1) if m else None
        if url is None:
            continue
        try:
            data = _http_get(url, PLAIN_USER_AGENT, timeout=60.0)
        except Exception:  # noqa: BLE001
            continue
        if _valid_font_bytes(data):
            return data
    return None


#: Upgrade attempts already made this process, keyed (family, missing chars).
_UPGRADE_ATTEMPTED: set[tuple[str, str]] = set()


def ensure_font_for_text(
    family: str, text: str | None = None, download: bool = True
) -> Path | None:
    """Like :func:`ensure_font`, but upgrades a partial Google block when needed.

    When the cached file is a CSS-API download (it has a ``.gsubsets``
    sidecar) and *text* uses characters its ``cmap`` does not map, the
    covering Google subsets are looked up and the cache is upgraded to a
    merged TTF including them. Fonts without a sidecar (local fonts from
    :func:`register_font`, pre-existing caches) are returned untouched.
    """
    path = ensure_font(family, download=download)
    if path is None or not text:
        return path
    subsets = _read_provenance(path)
    if subsets is None:
        return path
    missing = _unmapped_chars(path, text)
    if not missing:
        return path
    if not download or not _downloads_enabled():
        return path

    covering = _subsets_covering(family, missing)
    if covering is None:
        return path  # network failure: nothing memoized, retried next call
    needed = [s for s in covering if s not in subsets]
    if not needed:
        return path  # the family has no block for those glyphs (cheap: blocks cached)

    want = list(dict.fromkeys(["latin", *subsets, *needed]))
    memo = (family, ",".join(want))
    if memo in _UPGRADE_ATTEMPTED:
        return path
    _UPGRADE_ATTEMPTED.add(memo)

    data = _download_merged_ttf(family, want)
    if data is None:
        return path  # memoized: one failed merged download per subset set

    new = font_cache_dir() / f"{_family_key(family)}.ttf"
    _write_atomic(new, data)
    _write_provenance(new, want)
    if new != path:
        # Replacing our own partial CSS-API download (provenance proven by
        # the sidecar); never reached for local fonts. The font file goes
        # first: if we die between the unlinks, a dangling sidecar is inert,
        # while a sidecar-less partial font would be mistaken for a complete
        # local font and shadow the merged TTF forever.
        path.unlink(missing_ok=True)
        _provenance_sidecar(path).unlink(missing_ok=True)
    _drop_glyph_subsets(family)  # derived from the old, narrower file
    _clear_metrics_cache()
    return new


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
    TrueType file served to non-browser clients (also just the *latin*
    subset) is cached instead. Either way the covered subsets are recorded in
    a ``.gsubsets`` sidecar, and :func:`ensure_font_for_text` upgrades the
    cache when text needs more coverage.

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
                _write_provenance(dest, [face.subset or "latin"])
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
        _forget_family(fam)
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
    # A family has a single full font in the cache; drop other formats, their
    # provenance sidecars (the user's font is complete -- a stale .gsubsets
    # would let a Google download replace it) and stale derived subsets.
    for other in FONT_EXTENSIONS:
        candidate = font_cache_dir() / f"{key}.{other}"
        if other != ext:
            candidate.unlink(missing_ok=True)
        _provenance_sidecar(candidate).unlink(missing_ok=True)
    shutil.copyfile(src, out)
    _drop_glyph_subsets(family)
    _forget_family(family)
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
        if not _unmapped_chars(out, charset):
            return out
        cur = _cached_full_font(family)
        if cur is not None and _read_provenance(cur) is None:
            # The complete/local font lacks those glyphs too: the cached
            # subset is the best possible, keep serving it.
            return out
        # Subset poisoned by a failed coverage upgrade: rebuild it below.
    # ensure_font_for_text: a partial latin-only block would silently produce
    # a subset MISSING the non-latin glyphs (R package issue #29).
    full = ensure_font_for_text(family, charset, download=download)
    if full is None:
        return None
    if _unmapped_chars(full, charset) and _read_provenance(full) is not None:
        # The coverage upgrade did not happen (network?): do NOT cache a
        # subset missing the glyphs -- fall back to the full font and let a
        # later call retry the upgrade.
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
    _CMAPS.clear()


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
    # Characters outside the cmap may live in a Google block the partial
    # cached font does not include: upgrade the cache and re-measure so the
    # layout is computed with the real glyph metrics (not the heuristic).
    missing = "".join(sorted({ch for ch in text if ord(ch) > 0x7F and m.char(ch) is None}))
    if missing and ensure_font_for_text(font, missing) is not None:
        m2 = _measurer(font)  # rebuilt when the upgrade cleared the cache
        if m2 is not None:
            m = m2
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
