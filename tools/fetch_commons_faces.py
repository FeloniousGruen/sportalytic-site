#!/usr/bin/env python3
"""Portraits from Wikimedia Commons, for both networks.

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
ap.add_argument('--stage', choices=['resolve', 'licence', 'fetch'], required=True)
ap.add_argument('--sport', choices=['nfl', 'football'], default='nfl',
                help='which game, which changes the search term and the test '
                     'that an article is about the right kind of player')
ap.add_argument('--names', help='one player name per line (resolve)')
ap.add_argument('--rosters', help='memberships csv, for careers (resolve). '
                'Omit to read the careers straight out of graph.bin.gz, which '
                'is index-aligned with names.txt.gz and needs no join.')
ap.add_argument('--data', default='assets/net')
ap.add_argument('--out', default='commons_manifest.json')
ap.add_argument('--manifest')
ap.add_argument('--faces', default='assets/net/faces')
ap.add_argument('--workers', type=int, default=2)
ap.add_argument('--delay', type=float, default=0.7,
                help='minimum seconds between API calls; Wikimedia throttles bursts')
ap.add_argument('--contact', default='https://github.com/FeloniousGruen/sportalytic-site',
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


# What to search for, and how to tell the article really is about the right
# sport. A name like Alan Smith or David Jones has holders in several codes, so
# the test has to exclude as well as include.
#
# Getting this right took four goes, each failure worth recording:
#   - requiring the word "footballer" lost David O'Leary, whose article opens
#     "is a football manager and former player";
#   - excluding any article mentioning rugby lost Ryan Giggs, whose father
#     played it;
#   - not excluding disambiguation pages meant "Alan Ball" matched the page
#     that merely lists the Alan Balls, which mentions every code at once;
#   - and demanding the title equal the name exactly lost Alan Ball Jr., since
#     that is what the England midfielder's article is called.
FOOT_NO = re.compile(r'american football|australian rules|gaelic football|'
                     r'rugby (league|union)|baseball|ice hockey|'
                     r'national football league|\bnfl\b|'
                     r'cornerback|quarterback|linebacker|wide receiver|'
                     r'running back|tight end|defensive end')
SPORT = {
    'nfl': {
        'search': '{} American football',
        'ok': lambda t: 'football' in t,
        'no': lambda t: False,
    },
    'football': {
        'search': '{} footballer',
        # "football" alone: manager, player, club, whichever the sentence uses
        'ok': lambda t: 'football' in t or 'soccer' in t,
        'no': lambda t: bool(FOOT_NO.search(t)),
    },
}[a.sport]

# Titles Wikipedia hangs a suffix on. Frank Lampard and Frank Lampard Sr. are
# two real players and both are in this graph, so a suffix must not be treated
# as noise -- it is allowed to match, and the career-years check below decides
# which node it belongs to.
SUFFIX = re.compile(r'(jr|jnr|junior|sr|snr|senior)$')


def title_rank(title, name):
    """0 for an exact title, 1 for one carrying a Jr/Sr suffix, None for neither.

    The two are tried in that order rather than together. Allowing suffixes at
    all is what finds Alan Ball Jr. for "Alan Ball"; trying them at the same
    priority is what let "Frank Lampard Sr." answer to "Frank Lampard" while
    the article about the son sat one hit further down the list.
    """
    t = key(title.split('(')[0])
    n = key(name)
    if t == n:
        return 0
    if t.startswith(n) and SUFFIX.fullmatch(t[len(n):]):
        return 1
    return None


def key(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z]', '', s.lower())


# Files that turn up on every article and are never the player.
JUNK = re.compile(r'logo|icon|map|flag|helmet|stub|ambox|commons|wiki|banner|'
                  r'symbol|seal|emblem|arrow|edit|padlock|question|blank|'
                  r'sound|speaker|nfl_?100|hall of fame|trophy|crest|badge|'
                  r'kit_?body|kit_?shorts|kit_?socks|premier ?league|'
                  r'football ?league|stadium|ground', re.I)


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
def resolve(name, spans, unique=False):
    """spans: list of (node index, first season, last season) sharing this name.

    `unique` says this name belongs to exactly one player in the whole graph,
    which is what makes it safe to accept an article whose years cannot be
    matched to the career. Where a name is shared, that check has to stand: it
    is the only thing that stopped the Vikings Adrian Peterson's photograph
    being filed against the Bears one.
    """
    hits = api(action='query', list='search',
               srsearch=SPORT['search'].format(name),
               srlimit=6).get('query', {}).get('search', [])
    ranked = [(title_rank(h['title'], name), k, h) for k, h in enumerate(hits)]
    ranked = sorted((r for r in ranked if r[0] is not None))
    for _, _, h in ranked:
        title = h['title']
        # Not exintro. One opening sentence carries a birth year and little
        # else, and the career-years test below needs seasons to test against
        # -- which is how the two Frank Lampards ended up indistinguishable.
        pg = api(action='query', prop='pageimages|extracts|pageprops',
                 exchars=1500, explaintext=1, piprop='original',
                 titles=title, redirects=1).get('query', {}).get('pages', [])
        if not pg:
            continue
        p = pg[0]
        # A disambiguation page passes every text test there is -- it lists a
        # footballer, an American footballer and a screenwriter in one
        # paragraph -- and carries no usable photo. pageprops says so outright.
        if 'disambiguation' in (p.get('pageprops') or {}):
            continue
        text = p.get('extract', '')
        # Which sport, from the opening sentence only -- that is where the
        # article says what the subject is. Run over the whole extract instead
        # and Ryan Giggs is thrown out for the paragraph about his father's
        # rugby league career. The full text is still used for the years below.
        low = text[:400].lower()
        if not SPORT['ok'](low) or SPORT['no'](low):
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
        if years and overlap(best) == 0 and not unique:
            return {'name': name, 'title': title,
                    'skip': f'the article describes no season this player '
                            f'({best[1]}-{best[2]}) was playing'}
        return {'name': name, 'node': node, 'title': title, 'url': orig,
                'file': fname, 'why': why,
                'span': f'{spans[0][1]}-{spans[0][2]}' if len(spans) == 1 else
                        next(f'{s[1]}-{s[2]}' for s in spans if s[0] == node),
                'summary': text[:220].replace('\n', ' ')}
    return {'name': name, 'skip': 'no article whose title matches and is about the right sport'}


def spans_from_graph(data):
    """first/last season per node, straight out of the shipped binary.

    The NFL path rebuilds these from the memberships CSV because it also has to
    apply the PFR alias merge before grouping. There is no such join here, and
    graph.bin.gz already carries the two arrays index-aligned with the names --
    so for anything else this is both simpler and guaranteed to agree with what
    the page is actually drawing.
    """
    import struct
    buf = gzip.open(os.path.join(data, 'graph.bin.gz'), 'rb').read()
    assert buf[:8] == b'SPNET001', 'unexpected graph file'
    P, T = struct.unpack_from('<ii', buf, 8)
    # header, then p_ip, p_ix, t_ip, t_ix, then the two season arrays. Each
    # index array's length is the last entry of the pointer array before it.
    o = 16
    o += (P + 1) * 4 + struct.unpack_from('<i', buf, o + P * 4)[0] * 4
    o += (T + 1) * 4 + struct.unpack_from('<i', buf, o + T * 4)[0] * 4
    first = struct.unpack_from(f'<{P}h', buf, o); o += P * 2
    last = struct.unpack_from(f'<{P}h', buf, o)
    return {i: (int(first[i]), int(last[i])) for i in range(P)}


def licences(rows):
    """Fill in licence and author for every accepted file, 40 titles a request.

    Its own step, because it used to run only after the whole resolve loop had
    finished -- so stopping a long run early left every checkpointed entry
    without the attribution Commons reuse requires. Rows that already have one
    are left alone, which makes this cheap to re-run.
    """
    need = [r for r in rows if r.get('url') and not r.get('licence')]
    for k in range(0, len(need), 40):
        chunk = need[k:k + 40]
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
    return rows


if a.stage == 'resolve':
    names = [l.strip() for l in open(a.names) if l.strip()]
    allnames = gzip.open(os.path.join(a.data, 'names.txt.gz'), 'rb').read().decode().split('\n')
    flags = gzip.open(os.path.join(a.data, 'faces.bin.gz'), 'rb').read()

    # Careers, in the graph's own node order, so a name shared by several
    # players can be pinned to the one the article is about. That matters far
    # more for football than for the NFL: identity there is name-based before
    # 1992 and 635 names are already split into two or more people.
    if a.rosters:
        import pandas as pd
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
    else:
        span = spans_from_graph(a.data)
        assert len(span) == len(allnames), f'{len(span)} nodes vs {len(allnames)} names'

    spans_by_key = {}
    for i, n in enumerate(allnames):
        spans_by_key.setdefault(key(n), []).append(i)

    # Resume: a run of this size is the better part of an hour, and losing it to
    # a dropped connection or a change of mind would be wasteful. Whatever is
    # already in the output file is kept and not asked for again.
    out, seen = [], set()
    if os.path.exists(a.out):
        try:
            out = json.load(open(a.out))
            seen = {r['name'] for r in out}
            print(f'resuming: {len(seen)} names already resolved in {a.out}')
        except Exception:
            out, seen = [], set()

    jobs = []
    for nm in names:
        if nm in seen:
            continue
        all_ix = spans_by_key.get(key(nm), [])
        ix = [i for i in all_ix if not flags[i]]
        jobs.append((nm, [(i, *span[i]) for i in ix] or None, len(all_ix) == 1))
    print(f'{len(jobs)} names to resolve', flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for k, r in enumerate(ex.map(
                lambda j: ({'name': j[0], 'skip': 'not in the graph, or already has a photo'}
                           if j[1] is None else resolve(j[0], j[1], j[2])), jobs), 1):
            out.append(r)
            print(('  ok   ' if 'url' in r else '  SKIP ') + r['name'] +
                  ('' if 'url' in r else ' -- ' + r['skip']), flush=True)
            if k % 25 == 0:                  # checkpoint, so a stop costs 25 names
                json.dump(out, open(a.out, 'w'), indent=1)
    licences(out)
    json.dump(out, open(a.out, 'w'), indent=1)
    ok = [r for r in out if 'url' in r]
    print(f'\n{len(ok)} of {len(out)} resolved to a Commons image -> {a.out}')
    for lic in sorted({r.get('licence', '?') for r in ok}):
        print(f"   {sum(1 for r in ok if r.get('licence','?')==lic):3d}  {lic}")
    sys.exit(0)

if a.stage == 'licence':
    man = json.load(open(a.manifest or a.out))
    licences(man)
    json.dump(man, open(a.manifest or a.out, 'w'), indent=1)
    ok = [r for r in man if 'url' in r]
    print(f'{sum(1 for r in ok if r.get("licence"))} of {len(ok)} now carry a licence')
    for lic in sorted({r.get('licence', '?') for r in ok}):
        print(f"   {sum(1 for r in ok if r.get('licence','?')==lic):3d}  {lic}")
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
