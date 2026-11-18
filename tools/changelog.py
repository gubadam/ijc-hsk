#!/usr/bin/env python3
"""Generate release notes: what changed in the decks since a git ref.

Usage:
    python tools/changelog.py [--since REF] [--output FILE]

Without --since (or with an empty one) everything counts as new (first release).
Compares the CSVs at REF with the working tree, word by word, and lists
template/build changes and the commit messages since REF.
Exit code 0 always; the "changed" flag goes to $GITHUB_OUTPUT when available.
"""
import argparse
import csv
import io
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from build import FIELDS, SENTENCE_FIELDS, deck_name, is_sentences_file, sniff_reader  # noqa: E402

WORD_TRACKED = ["Lesson"] + FIELDS + ["Tags"]
SENTENCE_TRACKED = ["Lesson"] + SENTENCE_FIELDS + ["Tags"]


def kind(name: str):
    """(key column, tracked columns, unit) for a CSV file name."""
    if is_sentences_file(Path(name)):
        return "Question", SENTENCE_TRACKED, "sentences"
    return "WordSimplified", WORD_TRACKED, "words"
STYLE_PATHS = ["templates"]
BUILD_PATHS = ["build.py", "requirements.txt"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout


def parse(text: str, name: str) -> dict:
    key, tracked, _ = kind(name)
    reader = sniff_reader(io.StringIO(text.lstrip("\ufeff")))
    reader.fieldnames = [h.strip() for h in (reader.fieldnames or [])]
    rows = {}
    for row in reader:
        k = (row.get(key) or "").strip()
        if k:
            rows[k] = {c: (row.get(c) or "").strip() for c in tracked}
    return rows


def decks_at(ref: str) -> dict:
    """{csv file name: rows} at a git ref ('' = nothing)."""
    if not ref:
        return {}
    names = git("ls-tree", "--name-only", f"{ref}:decks").split()
    return {n: parse(git("show", f"{ref}:decks/{n}"), n) for n in names if n.endswith(".csv")}


def decks_now() -> dict:
    return {p.name: parse(p.read_text(encoding="utf-8"), p.name)
            for p in sorted((ROOT / "decks").glob("*.csv"))}


def label(key: str, row: dict) -> str:
    lesson = f"[L{row['Lesson']}] " if row.get("Lesson") else ""
    if "Question" in row:
        t = row["QuestionTranslation"]
        return lesson + key + (f" — {t}" if t else "")
    parts = [key]
    if row["WordPinyin"]:
        parts.append(row["WordPinyin"])
    d = row["Definition"].split("\n")[0]
    return lesson + " ".join(parts) + (f" — {d}" if d else "")


def deck_section(name: str, old: dict | None, new: dict | None) -> list[str]:
    _, tracked, unit = kind(name)
    title = deck_name(Path(name)) + (" — zdania" if unit == "sentences" else "")
    if new is None:
        return [f"### {title} — removed ({len(old)} {unit})", ""]
    old = old or {}
    added = [w for w in new if w not in old]
    removed = [w for w in old if w not in new]
    changed, moved = [], []
    for w in new:
        if w in old and old[w] != new[w]:
            fields = [f for f in tracked if old[w].get(f, "") != new[w][f]]
            (moved if fields == ["Lesson"] else changed).append((w, fields))
    if not (added or removed or changed or moved):
        return []

    head = f"### {title} — new" if not old else f"### {title}"
    out = [f"{head} ({len(new)} {unit})", ""]
    if added:
        out.append(f"**Added ({len(added)}):**")
        out += [f"- {label(w, new[w])}" for w in added]
        out.append("")
    if removed:
        out.append(f"**Removed ({len(removed)}):**")
        out += [f"- {label(w, old[w])}" for w in removed]
        out.append("")
    if changed:
        out.append(f"**Changed ({len(changed)}):**")
        out += [f"- {w}: {', '.join(fields)}" for w, fields in changed]
        out.append("")
    if moved:
        by_lesson: dict = {}
        for w, _ in moved:
            by_lesson.setdefault(new[w]["Lesson"] or "–", []).append(w)
        out.append(f"**Moved to another lesson ({len(moved)}):**")
        out += [f"- Lekcja {n}: {' '.join(ws)}" for n, ws in sorted(by_lesson.items())]
        out.append("")
    return out


def path_section(title: str, since: str, paths: list[str]) -> list[str]:
    if not since:
        return []
    files = git("diff", "--name-only", since, "--", *paths).split()
    if not files:
        return []
    out = [f"## {title}", "", "Files: " + ", ".join(f"`{f}`" for f in files), ""]
    subjects = git("log", "--format=- %s (%h)", f"{since}..HEAD", "--", *paths).strip()
    if subjects:
        out += [subjects, ""]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="", help="git ref of the previous release")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    old, new = decks_at(args.since), decks_now()
    deck_lines = []
    for name in sorted(set(old) | set(new)):
        deck_lines += deck_section(name, old.get(name), new.get(name))

    lines = []
    if deck_lines:
        lines += ["## Decks", ""] + deck_lines
    lines += path_section("Card templates", args.since, STYLE_PATHS)
    lines += path_section("Build", args.since, BUILD_PATHS)
    changed = bool(lines)

    if args.since:
        commits = git("log", "--format=- %s (%h)", "--invert-grep", "--grep=^Fill GUIDs",
                      f"{args.since}..HEAD").strip()
        if commits:
            lines += ["## Commits", "", commits, ""]
        lines.insert(0, f"Changes since `{args.since}`.\n")
    else:
        lines.insert(0, "First release.\n")
    if not changed:
        lines.insert(1, "No changes to decks, templates or build.\n")

    text = "\n".join(lines).rstrip() + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
