/* The Suppliers page: who you buy from, what you buy from them, and how to reach them.
   Reads the supplier list and compact inventory list for the register and its detail drawer. */
(function () {
  'use strict';

  var root = document.querySelector('[data-suppliers-page]');
  if (!root) return;

  var $ = function (selector) { return root.querySelector(selector); };
  var figures = $('[data-suppliers-figures]');
  var chips = $('[data-suppliers-chips]');
  var list = $('[data-suppliers-table]');
  var count = $('[data-suppliers-count]');
  var heading = $('[data-suppliers-heading]');
  var search = $('[data-suppliers-search]');
  var message = $('[data-suppliers-message]');
  var drawer = $('[data-supplier-drawer]');
  var drawerBody = $('[data-supplier-drawer-body]');

  var suppliers = [];
  var unlisted = [];  // names on inventory lines with no supplier record: [{name, lines}]
  var stockKnown = false;
  var loaded = false;
  var failed = false;
  var activeFilter = 'all';
  var query = '';
  var selectedId = null;
  var drawerOpener = null;
  var savedId = null;  // the supplier just saved: its details say so

  var FILTERS = {
    all: { chip: 'All', title: 'Suppliers', test: function () { return true; } },
    buying: { chip: 'Buying from now', title: 'Buying from now', test: function (s) { return s.lots > 0; } },
    incomplete: { chip: 'Need details', title: 'Need details', test: function (s) { return s.missing.length > 0; } },
  };
  var FIELD_WORDS = { phone: 'phone', email: 'email', address: 'address' };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function button(className, text) {
    var node = el('button', className, text);
    node.type = 'button';
    return node;
  }
  function plural(n, word, many) { return n + ' ' + (n === 1 ? word : (many || word + 's')); }
  function joinWords(words) {
    if (words.length < 2) return words.join('');
    return words.slice(0, -1).join(', ') + ' or ' + words[words.length - 1];
  }
  function key(name) { return String(name || '').trim().toLowerCase(); }
  function say(text, isError) {
    message.textContent = text || '';
    message.className = 'sup-message' + (isError ? ' sup-message--error' : ' sup-message--ok');
    message.hidden = !text;
  }

  // ── Data ────────────────────────────────────────────────────────────────────────────────
  function enrich(rawSuppliers, items) {
    var bySupplier = {};
    (items || []).forEach(function (item) {
      var k = key(item.supplier);
      if (!k) return;
      (bySupplier[k] = bySupplier[k] || []).push(item);
    });
    var listed = {};
    suppliers = rawSuppliers.map(function (raw) {
      var lines = bySupplier[key(raw.name)] || [];
      listed[key(raw.name)] = true;
      var names = [];
      lines.forEach(function (line) { if (names.indexOf(line.name) === -1) names.push(line.name); });
      return Object.assign({}, raw, {
        lines: lines,
        products: names.sort(function (a, b) { return a.localeCompare(b); }),
        lots: lines.filter(function (line) { return Number(line.quantity) > 0; }).length,
        missing: ['phone', 'email', 'address'].filter(function (field) { return !raw[field]; }),
      });
    });
    unlisted = Object.keys(bySupplier).filter(function (k) { return !listed[k]; }).map(function (k) {
      return { name: String(bySupplier[k][0].supplier).trim(), lines: bySupplier[k].length };
    }).sort(function (a, b) { return a.name.localeCompare(b.name); });
  }

  function missingText(supplier) {
    var m = supplier.missing;
    if (!m.length) return '';
    if (m.length === 3) return 'No contact details';
    return 'No ' + joinWords(m.map(function (f) { return FIELD_WORDS[f]; }));
  }
  function buysText(supplier, max) {
    if (!supplier.products.length) return stockKnown ? 'Nothing bought yet' : '';
    var shown = supplier.products.slice(0, supplier.products.length === max + 1 ? max + 1 : max);
    var more = supplier.products.length - shown.length;
    return shown.join(', ') + (more > 0 ? ' and ' + more + ' more' : '');
  }
  function lotsText(supplier) {
    if (!supplier.lines.length) return '';
    return supplier.lots ? plural(supplier.lots, 'lot') + ' in stock' : 'None in stock';
  }
  function matches(supplier) {
    if (!FILTERS[activeFilter].test(supplier)) return false;
    if (!query) return true;
    var haystack = ['name', 'contact_name', 'phone', 'email', 'address', 'notes'].map(function (k) { return supplier[k] || ''; })
      .concat(supplier.products).join(' ').toLowerCase();
    return haystack.indexOf(query) !== -1;
  }

  // ── Small pieces ────────────────────────────────────────────────────────────────────────
  function tag(text, kind) { return el('span', 'sup-tag' + (kind ? ' sup-tag--' + kind : ''), text); }
  function contactLink(kind, value, className, label) {
    var a = el('a', className || 'sup-link', label || value);
    var at = value.indexOf('@');
    if (!label && kind === 'email' && at > 0) {
      // Let a long address break after the @, never mid-word.
      a.replaceChildren(document.createTextNode(value.slice(0, at)), document.createElement('wbr'), document.createTextNode(value.slice(at)));
    }
    a.href = (kind === 'phone' ? 'tel:' + value.replace(/[^\d+]/g, '') : 'mailto:' + value);
    return a;
  }
  function openButton(supplier, className) {
    var b = button('sup-open ' + (className || ''), supplier.name);
    b.setAttribute('data-supplier-open', supplier.id);
    b.addEventListener('click', function () { showDetail(supplier.id, b); });
    return b;
  }

  // ── At a glance ─────────────────────────────────────────────────────────────────────────
  function renderGlance() {
    figures.replaceChildren();
    if (!loaded) {
      if (failed) {
        figures.appendChild(el('p', 'sup-none sup-glance-note', 'The figures appear once suppliers load.'));
      }
      return;
    }
    var buying = suppliers.filter(FILTERS.buying.test).length;
    var incomplete = suppliers.filter(FILTERS.incomplete.test).length;
    var tiles = [
      { filter: 'all', value: suppliers.length, label: 'Suppliers', note: 'in your list' },
      { filter: 'buying', value: buying, label: 'Buying from now', note: stockKnown ? 'with stock in hand' : 'stock not loaded' },
      { filter: 'incomplete', value: incomplete, label: 'Need details', note: 'missing a phone, email or address', state: incomplete ? 'warn' : '' },
      {
        importer: true, value: unlisted.length, label: 'On stock, not listed',
        note: unlisted.length ? unlisted.map(function (u) { return u.name; }).join(', ') : 'every name is listed',
        state: unlisted.length ? 'warn' : '',
      },
    ];
    tiles.forEach(function (tile) {
      var node = button('sup-figure' + (tile.filter === activeFilter && activeFilter !== 'all' ? ' is-active' : ''));
      if (tile.state) node.setAttribute('data-state', tile.state);
      node.appendChild(el('span', 'sup-figure__label', tile.label));
      node.appendChild(el('strong', 'sup-figure__value', String(tile.value)));
      node.appendChild(el('span', 'sup-figure__note', tile.note));
      if (tile.importer) {
        node.disabled = !unlisted.length;
        node.setAttribute('aria-label', unlisted.length ? 'Import ' + plural(unlisted.length, 'supplier') + ' named on your stock' : 'Every supplier on your stock is listed');
        node.addEventListener('click', importFromInventory);
      } else {
        node.setAttribute('data-suppliers-filter', tile.filter);
        node.setAttribute('aria-pressed', String(tile.filter === activeFilter));
        node.addEventListener('click', function () { setFilter(tile.filter); });
      }
      figures.appendChild(node);
    });

  }

  function renderChips() {
    chips.replaceChildren();
    Object.keys(FILTERS).forEach(function (k) {
      var n = loaded ? suppliers.filter(FILTERS[k].test).length : 0;
      var chip = button('sup-chip', FILTERS[k].chip + (loaded ? ' ' + n : ''));
      chip.setAttribute('data-suppliers-filter', k);
      chip.setAttribute('aria-pressed', String(activeFilter === k));
      chip.addEventListener('click', function () { setFilter(k); });
      chips.appendChild(chip);
    });
  }

  // ── Supplier register ──────────────────────────────────────────────────────────────────
  function renderList() {
    list.replaceChildren();
    if (failed) {
      count.textContent = '';
      var box = el('div', 'sup-empty');
      box.appendChild(el('p', '', 'Suppliers could not be loaded.'));
      var retry = button('workspace-button', 'Try again');
      retry.addEventListener('click', function () { load(); });
      box.appendChild(retry);
      list.appendChild(box);
      return;
    }
    if (!loaded) { list.appendChild(el('p', 'sup-empty', 'Loading suppliers…')); return; }
    var visible = suppliers.filter(matches);
    heading.textContent = query ? 'Search results' : FILTERS[activeFilter].title;
    count.textContent = visible.length + ' of ' + plural(suppliers.length, 'supplier');
    if (!visible.length) {
      var empty = el('div', 'sup-empty');
      if (!suppliers.length) {
        empty.appendChild(el('p', '', 'No suppliers yet. Add one, or import the suppliers already named on your inventory.'));
      } else {
        empty.appendChild(el('p', '', 'No suppliers match this search or view.'));
        var clear = button('workspace-button', 'Clear search and filters');
        clear.addEventListener('click', function () { search.value = ''; query = ''; setFilter('all'); });
        empty.appendChild(clear);
      }
      list.appendChild(empty);
      return;
    }
    renderTable(visible);
  }

  function renderTable(visible) {
    var table = el('table', 'sup-table');
    var head = table.createTHead().insertRow();
    ['Supplier', 'What you buy', 'Phone', 'Email', ''].forEach(function (label, i) {
      var th = el('th', '', label);
      if (i === 4) th.appendChild(el('span', 'sup-visually-hidden', 'Details to add'));
      head.appendChild(th);
    });
    var body = table.createTBody();
    visible.forEach(function (supplier) {
      var row = body.insertRow();
      row.className = 'sup-table__row';
      var name = row.insertCell();
      name.className = 'sup-col--name';
      name.appendChild(openButton(supplier));
      if (supplier.contact_name) name.appendChild(el('span', 'sup-sub', supplier.contact_name));
      var buys = row.insertCell();
      buys.className = 'sup-col--buys';
      buys.appendChild(el('span', '', buysText(supplier, 3)));
      if (lotsText(supplier)) buys.appendChild(el('span', 'sup-sub', lotsText(supplier)));
      ['phone', 'email'].forEach(function (field) {
        var cell = row.insertCell();
        cell.className = 'sup-col--' + field;
        if (supplier[field]) cell.appendChild(contactLink(field, supplier[field]));
        else { cell.appendChild(el('span', 'sup-none', '—')); cell.className += ' sup-col--empty'; }
      });
      var status = row.insertCell();
      status.className = 'sup-col--status';
      if (supplier.missing.length) status.appendChild(tag(missingText(supplier), 'warn'));
      row.addEventListener('click', function (event) {
        if (event.target.closest('a, button')) return;
        showDetail(supplier.id, row.querySelector('[data-supplier-open]'));
      });
    });
    list.appendChild(table);
  }

  // ── Supplier detail drawer ─────────────────────────────────────────────────────────────
  function detailFor(supplier) {
    var wrap = el('div', 'sup-detail');
    var head = el('div', 'sup-detail__head');
    var titles = el('div');
    titles.appendChild(el('h2', 'sup-detail__title', supplier.name));
    if (supplier.contact_name) titles.appendChild(el('p', 'sup-sub', supplier.contact_name));
    head.appendChild(titles);
    if (supplier.id === savedId) {
      var saved = el('p', 'sup-detail__saved', 'Saved');
      saved.setAttribute('role', 'status');
      titles.appendChild(saved);
    }
    var close = button('sup-detail__close', '×');
    close.setAttribute('aria-label', 'Close supplier details');
    close.setAttribute('data-supplier-drawer-close', '');
    head.appendChild(close);
    wrap.appendChild(head);

    if (supplier.phone || supplier.email) {
      var reach = el('div', 'sup-detail__reach');
      if (supplier.phone) reach.appendChild(contactLink('phone', supplier.phone, 'workspace-button', 'Call'));
      if (supplier.email) reach.appendChild(contactLink('email', supplier.email, 'workspace-button', 'Email'));
      wrap.appendChild(reach);
    }

    var facts = el('dl', 'sup-facts');
    [['Contact', 'contact_name'], ['Phone', 'phone'], ['Email', 'email'], ['Address', 'address'], ['Notes', 'notes']].forEach(function (pair) {
      var row = el('div', 'sup-facts__row');
      row.appendChild(el('dt', '', pair[0]));
      var dd = el('dd');
      var value = supplier[pair[1]];
      if (!value) dd.appendChild(el('span', 'sup-none', 'Not recorded'));
      else if (pair[1] === 'phone' || pair[1] === 'email') dd.appendChild(contactLink(pair[1], value));
      else dd.textContent = value;
      row.appendChild(dd);
      facts.appendChild(row);
    });
    wrap.appendChild(facts);

    var stock = el('section', 'sup-detail__stock');
    stock.appendChild(el('h3', '', 'What you buy'));
    if (!supplier.lines.length) {
      stock.appendChild(el('p', 'sup-none', stockKnown ? 'No inventory lines name this supplier yet.' : 'Stock could not be loaded.'));
    } else {
      var lines = supplier.lines.slice().sort(function (a, b) {
        return (Number(b.quantity) > 0) - (Number(a.quantity) > 0) || a.name.localeCompare(b.name);
      });
      var ul = el('ul', 'sup-lots');
      lines.forEach(function (line) {
        var li = el('li', 'sup-lots__item');
        var main = el('div');
        main.appendChild(el('span', 'sup-lots__name', line.name));
        if (line.supplier_batch_number) main.appendChild(el('span', 'sup-sub', 'Batch ' + line.supplier_batch_number));
        li.appendChild(main);
        li.appendChild(el('span', 'sup-lots__qty', Number(line.quantity) > 0
          ? Number(line.quantity).toLocaleString('en-NZ', { maximumFractionDigits: 2 }) + ' ' + line.unit
          : 'Used up'));
        ul.appendChild(li);
      });
      stock.appendChild(ul);
    }
    wrap.appendChild(stock);

    var foot = el('div', 'sup-detail__foot');
    var editButton = button('workspace-button workspace-button--primary', 'Edit details');
    editButton.setAttribute('data-supplier-edit', supplier.id);
    editButton.addEventListener('click', function () { edit(supplier, editButton); });
    var remove = button('sup-delete', 'Delete supplier');
    remove.setAttribute('aria-label', 'Delete ' + supplier.name);
    remove.addEventListener('click', function () { deleteSupplier(supplier); });
    foot.append(editButton, remove);
    wrap.appendChild(foot);
    return wrap;
  }

  function showDetail(id, opener) {
    if (id !== selectedId) savedId = null;
    selectedId = id;
    var supplier = suppliers.filter(function (s) { return s.id === id; })[0];
    if (!supplier) return;
    drawerOpener = opener || document.activeElement;
    drawerBody.replaceChildren(detailFor(supplier));
    drawer.hidden = false;
    drawerBody.focus();
  }

  function closeDrawer(restoreFocus) {
    if (drawer.hidden) return;
    drawer.hidden = true;
    drawerBody.replaceChildren();
    if (restoreFocus !== false && drawerOpener && document.contains(drawerOpener)) drawerOpener.focus();
  }

  function edit(supplier, opener) {
    closeDrawer(false);
    if (opener && document.contains(opener)) opener.focus();
    window.CoreSuppliers.openForm(supplier, async function (saved) {
      selectedId = saved.id;
      savedId = saved.id;
      await load();
      // Back to the details just changed, so the change is seen where it was made.
      showDetail(saved.id, opener);
    });
  }

  // ── Rendering and actions ───────────────────────────────────────────────────────────────
  function render() {
    renderGlance();
    renderChips();
    renderList();
  }
  function setFilter(next) {
    activeFilter = FILTERS[next] ? next : 'all';
    render();
  }

  async function load(notice, isError) {
    root.setAttribute('aria-busy', 'true');
    try {
      var results = await Promise.all([
        window.CoreAPI.request('/suppliers'),
        // "What you buy" is a nice-to-have: the register still works if stock cannot be read.
        window.CoreAPI.request('/inventory?view=compact').catch(function () { return null; }),
      ]);
      stockKnown = !!results[1];
      enrich(results[0].suppliers || [], results[1] ? results[1].inventory_items : []);
      loaded = true;
      failed = false;
      render();
      say(notice, isError);
    } catch (err) {
      failed = !loaded;
      render();
      say(err.message, true);
    } finally {
      root.setAttribute('aria-busy', 'false');
    }
  }

  async function deleteSupplier(supplier) {
    if (!window.confirm('Delete ' + supplier.name + '? This is recorded in the audit log.')) return;
    try {
      await window.CoreAPI.request('/suppliers/' + encodeURIComponent(supplier.id), { method: 'DELETE' });
      closeDrawer(false);
      if (selectedId === supplier.id) selectedId = null;
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
    renderGlance();
    renderList();
  });
  $('[data-supplier-add]').addEventListener('click', function () {
    window.CoreSuppliers.openForm(null, function (saved) { selectedId = saved.id; load('Added ' + saved.name + '.'); });
  });
  $('[data-suppliers-import]').addEventListener('click', importFromInventory);
  drawer.addEventListener('click', function (event) {
    if (event.target instanceof Element && event.target.closest('[data-supplier-drawer-close]')) closeDrawer();
  });
  // Bound to the page root, not document: a boosted visit re-runs this script on a fresh root.
  root.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !document.querySelector('[data-supplier-sheet]')) closeDrawer();
  });
  render();
  load();
})();
