#!/usr/bin/env python3
"""Turn the English top-flight teammate CSVs into the binary the football page loads.

Same shape as tools/build_network_data.py, and deliberately so -- the browser
engine is shared between the two pages, so both must emit SPNET001. Read that
file first for why the bipartite player <-> (club, season) index is shipped
rather than the materialised edges.

Two things differ from the NFL build:

  * A season here is a straddling one. `year` is the STARTING year throughout,
    so 1888 means 1888/89 -- tables.json carries seasonStyle so the page knows
    to print it that way. Storing the start year keeps every comparison and
    every range filter a plain integer.

  * Identity is name-based before 1992. Upstream (build_player_master.py in the
    pl_reel working directory) splits a name into separate people at a gap of
    more than ten seasons, which is deliberately biased towards splitting: a
    wrong split loses links, a wrong merge invents a person who bridges two
    eras he never played in. 635 names are split. Namesakes closer together
    than that still merge, and that is the largest known defect in this data --
    it is why Stanley Matthews appears twice.

The source lives outside this repo (the scrape is large and most of it is
licensed). Point --src at it.

Output (assets/foot/):
    graph.bin.gz   arrays, pre-gzipped
    names.txt.gz   player names, index-aligned with the arrays
    tables.json    positions, club codes, club metadata, season range
    fame.csv       NOT shipped: career league appearances per node, for ranking
                   who is worth a portrait and who can carry a puzzle

Run:  python3 tools/build_football_data.py --src ~/Downloads/pl_reel
"""
import argparse, gzip, json, os, re, struct, sys
from collections import Counter
import numpy as np
import pandas as pd

MAGIC = b'SPNET001'
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ap = argparse.ArgumentParser()
ap.add_argument('--src', default=os.path.expanduser('~/Downloads/pl_reel'))
ap.add_argument('--out', default=os.path.join(HERE, 'assets', 'foot'))
a = ap.parse_args()
S = lambda *p: os.path.join(a.src, *p)

# ------------------------------------------------------------------ clubs ----
# Three letters per club, in the way each is actually abbreviated. These are
# only ever shown beside the full name, but they key the crest files and the
# share text, so they need to be stable and they need to be unique.
CLUB_CODE = {
  'AFC Bournemouth': 'BOU', 'Accrington F.C.': 'ACC', 'Arsenal': 'ARS',
  'Aston Villa': 'AVL', 'Barnsley': 'BAR', 'Birmingham City': 'BIR',
  'Blackburn Rovers': 'BLB', 'Blackpool': 'BLP', 'Bolton Wanderers': 'BOL',
  'Bradford City': 'BRC', 'Bradford Park Avenue': 'BPA', 'Brentford': 'BRE',
  'Brighton & Hove Albion': 'BHA', 'Bristol City': 'BRI', 'Burnley': 'BUR',
  'Bury': 'BURY', 'Cardiff City': 'CAR', 'Carlisle United': 'CARL',
  'Charlton Athletic': 'CHA', 'Chelsea': 'CHE', 'Coventry City': 'COV',
  'Crystal Palace': 'CRY', 'Darwen': 'DAR', 'Derby County': 'DER',
  'Everton': 'EVE', 'Fulham': 'FUL', 'Glossop North End': 'GLO',
  'Grimsby Town': 'GRI', 'Huddersfield Town': 'HUD', 'Hull City': 'HUL',
  'Ipswich Town': 'IPS', 'Leeds United': 'LEE', 'Leicester City': 'LEI',
  'Leyton Orient': 'LEY', 'Liverpool': 'LIV', 'Luton Town': 'LUT',
  'Manchester City': 'MCI', 'Manchester United': 'MUN', 'Middlesbrough': 'MID',
  'Millwall': 'MIL', 'Newcastle United': 'NEW', 'Northampton Town': 'NOR',
  'Norwich City': 'NRW', 'Nottingham Forest': 'NFO', 'Notts County': 'NOT',
  'Oldham Athletic': 'OLD', 'Oxford United': 'OXF', 'Portsmouth': 'POR',
  'Preston North End': 'PRE', 'Queens Park Rangers': 'QPR', 'Reading': 'REA',
  'Sheffield United': 'SHU', 'Sheffield Wednesday': 'SHW', 'Southampton': 'SOU',
  'Stoke City': 'STK', 'Sunderland': 'SUN', 'Swansea City': 'SWA',
  'Swindon Town': 'SWI', 'Tottenham Hotspur': 'TOT', 'Watford': 'WAT',
  'West Bromwich Albion': 'WBA', 'West Ham United': 'WHU',
  'Wigan Athletic': 'WIG', 'Wimbledon': 'WIM',
  'Wolverhampton Wanderers': 'WOL',
}

