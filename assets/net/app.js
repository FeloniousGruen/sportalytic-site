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

  // ---------- palette: degree from the centre, matching the reels ----------
  const DEG_COLOUR = ['#2e2e2e', '#f4b400', '#6a5acd', '#23b5d3', '#ff7f50',
                      '#ff4fa3', '#7cc943', '#2ec4b6', '#c77dff', '#ff9f1c',
                      '#00a8ff', '#7a7a7a'];
  const EDGE = 'rgba(150,168,194,0.20)';
  const PATH = '#FBC247';

  let P = 0, T = 0;
  let p_ip, p_ix, t_ip, t_ix;         // bipartite index
  let firstSeason, lastSeason, posIdx, tsTeam, tsSeason;
  let names = [], tables = null;

  // scratch reused across traversals so a recentre allocates nothing
  let dist, parent, order, leaves, radius, angle, px, py, tstamp;
  let wA0, wSpan, wAcc;
  let stampCounter = 0;

  async function loadGz(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url}: ${res.status}`);
    // Pre-gzipped on disk so the transfer size does not depend on the host's
    // content-type compression rules. DecompressionStream is in every current
    // browser; if it ever is not, ship the plain file alongside.
    const stream = res.body.pipeThrough(new DecompressionStream('gzip'));
    return new Response(stream).arrayBuffer();
  }

  async function load(base = 'assets/net') {
    const t0 = performance.now();
    const [gbuf, nbuf, tbl] = await Promise.all([
      loadGz(`${base}/graph.bin.gz`),
      loadGz(`${base}/names.txt.gz`),
      fetch(`${base}/tables.json`).then(r => r.json()),
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
    for (let k = 1; k < reached; k++) {
      const u = order[k], p = parent[u];
      const w = wSpan[p] * (leaves[u] / leaves[p]);
      const start = wA0[p] + wAcc[p];
      wAcc[p] += w;
      wA0[u] = start; wSpan[u] = w; wAcc[u] = 0;
      angle[u] = start + w / 2;
      radius[u] = dist[u];
    }
    for (let i = 0; i < P; i++) {
      if (dist[i] < 0) { px[i] = NaN; py[i] = NaN; continue; }
      px[i] = radius[i] * Math.cos(angle[i]);
      py[i] = radius[i] * Math.sin(angle[i]);
    }
  }

  function recentre(src) {
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

  /* First-ring view: the centre's direct team-mates only, grouped into a wedge
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

  function info(i) {
    return {
      id: i, name: names[i], position: tables.positions[posIdx[i]] || '',
      first: firstSeason[i], last: lastSeason[i], degree: dist[i],
    };
  }

  return {
    load, bfs, layout, recentre, pathToCentre, info, maxDist,
    sharedTeamSeasons, teamLabel, ringLayout,
    get P() { return P; }, get names() { return names; },
    get tables() { return tables; },
    get dist() { return dist; }, get parent() { return parent; },
    get order() { return order; },
    get px() { return px; }, get py() { return py; },
    get firstSeason() { return firstSeason; }, get lastSeason() { return lastSeason; },
    get p_ip() { return p_ip; }, get p_ix() { return p_ix; },
    get t_ip() { return t_ip; }, get t_ix() { return t_ix; },
    get tsTeam() { return tsTeam; }, get tsSeason() { return tsSeason; },
    DEG_COLOUR, EDGE, PATH,
  };
})();
