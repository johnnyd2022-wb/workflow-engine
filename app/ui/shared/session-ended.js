/**
 * What happens when a save meets an expired session (GL-U03).
 *
 * Every API client in the app (CoreAPI, CRMAPI, the compliance pages' own fetches) shows the
 * 401 as an error and leaves the form as it was, but nothing told the person how to get back
 * in without leaving the page and losing what they typed. This watches same-origin writes;
 * when one comes back 401 it shows one notice with a "Sign in again" link that opens in a
 * new tab (2FA works as normal there). The form on this page is never touched, so after
 * signing in they press Save again.
 *
 * Loaded once from base_spa.html.
 */
(function () {
  'use strict';
  if (window.__bizeSessionEnded || typeof window.fetch !== 'function') return;
  window.__bizeSessionEnded = true;

  var WRITES = { POST: 1, PUT: 1, PATCH: 1, DELETE: 1 };
  var originalFetch = window.fetch;

  function sameOrigin(url) {
    try { return new URL(url, window.location.href).origin === window.location.origin; } catch (e) { return false; }
  }

  function isAuthRoute(url) {
    try { return new URL(url, window.location.href).pathname.indexOf('/auth/') === 0; } catch (e) { return true; }
  }

  function notice() {
    var existing = document.getElementById('session-ended-notice');
    if (existing) { existing.hidden = false; return existing; }
    var box = document.createElement('div');
    box.id = 'session-ended-notice';
    box.className = 'session-ended';
    box.setAttribute('role', 'alert');
    var text = document.createElement('p');
    text.className = 'session-ended__text';
    var strong = document.createElement('strong');
    strong.textContent = 'You’ve been signed out, so that wasn’t saved.';
    text.append(strong, document.createTextNode(' What you entered is still on this page. Sign in again in a new tab, then come back and save.'));
    var link = document.createElement('a');
    link.className = 'session-ended__signin';
    link.href = '/?login=1';
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = 'Sign in again';
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'session-ended__close';
    close.setAttribute('aria-label', 'Close');
    close.textContent = '×';
    close.addEventListener('click', function () { box.hidden = true; });
    box.append(text, link, close);
    document.body.append(box);
    return box;
  }

  window.fetch = function (input, init) {
    var method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    var watched = WRITES[method] && sameOrigin(url) && !isAuthRoute(url);
    var pending = originalFetch.apply(this, arguments);
    if (!watched) return pending;
    return pending.then(function (response) {
      if (response.status === 401) notice();
      return response;
    });
  };

  // Signing in on the other tab: hide the notice when this tab is looked at again.
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState !== 'visible') return;
    var box = document.getElementById('session-ended-notice');
    if (!box || box.hidden) return;
    originalFetch('/auth/me', { credentials: 'include' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data && data.user) box.hidden = true; })
      .catch(function () {});
  });
})();
