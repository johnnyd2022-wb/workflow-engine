/**
 * Help and contact (GL-C04): the account menu's "Help and contact" opens #bize-help with the
 * page, this page's reference and, if a request failed on the server since, that request's
 * reference. The support email link starts with all of it filled in.
 *
 * A reference is the first 8 characters of the request's X-Request-ID, the request_id on every
 * log line for it (app/observability/reference.py). The page's own reference comes from
 * <meta name="request-reference"> on a full load and from the response header on a boosted
 * navigation (which swaps only #page-content, so the meta tag would go stale).
 */
(function () {
  'use strict';
  if (window.BizeHelp) return;

  function short(id) {
    return String(id || '').replace(/-/g, '').slice(0, 8).toLowerCase();
  }

  var meta = document.querySelector('meta[name="request-reference"]');
  var state = { ref: meta ? meta.getAttribute('content') || '' : '', lastError: null };

  function noteFailure(id, status, path) {
    // A boosted 403/404 is a failed page navigation too; keep its reference available after the toast.
    if (!id || (status < 500 && status !== 403 && status !== 404)) return;
    state.lastError = { ref: short(id), status: status, path: path || '', at: new Date() };
  }

  // Boosted page loads, and htmx requests that fail on the server.
  document.addEventListener('htmx:afterRequest', function (evt) {
    var d = evt.detail || {};
    var xhr = d.xhr;
    if (!xhr || typeof xhr.getResponseHeader !== 'function') return;
    var id = xhr.getResponseHeader('X-Request-ID');
    if (!id) return;
    var boosted = d.boosted || (d.requestConfig && d.requestConfig.boosted);
    if (boosted && xhr.status < 400) state.ref = short(id);
    if (boosted || xhr.status >= 500) noteFailure(id, xhr.status, d.pathInfo && d.pathInfo.requestPath);
  });

  // fetch() calls that fail on the server. Passes every response and rejection through untouched.
  if (typeof window.fetch === 'function') {
    var originalFetch = window.fetch;
    window.fetch = function (input) {
      return originalFetch.apply(this, arguments).then(function (response) {
        try {
          if (response && response.status >= 500) {
            var url = typeof input === 'string' ? input : (input && input.url) || '';
            noteFailure(response.headers.get('X-Request-ID'), response.status, url.split('?')[0]);
          }
        } catch (e) { /* never break the caller */ }
        return response;
      });
    };
  }

  function el(id) { return document.getElementById(id); }

  function timeText(when) {
    try {
      return when.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
    } catch (e) {
      return when.toISOString();
    }
  }

  function fill() {
    var page = (document.title || '').replace(/\s*·\s*biz-e\s*$/, '') + ' (' + location.pathname + ')';
    el('bize-help-page').textContent = page;
    el('bize-help-ref').textContent = state.ref || 'not available';
    var errorRow = el('bize-help-error-row');
    if (state.lastError) {
      el('bize-help-error').textContent = state.lastError.ref + ' (' + state.lastError.status + ', ' + timeText(state.lastError.at) + ')';
      errorRow.hidden = false;
    } else {
      errorRow.hidden = true;
    }
    var mail = el('bize-help-mail');
    if (mail) {
      var ref = (state.lastError && state.lastError.ref) || state.ref;
      var lines = [
        'What happened:',
        '',
        '',
        '---',
        'Page: ' + page,
        'Reference: ' + (state.ref || 'not available'),
        state.lastError ? 'Last error: ' + state.lastError.ref + ' (' + state.lastError.status + ' on ' + state.lastError.path + ')' : '',
        'Time: ' + timeText(new Date())
      ].filter(function (line, i) { return line !== '' || i < 3; });
      mail.href = 'mailto:' + mail.getAttribute('data-support-email') +
        '?subject=' + encodeURIComponent('biz-e help' + (ref ? ' (ref ' + ref + ')' : '')) +
        '&body=' + encodeURIComponent(lines.join('\n'));
    }
  }

  function open() {
    var dialog = el('bize-help');
    if (!dialog) return;
    fill();
    var copy = el('bize-help-copy');
    if (copy) copy.textContent = 'Copy';
    if (!dialog.__bizeHelpWired) {
      dialog.__bizeHelpWired = true;
      // Opened from an item in the account menu, which has closed by now: give focus back to the
      // menu's button, after the shared dialog helper has tried the (hidden) item.
      dialog.addEventListener('close', function () {
        setTimeout(function () {
          var button = document.querySelector('.bee-profile__button');
          if (button && (document.activeElement === document.body || !document.activeElement || document.activeElement.offsetParent === null)) {
            button.focus();
          }
        }, 0);
      });
    }
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
  }

  document.addEventListener('click', function (evt) {
    var target = evt.target;
    if (!(target instanceof Element)) return;
    var dialog = el('bize-help');
    if (!dialog) return;
    if (target.closest('#bize-help [data-dialog-close]') || target === dialog) {
      dialog.close();
      return;
    }
    if (target.closest('#bize-help-copy')) {
      var text = el('bize-help-ref').textContent;
      var button = el('bize-help-copy');
      var done = function () { button.textContent = 'Copied'; };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { button.textContent = 'Select and copy'; });
      } else {
        button.textContent = 'Select and copy';
      }
    }
  });

  window.BizeHelp = { open: open, reference: function () { return state.ref; }, lastError: function () { return state.lastError; } };
})();
