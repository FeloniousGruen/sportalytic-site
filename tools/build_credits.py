#!/usr/bin/env python3
"""Write the photo-credits file the page links to.

Every Commons portrait here is freely licensed, but most of them are CC and ask
to be credited, so the attribution has to be reachable from the page rather
than sitting in a manifest in the repo. Only rows whose file was actually
written are listed -- a resolved-but-unfetched entry credits a photo nobody can
see.

Usage: python3 tools/build_credits.py --manifest tools/football_commons_manifest.json \\
                                      --faces assets/foot/faces
"""
import argparse, json, os, re

# Commons' Artist field often holds a wiki signature rather than a name --
# "--Steindy (talk) 15:59, 29 August 2019 (UTC)". The credit owed is to
# Steindy; the timestamp is noise on a page a visitor is reading.
SIG = re.compile(r'\s*\(talk\).*$|\s*\d{1,2}:\d{2},\s+\d{1,2}\s+\w+\s+\d{4}.*$')


def tidy(who):
    return SIG.sub('', (who or '').strip().lstrip('-').strip()).strip(' ,;')

ap = argparse.ArgumentParser()
ap.add_argument('--manifest', required=True)
ap.add_argument('--faces', required=True)
a = ap.parse_args()

man = json.load(open(a.manifest))
rows, missing, seen = [], 0, set()
for r in man:
    if not r.get('url') or r.get('node') is None:
        continue
    if not os.path.exists(os.path.join(a.faces, f"{r['node']}.webp")):
        continue
    # One credit per portrait. A name can be asked for twice under different
    # spellings -- N'Golo Kante with a straight apostrophe and with a curly one
    # -- and resolve to the same player and the same file both times.
    if r['node'] in seen:
        continue
    seen.add(r['node'])
    if not r.get('licence'):
        missing += 1
    # the "File:" prefix is Commons' namespace, not part of the filename
    rows.append({'i': int(r['node']), 'n': r['name'],
                 'f': r['file'].split(':', 1)[-1],
                 'l': r.get('licence') or '?', 'a': tidy(r.get('artist'))})
rows.sort(key=lambda x: x['n'])

out = os.path.join(a.faces, 'credits.json')
json.dump(rows, open(out, 'w'), separators=(',', ':'))
cc = sum(1 for r in rows if r['l'] not in ('Public domain', 'CC0'))
print(f'{len(rows)} portraits credited -> {out} '
      f'({os.path.getsize(out)/1024:.1f} KB); {cc} need attribution')
if missing:
    print(f'WARNING: {missing} rows have no licence -- run --stage licence first')
