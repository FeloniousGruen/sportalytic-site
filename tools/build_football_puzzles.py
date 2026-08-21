#!/usr/bin/env python3
"""Pick the pairs of footballers the games are played on.

The NFL version of this (tools/build_puzzles.py) uses "has a portrait" as its
proxy for fame, because that was the only signal in the nflverse data. The
football source is better: it carries **career top-flight league appearances**
for 16,439 of the 18,761 players, from 1888 onward. That is a far more honest
measure -- it does not smuggle in the present day the way a photo does, and it
reaches the pre-war game, where nobody has a headshot but Dixie Dean still
played 399 times.

Two tiers, and every endpoint must be in one of them:

    recent   still playing within the last fifteen years, with a real career
             behind them -- the players a reader has actually watched
    great    a top-flight career long enough that anyone following the game at
             the time knew the name, plus a hand-list for the short and
             brilliant, who the appearance count cannot see (Cantona played
             159 league games and is not a lesser-known player than the 400-cap
             full back the threshold lets in instead)

Unlike the NFL, this graph has real depth. There, 78% of well-known pairs sit
exactly 2 apart and no pair of players both active since 1996 is ever 4 apart,
which is why that round has to stop at par 4. English football spreads properly
-- a top flight of twenty clubs over 138 seasons churns far less -- so the same
sample of household names gives 2, 3, 4, 5 and 6 in useful numbers, and the
round can climb the way a round of golf should. The measured spread is printed
at the end of every run; re-read it before changing the pars.

Usage: python3 tools/build_football_puzzles.py [--per-bucket 400]
"""
import argparse, gzip, json, os, struct, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(HERE, 'assets', 'foot')

ap = argparse.ArgumentParser()
ap.add_argument('--per-bucket', type=int, default=400)
ap.add_argument('--recent-from', type=int, default=2011,
                help='a "recent" player must still have been playing this season')
ap.add_argument('--recent-apps', type=int, default=80)
ap.add_argument('--great-apps', type=int, default=260)
ap.add_argument('--icon-apps', type=int, default=450,
                help='the far end of a par 5 or 6 has to be a name people know, '
                     'and 260 appearances is not that -- it admits a great many '
                     'sound professionals nobody outside their own club recalls')
ap.add_argument('--per-source', type=int, default=6,
                help='cap pairs taken from one player per bucket, so the pool '
                     'is not five variations on the same career')
ap.add_argument('--seed', type=int, default=20260821)
ap.add_argument('--pl-from', type=int, default=1992,
                help='the Premier League pools are built over these seasons '
                     'alone, because the page now defaults to them: a puzzle '
                     'whose answer runs through a 1975 dressing room has no '
                     'route at all once the graph is cut to 1992 on')
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
first = np.frombuffer(buf, np.int16, P, o).copy(); o += P * 2
last = np.frombuffer(buf, np.int16, P, o).copy(); o += P * 2
o += P                                        # positions
ts_team = np.frombuffer(buf, np.uint16, T, o).copy(); o += T * 2
ts_season = np.frombuffer(buf, np.int16, T, o).copy()

names = gzip.open(os.path.join(NET, 'names.txt.gz'), 'rb').read().decode().split('\n')

fame = pd.read_csv(os.path.join(HERE, 'tools', 'football_fame.csv'))
apps = np.zeros(P, np.int32)
apps[fame.node.values] = fame.apps.values

