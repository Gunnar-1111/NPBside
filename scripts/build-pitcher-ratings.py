#!/usr/bin/env python3
"""Build per-pitcher ratings from the 2024-2025 NPB boxscore corpus.

For each pitcher across the corpus:
- Aggregate IP / BF / H / BB / HBP / K / ER from every appearance
- Attribute HRs allowed from the HR list's `oppPitcher` field
- Compute ERA / FIP / K% / BB% / HR-per-9
- Mark starts (first pitcher in each team's box) separately from appearances
- Derive cFIP_npb such that league-avg FIP equals league-avg ERA
- Convert each pitcher's FIP into a runs-above-average rating

Output: data/pitcher-ratings.json with both `pitchers` (all appearances) and
`starters` (SP-only stats, ≥30 IP filter). League constants in the top-level
keys feed back into the engine — cFIP_npb in particular is the load-bearing
NPB-vs-MLB difference.

Usage:
    python3 scripts/build-pitcher-ratings.py             # dry-run, print summary
    python3 scripts/build-pitcher-ratings.py --write     # write data/pitcher-ratings.json
"""

import glob
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).parent.parent
BOX_DIR = REPO / "data" / "boxscores"
OUT = REPO / "data" / "pitcher-ratings.json"

# Min innings to be ranked as a "qualified" starter for the engine-facing list.
# 30 IP across 2 seasons is a low floor — surfaces ~120 SPs while excluding
# random spot-starters. Tune up to ~80 IP once the engine actually consumes it.
MIN_IP_QUALIFIED = 30

# Seasons that define the rating corpus. We pool 2024-25 (full prior seasons)
# with 2026 (current season, in progress) so ratings reflect current form and
# 2026 debutants/imports get rated at all instead of defaulting to league avg.
# Pooling is IP-weighted, so a thin 2026 sample barely moves an established
# pitcher; debutants with few IP are then regressed by shrink_rating downstream
# (REGRESSION_IP=50). The filter exists so the build is deterministic (the dir
# also holds non-NPB / stray files) — override via e.g. `--seasons 2024,2025`.
CORPUS_SEASONS = {"2024", "2025", "2026"}


def parse_ip_to_outs(ip_str):
    """Convert NPB IP encoding to outs.

    NPB stores IP as "5" (full innings) or "5.1" (5⅓) / "5.2" (5⅔). The fraction
    after the dot is literal thirds-of-an-inning, NOT decimal — so .1 = 1 out
    past 5, .2 = 2 outs past 5. Returns int outs, or None if unparseable.
    """
    if not ip_str:
        return None
    s = str(ip_str).strip()
    s = re.sub(r"\s+", "", s)
    if "+" in s:  # legacy "0+" relief appearance — zero outs but BF >= 1
        return 0
    m = re.match(r"^(\d+)(?:\.([012]))?$", s)
    if not m:
        return None
    inn = int(m.group(1))
    frac = int(m.group(2)) if m.group(2) else 0
    return inn * 3 + frac


def outs_to_ip(outs):
    """Decimal IP for display (5.333 for 5⅓). Engine math uses outs internally."""
    return outs / 3.0


