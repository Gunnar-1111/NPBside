#!/usr/bin/env python3
"""Backfill multiple seasons of NPB boxscores by looping scrape-day.py.

Usage:
    python3 scripts/backfill.py START END [--force]
    python3 scripts/backfill.py 2024            # shorthand: 2024 season (Mar-Oct)

Examples:
    python3 scripts/backfill.py 2024 2025                       # both full seasons
    python3 scripts/backfill.py 2025-04-01 2025-04-30           # narrow window
    python3 scripts/backfill.py 2024-03-29 2024-10-15 --force   # overwrite cached

Behavior:
- Skips dates where data/boxscores/{date}.json already exists (resumeable).
- Skips Nov/Dec/Jan/Feb (NPB off-season) automatically.
- Rate-limits ~1 request per 1.5s to be polite to npb.jp.
- Logs per-day progress to stderr; final summary at end.
- Empty-day files (no games scheduled, e.g., All-Star break, off days) are
  preserved as empty `{"games": []}` so the resume check doesn't re-fetch them.
"""

import json
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).parent.parent
DATA = REPO / "data" / "boxscores"
SCRAPER = REPO / "scripts" / "scrape-day.py"

DELAY_SEC = 1.5  # between days (scrape-day itself makes 7 requests/day: 1 schedule + 6 games)
OFF_SEASON_MONTHS = (1, 2, 11, 12)


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def parse_args(argv):
    args = [a for a in argv if not a.startswith("--")]
    force = "--force" in argv

    if len(args) == 1:
        # Shorthand: single year → full season window (Mar 15 – Oct 31)
        yr = int(args[0])
        return date(yr, 3, 15), date(yr, 10, 31), force
    if len(args) == 2:
        # Could be (YYYY YYYY) full multi-year, or (YYYY-MM-DD YYYY-MM-DD)
        a, b = args
        if len(a) == 4 and len(b) == 4:
            return date(int(a), 3, 15), date(int(b), 10, 31), force
        return date.fromisoformat(a), date.fromisoformat(b), force
    print("Usage: backfill.py START END [--force]", file=sys.stderr)
    print("  START/END: YYYY-MM-DD or YYYY (shorthand for full season)", file=sys.stderr)
    sys.exit(1)


def main():
    start, end, force = parse_args(sys.argv[1:])
    DATA.mkdir(parents=True, exist_ok=True)

    total_days = (end - start).days + 1
    print(f"[backfill] {start} → {end}  ({total_days} days, force={force})", file=sys.stderr)

    skipped_existing = 0
    skipped_offseason = 0
    scraped_with_games = 0
    scraped_empty = 0
    errors = 0

    for d in daterange(start, end):
        date_str = d.isoformat()
        out_path = DATA / f"{date_str}.json"

        if d.month in OFF_SEASON_MONTHS:
            skipped_offseason += 1
            continue

        if out_path.exists() and not force:
            skipped_existing += 1
            continue

        print(f"  [{date_str}]  ", end="", flush=True, file=sys.stderr)
        try:
            result = subprocess.run(
                ["python3", str(SCRAPER), date_str],
                capture_output=True, text=True, timeout=180,
            )
            if result.returncode != 0:
                print(f"ERR rc={result.returncode}", file=sys.stderr)
                errors += 1
            elif out_path.exists():
                try:
                    games = json.load(open(out_path)).get("games", [])
                    n = len(games)
                    if n > 0:
                        print(f"{n} games", file=sys.stderr)
                        scraped_with_games += 1
                    else:
                        print("no games", file=sys.stderr)
                        scraped_empty += 1
                except json.JSONDecodeError:
                    print("BAD JSON", file=sys.stderr)
                    errors += 1
            else:
                print("no output", file=sys.stderr)
                errors += 1
        except subprocess.TimeoutExpired:
            print("TIMEOUT", file=sys.stderr)
            errors += 1

        time.sleep(DELAY_SEC)

    print(file=sys.stderr)
    print(f"[backfill] complete", file=sys.stderr)
    print(f"  scraped with games: {scraped_with_games}", file=sys.stderr)
    print(f"  scraped empty days: {scraped_empty}", file=sys.stderr)
    print(f"  skipped (existing): {skipped_existing}", file=sys.stderr)
    print(f"  skipped (offseason): {skipped_offseason}", file=sys.stderr)
    print(f"  errors:             {errors}", file=sys.stderr)
    print(f"  total days in range: {total_days}", file=sys.stderr)


if __name__ == "__main__":
    main()
