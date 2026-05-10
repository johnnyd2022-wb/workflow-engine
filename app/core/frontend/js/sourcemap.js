/* ─────────────────────────────────────────────────────────────
   Sourcemap V2  –  sourcemap.js
   Script lives inside #page-content so HTMX re-executes on swap.
───────────────────────────────────────────────────────────────*/

(function () {
  'use strict';

  /* ── State ─────────────────────────────────────────────── */
  let allProcesses = [];
  let allInventory = [];
  let allExecutions = [];
  let allExecutionMetadata = [];
  let allOutOfStockRawMaterials = [];
  let checkNeededData = { expired_raw_materials: [], impacted_items: [], connections: [], untracked_items: [] };
  let findingsData = { expired: [], untracked: [], expiry: [], ready: [] };

  let tracedItemId = null;
  let tracedItemName = '';
  let tracedItemBatch = '';
  let lastTraceResult = null;
  let currentView = 'timeline';       // 'timeline' | 'map' | 'table'
  let currentBrowseTab = 'inventory'; // 'inventory' | 'batches' | 'suppliers' | 'operators' | 'activity'
  let showWastage = false;
  let currentFindingsTab = 'all';
  let allInventoryForSearch = [];
  let filterQuery = '';
  let filterTimeout = null;
  let activityStartDate = '';
  let activityEndDate = '';

  /* ── Boot ──────────────────────────────────────────────── */
  function smBoot() {
    if (!document.getElementById('sm-trace-area')) return;
    smBindControls();
    smInitSearch();
    smBindModal();
    smLoadAllData();
  }

  /* ── Data loading ──────────────────────────────────────── */
  async function smLoadAllData() {
    smShowAreaLoading();
    try {
      const [
        processesData,
        inventoryData,
        executionsData,
        metadataData,
        outOfStockData,
        expiredResult,
        untrackedResult,
      ] = await Promise.all([
        CoreAPI.getProcesses(true).catch(() => ({ processes: [] })),
        CoreAPI.getInventory().catch(() => ({ inventory_items: [] })),
        CoreAPI.getExecutions().catch(() => ({ executions: [] })),
        CoreAPI.getExecutionMetadata().catch(() => ({ metadata: [] })),
        CoreAPI.getOutOfStockRawMaterials().catch(() => ({ inventory_items: [] })),
        CoreAPI.getExpiredMaterials().catch(() => ({ expired_raw_materials: [], impacted_items: [], connections: [] })),
        CoreAPI.getUntrackedItems().catch(() => ({ untracked_items: [], connections: [] })),
      ]);

      allProcesses = processesData.processes || [];
      allInventory = inventoryData.inventory_items || [];
      allExecutions = (executionsData.executions || []).filter(e => e && e.id);
      allExecutionMetadata = metadataData.metadata || [];
      allOutOfStockRawMaterials = outOfStockData.inventory_items || [];
      checkNeededData = expiredResult || { expired_raw_materials: [], impacted_items: [], connections: [] };
      checkNeededData.untracked_items = (untrackedResult && untrackedResult.untracked_items) ? untrackedResult.untracked_items : [];

      smUpdateSearchPool();
      smRenderBrowseGrid();
      smLoadFindings();

      const params = new URLSearchParams(window.location.search);
      if (params.get('show') === 'check-needed') smSwitchFindingsTab('expired');
    } catch (err) {
      console.error('[sourcemap] load failed', err);
      const area = document.getElementById('sm-trace-area');
      if (area) area.innerHTML = smEmptyState('Failed to load data. Please refresh the page.');
    }
  }

  /* ── Browse grid (idle state) ────────────────────────────── */
  function smRenderBrowseGrid() {
    const area = document.getElementById('sm-trace-area');
    if (!area) return;
    area.innerHTML = '';

    smSetControlsVisible(false);

    const container = document.createElement('div');
    container.className = 'sm-browse';

    // Category tabs
    const tabs = [
      { key: 'inventory', label: 'Inventory' },
      { key: 'batches',   label: 'Batches' },
      { key: 'suppliers', label: 'Suppliers' },
      { key: 'operators', label: 'Operators' },
      { key: 'activity',  label: 'Activity' },
    ];

    const tabStrip = document.createElement('div');
    tabStrip.className = 'sm-browse-seg';
    tabStrip.setAttribute('role', 'tablist');
    tabs.forEach(t => {
      const btn = document.createElement('button');
      btn.className = 'sm-browse-seg__btn' + (t.key === currentBrowseTab ? ' sm-browse-seg__btn--active' : '');
      btn.dataset.browseTab = t.key;
      btn.textContent = t.label;
      btn.setAttribute('role', 'tab');
      btn.setAttribute('aria-selected', t.key === currentBrowseTab ? 'true' : 'false');
      btn.addEventListener('click', () => {
        currentBrowseTab = t.key;
        tabStrip.querySelectorAll('.sm-browse-seg__btn').forEach(b => {
          b.classList.toggle('sm-browse-seg__btn--active', b.dataset.browseTab === t.key);
          b.setAttribute('aria-selected', b.dataset.browseTab === t.key ? 'true' : 'false');
        });
        // Activity tab uses block layout; all others use grid
        grid.style.display = t.key === 'activity' ? 'block' : '';
        smRefreshBrowseCards(grid);
      });
      tabStrip.appendChild(btn);
    });
    container.appendChild(tabStrip);

    const grid = document.createElement('div');
    grid.className = 'sm-browse-grid';
    container.appendChild(grid);

    area.appendChild(container);
    smRefreshBrowseCards(grid);
  }

  function smRefreshBrowseCards(grid) {
    grid.innerHTML = '';
    const q = filterQuery.toLowerCase();

    switch (currentBrowseTab) {
      case 'inventory': {
        const items = allInventoryForSearch.filter(it => {
          if (!it || !it.name) return false;
          if (!q) return true;
          return it.name.toLowerCase().includes(q)
            || (it.supplier_batch_number || '').toLowerCase().includes(q)
            || (it.supplier || '').toLowerCase().includes(q);
        });

        // Group by name, show type breakdown
        const byName = new Map();
        items.forEach(it => {
          if (!it.name) return;
          if (!byName.has(it.name)) byName.set(it.name, []);
          byName.get(it.name).push(it);
        });

        if (!byName.size) {
          grid.innerHTML = smBrowseEmpty(q ? `No inventory items matching "${q}"` : 'No inventory items found.');
          return;
        }

        [...byName.entries()]
          .sort(([a], [b]) => a.toLowerCase().localeCompare(b.toLowerCase()))
          .forEach(([name, group]) => grid.appendChild(smBuildInventoryBrowseCard(name, group)));
        break;
      }

      case 'batches': {
        const batchMap = new Map();
        allInventoryForSearch.forEach(it => {
          const bn = it.supplier_batch_number;
          if (!bn) return;
          if (q && !bn.toLowerCase().includes(q) && !(it.name || '').toLowerCase().includes(q)) return;
          if (!batchMap.has(bn)) batchMap.set(bn, []);
          batchMap.get(bn).push(it);
        });

        if (!batchMap.size) {
          grid.innerHTML = smBrowseEmpty(q ? `No batches matching "${q}"` : 'No batch numbers recorded.');
          return;
        }

        [...batchMap.entries()]
          .sort(([a], [b]) => a.localeCompare(b))
          .forEach(([bn, items]) => grid.appendChild(smBuildBatchBrowseCard(bn, items)));
        break;
      }

      case 'suppliers': {
        const supplierMap = new Map();
        allInventoryForSearch.forEach(it => {
          const sup = it.supplier;
          if (!sup) return;
          if (q && !sup.toLowerCase().includes(q)) return;
          if (!supplierMap.has(sup)) supplierMap.set(sup, []);
          supplierMap.get(sup).push(it);
        });

        if (!supplierMap.size) {
          grid.innerHTML = smBrowseEmpty(q ? `No suppliers matching "${q}"` : 'No suppliers recorded.');
          return;
        }

        [...supplierMap.entries()]
          .sort(([a], [b]) => a.localeCompare(b))
          .forEach(([sup, items]) => grid.appendChild(smBuildSupplierBrowseCard(sup, items)));
        break;
      }

      case 'operators': {
        const personMap = new Map();
        (allExecutions || []).forEach(exec => {
          const person = exec.completed_by || exec.created_by;
          if (!person) return;
          if (q && !person.toLowerCase().includes(q)) return;
          if (!personMap.has(person)) personMap.set(person, []);
          personMap.get(person).push(exec);
        });

        if (!personMap.size) {
          grid.innerHTML = smBrowseEmpty(q ? `No operators matching "${q}"` : 'No operator data recorded on executions yet.');
          return;
        }

        [...personMap.entries()]
          .sort(([a], [b]) => a.localeCompare(b))
          .forEach(([person, execs]) => grid.appendChild(smBuildOperatorBrowseCard(person, execs)));
        break;
      }

      case 'activity': {
        // Switch grid to block layout so the timeline renders full-width (not card grid)
        grid.style.display = 'block';

        const hasFilter = activityStartDate || activityEndDate;
        const pickerDiv = document.createElement('div');
        pickerDiv.className = 'sm-act-picker';
        pickerDiv.innerHTML = `
          <label class="sm-act-picker__label" for="sm-act-start">From</label>
          <input type="date" class="sm-act-date-input" id="sm-act-start" value="${smEsc(activityStartDate)}">
          <label class="sm-act-picker__label" for="sm-act-end">To</label>
          <input type="date" class="sm-act-date-input" id="sm-act-end" value="${smEsc(activityEndDate)}">
          <button class="sm-act-filter-btn" id="sm-act-apply">Show</button>
          ${hasFilter ? '<button class="sm-act-clear-btn" id="sm-act-clear">Clear</button>' : ''}
        `;
        grid.appendChild(pickerDiv);

        const startD = activityStartDate ? new Date(activityStartDate + 'T00:00:00') : null;
        const endD   = activityEndDate   ? new Date(activityEndDate   + 'T23:59:59') : null;

        let filtered = [...(allExecutions || [])];
        if (q) {
          filtered = filtered.filter(exec => {
            const proc = allProcesses.find(p => p.id === exec.process_id);
            const name = proc ? proc.name.toLowerCase() : '';
            return name.includes(q) || (exec.completed_by || '').toLowerCase().includes(q);
          });
        }
        if (startD) filtered = filtered.filter(e => new Date(e.started_at || e.created_at || 0) >= startD);
        if (endD)   filtered = filtered.filter(e => new Date(e.started_at || e.created_at || 0) <= endD);
        filtered.sort((a, b) => new Date(b.started_at || b.created_at || 0) - new Date(a.started_at || a.created_at || 0));

        if (!filtered.length) {
          const msg = (hasFilter || q)
            ? (q ? `No activity matching "${q}"` : 'No activity in selected date range.')
            : 'Pick a date range or use the search bar to browse production activity.';
          grid.insertAdjacentHTML('beforeend', `<div class="sm-browse-empty" style="margin-top:16px">${smEsc(msg)}</div>`);
        } else {
          // Render inline activity timeline — same as operator tracing, no separate card step
          const tl = smBuildInlineActivityTimeline(filtered);
          grid.appendChild(tl);
        }

        // Wire controls
        const applyBtn = pickerDiv.querySelector('#sm-act-apply');
        const wireApply = () => {
          activityStartDate = (pickerDiv.querySelector('#sm-act-start') || {}).value || '';
          activityEndDate   = (pickerDiv.querySelector('#sm-act-end')   || {}).value || '';
          smRefreshBrowseCards(grid);
        };
        if (applyBtn) applyBtn.addEventListener('click', wireApply);
        const clearBtn = pickerDiv.querySelector('#sm-act-clear');
        if (clearBtn) {
          clearBtn.addEventListener('click', () => {
            activityStartDate = '';
            activityEndDate   = '';
            smRefreshBrowseCards(grid);
          });
        }
        pickerDiv.querySelectorAll('.sm-act-date-input').forEach(inp => {
          inp.addEventListener('keydown', e => { if (e.key === 'Enter') wireApply(); });
        });
        break;
      }
    }
  }

  function smBuildInventoryBrowseCard(name, group) {
    const typeOrder = { raw_material: 0, work_in_progress: 1, final_product: 2 };
    const sorted = [...group].sort((a, b) => (typeOrder[a.inventory_type] || 0) - (typeOrder[b.inventory_type] || 0));
    const primary = sorted.find(it => !it._oos) || sorted[0];
    const typeClass = smTypeClass(primary.inventory_type);
    const inStock = group.filter(it => !it._oos);
    const hasCheck = group.some(it => smIsCheckNeeded(it.id));

    const card = document.createElement('div');
    card.className = 'sm-browse-card sm-browse-card--inventory' + (hasCheck ? ' sm-browse-card--check' : '');

    const qtyParts = [];
    if (primary.quantity != null) qtyParts.push(`${smFmtQty(primary.quantity)}${primary.unit ? ' ' + primary.unit : ''}`);
    const batchText = primary.supplier_batch_number ? `Batch ${primary.supplier_batch_number}` : '';
    const supplierText = primary.supplier || '';

    card.innerHTML = `
      <div class="sm-browse-card__header">
        <span class="sm-type-badge sm-type-badge--${typeClass}">${smTypeLabelShort(primary.inventory_type)}</span>
        ${hasCheck ? '<span class="sm-check-pill">⚠</span>' : ''}
      </div>
      <div class="sm-browse-card__name">${smEsc(name)}</div>
      ${qtyParts.length ? `<div class="sm-browse-card__meta">${smEsc(qtyParts.join(' · '))}</div>` : ''}
      ${batchText ? `<div class="sm-browse-card__meta sm-browse-card__meta--muted">${smEsc(batchText)}</div>` : ''}
      ${supplierText ? `<div class="sm-browse-card__meta sm-browse-card__meta--muted">${smEsc(supplierText)}</div>` : ''}
      ${inStock.length > 1 ? `<div class="sm-browse-card__count">${inStock.length} lots in stock</div>` : ''}
    `;

    card.addEventListener('click', () => {
      if (group.length === 1) {
        const it = group[0];
        smTraceItem(it.id, it.name, it.supplier_batch_number, it.inventory_type !== 'raw_material');
      } else {
        smShowBatchModal(name, group);
      }
    });

    return card;
  }

  function smBuildBatchBrowseCard(batchNumber, items) {
    const uniqueItems = [...new Map(items.map(it => [it.name, it])).values()];
    const suppliers = [...new Set(items.map(it => it.supplier).filter(Boolean))];

    const card = document.createElement('div');
    card.className = 'sm-browse-card sm-browse-card--batch';
    card.innerHTML = `
      <div class="sm-browse-card__header">
        <span class="sm-browse-card__type-label">Batch</span>
      </div>
      <div class="sm-browse-card__name">${smEsc(batchNumber)}</div>
      <div class="sm-browse-card__meta">${uniqueItems.length} item type${uniqueItems.length !== 1 ? 's' : ''}</div>
      ${suppliers.length ? `<div class="sm-browse-card__meta sm-browse-card__meta--muted">${smEsc(suppliers.join(', '))}</div>` : ''}
    `;

    card.addEventListener('click', () => {
      if (items.length === 1) {
        const it = items[0];
        smTraceItem(it.id, it.name, it.supplier_batch_number, it.inventory_type !== 'raw_material');
      } else {
        smShowBatchModal(`Batch: ${batchNumber}`, items);
      }
    });

    return card;
  }

  function smBuildSupplierBrowseCard(supplier, items) {
    const uniqueNames = [...new Set(items.map(it => it.name).filter(Boolean))];

    const card = document.createElement('div');
    card.className = 'sm-browse-card sm-browse-card--supplier';
    card.innerHTML = `
      <div class="sm-browse-card__header">
        <span class="sm-browse-card__type-label">Supplier</span>
      </div>
      <div class="sm-browse-card__name">${smEsc(supplier)}</div>
      <div class="sm-browse-card__meta">${uniqueNames.length} item type${uniqueNames.length !== 1 ? 's' : ''}</div>
      ${uniqueNames.slice(0, 3).map(n => `<div class="sm-browse-card__meta sm-browse-card__meta--muted">${smEsc(n)}</div>`).join('')}
      ${uniqueNames.length > 3 ? `<div class="sm-browse-card__meta sm-browse-card__meta--muted">+ ${uniqueNames.length - 3} more</div>` : ''}
    `;

    card.addEventListener('click', () => smShowBatchModal(`Supplier: ${supplier}`, items));
    return card;
  }

  function smBuildOperatorBrowseCard(person, execs) {
    const sorted = [...execs].sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
    const lastExec = sorted[0];
    const processNames = [...new Set(execs.map(e => {
      const proc = allProcesses.find(p => p.id === e.process_id);
      return proc ? proc.name : null;
    }).filter(Boolean))];

    const card = document.createElement('div');
    card.className = 'sm-browse-card sm-browse-card--operator';
    card.innerHTML = `
      <div class="sm-browse-card__header">
        <span class="sm-browse-card__type-label">Operator</span>
      </div>
      <div class="sm-browse-card__name">${smEsc(person)}</div>
      <div class="sm-browse-card__meta">${execs.length} execution${execs.length !== 1 ? 's' : ''}</div>
      ${lastExec ? `<div class="sm-browse-card__meta sm-browse-card__meta--muted">Last: ${smFmtDate(lastExec.created_at)}</div>` : ''}
      ${processNames.slice(0, 2).map(n => `<div class="sm-browse-card__meta sm-browse-card__meta--muted">${smEsc(n)}</div>`).join('')}
    `;

    card.addEventListener('click', () => smTraceByPerson(person, execs));
    return card;
  }

  /* Shared timeline builder used by both inline Activity tab and smRenderActivityLog */
  function smBuildInlineActivityTimeline(execs) {
    const groups = smBuildActivityGroups(execs);

    const tl = document.createElement('div');
    tl.className = 'sm-timeline sm-activity-log';
    tl.style.marginTop = '16px';

    if (!groups.length) {
      tl.innerHTML = '<div class="sm-timeline-empty">No production steps recorded for these executions.</div>';
      return tl;
    }

    groups.forEach((group, idx) => {
      const isLast = idx === groups.length - 1;
      const entry = document.createElement('div');
      entry.className = 'sm-timeline-entry' + (isLast ? ' sm-timeline-entry--last' : '');
      const detailId = `sm-act-tl-${idx}`;

      const stepsHtml = group.steps.map(step => {
        const stepDate = step.tos.length && step.tos[0].step_data && step.tos[0].step_data.completed_at
          ? step.tos[0].step_data.completed_at : null;
        return `
          <div class="sm-timeline-step-row">
            <span class="sm-timeline-label">Step</span>
            ${step.stepName ? `<span class="sm-timeline-step-name">${smEsc(step.stepName)}</span>` : '<span class="sm-timeline-step-name">—</span>'}
            ${stepDate ? `<span class="sm-timeline-step-date">${smFmtDate(stepDate)}</span>` : ''}
          </div>`;
      }).join('');

      entry.innerHTML = `
        <div class="sm-timeline-dot-col" aria-hidden="true">
          <div class="sm-timeline-dot"></div>
          ${!isLast ? '<div class="sm-timeline-line"></div>' : ''}
        </div>
        <div class="sm-timeline-content">
          <div class="sm-timeline-meta">
            <span class="sm-timeline-label">Process</span>
            <span class="sm-timeline-process">${smEsc(group.processName)}</span>
            ${group.executionDate ? `<span class="sm-timeline-date">${smFmtDate(group.executionDate)}</span>` : ''}
          </div>
          ${stepsHtml ? `<div class="sm-timeline-steps-list">${stepsHtml}</div>` : ''}
          ${group.operator ? `<div class="sm-timeline-operator">
            <span class="sm-timeline-label">Completed by</span>
            <span>${smEsc(group.operator)}</span>
          </div>` : ''}
          <button class="sm-timeline-expand-btn" aria-expanded="false" aria-controls="${detailId}">Details ›</button>
          <div class="sm-timeline-detail" id="${detailId}" hidden></div>
        </div>
      `;

      const detailDiv = entry.querySelector(`#${detailId}`);
      if (group.steps.some(s => s.tos.length)) {
        group.steps.forEach(step => {
          if (!step.tos.length) return;
          const section = document.createElement('div');
          section.className = 'sm-tl-step-section';
          if (step.stepName) {
            const hdr = document.createElement('div');
            hdr.className = 'sm-tl-step-header';
            hdr.textContent = step.stepName;
            section.appendChild(hdr);
          }
          const lbl = document.createElement('div');
          lbl.className = 'sm-tl-io-label sm-tl-io-label--out';
          lbl.textContent = 'Produced';
          section.appendChild(lbl);
          const grid2 = document.createElement('div');
          grid2.className = 'sm-tl-detail-grid';
          step.tos.forEach(item => {
            const out = item.step_data && item.step_data.actual_outputs
              ? item.step_data.actual_outputs.find(o => o.name === item.name) : null;
            const historicalQty = out ? `${smFmtQty(out.quantity)}${out.unit ? ' ' + out.unit : ''}`.trim() : null;
            grid2.appendChild(smBuildItemCard(item, smTypeClass(item.inventory_type), false, group, { historicalQty }));
          });
          section.appendChild(grid2);
          detailDiv.appendChild(section);
        });
      } else {
        detailDiv.innerHTML = '<div class="sm-findings-empty" style="padding:8px 0">No items recorded.</div>';
      }

      entry.querySelector('.sm-timeline-expand-btn').addEventListener('click', function () {
        const detail = document.getElementById(detailId);
        const isOpen = !detail.hidden;
        detail.hidden = isOpen;
        this.setAttribute('aria-expanded', String(!isOpen));
        this.textContent = isOpen ? 'Details ›' : 'Hide ‹';
      });

      tl.appendChild(entry);
    });

    return tl;
  }

  function smBuildActivityExecutionCard(exec) {
    const proc = allProcesses.find(p => p.id === exec.process_id);
    const procName = proc ? proc.name : (exec.process_name || 'Unknown Process');
    const operator = exec.completed_by || null;
    const date = exec.started_at || exec.created_at;
    const stepCount = (exec.execution_steps || []).length;
    const statusLabel = { completed: 'Done', in_progress: 'In progress', pending: 'Pending', failed: 'Failed' }[exec.status] || exec.status || '';

    const card = document.createElement('div');
    card.className = 'sm-browse-card sm-browse-card--activity';
    card.innerHTML = `
      <div class="sm-browse-card__header">
        <span class="sm-browse-card__type-label">${smEsc(statusLabel)}</span>
      </div>
      <div class="sm-browse-card__name">${smEsc(procName)}</div>
      ${date ? `<div class="sm-browse-card__meta">${smFmtDate(date)}</div>` : ''}
      ${operator ? `<div class="sm-browse-card__meta sm-browse-card__meta--muted">${smEsc(operator)}</div>` : ''}
      ${stepCount ? `<div class="sm-browse-card__meta sm-browse-card__meta--muted">${stepCount} step${stepCount !== 1 ? 's' : ''}</div>` : ''}
    `;

    card.addEventListener('click', () => {
      smRenderActivityLog([exec], { type: 'activity', label: procName });
      const input = document.getElementById('sm-search-input');
      if (input) { input.value = procName; filterQuery = procName; }
      smShowSearchClear();
      smSetControlsVisible(true);
    });

    return card;
  }

  function smBrowseEmpty(msg) {
    return `<div class="sm-browse-empty">${smEsc(msg)}</div>`;
  }

  /* ── Trace: call API then render ────────────────────────── */
  async function smTraceItem(itemId, itemName, itemBatch, isBackward) {
    tracedItemId = itemId;
    tracedItemName = itemName;
    tracedItemBatch = itemBatch || '';
    showWastage = false;
    smSetWastageChip(false);
    smShowAreaLoading();
    smSetControlsVisible(true);

    try {
      const endpoint = isBackward
        ? `/api/core/inventory/trace-backward/${itemId}`
        : `/api/core/inventory/trace/${itemId}`;
      const res = await fetch(endpoint, { headers: smCsrfHeader() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      smRenderTrace(data);
    } catch (err) {
      console.error('[sourcemap] trace failed', err);
      const area = document.getElementById('sm-trace-area');
      if (area) area.innerHTML = smEmptyState('Trace failed. Please try again.');
    }
  }

  function smClearTrace() {
    tracedItemId = null;
    tracedItemName = '';
    tracedItemBatch = '';
    lastTraceResult = null;
    showWastage = false;
    smSetWastageChip(false);
    const input = document.getElementById('sm-search-input');
    if (input) { input.value = ''; filterQuery = ''; }
    smHideSearchClear();
    smRenderBrowseGrid();
    smClearTable();
  }

  /* ── Show/hide controls bar ─────────────────────────────── */
  function smSetControlsVisible(visible) {
    const bar = document.getElementById('sm-controls');
    if (bar) bar.style.display = visible ? '' : 'none';
  }

  /* ── Render: dispatch by view ────────────────────────────── */
  function smRenderTrace(traceResult) {
    lastTraceResult = traceResult;
    const area = document.getElementById('sm-trace-area');
    if (!area) return;
    area.innerHTML = '';

    const allItems = traceResult.all_items || [];
    const connections = traceResult.connections || [];
    // raw_material = forward trace root; traced_item = backward trace root
    const tracedItem = traceResult.raw_material || traceResult.traced_item || allItems[0];

    if (!tracedItem) {
      area.innerHTML = smEmptyState('No items found for this trace.');
      return;
    }

    const groups = connections.length ? smBuildExecutionGroups(allItems, connections) : [];

    const rawCountMap = new Map();
    groups.forEach(g => g.raws.forEach(r => rawCountMap.set(r.id, (rawCountMap.get(r.id) || 0) + 1)));
    const sharedSourceIds = new Set([...rawCountMap.entries()].filter(([, c]) => c > 1).map(([id]) => id));

    area.appendChild(smBuildImpactHeader(tracedItem, groups));

    if (!connections.length) {
      const lone = document.createElement('div');
      lone.className = 'sm-lone-item';
      lone.appendChild(smBuildItemCard(tracedItem, smTypeClass(tracedItem.inventory_type), false, null));
      area.appendChild(lone);
      if (currentView === 'table') smUpdateTable(allItems, []);
      return;
    }

    if (currentView === 'timeline') {
      area.appendChild(smRenderTimeline(groups, sharedSourceIds));
    } else if (currentView === 'map') {
      area.appendChild(smRenderMap(groups, tracedItem, sharedSourceIds));
    }

    if (currentView === 'table') smUpdateTable(allItems, connections);
  }

  /* ── Impact header ─────────────────────────────────────── */
  function smBuildImpactHeader(tracedItem, groups) {
    const div = document.createElement('div');
    div.className = 'sm-impact-header';

    const typeClass = smTypeClass(tracedItem.inventory_type);
    const batchText = tracedItem.supplier_batch_number ? `Batch ${tracedItem.supplier_batch_number}` : '';

    const uniqueProcesses = new Set(groups.map(g => g.processId).filter(Boolean)).size || groups.length;
    const execCount = groups.length;
    const findingCount = smCountFindingsForTrace(groups);

    const stats = [];
    if (uniqueProcesses) stats.push({ label: `${uniqueProcesses} process${uniqueProcesses !== 1 ? 'es' : ''}`, warn: false });
    if (execCount) stats.push({ label: `${execCount} execution${execCount !== 1 ? 's' : ''}`, warn: false });
    if (findingCount) stats.push({ label: `${findingCount} finding${findingCount !== 1 ? 's' : ''}`, warn: true });

    const statsHtml = stats.map(s =>
      `<span class="sm-impact-stat${s.warn ? ' sm-impact-stat--warn' : ''}">${smEsc(s.label)}</span>`
    ).join('');

    div.innerHTML = `
      <div class="sm-impact-header__left">
        <div class="sm-impact-header__name">
          <span class="sm-type-badge sm-type-badge--${typeClass}">${smEsc(smTypeLabelShort(tracedItem.inventory_type))}</span>
          <span class="sm-impact-header__item-name">${smEsc(tracedItem.name || 'Unknown item')}</span>
          ${batchText ? `<span class="sm-impact-header__batch">${smEsc(batchText)}</span>` : ''}
        </div>
        ${statsHtml ? `<div class="sm-impact-header__stats">${statsHtml}</div>` : ''}
      </div>
      <button class="sm-trace-clear" onclick="window.smClearTrace()">← Back to browse</button>
    `;
    return div;
  }

  function smCountFindingsForTrace(groups) {
    const ids = new Set();
    groups.forEach(g => [...g.raws, ...g.wips, ...g.finals].forEach(it => ids.add(it.id)));
    return [...ids].filter(id => smIsCheckNeeded(id)).length;
  }

  /* ── Timeline view ──────────────────────────────────────── */
  function smRenderTimeline(groups, sharedSourceIds) {
    const container = document.createElement('div');
    container.className = 'sm-timeline';

    if (!groups.length) {
      container.innerHTML = '<div class="sm-timeline-empty">No execution history found for this item.</div>';
      return container;
    }

    groups.forEach((group, idx) => {
      const isLast = idx === groups.length - 1;
      const entry = document.createElement('div');
      entry.className = 'sm-timeline-entry' + (isLast ? ' sm-timeline-entry--last' : '');

      const detailId = `sm-tl-detail-${idx}`;

      // Step rows: step name + completion date + "traced here" indicator (no inline IN/OUT tag lists)
      const stepsHtml = group.steps.map(step => {
        // "traced here" = the step where the traced item was consumed (froms) or produced (tos)
        const isTracedHere = tracedItemId && (
          step.froms.some(i => i.id === tracedItemId) || step.tos.some(i => i.id === tracedItemId)
        );
        const stepDate = step.tos.length && step.tos[0].step_data && step.tos[0].step_data.completed_at
          ? step.tos[0].step_data.completed_at
          : null;
        return `
          <div class="sm-timeline-step-row">
            <span class="sm-timeline-label">Step</span>
            ${step.stepName ? `<span class="sm-timeline-step-name">${smEsc(step.stepName)}</span>` : ''}
            ${stepDate ? `<span class="sm-timeline-step-date">${smFmtDate(stepDate)}</span>` : ''}
            ${isTracedHere ? '<span class="sm-tl-traced-here">traced here</span>' : ''}
          </div>`;
      }).join('');

      entry.innerHTML = `
        <div class="sm-timeline-dot-col" aria-hidden="true">
          <div class="sm-timeline-dot"></div>
          ${!isLast ? '<div class="sm-timeline-line"></div>' : ''}
        </div>
        <div class="sm-timeline-content">
          <div class="sm-timeline-meta">
            <span class="sm-timeline-label">Process</span>
            <span class="sm-timeline-process">${smEsc(group.processName)}</span>
          </div>
          ${stepsHtml ? `<div class="sm-timeline-steps-list">${stepsHtml}</div>` : ''}
          ${group.operator ? `<div class="sm-timeline-operator">
            <span class="sm-timeline-label">Completed by</span>
            <span>${smEsc(group.operator)}</span>
          </div>` : ''}
          <button class="sm-timeline-expand-btn" aria-expanded="false" aria-controls="${detailId}">Details ›</button>
          <div class="sm-timeline-detail" id="${detailId}" hidden></div>
        </div>
      `;

      // Build detail organised by step (preserves click handlers via real DOM nodes)
      const detailDiv = entry.querySelector(`#${detailId}`);
      const hasStepData = group.steps.some(s => s.froms.length || s.tos.length);

      if (hasStepData) {
        group.steps.forEach(step => {
          if (!step.froms.length && !step.tos.length) return;

          const section = document.createElement('div');
          section.className = 'sm-tl-step-section';

          if (step.stepName) {
            const hdr = document.createElement('div');
            hdr.className = 'sm-tl-step-header';
            hdr.textContent = step.stepName;
            section.appendChild(hdr);
          }

          // step_data for the consuming step lives on the produced (tos) items
          const consumingStepData = step.tos.length ? step.tos[0].step_data : null;

          const addSubSection = (items, labelText, tagClass, getHistoricalQty) => {
            if (!items.length) return;
            const lbl = document.createElement('div');
            lbl.className = `sm-tl-io-label ${tagClass}`;
            lbl.textContent = labelText;
            section.appendChild(lbl);
            const grid = document.createElement('div');
            grid.className = 'sm-tl-detail-grid';
            items.forEach(item => {
              const historicalQty = getHistoricalQty ? getHistoricalQty(item) : null;
              grid.appendChild(smBuildItemCard(item, smTypeClass(item.inventory_type), sharedSourceIds.has(item.id), group, { historicalQty }));
            });
            section.appendChild(grid);
          };

          // Consumed: look up qty in the consuming step's actual_inputs by inventory_item_id
          addSubSection(step.froms, 'Consumed', 'sm-tl-io-label--in', item => {
            if (!consumingStepData || !consumingStepData.actual_inputs) return null;
            const inp = consumingStepData.actual_inputs.find(i => i.inventory_item_id === item.id);
            return inp ? `${smFmtQty(inp.quantity)}${inp.unit ? ' ' + inp.unit : ''}`.trim() : null;
          });

          // Produced: look up qty in the item's own step_data actual_outputs by name
          addSubSection(step.tos, 'Produced', 'sm-tl-io-label--out', item => {
            if (!item.step_data || !item.step_data.actual_outputs) return null;
            const out = item.step_data.actual_outputs.find(o => o.name === item.name);
            return out ? `${smFmtQty(out.quantity)}${out.unit ? ' ' + out.unit : ''}`.trim() : null;
          });

          detailDiv.appendChild(section);
        });
      } else {
        // Fallback: flat list when no step data available
        const grid = document.createElement('div');
        grid.className = 'sm-tl-detail-grid';
        [...group.raws, ...group.wips, ...group.finals].forEach(item => {
          grid.appendChild(smBuildItemCard(item, smTypeClass(item.inventory_type), sharedSourceIds.has(item.id), group));
        });
        detailDiv.appendChild(grid);
      }

      entry.querySelector('.sm-timeline-expand-btn').addEventListener('click', function () {
        const detail = document.getElementById(detailId);
        const isOpen = !detail.hidden;
        detail.hidden = isOpen;
        this.setAttribute('aria-expanded', String(!isOpen));
        this.textContent = isOpen ? 'Details ›' : 'Hide ‹';
      });

      container.appendChild(entry);
    });

    return container;
  }

  /* ── Map view (vertical CSS tree) ──────────────────────── */
  function smRenderMap(groups, tracedItem, sharedSourceIds) {
    const container = document.createElement('div');
    container.className = 'sm-tree-container';

    const rootType = smTypeClass(tracedItem.inventory_type);
    const rootDiv = document.createElement('div');
    rootDiv.className = 'sm-tree-root';
    rootDiv.innerHTML = `
      <div class="sm-tree-node sm-tree-node--${rootType}${smIsCheckNeeded(tracedItem.id) ? ' sm-tree-node--check' : ''}">
        <span class="sm-type-badge sm-type-badge--${rootType}">${smTypeLabelShort(tracedItem.inventory_type)}</span>
        <span class="sm-tree-node__name">${smEsc(tracedItem.name || 'Unknown')}</span>
        ${tracedItem.supplier_batch_number ? `<span class="sm-tree-node__meta">Batch: ${smEsc(tracedItem.supplier_batch_number)}</span>` : ''}
        ${tracedItem.quantity != null ? `<span class="sm-tree-node__meta">${smFmtQty(tracedItem.quantity)}${tracedItem.unit ? ' ' + smEsc(tracedItem.unit) : ''}</span>` : ''}
      </div>
    `;
    container.appendChild(rootDiv);

    if (!groups.length) return container;

    const childrenUl = document.createElement('ul');
    childrenUl.className = 'sm-tree-children';

    groups.forEach(group => {
      const groupLi = document.createElement('li');
      groupLi.className = 'sm-tree-item';

      const groupLabel = document.createElement('div');
      groupLabel.className = 'sm-tree-group-label';
      groupLabel.innerHTML = `
        <div class="sm-tree-group__row">
          <span class="sm-tree-group__label-tag">Process</span>
          <span class="sm-tree-group__process">${smEsc(group.processName)}</span>
        </div>
        ${group.operator ? `<div class="sm-tree-group__row">
          <span class="sm-tree-group__label-tag">By</span>
          <span class="sm-tree-group__operator">${smEsc(group.operator)}</span>
        </div>` : ''}
      `;
      groupLi.appendChild(groupLabel);

      // Render steps individually; fall back to flat WIP/Final list if no step data
      const namedSteps = group.steps.filter(s => s.froms.length || s.tos.length);

      if (namedSteps.length) {
        const stepsUl = document.createElement('ul');
        stepsUl.className = 'sm-tree-children';

        namedSteps.forEach(step => {
          const stepLi = document.createElement('li');
          stepLi.className = 'sm-tree-item';

          const isTracedHere = tracedItemId && (
            step.froms.some(i => i.id === tracedItemId) || step.tos.some(i => i.id === tracedItemId)
          );
          const stepDate = step.tos.length && step.tos[0].step_data && step.tos[0].step_data.completed_at
            ? step.tos[0].step_data.completed_at
            : null;
          const stepLabel = document.createElement('div');
          stepLabel.className = 'sm-tree-step-label';
          stepLabel.innerHTML = `
            <span class="sm-tree-group__label-tag">Step</span>
            ${step.stepName ? `<span class="sm-tree-step-name">${smEsc(step.stepName)}</span>` : ''}
            ${stepDate ? `<span class="sm-timeline-step-date">${smFmtDate(stepDate)}</span>` : ''}
            ${isTracedHere ? '<span class="sm-tl-traced-here">traced here</span>' : ''}
          `;
          stepLi.appendChild(stepLabel);

          // Render froms (consumed) and tos (produced) as separate tree nodes with IO tags
          const fromItems = step.froms.filter(i => i.id !== tracedItem.id);
          const toItems   = step.tos.filter(i => i.id !== tracedItem.id);

          if (fromItems.length || toItems.length) {
            const producedUl = document.createElement('ul');
            producedUl.className = 'sm-tree-children';
            fromItems.forEach(item => {
              const itemLi = document.createElement('li');
              itemLi.className = 'sm-tree-item';
              itemLi.appendChild(smBuildTreeNode(item, smTypeClass(item.inventory_type), sharedSourceIds.has(item.id), 'in'));
              producedUl.appendChild(itemLi);
            });
            toItems.forEach(item => {
              const itemLi = document.createElement('li');
              itemLi.className = 'sm-tree-item';
              itemLi.appendChild(smBuildTreeNode(item, smTypeClass(item.inventory_type), sharedSourceIds.has(item.id), 'out'));
              producedUl.appendChild(itemLi);
            });
            stepLi.appendChild(producedUl);
          }

          stepsUl.appendChild(stepLi);
        });

        groupLi.appendChild(stepsUl);
      } else {
        // Fallback: flat WIP → Final structure
        if (group.wips.length) {
          const wipUl = document.createElement('ul');
          wipUl.className = 'sm-tree-children';
          group.wips.forEach(wip => {
            const wipLi = document.createElement('li');
            wipLi.className = 'sm-tree-item';
            wipLi.appendChild(smBuildTreeNode(wip, 'wip', sharedSourceIds.has(wip.id)));
            if (group.finals.length) {
              const finalUl = document.createElement('ul');
              finalUl.className = 'sm-tree-children';
              group.finals.forEach(fin => {
                const finLi = document.createElement('li');
                finLi.className = 'sm-tree-item';
                finLi.appendChild(smBuildTreeNode(fin, 'final', false));
                finalUl.appendChild(finLi);
              });
              wipLi.appendChild(finalUl);
            }
            wipUl.appendChild(wipLi);
          });
          groupLi.appendChild(wipUl);
        } else if (group.finals.length) {
          const finalUl = document.createElement('ul');
          finalUl.className = 'sm-tree-children';
          group.finals.forEach(fin => {
            const finLi = document.createElement('li');
            finLi.className = 'sm-tree-item';
            finLi.appendChild(smBuildTreeNode(fin, 'final', false));
            finalUl.appendChild(finLi);
          });
          groupLi.appendChild(finalUl);
        }
      }

      const otherRaws = group.raws.filter(r => r.id !== tracedItem.id);
      if (otherRaws.length) {
        const othersDiv = document.createElement('div');
        othersDiv.className = 'sm-tree-other-inputs';
        othersDiv.textContent = `+ combined with: ${otherRaws.map(r => r.name).join(', ')}`;
        groupLi.appendChild(othersDiv);
      }

      childrenUl.appendChild(groupLi);
    });

    container.appendChild(childrenUl);
    return container;
  }

  function smBuildTreeNode(item, type, isShared, ioTag) {
    const div = document.createElement('div');
    div.className = `sm-tree-node sm-tree-node--${type}${smIsCheckNeeded(item.id) ? ' sm-tree-node--check' : ''}`;
    div.innerHTML = `
      ${ioTag ? `<span class="sm-tl-io-tag sm-tl-io-tag--${ioTag}">${ioTag === 'in' ? 'In' : 'Out'}</span>` : ''}
      <span class="sm-type-badge sm-type-badge--${type}">${smTypeLabelShort(item.inventory_type)}</span>
      <span class="sm-tree-node__name">${smEsc(item.name || 'Unknown')}</span>
      ${item.quantity != null ? `<span class="sm-tree-node__meta">${smFmtQty(item.quantity)}${item.unit ? ' ' + smEsc(item.unit) : ''}</span>` : ''}
      ${isShared ? '<span class="sm-shared-pill">shared</span>' : ''}
      ${smIsCheckNeeded(item.id) ? '<span class="sm-check-pill">⚠ check</span>' : ''}
    `;
    return div;
  }

  /* ── Build execution groups ─────────────────────────────── */
  function smBuildExecutionGroups(allItems, connections) {
    const itemMap = new Map(allItems.map(it => [it.id, it]));
    // Preserve all_items order so we can sort steps chronologically
    const itemOrder = new Map(allItems.map((it, i) => [it.id, i]));

    const execMap = new Map();
    connections.forEach(conn => {
      const eid = conn.execution_id;
      if (!execMap.has(eid)) execMap.set(eid, { connections: [], itemIds: new Set() });
      const g = execMap.get(eid);
      g.connections.push(conn);
      if (conn.from_id) g.itemIds.add(conn.from_id);
      if (conn.to_id) g.itemIds.add(conn.to_id);
    });

    const groups = [];
    execMap.forEach((g, eid) => {
      const exec = allExecutions.find(e => e.id === eid) || null;
      const process = exec ? allProcesses.find(p => p.id === exec.process_id) : null;
      const items = [...g.itemIds].map(id => itemMap.get(id)).filter(Boolean);

      // Steps are derived from items: each non-raw item carries source_execution_id + source_step_name
      // Group produced items by the step that created them within this execution
      const stepMap = new Map();
      items.forEach(item => {
        if (item.source_execution_id !== eid) return;
        const key = item.source_step_name || '';
        if (!stepMap.has(key)) stepMap.set(key, { stepName: item.source_step_name || '', toIds: new Set(), fromIds: new Set() });
        stepMap.get(key).toIds.add(item.id);
      });

      // Sort steps by earliest produced item position in all_items (creation order)
      const steps = [...stepMap.values()]
        .map(s => ({
          stepName: s.stepName,
          tos:   [...s.toIds].map(id => itemMap.get(id)).filter(Boolean),
          froms: [], // derived below from step order — avoids synthetic connection noise
        }))
        .sort((a, b) => {
          const aMin = Math.min(...a.tos.map(i => itemOrder.get(i.id) ?? Infinity));
          const bMin = Math.min(...b.tos.map(i => itemOrder.get(i.id) ?? Infinity));
          return aMin - bMin;
        });

      // Derive froms from step order: step[0] consumes external inputs; step[N] consumes step[N-1]'s outputs.
      // This removes synthetic raw→item edges that would otherwise appear as spurious inputs to every step.
      const producedInExec = new Set(steps.flatMap(s => s.tos.map(i => i.id)));
      steps.forEach((step, i) => {
        step.froms = i === 0
          ? items.filter(it => !producedInExec.has(it.id))   // items not produced by any step here
          : [...steps[i - 1].tos];                            // previous step's outputs
      });

      groups.push({
        executionId: eid,
        exec,
        processId: exec ? exec.process_id : null,
        processName: process ? process.name : (exec ? (exec.process_name || 'Unknown Process') : 'Unknown Process'),
        executionDate: exec ? (exec.created_at || exec.started_at || null) : null,
        operator: exec ? (exec.completed_by || exec.created_by || null) : null,
        raws:   items.filter(it => it.inventory_type === 'raw_material'),
        wips:   items.filter(it => it.inventory_type === 'work_in_progress'),
        finals: items.filter(it => it.inventory_type === 'final_product'),
        connections: g.connections,
        steps,
      });
    });

    groups.sort((a, b) => {
      if (!a.executionDate) return 1;
      if (!b.executionDate) return -1;
      return new Date(a.executionDate) - new Date(b.executionDate);
    });

    return groups;
  }

  /* ── Item card (used in timeline detail) ────────────────── */
  function smBuildItemCard(item, type, isShared, execGroup, options) {
    const { historicalQty = null } = options || {};
    const card = document.createElement('div');
    card.className = `sm-item-card sm-item-card--${type}${smIsCheckNeeded(item.id) ? ' sm-item-card--check' : ''}`;
    card.dataset.itemId = item.id;

    const currentQty = item.quantity != null ? `${smFmtQty(item.quantity)}${item.unit ? ' ' + item.unit : ''}` : null;
    const displayQty = historicalQty !== null ? historicalQty : currentQty;
    const qty = displayQty;
    const batch = item.supplier_batch_number ? `Batch ${item.supplier_batch_number}` : null;
    const summary = [batch, displayQty].filter(Boolean).join(' · ');

    const pills = [];
    if (isShared) pills.push('<span class="sm-shared-pill">shared source</span>');
    if (smIsCheckNeeded(item.id)) pills.push('<span class="sm-check-pill">⚠ check needed</span>');

    const checkReason = smGetCheckReason(item.id);
    const today = new Date();
    const expiry = item.expiry_date ? new Date(item.expiry_date) : null;
    const isExpired = expiry && expiry < today;

    // Rich detail rows — all human language labels
    const rows = [];
    if (item.inventory_type) rows.push(['Type', smTypeLabel(item.inventory_type), false]);
    if (item.supplier) rows.push(['Supplier', item.supplier, false]);
    if (item.supplier_batch_number) rows.push(['Batch number', item.supplier_batch_number, false]);
    if (historicalQty !== null) {
      rows.push(['Recorded qty', historicalQty, false]);
      if (currentQty && currentQty !== historicalQty) rows.push(['Current stock', currentQty, false]);
    } else if (currentQty) {
      rows.push(['Quantity', currentQty, false]);
    }
    if (item.purchase_date) rows.push(['Purchase date', smFmtDate(item.purchase_date), false]);
    if (item.expiry_date) rows.push(['Expiry date', smFmtDate(item.expiry_date), isExpired]);
    if (item.ready_date) rows.push(['Ready date', smFmtDate(item.ready_date), false]);
    if (item.notes) rows.push(['Notes', item.notes, false]);
    if (item.process_name) rows.push(['Produced in', item.process_name, false]);
    if (item.created_at) rows.push(['Date added', smFmtDate(item.created_at), false]);

    // Execution-level context if available
    if (execGroup) {
      if (execGroup.operator) rows.push(['Completed by', execGroup.operator, false]);
      if (execGroup.executionDate) rows.push(['Execution date', smFmtDate(execGroup.executionDate), false]);
    }

    // Check reason
    if (checkReason) rows.push(['Check reason', checkReason, true]);

    const detailGridHtml = rows.map(([label, value, isWarn]) =>
      `<dt class="sm-detail-label">${smEsc(label)}</dt>
       <dd class="sm-detail-value${isWarn ? ' sm-detail-value--warn' : ''}">${smEsc(String(value || '—'))}</dd>`
    ).join('');

    card.innerHTML = `
      <div class="sm-item-card__header">
        <span class="sm-item-card__name">${smEsc(item.name || item.expired_raw_material_name || 'Unnamed')}</span>
        <span class="sm-type-badge sm-type-badge--${type}">${smTypeLabelShort(item.inventory_type)}</span>
      </div>
      ${summary ? `<div class="sm-item-card__summary">${smEsc(summary)}</div>` : ''}
      ${pills.length ? `<div class="sm-item-card__pills">${pills.join('')}</div>` : ''}
      <button class="sm-item-card__toggle" tabindex="-1" aria-hidden="true">
        <i class="sm-item-card__toggle-icon">›</i> Details
      </button>
      <div class="sm-item-card__detail">
        <dl class="sm-detail-grid">${detailGridHtml}</dl>
      </div>
    `;

    card.addEventListener('click', () => card.classList.toggle('sm-item-card--expanded'));
    return card;
  }

  /* ── Wastage view ───────────────────────────────────────── */
  async function smShowWastageView() {
    const inline = document.getElementById('sm-wastage-inline');
    if (inline) inline.innerHTML = '<div class="sm-loading">Loading…</div>';
    try {
      const data = await CoreAPI.getWastageRecords();
      smRenderWastage(data.wastage_records || data.wastage || []);
    } catch (err) {
      console.error('[sourcemap] wastage load failed', err);
    }
  }

  function smRenderWastage(records) {
    const area = document.getElementById('sm-wastage-inline');
    if (!area) return;
    area.innerHTML = '';

    if (!records.length) {
      area.innerHTML = smEmptyState('No wastage records found.');
      return;
    }

    // Group by calendar day (records arrive newest-first from API)
    const byDay = [];
    const dayMap = {};
    records.forEach(r => {
      const day = r.recorded_at ? smFmtDate(r.recorded_at) : 'Unknown date';
      if (!dayMap[day]) { dayMap[day] = []; byDay.push({ day, entries: dayMap[day] }); }
      dayMap[day].push(r);
    });

    const wrap = document.createElement('div');
    wrap.className = 'sm-wastage-log';

    const hdr = document.createElement('div');
    hdr.className = 'sm-wastage-log__header';
    hdr.textContent = `Wastage log — ${records.length} record${records.length !== 1 ? 's' : ''}`;
    wrap.appendChild(hdr);

    byDay.forEach(({ day, entries }) => {
      const dayEl = document.createElement('div');
      dayEl.className = 'sm-wastage-day';
      dayEl.innerHTML = `<div class="sm-wastage-day__label">${smEsc(day)}</div>`;

      entries.forEach(r => {
        const itemName = r.item_name || r.inventory_item_name || r.name || 'Unknown item';
        const qty = r.quantity_wasted != null ? `${smFmtQty(r.quantity_wasted)} ${r.unit || ''}`.trim() : '—';
        const who = r.recorded_by || 'Unknown operator';
        const time = smFmtTime(r.recorded_at);

        const entry = document.createElement('div');
        entry.className = 'sm-wastage-entry';
        const reasonText = r.reason || null;
        entry.innerHTML = `
          <div class="sm-wastage-entry__main">
            <span class="sm-wastage-entry__name">${smEsc(itemName)}</span>
            <span class="sm-wastage-entry__qty">−${smEsc(qty)}</span>
          </div>
          ${reasonText ? `<div class="sm-wastage-entry__reason">${smEsc(reasonText)}</div>` : ''}
          <div class="sm-wastage-entry__meta">
            <span class="sm-wastage-entry__who">
              <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
              ${smEsc(who)}
            </span>
            <span class="sm-wastage-entry__time">${smEsc(time)}</span>
            ${r.inventory_item_id ? `<button class="sm-wastage-entry__trace" data-id="${smEsc(r.inventory_item_id)}" title="Trace this item">Trace ↗</button>` : ''}
          </div>
        `;

        if (r.inventory_item_id) {
          entry.querySelector('.sm-wastage-entry__trace').addEventListener('click', e => {
            e.stopPropagation();
            smTraceItem(r.inventory_item_id, itemName);
          });
        }

        dayEl.appendChild(entry);
      });

      wrap.appendChild(dayEl);
    });

    area.appendChild(wrap);
  }

  /* ── System findings ────────────────────────────────────── */
  async function smLoadFindings() {
    try {
      const [expiredRes, untrackedRes, expiryRes, readyRes] = await Promise.all([
        CoreAPI.getExpiredMaterials().catch(() => ({})),
        CoreAPI.getUntrackedItems().catch(() => ({})),
        fetch('/api/core/inventory/output-expiry', { headers: smCsrfHeader() }).then(r => r.json()).catch(() => ({})),
        CoreAPI.getOutputReadyDate().catch(() => ({})),
      ]);

      findingsData.expired = [...(expiredRes.expired_raw_materials || []), ...(expiredRes.impacted_items || [])];
      findingsData.untracked = untrackedRes.untracked_items || [];
      findingsData.expiry = expiryRes.output_expiry_items || [];
      findingsData.ready = readyRes.output_ready_date_items || readyRes.ready_date_items || [];
    } catch (err) {
      console.error('[sourcemap] findings load failed', err);
    }

    smUpdateFindingsBadges();
    smRenderFindings();
  }

  function smUpdateFindingsBadges() {
    const counts = {
      all: findingsData.expired.length + findingsData.untracked.length + findingsData.expiry.length + findingsData.ready.length,
      expired: findingsData.expired.length,
      untracked: findingsData.untracked.length,
      expiry: findingsData.expiry.length,
      ready: findingsData.ready.length,
    };

    Object.entries(counts).forEach(([key, count]) => {
      const badge = document.getElementById(`sm-findings-badge-${key}`);
      if (!badge) return;
      badge.textContent = count;
      badge.classList.toggle('sm-findings-badge--alert', count > 0);
    });
  }

  function smSwitchFindingsTab(tab) {
    currentFindingsTab = tab;
    document.querySelectorAll('.sm-findings-tab').forEach(btn => {
      btn.classList.toggle('sm-findings-tab--active', btn.dataset.tab === tab);
      btn.setAttribute('aria-selected', btn.dataset.tab === tab ? 'true' : 'false');
    });
    smRenderFindings();
  }

  function smRenderFindings() {
    const list = document.getElementById('sm-findings-list');
    if (!list) return;

    let items = currentFindingsTab === 'all'
      ? [
          ...findingsData.expired.map(it => ({ ...it, _category: 'expired' })),
          ...findingsData.untracked.map(it => ({ ...it, _category: 'untracked' })),
          ...findingsData.expiry.map(it => ({ ...it, _category: 'expiry' })),
          ...findingsData.ready.map(it => ({ ...it, _category: 'ready' })),
        ]
      : (findingsData[currentFindingsTab] || []).map(it => ({ ...it, _category: currentFindingsTab }));

    if (!items.length) {
      list.innerHTML = '<div class="sm-findings-empty">No findings in this category.</div>';
      return;
    }

    list.innerHTML = '';
    items.forEach(item => {
      const name = item.name || item.expired_raw_material_name || item.inventory_item_name || 'Unknown item';
      const itemId = item.id || item.inventory_item_id;
      const reason = smFindingReason(item);

      const card = document.createElement('div');
      card.className = 'sm-finding-card';
      card.innerHTML = `
        <div class="sm-finding-card__body">
          <div class="sm-finding-card__name">${smEsc(name)}</div>
          ${reason ? `<div class="sm-finding-card__reason">${smEsc(reason)}</div>` : ''}
        </div>
        <button class="sm-finding-trace-btn" aria-label="Trace ${smEsc(name)}">Trace ↗</button>
      `;

      card.querySelector('.sm-finding-trace-btn').addEventListener('click', () => {
        if (!itemId) return;
        const entry = allInventory.find(i => i.id === itemId) || allOutOfStockRawMaterials.find(i => i.id === itemId);
        smTraceItem(itemId, name, entry ? entry.supplier_batch_number : '', false);
        const input = document.getElementById('sm-search-input');
        if (input) input.value = name;
        smShowSearchClear();
      });

      list.appendChild(card);
    });
  }

  function smFindingReason(item) {
    if (item._category === 'expired') {
      if (item.expired_raw_material_name) return `Made with expired: ${item.expired_raw_material_name}`;
      if (item.expiry_date) return `Expired ${smFmtDate(item.expiry_date)}`;
      return 'Expired raw material';
    }
    if (item._category === 'untracked') return item.check_reason || 'Untracked — reconciliation required';
    if (item._category === 'expiry') return item.message || 'Custom output expiry reached';
    if (item._category === 'ready') return item.message || 'Output not yet ready';
    return item.reason || '';
  }

  /* ── Table view ─────────────────────────────────────────── */
  function smUpdateTable(items, connections) {
    const wrap = document.getElementById('sm-table-wrap');
    if (!wrap) return;

    if (!items || !items.length) {
      wrap.style.display = 'none';
      return;
    }

    wrap.style.display = 'block';

    const tbody = document.getElementById('sm-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    items.forEach(item => {
      const tr = document.createElement('tr');
      const typeClass = smTypeClass(item.inventory_type);
      const qty = item.quantity != null ? `${smFmtQty(item.quantity)} ${item.unit || ''}`.trim() : '—';
      tr.innerHTML = `
        <td>${smEsc(item.name || '—')}</td>
        <td><span class="sm-type-badge sm-type-badge--${typeClass}">${smTypeLabel(item.inventory_type)}</span></td>
        <td>${qty}</td>
        <td>${smEsc(item.supplier_batch_number || '—')}</td>
        <td>${smEsc(item.supplier || '—')}</td>
        <td>${smFmtDate(item.expiry_date)}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  function smClearTable() {
    const tbody = document.getElementById('sm-table-body');
    if (tbody) tbody.innerHTML = '';
    const wrap = document.getElementById('sm-table-wrap');
    const empty = document.getElementById('sm-table-empty');
    if (wrap) wrap.style.display = 'none';
    if (empty) empty.style.display = 'block';
  }

  /* ── Search (filters browse grid, no dropdown) ──────────── */
  function smUpdateSearchPool() {
    const inStock = (allInventory || []).map(it => ({ ...it, _oos: false }));
    const oos = (allOutOfStockRawMaterials || []).map(it => ({ ...it, _oos: true }));
    allInventoryForSearch = [...inStock, ...oos];
  }

  function smInitSearch() {
    const input = document.getElementById('sm-search-input');
    const clearBtn = document.getElementById('sm-search-clear');
    if (!input) return;

    input.addEventListener('input', () => {
      filterQuery = input.value.trim();
      if (filterQuery) smShowSearchClear(); else smHideSearchClear();

      // Only filter browse grid; in trace mode the input is for reference only
      if (!tracedItemId && !showWastage) {
        clearTimeout(filterTimeout);
        filterTimeout = setTimeout(() => {
          const grid = document.querySelector('.sm-browse-grid');
          if (grid) smRefreshBrowseCards(grid);
        }, 180);
      }
    });

    input.addEventListener('keydown', e => {
      if (e.key === 'Escape') { input.value = ''; filterQuery = ''; smHideSearchClear(); }
    });

    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        input.value = '';
        filterQuery = '';
        smHideSearchClear();
        if (tracedItemId || showWastage) {
          smClearTrace();
        } else {
          const grid = document.querySelector('.sm-browse-grid');
          if (grid) smRefreshBrowseCards(grid);
        }
      });
    }
  }

  function smShowSearchClear() {
    const btn = document.getElementById('sm-search-clear');
    if (btn) btn.style.display = 'block';
  }

  function smHideSearchClear() {
    const btn = document.getElementById('sm-search-clear');
    if (btn) btn.style.display = 'none';
  }

  /* ── Batch entry modal ──────────────────────────────────── */
  function smShowBatchModal(name, entries) {
    const overlay = document.getElementById('sm-modal-overlay');
    const title = document.getElementById('sm-modal-title');
    const body = document.getElementById('sm-modal-body');
    if (!overlay || !title || !body) return;

    title.textContent = name;
    body.innerHTML = '';

    const inStock = entries.filter(e => !e._oos);
    const oos = entries.filter(e => e._oos);

    function renderGroup(label, items) {
      if (!items.length) return;
      const groupLabel = document.createElement('p');
      groupLabel.className = 'sm-modal-group-label';
      groupLabel.textContent = label;
      body.appendChild(groupLabel);

      items.forEach(entry => {
        const parts = [];
        if (entry.supplier_batch_number) parts.push(`Batch: ${entry.supplier_batch_number}`);
        if (entry.quantity != null) parts.push(`${smFmtQty(entry.quantity)} ${entry.unit || ''}`.trim());
        if (entry.supplier) parts.push(entry.supplier);
        if (entry.expiry_date) parts.push(`Expires: ${smFmtDate(entry.expiry_date)}`);

        const card = document.createElement('div');
        card.className = 'sm-batch-entry';
        card.innerHTML = `
          <div>
            <div class="sm-batch-entry__name">${smEsc(entry.name || name)}</div>
            <div class="sm-batch-entry__meta">${smEsc(parts.join(' · '))}</div>
          </div>
          <button class="sm-batch-trace-btn">Trace →</button>
        `;
        card.querySelector('.sm-batch-trace-btn').addEventListener('click', () => {
          smCloseBatchModal();
          const direction = entry.inventory_type === 'raw_material' ? false : true;
          smTraceItem(entry.id, entry.name || name, entry.supplier_batch_number, direction);
          const searchInput = document.getElementById('sm-search-input');
          if (searchInput) searchInput.value = entry.name || name;
          smShowSearchClear();
        });
        body.appendChild(card);
      });
    }

    renderGroup('In stock', inStock);
    renderGroup('Archived / used batches', oos);
    if (!inStock.length && !oos.length) {
      body.innerHTML = '<p style="padding:12px;color:var(--text-secondary)">No entries found.</p>';
    }

    overlay.classList.add('sm-modal-overlay--open');
  }

  function smCloseBatchModal() {
    const overlay = document.getElementById('sm-modal-overlay');
    if (overlay) overlay.classList.remove('sm-modal-overlay--open');
  }

  function smBindModal() {
    const overlay = document.getElementById('sm-modal-overlay');
    const closeBtn = document.getElementById('sm-modal-close');
    if (overlay) overlay.addEventListener('click', e => { if (e.target === overlay) smCloseBatchModal(); });
    if (closeBtn) closeBtn.addEventListener('click', smCloseBatchModal);
  }

  /* ── Activity log (metadata traces: operator, date, etc.) ─── */
  function smTraceByPerson(person, execs) {
    tracedItemId = null;
    tracedItemName = '';
    tracedItemBatch = '';
    lastTraceResult = null;
    showWastage = false;
    smSetWastageChip(false);
    smSetControlsVisible(true);

    const input = document.getElementById('sm-search-input');
    if (input) input.value = person;
    smShowSearchClear();

    smRenderActivityLog(execs, { type: 'operator', label: person });
  }

  function smBuildActivityGroups(execs) {
    return execs
      .map(exec => {
        const process = allProcesses.find(p => p.id === exec.process_id);
        const execItems = allInventoryForSearch.filter(it => it.source_execution_id === exec.id);

        const stepMap = new Map();
        execItems.forEach(item => {
          const key = item.source_step_name || '';
          if (!stepMap.has(key)) stepMap.set(key, { stepName: key, tos: [], froms: [] });
          stepMap.get(key).tos.push(item);
        });

        return {
          executionId: exec.id,
          exec,
          processName: process ? process.name : (exec.process_name || 'Unknown Process'),
          executionDate: exec.created_at || exec.started_at || null,
          operator: exec.completed_by || exec.created_by || null,
          steps: [...stepMap.values()],
        };
      })
      .filter(g => g.steps.length > 0)
      .sort((a, b) => {
        if (!a.executionDate) return 1;
        if (!b.executionDate) return -1;
        return new Date(a.executionDate) - new Date(b.executionDate);
      });
  }

  function smRenderActivityLog(execs, context) {
    const area = document.getElementById('sm-trace-area');
    if (!area) return;
    area.innerHTML = '';

    const groups = smBuildActivityGroups(execs);
    const stepTotal = groups.reduce((t, g) => t + g.steps.length, 0);

    const header = document.createElement('div');
    header.className = 'sm-impact-header';
    header.innerHTML = `
      <div class="sm-impact-header__left">
        <div class="sm-impact-header__name">
          <span class="sm-type-badge sm-type-badge--wip">${smEsc(context.type === 'operator' ? 'Operator' : 'Activity')}</span>
          <span class="sm-impact-header__item-name">${smEsc(context.label)}</span>
        </div>
        <div class="sm-impact-header__stats">
          <span class="sm-impact-stat">${execs.length} execution${execs.length !== 1 ? 's' : ''}</span>
          ${stepTotal ? `<span class="sm-impact-stat">${stepTotal} step${stepTotal !== 1 ? 's' : ''}</span>` : ''}
        </div>
      </div>
      <button class="sm-trace-clear" onclick="window.smClearTrace()">← Back to browse</button>
    `;
    area.appendChild(header);

    if (!groups.length) {
      area.insertAdjacentHTML('beforeend', smEmptyState('No production activity found.'));
      return;
    }

    area.appendChild(smBuildInlineActivityTimeline(execs));
  }

  /* ── Controls binding ───────────────────────────────────── */
  function smBindControls() {
    // View toggle: timeline | map | table
    document.querySelectorAll('.sm-view-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const view = btn.dataset.view;
        currentView = view;

        document.querySelectorAll('.sm-view-btn').forEach(b => {
          b.classList.toggle('sm-view-btn--active', b.dataset.view === view);
          b.setAttribute('aria-selected', b.dataset.view === view ? 'true' : 'false');
        });

        const flowArea = document.getElementById('sm-trace-area');
        const tableWrap = document.getElementById('sm-table-wrap');

        if (view === 'table') {
          if (flowArea) flowArea.style.display = 'none';
          if (lastTraceResult && (lastTraceResult.all_items || []).length) {
            smUpdateTable(lastTraceResult.all_items || [], lastTraceResult.connections || []);
          } else {
            if (tableWrap) tableWrap.style.display = 'none';
          }
        } else {
          if (flowArea) flowArea.style.display = '';
          if (tableWrap) tableWrap.style.display = 'none';

          if (lastTraceResult) smRenderTrace(lastTraceResult);
          else smRenderBrowseGrid();
        }
      });
    });

    // Wastage toggle (persistent bar, independent of trace state)
    const wastageToggle = document.getElementById('sm-wastage-toggle');
    const wastageTrack = document.getElementById('sm-wastage-track');
    const wastageInline = document.getElementById('sm-wastage-inline');
    if (wastageToggle && wastageInline) {
      wastageToggle.addEventListener('click', () => {
        showWastage = !showWastage;
        wastageToggle.setAttribute('aria-expanded', String(showWastage));
        wastageToggle.setAttribute('aria-checked', String(showWastage));
        if (wastageTrack) wastageTrack.classList.toggle('spa-advanced-toggle__track--on', showWastage);
        wastageInline.style.display = showWastage ? '' : 'none';
        if (showWastage) smShowWastageView();
        else wastageInline.innerHTML = '';
      });
    }

    // Findings tabs
    document.querySelectorAll('.sm-findings-tab').forEach(tab => {
      tab.addEventListener('click', () => smSwitchFindingsTab(tab.dataset.tab));
    });

    // Findings collapse
    const findingsCollapse = document.getElementById('sm-findings-collapse');
    const findingsBody = document.getElementById('sm-findings-body');
    if (findingsCollapse && findingsBody) {
      findingsCollapse.addEventListener('click', () => {
        const isExpanded = findingsCollapse.getAttribute('aria-expanded') === 'true';
        findingsCollapse.setAttribute('aria-expanded', String(!isExpanded));
        findingsBody.hidden = isExpanded;
        const section = document.getElementById('sm-findings-section');
        if (section) section.classList.toggle('sm-findings--collapsed', isExpanded);
      });
    }
  }


  /* ── UI helpers ─────────────────────────────────────────── */
  function smShowAreaLoading() {
    const area = document.getElementById('sm-trace-area');
    if (area) area.innerHTML = '<div class="sm-loading">Loading…</div>';
  }

  function smEmptyState(msg) {
    return `
      <div class="sm-empty-state">
        <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/></svg>
        <p>${smEsc(msg)}</p>
      </div>
    `;
  }

  /* ── Check-needed helpers ───────────────────────────────── */
  function smIsCheckNeeded(itemId) {
    if (!checkNeededData) return false;
    return (checkNeededData.expired_raw_materials || []).some(r => r.id === itemId)
      || (checkNeededData.impacted_items || []).some(i => i.id === itemId)
      || (checkNeededData.untracked_items || []).some(i => i.id === itemId);
  }

  function smGetCheckReason(itemId) {
    if (!checkNeededData) return null;
    const expired = (checkNeededData.expired_raw_materials || []).find(r => r.id === itemId);
    if (expired) return (expired.name || 'Item') + ' expired';
    const impacted = (checkNeededData.impacted_items || []).find(i => i.id === itemId);
    if (impacted && impacted.expired_raw_material_name) return `Made with expired: ${impacted.expired_raw_material_name}`;
    const untracked = (checkNeededData.untracked_items || []).find(i => i.id === itemId);
    if (untracked) return untracked.check_reason || 'Untracked — reconciliation required';
    return null;
  }

  /* ── Pure utilities ─────────────────────────────────────── */
  function smEsc(str) {
    return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function smFmtDate(str) {
    if (!str) return '—';
    try { return new Date(str).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }); }
    catch { return String(str); }
  }

  function smFmtDateTime(str) {
    if (!str) return '—';
    try {
      const d = new Date(str);
      return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
        + ' at ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    } catch { return String(str); }
  }

  function smFmtTime(str) {
    if (!str) return '—';
    try { return new Date(str).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }); }
    catch { return String(str); }
  }

  function smFmtQty(val) {
    if (val == null) return '0';
    const n = parseFloat(val);
    return isNaN(n) ? String(val) : parseFloat(n.toFixed(4)).toString();
  }

  function smTypeClass(type) {
    if (type === 'raw_material') return 'raw';
    if (type === 'work_in_progress') return 'wip';
    if (type === 'final_product') return 'final';
    return 'raw';
  }

  function smTypeLabel(type) {
    if (type === 'raw_material') return 'Raw Material';
    if (type === 'work_in_progress') return 'Work in Progress';
    if (type === 'final_product') return 'Final Product';
    return type || '—';
  }

  function smTypeLabelShort(type) {
    if (type === 'raw_material') return 'Raw';
    if (type === 'work_in_progress') return 'WIP';
    if (type === 'final_product') return 'Final';
    return 'Item';
  }

  function smCsrfHeader() {
    const token = document.querySelector('meta[name="csrf-token"]');
    return token ? { 'X-CSRFToken': token.content } : {};
  }

  /* ── Public API ─────────────────────────────────────────── */
  window.smClearTrace = smClearTrace;
  window.smCloseBatchModal = smCloseBatchModal;

  /* ── Init ────────────────────────────────────────────────── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', smBoot);
  } else {
    smBoot();
  }
})();
