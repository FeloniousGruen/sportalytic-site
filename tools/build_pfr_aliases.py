#!/usr/bin/env python3
"""Work out which PFR-keyed nodes are the same person as a normal-keyed node.

The 2017-18 block of the memberships file came from Pro-Football-Reference
rosters. Players there who had a birth date got the normal uid (lowercased
letters of the name + '|' + birth date); the 424 who did not fell back to
`PFR:<pfr player id>`. That splits a single career across two nodes -- Wyatt
Teller is `PFR:TellWy00` at BUF in 2018 and `wyattteller|1994-11-21` at CLE
from 2019 -- which costs the graph every edge between the two halves.

Name matching would be wrong here: it merges Leon McQuay III (KC 2017) into
Leon McQuay (RB, 1974-76), and it misses Buddy Howell entirely because PFR
files him as Gregory Howell. The PFR id in the uid is an exact identifier, so
this resolves it through nflverse's players table, which carries both `pfr_id`
and `birth_date` -- giving the same uid recipe the rest of the data uses.

Writes tools/pfr_aliases.csv so the build does not need the network. Rerun only
when the memberships file gains new PFR-keyed rows.

Usage: python3 tools/build_pfr_aliases.py --rosters memberships.csv
"""
import argparse, os, re, sys
import pandas as pd

PLAYERS = 'https://github.com/nflverse/nflverse-data/releases/download/players/players.csv'

ap = argparse.ArgumentParser()
ap.add_argument('--rosters', required=True)
ap.add_argument('--players', default=PLAYERS,
                help='override with a local copy of nflverse players.csv')
ap.add_argument('--out', default=os.path.join(os.path.dirname(__file__), 'pfr_aliases.csv'))
a = ap.parse_args()


def mkuid(name, bd):
    if not isinstance(name, str) or not isinstance(bd, str) or len(bd) < 10:
        return None
    return re.sub(r'[^a-z]', '', name.lower()) + '|' + bd[:10]


mem = pd.read_csv(a.rosters)
pfr_uids = sorted({u for u in mem.uid.unique() if isinstance(u, str) and u.startswith('PFR:')})
if not pfr_uids:
    sys.exit('no PFR-keyed uids in ' + a.rosters)

pl = pd.read_csv(a.players, low_memory=False)
byid = {}
for pid, dn, bd in zip(pl.pfr_id, pl.display_name, pl.birth_date):
    if isinstance(pid, str):
        u = mkuid(dn, bd)
        if u:
            byid.setdefault(pid, (u, dn))

rows, unresolved = [], []
for u in pfr_uids:
    hit = byid.get(u[4:])
    if hit is None:
        unresolved.append(u)
        continue
    rows.append({'pfr_uid': u, 'uid': hit[0], 'name': hit[1]})

out = pd.DataFrame(rows).sort_values('pfr_uid')
out.to_csv(a.out, index=False)

known = set(mem.uid)
absorbed = sum(1 for r in rows if r['uid'] in known)
print(f'{len(pfr_uids)} PFR-keyed nodes')
print(f'  resolved   {len(rows)}  ->  {absorbed} merge into an existing node, '
      f'{len(rows) - absorbed} are renames only')
print(f'  unresolved {len(unresolved)}: {unresolved}')
print(f'wrote {a.out}')
