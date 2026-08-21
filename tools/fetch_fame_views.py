#!/usr/bin/env python3
"""How well known is each player, measured rather than assumed.

The puzzle builder used to rank fame by career top-flight appearances, which is
the only fame-ish number the source carries. It does not work. Steve Potts made
297 appearances for West Ham and nobody outside the Boleyn could name him;
Jean-Ricner Bellegarde made 83 and is a Premier League regular; Eric Cantona
made 159. Appearances measure a career, not a reputation, and a round built on
them hands you two men you have never heard of and calls it a puzzle.

Wikipedia traffic measures the reputation directly: it is how many people went
looking for this person. So this script resolves each candidate to their
article and records views over the last 60 days, into tools/football_views.json.

Two things it has to get right, both of which cost a false reading otherwise:

  * the name alone is often a disambiguation page -- "Danny Rose" and "Steve
    Potts" both are -- and a disambiguation page gets almost no traffic, so
    taking it at face value would rule out a well-known player for being
    obscure. Anything that lands on one goes to a search.
  * the name alone is often the WRONG person -- there is a "Danny Williams"
    in most walks of life -- and that error runs the other way, letting a
    journeyman into the pool on a musician's traffic. So every article has to
    describe a footballer, and its birth year has to fit the career we hold.

Written a batch at a time, resumable: an interrupt costs the current batch of
fifty and nothing else.

Usage: python3 tools/fetch_fame_views.py [--limit N] [--contact you@example.com]
"""
import argparse, json, os, re, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request
import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = 'https://en.wikipedia.org/w/api.php'
OUT = os.path.join(HERE, 'tools', 'football_views.json')

ap = argparse.ArgumentParser()
ap.add_argument('--modern-from', type=int, default=2011)
ap.add_argument('--modern-apps', type=int, default=60)
ap.add_argument('--historic-apps', type=int, default=180)
ap.add_argument('--limit', type=int, default=0, help='stop after N new players')
ap.add_argument('--delay', type=float, default=0.4)
ap.add_argument('--contact', default='https://sportalytic.co.uk')
a = ap.parse_args()

UA = {'User-Agent': f'sportalytic-fame/1.0 ({a.contact}; ranking a teammate '
                    f'graph by article traffic) python-urllib'}
_last = [0.0]


def get(url, tries=8):
    for k in range(tries):
        wait = a.delay - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=45).read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or k == tries - 1:
                raise
            time.sleep(float(e.headers.get('Retry-After') or 0) or min(8, 2 + k))
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(1 + k)


def api(**p):
    p.setdefault('format', 'json')
    p.setdefault('formatversion', '2')
    return json.loads(get(API + '?' + urllib.parse.urlencode(p)))


# Same exclusions as the portrait resolver, and for the same reason: Alan
# Smith, David Jones and Danny Williams all have holders in several codes.
NOT_FOOT = re.compile(r'american football|australian rules|gaelic|'
                      r'rugby|baseball|ice hockey|cricketer|\bnfl\b')
YEARS = re.compile(r'\((?:born\s+)?(?:\d+\s+\w+\s+)?(\d{4})')


def looks_right(desc, first, last):
    """Is this article about the footballer whose career we are holding?

    The short description is doing two jobs -- "English footballer (born 1994)"
    says both what he is and when he was born -- and both are needed. A player
    debuts somewhere between 15 and 35 years after birth; outside that it is a
    different man of the same name, which is the error that matters, because it
    would put someone nobody has heard of into the round on borrowed traffic.
    """
    if not desc:
        return False
    d = desc.lower()
    if 'referred to by the same term' in d:      # disambiguation
        return False
    if NOT_FOOT.search(d):
        return False
    if not ('footballer' in d or 'football' in d or 'soccer' in d):
        return False
    m = YEARS.search(desc)
    if m:
        born = int(m.group(1))
        # a death year can be the first number for "(1925-2011)"-style
        # descriptions, but those open with the birth, so this is the birth
        if not (15 <= first - born <= 35):
            return False
    return True


def key(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z]', '', s.lower())


def views_of(page):
    pv = page.get('pageviews') or {}
    return sum(v for v in pv.values() if v)


