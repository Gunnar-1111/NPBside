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


def parse_game_meta(html):
    """Extract game-level metadata from the specific-game data section.

    Reads from `<table id="tablefix_ls">` (the linescore) and surrounding
    `<span class="place">`, `<time>`, `<p class="game_info">` markers — NOT
    from the navigation header at the top of the boxscore page, which
    always shows the CURRENT day's games regardless of the URL date.

    Returns dict (always non-None). Keys present:
      - venue (str | None)
      - status: "final" | "cancelled_rain" | "cancelled" | "no_game" | "unknown"
      - startTime (str "HH:MM" | None)
      - awayRuns, awayHits, awayErrors (int | None — None if cancelled)
      - homeRuns, homeHits, homeErrors (int | None)
    """
    out = {"status": "unknown", "venue": None, "startTime": None,
           "awayRuns": None, "homeRuns": None, "awayHits": None, "homeHits": None,
           "awayErrors": None, "homeErrors": None}

    venue_m = re.search(r'<span class="place">([^<]+)</span>', html)
    if venue_m:
        out["venue"] = venue_m.group(1).replace("　", "").strip()

    if "【雨天のため中止】" in html:
        out["status"] = "cancelled_rain"
    elif "【ノーゲーム】" in html:
        out["status"] = "no_game"
    elif "【中止】" in html:
        out["status"] = "cancelled"
    elif "【試合終了】" in html or "【試合中】" in html:
        out["status"] = "final" if "試合終了" in html else "in_progress"

    start_m = re.search(r"◇開始\s*(\d{1,2}:\d{2})", html)
    if start_m:
        out["startTime"] = start_m.group(1)

    # Linescore totals — top row is AWAY, bottom row is HOME by NPB convention.
    # Each row ends with: <td class="total-1">{R}</td><td class="total-2">{H}</td><td class="total-2">{E}</td>
    top_m = re.search(
        r'<tr class="top">.*?<td class="total-1">(\d+)</td>\s*<td class="total-2">(\d+)</td>\s*<td class="total-2">(\d+)</td>',
        html, re.DOTALL,
    )
    if top_m:
        out["awayRuns"], out["awayHits"], out["awayErrors"] = (int(x) for x in top_m.groups())

    bottom_m = re.search(
        r'<tr class="bottom">.*?<td class="total-1">(\d+)</td>\s*<td class="total-2">(\d+)</td>\s*<td class="total-2">(\d+)</td>',
        html, re.DOTALL,
    )
    if bottom_m:
        out["homeRuns"], out["homeHits"], out["homeErrors"] = (int(x) for x in bottom_m.groups())

    return out


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


# ─── Legacy parser (/bis/{yyyy}/games/sXXXX.html) ──────────────────

# Legacy boxscore pitcher stats row — pitcher table has 10 columns:
#   decision(○/●/blank), name, IP_int, IP_frac, BF(打者), H(安打), BB(四球),
#   HBP(死球), K(三振), ER(自責)
# Decision cell may contain "○" / "●" / "S" (save) / "<br />" (no decision).
# IP_frac cell is e.g. ".1" / ".2" / "<br />" (full innings).
LEGACY_PITCHER_ROW_RE = re.compile(
    r'<tr class="gmstats">'
    r'<td>([^<]*(?:<br ?/?>)?)</td>'      # decision (○/●/S/empty)
    r'<td align="left" nowrap="nowrap">([^<]+)</td>'  # pitcher name
    r'<td align="right">(\d+|<br ?/?>)</td>'           # IP integer
    r'<td align="left">(\.?\d*|<br ?/?>)</td>'         # IP fraction
    r'<td>(\d+)</td>'                                   # BF
    r'<td>(\d+)</td>'                                   # H
    r'<td>(\d+)</td>'                                   # BB
    r'<td>(\d+)</td>'                                   # HBP
    r'<td>(\d+)</td>'                                   # K
    r'<td>(\d+)</td>',                                  # ER
    re.DOTALL,
)

