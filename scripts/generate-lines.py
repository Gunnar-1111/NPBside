#!/usr/bin/env python3
"""Generate NPB opening lines for a date.

Combines:
- data/yokoku-{date}.json: probable SPs for the date (incl. player IDs)
- data/pitcher-ratings.json: per-pitcher FIP-based runs-above-avg rating
- data/park-factors.json: per-park runs + HR multipliers

Produces moneyline + total + run-line per game and writes data/lines-{date}.json.
Currently no offense rating — uses NPB league-avg total runs (6.60/game) as
baseline. Offense per-team can layer in once we aggregate batter lines.

Pythagorean win prob from run differential:
    P(home_wins) = 1 / (1 + 10^(-run_diff / DIV))
DIV is calibrated to MLB convention (3.8) scaled by NPB's lower run env →
NPB_DIV ≈ 2.9. Real calibration requires graded model-vs-actuals; this is
a starting point.

Usage:
    python3 scripts/generate-lines.py YYYY-MM-DD             # dry-run, print table
    python3 scripts/generate-lines.py YYYY-MM-DD --write     # write data/lines-{date}.json
"""

import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent

# Engine constants (DERIVED from 2024-25 corpus where possible; the rest are
# starting-point estimates with TODOs to calibrate).
LEAGUE_AVG_PER_TEAM = 3.30       # DERIVED (6.60 / 2)
LEAGUE_AVG_TOTAL = 6.60          # DERIVED
HCA_RUNS = 0.30                  # not yet derived — placeholder
WIN_DIVISOR = 2.9                # NPB-scaled pythagorean divisor; calibrate later
VIG = 0.045                      # standard ~4.5% hold (MLB convention)

# Floors so MLs don't blow up on absurd projections
MIN_EXPECTED_RUNS = 1.5
MAX_ML_PROB = 0.92
MIN_ML_PROB = 0.08


def prob_to_american_with_vig(prob, vig=VIG):
    vigged = min(MAX_ML_PROB, max(MIN_ML_PROB, prob + vig / 2))
    if vigged >= 0.5:
        return int(-(vigged / (1 - vigged)) * 100)
    return int(((1 - vigged) / vigged) * 100)


def run_diff_to_home_win_prob(run_diff):
    return 1.0 / (1.0 + math.pow(10, -run_diff / WIN_DIVISOR))


def run_line_prob(team_runs, opp_runs, line=1.5):
    """P(team wins by ≥2) using Poisson per team. NPB lower scoring rate
    makes the Poisson approximation a bit worse than MLB; good enough for v1."""
    import scipy_poisson as _  # noqa: F401  (intentionally fail → fallback below)


def _poisson_pmf(k, lam):
    # stdlib-only Poisson PMF
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _poisson_cdf(k, lam):
    return sum(_poisson_pmf(i, lam) for i in range(0, max(0, int(k)) + 1))


def calculate_run_line_prob(team_runs, opp_runs, line=1.5):
    """Probability team wins by ≥ ceil(line+0.5) (i.e. ≥2 for line=1.5)."""
    prob = 0.0
    margin = int(math.ceil(line + 0.5))  # 2 for -1.5
    for k in range(0, 20):
        prob += _poisson_pmf(k, team_runs) * _poisson_cdf(k - margin, opp_runs)
    return prob


def lookup_pitcher_rating(ratings, name, player_id=None):
    """Best-effort match against the pitcher-ratings map.

    Legacy ratings are keyed by display name (no IDs). Yokoku names use
    a regular space between surname and given name; legacy keys are
    either bare surname or surname + first kanji of given name (e.g.
    `加藤貴` for Kato Takayuki). Try several normalizations in order
    of specificity.
    """
    if not name:
        return None
    name_clean = name.replace("　", " ").strip()
    parts = name_clean.split()
    surname = parts[0] if parts else name_clean
    given = parts[1] if len(parts) > 1 else ""

    # Try exact, full-width-space, surname, surname+first-given-kanji
    candidates = [
        name_clean,
        name_clean.replace(" ", "　"),
        name_clean.replace(" ", ""),
        surname,
    ]
    if given:
        # `加藤貴` (surname + first char of given name)
        candidates.append(surname + given[0])
    for c in candidates:
        if c in ratings:
            return ratings[c]
    return None


