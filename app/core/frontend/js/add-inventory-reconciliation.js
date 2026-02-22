/**
 * Add-to-Inventory reconciliation (Path A): optional "Map to Untracked Item" in core2 add-inventory modal.
 * New code only; does not modify existing addInventoryItem logic. Listens for submit and handles
 * reconciliation when user selected an untracked mapping.
 */
(function () {
  'use strict';

  var cachedUntracked = [];
  var addModal = null;
  var form = null;
  var mapWrapper = null;
  var mapSelect = null;
  var untrackedHint = null;
  var nameInput = null;
  var unitSelect = null;

  function escapeHtml(text) {
    if (text == null) return '';
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function getFormData(formEl) {
    var fd = new FormData(formEl);
    var name = (fd.get('name') || '').trim();
    var quantity = parseFloat(fd.get('quantity'));
    var unit = fd.get('unit') || '';
    var inventoryType = fd.get('inventoryType') || 'raw_material';
    var mapId = (fd.get('mapToUntrackedItemId') || '').trim();
    return {
      name: name,
      quantity: quantity,
      unit: unit,
      inventory_type: inventoryType,
      untracked_item_id: mapId || undefined,
      purchase_date: fd.get('purchaseDate') || undefined,
      supplier: fd.get('supplier') || undefined,
      supplier_batch_number: fd.get('batchNumber') || undefined,
      expiry_date: fd.get('expiryDate') || undefined,
    };
  }

  function filterMatching(name, unit) {
    var n = (name || '').trim().toLowerCase();
    var u = (unit || '').trim();
    if (!n || !u) return [];
    return cachedUntracked.filter(function (item) {
      var qty = parseFloat(item.quantity);
      if (isNaN(qty) || qty <= 0) return false;
      return (item.name || '').trim().toLowerCase() === n && (item.unit || '').trim() === u;
    });
  }

  function updateMapDropdown() {
    if (!mapWrapper || !mapSelect || !nameInput || !unitSelect) return;
    var name = nameInput.value;
    var unit = unitSelect.value;
    var matching = filterMatching(name, unit);
    if (matching.length === 0) {
      mapWrapper.style.display = 'none';
      mapSelect.innerHTML = '<option value="">— No mapping —</option>';
      if (untrackedHint) untrackedHint.textContent = '';
      return;
    }
    mapWrapper.style.display = 'block';
    mapSelect.innerHTML = '<option value="">— No mapping —</option>';
    matching.forEach(function (item) {
      var opt = document.createElement('option');
      opt.value = item.id;
      opt.textContent = item.name + ' — ' + item.quantity + ' ' + (item.unit || '') + ' (untracked)';
      mapSelect.appendChild(opt);
    });
    if (untrackedHint) {
      untrackedHint.textContent = 'Mapping will reduce untracked balance and add this quantity to live inventory.';
    }
  }

  function loadUntrackedOnModalOpen() {
    var btn = document.querySelector('[data-modal-open="add-inventory-modal"]');
    if (!btn) return;
    btn.addEventListener('click', function () {
      if (typeof window.CoreAPI !== 'undefined' && window.CoreAPI.getUntrackedItems) {
        window.CoreAPI.getUntrackedItems()
          .then(function (res) {
            cachedUntracked = (res && res.untracked_items) ? res.untracked_items : [];
          })
          .catch(function () { cachedUntracked = []; });
      }
    });
  }

  function setupSubmitInterceptor() {
    if (!form) return;
    form.addEventListener('submit', function (e) {
      var mapId = (form.querySelector('[name="mapToUntrackedItemId"]') || {}).value;
      if (!mapId || !window.CoreAPI || !window.CoreAPI.reconcileViaAddition) return;
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      var data = getFormData(form);
      if (!data.name || data.quantity == null || isNaN(data.quantity) || !data.unit) {
        if (typeof window.showNotification === 'function') {
          window.showNotification('error', 'Validation Error', 'Please enter name, quantity, and unit.');
        }
        return false;
      }
      var payload = {
        name: data.name,
        quantity: data.quantity,
        unit: data.unit,
        inventory_type: data.inventory_type,
        untracked_item_id: mapId,
        purchase_date: data.purchase_date || null,
        supplier: data.supplier || null,
        supplier_batch_number: data.supplier_batch_number || null,
        expiry_date: data.expiry_date || null,
      };
      window.CoreAPI.reconcileViaAddition(payload)
        .then(function (result) {
          var modal = document.getElementById('add-inventory-modal');
          if (modal) {
            modal.style.display = 'none';
            document.body.style.overflow = 'auto';
          }
          form.reset();
          if (typeof window.loadInventoryV2 === 'function') window.loadInventoryV2();
          if (typeof window.updateMetricsV2 === 'function' && window.CoreAPI.getMetrics) {
            window.CoreAPI.getMetrics().then(window.updateMetricsV2);
          }
          var msg = 'Inventory added.';
          if (result.reconciled_amount && parseFloat(result.reconciled_amount) > 0) {
            msg = 'Inventory added and ' + result.reconciled_amount + ' ' + (result.unit || '') + ' reconciled from untracked.';
          }
          if (typeof window.showNotification === 'function') {
            window.showNotification('success', 'Inventory Item Added', msg);
          }
        })
        .catch(function (err) {
          var message = (err && err.message) ? err.message : 'Failed to add inventory.';
          if (typeof window.showNotification === 'function') {
            window.showNotification('error', 'Failed to Add', message);
          }
        });
      return false;
    }, true);
  }

  function init() {
    addModal = document.getElementById('add-inventory-modal');
    form = document.querySelector('#add-inventory-modal form');
    mapWrapper = document.getElementById('add-inventory-map-untracked-wrapper');
    mapSelect = document.getElementById('add-inventory-map-untracked-select');
    untrackedHint = document.getElementById('add-inventory-untracked-hint');
    nameInput = form && form.querySelector('[name="name"]');
    unitSelect = form && form.querySelector('[name="unit"]');

    if (nameInput) nameInput.addEventListener('input', updateMapDropdown);
    if (nameInput) nameInput.addEventListener('change', updateMapDropdown);
    if (unitSelect) unitSelect.addEventListener('change', updateMapDropdown);

    loadUntrackedOnModalOpen();
    setupSubmitInterceptor();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
