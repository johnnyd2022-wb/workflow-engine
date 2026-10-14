(() => {
  'use strict';
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const showError = (message) => {
    const target = document.querySelector('.contract-error');
    if (target) {
      target.textContent = message;
      target.hidden = false;
      target.scrollIntoView({ block: 'center' });
    }
  };
  const request = async (url, method, body) => {
    const response = await fetch(url, {
      method,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, Accept: 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = response.status === 204 ? {} : await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to save. Please try again.');
    return data;
  };
  const mapping = (record) => {
    if (record.product_mapping) {
      const [version, output] = record.product_mapping.split('|');
      record.process_id = null;
      record.process_version_id = version;
      record.source_output_id = output;
    }
    delete record.product_mapping;
    return record;
  };
  // Bound once per form element, so a boosted return (which runs this script again) does not
  // submit twice.
  document.querySelectorAll('form[data-contract-api]').forEach((form) => {
    if (form.dataset.contractBound) return;
    form.dataset.contractBound = 'true';
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('button[type="submit"]');
      button.disabled = true;
      try {
        const body = {};
        const line = {};
        new FormData(form).forEach((value, name) => {
          if (name.startsWith('line.')) line[name.slice(5)] = value;
          else body[name] = value;
        });
        if ('is_active' in body) body.is_active = body.is_active === 'true';
        if (form.hasAttribute('data-create-order')) body.lines = [mapping(line)];
        mapping(body);
        const saved = await request(form.dataset.contractApi, form.dataset.method, body);
        if (form.hasAttribute('data-create-order')) {
          window.location.assign('/core/contracts/' + encodeURIComponent(saved.order.id));
        } else window.location.reload();
      } catch (error) {
        showError(error.message);
        button.disabled = false;
      }
    });
  });
  document.querySelectorAll('[data-contract-delete]').forEach((button) => {
    if (button.dataset.contractBound) return;
    button.dataset.contractBound = 'true';
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        await request(button.dataset.contractDelete, 'DELETE');
        window.location.reload();
      } catch (error) {
        showError(error.message);
        button.disabled = false;
      }
    });
  });

  // Contract orders home: due dates and quantities in words, the figures, and the forms that
  // open from their buttons.
  const DAY = 86400000;
  function daysUntil(iso) {
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
    if (!match) return null;
    const due = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    const now = new Date();
    return Math.round((due - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / DAY);
  }
  function dueWords(iso, open) {
    const days = daysUntil(iso);
    if (days === null) return { label: iso, state: 'later' };
    if (open && days < 0) return { label: -days + ' day' + (days === -1 ? '' : 's') + ' overdue', state: 'overdue' };
    if (open && days === 0) return { label: 'Due today', state: 'soon' };
    if (open && days === 1) return { label: 'Due tomorrow', state: 'soon' };
    if (open && days <= 7 && days > 0) return { label: 'Due in ' + days + ' days', state: 'soon' };
    const date = new Date(iso + 'T00:00:00');
    return { label: date.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: days < -300 || days > 300 ? 'numeric' : undefined }), state: 'later' };
  }
  function init(root) {
    const plural = (count, one, many) => count + ' ' + (count === 1 ? one : many);
    let overdue = 0;
    let week = 0;
    const counted = new Set();
    root.querySelectorAll('tr[data-order-status]').forEach((row) => {
      const open = row.dataset.orderStatus === 'draft' || row.dataset.orderStatus === 'confirmed';
      const due = row.querySelector('[data-due]');
      const words = dueWords(due.dataset.due, open);
      due.textContent = words.label;
      due.dataset.state = words.state;
      // The same order appears in the table and in the customer grouping; count it once.
      const key = row.querySelector('a') ? row.querySelector('a').getAttribute('href') : '';
      if (open && !counted.has(key)) {
        counted.add(key);
        const days = daysUntil(due.dataset.due);
        if (days < 0) overdue += 1;
        else if (days <= 7) week += 1;
      }
      row.querySelectorAll('[data-quantity]').forEach((amount) => {
        const value = Number(amount.dataset.quantity);
        if (Number.isFinite(value)) amount.textContent = value.toLocaleString('en-NZ', { maximumFractionDigits: 4 }) + ' ' + amount.dataset.unit;
      });
    });
    const set = (selector, text) => { const target = root.querySelector(selector); if (target) target.textContent = text; };
    set('[data-figure="overdue"]', String(overdue));
    set('[data-figure="week"]', String(week));
    set('[data-figure-note="overdue"]', overdue ? 'past their due date' : 'nothing is late');
    const overdueTile = root.querySelector('[data-figure-tile="overdue"]');
    if (overdueTile) overdueTile.dataset.state = overdue ? 'overdue' : 'clear';
    const open = Number(root.querySelector('[data-figure="open"]')?.textContent || 0);
    // CONCEPT ONLY: Styles 2 and 3 lead with a sentence in place of the figures card.
    const brief = root.querySelector('[data-contracts-brief]');
    function renderBrief(style) {
      if (!brief) return;
      brief.hidden = style === '1';
      brief.textContent = open ? plural(open, 'open order', 'open orders') + ': ' + (overdue ? overdue + ' overdue, ' : '') + week + ' due this week.' : 'No open contract orders.';
    }

    function toggle(id, show) {
      const target = root.querySelector('#' + id);
      if (!target) return;
      const opening = show === undefined ? target.hidden : show;
      target.hidden = !opening;
      root.querySelectorAll('[aria-controls="' + id + '"]').forEach((button) => button.setAttribute('aria-expanded', String(opening)));
      if (opening) target.querySelector('input, select')?.focus();
      else root.querySelector('[aria-controls="' + id + '"]')?.focus();
    }
    // CONCEPT ONLY — preview switch and the tab pair Style 2 uses.
    function selectTab(name) {
      root.dataset.contractsTab = name;
      root.querySelectorAll('button[data-contracts-tab]').forEach((tab) => tab.setAttribute('aria-selected', String(tab.dataset.contractsTab === name)));
    }
    function setStyle(value) {
      const style = ['1', '2', '3'].includes(value) ? value : '1';
      root.dataset.contractsStyle = style;
      try { sessionStorage.setItem('contracts-design-style', style); } catch (_) { /* Storage is optional. */ }
      root.querySelectorAll('[data-style-pick]').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.stylePick === style)));
      renderBrief(style);
    }
    function onClick(event) {
      const toggleButton = event.target.closest('[data-toggle-form]');
      if (toggleButton) { toggle(toggleButton.dataset.toggleForm); return; }
      const tab = event.target.closest('button[data-contracts-tab]');
      if (tab) { selectTab(tab.dataset.contractsTab); return; }
      const pick = event.target.closest('[data-style-pick]');
      if (pick) setStyle(pick.dataset.stylePick);
    }
    root.addEventListener('click', onClick);
    selectTab('orders');
    let remembered;
    try { remembered = sessionStorage.getItem('contracts-design-style'); } catch (_) { /* Defaults work without storage. */ }
    setStyle(new URLSearchParams(window.location.search).get('style') || remembered || '1');
    return () => root.removeEventListener('click', onClick);
  }
  if (window.bize && window.bize.onPage) window.bize.onPage('[data-contracts-root]', init);
})();
