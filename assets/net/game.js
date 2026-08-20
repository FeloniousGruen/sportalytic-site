/* Sportalytic — the games played on the teammate network.
 *
 * Four modes, three of which are the same thing underneath: join two players by
 * naming the people who link them. That shared part is `leg` below. Expedition
 * is a different shape and sits on its own at the bottom.
 *
 * A link is only accepted if the two players actually shared a squad in the
 * same season, which the graph can answer exactly, so nothing here needs a
 * server or a word list -- the record is the referee.
 *
 * Distance is really an era gap: two current players are almost always 2 apart,
 * and reaching 5 or 6 means crossing fifty or seventy years. The long holes are
 * hard for that reason, and the clue ladder exists to make them finishable.
 */
'use strict';

const GAME = (() => {

  const $ = s => document.querySelector(s);
  /* Five holes: 2, 3, 3, 3, 4 -- fifteen in all, and fifteen is the best there
     is, since a shortest route cannot be beaten. The first three come from the
     pool of players active in the last thirty years, the last two reach back
     within fifty, which is as far as a round can go and still be playable.
     Distance is an era gap, so a par 5 or 6 would mean naming journeymen from
     the 1950s and nobody finishes those. */
  const HOLES = [
    { par: 2, pool: 'r2' }, { par: 3, pool: 'r3' }, { par: 3, pool: 'r3' },
    { par: 3, pool: 'm3' }, { par: 4, pool: 'm4' },
  ];
  const PAR_TOTAL = HOLES.reduce((n, h) => n + h.par, 0);
  const DAILY_TARGET = 10;                 // beat this on the daily
  const EPOCH = Date.UTC(2026, 0, 1);

  let puzzles = null;                      // pairs by distance, built offline
  let host = null;                         // the element to draw into
  let onExit = null;                       // hand the screen back to the chart
  let state = null;                        // whatever mode is running

  async function load(base = 'assets/net') {
    if (puzzles) return puzzles;
    puzzles = await fetch(`${base}/puzzles.json`).then(r => r.json());
    return puzzles;
  }

  function init(el, exit) { host = el; onExit = exit; }

  // ---------------------------------------------------------------- utils --
  const lower = () => (lower.c || (lower.c = NET.names.map(s => s.toLowerCase())));

  function findByName(s) {
    s = s.replace(/\s*\((?:\d{4})\s*[–-]\s*(?:\d{4})\)\s*$/, '').trim().toLowerCase();
    if (!s) return -1;
    const L = lower();
    let part = -1;
    for (let i = 0; i < NET.P; i++) {
      if (L[i] === s) return i;
      if (part < 0 && L[i].indexOf(s) >= 0) part = i;
    }
    return part;
  }

  function pick(bucket, rng) {
    const rows = puzzles.buckets[bucket];
    return rows[Math.floor(rng() * rows.length)];
  }

  // A seed the whole world shares for a given day, so the daily is the same
  // puzzle everywhere without anything being served.
  function dayNumber(now = new Date()) {
    const utc = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    return Math.floor((utc - EPOCH) / 86400000);
  }

  function seeded(n) {                     // mulberry32, plenty for picking rows
    let a = n >>> 0;
    return () => {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  const store = {
    get(k, d) { try { return JSON.parse(localStorage.getItem('sp.' + k)) ?? d; }
                catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('sp.' + k, JSON.stringify(v)); }
                catch (e) { /* private browsing; the game still plays */ } },
  };

  // --------------------------------------------------------------- a leg ---
  /* One A -> B chain. Every mode that involves joining two players uses this;
     it owns the validation, the clue ladder and the chart highlight, and calls
     back when the chain closes. */
  function leg(a, b, opts = {}) {
    const L = {
      a, b, chain: [a], done: false, clues: 0, clueLevel: 0, clue: null,
      par: opts.par ?? null, best: null, revealed: false,
    };
    L.best = NET.route(a, b).degrees;
    L.links = () => L.chain.length - 1;
    L.score = () => L.links() + L.clues;

    L.add = function (i) {
      const last = L.chain[L.chain.length - 1];
      if (i === last) return 'That is the player you are already on.';
      if (L.chain.indexOf(i) >= 0) return 'That player is already in your chain.';
      if (!NET.sharedTeamSeasons(last, i).length)
        return `${NET.names[last]} and ${NET.names[i]} were never teammates.`;
      L.chain.push(i);
      L.clue = null; L.clueLevel = 0;
      if (i === b) L.done = true;
      return null;
    };

    /* Four rungs, each costing a stroke, worked out from wherever you have got
       to rather than from a fixed answer -- so a clue still helps after you
       have wandered off the shortest route. Hole six spans seventy years and
       the players who bridge it are journeymen; without this ladder almost
       nobody finishes it. */
    L.nextClue = function () {
      const last = L.chain[L.chain.length - 1];
      const r = NET.route(last, b);
      const next = r.path[r.path.length - 2];
      if (next == null) { L.clue = 'No route left from here.'; return; }
      const sh = NET.sharedTeamSeasons(last, next);
      if (!sh.length) { L.clue = 'No clue available.'; return; }
      if (L.clueLevel >= 4) return;
      L.clueLevel++; L.clues++;
      const f = sh[0];
      const club = (NET.tables.teamMeta[f.team] || {}).name || f.team;
      const info = NET.info(next);
      // no trailing stop: the sentence supplies one, and "A.B.." looks broken
      const initials = NET.names[next].split(/\s+/)
        .map(w => w[0]).filter(Boolean).join('.');
      const bits = [`played for <b>${club}</b>`];
      if (L.clueLevel >= 2) bits.push(`in <b>${f.season}</b>`);
      if (L.clueLevel >= 3) bits.push(`as a <b>${info.position || '?'}</b>`);
      if (L.clueLevel >= 4) bits.push(`initials <b>${initials}</b>`);
      L.clue = 'Someone who ' + bits.join(', ') + '.';
    };

    L.reveal = function () {
      L.chain = NET.route(a, b).path.slice().reverse();
      L.done = true; L.revealed = true;
    };

    L.draw = function () {
      VIEW.selected = -1;
      VIEW.path = L.chain.length > 1 ? L.chain.slice() : [];
    };
    return L;
  }

  // ------------------------------------------------------------ rendering --
  function chainHtml(L, showInput) {
    const via = (u, v) => {
      const sh = NET.sharedTeamSeasons(u, v);
      if (!sh.length) return '';
      const f = sh[0], more = sh.length > 1 ? ` +${sh.length - 1}` : '';
      return `<li class="qstep via"><span class="chip">${f.team}</span> ${f.season}${more}</li>`;
    };
    const rows = L.chain.map((n, k) =>
      `<li class="qstep ${k === 0 ? 'fix' : ''}"><span class="dot"></span>${NET.names[n]}</li>`
      + (k < L.chain.length - 1 ? via(n, L.chain[k + 1]) : '')).join('');
    const gap = showInput && !L.done
      ? `<li class="qstep gap"><input id="gnext" placeholder="Next teammate…" autocomplete="off">
           <div id="gres" hidden></div>
           ${L.clue ? `<div class="qclue">${L.clue}</div>` : ''}</li>` : '';
    const target = L.done ? ''
      : `<li class="qstep fix"><span class="dot"></span>${NET.names[L.b]}</li>`;
    return `<ul class="qchain">${rows}${gap}${target}</ul>`;
  }

  function wireInput(L, after) {
    const inp = $('#gnext');
    if (!inp) return;
    inp.oninput = () => {
      const q = inp.value.trim().toLowerCase();
      const box = $('#gres');
      if (q.length < 2) { box.hidden = true; return; }
      const L2 = lower(), out = [];
      for (let i = 0; i < NET.P && out.length < 25; i++)
        if (L2[i].indexOf(q) >= 0) out.push(i);
      box.hidden = false;
      box.innerHTML = out.length ? out.map(i =>
        `<div data-i="${i}">${NET.names[i]} <span style="color:var(--grey)">${
          NET.firstSeason[i]}–${NET.lastSeason[i]}</span></div>`).join('')
        : '<div style="color:var(--grey)">No players match</div>';
    };
    inp.focus();
    $('#gres').onclick = e => {
      const d = e.target.closest('[data-i]');
      if (!d) return;
      after(L.add(+d.dataset.i));
    };
  }

  function exitBtn() {
    return `<button class="xclose" id="gclose" title="Back to the chart">&times;</button>`;
  }

  // ------------------------------------------------------------ the round --
  /* Five holes at par 2, 3, 4, 5 and 6 -- twenty in total, and twenty is the
     best there is, because a shortest route cannot be beaten. Everything above
     that is strokes dropped, which is why it reads like golf. */
  function startRound() {
    const rng = Math.random;
    state = {
      mode: 'round', hole: 0,
      holes: HOLES.map(h => {
        const [x, y] = pick(h.pool, rng);
        return { par: h.par, a: x, b: y };
      }),
    };
    state.leg = leg(state.holes[0].a, state.holes[0].b, { par: HOLES[0].par });
    render();
  }

  function roundTotals() {
    const done = state.holes.filter(h => h.score != null);
    return {
      played: done.length,
      shot: done.reduce((n, h) => n + h.score, 0),
      par: done.reduce((n, h) => n + h.par, 0),
    };
  }

  function nextHole() {
    const h = state.holes[state.hole];
    h.score = state.leg.score();
    h.gave = state.leg.revealed;
    if (state.hole === state.holes.length - 1) { state.finished = true; render(); return; }
    state.hole++;
    const nx = state.holes[state.hole];
    state.leg = leg(nx.a, nx.b, { par: nx.par });
    render();
  }

  function shareText() {
    const t = roundTotals();
    const diff = t.shot - t.par;
    const rows = state.holes.map(h => {
      const over = h.score - h.par;
      const mark = h.gave ? '❌' : over === 0 ? '🟢' : over <= 2 ? '🟡' : '🔴';
      return `${mark} par ${h.par} — ${NET.names[h.a]} → ${NET.names[h.b]}: ${h.score}`;
    }).join('\n');
    return `11 Degrees — The Round\n${t.shot} strokes (${diff === 0 ? 'level par' :
      diff > 0 ? '+' + diff : diff})\n\n${rows}\n\nEvery NFL player since 1920.`;
  }

  async function share() {
    const text = shareText();
    try {
      if (navigator.share) { await navigator.share({ text }); return 'Shared'; }
      await navigator.clipboard.writeText(text);
      return 'Copied to the clipboard';
    } catch (e) { return null; }
  }

  // ------------------------------------------------------------ the daily --
  function startDaily() {
    const day = dayNumber();
    const saved = store.get('daily', null);
    const [a, b] = pick('m4', seeded(day * 2654435761));
    state = { mode: 'daily', day, target: DAILY_TARGET };
    if (saved && saved.day === day && saved.done) {
      state.leg = leg(a, b);
      state.leg.chain = saved.chain;
      state.leg.clues = saved.clues;
      state.leg.done = true;
      state.leg.revealed = saved.revealed;
      state.replay = true;
    } else {
      state.leg = leg(a, b);
    }
    render();
  }

  function saveDaily() {
    store.set('daily', {
      day: state.day, done: state.leg.done, chain: state.leg.chain,
      clues: state.leg.clues, revealed: state.leg.revealed,
    });
  }

  // -------------------------------------------------------- the expedition --
  /* Start anywhere. Name a player and everyone they ever played with lights up
     -- lit, not named. You can only name someone already lit, so the game is
     working out who stands at the edge of what you have found, and the map is
     the only clue you get. */
  function startExpedition(start) {
    NET.recentre(start);
    const lit = new Uint8Array(NET.P);
    state = { mode: 'expedition', start, lit, unlocked: [], litCount: 0 };
    unlock(start);
    VIEW.centre = start;
    VIEW.path = []; VIEW.selected = -1;
    VIEW.lit = lit;
    VIEW.fit();
    render();
  }

  function unlock(i) {
    const { lit } = state;
    lit[i] = 2;
    state.unlocked.push(i);
    for (const v of NET.neighbours(i)) if (lit[v] === 0) lit[v] = 1;
    state.litCount = 0;
    for (let k = 0; k < lit.length; k++) if (lit[k]) state.litCount++;
    VIEW.lit = lit;
  }

  function expeditionAdd(i) {
    if (state.lit[i] === 2) return 'You have already named them.';
    if (state.lit[i] !== 1) return 'Nobody you have found so far played with them.';
    unlock(i);
    return null;
  }

  // ------------------------------------------------------------- rendering --
  function render() {
    if (!state) return;
    if (state.mode === 'expedition') return renderExpedition();
    if (state.mode === 'round' && state.finished) return renderCard();
    renderLeg();
  }

  function renderLeg() {
    const L = state.leg;
    const daily = state.mode === 'daily';
    const head = daily
      ? `<h2>The daily</h2>
         <div class="lead">Four links apart at best. Join them in under
           <b>${state.target}</b> — puzzle #${state.day}.</div>`
      : `<h2>Hole ${state.hole + 1} of 5</h2>
         <div class="lead">Par <b>${L.par}</b>. Join
           <b>${NET.names[L.a]}</b> to <b>${NET.names[L.b]}</b>.</div>`;

    let verdict = '';
    if (L.done) {
      const s = L.score();
      if (daily) {
        const win = !L.revealed && s < state.target;
        verdict = `<div class="qdone"><b>${s}</b> link${s === 1 ? '' : 's'}${
          L.clues ? ` (${L.clues} from clues)` : ''}. ${
          L.revealed ? 'That is the shortest route.'
            : win ? `Under ${state.target} — that is a win.`
                  : `Over ${state.target} today.`}</div>`;
      } else {
        const over = s - L.par;
        verdict = `<div class="qdone"><b>${s}</b> against a par of ${L.par}${
          over === 0 ? ' — the shortest there is.'
                     : `, ${over} over.`}</div>`;
      }
    }

    const t = state.mode === 'round' ? roundTotals() : null;
    host.innerHTML = exitBtn() + head + chainHtml(L, true) + verdict +
      `<div class="gmeta">${L.links()} link${L.links() === 1 ? '' : 's'}${
        L.clues ? ` · ${L.clues} clue${L.clues === 1 ? '' : 's'}` : ''}${
        t && t.played ? ` · round so far ${t.shot} (par ${t.par})` : ''}</div>` +
      (L.done
        ? (state.mode === 'round'
            ? `<button class="btn" id="gnexth">${
                state.hole === 4 ? 'See the card' : 'Next hole'}</button>`
            : `<button class="btn ghost" id="gagain">Back to the chart</button>`)
        : `<button class="btn ghost" id="gclue">${
              L.clueLevel ? 'Another clue' : 'Clue'} (+1)</button>
           <button class="btn ghost" id="ggive">Give up on this one</button>`);

    if (!L.done) {
      wireInput(L, err => { render(); if (err) flash(err); });
      $('#gclue').onclick = () => { L.nextClue(); render(); };
      $('#ggive').onclick = () => { L.reveal(); if (daily) saveDaily(); render(); };
    } else {
      if (daily) saveDaily();
      const nx = $('#gnexth'); if (nx) nx.onclick = nextHole;
      const ag = $('#gagain'); if (ag) ag.onclick = () => onExit();
    }
    $('#gclose').onclick = () => onExit();
    L.draw();
  }

  function renderCard() {
    const t = roundTotals();
    const diff = t.shot - t.par;
    host.innerHTML = exitBtn() +
      `<h2>The card</h2>
       <div class="lead">${diff === 0
          ? `${t.shot} against a par of ${t.par}. Nobody links them faster.`
          : `${t.shot} strokes, ${diff} over par.`}</div>
       <ul class="qchain card">${state.holes.map((h, k) => {
         const over = h.score - h.par;
         return `<li class="qstep"><span class="dot"></span>
           <b>${h.score}</b> <span style="color:var(--grey)">par ${h.par}</span>
           — ${NET.names[h.a]} → ${NET.names[h.b]}
           ${h.gave ? '<span style="color:#F38A1C"> gave up</span>'
                    : over ? `<span style="color:var(--grey)"> +${over}</span>` : ''}</li>`;
       }).join('')}</ul>
       <div class="gmeta">Par ${t.par} · you shot ${t.shot}</div>
       <button class="btn" id="gshare">Share the card</button>
       <button class="btn ghost" id="gagain">Play another round</button>`;
    $('#gshare').onclick = async () => {
      const msg = await share();
      if (msg) flash(msg);
    };
    $('#gagain').onclick = startRound;
    $('#gclose').onclick = () => onExit();
  }

  function renderExpedition() {
    const pct = (100 * state.litCount / NET.P).toFixed(1);
    host.innerHTML = exitBtn() +
      `<h2>Expedition</h2>
       <div class="lead">Name anyone lit on the chart and their teammates light
         up too. You are told where they are, never who they are.</div>
       <div class="gbig"><b>${state.litCount.toLocaleString()}</b>
         <span>of ${NET.P.toLocaleString()} found · ${pct}%</span></div>
       <div class="slot"><input id="gnext" placeholder="Name a player…" autocomplete="off">
         <div id="gres" hidden></div></div>
       <div class="gmeta">${state.unlocked.length} named ·
         started from ${NET.names[state.start]}</div>
       <ul class="qchain">${state.unlocked.slice().reverse().slice(0, 8).map(i =>
          `<li class="qstep"><span class="dot"></span>${NET.names[i]}</li>`).join('')}</ul>
       <button class="btn ghost" id="gagain">Start somewhere else</button>`;
    const fake = { add: expeditionAdd };
    wireInput(fake, err => { render(); if (err) flash(err); });
    $('#gagain').onclick = () => { VIEW.lit = null; onExit(); };
    $('#gclose').onclick = () => { VIEW.lit = null; onExit(); };
  }

  function flash(msg) {
    const el = document.createElement('div');
    el.className = 'qerr'; el.textContent = msg;
    host.appendChild(el);
    setTimeout(() => el.remove(), 2600);
  }

  return { load, init, startRound, startDaily, startExpedition, dayNumber,
           get state() { return state; },
           stop() { state = null; VIEW.lit = null; } };
})();
