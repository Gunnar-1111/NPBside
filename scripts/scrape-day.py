#!/usr/bin/env python3
"""Scrape a day of NPB boxscores from npb.jp into structured JSON.

Usage: python3 scripts/scrape-day.py YYYY-MM-DD
Output: data/boxscores/YYYY-MM-DD.json

Discovers the day's games from /games/YYYY/schedule_MM.html, then for each
game URL fetches /scores/YYYY/MMDD/{away}-{home}-{n}/box.html and parses the
pitcher + batter tables. Stdlib only — no bs4 / requests deps.
"""

import json
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://npb.jp"

# Pitcher table column headers (in order, as they appear on NPB.jp boxscore).
# The leading "" column is the W/L/S decision marker; not labeled in the <th>.
# We identify a pitcher table by checking the first row's <th> kanji sequence.
PITCHER_HEADERS = ["", "投手", "投球数", "打者", "投球回", "安打", "本塁打",
                   "四球", "死球", "三振", "暴投", "ボーク", "失点", "自責点"]
PITCHER_KEYS = ["decision", "pitcher", "pitches", "bf", "ip", "h", "hr",
                "bb", "hbp", "k", "wp", "bk", "r", "er"]

# Batter table — variable suffix of per-inning at-bat outcome cells.
# Leading "" is the lineup-order column (unnamed). 守備 = position, 選手 = player.
BATTER_HEADERS = ["", "守備", "選手", "打数", "得点", "安打", "打点", "盗塁"]
BATTER_KEYS = ["order", "position", "batter", "ab", "r", "h", "rbi", "sb"]

# URL team-code → our teams.json abbr (uppercase per data/teams.json convention)
TEAM_CODE_MAP = {
    "g": "G", "t": "T", "db": "DB", "c": "C", "s": "S", "d": "D",
    "h": "H", "m": "M", "l": "L", "e": "E", "b": "B", "f": "F",
}

PLAYER_LINK_RE = re.compile(r'/bis/players/(\d+)\.html')
GAME_URL_RE = re.compile(r'/scores/(\d{4})/(\d{4})/([a-z]+-[a-z]+-\d+)/')


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "NPBSide-scraper/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


