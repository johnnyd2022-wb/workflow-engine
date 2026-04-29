/**
 * Add missing inventory, untracked output modal, and refreshExecutionModalInventory.
 * Call ExecutionModalSecondary.install({ config, CoreAPI }) from execution-modal.js.
 */
(function (root) {
  'use strict';

  function install(ctx) {
    var refreshInventoryGeneration = 0;
    var refreshInventoryAbort = null;
    var config = ctx.config || {};
    var CoreAPI = ctx.CoreAPI != null ? ctx.CoreAPI : root.CoreAPI;
    var escapeHtml =
      typeof root.escapeHtml === 'function'
        ? root.escapeHtml
        : function (x) {
            return String(x == null ? '' : x);
          };
    var showNotification = root.showNotification;

  // ============================================================
  // ADD MISSING ITEM (in-flow raw material)
  // ============================================================
  // Opens the page's Add Inventory modal with prefill. Set window.addInventoryContext
  // so the add-inventory submit handler can call refreshExecutionModalInventory(savedItem) on success.
  window.openAddInventoryModalForMissingInput = function(prefill) {
    var addModal = document.getElementById('add-inventory-modal');
    if (!addModal) return;
    var form = addModal.querySelector('form');
    if (form) {
      var nameEl = form.querySelector('[name="name"]');
      var qtyEl = form.querySelector('[name="quantity"]');
      var unitEl = form.querySelector('[name="unit"]');
      if (nameEl) nameEl.value = prefill.name || '';
      if (qtyEl) qtyEl.value = prefill.quantity != null && prefill.quantity !== '' ? prefill.quantity : '';
      if (unitEl) unitEl.value = prefill.unit || 'kg';
    }
    window.addInventoryContext = { fromExecutionModal: true, inputName: prefill.name || '' };
    addModal.style.zIndex = '1001'; // Above execution modal (z-index 1000)
    addModal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  };

  // Open lightweight "Add untracked output" modal (missing output recorded during execution).
  window.openAddUntrackedOutputModal = function(outputDef, executionId, executionStepId) {
    var m = document.getElementById('add-untracked-output-modal');
    if (!m) return;
    var nameEl = document.getElementById('untracked-output-name');
    var qtyEl = document.getElementById('untracked-output-quantity');
    var unitEl = document.getElementById('untracked-output-unit');
    var dateEl = document.getElementById('untracked-output-date');
    if (nameEl) nameEl.value = outputDef.name || '';
    if (qtyEl) qtyEl.value = outputDef.quantity != null && outputDef.quantity !== '' ? outputDef.quantity : '';
    if (unitEl) {
      var allowedUnits = ['kg', 'g', 'L', 'mL', 'pcs', 'units'];
      var u = (outputDef.unit || 'kg').trim();
      unitEl.value = allowedUnits.indexOf(u) !== -1 ? u : 'kg';
    }
    if (dateEl) {
      var today = new Date();
      dateEl.value = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
    }
    var notesEl = document.getElementById('untracked-output-notes');
    if (notesEl) notesEl.value = '';
    window.untrackedOutputContext = {
      executionId: executionId,
      executionStepId: executionStepId,
      outputId: outputDef.id || null
    };
    m.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  };

  // Submit handler for add-untracked-output form (bound when DOM ready so form exists)
  function bindUntrackedOutputForm() {
    var form = document.getElementById('add-untracked-output-form');
    if (!form) return;
    if (form._executionUntrackedFormBound) {
      return;
    }
    form._executionUntrackedFormBound = true;
    form.addEventListener('submit', async function(e) {
      e.preventDefault();
      if (form._untrackedSubmitInFlight) {
        return;
      }
      form._untrackedSubmitInFlight = true;
      try {
      var ctx = window.untrackedOutputContext;
      if (!ctx) return;
      var name = (form.querySelector('[name="name"]') || {}).value;
      var quantity = parseFloat((form.querySelector('[name="quantity"]') || {}).value);
      var unit = (form.querySelector('[name="unit"]') || {}).value;
      var inventoryType = (form.querySelector('[name="inventory_type"]') || {}).value || 'work_in_progress';
      var notesEl = form.querySelector('[name="notes"]');
      var notes = notesEl ? String(notesEl.value || '').trim() : '';
      var dateEl = document.getElementById('untracked-output-date');
      var recordedDate = dateEl ? dateEl.value : null;
      if (!name || !unit || isNaN(quantity) || quantity < 0) {
        if (typeof showNotification === 'function') showNotification('error', 'Validation error', 'Please provide a valid name, unit, and non-negative quantity.');
        return;
      }
      if (!notes) {
        if (typeof showNotification === 'function') showNotification('error', 'Notes required', 'Please provide notes explaining why this item is being added as untracked.');
        return;
      }
      var uuidRe = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
      var metadata = recordedDate ? { recorded_date: recordedDate } : {};
      metadata.notes = notes;
      var payload = {
        name: name,
        quantity: quantity,
        unit: unit,
        inventory_type: inventoryType,
        source_execution_id: ctx.executionId || undefined,
        source_execution_step_id: ctx.executionStepId || undefined,
        untracked: true,
        metadata: metadata
      };
      if (ctx.outputId && uuidRe.test(String(ctx.outputId))) payload.source_output_id = ctx.outputId;
      try {
        var created = await CoreAPI.createInventoryItem(payload);
        var m = document.getElementById('add-untracked-output-modal');
        if (m) { m.style.display = 'none'; document.body.style.overflow = 'auto'; }
        window.untrackedOutputContext = null;
        if (typeof showNotification === 'function') showNotification('success', 'Untracked output added', 'Item has been added to inventory and flagged for reconciliation.');
        if (window.addInventoryContext && window.addInventoryContext.fromExecutionModal && created) {
          await window.refreshExecutionModalInventory(created);
        }
        if (config.onStepCompleted) await config.onStepCompleted();
      } catch (err) {
        console.error('Failed to add untracked output:', err);
        if (typeof showNotification === 'function') showNotification('error', 'Failed to add', err.message || 'Could not add untracked output.');
      }
      } finally {
        form._untrackedSubmitInFlight = false;
      }
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindUntrackedOutputForm);
  } else {
    bindUntrackedOutputForm();
  }

  // Called by core2/flows2 add-inventory success when item was added from execution modal.
  // Refetches inventory and updates execute-step-modal dropdowns; optionally selects the new item.
  // AbortController cancels in-flight fetch; generation token drops stale DOM work after await (belt + suspenders).
  window.refreshExecutionModalInventory = async function(newItem) {
    var gen = ++refreshInventoryGeneration;
    if (refreshInventoryAbort) {
      try {
        refreshInventoryAbort.abort();
      } catch (e) {}
    }
    refreshInventoryAbort = new AbortController();
    var refreshSignal = refreshInventoryAbort.signal;
    var modal = document.getElementById('execute-step-modal');
    if (!modal) return;
    var pageEmbed =
      (modal.dataset && modal.dataset.renderMode === 'page') ||
      (typeof document !== 'undefined' &&
        document.body &&
        document.body.classList &&
        document.body.classList.contains('batch-start-spa'));
    if (!pageEmbed && modal.style.display === 'none') return;
    var ctx = window.addInventoryContext;
    if (!ctx || !ctx.fromExecutionModal) return;

    var inventoryData;
    try {
      inventoryData = await CoreAPI.getInventory(null, null, { signal: refreshSignal });
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      throw e;
    }
    if (gen !== refreshInventoryGeneration) {
      return;
    }
    var allInventory = inventoryData.inventory_items || [];
    var currentExecutionId = modal.dataset.executionId;

    var selects = modal.querySelectorAll('.execute-inventory-select');
    for (var i = 0; i < selects.length; i++) {
      var hiddenInput = selects[i];
      var inputName = hiddenInput.dataset.inputName;
      if (!inputName) continue;
      var section = hiddenInput.closest('.execute-input-section');
      var cardsContainer = section ? section.querySelector('.execute-inventory-picker-cards') : null;
      var triggerLabel = section ? section.querySelector('.execute-inventory-picker-label') : null;
      var currentValue = (hiddenInput.value || '').trim();
      var matching = allInventory.filter(function(inv) {
        return inv.name.toLowerCase().indexOf(inputName.toLowerCase()) !== -1 ||
          inputName.toLowerCase().indexOf(inv.name.toLowerCase()) !== -1;
      });
      matching.sort(function(a, b) {
        var aEid = a.source_execution_id || a.execution_id || null;
        var bEid = b.source_execution_id || b.execution_id || null;
        if (currentExecutionId) {
          var aMatch = aEid && String(aEid) === String(currentExecutionId);
          var bMatch = bEid && String(bEid) === String(currentExecutionId);
          if (aMatch && !bMatch) return -1;
          if (!aMatch && bMatch) return 1;
        }
        return 0;
      });
      if (cardsContainer) {
        cardsContainer.innerHTML = '';
        var noneCard = document.createElement('div');
        noneCard.className = 'execute-inventory-input-card execute-reconcile-untracked-card';
        noneCard.dataset.inventoryId = '';
        noneCard.style.cssText = 'padding: 10px 14px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); cursor: pointer;';
        noneCard.innerHTML = '<span style="color: var(--text-secondary); font-size: 13px;">— None —</span>';
        noneCard.onclick = function() {
          hiddenInput.value = '';
          hiddenInput.dataset.quantity = '';
          hiddenInput.dataset.unit = '';
          if (triggerLabel) triggerLabel.textContent = 'Select inventory item...';
          var q = section.querySelector('.execute-quantity-input');
          var u = section.querySelector('.execute-quantity-unit-display');
          if (q && u) {
            u.textContent = q.dataset.stepUnit || '';
            q.value = q.dataset.originalQuantity || '';
            q.dataset.inventoryUnit = '';
          }
          cardsContainer.querySelectorAll('.execute-inventory-input-card').forEach(function(c) {
            c.classList.remove('execute-reconcile-card-selected');
            c.style.borderColor = '';
            c.style.boxShadow = '';
          });
          noneCard.classList.add('execute-reconcile-card-selected');
          var drop = section.querySelector('.execute-inventory-picker-dropdown');
          if (drop) drop.style.display = 'none';
          var arrow = section.querySelector('.execute-inventory-picker-arrow');
          if (arrow) arrow.style.transform = 'rotate(0deg)';
        };
        cardsContainer.appendChild(noneCard);
        var safeInputName = (inputName || '').replace(/[^a-zA-Z0-9_-]/g, '_');
        matching.forEach(function(inv) {
          var id = String(inv.id);
          var card = document.createElement('div');
          card.className = 'execute-inventory-input-card card card-interactive execute-reconcile-untracked-card';
          card.dataset.inventoryId = id;
          card.style.cssText = 'margin-bottom: 0; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); cursor: pointer; overflow: hidden;';
          var createdStr = inv.created_at ? (function() { try { return new Date(inv.created_at).toLocaleDateString(); } catch (e) { return ''; } })() : '';
          var subtitleParts = [(inv.quantity != null ? inv.quantity : '') + ' ' + (inv.unit || ''), inv.process_name].filter(Boolean);
          var subtitleLine = subtitleParts.map(function(x) { return escapeHtml(x); }).join(' · ');
          var detailsParts = [];
          if (inv.quantity != null) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Quantity</span> ' + escapeHtml(String(inv.quantity)) + ' ' + escapeHtml(inv.unit || '') + '</p>');
          if (inv.process_name) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Process</span> ' + escapeHtml(inv.process_name) + '</p>');
          if (createdStr) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Created</span> ' + escapeHtml(createdStr) + '</p>');
          if (inv.supplier) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Supplier</span> ' + escapeHtml(inv.supplier) + '</p>');
          if (inv.supplier_batch_number) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Batch</span> ' + escapeHtml(inv.supplier_batch_number) + '</p>');
          card.innerHTML = '<div class="process-card-header" style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px;"><div style="flex: 1; min-width: 0;"><h4 style="margin: 0; font-size: 14px; font-weight: 600;">' + escapeHtml(inv.name || '') + '</h4><p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-secondary);">' + subtitleLine + '</p></div></div><div class="execute-reconcile-details" style="padding: 12px 16px; border-top: 1px solid var(--border-default); background: var(--bg-secondary, #f9fafb); font-size: 13px;">' + detailsParts.join('') + '</div>';
          card.onclick = function() {
            hiddenInput.value = id;
            hiddenInput.dataset.quantity = inv.quantity != null ? String(inv.quantity) : '';
            hiddenInput.dataset.unit = inv.unit || '';
            if (triggerLabel) triggerLabel.textContent = (inv.process_name ? escapeHtml(inv.process_name) + ' - ' : '') + escapeHtml(inv.name) + ' - ' + (inv.quantity != null ? inv.quantity : '') + ' ' + (inv.unit || '');
            var q = section.querySelector('.execute-quantity-input');
            var u = section.querySelector('.execute-quantity-unit-display');
            if (q && u) {
              q.value = inv.quantity != null ? inv.quantity : q.value;
              q.dataset.inventoryUnit = inv.unit || '';
              u.textContent = inv.unit || '';
            }
            cardsContainer.querySelectorAll('.execute-inventory-input-card').forEach(function(c) {
              var sel = (c.dataset.inventoryId || '') === id;
              c.classList.toggle('execute-reconcile-card-selected', sel);
              c.style.borderColor = sel ? 'var(--primary, #2563eb)' : '';
              c.style.boxShadow = sel ? '0 0 0 2px rgba(37, 99, 235, 0.25)' : '';
            });
            var drop = section.querySelector('.execute-inventory-picker-dropdown');
            if (drop) drop.style.display = 'none';
            var arrow = section.querySelector('.execute-inventory-picker-arrow');
            if (arrow) arrow.style.transform = 'rotate(0deg)';
          };
          cardsContainer.appendChild(card);
        });
        var selectedId = (newItem && ctx.inputName && inputName === ctx.inputName && newItem.id != null) ? String(newItem.id) : (matching.some(function(inv) { return String(inv.id) === currentValue; }) ? currentValue : '');
        if (!selectedId && noneCard) noneCard.classList.add('execute-reconcile-card-selected');
      }
      var selectedId = (newItem && ctx.inputName && inputName === ctx.inputName && newItem.id != null) ? String(newItem.id) : (matching.some(function(inv) { return String(inv.id) === currentValue; }) ? currentValue : '');
      if (selectedId && matching.some(function(inv) { return String(inv.id) === selectedId; })) {
        var inv = matching.find(function(inv) { return String(inv.id) === selectedId; });
        hiddenInput.value = selectedId;
        hiddenInput.dataset.quantity = inv.quantity != null ? String(inv.quantity) : '';
        hiddenInput.dataset.unit = inv.unit || '';
        if (triggerLabel) triggerLabel.textContent = (inv.process_name ? escapeHtml(inv.process_name) + ' - ' : '') + escapeHtml(inv.name) + ' - ' + (inv.quantity != null ? inv.quantity : '') + ' ' + (inv.unit || '');
        var qtyInput = section ? section.querySelector('.execute-quantity-input') : null;
        var unitDisplay = section ? section.querySelector('.execute-quantity-unit-display') : null;
        if (qtyInput && unitDisplay) {
          qtyInput.value = inv.quantity != null ? inv.quantity : qtyInput.value;
          qtyInput.dataset.inventoryUnit = inv.unit || '';
          unitDisplay.textContent = inv.unit || '';
        }
        var noInvWarning = section ? section.querySelector('.execute-input-no-inventory-warning') : null;
        if (noInvWarning) noInvWarning.style.display = 'none';
        var triggerEl = section ? section.querySelector('.execute-inventory-picker-trigger') : null;
        if (triggerEl) { triggerEl.style.border = ''; triggerEl.style.boxShadow = ''; }
        if (cardsContainer) {
          cardsContainer.querySelectorAll('.execute-inventory-input-card').forEach(function(c) {
            var sel = (c.dataset.inventoryId || '') === selectedId;
            c.classList.toggle('execute-reconcile-card-selected', sel);
            c.style.borderColor = sel ? 'var(--primary, #2563eb)' : '';
            c.style.boxShadow = sel ? '0 0 0 2px rgba(37, 99, 235, 0.25)' : '';
          });
        }
        var drop = section ? section.querySelector('.execute-inventory-picker-dropdown') : null;
        if (drop) drop.style.display = 'none';
        var arr = section ? section.querySelector('.execute-inventory-picker-arrow') : null;
        if (arr) arr.style.transform = 'rotate(0deg)';
        var submitBtn = modal.querySelector('#execute-step-submit-btn');
        if (submitBtn) {
          var allRequired = modal.querySelectorAll('.execute-inventory-select[data-required="true"]');
          var allHave = true;
          allRequired.forEach(function(s) { if (!s.value) allHave = false; });
          if (allHave) {
            submitBtn.disabled = false;
            submitBtn.style.opacity = '1';
            submitBtn.style.cursor = 'pointer';
            submitBtn.title = '';
          }
        }
      }
    }
    window.addInventoryContext = null;
  };
  }

  root.ExecutionModalSecondary = {
    install: install,
  };
})(typeof window !== 'undefined' ? window : this);
