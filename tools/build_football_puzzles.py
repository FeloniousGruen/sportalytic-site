#!/usr/bin/env python3
"""Pick the pairs of footballers the games are played on.

Fame is measured, not proxied. The first version of this ranked players by
career top-flight appearances, because that is the only fame-ish number the
source carries, and it does not work: Steve Potts made 297 appearances for West
Ham and nobody outside the Boleyn could name him, Bellegarde made 83 and is a
Premier League regular, Cantona made 159. Appearances measure a career, not a
reputation, and a round built on them hands you two men you have never heard of
and calls it a puzzle.

tools/football_views.json holds Wikipedia traffic for every plausible candidate
(see fetch_fame_views.py), which is the reputation directly: how many people
went looking for this person. What it cannot be is compared across eras -- the
median player still active reads 38,570 views over sixty days, the median
player who finished before 1965 reads 219. So fame is a **rank within an era
band**, never an absolute, and the bar is set on that rank.

Three rules, all of them the user's:

  1. at least nine of the ten names in a round are people you have heard of.
     Delivered as ten of ten: both ends of every pair clear the bar for their
     own era.
  2. every pair carries someone from the last ten years, so no hole is two
     names from before you were watching.
  3. expert runs over the whole record, 1888 on, with the bar rising the
     further back an endpoint sits -- top half of the modern game, top few per
     cent of the pre-war one. A 1930s name has to be Dixie Dean to be worth
     asking about; a 2024 name only has to be a starter.

Usage: python3 tools/build_football_puzzles.py [--per-bucket 400]
"""
import argparse, gzip, json, os, struct, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(HERE, 'assets', 'foot')

ap = argparse.ArgumentParser()
ap.add_argument('--per-bucket', type=int, default=400)
ap.add_argument('--recent-from', type=int, default=2016,
                help='"the last ten years": one end of every pair reaches it')
ap.add_argument('--floor', type=int, default=300,
                help='absolute view floor. A rank alone would promote whoever '
                     'happens to top a thin era band, however little anyone '
                     'reads about them')
ap.add_argument('--per-source', type=int, default=6,
                help='cap pairs taken from one player per bucket, so the pool '
                     'is not five variations on the same career')
ap.add_argument('--seed', type=int, default=20260823)
ap.add_argument('--pl-from', type=int, default=1992,
                help='the Premier League pools are built over these seasons '
                     'alone, because the page defaults to them: a puzzle whose '
                     'answer runs through a 1975 dressing room has no route at '
                     'all once the graph is cut to 1992 on')
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

# ------------------------------------------------------------------ fame ----
views = np.zeros(P, np.int64)
looked = np.zeros(P, bool)                    # we have a reading, even if zero
raw = json.load(open(os.path.join(HERE, 'tools', 'football_views.json')))
for rec in raw.values():
    n = rec['node']
    if 0 <= n < P:
        looked[n] = True
        views[n] = rec['views']
print(f'{int(looked.sum())} players with a traffic reading, '
      f'{int((views > 0).sum())} of them non-zero')

# Era bands. Not decades: the shape of the game changes at the Premier League
# and again at the war, and a band that straddles either mixes two different
# levels of how-well-remembered into one ranking.
BANDS = [(2016, 3000, 'still playing'),
         (2005, 2015, 'the 2000s'),
         (1993, 2004, 'the early Premier League'),
         (1980, 1992, 'the eighties'),
         (1966, 1979, 'after the World Cup'),
         (1946, 1965, 'post-war'),
         (1888, 1945, 'before the war')]
# How well known you have to be FOR YOUR OWN ERA to be worth asking about, as
# a rank within the band. Rising backwards is the whole of rule 3: the further
# back a name sits the fewer people carry it, so the bar has to climb or the
# older end of a puzzle is always a stranger.
KNOWN_BAR = np.array([0.50, 0.55, 0.62, 0.70, 0.78, 0.86, 0.93])
# ...and the far end of a five- or six-link hole has to be better known still,
# because at that distance the men in between are unnameable either way and
# recognising who you are being asked to reach is the only thing holding the
# puzzle up.
ICON_BAR = np.minimum(0.985, KNOWN_BAR + 0.06)

band = np.full(P, -1, np.int8)
for k, (lo, hi, _) in enumerate(BANDS):
    band[(last >= lo) & (last <= hi)] = k

pct = np.zeros(P)
for k in range(len(BANDS)):
    idx = np.where((band == k) & looked)[0]
    if idx.size < 2:
        continue
    order = np.argsort(views[idx], kind='stable')
    r = np.empty(idx.size)
    r[order] = np.arange(idx.size)
    pct[idx] = r / (idx.size - 1)

by_name = {}
for i, n in enumerate(names):
    by_name.setdefault(n, []).append(i)

