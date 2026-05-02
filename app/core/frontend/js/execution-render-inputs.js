/**
 * Variable inventory input rows + card picker for execute-step UI.
 * Load before execution-modal.js.
 */
(function (root) {
  "use strict";

  var ITU = root.InventoryTypeUtils;
  var IDisp = root.InventoryDisplay;
  if (!ITU || typeof ITU.normalizeInventoryTabType !== "function" || typeof ITU.normalizeExpectedInventoryTabHint !== "function" || typeof ITU.matchesInventoryTab !== "function" || typeof ITU.matchesSearch !== "function") {
    throw new Error("inventory-type-utils.js must load before execution-render-inputs.js");
  }
  if (!IDisp || typeof IDisp.formatTriggerLabel !== "function" || typeof IDisp.quantityUnitLine !== "function") {
    throw new Error("inventory-display.js must load before execution-render-inputs.js");
  }
  var ExecInvPickView = root.ExecutionInventoryPickerView;
  if (!ExecInvPickView || typeof ExecInvPickView.buildPayload !== "function" || typeof ExecInvPickView.assembleCard !== "function" || typeof ExecInvPickView.syncCard !== "function") {
    throw new Error("execution-inventory-picker-view.js must load before execution-render-inputs.js");
  }
  var EIRR = root.ExecutionInventoryRowRenderer;
  if (!EIRR || typeof EIRR.createInputRow !== "function") {
    throw new Error("execution-inventory-row-renderer.js must load before execution-render-inputs.js");
  }

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
        
        // Get current execution ID from modal context (used to prioritize inventory produced in this execution).
        const currentExecutionId = modal.dataset.executionId;

        function safeName(inv) {
          try { return String((inv && inv.name) || '').trim().toLowerCase(); } catch (e) { return ''; }
        }

        // Default list (no search): only inventory whose name exactly matches the expected input (trimmed, case-insensitive).
        const expectedInputNorm = String((input && input.name) || '').trim().toLowerCase();
        const matchingInventory = allInventory.filter(function(inv) {
          if (!expectedInputNorm) return false;
          return safeName(inv) === expectedInputNorm;
        });

        // Keep ordering stable, but float "same execution" items to the top.
        function sortWithExecutionBias(list) {
          return (list || []).slice().sort((a, b) => {
            const aExecutionId = a.source_execution_id || a.execution_id || null;
            const bExecutionId = b.source_execution_id || b.execution_id || null;

            if (currentExecutionId) {
              const aMatches = aExecutionId && String(aExecutionId) === String(currentExecutionId);
              const bMatches = bExecutionId && String(bExecutionId) === String(currentExecutionId);
              if (aMatches && !bMatches) return -1;
              if (!aMatches && bMatches) return 1;
            }
            return 0;
          });
        }

        const sortedInventory = sortWithExecutionBias(matchingInventory);
        const allInventorySorted = sortWithExecutionBias(allInventory);
        
        // Check if no matching inventory is available
        const hasNoInventory = sortedInventory.length === 0;
        const safeInputName = (input.name || '').replace(/[^a-zA-Z0-9_-]/g, '_');
        const inventoryById = new Map();
        allInventory.forEach(function(inv) { inventoryById.set(String(inv.id), inv); });

        var headerEl = document.createElement("div");
        headerEl.className = "execute-input-section-header";
        headerEl.style.marginBottom = "12px";
        var headerLabel = document.createElement("label");
        headerLabel.style.cssText = "display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;";
        headerLabel.appendChild(document.createTextNode(input.name || ""));
        headerLabel.appendChild(document.createTextNode(" "));
        var expSpan = document.createElement("span");
        expSpan.style.cssText = "color: var(--text-secondary); font-weight: normal;";
        expSpan.textContent =
          "(Expected: " +
          String(input.quantity != null ? input.quantity : "0") +
          " " +
          (input.unit || "") +
          ")";
        headerLabel.appendChild(expSpan);
        headerEl.appendChild(headerLabel);
        inputSection.appendChild(headerEl);

        const rowsContainer = document.createElement("div");
        rowsContainer.className = "execute-input-rows-container";
        rowsContainer.dataset.inputName = input.name || "";
        rowsContainer.dataset.safeName = safeInputName;
        inputSection.appendChild(rowsContainer);

        var pickerPanel = document.createElement("div");
        pickerPanel.className = "exec-picker-panel";
        pickerPanel.setAttribute("data-exec-picker-panel", "true");
        pickerPanel.style.display = "block";
        pickerPanel.style.marginTop = "10px";
        var seg = document.createElement("div");
        seg.className = "flow-mode-segmented";
        seg.setAttribute("role", "group");
        seg.setAttribute("aria-label", "Inventory category");
        seg.style.marginBottom = "10px";
        [["raw_material", "Raw materials", true], ["work_in_progress", "Intermediate", false], ["final_product", "Final products", false]].forEach(function(spec) {
          var b = document.createElement("button");
          b.type = "button";
          b.className = "flow-mode-segment" + (spec[2] ? " flow-mode-segment--active" : "");
          b.setAttribute("data-exec-type", spec[0]);
          b.setAttribute("aria-pressed", spec[2] ? "true" : "false");
          b.textContent = spec[1];
          seg.appendChild(b);
        });
        pickerPanel.appendChild(seg);
        var searchWrap = document.createElement("div");
        searchWrap.className = "exec-picker-search";
        var pickerSearch = document.createElement("input");
        pickerSearch.type = "search";
        pickerSearch.className = "spa-inp";
        pickerSearch.setAttribute("data-exec-picker-search", "true");
        pickerSearch.placeholder = "Search inventory…";
        pickerSearch.autocomplete = "off";
        searchWrap.appendChild(pickerSearch);
        pickerPanel.appendChild(searchWrap);
        var pickerCards = document.createElement("div");
        pickerCards.className = "exec-picker-cards";
        pickerCards.setAttribute("data-exec-picker-cards", "true");
        pickerPanel.appendChild(pickerCards);
        inputSection.appendChild(pickerPanel);

        if (hasNoInventory) {
          var missPane = document.createElement("div");
          missPane.className = "execute-missing-inventory-pane";
          missPane.style.cssText =
            "margin-top: 12px; margin-bottom: 0; padding: 16px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-lg); border: 1px solid var(--border-light, #e5e7eb);";
          var missP = document.createElement("p");
          missP.style.cssText = "font-size: 13px; color: var(--text-secondary); margin: 0 0 12px 0; line-height: 1.5;";
          missP.appendChild(document.createTextNode("⚠️ Nothing in inventory matches this input yet. Use "));
          var sStrong = document.createElement("strong");
          sStrong.textContent = "Add Missing Item";
          missP.appendChild(sStrong);
          missP.appendChild(
            document.createTextNode(
              " below to register what you need—you’ll be returned here afterwards to continue recording this step."
            )
          );
          missPane.appendChild(missP);
          var missBtn = document.createElement("button");
          missBtn.type = "button";
          missBtn.className = "btn btn-secondary btn-sm exec-add-missing-item-btn add-missing-item-btn";
          missBtn.style.fontSize = "13px";
          missBtn.dataset.inputName = input.name || "";
          missBtn.dataset.inputQuantity = input.quantity != null ? String(input.quantity) : "";
          missBtn.dataset.inputUnit = input.unit || "";
          missBtn.dataset.expectedInventoryType =
            input.expected_inventory_type || input.expectedInventoryType
              ? String(input.expected_inventory_type || input.expectedInventoryType)
              : input.source_output_id
                ? "work_in_progress"
                : "";
          if (input.producing_process_name) missBtn.dataset.producingProcessName = String(input.producing_process_name);
          if (input.producing_step_name) missBtn.dataset.producingStepName = String(input.producing_step_name);
          if (input.source_output_id) missBtn.dataset.sourceOutputId = String(input.source_output_id);
          if (input.source_step_id) missBtn.dataset.sourceStepId = String(input.source_step_id);
          if (input.source_process_id) missBtn.dataset.sourceProcessId = String(input.source_process_id);
          missBtn.textContent = "Add Missing Item";
          missPane.appendChild(missBtn);
          inputSection.appendChild(missPane);
        }

        var addPane = document.createElement("div");
        addPane.className = "execute-add-input-pane";
        addPane.style.cssText =
          "margin-top: 12px; margin-bottom: 0; padding: 16px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-lg); border: 1px solid var(--border-light, #e5e7eb);";
        var addLbl = document.createElement("label");
        addLbl.style.cssText = "display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 6px;";
        addLbl.textContent = "Add another input";
        addPane.appendChild(addLbl);
        var addDesc = document.createElement("p");
        addDesc.style.cssText = "font-size: 12px; color: var(--text-secondary); margin: 0 0 10px 0; line-height: 1.45;";
        addDesc.textContent =
          "Add one or more inputs to meet step quantity (e.g. multiple batches) or to record an additional material when inputs are not always set per execution.";
        addPane.appendChild(addDesc);
        var execAddAnotherButton = document.createElement("button");
        execAddAnotherButton.type = "button";
        execAddAnotherButton.className = "btn btn-secondary btn-sm execute-add-another-input-btn";
        execAddAnotherButton.style.fontSize = "13px";
        execAddAnotherButton.dataset.inputName = input.name || "";
        execAddAnotherButton.dataset.safeName = safeInputName;
        execAddAnotherButton.textContent = "+ Add another input";
        addPane.appendChild(execAddAnotherButton);
        inputSection.appendChild(addPane);

        var qtyWarn = document.createElement("div");
        qtyWarn.className = "execute-input-qty-expected-warning";
        qtyWarn.style.cssText =
          "display: none; margin-top: 12px; padding: 10px 12px; background: hsl(38, 92%, 95%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md); color: #92400e; font-size: 13px; font-weight: 500;";
        qtyWarn.setAttribute("role", "status");
        inputSection.appendChild(qtyWarn);
        var matWarn = document.createElement("div");
        matWarn.className = "execute-input-unexpected-material-warning";
        matWarn.style.cssText =
          "display: none; margin-top: 8px; padding: 10px 12px; background: hsl(210, 90%, 96%); border: 1px solid var(--info, #3b82f6); border-radius: var(--radius-md); color: #1e40af; font-size: 13px; font-weight: 500;";
        matWarn.setAttribute("role", "status");
        inputSection.appendChild(matWarn);

        // Ensure rows stack cleanly when adding additional inputs.
        if (rowsContainer) {
          rowsContainer.style.display = 'flex';
          rowsContainer.style.flexDirection = 'column';
          rowsContainer.style.gap = '12px';
        }
        const pickerTabs = Array.prototype.slice.call(inputSection.querySelectorAll('.flow-mode-segment'));
        let rowIndex = 0;
        var rowInputApi = {};
        if (!ses.inputStateByKey) ses.inputStateByKey = new Map();

        function normalizeInventoryTabType(inv) {
          return ITU.normalizeInventoryTabType(inv);
        }
        function invMatchesType(inv, selected) {
          return ITU.matchesInventoryTab(inv, selected);
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

          var qTrim = (q || '').trim();
          // Default (no search): show inventory related to expected input name.
          // While searching: search across all inventory.
          var base = qTrim ? allInventorySorted : sortedInventory;
          var list = base
            .filter(function(inv) { return invMatchesType(inv, activeType); })
            .filter(function(inv) { return ITU.matchesSearch(inv, qTrim); });
          list = list.filter(function(inv) {
            var id = String(inv.id);
            if (pendingId && id === pendingId) return true;
            return !selectedIds.has(id);
          });

          /**
           * Reuse picker card DOM nodes across filter/tab/search rerenders (same inventory row objects).
           */
          var pickerCardCache =
            inputSection._execPickerCardElCache ||
            (inputSection._execPickerCardElCache = new Map());

          var pickerCardCtx = {
            getExpiredReason: getExpiredReason,
            escapeHtml: escapeHtml,
            prettyLabel: prettyLabel,
            orgUsersMap: orgUsersMap
          };

          function computeExecPickerCardPayload(inv) {
            return ExecInvPickView.buildPayload(inv, pickerCardCtx);
          }
          function assembleExecPickerCard(inv, payload, isPending, rawId) {
            return ExecInvPickView.assembleCard(inv, payload, isPending, rawId, IDisp);
          }
          function syncExecPickerCard(card, inv, payload, isPending, rawId) {
            ExecInvPickView.syncCard(card, inv, payload, isPending, rawId, IDisp);
          }

          if (!list.length) {
            pickerCardCache.clear();
            pickerCards.replaceChildren();
            var emptyP = document.createElement('p');
            emptyP.style.cssText = 'margin: 0; font-size: 13px; color: var(--text-secondary); padding: 6px 2px;';
            emptyP.textContent = 'No inventory matches.';
            pickerCards.appendChild(emptyP);
            return;
          }
          var pickerFrag = document.createDocumentFragment();
          var seenIds = new Set();
          list.forEach(function(inv) {
            var rawId = String(inv.id);
            seenIds.add(rawId);
            var payload = computeExecPickerCardPayload(inv);
            var isPending = pendingId && pendingId === rawId;
            var card = pickerCardCache.get(rawId);
            if (card) {
              syncExecPickerCard(card, inv, payload, isPending, rawId);
            } else {
              card = assembleExecPickerCard(inv, payload, isPending, rawId);
              pickerCardCache.set(rawId, card);
            }
            pickerFrag.appendChild(card);
          });
          pickerCardCache.forEach(function(_el, id) {
            if (!seenIds.has(id)) pickerCardCache.delete(id);
          });
          pickerCards.replaceChildren(pickerFrag);
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
        function normalizeExpectedInventoryTabHint(inp) {
          return ITU.normalizeExpectedInventoryTabHint(inp);
        }

        /**
         * Choose initial category tab from name-matched inventory.
         * Previously any WIP/final in the fuzzy-matched set forced WIP/final over raw — wrong when the step
         * expects a raw material but loose name matching also pulled in finals.
         */
        function pickDefaultPickerType() {
          var hinted = normalizeExpectedInventoryTabHint(input);
          if (hinted) return hinted;

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

          // No rows matching this input name: tab counts are all zero — avoid defaulting to Raw unless we are sure.
          if (!list.length) {
            if (input && input.source_output_id) return 'work_in_progress';
            var expectedN = normInputName(input && input.name);
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

          if (input && input.source_output_id) {
            if (hasWip || hasFinal) {
              return counts.final_product > counts.work_in_progress ? 'final_product' : 'work_in_progress';
            }
            // Chained / previous-output inputs are never raw materials; default Intermediate when stock is missing.
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

        var defaultPickerType = pickDefaultPickerType();
        var IPC = root.InventoryPickerController;
        if (!IPC || typeof IPC.create !== "function") {
          throw new Error("inventory-picker-controller.js must load before execution-render-inputs.js");
        }
        var pickerCtl = IPC.create({
          inputSection: inputSection,
          pickerTabs: pickerTabs,
          pickerSearch: pickerSearch,
          defaultActiveType: defaultPickerType,
          onFilterChange: function (activeType, q) {
            renderPickerCards(activeType, q);
          },
          searchDebounceMs: 300
        });
        var pickerState = pickerCtl.state;
        var syncTabState = pickerCtl.syncTabState;
        pickerCtl.bind();
        if (pickerPanel) {
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
          return EIRR.createInputRow({
            isFirst: isFirst,
            safeInputName: safeInputName,
            bumpRowIndex: function () {
              return rowIndex++;
            },
            ses: ses,
            input: input,
            rowsContainer: rowsContainer,
            api: rowInputApi
          });
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
          delete hiddenInput.dataset.quantity;
          delete hiddenInput.dataset.unit;
          delete hiddenInput.dataset.expiredReason;

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
            hiddenInput.setAttribute('data-input-name', input.name || '');
            if (st) {
              st.input_name = input.name || '';
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
            var consumedLabel = (inv.name && String(inv.name).trim()) ? String(inv.name).trim() : (input.name || '');
            hiddenInput.setAttribute('data-input-name', consumedLabel);
            if (st) {
              st.input_name = consumedLabel;
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
              function addMetaCell(grid, label, value) {
                if (value == null || String(value) === '') return;
                var cell = document.createElement('div');
                var lab = document.createElement('span');
                lab.style.cssText = 'color:var(--text-tertiary,#9ca3af); font-size:12px;';
                lab.textContent = label;
                var valEl = document.createElement('div');
                valEl.style.fontWeight = '600';
                valEl.textContent = String(value);
                cell.appendChild(lab);
                cell.appendChild(valEl);
                grid.appendChild(cell);
              }
              selectedCardEl.replaceChildren();
              var rowTop = document.createElement('div');
              rowTop.style.cssText = 'display:flex; align-items:flex-start; justify-content:space-between; gap:12px;';
              var col = document.createElement('div');
              col.style.minWidth = '0';
              var t1 = document.createElement('div');
              t1.style.cssText = 'font-size:14px; font-weight:700; color:var(--text-primary,#111827);';
              t1.textContent = inv.name || 'Selected item';
              var t2 = document.createElement('div');
              t2.style.cssText = 'font-size:12px; color:var(--text-secondary,#6b7280); margin-top:4px;';
              t2.textContent = IDisp.formatSelectedRowSubtitle(inv);
              col.appendChild(t1);
              col.appendChild(t2);
              rowTop.appendChild(col);
              if (reason) {
                var chip = document.createElement('div');
                chip.className = 'exec-picker-chip exec-picker-chip--warn';
                chip.style.flexShrink = '0';
                chip.textContent = reason;
                rowTop.appendChild(chip);
              }
              selectedCardEl.appendChild(rowTop);
              var batchAny = inv.supplier_batch_number || inv.batch_number || inv.lot_number || '';
              var operatorAny = inv.operator_name || inv.operator || '';
              var createdByAny = inv.created_by_name || inv.created_by || '';
              if (inv.supplier || batchAny || operatorAny || createdByAny || inv.purchase_date || inv.expiry_date || inv.ready_date || inv.created_at) {
                var grid = document.createElement('div');
                grid.style.cssText =
                  'display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin-top:12px;';
                addMetaCell(grid, 'Supplier', inv.supplier);
                addMetaCell(grid, 'Batch', batchAny);
                addMetaCell(grid, 'Operator', operatorAny);
                addMetaCell(grid, 'Created by', createdByAny);
                if (inv.purchase_date) addMetaCell(grid, 'Purchase date', fmtDate(inv.purchase_date));
                if (inv.expiry_date) addMetaCell(grid, 'Expiry date', fmtDate(inv.expiry_date));
                if (inv.ready_date) addMetaCell(grid, 'Ready date', fmtDate(inv.ready_date));
                if (inv.created_at) addMetaCell(grid, 'Created', fmtDate(inv.created_at));
                selectedCardEl.appendChild(grid);
              }
              selectedCardEl.style.display = 'block';
            }
            if (qtyPane) qtyPane.style.display = 'block';
          }
          if (quantityInput) quantityInput.style.border = '1px solid var(--border-default, #e5e7eb)';
          updateSectionQtyExpectedWarning();
          updateUnexpectedMaterialWarning();
        }

        rowInputApi.setRowSelection = setRowSelection;

        const firstRow = createInputRow(true);
        rowsContainer.appendChild(firstRow);

        const hiddenInput = firstRow.querySelector('.execute-inventory-select');
        const quantityInput = firstRow.querySelector('.execute-quantity-input');
        const unitDisplay = firstRow.querySelector('.execute-quantity-unit-display');
        const triggerLabel = firstRow.querySelector('.execute-inventory-picker-label');
        const expiredWarningEl = firstRow.querySelector('.execute-input-expired-warning');

        function getInventorySelectionLabel(invId) {
          if (!invId) return 'Select inventory item...';
          var inv = inventoryById.get(String(invId));
          if (!inv) return 'Select inventory item...';
          return IDisp.formatTriggerLabel(inv);
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
        rowInputApi.setActiveRow = setActiveRow;
        rowInputApi.refreshPicker = function () {
          renderPickerCards(pickerState.activeType, pickerState.q);
        };

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
          var subtitleLine = escapeHtml(IDisp.formatDropdownCardSubtitle(inv));
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
        pickerCtl.resetSearchUiAndQuery();
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

        if (execAddAnotherButton) {
          execAddAnotherButton.addEventListener('click', function() {
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
        
        // Add Missing Item: previous-step output → untracked/WIP modal; catalog intermediate/final → same modal (via openAddInventoryModalForMissingInput); raw → raw modal or /inventory/add/manual
        const addMissingBtn = inputSection.querySelector('.add-missing-item-btn');
        if (addMissingBtn) {
          addMissingBtn.addEventListener('click', function() {
            var fromOutput = Boolean(this.dataset.sourceOutputId || this.dataset.sourceStepId || this.dataset.sourceProcessId);
            var sourceOutputId = this.dataset.sourceOutputId || '';
            var name_ = this.dataset.inputName || '';
            var quantity_ = this.dataset.inputQuantity != null && this.dataset.inputQuantity !== '' ? this.dataset.inputQuantity : '';
            var unit_ = this.dataset.inputUnit || '';
            var expectedInv = (this.dataset.expectedInventoryType || '').trim();
            if (!expectedInv) {
              try {
                expectedInv = String((inputSection && inputSection.dataset && inputSection.dataset.activePickerType) || '').trim();
              } catch (e0) {}
            }
            if (!expectedInv && pickerState && pickerState.activeType) {
              expectedInv = String(pickerState.activeType || '').trim();
            }
            var typeOpt =
              expectedInv === 'work_in_progress' || expectedInv === 'final_product' ? { inventory_type: expectedInv } : undefined;
            // Always route through openAddInventoryModalForMissingInput so batches/start uses the manual add page
            // and so intermediate/final get the correct field set.
            if (fromOutput && !expectedInv) expectedInv = 'work_in_progress';
            if (window.openAddInventoryModalForMissingInput) {
              window.openAddInventoryModalForMissingInput({
                name: name_,
                quantity: quantity_,
                unit: unit_,
                inventory_type: expectedInv || 'raw_material',
                producing_process_name: this.dataset.producingProcessName || '',
                producing_step_name: this.dataset.producingStepName || ''
              });
            }
          });
        }
        
        inputsContainer.appendChild(inputSection);
      });

  }

  /**
   * Variable inputs that do not use inventory: confirm quantity + unit at execution.
   * @param {{ inputsContainer: HTMLElement | null, confirmInputs: Array<unknown> }} ctx
   */
  function renderConfirmExecutionInputs(ctx) {
    var inputsContainer = ctx.inputsContainer;
    var confirmInputs = ctx.confirmInputs;
    if (!confirmInputs || !confirmInputs.length || !inputsContainer) return;
    confirmInputs.forEach(function (input) {
      const inputSection = document.createElement('div');
      inputSection.className = 'execute-input-section';
      inputSection.style.cssText =
        'margin-bottom: 20px; padding: 16px; border: 1px solid var(--border-light); border-radius: var(--radius-md);';

      var rowHead = document.createElement('div');
      rowHead.style.marginBottom = '12px';
      var lblHead = document.createElement('label');
      lblHead.style.cssText =
        'display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;';
      lblHead.appendChild(document.createTextNode(input.name || ''));
      lblHead.appendChild(document.createTextNode(' '));
      var expSp = document.createElement('span');
      expSp.style.cssText = 'color: var(--text-secondary); font-weight: normal;';
      expSp.textContent =
        '(Expected: ' + String(input.quantity != null ? input.quantity : '0') + ' ' + (input.unit || '') + ')';
      lblHead.appendChild(expSp);
      lblHead.appendChild(document.createTextNode(' '));
      var ast1 = document.createElement('span');
      ast1.style.color = 'var(--error, #ef4444)';
      ast1.textContent = '*';
      lblHead.appendChild(ast1);
      rowHead.appendChild(lblHead);
      inputSection.appendChild(rowHead);

      var qtyRow = document.createElement('div');
      qtyRow.style.marginBottom = '12px';
      var qtyLbl = document.createElement('label');
      qtyLbl.style.cssText =
        'display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;';
      qtyLbl.appendChild(document.createTextNode('Quantity '));
      var ast2 = document.createElement('span');
      ast2.style.color = 'var(--error, #ef4444)';
      ast2.textContent = '*';
      qtyLbl.appendChild(ast2);
      qtyRow.appendChild(qtyLbl);
      var qtyInputEl = document.createElement('input');
      qtyInputEl.type = 'number';
      qtyInputEl.className = 'spa-inp execute-confirm-quantity-input';
      qtyInputEl.dataset.inputName = input.name || '';
      qtyInputEl.dataset.required = 'true';
      qtyInputEl.placeholder = String(input.quantity != null ? input.quantity : '0');
      qtyInputEl.value = input.quantity != null ? String(input.quantity) : '';
      qtyInputEl.step = '0.01';
      qtyInputEl.min = '0';
      qtyRow.appendChild(qtyInputEl);
      inputSection.appendChild(qtyRow);

      var unitRow = document.createElement('div');
      var unitLbl = document.createElement('label');
      unitLbl.style.cssText =
        'display: block; font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;';
      unitLbl.appendChild(document.createTextNode('Unit '));
      var ast3 = document.createElement('span');
      ast3.style.color = 'var(--error, #ef4444)';
      ast3.textContent = '*';
      unitLbl.appendChild(ast3);
      unitRow.appendChild(unitLbl);
      var unitSel = document.createElement('select');
      unitSel.className = 'spa-inp execute-confirm-unit-input';
      unitSel.dataset.inputName = input.name || '';
      unitSel.dataset.required = 'true';
      var opt0 = document.createElement('option');
      opt0.value = '';
      opt0.textContent = 'Select unit...';
      unitSel.appendChild(opt0);
      [
        'kg', 'g', 'mg', 'lb', 'oz', 'ton', 'tonne', 'l', 'ml', 'gal', 'm3', 'ft3', 'm', 'cm', 'mm', 'ft', 'in',
        'units', 'pcs', 'pieces', 'boxes', 'pallets', 'containers',
      ].forEach(function(unit) {
        var op = document.createElement('option');
        op.value = unit;
        op.textContent = unit;
        if (input.unit === unit) op.selected = true;
        unitSel.appendChild(op);
      });
      unitRow.appendChild(unitSel);
      inputSection.appendChild(unitRow);

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
