/**
 * Variable output quantity + untracked reconciliation UI for execute-step.
 * Depends on CoreAPI.getMatchingUntracked, escapeHtml, window render helpers for expiry/ready date.
 * Load before execution-modal.js — exposes window.ExecutionRenderOutputs.
 */
(function (root) {
  'use strict';

  /** Tracks containers that already have the delegated reconcile click handler (avoids DOM property mutation). */
  var reconcileCardsDelegationBound =
    typeof WeakSet !== 'undefined' ? new WeakSet() : null;
  var reconcileCardsDelegationFallback = [];

  /**
   * Collapsible details for untracked reconciliation cards — aligns with inventory picker (audit, notes).
   */
  function buildUntrackedReconcileExpandHtml(u, escapeHtml, prettyLabel, orgUsersMap) {
    var pl = typeof prettyLabel === 'function' ? prettyLabel : function(s) {
      return String(s == null ? '' : s).replace(/_/g, ' ');
    };
    var extra = (u && u.extra_data && typeof u.extra_data === 'object') ? u.extra_data : {};
    function section(title, innerHtml) {
      if (!innerHtml || !String(innerHtml).trim()) return '';
      return (
        '<div style="margin-top: 12px;">' +
          '<div style="font-size: 12px; font-weight: 700; color: var(--text-secondary,#6b7280); letter-spacing:0.03em; text-transform: uppercase; margin-bottom: 8px;">' +
            escapeHtml(title) +
          '</div>' +
          innerHtml +
        '</div>'
      );
    }
    var parts = [];
    var rem = u.remaining_balance_to_reconcile;
    var unreconciledQty = (rem != null && String(rem).trim() !== '') ? String(rem).trim() : null;
    var createdStr = '';
    if (u.created_at) {
      try { createdStr = new Date(u.created_at).toLocaleString(); } catch (e) { createdStr = String(u.created_at); }
    }
    var summaryRows = '';
    function kv(label, val) {
      if (val == null || String(val).trim() === '') return;
      summaryRows +=
        '<div class="exec-picker-kv__k">' + escapeHtml(label) + '</div>' +
        '<div class="exec-picker-kv__v">' + escapeHtml(String(val)) + '</div>';
    }
    if (unreconciledQty !== null) kv('Unreconciled quantity', unreconciledQty + ' ' + (u.unit || ''));
    if (u.process_name) kv('Process', u.process_name);
    if (u.producing_step_name) kv('Step to execute to reconcile', u.producing_step_name);
    else if (u.step_name) kv('Source step', u.step_name);
    if (u.source_step_completed_by) kv('Step completed by', u.source_step_completed_by);
    if (createdStr) kv('Created', createdStr);
    if (summaryRows) parts.push(section('Summary', '<div class="exec-picker-kv">' + summaryRows + '</div>'));

    var invRows = '';
    function kv2(label, val) {
      if (val == null || String(val).trim() === '') return;
      invRows +=
        '<div class="exec-picker-kv__k">' + escapeHtml(label) + '</div>' +
        '<div class="exec-picker-kv__v">' + escapeHtml(String(val)) + '</div>';
    }
    if (u.inventory_type) kv2('Inventory type', pl(String(u.inventory_type).replace(/_/g, ' ')));
    if (u.quantity != null && String(u.quantity).trim() !== '') kv2('Quantity on hand', String(u.quantity) + ' ' + (u.unit || ''));
    if (u.purchase_date) kv2('Purchase date', String(u.purchase_date));
    if (u.expiry_date) kv2('Expiry date', String(u.expiry_date));
    if (u.supplier) kv2('Supplier', u.supplier);
    if (u.supplier_batch_number) kv2('Supplier batch', u.supplier_batch_number);
    if (u.barcode) kv2('Barcode', u.barcode);
    if (u.source_execution_id) kv2('Source execution', u.source_execution_id);
    if (u.source_execution_step_id) kv2('Source execution step', u.source_execution_step_id);
    if (invRows) parts.push(section('Inventory', '<div class="exec-picker-kv">' + invRows + '</div>'));

    var noteStr = (extra.notes != null && String(extra.notes).trim()) ? String(extra.notes) : (u.notes != null ? String(u.notes) : '');
    if (noteStr.trim()) {
      parts.push(section('Notes', '<div style="font-size: 13px; color: var(--text-primary,#111827); line-height: 1.5; white-space: pre-line;">' + escapeHtml(noteStr) + '</div>'));
    }

    var prompts = u.source_step_execution_prompts;
    if (prompts && typeof prompts === 'object') {
      var entries = Object.keys(prompts).map(function(k) { return [k, prompts[k]]; }).filter(function(e) {
        return e[1] != null && String(e[1]).trim() !== '';
      });
      if (entries.length) {
        var ul = '<ul style="margin: 0; padding-left: 18px;">' +
          entries.map(function(e, idx) {
            return '<li style="margin: 0 0 6px 0; font-size: 13px;">' +
              '<span style="font-weight:600;">Prompt ' + (idx + 1) + '</span>' +
              ' <span style="color: var(--text-secondary,#6b7280);">(' + escapeHtml(pl(e[0])) + ')</span>: ' +
              '<span style="font-weight:400;">' + escapeHtml(String(e[1])) + '</span></li>';
          }).join('') +
        '</ul>';
        parts.push(section('Step prompts', ul));
      }
    }

    var rh = extra.reconciliation_history;
    if (Array.isArray(rh) && rh.length) {
      var rhBlocks = rh.slice().reverse().map(function(h) {
        if (!h || typeof h !== 'object') return '';
        var lines = '';
        function hkv(k, v) {
          if (v == null || v === '') return;
          lines += '<div class="exec-picker-kv__k">' + escapeHtml(pl(k)) + '</div><div class="exec-picker-kv__v">' + escapeHtml(String(v)) + '</div>';
        }
        hkv('timestamp', h.timestamp || h.ts || '');
        hkv('method', h.method != null ? pl(String(h.method)) : '');
        hkv('quantity_reconciled', h.quantity_reconciled);
        hkv('surplus_to_live', h.surplus_to_live);
        hkv('user_email', h.user_email);
        if (h.reconciliation_via_execution === true) hkv('via_execution', 'yes');
        if (!lines) {
          try { lines = '<div class="exec-picker-kv__k"></div><div class="exec-picker-kv__v">' + escapeHtml(JSON.stringify(h)) + '</div>'; } catch (e2) {}
        }
        return '<div class="exec-picker-kv" style="margin-bottom: 10px;">' + lines + '</div>';
      }).join('');
      parts.push(section('Reconciliation history', rhBlocks));
    }

    var auditInner = '';
    try {
      var hist = extra.inventory_audit_history ? extra.inventory_audit_history : [];
      if (Array.isArray(hist) && hist.length) {
        var rows = hist.slice().reverse().map(function(h) {
          var when = h.timestamp_utc || h.timestamp || h.created_at || '';
          var src = h.source_method || h.source || '';
          var opEmail = (h.operator_email || h.email || '').trim();
          var rawName = (h.operator_name || '').trim();
          var opId = h.user_id || h.operator_id || h.user || '';
          var opLabel = rawName;
          if (opEmail && rawName === opEmail) {
            opLabel = '';
          }
          if (!opLabel && opId && orgUsersMap && typeof orgUsersMap.get === 'function') {
            opLabel = (orgUsersMap.get(String(opId)) || '').trim();
          }
          if (!opLabel && !opEmail && opId) {
            opLabel = String(opId);
          }
          try {
            var uuidLike = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
            if (opLabel && uuidLike.test(String(opLabel).trim())) opLabel = '';
          } catch (eU) {}
          if (!opLabel) {
            opLabel = opEmail ? '—' : 'Unknown operator';
          }
          var action = h.action || h.event || '';
          if (!action) action = 'inventory change';
          return (
            '<div class="exec-picker-kv__k">' + escapeHtml(pl('action')) + '</div><div class="exec-picker-kv__v">' + escapeHtml(pl(action)) + '</div>' +
            '<div class="exec-picker-kv__k">' + escapeHtml(pl('timestamp_utc')) + '</div><div class="exec-picker-kv__v">' + escapeHtml(String(when || '—')) + '</div>' +
            '<div class="exec-picker-kv__k">' + escapeHtml(pl('operator')) + '</div><div class="exec-picker-kv__v">' + escapeHtml(String(opLabel)) + '</div>' +
            '<div class="exec-picker-kv__k">' + escapeHtml('Operator email') + '</div><div class="exec-picker-kv__v">' + escapeHtml(opEmail || '—') + '</div>' +
            '<div class="exec-picker-kv__k">' + escapeHtml(pl('source_method')) + '</div><div class="exec-picker-kv__v">' + escapeHtml(pl(src) || '—') + '</div>'
          );
        }).join('');
        auditInner = '<div class="exec-picker-kv">' + rows + '</div>';
      }
    } catch (eA) {}
    if (auditInner) parts.push(section('Audit history', auditInner));

    if (!parts.length) {
      return '<p style="margin:0; font-size:13px; color: var(--text-secondary);">No additional metadata.</p>';
    }
    return parts.join('');
  }

  async function renderVariableOutputs(ctx) {
    var modal = ctx.modal;
    var outputsContainer = ctx.outputsContainer;
    var stepDefinition = ctx.stepDefinition;
    var untrackedItems = ctx.untrackedItems;
    var escapeHtml = ctx.escapeHtml;
    var prettyLabel = ctx.prettyLabel;
    var orgUsersMap = ctx.orgUsersMap;
    var signal = ctx.signal;
    var CoreAPI = root.CoreAPI;
    // Render variable outputs (confirmation/override)
    const variableOutputs = (stepDefinition.outputs || []).filter(output =>
      output.requires_execution_confirmation !== false && output.is_variable !== false
    );
    const outputNameNorm = function(n) { return (n || '').trim().toLowerCase(); };
    const unitNorm = function(u) { return (u || '').trim(); };

    // Fetch matching untracked per output from backend (includes qty>0 and qty 0 consumed in this execution).
    // Do not pass process_id so untracked items without source_execution (e.g. manually added) are included.
    let matchingUntrackedPerOutput = [];
    var matchingUntrackedFetchFailed = false;
    const currentExecutionId = modal.dataset.executionId;
    if (CoreAPI && variableOutputs.length > 0 && currentExecutionId && typeof CoreAPI.getMatchingUntracked === 'function') {
      try {
        const results = await Promise.all(
          variableOutputs.map(function(o) {
            var name = (o.name && String(o.name).trim()) || '';
            var unit = (o.unit && String(o.unit).trim()) || 'units';
            return CoreAPI.getMatchingUntracked(name, unit, null, currentExecutionId, { signal: signal });
          })
        );
        matchingUntrackedPerOutput = results.map(function(r) { return (r && r.matching_untracked) ? r.matching_untracked : []; });
      } catch (e) {
        if (e && e.name === 'AbortError') throw e;
        matchingUntrackedFetchFailed = true;
        console.warn('Could not fetch matching untracked per output', e);
      }
    }

    if (variableOutputs.length > 0 && outputsContainer) {
      if (matchingUntrackedFetchFailed) {
        var fetchWarn = document.createElement('div');
        fetchWarn.setAttribute('role', 'alert');
        fetchWarn.style.cssText =
          'margin-bottom: 12px; padding: 10px 14px; background: hsl(38, 92%, 95%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); font-size: 13px; color: #92400e;';
        fetchWarn.textContent =
          'Could not load the latest untracked inventory matches. Using the list from this page if available.';
        outputsContainer.appendChild(fetchWarn);
      }
      variableOutputs.forEach((output, index) => {
        const outputSection = document.createElement('div');
        outputSection.className = 'execute-output-section';
        outputSection.style.cssText = 'margin-bottom: 20px; padding: 16px; border: 1px solid var(--border-light); border-radius: var(--radius-md);';
        const outputId = (output.id != null && String(output.id).trim() !== '') ? String(output.id) : (output.name ? 'out-' + (output.name || '').replace(/\s+/g, '-') : 'out-unknown');
        const outName = output.name || '';
        const outUnit = output.unit || 'units';
        // Match = backend semantics: name case-insensitive (ilike), unit exact after trim. Use API result when available.
        const matchingFromApi = matchingUntrackedPerOutput[index];
        const matchingUntracked = (matchingFromApi != null && Array.isArray(matchingFromApi))
          ? matchingFromApi
          : (untrackedItems || []).filter(function(u) {
              if (!u || !u.id) return false;
              if (outputNameNorm(u.name) !== outputNameNorm(outName)) return false;
              if (unitNorm(u.unit) !== unitNorm(outUnit)) return false;
              var q = parseFloat(u.quantity);
              return !isNaN(q) && q >= 0;
            });
        var defaultId = matchingUntracked.length === 1 ? String(matchingUntracked[0].id) : '';
        var hasMatch = matchingUntracked.length > 0;
        var promptsContainer = modal ? modal.querySelector('#execute-prompts-container') : null;
        var ce = (output.extra_data || {}).custom_expiry;
        var rd = (output.extra_data || {}).ready_date;
        var customExpiryHtml = '';
        var expiryInputHtml = '';
        var readyDateHtml = '';
        if (ce && ce.enabled) {
          var mode = (ce.mode || '').trim();
          if (mode !== 'fixed_duration' && mode !== 'set_at_execution') mode = '';
          if (mode === 'fixed_duration') {
            var v = (ce.duration_value != null) ? ce.duration_value : ce.expiry_days;
            var u = (ce.duration_unit || 'days');
            var msg = 'Output must be consumed in ' + String(v != null ? v : 'X') + ' ' + String(u) + '.';
            customExpiryHtml = '<div class="execute-output-expiry-warning" style="margin-bottom: 12px; padding: 10px 14px; background: hsl(38, 92%, 95%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); font-size: 13px; color: #92400e;"><strong>⚠️ Custom expiry rule applies:</strong> ' + escapeHtml(msg) + '</div>';
          } else if (mode === 'set_at_execution') {
            expiryInputHtml = (typeof window.renderExecutionExpiryUI === 'function')
              ? window.renderExecutionExpiryUI(output, escapeHtml)
              : '';
          }
        }
        if (rd && rd.enabled) {
          var rdMode = (rd.mode || '').trim();
          if (rdMode === 'fixed_duration' && rd.duration_value != null && rd.duration_unit) {
            var v = rd.duration_value;
            var u = rd.duration_unit;
            var msg = 'Status: Not ready. This output cannot be consumed for ' + String(v) + ' ' + String(u) + ' after step completion.';
            readyDateHtml = '<div class="execute-output-ready-date-warning" style="margin-bottom: 12px; padding: 10px 14px; background: hsl(38, 92%, 95%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); font-size: 13px; color: #92400e;"><strong>&#x26A0;&#xFE0F; Ready date:</strong> ' + escapeHtml(msg) + '</div>';
          } else if (rdMode === 'set_at_execution') {
            readyDateHtml = (typeof window.renderExecutionReadyDateUI === 'function')
              ? window.renderExecutionReadyDateUI(output, escapeHtml)
              : '';
          } else if (rd.date) {
            var readyDate = new Date(rd.date);
            if (!isNaN(readyDate.getTime()) && readyDate > new Date()) {
              var readyFrom = readyDate.toLocaleDateString(undefined, { dateStyle: 'long' });
              var rdMsg = (rd.prompt && rd.prompt.trim()) ? escapeHtml(rd.prompt.trim()) : ('Ready from: ' + readyFrom + '. Status: Not ready.');
              readyDateHtml = '<div class="execute-output-ready-date-warning" style="margin-bottom: 12px; padding: 10px 14px; background: hsl(38, 92%, 95%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); font-size: 13px; color: #92400e;"><strong>&#x26A0;&#xFE0F; Ready date:</strong> ' + rdMsg + '</div>';
            }
          }
        }
        var expiryReadyValidationErrorHtml = (expiryInputHtml && readyDateHtml) ? ('<div class="execute-output-expiry-ready-validation-error" data-output-id="' + escapeHtml(outputId) + '" style="display: none; margin-top: 8px; padding: 10px 12px; background: hsl(0, 93%, 94%); border: 1px solid var(--error, #ef4444); border-radius: var(--radius-md); color: #b91c1c; font-size: 13px; font-weight: 500;" role="alert" aria-live="polite"></div>') : '';
        outputSection.innerHTML = `
          ${customExpiryHtml}
          ${readyDateHtml}
          ${expiryInputHtml}
          ${expiryReadyValidationErrorHtml}
          <div style="margin-bottom: 12px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">
              ${escapeHtml(output.name)}
              <span style="color: var(--text-secondary); font-weight: normal;">(Expected: ${output.quantity || '0'} ${output.unit || ''})</span>
            </label>
            <input type="number" class="spa-inp execute-output-quantity-input" data-output-id="${escapeHtml(outputId)}" placeholder="${output.quantity || '0'}" value="${output.quantity || ''}" step="0.01" min="0">
            <p style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">Actual produced quantity (override if different from expected)</p>
            <input type="hidden" class="execute-reconcile-untracked-value" data-output-id="${escapeHtml(outputId)}" value="${escapeHtml(defaultId)}">
          </div>
        `;
        outputsContainer.appendChild(outputSection);

        // Reconciliation UI belongs in Compliance and traceability section (not Outputs).
        if (hasMatch && promptsContainer) {
          var recon = document.createElement('div');
          recon.className = 'execute-reconcile-untracked-wrapper';
          recon.setAttribute('data-output-id', String(outputId));
          recon.style.cssText = 'margin-top: 12px; padding: 14px 16px; background: hsl(42, 93%, 96%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); font-size: 13px;';
          recon.innerHTML =
            '<label style="display:block; font-weight: 700; color: #92400e; margin-bottom: 6px;">Reconciliation</label>' +
            '<p style="margin: 0 0 12px 0; color: #92400e; font-size: 12px; line-height: 1.45;">This step produces an output that is currently untracked in your inventory. Choose an item to reconcile when you record this step.</p>' +
            '<div class="execute-reconcile-untracked-cards" style="display:flex; flex-direction:column; gap: 10px;"></div>';
          promptsContainer.appendChild(recon);

          var cardsContainer = recon.querySelector('.execute-reconcile-untracked-cards');
          var hiddenInput = outputSection.querySelector('.execute-reconcile-untracked-value');

          if (!cardsContainer || !hiddenInput) {
            console.warn('execute reconcile UI: missing cards container or hidden input');
          } else {
          function setLocked(locked) {
            recon.dataset.reconcileLocked = locked ? '1' : '0';
          }

          function applyVisibility(cards) {
            var locked = recon.dataset.reconcileLocked === '1';
            var selectedId = (hiddenInput.value || '').trim();
            var list = cards || recon.querySelectorAll('.execute-reconcile-untracked-card');
            list.forEach(function(c) {
              if (!locked) {
                c.style.display = '';
                return;
              }
              var id = c.dataset.untrackedId || '';
              c.style.display = id === selectedId ? '' : 'none';
            });
          }

          function setSelection(selectedId) {
            hiddenInput.value = selectedId || '';
            var cards = recon.querySelectorAll('.execute-reconcile-untracked-card');
            cards.forEach(function(c) {
              var id = c.dataset.untrackedId || '';
              var selected = id === selectedId;
              c.classList.toggle('execute-reconcile-card-selected', selected);
              c.style.borderColor = selected ? 'var(--warning, #f59e0b)' : '';
              c.style.boxShadow = selected ? '0 0 0 2px rgba(245, 158, 11, 0.25)' : '';
              var btn = c.querySelector('.exec-reconcile-confirm-btn');
              if (btn) {
                btn.textContent = selected ? 'Reconciliation selected' : 'Confirm reconciliation';
                btn.disabled = !!selected;
              }
              var removeBtn = c.querySelector('.exec-reconcile-remove-btn');
              if (removeBtn) {
                removeBtn.style.display = selected ? '' : 'none';
              }
            });
            applyVisibility(cards);
          }

          function bindReconcileCardsDelegation() {
            if (reconcileCardsDelegationBound) {
              if (reconcileCardsDelegationBound.has(cardsContainer)) return;
              reconcileCardsDelegationBound.add(cardsContainer);
            } else {
              if (reconcileCardsDelegationFallback.indexOf(cardsContainer) !== -1) return;
              reconcileCardsDelegationFallback.push(cardsContainer);
            }
            cardsContainer.addEventListener('click', function(ev) {
              var target = ev.target;
              var detailBtn = target && target.closest
                ? target.closest('[data-action="toggle-reconcile-details"]')
                : null;
              if (detailBtn && cardsContainer.contains(detailBtn)) {
                ev.preventDefault();
                ev.stopPropagation();
                var rowForDetail = detailBtn.closest('.execute-reconcile-untracked-card');
                var panel = rowForDetail && rowForDetail.querySelector('.exec-reconcile-details-panel');
                if (!panel) return;
                var isOpen = panel.style.display === 'block';
                panel.style.display = isOpen ? 'none' : 'block';
                detailBtn.textContent = isOpen ? 'Details' : 'Hide details';
                return;
              }
              var confirmBtn = target && target.closest
                ? target.closest('.exec-reconcile-confirm-btn')
                : null;
              if (confirmBtn && cardsContainer.contains(confirmBtn)) {
                ev.preventDefault();
                ev.stopPropagation();
                var rowCard = confirmBtn.closest('.execute-reconcile-untracked-card');
                if (!rowCard || !cardsContainer.contains(rowCard)) return;
                var uid = (rowCard.dataset.untrackedId || '').trim();
                if (uid === '') {
                  setLocked(false);
                  setSelection('');
                } else {
                  setLocked(true);
                  setSelection(uid);
                }
                return;
              }
              var removeBtn = target && target.closest
                ? target.closest('.exec-reconcile-remove-btn')
                : null;
              if (removeBtn && cardsContainer.contains(removeBtn)) {
                ev.preventDefault();
                ev.stopPropagation();
                setLocked(false);
                setSelection('');
              }
            });
          }

          var noneCard = document.createElement('div');
          noneCard.className = 'execute-reconcile-untracked-card' + (defaultId ? '' : ' execute-reconcile-card-selected');
          noneCard.dataset.untrackedId = '';
          noneCard.style.cssText = 'margin-bottom: 0; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); overflow: hidden; transition: border-color 0.15s, box-shadow 0.15s;';
          noneCard.innerHTML =
            '<div style="padding: 12px 16px;">' +
              '<div style="font-size: 13px; font-weight: 600; color: var(--text-secondary);">— None —</div>' +
            '</div>' +
            '<div style="padding: 0 16px 14px 16px;">' +
              '<div style="display:flex; gap: 10px; justify-content:flex-start;">' +
                '<button type="button" class="btn btn-secondary btn-sm exec-reconcile-confirm-btn" style="font-size: 12px; font-weight: 700;">Confirm reconciliation</button>' +
              '</div>' +
            '</div>';
          var cardsFrag = document.createDocumentFragment();
          cardsFrag.appendChild(noneCard);

          matchingUntracked.forEach(function(u) {
            var id = String(u.id);
            var card = document.createElement('div');
            card.className = 'execute-reconcile-untracked-card card card-interactive' + (id === defaultId ? ' execute-reconcile-card-selected' : '');
            card.dataset.untrackedId = id;
            card.style.cssText = 'margin-bottom: 0; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s; overflow: hidden;';
            var unreconciledQty = (u.remaining_balance_to_reconcile != null && String(u.remaining_balance_to_reconcile).trim() !== '') ? String(u.remaining_balance_to_reconcile).trim() : null;
            var subtitleParts = [];
            if (unreconciledQty !== null) {
              subtitleParts.push('Unreconciled: ' + escapeHtml(unreconciledQty) + ' ' + escapeHtml(u.unit || ''));
            } else {
              subtitleParts.push(escapeHtml(u.quantity != null ? String(u.quantity) : '0') + ' ' + escapeHtml(u.unit || ''));
            }
            if (u.process_name || u.producing_step_name || u.step_name) {
              var stepLabel = (u.producing_step_name != null && u.producing_step_name !== '') ? u.producing_step_name : u.step_name;
              var ps = [u.process_name, stepLabel].filter(Boolean).map(function(x) { return escapeHtml(x); }).join(' · ');
              if (ps) subtitleParts.push(ps);
            }
            if (u.source_step_completed_by) subtitleParts.push('Completed by: ' + escapeHtml(u.source_step_completed_by));
            var subtitleLine = subtitleParts.join(' · ');
            var expandInner = buildUntrackedReconcileExpandHtml(u, escapeHtml, prettyLabel, orgUsersMap);
            card.innerHTML =
              '<div style="padding: 12px 16px;">' +
                '<div style="display:flex; justify-content: space-between; align-items: flex-start; gap: 10px;">' +
                  '<div style="min-width:0;">' +
                    '<div style="font-size: 14px; font-weight: 700; color: var(--text-primary);">' + escapeHtml(u.name || 'Unknown') + '</div>' +
                    (subtitleLine
                      ? '<div style="font-size: 12px; color: var(--text-secondary); margin-top: 6px; line-height: 1.4;">' + subtitleLine + '</div>'
                      : '') +
                  '</div>' +
                  '<button type="button" class="btn btn-secondary btn-sm" data-action="toggle-reconcile-details" style="flex-shrink:0; font-size: 12px;">Details</button>' +
                '</div>' +
              '</div>' +
              '<div class="exec-reconcile-details-panel" style="display: none; padding: 0 16px 12px 16px;">' +
                '<div style="padding: 12px 14px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;">' +
                  expandInner +
                '</div>' +
              '</div>' +
              '<div style="padding: 0 16px 14px 16px;">' +
                '<div style="display:flex; gap: 10px; justify-content:flex-start;">' +
                  '<button type="button" class="btn btn-secondary btn-sm exec-reconcile-confirm-btn" style="font-size: 12px; font-weight: 700;">Confirm reconciliation</button>' +
                  '<button type="button" class="btn btn-secondary btn-sm exec-reconcile-remove-btn" style="font-size: 12px; display:none;">Remove reconciliation</button>' +
                '</div>' +
              '</div>';
            cardsFrag.appendChild(card);
          });

          cardsContainer.appendChild(cardsFrag);

          bindReconcileCardsDelegation();

          setLocked(false);
          setSelection(defaultId);
          }
        }

        // Wire expiry input toggle (set_at_execution)
        try {
          var expiryBox = outputSection.querySelector('.execute-output-expiry-input');
          if (expiryBox) {
            var modeSel = outputSection.querySelector('.execute-output-expiry-input-mode');
            var durFields = outputSection.querySelector('.execute-output-expiry-duration-fields');
            var dtFields = outputSection.querySelector('.execute-output-expiry-datetime-fields');
            var warnFields = outputSection.querySelector('.execute-output-expiry-warning-fields');
            if (modeSel && durFields && dtFields) {
              var apply = function() {
                var v = modeSel.value;
                durFields.style.display = v === 'duration' ? 'block' : 'none';
                dtFields.style.display = v === 'datetime' ? 'block' : 'none';
                if (warnFields) warnFields.style.display = (v === 'duration' || v === 'datetime') ? 'block' : 'none';
              };
              modeSel.addEventListener('change', apply);
              apply();
              (function() {
                function runValidation() {
                  var v = modeSel.value;
                  var errEl = expiryBox.querySelector('.execute-output-expiry-validation-error');
                  var warnValEl = expiryBox.querySelector('.execute-output-expiry-warning-value');
                  var warnUnitEl = expiryBox.querySelector('.execute-output-expiry-warning-unit');
                  if (!errEl || !warnValEl || !warnUnitEl) return;
                  errEl.style.display = 'none';
                  errEl.textContent = '';
                  warnValEl.style.borderColor = '';
                  warnUnitEl.style.borderColor = '';
                  if (v !== 'duration' && v !== 'datetime') return;
                  var warnVal = parseInt(warnValEl.value, 10);
                  var warnUnit = (warnUnitEl.value || 'days').trim();
                  var expiryHours = null;
                  var expiryLabel = 'the expiry period';
                  var validator = (window.CustomExpiryValidation || {});
                  var durationToHours = (typeof validator.durationToHours === 'function') ? validator.durationToHours : function() { return null; };
                  if (v === 'duration') {
                    var durValEl = expiryBox.querySelector('.execute-output-expiry-duration-value');
                    var durUnitEl = expiryBox.querySelector('.execute-output-expiry-duration-unit');
                    var durVal = durValEl ? parseInt(durValEl.value, 10) : null;
                    var durUnit = (durUnitEl ? (durUnitEl.value || 'days') : 'days').trim();
                    expiryHours = durationToHours(durVal != null && !isNaN(durVal) ? durVal : null, durUnit);
                    expiryLabel = (durVal != null ? durVal : '') + ' ' + durUnit;
                  } else {
                    var dtEl = expiryBox.querySelector('.execute-output-expiry-datetime');
                    var raw = dtEl ? (dtEl.value || '').trim() : '';
                    if (raw) {
                      var expiryAt = new Date(raw);
                      if (!isNaN(expiryAt.getTime())) {
                        expiryHours = (expiryAt.getTime() - Date.now()) / (1000 * 60 * 60);
                        expiryLabel = 'the expiry date/time';
                      }
                    }
                  }
                  if (expiryHours != null && expiryHours <= 0 && v === 'datetime') {
                    errEl.textContent = 'Expiry date and time must be in the future.';
                    errEl.style.display = 'block';
                    return;
                  }
                  if (typeof validator.validateWarnNotLongerThanExpiry === 'function') {
                    var res = validator.validateWarnNotLongerThanExpiry({
                      outputName: outName,
                      warnValue: isNaN(warnVal) ? null : warnVal,
                      warnUnit: warnUnit,
                      expiryHours: expiryHours,
                      expiryLabel: expiryLabel,
                    });
                    if (res && res.valid === false) {
                      errEl.textContent = res.message || 'Warn period must not be longer than the expiry period.';
                      errEl.style.display = 'block';
                      warnValEl.style.borderColor = 'var(--danger, #dc2626)';
                      warnUnitEl.style.borderColor = 'var(--danger, #dc2626)';
                    }
                  }
                }
                [expiryBox.querySelector('.execute-output-expiry-duration-value'), expiryBox.querySelector('.execute-output-expiry-duration-unit'), expiryBox.querySelector('.execute-output-expiry-warning-value'), expiryBox.querySelector('.execute-output-expiry-warning-unit'), expiryBox.querySelector('.execute-output-expiry-datetime')].forEach(function(el) {
                  if (el) { el.addEventListener('input', runValidation); el.addEventListener('change', runValidation); }
                });
                modeSel.addEventListener('change', runValidation);
              })();
            }
          }
          // When both expiry and ready date are set at execution, highlight "expiry before ready" before submit
          var readyDateBox = outputSection.querySelector('.execute-output-ready-date-input');
          if (expiryBox && readyDateBox && typeof window.ExpiryReadyDateValidation !== 'undefined' && typeof window.ExpiryReadyDateValidation.validateExpiryAfterReadyDates === 'function') {
            var expiryReadyErrEl = outputSection.querySelector('.execute-output-expiry-ready-validation-error');
            var readyDateInputEl = readyDateBox.querySelector('.execute-output-ready-date-date');
            function runExpiryReadyValidation() {
              if (!expiryReadyErrEl) return;
              expiryReadyErrEl.style.display = 'none';
              expiryReadyErrEl.textContent = '';
              expiryBox.style.borderColor = '';
              expiryBox.style.boxShadow = '';
              readyDateBox.style.borderColor = '';
              readyDateBox.style.boxShadow = '';
              var modeSel = expiryBox.querySelector('.execute-output-expiry-input-mode');
              var inputMode = modeSel ? (modeSel.value || 'duration') : 'duration';
              if (inputMode !== 'datetime') return;
              var dtEl = expiryBox.querySelector('.execute-output-expiry-datetime');
              var expiryRaw = dtEl ? (dtEl.value || '').trim() : '';
              var readyRaw = readyDateInputEl ? (readyDateInputEl.value || '').trim() : '';
              if (!expiryRaw || !readyRaw) return;
              var readyIso = readyRaw ? (new Date(readyRaw + 'T00:00:00Z')).toISOString() : null;
              var expiryIso = expiryRaw ? (new Date(expiryRaw)).toISOString() : null;
              if (!readyIso || !expiryIso) return;
              var res = window.ExpiryReadyDateValidation.validateExpiryAfterReadyDates(outName, readyIso, expiryIso);
              if (!res.valid) {
                expiryReadyErrEl.textContent = res.message || 'Expiry date cannot be before the ready date.';
                expiryReadyErrEl.style.display = 'block';
                expiryBox.style.borderColor = 'var(--error, #ef4444)';
                expiryBox.style.boxShadow = '0 0 0 1px var(--error, #ef4444)';
                readyDateBox.style.borderColor = 'var(--error, #ef4444)';
                readyDateBox.style.boxShadow = '0 0 0 1px var(--error, #ef4444)';
              }
            }
            if (readyDateInputEl) {
              readyDateInputEl.addEventListener('input', runExpiryReadyValidation);
              readyDateInputEl.addEventListener('change', runExpiryReadyValidation);
            }
            [expiryBox.querySelector('.execute-output-expiry-datetime'), expiryBox.querySelector('.execute-output-expiry-input-mode')].forEach(function(el) {
              if (el) { el.addEventListener('input', runExpiryReadyValidation); el.addEventListener('change', runExpiryReadyValidation); }
            });
          }
        } catch (e) {}

        // Reconciliation cards are rendered above (in prompts section). No dropdown wiring needed here.
      });
    } else if (outputsContainer) {
      outputsContainer.innerHTML = '<p style="color: var(--text-secondary); font-size: 14px; padding: 16px;">No variable outputs for this step.</p>';
    }

  }

  root.ExecutionRenderOutputs = {
    renderVariableOutputs: renderVariableOutputs,
  };
})(typeof window !== 'undefined' ? window : this);
