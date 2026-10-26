# CLAUDE.md — cardargus-py

Guia para agentes trabalhando neste repositório. Leia antes de editar.

## O que é

Port Python do pacote R **cardargus** (`~/Github/cardargus`, no CRAN): cards
informativos em **SVG autocontido** com fontes Google embutidas, badges estilo
shields.io, temas, sparklines e logos. **Os dois pacotes devem produzir o mesmo
SVG** — o R é a implementação de referência; mudança visual aqui precisa de
contraparte lá (ou registro consciente da divergência no README, seção
"Differences from R").

- PyPI: `cardargus` (v0.1.0, lançado 2026-10-25)
- Site: https://strategicprojects.github.io/cardargus-py/
- DOI Zenodo: 10.5281/zenodo.23652572 (badge via repo id 1433712041)

## Arquitetura (src/cardargus/)

| Módulo | Responsabilidade |
|---|---|
| `cards.py` | `svg_card()` — coração; mesma estrutura de SVG do R (classes `.card-title` etc.). |
| `themes.py` | `card_theme()`/`card_themes()`/`CardTheme` — 8 presets, cores idênticas ao R/themes.R. |
| `sparklines.py` | `create_sparkline()` line/area/bar. |
| `badges.py` | `create_badge()`, `css_gradient_to_svg()`. |
| `icons.py` / `logos.py` | Ícones embutidos (path data copiado do R) e `resolve_svg_source()` (ver segurança). |
| `fonts.py` | Cache (platformdirs), download Google WOFF2, métricas via fontTools, **subsetting LOCAL** (fontTools.subset, não a API `&text=` do R). |
| `conversion.py` | `save_svg(svg, path, subset_fonts=False)`. |
| `utils.py` | `escape_xml`, `wrap_text`, `compress_number` (pt-BR), `validate_color`/`validate_font_family`. |
| `_svgparse.py` / `_colors.py` | Parsing regex de SVG e cores nomeadas (CSS + gray ramp do R). |

## Padrões e invariantes

- **Segurança (não regredir):** todo valor de usuário que cai em atributo ou
  `<style>` passa por `validate_color`/`validate_font_family`/`escape_xml`.
  `resolve_svg_source()` decide path-vs-markup: `os.PathLike` = arquivo;
  str começando com `<svg` = markup; str terminando `.svg` existente ≤16 MiB
  com raiz `<svg` = arquivo; resto = `ValueError`. Testes em
  `tests/test_security.py`.
- **API:** argumentos após `fields` são keyword-only; temáveis defaultam
  `None` (resolvidos tema → default). Argumento novo NUNCA entra posicional.
- Métricas de texto via fontTools (cmap+hmtx); sem fonte, heurística com
  `FontFallbackWarning`. Env vars: `CARDARGUS_CACHE_DIR`, `CARDARGUS_OFFLINE`.
- Divergências deliberadas do R estão documentadas no README — mantenha a
  lista atualizada.

## Dev / test / release

- venv: `.venv` (`uv venv .venv && uv pip install -e ".[dev]" --python .venv/bin/python`).
- Testes: `.venv/bin/python -m pytest` — **140 testes, todos offline** (rede é
  mockada; fonte sintética via FontBuilder para métricas/subset exatos).
- Galeria de validação: `.venv/bin/python examples/gallery.py` →
  `examples/output/` (gitignored). Compare com
  `~/Github/cardargus/vignettes/figures/theme-*.svg` (referência R; diferença
  esperada: 0,1 px em ~4 linhas por ruído de float do FreeType).
- Docs: MkDocs Material + mkdocstrings (`mkdocs build --strict` antes de
  push). `docs/index.md` inclui o README via snippet; galeria usa
  `docs/assets/theme-*.svg` (commitados — atualizar junto com mudança visual).
  Deploy automático: workflow `docs.yml` → GitHub Pages modo "GitHub Actions"
  (sem branch gh-pages).
- **Release:** bump `version` em `pyproject.toml` e `__version__` em
  `__init__.py` → commit → tag anotada `vX.Y.Z` → `gh release create` →
  `publish.yml` publica no PyPI via **Trusted Publishing** (environment
  `pypi`, sem token) e o Zenodo arquiva com DOI novo. CI de testes:
  `test.yml` (3.10/3.12/3.14).

## Roadmap (fase 2, não iniciado)

- Export raster/PDF (cairosvg como extra opcional; playwright no lugar do
  chromote para o caminho "Chrome").
- Integração Jupyter (`_repr_html_`/`_repr_svg_` num objeto Card?).
- Espelhar features novas do R ≥0.3.1 conforme saírem.
