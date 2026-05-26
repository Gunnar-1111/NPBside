# NPB.jp Scrape Investigation — 2026-05-26

**Verdict: NPB.jp is the data layer. Static HTML, clean tables, stable URL patterns, player IDs. No JS rendering. Free.**

## URL patterns confirmed

| What | URL | Notes |
|---|---|---|
| Monthly schedule | `/games/2026/schedule_MM.html` | Calendar view. Has team matchups, start times, venues. **No probable SP** on this page. |
| Game boxscore | `/scores/YYYY/MMDD/{team1}-{team2}-{game}/box.html` | Static HTML tables. Sample: `/scores/2026/0526/g-h-01/box.html` (Giants @ SoftBank game 1) |
| Player profile | `/bis/players/{id}.html` | 8-digit numeric ID. Year-by-year career stats. Example: `/bis/players/01305157.html` (Ryosuke Ohtsu, SoftBank P) |
| League leaders | `/bis/YYYY/stats/lp_X_{league}.html` | One stat per page. `c` = Central, `p` = Pacific. E.g., `lp_era_c.html` = Central ERA leaders. Awkward — need to crawl multiple. |
| English | `/eng/` | Footer link. Likely sparser; default to Japanese for breadth. |

Team-code mapping in boxscore URL: `g` = Giants, `h` = Hawks. Matches our single-letter convention but lowercase. `01` = game number for doubleheaders.

## Boxscore structure (the load-bearing scrape)

`box.html` contains a full `<table>` per team with these column headers:

**Pitcher table** (everything we need + more):
```
投手        投球数  打者   投球回  安打   本塁打 四球   死球   三振   暴投   ボーク 失点   自責点
pitcher    pitches BF     IP     H      HR     BB     HBP    K      WP     BK     R      ER
```

Player names link to `/bis/players/{id}.html` — **stable 8-digit IDs are exposed at the boxscore level**, no separate lookup needed. Pitcher line includes a W/L decision marker (○ = win, ● = loss, S = save).

**Batter table**:
```
打順 守備位置 打者   打数  得点  安打  打点  盗塁  + per-inning at-bat outcomes
ord  pos     player AB    R     H     RBI   SB    (per-inning cells, kanji-encoded outcomes like 三振=K, 左越本=LF-HR)
```

Linescore + final score at top. HR list called out separately.

## Player profile (`/bis/players/{id}.html`)

For pitchers, year-by-year + career totals:
- Appearances (試合), Wins, Losses, Saves, ERA, IP (投球回), H, HR, BB, K, HBP, WP, BK, ER, W%

For batters (when pitcher profile, shows zeros): G, AB, H, 2B, 3B, HR, RBI, SB, K, AVG.

**Missing**: xFIP, SIERA, xERA, hard-hit%, anything Statcast-derived. Confirmed — no public batted-ball data for NPB.

## Implications for the engine

**Can derive ourselves** from raw boxscore + profile data:
- FIP: `((13*HR) + (3*(BB+HBP)) - (2*K)) / IP + cFIP_npb`  (cFIP_npb ≈ 3.10, vs MLB's ~3.20)
- xFIP: same formula but with league-average HR/FB applied to FB%. We don't have FB% from NPB.jp profile, so xFIP is **harder** — would need to scrape Statcast-equivalent from delta-graphs or compute from boxscore per-inning batted-ball type.
- WHIP: (H + BB) / IP — trivial from profile.
- K%, BB%: K/BF, BB/BF — need BF (batters faced), which IS in the boxscore.

**Must skip** (no public data source):
- xERA (Statcast-derived)
- hard-hit % / barrel%
- Pitch-by-pitch / launch angle data

So the DugoutSide `SP_WEIGHTS` need a rework: zero out `xera` and `hard_hit_pct` weights, redistribute to FIP/K%/BB%/GB% (or drop GB% if we can't compute it either).

## Open gotchas

1. **Probable SP** not on the monthly schedule page. NPB has a "予告先発" (yokoku sensh, "announced starter") page — needs its own URL. Usually announced ~24 hours before game. Need to find that endpoint.
2. **Player name encoding**. Names appear as kanji in HTML; romaji only on the English version. We'll want a canonical names mapping table (`canonical_names.json`) — players show up in Pinnacle odds as romaji.
3. **Team URL codes vs our abbreviations**. URL uses `g h t db c s d m l e b f` (12 unique). Our `data/teams.json` uses NPB single-letter convention which matches except for `DB` → `db` lowercase. Easy mapping.
4. **Doubleheaders**. `-01` and `-02` suffix in URL. Rare in NPB but they happen.
5. **Called games**. Rain delays + the "5-inning rule" can make a game official short. Handle in totals grading.
6. **Foreign player flags**. Not surfaced in the boxscore obviously. Roster page presumably has it.

## Next steps (in order)

1. **Write a scraper** for daily boxscores → JSON. Single file: `scripts/scrape-day.py YYYY-MM-DD`. Output: per-game pitcher line, batter line, linescore, IDs.
2. **Find the 予告先発 (probable SP) page** — figure out URL, scrape it.
3. **Backfill 2024-2025 seasons** of boxscores → build park-factor calibration dataset.
4. **Pinnacle odds API** — separately, figure out NPB endpoint. Then we have model vs market.
