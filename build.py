#!/usr/bin/env python3
"""Build Anki decks from CSV files.

Every decks/<name>.csv becomes its own deck ("IJC HSK::<NAME>") and its own
dist/<name>.apkg. dist/ijc-hsk-all.apkg contains all decks at once.

Usage:
    python build.py            # validate + build
    python build.py --check    # validate only (used on pull requests)
"""
import argparse
import csv
import hashlib
import html
import os
import re
import sys
from pathlib import Path

import genanki
from pypinyin import Style, lazy_pinyin

ROOT = Path(__file__).resolve().parent
DECKS_DIR = ROOT / "decks"
TEMPLATES_DIR = ROOT / "templates"
MEDIA_DIR = ROOT / "media"
DIST_DIR = ROOT / "dist"

DECK_PARENT = "IJC HSK"
ALL_PACKAGE = "ijc-hsk-all.apkg"

# Never change these IDs: Anki uses them to recognise the note type and the
# notes on re-import, so changing them creates duplicates instead of updates.
MODEL_ID = 1735209647
GUID_NAMESPACE = "ijc-hsk"

FIELDS = [
    "Definition",
    "WordSimplified",
    "WordPinyin",
    "SentenceSimplified",
    "SentencePinyin",
    "SentenceTranslation",
    "Image",
]
REQUIRED = ["Definition", "WordSimplified"]
OPTIONAL_EXTRA = ["Tags"]

HAN = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
SPACE_BEFORE_PUNCT = re.compile(r"\s+([，。！？、；：,.!?;:)）」』])")


# ---------------------------------------------------------------- helpers ---

def read_template(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")


def build_model() -> genanki.Model:
    script = read_template("script.html")

    def tpl(name: str) -> str:
        return read_template(name).replace("<!-- SCRIPT -->", script)

    return genanki.Model(
        MODEL_ID,
        "IJC Chinese (zh⇄pl)",
        fields=[{"name": f} for f in FIELDS],
        templates=[
            {"name": "Chiński → Polski", "qfmt": tpl("zh-pl_front.html"), "afmt": tpl("zh-pl_back.html")},
            {"name": "Polski → Chiński", "qfmt": tpl("pl-zh_front.html"), "afmt": tpl("pl-zh_back.html")},
        ],
        css=read_template("style.css"),
        sort_field_index=FIELDS.index("WordSimplified"),
    )


def deck_name(csv_path: Path) -> str:
    stem = csv_path.stem
    if stem.lower().startswith("ijc_"):
        stem = stem[4:]
    return f"{DECK_PARENT}::{stem.upper()}"


def stable_id(text: str) -> int:
    h = int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16)
    return (1 << 30) + h % (1 << 30)


FULLWIDTH_PUNCT = str.maketrans("，。！？：；、（）“”", ",.!?:;,()\"\"")


def to_pinyin(text: str, sentence: bool) -> str:
    syllables = lazy_pinyin(text, style=Style.TONE)
    out = " ".join(syllables) if sentence else "".join(syllables)
    out = out.translate(FULLWIDTH_PUNCT)
    return SPACE_BEFORE_PUNCT.sub(r"\1", out).strip()


def sentence_pinyin(sentence: str, word: str, word_pinyin: str) -> str:
    """Pinyin for a sentence, reusing the (verified) word pinyin where the word occurs."""
    parts = sentence.split(word) if word else [sentence]
    if len(parts) == 1:
        return to_pinyin(sentence, sentence=True)
    pieces = []
    for i, part in enumerate(parts):
        if part:
            pieces.append(to_pinyin(part, sentence=True))
        if i < len(parts) - 1:
            pieces.append(word_pinyin)
    return SPACE_BEFORE_PUNCT.sub(r"\1", " ".join(pieces)).strip()


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def sniff_reader(f):
    sample = f.read(4096)
    f.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return csv.DictReader(f, dialect=dialect)


# ------------------------------------------------------------------ build ---

class Report:
    def __init__(self):
        self.errors, self.warnings, self.filled = [], [], []

    def where(self, path, line):
        return f"{path.relative_to(ROOT)}:{line}"


