# ijc-hsk

Anki decks for Chinese (zh ⇄ pl), built from CSV files.

Every `decks/<name>.csv` becomes a separate deck named `IJC <NAME>`
(the `ijc_` prefix is dropped, e.g. `ijc_hsk1-2.csv` → `IJC HSK1-2`).
Each note produces two cards: **Chiński → Polski** and **Polski → Chiński**.

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
| `Definition` | ✅ | Polish meaning |
| `WordSimplified` | ✅ | Unique across **all** decks |
| `WordPinyin` | | Auto-filled when empty |
| `SentenceSimplified` | | Example sentence; should contain the word |
| `SentencePinyin` | | Auto-filled when empty |
| `SentenceTranslation` | | |
| `Image` | | File name of an image in `media/` |
| `Tags` | | Space- or comma-separated; the CSV name is always added as a tag |
| `Guid` | | Anki note ID; leave empty for new words, CI fills it in. Never edit or copy it |

UTF-8, comma-, semicolon- or tab-separated (Excel exports work).
Line breaks inside a (quoted) cell are shown as line breaks on the card.

Auto-filled pinyin uses dictionary tones, so neutral tones come out as full
tones (e.g. 谢谢 → `xièxiè` instead of `xièxie`). The build log lists every
auto-filled value. If one is wrong, write the correct one into the CSV.

### Validation

The build **fails** on missing required fields, duplicate words or missing
images, and **warns** when a sentence doesn't contain the word or the sentence
pinyin doesn't contain the word pinyin.

## Importing notes from Anki

Export from Anki with *Notes in Plain Text*, with the unique identifier,
notetype, deck and tags included, then:

```bash
python tools/import_anki_export.py export.txt decks/ijc_hsk1-1.csv
```

HTML is converted to plain text and Anki's GUID goes into the `Guid` column, so
the generated deck updates those notes instead of duplicating them. Words
already in the CSV are skipped (`--replace` overwrites the whole file).

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
