// Shared sidebar toggle function for V2 Modern design
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const mainContent = document.querySelector('.main-content');
  sidebar.classList.toggle('collapsed');
  
  // Adjust main content margin based on sidebar state
  if (sidebar.classList.contains('collapsed')) {
    mainContent.style.marginLeft = '72px';
  } else {
    mainContent.style.marginLeft = '260px';
  }
}

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

// Initial paint (full load)
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', function () {
    _lastSidebarPathname = normalizePathname(window.location.pathname);
    updateSidebarActiveLink();
  });
} else {
  _lastSidebarPathname = normalizePathname(window.location.pathname);
  updateSidebarActiveLink();
}

// HTMX SPA navigation: sidebar stays, content swaps.
document.body.addEventListener('htmx:afterSwap', function (evt) {
  // Only run when main content was swapped
  const target = evt && evt.detail && evt.detail.target;
  if (target && (target.id === 'page-content' || target.closest && target.closest('#page-content'))) {
    const now = normalizePathname(window.location.pathname);
    if (now === _lastSidebarPathname) return; // in-page content updates; no navigation
    _lastSidebarPathname = now;
    updateSidebarActiveLink();
  }
});

// Back/forward navigation
window.addEventListener('popstate', function () {
  const now = normalizePathname(window.location.pathname);
  _lastSidebarPathname = now;
  updateSidebarActiveLink();
});

