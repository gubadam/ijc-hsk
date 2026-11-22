#!/usr/bin/env python3
"""Build Anki decks from CSV files.

Every decks/<name>.csv (words) becomes its own deck (ijc_hsk1-1.csv -> "IJC HSK1-1")
and its own dist/<name>.apkg. An optional decks/<name>.sentences.csv adds sentence
cards and decks/<name>.components.csv radicals / character components to the
same package. Rows with a Lesson number go to subdecks:

    IJC HSK1-1::Słowa::Lekcja 3        words of lesson 3
    IJC HSK1-1::Zdania::Lekcja 3       sentences of lesson 3
    IJC HSK1-1::Komponenty::Lekcja 3   components first seen in lesson 3

dist/ijc-hsk-all.apkg contains all decks at once.

Usage:
    python build.py                 # validate + build
    python build.py --check         # validate only (used on pull requests)
    python build.py --write-guids   # also store GUIDs of new words in the CSVs
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

DECK_PREFIX = "IJC"
ALL_PACKAGE = "ijc-hsk-all.apkg"

# Never change these IDs: Anki uses them to recognise the note type and the
# notes on re-import, so changing them creates duplicates instead of updates.
MODEL_ID = 1735209647
SENTENCE_MODEL_ID = 1735209648
COMPONENT_MODEL_ID = 1735209649
GUID_NAMESPACE = "ijc-hsk"

SENTENCES_SUFFIX = ".sentences"
COMPONENTS_SUFFIX = ".components"
LESSON_DECK = "Lekcja {n}"
WORDS_SUBDECK = "Słowa"
SENTENCES_SUBDECK = "Zdania"
COMPONENTS_SUBDECK = "Komponenty"

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
OPTIONAL_EXTRA = ["Lesson", "Tags", "Guid"]

SENTENCE_FIELDS = [
    "Question",
    "QuestionPinyin",
    "QuestionTranslation",
    "Answer",
    "AnswerPinyin",
    "AnswerTranslation",
]
SENTENCE_REQUIRED = ["Question"]

COMPONENT_FIELDS = [
    "Component",
    "Pinyin",
    "Name",
    "Forms",
    "Kangxi",
    "Role",
    "Hint",
    "Examples",   # rendered from the CSV's example characters
]
COMPONENT_EXTRA = ["Type"]   # CSV-only: rendered into the Role field and tags
COMPONENT_COLUMNS = ["Lesson"] + COMPONENT_FIELDS + COMPONENT_EXTRA + ["Tags", "Guid"]
COMPONENT_TYPES = {  # traditional six categories (六书), as far as they apply
    "piktogram": "piktogram",
    "ideogram prosty": "ideogram_prosty",
    "ideogram złożony": "ideogram_złożony",
    "fonosemantyczny": "fonosemantyczny",
    "niejasny": "niejasny",
}
COMPONENT_ROLES = {"znaczeniowy", "fonetyczny"}

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


def build_sentence_model() -> genanki.Model:
    script = read_template("script.html")

    def tpl(name: str) -> str:
        return read_template(name).replace("<!-- SCRIPT -->", script)

    return genanki.Model(
        SENTENCE_MODEL_ID,
        "IJC Chinese sentence (zh→pl)",
        fields=[{"name": f} for f in SENTENCE_FIELDS],
        templates=[
            {"name": "Zdanie", "qfmt": tpl("sentence_front.html"), "afmt": tpl("sentence_back.html")},
        ],
        css=read_template("style.css"),
        sort_field_index=0,
    )


def build_component_model() -> genanki.Model:
    script = read_template("script.html")

    def tpl(name: str) -> str:
        return read_template(name).replace("<!-- SCRIPT -->", script)

    return genanki.Model(
        COMPONENT_MODEL_ID,
        "IJC Chinese component",
        fields=[{"name": f} for f in COMPONENT_FIELDS],
        templates=[
            {"name": "Komponent", "qfmt": tpl("component_front.html"), "afmt": tpl("component_back.html")},
        ],
        css=read_template("style.css"),
        sort_field_index=0,
    )


def file_kind(csv_path: Path) -> str:
    """'words', 'sentences' or 'components'."""
    stem = csv_path.stem
    if stem.endswith(SENTENCES_SUFFIX):
        return "sentences"
    if stem.endswith(COMPONENTS_SUFFIX):
        return "components"
    return "words"


def is_sentences_file(csv_path: Path) -> bool:
    return file_kind(csv_path) == "sentences"


def is_components_file(csv_path: Path) -> bool:
    return file_kind(csv_path) == "components"


def base_stem(csv_path: Path) -> str:
    stem = csv_path.stem
    for suffix in (SENTENCES_SUFFIX, COMPONENTS_SUFFIX):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def deck_name(csv_path: Path) -> str:
    """Top-level deck for a CSV (words and sentences of one CSV share it)."""
    stem = base_stem(csv_path)
    if stem.lower().startswith("ijc_"):
        stem = stem[4:]
    return f"{DECK_PREFIX} {stem.upper()}"


def subdeck_name(csv_path: Path, lesson: str) -> str:
    base = deck_name(csv_path)
    kind = {"sentences": SENTENCES_SUBDECK, "components": COMPONENTS_SUBDECK}.get(
        file_kind(csv_path), WORDS_SUBDECK)
    if not lesson:
        return f"{base}::{kind}"
    return f"{base}::{kind}::{LESSON_DECK.format(n=lesson)}"


def lesson_tag(lesson: str) -> list:
    """Hierarchical tag (lekcja::3) for finding a lesson's cards in the Browser."""
    return [f"lekcja::{lesson}"] if lesson else []


