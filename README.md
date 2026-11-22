# ijc-hsk

Anki decks for Chinese (zh ⇄ pl), built from CSV files.

Every `decks/<name>.csv` becomes a separate deck named `IJC <NAME>`
(the `ijc_` prefix is dropped, e.g. `ijc_hsk1-2.csv` → `IJC HSK1-2`).
Each word produces two cards: **Chiński → Polski** and **Polski → Chiński**.

An optional `decks/<name>.sentences.csv` adds sentence cards (dialog lines:
question in hanzi on the front; question pinyin + translation and the answer
on the back) to the same deck.

Rows are split into subdecks by their `Lesson` column:

```
IJC HSK1-1
├── Komponenty        radicals (klucze) and other character components
│   ├── Lekcja 1
│   └── …
├── Słowa
│   ├── Lekcja 1
│   ├── Lekcja 2
│   └── …
└── Zdania
    ├── Lekcja 1
    └── …
```

Studying `IJC HSK1-1` covers everything, `Słowa` all words, `Słowa::Lekcja 3`
only the words of lesson 3. Rows without `Lesson` go straight into
`Słowa` / `Zdania`.

## Workflow

1. Add rows to a CSV in `decks/` (or create a new CSV for a new deck).
2. Push to `main`.
3. GitHub Actions validates the data, builds the decks and publishes a new
   release (`v<date>.<run>`), so every previous version stays available under
   **[Releases](../../releases)**. The newest one is always at
   **[releases/latest](../../releases/latest)**.
4. Download the `.apkg` and import it in Anki (*File → Import*).

Release notes are generated from the data, compared with the previous release:
words added, removed or changed per deck (and which fields changed), template
and build changes, and the commit messages since then. A push that changes
nothing in the decks, templates or build doesn't create a release.

Pull requests only run validation, plus a changelog preview in the run summary.

Preview the notes locally:

```bash
python tools/changelog.py --since "$(git tag --list 'v*' --sort=-v:refname | head -n1)"
```

Re-importing is safe: every note has a stable GUID, so editing a word updates
the existing card in Anki and keeps its review history. For new words you don't
need to fill in `Guid`: on push to `main` the workflow stores one in the CSV and
commits it back ("Fill GUIDs for new words"). **Run `git pull` before your next
edit**, or your push will be rejected.

## CSV format

| Column | Required | Notes |
|---|---|---|
| `Lesson` | | Lesson number → `Słowa::Lekcja N` subdeck |
| `Definition` | ✅ | Polish meaning |
| `WordSimplified` | ✅ | Unique across **all** decks |
| `WordPinyin` | | Auto-filled when empty |
| `SentenceSimplified` | | Example sentence; should contain the word |
| `SentencePinyin` | | Auto-filled when empty |
| `SentenceTranslation` | | |
| `Image` | | File name of an image in `media/` |
| `Tags` | | Space- or comma-separated; the CSV name is always added as a tag. Include a part-of-speech tag (see below) |
| `Guid` | | Anki note ID; leave empty for new words, CI fills it in. Never edit or copy it |

UTF-8, comma-, semicolon- or tab-separated (Excel exports work).
Line breaks inside a (quoted) cell are shown as line breaks on the card.

### Part-of-speech tags

Every word gets one `pos::` tag, so Anki groups them under **pos** in the
Browser sidebar and you can study by type (search `tag:pos::verb`):

`pos::noun`, `pos::verb`, `pos::adjective`, `pos::adverb`, `pos::pronoun`,
`pos::numeral`, `pos::measure-word`, `pos::particle`, `pos::preposition`,
`pos::conjunction`, `pos::interjection`, `pos::phrase`

A word that works as two parts of speech can have two tags.

### Pinyin capitalization

