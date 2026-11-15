/* Trader Desk markets (ADR-037): the five coins, a candle chart with the two moving
   averages, and the leverage-practice history replay. Read-only: GET requests to /api. */
(() => {
  'use strict';
  const { $, css, el, svg, usd, signed, pct, arrow, tone, digits, stat, get } = Desk;
  let market = 'BTC', tf = '4h', watch = [], replay = null, replayError = null, liqLines = [];
  const trendText = (t) => (t === 'up' ? 'Uptrend' : t === 'down' ? 'Downtrend' : 'Warming up');

  // ---- layout: coins on one side, the chart on the other ----
  const list = el('div', 'list'), listCard = el('section', 'card');
  listCard.append(el('h2', 'label', 'Coins'), list);
  const px = el('div', 'hero', '—'), pxNote = el('div', 'muted', 'Kraken price'), chartNote = el('p', 'note', 'Candles: Kraken public data.');
  const chartBox = el('div'); chartBox.id = 'chart'; chartBox.setAttribute('role', 'img');
  chartBox.setAttribute('aria-label', 'Candlestick chart with the two moving averages');
  const tfTabs = el('div', 'chips'); tfTabs.setAttribute('role', 'group'); tfTabs.setAttribute('aria-label', 'Candle size');
  ['1h', '4h', '1d'].forEach((v) => {
    const b = el('button', null, v); b.dataset.v = v; b.setAttribute('aria-pressed', String(v === tf));
    b.addEventListener('click', () => {
      tf = v; tfTabs.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      chart.timeScale().resetTimeScale(); refreshChart();
    });
    tfTabs.append(b);
  });
  const legend = el('div', 'legend');
  [['--accent', 'SMA 20'], ['--warn', 'SMA 50']].forEach(([v, name]) => { const s = el('span'), i = el('i'); i.style.background = `var(${v})`; s.append(i, name); legend.append(s); });
  legend.append(el('span', null, '▲▼ practice entries · ✕ liquidation'));
  const quote = el('div', 'row'), left = el('div'); left.append(pxNote, px); quote.append(left, tfTabs);
  const replayBox = el('div'), chartCard = el('section', 'card');
  chartCard.append(quote, chartBox, legend, chartNote);
  const replayCard = el('section', 'card'); replayCard.append(el('h2', 'label', 'Leverage practice · history replay'), replayBox);
  const right = el('div', 'stack'); right.append(chartCard, replayCard);
  const grid = el('div', 'grid2 even'); grid.append(listCard, right);
  $('markets').append(grid);

  // ---- chart ----
  const chart = LightweightCharts.createChart(chartBox, { autoSize: true, handleScale: { axisPressedMouseMove: true }, crosshair: { mode: 0 }, timeScale: { timeVisible: true } });
  const candles = chart.addCandlestickSeries({ borderVisible: false });
  const fast = chart.addLineSeries({ lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
  const slow = chart.addLineSeries({ lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
  function paint() {
    chart.applyOptions({ layout: { background: { color: 'transparent' }, textColor: css('--muted'), fontFamily: css('--body') },
      grid: { vertLines: { color: css('--line') }, horzLines: { color: css('--line') } },
      rightPriceScale: { borderColor: css('--line') }, timeScale: { borderColor: css('--line') } });
    candles.applyOptions({ upColor: css('--accent'), downColor: css('--bad'), wickUpColor: css('--accent'), wickDownColor: css('--bad') });
    fast.applyOptions({ color: css('--accent') }); slow.applyOptions({ color: css('--warn') });
  }
  paint();
  Look.onChange(() => { paint(); drawReplay(); });

  function spark(values) {
    const lo = Math.min(...values), hi = Math.max(...values), n = values.length - 1 || 1;
    const pts = values.map((v, i) => `${((i / n) * 100).toFixed(1)},${(24 - ((v - lo) / (hi - lo || 1)) * 22).toFixed(1)}`).join(' ');
    const s = svg('svg', { viewBox: '0 0 100 26', preserveAspectRatio: 'none', 'aria-hidden': 'true' });
    s.append(svg('polyline', { points: pts, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5, 'vector-effect': 'non-scaling-stroke' }));
    return s;
  }
  function drawList(error) {
    list.replaceChildren();
    if (!watch.length) { list.append(el('p', 'empty', error || 'Loading prices…')); return; }
    watch.forEach((w) => {
      const b = el('button', 'mk'); b.setAttribute('aria-pressed', String(w.market === market)); b.title = `Show ${w.market} on the chart`;
      const r = el('span', 'right');
      r.append(el('div', tone(w.change_24h_pct), `${arrow(w.change_24h_pct)}${pct(w.change_24h_pct)}`), el('div', 'muted', trendText(w.trend)));
      b.append(el('span', 'coin', w.market), el('span', 'num', usd(w.price, digits(w.market))), spark(w.spark), r);
      b.addEventListener('click', () => { market = w.market; chart.timeScale().resetTimeScale(); drawList(); drawPrice(); refreshChart(); });
      list.append(b);
    });
  }
  function drawPrice() {
    const w = watch.find((x) => x.market === market);
    px.textContent = w ? usd(w.price, digits(market)) : '—';
    pxNote.textContent = w?.change_24h_pct != null ? `${market} · Kraken price · ${arrow(w.change_24h_pct)}${pct(w.change_24h_pct)} in 24h` : `${market} · Kraken price`;
  }

  // ---- leverage practice replay over the candles on the chart ----
  function drawReplay() {
    const p = replay;
    replayBox.replaceChildren();
    liqLines.forEach((l) => candles.removePriceLine(l)); liqLines = [];
    if (!p) { candles.setMarkers([]); replayBox.append(el('p', 'empty', replayError || 'Loading…')); return; }
    if (p.blocked) {
      candles.setMarkers([]);
      const off = p.blocked.some((k) => k.startsWith('market '));
      replayBox.append(el('p', 'empty', off ? `${market} is not in the leverage practice config.` : `Waiting on your approval of: ${p.blocked.join(', ')}.`));
      return;
    }
    const pnl = p.end_equity_usd - p.start_equity_usd, rejected = Object.values(p.rejections).reduce((a, b) => a + b, 0);
    const g = el('div', 'stats'); g.style.borderTop = '0';
    g.append(stat(`${market} · ${tf} replay`, usd(p.end_equity_usd)), stat('Gain or loss', `${arrow(pnl)}${signed(pnl)}`, tone(pnl)),
      stat('Largest drop', `${p.max_drawdown_pct.toFixed(1)}%`), stat('Trades · liquidations', `${p.trades} · ${p.liquidations}`, p.liquidations ? 'warn' : ''),
      stat('Starting collateral', usd(p.start_equity_usd)), stat('Fees paid', usd(p.fees_paid_usd)), stat('Orders the risk rules refused', String(rejected)));
    replayBox.append(g, el('p', 'note', `${p.disclaimer} This replays the old moving-average signal with leverage over the candles on the chart; it is not live trading.`));
    const marks = p.markers.map((m) => (m.event === 'LIQUIDATED'
      ? { time: m.time, position: 'aboveBar', color: css('--warn'), shape: 'square', text: '✕' }
      : m.event === 'OPENED'
        ? { time: m.time, position: m.side === 'long' ? 'belowBar' : 'aboveBar', color: css(m.side === 'long' ? '--accent' : '--bad'), shape: m.side === 'long' ? 'arrowUp' : 'arrowDown', text: m.side === 'long' ? 'L' : 'S' }
        : { time: m.time, position: 'inBar', color: css('--muted'), shape: 'circle', text: '' }));
    candles.setMarkers(marks.sort((a, b) => a.time - b.time));
    const last = p.markers[p.markers.length - 1];
    if (last?.event === 'OPENED' && last.liquidation_price) {
      liqLines.push(candles.createPriceLine({ price: last.liquidation_price, color: css('--warn'), lineStyle: 2, lineWidth: 1, title: 'liq' }));
    }
  }
  async function refreshChart() {
    const q = `market=${market}&timeframe=${tf}`;
    try {
      const c = await get(`/api/candles?${q}`);
      candles.setData(c.candles); fast.setData(c.sma_fast); slow.setData(c.sma_slow);
      chartNote.textContent = `Candles: Kraken public data. Updated ${new Date().toLocaleTimeString()}.`;
    } catch (e) { chartNote.textContent = `Candles unavailable: ${e.message}`; }
    try { replay = await get(`/api/perps?${q}`); replayError = null; } catch (e) { replay = null; replayError = `Replay unavailable: ${e.message}`; }
    drawReplay();
  }

  window.Markets = {
    update(rows, error) { watch = rows; drawList(error); drawPrice(); refreshChart(); },
  };
})();
