#!/usr/bin/env python3
"""Club crests for the first-ring view, and a colour to tint each wedge with.

The "Direct teammates" view fans the centre's teammates into a wedge per club.
Without a crest a wedge is a grey band with three letters on it; with one it is
immediately readable, which is the whole point of that view. The NFL page has
had this since the start -- this brings the football page into line.

Licence, plainly: club crests are TRADEMARKS. They are not freely licensed and
most are not on Commons at all. They are used here nominatively -- to identify
the club whose players are in that wedge -- which is the same basis on which
the NFL page carries its 34 marks, and the page says so in its credits. That is
a deliberate choice rather than an oversight; if it ever needs undoing, delete
assets/foot/logos and the view falls back to the tinted band and lettering with
nothing else to change.

The tint is taken from the crest itself rather than hand-picked, so a wedge and
the mark sitting on it can never disagree. Near-white, near-black and low
saturation pixels are ignored: a crest is mostly outline and background, and
the colour anyone would name is the most common strongly-coloured one.

Usage:
  python3 tools/fetch_crests.py --contact you@example.com
  python3 tools/fetch_crests.py --contact ... --only ARS,LIV   # a few
"""
import argparse, io, json, os, re, sys, time, urllib.parse, urllib.request
from collections import Counter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = 'https://en.wikipedia.org/w/api.php'

ap = argparse.ArgumentParser()
ap.add_argument('--data', default=os.path.join(HERE, 'assets', 'foot'))
ap.add_argument('--out', default=None, help='defaults to <data>/logos')
ap.add_argument('--contact', required=True,
                help='email or url for the User-Agent, per Wikimedia robot policy')
ap.add_argument('--size', type=int, default=200)
ap.add_argument('--delay', type=float, default=0.4)
ap.add_argument('--only', default='', help='comma-separated club codes')
a = ap.parse_args()
OUT = a.out or os.path.join(a.data, 'logos')
UA = {'User-Agent': f'sportalytic-network/1.0 ({a.contact}; club marks for a '
                    f'teammate graph) python-urllib'}
_last = [0.0]


def get(url, tries=5):
    for k in range(tries):
        wait = a.delay - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=45).read()
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(1 + k)


def api(**p):
    p.setdefault('format', 'json'); p.setdefault('formatversion', '2')
    return json.loads(get(API + '?' + urllib.parse.urlencode(p)))


tab = json.load(open(os.path.join(a.data, 'tables.json')))
meta = tab['teamMeta']
codes = [c for c in tab['teams']]
if a.only:
    want = {x.strip().upper() for x in a.only.split(',')}
    codes = [c for c in codes if c in want]

# A club's article title is not always its name in the data. Where the plain
# name is a disambiguation or a different subject entirely, say so here.
TITLE = {
    'Accrington F.C.': 'Accrington F.C.', 'Arsenal': 'Arsenal F.C.',
    'Barnsley': 'Barnsley F.C.', 'Blackpool': 'Blackpool F.C.',
    'Brentford': 'Brentford F.C.', 'Burnley': 'Burnley F.C.',
    'Bury': 'Bury F.C.', 'Chelsea': 'Chelsea F.C.', 'Darwen': 'Darwen F.C.',
    'Everton': 'Everton F.C.', 'Fulham': 'Fulham F.C.',
    'Liverpool': 'Liverpool F.C.', 'Middlesbrough': 'Middlesbrough F.C.',
    'Millwall': 'Millwall F.C.', 'Portsmouth': 'Portsmouth F.C.',
    'Reading': 'Reading F.C.', 'Southampton': 'Southampton F.C.',
    'Sunderland': 'Sunderland A.F.C.', 'Watford': 'Watford F.C.',
    'Wimbledon': 'Wimbledon F.C.', 'Bradford Park Avenue': 'Bradford (Park Avenue) A.F.C.',
    'Leyton Orient': 'Leyton Orient F.C.', 'Glossop North End': 'Glossop North End A.F.C.',
    'AFC Bournemouth': 'AFC Bournemouth',
}

# Clubs whose article carries no usable mark. Burnley's best-scoring file was a
# black-and-white team photograph from 1889-90; better no crest than a
# photograph pretending to be one. The wedge falls back to a tinted band and
# its three letters, which is what every club had before this existed.
NO_CREST = {'BUR'}


# Junk that appears on every club article and is never the crest.
JUNK = re.compile(r'commons|wiki|symbol|ambox|question|edit-|padlock|flag|'
                  r'stadium|ground|map|portal|sport|football_?pitch|kit_|'
                  r'red_pog|blue_pog|location|speaker|folder|'
                  # charts named after the club scored as well as the crest did:
                  # "Accrington FC league results 1889-1893", "ManchesterCityFC
                  # League Performance". They are not marks.
                  r'result|performance|chart|graph|attendance|position|'
                  r'history|season|table|record|home_?shirt|away_?shirt', re.I)
CREST = re.compile(r'crest|badge|logo|\bfc\b|\bafc\b', re.I)


