// Getting started (GL-P09). The server works out every step's state from the org's own
// records; this page only lays the steps out. Three layouts share the data (CONCEPT ONLY
// until one is chosen): a setup guide, a task list, and one step at a time.
(function () {
  'use strict';

  var STATUS = { done: 'Done', todo: 'To do', blocked: 'Cannot start yet' };
  var STYLE_KEY = 'gettingStarted.style'; // CONCEPT ONLY

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

  function action(step, primary) {
    if (step.status === 'blocked') return el('p', { className: 'gs-blocked', text: step.blocked_by });
    var cls = 'workspace-button' + (primary ? ' workspace-button--primary gs-primary' : '');
    return el('a', { className: cls, href: step.href, text: step.status === 'done' ? 'Open' : step.action });
  }

  // --- Style 1: setup guide ---------------------------------------------------------------

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
        action(step, step.status === 'todo')
      ]);
      body.hidden = !open;
      toggle.addEventListener('click', function () { renderGuide(root, data, open ? null : step.key); });
      list.append(el('li', { className: 'gs-guide__item gs-guide__item--' + step.status + (open ? ' is-open' : '') }, [toggle, body]));
    });
  }

  // --- Style 2: task list ------------------------------------------------------------------

  function renderTasks(root, data) {
    var wrap = root.querySelector('[data-gs-tasks]');
    wrap.replaceChildren();
    var groups = [];
    data.steps.forEach(function (step) {
      var g = groups.find(function (x) { return x.name === step.group; });
      if (!g) { g = { name: step.group, steps: [] }; groups.push(g); }
      g.steps.push(step);
    });
    groups.forEach(function (g, i) {
      var titleId = 'gs-group-' + i;
      var ul = el('ul', { className: 'gs-task-list' });
      g.steps.forEach(function (step) {
        var main = el('span', { className: 'gs-task__main' }, [
          el('span', { className: 'gs-task__title', text: step.title }),
          el('span', { className: 'gs-task__hint', text: step.status === 'blocked' ? step.blocked_by : (step.fact || step.why) })
        ]);
        var row = step.status === 'blocked'
          ? el('div', { className: 'gs-task gs-task--blocked' }, [main, tag(step)])
          : el('a', { className: 'gs-task', href: step.href }, [main, tag(step)]);
        ul.append(el('li', { className: 'gs-task-item' + (step.key === data.next ? ' is-next' : '') }, [row]));
      });
      wrap.append(el('section', { className: 'workspace-card gs-group', 'aria-labelledby': titleId }, [
        el('h2', { id: titleId, text: g.name }),
        ul
      ]));
    });
  }

  // --- Style 3: one step at a time ---------------------------------------------------------

  function renderFocus(root, data, key) {
    var current = data.steps.find(function (s) { return s.key === key; }) || data.steps[0];
    var path = root.querySelector('[data-gs-path]');
    path.replaceChildren();
    data.steps.forEach(function (step) {
      var link = el('button', { type: 'button', className: 'gs-path__step gs-path__step--' + step.status }, [
        mark(step),
        el('span', { className: 'gs-path__title', text: step.title }),
        el('span', { className: 'gs-visually-hidden', text: ', ' + STATUS[step.status] })
      ]);
      if (step === current) {
        link.setAttribute('aria-current', 'step');
        window.requestAnimationFrame(function () {
          if (link.isConnected && path.scrollWidth > path.clientWidth) link.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        });
      }
      link.addEventListener('click', function () { renderFocus(root, data, step.key); });
      path.append(el('li', null, [link]));
    });
    var box = root.querySelector('[data-gs-current]');
    var index = data.steps.indexOf(current);
    var later = data.steps.slice(index + 1).find(function (s) { return s.status === 'todo'; });
    box.replaceChildren.apply(box, [
      el('p', { className: 'gs-current__eyebrow', text: 'Step ' + (index + 1) + ' of ' + data.steps.length + ' · ' + current.group }),
      el('h2', { text: current.title }),
      el('p', { className: 'gs-why gs-why--large', text: current.why }),
      current.fact ? el('p', { className: 'gs-fact', text: current.fact }) : null,
      el('div', { className: 'gs-current__actions' }, [
        current.status === 'blocked' ? blockedAction(root, data, current) : action(current, current.status === 'todo'),
        later && current.status !== 'done'
          ? (function () {
              var skip = el('button', { type: 'button', className: 'gs-skip', text: 'Skip for now' });
              skip.addEventListener('click', function () { renderFocus(root, data, later.key); });
              return skip;
            })()
          : null
      ]),
      current.status === 'done' ? el('p', { className: 'gs-done-note', text: 'Done. ' + (later ? 'Next: ' + later.title + '.' : '') }) : null
    ].filter(Boolean));
  }

  // A blocked step says what it waits for, and goes there.
  function blockedAction(root, data, step) {
    var need = data.steps.find(function (s) { return s.key === step.needs; });
    var wrap = el('div', { className: 'gs-blocked-wrap' }, [el('p', { className: 'gs-blocked', text: step.blocked_by })]);
    if (need) {
      var go = el('button', { type: 'button', className: 'gs-goto', text: 'Go to: ' + need.title });
      go.addEventListener('click', function () { renderFocus(root, data, need.key); });
      wrap.append(go);
    }
    return wrap;
  }

  // --- the page ------------------------------------------------------------------------------

  function render(root, data) {
    data.steps.forEach(function (s, i) { s.n = i + 1; });
    root.querySelector('[data-gs-loading]').hidden = true;
    root.classList.add('is-ready');
    var progress = root.querySelector('[data-gs-progress]');
    progress.hidden = false;
    root.querySelector('[data-gs-done]').textContent = data.done;
    root.querySelector('[data-gs-total]').textContent = data.total;
    root.querySelector('[data-gs-bar]').style.width = (data.total ? Math.round(100 * data.done / data.total) : 0) + '%';
    root.querySelector('[data-gs-complete]').hidden = !data.complete;
    // All done: "You're set up" is the answer, so Style 3 keeps the path but drops the step card.
    root.querySelector('[data-gs-current]').hidden = !!data.complete;
    renderGuide(root, data, data.next);
    renderTasks(root, data);
    renderFocus(root, data, data.next || data.steps[0] && data.steps[0].key);
  }

  // CONCEPT ONLY: which layout to show.
  function setStyle(root, style) {
    root.setAttribute('data-gs-style', style);
    root.querySelectorAll('[data-gs-view]').forEach(function (v) { v.hidden = v.getAttribute('data-gs-view') !== style; });
    root.querySelectorAll('[data-gs-pick]').forEach(function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-gs-pick') === style ? 'true' : 'false'); });
    try { window.localStorage.setItem(STYLE_KEY, style); } catch (e) { /* private mode */ }
  }

  function init(root) {
    var wanted = new URLSearchParams(window.location.search).get('style');
    var remembered = null;
    try { remembered = window.localStorage.getItem(STYLE_KEY); } catch (e) { /* private mode */ }
    var style = /^[123]$/.test(wanted || '') ? wanted : (/^[123]$/.test(remembered || '') ? remembered : '1');
    root.querySelectorAll('[data-gs-pick]').forEach(function (b) {
      b.addEventListener('click', function () { setStyle(root, b.getAttribute('data-gs-pick')); });
    });
    setStyle(root, style);

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
