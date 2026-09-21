/* Suppliers on the Core inventory tab: add, view, edit, delete, and pull in the suppliers
   already named on inventory items. One delegated listener, so it survives HTMX navigation. */
(function () {
  'use strict';
  if (window.__core2SuppliersBound) return;
  window.__core2SuppliersBound = true;

  var FIELDS = [
    { key: 'name', label: 'Supplier name', required: true, max: 255 },
    { key: 'contact_name', label: 'Contact', max: 255 },
    { key: 'phone', label: 'Phone', type: 'tel', max: 50 },
    { key: 'email', label: 'Email', type: 'email', max: 255 },
    { key: 'address', label: 'Address', textarea: true, max: 2000 },
    { key: 'notes', label: 'Notes', textarea: true, max: 4000 },
  ];

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function button(label, className, onClick) {
    var node = el('button', 'btn ' + className, label);
    node.type = 'button';
    node.addEventListener('click', onClick);
    return node;
  }
  function api(path, options) { return window.CoreAPI.request('/suppliers' + path, options || {}); }
  function dialog() { return document.querySelector('[data-core2-suppliers-dialog]'); }

  function open(title, body) {
    var box = dialog();
    if (!box) return null;
    box.replaceChildren();
    var header = el('div', 'core2-suppliers-dialog__header');
    var heading = el('h2', 'spa-form-section-title', title);
    heading.id = 'core2-suppliers-dialog-title';
    header.appendChild(heading);
    header.appendChild(button('Close', 'btn-secondary', function () { box.close(); }));
    box.append(header, body);
    if (!box.open) box.showModal();
    return box;
  }

  function status(message, isError) {
    var node = el('p', 'core2-suppliers-dialog__status' + (isError ? ' core2-suppliers-dialog__status--error' : ''), message || '');
    node.setAttribute('role', isError ? 'alert' : 'status');
    node.hidden = !message;
    return node;
  }

  async function showList(message, isError) {
    var body = el('div', 'core2-suppliers-dialog__body');
    var suppliers = [];
    try {
      suppliers = (await api('')).suppliers || [];
    } catch (err) {
      message = err.message;
      isError = true;
    }
    var actions = el('div', 'core2-suppliers-dialog__actions');
    actions.appendChild(button('Add new supplier', 'btn-primary', function () { showForm(null); }));
    actions.appendChild(button('Import from inventory', 'btn-secondary', importFromInventory));
    body.append(actions, status(message, isError));

    if (!suppliers.length) {
      body.appendChild(el('p', '', 'No suppliers yet. Add one, or import the suppliers already named on your inventory items.'));
    } else {
      var table = el('table', 'core2-suppliers-table');
      var head = table.createTHead().insertRow();
      ['Supplier', 'Contact', 'Phone', 'Email', 'Address', 'Notes', ''].forEach(function (label) {
        head.appendChild(el('th', '', label));
      });
      var rows = table.createTBody();
      suppliers.forEach(function (supplier) {
        var row = rows.insertRow();
        ['name', 'contact_name', 'phone', 'email', 'address', 'notes'].forEach(function (key) {
          row.insertCell().textContent = supplier[key] || '—';
        });
        var cell = row.insertCell();
        cell.className = 'core2-suppliers-table__actions';
        cell.appendChild(button('Edit', 'btn-secondary', function () { showForm(supplier); }));
        cell.appendChild(button('Delete', 'btn-secondary', function () { remove(supplier); }));
      });
      var scroller = el('div', 'core2-suppliers-table-wrap');
      scroller.appendChild(table);
      body.appendChild(scroller);
    }
    open('Suppliers', body);
  }

  function showForm(supplier) {
    var editing = !!supplier;
    var form = el('form', 'core2-suppliers-dialog__body core2-suppliers-form');
    var inputs = {};
    FIELDS.forEach(function (field) {
      var label = el('label', 'core2-suppliers-form__field');
      label.appendChild(el('span', '', field.label + (field.required ? ' *' : '')));
      var input = document.createElement(field.textarea ? 'textarea' : 'input');
      if (field.textarea) input.rows = 3; else input.type = field.type || 'text';
      input.maxLength = field.max;
      input.required = !!field.required;
      input.value = (supplier && supplier[field.key]) || '';
      label.appendChild(input);
      form.appendChild(label);
      inputs[field.key] = input;
    });
    var message = status('');
    form.appendChild(message);
    var actions = el('div', 'core2-suppliers-dialog__actions');
    var save = el('button', 'btn btn-primary', editing ? 'Save changes' : 'Add supplier');
    save.type = 'submit';
    actions.append(save, button('Back to suppliers', 'btn-secondary', function () { showList(); }));
    form.appendChild(actions);
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      var payload = {};
      FIELDS.forEach(function (field) { payload[field.key] = inputs[field.key].value; });
      save.disabled = true;
      try {
        await api(editing ? '/' + encodeURIComponent(supplier.id) : '', {
          method: editing ? 'PUT' : 'POST',
          body: payload,
        });
        await showList((editing ? 'Saved ' : 'Added ') + payload.name.trim() + '.');
      } catch (err) {
        message.textContent = err.message;
        message.className = 'core2-suppliers-dialog__status core2-suppliers-dialog__status--error';
        message.hidden = false;
        save.disabled = false;
      }
    });
    open(editing ? 'Edit supplier' : 'Add new supplier', form);
    inputs.name.focus();
  }

  async function remove(supplier) {
    if (!window.confirm('Delete ' + supplier.name + '? This is recorded in the audit log.')) return;
    try {
      await api('/' + encodeURIComponent(supplier.id), { method: 'DELETE' });
      await showList('Deleted ' + supplier.name + '.');
    } catch (err) {
      await showList(err.message, true);
    }
  }

  async function importFromInventory() {
    try {
      var result = await api('/import-from-inventory', { method: 'POST', body: {} });
      var created = result.created || [];
      await showList(created.length
        ? 'Added ' + created.length + ' from inventory: ' + created.join(', ') + '.'
        : 'Every supplier named on your inventory is already here.');
    } catch (err) {
      await showList(err.message, true);
    }
  }

  document.addEventListener('click', function (event) {
    if (!(event.target instanceof Element)) return;
    if (event.target.closest('[data-supplier-add]')) showForm(null);
    else if (event.target.closest('[data-supplier-view]')) showList();
  });
})();
