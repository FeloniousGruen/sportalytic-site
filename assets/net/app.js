/* Sportalytic — NFL teammate network, interactive.
 *
 * The whole point of this page is that any player can become the centre. That
 * means a breadth-first pass over the real teammate relation on every click,
 * so the data is shipped as the bipartite player <-> (team, season) index and
 * traversed directly rather than as 2.2M materialised edges. See
 * tools/build_network_data.py for why.
 */
'use strict';

const NET = (() => {

  /* Palette: degree from the centre, matching the reels.
     The neons are built for a near-black background and wash out on a light
     one, so light mode gets deeper, more saturated versions of the same hues
     rather than the same colours dimmed -- the ring order has to stay
     readable either way. */
  const DARK_DEG = ['#2e2e2e', '#f4b400', '#6a5acd', '#23b5d3', '#ff7f50',
                    '#ff4fa3', '#7cc943', '#2ec4b6', '#c77dff', '#ff9f1c',
                    '#00a8ff', '#7a7a7a'];
  const LIGHT_DEG = ['#8a8a8a', '#b07500', '#4334a8', '#0f7f96', '#c2461c',
                     '#c2185b', '#3f7d16', '#12786d', '#7a35b8', '#b06a05',
                     '#0a67a3', '#6a6a6a'];
  let DEG_COLOUR = DARK_DEG.slice();
  let EDGE = 'rgba(150,168,194,0.20)';
  let BG = '#0B1117';
  let theme = 'dark';

  function setTheme(name) {
    theme = name === 'light' ? 'light' : 'dark';
    const light = theme === 'light';
    DEG_COLOUR.length = 0;
    DEG_COLOUR.push(...(light ? LIGHT_DEG : DARK_DEG));
    EDGE = light ? 'rgba(70,84,104,0.28)' : 'rgba(150,168,194,0.20)';
    BG = light ? '#F4F6F8' : '#0B1117';
    return theme;
  }

  /* Two ways to shift a palette colour without leaving its hue: down into the
     background for something not yet found, and up towards white for something
     you have. Used by Expedition so a dot brightens in its own colour rather
     than being repainted in a highlight. */
  function mixHex(h, target, amount) {
    const n = parseInt(h.slice(1), 16);
    const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    const out = c.map((v, k) => Math.round(v + (target[k] - v) * amount));
    return `rgb(${out[0]},${out[1]},${out[2]})`;
  }
  const dim = h => mixHex(h, theme === 'light' ? [244, 246, 248] : [11, 17, 23], 0.74);
  const lift = h => mixHex(h, theme === 'light' ? [0, 0, 0] : [255, 255, 255], 0.34);
  const PATH = '#FBC247';   // rings and labels
  const LINK = '#FFFFFF';   // the chain itself, which reads better plain

  let P = 0, T = 0;
  let p_ip, p_ix, t_ip, t_ix;         // bipartite index
  let firstSeason, lastSeason, posIdx, tsTeam, tsSeason;
  let names = [], tables = null;

  // scratch reused across traversals so a recentre allocates nothing
  let dist, parent, order, leaves, radius, angle, px, py, tstamp;
  let wA0, wSpan, wAcc;
  let dist2, order2, tstamp2, through;   // second traversal, for share-of-connections
  let dist3, order3, tstamp3;            // third: the same graph with the pick removed
  let par2;                              // parent in the traversal from the pick
  let stampCounter = 0;

  /* These files are gzipped on disk so the transfer size does not depend on the
     host's compression rules. Two ways they arrive:

     - the host sends Content-Encoding: gzip (netlify.toml asks it to), and the
       browser has already inflated them by the time we look;
     - it does not, and we get the gzip bytes raw.

     Sniffing the magic number tells the two apart, which matters because
     DecompressionStream is not everywhere: on iOS every browser is WebKit, and
     WebKit only got it in Safari 16.4. Anything older used to hang on the
     loading line for ever. */
  async function inflate(buf, url) {
    const head = new Uint8Array(buf, 0, Math.min(2, buf.byteLength));
    if (!(head[0] === 0x1f && head[1] === 0x8b)) return buf;   // already plain
    if (typeof DecompressionStream !== 'function') {
      throw new Error(`${url} arrived compressed and this browser cannot ` +
                      `decompress it. Update the browser, or set ` +
                      `Content-Encoding: gzip on the host.`);
    }
    const stream = new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'));
    return new Response(stream).arrayBuffer();
  }

  // see the note by the script tags: old browsers have these pinned for a year
  const V = () => (typeof window !== 'undefined' && window.ASSET_V)
    ? `?v=${window.ASSET_V}` : '';

  async function loadGz(url) {
    const res = await fetch(url + V());
    if (!res.ok) throw new Error(`${url}: ${res.status}`);
    return inflate(await res.arrayBuffer(), url);
  }

  async function load(base = 'assets/net') {
    const t0 = performance.now();
    const [gbuf, nbuf, tbl] = await Promise.all([
      loadGz(`${base}/graph.bin.gz`),
      loadGz(`${base}/names.txt.gz`),
      fetch(`${base}/tables.json${V()}`).then(r => r.json()),
    ]);
    tables = tbl;
    names = new TextDecoder().decode(nbuf).split('\n');

    const dv = new DataView(gbuf);
    const magic = new TextDecoder().decode(new Uint8Array(gbuf, 0, 8));
    if (magic !== 'SPNET001') throw new Error(`bad graph file: ${magic}`);
    let o = 8;
    P = dv.getInt32(o, true); o += 4;
    T = dv.getInt32(o, true); o += 4;
    const i32 = n => { const a = new Int32Array(gbuf.slice(o, o + n * 4)); o += n * 4; return a; };
    p_ip = i32(P + 1);
    p_ix = i32(p_ip[P]);
    t_ip = i32(T + 1);
    t_ix = i32(t_ip[T]);
    const i16 = n => { const a = new Int16Array(gbuf.slice(o, o + n * 2)); o += n * 2; return a; };
    firstSeason = i16(P);
    lastSeason = i16(P);
    posIdx = new Uint8Array(gbuf.slice(o, o + P)); o += P;
    tsTeam = new Uint16Array(gbuf.slice(o, o + T * 2)); o += T * 2;
    tsSeason = i16(T);

    dist = new Int16Array(P);
    parent = new Int32Array(P);
    order = new Int32Array(P);
    leaves = new Int32Array(P);
    radius = new Float32Array(P);
    angle = new Float32Array(P);
    px = new Float32Array(P);
    py = new Float32Array(P);
    tstamp = new Int32Array(T).fill(-1);
    wA0 = new Float32Array(P);
    wSpan = new Float32Array(P);
    wAcc = new Float32Array(P);
    dist2 = new Int16Array(P);
    order2 = new Int32Array(P);
    tstamp2 = new Int32Array(T).fill(-1);
    through = new Uint8Array(P);
    dist3 = new Int16Array(P);
    order3 = new Int32Array(P);
    tstamp3 = new Int32Array(T).fill(-1);
    par2 = new Int32Array(P);
    return { ms: performance.now() - t0, players: P, teamSeasons: T };
  }

  /* Breadth-first over the bipartite index. A roster is absorbed once and then
   * skipped: without that, a team-season is rewalked for every one of its ~54
   * members, which is both slower and how an earlier version managed to enqueue
   * a node twice. Verified against the reference degree column: exact match. */
  function bfs(src) {
    const stamp = ++stampCounter;
    dist.fill(-1); parent.fill(-1);
    dist[src] = 0; parent[src] = -1;
    order[0] = src;
    let head = 0, tail = 1;
    while (head < tail) {
      const u = order[head++], d = dist[u] + 1;
      for (let i = p_ip[u], ie = p_ip[u + 1]; i < ie; i++) {
        const ts = p_ix[i];
        if (tstamp[ts] === stamp) continue;
        tstamp[ts] = stamp;
        for (let j = t_ip[ts], je = t_ip[ts + 1]; j < je; j++) {
          const v = t_ix[j];
          if (dist[v] < 0) { dist[v] = d; parent[v] = u; order[tail++] = v; }
        }
      }
    }
    return tail;
  }

  /* Radial tree layout: each subtree gets a wedge proportional to its leaf
   * count, radius by depth. Same rule that generated the original stills, so a
   * recentred chart looks like the ones in the reels. */
  const RING_GAP = 1.6;     // room for the centre portrait, which is now much bigger

  function layout(reached) {
    // leaf counts: reverse BFS order visits every child before its parent
    leaves.fill(0);
    for (let k = reached - 1; k >= 0; k--) {
      const u = order[k];
      if (leaves[u] === 0) leaves[u] = 1;     // no children of its own
      const p = parent[u];
      if (p >= 0) leaves[p] += leaves[u];
    }
    // wedges: forward BFS order, so a parent's span is fixed before its
    // children draw from it. `wAcc` is how much of the parent's wedge is spent.
    const root = order[0];
    wA0[root] = 0; wSpan[root] = Math.PI * 2; wAcc[root] = 0;
    angle[root] = 0; radius[root] = 0;
    // The centre and the first ring both wear a portrait, and at one unit
    // apart those two circles touch. Everything outside the centre moves out
    // by a constant, which opens that gap without changing the spacing
    // between any other pair of rings.
    for (let k = 1; k < reached; k++) {
      const u = order[k], p = parent[u];
      const w = wSpan[p] * (leaves[u] / leaves[p]);
      const start = wA0[p] + wAcc[p];
      wAcc[p] += w;
      wA0[u] = start; wSpan[u] = w; wAcc[u] = 0;
      angle[u] = start + w / 2;
      radius[u] = dist[u] + RING_GAP;
    }
    for (let i = 0; i < P; i++) {
      if (dist[i] < 0) { px[i] = NaN; py[i] = NaN; continue; }
      px[i] = radius[i] * Math.cos(angle[i]);
      py[i] = radius[i] * Math.sin(angle[i]);
    }
  }

  let centreId = 0;

  /* Re-hang everyone routing through the player behind HIM.
   *
   * Placing them in a wedge was not enough: their links still ran back to the
   * branches they came from, so they read as belonging to other players'
   * spokes. Here they are laid out as a tree rooted at the selected player,
   * using the traversal from him (par2) for both the nesting and the links, so
   * the wedge becomes one connected fan hanging off his dot -- the share is
   * visible as an area and as a structure.
   *
   * Radius still comes from distance to the CENTRE, so nobody changes ring and
   * the rest of the chart is untouched beyond taking the remaining angle. */
  function shareLayout(p, mask) {
    let inSet = 0;
    for (let i = 0; i < P; i++) if (mask[i]) inSet++;
    if (!inSet) return { moved: 0, frac: 0 };

    const pa = Math.atan2(py[p], px[p]) || 0;
    const frac = inSet / Math.max(1, P - 1);
    const spanA = 2 * Math.PI * frac;
    const a0A = pa - spanA / 2;
    const secB = [pa + spanA / 2, pa - spanA / 2 + 2 * Math.PI];

    // leaf counts over the p-rooted tree, restricted to the highlighted set
    const lv = new Float64Array(P);
    const kids = new Map();
    for (let k = order2.length - 1, seen = 0; k >= 0 && seen < inSet + 1; k--) { /* noop */ break; }
    const inOrder = [];
    for (let k = 0; k < P; k++) {
      const u = order2[k];
      if (u === p) { inOrder.push(u); continue; }
      if (!mask[u] || dist2[u] < 0) continue;
      inOrder.push(u);
      const q = (par2[u] >= 0 && (mask[par2[u]] || par2[u] === p)) ? par2[u] : p;
      let arr = kids.get(q); if (!arr) { arr = []; kids.set(q, arr); }
      arr.push(u);
    }
    for (let k = inOrder.length - 1; k >= 0; k--) {
      const u = inOrder[k];
      if (!lv[u]) lv[u] = 1;
      const ch = kids.get(u);
      if (ch) { let t = 0; for (const c of ch) t += lv[c] || 1; lv[u] = t; }
    }
    // wedge nesting down the p-rooted tree
    const wa = new Float64Array(P), ws = new Float64Array(P), wacc = new Float64Array(P);
    wa[p] = a0A; ws[p] = spanA; wacc[p] = 0;
    for (const u of inOrder) {
      const ch = kids.get(u);
      if (!ch) continue;
      for (const c of ch) {
        const w = ws[u] * ((lv[c] || 1) / (lv[u] || 1));
        wa[c] = wa[u] + wacc[u]; ws[c] = w; wacc[u] += w; wacc[c] = 0;
        const ang2 = wa[c] + w / 2;
        angle[c] = ang2;
        px[c] = radius[c] * Math.cos(ang2);
        py[c] = radius[c] * Math.sin(ang2);
      }
    }
    // Everyone NOT in the highlight is left exactly where they were. An
    // earlier version also re-angled them into the remaining wedge, which
    // rearranged the whole chart to answer a question about one player; the
    // point is to see the share against the graph you already had.
    return { moved: inSet, frac, angle: pa, span: spanA };
  }

  function throughParent(v) { return par2 ? par2[v] : -1; }

  /* Swing the whole layout so a given player sits at `target` (default: straight
   * down). Names are drawn horizontally, so a path running vertically gets the
   * most separation between consecutive labels -- far more effective than
   * nudging each label out of the way after the fact. */
  function rotateSo(i, targets = [Math.PI / 2, -Math.PI / 2], onlyWithinDeg = 40) {
    const cur = Math.atan2(py[i], px[i]);
    if (!isFinite(cur)) return 0;
    /* Only worth spinning when the chain lies near the horizontal, where
     * horizontal labels stack on top of each other. A chain that already runs
     * steeply has plenty of vertical room, so leave the chart where the reader
     * left it. */
    if (Math.abs(Math.cos(cur)) < Math.cos(onlyWithinDeg * Math.PI / 180)) return 0;
    // straight down or straight up, whichever is the shorter swing -- both give
    // labels the same room, so there is no reason to spin the chart further
    // than necessary
    const list = Array.isArray(targets) ? targets : [targets];
    let delta = Infinity;
    for (const t of list) {
      const d = Math.atan2(Math.sin(t - cur), Math.cos(t - cur));
      if (Math.abs(d) < Math.abs(delta)) delta = d;
    }
    if (!isFinite(delta)) return 0;
    for (let k = 0; k < P; k++) {
      if (dist[k] < 0) continue;
      angle[k] += delta;
      px[k] = radius[k] * Math.cos(angle[k]);
      py[k] = radius[k] * Math.sin(angle[k]);
    }
    return delta;
  }

  function recentre(src) {
    centreId = src;
    const t0 = performance.now();
    const reached = bfs(src);
    const t1 = performance.now();
    layout(reached);
    return { reached, bfsMs: t1 - t0, layoutMs: performance.now() - t1,
             ecc: maxDist() };
  }

  function maxDist() { let m = 0; for (let i = 0; i < P; i++) if (dist[i] > m) m = dist[i]; return m; }

  function pathToCentre(v) {
    const out = [];
    for (let u = v; u >= 0; u = parent[u]) { out.push(u); if (parent[u] < 0) break; }
    return out;
  }

  /* Shortest route between any two players, without moving the chart.
   *
   * The quiz needs to know the answer while the user is still guessing, and
   * recentring to find it would both spoil it -- the target's ring is its
   * degree -- and throw away the layout on screen. So this runs the search,
   * reads the route off it, and puts the centre back before returning. Two
   * traversals, about 4 ms. */
  function route(a, b) {
    bfs(a);
    const d = dist[b];
    const out = [];
    if (d >= 0) for (let u = b; u >= 0; u = parent[u]) { out.push(u); if (parent[u] < 0) break; }
    recentre(centreId);
    return { degrees: d, path: out };          // path runs b -> ... -> a
  }

  /* Everyone who ever shared a squad with this player.
   *
   * Expedition lights these up a step at a time, so it wants the set rather
   * than a traversal. A long career reaches a few thousand people; building the
   * set costs about a millisecond and the caller can keep it. */
  function neighbours(i) {
    const out = new Set();
    for (let k = p_ip[i], ke = p_ip[i + 1]; k < ke; k++) {
      const ts = p_ix[k];
      for (let j = t_ip[ts], je = t_ip[ts + 1]; j < je; j++) out.add(t_ix[j]);
    }
    out.delete(i);
    return out;
  }

  /* Which team-season(s) actually connect two players. The bipartite index
   * already holds this, so a link can say "KAN 2013" rather than just existing.
   * Both lists are short (a career is a handful of team-seasons), so the nested
   * scan is cheaper than building sets. */
  function sharedTeamSeasons(u, v) {
    const out = [];
    for (let i = p_ip[u], ie = p_ip[u + 1]; i < ie; i++) {
      const a = p_ix[i];
      for (let j = p_ip[v], je = p_ip[v + 1]; j < je; j++) {
        if (p_ix[j] === a) { out.push(a); break; }
      }
    }
    out.sort((x, y) => tsSeason[x] - tsSeason[y]);
    return out.map(k => ({ team: tables.teams[tsTeam[k]], season: tsSeason[k] }));
  }

  function teamLabel(code) {
    const m = tables.teamMeta && tables.teamMeta[code];
    if (!m) return code;
    return m.name ? `${m.name} (${code})` : `${code} · ${m.from}\u2013${m.to}`;
  }

  /* First-ring view: the centre's direct teammates only, grouped into a wedge
   * per club they actually shared a season with, biggest club first. Same idea
   * as the fan in the reels. Returns the segments so the view can label them. */
  function ringLayout(centre) {
    const byTeam = new Map();
    for (let i = 0; i < P; i++) {
      if (dist[i] !== 1) continue;
      const sh = sharedTeamSeasons(centre, i);
      const t = sh.length ? sh[0].team : '?';
      let g = byTeam.get(t); if (!g) { g = []; byTeam.set(t, g); }
      g.push(i);
    }
    const groups = [...byTeam.entries()].sort((a, b) => b[1].length - a[1].length);
    const total = groups.reduce((n, g) => n + g[1].length, 0) || 1;
    const R_IN = 3.1, R_OUT = 6.4, PAD = 0.035;
    const segs = [];
    let a = -Math.PI / 2;
    for (const [team, members] of groups) {
      const span = 2 * Math.PI * (members.length / total);
      members.sort((x, y) => firstSeason[x] - firstSeason[y] || x - y);
      const inner = a + span * PAD / 2, outer = a + span * (1 - PAD / 2);
      for (let k = 0; k < members.length; k++) {
        const u = members[k];
        const frac = members.length === 1 ? 0.5 : k / (members.length - 1);
        const ang = inner + (outer - inner) * frac;
        // radius spread deterministic per player so the band has depth
        const jitter = ((u * 2654435761) >>> 0) / 4294967295;
        const r = R_IN + (R_OUT - R_IN) * jitter;
        px[u] = r * Math.cos(ang); py[u] = r * Math.sin(ang);
      }
      segs.push({ team, count: members.length, a0: a, a1: a + span,
                  rIn: R_IN, rOut: R_OUT });
      a += span;
    }
    px[centre] = 0; py[centre] = 0;
    return segs;
  }

  /* Share of connections: how much of the network reaches the current centre
   * by a shortest route that passes through this player.
   *
   *   v routes through p  <=>  dist(centre, v) === dist(centre, p) + dist(p, v)
   *
   * so one extra traversal from p answers it for every player at once -- the
   * same measure behind the "60% through Matt Moore" beat in the reel. */
  function shareThrough(p) {
    const t0 = performance.now();
    const stamp = ++stampCounter;
    dist2.fill(-1); par2.fill(-1); dist2[p] = 0; order2[0] = p;
    let head = 0, tail = 1;
    while (head < tail) {
      const u = order2[head++], d = dist2[u] + 1;
      for (let i = p_ip[u], ie = p_ip[u + 1]; i < ie; i++) {
        const ts = p_ix[i];
        if (tstamp2[ts] === stamp) continue;
        tstamp2[ts] = stamp;
        for (let j = t_ip[ts], je = t_ip[ts + 1]; j < je; j++) {
          const v = t_ix[j];
          if (dist2[v] < 0) { dist2[v] = d; par2[v] = u; order2[tail++] = v; }
        }
      }
    }
    const base = dist[p];
    through.fill(0);
    let count = 0;
    for (let v = 0; v < P; v++) {
      if (v === p || dist[v] < 0 || dist2[v] < 0) continue;
      if (dist[v] === base + dist2[v]) { through[v] = 1; count++; }
    }

    /* "Routes through p" is not the same as "depends on p". Most of these
     * players have several equally short routes and p is only one of them, so
     * the shares of different players overlap heavily and sum to far more than
     * 100%. To separate the two, walk the graph again with p removed: whoever
     * ends up further away (or unreachable) genuinely needed him. */
    const st3 = ++stampCounter;
    dist3.fill(-1); dist3[centreId] = 0; order3[0] = centreId;
    let h3 = 0, t3 = 1;
    while (h3 < t3) {
      const u = order3[h3++], d = dist3[u] + 1;
      if (u === p) continue;                       // p is removed from the graph
      for (let i = p_ip[u], ie = p_ip[u + 1]; i < ie; i++) {
        const ts = p_ix[i];
        if (tstamp3[ts] === st3) continue;
        tstamp3[ts] = st3;
        for (let j = t_ip[ts], je = t_ip[ts + 1]; j < je; j++) {
          const v = t_ix[j];
          if (v !== p && dist3[v] < 0) { dist3[v] = d; order3[t3++] = v; }
        }
      }
    }
    let exclusive = 0, stranded = 0;
    for (let v = 0; v < P; v++) {
      if (v === p || dist[v] < 0) continue;
      if (dist3[v] < 0) { exclusive++; stranded++; }
      else if (dist3[v] > dist[v]) exclusive++;
    }

    return { count, exclusive, stranded, total: P - 1,
             pct: 100 * count / (P - 1),
             exclusivePct: 100 * exclusive / (P - 1),
             ms: performance.now() - t0, mask: through };
  }

  function info(i) {
    return {
      id: i, name: names[i], position: tables.positions[posIdx[i]] || '',
      first: firstSeason[i], last: lastSeason[i], degree: dist[i],
    };
  }

  return {
    load, inflate, bfs, layout, recentre, pathToCentre, route, info, maxDist,
    neighbours,
    sharedTeamSeasons, teamLabel, ringLayout, shareThrough, shareLayout, rotateSo,
    throughParent,
    get P() { return P; }, get names() { return names; },
    get tables() { return tables; },
    get dist() { return dist; }, get parent() { return parent; },
    get order() { return order; },
    get px() { return px; }, get py() { return py; },
    get firstSeason() { return firstSeason; }, get lastSeason() { return lastSeason; },
    get p_ip() { return p_ip; }, get p_ix() { return p_ix; },
    get t_ip() { return t_ip; }, get t_ix() { return t_ix; },
    get tsTeam() { return tsTeam; }, get tsSeason() { return tsSeason; },
    dim, lift, setTheme, V,
    get DEG_COLOUR() { return DEG_COLOUR; },
    get EDGE() { return EDGE; },
    get BG() { return BG; },
    get PATH() { return theme === 'light' ? '#B45309' : PATH; },
    get LINK() { return theme === 'light' ? '#1A202C' : LINK; },
  };
})();