# The short and brilliant. An appearance count cannot see these -- each played
# too few league games to clear the threshold and every one of them is better
# known than the journeyman it lets in instead. Kept deliberately short and
# only ever ADDED to a tier, never used to exclude anyone.
GREAT_ALSO = [
    'Eric Cantona', 'Gianfranco Zola', 'Dennis Bergkamp', 'Ruud van Nistelrooy',
    'Jürgen Klinsmann', 'Gary Lineker', 'Peter Schmeichel', 'Roy Keane',
    'Paul Gascoigne', 'Chris Waddle', 'Duncan Edwards', 'Dixie Dean',
    'Nat Lofthouse', 'Wilf Mannion', 'Len Shackleton', 'Danny Blanchflower',
    'Dave Mackay', 'John Charles', 'Trevor Francis', 'Kenny Dalglish',
    'Graeme Souness', 'Glenn Hoddle', 'Bryan Robson', 'Peter Beardsley',
    'Matt Le Tissier', 'David Ginola', 'Patrick Vieira', 'Didier Drogba',
    'Fernando Torres', 'Carlos Tevez', 'Sergio Agüero', 'Luis Suárez',
    'Robin van Persie', 'Cristiano Ronaldo', 'David Beckham', 'Michael Owen',
    'Rio Ferdinand', 'Nemanja Vidic', 'Vincent Kompany', 'Yaya Touré',
    'Cesc Fàbregas', 'Luka Modric', 'Gareth Bale', 'Eden Hazard',
    'Riyad Mahrez', 'N’Golo Kanté', 'Son Heung-Min', 'Sadio Mané',
]
by_name = {}
for i, n in enumerate(names):
    by_name.setdefault(n, []).append(i)

extra = np.zeros(P, bool)
found, absent = 0, []
for n in GREAT_ALSO:
    hits = by_name.get(n)
    if not hits:
        absent.append(n); continue
    # a name split into two people by the identity heuristic: take the one with
    # the most appearances, which is the one the reader means
    i = max(hits, key=lambda k: apps[k])
    extra[i] = True; found += 1
if absent:
    print(f'hand-list: {len(absent)} names not in the data: {", ".join(absent)}')

recent = (last >= a.recent_from) & (apps >= a.recent_apps)
great = (apps >= a.great_apps) | extra
# A longer hole needs a MORE famous far end, not a less famous one: the men in
# between are unnameable either way, so the only thing that makes a par 6
# playable rather than absurd is that both ends are people you have heard of.
icon = (apps >= a.icon_apps) | extra
usable = recent | great
pool = np.where(usable)[0]

print(f'{int(recent.sum())} recent (played since {a.recent_from}/'
      f'{str(a.recent_from+1)[2:]}, {a.recent_apps}+ apps), '
      f'{int(great.sum())} greats ({a.great_apps}+ apps or hand-listed, '
      f'{found} of those), {int(icon.sum())} icons ({a.icon_apps}+ apps or '
      f'hand-listed), {len(pool)} usable endpoints')

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


def distances(src, era=None):
    """Player-to-player distances from src. Same rule the page uses: a squad is
    absorbed once and then skipped, so a club-season is never walked twice.

    `era` bars club-seasons outside a season range, exactly as NET.setEra does
    in the browser -- marking them already-seen is the same thing as their not
    existing.
    """
    # in place, not `seen_ts |= ...`: rebinding the name would make it local
    if era is None:
        seen_ts[:] = False
    else:
        np.logical_not(era, out=seen_ts)
    dist = np.full(P, -1, np.int16)
    dist[src] = 0
    frontier = np.array([src], np.int32)
    d = 0
    while frontier.size:
        ts = np.unique(gather(p_ix, p_ip[frontier], p_ip[frontier + 1]))
        ts = ts[~seen_ts[ts]]
        if ts.size == 0:
            break
        seen_ts[ts] = True
        nxt = np.unique(gather(t_ix, t_ip[ts], t_ip[ts + 1]))
        nxt = nxt[dist[nxt] < 0]
        if nxt.size == 0:
            break
        d += 1
        dist[nxt] = d
        frontier = nxt
    return dist


# r* : both ends someone playing now. Beyond 3 these barely exist -- a first
#      run of this found 24 pairs of modern players 4 apart in the whole record
#      -- so the long holes have to reach back, exactly as the NFL ones do.
# g* : one all-time great and one current player. This is the era gap, and it
#      is what makes a par 4 hard without making it unnameable: both ENDS are
#      famous even though the men between them are not.
# i* : the same, with the far end drawn from the much stricter icon tier,
#      because at five and six links the only thing holding the puzzle up is
#      recognising who you are being asked to reach.
BUCKETS = [('r2', 2, 'recent'), ('r3', 3, 'recent'),
           ('g3', 3, 'great'), ('g4', 4, 'great'),
           ('i5', 5, 'icon'), ('i6', 6, 'icon')]
FAR = {'great': great, 'icon': icon}