def sentence_guid(question: str) -> str:
    return genanki.guid_for(GUID_NAMESPACE, "sentence", question)


def component_guid(component: str) -> str:
    return genanki.guid_for(GUID_NAMESPACE, "component", component)


def capitalize_first(text: str) -> str:
    # GB/T 16159-2012, 6.3.1: capitalize the first letter of a sentence
    m = re.search(r"[^\W\d_]", text)
    return text if not m else text[:m.start()] + text[m.start()].upper() + text[m.start() + 1:]


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


def natural_key(text: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)]


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


def write_guids(csv_path: Path) -> list:
    """Fill empty Guid cells (adding the column if needed). Returns the rows filled.

    The value is the same one the build would derive from the word, so notes that
    were already released keep their identity; afterwards the word can be edited
    without Anki treating it as a new note.
    """
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = sniff_reader(f)
        delimiter = reader.reader.dialect.delimiter
        header = [h.strip() for h in (reader.fieldnames or [])]
        reader.fieldnames = header
        rows = list(reader)

    filled = []
    added_column = "Guid" not in header
    if added_column:
        header.append("Guid")
    kind = file_kind(csv_path)
    key_col, make_guid = {
        "sentences": ("Question", sentence_guid),
        "components": ("Component", component_guid),
    }.get(kind, ("WordSimplified", lambda w: genanki.guid_for(GUID_NAMESPACE, w)))
    for row in rows:
        key = (row.get(key_col) or "").strip()
        if key and not (row.get("Guid") or "").strip():
            row["Guid"] = make_guid(key)
            filled.append(key)

    if filled or (added_column and rows):
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header, delimiter=delimiter,
                               lineterminator="\n", extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    return filled


# ------------------------------------------------------------------ build ---

class Report:
    def __init__(self):
        self.errors, self.warnings, self.filled = [], [], []

    def where(self, path, line):
        return f"{path.relative_to(ROOT)}:{line}"


def get_deck(decks: dict, name: str) -> genanki.Deck:
    if name not in decks:
        decks[name] = genanki.Deck(stable_id(name), name)
    return decks[name]


def check_lesson(row: dict, loc: str, report: Report) -> bool:
    lesson = row.get("Lesson", "")
    if lesson and not lesson.isdigit():
        report.errors.append(f"{loc}: Lesson must be a number, got '{lesson}'")
        return False
    if lesson:
        row["Lesson"] = str(int(lesson))
    else:
        report.warnings.append(f"{loc}: no Lesson, card goes straight into the Słowa/Zdania deck")
    return True


