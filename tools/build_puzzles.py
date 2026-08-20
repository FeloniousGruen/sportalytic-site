#!/usr/bin/env python3
"""Pick the pairs of players the games are played on.

Finding a pair exactly six links apart needs a full breadth-first pass, so the
browser cannot go looking for one on demand. This does it offline over every
candidate and ships the answers.

What counts as a candidate: a player with a portrait and a career of seven
seasons or more. Both halves of that matter. The portrait is a decent proxy for
"someone has heard of them", and a long career means they turn up in enough
squads to be findable. Endpoints only -- the players who bridge two eras are
almost always journeymen, and there is no way around that.

Worth knowing before tuning this: distance is really an era gap. Two
contemporaries are nearly always 2 apart -- 78% of well-known pairs are -- and
reaching 5 or 6 means crossing fifty or seventy years, which puts the linking
players beyond anyone's recall. That is why the round is 2/3/3/3/4 rather than
2/3/4/5/6, and why these pools are cut by era as well as by distance:

    recent  both players inside the last thirty years, one at a marquee
            position -- the holes most people can actually play
    mid     both debuted within fifty years, which reaches back without
            leaving the game unrecognisable

Usage: python3 tools/build_puzzles.py [--per-bucket 400]
"""
import argparse, gzip, json, os, struct
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(HERE, 'assets', 'net')

ap = argparse.ArgumentParser()
ap.add_argument('--per-bucket', type=int, default=400)
ap.add_argument('--min-seasons', type=int, default=7)
ap.add_argument('--per-source', type=int, default=6,
                help='cap pairs taken from one player per bucket, so the pool '
                     'is not five variations on the same career')
ap.add_argument('--seed', type=int, default=20260820)
a = ap.parse_args()

# ------------------------------------------------------------------ data ----
buf = gzip.open(os.path.join(NET, 'graph.bin.gz'), 'rb').read()
assert buf[:8] == b'SPNET001'
P, T = struct.unpack_from('<ii', buf, 8)
o = 16


def i32(n):
    global o
    arr = np.frombuffer(buf, np.int32, n, o); o += n * 4; return arr


p_ip = i32(P + 1); p_ix = i32(int(p_ip[P]))
t_ip = i32(T + 1); t_ix = i32(int(t_ip[T]))
first = np.frombuffer(buf, np.int16, P, o); o += P * 2
last = np.frombuffer(buf, np.int16, P, o); o += P * 2

names = gzip.open(os.path.join(NET, 'names.txt.gz'), 'rb').read().decode().split('\n')
faces = np.frombuffer(gzip.open(os.path.join(NET, 'faces.bin.gz'), 'rb').read(), np.uint8)

# A portrait and a long career is a poor test of fame on its own -- it returns
# a lot of guards nobody outside their own city could name. Cut it three ways:
# recent enough to have been watched, at a position whose names get said out
# loud, and long enough in the league to have been somewhere.
tables = json.load(open(os.path.join(NET, 'tables.json')))
positions = tables['positions']
pos_i = np.frombuffer(buf, np.uint8, P, o); o += P

STAR = {'QB', 'RB', 'WR', 'TE'}
SKILL = STAR | {'FB', 'K', 'LB', 'MLB', 'OLB', 'ILB',
                'DE', 'DT', 'CB', 'S', 'FS', 'SS', 'DB', 'DL'}

seasons = last - first
ok_pos = np.array([positions[pos_i[i]] in SKILL for i in range(P)])
is_star = np.array([positions[pos_i[i]] in STAR for i in range(P)])
base = (faces > 0) & ok_pos & (seasons >= a.min_seasons - 1)

recent = base & (last >= 2006) & (first >= 1996)   # inside the last thirty
mid = base & (first >= 1976)                       # inside the last fifty
pool = np.where(mid)[0]

print(f'{len(pool)} endpoints within fifty years; '
      f'{int(recent.sum())} inside thirty, {int((recent & is_star).sum())} of those '
      f'at a marquee position')

