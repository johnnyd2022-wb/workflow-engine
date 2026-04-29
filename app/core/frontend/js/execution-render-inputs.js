/**
 * Variable inventory input rows + card picker for execute-step UI.
 * Load before execution-modal.js.
 */
(function (root) {
  "use strict";

  function renderVariableInventoryInputs(ctx) {
    var modal = ctx.modal;
    var ses = ctx.ses;
    var inputsContainer = ctx.inputsContainer;
    var variableInputs = ctx.variableInputs;
    var allInventory = ctx.allInventory;
    var getExpiredReason = ctx.getExpiredReason;
    var escapeHtml = ctx.escapeHtml;
    var prettyLabel = ctx.prettyLabel;
    var convertUnit = ctx.convertUnit;
    var orgUsersMap = ctx.orgUsersMap;
    if (!variableInputs || !variableInputs.length || !inputsContainer) return;
      variableInputs.forEach((input, inputIdx) => {
        const inputSection = document.createElement('div');
        inputSection.className = 'execute-input-section';
        // Page-style sections (no card chrome). CSS can further refine.
        inputSection.style.cssText = 'margin: 0; padding: 18px 0;' + (inputIdx === 0 ? '' : ' border-top: 1px solid var(--border-default, #e5e7eb);');
        
        // Filter inventory by material name (shows all matching items)
        const matchingInventory = allInventory.filter(inv => 
          inv.name.toLowerCase().includes(input.name.toLowerCase()) || 
          input.name.toLowerCase().includes(inv.name.toLowerCase())
        );
        
        // Get current execution ID from modal context
        const currentExecutionId = modal.dataset.executionId;
        
        // Sort inventory: items with same execution_id first, then others
        const sortedInventory = matchingInventory.sort((a, b) => {
          const aExecutionId = a.source_execution_id || a.execution_id || null;
          const bExecutionId = b.source_execution_id || b.execution_id || null;
          
          // If current execution ID is available, prioritize items from same execution
          if (currentExecutionId) {
            const aMatches = aExecutionId && String(aExecutionId) === String(currentExecutionId);
            const bMatches = bExecutionId && String(bExecutionId) === String(currentExecutionId);
            
            if (aMatches && !bMatches) return -1; // a comes first
            if (!aMatches && bMatches) return 1;  // b comes first
          }
          
          // If both match or both don't match, maintain original order
          return 0;
        });
        
        // Check if no matching inventory is available
        const hasNoInventory = sortedInventory.length === 0;
        const errorStyle = hasNoInventory ? 'border: 2px solid var(--error, #ef4444);' : '';
        const errorMessage = hasNoInventory ? `<p class="execute-input-no-inventory-warning" style="color: var(--error, #ef4444); font-size: 12px; margin-top: 4px; font-weight: 500;">⚠️ No matching inventory items found. Please add inventory before executing this step.</p>` : '';
        const safeInputName = (input.name || '').replace(/[^a-zA-Z0-9_-]/g, '_');
        const inventoryById = new Map();
        allInventory.forEach(function(inv) { inventoryById.set(String(inv.id), inv); });

        inputSection.innerHTML = `
          <div class="execute-input-section-header" style="margin-bottom: 12px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">
              ${escapeHtml(input.name)} 
              <span style="color: var(--text-secondary); font-weight: normal;">(Expected: ${input.quantity || '0'} ${input.unit || ''})</span>
            </label>
          </div>
          <div class="execute-input-rows-container" data-input-name="${escapeHtml(input.name)}" data-safe-name="${safeInputName}"></div>
          <div class="exec-picker-panel" data-exec-picker-panel="true" style="display:block; margin-top: 10px;">
            <div class="flow-mode-segmented" role="group" aria-label="Inventory category" style="margin-bottom: 10px;">
              <button type="button" class="flow-mode-segment flow-mode-segment--active" data-exec-type="raw_material" aria-pressed="true">Raw materials</button>
              <button type="button" class="flow-mode-segment" data-exec-type="work_in_progress" aria-pressed="false">Intermediate</button>
              <button type="button" class="flow-mode-segment" data-exec-type="final_product" aria-pressed="false">Finals products</button>
            </div>
            <div class="exec-picker-search">
              <input type="search" class="spa-inp" data-exec-picker-search="true" placeholder="Search inventory…" autocomplete="off">
            </div>
            <div class="exec-picker-cards" data-exec-picker-cards="true"></div>
          </div>
          <div class="execute-add-input-pane" style="margin-top: 12px; margin-bottom: 0; padding: 16px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-lg); border: 1px solid var(--border-light, #e5e7eb);">
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 6px;">Add another input</label>
            <p style="font-size: 12px; color: var(--text-secondary); margin: 0 0 10px 0; line-height: 1.45;">Add one or more inputs to meet step quantity (e.g. multiple batches) or to record an additional material when inputs are not always set per execution.</p>
            <button type="button" class="btn btn-secondary btn-sm execute-add-another-input-btn" data-input-name="${escapeHtml(input.name)}" data-safe-name="${safeInputName}" style="font-size: 13px;">+ Add another input</button>
          </div>
          <div class="execute-input-qty-expected-warning" style="display: none; margin-top: 12px; padding: 10px 12px; background: hsl(38, 92%, 95%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); color: #92400e; font-size: 13px; font-weight: 500;" role="status"></div>
          <div class="execute-input-unexpected-material-warning" style="display: none; margin-top: 8px; padding: 10px 12px; background: hsl(210, 90%, 96%); border: 1px solid var(--info, #3b82f6); border-radius: var(--radius-md); color: #1e40af; font-size: 13px; font-weight: 500;" role="status"></div>
          ${errorMessage}
          ${hasNoInventory ? `<p style="margin-top: 8px;"><button type="button" class="btn btn-secondary btn-sm add-missing-item-btn" data-input-name="${escapeHtml(input.name)}" data-input-quantity="${escapeHtml(String(input.quantity != null ? input.quantity : ''))}" data-input-unit="${escapeHtml(input.unit || '')}" data-source-output-id="${input.source_output_id ? escapeHtml(String(input.source_output_id)) : ''}" data-source-step-id="${input.source_step_id ? escapeHtml(String(input.source_step_id)) : ''}" data-source-process-id="${input.source_process_id ? escapeHtml(String(input.source_process_id)) : ''}" style="font-size: 13px;">Add Missing Item</button></p>` : ''}
        `;

        const rowsContainer = inputSection.querySelector('.execute-input-rows-container');
        const pickerPanel = inputSection.querySelector('[data-exec-picker-panel="true"]');
        const pickerCards = inputSection.querySelector('[data-exec-picker-cards="true"]');
        const pickerSearch = inputSection.querySelector('[data-exec-picker-search="true"]');

        // Ensure rows stack cleanly when adding additional inputs.
        if (rowsContainer) {
          rowsContainer.style.display = 'flex';
          rowsContainer.style.flexDirection = 'column';
          rowsContainer.style.gap = '12px';
        }
        const pickerTabs = Array.prototype.slice.call(inputSection.querySelectorAll('.flow-mode-segment'));
        let rowIndex = 0;
        if (!ses.inputStateByKey) ses.inputStateByKey = new Map();

        function getInvType(inv) {
          return inv && (inv.inventory_type || inv.type || inv.category || inv.item_type || '');
        }
        /** Map API/mock inventory types onto picker tab keys (raw_material | work_in_progress | final_product). */
        function normalizeInventoryTabType(inv) {
          var t = String(getInvType(inv) || '').toLowerCase().trim();
          if (!t) return 'raw_material';
          if (t === 'intermediate' || t === 'work_in_progress' || t === 'wip') return 'work_in_progress';
          if (t === 'final' || t === 'final_product') return 'final_product';
          if (t === 'raw' || t === 'raw_material') return 'raw_material';
          return t;
        }
        function invMatchesType(inv, selected) {
          if (!selected || selected === 'all') return true;
          return normalizeInventoryTabType(inv) === selected;
        }
        function invMatchesSearch(inv, q) {
          q = (q || '').trim().toLowerCase();
          if (!q) return true;
          var hay = [
            inv && inv.name,
            inv && inv.unit,
            inv && inv.supplier,
            inv && inv.supplier_batch_number,
            inv && inv.process_name,
          ].filter(Boolean).join(' ').toLowerCase();
          return hay.indexOf(q) !== -1;
        }
        function fmtQty(inv) {
          if (!inv) return '';
          var q = (inv.quantity != null) ? String(inv.quantity) : '';
          var u = inv.unit || '';
          return (q && u) ? (q + ' ' + u) : (q || u || '');
        }
        function renderPickerCards(activeType, q) {
          if (!pickerCards) return;
          var activeRow = ses.editingInputRow;
          var selectedId = '';
          try {
            var sel = activeRow ? activeRow.querySelector('.execute-inventory-select') : null;
            selectedId = sel && sel.value ? String(sel.value) : '';
          } catch (e) {}
          var pendingId = '';
          try {
            var pSel = activeRow ? activeRow.getAttribute('data-pending-inv-id') : '';
            pendingId = pSel ? String(pSel) : '';
          } catch (e) {}
          // Hide items that are already selected in any input row (operator workflow).
          var selectedIds = new Set();
          try {
            inputSection.querySelectorAll('.execute-input-row').forEach(function(r) {
              var s = r.querySelector('.execute-inventory-select');
              if (s && s.value) selectedIds.add(String(s.value));
            });
          } catch (e) {}

          var list = sortedInventory
            .filter(function(inv) { return invMatchesType(inv, activeType); })
            .filter(function(inv) { return invMatchesSearch(inv, q); });
          list = list.filter(function(inv) {
            var id = String(inv.id);
            if (pendingId && id === pendingId) return true;
            return !selectedIds.has(id);
          });

          // Keep list stable during preview (no reordering).
          if (!list.length) {
            pickerCards.innerHTML = '<p style="margin: 0; font-size: 13px; color: var(--text-secondary); padding: 6px 2px;">No inventory matches.</p>';
            return;
          }
          pickerCards.innerHTML = list.map(function(inv) {
            var rawId = String(inv.id);
            var id = escapeHtml(rawId);
            var name = escapeHtml(inv.name || 'Unnamed');
            var sub = escapeHtml(fmtQty(inv));
            var chips = '';
            if (inv.supplier) chips += '<span class="exec-picker-chip">' + escapeHtml(inv.supplier) + '</span>';
            if (inv.supplier_batch_number) chips += '<span class="exec-picker-chip">Batch ' + escapeHtml(inv.supplier_batch_number) + '</span>';
            var reason = getExpiredReason(inv.id);
            if (reason) {
              var cls = reason.toLowerCase().indexOf('untracked') !== -1 ? 'exec-picker-chip--danger'
                : (reason.toLowerCase().indexOf('expired') !== -1 ? 'exec-picker-chip--danger' : 'exec-picker-chip--warn');
              chips += '<span class="exec-picker-chip ' + cls + '">' + escapeHtml(reason) + '</span>';
            }
            var isPending = pendingId && pendingId === rawId;
            function fmtDate(raw) {
              if (!raw) return '';
              try { return new Date(raw).toLocaleDateString(); } catch (e) { return String(raw); }
            }
            function addMeta(label, value) {
              if (value == null) return '';
              var s = String(value);
              if (!s.trim()) return '';
              return (
                '<div style="min-width:0;">' +
                  '<div style="font-size:11px; color: var(--text-tertiary, #9ca3af); line-height:1.2;">' + escapeHtml(label) + '</div>' +
                  '<div style="font-size:12px; color: var(--text-primary, #111827); font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + escapeHtml(s) + '</div>' +
                '</div>'
              );
            }
            var metaBits = '';
            // Core production identifiers
            metaBits += addMeta('Process', inv.process_name || '');
            metaBits += addMeta('Supplier', inv.supplier || '');
            metaBits += addMeta('Batch', inv.supplier_batch_number || inv.batch_number || inv.lot_number || '');
            metaBits += addMeta('Barcode', inv.barcode || '');
            metaBits += addMeta('Source step', inv.source_step_name || '');
            // Dates (if present)
            metaBits += addMeta('Purchase', inv.purchase_date ? fmtDate(inv.purchase_date) : '');
            metaBits += addMeta('Expiry', inv.expiry_date ? fmtDate(inv.expiry_date) : '');
            metaBits += addMeta('Ready', inv.ready_date ? fmtDate(inv.ready_date) : '');
            metaBits += addMeta('Created', inv.created_at ? fmtDate(inv.created_at) : '');
            // Provenance (if present)
            metaBits += addMeta('Operator', inv.operator_name || inv.operator || '');
            metaBits += addMeta('Created by', inv.created_by_name || inv.created_by || '');

            // Extra metadata (bounded): show up to 8 keys, include small objects with "name"/"email".
            var extraBits = '';
            try {
              var extra = inv.extra_data;
              if (extra && typeof extra === 'object') {
                var keys = Object.keys(extra);
                var shown = 0;
                for (var k = 0; k < keys.length; k++) {
                  if (shown >= 8) break;
                  var key = keys[k];
                  if (key === 'execution_prompts') continue; // handled elsewhere / too verbose
                  var val = extra[key];
                  if (val == null) continue;
                  var vv = '';
                  if (typeof val === 'object') {
                    if (val && (val.name || val.email)) vv = String(val.name || val.email);
                    else continue;
                  } else {
                    vv = String(val);
                  }
                  if (!vv.trim()) continue;
                  // Prefer showing common production keys early.
                  var label = key;
                  if (/batch|lot/i.test(key)) label = 'Batch';
                  if (/operator/i.test(key)) label = 'Operator';
                  if (/created_by|creator|made_by/i.test(key)) label = 'Created by';
                  extraBits += addMeta(label, vv);
                  shown++;
                }
              }
            } catch (e) {}

            var metaBlock = '';
            var combined = (metaBits || '') + (extraBits || '');
            if (combined) {
              metaBlock =
                '<div class="exec-picker-card__meta-grid" style="margin-top: 10px; display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px;">' +
                  combined +
                '</div>';
            }

            // Full metadata (expand/collapse): show every scalar key on inv + full JSON for extra_data.
            function safeString(v) {
              if (v == null) return '';
              if (typeof v === 'string') return v;
              if (typeof v === 'number' || typeof v === 'boolean') return String(v);
              return '';
            }
            var kv = [];
            try {
              Object.keys(inv || {}).forEach(function(k) {
                if (k === 'extra_data') return;
                var v = inv[k];
                if (v == null) return;
                if (typeof v === 'object') return;
                var s = safeString(v);
                if (!s || !String(s).trim()) return;
                kv.push([k, s]);
              });
            } catch (e) {}
            kv.sort(function(a, b) { return a[0].localeCompare(b[0]); });
            var kvHtml = kv.map(function(p) {
              return '<div class="exec-picker-kv__k">' + escapeHtml(p[0]) + '</div><div class="exec-picker-kv__v">' + escapeHtml(p[1]) + '</div>';
            }).join('');
            var extraJson = '';
            try {
              if (inv.extra_data && typeof inv.extra_data === 'object') {
                extraJson = JSON.stringify(inv.extra_data, null, 2);
              }
            } catch (e) {}
            // Audit history (extra_data.inventory_audit_history): show human-friendly operator + cleaned labels.
            var auditHtml = '';
            try {
              var hist = (inv.extra_data && inv.extra_data.inventory_audit_history) ? inv.extra_data.inventory_audit_history : [];
              if (Array.isArray(hist) && hist.length) {
                var rows = hist.slice().reverse().map(function(h) {
                  var when = h.timestamp_utc || h.timestamp || h.created_at || '';
                  var src = h.source_method || h.source || '';
                  var opLabel = h.operator_name || h.operator_email || '';
                  if (!opLabel) {
                    var opId = h.user_id || h.operator_id || h.user || '';
                    opLabel = opId && orgUsersMap && typeof orgUsersMap.get === 'function'
                      ? (orgUsersMap.get(String(opId)) || String(opId))
                      : String(opId || '');
                  }
                  // Never leak raw UUIDs in the UI; show a friendly fallback.
                  try {
                    var uuidLike = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
                    if (!opLabel || uuidLike.test(String(opLabel).trim())) opLabel = 'Unknown operator';
                  } catch (e) {
                    if (!opLabel) opLabel = 'Unknown operator';
                  }
                  // Action isn't logged yet for raw materials; use a sensible default for now.
                  var action = h.action || h.event || '';
                  if (!action) action = 'inventory item added';
                  return (
                    '<div class="exec-picker-kv__k">' + escapeHtml(prettyLabel('action')) + '</div><div class="exec-picker-kv__v">' + escapeHtml(prettyLabel(action)) + '</div>' +
                    '<div class="exec-picker-kv__k">' + escapeHtml(prettyLabel('timestamp_utc')) + '</div><div class="exec-picker-kv__v">' + escapeHtml(String(when || '—')) + '</div>' +
                    '<div class="exec-picker-kv__k">' + escapeHtml(prettyLabel('operator')) + '</div><div class="exec-picker-kv__v">' + escapeHtml(String(opLabel || '—')) + '</div>' +
                    '<div class="exec-picker-kv__k">' + escapeHtml(prettyLabel('source_method')) + '</div><div class="exec-picker-kv__v">' + escapeHtml(prettyLabel(src) || '—') + '</div>'
                  );
                }).join('');
                auditHtml =
                  '<div style="margin-top: 12px;">' +
                    '<div style="font-size: 12px; font-weight: 700; color: var(--text-secondary,#6b7280); letter-spacing:0.03em; text-transform: uppercase; margin-bottom: 8px;">Audit history</div>' +
                    '<div class="exec-picker-kv">' + rows + '</div>' +
                  '</div>';
              }
            } catch (e) {}

            var isRawMaterial = String(inv.inventory_type || 'raw_material') === 'raw_material';

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
            function li(text) {
              return '<li style="margin: 0 0 6px 0; font-size: 13px; color: var(--text-primary, #111827); line-height: 1.35;">' + text + '</li>';
            }
            function fmtIso(iso) {
              if (!iso) return '';
              try { return new Date(iso).toISOString().replace('.000Z','Z'); } catch (e) { return String(iso); }
            }
            function fmtCustomExpiry(obj) {
              if (!obj || typeof obj !== 'object') return '';
              var mode = (obj.mode || '').toString();
              if (mode === 'duration') {
                var dv = obj.duration_value != null ? String(obj.duration_value) : '';
                var du = obj.duration_unit != null ? String(obj.duration_unit).replace(/_/g, ' ') : '';
                var wv = obj.warning_value != null ? String(obj.warning_value) : '';
                var wu = obj.warning_unit != null ? String(obj.warning_unit).replace(/_/g, ' ') : '';
                var base = (dv && du) ? ('Expiry: ' + escapeHtml(dv + ' ' + du)) : '';
                var warn = (wv && wu) ? ('Warning: ' + escapeHtml(wv + ' ' + wu)) : '';
                return [base, warn].filter(Boolean).join(' · ');
              }
              if (mode === 'datetime') {
                var exp = obj.expiry_at || obj.expiryAt || '';
                var warnAt = obj.warning_at || obj.warn_at || obj.warningAt || '';
                var base2 = exp ? ('Expiry at (UTC): ' + escapeHtml(fmtIso(exp))) : '';
                var warn2 = warnAt ? ('Warning at (UTC): ' + escapeHtml(fmtIso(warnAt))) : '';
                return [base2, warn2].filter(Boolean).join(' · ');
              }
              // Unknown schema
              try { return escapeHtml(JSON.stringify(obj)); } catch (e) { return ''; }
            }

            var humanDetails = '';
            if (!isRawMaterial) {
              // Traceability summary for intermediate/final products.
              var trace = (inv.extra_data && inv.extra_data.execution_trace) ? inv.extra_data.execution_trace : {};
              var prompts = (inv.extra_data && inv.extra_data.execution_prompts) ? inv.extra_data.execution_prompts : null;
              var vInputs = (inv.extra_data && inv.extra_data.variable_inputs) ? inv.extra_data.variable_inputs : null;
              var vOut = (inv.extra_data && inv.extra_data.variable_output) ? inv.extra_data.variable_output : null;

              var top = '';
              var topRows = '';
              if (inv.process_name) topRows += '<div class="exec-picker-kv__k">' + escapeHtml('Process name') + '</div><div class="exec-picker-kv__v">' + escapeHtml(String(inv.process_name)) + '</div>';
              if (inv.source_step_name) topRows += '<div class="exec-picker-kv__k">' + escapeHtml('Source step name') + '</div><div class="exec-picker-kv__v">' + escapeHtml(String(inv.source_step_name)) + '</div>';
              if (topRows) top = '<div class="exec-picker-kv">' + topRows + '</div>';
              humanDetails += section('Production', top);

              // Custom expiry (differentiate inputs)
              var ceActual = (inv.extra_data && inv.extra_data.custom_expiry_actual) ? inv.extra_data.custom_expiry_actual : null;
              var ceInput = vOut && vOut.custom_expiry_input ? vOut.custom_expiry_input : (inv.extra_data && inv.extra_data.custom_expiry_input ? inv.extra_data.custom_expiry_input : null);
              var ceBits = '';
              if (ceActual) ceBits += '<div class="exec-picker-kv">' +
                '<div class="exec-picker-kv__k">' + escapeHtml('Custom expiry (applied)') + '</div><div class="exec-picker-kv__v">' + fmtCustomExpiry(ceActual) + '</div>' +
              '</div>';
              if (ceInput) ceBits += '<div class="exec-picker-kv" style="margin-top:6px;">' +
                '<div class="exec-picker-kv__k">' + escapeHtml('Custom expiry (entered)') + '</div><div class="exec-picker-kv__v">' + fmtCustomExpiry(ceInput) + '</div>' +
              '</div>';
              humanDetails += section('Custom expiry', ceBits);

              // Execution prompts
              if (prompts && typeof prompts === 'object') {
                var entries = Object.entries(prompts);
                if (entries.length) {
                  var ul = '<ul style="margin: 0; padding-left: 18px;">' +
                    entries.map(function(e, idx) {
                      var k = e[0];
                      var v = e[1];
                      return li('<span style="font-weight:600;">Prompt ' + (idx + 1) + '</span>' +
                        ' <span style="color: var(--text-secondary,#6b7280); font-weight:500;">(' + escapeHtml(prettyLabel(k)) + ')</span>' +
                        ': <span style="font-weight:400;">' + escapeHtml(String(v)) + '</span>');
                    }).join('') +
                  '</ul>';
                  humanDetails += section('Custom prompts', ul);
                }
              }

              // Inputs (variable_inputs)
              if (Array.isArray(vInputs) && vInputs.length) {
                var ul2 = '<ul style="margin: 0; padding-left: 18px;">' +
                  vInputs.map(function(x) {
                    var nm = (x && (x.name || x.input_name || x.inputName)) ? String(x.name || x.input_name || x.inputName) : 'Input';
                    var q = (x && (x.quantity != null ? x.quantity : x.input_quantity)) != null ? String(x.quantity != null ? x.quantity : x.input_quantity) : '';
                    var u = (x && (x.unit || x.input_unit)) ? String(x.unit || x.input_unit) : '';
                    return li('<span style="font-weight:400;">' + escapeHtml(nm) + '</span>' +
                      (q ? (' <span style="color: var(--text-secondary,#6b7280); font-weight:400;">— ' + escapeHtml(String(q)) + (u ? (' ' + escapeHtml(u)) : '') + '</span>') : ''));
                  }).join('') +
                '</ul>';
                humanDetails += section('Inputs', ul2);
              }

              // Variable output (human-readable)
              if (vOut && typeof vOut === 'object') {
                var outNm = vOut.name || inv.name || '';
                var outQ = vOut.quantity != null ? vOut.quantity : '';
                var outU = vOut.unit || inv.unit || '';
                var outRows = '';
                if (outNm) outRows += '<div class="exec-picker-kv__k">' + escapeHtml('Output name') + '</div><div class="exec-picker-kv__v">' + escapeHtml(String(outNm)) + '</div>';
                if (outQ !== '' && outQ != null) outRows += '<div class="exec-picker-kv__k">' + escapeHtml('Output quantity') + '</div><div class="exec-picker-kv__v">' + escapeHtml(String(outQ)) + (outU ? (' ' + escapeHtml(String(outU))) : '') + '</div>';
                humanDetails += section('Output', outRows ? ('<div class="exec-picker-kv">' + outRows + '</div>') : '');
              }

              // Execution trace (audit-like, human labels)
              var auditBits = '';
              var ts = inv.created_at || (trace && trace.completed_at) || '';
              // Operator: prefer completed_by label; else map completed_by_user_id to org user display; else email.
              var op = (trace && (trace.completed_by || trace.completed_by_email)) || inv.operator_name || inv.created_by_name || '';
              if (!op) {
                var uid = trace && (trace.completed_by_user_id || trace.completed_by_user || trace.user_id);
                if (uid && orgUsersMap && typeof orgUsersMap.get === 'function') {
                  op = orgUsersMap.get(String(uid)) || '';
                }
              }
              var srcMethod = (trace && trace.source_method) || '';
              if (!srcMethod && inv.source_execution_step_id) srcMethod = 'completed step';
              auditBits += '<div class="exec-picker-kv">' +
                '<div class="exec-picker-kv__k">' + escapeHtml('Action') + '</div><div class="exec-picker-kv__v">' + escapeHtml('Inventory item created') + '</div>' +
                '<div class="exec-picker-kv__k">' + escapeHtml('Timestamp UTC') + '</div><div class="exec-picker-kv__v">' + escapeHtml(ts ? fmtIso(ts) : '—') + '</div>' +
                '<div class="exec-picker-kv__k">' + escapeHtml('Operator') + '</div><div class="exec-picker-kv__v">' + escapeHtml(op || '—') + '</div>' +
                '<div class="exec-picker-kv__k">' + escapeHtml('Source method') + '</div><div class="exec-picker-kv__v">' + escapeHtml(srcMethod ? prettyLabel(srcMethod) : '—') + '</div>' +
              '</div>';
              humanDetails += section('Audit history', auditBits);
            }

            var detailsHtml =
              '<div class="exec-picker-card__details">' +
                (isRawMaterial ? '' : humanDetails) +
                (isRawMaterial ? auditHtml : '') +
              '</div>';
            var actions = '';
            if (isPending) {
              actions =
                '<div class="exec-picker-card__actions" style="justify-content:flex-start;">' +
                  '<button type="button" class="btn btn-secondary btn-sm exec-picker-confirm-btn" data-action="confirm-input" data-inv-id="' + id + '">Confirm input</button>' +
                '</div>';
            }
            return (
              '<div class="exec-picker-card" role="button" tabindex="0" data-inv-id="' + id + '" aria-pressed="' + (isPending ? 'true' : 'false') + '" data-expanded="false">' +
                '<div class="exec-picker-card__top">' +
                  '<div style="min-width:0;">' +
                    '<p class="exec-picker-card__title">' + name + '</p>' +
                    '<p class="exec-picker-card__sub">' + sub + '</p>' +
                  '</div>' +
                  '<button type="button" class="exec-picker-card__toggle" data-action="toggle-details" data-inv-id="' + id + '">Details</button>' +
                '</div>' +
                (chips ? '<div class="exec-picker-card__meta">' + chips + '</div>' : '') +
                metaBlock +
                '<div class="exec-picker-card__spacer"></div>' +
                actions +
                detailsHtml +
              '</div>'
            );
          }).join('');
        }

        function normInputName(s) {
          return String(s || '').trim().toLowerCase();
        }
        function countTabTypes(list) {
          var counts = { raw_material: 0, work_in_progress: 0, final_product: 0 };
          (list || []).forEach(function(inv) {
            var tab = normalizeInventoryTabType(inv);
            if (counts[tab] != null) counts[tab] += 1;
          });
          return counts;
        }
        /**
         * Choose initial category tab from name-matched inventory.
         * Previously any WIP/final in the fuzzy-matched set forced WIP/final over raw — wrong when the step
         * expects a raw material but loose name matching also pulled in finals.
         */
        function pickDefaultPickerType() {
          var list = sortedInventory || [];
          var expected = normInputName(input && input.name);
          var exact =
            expected
              ? list.filter(function(inv) {
                  return normInputName(inv && inv.name) === expected;
                })
              : [];
          if (exact.length) {
            var ec = countTabTypes(exact);
            var er = ec.raw_material > 0;
            var ew = ec.work_in_progress > 0;
            var ef = ec.final_product > 0;
            var kinds = (er ? 1 : 0) + (ew ? 1 : 0) + (ef ? 1 : 0);
            if (kinds === 1) {
              if (er) return 'raw_material';
              if (ew) return 'work_in_progress';
              return 'final_product';
            }
            if (er && !ew && !ef) return 'raw_material';
            if (ew && !er && !ef) return 'work_in_progress';
            if (ef && !er && !ew) return 'final_product';
            if (ec.final_product > ec.work_in_progress) return 'final_product';
            if (ec.work_in_progress > ec.final_product) return 'work_in_progress';
            if (ec.raw_material >= ec.work_in_progress && ec.raw_material >= ec.final_product) return 'raw_material';
          }

          var counts = countTabTypes(list);
          var hasWip = counts.work_in_progress > 0;
          var hasFinal = counts.final_product > 0;
          var hasRaw = counts.raw_material > 0;

          if (input && input.source_output_id) {
            if (hasWip || hasFinal) {
              return counts.final_product > counts.work_in_progress ? 'final_product' : 'work_in_progress';
            }
            return 'raw_material';
          }

          if (hasRaw && !hasWip && !hasFinal) return 'raw_material';
          if (!hasRaw && (hasWip || hasFinal)) {
            return counts.work_in_progress >= counts.final_product ? 'work_in_progress' : 'final_product';
          }
          if (hasRaw && (hasWip || hasFinal)) {
            return 'raw_material';
          }
          return 'raw_material';
        }

        var defaultPickerType = pickDefaultPickerType();
        var pickerState = { activeType: defaultPickerType, q: '' };
        function syncTabState(next) {
          pickerState.activeType = next;
          pickerTabs.forEach(function(t) {
            var isOn = t.getAttribute('data-exec-type') === next;
            t.setAttribute('aria-pressed', isOn ? 'true' : 'false');
            t.classList.toggle('flow-mode-segment--active', isOn);
          });
          renderPickerCards(pickerState.activeType, pickerState.q);
        }
        pickerTabs.forEach(function(btn) {
          btn.addEventListener('click', function() {
            syncTabState(btn.getAttribute('data-exec-type') || 'all');
          });
        });
        if (pickerSearch) {
          pickerSearch.addEventListener('input', function() {
            pickerState.q = pickerSearch.value || '';
            renderPickerCards(pickerState.activeType, pickerState.q);
          });
        }
        if (pickerPanel) {
          // initial render (ensure correct default tab is active)
          syncTabState(defaultPickerType);
        }

        // Card clicks: preview for active row; confirm happens on the picker card.
        if (pickerCards && !pickerCards._boundPickerClick) {
          pickerCards._boundPickerClick = true;
          pickerCards.addEventListener('click', function(ev) {
            var toggleBtn = ev.target && ev.target.closest ? ev.target.closest('[data-action="toggle-details"]') : null;
            if (toggleBtn) {
              ev.preventDefault();
              ev.stopPropagation();
              var card = toggleBtn.closest('.exec-picker-card');
              if (!card) return;
              var isOn = String(card.getAttribute('data-expanded') || 'false') === 'true';
              card.setAttribute('data-expanded', isOn ? 'false' : 'true');
              toggleBtn.textContent = isOn ? 'Details' : 'Hide details';
              return;
            }
            var confirmBtn = ev.target && ev.target.closest ? ev.target.closest('[data-action="confirm-input"]') : null;
            if (confirmBtn) {
              ev.preventDefault();
              ev.stopPropagation();
              var invId = confirmBtn.getAttribute('data-inv-id') || '';
              var targetRow = ses.editingInputRow || (rowsContainer && rowsContainer.firstElementChild);
              if (!targetRow) return;
              var locked = targetRow.getAttribute('data-selection-locked') === 'true';
              var selNow = targetRow.querySelector('.execute-inventory-select');
              if (locked && selNow && selNow.value) return;
              setRowSelection(targetRow, invId);
              targetRow.setAttribute('data-pending-inv-id', '');
              targetRow.setAttribute('data-selection-locked', 'true');
              // Once confirmed, hide picker for this row to reduce noise.
              try { if (pickerPanel) pickerPanel.style.display = 'none'; } catch (e) {}
              renderPickerCards(pickerState.activeType, pickerState.q);
              return;
            }
            var btn = ev.target && ev.target.closest ? ev.target.closest('.exec-picker-card') : null;
            if (!btn) return;
            ev.preventDefault();
            var invId = btn.getAttribute('data-inv-id') || '';
            var targetRow = ses.editingInputRow || (rowsContainer && rowsContainer.firstElementChild);
            if (!targetRow) return;
            // If already confirmed for this row, don't allow changing unless they add another input row.
            var locked = targetRow.getAttribute('data-selection-locked') === 'true';
            var selNow = targetRow.querySelector('.execute-inventory-select');
            if (locked && selNow && selNow.value) return;
            // Preview selection first; require explicit confirmation.
            targetRow.setAttribute('data-pending-inv-id', invId);
            renderPickerCards(pickerState.activeType, pickerState.q);
          });
        }

        function createInputRow(isFirst) {
          const rowId = 'execute-input-row-' + safeInputName + '-' + rowIndex++;
          const stateKey = safeInputName + '::' + rowId;
          const row = document.createElement('div');
          row.className = 'execute-input-row';
          row.id = rowId;
          row.dataset.inputName = input.name;
          row.dataset.stateKey = stateKey;
          // Ensure rows naturally stack in the document flow.
          row.style.display = 'block';
          row.style.width = '100%';
          row.style.position = 'relative';
          if (!ses.inputStateByKey.has(stateKey)) {
            ses.inputStateByKey.set(stateKey, {
              input_name: input.name,
              inventory_item_id: '',
              quantity: input.quantity != null ? Number(input.quantity) : 0,
              unit: input.unit || '',
              expired_reason: '',
            });
          }
          row.innerHTML = `
            <input type="hidden" class="execute-inventory-select" data-input-name="${escapeHtml(input.name)}" data-quantity="" data-unit="" data-expired-reason="" value="">

            <div style="display:flex; justify-content:flex-end; margin-bottom: 10px;">
              <button type="button" class="execute-remove-input-row-btn btn btn-secondary btn-sm" style="font-size: 12px;">Remove input</button>
            </div>

            <div class="execute-selected-inv-card" style="display:none; padding: 12px 14px; border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md, 10px); background: var(--bg-card, #fff);"></div>

            <div class="execute-input-expired-warning" data-input-name="${escapeHtml(input.name)}" style="display: none; margin-top: 8px; padding: 10px 12px; background: hsl(0, 93%, 94%); border: 1px solid var(--error, #ef4444); border-radius: var(--radius-md); color: #b91c1c; font-size: 13px; font-weight: 500;" role="alert"></div>
            <div class="execute-input-unexpected-row-warning" data-input-name="${escapeHtml(input.name)}" style="display: none; margin-top: 8px; padding: 10px 12px; background: hsl(210, 90%, 96%); border: 1px solid var(--info, #3b82f6); border-radius: var(--radius-md); color: #1e40af; font-size: 13px; font-weight: 500;" role="status"></div>

            <div class="execute-qty-pane" style="display:none; margin-top: 12px;">
              <label class="spa-field-label">Quantity to consume</label>
              <div style="display: flex; align-items: center; gap: 8px;">
                <input type="number" class="spa-inp execute-quantity-input" data-input-name="${escapeHtml(input.name)}" data-step-unit="${escapeHtml(input.unit || '')}" data-original-quantity="${input.quantity || ''}" placeholder="${input.quantity || '0'}" value="${input.quantity || ''}" step="0.01" min="0" style="flex: 1;">
                <span class="execute-quantity-unit-display" style="font-size: 14px; color: var(--text-secondary); min-width: 40px; text-align: left;">${input.unit || ''}</span>
              </div>
            </div>
          `;
          var qtyInput = row.querySelector('.execute-quantity-input');
          if (qtyInput) {
            // Ensure we start from a neutral border (avoid stale inline styles / bfcache).
            qtyInput.style.border = '1px solid var(--border-default, #e5e7eb)';
            qtyInput.addEventListener('input', function() {
              var st = ses.inputStateByKey.get(stateKey);
              if (!st) return;
              var q = parseFloat(qtyInput.value);
              st.quantity = isNaN(q) ? 0 : q;
            });
          }

          // Remove input: if it's the only row, clear selection + unlock; otherwise remove the row.
          var removeBtn = row.querySelector('.execute-remove-input-row-btn');
          if (removeBtn) {
            removeBtn.addEventListener('click', function(e) {
              if (e) { e.preventDefault(); e.stopPropagation(); }
              row.setAttribute('data-pending-inv-id', '');
              row.setAttribute('data-selection-locked', 'false');
              if (!rowsContainer) return;
              var rowCount = rowsContainer.querySelectorAll('.execute-input-row').length;
              if (rowCount <= 1) {
                setRowSelection(row, '');
                setActiveRow(row);
              } else {
                var stateKey = row.dataset.stateKey || '';
                if (stateKey && ses.inputStateByKey) ses.inputStateByKey.delete(stateKey);
                row.remove();
                // Ensure active row points to a remaining row.
                var next = rowsContainer.querySelector('.execute-input-row');
                if (next) setActiveRow(next);
              }
              renderPickerCards(pickerState.activeType, pickerState.q);
            });
          }
          return row;
        }

        function nameMatchesExact(invName) {
          var a = (input.name || '').trim().toLowerCase();
          var b = (invName || '').trim().toLowerCase();
          return a.length > 0 && a === b;
        }

        function itemIsOutput(inv) {
          return inv && (inv.source_output_id != null && inv.source_output_id !== '');
        }

        function inputExpectsOutput() {
          return (input.source_output_id != null && input.source_output_id !== '');
        }

        function isUnexpectedType(inv) {
          if (!inv) return false;
          var expectsOutput = inputExpectsOutput();
          var invIsOutput = itemIsOutput(inv);
          if (expectsOutput) return !invIsOutput || String(inv.source_output_id) !== String(input.source_output_id);
          return invIsOutput;
        }

        function isUnexpectedItem(inv) {
          if (!inv) return false;
          if (isUnexpectedType(inv)) return true;
          return !nameMatchesExact(inv.name);
        }

        function isExpectedItem(invId) {
          if (!invId) return false;
          var inv = invId ? inventoryById.get(String(invId)) : null;
          if (!inv) return false;
          if (inputExpectsOutput()) {
            return itemIsOutput(inv) && String(inv.source_output_id) === String(input.source_output_id) && nameMatchesExact(inv.name);
          }
          return !itemIsOutput(inv) && nameMatchesExact(inv.name);
        }

        function updateRowUnexpectedWarning(rowEl) {
          var el = rowEl ? rowEl.querySelector('.execute-input-unexpected-row-warning') : null;
          var sel = rowEl ? rowEl.querySelector('.execute-inventory-select') : null;
          var invId = sel && sel.value ? sel.value : null;
          var inv = invId ? inventoryById.get(String(invId)) : null;
          var unexpected = inv && isUnexpectedItem(inv);
          if (!el) return;
          if (!sel || !invId) {
            el.style.display = 'none';
            el.textContent = '';
            return;
          }
          if (!inv || !unexpected) {
            el.style.display = 'none';
            el.textContent = '';
            return;
          }
          el.textContent = 'Warning - this selection is not the expected input for this step';
          el.style.display = 'block';
        }

        function updateSectionQtyExpectedWarning() {
          var qtyWarningEl = inputSection.querySelector('.execute-input-qty-expected-warning');
          if (!qtyWarningEl) return;
          var expectedNum = parseFloat(input.quantity);
          if (isNaN(expectedNum) || expectedNum <= 0) {
            qtyWarningEl.style.display = 'none';
            qtyWarningEl.textContent = '';
            return;
          }
          var totalExpectedQty = 0;
          inputSection.querySelectorAll('.execute-input-row').forEach(function(row) {
            var sel = row.querySelector('.execute-inventory-select');
            var qtyInput = row.querySelector('.execute-quantity-input');
            // Compare against total selected quantity for this input (regardless of "expected vs unexpected" inventory),
            // since "unexpected selection" is already handled by a separate warning.
            if (sel && sel.value && qtyInput) {
              var v = parseFloat(qtyInput.value);
              if (!isNaN(v) && v > 0) totalExpectedQty += v;
            }
          });
          var fmt = function(n) { return Number(n.toFixed(3)); };
          var unit = (input.unit || '').trim() || 'units';
          if (totalExpectedQty < expectedNum) {
            var moreNeeded = expectedNum - totalExpectedQty;
            qtyWarningEl.textContent = fmt(moreNeeded) + ' ' + unit + ' more needed to meet expected quantity (' + fmt(expectedNum) + ' ' + unit + ') for this input.';
            qtyWarningEl.style.display = 'block';
          } else if (totalExpectedQty > expectedNum) {
            var over = totalExpectedQty - expectedNum;
            qtyWarningEl.textContent = fmt(over) + ' ' + unit + ' over expected quantity (' + fmt(expectedNum) + ' ' + unit + ') for this input.';
            qtyWarningEl.style.display = 'block';
          } else {
            qtyWarningEl.style.display = 'none';
            qtyWarningEl.textContent = '';
          }
        }

        function updateUnexpectedMaterialWarning() {
          var unexpectedEl = inputSection.querySelector('.execute-input-unexpected-material-warning');
          var hasUnexpected = false;
          inputSection.querySelectorAll('.execute-input-row').forEach(function(row) {
            var sel = row.querySelector('.execute-inventory-select');
            if (sel && sel.value) {
              var inv = sel.value ? inventoryById.get(String(sel.value)) : null;
              if (inv && isUnexpectedItem(inv)) hasUnexpected = true;
            }
            updateRowUnexpectedWarning(row);
          });
          if (unexpectedEl) {
            if (hasUnexpected) {
              unexpectedEl.textContent = 'Warning - one or more selections are not the expected input for this step';
              unexpectedEl.style.display = 'block';
            } else {
              unexpectedEl.style.display = 'none';
              unexpectedEl.textContent = '';
            }
          }
        }

        function setRowSelection(rowEl, invId) {
          if (!rowEl) return;
          const hiddenInput = rowEl.querySelector('.execute-inventory-select');
          const quantityInput = rowEl.querySelector('.execute-quantity-input');
          const unitDisplay = rowEl.querySelector('.execute-quantity-unit-display');
          const expiredWarningEl = rowEl.querySelector('.execute-input-expired-warning');
          const selectedCardEl = rowEl.querySelector('.execute-selected-inv-card');
          const qtyPane = rowEl.querySelector('.execute-qty-pane');
          if (!hiddenInput) return;
          var stateKey = rowEl.dataset.stateKey || '';
          var st = stateKey ? ses.inputStateByKey.get(stateKey) : null;
          hiddenInput.value = invId || '';
          hiddenInput.dataset.quantity = '';
          hiddenInput.dataset.unit = '';
          hiddenInput.dataset.expiredReason = '';

          // Always clear warning when changing selection; only show if the selected item needs it.
          if (expiredWarningEl) { expiredWarningEl.style.display = 'none'; expiredWarningEl.textContent = ''; }

          if (!invId) {
            if (selectedCardEl) { selectedCardEl.style.display = 'none'; selectedCardEl.innerHTML = ''; }
            if (qtyPane) qtyPane.style.display = 'none';
            if (unitDisplay && quantityInput) {
              unitDisplay.textContent = quantityInput.dataset.stepUnit || input.unit || '';
              quantityInput.value = input.quantity || '';
              quantityInput.dataset.originalQuantity = input.quantity || '';
              quantityInput.dataset.inventoryUnit = '';
            }
            if (st) {
              st.inventory_item_id = '';
              st.unit = (quantityInput && (quantityInput.dataset.stepUnit || input.unit)) || (input.unit || '');
              st.expired_reason = '';
              var qv = quantityInput ? parseFloat(quantityInput.value) : NaN;
              st.quantity = isNaN(qv) ? 0 : qv;
            }
            updateSectionQtyExpectedWarning();
            updateUnexpectedMaterialWarning();
            return;
          }
          const inv = invId ? inventoryById.get(String(invId)) : null;
          if (inv && unitDisplay && quantityInput) {
            // Prefill should follow the step definition expected quantity (operator-friendly),
            // not "available inventory quantity".
            var expectedQty = parseFloat(input.quantity);
            if (!isNaN(expectedQty) && expectedQty > 0) {
              quantityInput.value = String(expectedQty);
            } else if (!quantityInput.value) {
              quantityInput.value = input.quantity || '';
            }
            // Keep display unit as the step unit if available; inventory unit remains for validation.
            unitDisplay.textContent = (quantityInput.dataset.stepUnit || input.unit || inv.unit || '');
            quantityInput.dataset.inventoryUnit = inv.unit || '';
          }
          if (inv) {
            hiddenInput.dataset.quantity = inv.quantity != null ? String(inv.quantity) : '';
            hiddenInput.dataset.unit = inv.unit || '';
            const reason = getExpiredReason(inv.id);
            hiddenInput.dataset.expiredReason = reason || '';
            if (st) {
              st.inventory_item_id = String(inv.id);
              st.unit = (quantityInput && (quantityInput.dataset.stepUnit || input.unit)) || (input.unit || inv.unit || '');
              st.expired_reason = reason || '';
              var q = quantityInput ? parseFloat(quantityInput.value) : NaN;
              st.quantity = isNaN(q) ? 0 : q;
            }
            if (reason && expiredWarningEl) {
              expiredWarningEl.textContent = 'Check: ' + reason;
              expiredWarningEl.style.display = 'block';
            }
            if (selectedCardEl) {
              function fmtDate(raw) {
                if (!raw) return '';
                try { return new Date(raw).toLocaleDateString(); } catch (e) { return String(raw); }
              }
              var meta = [];
              if (inv.supplier) meta.push('<div><span style="color:var(--text-tertiary,#9ca3af); font-size:12px;">Supplier</span><div style="font-weight:600;">' + escapeHtml(inv.supplier) + '</div></div>');
              var batchAny = inv.supplier_batch_number || inv.batch_number || inv.lot_number || '';
              if (batchAny) meta.push('<div><span style="color:var(--text-tertiary,#9ca3af); font-size:12px;">Batch</span><div style="font-weight:600;">' + escapeHtml(batchAny) + '</div></div>');
              var operatorAny = inv.operator_name || inv.operator || '';
              if (operatorAny) meta.push('<div><span style="color:var(--text-tertiary,#9ca3af); font-size:12px;">Operator</span><div style="font-weight:600;">' + escapeHtml(operatorAny) + '</div></div>');
              var createdByAny = inv.created_by_name || inv.created_by || '';
              if (createdByAny) meta.push('<div><span style="color:var(--text-tertiary,#9ca3af); font-size:12px;">Created by</span><div style="font-weight:600;">' + escapeHtml(createdByAny) + '</div></div>');
              if (inv.purchase_date) meta.push('<div><span style="color:var(--text-tertiary,#9ca3af); font-size:12px;">Purchase date</span><div style="font-weight:600;">' + escapeHtml(fmtDate(inv.purchase_date)) + '</div></div>');
              if (inv.expiry_date) meta.push('<div><span style="color:var(--text-tertiary,#9ca3af); font-size:12px;">Expiry date</span><div style="font-weight:600;">' + escapeHtml(fmtDate(inv.expiry_date)) + '</div></div>');
              if (inv.ready_date) meta.push('<div><span style="color:var(--text-tertiary,#9ca3af); font-size:12px;">Ready date</span><div style="font-weight:600;">' + escapeHtml(fmtDate(inv.ready_date)) + '</div></div>');
              if (inv.created_at) meta.push('<div><span style="color:var(--text-tertiary,#9ca3af); font-size:12px;">Created</span><div style="font-weight:600;">' + escapeHtml(fmtDate(inv.created_at)) + '</div></div>');
              selectedCardEl.innerHTML =
                '<div style="display:flex; align-items:flex-start; justify-content:space-between; gap:12px;">' +
                  '<div style="min-width:0;">' +
                    '<div style="font-size:14px; font-weight:700; color:var(--text-primary,#111827);">' + escapeHtml(inv.name || 'Selected item') + '</div>' +
                    '<div style="font-size:12px; color:var(--text-secondary,#6b7280); margin-top:4px;">' + escapeHtml((inv.process_name ? (inv.process_name + ' · ') : '') + fmtQty(inv)) + '</div>' +
                  '</div>' +
                  (reason ? ('<div class="exec-picker-chip exec-picker-chip--warn" style="flex-shrink:0;">' + escapeHtml(reason) + '</div>') : '') +
                '</div>' +
                (meta.length ? ('<div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin-top:12px;">' + meta.join('') + '</div>') : '');
              selectedCardEl.style.display = 'block';
            }
            if (qtyPane) qtyPane.style.display = 'block';
          }
          if (quantityInput) quantityInput.style.border = '1px solid var(--border-default, #e5e7eb)';
          updateSectionQtyExpectedWarning();
          updateUnexpectedMaterialWarning();
        }

        const firstRow = createInputRow(true);
        rowsContainer.appendChild(firstRow);

        const hiddenInput = firstRow.querySelector('.execute-inventory-select');
        const quantityInput = firstRow.querySelector('.execute-quantity-input');
        const unitDisplay = firstRow.querySelector('.execute-quantity-unit-display');
        const triggerLabel = firstRow.querySelector('.execute-inventory-picker-label');
        const expiredWarningEl = firstRow.querySelector('.execute-input-expired-warning');

        function getInventorySelectionLabel(invId) {
          if (!invId) return 'Select inventory item...';
          const inv = inventoryById.get(String(invId));
          if (!inv) return 'Select inventory item...';
          const productName = inv.process_name ? escapeHtml(inv.process_name) + ' - ' + escapeHtml(inv.name) : escapeHtml(inv.name);
          return productName + ' - ' + (inv.quantity != null ? inv.quantity : '') + ' ' + (inv.unit || '');
        }

        // Always-on card picker: clicking a row makes it active; clicking a card assigns selection to the active row.
        function setActiveRow(rowEl) {
          if (!rowEl) return;
          ses.editingInputRow = rowEl;
          inputSection.querySelectorAll('.execute-input-row').forEach(function(r) {
            r.classList.toggle('execute-input-row--active', r === rowEl);
          });

          // If the active row is already confirmed, keep picker hidden to reduce noise.
          try {
            var locked = rowEl.getAttribute('data-selection-locked') === 'true';
            var sel = rowEl.querySelector('.execute-inventory-select');
            var hasSel = Boolean(sel && sel.value);
            if (pickerPanel) pickerPanel.style.display = (locked && hasSel) ? 'none' : 'block';
          } catch (e) {}
        }
        function getSelectedInventoryIdsExcludingRow(excludeRowEl) {
          var ids = new Set();
          inputSection.querySelectorAll('.execute-input-row').forEach(function(row) {
            if (row === excludeRowEl) return;
            var sel = row.querySelector('.execute-inventory-select');
            if (sel && sel.value) ids.add(String(sel.value));
          });
          return ids;
        }
        function createCardForInv(inv) {
          var id = String(inv.id);
          var card = document.createElement('div');
          card.className = 'execute-inventory-input-card card card-interactive execute-reconcile-untracked-card';
          card.dataset.inventoryId = id;
          var searchParts = [inv.name, inv.process_name, inv.unit, inv.supplier, inv.supplier_batch_number].filter(Boolean);
          card.dataset.searchText = (searchParts.join(' ') || '').toLowerCase();
          card.style.cssText = 'margin-bottom: 0; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s; overflow: hidden;';
          var createdStr = '';
          if (inv.created_at) {
            try { createdStr = new Date(inv.created_at).toLocaleDateString(); } catch (e) {}
          }
          var subtitleParts = [];
          subtitleParts.push(escapeHtml(inv.quantity != null ? String(inv.quantity) : '0') + ' ' + escapeHtml(inv.unit || ''));
          if (inv.process_name) subtitleParts.push(escapeHtml(inv.process_name));
          var subtitleLine = subtitleParts.join(' · ');
          var detailsParts = [];
          if (inv.quantity != null) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Quantity</span> ' + escapeHtml(String(inv.quantity)) + ' ' + escapeHtml(inv.unit || '') + '</p>');
          if (inv.process_name) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Process</span> ' + escapeHtml(inv.process_name) + '</p>');
          if (createdStr) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Created</span> ' + escapeHtml(createdStr) + '</p>');
          if (inv.supplier) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Supplier</span> ' + escapeHtml(inv.supplier) + '</p>');
          if (inv.supplier_batch_number) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Batch</span> ' + escapeHtml(inv.supplier_batch_number) + '</p>');
          var promptsHtml = '';
          if (inv.extra_data && inv.extra_data.execution_prompts && typeof inv.extra_data.execution_prompts === 'object') {
            var prompts = inv.extra_data.execution_prompts;
            promptsHtml = '<div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-default);"><div style="font-size: 11px; font-weight: 600; color: var(--text-secondary); margin-bottom: 8px;">Step metadata</div><div style="display: flex; flex-direction: column; gap: 6px;">' +
              Object.entries(prompts).map(function(e) {
                return '<div style="padding: 6px 10px; background: var(--bg-secondary, #f9fafb); border-radius: 6px;"><span style="color: var(--text-secondary); font-size: 11px;">' + escapeHtml(e[0]) + '</span><br><span style="color: var(--text-primary); font-size: 13px;">' + escapeHtml(String(e[1])) + '</span></div>';
              }).join('') + '</div></div>';
          }
          var reason = getExpiredReason(inv.id);
          var titlePrefix = reason ? '⚠ ' + escapeHtml(reason) + ': ' : '';
          card.innerHTML =
            '<div class="process-card-header" style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; word-wrap: break-word; overflow-wrap: break-word;">' +
              '<div style="flex: 1; min-width: 0; cursor: pointer;" data-expand-trigger="1">' +
                '<h4 style="margin: 0; font-size: 14px; font-weight: 600; color: var(--text-primary);">' + titlePrefix + escapeHtml(inv.name || 'Unknown') + '</h4>' +
                '<p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-secondary);">' + subtitleLine + '</p>' +
              '</div>' +
              '<svg class="execute-reconcile-arrow" id="execute-inv-arrow-' + safeInputName + '-' + id + '" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink: 0; cursor: pointer; transform: rotate(0deg); transition: transform 0.2s;" data-expand-trigger="1">' +
                '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>' +
              '</svg>' +
            '</div>' +
            '<div class="execute-reconcile-details" id="execute-inv-details-' + safeInputName + '-' + id + '" style="display: none; padding: 12px 16px; border-top: 1px solid var(--border-default); background: var(--bg-secondary, #f9fafb); font-size: 13px;">' +
              detailsParts.join('') + promptsHtml +
            '</div>';
          card.onclick = function(e) {
            if (e.target.closest('[data-expand-trigger="1"]')) {
              e.stopPropagation();
              toggleInventoryCardDetails(id);
              return;
            }
            setRowSelection(ses.editingInputRow || firstRow, id);
          };
          return card;
        }

        function appendSectionHeader(container, title) {
          var h = document.createElement('div');
          h.className = 'execute-inventory-dropdown-section-header';
          h.style.cssText = 'font-size: 11px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em; margin: 12px 0 6px 0; padding: 0 4px;';
          h.textContent = title;
          container.appendChild(h);
        }

        function filterAddAnotherDropdown() {
          var searchEl = dropdown ? dropdown.querySelector('.execute-addanother-search') : null;
          if (!cardsContainer || !searchEl) return;
          var searchVal = (searchEl.value || '').trim().toLowerCase();
          var selectedElsewhere = ses.editingInputRow ? getSelectedInventoryIdsExcludingRow(ses.editingInputRow) : new Set();
          var children = cardsContainer.children;
          for (var i = 0; i < children.length; i++) {
            var el = children[i];
            if (el.classList.contains('execute-inventory-dropdown-section-header')) continue;
            if (el.classList.contains('execute-inventory-input-card')) {
              var id = el.dataset.inventoryId;
              if (id === '' || id === undefined) {
                el.style.display = '';
                continue;
              }
              if (selectedElsewhere.has(id)) {
                el.style.display = 'none';
                continue;
              }
              var text = (el.dataset.searchText || '');
              el.style.display = !searchVal || (text && text.indexOf(searchVal) !== -1) ? '' : 'none';
            }
          }
          for (var i = 0; i < children.length; i++) {
            var el = children[i];
            if (!el.classList.contains('execute-inventory-dropdown-section-header')) continue;
            var hasVisible = false;
            for (var j = i + 1; j < children.length; j++) {
              var next = children[j];
              if (next.classList.contains('execute-inventory-dropdown-section-header')) break;
              if (next.classList.contains('execute-inventory-input-card') && next.dataset.inventoryId && next.style.display !== 'none') {
                hasVisible = true;
                break;
              }
            }
            el.style.display = hasVisible ? '' : 'none';
          }
        }

        function ensureAddAnotherSearchRow(show) {
          var wrap = dropdown ? dropdown.querySelector('.execute-addanother-search-wrap') : null;
          if (show) {
            if (!wrap) {
              wrap = document.createElement('div');
              wrap.className = 'execute-addanother-search-wrap';
              wrap.style.cssText = 'flex-shrink: 0; padding: 0 0 8px 0; border-bottom: 1px solid var(--border-default, #e5e7eb); margin-bottom: 8px;';
              var inp = document.createElement('input');
              inp.type = 'text';
              inp.className = 'execute-addanother-search';
              inp.placeholder = 'Type to filter…';
              inp.autocomplete = 'off';
              inp.style.cssText = 'width: 100%; box-sizing: border-box; padding: 6px 10px; border: 1px solid var(--border-default); border-radius: var(--radius-md); font-size: 13px; background: var(--bg-card); color: var(--text-primary);';
              inp.addEventListener('input', filterAddAnotherDropdown);
              inp.addEventListener('click', function(e) { e.stopPropagation(); });
              wrap.appendChild(inp);
              dropdown.insertBefore(wrap, cardsContainer);
              dropdown.style.display = 'flex';
              dropdown.style.flexDirection = 'column';
              dropdown.style.height = '320px';
              dropdown.style.overflow = 'hidden';
              dropdown.style.overflowY = '';
              cardsContainer.style.flex = '1';
              cardsContainer.style.minHeight = '0';
              cardsContainer.style.overflowY = 'auto';
            }
            for (var c = 0; c < cardsContainer.children.length; c++) {
              cardsContainer.children[c].style.flexShrink = '0';
            }
            var inp = wrap.querySelector('.execute-addanother-search');
            if (inp) {
              inp.value = '';
              filterAddAnotherDropdown();
              setTimeout(function() { inp.focus(); }, 0);
            }
          } else {
            if (wrap) {
              wrap.remove();
              dropdown.style.display = 'block';
              dropdown.style.height = '';
              dropdown.style.overflowY = 'auto';
              dropdown.style.flex = '';
              dropdown.style.flexDirection = '';
              cardsContainer.style.flex = '';
              cardsContainer.style.minHeight = '';
              cardsContainer.style.overflowY = '';
            }
          }
        }

        function populateDropdownContent(rowEl) {
          if (!cardsContainer) return;
          cardsContainer.innerHTML = '';
          var isFirstRow = rowsContainer && rowsContainer.firstElementChild === rowEl;
          var noneCard = document.createElement('div');
          noneCard.className = 'execute-inventory-input-card execute-reconcile-untracked-card';
          noneCard.dataset.inventoryId = '';
          noneCard.style.cssText = 'padding: 10px 14px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s;';
          noneCard.innerHTML = '<span style="color: var(--text-secondary); font-size: 13px;">— None —</span>';
          noneCard.onclick = function(e) { e.stopPropagation(); setRowSelection(ses.editingInputRow || rowEl, ''); };
          cardsContainer.appendChild(noneCard);
          if (isFirstRow) {
            sortedInventory.forEach(function(inv) {
              cardsContainer.appendChild(createCardForInv(inv));
            });
          } else {
            var matchingName = allInventory.filter(function(inv) { return nameMatchesExact(inv.name); });
            var matchingIds = new Set(matchingName.map(function(i) { return String(i.id); }));
            var others = allInventory.filter(function(inv) { return !matchingIds.has(String(inv.id)); });
            if (matchingName.length > 0) {
              appendSectionHeader(cardsContainer, 'Expected: ' + (input.name || ''));
              matchingName.forEach(function(inv) {
                cardsContainer.appendChild(createCardForInv(inv));
              });
            }
            var raw = others.filter(function(inv) { return (inv.inventory_type || 'raw_material') === 'raw_material'; });
            var wip = others.filter(function(inv) { return inv.inventory_type === 'work_in_progress'; });
            var fin = others.filter(function(inv) { return inv.inventory_type === 'final_product'; });
            if (raw.length > 0) {
              appendSectionHeader(cardsContainer, 'Raw materials');
              raw.forEach(function(inv) { cardsContainer.appendChild(createCardForInv(inv)); });
            }
            if (wip.length > 0) {
              appendSectionHeader(cardsContainer, 'Intermediate');
              wip.forEach(function(inv) { cardsContainer.appendChild(createCardForInv(inv)); });
            }
            if (fin.length > 0) {
              appendSectionHeader(cardsContainer, 'Final products');
              fin.forEach(function(inv) { cardsContainer.appendChild(createCardForInv(inv)); });
            }
          }
        }

        // Picker is always visible; keep tab/search predictable once on init.
        if (pickerSearch) pickerSearch.value = '';
        pickerState.q = '';
        syncTabState(defaultPickerType);

        function toggleInventoryCardDetails(cardId) {
          var details = inputSection.querySelector('#execute-inv-details-' + safeInputName + '-' + cardId);
          var arrow = inputSection.querySelector('#execute-inv-arrow-' + safeInputName + '-' + cardId);
          if (!details || !arrow) return;
          var isExpanded = details.style.display === 'block';
          details.style.display = isExpanded ? 'none' : 'block';
          arrow.style.transform = isExpanded ? 'rotate(0deg)' : 'rotate(90deg)';
        }

        // Row activation
        firstRow.addEventListener('click', function() { setActiveRow(firstRow); });
        setActiveRow(firstRow);

        // Always start with neutral borders (avoid stale validation styles).
        inputSection.querySelectorAll('.execute-quantity-input').forEach(function(inp) {
          if (inp) inp.style.border = '1px solid var(--border-default, #e5e7eb)';
        });

        if (quantityInput) {
          if (!quantityInput.dataset.originalQuantity || quantityInput.dataset.originalQuantity === '' || quantityInput.dataset.originalQuantity === 'undefined') {
            quantityInput.dataset.originalQuantity = input.quantity || quantityInput.value || '0';
          }
          quantityInput.addEventListener('input', function() {
            if (parseFloat(this.value) > 0) this.style.border = '1px solid var(--border-default, #e5e7eb)';
            updateSectionQtyExpectedWarning();
            updateUnexpectedMaterialWarning();
          });
        }

        var addAnotherBtn = inputSection.querySelector('.execute-add-another-input-btn');
        if (addAnotherBtn) {
          addAnotherBtn.addEventListener('click', function() {
            var newRow = createInputRow(false);
            rowsContainer.appendChild(newRow);
            newRow.addEventListener('click', function() { setActiveRow(newRow); });
            // Immediately activate the new row, otherwise selection remains locked to previous row.
            setActiveRow(newRow);
            var qInput = newRow.querySelector('.execute-quantity-input');
            if (qInput) {
              qInput.addEventListener('input', function() {
                if (parseFloat(this.value) > 0) this.style.border = '1px solid var(--border-default, #e5e7eb)';
                updateSectionQtyExpectedWarning();
                updateUnexpectedMaterialWarning();
              });
            }
            // remove handler already attached in createInputRow
            renderPickerCards(pickerState.activeType, pickerState.q);
          });
        }
        
        // Add Missing Item: fromOutput = from previous output; else raw material modal
        const addMissingBtn = inputSection.querySelector('.add-missing-item-btn');
        if (addMissingBtn) {
          addMissingBtn.addEventListener('click', function() {
            var fromOutput = Boolean(this.dataset.sourceOutputId || this.dataset.sourceStepId || this.dataset.sourceProcessId);
            var sourceOutputId = this.dataset.sourceOutputId || '';
            var name_ = this.dataset.inputName || '';
            var quantity_ = this.dataset.inputQuantity != null && this.dataset.inputQuantity !== '' ? this.dataset.inputQuantity : '';
            var unit_ = this.dataset.inputUnit || '';
            if (fromOutput && window.openAddUntrackedOutputModal) {
              window.addInventoryContext = { fromExecutionModal: true, inputName: name_ };
              window.openAddUntrackedOutputModal(
                { name: name_, quantity: quantity_, unit: unit_, id: sourceOutputId || undefined },
                modal.dataset.executionId,
                modal.dataset.executionStepId
              );
              var untrackedModal = document.getElementById('add-untracked-output-modal');
              if (untrackedModal) untrackedModal.style.zIndex = '1001';
            } else if (!fromOutput && window.openAddInventoryModalForMissingInput) {
              window.openAddInventoryModalForMissingInput({ name: name_, quantity: quantity_, unit: unit_ });
            }
          });
        }
        
        inputsContainer.appendChild(inputSection);
      });

  }

  /**
   * Variable inputs that do not use inventory: confirm quantity + unit at execution.
   * @param {{ inputsContainer: HTMLElement | null, confirmInputs: Array<unknown>, escapeHtml: (s: string) => string }} ctx
   */
  function renderConfirmExecutionInputs(ctx) {
    var inputsContainer = ctx.inputsContainer;
    var confirmInputs = ctx.confirmInputs;
    var escapeHtml = ctx.escapeHtml;
    if (!confirmInputs || !confirmInputs.length || !inputsContainer) return;
    confirmInputs.forEach(function (input) {
      const inputSection = document.createElement('div');
      inputSection.className = 'execute-input-section';
      inputSection.style.cssText =
        'margin-bottom: 20px; padding: 16px; border: 1px solid var(--border-light); border-radius: var(--radius-md);';

      inputSection.innerHTML = `
          <div style="margin-bottom: 12px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">
              ${escapeHtml(input.name)} 
              <span style="color: var(--text-secondary); font-weight: normal;">(Expected: ${input.quantity || '0'} ${input.unit || ''})</span>
              <span style="color: var(--error, #ef4444);">*</span>
            </label>
          </div>
          <div style="margin-bottom: 12px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">Quantity <span style="color: var(--error, #ef4444);">*</span></label>
            <input type="number" class="spa-inp execute-confirm-quantity-input" data-input-name="${escapeHtml(input.name)}" data-required="true" placeholder="${input.quantity || '0'}" value="${input.quantity || ''}" step="0.01" min="0">
          </div>
          <div>
            <label style="display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">Unit <span style="color: var(--error, #ef4444);">*</span></label>
            <select class="spa-inp execute-confirm-unit-input" data-input-name="${escapeHtml(input.name)}" data-required="true">
              <option value="">Select unit...</option>
              ${['kg', 'g', 'mg', 'lb', 'oz', 'ton', 'tonne', 'l', 'ml', 'gal', 'm3', 'ft3', 'm', 'cm', 'mm', 'ft', 'in', 'units', 'pcs', 'pieces', 'boxes', 'pallets', 'containers'].map((unit) => `
                <option value="${unit}" ${input.unit === unit ? 'selected' : ''}>${unit}</option>
              `).join('')}
            </select>
          </div>
        `;

      const quantityInput = inputSection.querySelector('.execute-confirm-quantity-input');
      const unitSelect = inputSection.querySelector('.execute-confirm-unit-input');

      if (quantityInput) {
        quantityInput.addEventListener('input', function () {
          if (this.value && parseFloat(this.value) > 0) {
            this.style.border = '';
          }
        });
      }

      if (unitSelect) {
        unitSelect.addEventListener('change', function () {
          if (this.value) {
            this.style.border = '';
          }
        });
      }

      inputsContainer.appendChild(inputSection);
    });
  }

  root.ExecutionRenderInputs = {
    renderVariableInventoryInputs: renderVariableInventoryInputs,
    renderConfirmExecutionInputs: renderConfirmExecutionInputs,
  };
})(typeof window !== "undefined" ? window : this);
