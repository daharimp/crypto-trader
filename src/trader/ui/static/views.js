/* Trader Desk account views (ADR-037): Overview, Positions and Trades for the leverage
   paper account and the spot account. Read-only: every request is a GET to /api. */
(() => {
  'use strict';
  const { $, el, svg, usd, signed, pct, arrow, tone, digits, span, when, stat, meter, get, openSheet } = Desk;
  const D = { status: null, watch: [], paper: null, errors: {} };
  const SIGNALS = { tsmom_30d: '1-month trend', sma_stance_20_50: 'moving-average trend', consensus_sma_tsmom: 'both trend rules agree' };
  const NEAR = 15; // Reason: display only; a position inside 15% of liquidation is drawn amber.
  let account = 'perps';
  const num = (x) => (x == null || x === '' || Number.isNaN(Number(x)) ? null : Number(x));
  const priceOf = (instrument) => D.watch.find((w) => w.market === String(instrument).split(/[-/]/)[0])?.price ?? null;
  const card = (...kids) => { const c = el('section', 'card'); c.append(...kids); return c; };
  const heading = (text, right) => { const r = el('div', 'row'); r.append(el('h2', 'label', text)); if (right) r.append(right); return r; };

  // ---- one shape for both accounts ----
  function perpsModel() {
    const a = D.paper;
    if (!a) return { error: D.errors.paper || 'Loading…' };
    if (!a.running) return { error: 'The leverage paper account has not started. On the server: docker compose up -d perps' };
    const equity = num(a.equity_usd), start = num(a.start_equity_usd);
    const positions = a.positions.map((p) => {
      const size = num(p.size_usd), coll = num(p.collateral_usd), entry = num(p.entry_price), now = priceOf(p.market), liq = num(p.liquidation_price);
      // Reason: an estimate at the latest Kraken price, before closing fees and borrow; the
      // account itself marks at completed candles.
      const move = now == null || !entry ? null : (p.side === 'long' ? now / entry - 1 : 1 - now / entry);
      const dist = now == null || liq == null || liq <= 0 ? null : (p.side === 'long' ? (now - liq) / now : (liq - now) / now) * 100;
      return { coin: p.market, side: p.side, lev: num(p.leverage) ?? (coll ? size / coll : null), size, coll, entry, now, liq, dist,
        pnl: move == null ? null : move * size, opened: p.opened_at };
    });
    const trades = (a.trades || []).map((t) => ({ coin: t.market, side: t.side, lev: num(t.leverage), entry: num(t.entry), exit: num(t.exit),
      opened: t.opened_at, closed: t.closed_at, pnl: num(t.pnl_usd), liquidated: !!t.liquidated, reason: t.reason }));
    const points = (a.equity || []).map((e) => ({ t: Date.parse(e.at_utc), v: num(e.equity_usd) })).filter((p) => p.v != null && !Number.isNaN(p.t));
    const dayStart = points.length ? points[points.length - 1].v : null;
    if (equity != null) points.push({ t: Date.parse(a.last_cycle_utc) || Date.now(), v: equity });
    return {
      kind: 'perps', equity, start, points, positions, trades,
      title: 'Account value · paper money', since: a.started_at,
      today: dayStart == null || equity == null ? null : equity - dayStart,
      stats: [['Largest drop so far', `${num(a.max_drawdown_pct)?.toFixed(2) ?? '—'}%`], ['Fees and borrow paid', usd(num(a.fees_paid_usd))]],
      health: [['Rule', SIGNALS[a.signal] || a.signal], ['Candles', a.timeframe], ['Candles processed', String(a.cycles)],
        ['Last check', a.last_cycle_utc ? `${span(Date.now() - Date.parse(a.last_cycle_utc))} ago` : '—'], ['Started', when(a.started_at)]],
      note: 'Simulated money; it cannot place a real order. Account value is marked at the last completed candle; gain or loss per position uses the latest Kraken price, before closing fees and borrow. The liquidation price is the one recorded when the position opened. Results are not a forecast; profit is not guaranteed.',
    };
  }
  function spotModel() {
    const all = (D.status?.sessions || []).filter((s) => !s.error);
    const s = all.find((x) => x.environment === 'live') || all[0];
    if (!s) return { error: D.errors.status || 'No spot session has run on this server yet. On the server: docker compose up -d paper' };
    const live = s.environment === 'live', gate = D.status.live_gate;
    const positions = s.positions.map((p) => {
      const now = priceOf(p.instrument);
      return { coin: String(p.instrument).split(/[-/]/)[0], side: 'long', lev: null, qty: p.quantity, entry: p.entry, now, stop: p.stop,
        size: now == null ? null : now * p.quantity, pnl: now == null ? null : (now - p.entry) * p.quantity,
        room: now && p.stop ? (now - p.stop) / now * 100 : null };
    });
    const trades = [...s.trades].reverse().map((t) => ({ coin: String(t.instrument).split(/[-/]/)[0], side: 'long', lev: null, entry: t.entry, exit: t.exit,
      opened: t.opened_at, closed: t.closed_at, pnl: t.pnl_usd, liquidated: false, reason: null }));
    const health = [['Checks run', String(s.cycles)], ['Last check', s.last_cycle_utc ? `${span(Date.now() - Date.parse(s.last_cycle_utc))} ago` : '—'],
      ['Last candle', when(s.last_bar)], ['Loss breaker', s.breaker_open ? 'OPEN: paused' : 'closed (normal)'], ['Missed data cycles', String(s.stale_cycles)]];
    if (!live && gate?.min_paper_cycles) health.push(['Road to live', `${Math.min(s.cycles, gate.min_paper_cycles)} of ${gate.min_paper_cycles} paper cycles`]);
    return {
      kind: 'spot', equity: s.equity_usd, start: null, points: [], positions, trades, cash: s.cash_usd,
      title: `Account value · ${live ? 'live' : 'paper money'}`,
      today: s.day_start_usd == null ? null : s.equity_usd - s.day_start_usd,
      stats: [['Cash', usd(s.cash_usd)], ['Highest value', usd(s.high_water_usd)], ['Fees paid', usd(s.fees_usd)]],
      health,
      note: 'Account value is cash plus open positions at the price of the last completed 4-hour candle. Gain or loss per position uses the latest Kraken price and is before selling fees. Results are not a forecast; profit is not guaranteed.',
    };
  }
  const model = () => (account === 'perps' ? perpsModel() : spotModel());

  // ---- account value over time ----
  function valueChart(points, start) {
    const W = 800, H = 200, vs = points.map((p) => p.v).concat(start == null ? [] : [start]);
    const lo = Math.min(...vs), hi = Math.max(...vs), pad = (hi - lo || 1) * 0.12;
    const t0 = points[0].t, t1 = points[points.length - 1].t;
    const x = (t) => ((t - t0) / (t1 - t0 || 1)) * W, y = (v) => H - ((v - (lo - pad)) / (hi - lo + 2 * pad)) * H;
    const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)} ${y(p.v).toFixed(1)}`).join(' ');
    const s = svg('svg', { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', class: 'spark-big', role: 'img',
      'aria-label': `Account value from ${when(new Date(t0).toISOString())} to now, ${usd(points[0].v)} to ${usd(points[points.length - 1].v)}` });
    if (start != null) s.append(svg('line', { x1: 0, x2: W, y1: y(start), y2: y(start), stroke: 'currentColor', 'stroke-opacity': 0.45, 'stroke-dasharray': '4 5', 'vector-effect': 'non-scaling-stroke' }));
    s.append(svg('path', { d: `${path} L${W} ${H} L0 ${H} Z`, fill: 'currentColor', 'fill-opacity': 0.12 }),
      svg('path', { d: path, fill: 'none', stroke: 'currentColor', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke' }));
    return s;
  }

  // ---- Overview ----
  function drawOverview(m) {
    const box = $('overview'); box.replaceChildren();
    if (m.error) { box.append(card(el('p', 'empty', m.error))); return; }
    const hero = card(el('div', 'label', m.title), el('div', 'hero', usd(m.equity)));
    if (m.start != null) {
      const d = m.equity - m.start, line = el('div', `delta ${tone(d)}`, `${arrow(d)}${signed(d)} (${pct(m.start ? d / m.start * 100 : null, 2)}) `);
      line.append(el('span', null, `since ${when(m.since)} with ${usd(m.start)}`)); hero.append(line);
    } else if (m.today != null) {
      const line = el('div', `delta ${tone(m.today)}`, `${arrow(m.today)}${signed(m.today)} `); line.append(el('span', null, 'today')); hero.append(line);
    }
    if (m.points.length > 1) hero.append(valueChart(m.points, m.start), el('p', 'note', 'One point per day so far. The dashed line is the starting amount.'));
    const stats = el('div', 'stats');
    if (m.start != null && m.today != null) stats.append(stat('Today', signed(m.today), tone(m.today)));
    m.stats.forEach(([k, v]) => stats.append(stat(k, v)));
    hero.append(stats);

    const side = el('div', 'stack');
    const closest = m.positions.filter((p) => p.dist != null).sort((a, b) => a.dist - b.dist)[0];
    if (closest) {
      const r = el('div', 'risk');
      r.append(el('div', null, 'Closest to being liquidated'), el('div', 'big', `${closest.coin} ${closest.side} · ${closest.dist.toFixed(1)}% away`),
        el('div', null, `It is closed, and its ${usd(closest.coll)} lost, if ${closest.coin} ${closest.side === 'long' ? 'falls' : 'rises'} from ${usd(closest.now, digits(closest.coin))} to ${usd(closest.liq, digits(closest.coin))}.`));
      side.append(r);
    }
    const inUse = m.kind === 'perps' ? m.positions.reduce((a, p) => a + (p.coll || 0), 0) : m.equity - m.cash;
    const share = m.equity > 0 ? Math.max(0, inUse / m.equity) : 0, use = card();
    const top = el('div', 'row'); top.append(el('span', 'muted', 'Your money in open positions'), el('span', 'num', `${Math.round(share * 100)}%`));
    use.append(top, meter(share, `${Math.round(share * 100)} percent of the account is in open positions`), el('div', 'num muted', `${usd(inUse)} of ${usd(m.equity)}`));
    const health = card(el('h2', 'label', 'Bot health')), grid = el('div', 'stats');
    m.health.forEach(([k, v]) => grid.append(stat(k, v)));
    health.append(grid);
    side.append(use, health);
    const grid2 = el('div', 'grid2'); grid2.append(hero, side);
    box.append(grid2, el('p', 'note', m.note));
  }

  // ---- Positions ----
  function positionSheet(p) {
    const head = el('div', 'row'), left = el('div', 'row');
    left.append(el('span', 'coin', p.coin), el('span', 'tag', `${p.side === 'short' ? '▼ short' : '▲ long'}${p.lev ? ` · ${p.lev.toFixed(1)}x` : ''}`));
    head.append(left, el('span', `num ${tone(p.pnl)}`, signed(p.pnl)));
    const d = digits(p.coin), kv = el('div', 'kv');
    const rows = p.lev != null
      ? [['Position size', usd(p.size)], ['Your money in it', usd(p.coll)], ['Entry price', usd(p.entry, d)], ['Price now', usd(p.now, d)],
        ['Liquidation price', usd(p.liq, d)], ['Distance to liquidation', p.dist == null ? '—' : `${p.dist.toFixed(1)}%`], ['Opened', when(p.opened)]]
      : [['Amount', String(p.qty)], ['Worth now', usd(p.size)], ['Bought at', usd(p.entry, d)], ['Price now', usd(p.now, d)],
        ['Stop price', usd(p.stop, d)], ['Distance to stop', p.room == null ? '—' : `${p.room.toFixed(1)}%`]];
    rows.forEach(([k, v]) => kv.append(stat(k, v)));
    const nodes = [head, kv];
    if (p.dist != null) {
      const r = el('div', 'risk');
      r.append(el('div', null, `${p.coin} would have to ${p.side === 'long' ? 'fall' : 'rise'} ${p.dist.toFixed(1)}% from here before this position is closed and its ${usd(p.coll)} is lost.`));
      nodes.push(r);
    }
    openSheet(`${p.coin} position`, ...nodes);
  }
  function drawPositions(m) {
    const box = $('positions'); box.replaceChildren();
    if (m.error) { box.append(card(el('p', 'empty', m.error))); return; }
    const total = m.positions.reduce((a, p) => a + (p.pnl || 0), 0);
    box.append(heading(`${m.positions.length} open position${m.positions.length === 1 ? '' : 's'}`,
      m.positions.length ? el('span', `num ${tone(total)}`, `${arrow(total)}${signed(total)}`) : null));
    if (!m.positions.length) { box.append(card(el('p', 'empty', 'No open positions right now.'))); return; }
    const cards = el('div', 'cards');
    m.positions.forEach((p) => {
      const b = el('button', 'card'), head = el('span', 'row'), left = el('span', 'row');
      left.append(el('span', 'coin', p.coin), el('span', 'tag', `${p.side === 'short' ? '▼ short' : '▲ long'}${p.lev ? ` · ${p.lev.toFixed(1)}x` : ''}`));
      head.append(left, el('span', `num ${tone(p.pnl)}`, signed(p.pnl)));
      b.append(head, el('span', 'muted', p.lev != null ? `${usd(p.size, 0)} position on ${usd(p.coll)} of your money` : `${p.qty} bought at ${usd(p.entry, digits(p.coin))} · worth ${usd(p.size)}`));
      const room = p.lev != null ? p.dist : p.room, word = p.lev != null ? 'to liquidation' : 'above its stop';
      if (room != null) {
        const near = p.lev != null && room < NEAR, line = el('span', 'row');
        const bar = meter(1 - Math.min(room, 50) / 50, `${room.toFixed(1)} percent ${word}`, near ? 'near' : 'far'); bar.style.flex = '1 1 0';
        line.append(bar, el('span', `num ${near ? 'warn' : 'muted'}`, `${room.toFixed(1)}% ${word}`));
        b.append(line);
      }
      b.addEventListener('click', () => positionSheet(p));
      cards.append(b);
    });
    box.append(cards, el('p', 'note', 'Tap a position for its details. The bar fills as the price gets closer to liquidation, and turns amber inside 15%.'));
  }

  // ---- Trades ----
  function drawTrades(m) {
    const box = $('trades'); box.replaceChildren();
    if (m.error) { box.append(card(el('p', 'empty', m.error))); return; }
    const known = m.trades.filter((t) => t.pnl != null), net = known.reduce((a, t) => a + t.pnl, 0);
    box.append(heading(`${m.trades.length} closed trade${m.trades.length === 1 ? '' : 's'}`,
      known.length ? el('span', `num ${tone(net)}`, `${arrow(net)}${signed(net)}`) : null));
    if (!m.trades.length) { box.append(card(el('p', 'empty', 'No closed trades yet. A trade appears here once a position is closed.'))); return; }
    const sum = el('div', 'stats'); sum.style.borderTop = '0';
    sum.append(stat('Won', String(known.filter((t) => t.pnl > 0).length)), stat('Lost', String(known.filter((t) => t.pnl <= 0).length)),
      stat('Liquidated', String(m.trades.filter((t) => t.liquidated).length), m.trades.some((t) => t.liquidated) ? 'warn' : ''));
    const list = el('div', 'list');
    m.trades.slice(0, 100).forEach((t) => {
      const r = el('div', 'item'), left = el('span'), top = el('span');
      top.append(el('b', null, `${t.coin} `), el('span', 'num muted', `${t.side}${t.lev ? ` · ${t.lev.toFixed(1)}x` : ''}`));
      const held = t.opened && t.closed ? ` after ${span(Date.parse(t.closed) - Date.parse(t.opened))}` : '';
      const d = digits(t.coin), path = t.entry != null && t.exit != null ? ` · ${usd(t.entry, d)} → ${usd(t.exit, d)}` : '';
      left.append(top, el('span', `sub${t.liquidated ? ' warn' : ''}`, `${when(t.closed)} · ${t.liquidated ? 'liquidated' : (t.reason || 'closed')}${held}${path}`));
      r.append(left, el('span', `num ${tone(t.pnl)}`, signed(t.pnl)));
      list.append(r);
    });
    box.append(card(sum), card(list), el('p', 'note', `Dollars won or lost are after fees${m.kind === 'perps' ? ' and borrow; a liquidation loses the whole collateral' : ''}. Past results are not a forecast.`));
  }

  // ---- refresh ----
  function render() {
    const m = model(), ks = D.status?.kill_switch, on = ks?.state === 'engaged', pill = $('ks');
    pill.textContent = D.status ? `kill switch ${on ? 'ON' : 'off'}` : 'status unavailable';
    pill.className = `pill ${D.status ? (on ? 'bad' : 'ok') : 'warn'}`;
    $('sub').textContent = `Read-only · updated ${new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
    drawOverview(m); drawPositions(m); drawTrades(m);
  }
  async function refresh() {
    const [status, watch, paper] = await Promise.allSettled([get('/api/status'), get('/api/watch'), get('/api/perps-paper')]);
    D.paper = paper.status === 'fulfilled' ? paper.value : null;
    D.errors.paper = paper.status === 'rejected' ? `Leverage paper account unavailable: ${paper.reason.message}` : null;
    D.status = status.status === 'fulfilled' ? status.value : null;
    D.errors.status = status.status === 'rejected' ? `Status unavailable: ${status.reason.message}` : null;
    if (watch.status === 'fulfilled') D.watch = watch.value;
    D.errors.watch = watch.status === 'rejected' ? `Prices unavailable: ${watch.reason.message}` : null;
    render();
    window.Markets?.update(D.watch, D.errors.watch);
  }
  $('acct').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    account = b.dataset.v;
    $('acct').querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    render();
  }));
  Desk.start();
  refresh();
  setInterval(refresh, 60000);
})();
