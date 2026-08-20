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

"Test your knowledge" gives you two players and asks you to join them yourself.
Each name you add is checked against the record -- two players are linked only
if they shared a squad in the same season -- and at the end your chain is
compared with the shortest one there is. The answer comes from `NET.route`,
which runs the search and puts the layout back before returning: recentring on
one of the two would give the other's degree away just by which ring it landed
in. Random opponents are drawn from players who have a portrait and at least
four seasons, which is the difference between a game and an exercise in naming
practice-squad receivers.

Any equally short route counts, not only the one the chart drew. Each link you
add is checked on its own -- did these two share a squad that season -- and the
verdict compares your length with the shortest that exists, so a chain nobody
would have guessed scores the same as the tree's. Bo Jackson to Travis Kelce
via Bill Pickel, Aaron Glenn and Dunta Robinson is four steps, and so is the
drawn route through Bill Lewis, Drew Bledsoe and Anthony Fasano.

The clue button names the club the next player shares with you, then the
season. It recomputes from wherever you have got to, so it stays useful once
you have wandered off the drawn route.

Rebuilding the data (only needed when the source CSVs change):

```
python3 tools/fetch_season.py --season 2027 --out memberships.csv     # add a season
python3 tools/build_pfr_aliases.py --rosters memberships.csv          # -> tools/pfr_aliases.csv
python3 tools/build_network_data.py --rosters memberships.csv         # -> assets/net/
python3 tools/remap_faces.py --rosters memberships.csv                # renumber existing portraits
python3 tools/fetch_faces.py --rosters memberships.csv                # -> assets/net/faces/
```

Order matters. Portraits are named by node index, which is a player's rank in
the sorted uid list, so anything that changes the player list renumbers all of
them -- `remap_faces.py` renames the files in place (using `faces/owners.csv`,
which records who each one belongs to) rather than downloading 12 MB again.

### Two nodes, one player

The 2017-18 block of the memberships file came from Pro-Football-Reference
rosters, and the 424 players there with no birth date got a `PFR:<id>` uid
instead of the normal one. That splits a career in half -- Wyatt Teller was one
node at BUF in 2018 and another from CLE 2019 on, with no edge between them.

`build_pfr_aliases.py` resolves the PFR id through nflverse's players table,
which carries both `pfr_id` and `birth_date`, and so lands on exactly the same
uid the rest of the data uses. That rejoins 423 of the 424 and merges 226 into
an existing node. Do not be tempted to match on name instead: it merges Leon
McQuay III into the 1974 Leon McQuay, and it misses Buddy Howell entirely
because PFR files him as Gregory Howell. The one node left alone is
`PFR:HoweBu00`, which nflverse does not list and which sits at the same
club-season as a second PFR id for Howell -- too ambiguous to guess at.

### Portraits

Two sources. `fetch_faces.py` takes the NFL headshot the roster rows link to;
those URLs are unique per player but frequently resolve to one generic
silhouette, so it md5s each download and drops the known placeholder. That
archive reaches 84% of players who debuted from 2015 and essentially nobody
before 1990, which left the entire Hall of Fame as bare dots.

`fetch_commons_faces.py` fills those in from Wikipedia, in two stages so the
choices can be read before any file is written:

```
python3 tools/fetch_commons_faces.py --stage resolve --names greats.txt \
        --rosters memberships.csv --out commons_manifest.json
python3 tools/fetch_commons_faces.py --stage fetch --manifest commons_manifest.json
```

It goes name -> Wikipedia article -> lead image, never a Commons filename
search: searching Commons for "Husain Abdullah" returns an Indonesian
official. Only images served from `/wikipedia/commons/` are taken -- an image
hosted locally on en.wikipedia is there under fair use and must not be copied,
which is why 14 of the greats, Gene Upshaw and Alan Page among them, still have
no photo. Each entry in the manifest carries the licence and author, and a
`crop` field to nudge the framing for any picture whose face is not where the
default assumes.

Two things it is worth knowing before changing this tool. Wikimedia's robot
policy needs contact details in the User-Agent -- without them it answers
sustained traffic with a 429 -- so set `--contact`. And it refuses requests for
full-size originals, telling you to use a thumbnail, while also rejecting any
width that is not on its own list; the size to use comes back from the API
rather than being built by hand.

The check that the article really describes this player's career matters more
than it looks. It is what keeps the Vikings Adrian Peterson's photograph off
the 2002-09 Bears one of the same name -- who was the only candidate left
without a picture, and so would otherwise have been the one to get it.

170 portraits were resolved and reviewed by eye; one, that Adrian Peterson, was
wrong and was dropped. `assets/net/faces/credits.json` carries the file, licence
and author for the 169 that shipped: 83 are public domain and the rest are CC,
nearly all of which require attribution.

Three judgement calls to be aware of before this goes live. The club marks in
`assets/net/logos/` are trademarks. The CC portraits need their attribution
shown somewhere a visitor can reach -- `credits.json` has the data but no page
displays it yet. And the 2026 rows are opening rosters, not games played --
those players have not appeared in a regular-season game.

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
