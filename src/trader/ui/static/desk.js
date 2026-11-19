/* Trader Desk shell (ADR-037): sections you slide between, the sheet that slides in with
   details, the appearance choice, and the helpers every view uses. Read-only: the only
   request this page makes is a GET to this server's /api. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    if (tag === 'button') e.type = 'button';
    return e;
  };
  const svg = (tag, attrs) => {
    const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attrs || {}).forEach(([k, v]) => e.setAttribute(k, v));
    return e;
  };
  const fmt = (x, d) => Math.abs(Number(x)).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  const usd = (x, d = 2) => (x == null || Number.isNaN(Number(x)) ? '—' : (x < 0 ? '−$' : '$') + fmt(x, d));
  const signed = (x, d = 2) => (x == null || Number.isNaN(Number(x)) ? '—' : (x >= 0 ? '+$' : '−$') + fmt(x, d));
  const pct = (x, d = 1) => (x == null || Number.isNaN(x) ? '—' : `${x >= 0 ? '+' : '−'}${Math.abs(x).toFixed(d)}%`);
  const arrow = (x) => (x > 0 ? '▲ ' : x < 0 ? '▼ ' : '');
  const tone = (x) => (x > 0 ? 'ok' : x < 0 ? 'bad' : 'muted');
  const digits = (m) => (['BTC', 'ETH', 'SOL'].includes(m) ? 2 : 4);
  const span = (ms) => {
    const m = Math.max(0, Math.round(ms / 60000));
    if (m >= 2880) return `${Math.floor(m / 1440)}d ${Math.floor((m % 1440) / 60)}h`;
    return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`;
  };
  const when = (iso) => (iso ? new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—');
  const stat = (k, v, cls) => { const d = el('div'); d.append(el('div', 'k', k), el('div', `v ${cls || ''}`, v)); return d; };
  const meter = (share, label, cls) => {
    const m = el('div', `meter ${cls || ''}`), fill = el('i');
    m.setAttribute('role', 'img'); m.setAttribute('aria-label', label);
    fill.style.width = `${Math.max(0, Math.min(100, share * 100))}%`;
    m.append(fill);
    return m;
  };
  async function get(path) {
    const r = await fetch(path, { cache: 'no-store' });
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || r.status);
    return body;
  }
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- sections: swipe, arrow keys, or tap a name ----
  const pager = $('pager'), ink = $('ink');
  const tabs = [...$('tabs').querySelectorAll('button')], dots = [...$('dots').children];
  const names = tabs.map((b) => b.dataset.page), pageListeners = [];
  let page = -1, target = null, settle = 0;
  function mark(i) {
    if (i === page) return;
    page = i;
    tabs.forEach((b, k) => { if (k === i) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current'); });
    dots.forEach((d, k) => d.classList.toggle('on', k === i));
    ink.style.transform = `translateX(${i * 100}%)`;
    try { history.replaceState(null, '', `#${names[i]}`); } catch { /* sandboxed page: no address bar to update */ }
    pageListeners.forEach((f) => f(names[i]));
  }
  function go(i, smooth = true) {
    const n = Math.max(0, Math.min(names.length - 1, i));
    // Reason: while a tap slides across several sections, scroll events from the ones in
    // between must not move the marker back.
    target = n; clearTimeout(settle); settle = setTimeout(() => { target = null; }, 900);
    pager.scrollTo({ left: n * pager.clientWidth, behavior: smooth && !reduced() ? 'smooth' : 'auto' });
    mark(n);
  }
  pager.addEventListener('scroll', () => {
    const i = Math.round(pager.scrollLeft / pager.clientWidth);
    if (target != null) { if (i === target) target = null; return; }
    mark(i);
  }, { passive: true });
  tabs.forEach((b, i) => b.addEventListener('click', () => go(i)));
  addEventListener('resize', () => pager.scrollTo({ left: page * pager.clientWidth, behavior: 'auto' }));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeSheet(); return; }
    if (document.body.classList.contains('sheet-open') || e.altKey || e.metaKey || e.ctrlKey) return;
    if (e.target.closest?.('input, select, textarea, #chart')) return;
    if (e.key === 'ArrowRight') { go(page + 1); e.preventDefault(); }
    if (e.key === 'ArrowLeft') { go(page - 1); e.preventDefault(); }
  });

  // ---- the sheet ----
  const sheet = $('sheet'), sheetBody = $('sheetBody'), background = [document.querySelector('.top'), $('tabs'), pager];
  let lastFocus = null;
  function openSheet(label, ...nodes) {
    sheetBody.replaceChildren(...nodes);
    sheet.setAttribute('aria-label', label);
    lastFocus = document.activeElement;
    document.body.classList.add('sheet-open');
    sheet.inert = false; background.forEach((n) => { n.inert = true; });
    $('sheetClose').focus();
  }
  function closeSheet() {
    if (!document.body.classList.contains('sheet-open')) return;
    document.body.classList.remove('sheet-open');
    sheet.inert = true; background.forEach((n) => { n.inert = false; });
    lastFocus?.focus?.();
  }
  $('sheetClose').addEventListener('click', closeSheet);
  $('scrim').addEventListener('click', closeSheet);

  // ---- appearance ----
  const LOOKS = [['auto', 'Auto', 'Follows your phone or Mac'], ['light', 'Light', 'Always light'],
    ['dark', 'Dark', 'Always dark'], ['clock', 'Day and night', 'Light 7am to 7pm, dark after']];
  $('lookBtn').addEventListener('click', () => {
    const box = el('div', 'options'); box.setAttribute('role', 'group'); box.setAttribute('aria-label', 'Appearance');
    const paint = () => box.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === Look.mode)));
    LOOKS.forEach(([v, name, note]) => {
      const b = el('button'); b.dataset.v = v; b.append(el('b', null, name), el('span', null, note));
      b.addEventListener('click', () => { Look.set(v); paint(); });
      box.append(b);
    });
    paint();
    openSheet('Appearance', el('h2', null, 'Appearance'), box,
      el('p', 'note', 'Saved in this browser only. Auto uses your device setting, which can itself switch at sunset.'));
  });

  window.Desk = {
    $, css, el, svg, usd, signed, pct, arrow, tone, digits, span, when, stat, meter, get,
    go, openSheet, closeSheet,
    onPage(f) { pageListeners.push(f); },
    start() { const i = names.indexOf(location.hash.slice(1)); go(i < 0 ? 0 : i, false); },
  };
})();