# ------------------------------------------------------- Premier League ----
# The page defaults to the Premier League, so the default games have to be
# playable there. These pools are built over 1992 on ALONE -- an all-time
# puzzle whose answer runs through a 1975 dressing room simply has no route
# once the graph is cut, and the round would hand you an unsolvable hole.
#
# The shape is quite different. Thirty-odd seasons of twenty clubs is small and
# tightly connected: nobody is more than four from anyone, so there is no par 5
# or 6 to be had and the far tiers collapse into one. p* pools, one endpoint
# tier, distances 2 to 4.
pl_era = ts_season >= a.pl_from
in_pl = np.zeros(P, bool)
for i in range(P):
    for k in range(p_ip[i], p_ip[i + 1]):
        if pl_era[p_ix[k]]:
            in_pl[i] = True
            break
pl_known = in_pl & (recent | great | icon)
print(f'{int(in_pl.sum())} players appear in {a.pl_from}/'
      f'{str(a.pl_from+1)[2:]} or later, {int(pl_known.sum())} of them notable')
PL_BUCKETS = [('p2', 2), ('p3', 3), ('p4', 4)]
buckets = {k: [] for k, _, _ in BUCKETS}
rng = np.random.default_rng(a.seed)
sources = pool.copy()
rng.shuffle(sources)

spread = {}          # what the distance distribution across the pool looks like
for n, s_ in enumerate(sources, 1):
    if all(len(buckets[k]) >= a.per_bucket for k, _, _ in BUCKETS):
        print(f'  every bucket full after {n - 1} sources')
        break
    dist = distances(int(s_))
    hit = dist[pool]
    for v in hit[hit >= 0]:
        spread[int(v)] = spread.get(int(v), 0) + 1
    for key, d, tier in BUCKETS:
        if len(buckets[key]) >= a.per_bucket:
            continue
        if tier == 'recent':
            if not recent[s_]:
                continue
            hits = np.where((dist == d) & recent)[0]
            hits = hits[hits > int(s_)]              # each unordered pair once
        else:
            # exactly one end from the far tier, the other someone playing now
            far = FAR[tier]
            if far[s_] and not recent[s_]:
                hits = np.where((dist == d) & recent)[0]
            elif recent[s_]:
                hits = np.where((dist == d) & far & ~recent)[0]
            else:
                continue
            hits = hits[hits != int(s_)]
        if hits.size > a.per_source:
            hits = rng.choice(hits, a.per_source, replace=False)
        for t in hits:
            buckets[key].append([int(s_), int(t)])
            if len(buckets[key]) >= a.per_bucket:
                break
    if n % 200 == 0:
        print('  ' + f'{n} sources: ' +
              ' '.join(f'{k}={len(v)}' for k, v in buckets.items()), flush=True)

# ---- and again, restricted to the Premier League ----
pl_pool = np.where(pl_known)[0]
rng.shuffle(pl_pool)
for key, _ in PL_BUCKETS:
    buckets[key] = []
for n, s_ in enumerate(pl_pool, 1):
    if all(len(buckets[k]) >= a.per_bucket for k, _ in PL_BUCKETS):
        print(f'  every Premier League bucket full after {n - 1} sources')
        break
    dist = distances(int(s_), pl_era)
    for key, d in PL_BUCKETS:
        if len(buckets[key]) >= a.per_bucket:
            continue
        hits = np.where((dist == d) & pl_known)[0]
        hits = hits[hits > int(s_)]
        if hits.size > a.per_source:
            hits = rng.choice(hits, a.per_source, replace=False)
        for t in hits:
            buckets[key].append([int(s_), int(t)])
            if len(buckets[key]) >= a.per_bucket:
                break

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

tot = sum(spread.values()) or 1
print('\ndistance spread across the notable pool (this is what sets the pars):')
for d in sorted(spread):
    print(f'  {d}: {spread[d]:8d}  {100*spread[d]/tot:5.1f}%')

sl = lambda y: f'{y}/{str((y+1) % 100).zfill(2)}'
for key, pairs in buckets.items():
    for i, j in pairs[:2]:
        print(f'  {key}  {names[i]} ({sl(first[i])}-{sl(last[i])})  ->  '
              f'{names[j]} ({sl(first[j])}-{sl(last[j])})')