def fetch(titles):
    """{requested title: page dict} for up to 50 titles, redirects followed.

    Continuation is not optional here, and getting that wrong is quiet rather
    than loud: prop=pageviews pages out at around 48 articles, and the rest of
    the batch comes back as perfectly good page objects with the pageviews key
    simply absent -- which reads as "nobody visits this article" rather than as
    an error. A first run had Les Ferdinand, Gary Mabbutt and Des Walker on
    zero traffic and would have thrown all three out of the game.
    """
    args = dict(action='query', prop='pageviews|description|pageprops',
                ppprop='disambiguation', pvipdays=60, redirects=1,
                titles='|'.join(titles))
    merged, back, cont = {}, {}, {}
    for _ in range(8):
        r = api(**dict(args, **cont))
        q = r.get('query', {})
        for red in q.get('redirects', []):
            back.setdefault(red['to'], []).append(red['from'])
        for norm in q.get('normalized', []):
            back.setdefault(norm['to'], []).append(norm['from'])
        for p in q.get('pages', []):
            m = merged.setdefault(p['title'], {})
            for k, v in p.items():
                # later rounds carry the props the earlier ones ran out of room
                # for; an empty dict must not overwrite a full one
                if v or k not in m:
                    m[k] = v
        cont = r.get('continue') or {}
        if not cont:
            break
    out = {}
    for t, p in merged.items():
        for src in [t] + back.get(t, []):
            out[src] = p
        # a redirect chain: name -> normalised -> target
        for src in back.get(t, []):
            for s2 in back.get(src, []):
                out[s2] = p
    return out


def search(name, first, last):
    """Fall back to a search when the plain name is not the player's article."""
    r = api(action='query', list='search', srsearch=f'{name} footballer',
            srlimit=6, srnamespace=0)
    hits = [h['title'] for h in r.get('query', {}).get('search', [])]
    if not hits:
        return None, 0
    pages = fetch(hits[:6])
    best, best_v = None, 0
    n = key(name)
    for t in hits:
        p = pages.get(t)
        if not p or 'missing' in p:
            continue
        if not looks_right(p.get('description'), first, last):
            continue
        # the article's own title still has to be this man's name; a search for
        # "Bobby Craig footballer" will happily return the club he played for
        bare = key(p['title'].split('(')[0])
        if not (bare == n or bare.startswith(n) or n.startswith(bare)):
            continue
        v = views_of(p)
        if v > best_v:
            best, best_v = p['title'], v
    return best, best_v


# ----------------------------------------------------------------- players ---
fame = pd.read_csv(os.path.join(HERE, 'tools', 'football_fame.csv'))
want = fame[((fame['last'] >= a.modern_from) & (fame.apps >= a.modern_apps))
            | (fame.apps >= a.historic_apps)]
done = json.load(open(OUT)) if os.path.exists(OUT) else {}
todo = [r for r in want.itertuples() if str(r.uid) not in done]
if a.limit:
    todo = todo[:a.limit]
print(f'{len(want)} candidates, {len(done)} already held, {len(todo)} to fetch',
      flush=True)

BATCH = 50
for s in range(0, len(todo), BATCH):
    chunk = todo[s:s + BATCH]
    # duplicate names in one batch would collapse into a single page entry, and
    # they want the same article anyway, so ask once and read it twice
    pages = fetch(sorted({r.name for r in chunk}))
    for r in chunk:
        p = pages.get(r.name)
        rec = None
        if p and 'missing' not in p and not (p.get('pageprops') or {}).get('disambiguation') \
                and looks_right(p.get('description'), r.first, r.last):
            rec = {'title': p['title'], 'views': views_of(p), 'how': 'direct'}
        else:
            t, v = search(r.name, r.first, r.last)
            rec = ({'title': t, 'views': v, 'how': 'search'} if t
                   else {'title': None, 'views': 0, 'how': 'none'})
        rec['node'] = int(r.node)
        rec['name'] = r.name
        done[str(r.uid)] = rec
    json.dump(done, open(OUT, 'w'), indent=0, sort_keys=True)
    got = sum(1 for r in chunk if done[str(r.uid)]['views'] > 0)
    print(f'  {s + len(chunk)}/{len(todo)}  {got}/{len(chunk)} resolved',
          flush=True)

print(f'{OUT}  {len(done)} players, '
      f'{sum(1 for v in done.values() if v["views"] > 0)} with traffic')
