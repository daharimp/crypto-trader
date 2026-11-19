/* Trader Desk appearance (ADR-037): Auto follows the device, Light and Dark are fixed, and
   "Day and night" is light from 7am to 7pm by this device's clock. The choice is saved in
   this browser only (localStorage); nothing is sent to the server. */
(() => {
  'use strict';
  const KEY = 'trader-desk.look.v1';
  const MODES = ['auto', 'light', 'dark', 'clock'];
  const BG = { light: '#f3f5f4', dark: '#111816' };
  const root = document.documentElement, listeners = [];
  const system = matchMedia('(prefers-color-scheme: dark)');
  function read() {
    try { const v = localStorage.getItem(KEY); return MODES.includes(v) ? v : 'auto'; } catch { return 'auto'; }
  }
  let mode = read();
  function isDark() {
    if (mode === 'dark') return true;
    if (mode === 'light') return false;
    if (mode === 'clock') { const h = new Date().getHours(); return h < 7 || h >= 19; }
    return system.matches;
  }
  function apply() {
    const theme = isDark() ? 'dark' : 'light';
    if (root.dataset.theme === theme) return;
    root.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', BG[theme]);
    listeners.forEach((f) => f(theme));
  }
  window.Look = {
    modes: MODES,
    get mode() { return mode; },
    set(v) {
      if (!MODES.includes(v)) return;
      mode = v;
      try { localStorage.setItem(KEY, v); } catch { /* private mode: the choice just isn't kept */ }
      apply();
    },
    onChange(f) { listeners.push(f); },
  };
  apply();
  system.addEventListener('change', apply);
  setInterval(apply, 60000); // Reason: "Day and night" has to notice 7am and 7pm.
})();
