"""Render the theme gallery: one card per preset theme.

Reproduces the demo card of the R package's *Theme Gallery* vignette
(``vignettes/themes.Rmd``) so the output can be compared with the R reference
SVGs in ``cardargus/vignettes/figures/theme-*.svg``.

Usage::

    python examples/gallery.py [output_dir]

Cards are saved with ``save_svg(..., subset_fonts=True)`` (network needed the
first time to download Jost into the cache) into ``examples/output/`` by
default.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cardargus import card_themes, create_sparkline, save_svg, svg_card

BADGES = [
    {"label": "UH", "value": "192"},
    {"label": "Recurso", "value": "36,4 milhões"},
]


def gallery_fields() -> list[list[dict[str, object]]]:
    return [
        [{"label": "Empreendimento", "value": "CAIARA II", "with_icon": True}],
        [
            {
                "label": "Tendência",
                "value": "Alta",
                "with_icon": create_sparkline([2, 4, 3, 6, 5, 8], width=55, height=34),
            },
            {"label": "Município", "value": "Recife"},
        ],
    ]


def render_gallery(out_dir: Path) -> list[Path]:
    """Render and save one card per theme; return the written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in card_themes():
        card = svg_card(
            title=name.upper(),
            badges_data=BADGES,
            fields=gallery_fields(),
            theme=name,
            width=420,
            footer="cardargus • theme gallery",
        )
        written.append(save_svg(card, out_dir / f"theme-{name}.svg", subset_fonts=True))
    return written


def main(argv: list[str]) -> int:
    out_dir = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent / "output"
    for path in render_gallery(out_dir):
        print(f"{path}  ({path.stat().st_size / 1024:.1f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