def load_deck(csv_path: Path, model, report: Report, seen: dict, seen_guids: dict, decks: dict,
              index: list | None = None):
    """Load words; append (lesson, word, pinyin, definition) to `index` for components."""
    media = set()
    deck_tag = base_stem(csv_path).replace(" ", "_")

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = sniff_reader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        reader.fieldnames = header
        missing = [c for c in REQUIRED if c not in header]
        unknown = [c for c in header if c not in FIELDS + OPTIONAL_EXTRA]
        if missing:
            report.errors.append(f"{csv_path.name}: missing required column(s): {', '.join(missing)}")
            return media
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
            if not check_lesson(row, loc, report):
                continue
            if row["Guid"] and row["Guid"] in seen_guids:
                report.errors.append(f"{loc}: duplicate Guid '{row['Guid']}' (first at {seen_guids[row['Guid']]})")
                continue
            if word in seen:
                report.errors.append(f"{loc}: duplicate word '{word}' (first at {seen[word]})")
                continue
            seen[word] = loc
            if row["Guid"]:
                seen_guids[row["Guid"]] = loc

            # auto-fill pinyin
            if not row["WordPinyin"] and HAN.search(word):
                row["WordPinyin"] = to_pinyin(word, sentence=False)
                report.filled.append(f"{loc}: WordPinyin '{word}' → {row['WordPinyin']}")
            if row["SentenceSimplified"] and not row["SentencePinyin"]:
                sp = sentence_pinyin(row["SentenceSimplified"], word, row["WordPinyin"])
                row["SentencePinyin"] = capitalize_first(sp)
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

            fields = [row[f] if f == "Image" else html.escape(row[f], quote=False).replace("\n", "<br>")
                      for f in FIELDS]
            tags = [deck_tag] + row["Tags"].replace(",", " ").split() + lesson_tag(row["Lesson"])
            get_deck(decks, subdeck_name(csv_path, row["Lesson"])).add_note(genanki.Note(
                model=model,
                fields=fields,
                tags=tags,
                # GUID from an Anki export keeps matching your existing notes
                guid=row["Guid"] or genanki.guid_for(GUID_NAMESPACE, word),
            ))
            if index is not None:
                index.append((int(row["Lesson"] or 0), word, row["WordPinyin"],
                              row["Definition"].split("\n")[0]))
    return media


def example_for(char: str, index: list):
    """Best word showing a character: the character alone, else the earliest word with it."""
    hits = [w for w in index if char in w[1]]
    if not hits:
        return None
    return min(hits, key=lambda w: (w[1] != char, w[0] or 99, len(w[1])))


def render_examples(chars: list, index: list) -> str:
    items = []
    for ch in chars:
        lesson, word, pinyin, definition = example_for(ch, index)
        e = html.escape
        word_part = "" if word == ch else f' <span class="ex-word hanzi">{e(word)}</span>'
        items.append(
            f'<li><span class="ex-char hanzi">{e(ch)}</span>{word_part}'
            f' <span class="pinyin">{e(pinyin)}</span> — {e(definition)}</li>')
    return '<ul class="examples">' + "".join(items) + "</ul>"


