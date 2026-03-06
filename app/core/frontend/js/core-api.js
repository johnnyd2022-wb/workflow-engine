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
            let data;
            try {
                data = await response.json();
            } catch (parseErr) {
                console.error(`API request failed: ${endpoint} - invalid JSON`, parseErr);
                throw new Error(response.ok ? 'Invalid response from server.' : `Server error (${response.status}). Please try again.`);
            }
            if (!response.ok) {
                const msg = data.message || data.error || `HTTP error! status: ${response.status}`;
                const details = data.details ? ` ${data.details}` : '';
                throw new Error(msg + details);
            }
            return data;
        } catch (error) {
            console.error(`API request failed: ${endpoint}`, error);
            if (error.name === 'TypeError' && (error.message === 'Failed to fetch' || error.message === 'Load failed')) {
                throw new Error('Network error. Check your connection and that the server is running, then try again.');
            }
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

    // Evidence (execution attachments: images, PDFs)
    async uploadEvidence(formData) {
        const url = `${this.baseURL}/evidence/upload`;
        const config = { method: 'POST', body: formData };
        if (typeof window !== 'undefined' && window.fetch) {
            const response = await fetch(url, { ...config, credentials: 'same-origin' });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
            return data;
        }
        return this.request('/evidence/upload', { method: 'POST', body: formData });
    },

    async listEvidence(executionId) {
        return this.request(`/evidence/list?execution_id=${encodeURIComponent(executionId)}`);
    },

    /** Remove evidence (record and file). Use from execution modal before completing the step. */
    async deleteEvidence(evidenceId) {
        return this.request(`/evidence/${encodeURIComponent(evidenceId)}`, { method: 'DELETE' });
    },

    /** Evidence upload limits (single source of truth; use for client-side size check). */
    async getEvidenceConfig() {
        return this.request('/evidence/config');
    },

    getEvidenceDownloadUrl(evidenceId) {
        return `${this.baseURL}/evidence/${encodeURIComponent(evidenceId)}/download`;
    },

    /** Open evidence in browser (inline) without forcing download. Use for View. */
    getEvidenceViewUrl(evidenceId) {
        return `${this.baseURL}/evidence/${encodeURIComponent(evidenceId)}/download?inline=1`;
    },

    // Process step documentation (SOP) – for execution modal and step creation
    async getStepDocumentation(stepId) {
        return this.request(`/process-docs/${encodeURIComponent(stepId)}`);
    },

    /** Create or update inline SOP for a step (admin). Used when defining steps. */
    async createProcessDocInline(processId, stepId, title, contentMarkdown, documentId = null) {
        const body = { process_id: processId, step_id: stepId, title, content_markdown: contentMarkdown };
        if (documentId) body.document_id = documentId;
        return this.request('/process-docs/inline', { method: 'POST', body });
    },

    /** Upload SOP file for a step (admin). formData must include process_id, step_id, file; optional title. */
    async uploadProcessDoc(formData) {
        const url = `${this.baseURL}/process-docs/upload`;
        const config = { method: 'POST', body: formData };
        const response = await fetch(url, { ...config, credentials: 'same-origin' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        return data;
    },

    getProcessDocDownloadUrl(docId, inline = false) {
        const q = inline ? '?inline=1' : '';
        return `${this.baseURL}/process-docs/${encodeURIComponent(docId)}/download${q}`;
    },

    getProcessDocViewUrl(docId) {
        return this.getProcessDocDownloadUrl(docId, true);
    },

    /** Delete a process step document (admin). Used in create/edit process modal. */
    async deleteProcessDoc(docId) {
        return this.request(`/process-docs/${encodeURIComponent(docId)}`, { method: 'DELETE' });
    },
};

if (typeof window !== 'undefined') {
    window.CoreAPI = CoreAPI;
}

// ---------------------------------------------------------------------------
// Custom expiry validation helpers (shared by step builder + execution modal)
// ---------------------------------------------------------------------------
if (typeof window !== 'undefined') {
    window.CustomExpiryValidation = window.CustomExpiryValidation || (function () {
        function durationToHours(value, unit) {
            if (value == null || value === '' || isNaN(Number(value)) || Number(value) < 0) return null;
            var v = Number(value);
            switch ((unit || 'days').toLowerCase()) {
                case 'hours': return v;
                case 'days': return v * 24;
                case 'weeks': return v * 24 * 7;
                case 'months': return v * 24 * 30;
                default: return v * 24;
            }
        }

        function formatDurationLabel(value, unit) {
            var v = (value == null) ? '' : String(value);
            var u = (unit || 'days');
            return (v + ' ' + u).trim();
        }

        // Core rule: warn window must be <= expiry window (both in hours).
        function validateWarnNotLongerThanExpiry(opts) {
            opts = opts || {};
            var outputName = opts.outputName || '';
            var warnValue = opts.warnValue;
            var warnUnit = opts.warnUnit || 'days';
            var expiryHours = opts.expiryHours;
            var expiryLabel = opts.expiryLabel || 'the expiry period';

            var warnHours = durationToHours(warnValue, warnUnit);
            if (warnHours == null || expiryHours == null) return { valid: true };
            if (warnHours > expiryHours) {
                var prefix = outputName ? ('For output "' + outputName + '", ') : '';
                var warnLabel = formatDurationLabel(warnValue, warnUnit);
                return {
                    valid: false,
                    message:
                        prefix +
                        'the warn-before-expiry period (' +
                        warnLabel +
                        ') cannot be longer than ' +
                        expiryLabel +
                        '. Please set the warning to the same duration or less.',
                };
            }
            return { valid: true };
        }

        // Validate fixed-duration outputs: warning must not exceed expiry. Returns { valid, message, outputName }.
        function validateFixedExpiryWarning(outputs) {
            for (var i = 0; i < (outputs || []).length; i++) {
                var out = outputs[i] || {};
                var ce = (out.extra_data || {}).custom_expiry;
                if (!ce || ce.mode !== 'fixed_duration') continue;
                var expVal = ce.duration_value;
                var expUnit = ce.duration_unit || 'days';
                var warnVal = ce.warning_value;
                var warnUnit = ce.warning_unit || 'days';
                var expHours = durationToHours(expVal, expUnit);
                if (expHours != null && expHours <= 0) continue;
                var outName = out.name || 'this output';
                var expLabel = 'the expiry period (' + formatDurationLabel(expVal, expUnit) + ')';
                var r = validateWarnNotLongerThanExpiry({
                    outputName: outName,
                    warnValue: warnVal,
                    warnUnit: warnUnit,
                    expiryHours: expHours,
                    expiryLabel: expLabel,
                });
                if (!r.valid) {
                    return { valid: false, outputName: outName, message: r.message };
                }
            }
            return { valid: true };
        }

        return {
            durationToHours: durationToHours,
            formatDurationLabel: formatDurationLabel,
            validateWarnNotLongerThanExpiry: validateWarnNotLongerThanExpiry,
            validateFixedExpiryWarning: validateFixedExpiryWarning,
        };
    })();
}