def safe_int(v):
    """Cells render as <br /> for unscored events; treat as 0."""
    if v is None:
        return 0
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if not s or re.fullmatch(r"<br ?/?>", s):
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def collect(seasons=CORPUS_SEASONS):
    """Walk boxscores, aggregate per-pitcher stats (seasons filter by filename year)."""
    # appearances = every game pitcher pitched in
    # starts = appearance where pitcher was first in his team's box (NPB convention)
    factory = lambda: {
        "outs": 0, "bf": 0, "h": 0, "bb": 0, "hbp": 0, "k": 0, "er": 0,
        "hr_allowed": 0, "appearances": 0, "starts": 0,
        "wins": 0, "losses": 0, "saves": 0, "holds": 0,
        "outs_rel": 0,  # outs thrown in a relief role (appearance where idx>0)
        "teams": set(),
    }
    appear = defaultdict(factory)
    # League-wide FIP components split by role, to DERIVE the relief→start penalty:
    # relievers post better rates than starters (no times-through-order, max-effort
    # short bursts), so a relief-heavy rating over-credits a pitcher in a start.
    role_totals = {"GS": defaultdict(int), "REL": defaultdict(int)}
    # Same aggregation, but keyed by (name, team). Splits surname collisions
    # across teams — e.g. 平良 拳太郎 (DeNA SP) vs 平良 海馬 (Seibu RP) were being
    # merged into one bogus 平良 entry. Different teams ⇒ different pitchers.
    appear_team = defaultdict(factory)
    # name -> team -> [min_date, max_date], to tell a true two-person collision
    # (concurrent stints on two teams) from a trade (one person, sequential).
    team_date_span = defaultdict(lambda: defaultdict(lambda: [None, None]))
    n_games = 0

    for f in sorted(glob.glob(str(BOX_DIR / "*.json"))):
        if Path(f).name[:4] not in seasons:
            continue
        game_date = Path(f).name[:10]  # YYYY-MM-DD
        d = json.load(open(f))
        for g in d["games"]:
            if g.get("status") != "final":
                continue
            n_games += 1
            pitcher_team = {}  # name -> team within this game, for HR attribution
            pitcher_role = {}  # name -> "GS"/"REL" within this game, for role splits
            for side in ("away", "home"):
                team = g[side]["team"]
                pitchers = g[side]["pitchers"] or []
                for idx, p in enumerate(pitchers):
                    pname = p.get("pitcher", {}).get("name") if isinstance(p.get("pitcher"), dict) else None
                    if not pname:
                        continue
                    outs = parse_ip_to_outs(p.get("ip"))
                    if outs is None:
                        continue
                    role = "GS" if idx == 0 else "REL"
                    pitcher_team[pname] = team
                    pitcher_role[pname] = role
                    rt = role_totals[role]
                    rt["outs"] += outs
                    rt["bb"] += safe_int(p.get("bb"))
                    rt["hbp"] += safe_int(p.get("hbp"))
                    rt["k"] += safe_int(p.get("k"))
                    if role == "REL":
                        appear[pname]["outs_rel"] += outs
                        appear_team[(pname, team)]["outs_rel"] += outs
                    span = team_date_span[pname][team]
                    if span[0] is None or game_date < span[0]:
                        span[0] = game_date
                    if span[1] is None or game_date > span[1]:
                        span[1] = game_date
                    decision = (p.get("decision") or "").strip()
                    # Tally into both the name-only and (name, team) aggregates.
                    for a in (appear[pname], appear_team[(pname, team)]):
                        a["outs"] += outs
                        a["bf"] += safe_int(p.get("bf"))
                        a["h"] += safe_int(p.get("h"))
                        a["bb"] += safe_int(p.get("bb"))
                        a["hbp"] += safe_int(p.get("hbp"))
                        a["k"] += safe_int(p.get("k"))
                        a["er"] += safe_int(p.get("er"))
                        a["appearances"] += 1
                        if idx == 0:  # starter (first in team's box)
                            a["starts"] += 1
                        a["teams"].add(team)
                        if decision == "○":
                            a["wins"] += 1
                        elif decision == "●":
                            a["losses"] += 1
                        elif decision in ("S", "Ｓ"):
                            a["saves"] += 1
                        elif decision in ("H", "Ｈ"):
                            a["holds"] += 1

            # Attribute HRs from the HR list to both aggregates. The team comes
            # from who the pitcher pitched for in THIS game, so the (name, team)
            # split gets the HRs charged to the right pitcher.
            for hr in g.get("hrList", []) or []:
                pn = hr.get("oppPitcher")
                if pn and pn in appear:
                    appear[pn]["hr_allowed"] += 1
                    t = pitcher_team.get(pn)
                    if t is not None:
                        appear_team[(pn, t)]["hr_allowed"] += 1
                    r = pitcher_role.get(pn)
                    if r is not None:
                        role_totals[r]["hr"] += 1

    return appear, appear_team, team_date_span, role_totals, n_games


def compute_league_averages(pitchers):
    """League-level totals across all pitchers (≥1 IP). Used to derive cFIP_npb."""
    tot = {"outs": 0, "bf": 0, "h": 0, "bb": 0, "hbp": 0, "k": 0, "er": 0, "hr": 0}
    for p in pitchers.values():
        for k in tot:
            tot[k] += p[("outs" if k == "outs" else ("hr_allowed" if k == "hr" else k))]
    ip = outs_to_ip(tot["outs"])
    league = {
        "ip": round(ip, 1),
        "bf": tot["bf"],
        "era": round(tot["er"] * 9 / ip, 3) if ip else None,
        "kPct": round(tot["k"] / tot["bf"], 4) if tot["bf"] else None,
        "bbPct": round(tot["bb"] / tot["bf"], 4) if tot["bf"] else None,
        "hbpPct": round(tot["hbp"] / tot["bf"], 4) if tot["bf"] else None,
        "hr9": round(tot["hr"] * 9 / ip, 3) if ip else None,
    }
    # FIP without the constant: fip_core = (13*HR + 3*(BB+HBP) - 2*K) / IP
    fip_core = ((13 * tot["hr"] + 3 * (tot["bb"] + tot["hbp"]) - 2 * tot["k"]) / ip) if ip else 0
    # cFIP_npb chosen so league FIP = league ERA
    league["cFipNpb"] = round(league["era"] - fip_core, 3) if league["era"] is not None else None
    return league


