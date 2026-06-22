# Fonts

KDP embeds all fonts in your interior PDF, so every font you use must be licensed
for **commercial embedding**. The curated set below is all **SIL Open Font
License**, which explicitly permits that.

## Quick install

```bash
python download_fonts.py            # all categories
python download_fonts.py greek      # or just one: serif | medieval | greek
```

This fetches the fonts from the official Google Fonts repo into this folder.
Keep a copy of each `OFL.txt` license with your publishing records.

## How discovery works

The tool **auto-discovers** whatever `.ttf` files are here — it groups them into
families and infers regular/italic/bold from the filenames. So to add your own
font, just drop its files in (named `Family-Regular.ttf`, `Family-Italic.ttf`,
`Family-Bold.ttf`) and it appears automatically in the CLI (`--font`), config,
and the web UI picker. No code changes needed.

## What gets installed

- **Classic serif:** Cardo, EB Garamond, Gentium Book Plus, Old Standard,
  Libre Baskerville, IM Fell English, IM Fell DW Pica
- **Medieval / display:** UnifrakturMaguntia, UnifrakturCook, Grenze Gotisch,
  Pirata One, MedievalSharp
- **Greek display:** GFS Didot, GFS Neohellenic

Cardo and Old Standard cover both Latin and **polytonic Greek**, so they're safe
defaults for Greek texts. The medieval/display faces are Latin-only (best for
titles). If no font is found at all, rendering falls back to Times-Roman, which
**lacks Greek glyphs** — Greek would render as blank boxes.
