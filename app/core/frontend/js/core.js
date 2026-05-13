// Core page specific functionality - connects to backend APIs

document.addEventListener('DOMContentLoaded', async function() {
    await loadDashboardData();
    setupEventHandlers();
});

async function loadDashboardData() {
    try {
        // Load metrics
        const metrics = await CoreAPI.getMetrics();
        updateMetrics(metrics);
        
        // Load processes
        const processesData = await CoreAPI.getProcesses();
        renderProcesses(processesData.processes);
        
        // Load inventory
        await loadInventory();
        
    } catch (error) {
        console.error('Failed to load dashboard data:', error);
        showError('Failed to load dashboard data. Please refresh the page.');
    }
}

function updateMetrics(metrics) {
    // Update metric cards
    const totalProcessesEl = document.querySelector('.metric-card:nth-child(1) .metric-value');
    const activeExecutionsEl = document.querySelector('.metric-card:nth-child(2) .metric-value');
    const completedEl = document.querySelector('.metric-card:nth-child(3) .metric-value');
    const inventoryEl = document.querySelector('.metric-card:nth-child(4) .metric-value');
    
    if (totalProcessesEl) totalProcessesEl.textContent = metrics.total_processes || 0;
    if (activeExecutionsEl) activeExecutionsEl.textContent = metrics.active_executions || 0;
    if (completedEl) completedEl.textContent = metrics.completed_executions || 0;
    if (inventoryEl) inventoryEl.textContent = metrics.inventory_items?.total || 0;
}

function renderProcesses(processes) {
    const processGrid = document.querySelector('.process-grid');
    if (!processGrid) return;
    
    // Clear existing processes (except template)
    processGrid.innerHTML = '';
    
    if (!processes || processes.length === 0) {
        processGrid.innerHTML = '<p class="text-muted">No processes yet. Create your first process to get started.</p>';
        return;
    }
    
    processes.forEach(process => {
        const processCard = createProcessCard(process);
        processGrid.appendChild(processCard);
    });
}

function createProcessCard(process) {
    const card = document.createElement('div');
    card.className = 'process-card';
    card.onclick = () => navigateToProcess(process.id);
    
    const categoryBadgeClass = {
        'manufacturing': 'badge-accent',
        'chemical': 'badge-primary',
        'packaging': 'badge-success',
        'assembly': 'badge-accent',
        'other': 'badge-primary',
    }[process.category] || 'badge-primary';
    
    const createdDate = process.created_at ? new Date(process.created_at).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric'
    }) : 'Unknown';
    
    card.innerHTML = `
        <div class="process-card-header">
            <h3 class="process-card-title">${escapeHtml(process.name)}</h3>
            <p class="process-card-description">${escapeHtml(process.description || '')}</p>
        </div>
        <div class="process-card-content">
            <div class="process-stats">
                <div class="process-stat">
                    <span class="process-stat-label">Steps</span>
                    <span class="process-stat-value">${process.step_count || 0}</span>
                </div>
                <div class="process-stat">
                    <span class="process-stat-label">Active</span>
                    <span class="process-stat-value">${process.active_executions || 0}</span>
                </div>
                <div class="process-stat">
                    <span class="process-stat-label">Completed</span>
                    <span class="process-stat-value">${process.completed_executions || 0}</span>
                </div>
            </div>
        </div>
        <div class="process-card-footer">
            <span class="badge ${categoryBadgeClass}">${process.category ? process.category.charAt(0).toUpperCase() + process.category.slice(1) : 'Other'}</span>
            <span class="text-sm text-muted">Created ${createdDate}</span>
        </div>
    `;
    
    return card;
}

async function loadInventory() {
    try {
        // Load raw materials
        const rawMaterials = await CoreAPI.getInventory('raw_material');
        renderInventoryTab('tab-raw', rawMaterials.inventory || []);
        
        // Load WIP
        const wip = await CoreAPI.getInventory('work_in_progress');
        renderInventoryTab('tab-wip', wip.inventory || []);
        
        // Load final products
        const finalProducts = await CoreAPI.getInventory('final_product');
        renderInventoryTab('tab-final', finalProducts.inventory || []);
        
    } catch (error) {
        console.error('Failed to load inventory:', error);
    }
}

function renderInventoryTab(tabId, items) {
    const tab = document.getElementById(tabId);
    if (!tab) return;
    
    const inventoryGrid = tab.querySelector('.inventory-grid');
    if (!inventoryGrid) return;
    
    inventoryGrid.innerHTML = '';
    
    if (!items || items.length === 0) {
        inventoryGrid.innerHTML = '<p class="text-muted">No items in this category.</p>';
        return;
    }
    
    items.forEach(item => {
        const itemEl = createInventoryItem(item);
        inventoryGrid.appendChild(itemEl);
    });
}

