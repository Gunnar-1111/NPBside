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
import re
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent

# Engine constants (DERIVED from 2024-25 corpus where possible; the rest are
# starting-point estimates with TODOs to calibrate).
LEAGUE_AVG_PER_TEAM = 3.30       # DERIVED (6.60 / 2)
LEAGUE_AVG_TOTAL = 6.60          # DERIVED
HCA_RUNS = 0.11                  # DERIVED: home-away run diff over 2024-25 corpus (n=1753, +0.113); was 0.30 plan-number
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
    """P(X ≤ k) for X ~ Poisson(lam). Returns 0 when k < 0."""
    if k < 0:
        return 0.0
    return sum(_poisson_pmf(i, lam) for i in range(0, int(k) + 1))


def calculate_run_line_prob(team_runs, opp_runs, line=1.5):
    """Probability team wins by ≥ ceil(line+0.5) (i.e. ≥2 for line=1.5)."""
    prob = 0.0
    margin = int(math.ceil(line + 0.5))  # 2 for -1.5
    for k in range(0, 20):
        prob += _poisson_pmf(k, team_runs) * _poisson_cdf(k - margin, opp_runs)
    return prob


def name_candidates(name):
    """Ordered normalized forms of a yokoku name, most→least specific.

    Yokoku names use a regular space between surname and given name; legacy
    ratings keys are bare surname or surname + first kanji of given name (e.g.
    `加藤貴` for Kato Takayuki). A leading foreign initial ("Ａ．"/"K.") is
    stripped so katakana imports keyed by bare surname (ジャクソン, マラー) match.
    """
    if not name:
        return []
    name_clean = name.replace("　", " ").strip()
    m = re.match(r"^[A-Za-zＡ-Ｚａ-ｚ][.．]\s*(.+)$", name_clean)
    if m:
        name_clean = m.group(1).strip()
    parts = name_clean.split()
    surname = parts[0] if parts else name_clean
    given = parts[1] if len(parts) > 1 else ""
    candidates = [
        name_clean,
        name_clean.replace(" ", "　"),
        name_clean.replace(" ", ""),
    ]
    if given:
        # `松本健`, `加藤貴` — surname+first given kanji is MORE specific than the
        # bare surname, so try it BEFORE surname-only (松本 健吾 → 松本健 +0.12, not
        # the ambiguous bare 松本 −1.76).
        candidates.append(surname + given[0])
    candidates.append(surname)
    seen, out = set(), []
    for c in candidates:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


def lookup_pitcher_rating(by_name, by_team, name, player_id=None, team=None, id_map=None):
    """Resolve a pitcher to a rating, collision-safe.

    Order of preference:
      1. ID-keyed — the yokoku playerId maps (via data/pitcher-id-map.json) to a
         canonical `pitchersByTeam` key. Authoritative; immune to surname clashes.
      2. Team-aware — `name|TEAM` in pitchersByTeam splits same-surname pitchers
         across teams (平良 拳太郎 DeNA vs 平良 海馬 Seibu).
      3. Legacy name-only — bare display-name key (may be a merged collision).
    """
    if player_id and id_map:
        entry = id_map.get(str(player_id))
        if entry and entry.get("key"):
            key = entry["key"]
            if key in by_team:
                return by_team[key]
            if key in by_name:
                return by_name[key]
    cands = name_candidates(name)
    if team:
        for c in cands:
            k = f"{c}|{team}"
            if k in by_team:
                return by_team[k]
    for c in cands:
        if c in by_name:
            return by_name[c]
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


# Fallback if the ratings file predates the derived gap (build re-derives it).
RELIEF_START_GAP_FALLBACK = 0.17


def relief_start_penalty(sp, gap):
    """Runs to dock an SP's rating for relief-inflation when he's starting.

    A pitcher whose rating was built largely on relief innings (平良 海馬 6 GS /
    109 IP; 則本 a full bullpen convert) posts better rates than he would as a
    starter. Dock the rating by his relief share × the league relief→start FIP
    gap. A pure starter (reliefShare ≈ 0) is untouched.
    """
    if not sp:
        return 0.0
    return sp.get("reliefShare", 0.0) * gap


def project_game(home_sp_rating, away_sp_rating,
                 home_off_rating, away_off_rating,
                 park_runs_factor, hca=HCA_RUNS):
    """Expected runs for each team.

    home_runs = (league_avg + home_OFFENSE − away_SP) × park_factor + hca/2
    away_runs = (league_avg + away_OFFENSE − home_SP) × park_factor − hca/2

    Ratings are runs-above-avg per game:
    - SP rating: positive = better pitcher (allows fewer runs)
    - OFFENSE rating: positive = better offense (scores more runs)
    Subtracting opponent's SP from your own offense baseline gives expected
    runs scored. Park factor scales both teams equally.
    """
    home_runs = (LEAGUE_AVG_PER_TEAM + home_off_rating - away_sp_rating) * park_runs_factor + hca / 2
    away_runs = (LEAGUE_AVG_PER_TEAM + away_off_rating - home_sp_rating) * park_runs_factor - hca / 2
    home_runs = max(MIN_EXPECTED_RUNS, home_runs)
    away_runs = max(MIN_EXPECTED_RUNS, away_runs)
    return home_runs, away_runs


