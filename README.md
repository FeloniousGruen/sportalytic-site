# Sportalytic — one-page site

Static, no build step. `index.html` plus `assets/`, served from the repo root.

## Deploying

Connected to Netlify: pushing to `main` redeploys the site automatically.
`netlify.toml` tells Netlify there's nothing to build and sets cache headers.

To edit: change `index.html`, commit, push. That's the whole workflow.

```
git add -A
git commit -m "what changed"
git push
```

## Before publishing, change these

1. **Facts strip** — "1m+ views on a single reel" needs checking against your
   own analytics. The other three are safe.
2. **Form endpoint** — already set to `https://formspree.io/f/xvkprqjo` in
   `FORM_ENDPOINT`, near the top of the `<script>` block at the bottom of
   `index.html`. Change that one line if you ever move provider. Send a test
   through the live site after deploying; Formspree activates a form on its
   first submission.

3. **Email address** — `sportalyticmedia@gmail.com` appears twice.
4. **Film blurbs** — the `FILMS` array near the bottom of `index.html` holds the
   title, sport, description and source line for each tile. I wrote these from
   watching the videos; correct anything I got wrong.

## The interactive network page

`network.html` is a second, standalone page: every NFL player since 1920 as a
graph, click anyone to see their path to the centre or make them the centre.
It is separate from `index.html` so its code and data land in the immutable
`/assets` cache rather than the no-cache HTML.

It re-roots the graph on any player, which needs a breadth-first pass over the
real teammate relation. All 2.2M teammate edges are implied by 128k membership
rows, so the bipartite player <-> (team, season) index ships instead: 0.4 MB
rather than 7.9 MB, traversed in ~2 ms. Nothing is computed server-side.

Rebuilding the data (only needed when the source CSVs change):

```
python3 tools/fetch_season.py --season 2027 --out memberships.csv   # add a season
python3 tools/build_network_data.py --rosters memberships.csv       # -> assets/net/
python3 tools/fetch_faces.py --rosters memberships.csv              # -> assets/net/faces/
```

`build_network_data.py` must be rerun before `fetch_faces.py` if the player list
changed: portraits are named by node index.

Two judgement calls to be aware of before this goes live. The club marks in
`assets/net/logos/` are trademarks. And the 2026 rows are opening rosters, not
games played -- those players have not appeared in a regular-season game.

## Assets

The site is one file with two views: the landing page, and `#/reels` for the work.
To split them into real pages later, copy `index.html` twice and delete the
unused `<main>` from each.

Each reel has an 8-second silent loop in two formats (`assets/<id>.mp4` and
`assets/<id>.webm`, ~400 px wide) cut from
the **start** of the reel, so the hook is what plays, plus a poster frame
(`assets/<id>.jpg`) taken from the payoff. To swap in a new film, add both files,
then add an entry to `FILMS`.

Re-cutting a loop from a full reel:

```
ffmpeg -t 8 -i reel.mp4 -an -vf "scale=400:-2,fps=24" \
  -c:v libx264 -crf 32 -preset veryslow -pix_fmt yuv420p -movflags +faststart out.mp4
ffmpeg -t 8 -i reel.mp4 -an -vf "scale=400:-2,fps=24" \
  -c:v libvpx-vp9 -crf 42 -b:v 0 -row-mt 1 -cpu-used 3 out.webm
ffmpeg -ss <poster_time> -i reel.mp4 -frames:v 1 -vf scale=400:-2 -q:v 7 out.jpg
```

WebM exists because some browsers ship without H.264; the page picks whichever
it can play. Whole folder is under 2 MB.
