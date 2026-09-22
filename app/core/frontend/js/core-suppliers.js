/* Supplier add/edit form, shared by the Core inventory tab and the Suppliers page.
   It opens as a bottom sheet with the same chrome as the other Core sheets (system status, lots),
   and exposes window.CoreSuppliers.openForm(supplier | null, onSaved).
   The sheet is built on demand and attached to <body>, so it works on any page, is never left
   behind by an HTMX navigation, and needs no markup in the templates. */
(function () {
  'use strict';

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

  // The sheet is found in the DOM, not held in a variable: this script re-runs on every boosted
  // swap, but its document-level listeners are bound once, so they must not depend on one run's state.
  function closeSheet() {
    var open = document.querySelector('[data-supplier-sheet]');
    if (!open) return;
    var opener = open.__opener;
    open.remove();
    document.body.classList.remove('core2-sheet-open');
    if (opener && document.contains(opener)) opener.focus();
  }

  function openForm(supplier, onSaved) {
    closeSheet();
    var editing = !!supplier;

    var overlay = el('div', 'core2-health-sheet-overlay');
    overlay.setAttribute('data-supplier-sheet', '');
    overlay.__opener = document.activeElement;
    overlay.addEventListener('click', function (event) { if (event.target === overlay) closeSheet(); });
    var sheet = el('div', 'core2-health-sheet');
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-modal', 'true');
    sheet.setAttribute('aria-labelledby', 'core2-supplier-sheet-title');

    var header = el('div', 'core2-health-sheet__header');
    var title = el('h3', 'core2-health-sheet__title', editing ? 'Edit supplier' : 'Add new supplier');
    title.id = 'core2-supplier-sheet-title';
    var close = el('button', 'core2-health-sheet__close', '×');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close supplier form');
    close.addEventListener('click', closeSheet);
    header.append(title, close);

    var form = el('form', 'core2-suppliers-form');
    var body = el('div', 'core2-health-sheet__body');
    var inputs = {};
    FIELDS.forEach(function (field) {
      var label = el('label', 'core2-suppliers-form__field');
      label.appendChild(el('span', '', field.label + (field.required ? ' *' : '')));
      var input = document.createElement(field.textarea ? 'textarea' : 'input');
      if (field.textarea) input.rows = 3; else input.type = field.type || 'text';
      input.className = 'spa-inp';
      input.maxLength = field.max;
      input.required = !!field.required;
      input.value = (supplier && supplier[field.key]) || '';
      label.appendChild(input);
      body.appendChild(label);
      inputs[field.key] = input;
    });
    var message = el('p', 'core2-suppliers-form__error');
    message.setAttribute('role', 'alert');
    message.hidden = true;
    body.appendChild(message);

    var footer = el('div', 'core2-health-sheet__footer');
    var cancel = el('button', 'btn btn-secondary', 'Cancel');
    cancel.type = 'button';
    cancel.addEventListener('click', closeSheet);
    var save = el('button', 'btn btn-primary', editing ? 'Save changes' : 'Add supplier');
    save.type = 'submit';
    footer.append(cancel, save);
    form.append(body, footer);

    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      var payload = {};
      FIELDS.forEach(function (field) { payload[field.key] = inputs[field.key].value; });
      save.disabled = true;
      try {
        var result = await window.CoreAPI.request('/suppliers' + (editing ? '/' + encodeURIComponent(supplier.id) : ''), {
          method: editing ? 'PUT' : 'POST',
          body: payload,
        });
        closeSheet();
        if (onSaved) onSaved(result.supplier, editing);
      } catch (err) {
        message.textContent = err.message;
        message.hidden = false;
        save.disabled = false;
      }
    });

    sheet.append(header, form);
    overlay.appendChild(sheet);
    document.body.appendChild(overlay);
    document.body.classList.add('core2-sheet-open');
    inputs.name.focus();
  }

  window.CoreSuppliers = { openForm: openForm };

  // Bound once for the life of the tab; script re-execution after a boosted swap must not stack listeners.
  if (window.__core2SuppliersBound) return;
  window.__core2SuppliersBound = true;
  document.addEventListener('keydown', function (event) { if (event.key === 'Escape') closeSheet(); });
  document.addEventListener('htmx:beforeRequest', closeSheet);  // never leave a sheet behind on navigation
  // The inventory tab's "Add new supplier" card; the Suppliers page wires its own button.
  document.addEventListener('click', function (event) {
    if (!(event.target instanceof Element)) return;
    var add = event.target.closest('[data-supplier-add]');
    if (!add || document.querySelector('[data-suppliers-page]')) return;
    openForm(null, function (supplier) {
      var status = document.querySelector('[data-suppliers-hub-status]');
      if (!status) return;
      status.replaceChildren(document.createTextNode('Added ' + supplier.name + '. '));
      var link = document.createElement('a');
      link.href = '/core/suppliers';
      link.textContent = 'View suppliers';
      status.appendChild(link);
      status.hidden = false;
    });
  });
})();