function createInventoryItem(item) {
    const div = document.createElement('div');
    div.className = 'inventory-item';
    
    const purchaseDate = item.purchase_date ? new Date(item.purchase_date).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric'
    }) : null;
    
    const expiryDate = item.expiry_date ? new Date(item.expiry_date).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric'
    }) : null;
    
    const badgeClass = {
        'raw_material': 'badge-primary',
        'work_in_progress': 'badge-accent',
        'final_product': 'badge-success',
    }[item.inventory_type] || 'badge-primary';
    
    let details = [];
    if (item.supplier) details.push(`Supplier: ${escapeHtml(item.supplier)}`);
    if (item.supplier_batch_number) details.push(`Batch: ${escapeHtml(item.supplier_batch_number)}`);
    if (purchaseDate) details.push(`Purchased: ${purchaseDate}`);
    if (expiryDate) details.push(`Expires: ${expiryDate}`);
    if (item.source_step_name) details.push(`From: ${escapeHtml(item.source_step_name)}`);
    if (item.created_at) {
        const createdDate = new Date(item.created_at).toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric'
        });
        details.push(`Created: ${createdDate}`);
    }
    
    div.innerHTML = `
        <div class="inventory-item-header">
            <span class="inventory-item-name">${escapeHtml(item.name)}</span>
            <span class="badge ${badgeClass}">${item.quantity} ${item.unit}</span>
        </div>
        <div class="inv-adj-wrap">
            <button class="inv-adj-btn inv-adj-btn--primary" type="button"
                data-item-id="${escapeHtml(item.id || '')}"
                data-name="${escapeHtml(item.name || '')}"
                data-type="${escapeHtml(item.inventory_type || '')}"
                data-current="${escapeHtml(String(item.quantity != null ? item.quantity : ''))}"
                data-unit="${escapeHtml(item.unit || '')}"
                data-supplier="${escapeHtml(item.supplier || '')}"
                data-batch="${escapeHtml(item.supplier_batch_number || '')}"
                data-purchase="${escapeHtml(item.purchase_date ? item.purchase_date.slice(0, 10) : '')}"
                data-expiry="${escapeHtml(item.expiry_date ? item.expiry_date.slice(0, 10) : '')}"
                data-barcode="${escapeHtml(item.barcode || '')}">
                Edit
            </button>
        </div>
        <div class="inventory-item-details">
            ${details.map(d => `<span>${d}</span>`).join('')}
        </div>
    `;

    return div;
}

function setupEventHandlers() {
    // Create process form handler
    const createProcessForm = document.querySelector('form[onsubmit*="createNewProcess"]');
    if (createProcessForm) {
        createProcessForm.onsubmit = async function(e) {
            e.preventDefault();
            await handleCreateProcess(this);
            return false;
        };
    }
    
    // Add inventory form handler
    const addInventoryForm = document.querySelector('form[onsubmit*="addInventoryItem"]');
    if (addInventoryForm) {
        addInventoryForm.onsubmit = async function(e) {
            e.preventDefault();
            await handleAddInventoryItem(this);
            return false;
        };
    }
}

async function handleCreateProcess(form) {
    const formData = new FormData(form);
    const data = {
        name: formData.get('name'),
        description: formData.get('description') || '',
        category: formData.get('category') || null,
    };
    
    try {
        const result = await CoreAPI.createProcess(data);
        
        // Close modal
        const modal = form.closest('.modal-overlay');
        if (modal) {
            modal.classList.remove('active');
        }
        
        // Reload processes
        await loadDashboardData();
        
        // Show success message
        showSuccess('Process created successfully!');
        
        form.reset();
    } catch (error) {
        console.error('Failed to create process:', error);
        showError(error.message || 'Failed to create process. Please try again.');
    }
}

async function handleAddInventoryItem(form) {
    const formData = new FormData(form);
    const data = {
        name: formData.get('name'),
        quantity: formData.get('quantity'),
        unit: formData.get('unit'),
        supplier: formData.get('supplier') || null,
        purchase_date: formData.get('purchaseDate') || null,
        supplier_batch_number: formData.get('batchNumber') || null,
        expiry_date: formData.get('expiryDate') || null,
        inventory_type: 'raw_material',
    };
    
    try {
        await CoreAPI.createInventoryItem(data);
        
        // Close modal
        const modal = form.closest('.modal-overlay');
        if (modal) {
            modal.classList.remove('active');
        }
        
        // Reload inventory
        await loadInventory();
        
        // Update metrics
        const metrics = await CoreAPI.getMetrics();
        updateMetrics(metrics);
        
        // Show success message
        showSuccess('Inventory item added successfully!');
        
        form.reset();
    } catch (error) {
        console.error('Failed to add inventory item:', error);
        showError(error.message || 'Failed to add inventory item. Please try again.');
    }
}

function navigateToProcess(processId) {
    window.location.href = `flows.html?id=${processId}`;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showSuccess(message) {
    // Use notification modal if available, otherwise log to console
    if (typeof window.showNotification === 'function') {
        window.showNotification('success', 'Success', message);
    } else {
        console.log('Success:', message);
    }
}

function showError(message) {
    // Use notification modal if available, otherwise log to console
    if (typeof window.showNotification === 'function') {
        window.showNotification('error', 'Error', message);
    } else {
        console.error('Error:', message);
    }
}

