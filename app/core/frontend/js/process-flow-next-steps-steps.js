/**
 * Next-steps page: expandable step rows + drag/drop reorder (parity with flows2.html structure).
 */
(function () {
  var CONTAINER_ID = 'next-steps-steps-container';
  var DRAG_HINT_ID = 'next-steps-drag-hint';
  var processId = '';

  function escapeHtml(text) {
    if (!text) return '';
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function posNum(x) {
    var n = x && x.position != null ? Number(x.position) : NaN;
    return Number.isFinite(n) ? n : null;
  }

  function sortSteps(steps) {
    return [].concat(steps || []).sort(function (a, b) {
      var ap = posNum(a);
      var bp = posNum(b);
      if (ap != null && bp != null) return ap - bp;
      if (ap != null && bp == null) return -1;
      if (ap == null && bp != null) return 1;
      return (a.step_number || 0) - (b.step_number || 0);
    });
  }

  function notifySuccess(title, message) {
    if (typeof window.showNotification === 'function') {
      window.showNotification('success', title, message);
    }
  }

  function notifyError(title, message) {
    if (typeof window.showNotification === 'function') {
      window.showNotification('error', title, message);
    } else {
      console.error(title, message);
    }
  }

  /**
   * Mirrors flows2.html createStepCard (read-only summary + Edit link).
   */
  function createStepCard(step, displayIndex) {
    var card = document.createElement('div');
    card.className = 'step-card flows2-step';
    card.setAttribute('data-step-id', step.id || 'step-new-' + Date.now());
    card.setAttribute('data-expanded', 'false');

    var inputs = step.inputs || [];
    var outputs = step.outputs || [];
    var executionPrompts = step.execution_prompts || [];
    var displayNumber = typeof displayIndex === 'number' ? displayIndex + 1 : (step.step_number || 1);
    var hasConfigs = !!(step && (step.configurations || step.configuration || step.config || step.settings));

    function fmtQty(q, unit) {
      var hasQ = q === 0 || q;
      var qn = hasQ ? String(q) : '';
      var u = (unit || '').toString().trim();
      if (!qn && !u) return '';
      if (!qn) return escapeHtml(u);
      if (!u) return escapeHtml(qn);
      return escapeHtml(qn + ' ' + u);
    }

    function inputModeLabel(i) {
      var invSel = i && i.requires_inventory_selection === true;
      var isVar = i && i.is_variable !== false;
      if (invSel && isVar) return 'Select inventory at execution';
      if (isVar) return 'Confirm at execution';
      return 'Static';
    }

    function outputModeLabel(o) {
      var invSel = o && o.requires_inventory_selection === true;
      var isVar = o && o.is_variable !== false;
      if (invSel && isVar) return 'Select inventory at execution';
      if (isVar) return 'Confirm at execution';
      return 'Static';
    }

    function promptFlag(labelLower) {
      var p = (executionPrompts || []).find(function (x) {
        if (!x) return false;
        var l = (x.label || '').toString().toLowerCase();
        if (labelLower === 'evidence') {
          var t = (x.type || '').toString().toLowerCase();
          return t === 'evidence' || l === 'evidence';
        }
        return l === labelLower;
      });
      if (!p) return null;
      if (p.required === false) return 'Optional';
      return 'Required';
    }

    var batchFlag = promptFlag('batch number');
    var evidenceFlag = promptFlag('evidence');

    var cfgObj = step && (step.configurations || step.configuration || step.config || step.settings) || null;
    var cfgJson = hasConfigs ? escapeHtml(JSON.stringify(cfgObj, null, 2)) : '';

    var inputsSummaryHtml = inputs && inputs.length
      ? inputs.map(function (i) {
          var name = escapeHtml(i && i.name ? String(i.name) : '—');
          var qty = fmtQty(i && i.quantity, i && i.unit);
          var mode = escapeHtml(inputModeLabel(i));
          return (
            '<div class="flows2-summary-item">' +
              '<div class="flows2-summary-item__main">' +
                '<div class="flows2-summary-item__row">' +
                  '<div class="flows2-summary-item__title">' + name + '</div>' +
                  '<div class="flows2-chip">' + mode + '</div>' +
                '</div>' +
                '<div class="flows2-summary-item__sub">' + (qty || '') + '</div>' +
              '</div>' +
            '</div>'
          );
        }).join('')
      : '<p class="flows2-empty">No inputs configured.</p>';

    var outputsSummaryHtml = outputs && outputs.length
      ? outputs.map(function (o) {
          var name = escapeHtml(o && o.name ? String(o.name) : '—');
          var qty = fmtQty(o && o.quantity, o && o.unit);
          var mode = escapeHtml(outputModeLabel(o));
          var extra = o && o.extra_data && typeof o.extra_data === 'object' ? o.extra_data : null;
          var hasExpiry = !!(extra && extra.custom_expiry && extra.custom_expiry.enabled);
          var hasReady = !!(extra && extra.ready_date && extra.ready_date.enabled);
          var extras = [];
          if (hasExpiry) extras.push('Expiry rules');
          if (hasReady) extras.push('Ready date rules');
          var extrasText = extras.length ? escapeHtml(extras.join(' • ')) : '';
          var sub = [qty, extrasText].filter(Boolean).join(' • ');
          return (
            '<div class="flows2-summary-item">' +
              '<div class="flows2-summary-item__main">' +
                '<div class="flows2-summary-item__row">' +
                  '<div class="flows2-summary-item__title">' + name + '</div>' +
                  '<div class="flows2-chip">' + mode + '</div>' +
                '</div>' +
                '<div class="flows2-summary-item__sub">' + sub + '</div>' +
              '</div>' +
            '</div>'
          );
        }).join('')
      : '<p class="flows2-empty">No outputs configured.</p>';

    function isTraceabilityOrSystemPrompt(p) {
      if (!p) return false;
      var labelRaw = (p.label || p.prompt || '').toString().trim().toLowerCase();
      var typeRaw = (p.type || '').toString().trim().toLowerCase();
      if (labelRaw === 'batch number' || labelRaw === 'evidence') return true;
      if (typeRaw === 'evidence') return true;
      return false;
    }
    var customPrompts = (executionPrompts || []).filter(function (p) {
      return !isTraceabilityOrSystemPrompt(p);
    });

    var promptsSummaryHtml = customPrompts && customPrompts.length
      ? customPrompts.map(function (p) {
          var label = escapeHtml(p && (p.label || p.prompt) ? String(p.label || p.prompt) : '—');
          var type = escapeHtml(p && p.type ? String(p.type) : 'text');
          var unit = escapeHtml(p && p.unit ? String(p.unit) : '');
          var req = p && p.required === false ? 'Optional' : 'Required';
          var sub = [type, unit ? ('Unit: ' + unit) : ''].filter(Boolean).join(' • ');
          return (
            '<div class="flows2-summary-item">' +
              '<div class="flows2-summary-item__main">' +
                '<div class="flows2-summary-item__row">' +
                  '<div class="flows2-summary-item__title">' + label + '</div>' +
                  '<div class="flows2-chip">' + escapeHtml(req) + '</div>' +
                '</div>' +
                '<div class="flows2-summary-item__sub">' + escapeHtml(sub) + '</div>' +
              '</div>' +
            '</div>'
          );
        }).join('')
      : '';

    function pickDocs(obj) {
      if (!obj || typeof obj !== 'object') return null;
      return obj.docs || obj.documentation || obj.documents || obj.process_docs || obj.processDocs || null;
    }
    var docsObj = pickDocs(cfgObj);
    var hasDocs = !!(docsObj && (Array.isArray(docsObj) ? docsObj.length : true));
    var docsJson = hasDocs ? escapeHtml(JSON.stringify(docsObj, null, 2)) : '';

    var editHref =
      processId && step.id
        ? '/core/flows/create/step-name?id=' +
          encodeURIComponent(processId) +
          '&edit=' +
          encodeURIComponent(step.id)
        : '#';

    // nosemgrep: innerhtml-string-concat -- audited: all dynamic values here go through escapeHtml() or encodeURIComponent()
    card.innerHTML =
      '<div class="flows2-step__header">' +
        '<button type="button" class="flows2-step__drag step-drag-handle" draggable="true" title="Drag to reorder" aria-label="Drag to reorder" onmousedown="event.stopPropagation();" onclick="event.stopPropagation();">' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
            '<line x1="8" y1="6" x2="8" y2="6"></line>' +
            '<line x1="8" y1="12" x2="8" y2="12"></line>' +
            '<line x1="8" y1="18" x2="8" y2="18"></line>' +
            '<line x1="16" y1="6" x2="16" y2="6"></line>' +
            '<line x1="16" y1="12" x2="16" y2="12"></line>' +
            '<line x1="16" y1="18" x2="16" y2="18"></line>' +
          '</svg>' +
        '</button>' +
        '<div class="flow-step-num-badge step-number" aria-label="Step number">' +
          escapeHtml(String(displayNumber)) +
        '</div>' +
        '<div class="flows2-step__titlewrap" onclick="toggleStep(this)">' +
          '<p class="flows2-step__title">' +
            escapeHtml(step.name || 'Unnamed step') +
          '</p>' +
          '<p class="flows2-step__sub">' +
            (escapeHtml(step.description || '') || 'No description') +
          '</p>' +
        '</div>' +
        '<div class="flows2-step__header-edit">' +
          '<a class="btn btn-secondary btn-sm" href="' +
            editHref +
            '" hx-boost="false" onclick="event.stopPropagation();">Edit</a>' +
        '</div>' +
        '<button type="button" class="flows2-step__toggle" onclick="toggleStep(this)" aria-label="Expand step">' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
            '<polyline points="6 9 12 15 18 9"></polyline>' +
          '</svg>' +
        '</button>' +
      '</div>' +
      '<div class="flows2-step__body">' +
        '<div class="flows2-step__body-inner">' +
          '<div class="flows2-section">' +
            '<p class="flows2-section__title">Inputs</p>' +
            '<div class="flows2-summary-list">' +
              inputsSummaryHtml +
            '</div>' +
          '</div>' +
          '<div class="flows2-section">' +
            '<p class="flows2-section__title">Outputs</p>' +
            '<div class="flows2-summary-list">' +
              outputsSummaryHtml +
            '</div>' +
          '</div>' +
          '<div class="flows2-section">' +
            '<p class="flows2-section__title">Traceability & compliance</p>' +
            '<div class="flows2-summary-list">' +
              '<div class="flows2-summary-item">' +
                '<div class="flows2-summary-item__main">' +
                  '<div class="flows2-summary-item__row">' +
                    '<div class="flows2-summary-item__title">Batch number</div>' +
                    '<div class="flows2-chip">' +
                      escapeHtml(batchFlag || 'Off') +
                    '</div>' +
                  '</div>' +
                '</div>' +
              '</div>' +
              '<div class="flows2-summary-item">' +
                '<div class="flows2-summary-item__main">' +
                  '<div class="flows2-summary-item__row">' +
                    '<div class="flows2-summary-item__title">Evidence</div>' +
                    '<div class="flows2-chip">' +
                      escapeHtml(evidenceFlag || 'Off') +
                    '</div>' +
                  '</div>' +
                '</div>' +
              '</div>' +
            '</div>' +
          '</div>' +
          '<div class="flows2-section">' +
            '<p class="flows2-section__title">Prompts</p>' +
            '<div class="flows2-summary-list' +
              (promptsSummaryHtml ? '' : ' flows2-summary-list--empty') +
              '">' +
              (promptsSummaryHtml ||
                '<div class="flows2-summary-item"><div class="flows2-summary-item__main"><div class="flows2-summary-item__row">' +
                  '<div class="flows2-summary-item__title">No custom prompts configured.</div>' +
                '</div>' +
                '<div class="flows2-summary-item__sub">Add prompts to capture operator inputs during execution.</div>' +
              '</div></div>') +
            '</div>' +
          '</div>' +
          (hasDocs
            ? '<div class="flows2-section">' +
                '<p class="flows2-section__title">Documentation</p>' +
                '<pre style="margin:0; padding: 10px 0; overflow:auto; max-height: 240px;">' +
                  docsJson +
                '</pre>' +
              '</div>'
            : '') +
          (hasConfigs
            ? '<div class="flows2-section">' +
                '<p class="flows2-section__title">Advanced settings</p>' +
                '<pre style="margin:0; padding: 10px 0; overflow:auto; max-height: 240px;">' +
                  cfgJson +
                '</pre>' +
              '</div>'
            : '') +
        '</div>' +
      '</div>';

    return card;
  }

  function renderSteps(steps) {
    var container = document.getElementById(CONTAINER_ID);
    if (!container) return;

    container.innerHTML = '';

    var dragHint = document.getElementById(DRAG_HINT_ID);

    if (!steps || steps.length === 0) {
      container.innerHTML =
        '<p class="next-steps-hub-empty" role="status">No steps yet. Use the Add another step button below.</p>';
      if (dragHint) dragHint.style.display = 'none';
      return;
    }

    var sortedSteps = sortSteps(steps);
    sortedSteps.forEach(function (step, index) {
      container.appendChild(createStepCard(step, index));
    });

    initializeStepDragAndDrop();

    if (dragHint) {
      dragHint.style.display = sortedSteps.length > 1 ? 'block' : 'none';
    }
  }

  var draggedStepCard = null;

  function initializeStepDragAndDrop() {
    var container = document.getElementById(CONTAINER_ID);
    if (!container) return;

    var stepCards = container.querySelectorAll('.step-card');

    stepCards.forEach(function (card, index) {
      var dragHandle = card.querySelector('.step-drag-handle');
      if (!dragHandle) return;

      dragHandle.addEventListener('dragstart', function (e) {
        draggedStepCard = card;
        card.style.opacity = '0.5';
        dragHandle.style.cursor = 'grabbing';
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/html', card.innerHTML);
      });

      dragHandle.addEventListener('dragend', function () {
        card.style.opacity = '1';
        dragHandle.style.cursor = 'grab';
        Array.prototype.forEach.call(stepCards, function (c) {
          c.classList.remove('drag-over');
          c.style.borderTop = '';
          c.style.borderBottom = '';
        });
        draggedStepCard = null;
      });

      card.addEventListener('dragover', function (e) {
        if (draggedStepCard && draggedStepCard !== card) {
          e.preventDefault();
          e.dataTransfer.dropEffect = 'move';

          var rect = card.getBoundingClientRect();
          var midpoint = rect.top + rect.height / 2;
          var mouseY = e.clientY;

          Array.prototype.forEach.call(stepCards, function (c) {
            c.classList.remove('drag-over');
            c.style.borderTop = '';
            c.style.borderBottom = '';
          });

          if (mouseY < midpoint) {
            card.style.borderTop = '3px solid var(--primary, #3b82f6)';
          } else {
            card.style.borderBottom = '3px solid var(--primary, #3b82f6)';
          }
        }
      });

      card.addEventListener('dragleave', function (e) {
        if (!card.contains(e.relatedTarget)) {
          card.style.borderTop = '';
          card.style.borderBottom = '';
        }
      });

      card.addEventListener('drop', function (e) {
        e.preventDefault();
        e.stopPropagation();

        if (!draggedStepCard || draggedStepCard === card) {
          return;
        }

        Array.prototype.forEach.call(stepCards, function (c) {
          c.style.borderTop = '';
          c.style.borderBottom = '';
          c.classList.remove('drag-over');
        });

        var rect = card.getBoundingClientRect();
        var midpoint = rect.top + rect.height / 2;
        var mouseY = e.clientY;
        var insertBefore = mouseY < midpoint;

        if (insertBefore) {
          container.insertBefore(draggedStepCard, card);
        } else {
          var nextSibling = card.nextSibling;
          if (nextSibling) {
            container.insertBefore(draggedStepCard, nextSibling);
          } else {
            container.appendChild(draggedStepCard);
          }
        }

        void updateStepOrder();
      });
    });
  }

  async function updateStepOrder() {
    var container = document.getElementById(CONTAINER_ID);
    if (!container || !processId) return;

    var stepCards = container.querySelectorAll('.step-card');
    var orderedIds = [];

    stepCards.forEach(function (card, index) {
      var stepId = card.getAttribute('data-step-id');
      var newStepNumber = index + 1;

      var stepNumberEl = card.querySelector('.step-number');
      if (stepNumberEl) {
        stepNumberEl.textContent = String(newStepNumber);
      }

      if (stepId && !stepId.startsWith('step-new-') && !stepId.startsWith('temp-step-')) {
        orderedIds.push(stepId);
      }
    });

    if (orderedIds.length === 0) return;

    try {
      var csrfMeta = document.querySelector('meta[name="csrf-token"]');
      var csrfTok = csrfMeta && csrfMeta.getAttribute('content');
      var headers = { 'Content-Type': 'application/json' };
      if (csrfTok) {
        headers['X-CSRFToken'] = csrfTok;
        headers['X-CSRF-Token'] = csrfTok;
      }
      var spacing = 1000;
      var orders = orderedIds.map(function (id, idx) {
        return { id: id, position: spacing * (idx + 1) };
      });
      // nosemgrep: raw-fetch-post -- X-CSRFToken already attached above (headers)
      var res = await fetch(
        '/api/core/processes/' + encodeURIComponent(processId) + '/steps/reorder',
        {
          method: 'POST',
          credentials: 'include',
          headers: headers,
          body: JSON.stringify({ orders: orders })
        }
      );
      if (!res.ok) throw new Error('Failed to reorder');

      notifySuccess('Steps reordered', 'Step order has been saved successfully.');
    } catch (error) {
      console.error('Failed to update step order:', error);
      notifyError('Error', 'Failed to save step order. Please try again.');
      await loadAndRender();
    }
  }

  window.toggleStep = function (header) {
    var stepCard = header.closest('.step-card');
    if (!stepCard) return;
    var expanded = stepCard.getAttribute('data-expanded') === 'true';
    stepCard.setAttribute('data-expanded', expanded ? 'false' : 'true');
  };

  async function loadAndRender() {
    processId =
      new URLSearchParams(window.location.search || '').get('id') ||
      new URLSearchParams(window.location.search || '').get('process_id') ||
      '';

    var container = document.getElementById(CONTAINER_ID);
    if (!container) return;

    container.setAttribute('aria-busy', 'true');

    if (!processId) {
      container.innerHTML =
        '<p class="next-steps-hub-empty" role="status">No workflow selected.</p>';
      container.setAttribute('aria-busy', 'false');
      var dh0 = document.getElementById(DRAG_HINT_ID);
      if (dh0) dh0.style.display = 'none';
      return;
    }

    if (!window.CoreAPI || typeof window.CoreAPI.getProcess !== 'function') {
      container.innerHTML =
        '<p class="next-steps-hub-empty" role="alert">Could not load workflow API.</p>';
      container.setAttribute('aria-busy', 'false');
      return;
    }

    try {
      var data = await window.CoreAPI.getProcess(processId);
      renderSteps((data && data.steps) ? data.steps : []);
    } catch (e) {
      console.error(e);
      container.innerHTML =
        '<p class="next-steps-hub-empty" role="alert">Failed to load steps.</p>';
      var dh1 = document.getElementById(DRAG_HINT_ID);
      if (dh1) dh1.style.display = 'none';
    }

    container.setAttribute('aria-busy', 'false');
  }

  function boot() {
    loadAndRender();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();