Pinyin follows the official orthography standard **GB/T 16159-2012**
(汉语拼音正词法基本规则, [text](https://pinyin.info/rules/GBT16159-2012.html)):

- first letter of a sentence is capitalized (6.3.1): *Wǒ shì xuésheng.*
- proper nouns are capitalized (6.3.2): *Zhōngguó, Bōlán, Rìběn*
- surname and given name are separate words, both capitalized (6.2.1): *Lǐ Yuè*
- a proper noun joined with a common noun stays capitalized when the whole
  is a proper noun (6.3.3): *Hànyǔ*, and by the same rule *Zhōngguórén, Bōlánrén*

Applies to `WordPinyin` too. Auto-filled sentence pinyin gets a capital first
letter; proper nouns inside it have to be fixed by hand.

Auto-filled pinyin uses dictionary tones, so neutral tones come out as full
tones (e.g. 谢谢 → `xièxiè` instead of `xièxie`). The build log lists every
auto-filled value. If one is wrong, write the correct one into the CSV.

### Validation

The build **fails** on missing required fields, duplicate words or missing
images, and **warns** when a sentence doesn't contain the word or the sentence
pinyin doesn't contain the word pinyin.

### Sentences CSV (`<name>.sentences.csv`)

| Column | Required | Notes |
|---|---|---|
| `Lesson` | | Lesson number → `Zdania::Lekcja N` subdeck |
| `Question` | ✅ | Sentence or question in hanzi; unique |
| `QuestionPinyin` | | Auto-filled when empty |
| `QuestionTranslation` | | |
| `Answer` | | Optional answer in hanzi |
| `AnswerPinyin` | | Auto-filled when empty |
| `AnswerTranslation` | | |
| `Tags` | | Same as for words; `sentence` is added automatically |
| `Guid` | | Leave empty, CI fills it in. Changing `Question` makes a new note |

### Components CSV (`<name>.components.csv`)

Radicals (klucze, 部首) and other building blocks of the characters in the deck.

| Column | Required | Notes |
|---|---|---|
| `Lesson` | | → `Komponenty::Lekcja N`; when empty: first lesson of its examples |
| `Component` | ✅ | The component, e.g. `氵`; unique |
| `Pinyin` | | Reading of the full form (`氵` → shuǐ) |
| `Name` | | Polish name, e.g. *woda (trzy krople)* |
| `Type` | | `piktogram`, `ideogram prosty`, `ideogram złożony`, `fonosemantyczny` or `niejasny` (origin disputed) → tag `rodzaj::…` |
| `Forms` | | Variants, e.g. `水 → 氵 po lewej stronie znaku` (simplified characters only) |
| `Kangxi` | | Number of the Kangxi radical (1–214), if it is one |
| `Role` | | `znaczeniowy` (meaning), `fonetyczny` (sound) or both (`znaczeniowy / fonetyczny`) → tag `rola::…` |
| `Hint` | | What it usually signals in characters |
| `Examples` | | Characters containing it, e.g. `汉 波 法`; each must occur in a word of the deck, which the card shows next to it |
| `Tags`, `Guid` | | As for words |

## Importing notes from Anki

Export from Anki with *Notes in Plain Text*, with the unique identifier,
notetype, deck and tags included, then:

```bash
python tools/import_anki_export.py export.txt decks/ijc_hsk1-1.csv
```

HTML is converted to plain text and Anki's GUID goes into the `Guid` column, so
the generated deck updates those notes instead of duplicating them. Words
already in the CSV are skipped (`--replace` overwrites the whole file).

## Moving existing cards between decks

Anki never moves existing cards when you import a package; only new notes land
in the deck the package puts them in. Every card carries a `lekcja::N` tag, so
after changing a word's `Lesson` (or the deck layout) move its cards by hand:
*Browse* → search e.g. `tag:lekcja::3 note:"IJC Chinese (zh⇄pl)"` → select all →
*Change Deck* → `IJC HSK1-1::Słowa::Lekcja 3` (for sentences:
`tag:lekcja::3 tag:sentence` → `IJC HSK1-1::Zdania::Lekcja 3`).

Edits you make to these notes inside Anki are overwritten by the next import.
Change the CSV instead.

## Local build

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python build.py          # → dist/*.apkg
python build.py --check  # validate only
python build.py --write-guids  # store GUIDs of new words locally (what CI does)
```

## Layout

```
decks/       one CSV per deck
media/       images referenced from the Image column
templates/   card HTML, CSS and the shared script (highlighting + stroke order)
build.py     CSV → .apkg
tools/       helpers (Anki export → CSV, release notes)
```

`dist/ijc-hsk-all.apkg` contains all decks in one file.

> Don't change `MODEL_ID` or `GUID_NAMESPACE` in `build.py`. Anki relies on
> them to match notes on re-import; changing them creates duplicates.
