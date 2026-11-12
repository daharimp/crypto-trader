/* Trader Desk widgets (ADR-030). Read-only: every request is a GET to this server's /api. */
(() => {
  'use strict';
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  const usd = (x, d = 2) => (x == null ? '—' : (x < 0 ? '-$' : '$') + Math.abs(Number(x)).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }));
  const digits = (m) => (m === 'BTC' || m === 'ETH' ? 2 : m === 'SOL' ? 2 : 4);
  const signed = (x, d = 2) => (x == null ? '—' : (x >= 0 ? '+' : '') + usd(x, d));
  const pct = (x, d = 1) => (x == null ? '—' : `${x >= 0 ? '+' : ''}${x.toFixed(d)}%`);
  const arrow = (x) => (x > 0 ? '▲ ' : x < 0 ? '▼ ' : '');
  const tone = (x) => (x > 0 ? 'ok' : x < 0 ? 'bad' : 'muted');
  const span = (ms) => {
    const m = Math.max(0, Math.round(ms / 60000));
    return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`;
  };
  const when = (iso) => (iso ? new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—');
  const stat = (k, v, cls) => { const d = el('div'); d.append(el('div', 'k', k), el('div', `v ${cls || ''}`, v)); return d; };
  const table = (head, rows) => {
    const t = el('table'), hr = el('tr');
    head.forEach(([h, n]) => hr.append(el('th', n ? 'n' : '', h)));
    t.append(hr);
    rows.forEach((r) => { const tr = el('tr'); r.forEach((c, i) => { const td = el('td', head[i][1] ? 'n' : ''); td.append(c instanceof Node ? c : String(c)); tr.append(td); }); t.append(tr); });
    const box = el('div', 'scroll'); box.append(t); return box;
  };
  async function get(path) {
    const r = await fetch(path, { cache: 'no-store' });
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || r.status);
    return body;
  }

  const D = { status: null, watch: [], perps: null, errors: {} };
  const W = {};
  const add = (def) => (W[def.id] = Desk.add(def));
  let market = 'BTC', tf = '4h', sessionName = null;
  const session = () => {
    const all = (D.status?.sessions || []).filter((s) => !s.error);
    return all.find((s) => s.name === sessionName) || all.find((s) => s.environment === 'live') || all[0] || null;
  };
  const priceOf = (instrument) => D.watch.find((w) => w.market === String(instrument).split('-')[0])?.price;

  // ---- Account ----
  add({ id: 'account', title: 'Account', size: 6, render(open) {
    const s = session(), body = this.body, more = this.more;
    body.replaceChildren(); more.replaceChildren();
    if (!s) { body.append(el('p', 'empty', D.errors.status || 'No paper or live session has run on this server yet.')); return; }
    const all = D.status.sessions.filter((x) => !x.error);
    if (all.length > 1) {
      const chips = el('div', 'row tabs small');
      all.forEach((x) => {
        const b = el('button', null, x.environment || x.name); b.type = 'button';
        b.setAttribute('aria-pressed', String(x === s));
        b.addEventListener('click', () => { sessionName = x.name; renderAll(); });
        chips.append(b);
      });
      body.append(chips);
    }
    const invested = s.equity_usd - s.cash_usd, share = s.equity_usd > 0 ? Math.max(0, invested / s.equity_usd) : 0;
    const day = s.day_start_usd == null ? null : s.equity_usd - s.day_start_usd;
    body.append(el('div', 'k', `Equity · ${s.environment === 'live' ? 'live' : 'paper (simulated)'}`), el('div', 'hero', usd(s.equity_usd)));
    if (day != null) body.append(el('div', `delta ${tone(day)}`, `${arrow(day)}${signed(day)} today`));
    const meter = el('div', 'meter'); meter.setAttribute('role', 'img');
    meter.setAttribute('aria-label', `${Math.round(share * 100)} percent invested`);
    const fill = el('i'); fill.style.width = `${Math.min(100, share * 100)}%`; meter.append(fill);
    body.append(meter, el('div', 'k', `${Math.round(share * 100)}% invested · ${usd(s.cash_usd)} in cash`));
    if (!open) return;
    const peak = s.high_water_usd, off = peak ? (s.equity_usd / peak - 1) * 100 : null;
    const g = el('div', 'stats');
    g.append(stat('Cash', usd(s.cash_usd)), stat('In positions', usd(invested)), stat('Start of day', usd(s.day_start_usd)),
      stat('Highest equity', usd(peak)), stat('From highest', pct(off), off < 0 ? 'bad' : ''), stat('Fees paid', usd(s.fees_usd)),
      stat('Open positions', String(s.positions.length)), stat('Closed trades', String(s.trades.length)));
    more.append(g, el('p', 'note', 'Equity is cash plus open positions at the price of the last completed 4-hour candle.'));
  } });

  // ---- Bot health ----
  const nextCycle = (now) => { const H = 4 * 3600e3; let t = Math.floor(now / H) * H + 120e3; if (t <= now) t += H; return t; };
  add({ id: 'bot', title: 'Bot health', size: 6, render(open) {
    const s = session(), ks = D.status?.kill_switch, gate = D.status?.live_gate, now = Date.now();
    const body = this.body, more = this.more;
    body.replaceChildren(); more.replaceChildren();
    if (!s) { body.append(el('p', 'empty', 'The bot is not running. On the server: docker compose up -d paper')); return; }
    const last = s.last_cycle_utc ? new Date(s.last_cycle_utc).getTime() : null;
    const late = last != null && now - last > 4 * 3600e3 + 15 * 60e3;
    const [label, cls] = ks?.state === 'engaged' ? ['Stopped: kill switch on', 'bad'] : s.breaker_open ? ['Paused: loss breaker open', 'bad']
      : late ? ['Late: missed a check', 'warn'] : ['On schedule', 'ok'];
    const g = el('div', 'stats');
    g.append(stat('Status', label, cls), stat('Next check', `in ${span(nextCycle(now) - now)}`),
      stat('Last check', last ? `${span(now - last)} ago` : '—'), stat('Missed data cycles', String(s.stale_cycles), s.stale_cycles ? 'warn' : ''));
    body.append(g);
    if (s.environment === 'paper' && gate?.min_paper_cycles) {
      const need = gate.min_paper_cycles, done = Math.min(s.cycles, need), left = need - done;
      const meter = el('div', 'meter'); meter.setAttribute('role', 'img'); meter.setAttribute('aria-label', `${done} of ${need} paper cycles`);
      const fill = el('i'); fill.style.width = `${(done / need) * 100}%`; meter.append(fill);
      body.append(meter, el('div', 'k', left ? `Road to live: ${done} of ${need} paper cycles · about ${Math.ceil(left / 6)} day${Math.ceil(left / 6) === 1 ? '' : 's'} to go` : `Road to live: ${need} paper cycles reached`));
    }
    if (!open) return;
    const rows = [['Last candle processed', when(s.last_bar)], ['Last check ran', when(s.last_cycle_utc)], ['Checks run this session', String(s.cycles)],
      ['Kill switch', ks?.state === 'engaged' ? `ON${ks.reason ? ` (${ks.reason})` : ''}` : 'off'], ['Loss breaker', s.breaker_open ? 'OPEN: trading paused' : 'closed (normal)']];
    if (gate) rows.push(['Live capital cap', gate.max_capital_usd != null ? usd(gate.max_capital_usd, 0) : 'not approved'], ['Your live acknowledgement', gate.acknowledged ? 'recorded' : 'not written yet']);
    more.append(table([['Item'], ['Value', 1]], rows),
      el('p', 'note', 'The bot checks the market about 2 minutes after each 4-hour candle closes (00, 04, 08, 12, 16, 20 UTC). The live gate counts paper cycles itself; this bar is a progress display.'));
  } });

  // ---- Chart ----
  const chartDef = add({ id: 'chart', title: 'Chart', size: 8, render() { drawPrice(); } });
  const tabs = (items, current, small, pick) => {
    const row = el('div', `row tabs${small ? ' small' : ''}`);
    items.forEach((v) => {
      const b = el('button', null, v); b.type = 'button'; b.dataset.v = v; b.setAttribute('aria-pressed', String(v === current));
      b.addEventListener('click', () => pick(v));
      row.append(b);
    });
    return row;
  };
  const press = (row, v) => row.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === v)));
  const marketTabs = tabs(['BTC', 'ETH', 'SOL', 'XRP', 'SUI'], market, false, (v) => setMarket(v));
  const tfTabs = tabs(['1h', '4h', '1d'], tf, true, (v) => { tf = v; press(tfTabs, v); chart.timeScale().resetTimeScale(); refreshChart(); });
  const px = el('div', 'price', '—'), pxNote = el('div', 'k', 'Kraken price'), chartNote = el('p', 'note', 'Candles: Kraken public data.');
  const chartBox = el('div'); chartBox.id = 'chart'; chartBox.setAttribute('role', 'img');
  chartBox.setAttribute('aria-label', 'Candlestick chart with the two moving averages the strategy reads');
  {
    const quote = el('div', 'quote'), left = el('div'); left.append(pxNote, px); quote.append(left, tfTabs);
    const legend = el('div', 'legend');
    [['--fast', 'SMA 20'], ['--slow', 'SMA 50']].forEach(([v, name]) => { const s = el('span'), i = el('i', 'sw'); i.style.background = `var(${v})`; s.append(i, name); legend.append(s); });
    legend.append(el('span', null, '▲▼ paper perps entries · ✕ liquidation'));
    chartDef.body.append(marketTabs, quote, chartBox, legend, chartNote);
  }
  const chart = LightweightCharts.createChart(chartBox, { autoSize: true, handleScale: { axisPressedMouseMove: true }, crosshair: { mode: 0 }, timeScale: { timeVisible: true } });
  const candles = chart.addCandlestickSeries({ borderVisible: false });
  const fast = chart.addLineSeries({ lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
  const slow = chart.addLineSeries({ lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
  function paint() {
    chart.applyOptions({ layout: { background: { color: 'transparent' }, textColor: css('--muted'), fontFamily: css('--font') },
      grid: { vertLines: { color: css('--line') }, horzLines: { color: css('--line') } },
      rightPriceScale: { borderColor: css('--line') }, timeScale: { borderColor: css('--line') } });
    candles.applyOptions({ upColor: css('--up'), downColor: css('--down'), wickUpColor: css('--up'), wickDownColor: css('--down') });
    fast.applyOptions({ color: css('--fast') }); slow.applyOptions({ color: css('--slow') });
  }
  paint();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { paint(); drawPerps(); });
  function drawPrice() {
    const w = D.watch.find((x) => x.market === market);
    px.textContent = w ? usd(w.price, digits(market)) : '—';
    pxNote.textContent = w?.change_24h_pct != null ? `Kraken price · ${arrow(w.change_24h_pct)}${pct(w.change_24h_pct)} in 24h` : 'Kraken price';
  }
  function setMarket(v) { market = v; press(marketTabs, v); chart.timeScale().resetTimeScale(); drawPrice(); refreshChart(); }

  // ---- Markets ----
  function spark(values) {
    const lo = Math.min(...values), hi = Math.max(...values), n = values.length - 1 || 1;
    const pts = values.map((v, i) => `${((i / n) * 100).toFixed(1)},${(24 - ((v - lo) / (hi - lo || 1)) * 22).toFixed(1)}`).join(' ');
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 100 26'); svg.setAttribute('preserveAspectRatio', 'none'); svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = `<polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke"/>`;
    return svg;
  }
  const trendText = (t) => (t === 'up' ? 'Uptrend' : t === 'down' ? 'Downtrend' : 'Warming up');
  add({ id: 'markets', title: 'Markets', size: 4, render(open) {
    const body = this.body, more = this.more;
    body.replaceChildren(); more.replaceChildren();
    if (!D.watch.length) { body.append(el('p', 'empty', D.errors.watch || 'Loading prices…')); return; }
    const list = el('div', 'list');
    D.watch.forEach((w) => {
      const b = el('button', 'item mk'); b.type = 'button'; b.title = `Show ${w.market} on the chart`;
      const line = el('span', 'muted'); line.append(spark(w.spark));
      const right = el('span', 'num'); right.append(el('div', tone(w.change_24h_pct), `${arrow(w.change_24h_pct)}${pct(w.change_24h_pct)}`), el('span', 'tag', trendText(w.trend)));
      b.append(el('span', 'sym', w.market), el('span', 'num', usd(w.price, digits(w.market))), line, right);
      b.addEventListener('click', () => { setMarket(w.market); Desk.focus('chart'); });
      list.append(b);
    });
    body.append(list);
    if (!open) return;
    more.append(table([['Coin'], ['Price', 1], ['24 hours', 1], ['7 days', 1], ['Trend (4h)'], ['Bot stance']], D.watch.map((w) => {
      const week = w.spark.length > 1 ? (w.price / w.spark[0] - 1) * 100 : null;
      return [w.market, usd(w.price, digits(w.market)), pct(w.change_24h_pct), pct(week), trendText(w.trend), w.trend === 'up' ? 'May hold or buy' : 'Stays out'];
    })), el('p', 'note', 'Trend is what the sma_trend strategy reads: up while the 20-candle average is above the 50-candle average on 4-hour candles. Sparklines show 7 days.'));
  } });

  // ---- Positions ----
  add({ id: 'positions', title: 'Positions', size: 4, render(open) {
    const s = session(), body = this.body, more = this.more;
    body.replaceChildren(); more.replaceChildren();
    if (!s) { body.append(el('p', 'empty', 'No session yet.')); return; }
    if (!s.positions.length) {
      const flat = D.watch.length && D.watch.every((w) => w.trend === 'down');
      body.append(el('p', 'empty', flat ? 'In cash. All five markets read downtrend, and this strategy buys only in uptrends.' : 'In cash. No open positions.'));
      return;
    }
    const rows = s.positions.map((p) => {
      const price = priceOf(p.instrument), value = price == null ? null : price * p.quantity;
      return { ...p, price, value, pnl: price == null ? null : (price - p.entry) * p.quantity, room: price && p.stop ? (p.stop / price - 1) * 100 : null };
    });
    const list = el('div', 'list');
    rows.forEach((p) => {
      const r = el('div', 'item');
      r.append(el('span', null, `${p.instrument} · ${p.quantity}`), el('span', `num ${tone(p.pnl)}`, `${arrow(p.pnl)}${signed(p.pnl)}`),
        el('span', 'sub', `Bought at ${usd(p.entry)} · worth ${usd(p.value)}${p.stop ? ` · stop ${usd(p.stop)}` : ''}`));
      list.append(r);
    });
    body.append(list);
    if (!open) return;
    more.append(table([['Coin'], ['Amount', 1], ['Bought at', 1], ['Price now', 1], ['Worth', 1], ['Gain or loss', 1], ['Stop', 1], ['To stop', 1]],
      rows.map((p) => [p.instrument, p.quantity, usd(p.entry), usd(p.price), usd(p.value), signed(p.pnl), usd(p.stop), pct(p.room)])),
    el('p', 'note', 'Gain or loss uses the latest Kraken price and is before selling fees.'));
  } });

  // ---- Trades ----
  add({ id: 'trades', title: 'Closed trades', size: 4, render(open) {
    const s = session(), body = this.body, more = this.more;
    body.replaceChildren(); more.replaceChildren();
    const trades = s ? [...s.trades].reverse() : [];
    if (!trades.length) { body.append(el('p', 'empty', 'No closed trades yet. A trade appears here once a position is sold.')); return; }
    const total = trades.reduce((a, t) => a + t.pnl_usd, 0), wins = trades.filter((t) => t.pnl_usd > 0).length;
    const g = el('div', 'stats');
    g.append(stat('Total', `${arrow(total)}${signed(total)}`, tone(total)), stat('Won', `${wins} of ${trades.length}`));
    const list = el('div', 'list');
    trades.slice(0, 4).forEach((t) => {
      const r = el('div', 'item');
      r.append(el('span', null, t.instrument), el('span', `num ${tone(t.pnl_usd)}`, `${arrow(t.pnl_usd)}${signed(t.pnl_usd)}`), el('span', 'sub', `Closed ${when(t.closed_at)}`));
      list.append(r);
    });
    body.append(g, list);
    if (!open) return;
    more.append(table([['Coin'], ['Bought'], ['Sold'], ['Bought at', 1], ['Sold at', 1], ['Gain or loss', 1]],
      trades.map((t) => [t.instrument, when(t.opened_at), when(t.closed_at), usd(t.entry), usd(t.exit), signed(t.pnl_usd)])),
    el('p', 'note', 'Showing the most recent 50 closed trades, after fees.'));
  } });

  // ---- Paper perps replay ----
  let liqLines = [];
  const perps = add({ id: 'perps', title: 'Leverage practice · history replay', size: 4, render(open) { drawPerps(open); } });
  function drawPerps(open = Desk.isOpen('perps')) {
    const p = D.perps, body = perps.body, more = perps.more;
    body.replaceChildren(); more.replaceChildren();
    liqLines.forEach((l) => candles.removePriceLine(l)); liqLines = [];
    if (!p) { candles.setMarkers([]); body.append(el('p', 'empty', D.errors.perps || 'Loading…')); return; }
    if (p.blocked) {
      candles.setMarkers([]);
      const off = p.blocked.some((k) => k.startsWith('market '));
      body.append(el(off ? 'p' : 'div', off ? 'empty' : 'banner', off ? `${market} is not in the perps practice config (SOL, BTC and ETH are).` : `Waiting on your approval of: ${p.blocked.join(', ')}.`));
      return;
    }
    const pnl = p.end_equity_usd - p.start_equity_usd, rejected = Object.values(p.rejections).reduce((a, b) => a + b, 0);
    const g = el('div', 'stats');
    g.append(stat(`${market} · ${tf} replay`, usd(p.end_equity_usd)), stat('Gain or loss', `${arrow(pnl)}${signed(pnl)}`, tone(pnl)),
      stat('Largest drop', `${p.max_drawdown_pct.toFixed(1)}%`), stat('Trades · liquidations', `${p.trades} · ${p.liquidations}`, p.liquidations ? 'bad' : ''));
    body.append(g);
    if (open) {
      const g2 = el('div', 'stats');
      g2.append(stat('Starting collateral', usd(p.start_equity_usd)), stat('Fees paid', usd(p.fees_paid_usd)), stat('Orders the risk rules refused', String(rejected)));
      more.append(g2, el('p', 'note', `${p.disclaimer} This replays the old moving-average signal with leverage over the candles on the chart; it is not live trading.`));
    }
    const marks = p.markers.map((m) => (m.event === 'LIQUIDATED'
      ? { time: m.time, position: 'aboveBar', color: css('--down'), shape: 'square', text: '✕' }
      : m.event === 'OPENED'
        ? { time: m.time, position: m.side === 'long' ? 'belowBar' : 'aboveBar', color: css(m.side === 'long' ? '--up' : '--down'), shape: m.side === 'long' ? 'arrowUp' : 'arrowDown', text: m.side === 'long' ? 'L' : 'S' }
        : { time: m.time, position: 'inBar', color: css('--muted'), shape: 'circle', text: '' }));
    candles.setMarkers(marks.sort((a, b) => a.time - b.time));
    const last = p.markers[p.markers.length - 1];
    if (last?.event === 'OPENED' && last.liquidation_price) {
      liqLines.push(candles.createPriceLine({ price: last.liquidation_price, color: css('--down'), lineStyle: 2, lineWidth: 1, title: 'liq' }));
    }
  }

  // ---- data refresh ----
  function renderAll() {
    const ks = D.status?.kill_switch, pill = document.getElementById('ks'), on = ks?.state === 'engaged';
    pill.textContent = D.status ? `kill switch ${on ? 'ON' : 'off'}` : 'status unavailable';
    pill.className = `pill ${D.status ? (on ? 'bad' : 'ok') : 'warn'}`;
    ['account', 'bot', 'markets', 'positions', 'trades'].forEach((id) => renderOne(id));
    drawPrice();
  }
  function renderOne(id) { W[id].render(Desk.isOpen(id)); }
  async function refreshChart() {
    const q = `market=${market}&timeframe=${tf}`;
    try {
      const c = await get(`/api/candles?${q}`);
      candles.setData(c.candles); fast.setData(c.sma_fast); slow.setData(c.sma_slow);
      chartNote.textContent = `Candles: Kraken public data. Updated ${new Date().toLocaleTimeString()}.`;
    } catch (e) { chartNote.textContent = `Candles unavailable: ${e.message}`; }
    try { D.perps = await get(`/api/perps?${q}`); D.errors.perps = null; } catch (e) { D.perps = null; D.errors.perps = `Replay unavailable: ${e.message}`; }
    drawPerps();
  }
  async function refresh() {
    const [status, watch] = await Promise.allSettled([get('/api/status'), get('/api/watch')]);
    D.status = status.status === 'fulfilled' ? status.value : null;
    D.errors.status = status.status === 'rejected' ? `Status unavailable: ${status.reason.message}` : null;
    if (watch.status === 'fulfilled') D.watch = watch.value;
    D.errors.watch = watch.status === 'rejected' ? `Prices unavailable: ${watch.reason.message}` : null;
    renderAll();
    refreshChart();
  }
  Desk.start();
  refresh();
  setInterval(refresh, 60000);
  setInterval(() => renderOne('bot'), 30000); // Reason: keeps the "next check" countdown moving.
})();
