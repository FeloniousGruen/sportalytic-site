#!/usr/bin/env python3
"""Portraits for the famous players the NFL headshot archive does not reach.

That archive effectively starts around 2000 -- nobody who debuted before 1990
has a photo -- which leaves the whole Hall of Fame as bare dots. Wikipedia has
a lead image for almost all of them, and the ones hosted on Wikimedia Commons
are freely licensed. Images that live on en.wikipedia rather than Commons are
non-free (fair-use), so restricting to Commons is both the licence filter and
the quality filter.

Two stages, so the choices can be checked before 100 files are written:

    --stage resolve   name -> article -> Commons file, writes a manifest
    --stage fetch     manifest -> cropped circular avatars in faces/

Resolving goes through the article rather than a Commons filename search on the
name: a search for "Husain Abdullah" returns an Indonesian official, whereas the
article about the safety carries a picture of the safety. It still checks the
article really is about an American football player, and for a name shared by
several players it picks the node whose seasons match the article.

Usage:
  python3 tools/fetch_commons_faces.py --stage resolve --names <file> --out <manifest.json>
  python3 tools/fetch_commons_faces.py --stage fetch --manifest <manifest.json>
"""
import argparse, gzip, io, json, os, re, sys, threading, time, unicodedata, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

# Wikimedia's robot policy wants a way to contact whoever is making the
# requests. Without one it answers sustained traffic with 429 "your request
# does not comply with our robot policy" -- set --contact to your own address
# or site before any sizeable run.
UA = {}
API = 'https://en.wikipedia.org/w/api.php'
COMMONS = 'https://commons.wikimedia.org/w/api.php'
SIZE, SS = 96, 3

ap = argparse.ArgumentParser()
ap.add_argument('--stage', choices=['resolve', 'fetch'], required=True)
ap.add_argument('--names', help='one player name per line (resolve)')
ap.add_argument('--rosters', help='memberships csv, for careers (resolve)')
ap.add_argument('--data', default='assets/net')
ap.add_argument('--out', default='commons_manifest.json')
ap.add_argument('--manifest')
ap.add_argument('--faces', default='assets/net/faces')
ap.add_argument('--workers', type=int, default=2)
ap.add_argument('--delay', type=float, default=0.7,
                help='minimum seconds between API calls; Wikimedia throttles bursts')
ap.add_argument('--contact', default='https://sportalytic.netlify.app/network.html',
                help='email or url for the User-Agent, per Wikimedia robot policy')
a = ap.parse_args()

UA['User-Agent'] = (f'sportalytic-network/1.0 ({a.contact}; portraits for a '
                    f'teammate graph) python-urllib')


# Wikimedia throttles hard and stays throttled for a while once tripped, so
# hold every request to one at a time with a gap between them. 200 players is
# ~400 calls; at this rate that is a few minutes and it never gets a 429.
_gate, _last = threading.Lock(), [0.0]


def get(url, tries=10):
    for k in range(tries):
        with _gate:
            wait = a.delay - (time.time() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45).read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or k == tries - 1:
                raise
            # the image CDN sheds load in bursts; a short pause clears it, and a
            # long one just stalls the run behind a limit already lifted
            time.sleep(float(e.headers.get('Retry-After') or 0) or min(8, 2 + k))
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(1 + k)


def api(**params):
    params.setdefault('format', 'json')
    params.setdefault('formatversion', '2')
    return json.loads(get(API + '?' + urllib.parse.urlencode(params)))


def key(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z]', '', s.lower())


# Files that turn up on every article and are never the player.
JUNK = re.compile(r'logo|icon|map|flag|helmet|stub|ambox|commons|wiki|banner|'
                  r'symbol|seal|emblem|arrow|edit|padlock|question|blank|'
                  r'sound|speaker|nfl_?100|hall of fame|trophy', re.I)


def article_photo(title, name):
    """Best Commons photo used somewhere on a player's article, or (None, None).

    Ranked by how much of the player's name is in the filename, so
    'Gene Upshaw 1972.jpg' wins over a stadium shot on the same page.
    """
    imgs = api(action='query', prop='images', imlimit=60,
               titles=title, redirects=1).get('query', {}).get('pages', [])
    cand = [i['title'] for i in (imgs[0].get('images') or []) if imgs] \
        if imgs else []
    cand = [c for c in cand
            if c.lower().endswith(('.jpg', '.jpeg', '.png')) and not JUNK.search(c)]
    if not cand:
        return None, None
    parts = [w for w in re.split(r'\s+', name) if len(w) > 2]

    def score(c):
        k = key(c)
        return sum(1 for w in parts if key(w) in k)
    cand.sort(key=lambda c: (-score(c), len(c)))
    if score(cand[0]) < len(parts):        # filename must carry the whole name
        return None, None
    # imageinfo tells us the url and, by its repository, whether it is free
    ii = api(action='query', prop='imageinfo', iiprop='url',
             titles=cand[0], redirects=1).get('query', {}).get('pages', [])
    if not ii or ii[0].get('imagerepository') != 'shared':
        return None, None
    return (ii[0]['imageinfo'][0]['url'], cand[0])


