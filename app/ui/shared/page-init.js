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

  // HTMX deliberately leaves error responses unswapped. For a boosted page link that means the
  // user stays on the old page without feedback. Keep the current page intact and surface the
  // same request reference GL-C04 would show on a full-page error response.
  document.addEventListener('htmx:responseError', function (evt) {
    var d = evt.detail || {};
    var target = isPageContent(evt);
    var boosted = d.boosted || (d.requestConfig && d.requestConfig.boosted);
    var xhr = d.xhr;
    if (!target || !boosted || !xhr || Number(xhr.status) < 400) return;

    var status = Number(xhr.status);
    var requestId = typeof xhr.getResponseHeader === 'function' ? xhr.getResponseHeader('X-Request-ID') : '';
    var reference = String(requestId || '').replace(/-/g, '').slice(0, 8).toLowerCase();
    var title = status === 404 ? 'Page not found' : (status === 403 ? 'No access to that page' : 'Page could not load');
    var message = status === 404
      ? "We couldn't find that page."
      : (status === 403
        ? "Your role can't open that page. Ask an admin if you need it."
        : 'Something went wrong while loading this page.');
    message += reference
      ? ' Reference: ' + reference + '. Open Help and contact to share it.'
      : ' Open Help and contact to ask for support.';

    if (typeof window.showNotification === 'function') {
      window.showNotification('error', title, message);
    }
  });
})();
