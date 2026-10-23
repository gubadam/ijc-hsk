#!/usr/bin/env python3
"""Convert an Anki "Notes in Plain Text" export into a deck CSV.

Usage:
    python tools/import_anki_export.py export.txt decks/ijc_hsk1-1.csv [--replace]

Expects the export with "Include unique identifier", "Include notetype name",
"Include deck name" and "Include tags" checked (the default layout below), and
the note fields in this repo's order. HTML is converted to plain text; Anki's
GUID is kept so re-imports update your existing notes.

Rows whose word already exists in the target CSV are skipped, unless --replace
is given, in which case the target is overwritten.
"""
import argparse
import csv
import html
import re
import sys
from pathlib import Path

FIELDS = ["Definition", "WordSimplified", "WordPinyin", "SentenceSimplified",
          "SentencePinyin", "SentenceTranslation", "Image"]
COLUMNS = FIELDS + ["Tags", "Guid"]


def clean(value: str) -> str:
    if "<img" in value:
        m = re.search(r'src="([^"]+)"', value)
        return m.group(1) if m else value
    v = re.sub(r"</div>\s*<div>|<br\s*/?>", "\n", value, flags=re.I)
    v = re.sub(r"</?div[^>]*>", "", v, flags=re.I)
    v = re.sub(r"<[^>]+>", "", v)
    v = html.unescape(v).replace("\xa0", " ")
    return "\n".join(line.strip() for line in v.splitlines() if line.strip())


def parse_export(path: Path):
    headers = {}
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.startswith("#") and ":" in line and not lines:
            k, v = line[1:].strip().split(":", 1)
            headers[k] = v
        else:
            lines.append(line)
    sep = {"tab": "\t", "comma": ",", "semicolon": ";"}.get(headers.get("separator", "tab"), "\t")
    col = lambda name: int(headers[name]) - 1 if name in headers else None
    guid_c, nt_c, deck_c, tags_c = col("guid column"), col("notetype column"), col("deck column"), col("tags column")
    meta = {c for c in (guid_c, nt_c, deck_c, tags_c) if c is not None}

    for rec in csv.reader(lines, delimiter=sep):
        if not rec:
            continue
        fields = [v for i, v in enumerate(rec) if i not in meta]
        fields += [""] * (len(FIELDS) - len(fields))
        row = {f: clean(v) for f, v in zip(FIELDS, fields)}
        row["Tags"] = rec[tags_c].strip() if tags_c is not None and tags_c < len(rec) else ""
        row["Guid"] = rec[guid_c] if guid_c is not None else ""
        yield row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export", type=Path)
    ap.add_argument("target", type=Path)
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()

    existing = []
    if args.target.exists() and not args.replace:
        with args.target.open(encoding="utf-8-sig", newline="") as f:
            existing = list(csv.DictReader(f))
    words = {r.get("WordSimplified", "") for r in existing}

    added, skipped = [], 0
    for row in parse_export(args.export):
        if row["WordSimplified"] in words:
            skipped += 1
            continue
        words.add(row["WordSimplified"])
        added.append(row)

    args.target.parent.mkdir(parents=True, exist_ok=True)
    with args.target.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in existing + added:
            w.writerow({c: r.get(c, "") for c in COLUMNS})
    print(f"{args.target}: {len(added)} added, {skipped} skipped (already present), {len(existing) + len(added)} total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