# ---------------------------------------------------------------- resolve ----
def resolve(name, spans):
    """spans: list of (node index, first season, last season) sharing this name."""
    hits = api(action='query', list='search', srsearch=f'{name} American football',
               srlimit=6).get('query', {}).get('search', [])
    for h in hits:
        title = h['title']
        if key(title.split('(')[0]) != key(name):
            continue
        pg = api(action='query', prop='pageimages|extracts|pageprops',
                 exintro=1, explaintext=1, piprop='original',
                 titles=title, redirects=1).get('query', {}).get('pages', [])
        if not pg:
            continue
        p = pg[0]
        text = p.get('extract', '')
        if 'football' not in text.lower():
            continue
        # Commons-hosted means freely licensed. A file that lives only on
        # en.wikipedia is there under fair use and must not be copied -- and the
        # two are told apart by the path they serve from, no extra call needed.
        orig = (p.get('original') or {}).get('source')
        if orig and '/wikipedia/commons/' not in orig:
            orig = None
        if not orig:
            # No free lead image. PageImages also just omits a non-free one, so
            # both cases land here. Fall back to the Commons files used further
            # down the article -- still pictures someone put on this player's
            # page, which a Commons search on the name would not be.
            orig, fname = article_photo(title, name)
            if not orig:
                return {'name': name, 'title': title,
                        'skip': 'no freely licensed photo on the article'}
        else:
            # the API tacks a ?utm_... query onto the url; it is not in the name
            fname = 'File:' + urllib.parse.unquote(
                orig.split('?')[0].rsplit('/', 1)[-1]).replace('_', ' ')

        # Does the article describe the career this node actually had? Checked
        # even when only one node is left, because the others may have been
        # filtered out for already having a photo -- which is how the Vikings
        # Adrian Peterson's picture nearly ended up on the Bears one of the
        # same name, he being the only candidate still without one.
        years = sorted({int(y) for y in re.findall(r'\b(19\d\d|20\d\d)\b', text)})

        def overlap(s):
            return sum(1 for y in years if s[1] - 1 <= y <= s[2] + 1)
        best = max(spans, key=overlap)
        node = best[0]
        why = f'{overlap(best)} of {len(years)} article years in {best[1]}-{best[2]}'
        if years and overlap(best) == 0:
            return {'name': name, 'title': title,
                    'skip': f'the article describes no season this player '
                            f'({best[1]}-{best[2]}) was playing'}
        return {'name': name, 'node': node, 'title': title, 'url': orig,
                'file': fname, 'why': why,
                'span': f'{spans[0][1]}-{spans[0][2]}' if len(spans) == 1 else
                        next(f'{s[1]}-{s[2]}' for s in spans if s[0] == node),
                'summary': text[:220].replace('\n', ' ')}
    return {'name': name, 'skip': 'no article whose title matches and mentions football'}


if a.stage == 'resolve':
    import pandas as pd
    names = [l.strip() for l in open(a.names) if l.strip()]
    allnames = gzip.open(os.path.join(a.data, 'names.txt.gz'), 'rb').read().decode().split('\n')
    flags = gzip.open(os.path.join(a.data, 'faces.bin.gz'), 'rb').read()

    # Careers, in the graph's own node order, so a name shared by several
    # players can be pinned to the one the article is about.
    mem = pd.read_csv(a.rosters)
    alias = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pfr_aliases.csv')
    if os.path.exists(alias):
        af = pd.read_csv(alias)
        same = dict(zip(af.pfr_uid, af.uid))
        mem['uid'] = mem.uid.map(lambda u: same.get(u, u))
    g = mem.groupby('uid').season
    uids = sorted(g.groups.keys())
    lo, hi = g.min(), g.max()
    span = {i: (int(lo[u]), int(hi[u])) for i, u in enumerate(uids)}
    assert len(uids) == len(allnames), f'{len(uids)} uids vs {len(allnames)} names -- rebuild first'

    spans_by_key = {}
    for i, n in enumerate(allnames):
        spans_by_key.setdefault(key(n), []).append(i)

    jobs = []
    for nm in names:
        ix = [i for i in spans_by_key.get(key(nm), []) if not flags[i]]
        jobs.append((nm, [(i, *span[i]) for i in ix] or None))

    out = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(lambda j: ({'name': j[0], 'skip': 'not in the graph, or already has a photo'}
                                   if j[1] is None else resolve(j[0], j[1])), jobs):
            out.append(r)
            print(('  ok   ' if 'url' in r else '  SKIP ') + r['name'] +
                  ('' if 'url' in r else ' -- ' + r['skip']), flush=True)
    # Licence and author for every accepted file, 40 titles per request. Commons
    # reuse needs the attribution recorded even when the page does not show it.
    ok = [r for r in out if 'url' in r]
    for k in range(0, len(ok), 40):
        chunk = ok[k:k + 40]
        q = json.loads(get(COMMONS + '?' + urllib.parse.urlencode({
            'action': 'query', 'prop': 'imageinfo', 'iiprop': 'extmetadata',
            'titles': '|'.join(r['file'] for r in chunk), 'redirects': 1,
            'format': 'json', 'formatversion': '2'}))).get('query', {})
        # the API normalises titles, so map back through what it echoes
        back = {n['to']: n['from'] for n in q.get('normalized', [])}
        meta = {}
        for p in q.get('pages', []):
            e = (p.get('imageinfo') or [{}])[0].get('extmetadata', {})
            v = ((e.get('LicenseShortName') or {}).get('value', '?'),
                 re.sub('<[^>]+>', '', (e.get('Artist') or {}).get('value', '') or '').strip()[:90])
            meta[p['title']] = v
            if p['title'] in back:
                meta[back[p['title']]] = v
        for r in chunk:
            r['licence'], r['artist'] = meta.get(r['file'], ('?', ''))

    json.dump(out, open(a.out, 'w'), indent=1)
    print(f'\n{len(ok)} of {len(out)} resolved to a Commons image -> {a.out}')
    for lic in sorted({r['licence'] for r in ok}):
        print(f"   {sum(1 for r in ok if r['licence']==lic):3d}  {lic}")
    sys.exit(0)

