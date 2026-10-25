/**
 * Keyboard behaviour for every role="tablist" in the app (GL-U02a).
 *
 * A tab row is one stop in the Tab order: the selected tab takes focus, the others are reached
 * with the arrow keys, Home and End. Button tabs switch as focus moves onto them, as the ARIA
 * tabs pattern's automatic activation does. Link tabs (the section tabs, each a separate page)
 * only move focus; Enter follows the link, so arrowing past a tab never loads a page.
 *
 * Loaded once from base_spa.html; it reads the DOM each time, so Alpine and htmx tab rows need
 * no wiring.
 */
(function () {
  'use strict';
  if (window.__bizeTabsKeyboard) return;
  window.__bizeTabsKeyboard = true;

  function tabsOf(list) {
    return Array.prototype.filter.call(list.querySelectorAll('[role="tab"]'), function (tab) {
      return tab.closest('[role="tablist"]') === list && !tab.hidden && !tab.disabled && tab.getClientRects().length > 0;
    });
  }

  function selected(tabs) {
    return tabs.find(function (t) { return t.getAttribute('aria-selected') === 'true'; }) || tabs[0];
  }

  // One Tab stop per row: the selected tab. Re-run whenever a row may have changed.
  function rove(list) {
    var tabs = tabsOf(list);
    var current = selected(tabs);
    tabs.forEach(function (t) { t.setAttribute('tabindex', t === current ? '0' : '-1'); });
  }

  function roveAll() {
    Array.prototype.forEach.call(document.querySelectorAll('[role="tablist"]'), rove);
  }

  var scheduled = false;
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(function () { scheduled = false; roveAll(); });
  }

  document.addEventListener('keydown', function (event) {
    var tab = event.target.closest && event.target.closest('[role="tab"]');
    var list = tab && tab.closest('[role="tablist"]');
    if (!list || event.altKey || event.ctrlKey || event.metaKey) return;
    var tabs = tabsOf(list);
    var i = tabs.indexOf(tab);
    if (i === -1) return;
    var vertical = list.getAttribute('aria-orientation') === 'vertical';
    var next = null;
    if (event.key === (vertical ? 'ArrowDown' : 'ArrowRight')) next = tabs[(i + 1) % tabs.length];
    else if (event.key === (vertical ? 'ArrowUp' : 'ArrowLeft')) next = tabs[(i - 1 + tabs.length) % tabs.length];
    else if (event.key === 'Home') next = tabs[0];
    else if (event.key === 'End') next = tabs[tabs.length - 1];
    if (!next) return;
    event.preventDefault();
    tabs.forEach(function (t) { t.setAttribute('tabindex', t === next ? '0' : '-1'); });
    next.focus();
    if (next.tagName !== 'A') next.click();
  });

  // Leaving a row puts its Tab stop back on the selected tab.
  document.addEventListener('focusout', function (event) {
    var list = event.target.closest && event.target.closest('[role="tablist"]');
    if (list && !list.contains(event.relatedTarget)) rove(list);
  });

  new MutationObserver(schedule).observe(document.documentElement, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ['aria-selected', 'hidden']
  });
  document.addEventListener('htmx:afterSettle', schedule);
  schedule();
})();
