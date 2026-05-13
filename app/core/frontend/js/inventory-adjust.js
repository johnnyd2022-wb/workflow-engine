/**
 * Inventory item edit bottom sheet.
 * Backdrop and panel are direct <body> children (position:fixed).
 * Open/close = add/remove class on <body>. No display:none toggling.
 */
(function () {
  if (window._invAdjLoaded) return;
  window._invAdjLoaded = true;

  var panel    = null;
  var backdrop = null;
  var activeItemId = null;

  function getCsrf() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute('content') : '';
  }

  function ensureElements() {
    if (panel) return;

    backdrop = document.createElement('div');
    backdrop.className = 'inv-edit-backdrop';
    document.body.appendChild(backdrop);

    panel = document.createElement('div');
    panel.className = 'inv-edit-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-labelledby', 'inv-edit-title');
    panel.innerHTML =
      '<div class="inv-edit-handle" aria-hidden="true"></div>' +
      '<div class="inv-edit-header">' +
        '<span class="inv-edit-title" id="inv-edit-title">Edit item</span>' +
      '</div>' +
      '<form class="inv-edit-form" id="inv-edit-form" novalidate>' +
        '<div class="inv-edit-field">' +
          '<label class="inv-edit-label" for="inv-e-name">Name</label>' +
          '<input type="text" id="inv-e-name" class="inv-edit-input" required>' +
        '</div>' +
        '<div class="inv-edit-field">' +
          '<label class="inv-edit-label" for="inv-e-type">Type</label>' +
          '<select id="inv-e-type" class="inv-edit-input">' +
            '<option value="raw_material">Raw material</option>' +
            '<option value="work_in_progress">Intermediate (WIP)</option>' +
            '<option value="final_product">Final product</option>' +
          '</select>' +
        '</div>' +
        '<div class="inv-edit-row">' +
          '<div class="inv-edit-field">' +
            '<label class="inv-edit-label" for="inv-e-qty">Quantity</label>' +
            '<input type="number" id="inv-e-qty" class="inv-edit-input" step="any" min="0">' +
          '</div>' +
          '<div class="inv-edit-field">' +
            '<label class="inv-edit-label" for="inv-e-unit">Unit</label>' +
            '<input type="text" id="inv-e-unit" class="inv-edit-input">' +
          '</div>' +
        '</div>' +
        '<div class="inv-edit-field">' +
          '<label class="inv-edit-label" for="inv-e-supplier">Supplier</label>' +
          '<input type="text" id="inv-e-supplier" class="inv-edit-input">' +
        '</div>' +
        '<div class="inv-edit-field">' +
          '<label class="inv-edit-label" for="inv-e-batch">Batch number</label>' +
          '<input type="text" id="inv-e-batch" class="inv-edit-input">' +
        '</div>' +
        '<div class="inv-edit-row">' +
          '<div class="inv-edit-field">' +
            '<label class="inv-edit-label" for="inv-e-purchase">Purchase date</label>' +
            '<input type="date" id="inv-e-purchase" class="inv-edit-input">' +
          '</div>' +
          '<div class="inv-edit-field">' +
            '<label class="inv-edit-label" for="inv-e-expiry">Expiry date</label>' +
            '<input type="date" id="inv-e-expiry" class="inv-edit-input">' +
          '</div>' +
        '</div>' +
        '<div class="inv-edit-field">' +
          '<label class="inv-edit-label" for="inv-e-barcode">Barcode</label>' +
          '<input type="text" id="inv-e-barcode" class="inv-edit-input">' +
        '</div>' +
        '<p class="inv-edit-msg" id="inv-edit-msg" role="alert"></p>' +
        '<div class="inv-edit-actions">' +
          '<button type="button" class="inv-edit-cancel">Cancel</button>' +
          '<button type="submit" class="inv-edit-save">Save changes</button>' +
        '</div>' +
      '</form>';
    document.body.appendChild(panel);

    panel.querySelector('.inv-edit-cancel').addEventListener('click', closeSheet);
    panel.querySelector('#inv-edit-form').addEventListener('submit', function (e) {
      e.preventDefault();
      saveEdit();
    });

    /* On mobile, keep the panel above the bottom nav bar */
    window.addEventListener('resize', adjustBottom);
  }

  function adjustBottom() {
    if (!panel) return;
    var sidebar = document.getElementById('sidebar');
    var navH = 0;
    if (sidebar) {
      var r = sidebar.getBoundingClientRect();
      if (r.top > window.innerHeight / 2) navH = Math.round(window.innerHeight - r.top);
    }
    panel.style.bottom = navH ? navH + 'px' : '';
  }

  function openSheet(btn) {
    ensureElements();
    activeItemId = btn.dataset.itemId;

    panel.querySelector('#inv-e-name').value     = btn.dataset.name     || '';
    panel.querySelector('#inv-e-type').value     = btn.dataset.type     || 'raw_material';
    panel.querySelector('#inv-e-qty').value      = btn.dataset.current  || '';
    panel.querySelector('#inv-e-unit').value     = btn.dataset.unit     || '';
    panel.querySelector('#inv-e-supplier').value = btn.dataset.supplier || '';
    panel.querySelector('#inv-e-batch').value    = btn.dataset.batch    || '';
    panel.querySelector('#inv-e-purchase').value = btn.dataset.purchase || '';
    panel.querySelector('#inv-e-expiry').value   = btn.dataset.expiry   || '';
    panel.querySelector('#inv-e-barcode').value  = btn.dataset.barcode  || '';
    panel.querySelector('#inv-edit-msg').textContent = '';

    var saveBtn = panel.querySelector('.inv-edit-save');
    saveBtn.disabled = false;
    saveBtn.textContent = 'Save changes';

    adjustBottom();
    document.body.classList.add('inv-edit-open');
    panel.querySelector('#inv-e-name').focus();
  }

  function closeSheet() {
    document.body.classList.remove('inv-edit-open');
    activeItemId = null;
  }

  function saveEdit() {
    if (!activeItemId) return;
    var msgEl   = panel.querySelector('#inv-edit-msg');
    var saveBtn = panel.querySelector('.inv-edit-save');

    var name = panel.querySelector('#inv-e-name').value.trim();
    var unit = panel.querySelector('#inv-e-unit').value.trim();
    var qty  = panel.querySelector('#inv-e-qty').value.trim();

    if (!name) { msgEl.textContent = 'Name is required.'; return; }
    if (!unit) { msgEl.textContent = 'Unit is required.'; return; }
    if (qty === '' || isNaN(parseFloat(qty))) { msgEl.textContent = 'A valid quantity is required.'; return; }

    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';
    msgEl.textContent = '';

    var body = {
      name:                  name,
      inventory_type:        panel.querySelector('#inv-e-type').value,
      quantity:              qty,
      unit:                  unit,
      supplier:              panel.querySelector('#inv-e-supplier').value.trim() || null,
      supplier_batch_number: panel.querySelector('#inv-e-batch').value.trim()    || null,
      purchase_date:         panel.querySelector('#inv-e-purchase').value         || null,
      expiry_date:           panel.querySelector('#inv-e-expiry').value           || null,
      barcode:               panel.querySelector('#inv-e-barcode').value.trim()   || null,
    };

    var savedId = activeItemId;
    fetch('/api/core/inventory/' + encodeURIComponent(savedId), {
      method: 'PUT',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrf(),
        'X-CSRF-Token': getCsrf(),
      },
      body: JSON.stringify(body),
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok) {
          msgEl.textContent = res.data.error || 'Save failed.';
          saveBtn.disabled = false;
          saveBtn.textContent = 'Save changes';
          return;
        }
        closeSheet();
        if (typeof window.invAdjustOnSave === 'function') window.invAdjustOnSave(savedId);
      })
      .catch(function () {
        msgEl.textContent = 'Network error — try again.';
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save changes';
      });
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.inv-adj-btn');
    if (btn) openSheet(btn);
  });
})();
