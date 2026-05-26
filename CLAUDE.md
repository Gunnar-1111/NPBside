# NPBSide — NPB (Japanese baseball) Lines Engine

Sibling project to DugoutSide. Same SP-first architecture; different league, different data feeds, different coefficients.

## Status — scaffold only
Pre-bootstrap. Park/team tables drafted; data layer not built; no graded games yet.

## Why NPB
- Fewer US books take it (mostly Pinnacle + Asian books) → lower public action, softer lines.
- DugoutSide's SP-driven approach translates directly (pitchers dominate run prevention in NPB too).
- Originating niche: most US originators don't price NPB; the ones that do tend to lean on Pinnacle closes rather than independent models.

## Key differences vs MLB (DugoutSide)
| Factor | MLB | NPB |
|---|---|---|
| Teams | 30 | 12 (6 Central + 6 Pacific) |
| Games/season | 162 | 143 |
| Season | Mar-Oct | Mar-Oct |
| Ball | livelier (post-2024 dejuice) | tighter; HR rates ~25-30% lower |
| DH rule | Universal (2022+) | Pacific only (Central no DH except interleague June) |
| League avg runs/team/game | ~4.4 | ~3.8 |
| Typical total | 8.5 | 7.0-7.5 |
| HCA (runs) | ~0.35 | ~0.30 (slightly less) |
| Park HR factor range | 0.85-1.25 | tighter — most parks 0.85-1.10 |
| Notable extreme parks | Coors (1.18 runs, alt) | Koshien (very pitcher), Jingu (very hitter) |
| Bullpen usage | high leverage 9th = closer | similar but more setup specialization |
| Foreign player limit | none | 4 on roster, 1 on active each game |

## Architecture plan
Fork DugoutSide's structure 1:1 once data layer exists:
- Layer 0: power ratings (team offense/pitching/defense + per-SP)
- Layer 1: Monte Carlo sim (10k iters, neg-binomial scoring)
- Layer 2: ML correction (skip until 300+ graded games)
- Layer 4: AI qualitative (Claude layer)

Same SP_WEIGHTS philosophy (FIP/xFIP/SIERA), but recalibrate league averages and re-derive park factors from historical data.

## Open questions before building
1. **Data feed.** No `pybaseball` for NPB. Candidates:
   - Scrape NPB.jp (Japanese-only, javascript-heavy, fragile)
   - delta-graphs.com / 2nd team stats sites (some English coverage, scrape-friendly)
   - sportsdataio NPB ($)
   - Sportradar NPB ($$)
   - 1.02 Essence of Baseball (Japanese sabermetric site)
   See [notes/data-sources.md](notes/data-sources.md).
2. **Park factors.** Need 2-3 seasons of game-by-game results to back out factors with reasonable n. Initial table has placeholders.
3. **Pitcher peripherals.** FIP/xFIP can be computed from raw splits, but Statcast-equivalent (xERA, hard-hit%) doesn't exist for NPB. Will need to substitute simpler peripheral metrics.
4. **Vegas comparison.** Pinnacle has NPB lines via odds API; offshore books (Bovada, BetOnline) sometimes carry. Hcap consensus equivalent — none.
5. **Tech stack.** Mirror DugoutSide (Next.js + TS) for code reuse, or start lighter (Python scripts + JSON only) until data is proven?

## Bootstrap order
1. Data sources investigation (notes/data-sources.md)
2. Schedule + boxscore scraper for current season (validate data path)
3. Historical results scrape (2 seasons minimum for park factors)
4. Team + pitcher rating builder
5. Line generator (power ratings → sim → totals/ML/RL)
6. Comparison vs Pinnacle on live games

## Repo
https://github.com/Gunnar-1111/NPBside