# ------------------------------------------------------------------ fetch ----
from PIL import Image, ImageDraw

man = json.load(open(a.manifest))
todo = [r for r in man if r.get('url') and r.get('crop') != 'skip']
os.makedirs(a.faces, exist_ok=True)


def circular(im, cx=0.5, cy=0.38, scale=1.0):
    """Square crop centred on (cx, cy) of the frame, then a circular mask.

    Commons images are not framed like NFL headshots, so the default aims a
    little above the middle -- where a head is in most standing photographs --
    and each entry can override it in the manifest once it has been eyeballed.
    """
    w, h = im.size
    side = int(min(w, h) * scale)
    x = int(w * cx - side / 2)
    y = int(h * cy - side / 2)
    x = max(0, min(w - side, x))
    y = max(0, min(h - side, y))
    im = im.crop((x, y, x + side, y + side))
    S = SIZE * SS
    ph = im.convert('RGBA').resize((S, S), Image.LANCZOS)
    m = Image.new('L', (S, S), 0)
    ImageDraw.Draw(m).ellipse((0, 0, S - 1, S - 1), fill=255)
    out = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    out.paste(ph, (0, 0), m)
    return out.resize((SIZE, SIZE), Image.LANCZOS)


def thumbs(entries, px=320):
    """Ask Commons for a rendition url per file, 40 files a call.

    Not built by hand: upload.wikimedia.org rejects widths off its own list
    with a 400, and answers requests for the full original with a 429 telling
    you to use a thumbnail. The API knows which url is valid for each file --
    for one already narrower than px, that is the original -- and asking for
    originals is exactly what the CDN throttles, so px is kept small enough
    that almost every file comes back as a real cached thumbnail. 320px is
    ample for a 96px avatar.
    """
    todo = [r for r in entries if r.get('url') and not r.get('thumb')]
    for k in range(0, len(todo), 40):
        chunk = todo[k:k + 40]
        q = json.loads(get(COMMONS + '?' + urllib.parse.urlencode({
            'action': 'query', 'prop': 'imageinfo', 'iiprop': 'url|size',
            'iiurlwidth': px, 'titles': '|'.join(r['file'] for r in chunk),
            'redirects': 1, 'format': 'json', 'formatversion': '2'}))).get('query', {})
        back = {n['to']: n['from'] for n in q.get('normalized', [])}
        url = {}
        for p in q.get('pages', []):
            ii = (p.get('imageinfo') or [{}])[0]
            u = ii.get('thumburl') or ii.get('url')
            if u:
                url[p['title']] = u
                url[back.get(p['title'], p['title'])] = u
        for r in chunk:
            if r['file'] in url:
                r['thumb'] = url[r['file']]


def one(r):
    dest = os.path.join(a.faces, f"{r['node']}.webp")
    if r.get('done') and os.path.exists(dest):
        return (r['name'], None)          # already fetched; a rerun resumes
    try:
        d = get(r.get('thumb') or r['url'])
        im = Image.open(io.BytesIO(d)).convert('RGB')
        c = r.get('crop') or {}
        av = circular(im, c.get('cx', 0.5), c.get('cy', 0.38), c.get('scale', 1.0))
        av.save(dest, 'WEBP', quality=82, method=6)
        r['done'] = True
        return (r['name'], None)
    except Exception as e:
        return (r['name'], str(e)[:80])


thumbs(todo)
json.dump(man, open(a.manifest, 'w'), indent=1)   # keep the urls for a rerun

print(f'{len(todo)} portraits to fetch', flush=True)
res = []
with ThreadPoolExecutor(max_workers=a.workers) as ex:
    for k, x in enumerate(ex.map(one, todo), 1):
        res.append(x)
        if x[1] or k % 20 == 0:
            print(f"  {k}/{len(todo)} {x[0]}{'  FAILED: ' + x[1] if x[1] else ''}", flush=True)
json.dump(man, open(a.manifest, 'w'), indent=1)     # record what landed
bad = [x for x in res if x[1]]
print(f'{len(res)-len(bad)} written, {len(bad)} failed')
for n, e in bad:
    print('  ', n, e)
