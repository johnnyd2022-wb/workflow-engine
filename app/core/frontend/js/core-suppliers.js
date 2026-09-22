/* Supplier add/edit form, shared by the Core inventory tab and the Suppliers page.
   Exposes window.CoreSuppliers.openForm(supplier | null, onSaved). One delegated listener, so it
   survives HTMX navigation. */
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
  function button(label, className, onClick) {
    var node = el('button', 'btn ' + className, label);
    node.type = 'button';
    node.addEventListener('click', onClick);
    return node;
  }
  function dialog() { return document.querySelector('[data-core2-suppliers-dialog]'); }

  function openForm(supplier, onSaved) {
    var box = dialog();
    if (!box) return;
    var editing = !!supplier;
    box.replaceChildren();
    var header = el('div', 'core2-suppliers-dialog__header');
    var heading = el('h2', 'spa-form-section-title', editing ? 'Edit supplier' : 'Add new supplier');
    heading.id = 'core2-suppliers-dialog-title';
    header.append(heading, button('Close', 'btn-secondary', function () { box.close(); }));

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
    var message = el('p', 'core2-suppliers-dialog__status core2-suppliers-dialog__status--error');
    message.setAttribute('role', 'alert');
    message.hidden = true;
    form.appendChild(message);
    var actions = el('div', 'core2-suppliers-dialog__actions');
    var save = el('button', 'btn btn-primary', editing ? 'Save changes' : 'Add supplier');
    save.type = 'submit';
    actions.append(save, button('Cancel', 'btn-secondary', function () { box.close(); }));
    form.appendChild(actions);
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
        box.close();
        if (onSaved) onSaved(result.supplier, editing);
      } catch (err) {
        message.textContent = err.message;
        message.hidden = false;
        save.disabled = false;
      }
    });
    box.append(header, form);
    if (!box.open) box.showModal();
    inputs.name.focus();
  }

  window.CoreSuppliers = { openForm: openForm };

  // The inventory tab's "Add new supplier" button; the Suppliers page wires its own.
  if (window.__core2SuppliersBound) return;
  window.__core2SuppliersBound = true;
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
