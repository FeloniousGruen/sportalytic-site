#!/usr/bin/env python3
"""Turn the NFL teammate CSVs into the binary the network page loads.

The page needs to re-root the graph on any player, which means a breadth-first
pass over the real teammate relation -- 2,233,386 edges.  Shipping those edges
costs 7.9 MB gzipped.  They are all implied by 125,361 membership rows, so we
ship the bipartite player <-> (team, season) index instead, at 0.12 MB, and let
the browser traverse that directly.  Measured in node: 1.6 ms per full BFS.

Output (assets/net/):
    graph.bin.gz   arrays, pre-gzipped so the transfer size does not depend on
                   the host's content-type compression rules
    names.txt.gz   player names, newline separated, index-aligned with the arrays
    tables.json    position names, team codes, season range, notable ids

Run:  python3 tools/build_network_data.py --nodes <nodes.csv> --rosters <memberships.csv>
"""
import argparse, gzip, json, os, struct, sys
import numpy as np
import pandas as pd

MAGIC = b'SPNET001'

ap = argparse.ArgumentParser()
ap.add_argument('--nodes', default=None,
                help='optional: preferred name/position spellings')
ap.add_argument('--rosters', required=True)
ap.add_argument('--out', default='assets/net')
a = ap.parse_args()

mem_all = pd.read_csv(a.rosters)

# The player list is derived from the memberships rather than a fixed nodes
# file, so adding a season brings its new players in automatically. The nodes
# CSV is still read when present, only to prefer its spelling of a name.
prefer = {}
if a.nodes and os.path.exists(a.nodes):
    nf = pd.read_csv(a.nodes, usecols=['uid', 'name', 'position'])
    prefer = {u: (n, p_) for u, n, p_ in zip(nf.uid, nf.name, nf.position)}

grp = mem_all.groupby('uid')
nodes = pd.DataFrame({
    'uid': list(grp.groups.keys()),
})
first = grp.season.min()
last = grp.season.max()
namecol = 'full_name' if 'full_name' in mem_all.columns else 'uid'
lastname = grp[namecol].last()
lastpos = grp['position'].last() if 'position' in mem_all.columns else None
nodes['name'] = [prefer.get(u, (lastname.get(u, u), None))[0] for u in nodes.uid]
nodes['position'] = [
    (prefer[u][1] if u in prefer and isinstance(prefer[u][1], str)
     else (lastpos.get(u) if lastpos is not None else ''))
    for u in nodes.uid]
nodes['first_season'] = [int(first[u]) for u in nodes.uid]
nodes['last_season'] = [int(last[u]) for u in nodes.uid]
nodes = nodes.sort_values('uid').reset_index(drop=True)

mem = mem_all[['uid', 'team', 'season']].copy()

uids = list(nodes['uid'])
idx = {u: i for i, u in enumerate(uids)}
P = len(uids)
mem = mem[mem.uid.isin(idx)]

# The source labels the same club differently depending on era: a 1978-2016
# block uses KAN/GNB/NWE/NOR/TAM/SFO/LAR while the rest of the range uses
# KC/GB/NE/NO/TB/SF/LA. Verified that no pair ever covers the same season, so
# no roster is split across two codes and no edges are missing -- this is a
# relabelling only, and it leaves the team-season count unchanged.
ALIAS = {'KAN': 'KC', 'GNB': 'GB', 'NWE': 'NE', 'NOR': 'NO',
         'TAM': 'TB', 'SFO': 'SF', 'LAR': 'LA',
         'CHB': 'CHI',          # Bears: CHB 1922-59 then CHI 1960-2025
         'AZ': 'ARI',           # nflverse switched Arizona to AZ for 2026
         'COW': 'DAL'}          # Cowboys: COW 1960-62 then DAL 1963-
mem['team'] = mem.team.map(lambda t: ALIAS.get(t, t))

ts_keys = sorted({(t, int(s)) for t, s in zip(mem.team, mem.season)})
ts_i = {k: i for i, k in enumerate(ts_keys)}
T = len(ts_keys)

pl = np.array([idx[u] for u in mem.uid], np.int32)
tk = np.array([ts_i[(t, int(s))] for t, s in zip(mem.team, mem.season)], np.int32)


def csr(src, dst, n):
    o = np.argsort(src, kind='stable')
    src, dst = src[o], dst[o]
    indptr = np.concatenate([[0], np.cumsum(np.bincount(src, minlength=n))]).astype(np.int32)
    return indptr, dst.astype(np.int32)


p_ip, p_ix = csr(pl, tk, P)      # player -> team-seasons
t_ip, t_ix = csr(tk, pl, T)      # team-season -> players

