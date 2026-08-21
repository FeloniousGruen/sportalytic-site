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

  /* Everything that differs between the two datasets. The page sets
     window.SPORT before this script loads; the defaults below are the NFL, so
     network.html keeps working having said nothing.

     The pars are per-sport because the graphs are not the same shape. NFL
     distance is almost entirely an era gap -- 78% of well-known pairs are
     exactly 2 apart -- so its round tops out at 4. English football spreads
     much wider (2, 3, 4, 5 and 6 are all common between names you have heard
     of), because a top flight of twenty clubs over 138 years churns far less,
     so its round can climb properly. Measured, not guessed: see the working in
     tools/build_puzzles.py.

     `store` namespaces the saved history. Sharing one prefix would pile
     football scores into the NFL distribution and make both meaningless. */
  const CFG = Object.assign({
    base: 'assets/net',
    store: 'sp.',
    title: '11 Degrees',
    shareUrl: 'https://sportalytic.co.uk/network.html',
    holes: [{ par: 2, pool: 'r2' }, { par: 3, pool: 'r3' }, { par: 3, pool: 'r3' },
            { par: 3, pool: 'g3' }, { par: 4, pool: 'g4' }],
    // one entry per day of a repeating cycle, so most dailies are modern and
    // the occasional one reaches back
    dailyPools: ['r3', 'r3', 'r3', 'r3', 'g3'],
    dailyPar: 3,
    dailyTarget: 10,
    unit: 'squad',                         // "shared a squad" / "shared a club"
  }, (typeof window !== 'undefined' && window.SPORT) || {});

  const HOLES = CFG.holes;
  const PAR_TOTAL = HOLES.reduce((n, h) => n + h.par, 0);
  const DAILY_TARGET = CFG.dailyTarget;    // beat this on the daily
  /* Giving up is a fixed ten, not the par. Handing you the shortest route and
     then scoring it as if you had found it made surrender the best play on any
     hole you could not see -- you would card a par for pressing a button. */
  const GIVE_UP = 10;
  const MIN_QUERY = 5;                     // letters before a name is offered
  const EPOCH = Date.UTC(2026, 0, 1);

  let puzzles = null;                      // pairs by distance, built offline
  let host = null;                         // the element to draw into
  let onExit = null;                       // hand the screen back to the chart
  let state = null;                        // whatever mode is running

  async function load(base = CFG.base) {
    if (puzzles) return puzzles;
    puzzles = await fetch(`${base}/puzzles.json${NET.V()}`).then(r => r.json());
    return puzzles;
  }

  let onCentred = null;                    // let the page retitle the chart
  function init(el, exit, centred) { host = el; onExit = exit; onCentred = centred; }

  // each mode gets its own accent, so you can tell at a glance which you are in
  function setSkin(name) {
    if (host) host.className = name ? 'skin-' + name : '';
  }

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
    // a renamed bucket used to fail here silently and leave the mode half-built
    if (!rows || !rows.length) throw new Error(`puzzles.json has no "${bucket}" pool`);
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

  /* What you have played, kept on the device. There is no account and no
     server, so this is also the only record of a distribution to compare a new
     score against. */
  const history = {
    // v2: an earlier build replaced your chain with the answer when you gave
    // up, so those records claim you found a route you never found
    dailies() { return store.get('dailies2', {}); },
    rounds() { return store.get('rounds', []); },
    saveDaily(day, rec) {
      const all = history.dailies();
      all[day] = rec;
      store.set('dailies2', all);
    },
    saveRound(rec) {
      const all = history.rounds();
      all.push(rec);
      store.set('rounds', all.slice(-200));
    },
  };

  /* A Wordle-style distribution: one bar per score, yours picked out. Counting
     is done over whatever is in the history, so it reads as your own record
     rather than a leaderboard nobody can verify. */
  function distribution(values, mine, lo, hi, label) {
    if (!values.length) return '';
    const counts = {};
    for (const v of values) {
      const k = Math.min(hi, Math.max(lo, v));
      counts[k] = (counts[k] || 0) + 1;
    }
    const max = Math.max(...Object.values(counts));
    let rows = '';
    for (let k = lo; k <= hi; k++) {
      const c = counts[k] || 0;
      const w = max ? Math.round(100 * c / max) : 0;
      const here = k === Math.min(hi, Math.max(lo, mine));
      rows += `<div class="drow"><span class="dk">${k === hi ? k + '+' : k}</span>
        <span class="dbar ${here ? 'me' : ''}" style="width:${Math.max(w, c ? 8 : 2)}%">${
          c || ''}</span></div>`;
    }
    return `<div class="dist"><div class="dhead">${label} · ${values.length} played</div>${rows}</div>`;
  }

  const store = {
    get(k, d) { try { return JSON.parse(localStorage.getItem(CFG.store + k)) ?? d; }
                catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(CFG.store + k, JSON.stringify(v)); }
                catch (e) { /* private browsing; the game still plays */ } },
  };

  // --------------------------------------------------------------- a leg ---
  /* One A -> B chain. Every mode that involves joining two players uses this;
     it owns the validation, the clue ladder and the chart highlight, and calls
     back when the chain closes. */
  /* Hang the chart off one end of the puzzle, so the chain you are building
     grows out of the middle instead of across a tree rooted on somebody with
     nothing to do with it. */
  function centreOn(i, towards) {
    VIEW.captureFrom();
    NET.recentre(i);
    VIEW.centre = i;
    VIEW.setCentreImage(null);
    VIEW.path = []; VIEW.selected = -1;
    /* And swing the far end onto the vertical. Picking a player does this, so
       a chain always runs down the screen; without it a revealed route came
       out at whatever angle the layout happened to put it, which is a
       different-looking thing every time and hard to follow. The 180 forces
       it -- the default only rotates a chain already near the horizontal. */
    if (towards != null) NET.rotateSo(towards, [Math.PI / 2, -Math.PI / 2], 180);
    VIEW.beginMorph(800);
    if (onCentred) onCentred(i);           // the heading names the centre
  }

  function leg(a, b, opts = {}) {
    const L = {
      a, b, chain: [a], done: false, clues: 0, clueLevel: 0, clue: null,
      par: opts.par ?? null, best: null, revealed: false,
    };
    const first = NET.route(a, b);
    L.best = first.degrees;
    const answer = first.path.slice().reverse();
    L.links = () => L.chain.length - 1;
    L.score = () => L.revealed ? GIVE_UP : L.links() + L.clues;

    L.add = function (i) {
      const last = L.chain[L.chain.length - 1];
      if (i === last) return 'That is the player you are already on.';
      if (L.chain.indexOf(i) >= 0) return 'That player is already in your chain.';
      if (!NET.sharedTeamSeasons(last, i).length)
        return `${NET.names[last]} and ${NET.names[i]} were never teammates.`;
      L.chain.push(i);
      L.clue = null; L.clueLevel = 0; L.clueSpent = false;
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
      NET.rotateSo(b, [Math.PI / 2, -Math.PI / 2], 180);   // route() undid it
      VIEW.invalidate();
      const next = r.path[r.path.length - 2];
      if (next == null) { L.clue = 'No route left from here.'; return; }
      const sh = NET.sharedTeamSeasons(last, next);
      if (!sh.length) { L.clue = 'No clue available.'; return; }
      const f = sh[0];
      const club = (NET.tables.teamMeta[f.team] || {}).name || f.team;
      const info = NET.info(next);
      // no trailing stop: the sentence supplies one, and "A.B.." looks broken
      const initials = NET.names[next].split(/\s+/)
        .map(w => w[0]).filter(Boolean).join('.');
      /* The ladder is built from what is actually known about THIS player, not
         from a fixed list of four. The football source has no position for a
         fifth of its players, and a rung that reads "as a ?" told you nothing
         while still costing you a stroke -- the worst of both. A rung with
         nothing behind it is dropped, and the next real one takes its place. */
      const rungs = [
        `played for <b>${club}</b>`,
        `in <b>${NET.seasonLabel(f.season)}</b>`,
        info.position ? `as a <b>${info.position}</b>` : null,
        initials ? `initials <b>${initials}</b>` : null,
      ].filter(Boolean);
      if (L.clueLevel >= rungs.length) { L.clueSpent = true; return; }
      L.clueLevel++; L.clues++;
      L.clueSpent = L.clueLevel >= rungs.length;
      L.clue = 'Someone who ' + rungs.slice(0, L.clueLevel).join(', ') + '.';
    };

    /* Giving up used to replace your chain with the answer, which lost what
       you had actually tried. The answer is shown alongside instead -- and it
       is the copy taken up front, because NET.route puts the layout back when
       it finishes and that discards the rotation the puzzle was swung into. */
    L.bestPath = () => answer;
    L.reveal = function () { L.done = true; L.revealed = true; };

    L.draw = function () {
      VIEW.selected = -1;
      // give up and the chart shows the answer; otherwise it shows your attempt
      const shown = L.revealed ? L.bestPath() : L.chain;
      VIEW.path = shown.length > 1 ? shown.slice() : [];
    };
    return L;
  }

  // ------------------------------------------------------------ rendering --
  function via(u, v) {
    const sh = NET.sharedTeamSeasons(u, v);
    if (!sh.length) return '';
    const f = sh[0], more = sh.length > 1 ? ` +${sh.length - 1}` : '';
    return `<li class="qstep via"><span class="chip">${f.team}</span> ${
      NET.seasonLabel(f.season)}${more}</li>`;
  }

  function routeHtml(nodes, cls = '') {
    const rows = nodes.map((n, k) =>
      `<li class="qstep ${k === 0 || k === nodes.length - 1 ? 'fix' : ''}">` +
      `<span class="dot"></span>${NET.names[n]}</li>` +
      (k < nodes.length - 1 ? via(n, nodes[k + 1]) : '')).join('');
    return `<ul class="qchain ${cls}">${rows}</ul>`;
  }

  function chainHtml(L, showInput) {
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
      /* Five characters before anything is offered. At two you could type "a"
         and read the answer off a list, which is not the game. */
      if (q.length < MIN_QUERY) { box.hidden = true; return; }
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
    setSkin('round');
    const rng = Math.random;
    state = {
      mode: 'round', hole: 0,
      holes: HOLES.map(h => {
        const [x, y] = pick(h.pool, rng);
        return { par: h.par, a: x, b: y };
      }),
    };
    state.leg = leg(state.holes[0].a, state.holes[0].b, { par: HOLES[0].par });
    centreOn(state.holes[0].a, state.holes[0].b);
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
    centreOn(nx.a, nx.b);
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
    return `${CFG.title} — The Round\n${t.shot} strokes, par ${t.par} (${
      diff === 0 ? 'level' : '+' + diff})\n\n${rows}\n\nHave a go:\n${SHARE_URL}`;
  }

  /* Wordle-style: the shape of the result, not the answer. Nobody wants the
     linking players spoiled for them by a friend's share. */
  const SHARE_URL = CFG.shareUrl;

  function dailyShareText() {
    const L = state.leg, links = L.links(), par = L.best;
    const who = `${NET.names[L.a]} → ${NET.names[L.b]}`;
    const head = `${CFG.title} — daily #${state.day}\n${who}`;
    if (L.revealed) {
      return `${head}\n❌ Beat me today. See if you can do better.\n${SHARE_URL}`;
    }
    const blocks = '🟩'.repeat(Math.min(par, links)) +
                   '🟨'.repeat(Math.max(0, links - par)) +
                   (L.clues ? ' ' + '💡'.repeat(L.clues) : '');
    const line = links === par
      ? `✅ ${links} links — the shortest there is. Have a go:`
      : `✅ ${links} links (${par} is possible). Have a go:`;
    return `${head}\n${blocks}\n${line}\n${SHARE_URL}`;
  }

  async function shareTextOf() {
    return state.mode === 'daily' ? dailyShareText() : shareText();
  }

  async function share() {
    const text = await shareTextOf();
    try {
      if (navigator.share) { await navigator.share({ text }); return 'Shared'; }
      await navigator.clipboard.writeText(text);
      return 'Copied to the clipboard';
    } catch (e) { return null; }
  }

  // ------------------------------------------------------------ the daily --
  /* Par 3, and four days in five it is two players from the last twenty years.
     The fifth reaches back to an all-time great, which is the only way to get
     any era into it without the linking players becoming unnameable. */
  function dailyPuzzle(day) {
    const rng = seeded(day * 2654435761);
    const cyc = CFG.dailyPools;
    return pick(cyc[((day % cyc.length) + cyc.length) % cyc.length], rng);
  }

  function startDaily(day = dayNumber()) {
    setSkin('daily');
    const [a, b] = dailyPuzzle(day);
    const saved = history.dailies()[day];
    state = { mode: 'daily', day, target: DAILY_TARGET, par: CFG.dailyPar,
              today: day === dayNumber() };
    state.leg = leg(a, b, { par: CFG.dailyPar });
    if (saved && saved.chain) {
      // what you actually played, which after giving up is however far you got
      state.leg.chain = saved.chain;
      state.leg.clues = saved.clues || 0;
      state.leg.revealed = !!saved.revealed;
      state.leg.done = true;
      state.replay = true;
    }
    centreOn(a, b);
    render();
  }

  function saveDaily() {
    if (state.replay) return;              // do not overwrite the first attempt
    history.saveDaily(state.day, {
      chain: state.leg.chain, clues: state.leg.clues,
      revealed: state.leg.revealed, score: state.leg.score(),
    });
    state.replay = true;
  }

  /* Every past daily is still playable: the puzzle comes from the day number,
     so nothing had to be stored for it to exist. What is stored is how you did.
   */
  function renderArchive() {
    const today = dayNumber();
    const all = history.dailies();
    const days = [];
    for (let d = today; d > Math.max(-1, today - 60); d--) days.push(d);
    const scores = Object.values(all).map(r => r.score).filter(n => n != null);
    const rounds = history.rounds();
    host.innerHTML = exitBtn() +
      `<h2>Archive</h2>
       <div class="lead">Every daily since the start is still there. Your record
         is kept on this device only.</div>
       ${scores.length ? distribution(scores, -1, CFG.dailyPar, GIVE_UP, 'Your dailies') : ''}
       ${rounds.length ? distribution(rounds.map(r => r.shot), -1, PAR_TOTAL, PAR_TOTAL + 12, 'Your rounds') : ''}
       <div class="gmeta">Pick a day</div>
       <div class="arch">${days.map(d => {
         const r = all[d];
         const cls = r ? (r.revealed ? 'gave' : 'done') : '';
         return `<button class="aday ${cls}" data-day="${d}"
                   title="${r ? 'scored ' + r.score : 'not played'}">${
                   d === today ? 'today' : '#' + d}</button>`;
       }).join('')}</div>
       ${rounds.length ? `<div class="gmeta">Rounds played: ${rounds.length},
          best ${Math.min(...rounds.map(r => r.shot))}</div>` : ''}
       <button class="btn ghost" id="gagain">Back</button>`;
    host.querySelector('.arch').onclick = e => {
      const b = e.target.closest('[data-day]');
      if (b) { setSkin('daily'); startDaily(+b.dataset.day); }
    };
    $('#gagain').onclick = () => onExit();
    $('#gclose').onclick = () => onExit();
  }

  // -------------------------------------------------------- the expedition --
  /* Start anywhere. Name a player and everyone they ever played with lights up
     -- lit, not named. You can only name someone already lit, so the game is
     working out who stands at the edge of what you have found, and the map is
     the only clue you get. */
  function startExpedition(start) {
    setSkin('expedition');
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
         <div class="lead">${state.par} links apart at best. Join them in under
           <b>${state.target}</b> — puzzle #${state.day}${
           state.today ? '' : ' (from the archive)'}.</div>`
      : `<h2>Hole ${state.hole + 1} of ${HOLES.length}</h2>
         <div class="lead">Par <b>${L.par}</b>. Join
           <b>${NET.names[L.a]}</b> to <b>${NET.names[L.b]}</b>.</div>`;

    let verdict = '', best = '';
    if (L.done) {
      const links = L.links();
      const shortest = L.bestPath();
      const matched = !L.revealed && links === L.best;
      if (daily) {
        verdict = L.revealed
          ? `<div class="qdone"><b>Not this time.</b> You did not solve
               puzzle #${state.day}. There is a new one tomorrow.</div>`
          : `<div class="qdone"><b>Solved in ${links}</b>${
               L.clues ? ` link${links === 1 ? '' : 's'} plus ${L.clues} clue${
                 L.clues === 1 ? '' : 's'} — <b>${L.score()}</b> in all` : ''}. ${
               matched ? 'Nobody links them in fewer.'
                       : `The shortest way there is ${L.best}.`}</div>`;
      } else {
        const sc = L.score();
        verdict = L.revealed
          ? `<div class="qdone"><b>${sc}</b> for giving up on this one, against
               a par of ${L.par}.</div>`
          : `<div class="qdone"><b>${sc}</b> against a par of ${L.par}${
               matched ? ' — the shortest there is.' : `, ${sc - L.par} over.`}</div>`;
      }
      /* Show the answer beside what you did whenever they differ. Being told
         you took six is not much use without seeing what three looked like. */
      if (!matched && shortest.length) {
        const yourLabel = L.revealed
          ? (links ? `How far you got — ${links} link${links === 1 ? '' : 's'}`
                   : 'You did not get started')
          : `Your route — ${links} link${links === 1 ? '' : 's'}`;
        best = `<div class="routes">
                  <div><div class="rhead">${yourLabel}</div>${chainHtml(L, false)}</div>
                  <div><div class="rhead">${L.revealed ? 'The answer'
                        : `The shortest — ${L.best}`}</div>${routeHtml(shortest, 'best')}</div>
                </div>`;
      }
    }

    let chart = '';
    if (L.done && daily) {
      saveDaily();
      const all = history.dailies();
      const scores = Object.values(all).map(r => r.score).filter(n => n != null);
      chart = distribution(scores, L.score(), CFG.dailyPar, GIVE_UP, 'Your dailies');
    }
    const t = state.mode === 'round' ? roundTotals() : null;
    host.innerHTML = exitBtn() + head +
      (best ? '' : chainHtml(L, true)) + verdict + best + chart +
      `<div class="gmeta">${L.links()} link${L.links() === 1 ? '' : 's'}${
        L.clues ? ` · ${L.clues} clue${L.clues === 1 ? '' : 's'}` : ''}${
        t && t.played ? ` · round so far ${t.shot} (par ${t.par})` : ''}</div>` +
      (L.done
        ? (state.mode === 'round'
            ? `<button class="btn" id="gnexth">${
                state.hole === HOLES.length - 1 ? 'See the card' : 'Next hole'}</button>`
            : `<button class="btn" id="gshare">Share your result</button>
               <button class="btn ghost" id="gagain">Back</button>`)
        : `${L.clueSpent ? '' : `<button class="btn ghost" id="gclue">${
              L.clueLevel ? 'Another clue' : 'Clue'} (+1)</button>`}
           <button class="btn ghost" id="ggive">Give up on this one</button>`);

    if (!L.done) {
      wireInput(L, err => { render(); if (err) flash(err); });
      const cl = $('#gclue');
      if (cl) cl.onclick = () => { L.nextClue(); render(); };
      $('#ggive').onclick = () => { L.reveal(); if (daily) saveDaily(); render(); };
    } else {
      const nx = $('#gnexth'); if (nx) nx.onclick = nextHole;
      const sh = $('#gshare');
      if (sh) sh.onclick = async () => { const m = await share(); if (m) flash(m); };
      const ag = $('#gagain'); if (ag) ag.onclick = () => onExit();
    }
    $('#gclose').onclick = () => onExit();
    host.scrollTop = 0;          // a long result should not open half-read
    L.draw();
  }

  function renderCard() {
    const t = roundTotals();
    const diff = t.shot - t.par;
    if (!state.saved) {
      history.saveRound({ shot: t.shot, par: t.par,
                          holes: state.holes.map(h => [h.a, h.b, h.par, h.score]) });
      state.saved = true;
    }
    const past = history.rounds().map(r => r.shot);
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
       ${distribution(past, t.shot, t.par, t.par + 12, 'Your rounds')}
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
           renderArchive, setSkin,
           get state() { return state; },
           stop() { state = null; VIEW.lit = null; setSkin(null); } };
})();
