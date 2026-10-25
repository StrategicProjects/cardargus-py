# cardargus (Python)

Generate **self-contained SVG information cards** with embedded Google Fonts,
shields.io-style badges, sparklines, icons and logos, from Python.

This is a port of the R package
[**cardargus**](https://github.com/StrategicProjects/cardargus)
([site](https://strategicprojects.github.io/cardargus/)). Both implementations
produce the same SVG structure, so cards look the same whichever language
generated them.

## Features

- `svg_card()`: a complete card with title, badge row, rows of labelled value
  boxes (greedy word wrapping), optional icons, footer and logos.
- 8 preset themes (`card_themes()`), customizable with `card_theme()`.
  Arguments you pass explicitly always win over the theme.
- Solid or CSS `linear-gradient(...)` backgrounds, turned into SVG gradients.
- `create_sparkline()`: line, area and bar mini-charts to use as field icons.
- `create_badge()`: shields.io-style badges with automatic dark/light text.
- Built-in icons: `icon_house`, `icon_building`, `icon_construction`,
  `icon_map_pin`, `icon_money`. Any SVG string or `.svg` file also works.
- Accessibility: every card has an SVG `<title>`, an optional `<desc>`
  (`alt=`), `role="img"` and `aria-labelledby`.
- `save_svg()`: writes a portable SVG with the fonts embedded as base64 WOFF2
  `@font-face`. With `subset_fonts=True` the font is cut down **locally**
  (fontTools) to just the glyphs the card uses, about 3 KB instead of tens of KB.
- Text is measured with the real font metrics (fontTools), so wrapping and
  badge sizes match the R package.
- Small footprint: depends only on `fonttools`, `brotli` and `platformdirs`.

## Installation

```bash
pip install cardargus
```

Requires Python 3.10 or newer.

## Quickstart

```python
from cardargus import create_sparkline, save_svg, svg_card

card = svg_card(
    "FAR",
    badges_data=[
        {"label": "UH", "value": "192"},
        {"label": "Recurso", "value": "36,4 milhões"},
    ],
    fields=[
        [{"label": "Empreendimento", "value": "CAIARA II", "with_icon": True}],
        [
            {"label": "Tendência", "value": "Alta",
             "with_icon": create_sparkline([2, 4, 3, 6, 5, 8], width=55, height=34)},
            {"label": "Município", "value": "Recife"},
        ],
    ],
    theme="ocean",
    alt="Card com indicadores do programa FAR",
    footer="Atualizado em 2026-10-25",
)

save_svg(card, "far.svg", subset_fonts=True)  # self-contained, fonts embedded
```

`svg_card()` returns the SVG as a string. You can write it straight into
HTML or a notebook (`IPython.display.SVG(card)`), or save it with `save_svg()`.

### Fields and icons

`fields` is a list of rows, and each row is a list of dicts with `label` and
`value`. Only the **first** field of a row can carry `with_icon`:

| `with_icon` | Result |
|---|---|
| `True` | house icon |
| `False` / `None` | no icon |
| `"<svg ...>"` (a string starting with `<svg`) | that markup, embedded as is |
| `"path/to/icon.svg"` (a string ending in `.svg`) or a `pathlib.Path` | the file, scaled into the icon slot |

Logos (`logos=`, `bottom_logos=`) follow the same rules. Files must exist and
have an `<svg>` root element. Any other string raises `ValueError`. Raw
markup is embedded verbatim, so only pass markup you trust.

### Fonts

The default font is **Jost**. On first use cardargus downloads the font from
Google Fonts (WOFF2) into a user cache (`font_cache_dir()`,
`platformdirs.user_cache_dir("cardargus")`). Text metrics and `save_svg()`
both use that cache.

```python
from cardargus import install_fonts, register_font

install_fonts(["Jost", "Roboto"])     # pre-download for offline use
register_font("MyFont-Regular.ttf")    # or bring your own file (family "MyFont")
```

Environment variables:

- `CARDARGUS_CACHE_DIR`: use another cache directory.
- `CARDARGUS_OFFLINE=1`: never touch the network.

If a font is neither cached nor downloadable, cardargus falls back to
approximate metrics (each character about 0.55 em wide) and emits a single
`FontFallbackWarning`. It never fails because of a missing font.

## Themes

| Theme | Background |
|---|---|
| `default` | `#fab255` (orange) |
| `light` | `#f8f9fa` |
| `dark` | `#1e1e2e` |
| `slate` | `linear-gradient(135deg, #334155, #0f172a)` |
| `ocean` | `linear-gradient(135deg, #0284c7, #1e3a8a)` |
| `forest` | `linear-gradient(to right, #1a5a3a, #2e7d32)` |
| `sunset` | `linear-gradient(135deg, #f59e0b, #dc2626)` |
| `violet` | `linear-gradient(135deg, #667eea, #764ba2)` |

```python
from cardargus import card_theme, svg_card

mine = card_theme("ocean", footer_color="#cceeff")
svg = svg_card("FAR", theme=mine, footer="nota", bg_color="#123456")  # bg_color wins
```

Theme components: `bg_color`, `font`, `title_color`, `label_color`,
`value_bg_color`, `value_text_color`, `value_border_color`, `footer_color`.

To render the gallery (one card per theme, the same demo card as the R
package's *Theme Gallery* vignette), run:

```bash
python examples/gallery.py   # writes examples/output/theme-*.svg
```

## Utilities

```python
from cardargus import compress_number, is_light_color

compress_number(36_400_000)   # '36,4 milhões'
compress_number(1500)         # '1,5 mil'
compress_number(None)         # 'S/I'
is_light_color("#fab255")     # True
```

## Relationship to the R package

The Python package follows the R API (snake_case names, same defaults:
`width=500`, `padding=20`, `corner_radius=8`, `font="Jost"`,
`bg_color="#fab255"`, ...) and produces the same SVG elements in the same
order, with the same class names (`.card-title`, `.field-label`,
`.field-value`, `.footer-text`). Version 0.1.0 covers the SVG core only. The R
package's PNG/PDF export, Chrome rendering and knitr/Quarto integration are
not ported.

The known differences, mostly deliberate:

- Arguments after `fields` are keyword-only. The themable arguments default to
  `None` ("use the theme, or else the built-in default"), which replaces R's
  `missing()` check. `show_viewer` does not exist.
- `with_icon` also accepts `.svg` file paths (R accepts raw SVG only there).
- Colors and font names are validated. Invalid values raise `ValueError`
  instead of being written into the SVG as is.
- When resizing raw-SVG logos, only the root `<svg>` element is changed (R's
  `gsub` also rewrote attributes such as `stroke-width` inside the logo).
- Element ids are CRC32 hashes of the content plus a counter, like R, but the
  hex values differ, because R hashes serialized objects.
- Subsetting runs locally with fontTools, not through the Google Fonts
  `&text=` API.

## Development

```bash
uv venv .venv && uv pip install -e ".[dev]" --python .venv/bin/python
.venv/bin/python -m pytest
```

The test suite never uses the network.

## Authors

André Leite (maintainer), Marcos Wasiliew, Hugo Vasconcelos, Carlos Amorim,
Diogo Bezerra, Júlia Nascimento Barreto. See `CITATION.cff`.

## License

MIT. See [LICENSE](LICENSE).
