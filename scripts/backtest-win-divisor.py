#!/usr/bin/env python3
"""Backtest WIN_DIVISOR against live results — is the corpus-fit 5.4 well calibrated,
or does the live ledger want a flatter (wider) curve?

WIN_DIVISOR maps model run_diff -> P(home win): p = 1/(1+10^(-run_diff/DIV)).
A LARGER divisor flattens the curve (less chalk). It does NOT change which side is
favored (sign of run_diff), so side W-L is invariant — the only thing it changes is
how extreme our win probs are, i.e. calibration. So we sweep DIV and minimize
log-loss / Brier of our predicted prob vs actual outcomes.

If the live-optimal DIV >> 5.4, either (a) the divisor should widen, or (b) the
run_diffs themselves are inflated (SP-spread) and a wider divisor is compensating.
Both point the same way the chalk-tilt ledger does: we're too chalky.

Inputs (joined by team codes per date):
  data/lines-{date}.json       — model runDiff per game
  data/boxscores/{date}.json   — actual finals (winner)
  data/grade-{date}.json       — book fav + ML (for the chalk-gap-vs-book readout)

Usage:  python3 scripts/backtest-win-divisor.py
Stdlib only.
"""
import glob, json, math, os, re
from pathlib import Path

REPO = Path(__file__).parent.parent
CURRENT_DIV = 5.4

def p_home(run_diff, div):
    return 1.0 / (1.0 + math.pow(10, -run_diff / div))

def load(path):
    with open(path) as f:
        return json.load(f)

# ── Build calibration set: (run_diff, home_won) ─────────────────────────────
samples = []          # (date, home, away, run_diff, home_won)
ties = 0
for lp in sorted(glob.glob(str(REPO / "data" / "lines-*.json"))):
    date = re.search(r"lines-(\d{4}-\d{2}-\d{2})", lp).group(1)
    bp = REPO / "data" / "boxscores" / f"{date}.json"
    if not bp.exists():
        continue
    games = load(lp)
    games = games if isinstance(games, list) else games.get("games", games)
    box = load(bp)
    box_games = box.get("games", box) if isinstance(box, dict) else box
    # map (home,away) -> (homeRuns, awayRuns) for finals
    finals = {}
    for g in box_games:
        h, a = g["home"], g["away"]
        if g.get("status") != "final":
            continue
        hr, ar = h.get("runs"), a.get("runs")
        if hr is None or ar is None:
            continue
        finals[(h["team"], a["team"])] = (hr, ar)
    for g in games:
        rd = (g.get("lines") or {}).get("runDiff")
        if rd is None:
            continue
        key = (g["home"], g["away"])
        if key not in finals:
            continue
        hr, ar = finals[key]
        if hr == ar:
            ties += 1
            continue
        samples.append((date, g["home"], g["away"], rd, 1 if hr > ar else 0))

n = len(samples)
print(f"Calibration set: {n} decided games across "
      f"{len(set(s[0] for s in samples))} slates  ({ties} ties excluded)\n")

# ── Sweep divisor for log-loss + Brier ──────────────────────────────────────
def metrics(div):
    ll = br = 0.0
    eps = 1e-9
    for _, _, _, rd, y in samples:
        p = min(1 - eps, max(eps, p_home(rd, div)))
        ll += -(y * math.log(p) + (1 - y) * math.log(1 - p))
        br += (p - y) ** 2
    return ll / n, br / n

grid = [round(4.0 + 0.2 * i, 1) for i in range(int((12.0 - 4.0) / 0.2) + 1)]
results = [(d, *metrics(d)) for d in grid]
best_ll = min(results, key=lambda r: r[1])
best_br = min(results, key=lambda r: r[2])

print(f"{'DIV':>6}{'logloss':>10}{'brier':>9}")
print("-" * 25)
for d, ll, br in results:
    mark = ""
    if d == CURRENT_DIV: mark += "  <- current"
    if d == best_ll[0]:  mark += "  *min logloss"
    if d == best_br[0]:  mark += "  *min brier"
    # print every 0.4 to keep it readable, plus always print marked rows
    if abs((d * 10) % 4) < 1e-6 or mark:
        print(f"{d:>6.1f}{ll:>10.4f}{br:>9.4f}{mark}")

cur = dict((d, (ll, br)) for d, ll, br in results)[CURRENT_DIV]
print(f"\nCurrent DIV {CURRENT_DIV}: logloss {cur[0]:.4f}  brier {cur[1]:.4f}")
print(f"Min logloss: DIV {best_ll[0]} ({best_ll[1]:.4f})   "
      f"Min brier: DIV {best_br[0]} ({best_br[2]:.4f})")

# Side accuracy (invariant to DIV — confirm)
acc = sum(1 for _, _, _, rd, y in samples if (rd > 0) == (y == 1)) / n
print(f"\nSide accuracy (favorite = sign of run_diff, DIV-invariant): "
      f"{acc*100:.1f}%  ({sum(1 for _,_,_,rd,y in samples if (rd>0)==(y==1))}/{n})")

# ── Chalk gap vs book at current vs optimal DIV ─────────────────────────────
def fav_prob(rd, div):
    p = p_home(rd, div)
    return p if rd > 0 else 1 - p     # the favorite's win prob

def implied(ml):
    return (-ml) / (-ml + 100) if ml < 0 else 100 / (ml + 100)

NAME = {"G":"Giants","T":"Tigers","DB":"BayStars","C":"Carp","S":"Swallows","D":"Dragons",
        "H":"Hawks","M":"Marines","L":"Lions","E":"Eagles","B":"Buffaloes","F":"Fighters"}
name2code = {v: k for k, v in NAME.items()}

opt = best_ll[0]
gaps_cur, gaps_opt = [], []
for gp in sorted(glob.glob(str(REPO / "data" / "grade-*.json"))):
    date = re.search(r"grade-(\d{4}-\d{2}-\d{2})", gp).group(1)
    lp = REPO / "data" / f"lines-{date}.json"
    if not lp.exists():
        continue
    lines = load(lp)
    lines = lines if isinstance(lines, list) else lines.get("games", lines)
    rd_by_fav = {}
    for g in lines:
        rd = (g.get("lines") or {}).get("runDiff")
        if rd is None:
            continue
        fav_code = g["home"] if rd > 0 else g["away"]
        rd_by_fav[fav_code] = rd
    grade = load(gp)
    for row in grade.get("games", []):
        if row.get("bookFav") != row.get("modelFav"):
            continue   # agreement games only
        fav_code = name2code.get(row["modelFav"])
        rd = rd_by_fav.get(fav_code)
        if rd is None or row.get("bookFavMl") is None:
            continue
        book_p = implied(row["bookFavMl"])
        gaps_cur.append((fav_prob(rd, CURRENT_DIV) - book_p) * 100)
        gaps_opt.append((fav_prob(rd, opt) - book_p) * 100)

if gaps_cur:
    mc = sum(gaps_cur) / len(gaps_cur)
    mo = sum(gaps_opt) / len(gaps_opt)
    print(f"\nChalk gap vs book (agreement games, n={len(gaps_cur)}):")
    print(f"  mean model-fav minus book-fav implied:  DIV {CURRENT_DIV} = {mc:+.1f}pp   "
          f"DIV {opt} = {mo:+.1f}pp")
    print(f"  mean |gap|:                              DIV {CURRENT_DIV} = "
          f"{sum(abs(x) for x in gaps_cur)/len(gaps_cur):.1f}pp   "
          f"DIV {opt} = {sum(abs(x) for x in gaps_opt)/len(gaps_opt):.1f}pp")