# IP-based shrinkage: a pitcher with very few IP gets pulled toward league avg.
# rating_shrunk = rating × (IP / (IP + REGRESSION_IP))
# 50 IP regression target is in line with NPB starter sample volatility
# (an average SP starts ~25 games × 6 IP ≈ 150 IP/season — so 50 is ~1/3 season).
REGRESSION_IP = 50.0


def shrink_rating(rating, ip):
    """Pull rating toward 0 (league average) inversely with IP."""
    if not ip or ip <= 0:
        return 0.0
    weight = ip / (ip + REGRESSION_IP)
    return rating * weight


def project_game(home_sp_rating, away_sp_rating, park_runs_factor, hca=HCA_RUNS):
    """Expected runs for each team.

    home_runs = (league_avg − away_SP_rating) × park_factor + hca/2
    away_runs = (league_avg − home_SP_rating) × park_factor − hca/2

    SP rating is "runs better than league avg per 9 IP" (positive = better).
    Subtracting an opponent's rating gives expected runs they'd allow above/below
    league avg. Park factor scales both teams equally.
    """
    home_runs = (LEAGUE_AVG_PER_TEAM - away_sp_rating) * park_runs_factor + hca / 2
    away_runs = (LEAGUE_AVG_PER_TEAM - home_sp_rating) * park_runs_factor - hca / 2
    home_runs = max(MIN_EXPECTED_RUNS, home_runs)
    away_runs = max(MIN_EXPECTED_RUNS, away_runs)
    return home_runs, away_runs


