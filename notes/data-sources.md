# NPB Data Sources — Investigation List

The single biggest unknown for NPBSide. Goal: a reliable feed for schedule + boxscores + advanced pitching/batting stats, ideally without paying.

## What we need
| Need | MLB equivalent | NPB candidate (TBD) |
|---|---|---|
| Daily schedule + probable SPs | MLB Stats API | NPB.jp schedule, sportsdataio |
| Final scores + linescores | MLB Stats API | NPB.jp results |
| Standard batting/pitching stats | FanGraphs (pybaseball) | NPB.jp, 1.02 Essence |
| Advanced: FIP/xFIP/SIERA | FanGraphs | delta-graphs.com, npb.jp/bis |
| Statcast equivalent | Baseball Savant | **None** — NPB has no public batted-ball data |
| Park factors history | retrosheet + FanGraphs | back-calibrate from 2-3 seasons of game-by-game results |
| Vegas lines | Odds API, FD/DK | Pinnacle (odds API), offshore books |
| Hcap consensus | originators ledger | **None** — no comparable consensus source |
| Injuries | ESPN | NPB.jp team pages (Japanese) |

## Candidate feeds — chase order

### Free / scrape candidates (chase first)
1. **NPB.jp** — official league site. Schedule, results, basic stats. Japanese-only UI. Static-ish HTML; scrape-friendly with care. URL: https://npb.jp/
2. **1.02 Essence of Baseball** (1point02.jp) — Japanese sabermetric site. Has FIP/wOBA/wRC+ for NPB. Subscription tier exists.
3. **delta-graphs.com** — DELTA Inc. (publishes the Japanese sabermetrics book annually). Some free leaderboards.
4. **baseballreference.com /japan** — limited Japanese minor/major data. Decent for historical batter/pitcher career lines.
5. **NPB on Wikipedia** — surprisingly current park dimensions, attendance, etc. Useful for static reference data.

### Paid candidates (only if scrapes fail)
6. **sportsdataio NPB** — quote needed. They have NPB Live Odds + Stats endpoints.
7. **Sportradar NPB** — enterprise-tier; expensive.
8. **NPB Official Statistics Service** — bulk data licensing, contact via NPB.

### Vegas / market feeds
9. **Pinnacle** (via the-odds-api.com) — Pinnacle carries NPB regularly. Free tier 500 req/mo may be enough for daily snapshots.
10. **BetCRIS / Pinnacle direct** — sharpest closing lines.
11. **DraftKings / FanDuel** — US books with NPB during MLB off-season only.

## Validation plan
Before committing to a feed:
- Pull yesterday's full slate's schedule + final scores
- Match against Pinnacle closing lines
- Confirm pitcher splits resolve correctly (the "Yamamoto" name collision problem is real in NPB)
- Test coverage on a foreign player (e.g., Trevor Bauer's NPB tenure) — these are the names US-side bettors will recognize

## Open hard problems
- **Pitcher xERA / Statcast.** No public batted-ball data for NPB. Will need to either skip the xERA layer entirely (use FIP/xFIP/SIERA only) or approximate from K%/BB%/HR/9 alone.
- **Roster turnover.** NPB rosters churn more than MLB; foreign player slots fluctuate.
- **Schedule integrity.** Doubleheaders are rare but happen; rain delays affect totals; need to handle "called game" rule (5+ innings can be official).
- **Translation.** Player names will appear in both kanji/romaji depending on source. Need a canonical names table.
- **Park factor recency.** Es Con Field opened in 2023, so only 3 seasons of data — small sample for park factors. Belluna Dome had dimension tweaks. Need to flag low-confidence parks.

## Next actions
1. Manual: pull one full game's data from NPB.jp by hand. Document what's parseable.
2. Manual: hit the-odds-api.com NPB endpoint with a free key, see what comes back.
3. Decide: are scrapes viable, or do we need sportsdataio?
