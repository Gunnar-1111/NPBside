#!/usr/bin/env python3
"""Grade NPBSide's originated lines against actual game results.

Reads:
  data/lines-{date}.json      — our model output (line-generator)
  data/boxscores/{date}.json  — actual scores from NPB.jp scrape
  data/book-lines-{date}.json — book's posted line for comparison (optional)

Outputs a per-game scorecard + aggregate:
  - Side: did our favorite win? (W/L)
  - Total: actual vs model (OVER/UNDER, MAE)
  - Run line ±1.5: did each side cover?
  - vs Book: where did we agree/disagree, who got it right?

Run AFTER games are final. Re-scrape the boxscore first if needed:
    python3 scripts/scrape-day.py YYYY-MM-DD

Usage:
    python3 scripts/grade-day.py YYYY-MM-DD
    python3 scripts/grade-day.py YYYY-MM-DD --write   # also save grade-{date}.json
"""

import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent

TEAM_NAMES = {
    "G": "Giants", "T": "Tigers", "DB": "BayStars", "C": "Carp", "S": "Swallows", "D": "Dragons",
    "H": "Hawks", "M": "Marines", "L": "Lions", "E": "Eagles", "B": "Buffaloes", "F": "Fighters",
}


def ml_to_prob(ml):
    return -ml / (-ml + 100) if ml < 0 else 100 / (ml + 100)


def fmt_ml(ml):
    if ml is None:
        return "—"
    return f"+{ml}" if ml > 0 else str(ml)


def main():
    if len(sys.argv) < 2:
        print("Usage: grade-day.py YYYY-MM-DD [--write]", file=sys.stderr)
        sys.exit(1)
    date_str = sys.argv[1]
    write = "--write" in sys.argv

    lines = json.load(open(REPO / "data" / f"lines-{date_str}.json"))
    box_path = REPO / "data" / "boxscores" / f"{date_str}.json"
    if not box_path.exists():
        print(f"missing {box_path} — re-scrape after games finish", file=sys.stderr)
        sys.exit(1)
    box = json.load(open(box_path))
    box_by_match = {(g["away"]["team"], g["home"]["team"]): g for g in box["games"]}

    book_path = REPO / "data" / f"book-lines-{date_str}.json"
    book = {}
    if book_path.exists():
        bk = json.load(open(book_path))
        book = {(g["away"], g["home"]): g for g in bk["games"]}

    rows = []
    side_w, side_l = 0, 0
    rl_home_w, rl_home_l = 0, 0
    total_err = 0.0
    total_n = 0
    book_side_w, book_side_l = 0, 0
    head_to_head = {"we_only": 0, "book_only": 0, "both_right": 0, "both_wrong": 0}

    for entry in lines["games"]:
        away, home = entry["away"], entry["home"]
        g_act = box_by_match.get((away, home))
        if not g_act or g_act["status"] != "final":
            continue
        ar = g_act["away"].get("runs")
        hr = g_act["home"].get("runs")
        if ar is None or hr is None:
            continue
        actual_total = ar + hr
        L = entry["lines"]

        # Side
        model_fav = away if L["awayWinPct"] > 50 else home
        actual_winner = away if ar > hr else home
        side_ok = model_fav == actual_winner
        if side_ok: side_w += 1
        else: side_l += 1

        # Total
        total_diff = actual_total - L["total"]
        total_err += abs(total_diff)
        total_n += 1
        total_side = "OVER" if total_diff > 0 else "UNDER" if total_diff < 0 else "PUSH"

        # Run line — home -1.5 cover
        home_covered_rl = (hr - ar) >= 2
        rl_call = "home -1.5 covered" if home_covered_rl else "away +1.5 covered"
        if home_covered_rl: rl_home_w += 1
        else: rl_home_l += 1

        # Book comparison
        book_g = book.get((away, home))
        book_side_ok = None
        if book_g:
            book_side_ok = book_g["fav"] == actual_winner
            if book_side_ok: book_side_w += 1
            else: book_side_l += 1
            if side_ok and book_side_ok: head_to_head["both_right"] += 1
            elif side_ok and not book_side_ok: head_to_head["we_only"] += 1
            elif not side_ok and book_side_ok: head_to_head["book_only"] += 1
            else: head_to_head["both_wrong"] += 1

        rows.append({
            "matchup": f"{TEAM_NAMES.get(away,away)} @ {TEAM_NAMES.get(home,home)}",
            "actual": f"{ar}-{hr}",
            "actualTotal": actual_total,
            "modelFav": TEAM_NAMES.get(model_fav, model_fav),
            "modelFavMl": L["awayMl"] if L["awayWinPct"] > 50 else L["homeMl"],
            "modelTotal": L["total"],
            "sideOk": side_ok,
            "totalDiff": round(total_diff, 1),
            "totalSide": total_side,
            "rlOutcome": rl_call,
            "bookFav": TEAM_NAMES.get(book_g["fav"], book_g["fav"]) if book_g else None,
            "bookFavMl": book_g["favMl"] if book_g else None,
            "bookTotal": book_g["total"] if book_g else None,
            "bookSideOk": book_side_ok,
        })

    # Print
    print(f"\nNPBSide grading — {date_str}\n")
    print(f"{'Matchup':<24}  {'Actual':<9}  {'Our fav':<10} {'Our ML':>7} {'Our T':>5}  {'Side':>5}  {'T err':>6}  "
          f"{'Book fav':<10} {'Bk ML':>6} {'Bk T':>5}  {'Bk side':>7}")
    print("─" * 130)
    for r in rows:
        side_str = "WIN" if r["sideOk"] else "LOSS"
        td = f"+{r['totalDiff']:.1f}" if r["totalDiff"] > 0 else f"{r['totalDiff']:.1f}"
        book_side_str = ("WIN" if r["bookSideOk"] else "LOSS") if r["bookSideOk"] is not None else "—"
        print(f"{r['matchup']:<24}  {r['actual']:<9}  {r['modelFav']:<10} {fmt_ml(r['modelFavMl']):>7} {r['modelTotal']:>5.1f}  {side_str:>5}  {td:>6}  "
              f"{r['bookFav'] or '—':<10} {fmt_ml(r['bookFavMl']):>6} {(r['bookTotal'] or 0):>5.1f}  {book_side_str:>7}")

    print()
    print(f"NPBSide: {side_w}/{side_w+side_l} sides   Total MAE: {total_err / total_n:.2f} r/g")
    if book:
        print(f"Book:    {book_side_w}/{book_side_w+book_side_l} sides   "
              f"(both right: {head_to_head['both_right']}, we only: {head_to_head['we_only']}, "
              f"book only: {head_to_head['book_only']}, both wrong: {head_to_head['both_wrong']})")

    if write:
        out_path = REPO / "data" / f"grade-{date_str}.json"
        out_path.write_text(json.dumps({
            "date": date_str,
            "summary": {
                "model": {"sides": f"{side_w}-{side_l}", "totalMaeR": round(total_err / total_n, 2) if total_n else None},
                "book": {"sides": f"{book_side_w}-{book_side_l}"} if book else None,
                "headToHead": head_to_head if book else None,
            },
            "games": rows,
        }, ensure_ascii=False, indent=2))
        print(f"\n✓ wrote {out_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