# Full names for the franchises I can state with confidence. The set spans
# 1920-2025 and includes a lot of one-season clubs whose codes I will not guess
# at -- those keep the code, and the page shows the era and squad size beside it
# so the dropdown is still legible. Fill any of these in as you like.
TEAM_NAMES = {
  # current franchises
  'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BUF': 'Buffalo Bills',
  'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears', 'CIN': 'Cincinnati Bengals',
  'DAL': 'Dallas Cowboys', 'DEN': 'Denver Broncos', 'DET': 'Detroit Lions',
  'GB': 'Green Bay Packers', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars',
  'KC': 'Kansas City Chiefs', 'LV': 'Las Vegas Raiders', 'OAK': 'Oakland Raiders',
  'LAC': 'Los Angeles Chargers', 'SD': 'San Diego Chargers', 'MIA': 'Miami Dolphins',
  'MIN': 'Minnesota Vikings', 'NE': 'New England Patriots', 'NO': 'New Orleans Saints',
  'NYG': 'New York Giants', 'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles',
  'PIT': 'Pittsburgh Steelers', 'SEA': 'Seattle Seahawks', 'SF': 'San Francisco 49ers',
  'TB': 'Tampa Bay Buccaneers', 'TEN': 'Tennessee Titans',
  # codes that span more than one franchise in this data, so city-level only
  'BAL': 'Baltimore', 'CLE': 'Cleveland', 'HOU': 'Houston', 'LA': 'Los Angeles',
  'STL': 'St. Louis', 'BOS': 'Boston', 'NY': 'New York', 'WAS': 'Washington',
  'BRK': 'Brooklyn', 'CHC': 'Chicago Cardinals', 'RAM': 'Los Angeles Rams',
  # defunct and early-era clubs
  'AKR': 'Akron Pros', 'CAN': 'Canton Bulldogs', 'DAY': 'Dayton Triangles',
  'DEC': 'Decatur Staleys', 'ROC': 'Rochester Jeffersons', 'RAC': 'Racine Cardinals',
  'MIL': 'Milwaukee Badgers', 'HAM': 'Hammond Pros', 'TOL': 'Toledo Maroons',
  'DUL': 'Duluth Eskimos', 'PRO': 'Providence Steam Roller',
  'POT': 'Pottsville Maroons', 'FYJ': 'Frankford Yellow Jackets',
  'CHH': 'Chicago Hornets', 'CHR': 'Chicago Rockets', 'CHS': 'Chicago Staleys',
  'CHT': 'Chicago Tigers', 'COL': 'Columbus Panhandles', 
  'DON': 'Los Angeles Dons', 'ECG': 'Evansville Crimson Giants',
  'HAR': 'Hartford Blues', 'KEN': 'Kenosha Maroons', 'LOU': 'Louisville Colonels',
  'MUN': 'Muncie Flyers', 'NEW': 'Newark Tornadoes', 'NYB': 'New York Bulldogs',
  'NYT': 'New York Titans', 'NYY': 'New York Yankees', 'OOR': 'Oorang Indians',
  'ORG': 'Orange Tornadoes', 'POR': 'Portsmouth Spartans',
  'RI': 'Rock Island Independents', 'SI': 'Staten Island Stapletons',
  'TEX': 'Dallas Texans (AFL)', 'TON': 'Tonawanda Kardex',
  'C-P': 'Card-Pitt', 'P-P': 'Phil-Pitt Steagles',
  'CAL': 'California', 'IND_H': '', 'DEC_H': '',
}

# Codes the source reuses across genuinely different franchises. Listing one of
# these as a single club would be wrong -- BAL is the Colts until 1977 and the
# Ravens from 1996, which are not the same team -- so they are split into eras
# and offered separately. Where a code IS one continuous franchise it stays a
# single entry. Asserted from NFL history; worth a check.
TEAM_ERAS = {
  'BAL': [('Baltimore Colts', 1947, 1977), ('Baltimore Ravens', 1996, 2100)],
  'HOU': [('Houston Oilers', 1960, 1977), ('Houston Texans', 2002, 2100)],
  'CLE': [('Cleveland (early clubs)', 1920, 1931),
          ('Cleveland Rams', 1937, 1945), ('Cleveland Browns', 1946, 2100)],
  'STL': [('St. Louis All-Stars', 1923, 1923), ('St. Louis Gunners', 1934, 1934),
          ('St. Louis Cardinals', 1960, 1977)],
  'BOS': [('Boston Bulldogs', 1929, 1929), ('Boston Braves / Redskins', 1932, 1936),
          ('Boston Yanks', 1944, 1948), ('Boston Patriots', 1960, 1970)],
  'LA':  [('Los Angeles Buccaneers', 1926, 1926), ('Los Angeles Rams', 1950, 2100)],
  'DAL': [('Dallas Texans (NFL)', 1952, 1952), ('Dallas Cowboys', 1960, 2100)],
}

