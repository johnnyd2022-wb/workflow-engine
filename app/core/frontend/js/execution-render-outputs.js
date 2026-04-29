/**
 * Variable output quantity + untracked reconciliation UI for execute-step.
 * Depends on CoreAPI.getMatchingUntracked, escapeHtml, window render helpers for expiry/ready date.
 * Load before execution-modal.js — exposes window.ExecutionRenderOutputs.
 */
(function (root) {
  'use strict';

  async function renderVariableOutputs(ctx) {
    var modal = ctx.modal;
    var outputsContainer = ctx.outputsContainer;
    var stepDefinition = ctx.stepDefinition;
    var untrackedItems = ctx.untrackedItems;
    var escapeHtml = ctx.escapeHtml;
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
    const currentExecutionId = modal.dataset.executionId;
    if (CoreAPI && variableOutputs.length > 0 && currentExecutionId && typeof CoreAPI.getMatchingUntracked === 'function') {
      try {
        const results = await Promise.all(
          variableOutputs.map(function(o) {
            var name = (o.name && String(o.name).trim()) || '';
            var unit = (o.unit && String(o.unit).trim()) || 'units';
            return CoreAPI.getMatchingUntracked(name, unit, null, currentExecutionId);
          })
        );
        matchingUntrackedPerOutput = results.map(function(r) { return (r && r.matching_untracked) ? r.matching_untracked : []; });
      } catch (e) {
        console.warn('Could not fetch matching untracked per output', e);
      }
    }

    if (variableOutputs.length > 0 && outputsContainer) {
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
            <div class="execute-reconcile-untracked-wrapper" data-output-id="${escapeHtml(outputId)}" style="display: ${hasMatch ? 'block' : 'none'}; margin-top: 12px; padding: 12px 16px; background: hsl(42, 93%, 96%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); font-size: 13px; position: relative;">
              <input type="hidden" class="execute-reconcile-untracked-value" data-output-id="${escapeHtml(outputId)}" value="${escapeHtml(defaultId)}">
              <label style="display: block; font-weight: 600; color: #92400e; margin-bottom: 8px;">Reconcile to untracked item (optional)</label>
              <p style="margin: 0 0 8px 0; color: #92400e; font-size: 12px;">Choose an item from the dropdown to reconcile when you complete the step.</p>
              <div class="execute-reconcile-untracked-trigger" role="button" tabindex="0" style="display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 10px 14px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 14px; cursor: pointer; min-height: 44px;">
                <span class="execute-reconcile-trigger-label" style="flex: 1; text-align: left; min-width: 0;">— None —</span>
                <span class="execute-reconcile-trigger-arrow-box" style="flex-shrink: 0; margin-left: 8px; display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: var(--radius-md, 6px); border: 1px solid var(--border-default); background: var(--bg-secondary, #f9fafb); color: var(--text-secondary);">
                  <svg class="execute-reconcile-trigger-arrow" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="transition: transform 0.2s;"><polyline points="6 9 12 15 18 9"/></svg>
                </span>
              </div>
              <div class="execute-reconcile-untracked-dropdown" style="display: none; position: absolute; top: 100%; left: 0; right: 0; z-index: 100; margin-top: 6px; max-height: 320px; overflow-y: auto; background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); box-shadow: 0 10px 25px rgba(0,0,0,0.15); padding: 8px;">
                <div class="execute-reconcile-untracked-cards" style="display: flex; flex-direction: column; gap: 8px;"></div>
              </div>
            </div>
          </div>
        `;
        outputsContainer.appendChild(outputSection);

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

        if (hasMatch) {
          var wrapper = outputSection.querySelector('.execute-reconcile-untracked-wrapper');
          var trigger = outputSection.querySelector('.execute-reconcile-untracked-trigger');
          var triggerLabel = outputSection.querySelector('.execute-reconcile-trigger-label');
          var triggerArrow = outputSection.querySelector('.execute-reconcile-trigger-arrow');
          var dropdown = outputSection.querySelector('.execute-reconcile-untracked-dropdown');
          var cardsContainer = outputSection.querySelector('.execute-reconcile-untracked-cards');
          var hiddenInput = outputSection.querySelector('.execute-reconcile-untracked-value');
          var safeId = function(s) { return String(s).replace(/\s+/g, '-').replace(/[^a-zA-Z0-9-]/g, '').slice(0, 40); };
          var detailId = function(uOrId) { var id = typeof uOrId === 'string' ? uOrId : (uOrId && uOrId.id); return 'execute-reconcile-details-' + safeId(outName) + '-' + id; };
          var arrowId = function(uOrId) { var id = typeof uOrId === 'string' ? uOrId : (uOrId && uOrId.id); return 'execute-reconcile-arrow-' + safeId(outName) + '-' + id; };

          function getSelectionLabel(id) {
            if (!id) return '— None —';
            var u = matchingUntracked.find(function(x) { return String(x.id) === id; });
            if (!u) return '— None —';
            var qtyLabel = (u.remaining_balance_to_reconcile != null && String(u.remaining_balance_to_reconcile).trim() !== '') ? 'Unreconciled: ' + u.remaining_balance_to_reconcile : (u.quantity != null ? u.quantity : '0');
            return (u.name || 'Unknown') + ' · ' + qtyLabel + ' ' + (u.unit || '');
          }

          function closeDropdown() {
            dropdown.style.display = 'none';
            if (triggerArrow) triggerArrow.style.transform = '';
            document.removeEventListener('click', closeDropdownOutside);
          }
          function closeDropdownOutside(e) {
            if (wrapper && !wrapper.contains(e.target)) closeDropdown();
          }
          function openDropdown() {
            dropdown.style.display = 'block';
            if (triggerArrow) triggerArrow.style.transform = 'rotate(180deg)';
            setTimeout(function() { document.addEventListener('click', closeDropdownOutside); }, 0);
          }
          function toggleDropdown() {
            var isOpen = dropdown.style.display === 'block';
            if (isOpen) closeDropdown(); else openDropdown();
          }
          trigger.addEventListener('click', function(e) { e.stopPropagation(); toggleDropdown(); });
          trigger.addEventListener('keydown', function(e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleDropdown(); } });
          dropdown.addEventListener('click', function(e) { e.stopPropagation(); });

          function setSelection(selectedId) {
            hiddenInput.value = selectedId || '';
            triggerLabel.textContent = getSelectionLabel(selectedId);
            wrapper.querySelectorAll('.execute-reconcile-untracked-card').forEach(function(c) {
              var id = c.dataset.untrackedId || '';
              var selected = id === selectedId;
              c.classList.toggle('execute-reconcile-card-selected', selected);
              c.style.borderColor = selected ? 'var(--warning, #f59e0b)' : '';
              c.style.boxShadow = selected ? '0 0 0 2px rgba(245, 158, 11, 0.25)' : '';
            });
            closeDropdown();
          }

          function toggleCardDetails(itemId) {
            var details = outputSection.querySelector('#' + detailId(itemId));
            var arrow = outputSection.querySelector('#' + arrowId(itemId));
            if (!details || !arrow) return;
            var isExpanded = details.style.display === 'block';
            details.style.display = isExpanded ? 'none' : 'block';
            arrow.style.transform = isExpanded ? 'rotate(0deg)' : 'rotate(90deg)';
          }

          var noneCard = document.createElement('div');
          noneCard.className = 'execute-reconcile-untracked-card' + (defaultId ? '' : ' execute-reconcile-card-selected');
          noneCard.dataset.untrackedId = '';
          noneCard.style.cssText = 'padding: 10px 14px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s;';
          noneCard.innerHTML = '<span style="color: var(--text-secondary); font-size: 13px;">— None —</span>';
          noneCard.onclick = function(e) { e.stopPropagation(); setSelection(''); };
          cardsContainer.appendChild(noneCard);

          matchingUntracked.forEach(function(u) {
            var id = String(u.id);
            var card = document.createElement('div');
            card.className = 'execute-reconcile-untracked-card card card-interactive' + (id === defaultId ? ' execute-reconcile-card-selected' : '');
            card.dataset.untrackedId = id;
            card.style.cssText = 'margin-bottom: 0; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s; overflow: hidden;';
            var createdStr = '';
            if (u.created_at) {
              try { createdStr = new Date(u.created_at).toLocaleDateString(); } catch (e) {}
            }
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
            var promptsHtml = '';
            if (u.source_step_execution_prompts && typeof u.source_step_execution_prompts === 'object' && Object.keys(u.source_step_execution_prompts).length > 0) {
              promptsHtml = '<div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-default);"><div style="font-size: 11px; font-weight: 600; color: var(--text-secondary); margin-bottom: 8px;">Step metadata</div><div style="display: flex; flex-direction: column; gap: 6px;">' +
                Object.entries(u.source_step_execution_prompts).map(function(e) {
                  return '<div style="padding: 6px 10px; background: var(--bg-secondary, #f9fafb); border-radius: 6px;"><span style="color: var(--text-secondary); font-size: 11px;">' + escapeHtml(e[0]) + '</span><br><span style="color: var(--text-primary); font-size: 13px;">' + escapeHtml(String(e[1])) + '</span></div>';
                }).join('') + '</div></div>';
            }
            var detailsParts = [];
            if (unreconciledQty !== null) {
              detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Unreconciled quantity</span> ' + escapeHtml(unreconciledQty) + ' ' + escapeHtml(u.unit || '') + '</p>');
            }
            if (u.process_name) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Process</span> ' + escapeHtml(u.process_name) + '</p>');
            if (u.producing_step_name) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Step to execute to reconcile</span> ' + escapeHtml(u.producing_step_name) + '</p>');
            else if (u.step_name) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Step</span> ' + escapeHtml(u.step_name) + '</p>');
            if (createdStr) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Created</span> ' + escapeHtml(createdStr) + '</p>');
            if (u.notes) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Notes</span> ' + escapeHtml(u.notes) + '</p>');
            if (u.supplier) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Supplier</span> ' + escapeHtml(u.supplier) + '</p>');
            if (u.supplier_batch_number) detailsParts.push('<p style="margin: 0 0 6px 0;"><span style="color: var(--text-secondary);">Batch</span> ' + escapeHtml(u.supplier_batch_number) + '</p>');
            card.innerHTML =
              '<div class="process-card-header" style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; word-wrap: break-word; overflow-wrap: break-word;">' +
                '<div style="flex: 1; min-width: 0; cursor: pointer;" data-expand-trigger="1">' +
                  '<h4 style="margin: 0; font-size: 14px; font-weight: 600; color: var(--text-primary);">' + escapeHtml(u.name || 'Unknown') + '</h4>' +
                  '<p style="margin: 4px 0 0 0; font-size: 12px; color: var(--text-secondary);">' + subtitleLine + '</p>' +
                '</div>' +
                '<svg class="execute-reconcile-arrow" id="' + arrowId(u) + '" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink: 0; cursor: pointer; transform: rotate(0deg); transition: transform 0.2s;" data-expand-trigger="1">' +
                  '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>' +
                '</svg>' +
              '</div>' +
              '<div class="execute-reconcile-details" id="' + detailId(u) + '" style="display: none; padding: 12px 16px; border-top: 1px solid var(--border-default); background: var(--bg-secondary, #f9fafb); font-size: 13px;">' +
                detailsParts.join('') +
                promptsHtml +
              '</div>';
            card.onclick = function(e) {
              if (e.target.closest('[data-expand-trigger="1"]')) {
                e.stopPropagation();
                toggleCardDetails(id);
                return;
              }
              setSelection(id);
            };
            cardsContainer.appendChild(card);
          });
          setSelection(defaultId);
        }
      });
    } else if (outputsContainer) {
      outputsContainer.innerHTML = '<p style="color: var(--text-secondary); font-size: 14px; padding: 16px;">No variable outputs for this step.</p>';
    }

  }

  root.ExecutionRenderOutputs = {
    renderVariableOutputs: renderVariableOutputs,
  };
})(typeof window !== 'undefined' ? window : this);
