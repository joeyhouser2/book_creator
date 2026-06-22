# Fonts

KDP embeds all fonts in your interior PDF, so you need a Unicode serif that
covers **both** the Latin alphabet and **polytonic Greek** (accents + breathings).
ReportLab can only embed fonts it can find here.

Drop one of these font families into this folder (the renderer picks the first
it finds, in order):

1. **Cardo** (recommended, SIL OFL) — designed for classicists, full polytonic
   Greek and Latin. https://software.sil.org/cardo/
   Files: `Cardo-Regular.ttf`, `Cardo-Italic.ttf`, `Cardo-Bold.ttf`
2. **Gentium Plus** (SIL OFL) — https://software.sil.org/gentium/
   Files: `GentiumPlus-Regular.ttf`, `GentiumPlus-Italic.ttf`, `GentiumPlus-Bold.ttf`
3. **Noto Serif** (OFL) — broad coverage.
   Files: `NotoSerif-Regular.ttf`, `NotoSerif-Italic.ttf`, `NotoSerif-Bold.ttf`

All three are free and licensed for commercial use (the OFL permits embedding in
documents you sell). Keep a copy of the license with your records.

If no font is found, the renderer falls back to Times-Roman, which **lacks Greek
glyphs** — Greek will render as blank boxes. So for Greek titles, install a font
above first.
