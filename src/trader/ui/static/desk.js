/* Trader Desk workspace (ADR-030): widgets you can drag to reorder, resize, hide, and open.
   The layout is saved in this browser only (localStorage); nothing is sent to the server. */
(() => {
  'use strict';
  const KEY = 'trader-desk.layout.v1';
  const SIZES = [4, 6, 8, 12];
  const ICONS = {
    grip: '<svg viewBox="0 0 16 16"><circle cx="5" cy="3" r="1.4"/><circle cx="11" cy="3" r="1.4"/><circle cx="5" cy="8" r="1.4"/><circle cx="11" cy="8" r="1.4"/><circle cx="5" cy="13" r="1.4"/><circle cx="11" cy="13" r="1.4"/></svg>',
    open: '<svg viewBox="0 0 16 16"><path d="M9.5 2.5h4v4M13.5 2.5 9 7M6.5 13.5h-4v-4M2.5 13.5 7 9"/></svg>',
    close: '<svg viewBox="0 0 16 16"><path d="m3.5 3.5 9 9M12.5 3.5l-9 9"/></svg>',
  };
  const $ = (id) => document.getElementById(id);
  const desk = $('desk'), scrim = $('scrim'), live = $('live');
  const defs = new Map();
  let opened = null, placeholder = null, lastFocus = null, justDragged = false;

  // ---- saved layout ----
  function load() {
    try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; }
  }
  function save() {
    const cards = [...desk.querySelectorAll('.w')];
    const state = {
      order: cards.map((c) => c.dataset.id),
      hidden: cards.filter((c) => c.hidden).map((c) => c.dataset.id),
      size: Object.fromEntries(cards.map((c) => [c.dataset.id, Number(c.dataset.size)])),
    };
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* private mode: layout just isn't kept */ }
  }
  const say = (text) => { live.textContent = text; };
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- building cards ----
  function button(cls, label, icon) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = cls; b.setAttribute('aria-label', label); b.innerHTML = icon;
    return b;
  }
  function build(def) {
    const card = document.createElement('section');
    card.className = 'w'; card.dataset.id = def.id; card.dataset.size = def.size;
    card.setAttribute('aria-label', def.title);
    const head = document.createElement('div'); head.className = 'w-head';
    const grip = button('icon grip', `Move ${def.title}. Drag, or use the arrow keys.`, ICONS.grip);
    const title = document.createElement('button');
    title.type = 'button'; title.className = 'w-title'; title.textContent = def.title;
    const toggle = button('icon w-open', `Open ${def.title}`, ICONS.open);
    head.append(grip, title, toggle);
    const body = document.createElement('div'); body.className = 'w-body';
    const more = document.createElement('div'); more.className = 'w-more';
    const resize = button('resize', `Resize ${def.title}. Drag, or use the left and right arrow keys.`, '');
    card.append(head, body, more, resize);
    def.card = card; def.body = body; def.more = more;

    const toggleOpen = () => { if (!justDragged) (opened === card ? close() : open(card)); };
    title.addEventListener('click', toggleOpen);
    toggle.addEventListener('click', toggleOpen);
    grip.addEventListener('pointerdown', (e) => beginDrag(card, e, true));
    // Reason: with a mouse the whole header drags; on touch only the grip does, so a finger
    // on the header still scrolls the page.
    head.addEventListener('pointerdown', (e) => {
      if (e.pointerType === 'mouse' && e.button === 0 && !e.target.closest('.icon')) beginDrag(card, e, false);
    });
    grip.addEventListener('keydown', (e) => keyMove(card, e));
    resize.addEventListener('pointerdown', (e) => beginResize(card, e));
    resize.addEventListener('keydown', (e) => keyResize(card, e));
    return card;
  }

  // ---- reorder by dragging ----
  function flip(change) {
    const cards = [...desk.querySelectorAll('.w:not(.dragging)')];
    const before = new Map(cards.map((c) => [c, c.getBoundingClientRect()]));
    change();
    if (reduced()) return;
    cards.forEach((c) => {
      const a = before.get(c), b = c.getBoundingClientRect();
      const dx = a.left - b.left, dy = a.top - b.top;
      if (!dx && !dy) return;
      c.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], { duration: 180, easing: 'ease' });
    });
  }
  function beginDrag(card, e, immediate) {
    if (opened || e.button > 0) return;
    const rect = card.getBoundingClientRect();
    const grab = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    const start = { x: e.clientX, y: e.clientY };
    let active = false, cooldown = 0;

    const place = (ev) => {
      card.style.transform = 'none';
      const base = card.getBoundingClientRect();
      card.style.transform = `translate(${ev.clientX - grab.x - base.left}px, ${ev.clientY - grab.y - base.top}px)`;
    };
    const move = (ev) => {
      if (!active) {
        if (!immediate && Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 6) return;
        active = true;
        card.classList.add('dragging'); document.body.classList.add('dragging-any');
      }
      place(ev);
      const under = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('.w');
      if (under && under !== card && performance.now() > cooldown) {
        const u = under.getBoundingClientRect();
        const stacked = u.width > desk.clientWidth * 0.7;
        const before = stacked ? ev.clientY < u.top + u.height / 2 : ev.clientX < u.left + u.width / 2;
        const ref = before ? under : under.nextElementSibling;
        if (ref !== card && card.nextElementSibling !== ref) {
          flip(() => desk.insertBefore(card, ref));
          cooldown = performance.now() + 160;
          place(ev);
        }
      }
      // Reason: keep the drag going when the target is off screen.
      if (ev.clientY < 70) scrollBy(0, -14); else if (ev.clientY > innerHeight - 70) scrollBy(0, 14);
    };
    const end = () => {
      removeEventListener('pointermove', move); removeEventListener('pointerup', end); removeEventListener('pointercancel', end);
      if (!active) return;
      card.classList.remove('dragging'); document.body.classList.remove('dragging-any');
      card.classList.add('settle'); card.style.transform = '';
      setTimeout(() => card.classList.remove('settle'), 200);
      justDragged = true; setTimeout(() => { justDragged = false; }, 0);
      save(); announcePosition(card);
    };
    addEventListener('pointermove', move); addEventListener('pointerup', end); addEventListener('pointercancel', end);
    if (immediate) e.preventDefault();
  }
  function announcePosition(card) {
    const shown = [...desk.querySelectorAll('.w:not([hidden])')];
    say(`${defs.get(card.dataset.id).title} moved to position ${shown.indexOf(card) + 1} of ${shown.length}.`);
  }
  function keyMove(card, e) {
    const back = e.key === 'ArrowUp' || e.key === 'ArrowLeft', fwd = e.key === 'ArrowDown' || e.key === 'ArrowRight';
    if (!back && !fwd) return;
    e.preventDefault();
    const shown = [...desk.querySelectorAll('.w:not([hidden])')];
    const other = shown[shown.indexOf(card) + (back ? -1 : 1)];
    if (!other) return;
    flip(() => desk.insertBefore(card, back ? other : other.nextElementSibling));
    card.querySelector('.grip').focus();
    save(); announcePosition(card);
  }

  // ---- resize by dragging the right edge (desktop) ----
  function setSize(card, size) {
    if (Number(card.dataset.size) === size) return;
    flip(() => { card.dataset.size = size; });
    save(); say(`${defs.get(card.dataset.id).title} width ${size} of 12 columns.`);
  }
  function beginResize(card, e) {
    e.preventDefault();
    const move = (ev) => {
      const want = ((ev.clientX - card.getBoundingClientRect().left) / desk.clientWidth) * 12;
      setSize(card, SIZES.reduce((a, b) => (Math.abs(b - want) < Math.abs(a - want) ? b : a)));
    };
    const end = () => { removeEventListener('pointermove', move); removeEventListener('pointerup', end); document.body.classList.remove('dragging-any'); };
    document.body.classList.add('dragging-any');
    addEventListener('pointermove', move); addEventListener('pointerup', end);
  }
  function keyResize(card, e) {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const i = SIZES.indexOf(Number(card.dataset.size)) + step;
    if (SIZES[i]) setSize(card, SIZES[i]);
  }

  // ---- open a widget into a sheet, and close it ----
  function transition(card, change) {
    if (!document.startViewTransition || reduced()) { change(); return; }
    card.style.viewTransitionName = 'opening';
    document.startViewTransition(change).finished.finally(() => { card.style.viewTransitionName = ''; });
  }
  function setOpen(card, on) {
    const def = defs.get(card.dataset.id);
    const toggle = card.querySelector('.w-open');
    card.classList.toggle('open', on);
    scrim.hidden = !on; document.body.classList.toggle('locked', on);
    toggle.innerHTML = on ? ICONS.close : ICONS.open;
    toggle.setAttribute('aria-label', `${on ? 'Close' : 'Open'} ${def.title}`);
    if (on) { card.setAttribute('role', 'dialog'); card.setAttribute('aria-modal', 'true'); } else { card.removeAttribute('role'); card.removeAttribute('aria-modal'); }
    // Reason: everything behind the sheet is inert, so focus and clicks stay inside it.
    [...desk.children, document.querySelector('header')].forEach((n) => { if (n !== card) n.inert = on; });
    def.render?.(on);
  }
  function open(card) {
    if (opened) return;
    lastFocus = document.activeElement;
    transition(card, () => {
      placeholder = document.createElement('div');
      placeholder.className = 'ph'; placeholder.dataset.size = card.dataset.size;
      placeholder.style.height = `${card.offsetHeight}px`;
      card.after(placeholder);
      opened = card; setOpen(card, true);
    });
    card.querySelector('.w-open').focus();
  }
  function close() {
    if (!opened) return;
    const card = opened;
    transition(card, () => { setOpen(card, false); placeholder?.remove(); placeholder = null; opened = null; });
    lastFocus?.focus?.();
  }
  scrim.addEventListener('click', close);
  addEventListener('keydown', (e) => { if (e.key === 'Escape') { if (opened) close(); else closeMenu(); } });

  // ---- layout menu: show or hide widgets, reset ----
  const menu = $('layoutMenu'), menuBtn = $('layoutBtn');
  function closeMenu() { menu.hidden = true; menuBtn.setAttribute('aria-expanded', 'false'); }
  function drawMenu() {
    menu.replaceChildren();
    defs.forEach((def) => {
      const label = document.createElement('label'), box = document.createElement('input');
      box.type = 'checkbox'; box.checked = !def.card.hidden;
      box.addEventListener('change', () => { flip(() => { def.card.hidden = !box.checked; }); save(); if (box.checked) def.render?.(false); });
      label.append(box, def.title); menu.append(label);
    });
    const reset = document.createElement('button');
    reset.type = 'button'; reset.className = 'btn'; reset.textContent = 'Reset layout';
    reset.addEventListener('click', () => { try { localStorage.removeItem(KEY); } catch { /* nothing saved */ } arrange({}); drawMenu(); say('Layout reset.'); });
    menu.append(reset);
  }
  menuBtn.addEventListener('click', () => {
    const show = menu.hidden;
    if (show) drawMenu();
    menu.hidden = !show; menuBtn.setAttribute('aria-expanded', String(show));
  });
  document.addEventListener('pointerdown', (e) => { if (!menu.hidden && !e.target.closest('.hdr')) closeMenu(); });

  // ---- public API used by widgets.js ----
  function arrange(state) {
    const order = (state.order || []).filter((id) => defs.has(id));
    const ids = [...order, ...[...defs.keys()].filter((id) => !order.includes(id))];
    flip(() => ids.forEach((id) => {
      const def = defs.get(id);
      def.card.dataset.size = SIZES.includes(state.size?.[id]) ? state.size[id] : def.size;
      def.card.hidden = (state.hidden || []).includes(id);
      desk.append(def.card);
    }));
  }
  window.Desk = {
    add(def) { defs.set(def.id, def); build(def); return def; },
    start() { arrange(load()); },
    isOpen: (id) => opened === defs.get(id)?.card,
    /** Close any open sheet, reveal a widget, and scroll it into view. */
    focus(id) {
      const def = defs.get(id);
      if (!def) return;
      close();
      if (def.card.hidden) { def.card.hidden = false; save(); }
      def.card.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'center' });
      def.card.classList.add('flash'); setTimeout(() => def.card.classList.remove('flash'), 900);
    },
  };
})();
