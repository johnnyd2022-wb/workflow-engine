// Supply Chain Platform - Main Application JavaScript

document.addEventListener('DOMContentLoaded', function() {
    initializeSidebar();
    initializeTabs();
    initializeSteps();
    initializeModals();
  });
  
  // Sidebar functionality
  function initializeSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const sidebarToggle = document.querySelector('.sidebar-toggle');
    const mainContent = document.querySelector('.main-content');
    
    if (sidebarToggle) {
      sidebarToggle.addEventListener('click', function() {
        sidebar.classList.toggle('collapsed');
        mainContent.classList.toggle('sidebar-collapsed');
        
        // Save preference
        localStorage.setItem('sidebar-collapsed', sidebar.classList.contains('collapsed'));
      });
      
      // Restore preference
      const isCollapsed = localStorage.getItem('sidebar-collapsed') === 'true';
      if (isCollapsed) {
        sidebar.classList.add('collapsed');
        mainContent.classList.add('sidebar-collapsed');
      }
    }
    
    // Mobile toggle
    const mobileToggle = document.querySelector('.mobile-menu-toggle');
    if (mobileToggle) {
      mobileToggle.addEventListener('click', function() {
        sidebar.classList.toggle('mobile-open');
      });
    }
  }
  
  // Tab functionality
  function initializeTabs() {
    const tabTriggers = document.querySelectorAll('.tab-trigger');
    
    tabTriggers.forEach(trigger => {
      trigger.addEventListener('click', function() {
        const tabGroup = this.closest('.tabs');
        const targetId = this.dataset.tab;
        
        // Update triggers
        tabGroup.querySelectorAll('.tab-trigger').forEach(t => t.classList.remove('active'));
        this.classList.add('active');
        
        // Update content
        tabGroup.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        document.getElementById(targetId).classList.add('active');
      });
    });
  }
  
  // Step accordion functionality
  function initializeSteps() {
    const stepHeaders = document.querySelectorAll('.step-header');
    
    stepHeaders.forEach(header => {
      header.addEventListener('click', function() {
        const stepCard = this.closest('.step-card');
        const content = stepCard.querySelector('.step-content');
        const toggle = this.querySelector('.step-toggle');
        
        content.classList.toggle('expanded');
        toggle.classList.toggle('expanded');
      });
    });
  }
  
  // Modal functionality
  function initializeModals() {
    // Open modal triggers
    document.querySelectorAll('[data-modal-open]').forEach(trigger => {
      trigger.addEventListener('click', function() {
        const modalId = this.dataset.modalOpen;
        const modal = document.getElementById(modalId);
        if (modal) {
          modal.classList.add('active');
        }
      });
    });
    
    // Close modal triggers
    document.querySelectorAll('[data-modal-close]').forEach(trigger => {
      trigger.addEventListener('click', function() {
        const modal = this.closest('.modal-overlay');
        if (modal) {
          modal.classList.remove('active');
        }
      });
    });
    
    // Close on overlay click
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
      overlay.addEventListener('click', function(e) {
        if (e.target === this) {
          this.classList.remove('active');
        }
      });
    });
    
    // Close on escape key
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.active').forEach(modal => {
          modal.classList.remove('active');
        });
      }
    });
  }
  
  // Process card click handler
  function navigateToProcess(processId) {
    window.location.href = `flows.html?id=${processId}`;
  }
  
  // Add new step
  function addNewStep() {
    const stepsContainer = document.querySelector('.steps-container');
    const stepCount = stepsContainer.querySelectorAll('.step-card').length + 1;
    
    const stepHtml = `
      <div class="step-card" data-step-id="new-${Date.now()}">
        <div class="step-header">
          <div class="step-number">${stepCount}</div>
          <div class="step-info">
            <div class="step-name">New Step</div>
            <div class="step-description">Click to edit step details</div>
          </div>
          <div class="step-meta">
            <span>0 inputs</span>
            <span>0 outputs</span>
          </div>
          <div class="step-toggle">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </div>
        </div>
        <div class="step-content">
          <div class="form-group">
            <label class="form-label">Step Name</label>
            <input type="text" class="form-input" placeholder="Enter step name" value="New Step">
          </div>
          <div class="form-group">
            <label class="form-label">Description</label>
            <input type="text" class="form-input" placeholder="Enter description">
          </div>
          <div class="io-section">
            <div class="io-section-title">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 5v14M5 12l7-7 7 7"/>
              </svg>
              Inputs
              <button class="btn btn-ghost btn-sm" onclick="addInput(this)">+ Add</button>
            </div>
            <div class="io-list"></div>
          </div>
          <div class="io-section">
            <div class="io-section-title">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 19V5M5 12l7 7 7-7"/>
              </svg>
              Outputs
              <button class="btn btn-ghost btn-sm" onclick="addOutput(this)">+ Add</button>
            </div>
            <div class="io-list"></div>
          </div>
        </div>
      </div>
    `;
    
    stepsContainer.insertAdjacentHTML('beforeend', stepHtml);
    
    // Reinitialize step handlers
    initializeSteps();
  }
  
  // Add input to step
  function addInput(button) {
    const ioList = button.closest('.io-section').querySelector('.io-list');
    const inputHtml = `
      <div class="io-item">
        <input type="text" class="form-input io-item-name" placeholder="Input name" style="flex: 1;">
        <input type="number" class="form-input io-item-quantity" placeholder="Qty" style="width: 80px;">
        <select class="form-select io-item-unit" style="width: 100px;">
          <option value="kg">kg</option>
          <option value="g">g</option>
          <option value="L">L</option>
          <option value="mL">mL</option>
          <option value="units">units</option>
          <option value="pcs">pcs</option>
          <option value="hr">hr</option>
          <option value="min">min</option>
        </select>
        <button class="btn btn-ghost btn-icon btn-sm" onclick="this.closest('.io-item').remove()">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>
    `;
    ioList.insertAdjacentHTML('beforeend', inputHtml);
  }
  
  // Add output to step
  function addOutput(button) {
    const ioList = button.closest('.io-section').querySelector('.io-list');
    const outputHtml = `
      <div class="io-item">
        <input type="text" class="form-input io-item-name" placeholder="Output name" style="flex: 1;">
        <input type="number" class="form-input io-item-quantity" placeholder="Qty" style="width: 80px;">
        <select class="form-select io-item-unit" style="width: 100px;">
          <option value="kg">kg</option>
          <option value="g">g</option>
          <option value="L">L</option>
          <option value="mL">mL</option>
          <option value="units">units</option>
          <option value="pcs">pcs</option>
          <option value="hr">hr</option>
          <option value="min">min</option>
        </select>
        <button class="btn btn-ghost btn-icon btn-sm" onclick="this.closest('.io-item').remove()">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>
    `;
    ioList.insertAdjacentHTML('beforeend', outputHtml);
  }
  
  // Add inventory item
  function addInventoryItem(form) {
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);
    
    console.log('Adding inventory item:', data);
    
    // In real app, this would send to backend
    // For now, just close modal and show success
    const modal = form.closest('.modal-overlay');
    if (modal) {
      modal.classList.remove('active');
    }
    
    // Show success message (you could add a toast notification here)
    alert('Inventory item added successfully!');
    
    form.reset();
    return false; // Prevent form submission
  }
  
  // Create new process
  function createNewProcess(form) {
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);
    
    console.log('Creating new process:', data);
    
    // In real app, this would send to backend
    const modal = form.closest('.modal-overlay');
    if (modal) {
      modal.classList.remove('active');
    }
    
    alert('Process created successfully!');
    
    form.reset();
    return false;
  }
  
  // Execute next step in an execution
  function executeStep(executionId) {
    const executionCard = document.querySelector(`[data-execution-id="${executionId}"]`);
    if (!executionCard) return;
    
    const currentStep = parseInt(executionCard.dataset.currentStep);
    const totalSteps = 4; // Mock data - in real app, would come from process definition
    const newStep = currentStep + 1;
    
    // Update the card to reflect the new state
    if (newStep > totalSteps) {
      // Execution is complete - move to completed section
      const completedList = document.querySelector('#tab-executions .execution-list:last-of-type');
      
      // Update the card styling
      executionCard.querySelector('.badge-warning').className = 'badge badge-success';
      executionCard.querySelector('.badge-warning, .badge-success').textContent = 'Completed';
      executionCard.querySelector('.progress-fill').style.width = '100%';
      
      // Remove the next step section
      const nextStepSection = executionCard.querySelector('.next-step-section');
      if (nextStepSection) {
        nextStepSection.remove();
      }
      
      // Update execution date
      const dateEl = executionCard.querySelector('.execution-date');
      dateEl.textContent = `Completed: ${new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })} at ${new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}`;
      
      // Move card to completed section
      if (completedList) {
        completedList.insertBefore(executionCard, completedList.firstChild);
      }
      
      console.log(`Execution ${executionId} completed!`);
    } else {
      // Update to next step
      executionCard.dataset.currentStep = newStep;
      
      // Update progress bar
      const progressPercent = (newStep / totalSteps) * 100;
      executionCard.querySelector('.progress-fill').style.width = `${progressPercent}%`;
      
      // Update step indicator
      const stepDetail = executionCard.querySelector('.execution-detail-value');
      if (stepDetail) {
        stepDetail.textContent = `${newStep} of ${totalSteps}`;
      }
      
      // In a real app, we'd update the next step section with the new step's details
      // For this demo, just show feedback
      console.log(`Executed step ${currentStep} of execution ${executionId}, now on step ${newStep}`);
    }
    
    // Show success feedback (in real app, would be a toast notification)
    const btn = executionCard.querySelector('.next-step-section .btn-primary');
    if (btn) {
      const originalText = btn.innerHTML;
      btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg> Done!';
      btn.disabled = true;
      
      setTimeout(() => {
        if (newStep <= totalSteps) {
          btn.innerHTML = originalText;
          btn.disabled = false;
        }
      }, 1500);
    }
  }
  
  // Format date helper
  function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  }
  
  // Format time helper
  function formatTime(dateString) {
    const date = new Date(dateString);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
    });
  }