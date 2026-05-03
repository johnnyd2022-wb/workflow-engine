    // RULE: Never use innerHTML with API data. Use textContent or DOM APIs.
    function flows2InventoryTypeLabel(invType) {
      const map = {
        raw_material: 'Raw material',
        work_in_progress: 'Intermediate',
        final_product: 'Final product',
      };
      return map[invType] || invType || '';
    }

    /** Intermediate and final products are produced by a step; raw materials are not. */
    function flows2InventoryIsProducedItem(item) {
      const t = item.inventory_type || 'raw_material';
      return t === 'work_in_progress' || t === 'final_product';
    }

    function flows2InvFormatDate(dateStr) {
      if (!dateStr) return 'N/A';
      try {
        return new Date(dateStr).toLocaleString();
      } catch {
        return String(dateStr);
      }
    }

    function flows2InvFormatQty(qtyStr) {
      if (qtyStr === undefined || qtyStr === null || qtyStr === '') return '0';
      try {
        const q = parseFloat(qtyStr);
        if (Number.isNaN(q)) return String(qtyStr);
        return parseFloat(q.toFixed(4)).toString();
      } catch {
        return String(qtyStr);
      }
    }

    const FLOWS2_JSON_DISPLAY_MAX_DEPTH = 12;
    const FLOWS2_JSON_DISPLAY_MAX_ARRAY_ITEMS = 400;

    /** Same rules as execution-shared-utils.prettyLabel (batch/start picker Details). */
    function flows2PrettyLabel(s) {
      if (!s) return '';
      return String(s)
        .replace(/_/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/\b\w/g, (c) => c.toUpperCase());
    }

    function flows2FmtIsoAudit(iso) {
      if (!iso) return '';
      try {
        return new Date(iso).toISOString().replace('.000Z', 'Z');
      } catch {
        return String(iso);
      }
    }

    /** Operator-facing date/time (locale). API may send ISO via ready_date_display or raw input. */
    function flows2FormatReadyDateOperatorFacing(rawIsoOrStr) {
      if (!rawIsoOrStr || !String(rawIsoOrStr).trim()) return '—';
      return flows2InvFormatDate(String(rawIsoOrStr));
    }

    /** Single ready row: prefer execution-time input; else server-ready_date_display (set_at_execution or fixed duration). */
    function flows2InventorySingleReadyDate(item) {
      const ex = item.extra_data || {};
      const vOut = ex.variable_output || {};
      const inp = vOut.ready_date_input;
      if (inp && typeof inp === 'object' && inp.date != null && String(inp.date).trim() !== '') {
        return flows2FormatReadyDateOperatorFacing(String(inp.date));
      }
      if (item.ready_date_display && String(item.ready_date_display).trim()) {
        return flows2FormatReadyDateOperatorFacing(String(item.ready_date_display));
      }
      return null;
    }

    /** Labels for variable_output / merged Output section (inventory item). */
    function flows2InventoryOutputFieldLabel(key) {
      const map = {
        custom_expiry_input: 'Custom expiry entered',
        custom_expiry_actual: 'Custom expiry applied',
        name: 'Name',
        quantity: 'Quantity',
        unit: 'Unit',
      };
      if (map[key]) return map[key];
      return flows2HumanFieldLabel(key);
    }

    function flows2FormatCustomExpiryObj(obj) {
      if (!obj || typeof obj !== 'object') return '';
      const mode = String(obj.mode || '');
      if (mode === 'duration') {
        const dv = obj.duration_value != null ? String(obj.duration_value) : '';
        const du = obj.duration_unit != null ? String(obj.duration_unit).replace(/_/g, ' ') : '';
        const wv = obj.warning_value != null ? String(obj.warning_value) : '';
        const wu = obj.warning_unit != null ? String(obj.warning_unit).replace(/_/g, ' ') : '';
        const parts = [];
        if (dv && du) parts.push(`${dv} ${du}`);
        if (wv && wu) parts.push(`warning ${wv} ${wu}`);
        return parts.join(' · ') || flows2SerializeForDisplay(obj);
      }
      if (mode === 'datetime') {
        const exp = obj.expiry_at || obj.expiryAt || '';
        const warnAt = obj.warning_at || obj.warn_at || obj.warningAt || '';
        const bits = [];
        if (exp) bits.push(`Expiry at (UTC): ${flows2FmtIsoAudit(exp)}`);
        if (warnAt) bits.push(`Warning at (UTC): ${flows2FmtIsoAudit(warnAt)}`);
        return bits.join(' · ') || flows2SerializeForDisplay(obj);
      }
      try {
        return flows2SerializeForDisplay(obj);
      } catch {
        return '';
      }
    }

    function flows2FormatInventoryOutputValue(key, v) {
      if (v === null || v === undefined) return '—';
      if (typeof v === 'object' && !Array.isArray(v)) {
        if (flows2SafeKeys(v).length === 0) return '—';
        const ks = String(key || '');
        if (ks === 'ready_date_input' || ks.includes('ready_date')) {
          if (v.date != null && v.date !== '') {
            try {
              return flows2FmtIsoAudit(String(v.date));
            } catch {
              return String(v.date);
            }
          }
          return flows2SerializeForDisplay(v);
        }
        if (ks.includes('custom_expiry')) return flows2FormatCustomExpiryObj(v);
        return flows2SerializeForDisplay(v);
      }
      return String(v);
    }

    function flows2HumanFieldLabel(key) {
      const map = {
        operator_email: 'Operator email',
        operator_name: 'Operator name',
        timestamp_utc: 'Time',
        timestamp: 'Time',
        source_method: 'Source',
        quantity_added: 'Quantity added',
        supplier: 'Supplier',
        purchase_date: 'Purchase date',
        expiry_date: 'Expiry date',
        supplier_batch_number: 'Supplier batch',
        csv_row_index: 'CSV row',
        user_email: 'User email',
        quantity_reconciled: 'Quantity reconciled',
        surplus_to_live: 'Surplus to live inventory',
        reconciliation_amount: 'Reconciliation amount',
        surplus_from_reconciliation: 'Surplus from reconciliation',
        reconciled_amount: 'Reconciled amount',
      };
      if (map[key]) return map[key];
      return String(key)
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase());
    }

    function flows2HumanSourceMethod(m) {
      const map = {
        manual: 'Manual',
        csv_upload: 'CSV upload',
        barcode_scan: 'Barcode scan',
      };
      return map[m] || flows2HumanFieldLabel(String(m));
    }

    function flows2HumanReconciliationMethod(m) {
      const map = {
        add_to_inventory: 'Add to inventory',
        map_to_execution: 'Map to execution',
        map_to_untracked_at_completion: 'Map to untracked at completion',
      };
      return map[m] || String(m).replace(/_/g, ' ');
    }

    function flows2FormatPlainFieldValue(key, val) {
      if (val === null || val === undefined || val === '') return '';
      const s = String(val);
      if (key === 'timestamp_utc' || key === 'timestamp') return flows2InvFormatDate(s);
      if (key === 'purchase_date' || key === 'expiry_date') {
        try {
          return new Date(s).toLocaleDateString();
        } catch {
          return s;
        }
      }
      if (key === 'source_method') return flows2HumanSourceMethod(s);
      if (key === 'method') return flows2HumanReconciliationMethod(s);
      return s;
    }

    function flows2SystemFindingPlainMessage(f) {
      if (!f || typeof f !== 'object') return 'Something needs attention';
      const reason = (f.reason && String(f.reason).trim()) || '';
      if (reason) return reason;
      const checkId = String(f.check_id || '');
      const byCheck = {
        untracked_items: 'Untracked inventory item',
        expired_materials: 'Expiry or ingredient chain issue',
        output_expiry: 'Output expiry',
        output_ready_date: 'Output not yet ready',
      };
      return byCheck[checkId] || 'Something needs attention';
    }

    function flows2HasUntrackedSystemFinding(item) {
      const findings = item.system_findings || [];
      return findings.some((f) => f && String(f.check_id || '') === 'untracked_items');
    }

    function flows2InvAppendExecPickerKv(grid, keyText, valueText) {
      const k = document.createElement('div');
      k.className = 'exec-picker-kv__k';
      k.textContent = keyText;
      const v = document.createElement('div');
      v.className = 'exec-picker-kv__v';
      v.textContent = valueText;
      grid.appendChild(k);
      grid.appendChild(v);
    }

    function flows2InvCollectKvKeys(entry, options) {
      const skip = options.skipKeys || new Set(['user_id']);
      const preferred = options.preferredKeys || [];
      const keys = [];
      preferred.forEach((k) => {
        if (!skip.has(k) && Object.prototype.hasOwnProperty.call(entry, k)) {
          const v = entry[k];
          if (v !== undefined && v !== null && v !== '') keys.push(k);
        }
      });
      flows2SafeKeys(entry).forEach((k) => {
        if (skip.has(k) || keys.includes(k)) return;
        const v = entry[k];
        if (v === undefined || v === null || v === '') return;
        keys.push(k);
      });
      return keys;
    }

    function flows2InvAppendKvRowsFromObject(container, entry, options) {
      flows2InvCollectKvKeys(entry, options).forEach((k) => {
        const raw = entry[k];
        const label = flows2HumanFieldLabel(k);
        let display = flows2FormatPlainFieldValue(k, raw);
        if (typeof raw === 'object' && raw !== null) display = flows2SerializeForDisplay(raw);
        if (!display) return;
        const row = document.createElement('div');
        row.className = 'flows2-inv-kv';
        const s1 = document.createElement('span');
        s1.style.color = 'var(--text-secondary)';
        s1.textContent = label;
        const s2 = document.createElement('span');
        s2.textContent = display;
        row.appendChild(s1);
        row.appendChild(s2);
        container.appendChild(row);
      });
    }

    /** Audit rows — DOM nodes only (execution-modal.css .exec-picker-kv). */
    function flows2InvAppendAuditHistoryEntries(grid, history) {
      if (!Array.isArray(history) || !history.length) return;
      const uuidLike = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
      history
        .slice(-FLOWS2_MAX_AUDIT_HISTORY)
        .reverse()
        .forEach((h) => {
          if (!h || typeof h !== 'object') return;
          const when = h.timestamp_utc || h.timestamp || h.created_at || '';
          const src = h.source_method || h.source || '';
          let nameDisp = (h.operator_name && String(h.operator_name).trim()) || '';
          let emailDisp = (h.operator_email && String(h.operator_email).trim()) || '';
          if (nameDisp && uuidLike.test(nameDisp)) nameDisp = '';
          if (emailDisp && uuidLike.test(emailDisp)) emailDisp = '';
          if (!nameDisp && !emailDisp) {
            const opId = h.user_id || h.operator_id || h.user || '';
            if (opId && !uuidLike.test(String(opId).trim())) nameDisp = String(opId);
          }
          if (!nameDisp && !emailDisp) nameDisp = 'Unknown operator';
          const nameOut = nameDisp || '—';
          const emailOut = emailDisp || '—';
          let action = h.action || h.event || '';
          if (!action) action = 'inventory item added';
          const whenDisp = when ? flows2FmtIsoAudit(when) : '—';
          const srcDisp = src ? flows2PrettyLabel(String(src)) : '—';
          flows2InvAppendExecPickerKv(grid, flows2PrettyLabel('action'), flows2PrettyLabel(action));
          flows2InvAppendExecPickerKv(grid, flows2PrettyLabel('timestamp_utc'), whenDisp);
          flows2InvAppendExecPickerKv(grid, 'Operator name', nameOut);
          flows2InvAppendExecPickerKv(grid, 'Operator email', emailOut);
          flows2InvAppendExecPickerKv(grid, flows2PrettyLabel('source_method'), srcDisp);
        });
    }

    function flows2InvAppendSyntheticAuditFromTrace(grid, item, trace) {
      const ts = item.created_at || trace.completed_at || '';
      let opName = '';
      let opEmail = '';
      const cbe = trace.completed_by_email ? String(trace.completed_by_email).trim() : '';
      if (cbe) opEmail = cbe;
      const cb = trace.completed_by;
      if (cb != null && cb !== '') {
        if (typeof cb === 'object') {
          opName = flows2SerializeForDisplay(cb);
        } else {
          const s = String(cb).trim();
          if (s.includes('@')) {
            if (!opEmail) opEmail = s;
          } else {
            opName = s;
          }
        }
      }
      if (opName && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(opName.trim())) opName = '';
      let srcMethod = trace.source_method ? String(trace.source_method) : '';
      if (!srcMethod && item.source_execution_step_id) srcMethod = 'completed step';
      flows2InvAppendExecPickerKv(grid, flows2PrettyLabel('action'), 'Inventory item created');
      flows2InvAppendExecPickerKv(grid, flows2PrettyLabel('timestamp_utc'), ts ? flows2FmtIsoAudit(ts) : '—');
      flows2InvAppendExecPickerKv(grid, 'Operator name', opName || '—');
      flows2InvAppendExecPickerKv(grid, 'Operator email', opEmail || '—');
      flows2InvAppendExecPickerKv(
        grid,
        flows2PrettyLabel('source_method'),
        srcMethod ? flows2PrettyLabel(srcMethod) : '—'
      );
    }

    function flows2AppendInventoryAuditSection(frag, item) {
      const ex = item.extra_data || {};
      const audit = ex.inventory_audit_history;
      const auditArr = Array.isArray(audit) ? audit : [];
      const section = document.createElement('div');
      section.className = 'flows2-inv-detail-section';
      const h = document.createElement('h4');
      h.textContent = 'Audit history';
      section.appendChild(h);
      const grid = document.createElement('div');
      grid.className = 'exec-picker-kv';
      if (auditArr.length) {
        flows2InvAppendAuditHistoryEntries(grid, auditArr);
        section.appendChild(grid);
        frag.appendChild(section);
        return;
      }
      const trace = ex.execution_trace;
      if (trace && typeof trace === 'object' && flows2SafeKeys(trace).length) {
        flows2InvAppendSyntheticAuditFromTrace(grid, item, trace);
        section.appendChild(grid);
        frag.appendChild(section);
        return;
      }
      const empty = document.createElement('p');
      empty.style.margin = '0';
      empty.style.fontSize = '13px';
      empty.style.color = 'var(--text-secondary,#6b7280)';
      empty.textContent = 'No audit entries recorded for this item.';
      section.appendChild(empty);
      frag.appendChild(section);
    }

    /**
     * System findings messages plus, only when check_id untracked_items is present: remaining to reconcile
     * and reconciliation activity. No reconciliation UI when that finding is absent.
     */
    function flows2AppendInventorySystemFindingsSection(frag, item) {
      const ex = item.extra_data || {};
      const findings = item.system_findings;
      const hasUntracked = flows2HasUntrackedSystemFinding(item);

      const messagesFrag = document.createDocumentFragment();
      if (findings && findings.length) {
        const messages = [];
        findings.forEach((f) => {
          const msg = flows2SystemFindingPlainMessage(f);
          if (msg && !messages.includes(msg)) messages.push(msg);
        });
        messages.slice(0, FLOWS2_MAX_SYSTEM_FINDING_MESSAGES).forEach((m) => {
          const div = document.createElement('div');
          div.style.margin = '0 0 10px 0';
          div.style.fontSize = '13px';
          div.style.lineHeight = '1.4';
          div.style.color = 'var(--text-primary,#111827)';
          div.textContent = m;
          messagesFrag.appendChild(div);
        });
      }

      let untrackedOuter = null;
      if (hasUntracked) {
        const remainingBal = ex.remaining_balance_to_reconcile;
        const hasRemaining =
          remainingBal !== undefined && remainingBal !== null && String(remainingBal).trim() !== '';
        const arr = Array.isArray(ex.reconciliation_history) ? ex.reconciliation_history : [];
        const preferred = [
          'timestamp',
          'user_email',
          'method',
          'quantity_reconciled',
          'surplus_to_live',
          'reconciliation_amount',
          'surplus_from_reconciliation',
        ];

        const extras = document.createElement('div');
        if (hasRemaining) {
          const grid = document.createElement('div');
          grid.className = 'exec-picker-kv';
          flows2InvAppendExecPickerKv(grid, 'Remaining to reconcile', String(remainingBal));
          extras.appendChild(grid);
        }

        const boxesFrag = document.createDocumentFragment();
        arr.slice(0, FLOWS2_MAX_RECONCILIATION_BLOCKS).forEach((entry) => {
          if (!entry || typeof entry !== 'object') return;
          const inner = document.createElement('div');
          flows2InvAppendKvRowsFromObject(inner, entry, {
            preferredKeys: preferred,
            skipKeys: new Set(['user_id']),
          });
          if (!inner.childNodes.length) return;
          const box = document.createElement('div');
          box.style.cssText =
            'padding:12px;border:1px solid var(--border-default,#e5e7eb);border-radius:10px;margin-bottom:10px;background:var(--bg-secondary,#f9fafb);';
          box.appendChild(inner);
          boxesFrag.appendChild(box);
        });

        if (boxesFrag.childNodes.length) {
          const hdr = document.createElement('div');
          hdr.style.cssText = `${hasRemaining ? 'margin-top:14px;' : ''}margin-bottom:10px;font-size:12px;font-weight:600;color:var(--text-secondary,#6b7280);letter-spacing:0.03em;text-transform:uppercase;`;
          hdr.textContent = 'Reconciliation activity';
          extras.appendChild(hdr);
          extras.appendChild(boxesFrag);
        }

        if (extras.childNodes.length) {
          untrackedOuter = extras;
          if (messagesFrag.childNodes.length) {
            untrackedOuter.style.marginTop = '12px';
            untrackedOuter.style.paddingTop = '12px';
            untrackedOuter.style.borderTop = '1px solid var(--border-light,#e5e7eb)';
          }
        }
      }

      if (!messagesFrag.childNodes.length && !untrackedOuter) return;

      const section = document.createElement('div');
      section.className = 'flows2-inv-detail-section';
      const h = document.createElement('h4');
      h.textContent = 'System findings';
      section.appendChild(h);
      section.appendChild(messagesFrag);
      if (untrackedOuter) section.appendChild(untrackedOuter);
      frag.appendChild(section);
    }

    function flows2AppendInventoryOutputSection(frag, item) {
      const ex = item.extra_data || {};
      const vOut = ex.variable_output;
      const pairs = [];
      const skipOutKeys = new Set(['ready_date_input', 'ready_date_actual']);

      if (vOut && typeof vOut === 'object') {
        flows2SafeKeys(vOut).forEach((k) => {
          if (skipOutKeys.has(k)) return;
          const v = vOut[k];
          const label = flows2InventoryOutputFieldLabel(k);
          const display = flows2FormatInventoryOutputValue(k, v);
          pairs.push([label, display]);
        });
      }

      const readyOne = flows2InventorySingleReadyDate(item);
      if (readyOne) pairs.unshift(['Ready date', readyOne]);

      const vOutHas = (key) =>
        vOut && typeof vOut === 'object' && Object.prototype.hasOwnProperty.call(vOut, key);

      const cea = ex.custom_expiry_actual;
      if (
        !vOutHas('custom_expiry_actual') &&
        cea &&
        typeof cea === 'object' &&
        flows2SafeKeys(cea).length > 0
      ) {
        pairs.push(['Custom expiry applied', flows2FormatCustomExpiryObj(cea) || '—']);
      }

      if (!pairs.length) return;

      const section = document.createElement('div');
      section.className = 'flows2-inv-detail-section';
      const h = document.createElement('h4');
      h.textContent = 'Output';
      section.appendChild(h);
      const grid = document.createElement('div');
      grid.className = 'exec-picker-kv';
      pairs.forEach(([lab, val]) => flows2InvAppendExecPickerKv(grid, lab, String(val)));
      section.appendChild(grid);
      frag.appendChild(section);
    }

    function flows2AppendInventoryProductionBlock(frag, item) {
      const ex = item.extra_data || {};
      const producingProcessName = ex.producing_process_name ? String(ex.producing_process_name).trim() : '';
      const grid = document.createElement('div');
      grid.className = 'exec-picker-kv';
      let any = false;
      if (item.process_name) {
        flows2InvAppendExecPickerKv(grid, 'Process', String(item.process_name));
        any = true;
      }
      if (
        producingProcessName &&
        (!item.process_name || String(item.process_name) !== producingProcessName)
      ) {
        flows2InvAppendExecPickerKv(grid, 'Producing process', producingProcessName);
        any = true;
      }
      const stepName =
        (item.producing_step_name && String(item.producing_step_name).trim()) ||
        (ex.producing_step_name && String(ex.producing_step_name).trim()) ||
        '';
      if (stepName) {
        flows2InvAppendExecPickerKv(grid, 'Producing step', stepName);
        any = true;
      }
      if (!any) return;
      const wrap = document.createElement('div');
      wrap.style.marginTop = '0';
      const lbl = document.createElement('div');
      lbl.style.cssText =
        'font-size: 12px; font-weight: 700; color: var(--text-secondary,#6b7280); letter-spacing:0.03em; text-transform: uppercase; margin-bottom: 8px;';
      lbl.textContent = 'Production';
      wrap.appendChild(lbl);
      wrap.appendChild(grid);
      frag.appendChild(wrap);
    }

    function flows2AppendInventoryInputsSection(frag, item) {
      if (!flows2InventoryIsProducedItem(item)) return;
      const ex = item.extra_data || {};
      const fq = flows2InvFormatQty;
      const vInputs = ex.variable_inputs;
      const section = document.createElement('div');
      section.className = 'flows2-inv-detail-section';
      const h = document.createElement('h4');
      h.textContent = 'Inputs';
      section.appendChild(h);
      if (Array.isArray(vInputs) && vInputs.length) {
        vInputs.slice(0, FLOWS2_MAX_IO_ROWS_PER_STEP).forEach((input) => {
          const box = document.createElement('div');
          box.style.cssText =
            'padding:10px;background:var(--bg-secondary,#f9fafb);border-radius:8px;border:1px solid var(--border-light,#e5e7eb);margin-bottom:8px;';
          const p1 = document.createElement('p');
          p1.style.margin = '0 0 4px';
          p1.style.fontWeight = '600';
          p1.textContent = input.name || 'Input';
          const p2 = document.createElement('p');
          p2.style.margin = '4px 0 0';
          p2.style.fontSize = '12px';
          p2.style.color = 'var(--text-secondary)';
          p2.textContent = `${fq(input.quantity)} ${input.unit || ''}`.trim();
          box.appendChild(p1);
          box.appendChild(p2);
          section.appendChild(box);
        });
      } else {
        const p = document.createElement('p');
        p.style.margin = '0';
        p.style.fontSize = '13px';
        p.style.color = 'var(--text-secondary,#6b7280)';
        p.textContent = 'No inputs recorded for this step.';
        section.appendChild(p);
      }
      frag.appendChild(section);
    }

    function flows2AppendInventoryUpstreamSection(frag, item) {
      const ex = item.extra_data || {};
      const fq = flows2InvFormatQty;
      const fd = flows2InvFormatDate;
      const prevSteps = ex.previous_steps_data;
      if (!Array.isArray(prevSteps) || !prevSteps.length) return;

      const section = document.createElement('div');
      section.className = 'flows2-inv-detail-section';
      const h = document.createElement('h4');
      h.textContent = 'Upstream chain';
      section.appendChild(h);

      prevSteps.slice(0, FLOWS2_MAX_UPSTREAM_STEPS).forEach((step) => {
        const box = document.createElement('div');
        box.style.cssText =
          'padding:12px;border:1px solid var(--border-default,#e5e7eb);border-radius:10px;margin-bottom:10px;background:var(--bg-secondary,#f9fafb);';
        const sn = step.step_name || 'Step';
        const snum = step.step_number != null ? `#${step.step_number}` : '';
        const p1 = document.createElement('p');
        p1.style.margin = '0 0 8px';
        p1.style.fontWeight = '600';
        p1.textContent = `${sn} ${snum}`.trim();
        box.appendChild(p1);
        if (step.completed_at) {
          const p2 = document.createElement('p');
          p2.style.cssText = 'margin:0 0 6px;font-size:12px;color:var(--text-secondary);';
          p2.textContent = `Completed: ${fd(step.completed_at)}`;
          box.appendChild(p2);
        }
        if (step.input_name) {
          const p3 = document.createElement('p');
          p3.style.cssText = 'margin:0 0 4px;font-size:12px;';
          p3.textContent = `Consumed: ${step.input_name} — ${fq(step.input_quantity)} ${step.input_unit || ''}`;
          box.appendChild(p3);
        }
        const sp = step.execution_prompts;
        if (sp && typeof sp === 'object' && flows2SafeKeys(sp).length) {
          const pl = document.createElement('p');
          pl.style.cssText = 'margin:8px 0 4px;font-size:11px;font-weight:600;color:var(--text-secondary);';
          pl.textContent = 'Prompts in chain';
          box.appendChild(pl);
          flows2SafeKeys(sp)
            .slice(0, FLOWS2_MAX_PROMPT_ENTRIES)
            .forEach((k) => {
              const row = document.createElement('div');
              row.className = 'flows2-inv-kv';
              const s1 = document.createElement('span');
              s1.textContent = k;
              const s2 = document.createElement('span');
              s2.textContent = flows2SerializeForDisplay(sp[k]);
              row.appendChild(s1);
              row.appendChild(s2);
              box.appendChild(row);
            });
        }
        if (step.completed_by) {
          const row = document.createElement('div');
          row.className = 'flows2-inv-kv';
          const s1 = document.createElement('span');
          s1.textContent = 'Completed by';
          const s2 = document.createElement('span');
          s2.textContent = flows2SerializeForDisplay(step.completed_by);
          row.appendChild(s1);
          row.appendChild(s2);
          box.appendChild(row);
        }
        if (step.execution_errors) {
          const pe = document.createElement('p');
          pe.style.cssText = 'margin:8px 0 0;font-size:12px;color:var(--error,#b91c1c);';
          pe.textContent = flows2SerializeForDisplay(step.execution_errors);
          box.appendChild(pe);
        }
        if (step.execution_warnings) {
          const pw = document.createElement('p');
          pw.style.cssText = 'margin:4px 0 0;font-size:12px;color:var(--warning,#b45309);';
          pw.textContent = flows2SerializeForDisplay(step.execution_warnings);
          box.appendChild(pw);
        }
        section.appendChild(box);
      });
      frag.appendChild(section);
    }

    /** DOM-only inventory details (no innerHTML); appended under `.execution-content`. */
    function buildFlows2InventoryDetailsFragment(item) {
      const frag = document.createDocumentFragment();
      const ex = item.extra_data || {};

      flows2AppendInventoryProductionBlock(frag, item);
      flows2AppendInventorySystemFindingsSection(frag, item);

      const prompts = ex.execution_prompts;
      if (prompts && typeof prompts === 'object' && flows2SafeKeys(prompts).length) {
        const sec = document.createElement('div');
        sec.className = 'flows2-inv-detail-section';
        const h = document.createElement('h4');
        h.textContent = 'Custom prompts';
        sec.appendChild(h);
        const grid = document.createElement('div');
        grid.className = 'exec-picker-kv';
        flows2SafeKeys(prompts)
          .slice(0, FLOWS2_MAX_PROMPT_ENTRIES)
          .forEach((k) => {
            flows2InvAppendExecPickerKv(grid, flows2PrettyLabel(k), flows2SerializeForDisplay(prompts[k]));
          });
        sec.appendChild(grid);
        frag.appendChild(sec);
      }

      flows2AppendInventoryInputsSection(frag, item);
      flows2AppendInventoryOutputSection(frag, item);
      flows2AppendInventoryUpstreamSection(frag, item);

      const notes = (ex.notes && String(ex.notes).trim()) || '';
      if (notes) {
        const sec = document.createElement('div');
        sec.className = 'flows2-inv-detail-section';
        const hn = document.createElement('h4');
        hn.textContent = 'Notes';
        sec.appendChild(hn);
        const p = document.createElement('p');
        p.style.margin = '0';
        p.style.whiteSpace = 'pre-wrap';
        p.style.fontSize = '13px';
        p.textContent = notes;
        sec.appendChild(p);
        frag.appendChild(sec);
      }

      flows2AppendInventoryAuditSection(frag, item);
      return frag;
    }

    function createInventoryItemCardFlows(item) {
      const isUntracked = item.extra_data && item.extra_data.untracked === true;
      const card = document.createElement('div');
      card.className = 'execution-card' + (isUntracked ? ' inventory-card-untracked' : '');
      card.dataset.inventoryId = flows2NormalizeId(item.id);
      card.dataset.isExpanded = 'false';

      const fq = flows2InvFormatQty;
      const formattedQuantity = fq(item.quantity);
      const typeBadge = flows2InventoryTypeLabel(item.inventory_type);

      if (isUntracked) {
        const banner = document.createElement('div');
        banner.style.cssText =
          'margin-bottom: 0; padding: 10px 12px; background: hsl(0, 93%, 94%); border-bottom: 1px solid var(--border-light); color: #b91c1c; font-size: 12px; font-weight: 500;';
        banner.textContent = 'Untracked item — reconciliation may be required';
        card.appendChild(banner);
      }

      const header = document.createElement('div');
      header.className = 'execution-header flows2-inv-card-header';
      header.style.cssText =
        'display: flex; justify-content: space-between; align-items: flex-start; cursor: pointer; padding: 12px; border-bottom: 1px solid var(--border-light);';

      const left = document.createElement('div');
      left.style.cssText = 'flex: 1; min-width: 0;';

      const title = document.createElement('div');
      title.className = 'execution-id';
      title.style.cssText =
        'font-weight: 600; color: var(--text-primary); margin-bottom: 4px; word-wrap: break-word;';
      title.textContent = item.name != null ? String(item.name) : '';

      const detailsRowWrap = document.createElement('div');
      detailsRowWrap.className = 'execution-details';
      detailsRowWrap.style.cssText = 'margin-top: 8px; gap: 1rem;';

      function appendInventoryHdrRow(label, value) {
        if (value === undefined || value === null || value === '') return;
        const row = document.createElement('div');
        row.className = 'execution-detail';
        const lab = document.createElement('span');
        lab.className = 'execution-detail-label';
        lab.textContent = label;
        const val = document.createElement('span');
        val.className = 'execution-detail-value';
        val.textContent = String(value);
        row.appendChild(lab);
        row.appendChild(val);
        detailsRowWrap.appendChild(row);
      }

      appendInventoryHdrRow('Available quantity', `${formattedQuantity} ${item.unit || ''}`.trim());
      if (item.created_at) appendInventoryHdrRow('Created', flows2InvFormatDate(item.created_at));

      left.appendChild(title);
      left.appendChild(detailsRowWrap);

      const right = document.createElement('div');
      right.style.cssText = 'display: flex; align-items: center; gap: 12px; flex-shrink: 0;';

      const badge = document.createElement('span');
      badge.className = 'badge badge-accent';
      badge.style.flexShrink = '0';
      badge.textContent = typeBadge;

      const arrowWrap = document.createElement('div');
      arrowWrap.className = 'execution-toggle';
      arrowWrap.id = 'arrow-flows-' + flows2NormalizeId(item.id);
      arrowWrap.style.cssText = 'transition: transform 0.2s; transform: rotate(0deg);';
      arrowWrap.appendChild(flows2CreateChevronSvgEl16());

      right.appendChild(badge);
      right.appendChild(arrowWrap);

      header.appendChild(left);
      header.appendChild(right);
      card.appendChild(header);

      const content = document.createElement('div');
      content.className = 'execution-content';
      content.id = 'details-flows-' + flows2NormalizeId(item.id);
      content.style.cssText = 'display: none; padding: 12px;';
      content.appendChild(buildFlows2InventoryDetailsFragment(item));

      card.appendChild(content);

      header.addEventListener('click', () => {
        toggleInventoryItemDetailsFlows(String(item.id));
      });

      return card;
    }

    function flows2RenderInventoryList(items) {
      const container = document.getElementById('inventory-container');
      if (!container) return;

      container.replaceChildren();

      if (!flows2Inventory.allItems.length) {
        const empty = document.createElement('div');
        empty.className = 'flows2-inv-empty';
        const p = document.createElement('p');
        p.textContent = 'No inventory items for this process.';
        empty.appendChild(p);
        container.appendChild(empty);
        return;
      }

      if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'flows2-inv-empty';
        const p = document.createElement('p');
        p.textContent = 'No items in this category.';
        empty.appendChild(p);
        container.appendChild(empty);
        return;
      }

      items.forEach((item) => {
        container.appendChild(createInventoryItemCardFlows(item));
      });
    }

    function flows2RerenderInventory() {
      const items = flows2GetFilteredInventoryItems();
      flows2RenderInventoryList(items);
    }

    async function loadInventory() {
      if (!processId) return;
      const requestedPid = processId;
      const { signal, gen } = Flows2InvLoad.begin();
      try {
        const inventoryData = await CoreAPI.getInventory(null, requestedPid, { signal });
        if (gen !== Flows2InvLoad.generation || requestedPid !== processId) return;
        const items = inventoryData.inventory_items || [];
        flows2SetInventoryFromApi(items, requestedPid);
        flows2RerenderInventory();
      } catch (error) {
        if (error && error.name === 'AbortError') return;
        console.error('Failed to load inventory:', error);
        showNotification('error', 'Failed to Load Inventory', error.message || 'Failed to load inventory');
      }
    }

    function toggleInventoryItemDetailsFlows(itemId) {
      const idStr = String(itemId);
      const escAttr = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(idStr) : idStr.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
      const card = document.querySelector(`[data-inventory-id="${escAttr}"]`);
      if (!card) return;
      const details = flows2QueryById('details-flows-' + idStr);
      const arrow = flows2QueryById('arrow-flows-' + idStr);
      if (!details || !arrow) return;
      const isExpanded = card.dataset.isExpanded === 'true';

      if (isExpanded) {
        details.style.display = 'none';
        arrow.style.transform = 'rotate(0deg)';
        card.dataset.isExpanded = 'false';
      } else {
        details.style.display = 'block';
        arrow.style.transform = 'rotate(180deg)';
        card.dataset.isExpanded = 'true';
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
      }
    }
    
