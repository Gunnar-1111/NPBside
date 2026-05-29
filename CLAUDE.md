# NPBSide — NPB (Japanese baseball) Lines Engine

Sibling project to DugoutSide. Same SP-first architecture; different league, different data feeds, different coefficients.

## Status — data layer live, engine not yet built
2024-2025 NPB seasons scraped (1,819 games, 14k pitcher lines, 49k batter lines via `scripts/scrape-day.py` + legacy/modern parser dispatch). Park runs-factors empirically derived from the corpus. Engine layers (power ratings, sim, GBM, AI) still to build.

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
| League avg runs/team/game | ~4.4 | **~3.30** (empirical, 2024-25, n=1697) |
| Typical total | 8.5 | **6.60** (empirical, 2024-25; far lower than initial 7.5 estimate) |
| HCA (runs) | ~0.35 | **0.11** (DERIVED, 2024-25 corpus n=1753; home win rate 53.9%) |
| Park runs-factor range | 0.85-1.25 | **0.82-1.18** (empirical, 2024-25) |
| Notable extreme parks | Coors (1.18 runs, alt) | **Jingu 1.18 (most hitter-friendly)** ; **Koshien 0.82, Vantelin 0.84 (most pitcher-friendly)**. Tokyo Dome NOT a hitter's park anymore (0.90) — reputation is stale. |
| Bullpen usage | high leverage 9th = closer | similar but more setup specialization |
| Foreign player limit | none | 4 on roster, 1 on active each game |

## Architecture plan
Fork DugoutSide's structure 1:1 once data layer exists:
- Layer 0: power ratings (team offense/pitching/defense + per-SP)
- Layer 1: Monte Carlo sim (10k iters, neg-binomial scoring)
- Layer 2: ML correction (skip until 300+ graded games)
- Layer 4: AI qualitative (Claude layer)

Same SP_WEIGHTS philosophy (FIP/xFIP/SIERA), but **recalibrated constants** from the 2024-25 corpus:
- `LEAGUE_AVG_TOTAL_RUNS = 6.60` (NOT 7.5 as initially planned — NPB is more of a pitcher's league than the initial estimate suggested)
- `LEAGUE_AVG_RUNS_PER_TEAM = 3.30`
- Park `runs` factors: derived in `data/park-factors.json` with `_runsCalibration` field per park noting `n` games used
- `cFIP_npb = 2.618` (DERIVED from 2024-25 corpus; MLB uses 3.10-3.20). Lower constant reflects NPB's lower run environment. The initial plan-number guess of ~3.10 was significantly off.
- `HCA_RUNS = 0.11` (DERIVED from 2024-25 corpus: mean home−away run diff +0.113 over n=1753; home win rate 53.9%). Replaced the 0.30 plan-number, which was ~2.7× too high and was inflating home-favorite ML. Shipped 5/29 (commit 84da93e) — see chalk-tilt watchlist; A/B cut the home-favorite gap vs book +3.5pp→+0.9pp with no side-accuracy cost.
- HR factor still needs empirical derivation (requires HR-list parser from `<div id="gmdivhr">`)

Drop `xera` and `hard_hit_pct` weights from SP_WEIGHTS — no Statcast equivalent for NPB. Redistribute weight to FIP / K% / BB%.

## Open questions before building
1. ~~**Data feed**~~ — RESOLVED. NPB.jp scrape works for both current and historical seasons; two parsers (modern `/scores/` + legacy `/bis/games/`). See `notes/npb-jp-investigation.md`.
2. ~~**Park factors**~~ — Empirically derived from 2024-25 (n=1697). YoY instability on ~6 parks suggests 3rd season would help; revisit in 12 months.
3. **Pitcher peripherals.** FIP/xFIP/SIERA computable from raw boxscore data. Statcast-equivalent (xERA, hard-hit%) doesn't exist for NPB; SP_WEIGHTS will drop those weights and redistribute.
4. **HR park factors.** Legacy parser doesn't capture HR-allowed per pitcher. The HR list lives in `<div id="gmdivhr">` — needs a separate parse. Until then, `hr` factors in park-factors.json remain ROUGH_PRIOR.
5. **Vegas comparison.** Pinnacle NPB endpoint via the-odds-api.com — not yet wired up.
6. **Probable SP** — yokoku-sensh URL not yet found.
7. **Tech stack.** Mirror DugoutSide (Next.js + TS) for code reuse, or stay Python + JSON for the engine layer first?

## Bootstrap order
1. ~~Data sources investigation~~ — done (`notes/npb-jp-investigation.md`)
2. ~~Schedule + boxscore scraper~~ — done (`scripts/scrape-day.py`, modern + legacy parsers)
3. ~~Historical scrape (2024+2025)~~ — done (`scripts/backfill.py`, 1,819 games)
4. ~~Park-run-factor calibration~~ — done (`scripts/calibrate-park-factors.py`)
5. **NEXT: HR-factor parser** (extract HR list from `<div id="gmdivhr">`, calibrate `hr` field)
6. Probable-SP discovery — find yokoku-sensh URL
7. Pinnacle NPB odds via the-odds-api.com — for model-vs-market comparison
8. Team + pitcher rating builder (recompute FIP/xFIP/SIERA from corpus)
9. Line generator (power ratings → sim → totals/ML/RL)
10. Comparison vs Pinnacle on live games

## Repo
https://github.com/Gunnar-1111/NPBside