def compute_pitcher_metrics(p, cFipNpb, league_era):
    outs = p["outs"]
    if outs < 3:
        return None
    ip = outs_to_ip(outs)
    er = p["er"]
    hr = p["hr_allowed"]
    bb = p["bb"]
    hbp = p["hbp"]
    k = p["k"]
    bf = p["bf"]
    era = er * 9 / ip
    fip = (13 * hr + 3 * (bb + hbp) - 2 * k) / ip + cFipNpb
    # Rating: runs above/below league-avg ERA per 9 IP, FIP-based.
    # Positive = better than league average.
    rating = league_era - fip
    return {
        "ip": round(ip, 2),
        "bf": bf,
        "h": p["h"],
        "hr": hr,
        "bb": bb,
        "hbp": hbp,
        "k": k,
        "er": er,
        "era": round(era, 3),
        "fip": round(fip, 3),
        "kPct": round(k / bf, 4) if bf else None,
        "bbPct": round(bb / bf, 4) if bf else None,
        "hr9": round(hr * 9 / ip, 3),
        "reliefShare": round(p.get("outs_rel", 0) / outs, 3) if outs else 0.0,
        "appearances": p["appearances"],
        "starts": p["starts"],
        "wins": p["wins"],
        "losses": p["losses"],
        "saves": p["saves"],
        "holds": p["holds"],
        "rating": round(rating, 3),
    }


def is_true_collision(team_spans):
    """True iff a name's per-team date spans OVERLAP — meaning two different
    people pitched for two teams in the same window (e.g. 平良 Kentaro/DeNA &
    Kaima/Seibu, both active 2024-25). A trade is sequential (disjoint spans:
    Kuri Hiroshima-2024 → Orix-2025) and is the SAME person — don't split him.
    """
    spans = [s for s in team_spans.values() if s[0] and s[1]]
    if len(spans) < 2:
        return False
    spans.sort(key=lambda s: s[0])
    # If any later stint starts on/before an earlier stint ends, they overlap.
    for i in range(1, len(spans)):
        if spans[i][0] <= max(s[1] for s in spans[:i]):
            return True
    return False


