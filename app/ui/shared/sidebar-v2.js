// This file is re-evaluated after an HTMX boosted navigation. Keep its state
// private so a second evaluation cannot redeclare a top-level lexical binding.
(() => {
// Collapse the sidebar to a rail and back (laptop and desktop). The stylesheet does the moving
// (styles2.css, --sidebar-w); this fades the labels out first so nothing is seen to reflow,
// remembers the choice, and keeps the button's name in step with what it will do.
const COLLAPSED_KEY = 'sidebarCollapsed';
const FADE_MS = 90;
const SLIDE_MS = 280; // the 240ms glide in styles2.css, plus a margin so it is never cut short
let _sidebarTimers = [];

function syncSidebarToggle(sidebar, collapsed) {
  const button = sidebar.querySelector('[data-sidebar-toggle]');
  if (!button) return;
  const label = collapsed ? 'Expand menu' : 'Collapse menu';
  button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  button.setAttribute('aria-label', label);
  button.setAttribute('title', label);
}

window.toggleSidebar = function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;
  // Mid-move the class lags the choice, so a second press reverses the choice, not the class.
  const target = sidebar.getAttribute('data-sidebar-target');
  const collapse = !(target ? target === 'collapsed' : sidebar.classList.contains('collapsed'));
  sidebar.setAttribute('data-sidebar-target', collapse ? 'collapsed' : 'open');
  try { window.localStorage.setItem(COLLAPSED_KEY, String(collapse)); } catch (_) { /* private mode */ }
  syncSidebarToggle(sidebar, collapse);

  _sidebarTimers.forEach(clearTimeout);
  _sidebarTimers = [];
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    sidebar.classList.remove('sidebar--switching');
    sidebar.classList.toggle('collapsed', collapse);
    return;
  }
  sidebar.classList.add('sidebar--switching');
  _sidebarTimers.push(setTimeout(() => {
    sidebar.classList.toggle('collapsed', collapse);
    _sidebarTimers.push(setTimeout(() => sidebar.classList.remove('sidebar--switching'), SLIDE_MS));
  }, FADE_MS));
};

(function initSidebarToggle() {
  const sidebar = document.getElementById('sidebar');
  if (sidebar) syncSidebarToggle(sidebar, sidebar.classList.contains('collapsed'));
})();

function normalizePathname(pathname) {
  const p = (pathname || '').trim();
  if (!p) return '/';
  // drop trailing slashes except root
  return p.length > 1 ? p.replace(/\/+$/, '') : p;
}

let _lastSidebarPathname = null;

function updateSidebarActiveLink() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;

  const current = normalizePathname(window.location.pathname);
  const links = sidebar.querySelectorAll('a.nav-link[href]');

  // Choose best match by longest prefix:
  // - exact match wins
  // - otherwise a link to "/core" stays active for "/core/flows", etc.
  let bestLink = null;
  let bestLen = -1;

  links.forEach((a) => {
    try {
      const href = a.getAttribute('href') || '';
      // Ignore hash/empty/non-app links
      if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;

      const url = new URL(href, window.location.origin);
      const target = normalizePathname(url.pathname);
      const isExact = target === current;
      const isPrefix = current === target || current.startsWith(target + '/');
      if (!isPrefix) return;

      const score = isExact ? (target.length + 10000) : target.length;
      if (score > bestLen) {
        bestLen = score;
        bestLink = a;
      }
    } catch (_) {
      // If URL parsing fails, just skip.
    }
  });

  links.forEach((a) => {
    const isActive = a === bestLink;
    a.classList.toggle('active', isActive);
    if (isActive) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
}

function refreshSidebarActiveLink() {
  _lastSidebarPathname = normalizePathname(window.location.pathname);
  updateSidebarActiveLink();
}

function handleSidebarAfterSwap(evt) {
  // Only run when main content was swapped
  const target = evt && evt.detail && evt.detail.target;
  if (target && (target.id === 'page-content' || target.closest && target.closest('#page-content'))) {
    const now = normalizePathname(window.location.pathname);
    if (now === _lastSidebarPathname) return; // in-page content updates; no navigation
    _lastSidebarPathname = now;
    updateSidebarActiveLink();
  }
}

window.__sidebarV2Refresh = refreshSidebarActiveLink;
window.__sidebarV2HandleAfterSwap = handleSidebarAfterSwap;

// The asset can be evaluated again after HTMX navigation. Bind the shared
// document listeners once, while dispatching to the most recently evaluated
// implementation above.
if (!window.__sidebarV2ListenersBound) {
  document.addEventListener('DOMContentLoaded', function () {
    window.__sidebarV2Refresh();
  });
  document.body.addEventListener('htmx:afterSwap', function (evt) {
    window.__sidebarV2HandleAfterSwap(evt);
  });
  window.addEventListener('popstate', function () {
    window.__sidebarV2Refresh();
  });
  window.__sidebarV2ListenersBound = true;
}

// Initial paint (full load) or an immediately-evaluated boosted script.
if (document.readyState !== 'loading') refreshSidebarActiveLink();
})();