# Legacy HR-list entry. Each HR appears as:
#   <td class="gmresults">［{team_marker}］ {batter_name} {n}号 ( {inning}回{runs}点 {opp_pitcher} )</td>
# The brackets are full-width (FF3B / FF3D), not ASCII. Runs is the RBI total
# on the HR — 1=solo, 2=2-run, 3=3-run, 4=grand slam.
LEGACY_HR_RE = re.compile(
    r'<td class="gmresults">'
    r'\s*［([^］]+)］'           # team marker (full-width brackets)
    r'\s*([^\s0-9<]+)'           # batter name (stops at whitespace/digit/<)
    r'\s+(\d+)号'                # season HR number
    r'\s*\(\s*(\d+)回(\d+)点'    # inning + RBI count
    r'\s+([^\s)<]+)',            # opposing pitcher
    re.DOTALL,
)

# 1-char team markers (inside HR brackets) → team abbr in data/teams.json.
# Verified against sample of 2024-25 games.
LEGACY_HR_TEAM_MARKER = {
    "巨": "G",   # 巨人 (Yomiuri Giants)
    "神": "T",   # 阪神 (Hanshin Tigers)
    "デ": "DB",  # DeNA (Yokohama DeNA BayStars)
    "広": "C",   # 広島 (Hiroshima Carp)
    "ヤ": "S",   # ヤクルト (Yakult Swallows)
    "中": "D",   # 中日 (Chunichi Dragons)
    "ソ": "H",   # ソフトバンク (Fukuoka SoftBank Hawks)
    "ロ": "M",   # ロッテ (Chiba Lotte Marines)
    "西": "L",   # 西武 (Saitama Seibu Lions)
    "楽": "E",   # 楽天 (Tohoku Rakuten Golden Eagles)
    "オ": "B",   # オリックス (Orix Buffaloes)
    "日": "F",   # 日本ハム (Hokkaido Nippon-Ham Fighters)
}


def parse_legacy_hr_list(html):
    """Extract HR list from <div id="gmdivhr">.

    Returns list of dicts: {team, batter, seasonHrNum, inning, runs, oppPitcher}.
    Each entry's `team` is the our team abbr (G/T/DB/etc.) mapped from the marker.
    """
    hrs = []
    for m in LEGACY_HR_RE.finditer(html):
        marker = m.group(1).strip()
        team = LEGACY_HR_TEAM_MARKER.get(marker)
        hrs.append({
            "team": team,
            "teamMarker": marker,
            "batter": m.group(2).strip(),
            "seasonHrNum": int(m.group(3)),
            "inning": int(m.group(4)),
            "runs": int(m.group(5)),  # 1 = solo, 4 = grand slam
            "oppPitcher": m.group(6).strip(),
        })
    return hrs


# Legacy batter row — 8 columns: pos, name, AB, H, RBI, BB, HBP, K
LEGACY_BATTER_ROW_RE = re.compile(
    r'<tr class="gmstats">'
    r'<td>([^<]*)</td>'                                  # position (parens around pos, e.g. "(中)")
    r'<td align="left" nowrap="nowrap">([^<]+)</td>'    # batter name
    r'<td>(\d+)</td>'                                    # AB
    r'<td>(\d+)</td>'                                    # H
    r'<td>(\d+)</td>'                                    # RBI
    r'<td>(\d+)</td>'                                    # BB
    r'<td>(\d+)</td>'                                    # HBP
    r'<td>(\d+)</td>',                                   # K
    re.DOTALL,
)

# Section markers inside gmdivtbl. Order is: away_batters, home_batters, away_pitchers, home_pitchers.
# Each <td class="gmcolorsub"> wraps a <table ... class="gmtbltop"> for one team's table.
# The class attribute is not first; need to match any attribute order.
LEGACY_TBLTOP_RE = re.compile(
    r'<td class="gmcolorsub">.*?<table[^>]*\bclass="gmtbltop"[^>]*>(.*?)</table>',
    re.DOTALL,
)


def _clean_legacy_ip(int_part, frac_part):
    """Combine "3" + ".1" into "3.1" (3 1/3 IP). Empty → "0+" if BF > 0 else None."""
    def normalize(s):
        if not s or re.match(r'<br ?/?>', s.strip()):
            return ""
        return s.strip()
    i = normalize(int_part)
    f = normalize(frac_part)
    if not i and not f:
        return None
    return f"{i or '0'}{f}"


