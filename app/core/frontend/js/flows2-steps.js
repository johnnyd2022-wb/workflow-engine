    // RULE: Never use innerHTML with API data. Use textContent or DOM APIs.
    function renderSteps(steps) {
      const container = document.getElementById('steps-container');
      if (!container) return;
      
      container.replaceChildren();
      
      if (!steps || steps.length === 0) {
        const wrap = document.createElement('div');
        wrap.style.textAlign = 'center';
        wrap.style.padding = '32px';
        const p = document.createElement('p');
        p.style.color = 'var(--text-secondary)';
        p.textContent = 'No steps defined for this process.';
        wrap.appendChild(p);
        container.appendChild(wrap);
        // Update step count text
        const stepCountText = document.getElementById('step-count-text');
        if (stepCountText) {
          stepCountText.textContent = '0 steps in this process';
        }
        return;
      }
      
      // Update step count text
      const stepCountText = document.getElementById('step-count-text');
      if (stepCountText) {
        stepCountText.textContent = `${steps.length} step${steps.length !== 1 ? 's' : ''} in this process`;
      }
      
      function posNum(x) {
        const n = x && x.position != null ? Number(x.position) : NaN;
        return Number.isFinite(n) ? n : null;
      }
      // Prefer canonical ordering by position (reorder endpoint maintains it). Fall back to step_number.
      const sortedSteps = [...steps].sort((a, b) => {
        const ap = posNum(a);
        const bp = posNum(b);
        if (ap != null && bp != null) return ap - bp;
        if (ap != null && bp == null) return -1;
        if (ap == null && bp != null) return 1;
        return (a.step_number || 0) - (b.step_number || 0);
      });
      
      sortedSteps.forEach((step, index) => {
        const stepCard = createStepCard(step, index);
        container.appendChild(stepCard);
      });
      
      // Update button visibility after rendering all steps
      updateFromOutputButtonVisibility();
      
      // Initialize drag and drop functionality
      initializeStepDragAndDrop();
      
      // Show/hide drag hint text
      const dragHintText = document.getElementById('drag-hint-text');
      if (dragHintText) {
        dragHintText.style.display = sortedSteps.length > 1 ? 'block' : 'none';
      }
    }
    
    /**
     * Summary row in the flows2 step card body: title + chip + optional sub line.
     * @param {boolean} [omitSubRow] — if true, no `.flows2-summary-item__sub` (traceability rows).
     */
    function flows2AppendStepSummaryItem(listEl, titleText, chipText, subText, omitSubRow) {
      const item = document.createElement('div');
      item.className = 'flows2-summary-item';
      const main = document.createElement('div');
      main.className = 'flows2-summary-item__main';
      const row = document.createElement('div');
      row.className = 'flows2-summary-item__row';
      const titleEl = document.createElement('div');
      titleEl.className = 'flows2-summary-item__title';
      titleEl.textContent = titleText;
      row.appendChild(titleEl);
      if (chipText != null && chipText !== '') {
        const chipEl = document.createElement('div');
        chipEl.className = 'flows2-chip';
        chipEl.textContent = chipText;
        row.appendChild(chipEl);
      }
      main.appendChild(row);
      if (!omitSubRow) {
        const subEl = document.createElement('div');
        subEl.className = 'flows2-summary-item__sub';
        subEl.textContent = subText != null ? String(subText) : '';
        main.appendChild(subEl);
      }
      item.appendChild(main);
      listEl.appendChild(item);
    }
    // Create step card (displayIndex is 0-based; badge shows displayIndex + 1 so first step always shows 1)
    function createStepCard(step, displayIndex) {
      const card = document.createElement('div');
      card.className = 'step-card flows2-step';
      card.setAttribute('data-step-id', step.id || `step-new-${Date.now()}`);
      card.setAttribute('data-expanded', 'false');
      
      const inputs = step.inputs || [];
      const outputs = step.outputs || [];
      const executionPrompts = step.execution_prompts || [];
      const displayNumber = typeof displayIndex === 'number' ? displayIndex + 1 : (step.step_number || 1);
      const hasConfigs = !!(step && (step.configurations || step.configuration || step.config || step.settings));

      function fmtQtyPlain(q, unit) {
        const hasQ = (q === 0 || q);
        const qn = hasQ ? String(q) : '';
        const u = (unit || '').toString().trim();
        if (!qn && !u) return '';
        if (!qn) return u;
        if (!u) return qn;
        return `${qn} ${u}`;
      }

      function inputModeLabel(i) {
        const invSel = i && i.requires_inventory_selection === true;
        const isVar = i && i.is_variable !== false;
        if (invSel && isVar) return 'Select inventory at execution';
        if (isVar) return 'Confirm at execution';
        return 'Static';
      }

      function outputModeLabel(o) {
        const invSel = o && o.requires_inventory_selection === true;
        const isVar = o && o.is_variable !== false;
        if (invSel && isVar) return 'Select inventory at execution';
        if (isVar) return 'Confirm at execution';
        return 'Static';
      }

      function promptFlag(labelLower) {
        const p = (executionPrompts || []).find(function (x) {
          if (!x) return false;
          const l = (x.label || '').toString().toLowerCase();
          if (labelLower === 'evidence') {
            const t = (x.type || '').toString().toLowerCase();
            return t === 'evidence' || l === 'evidence';
          }
          return l === labelLower;
        });
        if (!p) return null;
        // Match create-process-modal.js deriveTraceabilityModes: only explicit false is optional.
        if (p.required === false) return 'Optional';
        return 'Required';
      }

      const batchFlag = promptFlag('batch number');
      const evidenceFlag = promptFlag('evidence');

      const cfgObj = step && (step.configurations || step.configuration || step.config || step.settings) || null;

      function isTraceabilityOrSystemPrompt(p) {
        if (!p) return false;
        const labelRaw = (p.label || p.prompt || '').toString().trim().toLowerCase();
        const typeRaw = (p.type || '').toString().trim().toLowerCase();
        if (labelRaw === 'batch number' || labelRaw === 'evidence') return true;
        if (typeRaw === 'evidence') return true;
        return false;
      }
      const customPrompts = (executionPrompts || []).filter(p => !isTraceabilityOrSystemPrompt(p));

      // Best-effort documentation extraction from advanced config blocks (if present).
      function pickDocs(obj) {
        if (!obj || typeof obj !== 'object') return null;
        return obj.docs || obj.documentation || obj.documents || obj.process_docs || obj.processDocs || null;
      }
      const docsObj = pickDocs(cfgObj);
      const hasDocs = !!(docsObj && (Array.isArray(docsObj) ? docsObj.length : true));

      const header = document.createElement('div');
      header.className = 'flows2-step__header';

      const dragBtn = document.createElement('button');
      dragBtn.type = 'button';
      dragBtn.className = 'flows2-step__drag step-drag-handle';
      dragBtn.draggable = true;
      dragBtn.title = 'Drag to reorder';
      dragBtn.setAttribute('aria-label', 'Drag to reorder');
      dragBtn.appendChild(flows2SvgStepDragGrip18());
      dragBtn.addEventListener('mousedown', (e) => e.stopPropagation());
      dragBtn.addEventListener('click', (e) => e.stopPropagation());

      const badge = document.createElement('div');
      badge.className = 'flow-step-num-badge step-number';
      badge.setAttribute('aria-label', 'Step number');
      badge.textContent = String(displayNumber);

      const titleWrap = document.createElement('div');
      titleWrap.className = 'flows2-step__titlewrap';
      titleWrap.addEventListener('click', () => {
        if (typeof window.toggleStep === 'function') window.toggleStep(titleWrap);
      });
      const titleP = document.createElement('p');
      titleP.className = 'flows2-step__title';
      titleP.textContent = step.name || 'Unnamed step';
      const subP = document.createElement('p');
      subP.className = 'flows2-step__sub';
      subP.textContent = (step.description && String(step.description)) || 'No description';
      titleWrap.appendChild(titleP);
      titleWrap.appendChild(subP);

      const meta = document.createElement('div');
      meta.className = 'flows2-step__meta';
      const metaIn = document.createElement('span');
      metaIn.textContent = `${inputs.length} input${inputs.length !== 1 ? 's' : ''}`;
      const metaOut = document.createElement('span');
      metaOut.textContent = `${outputs.length} output${outputs.length !== 1 ? 's' : ''}`;
      meta.appendChild(metaIn);
      meta.appendChild(metaOut);

      const expandBtn = document.createElement('button');
      expandBtn.type = 'button';
      expandBtn.className = 'flows2-step__toggle';
      expandBtn.setAttribute('aria-label', 'Expand step');
      expandBtn.appendChild(flows2SvgChevronDown18());
      expandBtn.addEventListener('click', () => {
        if (typeof window.toggleStep === 'function') window.toggleStep(expandBtn);
      });

      header.appendChild(dragBtn);
      header.appendChild(badge);
      header.appendChild(titleWrap);
      header.appendChild(meta);
      header.appendChild(expandBtn);
      card.appendChild(header);

      const body = document.createElement('div');
      body.className = 'flows2-step__body';
      const bodyInner = document.createElement('div');
      bodyInner.className = 'flows2-step__body-inner';

      function appendInputsSection() {
        const sec = document.createElement('div');
        sec.className = 'flows2-section';
        const t = document.createElement('p');
        t.className = 'flows2-section__title';
        t.textContent = 'Inputs';
        const list = document.createElement('div');
        list.className = 'flows2-summary-list';
        if (inputs && inputs.length) {
          inputs.forEach((i) => {
            const name = (i && i.name) ? String(i.name) : '—';
            const qty = fmtQtyPlain(i && i.quantity, i && i.unit);
            flows2AppendStepSummaryItem(list, name, inputModeLabel(i), qty);
          });
        } else {
          const empty = document.createElement('p');
          empty.className = 'flows2-empty';
          empty.textContent = 'No inputs configured.';
          list.appendChild(empty);
        }
        sec.appendChild(t);
        sec.appendChild(list);
        bodyInner.appendChild(sec);
      }

      function appendOutputsSection() {
        const sec = document.createElement('div');
        sec.className = 'flows2-section';
        const t = document.createElement('p');
        t.className = 'flows2-section__title';
        t.textContent = 'Outputs';
        const list = document.createElement('div');
        list.className = 'flows2-summary-list';
        if (outputs && outputs.length) {
          outputs.forEach((o) => {
            const name = (o && o.name) ? String(o.name) : '—';
            const qty = fmtQtyPlain(o && o.quantity, o && o.unit);
            const extra = o && o.extra_data && typeof o.extra_data === 'object' ? o.extra_data : null;
            const hasExpiry = !!(extra && extra.custom_expiry && extra.custom_expiry.enabled);
            const hasReady = !!(extra && extra.ready_date && extra.ready_date.enabled);
            const extras = [];
            if (hasExpiry) extras.push('Expiry rules');
            if (hasReady) extras.push('Ready date rules');
            const extrasText = extras.length ? extras.join(' • ') : '';
            const sub = [qty, extrasText].filter(Boolean).join(' • ');
            flows2AppendStepSummaryItem(list, name, outputModeLabel(o), sub);
          });
        } else {
          const empty = document.createElement('p');
          empty.className = 'flows2-empty';
          empty.textContent = 'No outputs configured.';
          list.appendChild(empty);
        }
        sec.appendChild(t);
        sec.appendChild(list);
        bodyInner.appendChild(sec);
      }

      function appendTraceabilitySection() {
        const sec = document.createElement('div');
        sec.className = 'flows2-section';
        const t = document.createElement('p');
        t.className = 'flows2-section__title';
        t.textContent = 'Traceability & compliance';
        const list = document.createElement('div');
        list.className = 'flows2-summary-list';
        flows2AppendStepSummaryItem(list, 'Batch number', batchFlag || 'Off', '', true);
        flows2AppendStepSummaryItem(list, 'Evidence', evidenceFlag || 'Off', '', true);
        sec.appendChild(t);
        sec.appendChild(list);
        bodyInner.appendChild(sec);
      }

      function appendPromptsSection() {
        const sec = document.createElement('div');
        sec.className = 'flows2-section';
        const t = document.createElement('p');
        t.className = 'flows2-section__title';
        t.textContent = 'Prompts';
        const list = document.createElement('div');
        list.className =
          'flows2-summary-list' + (customPrompts && customPrompts.length ? '' : ' flows2-summary-list--empty');
        if (customPrompts && customPrompts.length) {
          customPrompts.forEach((p) => {
            const label = (p && (p.label || p.prompt)) ? String(p.label || p.prompt) : '—';
            const type = (p && p.type) ? String(p.type) : 'text';
            const unit = (p && p.unit) ? String(p.unit) : '';
            const req = p && p.required === false ? 'Optional' : 'Required';
            const sub = [type, unit ? `Unit: ${unit}` : ''].filter(Boolean).join(' • ');
            flows2AppendStepSummaryItem(list, label, req, sub);
          });
        } else {
          const item = document.createElement('div');
          item.className = 'flows2-summary-item';
          const main = document.createElement('div');
          main.className = 'flows2-summary-item__main';
          const row = document.createElement('div');
          row.className = 'flows2-summary-item__row';
          const titleEl = document.createElement('div');
          titleEl.className = 'flows2-summary-item__title';
          titleEl.textContent = 'No custom prompts configured.';
          row.appendChild(titleEl);
          main.appendChild(row);
          const subEl = document.createElement('div');
          subEl.className = 'flows2-summary-item__sub';
          subEl.textContent = 'Add prompts to capture operator inputs during execution.';
          main.appendChild(subEl);
          item.appendChild(main);
          list.appendChild(item);
        }
        sec.appendChild(t);
        sec.appendChild(list);
        bodyInner.appendChild(sec);
      }

      appendInputsSection();
      appendOutputsSection();
      appendTraceabilitySection();
      appendPromptsSection();

      if (hasDocs) {
        const sec = document.createElement('div');
        sec.className = 'flows2-section';
        const pt = document.createElement('p');
        pt.className = 'flows2-section__title';
        pt.textContent = 'Documentation';
        const pre = document.createElement('pre');
        pre.style.cssText = 'margin:0; padding: 10px 0; overflow:auto; max-height: 240px;';
        try {
          pre.textContent = JSON.stringify(docsObj, null, 2);
        } catch (e) {
          pre.textContent = String(docsObj);
        }
        sec.appendChild(pt);
        sec.appendChild(pre);
        bodyInner.appendChild(sec);
      }

      if (hasConfigs) {
        const sec = document.createElement('div');
        sec.className = 'flows2-section';
        const pt = document.createElement('p');
        pt.className = 'flows2-section__title';
        pt.textContent = 'Advanced settings';
        const pre = document.createElement('pre');
        pre.style.cssText = 'margin:0; padding: 10px 0; overflow:auto; max-height: 240px;';
        try {
          pre.textContent = JSON.stringify(cfgObj, null, 2);
        } catch (e) {
          pre.textContent = String(cfgObj);
        }
        sec.appendChild(pt);
        sec.appendChild(pre);
        bodyInner.appendChild(sec);
      }

      body.appendChild(bodyInner);
      card.appendChild(body);

      return card;
    }
    
    // Step expand/collapse (global function for onclick)
    window.toggleStep = function(header) {
      const stepCard = header.closest('.step-card');
      if (!stepCard) return;
      const expanded = stepCard.getAttribute('data-expanded') === 'true';
      stepCard.setAttribute('data-expanded', expanded ? 'false' : 'true');
    };
    
    // Execution expand/collapse (global function for onclick)
    window.toggleExecution = function(header) {
      const executionCard = header.closest('.execution-card');
      const content = executionCard.querySelector('.execution-content');
      const toggle = executionCard.querySelector('.execution-toggle');
      
      if (content.style.display === 'none') {
        content.style.display = 'block';
        toggle.style.transform = 'rotate(180deg)';
      } else {
        content.style.display = 'none';
        toggle.style.transform = 'rotate(0deg)';
      }
    };
    
    window.toggleIOPane = function(paneId, event) {
      // Stop event propagation to prevent any bubbling issues
      if (event) {
        event.stopPropagation();
      }
      
      const pane = document.getElementById(paneId);
      const toggle = document.getElementById(`${paneId}-toggle`);
      
      if (pane && toggle) {
        const isHidden = pane.style.display === 'none' || !pane.style.display;
        
        // Find the flex container that holds both input and output panes for this step
        // Start from the pane's parent (the pane wrapper div) and traverse up
        let currentElement = pane.parentElement; // The div containing the pane
        let stepContainer = null;
        
        // Look for the flex container (has display: flex)
        while (currentElement && currentElement !== document.body) {
          const computedStyle = window.getComputedStyle(currentElement);
          if (computedStyle.display === 'flex' && currentElement.querySelectorAll('.io-pane-content').length >= 1) {
            stepContainer = currentElement;
            break;
          }
          currentElement = currentElement.parentElement;
        }
        
        if (stepContainer) {
          // Get all IO panes and toggles in this specific step's flex container
          const stepIOPanes = stepContainer.querySelectorAll('.io-pane-content');
          const stepIOToggles = stepContainer.querySelectorAll('.io-pane-toggle');
          
          if (isHidden) {
            // Expand all IO panes in this step (both inputs and outputs)
            stepIOPanes.forEach(p => {
              p.style.display = 'block';
            });
            stepIOToggles.forEach(t => {
              t.style.transform = 'rotate(180deg)';
            });
          } else {
            // Collapse all IO panes in this step
            stepIOPanes.forEach(p => {
              p.style.display = 'none';
            });
            stepIOToggles.forEach(t => {
              t.style.transform = 'rotate(0deg)';
            });
          }
        } else {
          // Fallback to single pane toggle if container not found
          if (isHidden) {
            pane.style.display = 'block';
            toggle.style.transform = 'rotate(180deg)';
          } else {
            pane.style.display = 'none';
            toggle.style.transform = 'rotate(0deg)';
          }
        }
      }
    };
    
    window.toggleCompletedSteps = function(sectionId) {
      const section = document.getElementById(sectionId);
      const toggle = document.getElementById(`${sectionId}-toggle`);
      
      if (section && toggle) {
        const isHidden = section.style.display === 'none' || !section.style.display;
        if (isHidden) {
          section.style.display = 'block';
          toggle.style.transform = 'rotate(180deg)';
        } else {
          section.style.display = 'none';
          toggle.style.transform = 'rotate(0deg)';
        }
      }
    };
    
    // ============================================================
    // GET PREVIOUS STEP OUTPUTS
    // ============================================================
    function getPreviousStepOutputs(currentStepCard) {
      const allStepCards = document.querySelectorAll('.step-card');
      const currentStepNumber = parseInt(currentStepCard.querySelector('.step-number')?.textContent || '0');
      
      if (currentStepNumber <= 1) {
        return []; // No previous steps
      }
      
      const previousOutputs = [];
      
      // Get outputs from all previous steps, ordered by step number (descending - most recent first)
      for (let i = currentStepNumber - 1; i >= 1; i--) {
        const stepCard = Array.from(allStepCards).find(card => {
          const stepNum = parseInt(card.querySelector('.step-number')?.textContent || '0');
          return stepNum === i;
        });
        
        if (stepCard) {
          // Find the Outputs section specifically (not the last section, since we now have execution prompts)
          // Look for the io-section that contains "Outputs" in its title
          const allIOSections = stepCard.querySelectorAll('.io-section');
          let outputsSection = null;
          
          // Find the section with "Outputs" in the title
          for (const section of allIOSections) {
            const title = section.querySelector('.io-section-title');
            if (title && title.textContent.includes('Outputs')) {
              outputsSection = section;
              break;
            }
          }
          
          // Fallback: if we can't find by title, use the second section (index 1) which should be outputs
          if (!outputsSection && allIOSections.length > 1) {
            outputsSection = allIOSections[1];
          }
          
          if (outputsSection) {
            const outputItems = outputsSection.querySelectorAll('.io-item');
            
            outputItems.forEach(item => {
              const name = item.querySelector('.io-name-input')?.value?.trim();
              const quantity = item.querySelector('.io-quantity-input')?.value;
              const unit = item.querySelector('.io-unit-input')?.value;
              
              if (name) {
                previousOutputs.push({
                  name: name,
                  quantity: quantity ? parseFloat(quantity) : null,
                  unit: unit || '',
                  step_number: i
                });
              }
            });
          }
        }
      }
      
      return previousOutputs;
    }
    
    // ============================================================
    // UPDATE "FROM OUTPUT" BUTTON VISIBILITY
    // ============================================================
    function updateFromOutputButtonVisibility() {
      const allStepCards = document.querySelectorAll('.step-card');
      allStepCards.forEach(stepCard => {
        const fromOutputBtn = stepCard.querySelector('[data-add-from-output-btn]');
        if (fromOutputBtn) {
          const stepNumberEl = stepCard.querySelector('.step-number');
          const stepNumberText = stepNumberEl?.textContent?.trim() || '';
          const stepNumber = stepNumberText ? parseInt(stepNumberText) : 0;
          // Show button for step 2 and onwards
          fromOutputBtn.style.display = stepNumber >= 2 ? 'inline-block' : 'none';
        }
      });
    }
    
    function updateStepMeta(stepCard) {
      if (!stepCard) return;
      
      const inputs = stepCard.querySelectorAll('.io-section:first-of-type .io-item').length;
      const outputs = stepCard.querySelectorAll('.io-section:last-of-type .io-item').length;
      
      const stepMeta = stepCard.querySelector('.flows2-step__meta');
      if (stepMeta) {
        stepMeta.textContent = '';
        const sIn = document.createElement('span');
        sIn.textContent = `${inputs} input${inputs !== 1 ? 's' : ''}`;
        const sOut = document.createElement('span');
        sOut.textContent = `${outputs} output${outputs !== 1 ? 's' : ''}`;
        stepMeta.appendChild(sIn);
        stepMeta.appendChild(sOut);
      }
    }
    
    // ============================================================
    // DRAG AND DROP FOR STEP REORDERING
    // ============================================================
    let draggedStepCard = null;
    let draggedStepIndex = -1;
    
    function initializeStepDragAndDrop() {
      const container = document.getElementById('steps-container');
      if (!container) return;
      
      const stepCards = container.querySelectorAll('.step-card');
      
      stepCards.forEach((card, index) => {
        const dragHandle = card.querySelector('.step-drag-handle');
        if (!dragHandle) return;
        
        // Make the entire card draggable via the handle
        dragHandle.addEventListener('dragstart', (e) => {
          draggedStepCard = card;
          draggedStepIndex = index;
          card.style.opacity = '0.5';
          dragHandle.style.cursor = 'grabbing';
          e.dataTransfer.effectAllowed = 'move';
          // Some browsers require setData for drag to proceed; reorder uses `draggedStepCard`, not this payload.
          const stepId = card.getAttribute('data-step-id') || '';
          e.dataTransfer.setData('text/plain', 'flows2-step:' + stepId);
        });
        
        dragHandle.addEventListener('dragend', (e) => {
          card.style.opacity = '1';
          dragHandle.style.cursor = 'grab';
          // Remove any drag-over styling from all cards
          stepCards.forEach(c => {
            c.classList.remove('drag-over');
            c.style.borderTop = '';
            c.style.borderBottom = '';
          });
          draggedStepCard = null;
          draggedStepIndex = -1;
        });
        
        // Make the card a drop target
        card.addEventListener('dragover', (e) => {
          if (draggedStepCard && draggedStepCard !== card) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            
            // Visual feedback: highlight the drop zone
            const rect = card.getBoundingClientRect();
            const midpoint = rect.top + rect.height / 2;
            const mouseY = e.clientY;
            
            // Remove previous styling
            stepCards.forEach(c => {
              c.classList.remove('drag-over');
              c.style.borderTop = '';
              c.style.borderBottom = '';
            });
            
            // Add border above or below based on mouse position
            if (mouseY < midpoint) {
              card.style.borderTop = '3px solid var(--primary, #3b82f6)';
            } else {
              card.style.borderBottom = '3px solid var(--primary, #3b82f6)';
            }
          }
        });
        
        card.addEventListener('dragleave', (e) => {
          // Only remove styling if we're actually leaving the card
          if (!card.contains(e.relatedTarget)) {
            card.style.borderTop = '';
            card.style.borderBottom = '';
          }
        });
        
        card.addEventListener('drop', async (e) => {
          e.preventDefault();
          e.stopPropagation();
          
          if (!draggedStepCard || draggedStepCard === card) {
            return;
          }
          
          // Remove all drag styling
          stepCards.forEach(c => {
            c.style.borderTop = '';
            c.style.borderBottom = '';
            c.classList.remove('drag-over');
          });
          
          // Get the new index
          const allCards = Array.from(container.querySelectorAll('.step-card'));
          const dropIndex = allCards.indexOf(card);
          
          // Determine if we're inserting before or after
          const rect = card.getBoundingClientRect();
          const midpoint = rect.top + rect.height / 2;
          const mouseY = e.clientY;
          const insertBefore = mouseY < midpoint;
          
          // Move the dragged card to the new position
          if (insertBefore) {
            container.insertBefore(draggedStepCard, card);
          } else {
            // Insert after the target card
            const nextSibling = card.nextSibling;
            if (nextSibling) {
              container.insertBefore(draggedStepCard, nextSibling);
            } else {
              container.appendChild(draggedStepCard);
            }
          }
          
          // Update step numbers and save to database
          await updateStepOrder();
        });
      });
    }
    
    // Update step order after drag and drop
    async function updateStepOrder() {
      const container = document.getElementById('steps-container');
      if (!container || !processId) return;
      
      const stepCards = container.querySelectorAll('.step-card');
      const orderedIds = [];
      
      stepCards.forEach((card, index) => {
        const stepId = card.getAttribute('data-step-id');
        const newStepNumber = index + 1;
        
        // Update the visual step number
        const stepNumberEl = card.querySelector('.step-number');
        if (stepNumberEl) {
          stepNumberEl.textContent = newStepNumber;
        }
        
        // Only include persisted steps for reorder endpoint
        if (stepId && !stepId.startsWith('step-new-') && !stepId.startsWith('temp-step-')) {
          orderedIds.push(stepId);
        }
      });
      
      // Save order to backend (atomic reorder endpoint)
      if (orderedIds.length > 0) {
        try {
          const csrfMeta = document.querySelector('meta[name="csrf-token"]');
          const csrfTok = csrfMeta && csrfMeta.getAttribute('content');
          const headers = { 'Content-Type': 'application/json' };
          if (csrfTok) {
            headers['X-CSRFToken'] = csrfTok;
            headers['X-CSRF-Token'] = csrfTok;
          }
          const spacing = 1000;
          const orders = orderedIds.map((id, idx) => ({ id, position: spacing * (idx + 1) }));
          const res = await fetch(`/api/core/processes/${encodeURIComponent(processId)}/steps/reorder`, {
            method: 'POST',
            credentials: 'include',
            headers,
            body: JSON.stringify({ orders })
          });
          if (!res.ok) throw new Error('Failed to reorder');
          
          showNotification('success', 'Steps Reordered', 'Step order has been saved successfully.');
        } catch (error) {
          console.error('Failed to update step order:', error);
          showNotification('error', 'Error', 'Failed to save step order. Please try again.');
          // Reload steps to restore original order
          await loadProcessData();
        }
      }
    }
    
    // ============================================================
    // SAVE STEP
    // ============================================================
    window.saveStep = async function(stepCard) {
      if (!stepCard || !processId) {
        showNotification('error', 'Error', 'Cannot save step: Process ID is missing');
        return;
      }
      
      const stepId = stepCard.getAttribute('data-step-id');
      const stepNameInput = stepCard.querySelector('.step-name-input');
      const stepDescriptionInput = stepCard.querySelector('.step-description-input');
      
      if (!stepNameInput || !stepNameInput.value.trim()) {
        showNotification('error', 'Validation Error', 'Please enter a step name');
        return;
      }
      
      const stepName = stepNameInput.value.trim();
      const stepDescription = stepDescriptionInput ? stepDescriptionInput.value.trim() : '';
      
      // Collect inputs and outputs - find all io-sections once
      const allIOSections = stepCard.querySelectorAll('.io-section');
      
      // Get inputs from the first io-section
      let inputItems = [];
      if (allIOSections.length > 0) {
        const firstIOSection = allIOSections[0];
        inputItems = firstIOSection.querySelectorAll('.io-item');
      }
      
      const inputs = [];
      inputItems.forEach(item => {
        // Check for dropdown input value first (what user sees/types), then hidden input, then regular input
        const dropdownInput = item.querySelector('.searchable-dropdown-input');
        const hiddenInput = item.querySelector('.io-name-input-hidden');
        const regularInput = item.querySelector('.io-name-input:not(.searchable-dropdown-input)');
        
        // Get the name - prioritize visible dropdown input, then hidden input, then regular input
        // Always read from dropdown input first since that's what the user sees and types in
        let name = '';
        if (dropdownInput) {
          name = dropdownInput.value?.trim() || '';
          // Sync hidden input with dropdown input value
          if (hiddenInput && name) {
            hiddenInput.value = name;
          }
        }
        
        // Fallback to hidden input if dropdown is empty
        if (!name && hiddenInput && hiddenInput.value) {
          name = hiddenInput.value.trim();
        }
        
        // Fallback to regular input if both are empty
        if (!name && regularInput && regularInput.value) {
          name = regularInput.value.trim();
        }
        
        const quantity = item.querySelector('.io-quantity-input')?.value;
        const unit = item.querySelector('.io-unit-input')?.value;
        const typeSelect = item.querySelector('.io-type-input');
        const typeValue = typeSelect ? typeSelect.value : 'confirm';
        // Determine flags based on type:
        // - "confirm" = Confirm at execution (editable quantity/unit, no inventory selection)
        // - "variable" = Select inventory at execution (inventory selection required)
        // - "static" = Static (no prompts)
        const isConfirm = typeValue === 'confirm';
        const isVariable = typeValue === 'variable';
        const isStatic = typeValue === 'static';
        
        if (name) {
          inputs.push({
            name: name,
            quantity: quantity ? parseFloat(quantity) : null,
            unit: unit || '',
            is_variable: isConfirm || isVariable, // Both confirm and variable are "variable" (not static)
            requires_inventory_selection: isVariable // Only inventory selection requires inventory
          });
        }
      });
      
      // Get outputs from the second io-section (outputs section)
      let outputItems = [];
      if (allIOSections.length > 1) {
        const outputsSection = allIOSections[1];
        outputItems = outputsSection.querySelectorAll('.io-item');
      }
      
      const outputs = [];
      outputItems.forEach(item => {
        const name = item.querySelector('.io-name-input')?.value?.trim();
        const quantity = item.querySelector('.io-quantity-input')?.value;
        const unit = item.querySelector('.io-unit-input')?.value;
        const typeSelect = item.querySelector('.io-type-input');
        const isVariable = typeSelect ? typeSelect.value === 'variable' : true;
        
        if (name) {
          outputs.push({
            name: name,
            quantity: quantity ? parseFloat(quantity) : null,
            unit: unit || '',
            is_variable: isVariable, // Keep for backward compatibility
            requires_execution_confirmation: isVariable
          });
        }
      });
      
      // Get execution prompts from the third io-section (execution prompts section)
      let promptItems = [];
      if (allIOSections.length > 2) {
        const promptsSection = allIOSections[2];
        promptItems = promptsSection.querySelectorAll('.io-item');
      }
      
      const executionPrompts = [];
      promptItems.forEach(item => {
        const label = item.querySelector('.prompt-label-input')?.value?.trim();
        const type = item.querySelector('.prompt-type-input')?.value || 'text';
        const unit = item.querySelector('.prompt-unit-input')?.value?.trim() || null;
        const requiredSelect = item.querySelector('.prompt-required-input');
        const required = requiredSelect ? requiredSelect.value === 'true' : true;
        
        if (label) {
          executionPrompts.push({
            label: label,
            type: type,
            unit: unit,
            required: required
          });
        }
      });
      
      // Get step number
      const stepNumberEl = stepCard.querySelector('.step-number');
      const stepNumber = stepNumberEl ? parseInt(stepNumberEl.textContent) || 1 : 1;
      
      try {
        let result;
        const stepData = {
          step_number: stepNumber,
          name: stepName,
          description: stepDescription,
          inputs: inputs || [],
          outputs: outputs || [],
          execution_prompts: executionPrompts || []
        };
        
        if (stepId && stepId.startsWith('step-new-')) {
          // This is a new step, create it
          result = await CoreAPI.createStep(processId, stepData);
          
          // Update the step card with the real ID
          stepCard.setAttribute('data-step-id', result.id);
        } else {
          // This is an existing step, update it
          result = await CoreAPI.updateStep(processId, stepId, stepData);
        }
        
        // Update the step header with saved data
        const stepNameEl = stepCard.querySelector('.step-name');
        const stepDescriptionEl = stepCard.querySelector('.step-description');
        if (stepNameEl) stepNameEl.textContent = stepName;
        if (stepDescriptionEl) stepDescriptionEl.textContent = stepDescription;
        
        showNotification('success', 'Step Saved', `Step "${stepName}" has been saved successfully.`);
        
        // Reload process data to get updated step list
        await loadProcessData();
        
        // Update button visibility after reload (with a small delay to ensure DOM is updated)
        setTimeout(() => updateFromOutputButtonVisibility(), 100);
        
        // Update button visibility after reload
        updateFromOutputButtonVisibility();
        
      } catch (error) {
        console.error('Failed to save step:', error);
        showNotification('error', 'Failed to Save Step', error.message || 'Failed to save step. Please try again.');
      }
    };
    
    // ============================================================
    // DELETE STEP
    // ============================================================
    window.deleteStep = async function(stepCard) {
      if (!stepCard || !processId) {
        showNotification('error', 'Error', 'Cannot delete step: Process ID is missing');
        return;
      }
      
      const stepId = stepCard.getAttribute('data-step-id');
      const stepName = stepCard.querySelector('.step-name')?.textContent || 'this step';
      
      // Check if this is a new step (not saved yet)
      if (!stepId || stepId.startsWith('step-new-')) {
        // Just remove from DOM
        if (confirm(`Are you sure you want to delete "${stepName}"?`)) {
          stepCard.remove();
          updateStepCount();
        }
        return;
      }
      
      // Confirm deletion
      if (!confirm(`Are you sure you want to delete "${stepName}"? This action cannot be undone.`)) {
        return;
      }
      
      try {
        await CoreAPI.deleteStep(processId, stepId);
        
        // Remove from DOM
        stepCard.remove();
        updateStepCount();
        
        showNotification('success', 'Step Deleted', `Step "${stepName}" has been deleted successfully.`);
        
        // Reload process data
        await loadProcessData();
        
      } catch (error) {
        console.error('Failed to delete step:', error);
        showNotification('error', 'Failed to Delete Step', error.message || 'Failed to delete step. Please try again.');
      }
    };
    
    function updateStepCount() {
      const stepsContainer = document.getElementById('steps-container');
      const stepCountText = document.getElementById('step-count-text');
      if (stepCountText && stepsContainer) {
        const totalSteps = stepsContainer.querySelectorAll('.step-card').length;
        if (totalSteps === 0) {
          // Don't update the innerHTML here as it might clear content unnecessarily
          // The empty state will be handled by renderSteps
          stepCountText.textContent = '0 steps in this process';
        } else {
          stepCountText.textContent = `${totalSteps} step${totalSteps !== 1 ? 's' : ''} in this process`;
        }
      }
    }
    
