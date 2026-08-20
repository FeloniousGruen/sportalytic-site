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

  function init(canvas, pickHandler) {
    cv = canvas; ctx = cv.getContext('2d', { alpha: false });
    onPick = pickHandler || onPick;
    resize();
    addEventListener('resize', () => { resize(); fit(); });
    cv.addEventListener('pointermove', e => {
      const r = cv.getBoundingClientRect();
      hover = pick(e.clientX - r.left, e.clientY - r.top);
      if (hover !== prevHover) { prevHover = hover; dirty = true; }
      cv.style.cursor = hover >= 0 ? 'pointer' : 'default';
    });
    cv.addEventListener('pointerleave', () => { hover = -1; dirty = true; });
    cv.addEventListener('click', e => {
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
    let drag = null;
    cv.addEventListener('pointerdown', e => { drag = { x: e.clientX, y: e.clientY }; });
    addEventListener('pointerup', () => { drag = null; });
    addEventListener('pointermove', e => {
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

  const sx = x => (x - cam.x) * cam.scale + W / 2;
  const sy = y => (y - cam.y) * cam.scale + H / 2;

  /* Uniform bucket grid over layout space. Rebuilt whenever the layout changes;
   * 28k points into ~64px buckets makes hit-testing a handful of comparisons. */
  function buildGrid() {
    const px = NET.px, py = NET.py, n = NET.P;
    const nd = NET.DEG_COLOUR.length;
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
    const wx = (mx - W / 2) / cam.scale + cam.x, wy = (my - H / 2) / cam.scale + cam.y;
    const rad = 9 / cam.scale;                       // ~9px grab radius
    const c0 = ((wx - rad - gridMinX) / gridCell) | 0, c1 = ((wx + rad - gridMinX) / gridCell) | 0;
    const r0 = ((wy - rad - gridMinY) / gridCell) | 0, r1 = ((wy + rad - gridMinY) / gridCell) | 0;
    let best = -1, bestD = rad * rad;
    for (let r = r0; r <= r1; r++) {
      for (let c = c0; c <= c1; c++) {
        const b = grid.get(r * gridW + c); if (!b) continue;
        for (const i of b) {
          const dx = NET.px[i] - wx, dy = NET.py[i] - wy, d = dx * dx + dy * dy;
          if (d < bestD) { bestD = d; best = i; }
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
    ctx.fillStyle = '#0B1117';
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
      const step = 1;
      for (let i = 0; i < n; i += step) {
        const p = par[i]; if (p < 0) continue;
        if (ringSegs && (dist[i] > 1 || dist[p] > 1)) continue;
        let ax = px[i], ay = py[i], bx = px[p], by = py[p];
        if (useMorph) {
          ax = fromX[i] + (ax - fromX[i]) * t; ay = fromY[i] + (ay - fromY[i]) * t;
          bx = fromX[p] + (bx - fromX[p]) * t; by = fromY[p] + (by - fromY[p]) * t;
        }
        if (!(ax === ax) || !(bx === bx)) continue;
        ctx.moveTo(sx(ax), sy(ay)); ctx.lineTo(sx(bx), sy(by));
      }
      ctx.stroke();
    }
    perf.edges = performance.now() - te;

    // ---- nodes, batched by degree so fillStyle changes 12 times, not 28,842 ----
    const tn = performance.now();
    const r = Math.max(1, Math.min(4.5, cam.scale * 0.030));
    const d2 = r * 2;
    for (let deg = 0; deg < buckets.length; deg++) {
      if (ringSegs && deg > 1) break;          // first-ring view: centre + ring 1
      const bucket = buckets[deg];
      if (!bucket || !bucket.length) continue;
      const dim = throughMask ? 'rgba(70,80,95,0.5)' : NET.DEG_COLOUR[deg];
      ctx.fillStyle = dim;
      for (let bi = 0; bi < bucket.length; bi++) {
        const i = bucket[bi];
        if (throughMask && throughMask[i]) continue;   // drawn hot, below
        let x = px[i], y = py[i];
        if (useMorph) { x = fromX[i] + (x - fromX[i]) * t; y = fromY[i] + (y - fromY[i]) * t; }
        if (!(x === x)) continue;
        const X = sx(x), Y = sy(y);
        if (X < -8 || Y < -8 || X > W + 8 || Y > H + 8) continue;
        ctx.fillRect(X - r, Y - r, d2, d2);
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
    if (path.length > 1 && !moving) {
      ctx.strokeStyle = NET.PATH; ctx.lineWidth = 2.5; ctx.beginPath();
      for (let k = 0; k < path.length; k++) {
        const [x, y] = frameXY(path[k]);
        const X = sx(x), Y = sy(y);
        k ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y);
      }
      ctx.stroke();
      ctx.fillStyle = NET.PATH;
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
        ctx.strokeStyle = 'rgba(251,194,71,0.16)'; ctx.lineWidth = 1;
        for (const edge of [sg.a0, sg.a1]) {
          ctx.beginPath();
          ctx.moveTo(sx(sg.rIn * 0.86 * Math.cos(edge)), sy(sg.rIn * 0.86 * Math.sin(edge)));
          ctx.lineTo(sx(sg.rOut * 1.14 * Math.cos(edge)), sy(sg.rOut * 1.14 * Math.sin(edge)));
          ctx.stroke();
        }
        if (sg.a1 - sg.a0 < 0.10) continue;      // too thin to letter
        const lr = sg.rOut * 1.24;
        const X = sx(lr * Math.cos(mid)), Y = sy(lr * Math.sin(mid));
        ctx.font = 'bold 12px Arial';
        const w = ctx.measureText(sg.team).width + 12;
        ctx.fillStyle = 'rgba(20,28,37,0.92)';
        ctx.fillRect(X - w / 2, Y - 11, w, 22);
        ctx.strokeStyle = 'rgba(251,194,71,0.5)'; ctx.lineWidth = 1;
        ctx.strokeRect(X - w / 2, Y - 11, w, 22);
        ctx.fillStyle = '#FBC247';
        ctx.fillText(sg.team, X, Y);
        if (sg.a1 - sg.a0 > 0.30) {
          ctx.fillStyle = 'rgba(255,255,255,0.55)'; ctx.font = '11px Arial';
          ctx.fillText(`${sg.count} team-mates`, X, Y + 18);
        }
      }
      ctx.restore();
    }

    // ---- portrait on the centre, when one exists for that player ----
    if (centreImg && centreImg.complete && !moving) {
      const [cxw, cyw] = frameXY(centre);
      if (cxw === cxw) {
        const d = Math.max(34, Math.min(96, cam.scale * 1.15));
        ctx.drawImage(centreImg, sx(cxw) - d / 2, sy(cyw) - d / 2, d, d);
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
    if (path.length > 1 && !moving) {
      ctx.font = 'bold 11px Arial';
      ctx.textBaseline = 'middle';
      ctx.textAlign = 'left';
      const BOX = 16, GAP = 3;
      const placed = [];
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
        const pad = (i === centre && centreImg)
          ? Math.max(34, Math.min(96, cam.scale * 1.15)) / 2 + 6 : 10;
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
        ctx.fillStyle = 'rgba(11,17,23,0.85)';
        ctx.fillRect(d.r.x, d.r.y, d.r.w, BOX);
        ctx.fillStyle = (d.k === path.length - 1) ? '#fff' : NET.PATH;
        ctx.fillText(d.label, d.r.x + 4, d.r.y + BOX / 2);
      }
    }
    if (hover >= 0) ring(hover, '#fff');
    if (selected >= 0) ring(selected, NET.PATH);
    perf.draw = performance.now() - t0;
    perf.frames++;
  }

  function ring(i, colour) {
    const [x, y] = frameXY(i);
    ctx.strokeStyle = colour; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(sx(x), sy(y), 7, 0, 6.2832); ctx.stroke();
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

  function setCentreImage(src) {
    if (!src) { centreImg = null; dirty = true; return; }
    const im = new Image();
    im.onload = () => { dirty = true; };
    im.src = src;
    centreImg = im;
  }

  function setRingSegments(segs) { ringSegs = segs; dirty = true; }

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
    const n = NET.P, rs = [];
    for (let i = 0; i < n; i++) { const x = NET.px[i]; if (x === x) rs.push(Math.hypot(x, NET.py[i])); }
    rs.sort((a, b) => a - b);
    const r = rs[Math.floor(rs.length * 0.995)] || rs[rs.length - 1] || 1;
    return Math.min(W, H) / (2 * r) * 0.94;
  }

  function fit() { cam.x = 0; cam.y = 0; cam.scale = fitScale(); dirty = true; }

  return {
    init, draw, tick, fit, fitScale, buildGrid, captureFrom, beginMorph, perf, cam,
    setCentreImage, setRingSegments, setThrough, zoomBy,
    get hasThrough() { return !!throughMask; },
    get ringMode() { return !!ringSegs; },
    invalidate,
    set path(p) { path = p; dirty = true; }, get path() { return path; },
    set selected(i) { selected = i; dirty = true; }, get selected() { return selected; },
    set centre(i) { centre = i; }, get centre() { return centre; },
    get morphing() { return morph < 1; },
  };
})();
