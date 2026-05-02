/**
 * Execution modal inventory picker: card payload + DOM assembly.
 * Details panel uses DOM APIs (no innerHTML on .exec-picker-card__details).
 * Load after inventory-display.js; before execution-render-inputs.js.
 *
 * Security contract: user- and server-supplied strings in details (notes, audit labels/values,
 * prompts, unknown expiry JSON) must stay on textContent / plain-text branches — never switch these
 * to innerHTML without a dedicated sanitization policy.
 */
(function (root) {
  'use strict';

  var doc = root.document;

  /** @param {string} title */
  function detailsSection(title, bodyEl) {
    if (!bodyEl) return null;
    var wrap = doc.createElement('div');
    wrap.style.marginTop = '12px';
    var h = doc.createElement('div');
    h.style.cssText =
      'font-size: 12px; font-weight: 700; color: var(--text-secondary,#6b7280); letter-spacing:0.03em; text-transform: uppercase; margin-bottom: 8px;';
    h.textContent = title;
    wrap.appendChild(h);
    wrap.appendChild(bodyEl);
    return wrap;
  }

  function fmtIso(iso) {
    if (!iso) return '';
    try {
      return new Date(iso).toISOString().replace('.000Z', 'Z');
    } catch (e) {
      return String(iso);
    }
  }

  function appendCustomExpiryValue(el, obj) {
    if (!obj || typeof obj !== 'object') return;
    var mode = (obj.mode || '').toString();
    if (mode === 'duration') {
      var dv = obj.duration_value != null ? String(obj.duration_value) : '';
      var du = obj.duration_unit != null ? String(obj.duration_unit).replace(/_/g, ' ') : '';
      var wv = obj.warning_value != null ? String(obj.warning_value) : '';
      var wu = obj.warning_unit != null ? String(obj.warning_unit).replace(/_/g, ' ') : '';
      var parts = [];
      if (dv && du) parts.push('Expiry: ' + dv + ' ' + du);
      if (wv && wu) parts.push('Warning: ' + wv + ' ' + wu);
      el.textContent = parts.join(' · ');
      return;
    }
    if (mode === 'datetime') {
      var exp = obj.expiry_at || obj.expiryAt || '';
      var warnAt = obj.warning_at || obj.warn_at || obj.warningAt || '';
      var parts2 = [];
      if (exp) parts2.push('Expiry at (UTC): ' + fmtIso(exp));
      if (warnAt) parts2.push('Warning at (UTC): ' + fmtIso(warnAt));
      el.textContent = parts2.join(' · ');
      return;
    }
    // Unknown schema: plain JSON text only (no HTML). Prefer tightening backend shapes vs rendering rich HTML here.
    try {
      el.textContent = JSON.stringify(obj);
    } catch (e) {}
  }

  /**
   * @param {object} ctx prettyLabel, orgUsersMap
   */
  function buildDetailsFragment(inv, ctx) {
    var prettyLabel = ctx.prettyLabel;
    var orgUsersMap = ctx.orgUsersMap;
    var frag = doc.createDocumentFragment();

    function fmtDate(raw) {
      if (!raw) return '';
      try {
        return new Date(raw).toLocaleDateString();
      } catch (e) {
        return String(raw);
      }
    }

    var isRawMaterial = String(inv.inventory_type || 'raw_material') === 'raw_material';

    if (!isRawMaterial) {
      var trace = inv.extra_data && inv.extra_data.execution_trace ? inv.extra_data.execution_trace : {};
      var prompts = inv.extra_data && inv.extra_data.execution_prompts ? inv.extra_data.execution_prompts : null;
      var vInputs = inv.extra_data && inv.extra_data.variable_inputs ? inv.extra_data.variable_inputs : null;
      var vOut = inv.extra_data && inv.extra_data.variable_output ? inv.extra_data.variable_output : null;
      var notes = inv.extra_data && inv.extra_data.notes ? String(inv.extra_data.notes) : '';
      var producingProcessName =
        inv.extra_data && inv.extra_data.producing_process_name ? String(inv.extra_data.producing_process_name) : '';
      var producingStepName =
        inv.producing_step_name != null && String(inv.producing_step_name).trim()
          ? String(inv.producing_step_name)
          : inv.extra_data && inv.extra_data.producing_step_name
            ? String(inv.extra_data.producing_step_name)
            : '';

      var topGrid = doc.createElement('div');
      topGrid.className = 'exec-picker-kv';
      var anyTop = false;
      function addTopKv(label, value) {
        if (value == null || String(value).trim() === '') return;
        anyTop = true;
        var k = doc.createElement('div');
        k.className = 'exec-picker-kv__k';
        k.textContent = label;
        var v = doc.createElement('div');
        v.className = 'exec-picker-kv__v';
        v.textContent = String(value);
        topGrid.appendChild(k);
        topGrid.appendChild(v);
      }
      if (inv.process_name) addTopKv('Process name', inv.process_name);
      if (producingProcessName && (!inv.process_name || String(inv.process_name) !== String(producingProcessName))) {
        addTopKv('Producing process', producingProcessName);
      }
      if (inv.source_step_name) addTopKv('Source step name', inv.source_step_name);
      if (producingStepName) addTopKv('Producing step', producingStepName);

      var prodBody = anyTop ? topGrid : null;
      var secProd = detailsSection('Production', prodBody);
      if (secProd) frag.appendChild(secProd);

      if (notes && notes.trim()) {
        // extra_data.notes: treat as plain text forever (XSS-safe). Do not refactor to innerHTML.
        var notesDiv = doc.createElement('div');
        notesDiv.style.cssText =
          'font-size: 13px; color: var(--text-primary,#111827); line-height: 1.5; white-space: pre-line;';
        notesDiv.textContent = notes;
        var secNotes = detailsSection('Notes', notesDiv);
        if (secNotes) frag.appendChild(secNotes);
      }

      var ceActual = inv.extra_data && inv.extra_data.custom_expiry_actual ? inv.extra_data.custom_expiry_actual : null;
      var ceInput =
        vOut && vOut.custom_expiry_input
          ? vOut.custom_expiry_input
          : inv.extra_data && inv.extra_data.custom_expiry_input
            ? inv.extra_data.custom_expiry_input
            : null;
      var ceWrap = doc.createElement('div');
      var ceAny = false;
      if (ceActual) {
        ceAny = true;
        var r1 = doc.createElement('div');
        r1.className = 'exec-picker-kv';
        var k1 = doc.createElement('div');
        k1.className = 'exec-picker-kv__k';
        k1.textContent = 'Custom expiry (applied)';
        var v1 = doc.createElement('div');
        v1.className = 'exec-picker-kv__v';
        appendCustomExpiryValue(v1, ceActual);
        r1.appendChild(k1);
        r1.appendChild(v1);
        ceWrap.appendChild(r1);
      }
      if (ceInput) {
        ceAny = true;
        var r2 = doc.createElement('div');
        r2.className = 'exec-picker-kv';
        r2.style.marginTop = '6px';
        var k2 = doc.createElement('div');
        k2.className = 'exec-picker-kv__k';
        k2.textContent = 'Custom expiry (entered)';
        var v2 = doc.createElement('div');
        v2.className = 'exec-picker-kv__v';
        appendCustomExpiryValue(v2, ceInput);
        r2.appendChild(k2);
        r2.appendChild(v2);
        ceWrap.appendChild(r2);
      }
      if (ceAny) {
        var secCe = detailsSection('Custom expiry', ceWrap);
        if (secCe) frag.appendChild(secCe);
      }

      if (prompts && typeof prompts === 'object') {
        var entries = Object.keys(prompts).map(function (k) {
          return [k, prompts[k]];
        });
        if (entries.length) {
          var ul = doc.createElement('ul');
          ul.style.cssText = 'margin: 0; padding-left: 18px;';
          for (var ei = 0; ei < entries.length; ei++) {
            var e = entries[ei];
            var k = e[0];
            var v = e[1];
            var li = doc.createElement('li');
            li.style.cssText = 'margin: 0 0 6px 0; font-size: 13px; color: var(--text-primary, #111827); line-height: 1.35;';
            var sBold = doc.createElement('span');
            sBold.style.fontWeight = '600';
            sBold.textContent = 'Prompt ' + (ei + 1);
            li.appendChild(sBold);
            li.appendChild(doc.createTextNode(' '));
            var sMeta = doc.createElement('span');
            sMeta.style.cssText = 'color: var(--text-secondary,#6b7280); font-weight:500;';
            sMeta.textContent = '(' + prettyLabel(k) + ')';
            li.appendChild(sMeta);
            li.appendChild(doc.createTextNode(': '));
            var sVal = doc.createElement('span');
            sVal.style.fontWeight = '400';
            sVal.textContent = String(v);
            li.appendChild(sVal);
            ul.appendChild(li);
          }
          var secPr = detailsSection('Custom prompts', ul);
          if (secPr) frag.appendChild(secPr);
        }
      }

      if (Array.isArray(vInputs) && vInputs.length) {
        var ul2 = doc.createElement('ul');
        ul2.style.cssText = 'margin: 0; padding-left: 18px;';
        for (var vi = 0; vi < vInputs.length; vi++) {
          var x = vInputs[vi];
          var nm =
            x && (x.name || x.input_name || x.inputName)
              ? String(x.name || x.input_name || x.inputName)
              : 'Input';
          var q =
            x && (x.quantity != null ? x.quantity : x.input_quantity) != null
              ? String(x.quantity != null ? x.quantity : x.input_quantity)
              : '';
          var u = x && (x.unit || x.input_unit) ? String(x.unit || x.input_unit) : '';
          var li2 = doc.createElement('li');
          li2.style.cssText = 'margin: 0 0 6px 0; font-size: 13px; color: var(--text-primary, #111827); line-height: 1.35;';
          var sn = doc.createElement('span');
          sn.style.fontWeight = '400';
          sn.textContent = nm;
          li2.appendChild(sn);
          if (q) {
            var sq = doc.createElement('span');
            sq.style.cssText = 'color: var(--text-secondary,#6b7280); font-weight:400;';
            sq.textContent = ' — ' + q + (u ? ' ' + u : '');
            li2.appendChild(sq);
          }
          ul2.appendChild(li2);
        }
        var secIn = detailsSection('Inputs', ul2);
        if (secIn) frag.appendChild(secIn);
      }

      var hasAuditHistory =
        !!(
          inv.extra_data &&
          inv.extra_data.inventory_audit_history &&
          Array.isArray(inv.extra_data.inventory_audit_history) &&
          inv.extra_data.inventory_audit_history.length
        );
      if (!hasAuditHistory) {
        var auditBits = doc.createElement('div');
        auditBits.className = 'exec-picker-kv';
        var ts = inv.created_at || (trace && trace.completed_at) || '';
        var op = (trace && (trace.completed_by || trace.completed_by_email)) || inv.operator_name || inv.created_by_name || '';
        if (!op) {
          var uid = trace && (trace.completed_by_user_id || trace.completed_by_user || trace.user_id);
          if (uid && orgUsersMap && typeof orgUsersMap.get === 'function') {
            op = orgUsersMap.get(String(uid)) || '';
          }
        }
        var srcMethod = (trace && trace.source_method) || '';
        if (!srcMethod && inv.source_execution_step_id) srcMethod = 'completed step';

        function addAuditKv(label, val) {
          var ke = doc.createElement('div');
          ke.className = 'exec-picker-kv__k';
          ke.textContent = label;
          var ve = doc.createElement('div');
          ve.className = 'exec-picker-kv__v';
          ve.textContent = val;
          auditBits.appendChild(ke);
          auditBits.appendChild(ve);
        }
        addAuditKv('Action', 'Inventory item created');
        addAuditKv('Timestamp UTC', ts ? fmtIso(ts) : '—');
        addAuditKv('Operator', op || '—');
        addAuditKv('Source method', srcMethod ? prettyLabel(srcMethod) : '—');
        var secAu = detailsSection('Audit history', auditBits);
        if (secAu) frag.appendChild(secAu);
      }
    }

    // inventory_audit_history: render as text-only kv cells (same contract as notes).
    try {
      var hist = inv.extra_data && inv.extra_data.inventory_audit_history ? inv.extra_data.inventory_audit_history : [];
      if (Array.isArray(hist) && hist.length) {
        var uuidLike = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
        var auditOuter = doc.createElement('div');
        auditOuter.style.marginTop = '12px';
        var auditTitle = doc.createElement('div');
        auditTitle.style.cssText =
          'font-size: 12px; font-weight: 700; color: var(--text-secondary,#6b7280); letter-spacing:0.03em; text-transform: uppercase; margin-bottom: 8px;';
        auditTitle.textContent = 'Audit history';
        auditOuter.appendChild(auditTitle);
        var kvRoot = doc.createElement('div');
        kvRoot.className = 'exec-picker-kv';

        for (var hi = hist.length - 1; hi >= 0; hi--) {
          var h = hist[hi];
          var when = h.timestamp_utc || h.timestamp || h.created_at || '';
          var src = h.source_method || h.source || '';
          var opLabel = h.operator_name || h.operator_email || '';
          if (!opLabel) {
            var opId = h.user_id || h.operator_id || h.user || '';
            opLabel =
              opId && orgUsersMap && typeof orgUsersMap.get === 'function'
                ? orgUsersMap.get(String(opId)) || String(opId)
                : String(opId || '');
          }
          try {
            if (!opLabel || uuidLike.test(String(opLabel).trim())) opLabel = 'Unknown operator';
          } catch (e2) {
            if (!opLabel) opLabel = 'Unknown operator';
          }
          var action = h.action || h.event || '';
          if (!action) action = 'inventory item added';

          var rowPairs = [
            [prettyLabel('action'), prettyLabel(action)],
            [prettyLabel('timestamp_utc'), String(when || '—')],
            [prettyLabel('operator'), String(opLabel || '—')],
            [prettyLabel('source_method'), prettyLabel(src) || '—']
          ];
          for (var ri = 0; ri < rowPairs.length; ri++) {
            var ke2 = doc.createElement('div');
            ke2.className = 'exec-picker-kv__k';
            ke2.textContent = rowPairs[ri][0];
            var ve2 = doc.createElement('div');
            ve2.className = 'exec-picker-kv__v';
            ve2.textContent = rowPairs[ri][1];
            kvRoot.appendChild(ke2);
            kvRoot.appendChild(ve2);
          }
        }
        auditOuter.appendChild(kvRoot);
        frag.appendChild(auditOuter);
      }
    } catch (e) {}

    return frag;
  }

  function appendMetaGridCell(grid, label, value) {
    if (value == null) return;
    var s = String(value);
    if (!s.trim()) return;
    var cell = doc.createElement('div');
    cell.style.minWidth = '0';
    var lab = doc.createElement('div');
    lab.style.cssText = 'font-size:11px; color: var(--text-tertiary, #9ca3af); line-height:1.2;';
    lab.textContent = label;
    var valEl = doc.createElement('div');
    valEl.style.cssText =
      'font-size:12px; color: var(--text-primary, #111827); font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;';
    valEl.textContent = s;
    cell.appendChild(lab);
    cell.appendChild(valEl);
    grid.appendChild(cell);
  }

  function buildChipsFragment(inv, getExpiredReason) {
    var frag = doc.createDocumentFragment();
    if (inv.supplier) {
      var sp = doc.createElement('span');
      sp.className = 'exec-picker-chip';
      sp.textContent = inv.supplier;
      frag.appendChild(sp);
    }
    if (inv.supplier_batch_number) {
      var ba = doc.createElement('span');
      ba.className = 'exec-picker-chip';
      ba.textContent = 'Batch ' + String(inv.supplier_batch_number);
      frag.appendChild(ba);
    }
    var reason = getExpiredReason(inv.id);
    if (reason) {
      var rs = doc.createElement('span');
      rs.className =
        'exec-picker-chip ' +
        (reason.toLowerCase().indexOf('untracked') !== -1
          ? 'exec-picker-chip--danger'
          : reason.toLowerCase().indexOf('expired') !== -1
            ? 'exec-picker-chip--danger'
            : 'exec-picker-chip--warn');
      rs.textContent = reason;
      frag.appendChild(rs);
    }
    return frag;
  }

  function buildPayload(inv, ctx) {
    var getExpiredReason = ctx.getExpiredReason;

    function fmtDate(raw) {
      if (!raw) return '';
      try {
        return new Date(raw).toLocaleDateString();
      } catch (e) {
        return String(raw);
      }
    }

    var chipsFragment = buildChipsFragment(inv, getExpiredReason);

    var metaGridEl = doc.createElement('div');
    metaGridEl.className = 'exec-picker-card__meta-grid';
    metaGridEl.style.cssText =
      'margin-top: 10px; display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px;';
    appendMetaGridCell(metaGridEl, 'Process', inv.process_name || '');
    appendMetaGridCell(metaGridEl, 'Supplier', inv.supplier || '');
    appendMetaGridCell(metaGridEl, 'Batch', inv.supplier_batch_number || inv.batch_number || inv.lot_number || '');
    appendMetaGridCell(metaGridEl, 'Barcode', inv.barcode || '');
    appendMetaGridCell(metaGridEl, 'Source step', inv.source_step_name || '');
    appendMetaGridCell(metaGridEl, 'Purchase', inv.purchase_date ? fmtDate(inv.purchase_date) : '');
    appendMetaGridCell(metaGridEl, 'Expiry', inv.expiry_date ? fmtDate(inv.expiry_date) : '');
    appendMetaGridCell(metaGridEl, 'Ready', inv.ready_date ? fmtDate(inv.ready_date) : '');
    appendMetaGridCell(metaGridEl, 'Created', inv.created_at ? fmtDate(inv.created_at) : '');
    appendMetaGridCell(metaGridEl, 'Operator', inv.operator_name || inv.operator || '');
    appendMetaGridCell(metaGridEl, 'Created by', inv.created_by_name || inv.created_by || '');

    try {
      var extra = inv.extra_data;
      if (extra && typeof extra === 'object') {
        var keys = Object.keys(extra);
        var shown = 0;
        for (var k = 0; k < keys.length; k++) {
          if (shown >= 8) break;
          var key = keys[k];
          if (key === 'execution_prompts') continue;
          if (key === 'variable_output') continue;
          if (key === 'remaining_balance_to_reconcile') continue;
          if (key === 'notes') continue;
          if (key === 'producing_process_id') continue;
          if (key === 'producing_process_name') continue;
          if (key === 'producing_step_name') continue;
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
          var label = key;
          if (/batch|lot/i.test(key)) label = 'Batch';
          if (/operator/i.test(key)) label = 'Operator';
          if (/created_by|creator|made_by/i.test(key)) label = 'Created by';
          appendMetaGridCell(metaGridEl, label, vv);
          shown++;
        }
      }
    } catch (e) {}

    var metaGridNode = metaGridEl.childNodes.length ? metaGridEl : null;

    var detailsFragment = buildDetailsFragment(inv, ctx);

    return {
      chipsFragment: chipsFragment,
      metaGridEl: metaGridNode,
      detailsFragment: detailsFragment
    };
  }

  function assembleCard(inv, payload, isPending, rawId, IDisp) {
    var chipsFragment = payload.chipsFragment;
    var metaGridEl = payload.metaGridEl;
    var detailsFragment = payload.detailsFragment;

    var card = doc.createElement('div');
    card.className = 'exec-picker-card';
    card.setAttribute('role', 'button');
    card.tabIndex = 0;
    card.dataset.invId = rawId;
    card.setAttribute('aria-pressed', isPending ? 'true' : 'false');
    card.dataset.expanded = 'false';

    var topOuter = doc.createElement('div');
    topOuter.className = 'exec-picker-card__top';
    var leftCol = doc.createElement('div');
    leftCol.style.minWidth = '0';
    var titleP = doc.createElement('p');
    titleP.className = 'exec-picker-card__title';
    titleP.textContent = inv.name || 'Unnamed';
    var subP = doc.createElement('p');
    subP.className = 'exec-picker-card__sub';
    subP.textContent = IDisp.quantityUnitLine(inv);
    leftCol.appendChild(titleP);
    leftCol.appendChild(subP);
    var toggleBtn = doc.createElement('button');
    toggleBtn.type = 'button';
    toggleBtn.className = 'exec-picker-card__toggle';
    toggleBtn.setAttribute('data-action', 'toggle-details');
    toggleBtn.dataset.invId = rawId;
    toggleBtn.textContent = 'Details';
    topOuter.appendChild(leftCol);
    topOuter.appendChild(toggleBtn);
    card.appendChild(topOuter);

    if (chipsFragment && chipsFragment.childNodes.length) {
      var chipHolder = doc.createElement('div');
      chipHolder.className = 'exec-picker-card__meta';
      chipHolder.appendChild(chipsFragment);
      card.appendChild(chipHolder);
    }
    if (metaGridEl) {
      card.appendChild(metaGridEl);
    }

    var spacerEl = doc.createElement('div');
    spacerEl.className = 'exec-picker-card__spacer';
    card.appendChild(spacerEl);

    if (isPending) {
      var actDiv = doc.createElement('div');
      actDiv.className = 'exec-picker-card__actions';
      actDiv.style.justifyContent = 'flex-start';
      var cBtn = doc.createElement('button');
      cBtn.type = 'button';
      cBtn.className = 'btn btn-secondary btn-sm exec-picker-confirm-btn';
      cBtn.setAttribute('data-action', 'confirm-input');
      cBtn.dataset.invId = rawId;
      var strongEl = doc.createElement('strong');
      strongEl.textContent = 'Confirm input';
      cBtn.appendChild(strongEl);
      actDiv.appendChild(cBtn);
      card.appendChild(actDiv);
    }

    var detailsEl = doc.createElement('div');
    detailsEl.className = 'exec-picker-card__details';
    if (detailsFragment && detailsFragment.childNodes.length) {
      detailsEl.appendChild(detailsFragment);
    }
    card.appendChild(detailsEl);

    return card;
  }

  function syncCard(card, inv, payload, isPending, rawId, IDisp) {
    var titleP = card.querySelector('.exec-picker-card__title');
    var subP = card.querySelector('.exec-picker-card__sub');
    if (titleP) titleP.textContent = inv.name || 'Unnamed';
    if (subP) subP.textContent = IDisp.quantityUnitLine(inv);
    card.setAttribute('aria-pressed', isPending ? 'true' : 'false');
    card.dataset.invId = rawId;
    var toggleBtn = card.querySelector('.exec-picker-card__toggle');
    if (toggleBtn) toggleBtn.dataset.invId = rawId;

    var topOuter = card.querySelector('.exec-picker-card__top');
    var spacerEl = card.querySelector('.exec-picker-card__spacer');
    if (topOuter && spacerEl && spacerEl.parentNode === card) {
      var n = topOuter.nextSibling;
      while (n && n !== spacerEl) {
        var next = n.nextSibling;
        if (
          n.nodeType === 1 &&
          n.classList &&
          (n.classList.contains('exec-picker-card__meta') || n.classList.contains('exec-picker-card__meta-grid'))
        ) {
          n.remove();
        }
        n = next;
      }
      if (payload.chipsFragment && payload.chipsFragment.childNodes.length) {
        var chipHolder = doc.createElement('div');
        chipHolder.className = 'exec-picker-card__meta';
        chipHolder.appendChild(payload.chipsFragment);
        card.insertBefore(chipHolder, spacerEl);
      }
      if (payload.metaGridEl) {
        card.insertBefore(payload.metaGridEl, spacerEl);
      }
    }

    var detailsEl = card.querySelector('.exec-picker-card__details');
    var actDiv = card.querySelector('.exec-picker-card__actions');
    if (isPending) {
      if (!actDiv && spacerEl && detailsEl) {
        actDiv = doc.createElement('div');
        actDiv.className = 'exec-picker-card__actions';
        actDiv.style.justifyContent = 'flex-start';
        var cBtn = doc.createElement('button');
        cBtn.type = 'button';
        cBtn.className = 'btn btn-secondary btn-sm exec-picker-confirm-btn';
        cBtn.setAttribute('data-action', 'confirm-input');
        cBtn.dataset.invId = rawId;
        var strongEl = doc.createElement('strong');
        strongEl.textContent = 'Confirm input';
        cBtn.appendChild(strongEl);
        actDiv.appendChild(cBtn);
        card.insertBefore(actDiv, detailsEl);
      } else if (actDiv) {
        var cBtn2 = actDiv.querySelector('.exec-picker-confirm-btn');
        if (cBtn2) cBtn2.dataset.invId = rawId;
      }
    } else if (actDiv) {
      actDiv.remove();
    }

    if (detailsEl) {
      while (detailsEl.firstChild) detailsEl.removeChild(detailsEl.firstChild);
      if (payload.detailsFragment && payload.detailsFragment.childNodes.length) {
        detailsEl.appendChild(payload.detailsFragment);
      }
    }
  }

  root.ExecutionInventoryPickerView = {
    buildPayload: buildPayload,
    assembleCard: assembleCard,
    syncCard: syncCard
  };
})(typeof window !== 'undefined' ? window : this);