class BoxscoreParser(HTMLParser):
    """Parse a boxscore HTML page into pitcher + batter rows per team.

    Identifies tables by their <th> header sequence and emits rows as dicts.
    Each row carries the team index (0/1) so we can attribute rows after parsing.
    The boxscore renders away team first, then home team, for each table type.
    """

    def __init__(self):
        super().__init__()
        # Depth counter to handle nested <table> markup. Only depth-1 (outermost)
        # tables are parsed; the boxscore embeds a small <table class="table_inning">
        # inside each pitcher's IP cell, and we want to ignore those entirely.
        self.table_depth = 0
        self.in_thead = False
        self.in_tbody = False
        self.in_th = False
        self.in_td = False
        self.in_a = False
        self.current_player_id = None
        self.headers_collected = []  # list of header kanji strings in current table
        self.row_cells = []          # list of cell text or {"id": "...", "name": "..."} for player cells
        self.current_text = []
        self.table_kind = None       # "pitcher" or "batter" or None
        # Output:
        # pitcher_tables / batter_tables are lists in document order — first
        # entry is away team, second is home team (NPB convention).
        self.pitcher_tables = []     # each entry: list of row dicts
        self.batter_tables = []
        self.current_rows = []
        # Linescore parsing is separate — handled by regex post-pass for simplicity.

    def _classify_table(self):
        h = self.headers_collected
        # Note: the "order" column header is an empty <th></th>, so we get "" at index 0.
        if len(h) >= 8 and h[:8] == BATTER_HEADERS:
            return "batter"
        if len(h) >= len(PITCHER_HEADERS) and h[:len(PITCHER_HEADERS)] == PITCHER_HEADERS:
            return "pitcher"
        return None

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "table":
            self.table_depth += 1
            if self.table_depth == 1:
                # Outer table only — reset parse state for it
                self.headers_collected = []
                self.current_rows = []
                self.table_kind = None
                self.in_thead = False
                self.in_tbody = False
            return
        # If we're inside a nested table (depth > 1), ignore all structural tags
        if self.table_depth > 1:
            return
        if tag == "thead":
            self.in_thead = True
        elif tag == "tbody":
            self.in_tbody = True
            if self.table_kind is None:
                self.table_kind = self._classify_table()
        elif tag == "tr":
            self.row_cells = []
        elif tag == "th":
            self.in_th = True
            self.current_text = []
        elif tag == "td":
            self.in_td = True
            self.current_text = []
            self.current_player_id = None
        elif tag == "a" and self.in_td:
            self.in_a = True
            href = attrs_d.get("href", "")
            m = PLAYER_LINK_RE.search(href)
            if m:
                self.current_player_id = m.group(1)

    def handle_endtag(self, tag):
        if tag == "table":
            if self.table_depth == 1:
                # Outermost table closing — commit rows
                if self.table_kind == "pitcher" and self.current_rows:
                    self.pitcher_tables.append(self.current_rows)
                elif self.table_kind == "batter" and self.current_rows:
                    self.batter_tables.append(self.current_rows)
                self.in_thead = False
                self.in_tbody = False
                self.table_kind = None
                self.current_rows = []
            self.table_depth = max(0, self.table_depth - 1)
            return
        if self.table_depth != 1:
            return
        if tag == "th" and self.in_th:
            self.headers_collected.append("".join(self.current_text).strip())
            self.in_th = False
        elif tag == "td" and self.in_td:
            text = "".join(self.current_text).strip()
            if self.current_player_id:
                self.row_cells.append({"id": self.current_player_id, "name": text})
            else:
                self.row_cells.append(text)
            self.in_td = False
        elif tag == "a" and self.in_a:
            self.in_a = False
        elif tag == "tr":
            if self.in_tbody and self.table_kind and self.row_cells:
                # Filter out nested-table garbage cells (per-inning sub-tables produce empty cells)
                # Keep first N cells per known schema.
                if self.table_kind == "pitcher" and len(self.row_cells) >= len(PITCHER_KEYS):
                    row = dict(zip(PITCHER_KEYS, self.row_cells[:len(PITCHER_KEYS)]))
                    # First column is the W/L/S decision marker, we want the pitcher name in column 1.
                    # NPB renders: [decision, pitcher, pitches, BF, IP, H, HR, BB, HBP, K, WP, BK, R, ER]
                    # = 14 columns. Re-shift if we detect that.
                    if len(self.row_cells) >= 14:
                        row = {
                            "decision": (self.row_cells[0] or "").strip(),
                            "pitcher": self.row_cells[1] if isinstance(self.row_cells[1], dict) else {"name": self.row_cells[1]},
                            "pitches": self.row_cells[2],
                            "bf": self.row_cells[3],
                            "ip": self.row_cells[4],
                            "h": self.row_cells[5],
                            "hr": self.row_cells[6],
                            "bb": self.row_cells[7],
                            "hbp": self.row_cells[8],
                            "k": self.row_cells[9],
                            "wp": self.row_cells[10],
                            "bk": self.row_cells[11],
                            "r": self.row_cells[12],
                            "er": self.row_cells[13],
                        }
                    self.current_rows.append(row)
                elif self.table_kind == "batter" and len(self.row_cells) >= len(BATTER_KEYS):
                    row = dict(zip(BATTER_KEYS, self.row_cells[:len(BATTER_KEYS)]))
                    self.current_rows.append(row)
            self.row_cells = []
    def handle_data(self, data):
        # Note: do NOT gate on table_depth here. The IP cell of the pitcher table
        # wraps a nested <table class="table_inning"> whose <th> contains the IP
        # value (e.g., "7"). We want that text aggregated into the outer cell.
        if self.in_th or self.in_td:
            # Skip text from nested <table class="table_inning"> (per-inning cells inside batter rows).
            # That table contains numbers/symbols that aren't part of the main batter line.
            self.current_text.append(data)


def parse_score_and_venue(html, matchup_path):
    """Extract final score + venue name from the boxscore HTML.

    The boxscore page renders a navigation header listing ALL games of the day,
    each as an <a href="/scores/YYYY/MMDD/{matchup}/"> block containing the score
    and venue (in `<div class="state">（venue）...</div>`). We anchor on the
    current game's matchup path to pick the right entry.

    Score format: `<div class="score">{home}-{away}</div>` (home runs first per
    NPB's left-home / right-away rendering convention).

    Returns dict or None.
    """
    # Locate the <a> tag for THIS game and capture the following score + state divs.
    pattern = re.compile(
        r'href="' + re.escape(matchup_path) + r'"' +
        r'.*?<div class="score">\s*(\d+)\s*-\s*(\d+)\s*</div>' +
        r'.*?<div class="state">（([^）]+)）',
        re.DOTALL
    )
    m = pattern.search(html)
    if not m:
        return None
    return {
        "homeRuns": int(m.group(1)),
        "awayRuns": int(m.group(2)),
        "venue": m.group(3).replace("　", ""),
    }


