/* Notifications: things features say need you (app/core/attention.py), above the findings. */
(function () {
  'use strict';
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function bind() {
    var mount = document.querySelector('[data-feature-attention]');
    if (!mount || mount.getAttribute('data-bound') === '1') return;
    mount.setAttribute('data-bound', '1');
    fetch('/api/core/attention', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .then(function (body) {
        var items = (body && body.items) || [];
        if (!items.length) return;
        var list = el('ul', 'nt-feature-list');
        items.forEach(function (item) {
          var li = el('li');
          var a = el('a', 'nt-feature');
          a.href = item.href;
          var main = el('span', 'nt-feature__main');
          main.appendChild(el('span', 'nt-feature__title', item.label));
          main.appendChild(el('span', 'nt-feature__meta', [item.workspace, item.detail].filter(Boolean).join(' · ')));
          a.appendChild(main);
          a.appendChild(el('span', 'nt-feature__count', String(item.count)));
          li.appendChild(a);
          list.appendChild(li);
        });
        mount.replaceChildren(list);
        mount.hidden = false;
      })
      .catch(function () { /* the findings below still load */ });
  }
  bind();
  if (!window.__featureAttentionListener) {
    window.__featureAttentionListener = true;
    document.addEventListener('htmx:afterSettle', bind);
  }
})();