# ------------------------------------------------------------------- data ----
mem_all = pd.read_csv(S('topflight_player_seasons_all.csv'))
linked = pd.read_csv(S('topflight_players_linked.csv'))

missing = sorted(set(mem_all.club) - set(CLUB_CODE))
if missing:
    sys.exit(f'no club code for: {missing}')
if len(set(CLUB_CODE.values())) != len(CLUB_CODE):
    dup = [c for c, n in Counter(CLUB_CODE.values()).items() if n > 1]
    sys.exit(f'club codes are not unique: {dup}')

# Rows that are not a person.
#
# 11v11's scorer tables carry an "Own Goal" line, and the upstream parser lets
# it through as a player. It is not harmless: it becomes a node sitting in 48
# club-seasons across ninety years, and every pair of real players in those
# squads gets a two-step link through a thing that never played. The identity
# splitter then made it worse by cutting it into four "people" at the gaps.
#
# "? Cavanagh" and friends are the opposite case -- a real player whose
# forename the source never recorded. Each holds a single club-season, so it
# bridges nothing, and dropping them would lose a man who did play. They stay.
NOT_A_PERSON = re.compile(r'^\s*(own goals?|unknown|unknown scorers?|opponents?)\s*$',
                          re.I)
before = len(mem_all)
mem_all = mem_all[~mem_all.name.astype(str).str.match(NOT_A_PERSON)].copy()
if before != len(mem_all):
    print(f'dropped {before - len(mem_all)} rows that are not a player '
          f'(own goals and the like)')

mem_all['team'] = mem_all.club.map(CLUB_CODE)
mem_all['season'] = mem_all.year.astype(int)
mem_all['uid'] = mem_all.player_id

# --------------------------------------------- hand-verified bad rows -------
# A club-season the man was never actually at. Not a namesake merge -- there is
# no second person to split off -- but just as damaging, because a squad row is
# a teammate row: Alan Ball on Wolves' books as a schoolboy makes him a one-step
# link to every Wolves player of 1961/62. See the note in the file for why this
# is deliberately narrow.
bad_path = os.path.join(HERE, 'tools', 'football_bad_rows.json')
if os.path.exists(bad_path):
    bad = json.load(open(bad_path)).get('rows', [])
    want = {(r['uid'], r['club'], int(r['season'])) for r in bad}
    key = list(zip(mem_all.uid, mem_all.team, mem_all.season))
    sel = np.array([k in want for k in key])
    found = {k for k in key if k in want}
    for miss in sorted(want - found):
        print(f'  WARNING: bad row {miss} is not in the data; drop it from '
              f'{os.path.basename(bad_path)}')
    if sel.any():
        mem_all = mem_all[~sel].copy()
        print(f'removed {int(sel.sum())} club-seasons the player was never at '
              f'({len(found)} of {len(want)} listed)')

# ------------------------------------------------- hand-verified namesakes ---
# The upstream heuristic only separates namesakes more than ten seasons apart.
# Closer than that and two men stay one record who bridges eras he never played
# in, which is the single worst thing that can happen to a graph whose whole
# purpose is shortest routes. tools/build_splits.py turns an audit of the
# highest-risk records into the file read here; every split in it assigns each
# of the player's club-seasons to exactly one person, or it is not in the file.
splits_path = os.path.join(HERE, 'tools', 'football_splits.json')
if os.path.exists(splits_path):
    splits = json.load(open(splits_path))
    key = list(zip(mem_all.uid, mem_all.team, mem_all.season))
    moved, people = 0, 0
    for uid, spec in splits.items():
        for k, person in enumerate(spec['people']):
            want = {(uid, c, int(y)) for c, y in person['seasons']}
            if not want:
                continue
            sel = np.array([kk in want for kk in key])
            if not sel.any():
                print(f'  WARNING: {spec["name"]} person {k} matched no rows')
                continue
            # the first person keeps the original uid, so anything else keyed
            # on it (a portrait, a puzzle) still points at a real player
            if k:
                mem_all.loc[sel, 'uid'] = f'{uid}~{k}'
                moved += int(sel.sum())
            people += 1
    print(f'applied {len(splits)} hand-verified splits: {people} people, '
          f'{moved} club-seasons moved to a new node')

