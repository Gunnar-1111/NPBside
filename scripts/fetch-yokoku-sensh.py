#!/usr/bin/env python3
"""Fetch tomorrow's NPB probable starters (予告先発 / yokoku-sensh).

The data lives in the third <div class="tab_content"> block on the main
npb.jp homepage. Each game block has:
- Home team logo (logo_{code}_m.gif)
- Home pitcher photo wrapped in <a href="/bis/players/{id}.html">
- Home pitcher name in <span class="player_name">
- Away team logo, photo, name (same pattern)
- Venue + start time in <div class="info">

Unlike the historical boxscores, the yokoku-sensh page exposes PLAYER IDs
for each pitcher, which lets us disambiguate the name-collisions in
data/pitcher-ratings.json (伊藤 / 髙橋 / 平良) going forward.

Usage:
    python3 scripts/fetch-yokoku-sensh.py                          # default: label as local-today+1, print to stdout
    python3 scripts/fetch-yokoku-sensh.py --write                  # save data/yokoku-{label}.json
    python3 scripts/fetch-yokoku-sensh.py 2026-05-29 --write       # explicit label (use when MST↔JST drift makes local-today+1 wrong)

Caveat: the npb.jp page always serves JST "tomorrow" — the date arg controls
the file label only. A mismatch warning fires if your label doesn't match the
JST-tomorrow the page is actually serving.
"""

import datetime as dt
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).parent.parent
BASE = "https://npb.jp"

TEAM_CODE_MAP = {
    "g": "G", "t": "T", "db": "DB", "c": "C", "s": "S", "d": "D",
    "h": "H", "m": "M", "l": "L", "e": "E", "b": "B", "f": "F",
}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "NPBSide-yokoku/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


# Match each pitcher entry — player ID + the surrounding team block.
# The link to /bis/players/{id}.html immediately precedes a team_left or
# team_right block that contains logo_{code}_m.gif and player_name.
ENTRY_RE = re.compile(
    r'<a href="/bis/players/(\d+)\.html">'        # player ID
    r'.*?'
    r'<div class="team_(left|right)">'             # team_left = HOME, team_right = AWAY
    r'.*?'
    r'logo_([a-z]+)_m\.gif'                        # team code
    r'.*?'
    r'<span class="player_name">([^<]+)</span>',   # pitcher name
    re.DOTALL,
)

# Venue + start time + weather per game in the info div.
# Stand-alone — paired to games by document order.
INFO_RE = re.compile(
    r'<div class="info">\s*'
    r'（([^）]+)）\s*'              # venue (full-width Japanese parens, kanji)
    r'(\d{1,2}:\d{2})'             # start time
    r'.*?'
    r'alt="([^"]+)"',              # weather alt text (e.g., "くもり時々雨")
    re.DOTALL,
)


def extract_yokoku_block(html):
    """Find the 3rd tab_content (明日の予告先発) block.

    Order: tab1 (前日の結果) > tab2 (本日の試合) > tab3 (明日の予告先発).
    We grab everything after the third occurrence of `<div class="tab_content"`.
    """
    # Match either `class="tab_content"` or `class="tab_content show"` (the
    # active tab has the extra class). Match on the prefix only.
    starts = [m.start() for m in re.finditer(r'<div class="tab_content[\s"]', html)]
    if len(starts) < 3:
        return None
    start = starts[2]
    # Cut at the closing tab_container or script section
    end_m = re.search(r'</div><!--\s*/\.tab_container', html[start:])
    end = start + end_m.start() if end_m else len(html)
    return html[start:end]


def parse_yokoku(html):
    """Return list of game dicts. Pairs entries 2-at-a-time (home then away)."""
    block = extract_yokoku_block(html)
    if not block:
        return []

    entries = []
    for m in ENTRY_RE.finditer(block):
        pid, side, team_code, name = m.groups()
        entries.append({
            "playerId": pid,
            "side": side,  # "left" = home, "right" = away
            "teamCode": team_code,
            "team": TEAM_CODE_MAP.get(team_code, team_code.upper()),
            "name": name.replace("　", " ").strip(),
        })

    infos = [(m.group(1).strip(), m.group(2), m.group(3))
             for m in INFO_RE.finditer(block)]

    # Pair entries 2-at-a-time. First should be home (left), second away (right).
    games = []
    for i in range(0, len(entries), 2):
        if i + 1 >= len(entries):
            break
        a, b = entries[i], entries[i + 1]
        home, away = (a, b) if a["side"] == "left" else (b, a)
        venue, start_time, weather = infos[i // 2] if i // 2 < len(infos) else (None, None, None)
        games.append({
            "home": home["team"],
            "homeSP": home["name"],
            "homeSPId": home["playerId"],
            "away": away["team"],
            "awaySP": away["name"],
            "awaySPId": away["playerId"],
            "venue": venue,
            "startTime": start_time,
            "weather": weather,
        })
    return games


def main():
    write = "--write" in sys.argv
    # First positional arg in YYYY-MM-DD form overrides the auto-computed label.
    date_args = [a for a in sys.argv[1:] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a)]
    if date_args:
        target_date = date_args[0]
    else:
        target_date = (dt.date.today() + dt.timedelta(days=1)).isoformat()

    # Sanity check: the npb.jp page always serves JST-tomorrow. Warn if the
    # requested label disagrees with what we expect the page to contain.
    jst_now = dt.datetime.utcnow() + dt.timedelta(hours=9)
    jst_tomorrow = (jst_now.date() + dt.timedelta(days=1)).isoformat()
    if target_date != jst_tomorrow:
        print(f"WARN: label {target_date} != JST-tomorrow {jst_tomorrow} — "
              f"npb.jp page always serves JST-tomorrow; the file will be labeled "
              f"{target_date} but contain {jst_tomorrow} data.", file=sys.stderr)

    html = fetch(BASE + "/")
    games = parse_yokoku(html)

    out = {
        "date": target_date,
        "fetchedAt": dt.datetime.utcnow().isoformat() + "Z",
        "source": BASE + "/  (third tab_content / 明日の予告先発)",
        "note": "Probable SPs for the next day's slate. Includes player IDs not present in historical legacy boxscores.",
        "games": games,
    }

    print(f"{target_date} probable starters ({len(games)} games):", file=sys.stderr)
    print(f'{"matchup":<8}  {"away SP":<20} (id {"away id":<8})  {"home SP":<20} (id {"home id":<8})  venue / start / weather', file=sys.stderr)
    print("-" * 130, file=sys.stderr)
    for g in games:
        venue = g["venue"] or "?"
        start = g["startTime"] or "?"
        wx = g["weather"] or ""
        m = f'{g["away"]}@{g["home"]}'
        print(f'{m:<8}  {g["awaySP"]:<20} (id {g["awaySPId"]:<8})  {g["homeSP"]:<20} (id {g["homeSPId"]:<8})  {venue} / {start} / {wx}', file=sys.stderr)

    if write:
        out_path = REPO / "data" / f"yokoku-{target_date}.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
        print(f"\n✓ wrote {out_path.relative_to(REPO)}", file=sys.stderr)
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
