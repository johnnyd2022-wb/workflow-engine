Update the layout and styling for flows2

css for styles2.css

/* ========== TABS ========== */
.tabs {
  margin-bottom: 1.5rem;
}

.tabs-list {
  display: flex;
  gap: 0.25rem;
  background: var(--secondary);
  padding: 0.25rem;
  border-radius: var(--radius);
  width: fit-content;
}

.tab-trigger {
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  font-weight: 500;
  border: none;
  background: transparent;
  color: var(--muted-foreground);
  border-radius: calc(var(--radius) - 0.125rem);
  cursor: pointer;
  transition: var(--transition-base);
}

.tab-trigger:hover {
  color: var(--foreground);
}

.tab-trigger.active {
  background: var(--card);
  color: var(--foreground);
  box-shadow: var(--shadow-sm);
}

.tab-content {
  display: none;
}

.tab-content.active {
  display: block;
}

/* ========== PROCESS STEPS ========== */
.steps-container {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.step-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.step-header {
  padding: 1rem 1.25rem;
  display: flex;
  align-items: center;
  gap: 1rem;
  cursor: pointer;
  transition: var(--transition-base);
}

.step-header:hover {
  background: var(--secondary);
}

.step-number {
  width: 2rem;
  height: 2rem;
  background: var(--primary);
  color: var(--primary-foreground);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.875rem;
  font-weight: 600;
  flex-shrink: 0;
}

.step-info {
  flex: 1;
}

.step-name {
  font-weight: 600;
  color: var(--foreground);
}

.step-description {
  font-size: 0.875rem;
  color: var(--muted-foreground);
}

.step-meta {
  display: flex;
  gap: 1rem;
  font-size: 0.75rem;
  color: var(--muted-foreground);
}

.step-toggle {
  width: 1.5rem;
  height: 1.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: var(--transition-base);
}

.step-toggle.expanded svg {
  transform: rotate(180deg);
}

.step-content {
  display: none;
  padding: 1.25rem;
  border-top: 1px solid var(--border);
  background: var(--secondary);
}

.step-content.expanded {
  display: block;
}

/* ========== INPUTS/OUTPUTS ========== */
.io-section {
  margin-bottom: 1.5rem;
}

.io-section:last-child {
  margin-bottom: 0;
}

.io-section-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--foreground);
  margin-bottom: 0.75rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.io-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.io-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.625rem 0.75rem;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 0.5rem;
}

.io-item-name {
  flex: 1;
  font-size: 0.875rem;
}

.io-item-quantity {
  font-size: 0.875rem;
  font-weight: 500;
}

.io-item-unit {
  font-size: 0.75rem;
  color: var(--muted-foreground);
  min-width: 3rem;
}

.io-item-badge {
  font-size: 0.625rem;
  padding: 0.125rem 0.375rem;
}

/* ========== EXECUTIONS ========== */
.execution-section-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--foreground);
  margin-bottom: 1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.execution-section-title svg {
  width: 1.25rem;
  height: 1.25rem;
}

.execution-section-title.in-flight svg {
  color: var(--accent);
}

.execution-section-title.completed svg {
  color: hsl(142, 71%, 45%);
}

.execution-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.execution-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.25rem;
}

.execution-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 1rem;
}

.execution-id {
  font-weight: 600;
  color: var(--foreground);
}

.execution-date {
  font-size: 0.75rem;
  color: var(--muted-foreground);
}

.execution-progress {
  margin-bottom: 1rem;
}

.progress-bar {
  height: 0.5rem;
  background: var(--secondary);
  border-radius: 9999px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--primary) 0%, var(--accent) 100%);
  border-radius: 9999px;
  transition: var(--transition-smooth);
}

.execution-details {
  display: flex;
  gap: 2rem;
  font-size: 0.875rem;
}

.execution-detail {
  display: flex;
  flex-direction: column;
}

.execution-detail-label {
  font-size: 0.75rem;
  color: var(--muted-foreground);
}

.execution-detail-value {
  font-weight: 500;
}