def load_components(csv_path: Path, model, report: Report, seen: dict, seen_guids: dict,
                    decks: dict, index: list):
    deck_tag = base_stem(csv_path).replace(" ", "_")
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = sniff_reader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        reader.fieldnames = header
        unknown = [c for c in header if c not in COMPONENT_COLUMNS]
        if "Component" not in header:
            report.errors.append(f"{csv_path.name}: missing required column: Component")
            return
        if unknown:
            report.warnings.append(f"{csv_path.name}: ignoring unknown column(s): {', '.join(unknown)}")

        for line, row in enumerate(reader, start=2):
            row = {k: (row.get(k) or "").strip() for k in COMPONENT_COLUMNS}
            loc = report.where(csv_path, line)
            if not any(row.values()):
                continue
            comp = row["Component"]
            if not comp:
                report.errors.append(f"{loc}: Component is required")
                continue
            if comp in seen:
                report.errors.append(f"{loc}: duplicate component '{comp}' (first at {seen[comp]})")
                continue
            if row["Guid"] and row["Guid"] in seen_guids:
                report.errors.append(f"{loc}: duplicate Guid '{row['Guid']}' (first at {seen_guids[row['Guid']]})")
                continue
            seen[comp] = loc
            if row["Guid"]:
                seen_guids[row["Guid"]] = loc
            if row["Kangxi"] and not (row["Kangxi"].isdigit() and 1 <= int(row["Kangxi"]) <= 214):
                report.errors.append(f"{loc}: Kangxi must be a radical number 1–214, got '{row['Kangxi']}'")
                continue

            if row["Type"] and row["Type"] not in COMPONENT_TYPES:
                report.errors.append(f"{loc}: Type must be one of: {', '.join(COMPONENT_TYPES)}")
                continue
            roles = [r.strip() for r in row["Role"].split("/") if r.strip()]
            if any(r not in COMPONENT_ROLES for r in roles):
                report.errors.append(f"{loc}: Role must be 'znaczeniowy', 'fonetyczny' or both separated by '/'")
                continue

            chars = [c for c in row["Examples"] if HAN.search(c)]
            missing = [c for c in chars if example_for(c, index) is None]
            if missing:
                report.errors.append(f"{loc}: example(s) {' '.join(missing)} not found in any word of the deck")
                continue
            if not chars:
                report.warnings.append(f"{loc}: '{comp}' has no example characters")
            # lesson: given, else the first lesson in which one of the examples appears
            if not row["Lesson"] and chars:
                row["Lesson"] = str(min(example_for(c, index)[0] for c in chars) or "")
            if not check_lesson(row, loc, report):
                continue

            values = {f: html.escape(row[f], quote=False) for f in COMPONENT_FIELDS}
            values["Kangxi"] = f"Klucz nr {row['Kangxi']}" if row["Kangxi"] else ""
            # Role field carries labels: role(s) + character type
            labels = [f"komponent {r}" for r in roles] + ([row["Type"]] if row["Type"] else [])
            values["Role"] = "".join(f'<span class="badge">{html.escape(x)}</span>' for x in labels)
            values["Examples"] = render_examples(chars, index) if chars else ""
            fields = [values[f] for f in COMPONENT_FIELDS]
            tags = ([deck_tag, "component"] + row["Tags"].replace(",", " ").split()
                    + [f"rola::{r}" for r in roles]
                    + ([f"rodzaj::{COMPONENT_TYPES[row['Type']]}"] if row["Type"] else [])
                    + lesson_tag(row["Lesson"]))
            get_deck(decks, subdeck_name(csv_path, row["Lesson"])).add_note(genanki.Note(
                model=model,
                fields=fields,
                tags=tags,
                guid=row["Guid"] or component_guid(comp),
            ))


