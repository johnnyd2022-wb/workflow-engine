// ============================================================
// Supply Chain Platform - Main Application JavaScript
// ============================================================

document.addEventListener('DOMContentLoaded', function() {
  initializeSidebar();
  initializeTabs();
  initializeSteps();
  initializeModals();
});

// ============================================================
// SIDEBAR
// ============================================================
function initializeSidebar() {
  const sidebar = document.getElementById('sidebar');
  const mainContent = document.querySelector('.main-content');
  
  // Restore sidebar state from localStorage
  const isCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
  if (isCollapsed && sidebar) {
    sidebar.classList.add('collapsed');
    if (mainContent) mainContent.classList.add('sidebar-collapsed');
  }
}

// ============================================================
// TABS
// ============================================================
function initializeTabs() {
  const tabTriggers = document.querySelectorAll('.tab-trigger');
  
  tabTriggers.forEach(trigger => {
    trigger.addEventListener('click', function() {
      const tabId = this.dataset.tab;
      
      // Remove active from all triggers and contents
      document.querySelectorAll('.tab-trigger').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      
      // Add active to clicked trigger and corresponding content
      this.classList.add('active');
      const tabContent = document.getElementById(tabId);
      if (tabContent) tabContent.classList.add('active');
    });
  });
}

// ============================================================
// STEP CARDS (Accordion)
// ============================================================
function initializeSteps() {
  const stepHeaders = document.querySelectorAll('.step-header');
  
  stepHeaders.forEach(header => {
    header.addEventListener('click', function() {
      const stepCard = this.closest('.step-card');
      stepCard.classList.toggle('expanded');
    });
  });
}

// ============================================================
// MODALS
// ============================================================
function initializeModals() {
  // Open modal buttons
  const modalTriggers = document.querySelectorAll('[data-modal-open]');
  modalTriggers.forEach(trigger => {
    trigger.addEventListener('click', function() {
      const modalId = this.dataset.modalOpen;
      openModal(modalId);
    });
  });
  
  // Close modal buttons
  const closeButtons = document.querySelectorAll('[data-modal-close]');
  closeButtons.forEach(button => {
    button.addEventListener('click', function() {
      const modal = this.closest('.modal-overlay');
      if (modal) closeModal(modal.id);
    });
  });
  
  // Close on overlay click
  const overlays = document.querySelectorAll('.modal-overlay');
  overlays.forEach(overlay => {
    overlay.addEventListener('click', function(e) {
      if (e.target === this) {
        closeModal(this.id);
      }
    });
  });
  
  // Close on Escape key
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      const activeModal = document.querySelector('.modal-overlay.active');
      if (activeModal) closeModal(activeModal.id);
    }
  });
}

function openModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
  }
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.remove('active');
    document.body.style.overflow = '';
  }
}

// ============================================================
// PROCESS NAVIGATION
// ============================================================
function navigateToProcess(processId) {
  window.location.href = 'flows.html?process=' + processId;
}