def _parse_legacy_pitcher_table(table_html):
    rows = []
    for m in LEGACY_PITCHER_ROW_RE.finditer(table_html):
        decision_raw, name, ip_int, ip_frac, bf, h, bb, hbp, k, er = m.groups()
        decision = re.sub(r'<br ?/?>', '', decision_raw).strip()
        rows.append({
            "decision": decision,
            "pitcher": {"id": None, "name": name.strip()},
            "ip": _clean_legacy_ip(ip_int, ip_frac),
            "bf": bf, "h": h, "hr": None, "bb": bb, "hbp": hbp,
            "k": k, "wp": None, "bk": None, "r": None, "er": er,
            "pitches": None,
        })
    return rows


def _parse_legacy_batter_table(table_html):
    rows = []
    order = 1
    for m in LEGACY_BATTER_ROW_RE.finditer(table_html):
        pos, name, ab, h, rbi, bb, hbp, k = m.groups()
        rows.append({
            "order": str(order),
            "position": pos.strip(),
            "batter": {"id": None, "name": name.strip()},
            "ab": ab, "r": None, "h": h, "rbi": rbi, "sb": None,
            "bb": bb, "hbp": hbp, "k": k,
        })
        order += 1
    return rows


def parse_legacy_boxscore(html, away_code, home_code):
    """Parse /bis/{yyyy}/games/sXXXX.html (NPB.jp legacy archive format).

    Schema differences vs the modern /scores/.../box.html parser:
    - No player IDs (plain text names only)
    - No HR-allowed column for pitchers
    - No pitch count, no R (only ER)
    - No WP / BK
    - IP split across two cells (integer and fraction)
    """
    # Score, venue, status. Score block has HOME first then AWAY in gmboxrun cells.
    # Pattern: flag{yyyy}_{code}_1l.gif ... gmboxrun">{R}
    box_iter = re.finditer(
        r'flag(\d{4})_([a-z]+)_1l\.gif.*?gmboxrun">(\d+)',
        html, re.DOTALL,
    )
    team_runs = {}
    for m in box_iter:
        _, code, runs = m.groups()
        team_runs[code] = int(runs)

    # Venue + start time + status in gmdivinfo
    venue_m = re.search(r'<td>([^<]+)</td><td align="right">試合時間', html)
    venue = venue_m.group(1).replace("　", "").strip() if venue_m else None
    start_m = re.search(r"開始(\d{1,2}:\d{2})", html)
    start_time = start_m.group(1) if start_m else None

    status = "final"
    if "【中止】" in html or "雨天のため中止" in html:
        status = "cancelled_rain"
    elif "ノーゲーム" in html:
        status = "no_game"

    # Linescore: H and E live in the last 3 <td class="gmscore"> cells of each row.
    # We've already got R from the score block; pull H/E from the linescore.
    # Top row = AWAY, bottom row = HOME (NPB convention).
    linescore_rows = re.findall(
        r'<td class="gmscoreteam">[^<]+</td>(.*?)</tr>',
        html, re.DOTALL,
    )
    away_hits = home_hits = away_errors = home_errors = None
    if len(linescore_rows) >= 2:
        def last_n(s, n):
            cells = re.findall(r'<td[^>]*class="gmscore"[^>]*>([^<]+)</td>', s)
            cells = [c for c in cells if c.strip() not in ("", "-")]
            return cells[-n:] if len(cells) >= n else []
        away_tail = last_n(linescore_rows[0], 3)
        home_tail = last_n(linescore_rows[1], 3)
        if len(away_tail) == 3:
            try: away_hits, away_errors = int(away_tail[1]), int(away_tail[2])
            except ValueError: pass
        if len(home_tail) == 3:
            try: home_hits, home_errors = int(home_tail[1]), int(home_tail[2])
            except ValueError: pass

    # Stat tables. gmdivtbl renders 4 <table class="gmtbltop"> in order:
    #   away_batter, home_batter, away_pitcher, home_pitcher.
    # Filter to just the tables inside gmdivtbl (the page also has stat-header tables
    # at the top with the same class — we want only the ones with gmstats rows).
    gmdivtbl_m = re.search(r'<div id="gmdivtbl">(.*?)</div>(?:\s*<div|\s*</div>)', html, re.DOTALL)
    tbl_section = gmdivtbl_m.group(1) if gmdivtbl_m else html

    away_batters = home_batters = []
    away_pitchers = home_pitchers = []
    tables = LEGACY_TBLTOP_RE.findall(tbl_section)
    # Filter to tables that actually contain gmstats rows (skip header-only tables)
    tables_with_stats = [t for t in tables if 'class="gmstats"' in t]
    if len(tables_with_stats) >= 4:
        away_batters = _parse_legacy_batter_table(tables_with_stats[0])
        home_batters = _parse_legacy_batter_table(tables_with_stats[1])
        away_pitchers = _parse_legacy_pitcher_table(tables_with_stats[2])
        home_pitchers = _parse_legacy_pitcher_table(tables_with_stats[3])

    # HR list (separately parsed; HR-allowed isn't in the pitcher table).
    hr_list = parse_legacy_hr_list(html)
    away_abbr = TEAM_CODE_MAP.get(away_code, away_code.upper())
    home_abbr = TEAM_CODE_MAP.get(home_code, home_code.upper())
    away_hrs = sum(1 for h in hr_list if h["team"] == away_abbr)
    home_hrs = sum(1 for h in hr_list if h["team"] == home_abbr)

    # Also detect rained-out games whose status didn't match my earlier markers.
    # The legacy format uses class="gmout">雨天中止 (no 【】 brackets).
    if 'class="gmout">雨天中止' in html:
        status = "cancelled_rain"
    elif 'class="gmout">ノーゲーム' in html:
        status = "no_game"
    elif 'class="gmout">' in html and status == "final":
        # Any other 'gmout' marker (suspended, postponed) — mark unknown
        # to surface for review rather than silently passing as final.
        status = "unplayed_other"

    return {
        "away": {
            "team": away_abbr,
            "runs": team_runs.get(away_code),
            "hits": away_hits,
            "errors": away_errors,
            "hrs": away_hrs,
            "pitchers": away_pitchers,
            "batters": away_batters,
        },
        "home": {
            "team": home_abbr,
            "runs": team_runs.get(home_code),
            "hits": home_hits,
            "errors": home_errors,
            "hrs": home_hrs,
            "pitchers": home_pitchers,
            "batters": home_batters,
        },
        "hrList": hr_list,
        "status": status,
        "venue": venue,
        "startTime": start_time,
        "format": "legacy",
    }