teams = sorted({t for t, _ in ts_keys})
team_i = {t: i for i, t in enumerate(teams)}
positions = sorted({str(p) for p in nodes.position.fillna('')})
pos_i = {p: i for i, p in enumerate(positions)}
if len(positions) > 255:
    sys.exit('more positions than a byte can hold; widen posIdx')

buf = bytearray()
buf += MAGIC
buf += struct.pack('<ii', P, T)
for arr in (p_ip, p_ix, t_ip, t_ix):
    buf += arr.tobytes()
buf += nodes.first_season.values.astype(np.int16).tobytes()
buf += nodes.last_season.values.astype(np.int16).tobytes()
buf += np.array([pos_i[str(p)] for p in nodes.position.fillna('')], np.uint8).tobytes()
buf += np.array([team_i[t] for t, _ in ts_keys], np.uint16).tobytes()
buf += np.array([s for _, s in ts_keys], np.int16).tobytes()

os.makedirs(a.out, exist_ok=True)
graph_path = os.path.join(a.out, 'graph.bin.gz')
with gzip.open(graph_path, 'wb', compresslevel=9) as f:
    f.write(bytes(buf))
names_path = os.path.join(a.out, 'names.txt.gz')
with gzip.open(names_path, 'wt', compresslevel=9, encoding='utf-8') as f:
    f.write('\n'.join(str(x) for x in nodes.name))

notable = {}
for who in ('Travis Kelce', 'George Blanda', 'Matt Moore', 'John Nesser'):
    hit = nodes.index[nodes.name == who]
    if len(hit):
        notable[who] = int(hit[0])
# per-team era and squad size, straight from the data, so the dropdown reads
# sensibly even where no full name is known
team_meta = {}
for ti, code in enumerate(teams):
    seasons = [s for (t, s) in ts_keys if t == code]
    members = set()
    for k, (t, s) in enumerate(ts_keys):
        if t != code:
            continue
        for j in range(t_ip[k], t_ip[k + 1]):
            members.add(int(t_ix[j]))
    entry = {'name': TEAM_NAMES.get(code, ''), 'from': min(seasons),
             'to': max(seasons), 'players': len(members),
             'seasons': sorted(set(seasons))}
    if code in TEAM_ERAS:
        eras = []
        for nm, lo, hi in TEAM_ERAS[code]:
            yrs = [y for y in seasons if lo <= y <= hi]
            if not yrs:
                continue
            mem = set()
            for k, (t, y) in enumerate(ts_keys):
                if t != code or not (lo <= y <= hi):
                    continue
                for j in range(t_ip[k], t_ip[k + 1]):
                    mem.add(int(t_ix[j]))
            eras.append({'name': nm, 'from': min(yrs), 'to': max(yrs),
                         'players': len(mem)})
        if len(eras) > 1:
            entry['eras'] = eras
    team_meta[code] = entry
named = sum(1 for c in teams if TEAM_NAMES.get(c))
print(f'team names: {named} of {len(teams)} mapped; the rest show code + era')

json.dump({'positions': positions, 'teams': teams, 'teamMeta': team_meta,
           'seasonMin': int(min(s for _, s in ts_keys)),
           'seasonMax': int(max(s for _, s in ts_keys)),
           'players': P, 'teamSeasons': T, 'memberships': int(p_ip[P]),
           'notable': notable},
          open(os.path.join(a.out, 'tables.json'), 'w'), indent=1)

# Which players have a portrait. Files are named by node index, so the page
# needs only a yes/no per player rather than a filename table; this also stops
# it firing 404s at the 25,000 players who have no photo.
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
print(f'portraits: {int(face_flags.sum())} of {P} players '
      f'({os.path.getsize(os.path.join(a.out, "faces.bin.gz"))/1024:.1f} KB flag file)')

raw = len(buf)
print(f'players {P}  team-seasons {T}  memberships {p_ip[P]}')
print(f'graph.bin  {raw/1e6:.2f} MB raw -> {os.path.getsize(graph_path)/1e6:.2f} MB gzipped')
print(f'names.txt  -> {os.path.getsize(names_path)/1e6:.2f} MB gzipped')
print(f'tables.json -> {os.path.getsize(os.path.join(a.out,"tables.json"))/1e3:.1f} KB')
