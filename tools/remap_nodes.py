#!/usr/bin/env python3
"""Move the portraits when a rebuild renumbers the nodes.

Portrait files are named by node index, not by name, because the page needs a
yes/no flag per player rather than a filename table -- see build_network_data.py
for why. The cost of that is this script: drop or add a single player and every
index after them shifts by one, so every file after them is now filed against
somebody else.

The join is the uid, which is stable across rebuilds. Both node->uid maps come
out of the build's own fame CSV, so take a copy of it BEFORE rebuilding:

    cp tools/football_fame.csv /tmp/fame_before.csv
    python3 tools/build_football_data.py
    python3 tools/remap_nodes.py --before /tmp/fame_before.csv \\
            --after tools/football_fame.csv --faces assets/foot/faces \\
            --manifest tools/football_commons_manifest.json

Renaming goes via a scratch directory. In place, a chain like 5->4, 6->5 either
overwrites a file that has not moved yet or, worse, half-succeeds.
"""
import argparse, json, os, shutil, sys
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument('--before', required=True, help='node->uid map from before the rebuild')
ap.add_argument('--after', required=True, help='node->uid map from after it')
ap.add_argument('--faces', required=True)
ap.add_argument('--manifest', help='also rewrite the node ids in this manifest')
ap.add_argument('--dry-run', action='store_true')
a = ap.parse_args()

before = pd.read_csv(a.before)
after = pd.read_csv(a.after)
new = dict(zip(after.uid, after.node))            # uid -> new index
# The whole old->new map, not just the nodes that happen to own a file. A
# manifest entry resolved but not yet fetched carries an index too, and leaving
# that stale would file the next fetch against the wrong player.
uid_of_old = dict(zip(before.node, before.uid))
ALL = {int(n): int(new[u]) for n, u in uid_of_old.items() if u in new}
GONE = {int(n) for n, u in uid_of_old.items() if u not in new}
print(f'{len(ALL)} nodes carried over, {len(GONE)} dropped by the rebuild')

moves, orphans = {}, []
for fn in os.listdir(a.faces):
    if not fn.endswith('.webp'):
        continue
    try:
        i = int(fn[:-5])
    except ValueError:
        continue
    if i in ALL:
        moves[i] = ALL[i]
    elif i in GONE:
        orphans.append((fn, f'{uid_of_old[i]} is no longer in the data'))
    else:
        orphans.append((fn, 'no uid had this index before the rebuild'))

changed = {k: v for k, v in moves.items() if k != v}
print(f'{len(moves)} portraits, {len(changed)} of them move, {len(orphans)} orphaned')
for fn, why in orphans:
    print(f'  orphan {fn}: {why}')
if a.dry_run:
    sys.exit(0)

tmp = os.path.join(a.faces, '_remap')
os.makedirs(tmp, exist_ok=True)
for oldi, newi in moves.items():
    shutil.move(os.path.join(a.faces, f'{oldi}.webp'), os.path.join(tmp, f'{newi}.webp'))
for fn, _ in orphans:
    os.remove(os.path.join(a.faces, fn))
for fn in os.listdir(tmp):
    shutil.move(os.path.join(tmp, fn), os.path.join(a.faces, fn))
os.rmdir(tmp)
print(f'moved {len(changed)}, deleted {len(orphans)}')

if a.manifest:
    man = json.load(open(a.manifest))
    hit = 0
    dropped = 0
    for r in man:
        n = r.get('node')
        if n is None:
            continue
        if n in ALL:
            if ALL[n] != n:
                r['node'] = ALL[n]
                hit += 1
        else:
            # the player is gone from the data entirely
            r.pop('node', None); r.pop('url', None); r.pop('done', None)
            r['skip'] = 'no longer in the data'
            dropped += 1
    json.dump(man, open(a.manifest, 'w'), indent=1)
    print(f'{a.manifest}: {hit} node ids rewritten, {dropped} entries dropped')