/* Next Step Section */
.next-step-section {
  margin-bottom: 1rem;
  padding: 1rem;
  background: hsl(175, 60%, 45% / 0.05);
  border: 1px solid hsl(175, 60%, 45% / 0.2);
  border-radius: 0.5rem;
}

.next-step-header {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}

.next-step-icon {
  width: 2rem;
  height: 2rem;
  background: hsl(175, 60%, 45% / 0.1);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--accent);
}

.next-step-info {
  flex: 1;
}

.next-step-label {
  font-size: 0.75rem;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted-foreground);
  margin-bottom: 0.25rem;
}

.next-step-name {
  font-weight: 600;
  color: var(--foreground);
}

.next-step-description {
  font-size: 0.875rem;
  color: var(--muted-foreground);
  margin-top: 0.25rem;
}

.next-step-requirements {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.75rem;
}

.requirement-label {
  font-size: 0.75rem;
  color: var(--muted-foreground);
}

.badge-outline {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--foreground);
  font-size: 0.75rem;
  padding: 0.25rem 0.5rem;
  border-radius: 0.25rem;
}

/* ========== INVENTORY (3-column colored cards) ========== */
.inventory-category-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

@media (max-width: 768px) {
  .inventory-category-grid {
    grid-template-columns: 1fr;
  }
}

.inventory-category-card {
  border-radius: var(--radius);
  overflow: hidden;
  border: 1px solid var(--border);
}

.inventory-category-card.raw {
  background-color: hsl(210, 100%, 97%);
  border-color: hsl(210, 80%, 85%);
}

.inventory-category-card.intermediate {
  background-color: hsl(45, 100%, 96%);
  border-color: hsl(45, 80%, 80%);
}

.inventory-category-card.final {
  background-color: hsl(142, 76%, 96%);
  border-color: hsl(142, 60%, 80%);
}

