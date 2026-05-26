#!/usr/bin/env python3
"""Calibrate NPB park-run factors from the 2024-2025 boxscore corpus.

Method: simple Bill-James-style ratio
    PF_runs(P) = avg(home_runs + away_runs at park P) / grand_mean_total_runs

where grand_mean is computed across all completed games at the 12 standard
NPB parks (neutral-site games are excluded). Splits 2024 vs 2025 alongside the
combined value as a stability sanity check.

This is the simplest valid park factor and doesn't control for team quality —
fine as a v1 replacement for the ROUGH_PRIOR values in data/park-factors.json.
A future regression-based factor (controlling for team offense/pitching) would
be a follow-up.

HR factor is NOT calibrated here — the legacy boxscore parser doesn't capture
HR-allowed per pitcher. Would need to parse the <div id="gmdivhr"> HR-list
section, deferred.

Usage:
    python3 scripts/calibrate-park-factors.py             # dry-run, print table
    python3 scripts/calibrate-park-factors.py --write     # update data/park-factors.json
"""

import glob
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).parent.parent
BOX_DIR = REPO / "data" / "boxscores"
PARK_FILE = REPO / "data" / "park-factors.json"

# Kanji venue prefix → park-factors.json key. Prefix-match handles the
# "バンテリン" / "バンテリンドーム" and "マツダ" / "マツダスタジアム" variants.
VENUE_MAP = [
    ("東京ドーム",       "TOKYO_DOME"),
    ("甲子園",            "KOSHIEN"),
    ("横浜",              "YOKOHAMA"),
    ("マツダ",            "MAZDA"),
    ("神宮",              "JINGU"),
    ("バンテリン",        "VANTELIN"),
    ("みずほPayPay",     "PAYPAY"),
    ("PayPay",            "PAYPAY"),    # alternate rendering
    ("ZOZOマリン",       "ZOZO_MARINE"),
    ("ベルーナ",          "BELLUNA"),
    ("楽天モバイル",      "RAKUTEN"),
    ("京セラ",            "KYOCERA"),
    ("エスコン",          "ES_CON"),
]


def map_venue(venue_kanji):
    """Return park key for a recognized venue, or None for neutral sites."""
    if not venue_kanji:
        return None
    for prefix, park_key in VENUE_MAP:
        if venue_kanji.startswith(prefix):
            return park_key
    return None


def collect_games():
    """Yield (year, park_key, total_runs, venue_raw) for completed games."""
    rows = []
    unmapped = defaultdict(int)
    skipped_no_score = 0
    skipped_non_final = 0
    for f in sorted(glob.glob(str(BOX_DIR / "*.json"))):
        d = json.load(open(f))
        year = int(d["date"][:4])
        for g in d["games"]:
            if g.get("status") != "final":
                skipped_non_final += 1
                continue
            ar = g["away"].get("runs")
            hr_ = g["home"].get("runs")
            if ar is None or hr_ is None:
                skipped_no_score += 1
                continue
            venue = g.get("venue")
            park = map_venue(venue)
            if not park:
                unmapped[venue] += 1
                continue
            rows.append((year, park, ar + hr_, venue))
    return rows, unmapped, skipped_no_score, skipped_non_final


def compute(rows):
    by_park = defaultdict(list)
    for year, park, total, _venue in rows:
        by_park[park].append((year, total))

    all_totals = [t for arr in by_park.values() for _, t in arr]
    grand_mean = sum(all_totals) / len(all_totals)
    grand_std = statistics.stdev(all_totals)

    out = {}
    for park, arr in by_park.items():
        totals = [t for _, t in arr]
        t_2024 = [t for y, t in arr if y == 2024]
        t_2025 = [t for y, t in arr if y == 2025]
        avg = sum(totals) / len(totals)
        out[park] = {
            "n_games": len(totals),
            "n_2024": len(t_2024),
            "n_2025": len(t_2025),
            "avg_runs": avg,
            "pf_runs": avg / grand_mean,
            "pf_2024": (sum(t_2024) / len(t_2024) / grand_mean) if t_2024 else None,
            "pf_2025": (sum(t_2025) / len(t_2025) / grand_mean) if t_2025 else None,
            "stdev": statistics.stdev(totals) if len(totals) > 1 else 0,
        }
    return out, grand_mean, grand_std