def project_lines(home_runs, away_runs):
    total = home_runs + away_runs
    run_diff = home_runs - away_runs
    home_win = run_diff_to_home_win_prob(run_diff)
    away_win = 1 - home_win
    # Home -1.5 covers iff home wins by ≥ 2.
    # Away +1.5 covers iff away loses by ≤ 1 OR wins — i.e., complement of
    # home winning by ≥ 2. No push possible at the half-line.
    home_cover_15 = calculate_run_line_prob(home_runs, away_runs, 1.5)
    away_cover_15 = 1.0 - home_cover_15
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
    pitchers_by_team = ratings_data.get("pitchersByTeam", {})
    id_map_path = REPO / "data" / "pitcher-id-map.json"
    id_map = json.load(open(id_map_path))["ids"] if id_map_path.exists() else {}
    relief_start_gap = ratings_data.get("_league", {}).get(
        "reliefStartFipGap", RELIEF_START_GAP_FALLBACK)
    team_offense_path = REPO / "data" / "team-offense-ratings.json"
    team_offense = json.load(open(team_offense_path))["teams"] if team_offense_path.exists() else {}

    lines_out = []
    for g in yokoku["games"]:
        home_sp = lookup_pitcher_rating(pitchers, pitchers_by_team, g["homeSP"],
                                        g.get("homeSPId"), g.get("home"), id_map)
        away_sp = lookup_pitcher_rating(pitchers, pitchers_by_team, g["awaySP"],
                                        g.get("awaySPId"), g.get("away"), id_map)
        # Relief→start penalty: dock a relief-inflated rating before shrinking, so
        # a bullpen arm making a start isn't priced on his (easier) relief rates.
        home_pen = relief_start_penalty(home_sp, relief_start_gap)
        away_pen = relief_start_penalty(away_sp, relief_start_gap)
        home_rating_raw = (home_sp["rating"] if home_sp else 0.0) - home_pen
        away_rating_raw = (away_sp["rating"] if away_sp else 0.0) - away_pen
        # Shrink rating by IP — a 5-IP rookie with a fluky -4.0 FIP shouldn't
        # produce a -1100 ML. Reverts to league average (0) when IP is small.
        home_ip = home_sp["ip"] if home_sp else 0.0
        away_ip = away_sp["ip"] if away_sp else 0.0
        home_rating = shrink_rating(home_rating_raw, home_ip)
        away_rating = shrink_rating(away_rating_raw, away_ip)

        # Team offense rating (positive = better offense than league avg)
        home_off = team_offense.get(g["home"], {}).get("offenseRating", 0.0)
        away_off = team_offense.get(g["away"], {}).get("offenseRating", 0.0)

        # Park lookup: pick the home team's park
        home_team_park = next(
            (k for k, v in parks.items()
             if not k.startswith("_") and isinstance(v, dict) and v.get("team") == g["home"]),
            None,
        )
        park_runs = parks[home_team_park]["runs"] if home_team_park else 1.0
        park_hr = parks[home_team_park]["hr"] if home_team_park else 1.0

        home_runs, away_runs = project_game(
            home_rating, away_rating,
            home_off, away_off,
            park_runs,
        )
        lines = project_lines(home_runs, away_runs)

        lines_out.append({
            "home": g["home"],
            "away": g["away"],
            "homeSP": g["homeSP"],
            "homeSPId": g.get("homeSPId"),
            "homeSPRating": round(home_rating, 3),
            "homeSPRatingRaw": round(home_rating_raw, 3),
            "homeSPReliefShare": round(home_sp.get("reliefShare", 0.0), 3) if home_sp else None,
            "homeSPReliefPenalty": round(home_pen, 3),
            "homeSPIp": home_ip,
            "homeSPFound": home_sp is not None,
            "homeOffense": round(home_off, 3),
            "awaySP": g["awaySP"],
            "awaySPId": g.get("awaySPId"),
            "awaySPRating": round(away_rating, 3),
            "awaySPRatingRaw": round(away_rating_raw, 3),
            "awaySPReliefShare": round(away_sp.get("reliefShare", 0.0), 3) if away_sp else None,
            "awaySPReliefPenalty": round(away_pen, 3),
            "awaySPIp": away_ip,
            "awaySPFound": away_sp is not None,
            "awayOffense": round(away_off, 3),
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
    print(f"{'matchup':<8}  {'awayML':>7} {'homeML':>7}  {'total':>5}  "
          f"{'home%':>6}  {'aSP':>6} {'hSP':>6}  {'aOff':>6} {'hOff':>6}  {'parkF':>6}  pitchers")
    print("-" * 110)
    for entry in lines_out:
        L = entry["lines"]
        af = "✓" if entry["awaySPFound"] else "✗"
        hf = "✓" if entry["homeSPFound"] else "✗"
        print(f"{entry['away']}@{entry['home']:<5}  "
              f"{L['awayMl']:>+7d} {L['homeMl']:>+7d}  {L['total']:>5.1f}  "
              f"{L['homeWinPct']:>5.1f}%  {entry['awaySPRating']:>+6.2f} {entry['homeSPRating']:>+6.2f}  "
              f"{entry['awayOffense']:>+6.2f} {entry['homeOffense']:>+6.2f}  "
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