# ------------------------------------------------------------- positions ----
# ENFA's vocabulary is period-correct and worth keeping: a wing half is not a
# midfielder and calling him one throws away the only thing the row says about
# how the game was played. The Premier League feed only distinguishes four, so
# modern players land in the coarse buckets and older ones in the fine ones,
# which is the right way round -- the detail exists exactly where it is known.
POS_CANON = {
  'goalkeeper': 'Goalkeeper', 'full back': 'Full Back',
  'centre half': 'Centre Half', 'central defender': 'Central Defender',
  'defender': 'Defender', 'wing half': 'Wing Half',
  'midfielder': 'Midfielder', 'winger': 'Winger',
  'inside forward': 'Inside Forward', 'centre forward': 'Centre Forward',
  'forward': 'Forward',
}


def canon(p):
    return POS_CANON.get(str(p).strip().lower(), '')


# (pkey, club, season) -> position, from every source that states one. The row
# key rather than the player key, because a pkey is shared by everyone the
# splitter separated and only the row knows which of them this is.
pos_rows, app_rows = {}, {}


def absorb(df, key, club, year, pos=None, apps=None, prefix=''):
    for r in df.itertuples(index=False):
        k = (prefix + str(getattr(r, key)), getattr(r, club), int(getattr(r, year)))
        if pos is not None:
            p = canon(getattr(r, pos))
            if p:
                pos_rows[k] = p
        if apps is not None:
            v = getattr(r, apps)
            if pd.notna(v):
                # Take the highest figure any source gives for this club-season
                # rather than the sum. ENFA runs to 2023/24 and the Premier
                # League feed covers 1992 on, so the two overlap for thirty
                # seasons and adding them would double every modern career.
                app_rows[k] = max(app_rows.get(k, 0), int(v))


enfa = pd.read_csv(S('english_topflight_players_enfa.csv'))
enfa['pk'] = enfa.player_key.str.replace(r'^name:', '', regex=True)
absorb(enfa, 'pk', 'club', 'season_start', 'position', 'appearances')

for f in ('english_topflight_players_1946_1992_11v11.csv',
          'english_topflight_players_1888_1946_11v11.csv'):
    if os.path.exists(S(f)):
        h = pd.read_csv(S(f))
        h['pk'] = h.player_key.str.replace(r'^name:', '', regex=True)
        absorb(h, 'pk', 'club', 'season_start', 'position', 'appearances')

pl = pd.read_csv(S('premier_league_player_seasons_1992_plus.csv'))
pl['pk'] = 'pl:' + pl.player_id.astype(str)
pl['yr'] = pl.season.str.slice(0, 4).astype(int)
absorb(pl, 'pk', 'club', 'yr', apps='appearances')

# The PL feed carries no position per season, only per player.
meta = pd.read_csv(S('player_meta.csv'))
pl_pos = {f'pl:{i}': canon(p) for i, p in zip(meta.player_id, meta.position)}

# ---------------------------------------------------------------- indexing ---
uids = sorted(mem_all.uid.unique())
idx = {u: i for i, u in enumerate(uids)}
P = len(uids)

ts_keys = sorted({(t, int(s)) for t, s in zip(mem_all.team, mem_all.season)})
ts_i = {k: i for i, k in enumerate(ts_keys)}
T = len(ts_keys)

pl_arr = np.array([idx[u] for u in mem_all.uid], np.int32)
tk_arr = np.array([ts_i[(t, int(s))] for t, s in zip(mem_all.team, mem_all.season)], np.int32)


def csr(src, dst, n):
    o = np.argsort(src, kind='stable')
    src, dst = src[o], dst[o]
    indptr = np.concatenate([[0], np.cumsum(np.bincount(src, minlength=n))]).astype(np.int32)
    return indptr, dst.astype(np.int32)


p_ip, p_ix = csr(pl_arr, tk_arr, P)      # player -> club-seasons
t_ip, t_ix = csr(tk_arr, pl_arr, T)      # club-season -> players

# --------------------------------------------------------- per-player facts --
name_of = dict(zip(linked.player_id, linked.player))
grp = mem_all.groupby('uid')
first = grp.season.min()
last = grp.season.max()
fallback_name = grp.name.last()

