#!/usr/bin/env python3
"""Append a season's rosters from nflverse to the memberships file.

The existing memberships blend three sources (PFR/FootballDB game logs, nflverse
season rosters, nflverse weekly rosters). This adds the nflverse season roster
for a given year in the same shape, keyed by the same uid recipe
(lowercased letters of the full name + '|' + birth date), which was validated
against 2025: 1,467 exact (uid, team, season) matches.

Note what a roster row means. PFR rows carry games-played evidence; a roster row
only says the player was on the squad. For a season not yet played that is the
only evidence available, and it is marked as such in the `evidence` column.

Usage: python3 tools/fetch_season.py --season 2026 --out merged.csv
"""
import argparse, re, sys
import pandas as pd

URL = 'https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{}.csv'

ap = argparse.ArgumentParser()
ap.add_argument('--season', type=int, required=True)
ap.add_argument('--base', default='/Users/agruen/Downloads/travis_kelce_team_memberships.csv')
ap.add_argument('--out', required=True)
ap.add_argument('--status', default='ACT')
a = ap.parse_args()


def mkuid(name, bd):
    if not isinstance(name, str) or not isinstance(bd, str) or len(bd) < 10:
        return None
    return re.sub(r'[^a-z]', '', name.lower()) + '|' + bd[:10]


base = pd.read_csv(a.base)
if (base.season == a.season).any():
    sys.exit(f'{a.season} already present in {a.base} ({(base.season==a.season).sum()} rows)')

r = pd.read_csv(URL.format(a.season), low_memory=False)
r = r[r.status == a.status] if 'status' in r.columns else r
r['uid'] = [mkuid(n, b) for n, b in zip(r.full_name, r.birth_date)]
dropped = int(r.uid.isna().sum())
r = r[r.uid.notna()].copy()

add = pd.DataFrame({
    'uid': r.uid,
    'full_name': r.full_name,
    'position': r.position if 'position' in r.columns else '',
    'team': r.team,
    'season': a.season,
    'source': f'nflverse season roster ({a.status})',
    'evidence': a.status,
    'headshot_url': r.headshot_url if 'headshot_url' in r.columns else None,
})
add = add.drop_duplicates(subset=['uid', 'team', 'season'])

known = set(base.uid)
new_players = sorted(set(add.uid) - known)
out = pd.concat([base, add], ignore_index=True)
out.to_csv(a.out, index=False)

print(f'{a.season}: {len(add)} roster rows over {add.team.nunique()} teams')
print(f'  players already in the network : {len(set(add.uid) & known)}')
print(f'  new players added              : {len(new_players)}')
print(f'  rows dropped for missing birth date: {dropped}')
print(f'  memberships {len(base)} -> {len(out)}   written to {a.out}')
