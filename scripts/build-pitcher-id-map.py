#!/usr/bin/env python3
"""Build a yokoku playerId → (name, team, ratings key) registry.

The legacy boxscore corpus has no player IDs, so pitcher-ratings.json is keyed
by display name (and now also by 'name|TEAM' in `pitchersByTeam`). The yokoku
(予告先発) page DOES expose a stable playerId per pitcher. This script harvests
every (id, name, team) it has seen across saved yokoku-*.json files and resolves
each to the canonical `pitchersByTeam` key, giving the engine an unambiguous,
ID-addressed path to a rating — the durable fix for surname collisions like
平良 拳太郎 (DeNA) vs 平良 海馬 (Seibu).

Output: data/pitcher-id-map.json — { playerId: {name, team, key, resolved} }.

Usage:
    python3 scripts/build-pitcher-id-map.py            # dry-run summary
    python3 scripts/build-pitcher-id-map.py --write     # write data/pitcher-id-map.json
"""

import glob
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent


def name_candidates(name):
    """Ordered normalized forms of a yokoku name, most→least specific.

    Mirrors generate-lines.lookup_pitcher_rating so a key resolved here matches
    what the engine would look up. Strips a leading foreign initial (Ａ．/K.) and
    prefers surname+given over the ambiguous bare surname.
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
    cands = [name_clean, name_clean.replace(" ", "　"), name_clean.replace(" ", "")]
    if given:
        cands.append(surname + given[0])
    cands.append(surname)
    # de-dupe, keep order
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


def resolve_key(name, team, by_team, by_name):
    """Resolve (name, team) → a ratings key. Prefer 'name|TEAM', then bare name."""
    for c in name_candidates(name):
        k = f"{c}|{team}"
        if k in by_team:
            return k, True
    for c in name_candidates(name):
        if c in by_name:
            return c, False   # matched name-only (no team split available)
    return None, False


def main():
    write = "--write" in sys.argv
    ratings = json.load(open(REPO / "data" / "pitcher-ratings.json"))
    by_team = ratings.get("pitchersByTeam", {})
    by_name = ratings.get("pitchers", {})

    id_map = {}
    n_files = 0
    for f in sorted(glob.glob(str(REPO / "data" / "yokoku-*.json"))):
        n_files += 1
        d = json.load(open(f))
        for g in d.get("games", []):
            for side in ("home", "away"):
                pid = g.get(f"{side}SPId")
                name = g.get(f"{side}SP")
                team = g.get(side)
                if not pid or not name:
                    continue
                key, team_split = resolve_key(name, team, by_team, by_name)
                # Latest yokoku wins (names/teams are stable; trades update here).
                id_map[str(pid)] = {
                    "name": name,
                    "team": team,
                    "key": key,
                    "teamSplit": team_split,
                }

    resolved = sum(1 for v in id_map.values() if v["key"])
    unresolved = [v for v in id_map.values() if not v["key"]]
    print(f"[build-pitcher-id-map] scanned {n_files} yokoku files → {len(id_map)} ids, "
          f"{resolved} resolved ({len(unresolved)} unresolved)", file=sys.stderr)
    for v in unresolved:
        print(f"  unresolved: {v['name']!r} ({v['team']}) — no ratings entry", file=sys.stderr)

    if write:
        out = REPO / "data" / "pitcher-id-map.json"
        out.write_text(json.dumps({
            "_doc": "yokoku playerId → pitcher identity + ratings key. `key` indexes "
                    "pitcher-ratings.json pitchersByTeam (preferred) or pitchers. Built "
                    "from data/yokoku-*.json by scripts/build-pitcher-id-map.py.",
            "ids": id_map,
        }, ensure_ascii=False, indent=2))
        print(f"✓ wrote {out.relative_to(REPO)}", file=sys.stderr)
    else:
        print("(dry-run — pass --write to save data/pitcher-id-map.json)", file=sys.stderr)


if __name__ == "__main__":
    main()