def main():
    write = "--write" in sys.argv

    parks = json.load(open(PARK_FILE))
    rows, unmapped, skip_no_score, skip_non_final = collect_games()

    print(f"loaded {len(rows)} games at known parks")
    if unmapped:
        print(f"skipped {sum(unmapped.values())} games at unrecognized venues:")
        for v, n in sorted(unmapped.items(), key=lambda x: -x[1]):
            print(f"   {v}: {n}")
    print(f"skipped {skip_non_final} non-final games, {skip_no_score} games with no score")
    print()

    stats, grand_mean, grand_std = compute(rows)
    print(f"Grand mean total runs/game across NPB parks: {grand_mean:.2f}  (stdev {grand_std:.2f})")
    print()

    print(f'{"park":<13} {"n":>5} {"24n":>4} {"25n":>4} {"avgR":>6} {"PF":>6} {"PF24":>6} {"PF25":>6} {"prior":>6} {"delta":>7} note')
    print("-" * 100)

    big_moves = []
    for park_key in sorted(parks.keys()):
        if park_key.startswith("_"):
            continue
        info = parks[park_key]
        s = stats.get(park_key)
        prior = info.get("runs")
        if not s:
            print(f"{park_key:<13}  NO DATA  (prior {prior})")
            continue

        delta = s["pf_runs"] - prior
        yoy_delta = abs(s["pf_2024"] - s["pf_2025"]) if (s["pf_2024"] and s["pf_2025"]) else 0
        note = ""
        if abs(delta) > 0.05:
            note += "BIG_MOVE "
            big_moves.append((park_key, prior, s["pf_runs"], delta))
        if yoy_delta > 0.06:
            note += "UNSTABLE_YoY "

        pf24 = f"{s['pf_2024']:.3f}" if s["pf_2024"] else "—"
        pf25 = f"{s['pf_2025']:.3f}" if s["pf_2025"] else "—"
        print(f"{park_key:<13} {s['n_games']:>5} {s['n_2024']:>4} {s['n_2025']:>4} "
              f"{s['avg_runs']:>6.2f} {s['pf_runs']:>6.3f} {pf24:>6} {pf25:>6} "
              f"{prior:>6.2f} {delta:>+7.3f} {note}")

    if big_moves:
        print()
        print("Parks that moved >5% from prior:")
        for park, prior, new, delta in sorted(big_moves, key=lambda x: -abs(x[3])):
            direction = "more hitter-friendly" if delta > 0 else "more pitcher-friendly"
            print(f"  {park:<13} {prior:.2f} → {new:.3f}  ({direction})")

    print()
    print(f"LEAGUE_AVG_TOTAL_RUNS candidate for engine constants: {grand_mean:.2f}")
    print(f"  (DugoutSide MLB uses 8.5; NPB CLAUDE.md plan was 7.5)")

    if write:
        for park_key in parks:
            if park_key.startswith("_"):
                continue
            s = stats.get(park_key)
            if s:
                parks[park_key]["runs"] = round(s["pf_runs"], 3)
                parks[park_key]["_runsCalibration"] = (
                    f"DERIVED 2024-2025 (n={s['n_games']}, avg {s['avg_runs']:.2f} r/g)"
                )
        parks["_calibrationStatus"] = "DERIVED — runs factor from 2024-2025 corpus"
        parks["_lastUpdated"] = "2026-05-26"
        parks["_leagueAvgTotalRuns"] = round(grand_mean, 2)
        with open(PARK_FILE, "w") as f:
            json.dump(parks, f, indent=2, ensure_ascii=False)
        print(f"\n✓ wrote {PARK_FILE.relative_to(REPO)}")
    else:
        print()
        print("(dry-run — pass --write to update data/park-factors.json)")


if __name__ == "__main__":
    main()
