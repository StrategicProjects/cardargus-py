"""Preset visual themes for :func:`cardargus.svg_card` (ported from R/themes.R)."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

__all__ = ["CardTheme", "card_theme", "card_themes", "THEME_COMPONENTS"]


@dataclass(frozen=True)
class CardTheme:
    """Defaults for the visual arguments of :func:`cardargus.svg_card`.

    ``font=None`` means "do not touch the font" (``svg_card``'s default, or
    whatever the caller passes, is used). Arguments set explicitly in the
    ``svg_card`` call always win over the theme.
    """

    bg_color: str
    font: str | None
    title_color: str
    label_color: str
    value_bg_color: str
    value_text_color: str
    value_border_color: str
    footer_color: str

    def as_dict(self) -> dict[str, Any]:
        """Return the theme components as a plain dict."""
        return dataclasses.asdict(self)

    def __str__(self) -> str:
        rows = "\n".join(f"  {k}: {v!r}" for k, v in self.as_dict().items())
        return f"cardargus theme\n{rows}"


#: Names of the theme components, in order.
THEME_COMPONENTS: tuple[str, ...] = tuple(f.name for f in dataclasses.fields(CardTheme))

# Color values copied verbatim from the R package (R/themes.R).
_THEMES: dict[str, CardTheme] = {
    "default": CardTheme(
        bg_color="#fab255",
        font=None,
        title_color="white",
        label_color="white",
        value_bg_color="#f8f8ff",
        value_text_color="#212529",
        value_border_color="#dee2e6",
        footer_color="white",
    ),
    "light": CardTheme(
        bg_color="#f8f9fa",
        font=None,
        title_color="#212529",
        label_color="#495057",
        value_bg_color="#ffffff",
        value_text_color="#212529",
        value_border_color="#dee2e6",
        footer_color="#6c757d",
    ),
    "dark": CardTheme(
        bg_color="#1e1e2e",
        font=None,
        title_color="#cdd6f4",
        label_color="#a6adc8",
        value_bg_color="#313244",
        value_text_color="#cdd6f4",
        value_border_color="#45475a",
        footer_color="#7f849c",
    ),
    "slate": CardTheme(
        bg_color="linear-gradient(135deg, #334155, #0f172a)",
        font=None,
        title_color="white",
        label_color="#cbd5e1",
        value_bg_color="#1e293b",
        value_text_color="#e2e8f0",
        value_border_color="#475569",
        footer_color="#94a3b8",
    ),
    "ocean": CardTheme(
        bg_color="linear-gradient(135deg, #0284c7, #1e3a8a)",
        font=None,
        title_color="white",
        label_color="white",
        value_bg_color="#f0f9ff",
        value_text_color="#0c4a6e",
        value_border_color="#bae6fd",
        footer_color="white",
    ),
    "forest": CardTheme(
        bg_color="linear-gradient(to right, #1a5a3a, #2e7d32)",
        font=None,
        title_color="white",
        label_color="white",
        value_bg_color="#f1f8e9",
        value_text_color="#1b5e20",
        value_border_color="#c5e1a5",
        footer_color="white",
    ),
    "sunset": CardTheme(
        bg_color="linear-gradient(135deg, #f59e0b, #dc2626)",
        font=None,
        title_color="white",
        label_color="white",
        value_bg_color="#fff7ed",
        value_text_color="#7c2d12",
        value_border_color="#fed7aa",
        footer_color="white",
    ),
    "violet": CardTheme(
        bg_color="linear-gradient(135deg, #667eea, #764ba2)",
        font=None,
        title_color="white",
        label_color="white",
        value_bg_color="#f5f3ff",
        value_text_color="#4c1d95",
        value_border_color="#ddd6fe",
        footer_color="white",
    ),
}


def card_themes() -> list[str]:
    """Names of the preset themes accepted by :func:`card_theme` and ``svg_card(theme=)``."""
    return list(_THEMES)


def card_theme(name: str | CardTheme = "default", **overrides: Any) -> CardTheme:
    """Create (or customize) a card theme.

    Args:
        name: A preset name (see :func:`card_themes`, case-insensitive) or an
            existing :class:`CardTheme` to use as base.
        **overrides: Theme components replacing the base values, e.g.
            ``bg_color="#123456"``.

    Raises:
        ValueError: For an unknown preset, a non-string name or an unknown
            component.
    """
    if isinstance(name, CardTheme):
        base = name
    else:
        if not isinstance(name, str):
            raise ValueError("`name` must be a single theme name. See card_themes().")
        key = name.lower()
        if key not in _THEMES:
            raise ValueError(
                f"Unknown theme {name!r}. Available themes: {', '.join(card_themes())}."
            )
        base = _THEMES[key]

    if overrides:
        unknown = [k for k in overrides if k not in THEME_COMPONENTS]
        if unknown:
            plural = "s" if len(unknown) > 1 else ""
            raise ValueError(
                f"Unknown theme component{plural}: {', '.join(map(repr, unknown))}. "
                f"Valid components: {', '.join(THEME_COMPONENTS)}."
            )
        base = dataclasses.replace(base, **overrides)
    return base
