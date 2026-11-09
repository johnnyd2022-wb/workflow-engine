/* The section tab strip scrolls sideways on a phone when its tabs don't fit
   (app/core/frontend/css/section-tabs.css). Two things make that visible:
   - the current tab is scrolled into view, so "Task settings" is never cut to "Task se";
   - data-more-start / data-more-end mark the edges with more tabs past them, which the CSS
     fades, so the strip reads as scrollable. Runs on a full load and after every boosted swap. */
(function () {
  function sync(nav) {
    var max = nav.scrollWidth - nav.clientWidth;
    nav.toggleAttribute('data-more-start', max > 1 && nav.scrollLeft > 1);
    nav.toggleAttribute('data-more-end', max > 1 && nav.scrollLeft < max - 1);
  }

  function reveal(nav) {
    var active = nav.querySelector('.flow-mode-segment--active');
    if (active) {
      var left = active.offsetLeft - nav.offsetLeft;
      var right = left + active.offsetWidth;
      // Keep a little of the next tab showing, so there is visibly more to scroll to.
      if (right > nav.scrollLeft + nav.clientWidth) nav.scrollLeft = right - nav.clientWidth + 24;
      else if (left < nav.scrollLeft) nav.scrollLeft = Math.max(0, left - 24);
    }
    sync(nav);
  }

  function init(root) {
    (root || document).querySelectorAll('.section-tabs').forEach(function (nav) {
      if (!nav.__sectionTabsBound) {
        nav.addEventListener('scroll', function () { sync(nav); }, { passive: true });
        nav.__sectionTabsBound = true;
      }
      reveal(nav);
    });
  }

  window.__sectionTabsInit = init;
  if (!window.__sectionTabsListenersBound) {
    document.addEventListener('DOMContentLoaded', function () { window.__sectionTabsInit(); });
    document.body.addEventListener('htmx:afterSwap', function () { window.__sectionTabsInit(); });
    window.addEventListener('resize', function () { window.__sectionTabsInit(); });
    window.__sectionTabsListenersBound = true;
  }
  if (document.readyState !== 'loading') init();
})();
