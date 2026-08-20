#!/usr/bin/env python3
"""Download player headshots and cut them into small circular avatars.

Only players who debuted from about 1990 have a real photo. Everything older
returns the league's generic silhouette -- sampled 12 players per era: 12/12
distinct for 2010+, 12/12 identical for 1970-89 and pre-1970. Those are skipped
by hashing each download against the placeholder rather than trusting the URL,
because every player has a distinct URL whether or not a photo exists.

Files are named by node index so the page can ask for faces/<idx>.webp without
a lookup table. Indices come from the same ordering as build_network_data.py,
so rerun this after rebuilding the graph if the roster file changed.

Usage: python3 tools/fetch_faces.py --rosters <memberships.csv> [--limit N]
"""
import argparse, hashlib, io, os, sys, threading
from concurrent.futures import ThreadPoolExecutor
import urllib.request
import pandas as pd
from PIL import Image, ImageDraw

PLACEHOLDER_MD5 = {'f63433b569d11ff35f8fe048849e34a1'}
UA = {'User-Agent': 'Mozilla/5.0'}
SIZE, SS = 96, 3

ap = argparse.ArgumentParser()
ap.add_argument('--rosters', required=True)
ap.add_argument('--nodes', default=None)
ap.add_argument('--out', default='assets/net/faces')
ap.add_argument('--min-debut', type=int, default=1990)
ap.add_argument('--limit', type=int, default=0)
ap.add_argument('--workers', type=int, default=16)
a = ap.parse_args()

mem = pd.read_csv(a.rosters)
# Same career merge the graph build applies, so indices line up.
alias_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pfr_aliases.csv')
if os.path.exists(alias_path):
    af = pd.read_csv(alias_path)
    same = dict(zip(af.pfr_uid, af.uid))
    mem['uid'] = mem.uid.map(lambda u: same.get(u, u))

grp = mem.groupby('uid')
uids = sorted(grp.groups.keys())                 # same order as the graph build
idx = {u: i for i, u in enumerate(uids)}
first = grp.season.min()

url = {}
if a.nodes and os.path.exists(a.nodes):
    nf = pd.read_csv(a.nodes, usecols=['uid', 'headshot_url'])
    for u, h in zip(nf.uid, nf.headshot_url):
        if isinstance(h, str) and h.startswith('http'):
            url[u] = h
if 'headshot_url' in mem.columns:
    for u, h in zip(mem.uid, mem.headshot_url):
        if isinstance(h, str) and h.startswith('http') and u not in url:
            url[u] = h

todo = [u for u in uids if u in url and int(first[u]) >= a.min_debut]
if a.limit:
    todo = todo[:a.limit]
os.makedirs(a.out, exist_ok=True)
print(f'{len(todo)} candidates (debut {a.min_debut}+, has a url)', flush=True)

lock = threading.Lock()
stat = {'ok': 0, 'placeholder': 0, 'fail': 0, 'skip': 0}


def circular(im):
    w, h = im.size
    side = int(h * 0.66)                          # NFL headshots share a framing
    box = ((w - side) // 2, int(h * 0.04))
    im = im.crop((box[0], box[1], box[0] + side, box[1] + side))
    S = SIZE * SS
    ph = im.convert('RGBA').resize((S, S), Image.LANCZOS)
    m = Image.new('L', (S, S), 0)
    ImageDraw.Draw(m).ellipse((0, 0, S - 1, S - 1), fill=255)
    out = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    out.paste(ph, (0, 0), m)
    return out.resize((SIZE, SIZE), Image.LANCZOS)


def one(u):
    dest = os.path.join(a.out, f'{idx[u]}.webp')
    if os.path.exists(dest):
        with lock: stat['skip'] += 1
        return
    try:
        d = urllib.request.urlopen(urllib.request.Request(url[u], headers=UA), timeout=30).read()
    except Exception:
        with lock: stat['fail'] += 1
        return
    if hashlib.md5(d).hexdigest() in PLACEHOLDER_MD5:
        with lock: stat['placeholder'] += 1
        return
    try:
        circular(Image.open(io.BytesIO(d)).convert('RGB')).save(dest, 'WEBP', quality=82, method=6)
        with lock:
            stat['ok'] += 1
            if stat['ok'] % 250 == 0:
                print(f"  {stat['ok']} saved, {stat['placeholder']} placeholders, "
                      f"{stat['fail']} failed", flush=True)
    except Exception:
        with lock: stat['fail'] += 1


with ThreadPoolExecutor(max_workers=a.workers) as ex:
    list(ex.map(one, todo))

# Record the owner of each file. Node indices shift whenever the player list
# changes, and without this the only way to renumber the directory would be to
# download all of it again; tools/remap_faces.py renames in place instead.
with open(os.path.join(a.out, 'owners.csv'), 'w') as f:
    f.write('index,uid\n')
    for u in uids:
        if os.path.exists(os.path.join(a.out, f'{idx[u]}.webp')):
            f.write(f'{idx[u]},{u}\n')

total = sum(os.path.getsize(os.path.join(a.out, f)) for f in os.listdir(a.out) if f.endswith('.webp'))
print(f"done: {stat['ok']} saved, {stat['placeholder']} placeholders skipped, "
      f"{stat['fail']} failed, {stat['skip']} already present", flush=True)
print(f'{total/1e6:.1f} MB on disk', flush=True)