# ------------------------------------------------------------- traversal ----

def gather(arr, starts, ends):
    """Concatenate arr[starts[k]:ends[k]] for every k, without a Python loop."""
    lens = (ends - starts).astype(np.int64)
    total = int(lens.sum())
    if total == 0:
        return np.empty(0, arr.dtype)
    offs = np.concatenate(([0], np.cumsum(lens)[:-1]))
    idx = np.repeat(starts.astype(np.int64) - offs, lens) + np.arange(total)
    return arr[idx]


seen_ts = np.zeros(T, bool)


def distances(src):
    """Player-to-player distances from src, level by level.

    Same rule the page uses: a squad is absorbed once and then skipped, so a
    team-season is never walked twice. Done with whole-array steps rather than
    a loop over nodes, which is the difference between minutes and hours.
    """
    seen_ts[:] = False
    dist = np.full(P, -1, np.int16)
    dist[src] = 0
    frontier = np.array([src], np.int32)
    d = 0
    while frontier.size:
        ts = gather(p_ix, p_ip[frontier], p_ip[frontier + 1])
        ts = np.unique(ts)
        ts = ts[~seen_ts[ts]]
        if ts.size == 0:
            break
        seen_ts[ts] = True
        nxt = gather(t_ix, t_ip[ts], t_ip[ts + 1])
        nxt = np.unique(nxt)
        nxt = nxt[dist[nxt] < 0]
        if nxt.size == 0:
            break
        d += 1
        dist[nxt] = d
        frontier = nxt
    return dist



# No r4: two players who were both active since 1996 are essentially never
# four apart -- the modern game is too tightly connected for that. The par-4
# hole therefore comes from the fifty-year tier, which is still recognisable
# (Tony Dorsett, Ozzie Newsome) without being unplayable.
BUCKETS = [('r2', 2, 'recent'), ('r3', 3, 'recent'),
           ('m3', 3, 'mid'), ('m4', 4, 'mid')]
buckets = {k: [] for k, _, _ in BUCKETS}
rng = np.random.default_rng(a.seed)
sources = pool.copy()
rng.shuffle(sources)

for n, s_ in enumerate(sources, 1):
    if all(len(buckets[k]) >= a.per_bucket for k, _, _ in BUCKETS):
        print(f'  every bucket full after {n - 1} sources')
        break
    dist = distances(int(s_))
    for key, d, tier in BUCKETS:
        if len(buckets[key]) >= a.per_bucket:
            continue
        mask = recent if tier == 'recent' else mid
        if not mask[s_]:
            continue
        hits = np.where((dist == d) & mask)[0]
        hits = hits[hits > int(s_)]                  # each unordered pair once
        if tier == 'recent' and not is_star[s_]:
            hits = hits[is_star[hits]]               # one marquee name at least
        if hits.size > a.per_source:
            hits = rng.choice(hits, a.per_source, replace=False)
        for t in hits:
            buckets[key].append([int(s_), int(t)])
            if len(buckets[key]) >= a.per_bucket:
                break
    if n % 200 == 0:
        print('  ' + f'{n} sources: ' +
              ' '.join(f'{k}={len(v)}' for k, v in buckets.items()), flush=True)

out = {'players': {}, 'buckets': {}}
for key, pairs in buckets.items():
    rng.shuffle(pairs)
    out['buckets'][key] = pairs
    for pr in pairs:
        for i in pr:
            out['players'][str(i)] = names[i]

path = os.path.join(NET, 'puzzles.json')
json.dump(out, open(path, 'w'), separators=(',', ':'))
print('\n' + ' '.join(f'{k}={len(v)}' for k, v in buckets.items()))
print(f'{path}  {os.path.getsize(path)/1024:.1f} KB')
for key, pairs in buckets.items():
    for i, j in pairs[:2]:
        print(f'  {key}  {names[i]} ({first[i]}-{last[i]})  ->  '
              f'{names[j]} ({first[j]}-{last[j]})')
