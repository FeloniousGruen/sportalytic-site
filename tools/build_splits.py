#!/usr/bin/env python3
"""Turn the audited namesake findings into a splits file the build can apply.

Identity before 1992 is name-based, and the upstream heuristic only separates
namesakes whose careers are more than ten seasons apart. Closer than that and
two men become one record who bridges eras he never played in -- which corrupts
every route that runs through him. An audit of the 64 highest-risk records
found 28 such merges.

This reads the audit verdicts, resolves each person's club-seasons against what
the graph actually holds, and writes tools/football_splits.json.

The one rule that matters: a split is only emitted when every club-season on
the node is claimed exactly once. Not claimed at all, or claimed twice, and the
node is REJECTED rather than half-split. A wrong merge invents a person; a
wrong split invents one too, and silently dropping a club-season would erase a
career. Rejected nodes are printed so they can be settled by hand.

Usage: python3 tools/build_splits.py --verdicts <dir> [--out tools/football_splits.json]
"""
import argparse, glob, gzip, json, os, re, struct
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ap = argparse.ArgumentParser()
ap.add_argument('--verdicts', required=True, help='directory of verdict*.json')
ap.add_argument('--data', default=os.path.join(HERE, 'assets', 'foot'))
ap.add_argument('--out', default=os.path.join(HERE, 'tools', 'football_splits.json'))
ap.add_argument('--before', default='/tmp/fame_before.csv',
                help='node->uid map from the graph the audit was run against')
ap.add_argument('--after', default=os.path.join(HERE, 'tools', 'football_fame.csv'))
ap.add_argument('--accept', default='high,medium',
                help='confidence levels to act on')
a = ap.parse_args()

# ------------------------------------------------------------ the graph ----
buf = gzip.open(os.path.join(a.data, 'graph.bin.gz'), 'rb').read()
assert buf[:8] == b'SPNET001'
P, T = struct.unpack_from('<ii', buf, 8)
o = 16


def i32(n):
    global o
    arr = np.frombuffer(buf, np.int32, n, o); o += n * 4; return arr


p_ip = i32(P + 1); p_ix = i32(int(p_ip[P]))
t_ip = i32(T + 1); t_ix = i32(int(t_ip[T]))
o += P * 2 * 2 + P
ts_team = np.frombuffer(buf, np.uint16, T, o).copy(); o += T * 2
ts_season = np.frombuffer(buf, np.int16, T, o).copy()
names = gzip.open(os.path.join(a.data, 'names.txt.gz'), 'rb').read().decode().split('\n')
tab = json.load(open(os.path.join(a.data, 'tables.json')))
teams, meta = tab['teams'], tab['teamMeta']
CODE_OF = {m['name'].lower(): c for c, m in meta.items()}
# what a club is called in prose, where that differs from the dataset's name
ALIAS = {
    'arsenal (woolwich arsenal)': 'arsenal', 'woolwich arsenal': 'arsenal',
    'spurs': 'tottenham hotspur', 'wolves': 'wolverhampton wanderers',
    'west brom': 'west bromwich albion', 'newcastle': 'newcastle united',
    'man city': 'manchester city', 'man utd': 'manchester united',
    'manchester utd': 'manchester united', 'qpr': 'queens park rangers',
    'bournemouth': 'afc bournemouth', 'brighton': 'brighton & hove albion',
    'sheffield weds': 'sheffield wednesday', 'forest': 'nottingham forest',
}


def club_code(txt):
    """Resolve a club from prose, longest sensible reading first.

    The capture can run wider than the club -- "Arsenal (Woolwich Arsenal)"
    collapses to "Arsenal Woolwich Arsenal" once the brackets go -- so fall
    back to progressively shorter trailing phrases until one is a club.
    """
    words = re.sub(r'\s+', ' ', txt.strip().lower().rstrip('.,;')).split()
    for start in range(len(words)):
        k = ' '.join(words[start:])
        k = ALIAS.get(k, k)
        if k in CODE_OF:
            return CODE_OF[k]
    return None


def node_seasons(i):
    return sorted({(teams[ts_team[p_ix[j]]], int(ts_season[p_ix[j]]))
                   for j in range(p_ip[i], p_ip[i + 1])})


