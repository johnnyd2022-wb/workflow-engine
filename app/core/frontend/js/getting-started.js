// Getting started (GL-P09). The server works out every step's state from the org's own
// records; this page lays them out as a setup guide: one card, the next step open with its
// button, the rest one line each with their status in words.
(function () {
  'use strict';

  var STATUS = { done: 'Done', todo: 'To do', blocked: 'Cannot start yet' };

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (attrs[k] == null) return;
      if (k === 'text') node.textContent = attrs[k];
      else if (k === 'className') node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c) node.append(c); });
    return node;
  }

  function tag(step) {
    return el('span', { className: 'gs-status gs-status--' + step.status, text: STATUS[step.status] });
  }

  function mark(step) {
    // A tick for done, the step's number otherwise; status is always in words beside it.
    return el('span', { className: 'gs-mark gs-mark--' + step.status, 'aria-hidden': 'true', text: step.status === 'done' ? '✓' : String(step.n) });
  }

  function action(step) {
    if (step.status === 'blocked') return el('p', { className: 'gs-blocked', text: step.blocked_by });
    var cls = 'workspace-button' + (step.status === 'todo' ? ' workspace-button--primary gs-primary' : '');
    return el('a', { className: cls, href: step.href, text: step.status === 'done' ? 'Open' : step.action });
  }

  function renderGuide(root, data, openKey) {
    var list = root.querySelector('[data-gs-guide]');
    list.replaceChildren();
    data.steps.forEach(function (step) {
      var open = step.key === openKey;
      var id = 'gs-guide-' + step.key;
      var toggle = el('button', { type: 'button', className: 'gs-guide__toggle', 'aria-expanded': open ? 'true' : 'false', 'aria-controls': id }, [
        mark(step),
        el('span', { className: 'gs-guide__text' }, [
          el('span', { className: 'gs-guide__title', text: step.title }),
          step.fact && !open ? el('span', { className: 'gs-guide__fact', text: step.fact }) : null
        ]),
        tag(step)
      ]);
      var body = el('div', { className: 'gs-guide__body', id: id }, [
        el('p', { className: 'gs-why', text: step.why }),
        step.fact ? el('p', { className: 'gs-fact', text: step.fact }) : null,
        action(step)
      ]);
      body.hidden = !open;
      toggle.addEventListener('click', function () { renderGuide(root, data, open ? null : step.key); });
      list.append(el('li', { className: 'gs-guide__item gs-guide__item--' + step.status + (open ? ' is-open' : '') }, [toggle, body]));
    });
  }

  function render(root, data) {
    data.steps.forEach(function (s, i) { s.n = i + 1; });
    root.querySelector('[data-gs-loading]').hidden = true;
    root.querySelector('[data-gs-progress]').hidden = false;
    root.querySelector('[data-gs-done]').textContent = data.done;
    root.querySelector('[data-gs-total]').textContent = data.total;
    root.querySelector('[data-gs-bar]').style.width = (data.total ? Math.round(100 * data.done / data.total) : 0) + '%';
    root.querySelector('[data-gs-complete]').hidden = !data.complete;
    root.querySelector('[data-gs-guide-card]').hidden = false;
    renderGuide(root, data, data.next);
  }

  function init(root) {
    fetch('/api/core/getting-started', { credentials: 'include', headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error('Could not load your progress (' + r.status + '). Refresh to try again.'); return r.json(); })
      .then(function (data) { if (root.isConnected) render(root, data); })
      .catch(function (err) {
        root.querySelector('[data-gs-loading]').hidden = true;
        var m = root.querySelector('[data-gs-message]');
        m.textContent = err.message;
        m.className = 'gs-message gs-message--error';
        m.hidden = false;
      });
  }

  // Runs at first load and after every boosted swap that brings the page in (page-init.js).
  bize.onPage('[data-getting-started-root]', init);
})();
