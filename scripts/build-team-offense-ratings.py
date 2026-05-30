#!/usr/bin/env python3
"""Build per-team offense ratings from the 2024-2026 NPB corpus.

Method: park-neutralize each team's runs scored per game, then subtract
the league average to get a "runs above/below avg per game" rating.

    PF_runs = parks[home_venue]['runs']  # per game's home park
    neutralized_runs = team_runs / PF_runs
    offense_rating  = weighted_mean(neutralized_runs) − LEAGUE_AVG_PER_TEAM

RECENCY WEIGHTING (added 2026-05-30): each game is weighted by an
exponential time-decay so recent form counts more than two-season-old
games. A flat mean let a stale 2024 dominate teams whose offense has since
shifted (e.g. the Lions: 2024 −0.73, 2025 −0.27 → flat blend −0.51, which
manufactured road-favorite flips vs the book). Weighting fixes that while
staying robust to tiny current-season samples, because per-game weighting
means a 1-game 2026 contributes ~1 unit of weight against ~100+ from prior
seasons — it barely moves the number until real volume accrues.

    w(game) = 0.5 ** (days_before_reference / HALF_LIFE_DAYS)
    reference = the most recent game date in the corpus (freshest = weight 1)

A game one HALF_LIFE_DAYS old counts half; the published `offenseRating`
is the weighted value (what the line generator reads), and the old flat
mean is preserved as `offenseRatingRaw` for comparison.

Stays raw on opponent quality — doesn't control for opposing-pitcher
strength. With ~280 games per team, schedule effects mostly wash out, but a
v2 regression conditioning on opp SP rating would tighten the estimates.

DH effect note: Pacific League games use DH, Central League don't. A
team's home games therefore reflect their own league's DH context. The
rating below pools both home and away games — Pacific teams' ratings are
slightly inflated and Central teams' slightly deflated by the
interleague-asymmetry. Subtract ~0.10 r from Pacific ratings (or add to
Central) for a quick DH-corrected comparison; v2 should split.

Usage:
    python3 scripts/build-team-offense-ratings.py             # dry-run
    python3 scripts/build-team-offense-ratings.py --write     # write data/team-offense-ratings.json
"""

import glob
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).parent.parent
BOX_DIR = REPO / "data" / "boxscores"
PARK_FILE = REPO / "data" / "park-factors.json"
TEAMS_FILE = REPO / "data" / "teams.json"
OUT = REPO / "data" / "team-offense-ratings.json"

LEAGUE_AVG_PER_TEAM = 3.30  # derived constant from park-factor calibration

# Recency half-life in days: a game this many days before the corpus's most
# recent game carries half the weight of the freshest game. 365 = "one year
# ago counts half" — keeps real signal from 2024-25 while letting current
# form lead. Lower it to trust recent form harder; raise it toward a flat
# mean. Tunable; calibrate against graded model-vs-actuals as the sample grows.
HALF_LIFE_DAYS = 365.0


def _ordinal(date_str):
    """'YYYY-MM-DD' -> day ordinal (int)."""
    y, m, d = (int(x) for x in date_str[:10].split("-"))
    return date(y, m, d).toordinal()

# Same kanji venue → park-key mapping used by the park-factor calibrator.
VENUE_MAP = [
    ("東京ドーム", "TOKYO_DOME"),
    ("甲子園", "KOSHIEN"),
    ("横浜", "YOKOHAMA"),
    ("マツダ", "MAZDA"),
    ("神宮", "JINGU"),
    ("バンテリン", "VANTELIN"),
    ("みずほPayPay", "PAYPAY"),
    ("PayPay", "PAYPAY"),
    ("ZOZOマリン", "ZOZO_MARINE"),
    ("ベルーナ", "BELLUNA"),
    ("楽天モバイル", "RAKUTEN"),
    ("京セラ", "KYOCERA"),
    ("エスコン", "ES_CON"),
]


def map_venue(venue_kanji):
    if not venue_kanji:
        return None
    for prefix, key in VENUE_MAP:
        if venue_kanji.startswith(prefix):
            return key
    return None


def collect():
    parks = json.load(open(PARK_FILE))
    teams_data = json.load(open(TEAMS_FILE))
    team_to_league = {}
    for t in teams_data["central"]:
        team_to_league[t["abbr"]] = "central"
    for t in teams_data["pacific"]:
        team_to_league[t["abbr"]] = "pacific"

    # Per-team accumulator: list of (year, neutralized_runs, raw_runs, opp, is_home)
    per_team = defaultdict(list)
    skipped_venue = 0
    skipped_status = 0
    for f in sorted(glob.glob(str(BOX_DIR / "*.json"))):
        d = json.load(open(f))
        game_date = d["date"][:10]
        year = int(d["date"][:4])
        for g in d["games"]:
            if g.get("status") != "final":
                skipped_status += 1
                continue
            park = map_venue(g.get("venue"))
            if not park or park not in parks or park.startswith("_"):
                skipped_venue += 1
                continue
            park_factor = parks[park]["runs"]
            if not park_factor:
                continue
            for side in ("away", "home"):
                team = g[side]["team"]
                opp = g["home" if side == "away" else "away"]["team"]
                runs = g[side].get("runs")
                if runs is None:
                    continue
                per_team[team].append({
                    "year": year,
                    "date": game_date,
                    "runs": runs,
                    "neutralized": runs / park_factor,
                    "opp": opp,
                    "is_home": side == "home",
                    "park": park,
                })
    return per_team, team_to_league, skipped_venue, skipped_status