# The short and brilliant, and the handful whose article title is not the name
# the source holds (Kanu is "Nwankwo Kanu", so the resolver never found him).
# Only ever ADDED to a tier, never used to exclude anyone.
GREAT_ALSO = [
    'Eric Cantona', 'Gianfranco Zola', 'Dennis Bergkamp', 'Ruud van Nistelrooij',
    'Jürgen Klinsmann', 'Gary Lineker', 'Peter Schmeichel', 'Roy Keane',
    'Paul Gascoigne', 'Chris Waddle', 'Duncan Edwards', 'Dixie Dean',
    'Nat Lofthouse', 'Wilf Mannion', 'Len Shackleton', 'Danny Blanchflower',
    'Dave MacKay', 'John Charles', 'Trevor Francis', 'Kenny Dalglish',
    'Graeme Souness', 'Glenn Hoddle', 'Bryan Robson', 'Peter Beardsley',
    'Matt Le Tissier', 'David Ginola', 'Patrick Vieira', 'Didier Drogba',
    'Fernando Torres', 'Carlos Tevez', 'Sergio Agüero', 'Luis Suárez',
    'Robin van Persie', 'Cristiano Ronaldo', 'David Beckham', 'Michael Owen',
    'Rio Ferdinand', 'Nemanja Vidic', 'Vincent Kompany', 'Yaya Touré',
    'Cesc Fàbregas', 'Luka Modric', 'Gareth Bale', 'Eden Hazard',
    'Riyad Mahrez', "N'Golo Kanté", 'Son Heung-Min', 'Sadio Mané',
    'Kanu', 'Petr Cech', 'Robert Lee', 'Tom Finney', 'Stanley Matthews',
    'Billy Wright', 'Bobby Moore', 'Bobby Charlton', 'Jimmy Greaves',
]
extra = np.zeros(P, bool)
absent = []
for n in GREAT_ALSO:
    hits = by_name.get(n)
    if not hits:
        absent.append(n); continue
    # a name split into two people: take the one with the most appearances,
    # which is the one the reader means
    extra[max(hits, key=lambda k: apps[k])] = True
if absent:
    print(f'hand-list: {len(absent)} names not in the data: {", ".join(absent)}')

ok_band = band >= 0
known = (looked & ok_band & (views >= a.floor)
         & (pct >= KNOWN_BAR[np.clip(band, 0, None)])) | extra
icon = (looked & ok_band & (views >= a.floor)
        & (pct >= ICON_BAR[np.clip(band, 0, None)])) | extra
recent = last >= a.recent_from

print(f'{int(known.sum())} known, {int(icon.sum())} icons, '
      f'{int((known & recent).sum())} of the known still playing since '
      f'{a.recent_from}/{str(a.recent_from + 1)[2:]}')
for k, (lo, hi, lab) in enumerate(BANDS):
    m = band == k
    print(f'  {lab:26} {int((m & known).sum()):4d} known  '
          f'{int((m & icon).sum()):4d} icons  of {int((m & looked).sum()):5d} read')

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


rng = np.random.default_rng(a.seed)
buckets = {}


def collect(key, d, src_pool, partner, era=None, need_recent=True, report=None):
    """Fill buckets[key] with pairs exactly d apart.

    Every pair carries at least one player from the last ten years (rule 2):
    a source who is not one of them may only be joined to a partner who is.
    """
    out, pairs, n = [], set(), 0
    order = np.where(src_pool)[0]
    rng.shuffle(order)
    for n, s_ in enumerate(order, 1):
        if len(out) >= a.per_bucket:
            break
        dist = distances(int(s_), era)
        want = partner
        if need_recent and not recent[s_]:
            want = partner & recent
        hits = np.where((dist == d) & want)[0]
        hits = hits[hits != int(s_)]
        if hits.size > a.per_source:
            hits = rng.choice(hits, a.per_source, replace=False)
        for t in hits:
            pr = (min(int(s_), int(t)), max(int(s_), int(t)))
            if pr in pairs:
                continue
            pairs.add(pr)
            out.append([int(s_), int(t)])
            if len(out) >= a.per_bucket:
                break
    buckets[key] = out
    print(f'  {key}: {len(out)} pairs from {n} sources', flush=True)
    return out


# ------------------------------------------------------- Premier League ----
# The page defaults to the Premier League, so the default games have to be
# playable there. Thirty-odd seasons of twenty clubs is small and tightly
# connected -- nobody is more than four from anyone -- so there is no par 5 or
# 6 to be had and the round is 2*2*3*3*4.
pl_era = ts_season >= a.pl_from
in_pl = np.zeros(P, bool)
for i in range(P):
    for k in range(p_ip[i], p_ip[i + 1]):
        if pl_era[p_ix[k]]:
            in_pl[i] = True
            break
pl_ok = in_pl & known
print(f'\n{int(in_pl.sum())} players appear in {a.pl_from}/'
      f'{str(a.pl_from + 1)[2:]} or later, {int(pl_ok.sum())} of them known '
      f'({int((pl_ok & recent).sum())} still playing)')
for key, d in [('p2', 2), ('p3', 3), ('p4', 4)]:
    collect(key, d, pl_ok, pl_ok, era=pl_era)

# ------------------------------------------------------------- all time ----
# r* : both ends someone playing now.
# g* : one all-time great and one current player -- the era gap, which is what
#      makes a par 4 hard without making it unnameable.
# i* : the same with a far end from the stricter icon tier, because at five and
#      six links recognising who you are being asked to reach is all there is.
print('\nall time:')
collect('r2', 2, known & recent, known & recent)
collect('r3', 3, known & recent, known & recent)
collect('g3', 3, known & ~recent, known & recent)
collect('g4', 4, known & ~recent, known & recent)
collect('i5', 5, icon & ~recent, known & recent)
collect('i6', 6, icon & ~recent, known & recent)

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
print(f'{path}  {os.path.getsize(path) / 1024:.1f} KB')

# ---- what a round would actually look like, which is the only real test ----
sl = lambda y: f'{y}/{str((y + 1) % 100).zfill(2)}'
for pools, what in [(['p2', 'p2', 'p3', 'p3', 'p4'], 'regular'),
                    (['r2', 'r3', 'g4', 'i5', 'i6'], 'expert')]:
    print(f'\na {what} round:')
    for key in pools:
        i, j = buckets[key][rng.integers(len(buckets[key]))]
        print(f'  {key}  {names[i]:24} ({sl(first[i])}-{sl(last[i])}, '
              f'{views[i]:>7,})  ->  {names[j]:24} ({sl(first[j])}-{sl(last[j])}, '
              f'{views[j]:>7,})')
