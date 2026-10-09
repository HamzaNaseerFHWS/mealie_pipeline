# 11: English, German and Roman Urdu/Hindi recipes with English ingredients

**What to build:** Per-Recipe-Part language handling.

- **Detection:** the Recipe Language (en/de/ur/hi) is detected from Whisper's language, the caption script and the website's `inLanguage`/`<html lang>`. Code-mixed Hinglish/Urdu-English with mostly Urdu/Hindi instructions counts as ur/hi.
- **Recipe text:**
  - English stays English.
  - German name, description and steps stay German.
  - Urdu/Hindi name, description and steps are written in **Roman Urdu/Hindi**, never Devanagari or Nastaliq. The style comes from `prompts/style_roman_urdu.md`, with English ingredient names inside the steps.
- **Ingredients:** every Ingredient Line is **English**. German and desi lines are translated during extraction using `config/glossary_desi.yaml` and `glossary_de_en.yaml` (shipped with a solid starter set). The original line is kept as `originalText` and is what Grounding checks.
- **Language tag:** added by rule if a matching tag exists.

**Blocked by:** 09, 07

**Status:** ready-for-agent

**Read first:** `PIPELINE_SPEC.md` §2c; `docs/adr/0003`; wayfinder tickets `08-languages.md`, `11-romanization-style.md`.

- [ ] Language detection is pure (given the transcript language, the caption text and the HTML lang) and table-tested, including Hinglish captions in Latin script with Hindi speech.
- [ ] A pure script validator rejects Devanagari/Arabic-script characters in the name/description/steps of ur/hi recipes and anything non-English in Ingredient Lines (heuristic + glossary). A violation triggers one extraction retry with the problem stated, then review.
- [ ] The glossaries ship with at least 60 desi and 60 German entries (spices, flours, dals, dairy, vegetables, common units). They're loaded into the extraction prompt only for the matching language.
- [ ] Grounding uses `original_line` / original-script quotes. A pipeline-seam test with a Hindi-Devanagari transcript fixture uploads a recipe with Roman steps and English ingredients, and all quotes are grounded.
- [ ] Pipeline-seam test: a German website recipe uploads with German steps and English ingredients (`originalText` German).

**Manual check on the laptop (user):** import one German and one Urdu/Hindi Video, and check that the steps read naturally and the ingredients are English.