def summarize(per_team, league_map, ref_ordinal):
    out = {}
    for team, games in per_team.items():
        if not games:
            continue
        runs = [g["runs"] for g in games]
        neut = [g["neutralized"] for g in games]
        home = [g["neutralized"] for g in games if g["is_home"]]
        away = [g["neutralized"] for g in games if not g["is_home"]]

        # Recency weights: exponential time-decay from the corpus's freshest
        # game. weighted_neut is what feeds offenseRating; the flat mean is
        # kept as offenseRatingRaw so the recency shift is auditable.
        weights = [0.5 ** ((ref_ordinal - _ordinal(g["date"])) / HALF_LIFE_DAYS) for g in games]
        wsum = sum(weights)
        weighted_neut = sum(w * n for w, n in zip(weights, neut)) / wsum
        # Kish effective sample size — how many "full-weight" games the
        # recency-weighted estimate effectively rests on.
        eff_n = (wsum ** 2) / sum(w * w for w in weights)

        by_year = defaultdict(list)
        for g in games:
            by_year[g["year"]].append(g["neutralized"])
        out[team] = {
            "league": league_map.get(team, "unknown"),
            "games": len(games),
            "effectiveGames": round(eff_n, 1),
            "avgRuns": round(sum(runs) / len(runs), 3),
            "avgNeutralized": round(weighted_neut, 3),
            "offenseRating": round(weighted_neut - LEAGUE_AVG_PER_TEAM, 3),
            "offenseRatingRaw": round(sum(neut) / len(neut) - LEAGUE_AVG_PER_TEAM, 3),
            "homeAvgNeutralized": round(sum(home) / len(home), 3) if home else None,
            "awayAvgNeutralized": round(sum(away) / len(away), 3) if away else None,
            "stdev": round(statistics.stdev(runs), 3) if len(runs) > 1 else 0,
            "by_year": {
                str(y): {
                    "n": len(arr),
                    "avgNeutralized": round(sum(arr) / len(arr), 3),
                    "offenseRating": round(sum(arr) / len(arr) - LEAGUE_AVG_PER_TEAM, 3),
                } for y, arr in sorted(by_year.items())
            },
        }
    return out


def main():
    write = "--write" in sys.argv
    per_team, league_map, skip_v, skip_s = collect()
    print(f"loaded games across {len(per_team)} teams (skip_venue={skip_v} skip_status={skip_s})", file=sys.stderr)

    # Reference date for recency decay = the freshest game in the whole corpus.
    ref_ordinal = max(_ordinal(g["date"]) for games in per_team.values() for g in games)
    ref_date = date.fromordinal(ref_ordinal).isoformat()
    print(f"recency: half-life {HALF_LIFE_DAYS:.0f}d, reference (freshest game) {ref_date}", file=sys.stderr)

    summary = summarize(per_team, league_map, ref_ordinal)
    print(f"\n{'team':<5} {'league':<8} {'n':>4} {'effN':>6} {'raw':>7} {'weighted':>9} {'Δ':>7} {'YoY24':>7} {'YoY25':>7}", file=sys.stderr)
    print("-" * 80, file=sys.stderr)
    for team in sorted(summary, key=lambda t: -summary[t]["offenseRating"]):
        s = summary[team]
        y24 = s["by_year"].get("2024", {}).get("offenseRating")
        y25 = s["by_year"].get("2025", {}).get("offenseRating")
        y24_s = f"{y24:+7.2f}" if y24 is not None else "       —"
        y25_s = f"{y25:+7.2f}" if y25 is not None else "       —"
        delta = s["offenseRating"] - s["offenseRatingRaw"]
        print(f"{team:<5} {s['league']:<8} {s['games']:>4} {s['effectiveGames']:>6.0f} "
              f"{s['offenseRatingRaw']:>+7.2f} {s['offenseRating']:>+9.2f} {delta:>+7.2f} "
              f"{y24_s} {y25_s}", file=sys.stderr)

    # League averages for sanity check
    central = [s for s in summary.values() if s["league"] == "central"]
    pacific = [s for s in summary.values() if s["league"] == "pacific"]
    print(f"\nCentral League avg offense rating: {sum(s['offenseRating'] for s in central)/len(central):+.3f}", file=sys.stderr)
    print(f"Pacific League avg offense rating: {sum(s['offenseRating'] for s in pacific)/len(pacific):+.3f}", file=sys.stderr)
    print(f"  (Should be ~0 since the corpus IS the league. Pacific positive / Central negative = DH effect.)", file=sys.stderr)

    if write:
        OUT.write_text(json.dumps({
            "_doc": "Per-team offense rating from the 2024-26 NPB corpus. `offenseRating` = team's recency-weighted park-neutralized avg runs per game minus league average (3.30). Positive = better offense. `offenseRatingRaw` is the un-weighted flat mean for comparison.",
            "_lastUpdated": ref_date,
            "_corpus": {"games": sum(s["games"] for s in summary.values()), "teams": len(summary)},
            "_leagueAvgPerTeam": LEAGUE_AVG_PER_TEAM,
            "_recency": {
                "method": "exponential time-decay by game date",
                "halfLifeDays": HALF_LIFE_DAYS,
                "referenceDate": ref_date,
                "note": "w = 0.5 ** (days_before_reference / halfLifeDays). offenseRating uses these weights; offenseRatingRaw is the flat mean.",
            },
            "_method": "Bill James-style park-neutralization, recency-weighted. NO control for opp SP — v2 should regress on opp pitching.",
            "_caveat": "Pacific League uses DH, Central doesn't. Pacific ratings inflated ~0.1 r/g vs Central.",
            "teams": summary,
        }, ensure_ascii=False, indent=2))
        print(f"\n✓ wrote {OUT.relative_to(REPO)}", file=sys.stderr)


if __name__ == "__main__":
    main()
