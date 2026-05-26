#!/usr/bin/env python3
"""Calibrate NPB park-run AND park-HR factors from the 2024-2025 boxscore corpus.

Method: simple Bill-James-style ratio
    PF_runs(P) = avg(home_runs + away_runs at park P) / grand_mean_total_runs
    PF_hr(P)   = avg(home_hrs  + away_hrs  at park P) / grand_mean_total_hrs

where grand_mean is computed across all completed games at the 12 standard
NPB parks (neutral-site games are excluded). Splits 2024 vs 2025 alongside the
combined value as a stability sanity check.

This is the simplest valid park factor and doesn't control for team quality —
fine as a v1 replacement for the ROUGH_PRIOR values in data/park-factors.json.
A future regression-based factor (controlling for team offense/pitching) would
be a follow-up.

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
    """Yield (year, park_key, total_runs, total_hrs) for completed games."""
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
            # HR counts — new in the HR-parser commit. Tolerate older files
            # without the field (treat as missing rather than 0).
            ah = g["away"].get("hrs")
            hh = g["home"].get("hrs")
            total_hrs = (ah + hh) if (ah is not None and hh is not None) else None
            rows.append((year, park, ar + hr_, total_hrs))
    return rows, unmapped, skipped_no_score, skipped_non_final


def compute(rows):
    by_park = defaultdict(list)
    for year, park, total_r, total_hr in rows:
        by_park[park].append((year, total_r, total_hr))

    all_totals_r = [t for arr in by_park.values() for _, t, _ in arr]
    all_totals_hr = [h for arr in by_park.values() for _, _, h in arr if h is not None]
    grand_mean_r = sum(all_totals_r) / len(all_totals_r)
    grand_mean_hr = (sum(all_totals_hr) / len(all_totals_hr)) if all_totals_hr else None
    grand_std_r = statistics.stdev(all_totals_r)

    out = {}
    for park, arr in by_park.items():
        totals_r = [t for _, t, _ in arr]
        totals_hr = [h for _, _, h in arr if h is not None]
        t24_r = [t for y, t, _ in arr if y == 2024]
        t25_r = [t for y, t, _ in arr if y == 2025]
        t24_hr = [h for y, _, h in arr if y == 2024 and h is not None]
        t25_hr = [h for y, _, h in arr if y == 2025 and h is not None]

        avg_r = sum(totals_r) / len(totals_r)
        avg_hr = (sum(totals_hr) / len(totals_hr)) if totals_hr else None
        out[park] = {
            "n_games": len(totals_r),
            "n_games_with_hr": len(totals_hr),
            "n_2024": len(t24_r),
            "n_2025": len(t25_r),
            "avg_runs": avg_r,
            "avg_hrs": avg_hr,
            "pf_runs": avg_r / grand_mean_r,
            "pf_hr": (avg_hr / grand_mean_hr) if (avg_hr is not None and grand_mean_hr) else None,
            "pf_runs_2024": (sum(t24_r) / len(t24_r) / grand_mean_r) if t24_r else None,
            "pf_runs_2025": (sum(t25_r) / len(t25_r) / grand_mean_r) if t25_r else None,
            "pf_hr_2024": (sum(t24_hr) / len(t24_hr) / grand_mean_hr) if (t24_hr and grand_mean_hr) else None,
            "pf_hr_2025": (sum(t25_hr) / len(t25_hr) / grand_mean_hr) if (t25_hr and grand_mean_hr) else None,
            "stdev": statistics.stdev(totals_r) if len(totals_r) > 1 else 0,
        }
    return out, grand_mean_r, grand_mean_hr, grand_std_r


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

    stats, grand_mean_r, grand_mean_hr, grand_std_r = compute(rows)
    print(f"Grand mean total runs/game: {grand_mean_r:.2f}  (stdev {grand_std_r:.2f})")
    if grand_mean_hr is not None:
        print(f"Grand mean total HRs/game:  {grand_mean_hr:.3f}")
    else:
        print("Grand mean total HRs/game:  (no HR data — re-scrape with HR parser first)")
    print()

    print(f'{"park":<13} {"n":>5} {"avgR":>6} {"PFr":>6} {"PFr24":>6} {"PFr25":>6} '
          f'{"avgHR":>6} {"PFhr":>6} {"PFhr24":>7} {"PFhr25":>7}  notes')
    print("-" * 110)

    big_runs_moves = []
    for park_key in sorted(parks.keys()):
        if park_key.startswith("_"):
            continue
        info = parks[park_key]
        s = stats.get(park_key)
        prior_r = info.get("runs")
        prior_hr = info.get("hr")
        if not s:
            print(f"{park_key:<13}  NO DATA")
            continue

        delta_r = s["pf_runs"] - prior_r
        yoy_r = abs(s["pf_runs_2024"] - s["pf_runs_2025"]) if (s["pf_runs_2024"] and s["pf_runs_2025"]) else 0
        notes = []
        if abs(delta_r) > 0.05:
            notes.append("BIG_R")
            big_runs_moves.append((park_key, prior_r, s["pf_runs"], delta_r))
        if yoy_r > 0.06:
            notes.append("YoY_R")
        if s["pf_hr"] is not None and prior_hr is not None:
            if abs(s["pf_hr"] - prior_hr) > 0.08:
                notes.append("BIG_HR")

        def fmt(v, prec=3):
            return f"{v:.{prec}f}" if v is not None else "—"

        avg_hr_str = f"{s['avg_hrs']:.2f}" if s['avg_hrs'] is not None else "—"
        print(f"{park_key:<13} {s['n_games']:>5} {s['avg_runs']:>6.2f} "
              f"{s['pf_runs']:>6.3f} {fmt(s['pf_runs_2024']):>6} {fmt(s['pf_runs_2025']):>6} "
              f"{avg_hr_str:>6} {fmt(s['pf_hr']):>6} {fmt(s['pf_hr_2024']):>7} {fmt(s['pf_hr_2025']):>7}  "
              f"{','.join(notes)}")

    if big_runs_moves:
        print()
        print("Parks where runs PF moved >5% from prior:")
        for park, prior, new, delta in sorted(big_runs_moves, key=lambda x: -abs(x[3])):
            direction = "hitter-friendly" if delta > 0 else "pitcher-friendly"
            print(f"  {park:<13} {prior:.2f} → {new:.3f}  (more {direction})")

    print()
    print(f"LEAGUE_AVG_TOTAL_RUNS: {grand_mean_r:.2f}  (MLB ~8.5; NPB plan was 7.5)")
    if grand_mean_hr is not None:
        print(f"LEAGUE_AVG_TOTAL_HRS:  {grand_mean_hr:.3f}")

    if write:
        for park_key in parks:
            if park_key.startswith("_"):
                continue
            s = stats.get(park_key)
            if not s:
                continue
            parks[park_key]["runs"] = round(s["pf_runs"], 3)
            parks[park_key]["_runsCalibration"] = (
                f"DERIVED 2024-2025 (n={s['n_games']}, avg {s['avg_runs']:.2f} r/g)"
            )
            if s["pf_hr"] is not None:
                parks[park_key]["hr"] = round(s["pf_hr"], 3)
                parks[park_key]["_hrCalibration"] = (
                    f"DERIVED 2024-2025 (n={s['n_games_with_hr']}, avg {s['avg_hrs']:.2f} hr/g)"
                )
        parks["_calibrationStatus"] = "DERIVED — runs + HR factors from 2024-2025 corpus"
        parks["_lastUpdated"] = "2026-05-26"
        parks["_leagueAvgTotalRuns"] = round(grand_mean_r, 2)
        if grand_mean_hr is not None:
            parks["_leagueAvgTotalHrs"] = round(grand_mean_hr, 3)
        with open(PARK_FILE, "w") as f:
            json.dump(parks, f, indent=2, ensure_ascii=False)
        print(f"\n✓ wrote {PARK_FILE.relative_to(REPO)}")
    else:
        print()
        print("(dry-run — pass --write to update data/park-factors.json)")


if __name__ == "__main__":
    main()
