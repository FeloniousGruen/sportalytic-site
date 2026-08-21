/* Rendering and interaction for the network page.
 *
 * 28,842 nodes and 28,841 tree edges, redrawn on a plain 2D canvas. The stress
 * case is the recentre morph, where every node moves at once; edges are the
 * expensive half, so they thin out while things are in motion and come back at
 * full strength once it settles.
 */
'use strict';

const VIEW = (() => {
  let cv, ctx, dpr = 1, W = 0, H = 0;
  let cam = { x: 0, y: 0, scale: 60 };
  let hover = -1, prevHover = -1, selected = -1, centre = 0;
  let path = [];
  let fromX = null, fromY = null, morph = 1, morphStart = 0, morphMs = 900;
  let fromScale = 0, toScale = 0;   // camera refits as the layout changes
  let grid = null, gridCell = 0, gridW = 0, gridH = 0, gridMinX = 0, gridMinY = 0;
  let buckets = [];            // node ids grouped by degree, rebuilt per layout
  let dirty = true;            // only redraw when something actually changed
  const perf = { draw: 0, edges: 0, nodes: 0, frames: 0, fps: 0, lastFps: 0 };
  let onPick = () => {};
  let centreImg = null;         // portrait drawn on the centre, when we have one
  let ringSegs = null;          // first-ring mode: wedge per club, or null
  let throughMask = null;       // share-of-connections highlight
  const LOGOS = {};             // club code -> Image, loaded on demand
  let logoCodes = null;
  let logoColours = {};   // club -> primary, for the wedge wash
  const FACES = {};       // node index -> portrait, loaded on demand
  let hasFace = null;     // one flag per player, so we never chase a 404
  let growFrom = 0, growWho = -1;   // a picked dot swelling into its picture
  const faceR = new Map();          // node -> radius its portrait took this frame
  let showLabels = true;            // off while the quiz owns a phone screen
  let litMask = null;               // Expedition: 0 dark, 1 lit, 2 unlocked
  let interactive = true;           // off while a game owns the chart
  let autoFit = true;               // off while a keyboard is up
  /* Page furniture labels must not cross. Held as a function rather than a
     list: the heading changes with the centre, cards open and close, and a
     stale set of rectangles is worse than none -- it moves labels away from
     clear space and leaves them on top of the thing that did move. */
  let keepOut = () => [];

  function init(canvas, pickHandler) {
    cv = canvas; ctx = cv.getContext('2d', { alpha: false });
    onPick = pickHandler || onPick;
    resize();
    addEventListener('resize', () => { resize(); fit(); });
    /* ...and refit when it changes materially, which on a phone is every time
       the bottom sheet opens or closes. Two guards. A few pixels is not worth
       a refit -- the keyboard settling, a card growing by a line -- and it
       reads as the chart twitching. And autoFit goes off while a keyboard is
       up, because refitting under someone who is typing moves the thing they
       are looking at. */
    if (typeof ResizeObserver === 'function') {
      let pw = W, ph = H;
      new ResizeObserver(() => {
        resize();
        if (!W || !H) return;
        const moved = Math.abs(W - pw) + Math.abs(H - ph);
        pw = W; ph = H;
        if (moved > 12 && autoFit) fit();
      }).observe(cv);
    }
    cv.addEventListener('pointermove', e => {
      if (!interactive) {
        if (hover !== -1) { hover = prevHover = -1; dirty = true; }
        cv.style.cursor = 'default';
        return;
      }
      const r = cv.getBoundingClientRect();
      hover = pick(e.clientX - r.left, e.clientY - r.top);
      if (hover !== prevHover) { prevHover = hover; dirty = true; }
      cv.style.cursor = hover >= 0 ? 'pointer' : 'default';
    });
    cv.addEventListener('pointerleave', () => { hover = -1; dirty = true; });
    cv.addEventListener('click', e => {
      if (!interactive) return;
      const r = cv.getBoundingClientRect();
      const i = pick(e.clientX - r.left, e.clientY - r.top);
      if (i >= 0) onPick(i);
    });
    cv.addEventListener('wheel', e => {
      e.preventDefault();
      const k = Math.exp(-e.deltaY * 0.0012);
      cam.scale = Math.max(12, Math.min(600, cam.scale * k));
      dirty = true;
    }, { passive: false });
    /* Drag to pan, two fingers to pinch. Without the pinch there is no way to
       zoom on a phone at all -- the wheel handler never fires and the +/- keys
       are a tool bar away. Pointer events give us both from one set of
       handlers, so long as we track the live ones ourselves. */
    let drag = null;
    const touches = new Map();
    const spread = () => {
      const [a, b] = [...touches.values()];
      return Math.hypot(a.x - b.x, a.y - b.y);
    };
    let pinchFrom = 0, pinchScale = 0;

    cv.addEventListener('pointerdown', e => {
      touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (touches.size === 2) {
        drag = null;                       // a second finger ends the pan
        pinchFrom = spread(); pinchScale = cam.scale;
      } else if (touches.size === 1) {
        drag = { x: e.clientX, y: e.clientY };
      }
    });
    const endTouch = e => {
      touches.delete(e.pointerId);
      drag = null;
      if (touches.size === 1) {            // one finger left: resume panning
        const t = [...touches.values()][0];
        drag = { x: t.x, y: t.y };
      }
    };
    addEventListener('pointerup', endTouch);
    addEventListener('pointercancel', endTouch);
    addEventListener('pointermove', e => {
      if (touches.has(e.pointerId)) touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (touches.size === 2) {
        const now = spread();
        if (pinchFrom > 8 && now > 8) {
          cam.scale = Math.max(6, Math.min(900, pinchScale * (now / pinchFrom)));
          dirty = true;
        }
        return;
      }
      if (!drag) return;
      cam.x -= (e.clientX - drag.x) / cam.scale;
      cam.y -= (e.clientY - drag.y) / cam.scale;
      drag = { x: e.clientX, y: e.clientY };
      dirty = true;
    });
  }

  function resize() {
    dpr = Math.min(2, devicePixelRatio || 1);
    W = cv.clientWidth; H = cv.clientHeight;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    dirty = true;
  }

  /* The heading and the controls sit across the top of the canvas, so the
     chart is centred in what is left underneath them rather than in the whole
     rectangle. Doing it here rather than by panning afterwards means it holds
     however the chart is rotated, and survives a fit -- panning did not,
     because a morph resets the camera before the new path is even set. */
  function topInset() {
    let m = 0;
    const cx = W / 2;
    for (const r of keepOut()) {
      if (r.y > H * 0.4) continue;                 // not along the top
      // and only what actually stands over the chart: the player card is off
      // to one side, so counting it squashed the chart for no reason
      if (r.x > cx || r.x + r.w < cx) continue;
      m = Math.max(m, r.y + r.h);
    }
    return Math.max(0, Math.min(m + 10, H * 0.3));
  }
  /* Memoised for the duration of a frame.
   *
   * sy() calls this for every point it projects, and it walks keepOut(), which
   * is getBoundingClientRect() on six elements -- a forced layout reflow. On
   * the all-time chart that was happening 18,874 times for the dots and twice
   * more per edge, which is where essentially the whole frame was going: 890ms
   * to draw, of which the actual painting is a couple. The furniture cannot
   * move mid-frame, so measuring it once is not an approximation. */
  let midYCache = null;
  const midY = () => (midYCache !== null ? midYCache
                      : (midYCache = topInset() + (H - topInset()) / 2));
  const remeasure = () => { midYCache = null; };

  const sx = x => (x - cam.x) * cam.scale + W / 2;
  const sy = y => (y - cam.y) * cam.scale + midY();

  /* Uniform bucket grid over layout space. Rebuilt whenever the layout changes;
   * 28k points into ~64px buckets makes hit-testing a handful of comparisons. */
  /* Level of detail.
   *
   * The all-time football chart is 18,876 dots and 18,875 edges, and the
   * outer rings are dense arcs where individual dots are not separable
   * anyway -- drawing every one costs frames to say something the eye cannot
   * read. So a share of them are left out of the DRAWING only.
   *
   * Nothing else changes: the graph, the traversal, the routes and the search
   * are all still over every player. Positions come from the full tree's leaf
   * counts, so a hidden player's place is computed exactly as before and is
   * simply not painted -- which means the moment anything makes them matter
   * (search, a route, a click) they appear in the right spot, in a cluster
   * that already exists, with nothing else shifting to accommodate them.
   *
   * Who is dropped: only leaves, only where a parent has a big fan of them,
   * and never anyone carrying a portrait. Structure -- the spokes, the
   * branching, the shape of the thing -- is untouched; what thins is the
   * repetition inside an arc.
   */
  let drawSkip = null;          // per node: leave out of the drawing
  let pathMark = null;          // per node: on the highlighted chain
  /* Default 1: draw everyone.
     This machinery was built to cut the lag by thinning the outer arcs, and it
     works -- but the lag turned out to be the per-dot layout reflow above, and
     with that fixed the full chart draws in under 3ms. Dropping dots would now
     cost information and buy nothing. It stays because it is tested and free
     at 1, and because a much older phone may yet want it: VIEW.detail = 0.5. */
  let detail = 1;               // share of a dense fan's leaves to keep

  function shown(i) {
    return !drawSkip || !drawSkip[i] || i === centre || i === selected ||
           i === hover || (pathMark && pathMark[i]);
  }

  function buildSkip() {
    const n = NET.P, par = NET.parent, dist = NET.dist;
    if (!drawSkip || drawSkip.length !== n) drawSkip = new Uint8Array(n);
    drawSkip.fill(0);
    if (detail >= 1) return;
    // how many children each node has, so a leaf can be told from a fork
    const kids = new Int32Array(n);
    for (let i = 0; i < n; i++) { const p = par[i]; if (p >= 0) kids[p]++; }
    // keep one in every `stride` leaves of a fan, in the order they are met
    const stride = Math.max(2, Math.round(1 / Math.max(0.05, detail)));
    const seen = new Int32Array(n);
    const MIN_FAN = 6;           // below this a fan is sparse enough to read
    for (let i = 0; i < n; i++) {
      if (dist[i] <= 1) continue;                 // centre and first ring stay
      if (kids[i]) continue;                      // only ever drop leaves
      if (hasFace && hasFace[i]) continue;        // never someone with a face
      const p = par[i];
      if (p < 0 || kids[p] < MIN_FAN) continue;
      if (seen[p]++ % stride) drawSkip[i] = 1;
    }
  }

  function buildGrid() {
    const px = NET.px, py = NET.py, n = NET.P;
    const nd = NET.DEG_COLOUR.length;
    buildSkip();
    buckets = Array.from({ length: nd }, () => []);
    for (let i = 0; i < n; i++) {
      const d = NET.dist[i];
      if (d >= 0 && d < nd) buckets[d].push(i);
    }
    buckets = buckets.map(b => Int32Array.from(b));
    let mnx = Infinity, mny = Infinity, mxx = -Infinity, mxy = -Infinity;
    for (let i = 0; i < n; i++) {
      const x = px[i], y = py[i];
      if (!(x === x)) continue;
      if (x < mnx) mnx = x; if (x > mxx) mxx = x;
      if (y < mny) mny = y; if (y > mxy) mxy = y;
    }
    gridMinX = mnx; gridMinY = mny;
    gridCell = Math.max(0.15, (mxx - mnx) / 120);
    gridW = Math.ceil((mxx - mnx) / gridCell) + 1;
    gridH = Math.ceil((mxy - mny) / gridCell) + 1;
    grid = new Map();
    for (let i = 0; i < n; i++) {
      const x = px[i]; if (!(x === x)) continue;
      const cx = ((x - mnx) / gridCell) | 0, cy = ((py[i] - mny) / gridCell) | 0;
      const k = cy * gridW + cx;
      let b = grid.get(k); if (!b) { b = []; grid.set(k, b); }
      b.push(i);
    }
  }

  function pick(mx, my) {
    if (!grid) return -1;
    remeasure();
    const wx = (mx - W / 2) / cam.scale + cam.x, wy = (my - midY()) / cam.scale + cam.y;
    // a player wearing a portrait should be grabbable by the portrait, not by
    // the small dot hiding behind it
    const centreR = Math.max(58, Math.min(104, cam.scale * 1.15)) / 2;
    const pickedR = Math.max(45, Math.min(108, cam.scale * 1.275)) / 2;
    const rad = Math.max(9, centreR) / cam.scale;
    const c0 = ((wx - rad - gridMinX) / gridCell) | 0, c1 = ((wx + rad - gridMinX) / gridCell) | 0;
    const r0 = ((wy - rad - gridMinY) / gridCell) | 0, r1 = ((wy + rad - gridMinY) / gridCell) | 0;
    let best = -1, bestD = Infinity;
    for (let r = r0; r <= r1; r++) {
      for (let c = c0; c <= c1; c++) {
        const b = grid.get(r * gridW + c); if (!b) continue;
        for (const i of b) {
          if (ringSegs && NET.dist[i] > 1) continue;     // first-ring view: ring 1 only
          const dx = NET.px[i] - wx, dy = NET.py[i] - wy, d = dx * dx + dy * dy;
          // whatever is actually drawn for this player is what you can hit
          let r = 9;
          if (i === centre && (centreImg || (hasFace && hasFace[i]))) r = centreR;
          else if (i === selected && hasFace && hasFace[i]) r = pickedR;
          const lim = (r / cam.scale) ** 2;
          if (d < bestD && d < lim) { bestD = d; best = i; }
        }
      }
    }
    return best;
  }

  function frameXY(i) {
    if (morph >= 1 || !fromX) return [NET.px[i], NET.py[i]];
    const t = morph;
    return [fromX[i] + (NET.px[i] - fromX[i]) * t, fromY[i] + (NET.py[i] - fromY[i]) * t];
  }

  function draw() {
    const t0 = performance.now();
    remeasure();
    ctx.fillStyle = NET.BG;
    ctx.fillRect(0, 0, W, H);
    const moving = morph < 1;
    const px = NET.px, py = NET.py, par = NET.parent, dist = NET.dist, n = NET.P;
    const useMorph = moving && fromX;
    const t = morph;

    // ---- edges ----
    const te = performance.now();
    if (!moving) {
      ctx.strokeStyle = NET.EDGE;
      ctx.lineWidth = 1;
      ctx.beginPath();
      /* Screen-space culling, in layout units so the test is two comparisons
         per endpoint rather than two projections. The all-time football chart
         is 18,876 edges and every one of them was being pushed into the path
         however far off screen it was; zoomed in, that is almost all of them.
         The nodes have always been culled -- this brings the expensive half
         into line. A generous margin keeps edges that cross the viewport
         without either end being inside it. */
      const mx = W / cam.scale, my = H / cam.scale;
      const clipL = cam.x - mx, clipR = cam.x + mx;
      const clipT = cam.y - my, clipB = cam.y + my;
      const step = 1;
      for (let i = 0; i < n; i += step) {
        // while a share is up, the highlighted players hang off the player in
        // question rather than off the branch they arrived from
        let p = (throughMask && throughMask[i]) ? NET.throughParent(i) : par[i];
        if (p < 0 || (throughMask && throughMask[i] && !throughMask[p] && p !== selected))
          p = par[i];
        if (p < 0) continue;
        if (!shown(i)) continue;          // its dot is not drawn either
        if (ringSegs && (dist[i] > 1 || dist[p] > 1)) continue;
        let ax = px[i], ay = py[i], bx = px[p], by = py[p];
        if (useMorph) {
          ax = fromX[i] + (ax - fromX[i]) * t; ay = fromY[i] + (ay - fromY[i]) * t;
          bx = fromX[p] + (bx - fromX[p]) * t; by = fromY[p] + (by - fromY[p]) * t;
        }
        if (!(ax === ax) || !(bx === bx)) continue;
        // both ends outside the same edge of the viewport: it cannot cross it
        if ((ax < clipL && bx < clipL) || (ax > clipR && bx > clipR) ||
            (ay < clipT && by < clipT) || (ay > clipB && by > clipB)) continue;
        ctx.moveTo(sx(ax), sy(ay)); ctx.lineTo(sx(bx), sy(by));
      }
      ctx.stroke();
    }
    perf.edges = performance.now() - te;

    // ---- nodes, batched by degree so fillStyle changes 12 times, not 28,842 ----
    const tn = performance.now();
    // Zoomed into a single club's wedge there are only a few dozen dots on
    // screen and they stayed pinpricks. The floor is what keeps the whole
    // chart legible; the ceiling only ever bites when you are already close.
    const r = Math.max(1, Math.min(8, cam.scale * 0.034));
    const d2 = r * 2;
    for (let deg = 0; deg < buckets.length; deg++) {
      if (ringSegs && deg > 1) break;          // first-ring view: centre + ring 1
      const bucket = buckets[deg];
      if (!bucket || !bucket.length) continue;
      const dim = throughMask ? 'rgba(70,80,95,0.5)' : NET.DEG_COLOUR[deg];
      ctx.fillStyle = dim;
      for (let bi = 0; bi < bucket.length; bi++) {
        const i = bucket[bi];
        if (litMask) continue;                         // drawn by state, below
        if (throughMask && throughMask[i]) continue;   // drawn hot, below
        if (!shown(i)) continue;
        let x = px[i], y = py[i];
        if (useMorph) { x = fromX[i] + (x - fromX[i]) * t; y = fromY[i] + (y - fromY[i]) * t; }
        if (!(x === x)) continue;
        const X = sx(x), Y = sy(y);
        if (X < -8 || Y < -8 || X > W + 8 || Y > H + 8) continue;
        ctx.fillRect(X - r, Y - r, d2, d2);
      }
    }
    /* Expedition draws by what you have found rather than by degree: the dark
       is everything still out there, and the point of the game is to see less
       of it. Three passes so the colour changes three times, not 29,000. */
    /* A dot lights up in its own colour, brighter, rather than being repainted
       in one highlight -- the ring a player sits in is the whole shape of the
       thing, and recolouring threw it away. Still three passes per degree
       rather than one per dot: unfound, found, named. */
    if (litMask) {
      for (let deg = 0; deg < buckets.length; deg++) {
        const bucket = buckets[deg];
        if (!bucket || !bucket.length) continue;
        const base = NET.DEG_COLOUR[deg];
        for (let st = 0; st < 3; st++) {
          ctx.fillStyle = st === 0 ? NET.dim(base) : st === 1 ? base : NET.lift(base);
          const rr = st === 0 ? r * 0.85 : st === 1 ? r * 1.1 : r * 1.75;
          const dd = rr * 2;
          for (let bi = 0; bi < bucket.length; bi++) {
            const i = bucket[bi];
            if (litMask[i] !== st) continue;
            let x = px[i], y = py[i];
            if (useMorph) { x = fromX[i] + (x - fromX[i]) * t; y = fromY[i] + (y - fromY[i]) * t; }
            if (!(x === x)) continue;
            const X = sx(x), Y = sy(y);
            if (X < -8 || Y < -8 || X > W + 8 || Y > H + 8) continue;
            ctx.fillRect(X - rr, Y - rr, dd, dd);
          }
        }
      }
    }

    if (throughMask) {                 // everyone routing through the pick
      ctx.fillStyle = '#F38A1C';
      const rr = r * 1.25, dd = rr * 2;
      for (let i = 0; i < n; i++) {
        if (!throughMask[i]) continue;
        let x = px[i], y = py[i];
        if (useMorph) { x = fromX[i] + (x - fromX[i]) * t; y = fromY[i] + (y - fromY[i]) * t; }
        if (!(x === x)) continue;
        const X = sx(x), Y = sy(y);
        if (X < -8 || Y < -8 || X > W + 8 || Y > H + 8) continue;
        ctx.fillRect(X - rr, Y - rr, dd, dd);
      }
    }
    perf.nodes = performance.now() - tn;

    // ---- highlighted path back to the centre ----
    if (path.length > 1 && !moving && !ringSegs) {
      ctx.strokeStyle = NET.LINK; ctx.lineWidth = 2.5; ctx.beginPath();
      for (let k = 0; k < path.length; k++) {
        const [x, y] = frameXY(path[k]);
        const X = sx(x), Y = sy(y);
        k ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y);
      }
      ctx.stroke();
      ctx.fillStyle = NET.LINK;
      for (const i of path) {
        const [x, y] = frameXY(i);
        ctx.beginPath(); ctx.arc(sx(x), sy(y), 3.5, 0, 6.2832); ctx.fill();
      }
    }

    // ---- first-ring wedges, labelled by club ----
    if (ringSegs && !moving) {
      ctx.save();
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      for (const sg of ringSegs) {
        const mid = (sg.a0 + sg.a1) / 2;
        // shaded band behind the club's teammates, with its mark on top
        const rIn = sg.rIn * 0.80, rOut = sg.rOut * 1.18;
        ctx.beginPath();
        ctx.arc(sx(0), sy(0), rOut * cam.scale, sg.a0, sg.a1);
        ctx.arc(sx(0), sy(0), rIn * cam.scale, sg.a1, sg.a0, true);
        ctx.closePath();
        // the club's own colour, taken from its badge, so the band and the
        // mark on it always agree
        ctx.fillStyle = hexRgba(logoColours[sg.team], 0.13);
        ctx.fill();
        const lg = logoFor(sg.team);
        if (lg && lg.complete && lg.naturalWidth) {
          const band = (rOut - rIn) * cam.scale;
          const arc = (sg.a1 - sg.a0) * ((rIn + rOut) / 2) * cam.scale;
          const d = Math.max(18, Math.min(band * 0.86, arc * 0.8, 150));
          const lr = (rIn + rOut) / 2;
          ctx.save();
          ctx.globalAlpha = 0.30;
          ctx.drawImage(lg, sx(lr * Math.cos(mid)) - d / 2, sy(lr * Math.sin(mid)) - d / 2, d, d);
          ctx.restore();
        }
        ctx.strokeStyle = hexRgba(logoColours[sg.team], 0.34); ctx.lineWidth = 1;
        for (const edge of [sg.a0, sg.a1]) {
          ctx.beginPath();
          ctx.moveTo(sx(sg.rIn * 0.86 * Math.cos(edge)), sy(sg.rIn * 0.86 * Math.sin(edge)));
          ctx.lineTo(sx(sg.rOut * 1.14 * Math.cos(edge)), sy(sg.rOut * 1.14 * Math.sin(edge)));
          ctx.stroke();
        }
        if (sg.a1 - sg.a0 < 0.10) continue;      // too thin to letter
        const lr = sg.rOut * 1.24;
        ctx.font = 'bold 12px Arial';
        const w = ctx.measureText(sg.team).width + 12;
        // pull the label back inside the viewport rather than letting it drift
        // off with the wedge when zoomed in
        let X = sx(lr * Math.cos(mid)), Y = sy(lr * Math.sin(mid));
        const mx = w / 2 + 8, my = 30;
        X = Math.max(mx, Math.min(W - mx, X));
        Y = Math.max(my, Math.min(H - my, Y));
        ctx.fillStyle = 'rgba(20,28,37,0.92)';
        ctx.fillRect(X - w / 2, Y - 11, w, 22);
        ctx.strokeStyle = 'rgba(251,194,71,0.5)'; ctx.lineWidth = 1;
        ctx.strokeRect(X - w / 2, Y - 11, w, 22);
        ctx.fillStyle = '#FBC247';
        ctx.fillText(sg.team, X, Y);
        if (sg.a1 - sg.a0 > 0.30) {
          ctx.fillStyle = 'rgba(255,255,255,0.55)'; ctx.font = '11px Arial';
          ctx.fillText(`${sg.count} teammates`, X, Y + 18);
        }
      }
      ctx.restore();
    }

    // ---- portraits: the centre always, and a picked player growing in ----
    // Each one records the radius it took so the highlight below can ring the
    // picture instead of the dot buried underneath it.
    faceR.clear();
    /* The centre's portrait is drawn on EVERY frame, including while the
       layout is moving. It used to be skipped during a morph, which is why it
       vanished the moment you pressed "Share of connections" -- that view
       re-hangs a third of the chart and morphs for the best part of a second,
       and any frame the morph does not cleanly finish leaves the face gone for
       good. It is one image at a known point; there was never a reason to
       drop it, and keeping it also stops the face flickering out on every
       ordinary recentre. */
    {
      const cIm = ready(centreImg) ? centreImg : faceFor(centre);
      if (ready(cIm)) {
        const [cxw, cyw] = frameXY(centre);
        if (cxw === cxw) {
          const d = Math.max(58, Math.min(104, cam.scale * 1.15));
          ctx.drawImage(cIm, sx(cxw) - d / 2, sy(cyw) - d / 2, d, d);
          faceR.set(centre, d / 2);
        }
      }
      if (selected >= 0 && selected !== centre) {
        const sIm = faceFor(selected);
        if (ready(sIm)) {
          const [x, y] = frameXY(selected);
          if (x === x) {
            // swell out of the dot rather than appearing at full size
            const e = growWho === selected
              ? Math.min(1, (performance.now() - growFrom) / 320) : 1;
            const k = 0.5 - 0.5 * Math.cos(Math.PI * e);
            const full = Math.max(45, Math.min(108, cam.scale * 1.275));
            const d = Math.max(6, (6 + (full - 6) * k));
            ctx.drawImage(sIm, sx(x) - d / 2, sy(y) - d / 2, d, d);
            faceR.set(selected, d / 2);
            if (e < 1) dirty = true;
          }
        }
      }
    }

    /* Names last, so the centre portrait cannot clip its own label.
     *
     * Consecutive stops on a path sit one ring apart, which at a fitted zoom is
     * far closer than a line of text is tall, so placing every label at its dot
     * guarantees a pile-up. Each label instead takes the first free slot from a
     * candidate list -- either side, then progressively further above and below
     * -- tested against the boxes already placed. Ends of the chain are placed
     * first so they win the good positions, and a label that had to move gets a
     * leader line back to its dot. */
    if (showLabels && path.length > 1 && !moving && !ringSegs) {
      ctx.font = 'bold 11px Arial';
      ctx.textBaseline = 'middle';
      ctx.textAlign = 'left';
      const BOX = 16, GAP = 3;
      const placed = [];
      /* The heading, the controls and whichever card is open are all drawn
         over this canvas by the page, so a label placed under them is either
         illegible or invisible. They go in as obstacles the same way. */
      for (const r of keepOut()) placed.push(r);
      /* Portraits are obstacles for every label, not just their own. Seeding
         them here is what stops a neighbour's name landing across a face --
         each one blocks the square its circle sits in. */
      for (const [pi, pr] of faceR) {
        const [fx, fy] = frameXY(pi);
        if (fx !== fx) continue;
        placed.push({ x: sx(fx) - pr, y: sy(fy) - pr, w: pr * 2, h: pr * 2 });
      }
      const hits = r => placed.some(q =>
        !(r.x + r.w + GAP < q.x || q.x + q.w + GAP < r.x ||
          r.y + r.h + GAP < q.y || q.y + q.h + GAP < r.y));
      // both ends matter most: the player asked for and the centre
      const order = path.map((_, k) => k)
        .sort((a, b) => (a === 0 || a === path.length - 1 ? 0 : 1)
                      - (b === 0 || b === path.length - 1 ? 0 : 1));
      const drawn = [];
      for (const k of order) {
        const i = path[k];
        const [x, y] = frameXY(i);
        const X = sx(x), Y = sy(y);
        if (X < -40 || Y < -20 || X > W + 40 || Y > H + 20) continue;
        const label = NET.names[i];
        const tw = ctx.measureText(label).width + 8;
        // clear whatever this player is actually wearing, so a portrait
        // never sits under its own name
        const fr = faceR.get(i);
        const pad = fr ? fr + 9 : 10;
        let best = null;
        for (const dy of [0, -15, 15, -30, 30, -45, 45, -62, 62, -80, 80]) {
          for (const side of [1, -1]) {
            const bx = side > 0 ? X + pad : X - tw - pad;
            if (bx < 4 || bx + tw > W - 4) continue;
            const r = { x: bx, y: Y + dy - BOX / 2, w: tw, h: BOX };
            if (r.y < 4 || r.y + BOX > H - 4) continue;
            if (!hits(r)) { best = { r, dy, side }; break; }
          }
          if (best) break;
        }
        if (!best) continue;            // no room: leave it out rather than stack
        placed.push(best.r);
        drawn.push({ k, X, Y, ...best, label });
      }
      for (const d of drawn) {
        if (Math.abs(d.dy) > 7) {       // moved, so show where it belongs
          ctx.strokeStyle = 'rgba(251,194,71,0.45)';
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(d.X + (d.side > 0 ? 5 : -5), d.Y);
          ctx.lineTo(d.side > 0 ? d.r.x : d.r.x + d.r.w, d.r.y + BOX / 2);
          ctx.stroke();
        }
        ctx.fillStyle = NET.BG === '#0B1117' ? 'rgba(11,17,23,0.85)' : 'rgba(255,255,255,0.88)';
        ctx.fillRect(d.r.x, d.r.y, d.r.w, BOX);
        ctx.fillStyle = NET.LINK;      // labels match the chain they belong to
        ctx.fillText(d.label, d.r.x + 4, d.r.y + BOX / 2);
      }
    }
    /* The centre wears a white ring whatever it is showing -- around the
       portrait when there is one, around the dot when there is not -- so the
       player the whole chart is hung on is never ambiguous. */
    if (!moving) ring(centre, NET.BG === '#0B1117' ? '#fff' : '#1A202C');
    // the white ring is also the "you are about to pick this" cue, so it is not
    // wanted on a dot that already carries the gold one
    if (hover >= 0 && hover !== selected && hover !== centre)
      ring(hover, NET.BG === '#0B1117' ? '#fff' : '#1A202C');
    if (selected >= 0) ring(selected, NET.PATH);
    perf.draw = performance.now() - t0;
    perf.frames++;
  }

  /* Ring the portrait when there is one -- a 7px circle inside a 60px face
     reads as a stray dot rather than a highlight. The radius comes from what
     was actually drawn this frame, so the ring swells with the picture. */
  function ring(i, colour) {
    const [x, y] = frameXY(i);
    const fr = faceR.get(i);
    ctx.strokeStyle = colour;
    ctx.lineWidth = fr ? Math.max(2, Math.min(4, fr * 0.09)) : 2;
    ctx.beginPath();
    ctx.arc(sx(x), sy(y), fr ? fr + ctx.lineWidth / 2 : 7, 0, 6.2832);
    ctx.stroke();
  }

  // capture where everyone is now, recentre, then beginMorph() to slide there
  function captureFrom() {
    fromX = Float32Array.from(NET.px);
    fromY = Float32Array.from(NET.py);
  }

  function beginMorph(ms = 900) {
    morph = 0; morphStart = performance.now(); morphMs = ms;
    fromScale = cam.scale; toScale = fitScale();
    cam.x = 0; cam.y = 0;
  }

  function invalidate() { dirty = true; }

  /* Which dataset's portraits and club marks to fetch. Set by whichever of the
     two loaders runs first; both pages call them at start-up. */
  let BASE = 'assets/net';
  function setBase(b) { BASE = b; }

  async function loadFaceFlags(base = 'assets/net') {
    BASE = base;
    // NET.inflate copes with the file arriving already decoded; see it for why
    try {
      const res = await fetch(`${base}/faces.bin.gz${NET.V()}`);
      hasFace = new Uint8Array(await NET.inflate(await res.arrayBuffer(), 'faces.bin.gz'));
    } catch (e) { hasFace = null; }
  }

  /* A player's portrait, fetched the first time it is needed. Files are named
   * by node index, and the flag array says who has one, so nothing is requested
   * speculatively. */
  function faceFor(i) {
    if (!hasFace || !hasFace[i]) return null;
    if (i in FACES) return FACES[i];
    const im = new Image();
    im.onload = () => { dirty = true; };
    im.onerror = () => { FACES[i] = null; };
    im.src = `${BASE}/faces/${i}.webp${NET.V()}`;   // indices moved; see the note in network.html
    FACES[i] = im;
    return im;
  }

  const ready = im => im && im.complete && im.naturalWidth > 0;

  function setCentreImage(src) {
    if (!src) { centreImg = null; dirty = true; return; }
    const im = new Image();
    im.onload = () => { dirty = true; };
    im.src = src;
    centreImg = im;
  }

  function setRingSegments(segs) {
    ringSegs = segs;
    if (segs) segs.forEach(sg => logoFor(sg.team));   // warm the ones we need
    dirty = true;
  }

  /* Club marks, loaded lazily and only for the wedges actually on screen.
   * Only the modern franchises have one; a 1920s club just gets its tinted
   * wedge and lettering. */
  function logoFor(code) {
    if (code in LOGOS) return LOGOS[code];
    if (!logoCodes) return null;
    if (!logoCodes.includes(code)) { LOGOS[code] = null; return null; }
    const im = new Image();
    im.onload = () => { dirty = true; };
    im.onerror = () => { LOGOS[code] = null; };
    im.src = `${BASE}/logos/${code}.png${NET.V()}`;
    LOGOS[code] = im;
    return im;
  }

  async function loadLogoIndex(base = 'assets/net') {
    BASE = base;
    try { logoCodes = await fetch(`${base}/logos/index.json${NET.V()}`).then(r => r.json()); }
    catch (e) { logoCodes = []; }
    try { logoColours = await fetch(`${base}/logos/colours.json${NET.V()}`).then(r => r.json()); }
    catch (e) { logoColours = {}; }
  }

  function hexRgba(hex, a) {
    const h = (hex || '').replace('#', '');
    if (h.length !== 6) return `rgba(255,255,255,${a})`;
    return `rgba(${parseInt(h.slice(0,2),16)},${parseInt(h.slice(2,4),16)},`
         + `${parseInt(h.slice(4,6),16)},${a})`;
  }

  function setThrough(mask) { throughMask = mask; dirty = true; }

  function zoomBy(k) {
    cam.scale = Math.max(6, Math.min(900, cam.scale * k));
    dirty = true;
  }

  function tick() {
    if (morph < 1) {
      const e = (performance.now() - morphStart) / morphMs;
      morph = e >= 1 ? 1 : 0.5 - 0.5 * Math.cos(Math.PI * Math.min(1, e));
      cam.scale = fromScale + (toScale - fromScale) * morph;
      if (e >= 1) { morph = 1; buildGrid(); }
      dirty = true;
    }
    if (dirty) { draw(); dirty = false; }
    requestAnimationFrame(tick);
  }

  /* Scale to the radius that holds ~99.5% of players rather than the single
   * furthest one. Re-rooting changes how many players sit on the outer rings --
   * Kelce has 41 at eleven degrees, other centres have thousands -- so fitting
   * to the extreme leaves one layout tiny and lets the next overflow. */
  function fitScale() {
    remeasure();
    // A canvas that has not been laid out yet reports zero size, and a zero
    // scale collapses all 29,000 dots onto one pixel -- the chart looks empty
    // until you press Fit. Keep whatever scale we have until there is a box.
    if (!W || !H) return cam.scale || 60;
    const n = NET.P, rs = [];
    for (let i = 0; i < n; i++) { const x = NET.px[i]; if (x === x) rs.push(Math.hypot(x, NET.py[i])); }
    rs.sort((a, b) => a - b);
    // A percentile rather than the plain maximum, so one freak outlier cannot
    // shrink the whole chart -- but 99.5 was cutting the outermost 148 dots
    // off the bottom edge. At 99.9 the tail costs about 8% of the zoom and
    // everything that is out there stays on screen.
    const r = rs[Math.floor(rs.length * 0.999)] || rs[rs.length - 1] || 1;
    return Math.min(W, H - topInset()) / (2 * r) * 0.94;
  }

  function fit() { cam.x = 0; cam.y = 0; cam.scale = fitScale(); dirty = true; }

  return {
    init, draw, tick, fit, fitScale, buildGrid, captureFrom, beginMorph, perf, cam,
    setCentreImage, setRingSegments, setThrough, zoomBy, loadLogoIndex,
    loadFaceFlags, faceFor, setBase,
    get faceFlagCount(){ return hasFace ? hasFace.reduce((a,b)=>a+b,0) : -1; },
    hasPortrait(i){ return !!(hasFace && hasFace[i]); },
    set labels(v){ showLabels = !!v; dirty = true; }, get labels(){ return showLabels; },
    set lit(m){ litMask = m; dirty = true; }, get lit(){ return litMask; },
    /* A game in progress owns the chart: clicking through it would hand over
       the very links you are being asked to name. */
    set autoFit(v){ autoFit = !!v; }, get autoFit(){ return autoFit; },
    setKeepOut(fn) {
      keepOut = typeof fn === 'function' ? fn : () => (fn || []);
      dirty = true;
    },
    set interactive(v){ interactive = !!v; if (!v) { hover = prevHover = -1; dirty = true; } },
    get interactive(){ return interactive; },
    get hasThrough() { return !!throughMask; },
    get ringMode() { return !!ringSegs; },
    invalidate,
    /* 1 draws every dot. Lower keeps that share of each dense fan's leaves;
       the graph is unaffected either way. */
    set detail(v) { detail = Math.max(0.05, Math.min(1, +v || 1)); buildGrid(); dirty = true; },
    get detail() { return detail; },
    get drawnCount() {
      let n = 0;
      for (let i = 0; i < NET.P; i++) if (NET.dist[i] >= 0 && shown(i)) n++;
      return n;
    },
    set path(p) {
      path = p;
      if (!pathMark || pathMark.length !== NET.P) pathMark = new Uint8Array(NET.P);
      pathMark.fill(0);
      for (const i of path) pathMark[i] = 1;
      dirty = true;
    },
    get path() { return path; },
    set selected(i) {
      if (i !== selected) { growWho = i; growFrom = performance.now(); }
      selected = i; dirty = true;
    }, get selected() { return selected; },
    set centre(i) { centre = i; }, get centre() { return centre; },
    get morphing() { return morph < 1; },
  };
})();
