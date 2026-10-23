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
from build import FIELDS, deck_name, sniff_reader  # noqa: E402

TRACKED = FIELDS + ["Tags"]
STYLE_PATHS = ["templates"]
BUILD_PATHS = ["build.py", "requirements.txt"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout


def parse(text: str) -> dict:
    reader = sniff_reader(io.StringIO(text.lstrip("﻿")))
    reader.fieldnames = [h.strip() for h in (reader.fieldnames or [])]
    rows = {}
    for row in reader:
        word = (row.get("WordSimplified") or "").strip()
        if word:
            rows[word] = {k: (row.get(k) or "").strip() for k in TRACKED}
    return rows


def decks_at(ref: str) -> dict:
    """{csv file name: rows} at a git ref ('' = nothing)."""
    if not ref:
        return {}
    names = git("ls-tree", "--name-only", f"{ref}:decks").split()
    return {n: parse(git("show", f"{ref}:decks/{n}")) for n in names if n.endswith(".csv")}


def decks_now() -> dict:
    return {p.name: parse(p.read_text(encoding="utf-8"))
            for p in sorted((ROOT / "decks").glob("*.csv"))}


def label(word: str, row: dict) -> str:
    d = row["Definition"].split("\n")[0]
    return f"{word} ({d})" if d else word


def deck_section(name: str, old: dict | None, new: dict | None) -> list[str]:
    title = deck_name(Path(name))
    if new is None:
        return [f"### {title} — deck removed ({len(old)} words)", ""]
    old = old or {}
    added = [w for w in new if w not in old]
    removed = [w for w in old if w not in new]
    changed = [(w, [f for f in TRACKED if old[w][f] != new[w][f]])
               for w in new if w in old and old[w] != new[w]]
    if not (added or removed or changed):
        return []

    head = f"### {title} — new deck" if not old else f"### {title}"
    out = [f"{head} ({len(new)} words)", ""]
    if added:
        out.append(f"**Added ({len(added)}):** " + ", ".join(label(w, new[w]) for w in added))
        out.append("")
    if removed:
        out.append(f"**Removed ({len(removed)}):** " + ", ".join(label(w, old[w]) for w in removed))
        out.append("")
    if changed:
        out.append(f"**Changed ({len(changed)}):**")
        out += [f"- {w}: {', '.join(fields)}" for w, fields in changed]
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
        commits = git("log", "--format=- %s (%h)", f"{args.since}..HEAD").strip()
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