# ─── Dispatch ─────────────────────────────────────────────────────


def parse_boxscore(html, away_code, home_code):
    parser = BoxscoreParser()
    parser.feed(html)
    meta = parse_game_meta(html)
    return {
        "away": {
            "team": TEAM_CODE_MAP.get(away_code, away_code.upper()),
            "runs": meta["awayRuns"],
            "hits": meta["awayHits"],
            "errors": meta["awayErrors"],
            # NPB boxscore renders the AWAY team's tables first.
            "pitchers": [_clean_pitcher_row(r) for r in (parser.pitcher_tables[0] if len(parser.pitcher_tables) >= 1 else [])],
            "batters": parser.batter_tables[0] if len(parser.batter_tables) >= 1 else [],
        },
        "home": {
            "team": TEAM_CODE_MAP.get(home_code, home_code.upper()),
            "runs": meta["homeRuns"],
            "hits": meta["homeHits"],
            "errors": meta["homeErrors"],
            "pitchers": [_clean_pitcher_row(r) for r in (parser.pitcher_tables[1] if len(parser.pitcher_tables) >= 2 else [])],
            "batters": parser.batter_tables[1] if len(parser.batter_tables) >= 2 else [],
        },
        "status": meta["status"],
        "venue": meta["venue"],
        "startTime": meta["startTime"],
    }


