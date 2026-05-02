    (function () {
      function setActive(target) {
        var buttons = Array.prototype.slice.call(document.querySelectorAll('[data-flows2-target]'));
        var ids = ['structure', 'batches', 'inventory'];
        ids.forEach(function (k) {
          var p = document.getElementById('flows2-panel-' + k);
          if (!p) return;
          p.setAttribute('data-active', k === target ? 'true' : 'false');
        });
        buttons.forEach(function (b) {
          var isActive = b.getAttribute('data-flows2-target') === target;
          b.classList.toggle('flow-mode-segment--active', isActive);
          b.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });
      }

      function onClick(e) {
        var btn = e.target && e.target.closest ? e.target.closest('[data-flows2-target]') : null;
        if (!btn) return;
        e.preventDefault();
        var target = btn.getAttribute('data-flows2-target');
        if (!target) return;
        setActive(target);
      }

      function bind() {
        if (document._flows2TabsBound) return;
        document._flows2TabsBound = true;
        document.addEventListener('click', onClick);
      }

      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
      else bind();
      window.setFlows2ActivePanel = setActive;
    })();

    // Inventory sub-tabs (Raw / Intermediate / Final) — uses flows2RerenderInventory after load
    (function () {
      function setInvFilter(type) {
        flows2Inventory.filter = type || 'raw_material';
        var buttons = document.querySelectorAll('[data-flows2-inv-type]');
        buttons.forEach(function (b) {
          var t = b.getAttribute('data-flows2-inv-type');
          var active = t === flows2Inventory.filter;
          b.classList.toggle('flow-mode-segment--active', active);
          b.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        if (typeof flows2RerenderInventory === 'function') flows2RerenderInventory();
      }
      function onClick(e) {
        var btn = e.target && e.target.closest ? e.target.closest('[data-flows2-inv-type]') : null;
        if (!btn) return;
        e.preventDefault();
        var type = btn.getAttribute('data-flows2-inv-type');
        if (!type) return;
        setInvFilter(type);
      }
      if (!document._flows2InvTabsBound) {
        document._flows2InvTabsBound = true;
        document.addEventListener('click', onClick);
      }
    })();

    // Manage menu (sticky bar)
    (function () {
      function getEls() {
        return {
          btn: document.getElementById('flows2-manage-btn'),
          menu: document.getElementById('flows2-manage-menu'),
          backdrop: document.getElementById('flows2-manage-backdrop'),
          del: document.getElementById('flows2-manage-delete'),
          edit: document.getElementById('flows2-manage-edit'),
          draft: document.getElementById('flows2-manage-draft'),
        };
      }

      function syncDraftMenuLabel() {
        var els = getEls();
        if (!els.draft) return;
        // currentProcess is a page-level variable populated by loadProcessData()
        var isDraft = !!(typeof currentProcess !== 'undefined' && currentProcess && currentProcess.is_draft);
        els.draft.textContent = isDraft ? 'Set workflow to ready' : 'Set workflow to draft';
      }

      function openMenu() {
        var els = getEls();
        if (!els.btn || !els.menu) return;
        syncDraftMenuLabel();
        els.menu.setAttribute('data-open', 'true');
        if (els.backdrop) els.backdrop.setAttribute('data-open', 'true');
        els.btn.setAttribute('aria-expanded', 'true');
      }
      function closeMenu() {
        var els = getEls();
        if (!els.btn || !els.menu) return;
        els.menu.setAttribute('data-open', 'false');
        if (els.backdrop) els.backdrop.setAttribute('data-open', 'false');
        els.btn.setAttribute('aria-expanded', 'false');
      }
      function isOpen() {
        var els = getEls();
        return !!(els.menu && els.menu.getAttribute('data-open') === 'true');
      }

      // Document-level listeners: bind once — handlers use getEls() at call time so work with new DOM
      if (!document._flows2ManageMenuBound) {
        document._flows2ManageMenuBound = true;
        document.addEventListener('pointerdown', function (e) {
          if (!isOpen()) return;
          var els = getEls();
          if (!els.btn || !els.menu) return;
          var t = e.target;
          if (t === els.btn || (els.btn.contains && els.btn.contains(t))) return;
          if (els.menu.contains && els.menu.contains(t)) return;
          closeMenu();
          e.preventDefault();
          e.stopPropagation();
        }, true);
        document.addEventListener('click', function (e) {
          var els = getEls();
          if (!els.btn || !els.menu) return;
          var t = e.target;
          if (t === els.btn || (els.btn.contains && els.btn.contains(t))) {
            if (isOpen()) closeMenu(); else openMenu();
            return;
          }
          if (els.menu.contains && els.menu.contains(t)) return;
          if (isOpen()) closeMenu();
        });
        document.addEventListener('keydown', function (e) {
          if (e.key === 'Escape' && isOpen()) closeMenu();
        });
      }

      var els = getEls();
      if (els.del) {
        els.del.addEventListener('click', function (e) {
          e.preventDefault();
          closeMenu();
          if (typeof showFlows2DeleteProcessModal === 'function') showFlows2DeleteProcessModal();
        });
      }
      if (els.edit) {
        els.edit.addEventListener('click', function (e) {
          e.preventDefault();
          closeMenu();
          if (!processId) return;
          window.location.href = '/core/flows/create/next-steps?id=' + encodeURIComponent(processId);
        });
      }
      if (els.draft) {
        els.draft.addEventListener('click', async function (e) {
          e.preventDefault();
          closeMenu();
          if (!processId) return;
          try {
            var nextIsDraft = !(typeof currentProcess !== 'undefined' && currentProcess && currentProcess.is_draft);
            await CoreAPI.updateProcess(processId, { is_draft: nextIsDraft });
            if (typeof loadProcessData === 'function') await loadProcessData();
            syncDraftMenuLabel();
          } catch (err) {
            console.error(err);
          }
        });
      }
    })();
    var notificationTimeout = null;

    function flows2SvgNotificationSuccess24() {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '24');
      svg.setAttribute('height', '24');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '2');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
      const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      p.setAttribute('d', 'M22 11.08V12a10 10 0 1 1-5.93-9.14');
      const pl = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      pl.setAttribute('points', '22 4 12 14.01 9 11.01');
      svg.appendChild(p);
      svg.appendChild(pl);
      return svg;
    }

    function flows2SvgNotificationError24() {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '24');
      svg.setAttribute('height', '24');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '2');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
      const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      c.setAttribute('cx', '12');
      c.setAttribute('cy', '12');
      c.setAttribute('r', '10');
      const l1 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      l1.setAttribute('x1', '12');
      l1.setAttribute('y1', '8');
      l1.setAttribute('x2', '12');
      l1.setAttribute('y2', '12');
      const l2 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      l2.setAttribute('x1', '12');
      l2.setAttribute('y1', '16');
      l2.setAttribute('x2', '12.01');
      l2.setAttribute('y2', '16');
      svg.appendChild(c);
      svg.appendChild(l1);
      svg.appendChild(l2);
      return svg;
    }
    
    // Define showNotification FIRST so overrides can use it immediately
    // Auto-dismissing toast notification
    window.showNotification = function(type, title, message) {
      const modal = document.getElementById('notification-modal');
      if (!modal) return;
      
      // Clear any existing timeout
      if (notificationTimeout) {
        clearTimeout(notificationTimeout);
        notificationTimeout = null;
      }
      
      const titleEl = document.getElementById('notification-title');
      const messageEl = document.getElementById('notification-message');
      const iconEl = document.getElementById('notification-icon');
      
      if (titleEl) titleEl.textContent = title;
      if (messageEl) messageEl.textContent = message;
      
      // Set icon and colors based on type
      if (type === 'success' && iconEl) {
        iconEl.replaceChildren(flows2SvgNotificationSuccess24());
        iconEl.style.color = 'var(--success, #10b981)';
      } else if (type === 'error' && iconEl) {
        iconEl.replaceChildren(flows2SvgNotificationError24());
        iconEl.style.color = 'var(--error, #ef4444)';
      }
      
      // Show notification
      modal.style.display = 'flex';
      
      // Auto-dismiss: errors stay longer (8 seconds), success messages (6 seconds)
      const timeoutDuration = type === 'error' ? 8000 : 6000;
      notificationTimeout = setTimeout(() => {
        closeNotification();
      }, timeoutDuration);
    };
    
    // Immediately override showSuccess and showError from core.js
    window.showSuccess = function(message) {
      window.showNotification('success', 'Success', message);
    };
    
    window.showError = function(message) {
      window.showNotification('error', 'Error', message);
    };
    
    function closeNotification() {
      const modal = document.getElementById('notification-modal');
      if (modal) {
        modal.style.display = 'none';
      }
      if (notificationTimeout) {
        clearTimeout(notificationTimeout);
        notificationTimeout = null;
      }
    }
    
    // Show custom modal for static input warning
    window.showStaticInputWarningModal = function(callback) {
      // Create modal if it doesn't exist
      let modal = document.getElementById('static-input-warning-modal');
      if (!modal) {
        modal = document.createElement('div');
        modal.id = 'static-input-warning-modal';
        modal.className = 'modal-overlay';
        modal.style.cssText = 'display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0, 0, 0, 0.7); backdrop-filter: blur(8px); z-index: 1000; align-items: center; justify-content: center;';
        const shell = document.createElement('div');
        shell.className = 'modal-content';
        shell.style.cssText =
          'background: var(--bg-card, #ffffff); border-radius: var(--radius-lg, 12px); padding: 24px; max-width: 500px; width: 90%; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);';
        const headerRow = document.createElement('div');
        headerRow.style.cssText = 'display: flex; align-items: center; gap: 12px; margin-bottom: 20px;';
        const iconWrap = document.createElement('div');
        iconWrap.style.cssText =
          'flex-shrink: 0; width: 40px; height: 40px; border-radius: 50%; background: var(--warning-bg, #fef3c7); display: flex; align-items: center; justify-content: center;';
        const warnSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        warnSvg.setAttribute('width', '24');
        warnSvg.setAttribute('height', '24');
        warnSvg.setAttribute('viewBox', '0 0 24 24');
        warnSvg.setAttribute('fill', 'none');
        warnSvg.setAttribute('stroke', 'currentColor');
        warnSvg.setAttribute('stroke-width', '2');
        warnSvg.setAttribute('stroke-linecap', 'round');
        warnSvg.setAttribute('stroke-linejoin', 'round');
        warnSvg.style.color = 'var(--warning, #f59e0b)';
        const wPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        wPath.setAttribute('d', 'M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z');
        const wL1 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        wL1.setAttribute('x1', '12');
        wL1.setAttribute('y1', '9');
        wL1.setAttribute('x2', '12');
        wL1.setAttribute('y2', '13');
        const wL2 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        wL2.setAttribute('x1', '12');
        wL2.setAttribute('y1', '17');
        wL2.setAttribute('x2', '12.01');
        wL2.setAttribute('y2', '17');
        warnSvg.appendChild(wPath);
        warnSvg.appendChild(wL1);
        warnSvg.appendChild(wL2);
        iconWrap.appendChild(warnSvg);
        const h2 = document.createElement('h2');
        h2.style.cssText = 'font-size: 20px; font-weight: 600; color: var(--text-primary); margin: 0;';
        h2.textContent = 'Changing to Static Input';
        headerRow.appendChild(iconWrap);
        headerRow.appendChild(h2);
        const bodyBlock = document.createElement('div');
        bodyBlock.style.marginBottom = '24px';
        const p1 = document.createElement('p');
        p1.style.cssText = 'font-size: 14px; color: var(--text-primary); margin: 0 0 16px 0; line-height: 1.6;';
        p1.textContent =
          'Outputs from previous steps are stored in inventory, which allows the system to:';
        const ul = document.createElement('ul');
        ul.style.cssText = 'font-size: 14px; color: var(--text-primary); margin: 0 0 16px 0; padding-left: 20px; line-height: 1.8;';
        ['Track live stock levels dynamically', 'Update inventory automatically when steps complete', 'See which physical items are being used'].forEach(
          (t) => {
            const li = document.createElement('li');
            li.textContent = t;
            ul.appendChild(li);
          }
        );
        const p2 = document.createElement('p');
        p2.style.cssText = 'font-size: 14px; color: var(--text-primary); margin: 0; line-height: 1.6; font-weight: 500;';
        p2.textContent = 'Using "Select inventory at execution" is recommended for outputs.';
        bodyBlock.appendChild(p1);
        bodyBlock.appendChild(ul);
        bodyBlock.appendChild(p2);
        const footer = document.createElement('div');
        footer.style.cssText = 'display: flex; gap: 12px; justify-content: flex-end;';
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn btn-secondary';
        cancelBtn.id = 'static-warning-cancel';
        cancelBtn.style.padding = '10px 20px';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', function() {
          modal.style.display = 'none';
          document.body.style.overflow = 'auto';
          if (callback) callback(false);
        });
        const contBtn = document.createElement('button');
        contBtn.type = 'button';
        contBtn.className = 'btn btn-primary';
        contBtn.id = 'static-warning-continue';
        contBtn.style.cssText = 'padding: 10px 20px; background: var(--warning, #f59e0b); border-color: var(--warning, #f59e0b);';
        contBtn.textContent = 'Continue with Static';
        contBtn.addEventListener('click', function() {
          modal.style.display = 'none';
          document.body.style.overflow = 'auto';
          if (callback) callback(true);
        });
        footer.appendChild(cancelBtn);
        footer.appendChild(contBtn);
        shell.appendChild(headerRow);
        shell.appendChild(bodyBlock);
        shell.appendChild(footer);
        modal.appendChild(shell);
        document.body.appendChild(modal);
      }
      
      // Show modal
      modal.style.display = 'flex';
      document.body.style.overflow = 'hidden';
    };
    
    // Initialize account info component
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function() {
        if (window.initAccountInfo) {
          window.initAccountInfo('account-info-container');
        }
      });
    } else {
      if (window.initAccountInfo) {
        window.initAccountInfo('account-info-container');
      }
    }
    // ============================================================
    // GET CURRENT USER
    // ============================================================
    async function getCurrentUser() {
      if (currentUser) {
        return currentUser;
      }
      
      try {
        const response = await fetch('/auth/me', {
          method: 'GET',
          credentials: 'include'
        });
        
        if (response.ok) {
          const data = await response.json();
          if (data.user) {
            currentUser = {
              email: data.user.email || 'Unknown',
              username: data.user.email || 'Unknown' // Use full email as username
            };
            return currentUser;
          }
        }
      } catch (error) {
        console.error('Failed to get current user:', error);
      }
      
      return { email: 'Unknown', username: 'Unknown' };
    }
    
    // Load process data
    async function loadProcessData() {
      if (!processId) {
        console.error('No process ID provided');
        return;
      }
      
      try {
        // Load process details
        const processData = await CoreAPI.getProcess(processId);
        currentProcess = processData;
        
        // Update process details in center pane
        document.getElementById('process-name').textContent = processData.name || 'Unnamed Process';
        document.getElementById('process-description').textContent = processData.description || 'No description';
        
        // Update stats
        document.getElementById('process-step-count').textContent = processData.steps?.length || 0;
        
        // Show draft status if applicable
        if (processData.is_draft) {
          // Add draft badge near process name or in header
          let draftBadge = document.getElementById('process-draft-badge');
          if (!draftBadge) {
            draftBadge = document.createElement('span');
            draftBadge.id = 'process-draft-badge';
            draftBadge.className = 'badge';
            draftBadge.style.cssText = 'background: var(--warning, #f59e0b); color: white; margin-left: 8px; font-size: 11px; padding: 4px 8px; border-radius: 4px;';
            draftBadge.textContent = 'DRAFT';
            const processNameEl = document.getElementById('process-name');
            if (processNameEl && processNameEl.parentNode) {
              processNameEl.parentNode.appendChild(draftBadge);
            }
          }
          draftBadge.style.display = 'inline-block';
        } else {
          const draftBadge = document.getElementById('process-draft-badge');
          if (draftBadge) {
            draftBadge.style.display = 'none';
          }
        }
        
        // Render steps
        renderSteps(processData.steps || []);
        
        // Load executions
        await loadExecutions();
        
        // Load inventory
        await loadInventory();
        
      } catch (error) {
        console.error('Failed to load process data:', error);
        document.getElementById('process-name').textContent = 'Error loading process';
        document.getElementById('process-description').textContent = error.message || 'Failed to load process details';
        showNotification('error', 'Failed to Load Process', error.message || 'Failed to load process details');
      }
    }
    window.loadProcessData = loadProcessData;

    if (!processId) {
      const manageBtn = document.getElementById('flows2-manage-btn');
      if (manageBtn) manageBtn.style.display = 'none';
    }

    function showFlows2DeleteProcessModal() {
      if (!processId) return;
      const nameEl = document.getElementById('process-name');
      const name = (nameEl && nameEl.textContent) ? nameEl.textContent.trim() : 'this workflow';
      const modal = document.getElementById('flows2-delete-process-modal');
      const msg = document.getElementById('flows2-delete-confirmation-message');
      if (msg) {
        msg.textContent = "Are you sure you want to delete workflow '" + name + "'? This action cannot be undone.";
      }
      if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
      }
    }

    async function confirmFlows2DeleteProcess() {
      if (!processId) return;
      try {
        await CoreAPI.deleteProcess(processId);
        flows2Navigate('/core/processes');
      } catch (e) {
        console.error(e);
        if (typeof showNotification === 'function') {
          showNotification('error', 'Failed to delete', e.message || 'Could not delete this product.');
        }
        cancelFlows2DeleteProcess();
      }
    }

    function cancelFlows2DeleteProcess() {
      const modal = document.getElementById('flows2-delete-process-modal');
      if (modal) modal.style.display = 'none';
      document.body.style.overflow = 'auto';
    }
    async function startExecution() {
      if (!processId) {
        showNotification('error', 'Error', 'No process ID available');
        return;
      }

      try {
        const processData = await CoreAPI.getProcess(processId);
        const steps = processData.steps || [];
        const stepDefinition = steps[0];
        if (!stepDefinition) {
          showNotification('error', 'Error', 'Process has no steps.');
          return;
        }
        const returnTo = processId ? (`/core/flows?id=${encodeURIComponent(processId)}`) : '/core/flows';
        const url =
          `/core/flows/batches/start?draft=1` +
          `&id=${encodeURIComponent(processId)}` +
          `&step_id=${encodeURIComponent(stepDefinition.id)}` +
          `&return_to=${encodeURIComponent(returnTo)}`;
        flows2Navigate(url);
      } catch (error) {
        console.error('Failed to open execution modal:', error);
        showNotification('error', 'Failed to Start Execution', error.message || 'Failed to open step. Please try again.');
      }
    }

    // HTMX-aware navigation: swaps #page-content without reloading sidebar/topbar.
    function flows2Navigate(url) {
      if (window.htmx) {
        history.pushState({}, '', url);
        htmx.ajax('GET', url, {
          target: '#page-content',
          swap: 'innerHTML',
          select: '#page-content',
        });
      } else {
        window.location.href = url;
      }
    }

    // startExecutionSpa removed: startExecution() routes to the dedicated execution-step screen.

    // Works on both initial page load (DOMContentLoaded not yet fired) and HTMX swap (DOM already ready)
    function flows2InitPage() {
      if (window.processId) {
        loadProcessData();
      } else {
        var nameEl = document.getElementById('process-name');
        var descEl = document.getElementById('process-description');
        if (nameEl) nameEl.textContent = 'No Process Selected';
        if (descEl) descEl.textContent = 'Please select a process from the Process Hub';
      }
    }
    window.flows2InitPage = flows2InitPage;

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', flows2InitPage);
    } else {
      flows2InitPage();
    }
