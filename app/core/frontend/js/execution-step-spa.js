// Dedicated SPA step execution UI (no modal).
// Renders the same fields as the legacy execution modal, using SPA layout + inline inventory picker.
(function() {
  'use strict';

  function ensureStyles() {
    if (document.getElementById('exec-spa-picker-styles')) return;
    var style = document.createElement('style');
    style.id = 'exec-spa-picker-styles';
    style.textContent = [
      // Section dividers
      '.exec-spa-section { padding: 18px 0; border-top: 1px solid var(--border-default, #e5e7eb); }',
      '.exec-spa-section-title { font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.07em; color: var(--text-secondary, #6b7280); margin: 0 0 14px 0; }',
      '.exec-spa-input-label { font-size: 14px; font-weight: 600; color: var(--text-primary, #111827); margin: 0 0 10px 0; }',
      '.exec-spa-input-label span { font-weight: 400; color: var(--text-secondary, #6b7280); margin-left: 4px; }',
      // Picker tabs (pill style, use app success green when selected)
      '.exec-picker-tabs { display: flex; gap: 6px; flex-wrap: wrap; margin: 0 0 10px 0; }',
      '.exec-picker-tab { appearance: none; border: 1px solid var(--border-default, #e5e7eb); background: var(--bg-card, #fff); color: var(--text-primary, #111827); border-radius: 999px; padding: 5px 12px; font-size: 12px; font-weight: 600; cursor: pointer; transition: border-color 120ms, background 120ms, color 120ms; }',
      '.exec-picker-tab[aria-selected="true"] { border-color: var(--success, #10b981); background: var(--bg-card, #fff); color: var(--success, #10b981); }',
      '.exec-picker-tab:hover:not([aria-selected="true"]) { border-color: color-mix(in srgb, var(--success, #10b981) 45%, transparent); }',
      // Search
      '.exec-picker-search { margin: 0 0 10px 0; }',
      // Card list
      '.exec-picker-cards { display: flex; flex-direction: column; gap: 8px; max-height: 320px; overflow-y: auto; padding-right: 2px; }',
      '.exec-picker-card { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; padding: 10px 14px; border-radius: var(--radius-md, 10px); border: 1px solid var(--border-default, #e5e7eb); background: var(--bg-card, #fff); color: var(--text-primary, #111827); cursor: pointer; transition: border-color 120ms, box-shadow 120ms, background 120ms; }',
      '.exec-picker-card:hover { border-color: color-mix(in srgb, var(--success, #10b981) 45%, transparent); }',
      '.exec-picker-card[aria-pressed="true"] { border-color: var(--success, #10b981); box-shadow: 0 0 0 3px color-mix(in srgb, var(--success, #10b981) 22%, transparent); }',
      '.exec-picker-card__title { font-size: 14px; font-weight: 600; margin: 0; }',
      '.exec-picker-card__sub { font-size: 12px; color: var(--text-tertiary, #9ca3af); margin: 0; line-height: 1.4; }',
      '.exec-picker-card__meta { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 6px; }',
      // Chips
      '.exec-picker-chip { display: inline-flex; align-items: center; padding: 3px 8px; border-radius: 999px; border: 1px solid var(--border-default, #e5e7eb); background: var(--bg-secondary, #f3f4f6); font-size: 11px; color: var(--text-secondary, #6b7280); }',
      '.exec-picker-chip--warn { background: hsl(42, 93%, 96%); border-color: var(--warning, #f59e0b); color: #92400e; }',
      '.exec-picker-chip--danger { background: hsl(0, 93%, 94%); border-color: var(--error, #ef4444); color: #b91c1c; }',
    ].join('\n');
    document.head.appendChild(style);
  }

  function escapeHtml(text) {
    if (window.escapeHtml) return window.escapeHtml(text);
    if (text == null) return '';
    var div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
  }

  function $all(root, sel) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function setBusy(btn, busy, label) {
    if (!btn) return;
    if (busy) {
      btn.dataset._origHtml = btn.innerHTML;
      btn.disabled = true;
      btn.textContent = label || 'Working…';
    } else {
      btn.disabled = false;
      if (btn.dataset._origHtml != null) btn.innerHTML = btn.dataset._origHtml;
    }
  }

  function fmtQty(inv) {
    if (!inv) return '';
    var q = (inv.quantity != null) ? String(inv.quantity) : '';
    var u = inv.unit || '';
    return (q && u) ? (q + ' ' + u) : (q || u || '');
  }

  function invMatchesType(inv, selected) {
    if (!selected || selected === 'all') return true;
    var t = String((inv && (inv.inventory_type || inv.type || inv.category || inv.item_type)) || '').toLowerCase();
    if (t === 'intermediate' || t === 'wip') t = 'work_in_progress';
    if (t === 'final') t = 'final_product';
    if (t === 'raw') t = 'raw_material';
    return t === selected;
  }

  function invMatchesSearch(inv, q) {
    q = (q || '').trim().toLowerCase();
    if (!q) return true;
    var hay = [inv && inv.name, inv && inv.unit, inv && inv.supplier, inv && inv.supplier_batch_number, inv && inv.process_name]
      .filter(Boolean).join(' ').toLowerCase();
    return hay.indexOf(q) !== -1;
  }

  function normalizeInventoryTabType(inv) {
    var t = String((inv && (inv.inventory_type || inv.type || inv.category || inv.item_type)) || '').toLowerCase().trim();
    if (!t) return 'raw_material';
    if (t === 'intermediate' || t === 'work_in_progress' || t === 'wip') return 'work_in_progress';
    if (t === 'final' || t === 'final_product') return 'final_product';
    if (t === 'raw' || t === 'raw_material') return 'raw_material';
    return t;
  }

  /**
   * Same rules as execution-render-inputs pickDefaultPickerType (modal / batches:start page).
   */
  function pickDefaultInventoryTab(inp, allInventory, executionId) {
    function normalizeExpectedInventoryTabHint(i) {
      if (!i) return null;
      var v = i.expected_inventory_type != null ? i.expected_inventory_type : i.expectedInventoryType;
      if (v == null || v === '') return null;
      var s = String(v).toLowerCase().trim();
      if (s === 'intermediate' || s === 'wip' || s === 'work_in_progress') return 'work_in_progress';
      if (s === 'final' || s === 'final_product') return 'final_product';
      if (s === 'raw' || s === 'raw_material') return 'raw_material';
      return null;
    }
    function normInputName(s) {
      return String(s || '').trim().toLowerCase();
    }
    function safeName(inv) {
      try { return String((inv && inv.name) || '').trim().toLowerCase(); } catch (e) { return ''; }
    }
    function countTabTypes(list) {
      var counts = { raw_material: 0, work_in_progress: 0, final_product: 0 };
      (list || []).forEach(function(inv) {
        var tab = normalizeInventoryTabType(inv);
        if (counts[tab] != null) counts[tab] += 1;
      });
      return counts;
    }
    function sortWithExecutionBias(list) {
      return (list || []).slice().sort(function(a, b) {
        var aExecutionId = a.source_execution_id || a.execution_id || null;
        var bExecutionId = b.source_execution_id || b.execution_id || null;
        if (executionId) {
          var aMatches = aExecutionId && String(aExecutionId) === String(executionId);
          var bMatches = bExecutionId && String(bExecutionId) === String(executionId);
          if (aMatches && !bMatches) return -1;
          if (!aMatches && bMatches) return 1;
        }
        return 0;
      });
    }

    var hinted = normalizeExpectedInventoryTabHint(inp);
    if (hinted) return hinted;

    var expectedNorm = normInputName(inp && inp.name);
    var matchingInventory = (allInventory || []).filter(function(inv) {
      if (!expectedNorm) return false;
      return safeName(inv) === expectedNorm;
    });
    var list = sortWithExecutionBias(matchingInventory);
    var expected = normInputName(inp && inp.name);
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

    if (!list.length) {
      if (inp && inp.source_output_id) return 'work_in_progress';
      var expectedN = normInputName(inp && inp.name);
      if (expectedN && allInventory && allInventory.length) {
        var byName = allInventory.filter(function(inv) {
          return normInputName(inv && inv.name) === expectedN;
        });
        if (byName.length) {
          var gc = countTabTypes(byName);
          var gr = gc.raw_material > 0;
          var gw = gc.work_in_progress > 0;
          var gf = gc.final_product > 0;
          var gkinds = (gr ? 1 : 0) + (gw ? 1 : 0) + (gf ? 1 : 0);
          if (gkinds === 1) {
            if (gr) return 'raw_material';
            if (gw) return 'work_in_progress';
            return 'final_product';
          }
          if (gw && !gr && !gf) return 'work_in_progress';
          if (gf && !gr && !gw) return 'final_product';
          if (gr && !gw && !gf) return 'raw_material';
        }
      }
      return 'raw_material';
    }

    if (inp && inp.source_output_id) {
      if (hasWip || hasFinal) {
        return counts.final_product > counts.work_in_progress ? 'final_product' : 'work_in_progress';
      }
      return 'work_in_progress';
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

  function renderPickerCards(container, allInventory, getExpiredReason, activeType, q, selectedId) {
    var list = allInventory
      .filter(function(inv) { return invMatchesType(inv, activeType); })
      .filter(function(inv) { return invMatchesSearch(inv, q); });

    if (!list.length) {
      container.innerHTML = '<p style="margin: 0; font-size: 13px; color: var(--text-secondary); padding: 6px 2px;">No inventory matches.</p>';
      return;
    }

    container.innerHTML = list.map(function(inv) {
      var id = String(inv.id);
      var chips = '';
      if (inv.supplier) chips += '<span class="exec-picker-chip">' + escapeHtml(inv.supplier) + '</span>';
      if (inv.supplier_batch_number) chips += '<span class="exec-picker-chip">Batch ' + escapeHtml(inv.supplier_batch_number) + '</span>';
      var reason = getExpiredReason(id);
      if (reason) {
        var cls = reason.toLowerCase().indexOf('untracked') !== -1 ? 'exec-picker-chip--danger'
          : (reason.toLowerCase().indexOf('expired') !== -1 ? 'exec-picker-chip--danger' : 'exec-picker-chip--warn');
        chips += '<span class="exec-picker-chip ' + cls + '">' + escapeHtml(reason) + '</span>';
      }
      return (
        '<button type="button" class="exec-picker-card" data-inv-id="' + escapeHtml(id) + '" aria-pressed="' + (selectedId && String(selectedId) === id ? 'true' : 'false') + '">' +
          '<p class="exec-picker-card__title">' + escapeHtml(inv.name || 'Unnamed') + '</p>' +
          '<p class="exec-picker-card__sub">' + escapeHtml(fmtQty(inv)) + '</p>' +
          (chips ? '<div class="exec-picker-card__meta">' + chips + '</div>' : '') +
        '</button>'
      );
    }).join('');
  }

  function renderExecutionStepSpa(root, ctx) {
    if (!root) return;
    // Full root.innerHTML reset below removes prior picker nodes; listeners on old elements go away with the DOM.
    ensureStyles();

    var step = ctx.stepDefinition || {};

    var variableInputs = (step.inputs || []).filter(function(i) {
      return i && i.requires_inventory_selection !== false && i.is_variable !== false;
    });
    var confirmInputs = (step.inputs || []).filter(function(i) {
      return i && i.is_variable !== false && i.requires_inventory_selection === false;
    });
    var prompts = (step.execution_prompts || []).filter(function(p) { return p && p.type !== 'evidence'; });
    var outputs = step.outputs || [];

    var state = { variableInputRows: {} };

    // ── Build HTML ────────────────────────────────────────────────────────────
    var html = '';

    // Step heading
    html += '<div style="padding: 4px 0 18px 0;">' +
      '<h2 style="margin: 0 0 4px 0; font-size: clamp(1.1rem, 2vw, 1.3rem); font-weight: 700; color: var(--text-primary);">' + escapeHtml(step.name || 'Step') + '</h2>' +
      '<p style="margin: 0; font-size: 0.9rem; color: var(--text-secondary);">Select inputs, record prompts, and confirm outputs to complete this step.</p>' +
    '</div>';

    // Variable inputs — inventory picker per input
    if (variableInputs.length) {
      html += '<div class="exec-spa-section">';
      html += '<div class="exec-spa-section-title">Select inventory</div>';
      variableInputs.forEach(function(inp) {
        var safe = (inp.name || '').replace(/[^a-zA-Z0-9_-]/g, '_');
        html += '<div data-var-input="' + escapeHtml(inp.name) + '" style="margin-bottom: 24px;">' +
          '<p class="exec-spa-input-label">' + escapeHtml(inp.name) +
            '<span>(Expected: ' + escapeHtml(String(inp.quantity || '0')) + ' ' + escapeHtml(inp.unit || '') + ')</span></p>' +
          '<div class="exec-picker-tabs" role="tablist" data-tabs-for="' + escapeHtml(safe) + '">' +
            '<button type="button" class="exec-picker-tab" role="tab" data-exec-type="raw_material" aria-selected="true">Raw materials</button>' +
            '<button type="button" class="exec-picker-tab" role="tab" data-exec-type="work_in_progress" aria-selected="false">Intermediate</button>' +
            '<button type="button" class="exec-picker-tab" role="tab" data-exec-type="final_product" aria-selected="false">Finals products</button>' +
          '</div>' +
          '<div class="exec-picker-search">' +
            '<input type="search" class="spa-inp" data-search-for="' + escapeHtml(safe) + '" placeholder="Search inventory…" autocomplete="off">' +
          '</div>' +
          '<div class="exec-picker-cards" id="exec-spa-cards-' + safe + '"><p style="margin: 0; font-size: 13px; color: var(--text-secondary);">Loading inventory…</p></div>' +
          '<div style="margin-top: 12px; display: flex; gap: 10px; flex-wrap: wrap; align-items: flex-end;">' +
            '<div style="flex: 1; min-width: 180px;">' +
              '<label class="spa-field-label" style="margin-bottom: 6px;">Quantity to consume</label>' +
              '<input type="number" class="spa-inp" step="0.01" min="0" value="' + escapeHtml(String(inp.quantity || '')) + '" data-qty-for="' + escapeHtml(inp.name) + '">' +
            '</div>' +
            '<div style="min-width: 48px; padding-bottom: 10px; color: var(--text-secondary); font-size: 14px;">' + escapeHtml(inp.unit || '') + '</div>' +
          '</div>' +
        '</div>';
      });
      html += '</div>';
    }

    // Confirm inputs
    if (confirmInputs.length) {
      html += '<div class="exec-spa-section">';
      html += '<div class="exec-spa-section-title">Confirm inputs</div>';
      html += '<div style="display: flex; flex-direction: column; gap: 12px;">';
      confirmInputs.forEach(function(inp) {
        html += '<div style="display: grid; grid-template-columns: 1fr 130px; gap: 12px; align-items: end;">' +
          '<div><label class="spa-field-label">' + escapeHtml(inp.name) + ' quantity</label>' +
          '<input type="number" class="spa-inp" step="0.01" min="0" value="' + escapeHtml(String(inp.quantity || '')) + '" data-confirm-qty="' + escapeHtml(inp.name) + '"></div>' +
          '<div><label class="spa-field-label">Unit</label>' +
          '<input type="text" class="spa-inp" value="' + escapeHtml(inp.unit || '') + '" data-confirm-unit="' + escapeHtml(inp.name) + '" placeholder="e.g. kg"></div>' +
        '</div>';
      });
      html += '</div></div>';
    }

    // Prompts
    if (prompts.length) {
      html += '<div class="exec-spa-section">';
      html += '<div class="exec-spa-section-title">Execution prompts</div>';
      html += '<div style="display: flex; flex-direction: column; gap: 12px;">';
      prompts.forEach(function(p) {
        var t = p.type || 'text';
        var req = p.required !== false;
        var inputHtml;
        if (t === 'number') inputHtml = '<input type="number" class="spa-inp" step="0.01"' + (req ? ' data-required="true"' : '') + ' data-prompt="' + escapeHtml(p.label || '') + '">';
        else if (t === 'date') inputHtml = '<input type="date" class="spa-inp"' + (req ? ' data-required="true"' : '') + ' data-prompt="' + escapeHtml(p.label || '') + '">';
        else if (t === 'select') inputHtml = '<select class="spa-inp"' + (req ? ' data-required="true"' : '') + ' data-prompt="' + escapeHtml(p.label || '') + '"><option value="">Select…</option></select>';
        else inputHtml = '<input type="text" class="spa-inp"' + (req ? ' data-required="true"' : '') + ' data-prompt="' + escapeHtml(p.label || '') + '">';
        html += '<div><label class="spa-field-label">' + escapeHtml(p.label || 'Prompt') +
          (req ? ' <span style="color: var(--error);">*</span>' : '') + '</label>' + inputHtml + '</div>';
      });
      html += '</div></div>';
    }

    // Outputs
    if (outputs.length) {
      html += '<div class="exec-spa-section">';
      html += '<div class="exec-spa-section-title">Confirm outputs</div>';
      html += '<div style="display: flex; flex-direction: column; gap: 12px;">';
      outputs.forEach(function(o, idx) {
        var outId = String(o.id || o.output_id || o.name || ('out_' + idx));
        html += '<div><label class="spa-field-label">' + escapeHtml(o.name || 'Output') +
          ' <span style="color: var(--text-secondary); font-weight: 400;">(Expected: ' + escapeHtml(String(o.quantity || '0')) + ' ' + escapeHtml(o.unit || '') + ')</span></label>' +
          '<input type="number" class="spa-inp" step="0.01" min="0" value="' + escapeHtml(String(o.quantity || '')) + '" data-output-id="' + escapeHtml(outId) + '">' +
        '</div>';
      });
      html += '</div></div>';
    }

    // Action row
    html += '<div style="display: flex; gap: 12px; justify-content: flex-end; margin-top: 8px; padding: 16px 0; border-top: 1px solid var(--border-light, #f3f4f6);">' +
      '<button type="button" class="btn btn-secondary" id="exec-spa-cancel">Cancel</button>' +
      '<button type="button" class="btn btn-primary" id="exec-spa-submit">Complete step</button>' +
    '</div>';

    root.innerHTML = html;

    // ── Cancel ────────────────────────────────────────────────────────────────
    root.querySelector('#exec-spa-cancel').addEventListener('click', function() {
      if (typeof ctx.onDone === 'function') ctx.onDone({ cancelled: true });
    });

    // ── Load inventory data + wire picker ─────────────────────────────────────
    (async function() {
      var results = await Promise.all([
        CoreAPI.getInventory(null, ctx.processId).catch(function() { return { inventory_items: [] }; }),
        CoreAPI.getExpiredMaterials().catch(function() { return { expired_raw_materials: [], impacted_items: [] }; }),
        CoreAPI.getUntrackedItems().catch(function() { return { untracked_items: [] }; }),
      ]);

      var allInventory = results[0].inventory_items || results[0].inventory || [];
      var expiredRaw = (results[1] && results[1].expired_raw_materials) ? results[1].expired_raw_materials : [];
      var impactedItems = (results[1] && results[1].impacted_items) ? results[1].impacted_items : [];
      var untrackedItems = (results[2] && results[2].untracked_items) ? results[2].untracked_items : [];

      var expiredIds = {};
      expiredRaw.forEach(function(m) { expiredIds[String(m.id)] = true; });
      var impactedMap = {};
      impactedItems.forEach(function(i) { impactedMap[String(i.id)] = i; });
      var untrackedIds = {};
      untrackedItems.forEach(function(i) { untrackedIds[String(i.id)] = true; });
      var readyDateReasons = {};
      allInventory.forEach(function(inv) {
        var f = (inv.system_findings || []).find(function(f) { return f && f.check_id === 'output_ready_date'; });
        if (f) readyDateReasons[String(inv.id)] = f.reason || 'Not ready';
      });

      function getExpiredReason(id) {
        if (readyDateReasons[String(id)]) return readyDateReasons[String(id)];
        if (expiredIds[String(id)]) return 'Expired';
        var imp = impactedMap[String(id)];
        if (imp && imp.expired_raw_material_name) return 'Made with expired: ' + imp.expired_raw_material_name;
        if (imp) return 'Made with expired ingredients';
        if (untrackedIds[String(id)]) return 'Untracked inventory item — reconciliation required';
        return null;
      }

      variableInputs.forEach(function(inp) {
        var safe = (inp.name || '').replace(/[^a-zA-Z0-9_-]/g, '_');
        var cardHost = root.querySelector('#exec-spa-cards-' + safe);
        var searchEl = root.querySelector('[data-search-for="' + safe + '"]');
        var tabContainer = root.querySelector('[data-tabs-for="' + safe + '"]');
        var tabs = tabContainer ? Array.prototype.slice.call(tabContainer.querySelectorAll('.exec-picker-tab')) : [];
        if (!cardHost) return;

        var defaultTab = pickDefaultInventoryTab(inp, allInventory, ctx.executionId);
        var pickerState = { activeType: defaultTab, q: '', selectedId: '' };
        tabs.forEach(function(tab) {
          var on = tab.getAttribute('data-exec-type') === defaultTab;
          tab.setAttribute('aria-selected', on ? 'true' : 'false');
        });

        function rerender() {
          renderPickerCards(cardHost, allInventory, getExpiredReason, pickerState.activeType, pickerState.q, pickerState.selectedId);
        }

        // cardHost is the persistent #exec-spa-cards-* container; innerHTML of cards only is replaced.
        if (!cardHost._execSpaPickerDelegate) {
          cardHost._execSpaPickerDelegate = true;
          cardHost.addEventListener('click', function(ev) {
            var t = ev.target;
            var btn = t && t.closest ? t.closest('.exec-picker-card') : null;
            if (!btn || !cardHost.contains(btn)) return;
            pickerState.selectedId = btn.getAttribute('data-inv-id') || '';
            if (!state.variableInputRows[inp.name]) state.variableInputRows[inp.name] = {};
            state.variableInputRows[inp.name].inventory_item_id = pickerState.selectedId;
            rerender();
          });
        }

        tabs.forEach(function(tab) {
          tab.addEventListener('click', function() {
            pickerState.activeType = tab.getAttribute('data-exec-type') || 'all';
            tabs.forEach(function(t) { t.setAttribute('aria-selected', t === tab ? 'true' : 'false'); });
            rerender();
          });
        });

        if (searchEl) {
          searchEl.addEventListener('input', function() {
            pickerState.q = searchEl.value || '';
            rerender();
          });
        }

        rerender();
      });
    })().catch(function(e) {
      if (window.showNotification) window.showNotification('error', 'Failed to load inventory', e && e.message ? e.message : 'Please try again.');
    });

    // ── Submit ────────────────────────────────────────────────────────────────
    root.querySelector('#exec-spa-submit').addEventListener('click', async function() {
      var submitBtn = this;
      var promptMissing = [];
      $all(root, '[data-prompt][data-required="true"]').forEach(function(el) {
        var ok = String(el.value || '').trim();
        if (!ok) {
          promptMissing.push(el.getAttribute('data-prompt') || 'Field');
          el.style.border = '2px solid var(--error, #ef4444)';
        } else {
          el.style.border = '';
        }
      });
      if (promptMissing.length) {
        if (window.showNotification) {
          window.showNotification('error', 'Validation error', 'Please fill in: ' + promptMissing.join(', ') + '.');
        }
        return;
      }
      setBusy(submitBtn, true, 'Completing…');
      try {
        var createResult = await CoreAPI.createExecution(ctx.processId);
        var executionId = createResult.id || createResult.execution_id || (createResult.execution && createResult.execution.id);
        if (!executionId) throw new Error('Could not create batch.');

        var execData = await CoreAPI.getExecution(executionId);
        var steps = execData.execution_steps || [];
        var readyStep = steps.find(function(es) { return es.status === 'ready' || es.status === 'READY'; });
        if (!readyStep || !readyStep.id) throw new Error('Could not find step to complete.');

        // Collect variable inputs
        var actualInputs = [];
        variableInputs.forEach(function(inp) {
          var sel = state.variableInputRows[inp.name] && state.variableInputRows[inp.name].inventory_item_id;
          if (!sel) return;
          var qtyEl = root.querySelector('[data-qty-for="' + CSS.escape(inp.name) + '"]');
          var qty = qtyEl ? parseFloat(qtyEl.value) : parseFloat(inp.quantity || '0');
          actualInputs.push({ name: inp.name, inventory_item_id: sel, quantity: isNaN(qty) ? 0 : qty, unit: inp.unit || '' });
        });

        // Collect confirm inputs
        confirmInputs.forEach(function(inp) {
          var qEl = root.querySelector('[data-confirm-qty="' + CSS.escape(inp.name) + '"]');
          var uEl = root.querySelector('[data-confirm-unit="' + CSS.escape(inp.name) + '"]');
          var q = qEl ? parseFloat(qEl.value) : parseFloat(inp.quantity || '0');
          var u = uEl ? (uEl.value || '') : (inp.unit || '');
          if (!isNaN(q) && q > 0 && u) actualInputs.push({ name: inp.name, quantity: q, unit: u });
        });

        // Collect prompts
        var promptPayload = {};
        $all(root, '[data-prompt]').forEach(function(el) {
          var k = el.getAttribute('data-prompt') || '';
          var v = (el.value || '').trim();
          if (k) promptPayload[k] = v;
        });

        // Collect outputs
        var actualOutputs = [];
        outputs.forEach(function(o, idx) {
          var outId = String(o.id || o.output_id || o.name || ('out_' + idx));
          var el = root.querySelector('[data-output-id="' + CSS.escape(outId) + '"]');
          var q = el ? parseFloat(el.value) : parseFloat(o.quantity || '0');
          actualOutputs.push({ name: o.name, quantity: isNaN(q) ? 0 : q, unit: o.unit || '' });
        });

        await CoreAPI.completeStep(executionId, readyStep.id, {
          inputs: actualInputs,
          outputs: actualOutputs,
          execution_prompts: promptPayload,
        });

        if (typeof ctx.onDone === 'function') ctx.onDone({ executionId: executionId, completed: true });
      } catch (e) {
        if (window.showNotification) window.showNotification('error', 'Could not complete step', e && e.message ? e.message : 'Please try again.');
      } finally {
        setBusy(submitBtn, false);
      }
    });
  }

  window.ExecutionStepSPA = { render: renderExecutionStepSpa };
})();