def discover_games(date_str):
    """Return list of (home_code, away_code, game_url) tuples for the date.

    Two discovery paths:

    1. **Historical archive**: /bis/{yyyy}/games/gm{yyyymmdd}.html lists each
       game with `pet{yyyy}_{home}_1.gif` then `pet{yyyy}_{away}_1.gif` images
       followed by `href="sXXXX.html"`. The s-URLs are the LEGACY boxscore
       format (different HTML schema than /scores/). Works for past seasons.

    2. **Current-season schedule**: /games/{yyyy}/schedule_{mm}.html lists
       /scores/.../box.html URLs directly. Modern boxscore format. Works for
       the CURRENT year only — past seasons show the navigation header but
       no game links to that year's games.

    Returns full URLs so the caller can dispatch to the right parser.
    """
    yyyy, mm, dd = date_str.split("-")
    mmdd = mm + dd

    # Path 1: historical archive (preferred — works for past seasons)
    archive_url = f"{BASE}/bis/{yyyy}/games/gm{yyyymmdd_compact(date_str)}.html"
    try:
        html = fetch(archive_url)
        games = _extract_from_archive(html, yyyy)
        if games:
            print(f"[fetch] {archive_url}  → {len(games)} games (legacy)", file=sys.stderr)
            return games
    except Exception as e:
        print(f"[fetch] {archive_url}  → err: {e}", file=sys.stderr)

    # Path 2: current-season schedule fallback (yields modern URLs)
    sched_url = f"{BASE}/games/{yyyy}/schedule_{mm}.html"
    print(f"[fetch] {sched_url}", file=sys.stderr)
    html = fetch(sched_url)
    pattern = re.compile(rf'/scores/{yyyy}/{mmdd}/([a-z]+)-([a-z]+)-(\d+)/')
    seen = set()
    games = []
    for m in pattern.finditer(html):
        key = m.group(0)
        if key in seen:
            continue
        seen.add(key)
        home, away, gnum = m.group(1), m.group(2), m.group(3)
        url = f"{BASE}/scores/{yyyy}/{mmdd}/{home}-{away}-{gnum}/box.html"
        games.append((home, away, url))
    return games


def yyyymmdd_compact(date_str):
    y, m, d = date_str.split("-")
    return f"{y}{m}{d}"


# Match a single game block in the daily archive index. Each game has:
#   pet{yyyy}_{home}_1.gif ... pet{yyyy}_{away}_1.gif ... href="sXXXX.html"
# where the s-URL is the actual archive boxscore for that game.
ARCHIVE_GAME_RE = re.compile(
    r'pet(\d{4})_([a-z]+)_1\.gif.*?pet\1_([a-z]+)_1\.gif.*?href="(s\d+\.html)"',
    re.DOTALL,
)


def _extract_from_archive(html, yyyy):
    """Parse /bis/{yyyy}/games/gm{date}.html.

    Returns list of (home_code, away_code, archive_url) tuples — archive_url is
    the full /bis/{yyyy}/games/sXXX.html URL pointing to the legacy boxscore.
    """
    games = []
    for m in ARCHIVE_GAME_RE.finditer(html):
        year_in_gif, home, away, url_rel = m.group(1), m.group(2), m.group(3), m.group(4)
        if year_in_gif != yyyy:
            continue
        full_url = f"{BASE}/bis/{yyyy}/games/{url_rel}"
        games.append((home, away, full_url))
    return games


def scrape_day(date_str):
    yyyy, mm, dd = date_str.split("-")
    mmdd = mm + dd
    games = discover_games(date_str)
    print(f"[discover] {len(games)} games on {date_str}: {games}", file=sys.stderr)

    out = {"date": date_str, "games": []}
    for home, away, url in games:
        print(f"[scrape] {url}", file=sys.stderr)
        try:
            html = fetch(url)
            # Dispatch: /scores/.../ → modern; /bis/games/sXXX.html → legacy.
            if "/bis/" in url and "/games/s" in url:
                box = parse_legacy_boxscore(html, away, home)
            else:
                box = parse_boxscore(html, away, home)
            box["gameUrl"] = url
            box["awayCode"] = away
            box["homeCode"] = home
            label = f"{box['away']['team']}@{box['home']['team']}"
            ar, hr_ = box["away"]["runs"], box["home"]["runs"]
            score_str = f"{ar}-{hr_}" if ar is not None else "—"
            fmt = box.get("format", "modern")
            print(f"  ✓ {label:<7} {box['status']:<14} {score_str:<6} venue={box['venue']}  start={box['startTime']}  [{fmt}]", file=sys.stderr)
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
