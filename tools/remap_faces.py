#!/usr/bin/env python3
"""Rename the portrait files after the player list changes.

Portraits are named by node index, which is a player's rank in the sorted uid
list -- so adding a season, or merging two split careers, renumbers the lot.
faces/owners.csv records the uid behind each file, which is enough to rename
them in place instead of downloading 12 MB again.

Run this after build_network_data.py and before fetch_faces.py.

Usage: python3 tools/remap_faces.py --rosters <memberships.csv>
"""
import argparse, os, shutil, sys
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument('--rosters', required=True)
ap.add_argument('--out', default='assets/net/faces')
ap.add_argument('--dry-run', action='store_true')
a = ap.parse_args()

man = os.path.join(a.out, 'owners.csv')
if not os.path.exists(man):
    sys.exit(f'no {man} -- cannot tell which player each file belongs to')
own = pd.read_csv(man)

mem = pd.read_csv(a.rosters)
alias_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pfr_aliases.csv')
if os.path.exists(alias_path):
    af = pd.read_csv(alias_path)
    same = dict(zip(af.pfr_uid, af.uid))
    mem['uid'] = mem.uid.map(lambda u: same.get(u, u))
else:
    same = {}

uids = sorted(mem.groupby('uid').groups.keys())
idx = {u: i for i, u in enumerate(uids)}

moves, gone, merged = {}, [], []
for i, u in zip(own['index'], own.uid):
    u = same.get(u, u)
    j = idx.get(u)
    if j is None:
        gone.append(u)
        continue
    if j in moves:                     # two files now describe one player
        merged.append(u)
        continue
    moves[j] = (int(i), u)

unchanged = sum(1 for j, (i, _) in moves.items() if i == j)
print(f'{len(own)} portraits: {len(moves)} keep a home ({unchanged} at the same index), '
      f'{len(gone)} players no longer exist, {len(merged)} duplicate after merging')
if a.dry_run:
    sys.exit(0)

# Two passes through a staging directory: source and destination indices overlap,
# so renaming in place would clobber files that have not been moved yet.
tmp = os.path.join(a.out, '_remap')
os.makedirs(tmp, exist_ok=True)
for j, (i, _) in moves.items():
    shutil.move(os.path.join(a.out, f'{i}.webp'), os.path.join(tmp, f'{j}.webp'))
for f in os.listdir(a.out):
    if f.endswith('.webp'):
        os.remove(os.path.join(a.out, f))
for f in os.listdir(tmp):
    shutil.move(os.path.join(tmp, f), os.path.join(a.out, f))
os.rmdir(tmp)

with open(man, 'w') as f:
    f.write('index,uid\n')
    for j in sorted(moves):
        f.write(f'{j},{moves[j][1]}\n')
print(f'renamed {len(moves)} files and rewrote {man}')
