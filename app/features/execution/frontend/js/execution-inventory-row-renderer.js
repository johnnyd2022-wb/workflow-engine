/**
 * DOM factory for execute-step variable inventory input rows (single row instance).
 * Consumers supply callbacks via api (setRowSelection, setActiveRow, refreshPicker) once defined.
 * Load before execution-render-inputs.js.
 */
(function (root) {
  'use strict';

  var doc = root.document;

  root.ExecutionInventoryRowRenderer = {
    /**
     * @param {object} d
     * @param {boolean} d.isFirst unused (reserved)
     * @param {string} d.safeInputName
     * @param {function(): number} d.bumpRowIndex
     * @param {object} d.ses
     * @param {object} d.input
     * @param {HTMLElement} d.rowsContainer
     * @param {object} d.api setRowSelection, setActiveRow, refreshPicker — assigned by caller when ready
     */
    createInputRow: function (d) {
      var safeInputName = d.safeInputName;
      var ses = d.ses;
      var input = d.input;
      var rowsContainer = d.rowsContainer;
      var api = d.api || {};

      var rowId = 'execute-input-row-' + safeInputName + '-' + d.bumpRowIndex();
      var stateKey = safeInputName + '::' + rowId;
      var row = doc.createElement('div');
      row.className = 'execute-input-row';
      row.id = rowId;
      row.dataset.inputName = input.name;
      row.dataset.stateKey = stateKey;
      row.style.display = 'block';
      row.style.width = '100%';
      row.style.position = 'relative';
      if (!ses.inputStateByKey.has(stateKey)) {
        ses.inputStateByKey.set(stateKey, {
          input_name: input.name,
          inventory_item_id: '',
          quantity: input.quantity != null ? Number(input.quantity) : 0,
          unit: input.unit || '',
          expired_reason: ''
        });
      }
      var hidInv = doc.createElement('input');
      hidInv.type = 'hidden';
      hidInv.className = 'execute-inventory-select';
      hidInv.dataset.inputName = input.name || '';
      hidInv.value = '';
      row.appendChild(hidInv);

      var rmWrap = doc.createElement('div');
      rmWrap.style.cssText = 'display:flex; justify-content:flex-end; margin-bottom: 10px;';
      var rmBtn = doc.createElement('button');
      rmBtn.type = 'button';
      rmBtn.className = 'execute-remove-input-row-btn btn btn-secondary btn-sm';
      rmBtn.style.fontSize = '12px';
      rmBtn.textContent = 'Remove input';
      rmWrap.appendChild(rmBtn);
      row.appendChild(rmWrap);

      var selCard = doc.createElement('div');
      selCard.className = 'execute-selected-inv-card';
      selCard.style.cssText =
        'display:none; padding: 12px 14px; border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md, 10px); background: var(--bg-card, #fff);';
      row.appendChild(selCard);

      var expWarn = doc.createElement('div');
      expWarn.className = 'execute-input-expired-warning';
      expWarn.dataset.inputName = input.name || '';
      expWarn.style.cssText =
        'display: none; margin-top: 8px; padding: 10px 12px; background: hsl(0, 93%, 94%); border: 1px solid var(--error, #ef4444); border-radius: var(--radius-md); color: #b91c1c; font-size: 13px; font-weight: 500;';
      expWarn.setAttribute('role', 'alert');
      row.appendChild(expWarn);

      var rowUnexp = doc.createElement('div');
      rowUnexp.className = 'execute-input-unexpected-row-warning';
      rowUnexp.dataset.inputName = input.name || '';
      rowUnexp.style.cssText =
        'display: none; margin-top: 8px; padding: 10px 12px; background: hsl(210, 90%, 96%); border: 1px solid var(--info, #3b82f6); border-radius: var(--radius-md); color: #1e40af; font-size: 13px; font-weight: 500;';
      rowUnexp.setAttribute('role', 'status');
      row.appendChild(rowUnexp);

      var qtyPane = doc.createElement('div');
      qtyPane.className = 'execute-qty-pane';
      qtyPane.style.cssText = 'display:none; margin-top: 12px;';
      var qtyLbl = doc.createElement('label');
      qtyLbl.className = 'spa-field-label';
      qtyLbl.textContent = 'Quantity to consume';
      qtyPane.appendChild(qtyLbl);
      var qtyRow = doc.createElement('div');
      qtyRow.style.cssText = 'display: flex; align-items: center; gap: 8px;';
      var qtyInput = doc.createElement('input');
      qtyInput.type = 'number';
      qtyInput.className = 'spa-inp execute-quantity-input';
      qtyInput.dataset.inputName = input.name || '';
      qtyInput.dataset.stepUnit = input.unit || '';
      qtyInput.dataset.originalQuantity = input.quantity != null ? String(input.quantity) : '';
      qtyInput.placeholder = String(input.quantity != null ? input.quantity : '0');
      qtyInput.value = input.quantity != null ? String(input.quantity) : '';
      qtyInput.step = '0.01';
      qtyInput.min = '0';
      qtyInput.style.flex = '1';
      qtyRow.appendChild(qtyInput);
      var unitDisp = doc.createElement('span');
      unitDisp.className = 'execute-quantity-unit-display';
      unitDisp.style.cssText =
        'font-size: 14px; color: var(--text-secondary); min-width: 40px; text-align: left;';
      unitDisp.textContent = input.unit || '';
      qtyRow.appendChild(unitDisp);
      qtyPane.appendChild(qtyRow);
      row.appendChild(qtyPane);
      if (qtyInput) {
        qtyInput.style.border = '1px solid var(--border-default, #e5e7eb)';
        qtyInput.addEventListener('input', function () {
          var st = ses.inputStateByKey.get(stateKey);
          if (!st) return;
          var q = parseFloat(qtyInput.value);
          st.quantity = isNaN(q) ? 0 : q;
        });
      }

      var removeBtn = row.querySelector('.execute-remove-input-row-btn');
      if (removeBtn) {
        removeBtn.addEventListener('click', function (e) {
          if (e) {
            e.preventDefault();
            e.stopPropagation();
          }
          row.setAttribute('data-pending-inv-id', '');
          row.setAttribute('data-selection-locked', 'false');
          if (!rowsContainer) return;
          var rowCount = rowsContainer.querySelectorAll('.execute-input-row').length;
          if (rowCount <= 1) {
            if (typeof api.setRowSelection === 'function') api.setRowSelection(row, '');
            if (typeof api.setActiveRow === 'function') api.setActiveRow(row);
          } else {
            var sk = row.dataset.stateKey || '';
            if (sk && ses.inputStateByKey) ses.inputStateByKey.delete(sk);
            row.remove();
            var next = rowsContainer.querySelector('.execute-input-row');
            if (next && typeof api.setActiveRow === 'function') api.setActiveRow(next);
          }
          if (typeof api.refreshPicker === 'function') api.refreshPicker();
        });
      }
      return row;
    }
  };
})(typeof window !== 'undefined' ? window : this);
