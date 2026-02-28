// Core API client for connecting frontend to backend

const CoreAPI = {
    baseURL: '/api/core',
    
    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const config = {
            headers: {
                'Content-Type': 'application/json',
            },
            ...options,
        };
        if (options.body instanceof FormData) {
            delete config.headers['Content-Type'];
            config.body = options.body;
        } else if (options.body && typeof options.body === 'object') {
            config.body = JSON.stringify(options.body);
        }
        
        try {
            const response = await fetch(url, config);
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.message || data.error || `HTTP error! status: ${response.status}`);
            }
            
            return data;
        } catch (error) {
            console.error(`API request failed: ${endpoint}`, error);
            throw error;
        }
    },
    
    // Processes
    async getProcesses() {
        return this.request('/processes');
    },
    
    async getProcess(processId) {
        return this.request(`/processes/${processId}`);
    },
    
    async createProcess(data) {
        return this.request('/processes', {
            method: 'POST',
            body: data,
        });
    },
    
    async updateProcess(processId, data) {
        return this.request(`/processes/${processId}`, {
            method: 'PUT',
            body: data,
        });
    },
    
    async deleteProcess(processId) {
        return this.request(`/processes/${processId}`, {
            method: 'DELETE',
        });
    },
    
    async addStep(processId, stepData) {
        return this.request(`/processes/${processId}/steps`, {
            method: 'POST',
            body: stepData,
        });
    },
    
    async updateStep(processId, stepId, stepData) {
        return this.request(`/processes/${processId}/steps/${stepId}`, {
            method: 'PUT',
            body: stepData,
        });
    },
    
    async deleteStep(processId, stepId) {
        return this.request(`/processes/${processId}/steps/${stepId}`, {
            method: 'DELETE',
        });
    },
    
    // Alias for addStep
    async createStep(processId, stepData) {
        return this.addStep(processId, stepData);
    },
    
    // Executions
    async getExecutions(processId = null, status = null) {
        const params = new URLSearchParams();
        if (processId) params.append('process_id', processId);
        if (status) params.append('status', status);
        const query = params.toString() ? `?${params.toString()}` : '';
        return this.request(`/executions${query}`);
    },
    
    async getExecution(executionId) {
        return this.request(`/executions/${executionId}`);
    },
    
    async createExecution(processId) {
        return this.request('/executions', {
            method: 'POST',
            body: { process_id: processId },
        });
    },
    
    async completeStep(executionId, executionStepId, data) {
        return this.request(`/executions/${executionId}/steps/${executionStepId}/complete`, {
            method: 'POST',
            body: data,
        });
    },
    
    // Inventory
    async getInventory(type = null, processId = null) {
        const params = new URLSearchParams();
        if (type) params.append('type', type);
        if (processId) params.append('process_id', processId);
        const query = params.toString() ? `?${params.toString()}` : '';
        return this.request(`/inventory${query}`);
    },
    
    async getOutOfStockRawMaterials() {
        return this.request('/inventory/out-of-stock');
    },
    
    async getExpiredMaterials() {
        return this.request('/inventory/expired-materials');
    },

    async getUntrackedItems() {
        return this.request('/inventory/untracked-items');
    },

    /** Get untracked items matching name and unit (for Add to Inventory and execution modal reconciliation).
     * When executionId is provided, includes items with qty 0 that were consumed in that execution. */
    async getMatchingUntracked(name, unit, processId = null, executionId = null) {
        const params = new URLSearchParams({ name: name || '', unit: unit || '' });
        if (processId) params.set('process_id', processId);
        if (executionId) params.set('execution_id', executionId);
        return this.request(`/inventory/reconcile/matching-untracked?${params.toString()}`);
    },

    /** Path A: Add to inventory with optional mapping to an untracked item. */
    async reconcileViaAddition(data) {
        return this.request('/inventory/reconcile/via-addition', {
            method: 'POST',
            body: data,
        });
    },

    /** Path B: Map untracked item to an execution output. */
    async reconcileViaExecution(data) {
        return this.request('/inventory/reconcile/via-execution', {
            method: 'POST',
            body: data,
        });
    },

    /** Run all system checks and return banner-ready findings (one request for the system-findings banner). */
    async getSystemFindings() {
        return this.request('/system-findings');
    },

    /** @deprecated Use getExpiredMaterials() */
    async getCheckNeededItems() {
        return this.getExpiredMaterials();
    },
    
    async createInventoryItem(data) {
        return this.request('/inventory', {
            method: 'POST',
            body: data,
        });
    },

    /** Look up product by barcode for inventory entry. Returns { exists: boolean, name?, unit?, supplier? }. */
    async lookupBarcode(code) {
        if (!code || !String(code).trim()) return { exists: false };
        const trimmed = String(code).trim();
        const encoded = encodeURIComponent(trimmed);
        return this.request(`/inventory/barcode/${encoded}`);
    },

    async getConfigUnits() {
        return this.request('/config/units');
    },

    async inventoryCsvValidate(formData) {
        return this.request('/inventory/csv-validate', {
            method: 'POST',
            body: formData,
        });
    },

    async inventoryCsvCommit(payload) {
        return this.request('/inventory/csv-commit', {
            method: 'POST',
            body: payload,
        });
    },

    async decodeBarcode(formData) {
        return this.request('/inventory/decode-barcode', {
            method: 'POST',
            body: formData,
        });
    },
    
    async updateInventoryItem(itemId, data) {
        return this.request(`/inventory/${itemId}`, {
            method: 'PUT',
            body: data,
        });
    },
    
    async deleteInventoryItem(itemId) {
        return this.request(`/inventory/${itemId}`, {
            method: 'DELETE',
        });
    },

    async recordWastage(entries) {
        return this.request('/inventory/wastage', {
            method: 'POST',
            body: { entries },
        });
    },

    async getWastageRecords(inventoryItemId = null) {
        const query = inventoryItemId ? `?inventory_item_id=${encodeURIComponent(inventoryItemId)}` : '';
        return this.request(`/inventory/wastage${query}`);
    },

    async traceRawMaterial(rawMaterialId) {
        return this.request(`/inventory/trace/${rawMaterialId}`);
    },
    
    async traceInventoryBackward(inventoryItemId) {
        return this.request(`/inventory/trace-backward/${inventoryItemId}`);
    },
    
    // Execution Metadata
    async getExecutionMetadata() {
        return this.request('/execution-metadata');
    },
    
    // Metrics
    async getMetrics() {
        return this.request('/metrics');
    },

    // Reset demo DB (test environment only)
    async resetDemoDb() {
        return this.request('/reset-demo-db', {
            method: 'POST',
        });
    },
};

if (typeof window !== 'undefined') {
    window.CoreAPI = CoreAPI;
}