names = [str(name_of.get(u, fallback_name.get(u, u))) for u in uids]
first_season = np.array([int(first[u]) for u in uids], np.int16)
last_season = np.array([int(last[u]) for u in uids], np.int16)

# Position and career appearances, gathered per node from its own rows.
by_uid_pos = {u: [] for u in uids}
by_uid_app = {u: 0 for u in uids}
for pk, club, yr, uid in zip(mem_all.pkey, mem_all.club, mem_all.season, mem_all.uid):
    k = (str(pk), club, int(yr))
    p = pos_rows.get(k)
    if p:
        by_uid_pos[uid].append(p)
    k2 = (str(uid), club, int(yr))
    by_uid_app[uid] += max(app_rows.get(k, 0), app_rows.get(k2, 0))

positions_of = []
for u in uids:
    c = Counter(by_uid_pos[u])
    if c:
        positions_of.append(c.most_common(1)[0][0])
    else:
        positions_of.append(pl_pos.get(str(u), ''))

positions = sorted(set(positions_of))
pos_i = {p: i for i, p in enumerate(positions)}
if len(positions) > 255:
    sys.exit('more positions than a byte can hold; widen posIdx')

teams = sorted({t for t, _ in ts_keys})
team_i = {t: i for i, t in enumerate(teams)}

# ------------------------------------------------------------------ write ----
buf = bytearray()
buf += MAGIC
buf += struct.pack('<ii', P, T)
for arr in (p_ip, p_ix, t_ip, t_ix):
    buf += arr.tobytes()
buf += first_season.tobytes()
buf += last_season.tobytes()
buf += np.array([pos_i[p] for p in positions_of], np.uint8).tobytes()
buf += np.array([team_i[t] for t, _ in ts_keys], np.uint16).tobytes()
buf += np.array([s for _, s in ts_keys], np.int16).tobytes()

os.makedirs(a.out, exist_ok=True)
graph_path = os.path.join(a.out, 'graph.bin.gz')
with gzip.open(graph_path, 'wb', compresslevel=9) as f:
    f.write(bytes(buf))
names_path = os.path.join(a.out, 'names.txt.gz')
with gzip.open(names_path, 'wt', compresslevel=9, encoding='utf-8') as f:
    f.write('\n'.join(names))

code_club = {v: k for k, v in CLUB_CODE.items()}
club_meta = {}
for k_i, code in enumerate(teams):
    seasons = sorted({s for (t, s) in ts_keys if t == code})
    members = set()
    for k, (t, s) in enumerate(ts_keys):
        if t != code:
            continue
        for j in range(t_ip[k], t_ip[k + 1]):
            members.add(int(t_ix[j]))
    club_meta[code] = {'name': code_club[code], 'from': min(seasons),
                       'to': max(seasons), 'players': len(members),
                       'seasons': seasons}

# The most capped holder of the name, not the first one in node order. The
# identity heuristic splits Stanley Matthews in two at the war, and index()
# returns the 1933-38 half -- the wrong man to hang anything on, and not the
# one the portrait was matched to either.
by_name_nodes = {}
for i, n in enumerate(names):
    by_name_nodes.setdefault(n, []).append(i)

notable = {}
for who in ('Erling Haaland', 'Jack Grealish', 'Stanley Matthews',
            'Bobby Charlton', 'Alan Shearer', 'Billy Meredith'):
    hits = by_name_nodes.get(who)
    if hits:
        notable[who] = max(hits, key=lambda i: by_uid_app[uids[i]])
if 'Erling Haaland' not in notable:
    sys.exit('Erling Haaland is not in the data; the page is centred on him')

# The eras the page offers. "Premier League" is not a separate competition for
# these purposes, it is the top flight from 1992/93 on -- so it is a year range
# like any other, and restricting to it restricts the club-seasons the traversal
# may walk. That is the only reading of the filter that keeps a distance
# honest: two players linked only through a 1975 dressing room are NOT two
# apart in the Premier League, they are not connected at all.
ERAS = [
  {'id': 'all', 'name': 'All time', 'from': 1888, 'to': 2100,
   'note': 'Every English top-flight season since 1888/89.'},
  {'id': 'pl', 'name': 'Premier League only', 'from': 1992, 'to': 2100,
   'note': 'From 1992/93. Links formed in the old First Division do not count.'},
  {'id': 'modern', 'name': 'Last 25 years', 'from': 2000, 'to': 2100,
   'note': 'From 2000/01.'},
  {'id': 'div1', 'name': 'Old First Division', 'from': 1946, 'to': 1991,
   'note': 'Post-war, 1946/47 to 1991/92.'},
  {'id': 'prewar', 'name': 'Before the war', 'from': 1888, 'to': 1938,
   'note': 'The Football League from its first season to 1938/39.'},
]