def project_lines(home_runs, away_runs):
    total = home_runs + away_runs
    run_diff = home_runs - away_runs
    home_win = run_diff_to_home_win_prob(run_diff)
    away_win = 1 - home_win
    home_cover_15 = calculate_run_line_prob(home_runs, away_runs, 1.5)
    away_cover_15 = calculate_run_line_prob(away_runs, home_runs, 1.5)
    return {
        "homeExpectedRuns": round(home_runs, 2),
        "awayExpectedRuns": round(away_runs, 2),
        "total": round(total * 2) / 2,
        "totalRaw": round(total, 2),
        "runDiff": round(run_diff, 2),
        "homeWinPct": round(home_win * 100, 1),
        "awayWinPct": round(away_win * 100, 1),
        "homeMl": prob_to_american_with_vig(home_win),
        "awayMl": prob_to_american_with_vig(away_win),
        "homeRl15Pct": round(home_cover_15 * 100, 1),
        "awayRl15Pct": round(away_cover_15 * 100, 1),
        "homeRl15Price": prob_to_american_with_vig(home_cover_15),
        "awayRl15Price": prob_to_american_with_vig(away_cover_15),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: generate-lines.py YYYY-MM-DD [--write]", file=sys.stderr)
        sys.exit(1)
    date_str = sys.argv[1]
    write = "--write" in sys.argv

    yokoku_path = REPO / "data" / f"yokoku-{date_str}.json"
    if not yokoku_path.exists():
        print(f"missing {yokoku_path}", file=sys.stderr)
        sys.exit(1)
    ratings_data = json.load(open(REPO / "data" / "pitcher-ratings.json"))
    parks = json.load(open(REPO / "data" / "park-factors.json"))
    yokoku = json.load(open(yokoku_path))
    pitchers = ratings_data["pitchers"]

    lines_out = []
    for g in yokoku["games"]:
        home_sp = lookup_pitcher_rating(pitchers, g["homeSP"])
        away_sp = lookup_pitcher_rating(pitchers, g["awaySP"])
        # Shrink rating by IP — a 5-IP rookie with a fluky -4.0 FIP shouldn't
        # produce a -1100 ML. Reverts to league average (0) when IP is small.
        home_rating_raw = home_sp["rating"] if home_sp else 0.0
        home_ip = home_sp["ip"] if home_sp else 0.0
        away_rating_raw = away_sp["rating"] if away_sp else 0.0
        away_ip = away_sp["ip"] if away_sp else 0.0
        home_rating = shrink_rating(home_rating_raw, home_ip)
        away_rating = shrink_rating(away_rating_raw, away_ip)

        # Park lookup: pick the home team's park
        home_team_park = next(
            (k for k, v in parks.items()
             if not k.startswith("_") and isinstance(v, dict) and v.get("team") == g["home"]),
            None,
        )
        park_runs = parks[home_team_park]["runs"] if home_team_park else 1.0
        park_hr = parks[home_team_park]["hr"] if home_team_park else 1.0

        home_runs, away_runs = project_game(home_rating, away_rating, park_runs)
        lines = project_lines(home_runs, away_runs)

        lines_out.append({
            "home": g["home"],
            "away": g["away"],
            "homeSP": g["homeSP"],
            "homeSPId": g.get("homeSPId"),
            "homeSPRating": round(home_rating, 3),
            "homeSPRatingRaw": round(home_rating_raw, 3),
            "homeSPIp": home_ip,
            "homeSPFound": home_sp is not None,
            "awaySP": g["awaySP"],
            "awaySPId": g.get("awaySPId"),
            "awaySPRating": round(away_rating, 3),
            "awaySPRatingRaw": round(away_rating_raw, 3),
            "awaySPIp": away_ip,
            "awaySPFound": away_sp is not None,
            "park": home_team_park,
            "parkRunsFactor": park_runs,
            "parkHrFactor": park_hr,
            "venue": g.get("venue"),
            "startTime": g.get("startTime"),
            "weather": g.get("weather"),
            "lines": lines,
        })

    # Print
    print(f"NPB {date_str} — {len(lines_out)} games")
    print(f"{'matchup':<8}  {'awayML':>8} {'homeML':>8}  {'total':>5}  "
          f"{'home%':>6}  {'awayR':>6} {'homeR':>6}  {'aRating':>8} {'hRating':>8}  {'parkF':>6}  pitchers (found?)")
    print("-" * 130)
    for entry in lines_out:
        L = entry["lines"]
        af = "✓" if entry["awaySPFound"] else "✗"
        hf = "✓" if entry["homeSPFound"] else "✗"
        print(f"{entry['away']}@{entry['home']:<5}  "
              f"{L['awayMl']:>+8d} {L['homeMl']:>+8d}  {L['total']:>5.1f}  "
              f"{L['homeWinPct']:>5.1f}%  {L['awayExpectedRuns']:>6.2f} {L['homeExpectedRuns']:>6.2f}  "
              f"{entry['awaySPRating']:>+8.2f} {entry['homeSPRating']:>+8.2f}  "
              f"{entry['parkRunsFactor']:>6.3f}  "
              f"{entry['awaySP']}({af}) vs {entry['homeSP']}({hf})")

    if write:
        out_path = REPO / "data" / f"lines-{date_str}.json"
        out_path.write_text(json.dumps({
            "date": date_str,
            "generatedAt": yokoku.get("fetchedAt"),
            "constants": {
                "LEAGUE_AVG_PER_TEAM": LEAGUE_AVG_PER_TEAM,
                "LEAGUE_AVG_TOTAL": LEAGUE_AVG_TOTAL,
                "HCA_RUNS": HCA_RUNS,
                "WIN_DIVISOR": WIN_DIVISOR,
                "VIG": VIG,
            },
            "games": lines_out,
        }, ensure_ascii=False, indent=2))
        print(f"\n✓ wrote {out_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