def main():
    write = "--write" in sys.argv
    seasons = CORPUS_SEASONS
    if "--seasons" in sys.argv:
        seasons = set(sys.argv[sys.argv.index("--seasons") + 1].split(","))

    print(f"[build-pitcher-ratings] aggregating corpus (seasons {sorted(seasons)})...", file=sys.stderr)
    pitchers, pitchers_team, team_date_span, role_totals, n_games = collect(seasons)
    print(f"  {n_games} final games, {len(pitchers)} distinct pitchers", file=sys.stderr)

    league = compute_league_averages(pitchers)
    cFip = league["cFipNpb"]
    league_era = league["era"]

    # DERIVE the relief→start FIP gap: how many runs of FIP the league loses
    # moving from a relief role to a starting role. cFIP cancels in the gap, so
    # it's purely the difference in FIP-cores. Used downstream to dock a relief-
    # heavy pitcher's rating in proportion to his relief share when he starts.
    def fip_core(t):
        ip_r = outs_to_ip(t["outs"])
        return ((13 * t["hr"] + 3 * (t["bb"] + t["hbp"]) - 2 * t["k"]) / ip_r) if ip_r else 0.0
    gs_fip_core, rel_fip_core = fip_core(role_totals["GS"]), fip_core(role_totals["REL"])
    league["reliefStartFipGap"] = round(gs_fip_core - rel_fip_core, 3)
    print(f"  relief→start FIP gap (DERIVED): {league['reliefStartFipGap']:+.3f} "
          f"(GS core {gs_fip_core:.2f} vs REL core {rel_fip_core:.2f})", file=sys.stderr)
    print(f"\nLeague (full corpus):", file=sys.stderr)
    print(f"  total IP {league['ip']:.0f},  ERA {league_era},  K% {league['kPct']:.3f},  BB% {league['bbPct']:.3f}", file=sys.stderr)
    print(f"  cFIP_npb derived: {cFip}  (MLB FanGraphs uses ~3.10-3.20)", file=sys.stderr)

    # Build per-pitcher records
    out = {}
    for name, p in pitchers.items():
        m = compute_pitcher_metrics(p, cFip, league_era)
        if m is None:
            continue
        m["name"] = name
        m["teams"] = sorted(p["teams"])
        out[name] = m

    # Per-(name, team) records — ONLY for surname collisions, i.e. names that
    # appear across multiple teams (平良 = DeNA's Kentaro + Seibu's Kaima). Single
    # -team pitchers are left out: their name-only entry is already correct and
    # identical, and emitting a split would only risk a tiny HR-attribution drift
    # (the name-only path occasionally over-credits an HR via global name match).
    # Restricting to collisions keeps the blast radius to exactly what's broken.
    collision_names = {
        name for name, p in pitchers.items()
        if len(p["teams"]) > 1 and is_true_collision(team_date_span[name])
    }
    traded = sum(1 for name, p in pitchers.items()
                 if len(p["teams"]) > 1 and name not in collision_names)
    out_by_team = {}
    for (name, team), p in pitchers_team.items():
        if name not in collision_names:
            continue
        m = compute_pitcher_metrics(p, cFip, league_era)
        if m is None:
            continue
        m["name"] = name
        m["team"] = team
        out_by_team[f"{name}|{team}"] = m
    print(f"  {len(collision_names)} true collisions split into {len(out_by_team)} entries "
          f"({traded} multi-team names kept merged as trades)", file=sys.stderr)

    # Qualified starters: starts >= 5 AND IP >= MIN_IP_QUALIFIED
    qualified_starters = sorted(
        [m for m in out.values() if m["starts"] >= 5 and m["ip"] >= MIN_IP_QUALIFIED],
        key=lambda x: -x["rating"],
    )

    print(f"\nQualified starters (≥5 starts AND ≥{MIN_IP_QUALIFIED} IP): {len(qualified_starters)}", file=sys.stderr)
    print(f"\nTop 15 by rating:", file=sys.stderr)
    print(f'{"":>2} {"pitcher":<14} {"team":<5} {"IP":>6} {"ERA":>5} {"FIP":>5} {"K%":>5} {"BB%":>5} {"HR/9":>5} {"rating":>7} {"GS":>3}', file=sys.stderr)
    for i, m in enumerate(qualified_starters[:15], 1):
        kp = f"{m['kPct']*100:.1f}" if m['kPct'] else "—"
        bp = f"{m['bbPct']*100:.1f}" if m['bbPct'] else "—"
        team = "/".join(m['teams'])[:5]
        print(f'{i:>2} {m["name"]:<14} {team:<5} {m["ip"]:>6.1f} {m["era"]:>5.2f} {m["fip"]:>5.2f} {kp:>5} {bp:>5} {m["hr9"]:>5.2f} {m["rating"]:>+7.2f} {m["starts"]:>3}', file=sys.stderr)

    print(f"\nBottom 10 by rating (qualified only):", file=sys.stderr)
    for m in qualified_starters[-10:]:
        kp = f"{m['kPct']*100:.1f}" if m['kPct'] else "—"
        bp = f"{m['bbPct']*100:.1f}" if m['bbPct'] else "—"
        team = "/".join(m['teams'])[:5]
        print(f'   {m["name"]:<14} {team:<5} {m["ip"]:>6.1f} {m["era"]:>5.2f} {m["fip"]:>5.2f} {kp:>5} {bp:>5} {m["hr9"]:>5.2f} {m["rating"]:>+7.2f} {m["starts"]:>3}', file=sys.stderr)

    if write:
        OUT.write_text(json.dumps({
            "_doc": "Per-pitcher ratings from 2024-2025 NPB corpus. `rating` is league-avg ERA minus pitcher FIP (positive=better). HR allowed attributed via HR list's oppPitcher field. Names are plain-text kanji/katakana — legacy NPB.jp pages don't expose player IDs. `pitchers` is keyed by display name (may merge same-surname pitchers across teams); `pitchersByTeam` is keyed 'name|TEAM' and splits those collisions — prefer it when the team is known (see data/pitcher-id-map.json for yokoku playerId → name/team).",
            "_lastUpdated": "2026-06-01",
            "_corpus": {
                "games": n_games,
                "distinctPitchers": len(pitchers),
                "qualifiedStarters": len(qualified_starters),
            },
            "_league": league,
            "_cFipNpb": cFip,
            "_minIpQualified": MIN_IP_QUALIFIED,
            "pitchers": out,
            "pitchersByTeam": out_by_team,
            "qualifiedStartersRanked": [
                {"name": m["name"], "rating": m["rating"], "fip": m["fip"], "ip": m["ip"],
                 "starts": m["starts"], "teams": m["teams"]}
                for m in qualified_starters
            ],
        }, ensure_ascii=False, indent=2))
        print(f"\n✓ wrote {OUT.relative_to(REPO)}  ({len(out)} pitchers, {len(qualified_starters)} qualified)", file=sys.stderr)
    else:
        print(f"\n(dry-run — pass --write to save data/pitcher-ratings.json)", file=sys.stderr)


if __name__ == "__main__":
    main()
