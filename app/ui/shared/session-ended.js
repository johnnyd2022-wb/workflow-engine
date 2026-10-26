/**
 * What happens when a save meets an expired session (GL-U03).
 *
 * Every API client in the app (CoreAPI, CRMAPI, the compliance pages' own fetches) shows a
 * failed save as an error and leaves the form as it was. This adds the way back in:
 *
 *  - a write that comes back 401 (the server also answers a signed-out CSRF failure that way)
 *    shows one notice with "Sign in again", which opens in a new tab (2FA works as usual);
 *  - signing in there rotates the session and its CSRF secret, so this page's token is stale.
 *    When a write comes back 400 with code "csrf" while signed in, the page fetches a fresh
 *    token, puts it in its meta tag and sends that write again, once. A CSRF failure means the
 *    write never ran, so the retry can't duplicate it;
 *  - coming back to this tab signed in hides the notice and refreshes the token straight away.
 *
 * Every client reads the meta tag at request time, so the next save uses the new token.
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

  // A native modal <dialog> makes everything outside it inert, whatever this page does, so the
  // notice goes inside the top one. Otherwise it sits on <body>.
  function topLayer() {
    var modals = Array.prototype.filter.call(document.querySelectorAll('dialog[open]'), function (d) {
      try { return d.matches(':modal'); } catch (e) { return false; }
    });
    return modals[modals.length - 1] || document.body;
  }

  function notice() {
    var existing = document.getElementById('session-ended-notice');
    if (existing) {
      var layer = topLayer();
      if (existing.parentNode !== layer) layer.append(existing);
      existing.hidden = false;
      return existing;
    }
    var box = document.createElement('div');
    box.id = 'session-ended-notice';
    box.className = 'session-ended';
    box.setAttribute('role', 'alert');
    // Usable over an open form: dialog-focus.js leaves it live and in the Tab order.
    box.setAttribute('data-live-over-modal', '');
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
    topLayer().append(box);
    return box;
  }

  function refreshToken() {
    return originalFetch('/auth/csrf-token', { credentials: 'include', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.csrf_token) return null;
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) meta.setAttribute('content', data.csrf_token);
        return data.csrf_token;
      })
      .catch(function () { return null; });
  }

  function withToken(init, token) {
    var copy = Object.assign({}, init || {});
    var headers = new Headers((init && init.headers) || {});
    if (headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', token);
    headers.set('X-CSRFToken', token);
    copy.headers = headers;
    return copy;
  }

  window.fetch = function (input, init) {
    var method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    var watched = WRITES[method] && sameOrigin(url) && !isAuthRoute(url);
    var pending = originalFetch.apply(this, arguments);
    if (!watched) return pending;
    // A Request object's body can only be read once; only plain (url, init) calls are retried.
    var canRetry = typeof input === 'string' || input instanceof URL;
    return pending.then(function (response) {
      if (response.status === 401) { notice(); return response; }
      if (response.status !== 400 || !canRetry) return response;
      return response.clone().json().catch(function () { return null; }).then(function (body) {
        if (!body || body.code !== 'csrf') return response;
        return refreshToken().then(function (token) {
          if (!token) return response;
          return originalFetch(input, withToken(init, token)).then(function (retried) {
            if (retried.status === 401) notice();
            return retried;
          });
        });
      });
    });
  };

  // Signing in on the other tab: when this tab is looked at again, hide the notice and take a
  // fresh token, so the next save goes through.
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState !== 'visible') return;
    var box = document.getElementById('session-ended-notice');
    if (!box || box.hidden) return;
    originalFetch('/auth/me', { credentials: 'include' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.user) return;
        box.hidden = true;
        refreshToken();
      })
      .catch(function () {});
  });
})();
