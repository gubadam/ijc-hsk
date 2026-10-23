# ijc-hsk

Anki decks for Chinese (zh ⇄ pl), built from CSV files.

Every `decks/<name>.csv` becomes a separate deck, `IJC HSK::<NAME>`
(the `ijc_` prefix is dropped, e.g. `ijc_hsk1-2.csv` → `IJC HSK::HSK1-2`).
Each note produces two cards: **Chiński → Polski** and **Polski → Chiński**.

## Workflow

1. Add rows to a CSV in `decks/` (or create a new CSV for a new deck).
2. Push to `main`.
3. GitHub Actions validates the data, builds the decks and publishes them on the
   **[latest release](../../releases/tag/latest)**.
4. Download the `.apkg` and import it in Anki (*File → Import*).

Pull requests only run validation (`python build.py --check`).

Re-importing is safe: notes are identified by `WordSimplified`, so fixing a
typo in a definition or sentence updates the existing card and keeps its review
history.

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

UTF-8, comma-, semicolon- or tab-separated (Excel exports work).

Auto-filled pinyin uses dictionary tones, so neutral tones come out as full
tones (e.g. 谢谢 → `xièxiè` instead of `xièxie`). The build log lists every
auto-filled value. If one is wrong, write the correct one into the CSV.

### Validation

The build **fails** on missing required fields, duplicate words or missing
images, and **warns** when a sentence doesn't contain the word or the sentence
pinyin doesn't contain the word pinyin.

## Local build

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python build.py          # → dist/*.apkg
python build.py --check  # validate only
```

## Layout

```
decks/       one CSV per deck
media/       images referenced from the Image column
templates/   card HTML, CSS and the shared script (highlighting + stroke order)
build.py     CSV → .apkg
```

`dist/ijc-hsk-all.apkg` contains all decks in one file.

> Don't change `MODEL_ID` or `GUID_NAMESPACE` in `build.py`. Anki relies on
> them to match notes on re-import; changing them creates duplicates.
