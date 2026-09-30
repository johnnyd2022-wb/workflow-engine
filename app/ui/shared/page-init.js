/**
 * One page-init convention for boosted navigation (docs/ux-overhaul-plan.md, 1.4).
 *
 * `DOMContentLoaded` fires once per full load, so a page script that starts there never runs
 * after an htmx-boosted swap of #page-content. Register instead:
 *
 *     bize.onPage('[data-np3-check-root]', function (root) {
 *       // wire `root`; optionally return a function that undoes global side effects
 *       return function teardown() {};
 *     });
 *
 * `init(root)` runs once for each element matching `selector`: at first load, and after every
 * swap that brings a new one in. A root is initialised at most once per key, so a page script
 * that htmx re-executes on every visit can register again without double-wiring. The optional
 * returned teardown runs before the root is swapped out. The key defaults to the selector; pass
 * `{ key: 'name' }` when two scripts share a selector.
 */
(function () {
  'use strict';

  var bize = (window.bize = window.bize || {});
  if (bize.onPage) return;

  var registry = Object.create(null); // key -> { selector, init }
  var live = []; // { el, teardown } for roots with a teardown

  function rootsFor(scope, selector) {
    var found = [];
    if (scope.nodeType === 1 && scope.matches && scope.matches(selector)) found.push(scope);
    return found.concat(Array.prototype.slice.call(scope.querySelectorAll(selector)));
  }

  function runEntry(key, scope) {
    var entry = registry[key];
    if (!entry) return;
    rootsFor(scope, entry.selector).forEach(function (el) {
      var done = el.__bizeInit || (el.__bizeInit = Object.create(null));
      if (done[key]) return;
      done[key] = true;
      try {
        var teardown = entry.init(el);
        if (typeof teardown === 'function') live.push({ el: el, teardown: teardown });
      } catch (err) {
        if (window.console) console.error('bize.onPage(' + key + ') failed:', err);
      }
    });
  }

  function runAll(scope) {
    Object.keys(registry).forEach(function (key) { runEntry(key, scope); });
  }

  bize.onPage = function (selector, init, options) {
    var key = (options && options.key) || selector;
    registry[key] = { selector: selector, init: init };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () { runEntry(key, document); }, { once: true });
    } else {
      runEntry(key, document);
    }
  };

  function isPageContent(evt) {
    var target = evt.detail && evt.detail.target;
    return target && target.id === 'page-content' ? target : null;
  }

  document.addEventListener('htmx:beforeSwap', function (evt) {
    var target = isPageContent(evt);
    if (!target || (evt.detail && evt.detail.shouldSwap === false)) return;
    live = live.filter(function (item) {
      if (!target.contains(item.el)) return true;
      try { item.teardown(); } catch (err) { if (window.console) console.error('page teardown failed:', err); }
      return false;
    });
  });

  document.addEventListener('htmx:afterSettle', function (evt) {
    var target = isPageContent(evt);
    if (target) runAll(target);
  });
})();
