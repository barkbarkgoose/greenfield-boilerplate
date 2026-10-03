#!/usr/bin/env python3
"""Export / import the site's translations as a spreadsheet for review.

    python i18n_review.py export translations.csv   # every string, both languages
    python i18n_review.py import translations.csv   # write edits back

The CSV has one row per text key with columns: area (site = pages,
server = API text and email subjects), key, english, spanish. Edit the
english/spanish cells in any spreadsheet app and import. Keys can't be added,
removed or renamed this way (do that in the JSON files), so a typo in a key
column is reported instead of silently creating a new string.

Long-form emails aren't in the CSV: review the templates directly in
backend/apps/intake/templates/intake/email/ (customer_*.es.txt are Spanish).
After importing, run the tests (README "Translations") to confirm every pair.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AREAS = {
    "site": ROOT / "frontend" / "src" / "i18n" / "locales",
    "server": ROOT / "backend" / "apps" / "intake" / "text",
}
COLUMNS = ["area", "key", "english", "spanish"]


def load(area: str, language: str) -> dict[str, str]:
    return json.loads((AREAS[area] / f"{language}.json").read_text(encoding="utf-8"))


def save(area: str, language: str, data: dict[str, str]) -> None:
    path = AREAS[area] / f"{language}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export(path: str) -> None:
    rows = 0
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:  # BOM: Excel-friendly
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for area in AREAS:
            english, spanish = load(area, "en"), load(area, "es")
            for key, text in english.items():
                writer.writerow([area, key, text, spanish.get(key, "")])
                rows += 1
    print(f"Wrote {rows} strings to {path}")


def import_(path: str) -> None:
    maps = {(area, lang): load(area, lang) for area in AREAS for lang in ("en", "es")}
    errors, changed = [], 0
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for line, row in enumerate(csv.DictReader(handle), start=2):
            area, key = (row.get("area") or "").strip(), (row.get("key") or "").strip()
            if area not in AREAS or key not in maps[(area, "en")]:
                errors.append(f"line {line}: unknown {area}/{key}")
                continue
            for lang, column in (("en", "english"), ("es", "spanish")):
                value = row.get(column) or ""
                if not value.strip():
                    errors.append(f"line {line}: {key} has an empty {column} cell")
                elif maps[(area, lang)].get(key) != value:
                    maps[(area, lang)][key] = value
                    changed += 1
    if errors:
        sys.exit("Nothing imported. Fix these rows:\n  " + "\n  ".join(errors))
    for (area, lang), data in maps.items():
        save(area, lang, data)
    print(f"Updated {changed} strings. Now run the tests to check every pair.")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in {"export", "import"}:
        sys.exit(__doc__)
    {"export": export, "import": import_}[sys.argv[1]](sys.argv[2])