// ============================================================
// ADD NEW STEP
// ============================================================
function addNewStep() {
  const stepsContainer = document.querySelector('.steps-container');
  if (!stepsContainer) return;
  
  const stepCount = stepsContainer.querySelectorAll('.step-card').length + 1;
  
  const stepHtml = `
    <div class="step-card expanded" data-step-id="step-new-${Date.now()}">
      <div class="step-header">
        <div class="step-number">${stepCount}</div>
        <div class="step-info">
          <div class="step-name">New Step</div>
          <div class="step-description">Add step description</div>
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
          <input type="text" class="form-input" value="New Step" placeholder="Enter step name">
        </div>
        <div class="form-group">
          <label class="form-label">Description</label>
          <input type="text" class="form-input" value="" placeholder="Enter step description">
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
  
  // Re-initialize step headers for the new step
  const newStep = stepsContainer.lastElementChild;
  const newHeader = newStep.querySelector('.step-header');
  newHeader.addEventListener('click', function() {
    newStep.classList.toggle('expanded');
  });
}

// ============================================================
// ADD INPUT/OUTPUT
// ============================================================
function addInput(button) {
  const ioSection = button.closest('.io-section');
  const ioList = ioSection.querySelector('.io-list');
  
  const inputHtml = `
    <div class="io-item">
      <span class="io-item-name">
        <input type="text" class="form-input" placeholder="Material name" style="width: 120px; padding: 0.25rem 0.5rem;">
      </span>
      <span class="io-item-quantity">
        <input type="number" class="form-input" placeholder="0" style="width: 60px; padding: 0.25rem 0.5rem;">
      </span>
      <span class="io-item-unit">
        <select class="form-select" style="width: 80px; padding: 0.25rem 0.5rem;">
          <option value="kg">kg</option>
          <option value="g">g</option>
          <option value="L">L</option>
          <option value="mL">mL</option>
          <option value="pcs">pcs</option>
          <option value="units">units</option>
        </select>
      </span>
      <span class="badge badge-accent io-item-badge">Variable</span>
    </div>
  `;
  
  ioList.insertAdjacentHTML('beforeend', inputHtml);
}

function addOutput(button) {
  const ioSection = button.closest('.io-section');
  const ioList = ioSection.querySelector('.io-list');
  
  const outputHtml = `
    <div class="io-item">
      <span class="io-item-name">
        <input type="text" class="form-input" placeholder="Product name" style="width: 120px; padding: 0.25rem 0.5rem;">
      </span>
      <span class="io-item-quantity">
        <input type="number" class="form-input" placeholder="0" style="width: 60px; padding: 0.25rem 0.5rem;">
      </span>
      <span class="io-item-unit">
        <select class="form-select" style="width: 80px; padding: 0.25rem 0.5rem;">
          <option value="kg">kg</option>
          <option value="g">g</option>
          <option value="L">L</option>
          <option value="mL">mL</option>
          <option value="pcs">pcs</option>
          <option value="units">units</option>
        </select>
      </span>
      <span class="badge badge-accent io-item-badge">Variable</span>
    </div>
  `;
  
  ioList.insertAdjacentHTML('beforeend', outputHtml);
}

// ============================================================
// FORM HANDLERS
// ============================================================
function addInventoryItem(form) {
  const formData = new FormData(form);
  const data = Object.fromEntries(formData.entries());
  
  console.log('Adding inventory item:', data);
  
  // Close modal
  closeModal('add-inventory-modal');
  
  // Reset form
  form.reset();
  
  // In a real app, you would send this to the backend
  // For now, we'll add it to the UI
  // Target the first inventory-grid (Raw Materials section)
  const inventoryGrid = document.querySelector('#tab-inventory .card:first-of-type .inventory-grid');
  if (inventoryGrid) {
    const itemHtml = `
      <div class="inventory-item">
        <div class="inventory-item-header">
          <span class="inventory-item-name">${data.name}</span>
          <span class="badge badge-primary">${data.quantity} ${data.unit}</span>
        </div>
        <div class="inventory-item-details">
          <span>Supplier: ${data.supplier}</span>
          <span>Batch: ${data.batchNumber || 'N/A'}</span>
        </div>
      </div>
    `;
    inventoryGrid.insertAdjacentHTML('beforeend', itemHtml);
  }
  
  return false; // Prevent form submission
}

function createNewProcess(form) {
  const formData = new FormData(form);
  const data = Object.fromEntries(formData.entries());
  
  console.log('Creating process:', data);
  
  // Close modal
  closeModal('create-process-modal');
  
  // Reset form
  form.reset();
  
  return false; // Prevent form submission
}

// ============================================================
// EXECUTION HANDLERS
// ============================================================
function executeStep(executionId) {
  const executionCard = document.querySelector(`[data-execution-id="${executionId}"]`);
  if (!executionCard) return;
  
  const progressFill = executionCard.querySelector('.progress-fill');
  const nextStepSection = executionCard.querySelector('.next-step-section');
  const statusBadge = executionCard.querySelector('.badge');
  
  // Simulate step execution
  const currentProgress = parseInt(progressFill.style.width) || 0;
  const stepIncrement = 25; // Assuming 4 steps
  const newProgress = Math.min(currentProgress + stepIncrement, 100);
  
  progressFill.style.width = newProgress + '%';
  
  if (newProgress >= 100) {
    // Execution complete
    statusBadge.textContent = 'Completed';
    statusBadge.classList.remove('badge-warning');
    statusBadge.classList.add('badge-success');
    if (nextStepSection) nextStepSection.remove();
  } else {
    // Update next step info
    const stepNumber = Math.floor(newProgress / stepIncrement) + 1;
    const stepNameEl = nextStepSection.querySelector('.next-step-name');
    if (stepNameEl) stepNameEl.textContent = `Step ${stepNumber}`;
  }
}

// ============================================================
// DATE/TIME FORMATTERS
// ============================================================
function formatDate(dateString) {
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric'
  });
}

function formatTime(dateString) {
  const date = new Date(dateString);
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit'
  });
}
