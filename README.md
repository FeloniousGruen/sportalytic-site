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