.inventory-category-header {
  padding: 0.75rem 1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.inventory-category-card.raw .inventory-category-header {
  background-color: hsl(210, 100%, 95%);
  color: hsl(210, 80%, 40%);
}

.inventory-category-card.intermediate .inventory-category-header {
  background-color: hsl(45, 100%, 92%);
  color: hsl(45, 80%, 35%);
}

.inventory-category-card.final .inventory-category-header {
  background-color: hsl(142, 76%, 92%);
  color: hsl(142, 60%, 35%);
}

.inventory-category-header svg {
  width: 1rem;
  height: 1rem;
}

.inventory-category-title {
  font-weight: 600;
  font-size: 0.875rem;
}

.inventory-category-count {
  margin-left: auto;
  font-size: 0.75rem;
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
  background: hsl(0, 0%, 100% / 0.5);
}

.inventory-category-content {
  padding: 0.75rem 1rem;
  background: var(--card);
}

.inventory-category-item {
  padding: 0.5rem 0.625rem;
  border-radius: 0.375rem;
  margin-bottom: 0.5rem;
}

.inventory-category-item:last-child {
  margin-bottom: 0;
}

.inventory-category-card.raw .inventory-category-item {
  background-color: hsl(210, 100%, 97%);
  border: 1px solid hsl(210, 80%, 85%);
}

.inventory-category-card.intermediate .inventory-category-item {
  background-color: hsl(45, 100%, 96%);
  border: 1px solid hsl(45, 80%, 80%);
}

.inventory-category-card.final .inventory-category-item {
  background-color: hsl(142, 76%, 96%);
  border: 1px solid hsl(142, 60%, 80%);
}

.inventory-item-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.inventory-item-name {
  font-size: 0.875rem;
  font-weight: 500;
}

.inventory-item-quantity {
  font-size: 0.875rem;
  font-weight: 600;
}

.inventory-category-card.raw .inventory-item-quantity {
  color: hsl(210, 80%, 40%);
}

.inventory-category-card.intermediate .inventory-item-quantity {
  color: hsl(45, 80%, 35%);
}

.inventory-category-card.final .inventory-item-quantity {
  color: hsl(142, 60%, 35%);
}

.inventory-item-meta {
  font-size: 0.75rem;
  color: var(--muted-foreground);
  margin-top: 0.25rem;
}

html for flows.html

<!-- Tabs -->
<div class="tabs">
  <div class="tabs-list">
    <button class="tab-trigger active" data-tab="tab-structure">Process Structure</button>
    <button class="tab-trigger" data-tab="tab-executions">Executions <span class="badge badge-accent" style="margin-left:0.5rem;">2</span></button>
    <button class="tab-trigger" data-tab="tab-inventory">Inventory</button>
  </div>
  
  <!-- Structure Tab -->
  <div id="tab-structure" class="tab-content active">
    <div class="flex justify-between items-center mt-4 mb-4">
      <p class="text-sm text-muted">4 steps in this process</p>
      <button class="btn btn-outline btn-sm">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        Add Step
      </button>
    </div>
    
    <div class="steps-container">
      <!-- Step Card (repeat for each step) -->
      <div class="step-card">
        <div class="step-header" onclick="toggleStep(this)">
          <div class="step-number">1</div>
          <div class="step-info">
            <div class="step-name">Raw Material Intake</div>
            <div class="step-description">Receive and quality check incoming materials</div>
          </div>
          <div class="step-meta">
            <span>2 inputs</span>
            <span>1 output</span>
          </div>
          <div class="step-toggle">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"></polyline></svg>
          </div>
        </div>
        <div class="step-content">
          <div class="form-group">
            <label class="form-label">Description</label>
            <textarea class="form-input" rows="2">Receive and quality check incoming materials</textarea>
          </div>
          <div class="io-section">
            <div class="io-section-title">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12l7-7 7 7"/></svg>
              Inputs
              <button class="btn btn-ghost btn-sm" style="margin-left:auto;">+ Add</button>
            </div>
            <div class="io-list">
              <div class="io-item">
                <span class="io-item-name">Aluminum Sheets</span>
                <span class="io-item-quantity">100</span>
                <span class="io-item-unit">kg</span>
                <span class="badge badge-accent io-item-badge">Variable</span>
              </div>
            </div>
          </div>
          <div class="io-section">
            <div class="io-section-title">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 19V5M5 12l7 7 7-7"/></svg>
              Outputs
              <button class="btn btn-ghost btn-sm" style="margin-left:auto;">+ Add</button>
            </div>
            <div class="io-list">
              <div class="io-item">
                <span class="io-item-name">Verified Materials</span>
                <span class="io-item-quantity">145</span>
                <span class="io-item-unit">kg</span>
                <span class="badge badge-accent io-item-badge">Variable</span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <!-- Repeat step-card for more steps -->
    </div>
  </div>
  
  <!-- Executions Tab -->
  <div id="tab-executions" class="tab-content">
    <!-- In-Flight Section -->
    <div class="mb-6">
      <h3 class="execution-section-title in-flight">
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        In-Flight Executions (2)
      </h3>
      <div class="execution-list">
        <div class="execution-card">
          <div class="execution-header">
            <div>
              <div class="execution-id">EXEC-2024-001</div>
              <div class="execution-date">Started: Jan 15, 2024</div>
            </div>
            <span class="badge badge-accent">In Progress</span>
          </div>
          <div class="execution-progress">
            <div class="progress-bar">
              <div class="progress-fill" style="width: 66%;"></div>
            </div>
          </div>
          <div class="next-step-section">
            <div class="next-step-header">
              <div class="next-step-icon">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              </div>
              <div class="next-step-info">
                <div class="next-step-label">Next Step</div>
                <div class="next-step-name">Assembly</div>
                <div class="next-step-description">Combine components into finished widgets</div>
                <div class="next-step-requirements">
                  <span class="requirement-label">Requires:</span>
                  <span class="badge-outline">Aluminum Parts: 200 pcs</span>
                  <span class="badge-outline">Plastic Housings: 200 pcs</span>
                </div>
              </div>
              <button class="btn btn-primary btn-sm">Execute Step</button>
            </div>
          </div>
          <div class="execution-details">
            <div class="execution-detail">
              <span class="execution-detail-label">Current Step</span>
              <span class="execution-detail-value">3 of 4</span>
            </div>
            <div class="execution-detail">
              <span class="execution-detail-label">Batch ID</span>
              <span class="execution-detail-value">BATCH-2024-001</span>
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Completed Section -->
    <div>
      <h3 class="execution-section-title completed">
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
        Completed Executions (3)
      </h3>
      <div class="execution-list">
        <div class="execution-card">
          <div class="execution-header">
            <div>
              <div class="execution-id">EXEC-2024-000</div>
              <div class="execution-date">Completed: Jan 10, 2024</div>
            </div>
            <span class="badge badge-success">Completed</span>
          </div>
          <div class="execution-progress">
            <div class="progress-bar">
              <div class="progress-fill" style="width: 100%;"></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  
  <!-- Inventory Tab -->
  <div id="tab-inventory" class="tab-content">
    <div class="flex justify-between items-center mb-4">
      <p class="text-sm text-muted">Track materials connected to this process</p>
      <button class="btn btn-outline btn-sm">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        Add Raw Material
      </button>
    </div>
    
    <div class="inventory-category-grid">
      <!-- Raw Materials -->
      <div class="inventory-category-card raw">
        <div class="inventory-category-header">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
          <span class="inventory-category-title">Raw Materials</span>
          <span class="inventory-category-count">2</span>
        </div>
        <div class="inventory-category-content">
          <div class="inventory-category-item">
            <div class="inventory-item-row">
              <span class="inventory-item-name">Aluminum Sheets</span>
              <span class="inventory-item-quantity">850 kg</span>
            </div>
            <div class="inventory-item-meta">Supplier: MetalCorp</div>
          </div>
          <div class="inventory-category-item">
            <div class="inventory-item-row">
              <span class="inventory-item-name">Plastic Pellets</span>
              <span class="inventory-item-quantity">400 kg</span>
            </div>
            <div class="inventory-item-meta">Supplier: PolymerTech</div>
          </div>
        </div>
      </div>
      
      <!-- Intermediate Products -->
      <div class="inventory-category-card intermediate">
        <div class="inventory-category-header">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
          <span class="inventory-category-title">Intermediate Products</span>
          <span class="inventory-category-count">2</span>
        </div>
        <div class="inventory-category-content">
          <div class="inventory-category-item">
            <div class="inventory-item-row">
              <span class="inventory-item-name">Aluminum Parts</span>
              <span class="inventory-item-quantity">400 pcs</span>
            </div>
            <div class="inventory-item-meta">From: EXEC-2024-001</div>
          </div>
          <div class="inventory-category-item">
            <div class="inventory-item-row">
              <span class="inventory-item-name">Plastic Housings</span>
              <span class="inventory-item-quantity">400 pcs</span>
            </div>
            <div class="inventory-item-meta">From: EXEC-2024-001</div>
          </div>
        </div>
      </div>
      
      <!-- Final Products -->
      <div class="inventory-category-card final">
        <div class="inventory-category-header">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
          <span class="inventory-category-title">Final Products</span>
          <span class="inventory-category-count">1</span>
        </div>
        <div class="inventory-category-content">
          <div class="inventory-category-item">
            <div class="inventory-item-row">
              <span class="inventory-item-name">Finished Widgets</span>
              <span class="inventory-item-quantity">600 pcs</span>
            </div>
            <div class="inventory-item-meta">From: EXEC-2024-000</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

JavaScript for tab switching and step expand/collapse

// Tab switching
document.querySelectorAll('.tab-trigger').forEach(trigger => {
  trigger.addEventListener('click', () => {
    // Remove active from all triggers and contents
    document.querySelectorAll('.tab-trigger').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    
    // Activate clicked tab
    trigger.classList.add('active');
    const tabId = trigger.getAttribute('data-tab');
    document.getElementById(tabId).classList.add('active');
  });
});

// Step expand/collapse
function toggleStep(header) {
  const stepCard = header.closest('.step-card');
  const content = stepCard.querySelector('.step-content');
  const toggle = stepCard.querySelector('.step-toggle');
  
  content.classList.toggle('expanded');
  toggle.classList.toggle('expanded');
}