def load_deck(csv_path: Path, model, report: Report, seen: dict):
    deck = genanki.Deck(stable_id(deck_name(csv_path)), deck_name(csv_path))
    media = set()
    deck_tag = csv_path.stem.replace(" ", "_")

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = sniff_reader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        reader.fieldnames = header
        missing = [c for c in REQUIRED if c not in header]
        unknown = [c for c in header if c not in FIELDS + OPTIONAL_EXTRA]
        if missing:
            report.errors.append(f"{csv_path.name}: missing required column(s): {', '.join(missing)}")
            return deck, media
        if unknown:
            report.warnings.append(f"{csv_path.name}: ignoring unknown column(s): {', '.join(unknown)}")

        for line, row in enumerate(reader, start=2):
            row = {k: (row.get(k) or "").strip() for k in FIELDS + OPTIONAL_EXTRA}
            loc = report.where(csv_path, line)
            word = row["WordSimplified"]

            if not any(row.values()):
                continue
            if not word or not row["Definition"]:
                report.errors.append(f"{loc}: Definition and WordSimplified are required")
                continue
            if word in seen:
                report.errors.append(f"{loc}: duplicate word '{word}' (first at {seen[word]})")
                continue
            seen[word] = loc

            # auto-fill pinyin
            if not row["WordPinyin"] and HAN.search(word):
                row["WordPinyin"] = to_pinyin(word, sentence=False)
                report.filled.append(f"{loc}: WordPinyin '{word}' → {row['WordPinyin']}")
            if row["SentenceSimplified"] and not row["SentencePinyin"]:
                row["SentencePinyin"] = sentence_pinyin(row["SentenceSimplified"], word, row["WordPinyin"])
                report.filled.append(f"{loc}: SentencePinyin → {row['SentencePinyin']}")

            # consistency checks
            if row["SentenceSimplified"] and word not in row["SentenceSimplified"]:
                report.warnings.append(f"{loc}: sentence '{row['SentenceSimplified']}' doesn't contain '{word}'")
            if row["SentencePinyin"] and row["WordPinyin"] and squash(row["WordPinyin"]) not in squash(row["SentencePinyin"]):
                report.warnings.append(f"{loc}: SentencePinyin doesn't contain '{row['WordPinyin']}'")
            if (row["SentencePinyin"] or row["SentenceTranslation"]) and not row["SentenceSimplified"]:
                report.warnings.append(f"{loc}: sentence pinyin/translation without SentenceSimplified won't be shown")

            # image: a file name from media/
            image = row["Image"]
            if image and not image.lstrip().startswith("<"):
                img_path = MEDIA_DIR / image
                if not img_path.is_file():
                    report.errors.append(f"{loc}: image '{image}' not found in media/")
                    continue
                media.add(str(img_path))
                row["Image"] = f'<img src="{html.escape(image)}">'
            elif image:
                row["Image"] = image  # raw HTML, keep as-is

            fields = [row[f] if f == "Image" else html.escape(row[f], quote=False) for f in FIELDS]
            tags = [deck_tag] + row["Tags"].replace(",", " ").split()
            deck.add_note(genanki.Note(
                model=model,
                fields=fields,
                tags=tags,
                guid=genanki.guid_for(GUID_NAMESPACE, word),
            ))
    return deck, media


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate only, don't write packages")
    args = ap.parse_args()

    csv_files = sorted(DECKS_DIR.glob("*.csv"))
    if not csv_files:
        print("No CSV files in decks/", file=sys.stderr)
        return 1

    model = build_model()
    report = Report()
    seen: dict = {}
    built = [(p, *load_deck(p, model, report, seen)) for p in csv_files]

    GHA = "GITHUB_ACTIONS" in os.environ
    for msg in report.filled:
        print(f"  filled   {msg}")
    for msg in report.warnings:
        print(f"::warning::{msg}" if GHA else f"  WARNING  {msg}")
    for msg in report.errors:
        print(f"::error::{msg}" if GHA else f"  ERROR    {msg}")

    for path, deck, _ in built:
        print(f"{deck.name:<24} {len(deck.notes):>4} notes  ({path.name})")

    if report.errors:
        print(f"\n{len(report.errors)} error(s), nothing written.", file=sys.stderr)
        return 1
    if args.check:
        print("\nOK (check only)")
        return 0

    DIST_DIR.mkdir(exist_ok=True)
    for old in DIST_DIR.glob("*.apkg"):
        old.unlink()
    all_media = set()
    for path, deck, media in built:
        pkg = genanki.Package(deck)
        pkg.media_files = sorted(media)
        pkg.write_to_file(DIST_DIR / f"{path.stem}.apkg")
        all_media |= media
    pkg = genanki.Package([d for _, d, _ in built])
    pkg.media_files = sorted(all_media)
    pkg.write_to_file(DIST_DIR / ALL_PACKAGE)
    print(f"\nWrote {len(built) + 1} package(s) to {DIST_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