# Choosing an era means the chart may no longer have a centre: Haaland never
# played a minute of the old First Division, and rooting a 1946-91 graph on him
# gives a chart of one dot. Each era therefore names a fallback -- the most
# capped player whose whole career falls inside it -- so the page can move the
# chart somewhere that exists and say why.
for e in ERAS:
    best, best_apps = None, -1
    for i, u in enumerate(uids):
        if first_season[i] < e['from'] or last_season[i] > e['to']:
            continue
        if by_uid_app[u] > best_apps:
            best, best_apps = i, by_uid_app[u]
    if best is not None:
        e['centre'] = int(best)
        e['centreName'] = names[best]

json.dump({'sport': 'football',
           'positions': positions, 'teams': teams, 'teamMeta': club_meta,
           'seasonStyle': 'split',      # 1992 is displayed as 1992/93
           'seasonMin': int(min(s for _, s in ts_keys)),
           'seasonMax': int(max(s for _, s in ts_keys)),
           'plFrom': 1992, 'eras': ERAS,
           'players': P, 'teamSeasons': T, 'memberships': int(p_ip[P]),
           'notable': notable},
          open(os.path.join(a.out, 'tables.json'), 'w'), indent=1)

# Portraits, if any have been fetched yet. Files are named by node index, so the
# page needs a yes/no per player rather than a filename table -- see the same
# note in build_network_data.py.
faces_dir = os.path.join(a.out, 'faces')
face_flags = np.zeros(P, dtype=np.uint8)
if os.path.isdir(faces_dir):
    for fn in os.listdir(faces_dir):
        if fn.endswith('.webp'):
            try:
                i = int(fn[:-5])
            except ValueError:
                continue
            if 0 <= i < P:
                face_flags[i] = 1
with gzip.open(os.path.join(a.out, 'faces.bin.gz'), 'wb', compresslevel=9) as f:
    f.write(face_flags.tobytes())

# Who is worth a portrait, and who can hold up a puzzle. Career league
# appearances is a far better proxy for that than anything the NFL build had --
# it is in the source, it spans the whole range, and it does not smuggle in the
# present day the way "has a photo on Commons" does. Not shipped to the browser.
fame = pd.DataFrame({
    'node': np.arange(P), 'uid': uids, 'name': names,
    'first': first_season, 'last': last_season,
    'position': positions_of,
    'apps': [by_uid_app[u] for u in uids],
    'club_seasons': [int(p_ip[i + 1] - p_ip[i]) for i in range(P)],
    'seasons': [len({ts_keys[p_ix[j]][1] for j in range(p_ip[i], p_ip[i + 1])})
                for i in range(P)],
    'clubs': [len({ts_keys[p_ix[j]][0] for j in range(p_ip[i], p_ip[i + 1])})
              for i in range(P)],
})
fame = fame.sort_values('apps', ascending=False)
fame.to_csv(os.path.join(HERE, 'tools', 'football_fame.csv'), index=False)

print(f'players {P}  club-seasons {T}  memberships {p_ip[P]}')
print(f'seasons {min(s for _, s in ts_keys)}/{str(min(s for _, s in ts_keys)+1)[2:]} '
      f'to {max(s for _, s in ts_keys)}/{str(max(s for _, s in ts_keys)+1)[2:]}  '
      f'clubs {len(teams)}')
print(f'positions {len(positions)}: {", ".join(positions)}')
known = sum(1 for p in positions_of if p)
print(f'position known for {known} of {P} players ({100*known/P:.0f}%)')
print(f'appearances known for {sum(1 for u in uids if by_uid_app[u])} players')
print(f'graph.bin  {len(buf)/1e6:.2f} MB raw -> {os.path.getsize(graph_path)/1e6:.2f} MB gzipped')
print(f'names.txt  -> {os.path.getsize(names_path)/1e6:.2f} MB gzipped')
print(f'portraits: {int(face_flags.sum())} of {P}')
print('notable: ' + ', '.join(f'{k}={v}' for k, v in notable.items()))
