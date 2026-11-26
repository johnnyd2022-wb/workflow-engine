// GLASS PROTOTYPE: the top bar's behaviour on every page. Theme switch, the Action items tray
// (filled from the dashboard summary's action board), and keeping the workspace links' current
// state right after a boosted navigation (the bar sits outside #page-content, so htmx leaves it).
(() => {
  if (window.__glassShell) return;
  window.__glassShell = true;

  const $ = (id) => document.getElementById(id);
  const phone = window.matchMedia('(max-width:720px)');
  const REFRESH_MS = 60 * 1000;
  let loadedAt = 0;
  let loading = null;

  // ---- Theme ----
  document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-glass-theme]');
    if (!t || !window.SpaTheme) return;
    window.SpaTheme.set(window.SpaTheme.get() === 'dark' ? 'light' : 'dark');
    if (typeof window.syncSpaThemeToggle === 'function') window.syncSpaThemeToggle();
  });

  // ---- Workspace links: which one is current ----
  function syncNav() {
    const marker = document.querySelector('#page-content [data-nav-section]');
    const section = marker ? marker.getAttribute('data-nav-section') : '';
    document.querySelectorAll('[data-glass-topbar] .g-ws a, [data-glass-tabbar] a').forEach((a) => {
      if (section && a.getAttribute('data-nav-section') === section) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
  }

  // ---- Action items tray ----
  const btn = $('g-act-btn');
  const tray = $('g-act-tray');
  const scrim = $('g-scrim');
  if (!btn || !tray) { syncNav(); return; }
  const home = tray.parentNode;

  function place() { (phone.matches ? document.body : home).appendChild(tray); }
  place();
  if (phone.addEventListener) phone.addEventListener('change', place);

  function setOpen(open) {
    tray.classList.toggle('open', open);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (scrim) scrim.classList.toggle('open', open && phone.matches);
    if (open) {
      load(false);
      const first = tray.querySelector('.g-items a') || tray.querySelector('a');
      if (first) first.focus({ preventScroll: true });
    }
  }
  btn.addEventListener('click', (e) => { e.stopPropagation(); setOpen(btn.getAttribute('aria-expanded') !== 'true'); });
  if (scrim) scrim.addEventListener('click', () => setOpen(false));
  document.addEventListener('click', (e) => {
    if (tray.classList.contains('open') && !e.target.closest('#g-act-tray') && !e.target.closest('#g-act-btn')) setOpen(false);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && tray.classList.contains('open')) { setOpen(false); btn.focus(); }
  });
  tray.addEventListener('click', (e) => { if (e.target.closest('a')) setOpen(false); });

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function chevron() {
    const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('class', 'go'); s.setAttribute('aria-hidden', 'true');
    const u = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    u.setAttribute('href', '#gi-right'); s.appendChild(u);
    return s;
  }
  const WS = { production: 'Production', compliance: 'Compliance', sales: 'Sales', settings: 'Settings' };

  function render(board) {
    const list = $('g-act-list');
    const count = $('g-act-count');
    const cap = $('g-act-cap');
    const items = (Array.isArray(board) ? board : []).filter((it) => it && Number(it.count) > 0);
    const total = items.reduce((n, it) => n + Number(it.count || 0), 0);
    list.replaceChildren();
    if (count) {
      count.textContent = total > 99 ? '99+' : String(total);
      count.hidden = total === 0;
    }
    btn.setAttribute('aria-label', total ? `Action items, ${total} open` : 'Action items, none open');
    if (!items.length) {
      cap.textContent = 'Nothing needs you right now.';
      const li = el('li'); li.appendChild(el('span', 'g-empty', 'All clear.')); list.appendChild(li);
      return;
    }
    const spaces = [...new Set(items.map((it) => WS[it.workspace] || it.workspace).filter(Boolean))];
    cap.textContent = `${total} open${spaces.length ? ' across ' + spaces.join(', ').toLowerCase().replace(/, ([^,]*)$/, ' and $1') : ''}.`;
    items.forEach((it) => {
      const li = el('li');
      const a = el('a', 'sev-' + (it.severity || 'medium'));
      a.href = it.href || '/core/notifications';
      a.appendChild(el('span', 'n', String(it.count)));
      const t = el('span');
      t.appendChild(el('b', null, it.label || 'Action item'));
      const meta = [WS[it.workspace] || it.workspace, it.detail || it.due_label].filter(Boolean).join(' · ');
      if (meta) t.appendChild(el('small', null, meta));
      a.appendChild(t);
      a.appendChild(chevron());
      li.appendChild(a); list.appendChild(li);
    });
  }

  function load(force) {
    if (loading) return loading;
    if (!force && Date.now() - loadedAt < REFRESH_MS) return Promise.resolve();
    const api = window.CoreAPI;
    if (!api || typeof api.getDashboardSummary !== 'function') return Promise.resolve();
    loading = api.getDashboardSummary(30)
      .then((data) => {
        if (!data || data._status >= 400) throw new Error('summary unavailable');
        const board = data.action_board || (data.data && data.data.action_board) || [];
        render(Array.isArray(board) ? board : board.items || []);
        loadedAt = Date.now();
      })
      .catch(() => {
        const cap = $('g-act-cap');
        if (cap && !loadedAt) cap.textContent = 'Action items could not load. Try again in a moment.';
      })
      .finally(() => { loading = null; });
    return loading;
  }

  document.body.addEventListener('htmx:afterSettle', () => { syncNav(); load(false); });
  window.addEventListener('pageshow', syncNav);
  syncNav();
  load(true);
})();