# "Aston Villa 1914/15-1928/29", "Chelsea 1912/13", "Arsenal 1921/22-1922/23",
# and the two shapes that a first pass missed: a parenthetical alias --
# "Arsenal (Woolwich Arsenal) 1905/06" -- and a continuation that inherits the
# club it follows, as in "Bolton Wanderers 1937/38-1938/39 and 1946/47".
RANGE = re.compile(r'(?:([A-Za-z][A-Za-z&.\' ]{2,}?)\s+)?'
                   r'(\d{4})/\d{2}(?:\s*(?:[-–]|and|to)\s*(\d{4})/\d{2})?')


def parse_seasons(text, have):
    """Club-seasons named in a sentence, restricted to ones the node holds."""
    text = re.sub(r'[()]', ' ', text)
    mine, current = set(), None
    for m in RANGE.finditer(text):
        if m.group(1):
            code = club_code(m.group(1))
            if code:
                current = code
        if not current:
            continue
        lo = int(m.group(2)); hi = int(m.group(3) or lo)
        for c, y in have:
            if c == current and lo <= y <= hi:
                mine.add((c, y))
    return mine

verdicts = []
for f in sorted(glob.glob(os.path.join(a.verdicts, 'verdict*.json'))):
    verdicts += json.load(open(f))

# old node index -> current one, joined on the uid
import pandas as pd
before = pd.read_csv(a.before)
after = pd.read_csv(a.after)
new_of = dict(zip(after.uid, after.node))
UID_OF = dict(zip(after.node, after.uid))          # current node -> uid
REMAP = {int(n): int(new_of[u]) for n, u in zip(before.node, before.uid) if u in new_of}

accept = set(a.accept.split(','))
splits, rejected, skipped = {}, [], []

for v in verdicts:
    if v.get('verdict') != 'SPLIT':
        continue
    if v.get('confidence') not in accept:
        skipped.append((v['name'], f"confidence {v.get('confidence')}"))
        continue
    # The audit's node index is from the graph as it stood then, and removing
    # the own-goal placeholders renumbered everything after them. Follow the
    # uid, which is stable. Matching on the name instead does not work: the
    # upstream splitter has ALREADY cut several of these names into two or
    # three nodes, so a name lookup is ambiguous exactly where it matters.
    node = REMAP.get(v['node'])
    if node is None:
        rejected.append((v['name'], f'node {v["node"]} is no longer in the data'))
        continue
    if names[node] != v['name']:
        rejected.append((v['name'], f'node {node} is now {names[node]!r}; '
                                    f'the audit and the data disagree'))
        continue
    have = set(node_seasons(node))
    claimed, people, bad = {}, [], None
    for p in v.get('people', []):
        mine = parse_seasons(p.get('clubs_seasons', ''), have)
        for cs in mine:
            if cs in claimed:
                bad = f'{cs} claimed by two people'
            claimed[cs] = True
        people.append({'who': p.get('who', ''), 'seasons': sorted(mine)})
    missing = have - set(claimed)
    if bad:
        rejected.append((v['name'], bad))
    elif missing:
        rejected.append((v['name'], 'unassigned: ' +
                         ', '.join(f'{c} {y}' for c, y in sorted(missing))))
    elif sum(1 for p in people if p['seasons']) < 2:
        rejected.append((v['name'], 'the split leaves only one person with seasons'))
    else:
        # keyed by uid, not node index: the index moves whenever anything is
        # added or removed, and this file has to outlive that
        splits[UID_OF[node]] = {
            'node_when_audited': v['node'],
            'name': v['name'], 'confidence': v['confidence'],
            'evidence': v.get('evidence', '')[:400],
            'people': [p for p in people if p['seasons']],
        }

json.dump(splits, open(a.out, 'w'), indent=1)
print(f'{len(splits)} splits written to {a.out}')
for n, r in rejected:
    print(f'  REJECTED  {n}: {r}')
for n, r in skipped:
    print(f'  skipped   {n}: {r}')
print(f'\n{len(splits)} applied, {len(rejected)} rejected, {len(skipped)} skipped')
for k, s in list(splits.items())[:4]:
    print(f"  {s['name']}:")
    for p in s['people']:
        print(f"     {len(p['seasons'])} club-seasons  {p['who'][:60]}")
