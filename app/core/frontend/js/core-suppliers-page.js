/* The Suppliers page: status cards that filter the register, search, and the table. */
(function () {
  'use strict';

  var root = document.querySelector('[data-suppliers-page]');
  if (!root) return;

  var cards = root.querySelector('[data-suppliers-cards]');
  var tableWrap = root.querySelector('[data-suppliers-table]');
  var count = root.querySelector('[data-suppliers-count]');
  var heading = root.querySelector('[data-suppliers-heading]');
  var search = root.querySelector('[data-suppliers-search]');
  var message = root.querySelector('[data-suppliers-message]');
  var suppliers = [];
  var activeFilter = 'all';
  var query = '';

  var FILTERS = {
    all: { label: 'All suppliers', title: 'Suppliers', test: function () { return true; } },
    complete: { label: 'Complete details', title: 'Complete details', test: isComplete },
    'no-contact': { label: 'No phone or email', title: 'No phone or email', test: function (s) { return !s.phone && !s.email; } },
    'no-address': { label: 'No address', title: 'No address', test: function (s) { return !s.address; } },
  };

  function isComplete(supplier) { return !!(supplier.phone && supplier.email && supplier.address); }
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function say(text, isError) {
    message.textContent = text || '';
    message.className = 'sup-message' + (isError ? ' sup-message--error' : '');
    message.hidden = !text;
  }
  function matches(supplier) {
    if (!FILTERS[activeFilter].test(supplier)) return false;
    if (!query) return true;
    return ['name', 'contact_name', 'phone', 'email', 'address', 'notes'].some(function (key) {
      return String(supplier[key] || '').toLowerCase().indexOf(query) !== -1;
    });
  }

  function renderCards() {
    cards.replaceChildren();
    var styles = { all: '', complete: '', 'no-contact': ' sup-card--overdue', 'no-address': ' sup-card--attention' };
    Object.keys(FILTERS).forEach(function (key) {
      var card = el('button', 'sup-card' + styles[key] + (activeFilter === key ? ' is-active' : ''));
      card.type = 'button';
      card.setAttribute('aria-pressed', activeFilter === key ? 'true' : 'false');
      card.appendChild(el('strong', '', String(suppliers.filter(FILTERS[key].test).length)));
      card.appendChild(el('span', '', FILTERS[key].label));
      card.addEventListener('click', function () {
        activeFilter = key;
        render();
      });
      cards.appendChild(card);
    });
  }

  function renderTable() {
    tableWrap.replaceChildren();
    var visible = suppliers.filter(matches);
    heading.textContent = query ? 'Search results' : FILTERS[activeFilter].title;
    count.textContent = visible.length + ' of ' + suppliers.length + ' supplier' + (suppliers.length === 1 ? '' : 's') +
      (activeFilter === 'all' ? '' : ' matching this view');
    if (!visible.length) {
      tableWrap.appendChild(el('p', 'sup-empty', suppliers.length
        ? 'No suppliers match this search or view.'
        : 'No suppliers yet. Add one, or import the suppliers already named on your inventory items.'));
      return;
    }
    var table = el('table', 'sup-table');
    var head = table.createTHead().insertRow();
    ['Supplier', 'Contact', 'Phone', 'Email', 'Address', 'Notes', ''].forEach(function (label) {
      head.appendChild(el('th', '', label));
    });
    var body = table.createTBody();
    visible.forEach(function (supplier) {
      var row = body.insertRow();
      [['name', 'sup-col--name'], ['contact_name', 'sup-col--contact'], ['phone', 'sup-col--phone'], ['email', 'sup-col--email'],
        ['address', 'sup-col--address'], ['notes', 'sup-col--notes']].forEach(function (column) {
        var cell = row.insertCell();
        cell.textContent = supplier[column[0]] || '—';
        cell.className = column[1] + (supplier[column[0]] ? '' : ' sup-table__empty');
      });
      var actions = row.insertCell().appendChild(el('div', 'sup-table__actions'));
      var edit = el('button', 'sup-btn sup-btn--ghost', 'Edit');
      edit.type = 'button';
      edit.setAttribute('aria-label', 'Edit ' + supplier.name);
      edit.addEventListener('click', function () {
        window.CoreSuppliers.openForm(supplier, function (saved) { load('Saved ' + saved.name + '.'); });
      });
      var remove = el('button', 'sup-btn sup-btn--ghost', 'Delete');
      remove.type = 'button';
      remove.setAttribute('aria-label', 'Delete ' + supplier.name);
      remove.addEventListener('click', function () { deleteSupplier(supplier); });
      actions.append(edit, remove);
    });
    tableWrap.appendChild(table);
  }

  function render() {
    renderCards();
    renderTable();
  }

  async function load(notice, isError) {
    root.setAttribute('aria-busy', 'true');
    try {
      suppliers = (await window.CoreAPI.request('/suppliers')).suppliers || [];
      render();
      say(notice, isError);
    } catch (err) {
      say(err.message, true);
    } finally {
      root.setAttribute('aria-busy', 'false');
    }
  }

  async function deleteSupplier(supplier) {
    if (!window.confirm('Delete ' + supplier.name + '? This is recorded in the audit log.')) return;
    try {
      await window.CoreAPI.request('/suppliers/' + encodeURIComponent(supplier.id), { method: 'DELETE' });
      await load('Deleted ' + supplier.name + '.');
    } catch (err) {
      say(err.message, true);
    }
  }

  async function importFromInventory() {
    try {
      var result = await window.CoreAPI.request('/suppliers/import-from-inventory', { method: 'POST', body: {} });
      var created = result.created || [];
      await load(created.length
        ? 'Added ' + created.length + ' from inventory: ' + created.join(', ') + '.'
        : 'Every supplier named on your inventory is already here.');
    } catch (err) {
      say(err.message, true);
    }
  }

  search.addEventListener('input', function () {
    query = String(search.value || '').trim().toLowerCase();
    renderTable();
  });
  root.querySelector('[data-supplier-add]').addEventListener('click', function () {
    window.CoreSuppliers.openForm(null, function (saved) { load('Added ' + saved.name + '.'); });
  });
  root.querySelector('[data-suppliers-import]').addEventListener('click', importFromInventory);

  load();
})();