def load_sentences(csv_path: Path, model, report: Report, seen: dict, seen_guids: dict, decks: dict):
    deck_tag = base_stem(csv_path).replace(" ", "_")
    cols = SENTENCE_FIELDS + ["Lesson", "Tags", "Guid"]
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = sniff_reader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        reader.fieldnames = header
        missing = [c for c in SENTENCE_REQUIRED if c not in header]
        unknown = [c for c in header if c not in cols]
        if missing:
            report.errors.append(f"{csv_path.name}: missing required column(s): {', '.join(missing)}")
            return
        if unknown:
            report.warnings.append(f"{csv_path.name}: ignoring unknown column(s): {', '.join(unknown)}")

        for line, row in enumerate(reader, start=2):
            row = {k: (row.get(k) or "").strip() for k in cols}
            loc = report.where(csv_path, line)
            if not any(row.values()):
                continue
            q = row["Question"]
            if not q:
                report.errors.append(f"{loc}: Question is required")
                continue
            if not check_lesson(row, loc, report):
                continue
            if row["Guid"] and row["Guid"] in seen_guids:
                report.errors.append(f"{loc}: duplicate Guid '{row['Guid']}' (first at {seen_guids[row['Guid']]})")
                continue
            if q in seen:
                report.errors.append(f"{loc}: duplicate sentence '{q}' (first at {seen[q]})")
                continue
            seen[q] = loc
            if row["Guid"]:
                seen_guids[row["Guid"]] = loc

            for text, pin in (("Question", "QuestionPinyin"), ("Answer", "AnswerPinyin")):
                if row[text] and not row[pin]:
                    row[pin] = capitalize_first(to_pinyin(row[text], sentence=True))
                    report.filled.append(f"{loc}: {pin} → {row[pin]}")
                if row[pin] and not row[text]:
                    report.warnings.append(f"{loc}: {pin} without {text} won't be shown")

            fields = [html.escape(row[f], quote=False).replace("\n", "<br>") for f in SENTENCE_FIELDS]
            tags = [deck_tag, "sentence"] + row["Tags"].replace(",", " ").split() + lesson_tag(row["Lesson"])
            get_deck(decks, subdeck_name(csv_path, row["Lesson"])).add_note(genanki.Note(
                model=model,
                fields=fields,
                tags=tags,
                guid=row["Guid"] or sentence_guid(q),
            ))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate only, don't write packages")
    ap.add_argument("--write-guids", action="store_true",
                    help="store GUIDs of words that don't have one yet in the CSVs")
    args = ap.parse_args()

    # words first: components link to them
    csv_files = sorted(DECKS_DIR.glob("*.csv"), key=lambda p: (file_kind(p) != "words", p.name))
    if not csv_files:
        print("No CSV files in decks/", file=sys.stderr)
        return 1

    if args.write_guids:
        for p in csv_files:
            for word in write_guids(p):
                print(f"  guid     {p.relative_to(ROOT)}: {word}")

    model, sentence_model = build_model(), build_sentence_model()
    component_model = build_component_model()
    report = Report()
    seen_words: dict = {}
    seen_sentences: dict = {}
    seen_components: dict = {}
    seen_guids: dict = {}
    packages: dict = {}  # base stem -> {"decks": {name: Deck}, "media": set(), "files": [...]}
    for p in csv_files:
        pkg = packages.setdefault(base_stem(p), {"decks": {}, "media": set(), "files": [], "index": []})
        pkg["files"].append(p.name)
        kind = file_kind(p)
        if kind == "sentences":
            load_sentences(p, sentence_model, report, seen_sentences, seen_guids, pkg["decks"])
        elif kind == "components":
            load_components(p, component_model, report, seen_components, seen_guids, pkg["decks"],
                            pkg["index"])
        else:
            pkg["media"] |= load_deck(p, model, report, seen_words, seen_guids, pkg["decks"],
                                      pkg["index"])
    for s, pkg in packages.items():
        if not (DECKS_DIR / f"{s}.csv").exists():
            report.warnings.append(f"{', '.join(pkg['files'])}: no matching decks/{s}.csv")

    GHA = "GITHUB_ACTIONS" in os.environ
    for msg in report.filled:
        print(f"  filled   {msg}")
    for msg in report.warnings:
        print(f"::warning::{msg}" if GHA else f"  WARNING  {msg}")
    for msg in report.errors:
        print(f"::error::{msg}" if GHA else f"  ERROR    {msg}")

    for stem, pkg in packages.items():
        for name in sorted(pkg["decks"], key=natural_key):
            print(f"{name:<36} {len(pkg['decks'][name].notes):>4} notes")

    if report.errors:
        print(f"\n{len(report.errors)} error(s), nothing written.", file=sys.stderr)
        return 1
    if args.check:
        print("\nOK (check only)")
        return 0

    DIST_DIR.mkdir(exist_ok=True)
    for old in DIST_DIR.glob("*.apkg"):
        old.unlink()
    all_media, all_decks = set(), []
    for stem, pkg in packages.items():
        decks = [d for d in pkg["decks"].values() if d.notes]
        out = genanki.Package(decks)
        out.media_files = sorted(pkg["media"])
        out.write_to_file(DIST_DIR / f"{stem}.apkg")
        all_media |= pkg["media"]
        all_decks += decks
    out = genanki.Package(all_decks)
    out.media_files = sorted(all_media)
    out.write_to_file(DIST_DIR / ALL_PACKAGE)
    print(f"\nWrote {len(packages) + 1} package(s) to {DIST_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
