#!/usr/bin/env python3
"""Draw the link-preview card: the real network, rendered from the real data.

A messenger or a chat app shows whatever og:image points at. Without one it
falls back to the favicon and scales a 192px mark up to card size, which is
what made the preview look so poor.

This reads the same graph.bin.gz the page reads and repeats the same
breadth-first pass and radial layout, so the card is the chart rather than an
impression of it. Drawn at 3x and reduced with LANCZOS, which is what gives the
rings their soft edge -- the same trick the reels use.

Usage: python3 tools/make_share_image.py
"""
import gzip, os, struct
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(HERE, 'assets', 'net')

W, H, SS = 1200, 630, 3
BG = (11, 17, 23)
AMBER = (251, 194, 71)
DEG_COLOUR = ['#2e2e2e', '#f4b400', '#6a5acd', '#23b5d3', '#ff7f50',
              '#ff4fa3', '#7cc943', '#2ec4b6', '#c77dff', '#ff9f1c',
              '#00a8ff', '#7a7a7a']
RING_GAP = 1.6
CENTRE_NAME = 'Travis Kelce'


def rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ------------------------------------------------------------------ data ----
buf = gzip.open(os.path.join(NET, 'graph.bin.gz'), 'rb').read()
assert buf[:8] == b'SPNET001', 'unexpected graph file'
P, T = struct.unpack_from('<ii', buf, 8)
o = 16


def i32(n):
    global o
    a = np.frombuffer(buf, np.int32, n, o); o += n * 4; return a


p_ip = i32(P + 1); p_ix = i32(int(p_ip[P]))
t_ip = i32(T + 1); t_ix = i32(int(t_ip[T]))

names = gzip.open(os.path.join(NET, 'names.txt.gz'), 'rb').read().decode().split('\n')
centre = names.index(CENTRE_NAME)

# ------------------------------------------------------- the same traversal --
dist = np.full(P, -1, np.int32)
parent = np.full(P, -1, np.int32)
order = np.zeros(P, np.int32)
seen_ts = np.zeros(T, bool)
dist[centre] = 0
order[0] = centre
head, tail = 0, 1
while head < tail:
    u = order[head]; head += 1
    d = dist[u] + 1
    for i in range(p_ip[u], p_ip[u + 1]):
        ts = p_ix[i]
        if seen_ts[ts]:
            continue
        seen_ts[ts] = True
        for j in range(t_ip[ts], t_ip[ts + 1]):
            v = t_ix[j]
            if dist[v] < 0:
                dist[v] = d; parent[v] = u; order[tail] = v; tail += 1
reached = tail

# ------------------------------------------------------- the same layout ----
leaves = np.zeros(P, np.int64)
for k in range(reached - 1, -1, -1):
    u = order[k]
    if leaves[u] == 0:
        leaves[u] = 1
    p = parent[u]
    if p >= 0:
        leaves[p] += leaves[u]

angle = np.zeros(P); radius = np.zeros(P)
wA0 = np.zeros(P); wSpan = np.zeros(P); wAcc = np.zeros(P)
wSpan[centre] = 2 * np.pi
for k in range(1, reached):
    u = order[k]; p = parent[u]
    w = wSpan[p] * (leaves[u] / leaves[p])
    start = wA0[p] + wAcc[p]
    wAcc[p] += w
    wA0[u] = start; wSpan[u] = w; wAcc[u] = 0.0
    angle[u] = start + w / 2
    radius[u] = dist[u] + RING_GAP

px = radius * np.cos(angle)
py = radius * np.sin(angle)

rs = np.sort(np.hypot(px[:], py[:])[dist >= 0])
r99 = rs[int(len(rs) * 0.999)]

# ------------------------------------------------------------------ draw ----
cw, ch = W * SS, H * SS
im = Image.new('RGB', (cw, ch), BG)
dr = ImageDraw.Draw(im, 'RGBA')

# the chart sits right of centre, leaving the left third for the words
cx, cy = int(cw * 0.68), ch // 2
scale = (ch / 2) / r99 * 0.86


def sx(x): return cx + x * scale
def sy(y): return cy + y * scale


for k in range(1, reached):
    u = order[k]; p = parent[u]
    dr.line((sx(px[p]), sy(py[p]), sx(px[u]), sy(py[u])),
            fill=(150, 168, 194, 46), width=max(1, SS // 2))

r = max(2, int(SS * 1.7))
for k in range(reached):
    u = order[k]
    c = rgb(DEG_COLOUR[min(int(dist[u]), len(DEG_COLOUR) - 1)])
    x, y = sx(px[u]), sy(py[u])
    dr.ellipse((x - r, y - r, x + r, y + r), fill=c)

im = im.resize((W, H), Image.LANCZOS)
dr = ImageDraw.Draw(im, 'RGBA')

# the centre's portrait, if there is one
face = os.path.join(NET, 'faces', f'{centre}.webp')
if os.path.exists(face):
    d = 96
    ph = Image.open(face).convert('RGBA').resize((d, d), Image.LANCZOS)
    im.paste(ph, (int(cx / SS) - d // 2, int(cy / SS) - d // 2), ph)

# ----------------------------------------------------------------- words ----
def font(sz):
    for p in ('/System/Library/Fonts/Supplemental/Arial Black.ttf',
              '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
              '/System/Library/Fonts/Supplemental/Arial.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


x0, y0 = 62, 196
CARDS = [
    ('share-network.jpg', '11 DEGREES OF', 'TRAVIS KELCE',
     'Every NFL player since 1920,\njoined wherever two of them\nshared a squad.'),
    ('share.jpg', 'SPORT,', 'IN NUMBERS',
     'Reels, carousels and stills that\nmake the numbers worth\nwatching.'),
]
for fname, l1, l2, body in CARDS:
    card = im.copy()
    d2 = ImageDraw.Draw(card, 'RGBA')
    d2.text((x0, y0), l1, font=font(46), fill=(255, 255, 255))
    d2.text((x0, y0 + 56), l2, font=font(46), fill=AMBER)
    d2.text((x0, y0 + 134), body, font=font(21), fill=(174, 186, 198), spacing=9)
    d2.text((x0, y0 + 252), 'SPORTALYTIC', font=font(18), fill=(108, 122, 136))
    out = os.path.join(HERE, 'assets', fname)
    card.save(out, 'JPEG', quality=88, optimize=True)
    print(f'{out}  {os.path.getsize(out) / 1024:.0f} KB  {W}x{H}')
print(f'{reached} players drawn')
