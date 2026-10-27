"""cardargus: self-contained SVG information cards.

Python port of the R package `cardargus <https://github.com/StrategicProjects/cardargus>`_:
cards with embedded Google Fonts (WOFF2 via ``@font-face``), shields-style
badges, sparklines, icons and logos.
"""

from __future__ import annotations

from .badges import Badge, create_badge, css_gradient_to_svg
from .cards import svg_card
from .conversion import save_svg
from .fonts import (
    FontFallbackWarning,
    font_available,
    font_cache_dir,
    install_fonts,
    list_fonts,
    register_font,
)
from .icons import icon_building, icon_construction, icon_house, icon_map_pin, icon_money
from .logos import create_logo_row, load_svg_for_embed
from .sparklines import create_sparkline
from .themes import CardTheme, card_theme, card_themes
from .utils import compress_number, escape_xml, is_light_color

__version__ = "0.1.1"

__all__ = [
    "Badge",
    "CardTheme",
    "FontFallbackWarning",
    "card_theme",
    "card_themes",
    "compress_number",
    "create_badge",
    "create_logo_row",
    "create_sparkline",
    "css_gradient_to_svg",
    "escape_xml",
    "font_available",
    "font_cache_dir",
    "icon_building",
    "icon_construction",
    "icon_house",
    "icon_map_pin",
    "icon_money",
    "install_fonts",
    "is_light_color",
    "list_fonts",
    "load_svg_for_embed",
    "register_font",
    "save_svg",
    "svg_card",
    "__version__",
]
