/**
 * Path B: Map to Execution Output — reconcile untracked item by creating an execution
 * record and linking output. New code only. Exposes window.openMapToExecutionReconciliationModal(untrackedItem).
 */
(function () {
  'use strict';

  var modal = null;
  var currentUntracked = null;
  var processesList = [];
  var stepsCache = {};

  function getEl(id) {
    return document.getElementById(id);
  }

  function escapeHtml(text) {
    if (text == null) return '';
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function ensureModal() {
    if (modal) return modal;
    var m = document.getElementById('map-to-execution-reconciliation-modal');
    if (m) {
      modal = m;
      return m;
    }
    m = document.createElement('div');
    m.id = 'map-to-execution-reconciliation-modal';
    m.className = 'modal-overlay';
    m.style.cssText = 'display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); backdrop-filter: blur(8px); z-index: 1001; align-items: center; justify-content: center;';
    m.innerHTML =
      '<div class="card" style="max-width: 500px; width: 90%; padding: 24px;">' +
      '  <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px;">' +
      '    <h2 style="font-size: 20px; font-weight: 600;">Map to Execution Output</h2>' +
      '    <button type="button" class="map-to-exec-close" style="padding: 8px; border: none; background: transparent; cursor: pointer;">✕</button>' +
      '  </div>' +
      '  <p id="map-to-exec-untracked-desc" style="margin-bottom: 16px; color: var(--text-secondary, #6b7280); font-size: 14px;"></p>' +
      '  <form id="map-to-execution-form">' +
      '    <div style="display: flex; flex-direction: column; gap: 16px; margin-bottom: 24px;">' +
      '      <div>' +
      '        <label style="display: block; font-size: 14px; font-weight: 500; margin-bottom: 6px;">Process</label>' +
      '        <select id="map-to-exec-process" required style="width: 100%; padding: 10px 14px; border-radius: 8px; border: 1px solid var(--border-default, #e5e7eb); font-size: 14px;">' +
      '          <option value="">— Select process —</option>' +
      '        </select>' +
      '      </div>' +
      '      <div>' +
      '        <label style="display: block; font-size: 14px; font-weight: 500; margin-bottom: 6px;">Step</label>' +
      '        <select id="map-to-exec-step" required style="width: 100%; padding: 10px 14px; border-radius: 8px; border: 1px solid var(--border-default, #e5e7eb); font-size: 14px;">' +
      '          <option value="">— Select step —</option>' +
      '        </select>' +
      '      </div>' +
      '      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">' +
      '        <div>' +
      '          <label style="display: block; font-size: 14px; font-weight: 500; margin-bottom: 6px;">Quantity produced</label>' +
      '          <input type="number" id="map-to-exec-quantity" required step="0.01" min="0.0001" style="width: 100%; padding: 10px 14px; border-radius: 8px; border: 1px solid var(--border-default, #e5e7eb); font-size: 14px;">' +
      '        </div>' +
      '        <div>' +
      '          <label style="display: block; font-size: 14px; font-weight: 500; margin-bottom: 6px;">Unit</label>' +
      '          <input type="text" id="map-to-exec-unit" readonly style="width: 100%; padding: 10px 14px; border-radius: 8px; border: 1px solid var(--border-default, #e5e7eb); font-size: 14px; background: #f3f4f6;">' +
      '        </div>' +
      '      </div>' +
      '      <div>' +
      '        <label style="display: block; font-size: 14px; font-weight: 500; margin-bottom: 6px;">Date (optional)</label>' +
      '        <input type="date" id="map-to-exec-date" style="width: 100%; padding: 10px 14px; border-radius: 8px; border: 1px solid var(--border-default, #e5e7eb); font-size: 14px;">' +
      '      </div>' +
      '    </div>' +
      '    <div style="display: flex; gap: 12px; justify-content: flex-end;">' +
      '      <button type="button" class="btn btn-secondary map-to-exec-close">Cancel</button>' +
      '      <button type="submit" class="btn btn-primary">Map to Execution Output</button>' +
      '    </div>' +
      '  </form>' +
      '</div>';
    document.body.appendChild(m);

    m.querySelector('.map-to-exec-close').addEventListener('click', function () {
      m.style.display = 'none';
      document.body.style.overflow = 'auto';
      currentUntracked = null;
    });
    m.querySelectorAll('.map-to-exec-close').forEach(function (btn) {
      if (btn.tagName === 'BUTTON') btn.addEventListener('click', function () {
        m.style.display = 'none';
        document.body.style.overflow = 'auto';
        currentUntracked = null;
      });
    });

    getEl('map-to-exec-process').addEventListener('change', function () {
      var pid = this.value;
      loadSteps(pid);
    });

    m.querySelector('#map-to-execution-form').addEventListener('submit', function (e) {
      e.preventDefault();
      if (!currentUntracked || !window.CoreAPI || !window.CoreAPI.reconcileViaExecution) return;
      var processId = getEl('map-to-exec-process').value;
      var stepId = getEl('map-to-exec-step').value;
      var quantity = getEl('map-to-exec-quantity').value;
      var unit = (getEl('map-to-exec-unit').value || currentUntracked.unit || '').trim();
      if (!processId || !stepId || !quantity) {
        if (typeof window.showNotification === 'function') {
          window.showNotification('error', 'Validation', 'Please select process, step, and enter quantity.');
        }
        return false;
      }
      var payload = {
        untracked_item_id: currentUntracked.id,
        process_id: processId,
        step_id: stepId,
        output_name: currentUntracked.name || '',
        output_quantity: quantity,
        output_unit: unit,
        output_date: getEl('map-to-exec-date').value || null,
      };
      window.CoreAPI.reconcileViaExecution(payload)
        .then(function (result) {
          m.style.display = 'none';
          document.body.style.overflow = 'auto';
          currentUntracked = null;
          if (typeof window.showNotification === 'function') {
            var msg = 'Mapped to execution. Reconciled: ' + (result.reconciled_amount || '') + (result.surplus && parseFloat(result.surplus) > 0 ? '; surplus to live: ' + result.surplus : '') + '.';
            window.showNotification('success', 'Reconciled', msg);
          }
          if (typeof window.renderProcessFlowcharts === 'function' && window.checkNeededData !== undefined) {
            window.CoreAPI.getUntrackedItems().then(function (r) {
              if (window.checkNeededData) window.checkNeededData.untracked_items = (r && r.untracked_items) ? r.untracked_items : [];
              window.renderProcessFlowcharts(window.allProcesses || []);
            });
          }
        })
        .catch(function (err) {
          var message = (err && err.message) ? err.message : 'Failed to reconcile.';
          if (typeof window.showNotification === 'function') {
            window.showNotification('error', 'Reconciliation failed', message);
          }
        });
      return false;
    });

    modal = m;
    return m;
  }

  function loadProcesses() {
    if (!window.CoreAPI || !window.CoreAPI.getProcesses) return Promise.resolve([]);
    return window.CoreAPI.getProcesses().then(function (res) {
      processesList = (res && res.processes) ? res.processes : [];
      return processesList;
    });
  }

  function loadSteps(processId) {
    var stepSel = getEl('map-to-exec-step');
    if (!stepSel) return;
    stepSel.innerHTML = '<option value="">— Select step —</option>';
    if (!processId || !window.CoreAPI || !window.CoreAPI.getProcess) return;
    if (stepsCache[processId]) {
      stepsCache[processId].forEach(function (s) {
        var opt = document.createElement('option');
        opt.value = s.id;
        opt.textContent = (s.name || s.step_number || 'Step') + (s.step_number != null ? ' (#' + s.step_number + ')' : '');
        stepSel.appendChild(opt);
      });
      return;
    }
    window.CoreAPI.getProcess(processId).then(function (process) {
      var steps = (process && process.steps) ? process.steps : [];
      stepsCache[processId] = steps;
      steps.forEach(function (s) {
        var opt = document.createElement('option');
        opt.value = s.id;
        opt.textContent = (s.name || s.step_number || 'Step') + (s.step_number != null ? ' (#' + s.step_number + ')' : '');
        stepSel.appendChild(opt);
      });
    }).catch(function () {
      stepSel.innerHTML = '<option value="">— Select step —</option>';
    });
  }

  document.body.addEventListener('click', function (e) {
    var start = e.target && e.target.nodeType === 1 ? e.target : (e.target && e.target.parentElement);
    var btn = start && start.closest ? start.closest('.map-to-execution-reconcile-btn') : null;
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();
    var raw = btn.getAttribute('data-untracked-item');
    if (raw) {
      try {
        var textarea = document.createElement('textarea');
        textarea.innerHTML = raw;
        var decoded = textarea.value;
        var item = JSON.parse(decoded);
        window.openMapToExecutionReconciliationModal(item);
      } catch (err) {
        console.warn('Map to Execution: failed to parse data', err);
      }
    }
  }, true);

  window.openMapToExecutionReconciliationModal = function (untrackedItem) {
    if (!untrackedItem || !untrackedItem.id) return;
    currentUntracked = untrackedItem;
    var m = ensureModal();
    var desc = getEl('map-to-exec-untracked-desc');
    if (desc) {
      var _name = escapeHtml(untrackedItem.name || '');
      var _qty = escapeHtml(String(untrackedItem.quantity || ''));
      var _unit = escapeHtml(untrackedItem.unit || '');
      desc.textContent = 'Reconcile untracked item "' + _name + '" (' + _qty + ' ' + _unit + ') by mapping it to an execution output.';
    }
    getEl('map-to-exec-process').innerHTML = '<option value="">— Select process —</option>';
    getEl('map-to-exec-step').innerHTML = '<option value="">— Select step —</option>';
    getEl('map-to-exec-quantity').value = untrackedItem.quantity != null ? String(untrackedItem.quantity) : '';
    getEl('map-to-exec-unit').value = (untrackedItem.unit || '').trim();
    getEl('map-to-exec-date').value = '';
    loadProcesses().then(function () {
      processesList.forEach(function (p) {
        var opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.name || p.id || '—';
        getEl('map-to-exec-process').appendChild(opt);
      });
    });
    m.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  };
})();