def _clean_ip(val):
    """IP cells render as '7' for full innings or '0\\n  \\xa0+' for partial-inning
    relievers (the '+' marks one or two outs short). Normalize to '7' or '0+'.
    """
    if not isinstance(val, str):
        return val
    s = val.replace("\xa0", "").replace("\n", "").strip()
    s = re.sub(r"\s+", "", s)
    return s


def _clean_pitcher_row(row):
    if "ip" in row:
        row["ip"] = _clean_ip(row["ip"])
    return row


def parse_boxscore(html, away_code, home_code, matchup_path):
    parser = BoxscoreParser()
    parser.feed(html)
    score = parse_score_and_venue(html, matchup_path)
    return {
        "away": {
            "team": TEAM_CODE_MAP.get(away_code, away_code.upper()),
            # NPB boxscore renders the AWAY team's tables first.
            "pitchers": [_clean_pitcher_row(r) for r in (parser.pitcher_tables[0] if len(parser.pitcher_tables) >= 1 else [])],
            "batters": parser.batter_tables[0] if len(parser.batter_tables) >= 1 else [],
        },
        "home": {
            "team": TEAM_CODE_MAP.get(home_code, home_code.upper()),
            "pitchers": [_clean_pitcher_row(r) for r in (parser.pitcher_tables[1] if len(parser.pitcher_tables) >= 2 else [])],
            "batters": parser.batter_tables[1] if len(parser.batter_tables) >= 2 else [],
        },
        "score": score,
    }


def discover_games(date_str):
    """Return list of (home_code, away_code, game_num) tuples for the date.

    NPB.jp URL convention: /scores/YYYY/MMDD/{home}-{away}-{num}/ — the first team
    code is the HOME team, the second is the visiting team. Verified by venue
    cross-check: g-h-01 played at 東京ドーム (Giants' home park), s-l-01 at 神宮
    (Yakult home), db-b-01 at 横浜 (DeNA home). The boxscore page renders the
    AWAY team's tables first, then the HOME team's tables.
    """
    yyyy, mm, dd = date_str.split("-")
    sched_url = f"{BASE}/games/{yyyy}/schedule_{mm}.html"
    print(f"[fetch] {sched_url}", file=sys.stderr)
    html = fetch(sched_url)
    mmdd = mm + dd
    pattern = re.compile(rf'/scores/{yyyy}/{mmdd}/([a-z]+)-([a-z]+)-(\d+)/')
    seen = set()
    games = []
    for m in pattern.finditer(html):
        key = m.group(0)
        if key in seen:
            continue
        seen.add(key)
        games.append((m.group(1), m.group(2), m.group(3)))
    return games


def scrape_day(date_str):
    yyyy, mm, dd = date_str.split("-")
    mmdd = mm + dd
    games = discover_games(date_str)
    print(f"[discover] {len(games)} games on {date_str}: {games}", file=sys.stderr)

    out = {"date": date_str, "games": []}
    for home, away, gnum in games:
        matchup_path = f"/scores/{yyyy}/{mmdd}/{home}-{away}-{gnum}/"
        url = f"{BASE}{matchup_path}box.html"
        print(f"[scrape] {url}", file=sys.stderr)
        try:
            html = fetch(url)
            box = parse_boxscore(html, away, home, matchup_path)
            box["gameUrl"] = url
            box["awayCode"] = away
            box["homeCode"] = home
            box["gameNum"] = int(gnum)
            n_pitchers = len(box["away"]["pitchers"]) + len(box["home"]["pitchers"])
            n_batters = len(box["away"]["batters"]) + len(box["home"]["batters"])
            print(f"  ✓ {box['away']['team']}@{box['home']['team']}  score={box['score']}  pitchers={n_pitchers}  batters={n_batters}", file=sys.stderr)
            out["games"].append(box)
        except Exception as e:
            print(f"  ✗ failed: {e}", file=sys.stderr)

    return out


def main():
    if len(sys.argv) < 2:
        print("Usage: scrape-day.py YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)
    date_str = sys.argv[1]
    result = scrape_day(date_str)

    out_dir = Path(__file__).parent.parent / "data" / "boxscores"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\nWrote {out_path}  ({len(result['games'])} games)", file=sys.stderr)


if __name__ == "__main__":
    main()