def crest_url(club):
    """The crest file used on the club's article.

    NOT PageImages. That prefers a freely licensed image, and a club crest is
    not free -- so on Everton and Manchester City it returned nothing at all,
    and on Arsenal it handed back a photograph, whose dominant colour is brown.
    The crest is in the article's file list; it is picked out by name.
    """
    title = TITLE.get(club, club + ' F.C.')
    words = [w.lower() for w in re.split(r'[^A-Za-z]+', club) if len(w) > 2]
    for t in (title, club):
        q = api(action='query', prop='images', imlimit='max', titles=t, redirects=1
                ).get('query', {}).get('pages', [])
        if not q or 'images' not in (q[0] or {}):
            continue
        cand = [i['title'] for i in q[0]['images']
                if i['title'].lower().endswith(('.png', '.svg'))
                and not JUNK.search(i['title'])]

        def score(c):
            k = c.lower()
            # an explicit crest/badge/logo in the name outweighs the club
            # name appearing, which any chart about the club also has
            # The club's own name must be in the filename. Without that gate
            # "logo" alone was enough, and both Watford and West Ham came back
            # with File:National Rail logo.svg -- the nearest station.
            hits = sum(1 for w in words if w in k)
            if not hits:
                return 0
            return hits + (6 if CREST.search(k) else 0)
        cand.sort(key=lambda c: (-score(c), len(c)))
        if not cand or score(cand[0]) < 6:
            continue
        # a thumbnail url, which renders SVG to PNG and works for non-free files
        ii = api(action='query', prop='imageinfo', iiprop='url',
                 iiurlwidth=a.size, titles=cand[0], redirects=1
                 ).get('query', {}).get('pages', [])
        if not ii or not ii[0].get('imageinfo'):
            continue
        info = ii[0]['imageinfo'][0]
        u = info.get('thumburl') or info.get('url')
        if u:
            return u, cand[0]
    return None, None


def tint(im):
    """The colour anyone would name the club by, taken from its own crest."""
    small = im.convert('RGBA').resize((64, 64))
    c = Counter()
    for r, g, b, alpha in list(small.getdata()):
        if alpha < 128:
            continue
        mx, mn = max(r, g, b), min(r, g, b)
        if mx < 40 or mn > 215:          # near-black outline, near-white ground
            continue
        if mx - mn < 45:                 # grey: not what anyone calls it
            continue
        c[(r // 24 * 24, g // 24 * 24, b // 24 * 24)] += 1
    if not c:
        return '#8A97A6'
    r, g, b = c.most_common(1)[0][0]
    return '#%02X%02X%02X' % (min(r + 12, 255), min(g + 12, 255), min(b + 12, 255))


# Where the crest's own pixels do not give the colour anyone would name it by.
# Liverpool's came out pale cyan off the anti-aliasing round a mostly-red mark;
# Derby, Swansea and Notts County are black-and-white crests, where "the most
# saturated colour" is meaningless and the extractor falls back to grey.
TINT_OVERRIDE = {
    'LIV': '#C8102E', 'TOT': '#132257', 'DER': '#1D2B39', 'SWA': '#121212',
    'NOT': '#1B1B1B', 'FUL': '#1B1B1B', 'NEW': '#1B1B1B', 'GRI': '#1B1B1B',
}

from PIL import Image

os.makedirs(OUT, exist_ok=True)
cpath = os.path.join(OUT, 'colours.json')
colours = json.load(open(cpath)) if os.path.exists(cpath) else {}
ok, miss = [], []
for code in codes:
    if code in NO_CREST:
        miss.append((code, meta[code]['name'], 'article has no usable mark')); continue
    club = meta[code]['name']
    dest = os.path.join(OUT, f'{code}.png')
    if os.path.exists(dest) and code in colours:
        ok.append(code); continue
    try:
        url, title = crest_url(club)
        if not url:
            miss.append((code, club, 'no crest found on the article')); continue
        im = Image.open(io.BytesIO(get(url.split('?')[0]))).convert('RGBA')
        # square it on transparency so every wedge gets the same treatment
        s = max(im.size)
        pad = Image.new('RGBA', (s, s), (0, 0, 0, 0))
        pad.paste(im, ((s - im.width) // 2, (s - im.height) // 2), im)
        pad = pad.resize((a.size, a.size), Image.LANCZOS)
        pad.save(dest, 'PNG', optimize=True)
        colours[code] = TINT_OVERRIDE.get(code) or tint(pad)
        ok.append(code)
        print(f'  {code:5s} {club:26s} {colours[code]}  {title}', flush=True)
    except Exception as e:
        miss.append((code, club, str(e)[:70]))

json.dump(colours, open(cpath, 'w'), indent=1, sort_keys=True)
json.dump(sorted(ok), open(os.path.join(OUT, 'index.json'), 'w'))
print(f'\n{len(ok)} crests in {OUT}, {len(miss)} missing')
for c, club, why in miss:
    print(f'  MISSING {c:5s} {club:26s} {why}')
print('Club crests are trademarks of their clubs, used here to identify them.')
